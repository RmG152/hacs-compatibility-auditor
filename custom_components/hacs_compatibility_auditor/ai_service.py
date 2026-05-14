"""AI service orchestration for HACS Compatibility Auditor.

Manages AI provider instances, builds prompts from compatibility context,
and coordinates analysis and categorization flows.
"""

import json
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .ai_provider import (
    AIAnalysisResult,
    AIProvider,
    AIProviderConfig,
    IssueCategoryResult,
    create_provider,
)
from .const import AI_CATEGORY_UNCERTAIN

_LOGGER = logging.getLogger(__name__)

ANALYSIS_SYSTEM_PROMPT = """You are a Home Assistant compatibility expert. You analyze GitHub issues from HACS (Home Assistant Community Store) packages to determine if they actually affect compatibility with specific Home Assistant versions.

Focus on:
- Breaking changes in Home Assistant that affect the package
- Deprecated features the package relies on
- API changes that break functionality
- False positives where users report issues unrelated to compatibility

Respond ONLY with valid JSON matching the requested schema."""

CATEGORIZE_SYSTEM_PROMPT = """You are a Home Assistant compatibility expert. You categorize GitHub issues from HACS packages to determine if they are real compatibility problems.

Categories:
- true_positive: The issue describes a real compatibility problem with current or upcoming HA versions
- false_positive: The issue looks like a compatibility problem but is actually a user error, configuration issue, or unrelated
- config_issue: The issue is about user configuration, not compatibility
- feature_request: This is a feature request, not a bug or compatibility issue
- unrelated: Not related to compatibility at all
- uncertain: Cannot determine from available information

Respond ONLY with valid JSON matching the requested schema."""


class AIManager:
    """Manages AI provider instances and orchestrates analysis."""

    def __init__(self, hass: HomeAssistant, providers_config: list[dict[str, Any]] | None = None) -> None:
        """Initialize AI manager."""
        self._hass = hass
        self._providers: dict[str, AIProvider] = {}
        self._providers_list: list[AIProviderConfig] = []
        if providers_config:
            self.load_providers(providers_config)

    def load_providers(self, providers_config: list[dict[str, Any]]) -> None:
        """Load/reload provider instances from configuration."""
        self._providers.clear()
        self._providers_list.clear()
        for cfg_dict in providers_config:
            config = AIProviderConfig.from_dict(cfg_dict)
            self._providers_list.append(config)
            provider = create_provider(config)
            if provider:
                self._providers[config.name] = provider
                _LOGGER.debug("Loaded AI provider: %s (%s)", config.name, config.provider_type)

    @property
    def provider_count(self) -> int:
        """Return number of configured providers."""
        return len(self._providers)

    @property
    def provider_names(self) -> list[str]:
        """Return list of configured provider names."""
        return list(self._providers.keys())

    def get_provider(self, name: str) -> AIProvider | None:
        """Get a provider by name."""
        return self._providers.get(name)

    def get_first_enabled(self) -> AIProvider | None:
        """Get the first configured provider."""
        for provider in self._providers.values():
            return provider
        return None

    def _resolve_provider(self, provider_name: str | None) -> AIProvider | None:
        """Resolve a provider by name, or return first available."""
        if provider_name:
            provider = self.get_provider(provider_name)
            if provider:
                return provider
            _LOGGER.warning("AI provider '%s' not found, falling back to first available", provider_name)
        return self.get_first_enabled()

    async def analyze_package(
        self,
        package_name: str,
        package_repo: str,
        installed_version: str,
        ha_current: str,
        ha_next: str | None,
        manifest_ha: str,
        current_status: str,
        issues: list[dict[str, Any]],
        provider_name: str | None = None,
    ) -> AIAnalysisResult:
        """Analyze package compatibility using AI."""
        provider = self._resolve_provider(provider_name)
        if not provider:
            return AIAnalysisResult(error="No AI provider configured")

        system_prompt, user_prompt = self._build_analysis_prompt(
            package_name=package_name,
            package_repo=package_repo,
            installed_version=installed_version,
            ha_current=ha_current,
            ha_next=ha_next,
            manifest_ha=manifest_ha,
            current_status=current_status,
            issues=issues,
        )

        session = async_create_clientsession(self._hass)
        try:
            return await provider.analyze(user_prompt, system_prompt, session=session)
        finally:
            await session.close()

    async def categorize_issue(
        self,
        package_name: str,
        package_repo: str,
        issue_title: str,
        issue_body: str,
        issue_labels: list[str],
        issue_number: int,
        ha_current: str,
        ha_next: str | None,
        provider_name: str | None = None,
    ) -> IssueCategoryResult:
        """Categorize a single issue using AI."""
        provider = self._resolve_provider(provider_name)
        if not provider:
            return IssueCategoryResult(error="No AI provider configured")

        system_prompt, user_prompt = self._build_categorize_prompt(
            package_name=package_name,
            package_repo=package_repo,
            issue_title=issue_title,
            issue_body=issue_body,
            issue_labels=issue_labels,
            issue_number=issue_number,
            ha_current=ha_current,
            ha_next=ha_next,
        )

        session = async_create_clientsession(self._hass)
        try:
            result = await provider.analyze(user_prompt, system_prompt, session=session)
        finally:
            await session.close()

        category_result = IssueCategoryResult(
            provider_used=result.provider_used,
            error=result.error,
            raw_response=result.raw_response,
        )
        if result.error:
            return category_result

        category_result.category = result.verdict or AI_CATEGORY_UNCERTAIN
        category_result.reasoning = result.reasoning
        category_result.confidence = result.confidence
        return category_result

    def build_report_body(
        self,
        package_repo: str,
        issue_number: int,
        category: str,
        reasoning: str,
        provider_name: str,
    ) -> str:
        """Build a GitHub issue body for reporting to the rules repository."""
        return (
            f"## AI Report: {category}\n\n"
            f"- **Package**: `{package_repo}`\n"
            f"- **Issue**: #{issue_number}\n"
            f"- **Category**: `{category}`\n"
            f"- **AI Provider**: {provider_name}\n\n"
            f"### AI Reasoning\n\n{reasoning}\n\n"
            f"---\n*Reported automatically by HACS Compatibility Auditor*"
        )

    def _build_analysis_prompt(
        self,
        package_name: str,
        package_repo: str,
        installed_version: str,
        ha_current: str,
        ha_next: str | None,
        manifest_ha: str,
        current_status: str,
        issues: list[dict[str, Any]],
    ) -> tuple[str, str]:
        """Build prompts for package compatibility analysis."""
        user_parts = [
            f"Package: {package_name}",
            f"Repository: {package_repo}",
            f"Installed version: {installed_version}",
            f"HA Current: {ha_current}",
        ]
        if ha_next:
            user_parts.append(f"HA Next: {ha_next}")
        if manifest_ha:
            user_parts.append(f"Manifest HA requirement: {manifest_ha}")
        user_parts.append(f"Current algorithm status: {current_status}")
        user_parts.append("")

        if issues:
            user_parts.append(f"Issues found ({len(issues)}):")
            for i, issue in enumerate(issues, 1):
                title = issue.get("title", "?")
                priority = issue.get("priority", 0)
                labels = ", ".join(issue.get("labels", []))
                body = (issue.get("body") or "")[:300]
                url = issue.get("url", "")
                user_parts.append(f"\n{i}. [{title}]({url})")
                user_parts.append(f"   Priority: {priority}, Labels: [{labels}]")
                if body:
                    user_parts.append(f"   Body: {body}")
        else:
            user_parts.append("No issues found.")

        target = ha_next or ha_current
        user_parts.append(
            f"\nQuestion: Is this package actually affected by compatibility issues with "
            f"Home Assistant {target}? "
            f"Answer ONLY with JSON: "
            f'{{"verdict": "affected|not_affected|uncertain", "reasoning": "...", "confidence": 0.0-1.0}}'
        )

        user_prompt = "\n".join(user_parts)
        return ANALYSIS_SYSTEM_PROMPT, user_prompt

    def _build_categorize_prompt(
        self,
        package_name: str,
        package_repo: str,
        issue_title: str,
        issue_body: str,
        issue_labels: list[str],
        issue_number: int,
        ha_current: str,
        ha_next: str | None,
    ) -> tuple[str, str]:
        """Build prompts for issue categorization."""
        labels_str = ", ".join(issue_labels) if issue_labels else "none"
        body_preview = (issue_body or "")[:500]

        user_parts = [
            f"Issue #{issue_number}: {issue_title}",
            f"Labels: [{labels_str}]",
            f"Body: {body_preview}",
            "",
            f"Package: {package_name}",
            f"Repository: {package_repo}",
            f"HA Current: {ha_current}",
        ]
        if ha_next:
            user_parts.append(f"HA Next: {ha_next}")

        user_parts.append(
            "\nWhich category? "
            "Answer ONLY with JSON: "
            '{"category": "true_positive|false_positive|config_issue|feature_request|unrelated|uncertain", '
            '"confidence": 0.0-1.0, "reasoning": "..."}'
        )

        user_prompt = "\n".join(user_parts)
        return CATEGORIZE_SYSTEM_PROMPT, user_prompt

    @staticmethod
    def _parse_category_result(raw_response: str, result: IssueCategoryResult) -> IssueCategoryResult:
        """Parse JSON category result from response content (for use without AIManager)."""
        content = raw_response.strip()
        json_start = content.find("{")
        json_end = content.rfind("}")

        if json_start >= 0 and json_end > json_start:
            json_str = content[json_start : json_end + 1]
            try:
                parsed = json.loads(json_str)
                result.category = parsed.get("category", parsed.get("verdict", AI_CATEGORY_UNCERTAIN))
                result.confidence = float(parsed.get("confidence", 0))
                result.reasoning = parsed.get("reasoning", parsed.get("reason", ""))
                return result
            except (ValueError, TypeError, json.JSONDecodeError):
                pass

        result.category = AI_CATEGORY_UNCERTAIN
        result.reasoning = content[:500]
        return result

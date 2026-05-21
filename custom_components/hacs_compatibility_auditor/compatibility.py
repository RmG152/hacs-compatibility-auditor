"""Compatibility checking logic for HACS packages.

This module contains the core algorithm for determining whether a HACS package
is compatible with the current and next versions of Home Assistant.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import json
import logging
from typing import Any

import aiohttp

from .const import (
    DEFAULT_ISSUE_KEYWORDS,
    DEFAULT_ISSUE_LABELS_PRIORITY,
    STATUS_COMPATIBLE,
    STATUS_INCOMPATIBLE,
    STATUS_UNKNOWN,
    STATUS_WARNING,
)
from .github_client import GitHubClient
from .hacs_repository import HacsPackage
from .rules_client import RulesClient
from .version_utils import (
    check_version_requirement,
    parse_ha_version,
    satisfies_constraint,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class CompatibilityResult:
    """Result of compatibility check for a single package."""

    package: HacsPackage
    compatible_with_current: bool | None = None
    compatible_with_next: bool | None = None
    status: str = STATUS_UNKNOWN
    issues_relevant: list[dict[str, Any]] = field(default_factory=list)
    latest_version: str = ""
    manifest_ha_requirement: str = ""
    last_checked: str = ""
    error: str = ""
    reason: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    ai_analysis: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for sensor attributes."""
        return {
            "name": self.package.name,
            "repository": self.package.full_name,
            "type": self.package.category,
            "installed_version": self.package.installed_version,
            "latest_version": self.latest_version,
            "compatible_with_current": self.compatible_with_current,
            "compatible_with_next": self.compatible_with_next,
            "status": self.status,
            "issues_relevant": self.issues_relevant,
            "manifest_ha_requirement": self.manifest_ha_requirement,
            "last_checked": self.last_checked,
            "error": self.error,
            "reason": self.reason,
            "ai_analysis": self.ai_analysis,
        }


class CompatibilityChecker:
    """Checks compatibility of HACS packages with HA versions."""

    def __init__(
        self,
        github_client: GitHubClient,
        issue_labels_priority: list[str] | None = None,
        issue_keywords: list[str] | None = None,
        ignore_list: list[str] | None = None,
        rules_client: RulesClient | None = None,
    ) -> None:
        """Initialize the compatibility checker."""
        self._github = github_client
        self._issue_labels = issue_labels_priority or DEFAULT_ISSUE_LABELS_PRIORITY
        self._issue_keywords = issue_keywords or DEFAULT_ISSUE_KEYWORDS
        self._ignore_list = set(ignore_list or [])
        self._rules = rules_client

    def update_config(
        self,
        issue_labels_priority: list[str],
        ignore_list: list[str],
    ) -> None:
        """Update checker configuration."""
        self._issue_labels = issue_labels_priority
        self._ignore_list = set(ignore_list)

    def should_ignore(self, package: HacsPackage) -> bool:
        """Check if a package should be ignored."""
        return package.full_name in self._ignore_list or package.name in self._ignore_list

    async def check_package(
        self,
        package: HacsPackage,
        ha_current: str,
        ha_next: str | None = None,
    ) -> CompatibilityResult:
        """Check compatibility of a single package."""
        _LOGGER.debug(
            "Checking compatibility for %s (%s, installed=%s, category=%s)",
            package.full_name,
            package.installed_version,
            package.installed,
            package.category,
        )

        result = CompatibilityResult(
            package=package,
            last_checked=datetime.now(tz=UTC).isoformat(),
        )

        if self.should_ignore(package):
            _LOGGER.debug("Package %s is in ignore list, skipping", package.full_name)
            result.status = "ignored"
            result.compatible_with_current = True
            result.compatible_with_next = True
            return result

        # Whitelist check (if rules available)
        if self._rules and self._rules.is_whitelisted(package.full_name):
            _LOGGER.debug("Package %s is whitelisted, marking compatible", package.full_name)
            result.compatible_with_current = True
            result.compatible_with_next = True
            result.status = STATUS_COMPATIBLE
            result.data["ruled_by"] = "whitelist"
            return result

        # Blacklist check (if rules available)
        if self._rules and self._rules.is_blacklisted(package.full_name):
            _LOGGER.debug("Package %s is blacklisted, marking incompatible", package.full_name)
            result.compatible_with_current = False
            result.compatible_with_next = False
            result.status = STATUS_INCOMPATIBLE
            result.data["ruled_by"] = "blacklist"
            return result

        try:
            # Step 1: Get manifest for declared HA version requirement
            _LOGGER.debug("Step 1: Fetching manifest for %s", package.full_name)
            manifest = await self._github.get_manifest(package.owner, package.repo)
            if manifest:
                result.manifest_ha_requirement = manifest.homeassistant
                result.latest_version = manifest.version
                _LOGGER.debug(
                    "Manifest for %s: version=%s, ha_requirement=%s, requirements=%s",
                    package.full_name,
                    manifest.version,
                    manifest.homeassistant,
                    manifest.requirements,
                )
            else:
                _LOGGER.debug("No manifest found for %s", package.full_name)

            # Step 2: Get latest release info
            _LOGGER.debug("Step 2: Fetching releases for %s", package.full_name)
            releases = await self._github.get_releases(package.owner, package.repo, per_page=5)
            if releases:
                latest_stable = None
                for release in releases:
                    if not release.prerelease:
                        latest_stable = release
                        break
                if latest_stable:
                    result.latest_version = result.latest_version or latest_stable.tag_name
                _LOGGER.debug(
                    "Releases for %s: %d total, latest_stable=%s",
                    package.full_name,
                    len(releases),
                    latest_stable.tag_name if latest_stable else "none",
                )
            else:
                _LOGGER.debug("No releases found for %s", package.full_name)

            # Step 3: Check manifest compatibility
            _LOGGER.debug("Step 3: Checking manifest compatibility for %s", package.full_name)
            manifest_compatible_current = True
            manifest_compatible_next = True

            if result.manifest_ha_requirement:
                manifest_compatible_current = self._check_version_requirement(
                    ha_current, result.manifest_ha_requirement
                )
                _LOGGER.debug(
                    "Version check for %s: ha_current=%s vs requirement=%s -> compatible=%s",
                    package.full_name,
                    ha_current,
                    result.manifest_ha_requirement,
                    manifest_compatible_current,
                )
                if ha_next:
                    manifest_compatible_next = self._check_version_requirement(ha_next, result.manifest_ha_requirement)
                    _LOGGER.debug(
                        "Version check for %s: ha_next=%s vs requirement=%s -> compatible=%s",
                        package.full_name,
                        ha_next,
                        result.manifest_ha_requirement,
                        manifest_compatible_next,
                    )
            else:
                _LOGGER.debug(
                    "No HA version requirement for %s, assuming compatible",
                    package.full_name,
                )

            # Step 4: Check for relevant issues
            _LOGGER.debug("Step 4: Checking issues for %s", package.full_name)

            since_date = (datetime.now(UTC) - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")

            issues = await self._github.get_issues(
                package.owner,
                package.repo,
                labels=self._issue_labels[:5],
                keywords=self._issue_keywords[:5],
                since=since_date,
            )

            # Filter false positives (if rules available)
            false_positives: set[int] = set()
            if self._rules:
                false_positives = self._rules.get_false_positives(package.full_name)
            if false_positives:
                _LOGGER.debug("Filtering %d false positive issues for %s", len(false_positives), package.full_name)
                issues = [i for i in issues if i.number not in false_positives]

            # Recalculate priority with overrides (if rules available)
            if self._rules:
                label_overrides = self._rules.get_label_overrides(package.full_name)
                keyword_overrides = self._rules.get_keyword_overrides(package.full_name)
                if label_overrides or keyword_overrides:
                    for issue in issues:
                        issue.priority = self._apply_priority_overrides(issue, label_overrides, keyword_overrides)

            result.issues_relevant = [
                {
                    "title": issue.title,
                    "url": issue.url,
                    "state": issue.state,
                    "labels": issue.labels,
                    "priority": issue.priority,
                    "updated_at": issue.updated_at,
                }
                for issue in issues
            ]
            _LOGGER.debug("Found %d relevant issues for %s", len(issues), package.full_name)

            # Step 5: Determine overall compatibility status
            _LOGGER.debug("Step 5: Determining status for %s", package.full_name)
            has_incompatible_issue = any(issue.priority >= 15 for issue in issues)
            has_warning_issue = any(5 <= issue.priority < 15 for issue in issues)

            # Check release notes for breaking change mentions and deprecation
            release_breaking = False
            release_deprecated = False
            matching_releases: list[str] = []
            if releases:
                for release in releases[:3]:
                    body = release.body or ""
                    if self._contains_breaking_keywords(body):
                        release_breaking = True
                        _LOGGER.debug(
                            "Breaking keywords found in release %s for %s",
                            release.tag_name,
                            package.full_name,
                        )
                        snippet = body[:500]
                        snippet = f"{release.tag_name}: {snippet}"
                        matching_releases.append(snippet)
                    if self._contains_deprecation_keywords(body):
                        release_deprecated = True
                        _LOGGER.debug(
                            "Deprecation keywords found in release %s for %s",
                            release.tag_name,
                            package.full_name,
                        )
                        if len(matching_releases) >= 3:
                            break
            if matching_releases:
                result.data["matching_releases"] = matching_releases

            # Determine final status
            # Note: release_deprecated is a strong signal - mark as incompatible
            # because the package author explicitly says to stop using it
            if not manifest_compatible_current or has_incompatible_issue or release_deprecated:
                result.status = STATUS_INCOMPATIBLE
                result.compatible_with_current = False
                result.compatible_with_next = (
                    manifest_compatible_next and not has_incompatible_issue and not release_deprecated
                )
                reasons: list[str] = []
                if not manifest_compatible_current:
                    reasons.append(
                        f"Manifest requires HA {result.manifest_ha_requirement}, "
                        f"current version {ha_current} does not satisfy it"
                    )
                if has_incompatible_issue:
                    high_prio = [i for i in issues if i.priority >= 15]
                    reasons.append(f"{len(high_prio)} high-priority issue(s) found")
                if release_deprecated:
                    reasons.append("Package is deprecated (END OF LIFE)")
                result.reason = "; ".join(reasons)
            elif (ha_next and not manifest_compatible_next) or has_warning_issue or release_breaking:
                result.status = STATUS_WARNING
                result.compatible_with_current = manifest_compatible_current and not has_warning_issue
                result.compatible_with_next = manifest_compatible_next and not release_breaking
                reasons = []
                if ha_next and not manifest_compatible_next:
                    reasons.append(
                        f"Manifest requires HA {result.manifest_ha_requirement}, "
                        f"next version {ha_next} may not satisfy it"
                    )
                if has_warning_issue:
                    mid_prio = [i for i in issues if 5 <= i.priority < 15]
                    reasons.append(f"{len(mid_prio)} warning issue(s) found")
                if release_breaking:
                    reasons.append("Breaking change keywords found in recent release notes")
                result.reason = "; ".join(reasons)
            else:
                result.status = STATUS_COMPATIBLE
                result.compatible_with_current = True
                result.compatible_with_next = True
                result.reason = "No compatibility issues detected"

            _LOGGER.info(
                "Compatibility result for %s: status=%s, current=%s, next=%s, "
                "issues=%d, manifest_ha=%s, latest_version=%s",
                package.full_name,
                result.status,
                result.compatible_with_current,
                result.compatible_with_next,
                len(issues),
                result.manifest_ha_requirement,
                result.latest_version,
            )

        except (
            TimeoutError,
            aiohttp.ClientError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            _LOGGER.error(
                "Error checking compatibility for %s: %s",
                package.full_name,
                exc,
            )
            result.error = str(exc)
            result.status = STATUS_UNKNOWN
            result.compatible_with_current = None
            result.compatible_with_next = None

        return result

    async def check_all_packages(
        self,
        packages: list[HacsPackage],
        ha_current: str,
        ha_next: str | None = None,
    ) -> list[CompatibilityResult]:
        """Check compatibility for all packages."""
        total = len(packages)
        _LOGGER.info(
            "Starting compatibility check for %d packages (ha_current=%s, ha_next=%s)",
            total,
            ha_current,
            ha_next,
        )
        results = []
        for idx, package in enumerate(packages, start=1):
            _LOGGER.debug("Checking package %d/%d: %s", idx, total, package.full_name)
            result = await self.check_package(package, ha_current, ha_next)
            results.append(result)

        # Summary of statuses
        status_counts: dict[str, int] = {}
        for r in results:
            status_counts[r.status] = status_counts.get(r.status, 0) + 1
        _LOGGER.info(
            "All packages checked. Status summary: %s",
            status_counts,
        )
        return results

    @staticmethod
    def _check_version_requirement(ha_version: str, requirement: str) -> bool:
        """Check if a HA version satisfies a requirement string.

        Delegates to version_utils.check_version_requirement.
        """
        return check_version_requirement(ha_version, requirement)

    @staticmethod
    def _parse_ha_version(version_str: str) -> Any:
        """Parse a Home Assistant version string. Delegates to version_utils."""
        return parse_ha_version(version_str)

    @staticmethod
    def _satisfies_constraint(version, constraint: str) -> bool:
        """Check if a version satisfies a single constraint. Delegates to version_utils."""
        return satisfies_constraint(version, constraint)

    def _apply_priority_overrides(
        self,
        issue,
        label_overrides: dict[str, int],
        keyword_overrides: dict[str, int],
    ) -> int:
        """Recalculate priority using label and keyword overrides."""
        priority = 0

        high_priority_labels = {
            "breaking-change": 20,
            "breaking": 15,
            "incompatible": 15,
            "deprecation": 10,
            "upgrade": 8,
            "compatibility": 8,
        }

        for label in issue.labels:
            label_name = label.lower() if isinstance(label, str) else label.name.lower()
            base_weight = high_priority_labels.get(label_name, 0)
            weight = label_overrides.get(label_name, base_weight)
            if weight > 0:
                priority += weight + 5

        keyword_boosts = {
            "breaking change": 10,
            "incompatible": 8,
            "not compatible": 8,
            "deprecated": 6,
            "stopped working": 5,
            "no longer works": 5,
        }

        issue_text = f"{issue.title} {issue.body}".lower()
        for keyword, boost in keyword_boosts.items():
            weight = keyword_overrides.get(keyword, boost)
            if weight > 0 and keyword in issue_text:
                priority += weight + 2

        return priority

    @staticmethod
    def _contains_breaking_keywords(text: str) -> bool:
        """Check if text contains breaking change keywords."""
        if not text:
            return False
        text_lower = text.lower()
        breaking_patterns = [
            "breaking change",
            "breaking-change",
            "**breaking**",
            "## breaking",
            "### breaking",
            "not compatible",
            "incompatible",
            "removed:",
            "deprecated:",
            "migration required",
            "end of life",
            "use this instead",
            "merged into",
            "migrated to",
        ]
        return any(pattern in text_lower for pattern in breaking_patterns)

    @staticmethod
    def _contains_deprecation_keywords(text: str) -> bool:
        """Check if text contains deprecation/obsolescence keywords.

        These indicate the package is deprecated and users should migrate.
        """
        if not text:
            return False
        text_lower = text.lower()
        deprecation_patterns = [
            "end of life",
            "deprecated",
            "use this instead",
            "use instead",
            "merged into",
            "migrated to",
            "superse",
            "please use",
            "has been deprecated",
        ]
        return any(pattern in text_lower for pattern in deprecation_patterns)

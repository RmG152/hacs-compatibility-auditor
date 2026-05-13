"""Compatibility checking logic for HACS packages.

This module contains the core algorithm for determining whether a HACS package
is compatible with the current and next versions of Home Assistant.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from packaging.version import InvalidVersion, Version, parse as parse_version

from .const import (
    DEFAULT_ISSUE_KEYWORDS,
    DEFAULT_ISSUE_LABELS_PRIORITY,
    STATUS_COMPATIBLE,
    STATUS_INCOMPATIBLE,
    STATUS_UNKNOWN,
    STATUS_WARNING,
)
from .github_client import GitHubClient, GitHubIssue, GitHubManifest, GitHubRelease
from .hacs_repository import HacsPackage

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

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for sensor attributes."""
        return {
            "nombre": self.package.name,
            "repositorio": self.package.full_name,
            "tipo": self.package.category,
            "version_instalada": self.package.installed_version,
            "version_mas_reciente": self.latest_version,
            "compatible_con_actual": self.compatible_with_current,
            "compatible_con_siguiente": self.compatible_with_next,
            "estado": self.status,
            "issues_relevantes": self.issues_relevantes,
            "requisito_ha_manifest": self.manifest_ha_requirement,
            "ultima_comprobacion": self.last_checked,
            "error": self.error,
        }


class CompatibilityChecker:
    """Checks compatibility of HACS packages with HA versions."""

    def __init__(
        self,
        github_client: GitHubClient,
        issue_labels_priority: list[str] | None = None,
        issue_keywords: list[str] | None = None,
        ignore_list: list[str] | None = None,
    ) -> None:
        """Initialize the compatibility checker."""
        self._github = github_client
        self._issue_labels = issue_labels_priority or DEFAULT_ISSUE_LABELS_PRIORITY
        self._issue_keywords = issue_keywords or DEFAULT_ISSUE_KEYWORDS
        self._ignore_list = set(ignore_list or [])

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
        result = CompatibilityResult(
            package=package,
            last_checked=datetime.utcnow().isoformat(),
        )

        if self.should_ignore(package):
            result.status = "ignored"
            result.compatible_with_current = True
            result.compatible_with_next = True
            return result

        try:
            # Step 1: Get manifest for declared HA version requirement
            manifest = await self._github.get_manifest(
                package.owner, package.repo
            )
            if manifest:
                result.manifest_ha_requirement = manifest.homeassistant
                result.latest_version = manifest.version

            # Step 2: Get latest release info
            releases = await self._github.get_releases(
                package.owner, package.repo, per_page=5
            )
            if releases:
                latest_stable = None
                for release in releases:
                    if not release.prerelease:
                        latest_stable = release
                        break
                if latest_stable:
                    result.latest_version = result.latest_version or latest_stable.tag_name

            # Step 3: Check manifest compatibility
            manifest_compatible_current = True
            manifest_compatible_next = True

            if result.manifest_ha_requirement:
                manifest_compatible_current = self._check_version_requirement(
                    ha_current, result.manifest_ha_requirement
                )
                if ha_next:
                    manifest_compatible_next = self._check_version_requirement(
                        ha_next, result.manifest_ha_requirement
                    )

            # Step 4: Check for relevant issues
            # Calculate a reasonable "since" date (last 90 days)
            from datetime import timedelta
            since_date = (datetime.utcnow() - timedelta(days=90)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

            issues = await self._github.get_issues(
                package.owner,
                package.repo,
                labels=self._issue_labels[:5],
                keywords=self._issue_keywords[:5],
                since=since_date,
            )

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

            # Step 5: Determine overall compatibility status
            has_incompatible_issue = any(
                issue.priority >= 15 for issue in issues
            )
            has_warning_issue = any(
                5 <= issue.priority < 15 for issue in issues
            )

            # Check release notes for breaking change mentions
            release_breaking = False
            if releases:
                for release in releases[:3]:
                    if self._contains_breaking_keywords(release.body):
                        release_breaking = True
                        break

            # Determine final status
            if not manifest_compatible_current or has_incompatible_issue:
                result.status = STATUS_INCOMPATIBLE
                result.compatible_with_current = False
                result.compatible_with_next = (
                    manifest_compatible_next and not has_incompatible_issue
                )
            elif (
                (ha_next and not manifest_compatible_next)
                or has_warning_issue
                or release_breaking
            ):
                result.status = STATUS_WARNING
                result.compatible_with_current = manifest_compatible_current and not has_warning_issue
                result.compatible_with_next = manifest_compatible_next and not release_breaking
            else:
                result.status = STATUS_COMPATIBLE
                result.compatible_with_current = True
                result.compatible_with_next = True

        except Exception as exc:
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
        results = []
        for package in packages:
            result = await self.check_package(package, ha_current, ha_next)
            results.append(result)
        return results

    @staticmethod
    def _check_version_requirement(
        ha_version: str, requirement: str
    ) -> bool:
        """Check if a HA version satisfies a requirement string.

        The requirement can be in various formats:
        - "2024.1.0" - minimum version
        - ">=2024.1.0" - minimum version with operator
        - ">=2024.1.0,<2025.0.0" - range
        - "2024.1" - major.minor format
        """
        if not requirement or not ha_version:
            return True  # No requirement = assumed compatible

        try:
            ha_ver = CompatibilityChecker._parse_ha_version(ha_version)
        except (InvalidVersion, ValueError):
            _LOGGER.warning("Cannot parse HA version: %s", ha_version)
            return True

        # Split by comma for multiple constraints
        constraints = [c.strip() for c in requirement.split(",")]

        for constraint in constraints:
            if not CompatibilityChecker._satisfies_constraint(ha_ver, constraint):
                return False

        return True

    @staticmethod
    def _parse_ha_version(version_str: str) -> Version:
        """Parse a Home Assistant version string.

        HA versions can be like: 2024.1.0, 2024.1.0b1, 2024.1.0dev0
        """
        # Remove 'dev' and 'b' suffixes for comparison
        cleaned = re.sub(r"(dev\d*|b\d+|rc\d+)$", "", version_str.strip())
        if not cleaned:
            raise ValueError(f"Empty version after cleaning: {version_str}")
        return parse_version(cleaned)

    @staticmethod
    def _satisfies_constraint(version: Version, constraint: str) -> bool:
        """Check if a version satisfies a single constraint."""
        constraint = constraint.strip()

        # Extract operator and version
        match = re.match(r"^([<>=!]+)\s*(.+)$", constraint)
        if match:
            op = match.group(1)
            req_str = match.group(2)
        else:
            # No operator means minimum version
            op = ">="
            req_str = constraint

        try:
            req_ver = CompatibilityChecker._parse_ha_version(req_str)
        except (InvalidVersion, ValueError):
            _LOGGER.warning("Cannot parse requirement version: %s", req_str)
            return True

        if op == ">=":
            return version >= req_ver
        elif op == ">":
            return version > req_ver
        elif op == "<=":
            return version <= req_ver
        elif op == "<":
            return version < req_ver
        elif op == "==":
            return version == req_ver
        elif op == "!=":
            return version != req_ver
        elif op == "~=":
            # Compatible release
            return version >= req_ver and version.release[:2] == req_ver.release[:2]
        else:
            _LOGGER.warning("Unknown version operator: %s", op)
            return True

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
        ]
        return any(pattern in text_lower for pattern in breaking_patterns)

"""DataUpdateCoordinator for HACS Compatibility Auditor.

Manages periodic scanning and caching of compatibility data.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .compatibility import CompatibilityChecker, CompatibilityResult
from .const import (
    CONF_CACHE_HOURS,
    CONF_CHECK_INTERVAL,
    CONF_GITHUB_RETRIES,
    CONF_GITHUB_TIMEOUT,
    CONF_GITHUB_TOKEN,
    CONF_IGNORE_LIST,
    CONF_ISSUE_LABELS_PRIORITY,
    DEFAULT_CACHE_HOURS,
    DEFAULT_CHECK_INTERVAL,
    DEFAULT_GITHUB_RETRIES,
    DEFAULT_GITHUB_TIMEOUT,
    DEFAULT_ISSUE_LABELS_PRIORITY,
    DOMAIN,
    STATUS_COMPATIBLE,
    STATUS_INCOMPATIBLE,
    STATUS_UNKNOWN,
    STATUS_WARNING,
)
from .github_client import GitHubClient
from .hacs_repository import HacsPackage, HacsRepositoryReader

_LOGGER = logging.getLogger(__name__)


class HacsCompatibilityData:
    """Container for all compatibility audit data."""

    def __init__(self) -> None:
        """Initialize data container."""
        self.ha_current: str = ""
        self.ha_next: str | None = None
        self.ha_next_is_rc: bool = False
        self.packages: list[HacsPackage] = []
        self.results: list[CompatibilityResult] = []
        self.packages_total: int = 0
        self.incompatible_count: int = 0
        self.warning_count: int = 0
        self.compatible_count: int = 0
        self.unknown_count: int = 0
        self.last_scan: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for coordinator data."""
        return {
            "ha_current": self.ha_current,
            "ha_next": self.ha_next,
            "ha_next_is_rc": self.ha_next_is_rc,
            "packages_total": self.packages_total,
            "incompatible_count": self.incompatible_count,
            "warning_count": self.warning_count,
            "compatible_count": self.compatible_count,
            "unknown_count": self.unknown_count,
            "results": [r.to_dict() for r in self.results],
            "last_scan": self.last_scan,
        }


class HacsCompatibilityCoordinator(DataUpdateCoordinator):
    """Coordinator for HACS compatibility data."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: Any,
    ) -> None:
        """Initialize the coordinator."""
        self._config_entry = config_entry
        self._data = HacsCompatibilityData()
        self._github_client: GitHubClient | None = None
        self._checker: CompatibilityChecker | None = None
        self._hacs_reader = HacsRepositoryReader(hass)

        # Read config
        entry_data = config_entry.data
        entry_options = config_entry.options

        self._github_token = entry_data.get(CONF_GITHUB_TOKEN, "")
        self._check_interval = entry_options.get(
            CONF_CHECK_INTERVAL, DEFAULT_CHECK_INTERVAL
        )
        self._cache_hours = entry_options.get(CONF_CACHE_HOURS, DEFAULT_CACHE_HOURS)
        self._github_timeout = entry_options.get(
            CONF_GITHUB_TIMEOUT, DEFAULT_GITHUB_TIMEOUT
        )
        self._github_retries = entry_options.get(
            CONF_GITHUB_RETRIES, DEFAULT_GITHUB_RETRIES
        )
        self._issue_labels_priority = entry_options.get(
            CONF_ISSUE_LABELS_PRIORITY, DEFAULT_ISSUE_LABELS_PRIORITY
        )
        self._ignore_list = entry_options.get(CONF_IGNORE_LIST, [])

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=self._check_interval),
        )

    async def _async_setup(self) -> None:
        """Set up the GitHub client and checker."""
        session = async_create_clientsession(self.hass)
        self._github_client = GitHubClient(
            session=session,
            token=self._github_token or None,
            timeout=self._github_timeout,
            retries=self._github_retries,
        )
        self._github_client._cache_ttl = self._cache_hours * 3600

        self._checker = CompatibilityChecker(
            github_client=self._github_client,
            issue_labels_priority=self._issue_labels_priority,
            ignore_list=self._ignore_list,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from all sources."""
        try:
            if not self._github_client:
                await self._async_setup()

            # Step 1: Get HA versions
            await self._update_ha_versions()

            # Step 2: Get HACS packages
            self._data.packages = await self._hacs_reader.get_installed_packages()
            self._data.packages_total = len(self._data.packages)

            if not self._data.packages:
                _LOGGER.warning("No HACS packages found")

            # Step 3: Check compatibility for each package
            if self._checker:
                self._data.results = await self._checker.check_all_packages(
                    self._data.packages,
                    self._data.ha_current,
                    self._data.ha_next,
                )

            # Step 4: Compute summary stats
            self._data.incompatible_count = sum(
                1 for r in self._data.results if r.status == STATUS_INCOMPATIBLE
            )
            self._data.warning_count = sum(
                1 for r in self._data.results if r.status == STATUS_WARNING
            )
            self._data.compatible_count = sum(
                1 for r in self._data.results if r.status == STATUS_COMPATIBLE
            )
            self._data.unknown_count = sum(
                1 for r in self._data.results if r.status == STATUS_UNKNOWN
            )

            from datetime import datetime
            self._data.last_scan = datetime.utcnow().isoformat()

            _LOGGER.info(
                "HACS compatibility scan complete: %d packages, %d incompatible, %d warnings, %d compatible",
                self._data.packages_total,
                self._data.incompatible_count,
                self._data.warning_count,
                self._data.compatible_count,
            )

            return self._data.to_dict()

        except Exception as exc:
            _LOGGER.error("Error updating HACS compatibility data: %s", exc)
            raise UpdateFailed(f"Error updating HACS compatibility data: {exc}") from exc

    async def _update_ha_versions(self) -> None:
        """Update HA current and next versions."""
        # Current version from HA core
        from homeassistant.const import __version__ as ha_version
        self._data.ha_current = ha_version

        # Next version from GitHub releases
        if self._github_client:
            try:
                releases = await self._github_client.get_ha_releases(per_page=10)
                current_ver = self._parse_simple_version(ha_version)

                for release in releases:
                    tag = release.tag_name
                    # Strip 'v' prefix if present
                    if tag.startswith("v"):
                        tag = tag[1:]

                    rel_ver = self._parse_simple_version(tag)
                    if rel_ver is None:
                        continue

                    if rel_ver > current_ver:
                        if release.prerelease:
                            # Only use pre-release if we haven't found a stable one
                            if self._data.ha_next is None:
                                self._data.ha_next = tag
                                self._data.ha_next_is_rc = True
                        else:
                            self._data.ha_next = tag
                            self._data.ha_next_is_rc = False
                            break  # First stable release > current is the "next" version
            except Exception as exc:
                _LOGGER.warning("Could not determine next HA version: %s", exc)

    @staticmethod
    def _parse_simple_version(version_str: str) -> Any | None:
        """Parse a version string for comparison, returning None on failure."""
        import re
        from packaging.version import InvalidVersion, parse as parse_version

        try:
            cleaned = re.sub(r"(dev\d*|b\d+|rc\d+)$", "", version_str.strip())
            if not cleaned:
                return None
            return parse_version(cleaned)
        except (InvalidVersion, ValueError):
            return None

    @property
    def data_container(self) -> HacsCompatibilityData:
        """Return the data container."""
        return self._data

    async def async_force_check(self) -> None:
        """Force an immediate re-check."""
        _LOGGER.info("Forcing HACS compatibility re-check")
        # Clear cache to force fresh data
        if self._github_client:
            self._github_client.clear_cache()
        await self.async_request_refresh()

    def update_config_from_entry(self) -> None:
        """Update configuration from the config entry (called on options update)."""
        entry_options = self._config_entry.options
        entry_data = self._config_entry.data

        self._check_interval = entry_options.get(
            CONF_CHECK_INTERVAL, DEFAULT_CHECK_INTERVAL
        )
        self._cache_hours = entry_options.get(CONF_CACHE_HOURS, DEFAULT_CACHE_HOURS)
        self._issue_labels_priority = entry_options.get(
            CONF_ISSUE_LABELS_PRIORITY, DEFAULT_ISSUE_LABELS_PRIORITY
        )
        self._ignore_list = entry_options.get(CONF_IGNORE_LIST, [])
        self._github_token = entry_data.get(CONF_GITHUB_TOKEN, "")

        # Update interval
        self.update_interval = timedelta(hours=self._check_interval)

        # Update cache TTL
        if self._github_client:
            self._github_client._cache_ttl = self._cache_hours * 3600

        # Update checker
        if self._checker:
            self._checker._issue_labels = self._issue_labels_priority
            self._checker._ignore_list = set(self._ignore_list)

"""DataUpdateCoordinator for HACS Compatibility Auditor.

Manages periodic scanning and caching of compatibility data.
Supports batch processing to handle large HACS installations efficiently.
"""

import asyncio
from datetime import UTC, datetime as dt, timedelta
import logging
import re
from typing import Any

import aiohttp
from packaging.version import InvalidVersion, parse as parse_version

from homeassistant.const import __version__ as ha_version
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .cache_manager import CacheManager
from .compatibility import CompatibilityChecker, CompatibilityResult
from .const import (
    CONF_BATCH_SIZE,
    CONF_CACHE_HOURS,
    CONF_CHECK_INTERVAL,
    CONF_GITHUB_RETRIES,
    CONF_GITHUB_TIMEOUT,
    CONF_GITHUB_TOKEN,
    CONF_IGNORE_LIST,
    CONF_ISSUE_LABELS_PRIORITY,
    CONF_RULES_ENABLED,
    CONF_RULES_REPO,
    DEFAULT_BATCH_SIZE,
    DEFAULT_CACHE_HOURS,
    DEFAULT_CHECK_INTERVAL,
    DEFAULT_GITHUB_RETRIES,
    DEFAULT_GITHUB_TIMEOUT,
    DEFAULT_ISSUE_LABELS_PRIORITY,
    DEFAULT_RULES_ENABLED,
    DEFAULT_RULES_REPO,
    DOMAIN,
    STATUS_COMPATIBLE,
    STATUS_INCOMPATIBLE,
    STATUS_UNKNOWN,
    STATUS_WARNING,
)
from .github_client import GitHubClient
from .hacs_repository import HacsPackage, HacsRepositoryReader
from .rules_client import RulesClient

_LOGGER = logging.getLogger(__name__)

# Minimum interval between automatic scans (seconds)
_UPDATE_MIN_INTERVAL = 300


class HacsCompatibilityData:
    """Container for all compatibility audit data."""

    def __init__(self) -> None:
        """Initialize data container."""
        self.ha_current: str = ""
        self.ha_next: str | None = None
        self.ha_next_is_rc: bool = False
        self.packages: list[HacsPackage] = []
        self.results: list[dict[str, Any]] = []
        self.packages_total: int = 0
        self.incompatible_count: int = 0
        self.warning_count: int = 0
        self.compatible_count: int = 0
        self.unknown_count: int = 0
        self.last_scan: str = ""
        self.rules_enabled: bool = False
        self.rules_loaded: bool = False
        self.scan_in_progress: bool = False
        self.scan_progress: int = 0
        self.scan_total: int = 0

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
            "results": self.results,
            "last_scan": self.last_scan,
            "rules_enabled": self.rules_enabled,
            "rules_loaded": self.rules_loaded,
            "scan_in_progress": self.scan_in_progress,
            "scan_progress": self.scan_progress,
            "scan_total": self.scan_total,
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
        self._rules_client: RulesClient | None = None
        self._hacs_reader = HacsRepositoryReader(hass)
        self._cache_manager: CacheManager | None = None
        self._scan_lock = asyncio.Lock()
        self._last_scan_ts: dt | None = None
        self._force_refresh: bool = False
        self._background_running: bool = False

        # Read config
        entry_data = config_entry.data
        entry_options = config_entry.options

        self._github_token = entry_data.get(CONF_GITHUB_TOKEN, "")
        self._check_interval = entry_options.get(CONF_CHECK_INTERVAL, DEFAULT_CHECK_INTERVAL)
        self._cache_hours = entry_options.get(CONF_CACHE_HOURS, DEFAULT_CACHE_HOURS)
        self._github_timeout = entry_options.get(CONF_GITHUB_TIMEOUT, DEFAULT_GITHUB_TIMEOUT)
        self._github_retries = entry_options.get(CONF_GITHUB_RETRIES, DEFAULT_GITHUB_RETRIES)
        self._issue_labels_priority = entry_options.get(CONF_ISSUE_LABELS_PRIORITY, DEFAULT_ISSUE_LABELS_PRIORITY)
        self._ignore_list = entry_options.get(CONF_IGNORE_LIST, [])
        self._rules_enabled = entry_options.get(CONF_RULES_ENABLED, DEFAULT_RULES_ENABLED)
        self._rules_repo = entry_options.get(CONF_RULES_REPO, DEFAULT_RULES_REPO)
        self._batch_size = entry_options.get(CONF_BATCH_SIZE, DEFAULT_BATCH_SIZE)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=self._check_interval),
        )

    async def _async_setup(self) -> None:
        """Set up the GitHub client, checker, and cache."""
        if self._github_client is not None:
            _LOGGER.debug("Coordinator already set up, skipping")
            return

        _LOGGER.debug(
            "Setting up GitHub client (timeout=%ds, retries=%d, cache_ttl=%dh, batch_size=%d)",
            self._github_timeout,
            self._github_retries,
            self._cache_hours,
            self._batch_size,
        )
        session = async_create_clientsession(self.hass)
        self._github_client = GitHubClient(
            session=session,
            token=self._github_token or None,
            timeout=self._github_timeout,
            retries=self._github_retries,
        )
        self._github_client.update_cache_ttl(self._cache_hours * 3600)

        # Initialize persistent cache
        _LOGGER.debug("Initializing CacheManager (ttl=%dh)", self._cache_hours)
        self._cache_manager = CacheManager(self.hass, ttl_hours=self._cache_hours)
        await self._cache_manager.async_load()
        _LOGGER.info("Loaded %d cached entries from disk", self._cache_manager.entry_count)

        # Initialize rules client (if enabled)
        rules_client = None
        if self._rules_enabled:
            _LOGGER.debug(
                "Creating RulesClient (repo=%s, hass_version=%s)",
                self._rules_repo,
                self._data.ha_current or "unknown",
            )
            rules_client = RulesClient(
                session=async_create_clientsession(self.hass),
                rules_repo=self._rules_repo,
                hass_version=self._data.ha_current or None,
            )
        self._rules_client = rules_client

        _LOGGER.debug(
            "Creating CompatibilityChecker (labels=%s, ignore_list=%s, rules=%s)",
            self._issue_labels_priority,
            self._ignore_list,
            rules_client is not None,
        )
        self._checker = CompatibilityChecker(
            github_client=self._github_client,
            issue_labels_priority=self._issue_labels_priority,
            ignore_list=self._ignore_list,
            rules_client=rules_client,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from all sources with rate limiting and batch processing."""

        async with self._scan_lock:
            # Rate limiting: skip if scanned too recently (unless forced)
            if not self._force_refresh and self._last_scan_ts is not None:
                elapsed = (dt.now(UTC) - self._last_scan_ts).total_seconds()
                if elapsed < _UPDATE_MIN_INTERVAL:
                    _LOGGER.debug(
                        "Scan skipped: only %.0fs since last scan (min %.0fs)",
                        elapsed,
                        _UPDATE_MIN_INTERVAL,
                    )
                    return self._data.to_dict()

            # If a background batch scan is already running, return current data
            if self._background_running and not self._force_refresh:
                _LOGGER.debug("Background scan already in progress, returning current data")
                return self._data.to_dict()

            was_forced = self._force_refresh
            self._force_refresh = False
            self._last_scan_ts = dt.now(UTC)
            return await self._async_update_data_impl(was_forced)

    async def _async_update_data_impl(self, was_forced: bool = False) -> dict[str, Any]:
        """Internal implementation of data update with batch support."""

        scan_start = dt.now(UTC)
        _LOGGER.info("=== Starting HACS compatibility scan ===")

        try:
            if not self._github_client:
                _LOGGER.debug("GitHub client not initialized, running setup")
                await self._async_setup()

            # Step 1: Get HA versions
            _LOGGER.debug("Step 1/4: Retrieving Home Assistant versions")
            await self._update_ha_versions()
            if self._rules_client and self._data.ha_current:
                self._rules_client.hass_version = self._data.ha_current
            _LOGGER.info(
                "HA versions — current: %s, next: %s (is_rc: %s)",
                self._data.ha_current,
                self._data.ha_next,
                self._data.ha_next_is_rc,
            )

            # Step 1.5: Update rules (if enabled)
            if self._rules_enabled and self._rules_client:
                try:
                    _LOGGER.debug("Step 1.5/4: Updating community rules")
                    await self._rules_client.async_update()
                except (
                    ValueError,
                    KeyError,
                    TypeError,
                    ConnectionError,
                    TimeoutError,
                    UpdateFailed,
                ) as exc:
                    _LOGGER.warning("Error updating rules: %s", exc)
                self._data.rules_loaded = self._rules_client.is_loaded
            else:
                self._data.rules_loaded = False
            self._data.rules_enabled = self._rules_enabled

            # Step 2: Get HACS packages
            _LOGGER.debug("Step 2/4: Enumerating installed HACS packages")
            self._data.packages = await self._hacs_reader.get_installed_packages()
            self._data.packages_total = len(self._data.packages)
            _LOGGER.info("Found %d installed HACS packages", self._data.packages_total)

            if not self._data.packages:
                _LOGGER.warning("No HACS packages found")

            # Step 3: Separate cached vs pending packages
            if self._checker and self._data.packages:
                current_ha = self._data.ha_current
                pending_packages: list[HacsPackage] = []
                cached_results: list[dict[str, Any]] = []

                for pkg in self._data.packages:
                    if self._checker.should_ignore(pkg):
                        cached_results.append(
                            {
                                "name": pkg.name,
                                "repository": pkg.full_name,
                                "type": pkg.category,
                                "installed_version": pkg.installed_version,
                                "latest_version": "",
                                "compatible_with_current": True,
                                "compatible_with_next": True,
                                "status": "ignored",
                                "issues_relevant": [],
                                "manifest_ha_requirement": "",
                                "last_checked": dt.now(tz=UTC).isoformat(),
                                "error": "",
                                "reason": "",
                            }
                        )
                        continue

                    # Check whitelist
                    if self._rules_client and self._rules_client.is_whitelisted(pkg.full_name):
                        cached_results.append(
                            {
                                "name": pkg.name,
                                "repository": pkg.full_name,
                                "type": pkg.category,
                                "installed_version": pkg.installed_version,
                                "latest_version": "",
                                "compatible_with_current": True,
                                "compatible_with_next": True,
                                "status": STATUS_COMPATIBLE,
                                "issues_relevant": [],
                                "manifest_ha_requirement": "",
                                "last_checked": dt.now(tz=UTC).isoformat(),
                                "error": "",
                                "reason": "Whitelisted by community rules",
                            }
                        )
                        continue

                    # Check blacklist
                    if self._rules_client and self._rules_client.is_blacklisted(pkg.full_name):
                        cached_results.append(
                            {
                                "name": pkg.name,
                                "repository": pkg.full_name,
                                "type": pkg.category,
                                "installed_version": pkg.installed_version,
                                "latest_version": "",
                                "compatible_with_current": False,
                                "compatible_with_next": False,
                                "status": STATUS_INCOMPATIBLE,
                                "issues_relevant": [],
                                "manifest_ha_requirement": "",
                                "last_checked": dt.now(tz=UTC).isoformat(),
                                "error": "",
                                "reason": "Blacklisted by community rules",
                            }
                        )
                        continue

                    # Try cache
                    cached = (
                        self._cache_manager.get_valid_entry(pkg.full_name, current_ha) if self._cache_manager else None
                    )
                    if cached is not None and not was_forced:
                        cached_results.append(cached)
                    else:
                        pending_packages.append(pkg)

                _LOGGER.info(
                    "Package check status: %d cached, %d pending%s",
                    len(cached_results),
                    len(pending_packages),
                    " (forced refresh)" if was_forced else "",
                )

                self._data.results = cached_results
                self._data.scan_progress = len(cached_results)
                self._data.scan_total = self._data.packages_total

                if pending_packages:
                    if cached_results:
                        # Return cached data immediately, process pending in background
                        _LOGGER.debug(
                            "Starting background batch scan for %d pending packages (batch_size=%d)",
                            len(pending_packages),
                            self._batch_size,
                        )
                        self._recompute_stats()
                        self._data.last_scan = dt.now(UTC).isoformat()
                        self._data.scan_in_progress = True
                        if self._cache_manager:
                            await self._cache_manager.async_save()
                        self.hass.async_create_task(self._background_batch_scan(pending_packages))
                        return self._data.to_dict()

                    # No cached data at all — process first batch synchronously
                    _LOGGER.debug(
                        "No cached data, processing first batch of %d packages synchronously",
                        min(self._batch_size, len(pending_packages)),
                    )
                    first_batch = pending_packages[: self._batch_size]
                    remaining = pending_packages[self._batch_size :]

                    self._data.scan_in_progress = True
                    await self._process_batch(first_batch, current_ha)

                    if remaining:
                        _LOGGER.debug(
                            "Starting background batch scan for remaining %d packages",
                            len(remaining),
                        )
                        self.hass.async_create_task(self._background_batch_scan(remaining))

                    self._recompute_stats()
                    self._data.last_scan = dt.now(UTC).isoformat()
                    if self._cache_manager:
                        await self._cache_manager.async_save()
                    return self._data.to_dict()

                # All packages cached
                _LOGGER.info(
                    "All %d packages are up to date from cache",
                    self._data.packages_total,
                )
            elif not self._checker:
                _LOGGER.warning("CompatibilityChecker not available, skipping checks")

            # Step 4: Compute summary stats
            self._recompute_stats()
            self._data.last_scan = dt.now(UTC).isoformat()
            self._data.scan_in_progress = False
            if self._cache_manager:
                await self._cache_manager.async_save()

            _LOGGER.info(
                "HACS compatibility scan complete: %d packages, %d incompatible, %d warnings, %d compatible, %d unknown",
                self._data.packages_total,
                self._data.incompatible_count,
                self._data.warning_count,
                self._data.compatible_count,
                self._data.unknown_count,
            )

            return self._data.to_dict()

        except UpdateFailed:
            raise
        except Exception as exc:
            elapsed = (dt.now(UTC) - scan_start).total_seconds()
            _LOGGER.error("Error updating HACS compatibility data after %.1fs: %s", elapsed, exc)
            raise UpdateFailed(f"Error updating HACS compatibility data: {exc}") from exc

    async def _process_batch(
        self,
        batch: list[HacsPackage],
        current_ha: str,
    ) -> None:
        """Process a batch of packages and update results."""
        if not self._checker:
            return

        tasks = [self._checker.check_package(pkg, self._data.ha_current, self._data.ha_next) for pkg in batch]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in batch_results:
            if isinstance(result, Exception):
                _LOGGER.error("Error processing package in batch: %s", result)
                continue
            if isinstance(result, CompatibilityResult):
                result_dict = result.to_dict()
                self._data.results.append(result_dict)
                if self._cache_manager:
                    self._cache_manager.set_entry(
                        result.package.full_name,
                        result_dict,
                        current_ha,
                    )

        self._data.scan_progress = len(self._data.results)

    async def _background_batch_scan(
        self,
        pending_packages: list[HacsPackage],
    ) -> None:
        """Process pending packages in batches in the background.

        After each batch, coordinator data is updated and sensors are notified.
        Handles CancelledError gracefully by saving progress to disk.
        """
        if self._background_running:
            _LOGGER.debug("Background scan already running, skipping duplicate")
            return

        self._background_running = True
        total = len(pending_packages)
        processed_before = len(self._data.results)
        _LOGGER.info(
            "Background batch scan started: %d packages to check (batch_size=%d)",
            total,
            self._batch_size,
        )

        try:
            current_ha = self._data.ha_current

            for i in range(0, total, self._batch_size):
                batch = pending_packages[i : i + self._batch_size]
                batch_num = i // self._batch_size + 1
                total_batches = (total + self._batch_size - 1) // self._batch_size

                _LOGGER.debug(
                    "Background batch %d/%d: checking packages %d-%d of %d",
                    batch_num,
                    total_batches,
                    i + 1,
                    min(i + self._batch_size, total),
                    total,
                )

                await self._process_batch(batch, current_ha)
                self._recompute_stats()
                if self._cache_manager:
                    await self._cache_manager.async_save()

                # Notify sensors with updated data
                self.async_set_updated_data(self._data.to_dict())

                # Yield control to event loop to prevent blocking
                await asyncio.sleep(0)

            _LOGGER.info(
                "Background batch scan complete: %d packages checked",
                total,
            )

        except asyncio.CancelledError:
            checked_count = len(self._data.results) - processed_before
            _LOGGER.warning(
                "Background batch scan cancelled after checking %d/%d packages. Progress saved",
                checked_count,
                total,
            )
            self._recompute_stats()
            if self._cache_manager:
                await self._cache_manager.async_save()
            self.async_set_updated_data(self._data.to_dict())
            raise

        finally:
            self._background_running = False
            self._data.scan_in_progress = False
            self._data.scan_progress = self._data.packages_total
            self.async_set_updated_data(self._data.to_dict())

    def _recompute_stats(self) -> None:
        """Recompute summary statistics from current results."""
        self._data.incompatible_count = sum(1 for r in self._data.results if r.get("status") == STATUS_INCOMPATIBLE)
        self._data.warning_count = sum(1 for r in self._data.results if r.get("status") == STATUS_WARNING)
        self._data.compatible_count = sum(1 for r in self._data.results if r.get("status") == STATUS_COMPATIBLE)
        self._data.unknown_count = sum(1 for r in self._data.results if r.get("status") == STATUS_UNKNOWN)

    async def _update_ha_versions(self) -> None:
        """Update HA current and next versions."""
        self._data.ha_current = ha_version
        _LOGGER.debug("Current HA version: %s", ha_version)

        if self._github_client:
            try:
                _LOGGER.debug("Fetching HA releases from GitHub (per_page=10)")
                releases = await self._github_client.get_ha_releases(per_page=10)
                _LOGGER.debug("Received %d HA releases from GitHub", len(releases))

                current_ver = self._parse_simple_version(ha_version)
                if current_ver is None:
                    _LOGGER.warning("Could not parse current HA version: %s", ha_version)
                    return

                for release in releases:
                    tag = release.tag_name.removeprefix("v")

                    rel_ver = self._parse_simple_version(tag)
                    if rel_ver is None:
                        _LOGGER.debug("Skipping unparseable release tag: %s", tag)
                        continue

                    _LOGGER.debug(
                        "Evaluating release: %s (prerelease=%s, parsed=%s)",
                        tag,
                        release.prerelease,
                        rel_ver,
                    )

                    if rel_ver > current_ver:
                        if release.prerelease:
                            if self._data.ha_next is None:
                                self._data.ha_next = tag
                                self._data.ha_next_is_rc = True
                                _LOGGER.debug(
                                    "Found candidate next version (pre-release): %s",
                                    tag,
                                )
                        else:
                            self._data.ha_next = tag
                            self._data.ha_next_is_rc = False
                            _LOGGER.debug("Found next stable version: %s", tag)
                            break

                if self._data.ha_next is None:
                    _LOGGER.debug("No newer HA version found beyond current %s", ha_version)
            except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
                _LOGGER.warning("Could not determine next HA version: %s", exc)
        else:
            _LOGGER.warning("GitHub client not available, cannot determine next HA version")

    @staticmethod
    def _parse_simple_version(version_str: str) -> Any | None:
        """Parse a version string for comparison, returning None on failure."""
        try:
            cleaned = version_str.strip()
            if "+" in cleaned:
                cleaned = cleaned.split("+")[0]
            cleaned = re.sub(r"(dev\d*|b\d+|rc\d+)$", "", cleaned).rstrip(".")
            if not cleaned:
                return None
            return parse_version(cleaned)
        except (InvalidVersion, ValueError):
            return None

    @property
    def data_container(self) -> HacsCompatibilityData:
        """Return the data container."""
        return self._data

    async def async_check_single_package(self, repository: str) -> dict[str, Any] | None:
        """Check compatibility for a single package by repository name."""
        if not self._checker or not self._github_client:
            _LOGGER.warning("Cannot check single package: checker not initialized")
            return None

        # Find the package in our list
        pkg = None
        for p in self._data.packages:
            if p.full_name == repository:
                pkg = p
                break

        if not pkg:
            _LOGGER.warning("Package %s not found in HACS packages list", repository)
            return None

        _LOGGER.info("Checking single package: %s", repository)
        result = await self._checker.check_package(
            pkg,
            self._data.ha_current,
            self._data.ha_next,
        )
        result_dict = result.to_dict()

        # Update in results list
        found = False
        for i, r in enumerate(self._data.results):
            if r.get("repository") == repository:
                self._data.results[i] = result_dict
                found = True
                break

        if not found:
            self._data.results.append(result_dict)

        # Update cache
        if self._cache_manager:
            self._cache_manager.set_entry(repository, result_dict, self._data.ha_current)
            await self._cache_manager.async_save()

        self._recompute_stats()
        self.async_set_updated_data(self._data.to_dict())

        _LOGGER.info(
            "Single package check complete: %s -> %s",
            repository,
            result_dict.get("status"),
        )
        return result_dict

    async def async_force_check(self) -> None:
        """Force an immediate re-check, bypassing rate limit."""
        _LOGGER.info("Forcing HACS compatibility re-check")
        self._force_refresh = True
        # Clear all caches to force fresh data
        if self._github_client:
            _LOGGER.debug("Clearing GitHub API client cache")
            self._github_client.clear_cache()
        if self._cache_manager:
            _LOGGER.debug("Clearing persistent cache")
            self._cache_manager.clear()
        await self.async_request_refresh()

    def update_config_from_entry(self) -> None:
        """Update configuration from the config entry (called on options update)."""
        entry_options = self._config_entry.options
        entry_data = self._config_entry.data

        old_rules_enabled = self._rules_enabled
        old_rules_repo = self._rules_repo

        self._check_interval = entry_options.get(CONF_CHECK_INTERVAL, DEFAULT_CHECK_INTERVAL)
        self._cache_hours = entry_options.get(CONF_CACHE_HOURS, DEFAULT_CACHE_HOURS)
        self._issue_labels_priority = entry_options.get(CONF_ISSUE_LABELS_PRIORITY, DEFAULT_ISSUE_LABELS_PRIORITY)
        self._ignore_list = entry_options.get(CONF_IGNORE_LIST, [])
        self._github_token = entry_data.get(CONF_GITHUB_TOKEN, "")
        self._rules_enabled = entry_options.get(CONF_RULES_ENABLED, DEFAULT_RULES_ENABLED)
        self._rules_repo = entry_options.get(CONF_RULES_REPO, DEFAULT_RULES_REPO)
        self._batch_size = entry_options.get(CONF_BATCH_SIZE, DEFAULT_BATCH_SIZE)

        # Update interval
        self.update_interval = timedelta(hours=self._check_interval)

        # Update cache TTL
        if self._github_client:
            self._github_client.update_cache_ttl(self._cache_hours * 3600)
        if self._cache_manager:
            self._cache_manager.set_ttl(self._cache_hours)

        # Reinitialize rules client if settings changed
        if old_rules_enabled != self._rules_enabled or old_rules_repo != self._rules_repo:
            if self._rules_enabled:
                self._rules_client = RulesClient(
                    session=async_create_clientsession(self.hass),
                    rules_repo=self._rules_repo,
                    hass_version=self._data.ha_current or None,
                )
            else:
                self._rules_client = None

        # Update checker
        if self._checker:
            self._checker.update_config(self._issue_labels_priority, self._ignore_list)

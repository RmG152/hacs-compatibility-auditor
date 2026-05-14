"""Client to download and cache rules from hacs-compatibility-auditor-rules."""

import json
import logging
import time
from typing import Any

import aiohttp
import yaml

from .const import (
    DEFAULT_RULES_REPO,
    GITHUB_API_BASE,
    RULES_CACHE_TTL_SECONDS,
    RULES_FILES,
    RULES_INDEX_FILE,
)
from .version_utils import check_version_requirement

_LOGGER = logging.getLogger(__name__)


class RulesClient:
    """Client to download and cache rules from hacs-compatibility-auditor-rules."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        rules_repo: str = DEFAULT_RULES_REPO,
        hass_version: str | None = None,
        cache_ttl: int = RULES_CACHE_TTL_SECONDS,
    ) -> None:
        """Initialize the rules client."""
        self._session = session
        self._rules_repo = rules_repo
        self._hass_version = hass_version
        self._cache_ttl = cache_ttl
        self._rules: dict[str, Any] = {}
        self._last_update: float = 0.0
        self._etag: str | None = None

    async def async_update(self) -> None:
        """Force reload rules from GitHub Releases."""
        _LOGGER.debug("Updating rules from %s", self._rules_repo)

        try:
            # 1. Get latest release
            url = f"{GITHUB_API_BASE}/repos/{self._rules_repo}/releases/latest"
            async with self._session.get(url) as resp:
                if resp.status != 200:
                    _LOGGER.warning(
                        "Failed to fetch latest release for %s (status=%d)",
                        self._rules_repo,
                        resp.status,
                    )
                    return
                release_data = await resp.json()

            assets = release_data.get("assets", [])
            if not assets:
                _LOGGER.warning(
                    "No assets found in latest release for %s", self._rules_repo
                )
                return

            # 2. Find and download index.json
            index_asset = None
            for asset in assets:
                if asset.get("name") == RULES_INDEX_FILE:
                    index_asset = asset
                    break

            if not index_asset:
                _LOGGER.warning(
                    "No index.json asset found in latest release for %s",
                    self._rules_repo,
                )
                return

            async with self._session.get(index_asset["browser_download_url"]) as resp:
                if resp.status != 200:
                    _LOGGER.warning(
                        "Failed to download index.json (status=%d)", resp.status
                    )
                    return
                index_data = json.loads(await resp.text())

            # 3. Check if rules have changed
            new_checksum = index_data.get("checksum", "")
            if new_checksum and new_checksum == self._etag:
                _LOGGER.debug(
                    "Rules haven't changed (etag/checksum match), using cache"
                )
                return

            # 4. Download each YAML file
            rules: dict[str, Any] = {}
            asset_map = {a["name"]: a["browser_download_url"] for a in assets}

            for rule_file in RULES_FILES:
                if rule_file not in asset_map:
                    _LOGGER.warning(
                        "Asset %s not found in release, skipping", rule_file
                    )
                    continue

                url = asset_map[rule_file]
                async with self._session.get(url) as resp:
                    if resp.status != 200:
                        _LOGGER.warning(
                            "Failed to download %s (status=%d)", rule_file, resp.status
                        )
                        continue

                    text = await resp.text()
                    parsed = yaml.safe_load(text) or {}

                    # 5. Validate structure
                    key = rule_file.replace(".yaml", "")
                    if isinstance(parsed, (dict, list)):
                        rules[key] = parsed
                    else:
                        _LOGGER.warning("Unexpected format for %s, skipping", rule_file)

            if not rules:
                _LOGGER.warning("No rules could be downloaded, keeping cache")
                return

            # 6. Update cache
            self._rules = rules
            self._last_update = time.time()
            self._etag = new_checksum or str(self._last_update)
            _LOGGER.info("Rules updated successfully (%d categories)", len(rules))

        except (
            TimeoutError,
            aiohttp.ClientError,
            json.JSONDecodeError,
            yaml.YAMLError,
        ) as exc:
            _LOGGER.warning("Error updating rules: %s", exc)

    @property
    def is_loaded(self) -> bool:
        """True if rules are loaded in cache."""
        return bool(self._rules)

    @property
    def last_update(self) -> float | None:
        """Timestamp of the last update."""
        return self._last_update if self._last_update > 0 else None

    def _match_ha_version(self, entry: dict[str, Any]) -> bool:
        """Check if an entry's ha_version matches the configured HA version."""
        ha_version = entry.get("ha_version", "*")
        if ha_version == "*":
            return True
        if not self._hass_version:
            return True
        return check_version_requirement(self._hass_version, ha_version)

    def is_whitelisted(self, full_name: str) -> bool:
        """True if the repo is in whitelist and its ha_version matches."""
        data = self._rules.get("whitelist", {})
        if isinstance(data, dict):
            repositories = data.get("repositories", [])
            if isinstance(repositories, list):
                for entry in repositories:
                    if isinstance(entry, dict) and entry.get("full_name") == full_name:
                        return self._match_ha_version(entry)
        return False

    def is_blacklisted(self, full_name: str) -> bool:
        """True if the repo is in blacklist and its ha_version matches."""
        data = self._rules.get("blacklist", {})
        if isinstance(data, dict):
            repositories = data.get("repositories", [])
            if isinstance(repositories, list):
                for entry in repositories:
                    if isinstance(entry, dict) and entry.get("full_name") == full_name:
                        return self._match_ha_version(entry)
        return False

    def get_false_positives(self, full_name: str) -> set[int]:
        """Returns a set of issue numbers to ignore for this repo."""
        data = self._rules.get("false_positives", {})
        if isinstance(data, dict):
            issues = data.get("issues", [])
            if isinstance(issues, list):
                return {
                    int(entry["issue_number"])
                    for entry in issues
                    if isinstance(entry, dict)
                    and entry.get("full_name") == full_name
                    and isinstance(entry.get("issue_number"), int)
                }
        return set()

    def get_label_overrides(self, full_name: str) -> dict[str, int]:
        """Returns label→weight override for this repo."""
        data = self._rules.get("label_overrides", {})
        if isinstance(data, dict):
            overrides = data.get("overrides", [])
            if isinstance(overrides, list):
                for entry in overrides:
                    if isinstance(entry, dict) and entry.get("full_name") == full_name:
                        labels = entry.get("labels", {})
                        if isinstance(labels, dict):
                            return {
                                str(k): int(v)
                                for k, v in labels.items()
                                if isinstance(v, (int, str)) and str(v).lstrip("-").isdigit()
                            }
        return {}

    def get_keyword_overrides(self, full_name: str) -> dict[str, int]:
        """Returns keyword→weight override for this repo."""
        data = self._rules.get("keyword_overrides", {})
        if isinstance(data, dict):
            overrides = data.get("overrides", [])
            if isinstance(overrides, list):
                for entry in overrides:
                    if isinstance(entry, dict) and entry.get("full_name") == full_name:
                        keywords = entry.get("keywords", {})
                        if isinstance(keywords, dict):
                            return {
                                str(k): int(v)
                                for k, v in keywords.items()
                                if isinstance(v, (int, str)) and str(v).lstrip("-").isdigit()
                            }
        return {}

"""Persistent cache for HACS compatibility results.

Stores individual package results on disk so they survive HA restarts.
Cache file: {config_dir}/.storage/hacs_compatibility_auditor_cache.json
"""

from datetime import UTC, datetime
import json
import logging
from pathlib import Path
import time
from typing import Any

from homeassistant.core import HomeAssistant

from .const import DEFAULT_CACHE_HOURS

_LOGGER = logging.getLogger(__name__)

CACHE_FILENAME = "hacs_compatibility_auditor_cache.json"
CACHE_VERSION = 1


class CacheManager:
    """Manages persistent cache for compatibility results."""

    def __init__(
        self,
        hass: HomeAssistant,
        ttl_hours: float = DEFAULT_CACHE_HOURS,
    ) -> None:
        """Initialize the cache manager."""
        self._hass = hass
        self._ttl_hours = ttl_hours
        self._cache: dict[str, dict[str, Any]] = {}
        self._dirty = False

    @property
    def cache_path(self) -> Path:
        """Return the path to the cache file."""
        return Path(self._hass.config.config_dir) / ".storage" / CACHE_FILENAME

    async def async_load(self) -> None:
        """Load cache entries from disk."""
        path = self.cache_path
        try:
            data = await self._hass.async_add_executor_job(self._read_json, str(path))
            if data and data.get("version") == CACHE_VERSION:
                self._cache = data.get("entries", {})
                _LOGGER.info(
                    "Loaded %d cached compatibility results from %s",
                    len(self._cache),
                    path,
                )
            else:
                _LOGGER.debug("Cache file has incompatible version, starting fresh")
                self._cache = {}
        except FileNotFoundError:
            _LOGGER.debug("No cache file found at %s", path)
            self._cache = {}
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            _LOGGER.warning("Could not read cache file: %s", exc)
            self._cache = {}

    def get_valid_entry(
        self,
        package_full_name: str,
        ha_version: str,
    ) -> dict[str, Any] | None:
        """Return a cached entry if it exists and is still valid."""
        entry = self._cache.get(package_full_name)
        if entry is None:
            return None

        # Check TTL
        cached_at = entry.get("cached_at", 0)
        if time.time() - cached_at > self._ttl_hours * 3600:
            _LOGGER.debug(
                "Cache expired for %s (age: %.1f hours)",
                package_full_name,
                (time.time() - cached_at) / 3600,
            )
            return None

        # Check HA version match (if HA changed, invalidate)
        entry_ha = entry.get("ha_version", "")
        if ha_version and entry_ha and entry_ha != ha_version:
            _LOGGER.debug(
                "Cache invalidated for %s (HA version changed: %s -> %s)",
                package_full_name,
                entry_ha,
                ha_version,
            )
            return None

        _LOGGER.debug("Cache HIT for %s", package_full_name)
        return entry.get("result")

    def set_entry(
        self,
        package_full_name: str,
        result_dict: dict[str, Any],
        ha_version: str,
    ) -> None:
        """Store a compatibility result in the cache."""
        self._cache[package_full_name] = {
            "result": result_dict,
            "cached_at": time.time(),
            "ha_version": ha_version,
        }
        self._dirty = True

    def remove(self, package_full_name: str) -> None:
        """Remove an entry from the cache."""
        self._cache.pop(package_full_name, None)
        self._dirty = True

    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()
        self._dirty = True

    async def async_save(self) -> None:
        """Save cache entries to disk if dirty."""
        if not self._dirty:
            return
        path = self.cache_path
        data = {
            "version": CACHE_VERSION,
            "updated_at": datetime.now(tz=UTC).isoformat(),
            "entries": self._cache,
        }
        try:
            await self._hass.async_add_executor_job(self._write_json, str(path), data)
            self._dirty = False
            _LOGGER.debug("Saved %d cache entries to %s", len(self._cache), path)
        except (OSError, TypeError) as exc:
            _LOGGER.error("Failed to save cache: %s", exc)

    def set_ttl(self, ttl_hours: float) -> None:
        """Set the cache TTL in hours."""
        self._ttl_hours = ttl_hours

    @property
    def entry_count(self) -> int:
        """Return the number of cached entries."""
        return len(self._cache)

    @staticmethod
    def _read_json(path: str) -> dict[str, Any]:
        with Path(path).open(encoding="utf-8") as f:
            return json.loads(f.read())

    @staticmethod
    def _write_json(path: str, data: dict[str, Any]) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with Path(path).open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

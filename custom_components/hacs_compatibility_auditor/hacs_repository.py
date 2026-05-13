"""HACS data repository reader.

This module reads the HACS stored data to enumerate installed packages
without depending on internal HACS APIs that may change between versions.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    PACKAGE_TYPE_APPDAEMON,
    PACKAGE_TYPE_INTEGRATION,
    PACKAGE_TYPE_NETDAEMON,
    PACKAGE_TYPE_PLUGIN,
    PACKAGE_TYPE_PYTHON_SCRIPT,
    PACKAGE_TYPE_THEME,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class HacsPackage:
    """Represents a HACS installed package."""

    id: str
    full_name: str  # "owner/repo"
    name: str
    category: str  # integration, plugin, theme, etc.
    installed_version: str = ""
    available_version: str = ""
    installed: bool = False
    repository_url: str = ""
    owner: str = ""
    repo: str = ""
    description: str = ""
    homeassistant_version: str = ""  # Declared HA version requirement
    last_updated: str = ""


class HacsRepositoryReader:
    """Reads HACS data to enumerate installed packages."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the HACS repository reader."""
        self._hass = hass

    async def get_installed_packages(self) -> list[HacsPackage]:
        """Get all installed HACS packages.

        This method tries multiple approaches to read HACS data:
        1. Direct access to HACS internal data
        2. Reading HACS .storage file
        3. Reading from HACS repositories directory
        """
        _LOGGER.debug("Starting HACS package enumeration")
        packages: list[HacsPackage] = []

        # Approach 1: Try direct HACS access
        _LOGGER.debug("Approach 1: Trying direct HACS internal data access")
        try:
            packages = await self._read_from_hacs_internal()
            if packages:
                _LOGGER.info(
                    "Found %d HACS packages via internal data access", len(packages)
                )
                return packages
            _LOGGER.debug("HACS internal data access returned no packages")
        except Exception as exc:
            _LOGGER.debug("Could not read HACS internal data: %s", exc)

        # Approach 2: Read from HACS .storage file
        _LOGGER.debug("Approach 2: Trying HACS .storage file")
        try:
            packages = await self._read_from_storage()
            if packages:
                _LOGGER.info(
                    "Found %d HACS packages via storage file", len(packages)
                )
                return packages
            _LOGGER.debug("HACS storage file returned no packages")
        except Exception as exc:
            _LOGGER.debug("Could not read HACS storage file: %s", exc)

        # Approach 3: Read from HACS repositories directory
        _LOGGER.debug("Approach 3: Trying HACS repositories directory")
        try:
            packages = await self._read_from_repositories_dir()
            if packages:
                _LOGGER.info(
                    "Found %d HACS packages via repositories directory", len(packages)
                )
                return packages
            _LOGGER.debug("HACS repositories directory returned no packages")
        except Exception as exc:
            _LOGGER.debug("Could not read HACS repositories dir: %s", exc)

        # Log available hass.data keys to help diagnose missing HACS integration
        hacs_keys = [k for k in self._hass.data if "hacs" in k.lower()]
        if hacs_keys:
            _LOGGER.debug(
                "Available hass.data keys containing 'hacs': %s", hacs_keys
            )
        else:
            _LOGGER.debug(
                "No hass.data keys containing 'hacs' found. "
                "Available keys: %s",
                list(self._hass.data.keys()),
            )

        _LOGGER.warning("Could not read HACS data from any source")
        return packages

    async def _read_from_hacs_internal(self) -> list[HacsPackage]:
        """Read packages from HACS internal data structure."""
        hacs_data = self._hass.data.get("hacs")
        if not hacs_data:
            # Fallback: search for any hass.data key containing "hacs"
            for key, value in self._hass.data.items():
                if "hacs" in key.lower():
                    _LOGGER.debug(
                        "Found HACS data under hass.data key: %s", key
                    )
                    hacs_data = value
                    break
        if not hacs_data:
            _LOGGER.debug(
                "HACS integration not found in hass.data"
            )
            return []

        _LOGGER.debug(
            "HACS data object type: %s, attributes: %s",
            type(hacs_data).__name__,
            [a for a in dir(hacs_data) if not a.startswith("_")][:10],
        )

        packages = []

        # Modern HACS: use list_downloaded (returns HacsRepository objects)
        repositories_obj = getattr(hacs_data, "repositories", None)
        if repositories_obj is not None:
            _LOGGER.debug("Found HACS repositories object: %s", type(repositories_obj).__name__)
            list_downloaded = getattr(repositories_obj, "list_downloaded", None)
            if list_downloaded is not None:
                downloaded_count = len(list_downloaded) if hasattr(list_downloaded, "__len__") else "?"
                _LOGGER.debug("Using list_downloaded (%s items)", downloaded_count)
                for repo in list_downloaded:
                    package = self._parse_hacs_repository(repo)
                    if package and package.installed:
                        packages.append(package)
                if packages:
                    _LOGGER.debug(
                        "Parsed %d installed packages from list_downloaded", len(packages)
                    )
                    return packages

            # Fallback: iterate repositories directly
            if isinstance(repositories_obj, dict):
                _LOGGER.debug("Iterating repositories dict (%d entries)", len(repositories_obj))
                for repo in repositories_obj.values():
                    package = self._parse_hacs_repository(repo)
                    if package and package.installed:
                        packages.append(package)
            elif hasattr(repositories_obj, "__iter__"):
                _LOGGER.debug("Iterating repositories collection")
                for repo in repositories_obj:
                    package = self._parse_hacs_repository(repo)
                    if package and package.installed:
                        packages.append(package)
            if packages:
                _LOGGER.debug(
                    "Parsed %d installed packages from repositories collection", len(packages)
                )
                return packages

        # Legacy: try hacs_data.repo
        repo_obj = getattr(hacs_data, "repo", None)
        if repo_obj is not None and hasattr(repo_obj, "__iter__"):
            _LOGGER.debug("Trying legacy hacs_data.repo iteration")
            for repo in repo_obj:
                package = self._parse_hacs_repository(repo)
                if package and package.installed:
                    packages.append(package)

        _LOGGER.debug("Internal HACS read: %d packages found", len(packages))
        return packages

    def _parse_hacs_repository(self, repo: Any) -> HacsPackage | None:
        """Parse a HACS repository object into a HacsPackage."""
        try:
            # Modern HACS: data is in repo.data; legacy: direct attributes
            source = getattr(repo, "data", repo)

            full_name = getattr(source, "full_name", "") or ""
            if not full_name:
                _LOGGER.debug("Skipping HACS repo with no full_name (type=%s)", type(repo).__name__)
                return None

            parts = full_name.split("/")
            owner = parts[0] if len(parts) > 0 else ""
            repo_name = parts[1] if len(parts) > 1 else ""

            category = self._map_category(
                getattr(source, "category", "") or ""
            )

            installed_version = (
                getattr(source, "version_installed", None)
                or getattr(source, "installed_version", "")
                or ""
            )

            available_version = (
                getattr(source, "last_version", None)
                or getattr(source, "available_version", "")
                or ""
            )

            installed = (
                getattr(source, "installed", False)
                or bool(installed_version)
            )

            # Try to get homeassistant_version from repository_manifest
            homeassistant_version = ""
            manifest = getattr(repo, "repository_manifest", None)
            if manifest is not None:
                homeassistant_version = getattr(manifest, "homeassistant", "") or ""
            if not homeassistant_version:
                homeassistant_version = getattr(source, "homeassistant_version", "") or ""

            _LOGGER.debug(
                "Parsed HACS repo: %s (category=%s, installed=%s, version=%s, ha_req=%s)",
                full_name,
                category,
                installed,
                installed_version,
                homeassistant_version,
            )

            return HacsPackage(
                id=str(getattr(source, "id", full_name)),
                full_name=full_name,
                name=getattr(source, "name", "") or repo_name,
                category=category,
                installed_version=installed_version,
                available_version=available_version,
                installed=installed,
                repository_url=f"https://github.com/{full_name}",
                owner=owner,
                repo=repo_name,
                description=getattr(source, "description", "") or "",
                homeassistant_version=homeassistant_version,
            )
        except Exception as exc:
            _LOGGER.debug("Error parsing HACS repository: %s", exc)
            return None

    async def _read_from_storage(self) -> list[HacsPackage]:
        """Read packages from HACS .storage file."""
        config_dir = self._hass.config.config_dir
        storage_dir = Path(config_dir) / ".storage"

        _LOGGER.debug("Looking for HACS storage files in: %s", storage_dir)

        # Try storage files in order of preference
        candidates = [
            storage_dir / "hacs.repositories",   # Modern HACS: all repos dict
            storage_dir / "hacs.data",            # Experimental: grouped by category
            storage_dir / "hacs.hacs",            # Legacy metadata
            storage_dir / "hacs",                 # Ancient format
        ]

        for storage_path in candidates:
            if not storage_path.exists():
                _LOGGER.debug("Storage file not found: %s", storage_path.name)
                continue
            _LOGGER.debug("Reading HACS storage file: %s", storage_path.name)
            try:
                data = await self._hass.async_add_executor_job(
                    self._read_storage_file, str(storage_path)
                )
                packages = self._parse_storage_data(data, storage_path.name)
                if packages:
                    _LOGGER.debug(
                        "Parsed %d packages from %s", len(packages), storage_path.name
                    )
                    return packages
                _LOGGER.debug("No installed packages found in %s", storage_path.name)
            except Exception as exc:
                _LOGGER.debug("Error reading HACS storage %s: %s", storage_path.name, exc)

        # Final fallback: ancient path inside HACS component dir
        ancient_path = Path(config_dir) / "custom_components" / "hacs" / ".storage"
        if ancient_path.exists():
            _LOGGER.debug("Trying legacy HACS storage path: %s", ancient_path)
            try:
                for f in ancient_path.iterdir():
                    if f.suffix == ".json":
                        _LOGGER.debug("Reading legacy storage file: %s", f.name)
                        data = await self._hass.async_add_executor_job(
                            self._read_storage_file, str(f)
                        )
                        packages = self._parse_storage_data(data, f.name)
                        if packages:
                            _LOGGER.debug(
                                "Parsed %d packages from legacy %s",
                                len(packages),
                                f.name,
                            )
                            return packages
            except Exception as exc:
                _LOGGER.debug("Error reading legacy HACS storage: %s", exc)
        else:
            _LOGGER.debug("Legacy HACS storage path does not exist: %s", ancient_path)

        return []

    def _read_storage_file(self, path: str) -> dict[str, Any]:
        """Read a storage file (run in executor)."""
        with open(path, "r", encoding="utf-8") as f:
            return json.loads(f.read())

    def _parse_storage_data(self, data: dict[str, Any], filename: str = "") -> list[HacsPackage]:
        """Parse HACS storage data into packages."""
        packages = []

        # Unwrap Store envelope
        inner = data.get("data", data)

        # Collect repository dicts from all recognized formats
        repo_dicts: list[dict[str, Any]] = []

        if filename == "hacs.repositories":
            # Format: dict keyed by numeric repo ID
            if isinstance(inner, dict):
                repo_dicts = [v for v in inner.values() if isinstance(v, dict)]
        elif filename == "hacs.data":
            # Format: {"repositories": {"category": [{...}, ...], ...}}
            by_category = inner.get("repositories", {})
            if isinstance(by_category, dict):
                for category_repos in by_category.values():
                    if isinstance(category_repos, list):
                        repo_dicts.extend(
                            r for r in category_repos if isinstance(r, dict)
                        )
        else:
            # Legacy formats: list of repos, or dict of repo objects
            repositories = inner.get("repositories", inner.get("data", []))
            if isinstance(repositories, dict):
                repo_dicts = [v for v in repositories.values() if isinstance(v, dict)]
            elif isinstance(repositories, list):
                repo_dicts = [r for r in repositories if isinstance(r, dict)]

        for repo_data in repo_dicts:
            if not repo_data.get("installed", False):
                continue

            full_name = repo_data.get("full_name", "")
            if not full_name:
                continue

            parts = full_name.split("/")
            owner = parts[0] if len(parts) > 0 else ""
            repo_name = parts[1] if len(parts) > 1 else ""

            # Storage uses "version_installed" (not "installed_version")
            installed_version = (
                repo_data.get("version_installed")
                or repo_data.get("installed_version", "")
                or ""
            )
            available_version = (
                repo_data.get("last_version")
                or repo_data.get("available_version", "")
                or ""
            )

            packages.append(
                HacsPackage(
                    id=str(repo_data.get("id", full_name)),
                    full_name=full_name,
                    name=repo_data.get("name", "") or repo_name,
                    category=self._map_category(
                        repo_data.get("category", "")
                    ),
                    installed_version=installed_version,
                    available_version=available_version,
                    installed=True,
                    repository_url=f"https://github.com/{full_name}",
                    owner=owner,
                    repo=repo_name,
                    description=repo_data.get("description", "") or "",
                    homeassistant_version=(
                        repo_data.get("homeassistant_version")
                        or repo_data.get("repository_manifest", {}).get("homeassistant", "")
                        or ""
                    ),
                )
            )

        return packages

    async def _read_from_repositories_dir(self) -> list[HacsPackage]:
        """Read packages from HACS repositories directory."""
        config_dir = self._hass.config.config_dir
        repos_path = Path(config_dir) / "custom_components" / "hacs" / "repositories"

        _LOGGER.debug("Looking for HACS repositories directory: %s", repos_path)

        if not repos_path.exists():
            _LOGGER.debug("HACS repositories directory does not exist")
            return []

        packages = []

        def _scan_dir() -> list[HacsPackage]:
            found = []
            try:
                for category_dir in repos_path.iterdir():
                    if not category_dir.is_dir():
                        continue
                    category = self._map_category(category_dir.name)
                    for repo_file in category_dir.iterdir():
                        if not repo_file.is_file() or not repo_file.suffix == ".json":
                            continue
                        try:
                            with open(repo_file, "r", encoding="utf-8") as f:
                                repo_data = json.loads(f.read())
                            if not repo_data.get("installed", False):
                                continue
                            full_name = repo_data.get("full_name", "")
                            if not full_name:
                                continue
                            parts = full_name.split("/")
                            owner = parts[0] if len(parts) > 0 else ""
                            repo_name = parts[1] if len(parts) > 1 else ""
                            found.append(
                                HacsPackage(
                                    id=str(repo_data.get("id", full_name)),
                                    full_name=full_name,
                                    name=repo_data.get("name", "") or repo_name,
                                    category=category,
                                    installed_version=repo_data.get(
                                        "installed_version", ""
                                    )
                                    or "",
                                    available_version=repo_data.get("last_version", "")
                                    or repo_data.get("available_version", "")
                                    or "",
                                    installed=True,
                                    repository_url=f"https://github.com/{full_name}",
                                    owner=owner,
                                    repo=repo_name,
                                    description=repo_data.get("description", "")
                                    or "",
                                    homeassistant_version=repo_data.get(
                                        "homeassistant_version", ""
                                    )
                                    or "",
                                )
                            )
                        except Exception as exc:
                            _LOGGER.debug(
                                "Error reading repo file %s: %s", repo_file, exc
                            )
            except Exception as exc:
                _LOGGER.debug("Error scanning repositories dir: %s", exc)
            return found

        packages = await self._hass.async_add_executor_job(_scan_dir)
        _LOGGER.debug("Repositories directory scan: %d packages found", len(packages))
        return packages

    @staticmethod
    def _map_category(raw: str) -> str:
        """Map HACS category strings to standard types."""
        mapping = {
            "integration": PACKAGE_TYPE_INTEGRATION,
            "plugin": PACKAGE_TYPE_PLUGIN,
            "theme": PACKAGE_TYPE_THEME,
            "appdaemon": PACKAGE_TYPE_APPDAEMON,
            "netdaemon": PACKAGE_TYPE_NETDAEMON,
            "python_script": PACKAGE_TYPE_PYTHON_SCRIPT,
            "frontend": PACKAGE_TYPE_PLUGIN,
            "card": PACKAGE_TYPE_PLUGIN,
            "lovelace": PACKAGE_TYPE_PLUGIN,
        }
        return mapping.get(raw.lower(), raw.lower() if raw else PACKAGE_TYPE_INTEGRATION)

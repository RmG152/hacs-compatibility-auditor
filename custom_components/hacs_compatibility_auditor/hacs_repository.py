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
        3. Reading from HACS websocket API
        """
        packages: list[HacsPackage] = []

        # Approach 1: Try direct HACS access
        try:
            packages = await self._read_from_hacs_internal()
            if packages:
                return packages
        except Exception as exc:
            _LOGGER.debug("Could not read HACS internal data: %s", exc)

        # Approach 2: Read from HACS .storage file
        try:
            packages = await self._read_from_storage()
            if packages:
                return packages
        except Exception as exc:
            _LOGGER.debug("Could not read HACS storage file: %s", exc)

        # Approach 3: Read from HACS repositories directory
        try:
            packages = await self._read_from_repositories_dir()
            if packages:
                return packages
        except Exception as exc:
            _LOGGER.debug("Could not read HACS repositories dir: %s", exc)

        _LOGGER.warning("Could not read HACS data from any source")
        return packages

    async def _read_from_hacs_internal(self) -> list[HacsPackage]:
        """Read packages from HACS internal data structure."""
        hacs_data = self._hass.data.get("hacs")
        if not hacs_data:
            return []

        packages = []
        repositories = getattr(hacs_data, "repositories", None)
        if repositories is None:
            # Try alternative access patterns
            repo_obj = getattr(hacs_data, "repo", None)
            if repo_obj is None:
                return []
            repositories = repo_obj

        # HACS stores repositories in various ways depending on version
        if isinstance(repositories, dict):
            for repo_id, repo in repositories.items():
                package = self._parse_hacs_repository(repo)
                if package and package.installed:
                    packages.append(package)
        elif hasattr(repositories, "__iter__"):
            for repo in repositories:
                package = self._parse_hacs_repository(repo)
                if package and package.installed:
                    packages.append(package)

        return packages

    def _parse_hacs_repository(self, repo: Any) -> HacsPackage | None:
        """Parse a HACS repository object into a HacsPackage."""
        try:
            full_name = getattr(repo, "full_name", "") or ""
            if not full_name:
                return None

            parts = full_name.split("/")
            owner = parts[0] if len(parts) > 0 else ""
            repo_name = parts[1] if len(parts) > 1 else ""

            return HacsPackage(
                id=str(getattr(repo, "id", full_name)),
                full_name=full_name,
                name=getattr(repo, "name", "") or repo_name,
                category=self._map_category(
                    getattr(repo, "category", "") or ""
                ),
                installed_version=getattr(repo, "installed_version", "") or "",
                available_version=getattr(repo, "last_version", "")
                or getattr(repo, "available_version", "")
                or "",
                installed=getattr(repo, "installed", False),
                repository_url=f"https://github.com/{full_name}",
                owner=owner,
                repo=repo_name,
                description=getattr(repo, "description", "") or "",
                homeassistant_version=getattr(repo, "homeassistant_version", "")
                or "",
            )
        except Exception as exc:
            _LOGGER.debug("Error parsing HACS repository: %s", exc)
            return None

    async def _read_from_storage(self) -> list[HacsPackage]:
        """Read packages from HACS .storage file."""
        config_dir = self._hass.config.config_dir
        storage_path = Path(config_dir) / ".storage" / "hacs"

        if not storage_path.exists():
            # Try alternative storage locations
            alt_paths = [
                Path(config_dir) / ".storage" / "hacs.hacs",
                Path(config_dir) / "custom_components" / "hacs" / ".storage",
            ]
            for alt in alt_paths:
                if alt.exists():
                    storage_path = alt
                    break
            else:
                return []

        try:
            data = await self._hass.async_add_executor_job(
                self._read_storage_file, str(storage_path)
            )
            return self._parse_storage_data(data)
        except Exception as exc:
            _LOGGER.debug("Error reading HACS storage: %s", exc)
            return []

    def _read_storage_file(self, path: str) -> dict[str, Any]:
        """Read a storage file (run in executor)."""
        with open(path, "r", encoding="utf-8") as f:
            return json.loads(f.read())

    def _parse_storage_data(self, data: dict[str, Any]) -> list[HacsPackage]:
        """Parse HACS storage data into packages."""
        packages = []
        repositories = data.get("data", {}).get("repositories", data.get("repositories", []))

        if isinstance(repositories, dict):
            repositories = repositories.values()

        for repo_data in repositories:
            if not isinstance(repo_data, dict):
                continue

            if not repo_data.get("installed", False):
                continue

            full_name = repo_data.get("full_name", "")
            if not full_name:
                continue

            parts = full_name.split("/")
            owner = parts[0] if len(parts) > 0 else ""
            repo_name = parts[1] if len(parts) > 1 else ""

            packages.append(
                HacsPackage(
                    id=str(repo_data.get("id", full_name)),
                    full_name=full_name,
                    name=repo_data.get("name", "") or repo_name,
                    category=self._map_category(
                        repo_data.get("category", "")
                    ),
                    installed_version=repo_data.get("installed_version", "") or "",
                    available_version=repo_data.get("last_version", "")
                    or repo_data.get("available_version", "")
                    or "",
                    installed=True,
                    repository_url=f"https://github.com/{full_name}",
                    owner=owner,
                    repo=repo_name,
                    description=repo_data.get("description", "") or "",
                    homeassistant_version=repo_data.get(
                        "homeassistant_version", ""
                    )
                    or "",
                )
            )

        return packages

    async def _read_from_repositories_dir(self) -> list[HacsPackage]:
        """Read packages from HACS repositories directory."""
        config_dir = self._hass.config.config_dir
        repos_path = Path(config_dir) / "custom_components" / "hacs" / "repositories"

        if not repos_path.exists():
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

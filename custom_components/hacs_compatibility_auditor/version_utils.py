"""Version comparison utilities for HA version checks."""

import logging
import re

from packaging.version import InvalidVersion, Version, parse as parse_version

_LOGGER = logging.getLogger(__name__)


def parse_ha_version(version_str: str) -> Version:
    """Parse a Home Assistant version string.

    HA versions can be like: 2024.1.0, 2024.1.0b1, 2024.1.0dev0
    """
    cleaned = re.sub(r"(dev\d*|b\d+|rc\d+)$", "", version_str.strip()).rstrip(".")
    if not cleaned:
        raise ValueError(f"Empty version after cleaning: {version_str}")
    return parse_version(cleaned)


def satisfies_constraint(version: Version, constraint: str) -> bool:
    """Check if a version satisfies a single constraint."""
    constraint = constraint.strip()

    match = re.match(r"^([<>=!~]+)\s*(.+)$", constraint)
    if match:
        op = match.group(1)
        req_str = match.group(2)
    else:
        op = ">="
        req_str = constraint

    try:
        req_ver = parse_ha_version(req_str)
    except (InvalidVersion, ValueError):
        _LOGGER.warning("Cannot parse requirement version: %s", req_str)
        return False

    result: bool
    if op == ">=":
        result = version >= req_ver
    elif op == ">":
        result = version > req_ver
    elif op == "<=":
        result = version <= req_ver
    elif op == "<":
        result = version < req_ver
    elif op == "==":
        result = version == req_ver
    elif op == "!=":
        result = version != req_ver
    elif op == "~=":
        result = version >= req_ver and version.release[:2] == req_ver.release[:2]
    else:
        _LOGGER.warning("Unknown version operator: %s", op)
        return False

    _LOGGER.debug("Version constraint check: %s %s %s -> %s", version, op, req_ver, result)
    return result


def check_version_requirement(ha_version: str, requirement: str) -> bool:
    """Check if a HA version satisfies a requirement string.

    The requirement can be in various formats:
    - "2024.1.0" - minimum version
    - ">=2024.1.0" - minimum version with operator
    - ">=2024.1.0,<2025.0.0" - range
    - "2024.1" - major.minor format
    """
    if not requirement or not ha_version:
        return True

    try:
        ha_ver = parse_ha_version(ha_version)
    except (InvalidVersion, ValueError):
        _LOGGER.warning("Cannot parse HA version: %s", ha_version)
        return False

    constraints = [c.strip() for c in requirement.split(",")]
    return all(satisfies_constraint(ha_ver, constraint) for constraint in constraints)

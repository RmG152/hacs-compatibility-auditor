"""HACS Compatibility Auditor integration.

Detects the current and next Home Assistant versions, enumerates all
HACS-installed packages, and verifies compatibility by consulting GitHub
issues, release notes, and manifest metadata.
"""

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, UnknownEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    PLATFORMS,
    SERVICE_AI_ANALYZE_PACKAGE,
    SERVICE_AI_CATEGORIZE_ISSUE,
    SERVICE_CHECK_NOW,
    SERVICE_CHECK_PACKAGE,
    SERVICE_REPORT_TO_RULES,
)
from .coordinator import HacsCompatibilityCoordinator

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_CHECK_NOW_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTITY_ID): cv.entity_ids,
    }
)

SERVICE_CHECK_PACKAGE_SCHEMA = vol.Schema(
    {
        vol.Required("repository"): cv.string,
    }
)

SERVICE_AI_ANALYZE_PACKAGE_SCHEMA = vol.Schema(
    {
        vol.Required("repository"): cv.string,
        vol.Optional("provider"): cv.string,
    }
)

SERVICE_AI_CATEGORIZE_ISSUE_SCHEMA = vol.Schema(
    {
        vol.Required("repository"): cv.string,
        vol.Required("issue_number"): vol.All(int, vol.Range(min=1)),
        vol.Optional("provider"): cv.string,
    }
)

SERVICE_REPORT_TO_RULES_SCHEMA = vol.Schema(
    {
        vol.Required("repository"): cv.string,
        vol.Required("issue_number"): vol.All(int, vol.Range(min=1)),
        vol.Required("category"): cv.string,
        vol.Required("reasoning"): cv.string,
        vol.Required("action"): cv.string,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HACS Compatibility Auditor from a config entry."""
    _LOGGER.info("Setting up HACS Compatibility Auditor")

    # Initialize coordinator
    coordinator = HacsCompatibilityCoordinator(hass, entry)

    # Store coordinator in hass data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Perform first data refresh — with batching + cache, this returns quickly
    await coordinator.async_config_entry_first_refresh()

    # Set up platforms (sensors)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services
    async def async_check_now(call: ServiceCall) -> ServiceResponse:
        """Handle the check_now service call."""
        _LOGGER.info("Forcing HACS compatibility check via service")
        await coordinator.async_force_check()
        return {"success": True}

    async def async_check_package(call: ServiceCall) -> ServiceResponse:
        """Handle the check_package service call."""
        repository = call.data.get("repository", "")
        if not repository:
            return {"success": False, "error": "repository parameter is required"}
        _LOGGER.info("Checking single package via service: %s", repository)
        result = await coordinator.async_check_single_package(repository)
        if result:
            return {"success": True, "result": result}
        return {"success": False, "error": f"Package {repository} not found"}

    hass.services.async_register(
        DOMAIN,
        SERVICE_CHECK_NOW,
        async_check_now,
        schema=SERVICE_CHECK_NOW_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_CHECK_PACKAGE,
        async_check_package,
        schema=SERVICE_CHECK_PACKAGE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )

    # Register AI services
    async def async_ai_analyze_package(call: ServiceCall) -> ServiceResponse:
        """Handle the ai_analyze_package service call."""
        repository = call.data.get("repository", "")
        provider = call.data.get("provider")
        if not repository:
            return {"success": False, "error": "repository parameter is required"}
        _LOGGER.info("AI analyzing package: %s", repository)
        return await coordinator.async_analyze_package(repository, provider)

    async def async_ai_categorize_issue(call: ServiceCall) -> ServiceResponse:
        """Handle the ai_categorize_issue service call."""
        repository = call.data.get("repository", "")
        issue_number = call.data.get("issue_number")
        provider = call.data.get("provider")
        if not repository or issue_number is None:
            return {
                "success": False,
                "error": "repository and issue_number parameters are required",
            }
        _LOGGER.info("AI categorizing issue #%d for %s", issue_number, repository)
        return await coordinator.async_categorize_issue(repository, issue_number, provider)

    async def async_report_to_rules(call: ServiceCall) -> ServiceResponse:
        """Handle the report_to_rules service call."""
        repository = call.data.get("repository", "")
        issue_number = call.data.get("issue_number")
        category = call.data.get("category", "")
        reasoning = call.data.get("reasoning", "")
        action = call.data.get("action", "")
        if not all([repository, issue_number, category, reasoning, action]):
            return {
                "success": False,
                "error": "repository, issue_number, category, reasoning, and action are required",
            }
        _LOGGER.info(
            "Reporting issue #%d for %s to rules repo (%s)",
            issue_number,
            repository,
            action,
        )
        return await coordinator.async_report_to_rules(repository, issue_number, category, reasoning, action)

    hass.services.async_register(
        DOMAIN,
        SERVICE_AI_ANALYZE_PACKAGE,
        async_ai_analyze_package,
        schema=SERVICE_AI_ANALYZE_PACKAGE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_AI_CATEGORIZE_ISSUE,
        async_ai_categorize_issue,
        schema=SERVICE_AI_CATEGORIZE_ISSUE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_REPORT_TO_RULES,
        async_report_to_rules,
        schema=SERVICE_REPORT_TO_RULES_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )

    # Register options update listener
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Fire initial compatibility event
    data = coordinator.data
    if data and data.get("incompatible_count", 0) > 0:
        hass.bus.async_fire(
            f"{DOMAIN}_incompatibility_detected",
            {
                "incompatible_count": data.get("incompatible_count", 0),
                "warning_count": data.get("warning_count", 0),
                "incompatible_packages": [
                    r.get("name", "") for r in data.get("results", []) if r.get("status") == "incompatible"
                ],
            },
        )

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    _LOGGER.info("HACS Compatibility Auditor options updated")
    coordinator: HacsCompatibilityCoordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.update_config_from_entry()
    try:
        hass.config_entries.async_schedule_reload(entry)
    except UnknownEntry:
        _LOGGER.warning("Entry %s not found for reload (transient state)", entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading HACS Compatibility Auditor")

    # Remove services
    for service in [
        SERVICE_CHECK_NOW,
        SERVICE_CHECK_PACKAGE,
        SERVICE_AI_ANALYZE_PACKAGE,
        SERVICE_AI_CATEGORIZE_ISSUE,
        SERVICE_REPORT_TO_RULES,
    ]:
        hass.services.async_remove(DOMAIN, service)

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Clean up coordinator
    if entry.entry_id in hass.data.get(DOMAIN, {}):
        del hass.data[DOMAIN][entry.entry_id]

    if not hass.data.get(DOMAIN):
        hass.data.pop(DOMAIN, None)

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle removal of a config entry."""
    _LOGGER.info("Removing HACS Compatibility Auditor entry")

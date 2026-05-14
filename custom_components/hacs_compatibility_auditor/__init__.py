"""HACS Compatibility Auditor integration.

Detects the current and next Home Assistant versions, enumerates all
HACS-installed packages, and verifies compatibility by consulting GitHub
issues, release notes, and manifest metadata.
"""

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, PLATFORMS, SERVICE_CHECK_NOW, SERVICE_CHECK_PACKAGE
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
    hass.config_entries.async_schedule_reload(entry)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading HACS Compatibility Auditor")

    # Remove services
    for service in [SERVICE_CHECK_NOW, SERVICE_CHECK_PACKAGE]:
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

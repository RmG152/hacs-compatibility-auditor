"""HACS Compatibility Auditor integration.

Detects the current and next Home Assistant versions, enumerates all
HACS-installed packages, and verifies compatibility by consulting GitHub
issues, release notes, and manifest metadata.
"""

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, UnknownEntry
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.helpers import config_validation as cv, entity_registry as er

from .const import (
    AI_CATEGORIES,
    AI_CATEGORY_FALSE_POSITIVE as AI_CATEGORY_FALSE_POSITIVE,
    AI_CATEGORY_TRUE_POSITIVE as AI_CATEGORY_TRUE_POSITIVE,
    DOMAIN,
    PLATFORMS,
    SERVICE_AI_ANALYZE_ALL,
    SERVICE_AI_ANALYZE_PACKAGE,
    SERVICE_AI_CATEGORIZE_ISSUE,
    SERVICE_AI_CONFIRM_REPORT,
    SERVICE_CHECK_NOW,
    SERVICE_CHECK_PACKAGE,
    SERVICE_REPORT_TO_RULES,
)
from .coordinator import HacsCompatibilityCoordinator

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


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

    # ------------------------------------------------------------------ #
    # Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _get_repository_from_entity_id(entity_id: str) -> str | None:
        """Resolve a package sensor entity_id to its repository string.

        Reads the ``repository`` attribute directly from the entity's
        ``extra_state_attributes`` so there is no ambiguity when owner or
        repo names contain underscores.
        """
        entity_reg = er.async_get(hass)
        entity = entity_reg.async_get(entity_id)
        if entity is None:
            _LOGGER.warning("Entity %s not found in registry", entity_id)
            return None
        # Prefer the live state attributes (always available once the sensor
        # has been initialised) which contain the full ``repository`` field.
        state = hass.states.get(entity_id)
        if state is not None:
            repository = state.attributes.get("repository")
            if repository:
                return repository
        # Fallback: try to reconstruct from unique_id.
        # unique_id format: hacs_compatibility_auditor_package_{slug}
        # where slug = full_name.lower().replace("/", "_").
        # Because owner/repo names can contain underscores we cannot reliably
        # reverse the slug.  Instead we match against known coordinator data.
        uid = entity.unique_id or ""
        prefix = f"{DOMAIN}_package_"
        if not uid.startswith(prefix):
            _LOGGER.warning(
                "Entity %s unique_id %s does not match expected pattern %s",
                entity_id,
                uid,
                prefix,
            )
            return None
        slug = uid[len(prefix) :]
        # Match slug against coordinator results by comparing lowercased
        # full_name with underscores replaced by the slug.
        coordinator_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if coordinator_data is not None:
            results = getattr(coordinator_data, "data", None)
            if results is not None:
                for result in results.get("results", []):
                    full_name = result.get("repository", "")
                    if full_name.lower().replace("/", "_") == slug:
                        return full_name
        _LOGGER.warning(
            "Cannot resolve repository for entity %s (unique_id=%s)",
            entity_id,
            uid,
        )
        return None

    def _get_provider_name(provider: str | None) -> str | None:
        """Resolve provider name: 'auto' or None → first configured provider."""
        if not provider or provider == "auto":
            return None  # coordinator / AIManager will use first available
        return provider

    # ------------------------------------------------------------------ #
    # Service handlers                                                     #
    # ------------------------------------------------------------------ #

    async def async_check_now(call: ServiceCall) -> ServiceResponse:
        """Handle the check_now service call."""
        _LOGGER.info("Forcing HACS compatibility check via service")
        await coordinator.async_force_check()
        return {"success": True}

    async def async_check_package(call: ServiceCall) -> ServiceResponse:
        """Handle the check_package service call."""
        entity_id = call.data.get("entity_id", "")
        if not entity_id:
            return {"success": False, "error": "entity_id parameter is required"}
        repository = _get_repository_from_entity_id(entity_id)
        if not repository:
            return {
                "success": False,
                "error": f"Could not resolve entity {entity_id} to a repository",
            }
        _LOGGER.info(
            "Checking single package via service: %s (entity: %s)",
            repository,
            entity_id,
        )
        result = await coordinator.async_check_single_package(repository)
        if result:
            return {"success": True, "result": result}
        return {"success": False, "error": f"Package {repository} not found"}

    async def async_ai_analyze_package(call: ServiceCall) -> ServiceResponse:
        """Handle the ai_analyze_package service call."""
        entity_id = call.data.get("entity_id", "")
        provider = call.data.get("provider", "auto")
        if not entity_id:
            return {"success": False, "error": "entity_id parameter is required"}
        repository = _get_repository_from_entity_id(entity_id)
        if not repository:
            return {
                "success": False,
                "error": f"Could not resolve entity {entity_id} to a repository",
            }
        resolved_provider = _get_provider_name(provider)
        _LOGGER.info(
            "AI analyzing package: %s (entity: %s, provider: %s)",
            repository,
            entity_id,
            resolved_provider or "auto",
        )
        return await coordinator.async_analyze_package(repository, resolved_provider)

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

    async def async_ai_analyze_all(call: ServiceCall) -> ServiceResponse:
        """Handle the ai_analyze_all service call."""
        provider = call.data.get("provider", "auto")
        use_cached_only = call.data.get("use_cached_only", False)
        resolved_provider = _get_provider_name(provider)
        _LOGGER.info(
            "AI analyzing all non-compatible packages (provider=%s, use_cached_only=%s)",
            resolved_provider or "auto",
            use_cached_only,
        )
        return await coordinator.async_analyze_all(resolved_provider, use_cached_only)

    async def async_ai_confirm_report(call: ServiceCall) -> ServiceResponse:
        """Handle the ai_confirm_report service call."""
        entity_id = call.data.get("entity_id", "")
        issue_number = call.data.get("issue_number")
        action = call.data.get("action")
        if not entity_id:
            return {"success": False, "error": "entity_id parameter is required"}
        repository = _get_repository_from_entity_id(entity_id)
        if not repository:
            return {
                "success": False,
                "error": f"Could not resolve entity {entity_id} to a repository",
            }
        _LOGGER.info(
            "Confirming AI report for %s (entity: %s, issue: %s)",
            repository,
            entity_id,
            issue_number,
        )
        return await coordinator.async_confirm_report(repository, action, issue_number)

    # ------------------------------------------------------------------ #
    # Register services                                                    #
    # ------------------------------------------------------------------ #

    hass.services.async_register(
        DOMAIN,
        SERVICE_CHECK_NOW,
        async_check_now,
        supports_response=SupportsResponse.OPTIONAL,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_CHECK_PACKAGE,
        async_check_package,
        schema=vol.Schema({"entity_id": cv.entity_id}),
        supports_response=SupportsResponse.OPTIONAL,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_AI_ANALYZE_PACKAGE,
        async_ai_analyze_package,
        schema=vol.Schema(
            {
                vol.Required("entity_id"): cv.entity_id,
                vol.Optional("provider", default="auto"): cv.string,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_AI_CATEGORIZE_ISSUE,
        async_ai_categorize_issue,
        schema=vol.Schema(
            {
                vol.Required("repository"): cv.string,
                vol.Required("issue_number"): vol.All(int, vol.Range(min=1)),
                vol.Optional("provider"): cv.string,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_REPORT_TO_RULES,
        async_report_to_rules,
        schema=vol.Schema(
            {
                vol.Required("repository"): cv.string,
                vol.Required("issue_number"): vol.All(int, vol.Range(min=1)),
                vol.Required("category"): vol.In(AI_CATEGORIES),
                vol.Required("reasoning"): cv.string,
                vol.Required("action"): cv.string,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_AI_ANALYZE_ALL,
        async_ai_analyze_all,
        schema=vol.Schema(
            {
                vol.Optional("provider", default="auto"): cv.string,
                vol.Optional("use_cached_only", default=False): bool,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_AI_CONFIRM_REPORT,
        async_ai_confirm_report,
        schema=vol.Schema(
            {
                vol.Required("entity_id"): cv.entity_id,
                vol.Optional("issue_number", default=None): vol.Any(None, vol.All(int, vol.Range(min=1))),
                vol.Optional("action"): vol.In({"add_false_positive", "report_incompatibility"}),
            }
        ),
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
        SERVICE_AI_ANALYZE_ALL,
        SERVICE_AI_ANALYZE_PACKAGE,
        SERVICE_AI_CATEGORIZE_ISSUE,
        SERVICE_AI_CONFIRM_REPORT,
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

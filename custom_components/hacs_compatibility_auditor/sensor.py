"""Sensor platform for HACS Compatibility Auditor."""

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    STATUS_COMPATIBLE,
    STATUS_INCOMPATIBLE,
    STATUS_UNKNOWN,
    STATUS_WARNING,
)
from .coordinator import HacsCompatibilityCoordinator

_LOGGER = logging.getLogger(__name__)


GLOBAL_SENSOR_DESCRIPTIONS = [
    SensorEntityDescription(
        key="ha_version_current",
        translation_key="ha_version_current",
        icon="mdi:home-assistant",
        device_class=SensorDeviceClass.ENUM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="ha_version_next",
        translation_key="ha_version_next",
        icon="mdi:home-assistant",
        device_class=SensorDeviceClass.ENUM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="hacs_packages_total",
        translation_key="hacs_packages_total",
        icon="mdi:package-variant-closed",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="hacs_incompatible_count",
        translation_key="hacs_incompatible_count",
        icon="mdi:alert-circle",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
]


class HacsCompatibilityGlobalSensor(CoordinatorEntity, SensorEntity):
    """Sensor for global HACS compatibility statistics."""

    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: HacsCompatibilityCoordinator,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{description.key}"
        self._attr_name = f"hca_{description.key}"
        self._attr_native_value = None

    @property
    def native_value(self) -> str | int | None:
        """Return the sensor value."""
        data = self.coordinator.data
        if data is None:
            return None

        key = self.entity_description.key
        if key == "ha_version_current":
            return data.get("ha_current")
        if key == "ha_version_next":
            return data.get("ha_next")
        if key == "hacs_packages_total":
            return data.get("packages_total", 0)
        if key == "hacs_incompatible_count":
            return data.get("incompatible_count", 0)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        data = self.coordinator.data
        if data is None:
            return {}

        key = self.entity_description.key
        attrs: dict[str, Any] = {"last_scan": data.get("last_scan", "")}

        if key == "hacs_incompatible_count":
            attrs["warning_count"] = data.get("warning_count", 0)
            attrs["compatible_count"] = data.get("compatible_count", 0)
            attrs["unknown_count"] = data.get("unknown_count", 0)
            # List incompatible packages
            incompatible = [r["name"] for r in data.get("results", []) if r.get("status") == STATUS_INCOMPATIBLE]
            attrs["incompatible_packages"] = incompatible
            # List warning packages
            warnings = [r["name"] for r in data.get("results", []) if r.get("status") == STATUS_WARNING]
            attrs["warning_packages"] = warnings
        elif key == "ha_version_next":
            attrs["is_release_candidate"] = data.get("ha_next_is_rc", False)
        elif key == "hacs_packages_total":
            # Breakdown by type
            type_counts: dict[str, int] = {}
            for r in data.get("results", []):
                pkg_type = r.get("type", "unknown")
                type_counts[pkg_type] = type_counts.get(pkg_type, 0) + 1
            attrs["by_type"] = type_counts

        # Add rules status to the incompatible_count sensor
        if key == "hacs_incompatible_count":
            attrs["rules_enabled"] = data.get("rules_enabled", False)
            attrs["rules_loaded"] = data.get("rules_loaded", False)

        return attrs

    @property
    def icon(self) -> str:
        """Return dynamic icon based on state."""
        key = self.entity_description.key
        if key == "hacs_incompatible_count":
            val = self.native_value
            if isinstance(val, int) and val > 0:
                return "mdi:alert-circle-outline"
            return "mdi:check-circle-outline"
        return self.entity_description.icon or "mdi:package-variant-closed"


class HacsPackageSensor(CoordinatorEntity, SensorEntity):
    """Sensor for individual HACS package compatibility status."""

    _attr_has_entity_name = False
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: HacsCompatibilityCoordinator,
        package_data: dict[str, Any],
    ) -> None:
        """Initialize the package sensor."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._package_full_name = package_data.get("repository", "")
        self._package_name = package_data.get("name", "")
        slug = self._package_full_name.replace("/", "_").lower()
        self._attr_unique_id = f"{DOMAIN}_package_{slug}"
        self._attr_name = f"hca_package_{slug}"
        self._attr_options = [
            STATUS_COMPATIBLE,
            STATUS_WARNING,
            STATUS_INCOMPATIBLE,
            STATUS_UNKNOWN,
            "ignored",
        ]
        self._package_data = package_data

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        data = self.coordinator.data
        if data:
            for result in data.get("results", []):
                if result.get("repository") == self._package_full_name:
                    self._package_data = result
                    break
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> str:
        """Return the compatibility status."""
        return self._package_data.get("status", STATUS_UNKNOWN)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detailed package attributes."""
        data = self._package_data
        return {
            "name": data.get("name", ""),
            "repository": data.get("repository", ""),
            "type": data.get("type", ""),
            "installed_version": data.get("installed_version", ""),
            "latest_version": data.get("latest_version", ""),
            "compatible_with_current": data.get("compatible_with_current"),
            "compatible_with_next": data.get("compatible_with_next"),
            "manifest_ha_requirement": data.get("manifest_ha_requirement", ""),
            "issues_relevant": data.get("issues_relevant", []),
            "last_checked": data.get("last_checked", ""),
            "error": data.get("error", ""),
            "repository_url": f"https://github.com/{self._package_full_name}",
        }

    @property
    def icon(self) -> str:
        """Return dynamic icon based on compatibility status."""
        status = self.native_value
        if status == STATUS_COMPATIBLE:
            return "mdi:check-circle"
        if status == STATUS_WARNING:
            return "mdi:alert"
        if status == STATUS_INCOMPATIBLE:
            return "mdi:close-circle"
        if status == "ignored":
            return "mdi:eye-off"
        return "mdi:help-circle"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HACS Compatibility Auditor sensors from a config entry."""
    coordinator: HacsCompatibilityCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = []

    # Add global sensors
    entities.extend(
        HacsCompatibilityGlobalSensor(coordinator, description) for description in GLOBAL_SENSOR_DESCRIPTIONS
    )

    # Add per-package sensors
    data = coordinator.data
    if data:
        entities.extend(HacsPackageSensor(coordinator, result) for result in data.get("results", []))

    async_add_entities(entities, True)

    # Store callback to add/remove package sensors on update
    entry.async_on_unload(
        coordinator.async_add_listener(
            lambda: _async_update_package_sensors(hass, entry, coordinator, async_add_entities)
        )
    )


def _async_update_package_sensors(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: HacsCompatibilityCoordinator,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Update package sensors when coordinator data changes."""
    data = coordinator.data
    if not data:
        return

    # Get existing entity unique IDs
    entity_registry = er.async_get(hass)
    existing_uids = {
        entity.unique_id
        for entity in entity_registry.entities.values()
        if entity.config_entry_id == entry.entry_id and entity.platform == DOMAIN
    }

    new_entities: list[SensorEntity] = []
    for result in data.get("results", []):
        slug = result.get("repository", "").replace("/", "_").lower()
        uid = f"{DOMAIN}_package_{slug}"
        if uid not in existing_uids:
            new_entities.append(HacsPackageSensor(coordinator, result))

    if new_entities:
        async_add_entities(new_entities, True)

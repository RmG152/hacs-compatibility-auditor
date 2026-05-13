"""Unit tests for sensor platform."""

import pytest
from unittest.mock import MagicMock, patch

from custom_components.hacs_compatibility_auditor.const import (
    STATUS_COMPATIBLE,
    STATUS_INCOMPATIBLE,
    STATUS_WARNING,
)
from custom_components.hacs_compatibility_auditor.sensor import (
    HacsCompatibilityGlobalSensor,
    HacsPackageSensor,
)


class TestGlobalSensorValues:
    """Tests for global sensor native values."""

    def _make_coordinator(self, data: dict):
        """Create a mock coordinator with given data."""
        coordinator = MagicMock()
        coordinator.data = data
        return coordinator

    def test_ha_version_current(self):
        """Test HA version current sensor value."""
        from custom_components.hacs_compatibility_auditor.sensor import (
            GLOBAL_SENSOR_DESCRIPTIONS,
        )

        desc = GLOBAL_SENSOR_DESCRIPTIONS[0]  # ha_version_current
        coordinator = self._make_coordinator({"ha_current": "2024.6.0"})
        sensor = HacsCompatibilityGlobalSensor(coordinator, desc)

        assert sensor.native_value == "2024.6.0"

    def test_ha_version_next(self):
        """Test HA version next sensor value."""
        from custom_components.hacs_compatibility_auditor.sensor import (
            GLOBAL_SENSOR_DESCRIPTIONS,
        )

        desc = GLOBAL_SENSOR_DESCRIPTIONS[1]  # ha_version_next
        coordinator = self._make_coordinator({"ha_next": "2024.7.0"})
        sensor = HacsCompatibilityGlobalSensor(coordinator, desc)

        assert sensor.native_value == "2024.7.0"

    def test_packages_total(self):
        """Test packages total sensor value."""
        from custom_components.hacs_compatibility_auditor.sensor import (
            GLOBAL_SENSOR_DESCRIPTIONS,
        )

        desc = GLOBAL_SENSOR_DESCRIPTIONS[2]  # hacs_packages_total
        coordinator = self._make_coordinator({"packages_total": 15})
        sensor = HacsCompatibilityGlobalSensor(coordinator, desc)

        assert sensor.native_value == 15

    def test_incompatible_count(self):
        """Test incompatible count sensor value."""
        from custom_components.hacs_compatibility_auditor.sensor import (
            GLOBAL_SENSOR_DESCRIPTIONS,
        )

        desc = GLOBAL_SENSOR_DESCRIPTIONS[3]  # hacs_incompatible_count
        coordinator = self._make_coordinator({
            "incompatible_count": 2,
            "warning_count": 3,
            "compatible_count": 10,
            "unknown_count": 0,
            "results": [],
        })
        sensor = HacsCompatibilityGlobalSensor(coordinator, desc)

        assert sensor.native_value == 2
        attrs = sensor.extra_state_attributes
        assert attrs["warning_count"] == 3
        assert attrs["compatible_count"] == 10

    def test_no_data_returns_none(self):
        """Test that no coordinator data returns None."""
        from custom_components.hacs_compatibility_auditor.sensor import (
            GLOBAL_SENSOR_DESCRIPTIONS,
        )

        desc = GLOBAL_SENSOR_DESCRIPTIONS[0]
        coordinator = self._make_coordinator(None)
        sensor = HacsCompatibilityGlobalSensor(coordinator, desc)

        assert sensor.native_value is None


class TestPackageSensor:
    """Tests for per-package sensor."""

    def _make_coordinator(self, data: dict = None):
        """Create a mock coordinator."""
        coordinator = MagicMock()
        coordinator.data = data
        return coordinator

    def test_compatible_status(self):
        """Test a compatible package sensor."""
        package_data = {
            "nombre": "Test Card",
            "repositorio": "test/card",
            "tipo": "plugin",
            "version_instalada": "1.0.0",
            "version_mas_reciente": "1.1.0",
            "compatible_con_actual": True,
            "compatible_con_siguiente": True,
            "estado": STATUS_COMPATIBLE,
            "issues_relevantes": [],
            "requisito_ha_manifest": "",
            "ultima_comprobacion": "2024-06-01T00:00:00",
            "error": "",
        }
        coordinator = self._make_coordinator()
        sensor = HacsPackageSensor(coordinator, package_data)

        assert sensor.native_value == STATUS_COMPATIBLE
        assert sensor.extra_state_attributes["nombre"] == "Test Card"
        assert sensor.extra_state_attributes["compatible_con_actual"] is True

    def test_incompatible_status(self):
        """Test an incompatible package sensor."""
        package_data = {
            "nombre": "Broken",
            "repositorio": "test/broken",
            "tipo": "integration",
            "version_instalada": "2.0.0",
            "version_mas_reciente": "2.0.0",
            "compatible_con_actual": False,
            "compatible_con_siguiente": False,
            "estado": STATUS_INCOMPATIBLE,
            "issues_relevantes": [
                {"title": "Broken after HA update", "url": "https://github.com/test/broken/issues/1"}
            ],
            "requisito_ha_manifest": ">=2025.1.0",
            "ultima_comprobacion": "2024-06-01T00:00:00",
            "error": "",
        }
        coordinator = self._make_coordinator()
        sensor = HacsPackageSensor(coordinator, package_data)

        assert sensor.native_value == STATUS_INCOMPATIBLE
        attrs = sensor.extra_state_attributes
        assert attrs["compatible_con_actual"] is False
        assert len(attrs["issues_relevantes"]) == 1

    def test_warning_icon(self):
        """Test dynamic icon for warning status."""
        package_data = {
            "nombre": "Warned",
            "repositorio": "test/warned",
            "tipo": "theme",
            "version_instalada": "1.0.0",
            "version_mas_reciente": "1.0.0",
            "compatible_con_actual": True,
            "compatible_con_siguiente": None,
            "estado": STATUS_WARNING,
            "issues_relevantes": [],
            "requisito_ha_manifest": "",
            "ultima_comprobacion": "",
            "error": "",
        }
        coordinator = self._make_coordinator()
        sensor = HacsPackageSensor(coordinator, package_data)

        assert sensor.icon == "mdi:alert"

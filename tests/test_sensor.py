"""Unit tests for sensor platform."""

from unittest.mock import MagicMock

from custom_components.hacs_compatibility_auditor.const import STATUS_COMPATIBLE, STATUS_INCOMPATIBLE, STATUS_WARNING
from custom_components.hacs_compatibility_auditor.sensor import HacsCompatibilityGlobalSensor, HacsPackageSensor


class TestGlobalSensorValues:
    """Tests for global sensor native values."""

    def _make_coordinator(self, data: dict):
        """Create a mock coordinator with given data."""
        coordinator = MagicMock()
        coordinator.data = data
        return coordinator

    def _make_description(self, key: str) -> MagicMock:
        """Create a mock SensorEntityDescription with the given key."""
        desc = MagicMock()
        desc.key = key
        return desc

    def test_ha_version_current(self):
        """Test HA version current sensor value."""
        desc = self._make_description("ha_version_current")
        coordinator = self._make_coordinator({"ha_current": "2024.6.0"})
        sensor = HacsCompatibilityGlobalSensor(coordinator, desc)

        assert sensor.native_value == "2024.6.0"

    def test_ha_version_next(self):
        """Test HA version next sensor value."""
        desc = self._make_description("ha_version_next")
        coordinator = self._make_coordinator({"ha_next": "2024.7.0"})
        sensor = HacsCompatibilityGlobalSensor(coordinator, desc)

        assert sensor.native_value == "2024.7.0"

    def test_packages_total(self):
        """Test packages total sensor value."""
        desc = self._make_description("hacs_packages_total")
        coordinator = self._make_coordinator({"packages_total": 15})
        sensor = HacsCompatibilityGlobalSensor(coordinator, desc)

        assert sensor.native_value == 15

    def test_incompatible_count(self):
        """Test incompatible count sensor value."""
        desc = self._make_description("hacs_incompatible_count")
        coordinator = self._make_coordinator(
            {
                "incompatible_count": 2,
                "warning_count": 3,
                "compatible_count": 10,
                "unknown_count": 0,
                "results": [],
            }
        )
        sensor = HacsCompatibilityGlobalSensor(coordinator, desc)

        assert sensor.native_value == 2
        attrs = sensor.extra_state_attributes
        assert attrs["warning_count"] == 3
        assert attrs["compatible_count"] == 10

    def test_no_data_returns_none(self):
        """Test that no coordinator data returns None."""
        desc = self._make_description("ha_version_current")
        coordinator = self._make_coordinator(None)
        sensor = HacsCompatibilityGlobalSensor(coordinator, desc)

        assert sensor.native_value is None


class TestPackageSensor:
    """Tests for per-package sensor."""

    def _make_coordinator(self, data: dict | None = None):
        """Create a mock coordinator."""
        coordinator = MagicMock()
        coordinator.data = data
        return coordinator

    def test_compatible_status(self):
        """Test a compatible package sensor."""
        package_data = {
            "name": "Test Card",
            "repository": "test/card",
            "type": "plugin",
            "installed_version": "1.0.0",
            "latest_version": "1.1.0",
            "compatible_with_current": True,
            "compatible_with_next": True,
            "status": STATUS_COMPATIBLE,
            "issues_relevant": [],
            "manifest_ha_requirement": "",
            "last_checked": "2024-06-01T00:00:00",
            "error": "",
        }
        coordinator = self._make_coordinator()
        sensor = HacsPackageSensor(coordinator, package_data)

        assert sensor.native_value == STATUS_COMPATIBLE
        assert sensor.extra_state_attributes["name"] == "Test Card"
        assert sensor.extra_state_attributes["compatible_with_current"] is True

    def test_incompatible_status(self):
        """Test an incompatible package sensor."""
        package_data = {
            "name": "Broken",
            "repository": "test/broken",
            "type": "integration",
            "installed_version": "2.0.0",
            "latest_version": "2.0.0",
            "compatible_with_current": False,
            "compatible_with_next": False,
            "status": STATUS_INCOMPATIBLE,
            "issues_relevant": [
                {
                    "title": "Broken after HA update",
                    "url": "https://github.com/test/broken/issues/1",
                }
            ],
            "manifest_ha_requirement": ">=2025.1.0",
            "last_checked": "2024-06-01T00:00:00",
            "error": "",
        }
        coordinator = self._make_coordinator()
        sensor = HacsPackageSensor(coordinator, package_data)

        assert sensor.native_value == STATUS_INCOMPATIBLE
        attrs = sensor.extra_state_attributes
        assert attrs["compatible_with_current"] is False
        assert len(attrs["issues_relevant"]) == 1

    def test_warning_icon(self):
        """Test dynamic icon for warning status."""
        package_data = {
            "name": "Warned",
            "repository": "test/warned",
            "type": "theme",
            "installed_version": "1.0.0",
            "latest_version": "1.0.0",
            "compatible_with_current": True,
            "compatible_with_next": None,
            "status": STATUS_WARNING,
            "issues_relevant": [],
            "manifest_ha_requirement": "",
            "last_checked": "",
            "error": "",
        }
        coordinator = self._make_coordinator()
        sensor = HacsPackageSensor(coordinator, package_data)

        assert sensor.icon == "mdi:alert"

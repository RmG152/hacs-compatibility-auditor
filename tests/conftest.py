"""pytest configuration and mocks for HACS Compatibility Auditor tests."""

import sys
from unittest.mock import MagicMock

# Build a mock homeassistant package hierarchy
ha = MagicMock()

# __version__ on const
ha.const.__version__ = "2026.4.0"
ha.const.ATTR_ENTITY_ID = "entity_id"

# Core classes
ha.core.HomeAssistant = MagicMock
ha.core.ServiceCall = MagicMock
ha.core.ServiceResponse = MagicMock
ha.core.SupportsResponse = MagicMock
ha.core.callback = lambda x: x

# Config entries
ha.config_entries.ConfigEntry = MagicMock


class MockConfigFlow:
    VERSION = 1


ha.config_entries.ConfigFlow = MockConfigFlow


class MockOptionsFlow:
    pass


ha.config_entries.OptionsFlow = MockOptionsFlow

# Data entry flow
ha.data_entry_flow.FlowResult = MagicMock

# Entity registry
ha.helpers.entity_registry.async_get = MagicMock(return_value={})
ha.helpers.entity_registry.er = MagicMock()

# aiohttp client
ha.helpers.aiohttp_client.async_create_clientsession = MagicMock(return_value=MagicMock())
ha.helpers.aiohttp_client.async_get_clientsession = MagicMock(return_value=MagicMock())

# Config validation
ha.helpers.config_validation = MagicMock()
ha.helpers.config_validation.config_entry_only_config_schema = MagicMock(return_value=MagicMock())

# Entity platform
ha.helpers.entity_platform.AddEntitiesCallback = MagicMock


# Update coordinator
class MockDataUpdateCoordinator:
    def __init__(self, *args, **kwargs):
        pass


ha.helpers.update_coordinator.DataUpdateCoordinator = MockDataUpdateCoordinator
ha.helpers.update_coordinator.UpdateFailed = type("UpdateFailed", (Exception,), {})


class MockCoordinatorEntity:
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.hass = None


ha.helpers.update_coordinator.CoordinatorEntity = MockCoordinatorEntity

# Sensor component
ha.components.sensor.SensorDeviceClass = MagicMock()
ha.components.sensor.SensorDeviceClass.ENUM = "enum"


class MockSensorEntity:
    pass


ha.components.sensor.SensorEntity = MockSensorEntity
ha.components.sensor.SensorEntityDescription = MagicMock()
ha.components.sensor.SensorStateClass = MagicMock()
ha.components.sensor.SensorStateClass.MEASUREMENT = "measurement"

# Const
ha.const.EntityCategory = MagicMock()
ha.const.EntityCategory.DIAGNOSTIC = "diagnostic"

# Exceptions
ha.exceptions.ConfigEntryNotReady = type("ConfigEntryNotReady", (Exception,), {})
ha.exceptions.HomeAssistantError = type("HomeAssistantError", (Exception,), {})

# Register in sys.modules
sys.modules["homeassistant"] = ha
sys.modules["homeassistant.const"] = ha.const
sys.modules["homeassistant.core"] = ha.core
sys.modules["homeassistant.exceptions"] = ha.exceptions
sys.modules["homeassistant.config_entries"] = ha.config_entries
sys.modules["homeassistant.helpers"] = ha.helpers
sys.modules["homeassistant.helpers.entity_registry"] = ha.helpers.entity_registry
sys.modules["homeassistant.helpers.aiohttp_client"] = ha.helpers.aiohttp_client
sys.modules["homeassistant.helpers.config_validation"] = ha.helpers.config_validation
sys.modules["homeassistant.helpers.entity_platform"] = ha.helpers.entity_platform
sys.modules["homeassistant.helpers.update_coordinator"] = ha.helpers.update_coordinator
sys.modules["homeassistant.data_entry_flow"] = ha.data_entry_flow
sys.modules["homeassistant.components"] = ha.components
sys.modules["homeassistant.components.sensor"] = ha.components.sensor

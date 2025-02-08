"""Sensor platform for EV Charger Modbus."""
import logging
from typing import Optional

import voluptuous as vol

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import (
    CONF_NAME,
    UnitOfElectricCurrent,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = vol.Schema({
    vol.Required(CONF_NAME): cv.string,
})

async def async_setup_platform(
    hass: HomeAssistant,
    config: dict,
    async_add_entities: AddEntitiesCallback,
    discovery_info: Optional[dict] = None,
) -> None:
    """Set up the EV Charger sensor platform."""
    name = config[CONF_NAME]
    device = hass.data.get(DOMAIN, {}).get("device")

    if not device:
        _LOGGER.error("Device not initialized in hass.data[%s]", DOMAIN)
        return

    sensors = [
        EVChargerStateSensor(device, name),
        EVChargerMaxCurrentSensor(device, name),
        EVChargerCurrent1Sensor(device, name),
        EVChargerCurrent2Sensor(device, name),
        EVChargerCurrent3Sensor(device, name),
    ]
    async_add_entities(sensors)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the EV Charger sensor platform from a config entry."""
    device = hass.data.get(DOMAIN, {}).get("device")
    name = config_entry.data[CONF_NAME]

    if not device:
        _LOGGER.error("Device not initialized in hass.data[%s]", DOMAIN)
        return

    sensors = [
        EVChargerStateSensor(device, name),
        EVChargerMaxCurrentSensor(device, name),
        EVChargerCurrent1Sensor(device, name),
        EVChargerCurrent2Sensor(device, name),
        EVChargerCurrent3Sensor(device, name),
    ]
    async_add_entities(sensors)

class EVChargerBaseSensor(SensorEntity):
    """Base class for EV Charger sensors."""

    def __init__(self, device, name: str, sensor_type: str):
        """Initialize the sensor."""
        self._device = device
        self._attr_name = f"{name} {sensor_type}"
        self._attr_unique_id = f"{DOMAIN}_{name.lower()}_{sensor_type.lower().replace(' ', '_')}"
        self._state = None

    async def async_update(self) -> None:
        """Update the sensor."""
        try:
            await self.hass.async_add_executor_job(self._device.update_state)
            values = await self.hass.async_add_executor_job(self._device.read_current)
            if values:
                self._update_from_values(values)
        except Exception as e:
            _LOGGER.error("Error updating sensor %s: %s", self._attr_name, str(e))

    def _update_from_values(self, values: dict) -> None:
        """Update state from values dictionary."""
        raise NotImplementedError

class EVChargerStateSensor(EVChargerBaseSensor):
    """Sensor for EV Charger state."""

    def __init__(self, device, name: str):
        """Initialize the sensor."""
        super().__init__(device, name, "State")

    def _update_from_values(self, values: dict) -> None:
        """Update state from values dictionary."""
        self._attr_native_value = values.get('state_description')

class EVChargerMaxCurrentSensor(EVChargerBaseSensor):
    """Sensor for EV Charger maximum current."""

    def __init__(self, device, name: str):
        """Initialize the sensor."""
        super().__init__(device, name, "Max Current")
        self._attr_device_class = SensorDeviceClass.CURRENT
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE

    def _update_from_values(self, values: dict) -> None:
        """Update state from values dictionary."""
        self._attr_native_value = values.get('max_current')

class EVChargerCurrent1Sensor(EVChargerBaseSensor):
    """Sensor for EV Charger current 1."""

    def __init__(self, device, name: str):
        """Initialize the sensor."""
        super().__init__(device, name, "Current 1")
        self._attr_device_class = SensorDeviceClass.CURRENT
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE

    def _update_from_values(self, values: dict) -> None:
        """Update state from values dictionary."""
        self._attr_native_value = values.get('ict1')

class EVChargerCurrent2Sensor(EVChargerBaseSensor):
    """Sensor for EV Charger current 2."""

    def __init__(self, device, name: str):
        """Initialize the sensor."""
        super().__init__(device, name, "Current 2")
        self._attr_device_class = SensorDeviceClass.CURRENT
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE

    def _update_from_values(self, values: dict) -> None:
        """Update state from values dictionary."""
        self._attr_native_value = values.get('ict2')

class EVChargerCurrent3Sensor(EVChargerBaseSensor):
    """Sensor for EV Charger current 3."""

    def __init__(self, device, name: str):
        """Initialize the sensor."""
        super().__init__(device, name, "Current 3")
        self._attr_device_class = SensorDeviceClass.CURRENT
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE

    def _update_from_values(self, values: dict) -> None:
        """Update state from values dictionary."""
        self._attr_native_value = values.get('ict3')
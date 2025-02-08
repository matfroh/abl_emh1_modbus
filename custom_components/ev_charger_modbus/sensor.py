# custom_components/ev_charger_modbus/sensor.py
"""EV Charger sensor platform."""
from typing import Optional, Dict, Any
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import UnitOfElectricCurrent
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

class EVChargerBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class for EV Charger sensors."""

    def __init__(self, coordinator, name: str, key_path: list):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = name
        self._key_path = key_path

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if self.coordinator.data is None:
            return False
        return self.coordinator.data.get("available", False)

    def _get_value_from_path(self, data: Dict[str, Any]) -> Any:
        """Get value from nested dictionary using key path."""
        for key in self._key_path:
            if not isinstance(data, dict) or key not in data:
                return None
            data = data[key]
        return data

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            return None
        return self._get_value_from_path(self.coordinator.data)

class EVChargerCurrentSensor(EVChargerBaseSensor):
    """Sensor for EV Charger current readings."""

    def __init__(self, coordinator, name: str, current_type: str):
        """Initialize the current sensor."""
        super().__init__(coordinator, name, ["current_measurements", current_type])
        self._attr_device_class = SensorDeviceClass.CURRENT
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE

class EVChargerStateSensor(EVChargerBaseSensor):
    """Sensor for EV Charger state."""

    def __init__(self, coordinator, name: str):
        """Initialize the state sensor."""
        super().__init__(coordinator, name, ["state", "description"])

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the EV Charger sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    name = hass.data[DOMAIN][entry.entry_id]["name"]

    sensors = [
        EVChargerCurrentSensor(coordinator, f"{name} Current 1", "ict1"),
        EVChargerCurrentSensor(coordinator, f"{name} Current 2", "ict2"),
        EVChargerCurrentSensor(coordinator, f"{name} Current 3", "ict3"),
        EVChargerStateSensor(coordinator, f"{name} State"),
    ]

    async_add_entities(sensors)
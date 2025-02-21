# custom_components/ev_charger_modbus/sensor.py
"""EV Charger sensor platform."""
from typing import Optional, Dict, Any
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import CONF_NAME, UnitOfElectricCurrent
from . import EVChargerEntity
from .const import DOMAIN

class EVChargerBaseSensor(EVChargerEntity, SensorEntity):
    """Base class for EV Charger sensors."""
    def __init__(self, coordinator, name: str, key_path: list):
        """Initialize the base sensor."""
        super().__init__(coordinator, name)
        self._key_path = key_path

    def _get_value_from_path(self, data: Dict[str, Any]) -> Any:
        """Get value from nested dictionary using key path."""
        for key in self._key_path:
            if not isinstance(data, dict) or key not in data:
                return None
            data = data[key]
        return data

class EVChargerStateSensor(EVChargerBaseSensor):
    """Sensor for EV Charger state."""
    def __init__(self, coordinator, name: str):
        """Initialize the state sensor."""
        super().__init__(coordinator, name, ["state", "description"])
        self._attr_name = "State"
        self._attr_unique_id = f"{name}_state"

    @property
    def native_value(self) -> str:
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("state", {}).get("description")

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if self.coordinator.data is None:
            return False
        return self.coordinator.data.get("available", False)

class EVChargerCurrentSensor(EVChargerEntity, SensorEntity):
    """Sensor for EV Charger current readings."""
    def __init__(self, coordinator, device_name: str, current_type: str):
        """Initialize the current sensor."""
        super().__init__(coordinator, device_name)
        self._current_type = current_type
        self._attr_name = f"Current {current_type.replace('ict', '')}"
        self._attr_unique_id = f"{device_name}_{current_type}_current"
        self._attr_device_class = SensorDeviceClass.CURRENT
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("current_measurements", {}).get(self._current_type)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the EV Charger sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    device_name = hass.data[DOMAIN][entry.entry_id][CONF_NAME]
    
    sensors = [
        EVChargerCurrentSensor(coordinator, device_name, "ict1"),
        EVChargerCurrentSensor(coordinator, device_name, "ict2"),
        EVChargerCurrentSensor(coordinator, device_name, "ict3"),
        EVChargerStateSensor(coordinator, device_name)
    ]
    
    async_add_entities(sensors)
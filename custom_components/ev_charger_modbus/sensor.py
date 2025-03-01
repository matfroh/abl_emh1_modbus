import logging
from typing import Optional, Dict, Any
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import CONF_NAME, UnitOfElectricCurrent, UnitOfPower, PERCENTAGE
from . import EVChargerEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)  # Initialize logger

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
                _LOGGER.debug("Key '%s' not found in data: %s", key, data)
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
            _LOGGER.debug("Coordinator data is None for State sensor.")
            return None
        value = self.coordinator.data.get("state", {}).get("description")
        _LOGGER.debug("State sensor value: %s", value)
        return value

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
            _LOGGER.debug("Coordinator data is None for Current sensor '%s'.", self._current_type)
            return None
        value = self.coordinator.data.get("current_measurements", {}).get(self._current_type)
        _LOGGER.debug("Current sensor '%s' value: %s", self._current_type, value)
        return value

class EVChargerDutyCycleSensor(EVChargerEntity, SensorEntity):
    """Sensor for EV Charger duty cycle."""
    def __init__(self, coordinator, device_name: str):
        """Initialize the duty cycle sensor."""
        super().__init__(coordinator, device_name)
        self._attr_name = "Duty Cycle"
        self._attr_unique_id = f"{device_name}_duty_cycle"
        self._attr_device_class = SensorDeviceClass.POWER_FACTOR
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = PERCENTAGE

    @property
    def native_value(self):
        """Return the duty cycle percentage."""
        try:
            duty_cycle = self.coordinator.device.read_duty_cycle()
            _LOGGER.debug(f"Duty Cycle sensor retrieved: {duty_cycle}")
            return duty_cycle
        except Exception as e:
            _LOGGER.error(f"Error getting duty cycle: {e}")
            return None

class EVChargerPowerConsumptionSensor(EVChargerEntity, SensorEntity):
    """Sensor for EV Charger power consumption."""
    def __init__(self, coordinator, device_name: str):
        """Initialize the power consumption sensor."""
        super().__init__(coordinator, device_name)
        self._attr_name = "Power Consumption"
        self._attr_unique_id = f"{device_name}_power_consumption"
        self._attr_device_class = SensorDeviceClass.POWER
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfPower.WATT

    @property
    def native_value(self):
        """Return the calculated power consumption."""
        try:
            power_consumption = self.coordinator.device.calculate_consumption_with_duty_cycle()
            _LOGGER.debug(f"Power Consumption sensor retrieved: {power_consumption}")
            return power_consumption
        except Exception as e:
            _LOGGER.error(f"Error getting power consumption: {e}")
            return None

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the EV Charger sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    device_name = hass.data[DOMAIN][entry.entry_id][CONF_NAME]
    
    sensors = [
        EVChargerCurrentSensor(coordinator, device_name, "ict1"),
        EVChargerCurrentSensor(coordinator, device_name, "ict2"),
        EVChargerCurrentSensor(coordinator, device_name, "ict3"),
        EVChargerStateSensor(coordinator, device_name),
        EVChargerDutyCycleSensor(coordinator, device_name),
        EVChargerPowerConsumptionSensor(coordinator, device_name),
    ]
    
    _LOGGER.debug("Adding EV Charger sensors: %s", [sensor._attr_name for sensor in sensors])
    async_add_entities(sensors)

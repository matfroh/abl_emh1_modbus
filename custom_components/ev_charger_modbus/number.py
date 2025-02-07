# custom_components/ev_charger_modbus/number.py
"""Number platform for EV Charger Modbus."""
import logging
from typing import Optional

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the EV Charger number platform."""
    device = hass.data[DOMAIN]["device"]
    name = hass.data[DOMAIN][CONF_NAME]
    
    entity = EVChargerNumber(device, name)
    async_add_entities([entity])
    
    # Store entity reference for service calls
    if "entities" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["entities"] = []
    hass.data[DOMAIN]["entities"].append(entity)

class EVChargerNumber(NumberEntity):
    """Representation of the EV Charger current setting."""
    
    def __init__(self, device: ModbusASCIIDevice, name: str):
        """Initialize the number entity."""
        self._device = device
        self._attr_name = f"{name} Current"
        self._attr_unique_id = f"{name.lower()}_current"
        self._attr_native_min_value = 0
        self._attr_native_max_value = 16
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = "A"
        self._attr_native_value = None

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
        current = await self.hass.async_add_executor_job(self._device.read_current)
        self._attr_native_value = current

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        success = await self.hass.async_add_executor_job(
            self._device.write_current, int(value)
        )
        if success:
            self._attr_native_value = value
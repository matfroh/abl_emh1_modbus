"""Number platform for EV Charger Modbus."""
from homeassistant.components.number import NumberEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from . import EVChargerEntity
from .const import (
    DOMAIN,
    CONF_MAX_CURRENT,
    DEFAULT_MAX_CURRENT,
)

import logging
_LOGGER = logging.getLogger(__name__)

class ChargingCurrentNumber(EVChargerEntity, NumberEntity):
    """Slider for setting maximum charging current."""

    def __init__(self, coordinator, device_name: str) -> None:
        """Initialize the slider."""
        super().__init__(coordinator, device_name)
        self._attr_native_min_value = 5
        self._attr_native_max_value = coordinator.max_current
        self._attr_native_step = 1
        self._attr_native_value = coordinator.max_current  # Default value
        _LOGGER.debug("Initialized slider with name: %s", self._attr_name)

    @property
    def native_value(self) -> float:
        """Return the current value."""
        if self.coordinator.data is None:
            return self._attr_native_value
        return self.coordinator.data.get("charging_current", self._attr_native_value)

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        _LOGGER.debug("Setting charging current to: %s", value)
        try:
            success = await self.hass.async_add_executor_job(
                self._device.write_current, int(value)
            )
            if success:
                self._attr_native_value = value
                _LOGGER.info("Successfully set charging current to %sA", value)
                await self.coordinator.async_request_refresh()
            else:
                _LOGGER.error("Failed to set charging current")
        except Exception as e:
            _LOGGER.exception("Error setting charging current: %s", e)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the EV Charger number platform from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    device = hass.data[DOMAIN][entry.entry_id]["device"]
    device_name = hass.data[DOMAIN][entry.entry_id][CONF_NAME]

    _LOGGER.debug("Setting up number platform with device_name: %s", device_name)
    
    entity = ChargingCurrentNumber(coordinator, device_name)
    async_add_entities([entity])
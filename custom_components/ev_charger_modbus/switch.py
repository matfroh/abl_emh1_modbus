"""Switch platform for EV Charger Modbus."""
import logging
from typing import Any, Optional

import voluptuous as vol

from homeassistant.components.switch import PLATFORM_SCHEMA, SwitchEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Platform schema for YAML configuration
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_NAME): cv.string,
})

async def async_setup_platform(
    hass: HomeAssistant,
    config: dict,
    async_add_entities: AddEntitiesCallback,
    discovery_info: Optional[dict] = None,
) -> None:
    """Set up the EV Charger switch platform from YAML."""
    name = config[CONF_NAME]
    device = hass.data.get(DOMAIN, {}).get("device")

    if not device:
        _LOGGER.error("Device not initialized in hass.data[%s]", DOMAIN)
        return

    async_add_entities([EVChargerSwitch(device, name)])

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the EV Charger switch platform from a config entry."""
    device = hass.data.get(DOMAIN, {}).get("device")
    name = config_entry.data[CONF_NAME]

    if not device:
        _LOGGER.error("Device not initialized in hass.data[%s]", DOMAIN)
        return

    async_add_entities([EVChargerSwitch(device, name)])

class EVChargerSwitch(SwitchEntity):
    """Switch for enabling/disabling EV charging."""

    def __init__(self, device, name):
        """Initialize the switch."""
        self._device = device
        self._attr_name = f"{name} Charging Enable"
        self._attr_unique_id = f"{DOMAIN}_{name.lower()}_charging_enable"
        self._attr_is_on = False  # Default state

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on charging."""
        try:
            success = await self.hass.async_add_executor_job(self._device.enable_charging)
            if success:
                self._attr_is_on = True
                self.async_write_ha_state()
                _LOGGER.info("Charging enabled")
            else:
                _LOGGER.error("Failed to enable charging")
        except Exception as e:
            _LOGGER.error("Error enabling charging: %s", e)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off charging."""
        try:
            success = await self.hass.async_add_executor_job(self._device.disable_charging)
            if success:
                self._attr_is_on = False
                self.async_write_ha_state()
                _LOGGER.info("Charging disabled")
            else:
                _LOGGER.error("Failed to disable charging")
        except Exception as e:
            _LOGGER.error("Error disabling charging: %s", e)


    async def async_update(self) -> None:
        """Update the switch state."""
        try:
            self._attr_is_on = await self.hass.async_add_executor_job(self._device.is_charging_enabled)
            self.async_write_ha_state()
            _LOGGER.debug(f"Updated charging state to: {'ON' if self._attr_is_on else 'OFF'}")
        except Exception as ex:
            _LOGGER.error("Error updating switch state: %s", ex)

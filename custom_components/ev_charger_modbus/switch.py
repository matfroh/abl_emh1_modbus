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
        _LOGGER.info("Initializing EVChargerSwitch with name: %s", name)
        self._device = device
        self._attr_name = f"{name} Charging Enable"
        self._attr_unique_id = f"{DOMAIN}_{name.lower()}_charging_enable"
        self._attr_is_on = False
        self._state_description = "Unknown"
        _LOGGER.debug("Switch initialized with name: %s, unique_id: %s", self._attr_name, self._attr_unique_id)

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        _LOGGER.debug("Getting extra state attributes: %s", {"state_description": self._state_description})
        return {
            "state_description": self._state_description
        }

    async def async_turn_on(self, **kwargs):
        """Turn on charging."""
        _LOGGER.info("Attempting to turn on charging")
        try:
            success = await self.hass.async_add_executor_job(self._device.enable_charging)
            if success:
                self._attr_is_on = True
                _LOGGER.info("Successfully enabled charging")
            else:
                _LOGGER.error("Failed to enable charging")
        except Exception as e:
            _LOGGER.exception("Error enabling charging: %s", e)

    async def async_turn_off(self, **kwargs):
        """Turn off charging."""
        _LOGGER.info("Attempting to turn off charging")
        try:
            success = await self.hass.async_add_executor_job(self._device.disable_charging)
            if success:
                self._attr_is_on = False
                _LOGGER.info("Successfully disabled charging")
            else:
                _LOGGER.error("Failed to disable charging")
        except Exception as e:
            _LOGGER.exception("Error disabling charging: %s", e)

    async def async_update(self) -> None:
        """Update the switch state based on the charging state."""
        _LOGGER.debug("Starting async_update()")
        try:
            # Update the device state first
            _LOGGER.debug("Calling device.update_state()")
            await self.hass.async_add_executor_job(self._device.update_state)
            
            # Get the current state code from the device
            state_code = self._device.state_code
            _LOGGER.debug("Retrieved state_code: 0x%02X", state_code if state_code is not None else 0)
            
            # Update the state description
            self._state_description = self._device.state_description
            _LOGGER.debug("Updated state_description: %s", self._state_description)
            
            # Update switch state based on state code
            old_state = self._attr_is_on
            if state_code is None or state_code in [0xE0, 0xE2]:
                self._attr_is_on = False
            else:
                self._attr_is_on = True

            _LOGGER.info(
                "Switch state updated - Old: %s, New: %s, State code: 0x%02X, Description: %s",
                old_state,
                self._attr_is_on,
                state_code if state_code is not None else 0,
                self._state_description
            )
            
        except Exception as ex:
            _LOGGER.exception("Error updating switch state: %s", ex)
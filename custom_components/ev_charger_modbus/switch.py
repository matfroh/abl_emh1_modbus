"""Switch platform for EV Charger Modbus."""
import logging
import asyncio
from typing import Any, Optional
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from . import EVChargerEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

class EVChargerSwitch(EVChargerEntity, SwitchEntity):
    """Switch for enabling/disabling EV charging."""

    def __init__(self, coordinator, device_name: str, device: Any):
        """Initialize the switch."""
        super().__init__(coordinator, device_name)
        self._device = device
        self._attr_name = f"{device_name} Charging Enable"
        self._attr_unique_id = f"{DOMAIN}_{device_name.lower()}_charging_enable"
        _LOGGER.debug("Switch initialized with name: %s, unique_id: %s", 
                     self._attr_name, self._attr_unique_id)

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        if self.coordinator.data is None:
            return {"state_description": "Unknown"}
        
        return {
            "state_description": self.coordinator.data.get("state", {}).get("description", "Unknown")
        }

    @property
    def is_on(self) -> bool | None:
        """Return true if the switch is on."""
        if self.coordinator.data is None:
            return None
            
        # Get state code from the new data structure
        state_code_hex = self.coordinator.data.get("state", {}).get("code")
        if state_code_hex is None:
            return None

        # Convert hex string to int if necessary
        if isinstance(state_code_hex, str) and state_code_hex.startswith("0x"):
            state_code = int(state_code_hex, 16)
        else:
            state_code = state_code_hex

        _LOGGER.debug("Got state_code from coordinator: 0x%02X", 
                     state_code if state_code is not None else 0)
        
        if state_code is None:
            return None

        # Get charging state from device
        return self.coordinator.data.get("charging", {}).get("enabled", False)

    async def async_turn_on(self, **kwargs):
        """Turn on charging."""
        _LOGGER.info("Attempting to turn on charging")
        try:
            success = await self._device.enable_charging()
            if success:
                _LOGGER.info("Successfully enabled charging")
                await asyncio.sleep(2)
                await self.coordinator.async_request_refresh()
            else:
                _LOGGER.error("Failed to enable charging")
        except Exception as e:
            _LOGGER.exception("Error enabling charging: %s", e)

    async def async_turn_off(self, **kwargs):
        """Turn off charging."""
        _LOGGER.info("Attempting to turn off charging")
        try:
            success = await self._device.disable_charging()
            if success:
                _LOGGER.info("Successfully disabled charging")
                await asyncio.sleep(2)
                await self.coordinator.async_request_refresh()
            else:
                _LOGGER.error("Failed to disable charging")
        except Exception as e:
            _LOGGER.exception("Error disabling charging: %s", e)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the EV Charger switch platform from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    device = hass.data[DOMAIN][entry.entry_id]["device"]
    device_name = hass.data[DOMAIN][entry.entry_id][CONF_NAME]
    
    if not device:
        _LOGGER.error("Device not initialized in hass.data[%s][%s]", 
                     DOMAIN, entry.entry_id)
        return

    async_add_entities([
        EVChargerSwitch(
            coordinator=coordinator,
            device_name=device_name,
            device=device
        )
    ])
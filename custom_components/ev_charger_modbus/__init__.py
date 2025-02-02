# custom_components/ev_charger_modbus/__init__.py
"""The EV Charger Modbus integration."""
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, CONF_PORT, CONF_SLAVE, Platform
from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    CONF_BAUDRATE,
    DEFAULT_NAME,
    DEFAULT_SLAVE,
    DEFAULT_BAUDRATE,
)
from .modbus_device import ModbusASCIIDevice

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.NUMBER]

SET_CURRENT_SCHEMA = vol.Schema({
    vol.Required("current"): vol.All(
        vol.Coerce(int),
        vol.Range(min=5, max=16)
    )
})

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_PORT): cv.string,
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
                vol.Optional(CONF_SLAVE, default=DEFAULT_SLAVE): cv.positive_int,
                vol.Optional(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): cv.positive_int,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the EV Charger component."""
    if DOMAIN not in config:
        return True

    hass.data.setdefault(DOMAIN, {})
    conf = config[DOMAIN]
    
    # Create ModbusASCIIDevice instance
    device = ModbusASCIIDevice(
        port=conf[CONF_PORT],
        slave_id=conf.get(CONF_SLAVE, DEFAULT_SLAVE),
        baudrate=conf.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)
    )
    
    hass.data[DOMAIN] = {
        "device": device,
        CONF_NAME: conf.get(CONF_NAME, DEFAULT_NAME),
    }

    async def handle_set_charging_current(call: ServiceCall) -> None:
        """Handle the service call."""
        current = call.data["current"]
        device = hass.data[DOMAIN]["device"]
        success = await hass.async_add_executor_job(device.write_current, current)
        
        if not success:
            _LOGGER.error(f"Failed to set charging current to {current}A")
            return
        
        _LOGGER.info(f"Successfully set charging current to {current}A")
        
        # Update all number entities
        for entity in hass.data[DOMAIN].get("entities", []):
            entity._attr_native_value = current
            entity.async_write_ha_state()

    # Register the service
    hass.services.async_register(
        DOMAIN,
        "set_charging_current",
        handle_set_charging_current,
        schema=SET_CURRENT_SCHEMA,
    )

    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up EV Charger from a config entry."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


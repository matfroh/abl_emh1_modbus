"""The EVSE Modbus Integration."""
from homeassistant.core import HomeAssistant
from homeassistant.const import (
    CONF_PORT,
    CONF_BAUDRATE,
    Platform,
)
import voluptuous as vol
import homeassistant.helpers.config_validation as cv

DOMAIN = "abl_emh1_modbus"
PLATFORMS = [Platform.SENSOR, Platform.NUMBER]

# Configuration schema
CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_PORT): cv.string,
                vol.Optional(CONF_BAUDRATE, default=38400): cv.positive_int,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the EVSE Modbus component."""
    if DOMAIN not in config:
        return True

    hass.data[DOMAIN] = {
        CONF_PORT: config[DOMAIN][CONF_PORT],
        CONF_BAUDRATE: config[DOMAIN][CONF_BAUDRATE],
    }

    await hass.helpers.discovery.async_load_platform("number", DOMAIN, {}, config)
    await hass.helpers.discovery.async_load_platform("sensor", DOMAIN, {}, config)

    return True

"""Config flow for EV Charger Modbus integration."""
import logging
import voluptuous as vol
from typing import Any, Dict, Optional

from homeassistant import config_entries
from homeassistant.const import CONF_NAME, CONF_PORT, CONF_SLAVE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_BAUDRATE,
    CONF_MAX_CURRENT,
    DEFAULT_NAME,
    DEFAULT_SLAVE,
    DEFAULT_BAUDRATE,
    DEFAULT_MAX_CURRENT,
)
from .modbus_device import ModbusASCIIDevice

_LOGGER = logging.getLogger(__name__)

class EVChargerModbusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for EV Charger Modbus."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            _LOGGER.debug(
                "Attempting to connect with settings - Port: %s, Slave: %s, Baudrate: %s",
                user_input[CONF_PORT],
                user_input.get(CONF_SLAVE, DEFAULT_SLAVE),
                user_input.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)
            )
            
            try:
                # Test the connection
                _LOGGER.debug("Initializing ModbusASCIIDevice...")
                device = ModbusASCIIDevice(
                    port=user_input[CONF_PORT],
                    slave_id=user_input.get(CONF_SLAVE, DEFAULT_SLAVE),
                    baudrate=user_input.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)
                )
                          
                # First, try to wake up the device
                _LOGGER.debug("Attempting to wake up the device...")
                await self.hass.async_add_executor_job(device.wake_up_device)
            
                # Wait a moment for the device to fully wake up
                import asyncio
                await asyncio.sleep(1)                
                
                _LOGGER.debug("ModbusASCIIDevice initialized, attempting to read current...")
                # Try to read values to verify connection
                result = await self.hass.async_add_executor_job(device.read_current)
                
                if result is None:
                    _LOGGER.error("Read operation returned None - connection failed")
                    errors["base"] = "cannot_connect"
                else:
                    _LOGGER.debug("Successfully read current value: %s", result)
                    
                    # Try to detect max current from device
                    detected_max_current = await self.hass.async_add_executor_job(device.read_max_current_setting)
                    if detected_max_current:
                        _LOGGER.info("Detected max current from device: %dA", detected_max_current)
                        # Store the detected value in user_input for the entry
                        user_input[CONF_MAX_CURRENT] = detected_max_current
                    else:
                        _LOGGER.warning("Could not detect max current, using default: %dA", DEFAULT_MAX_CURRENT)
                        user_input[CONF_MAX_CURRENT] = DEFAULT_MAX_CURRENT
                    
                    # Close the connection after testing
                    try:
                        device.serial.close()
                        _LOGGER.debug("Serial connection closed successfully")
                    except Exception as close_ex:
                        _LOGGER.warning("Error closing serial connection: %s", str(close_ex))
                    
                    # Create entry
                    return self.async_create_entry(
                        title=user_input[CONF_NAME],
                        data=user_input
                    )
            except Exception as ex:
                _LOGGER.error("Connection error details: %s", str(ex))
                _LOGGER.exception("Full traceback of connection error:")
                errors["base"] = "cannot_connect"

        # Show configuration form
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                    vol.Required(CONF_PORT): str,
                    vol.Optional(CONF_SLAVE, default=DEFAULT_SLAVE): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=247)
                    ),
                    vol.Optional(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): vol.All(
                        vol.Coerce(int), vol.In([9600, 19200, 38400, 57600, 115200])
                    ),
                }
            ),
            errors=errors,
        )
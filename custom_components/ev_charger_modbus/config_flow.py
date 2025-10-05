"""Config flow for EV Charger Modbus integration."""
import logging
import voluptuous as vol
from typing import Any, Dict, Optional
import asyncio
from homeassistant import config_entries
from homeassistant.const import CONF_NAME, CONF_PORT, CONF_SLAVE
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv
from .const import (
    DOMAIN,
    CONF_CONNECTION_TYPE,
    CONF_HOST,
    CONF_TCP_PORT,
    CONF_BAUDRATE,
    CONF_MAX_CURRENT,
    DEFAULT_NAME,
    DEFAULT_SLAVE,
    DEFAULT_BAUDRATE,
    DEFAULT_MAX_CURRENT,
    DEFAULT_TCP_PORT,
    CONNECTION_TYPE_SERIAL,
    CONNECTION_TYPE_TCP,
)
from .modbus_device import ModbusASCIIDevice

_LOGGER = logging.getLogger(__name__)

class EVChargerModbusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for EV Charger Modbus."""
    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    def __init__(self):
        """Initialize."""
        self._connection_type = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return EVChargerModbusOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the initial step - choose connection type."""
        if user_input is not None:
            self._connection_type = user_input[CONF_CONNECTION_TYPE]
            if self._connection_type == CONNECTION_TYPE_SERIAL:
                return await self.async_step_serial()
            else:
                return await self.async_step_tcp()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CONNECTION_TYPE, default=CONNECTION_TYPE_SERIAL): vol.In(
                        {
                            CONNECTION_TYPE_SERIAL: "Serial (RS485)",
                            CONNECTION_TYPE_TCP: "TCP/IP (Ethernet)",
                        }
                    ),
                }
            ),
        )

    async def async_step_serial(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle serial connection configuration."""
        errors = {}
        if user_input is not None:
            user_input[CONF_CONNECTION_TYPE] = CONNECTION_TYPE_SERIAL
            success, detected_max = await self._test_connection(user_input, errors)
            if success:
                user_input[CONF_MAX_CURRENT] = detected_max or DEFAULT_MAX_CURRENT
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data=user_input
                )
        return self.async_show_form(
            step_id="serial",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                    vol.Required(CONF_PORT, default="/dev/ttyUSB0"): str,
                    vol.Optional(CONF_SLAVE, default=DEFAULT_SLAVE): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=247)
                    ),
                    vol.Optional(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): vol.In(
                        [9600, 19200, 38400, 57600, 115200]
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_tcp(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle TCP connection configuration."""
        errors = {}
        if user_input is not None:
            user_input[CONF_CONNECTION_TYPE] = CONNECTION_TYPE_TCP
            user_input[CONF_PORT] = f"{user_input[CONF_HOST]}:{user_input[CONF_TCP_PORT]}"
            success, detected_max = await self._test_connection(user_input, errors)
            if success:
                user_input[CONF_MAX_CURRENT] = detected_max or DEFAULT_MAX_CURRENT
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data=user_input
                )
        return self.async_show_form(
            step_id="tcp",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                    vol.Required(CONF_HOST): str,
                    vol.Optional(CONF_TCP_PORT, default=DEFAULT_TCP_PORT): cv.port,
                    vol.Optional(CONF_SLAVE, default=DEFAULT_SLAVE): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=247)
                    ),
                }
            ),
            errors=errors,
        )

    async def _test_connection(
        self, user_input: Dict[str, Any], errors: Dict[str, str]
    ) -> tuple[bool, Optional[int]]:
        """Test the connection and return (success, detected_max_current)."""
        try:
            _LOGGER.debug("Testing connection with: %s", user_input)
            device = ModbusASCIIDevice(
                port=user_input[CONF_PORT],
                slave_id=user_input.get(CONF_SLAVE, DEFAULT_SLAVE),
                baudrate=user_input.get(CONF_BAUDRATE, DEFAULT_BAUDRATE),
                connection_type=user_input.get(CONF_CONNECTION_TYPE, CONNECTION_TYPE_SERIAL),
            )
            await device.connect()
            _LOGGER.debug("Waking up device...")
            await device.wake_up_device()
            await asyncio.sleep(1)
            _LOGGER.debug("Testing read operation...")
            result = await device.read_current()
            if result is None:
                _LOGGER.error("Read operation returned None")
                errors["base"] = "cannot_connect"
                return False, None
            _LOGGER.debug("Successfully read current: %s", result)
            detected_max = await device.read_max_current_setting()
            if detected_max:
                _LOGGER.info("Detected max current: %dA", detected_max)
            else:
                _LOGGER.warning("Could not detect max current")
            device.transport.close()
            return True, detected_max
        except Exception as ex:
            _LOGGER.exception("Connection test failed: %s", ex)
            errors["base"] = "cannot_connect"
            return False, None

class EVChargerModbusOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for reconfiguration."""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        """Initialize options flow."""
        self.config_entry = config_entry
        self._connection_type = config_entry.data.get(CONF_CONNECTION_TYPE, CONNECTION_TYPE_SERIAL)

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Manage the options: First, ask for connection type."""
        if user_input is not None:
            self._connection_type = user_input[CONF_CONNECTION_TYPE]
            if self._connection_type == CONNECTION_TYPE_SERIAL:
                return await self.async_step_serial_reconfigure()
            else:
                return await self.async_step_tcp_reconfigure()
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CONNECTION_TYPE,
                        default=self.config_entry.data.get(CONF_CONNECTION_TYPE, CONNECTION_TYPE_SERIAL),
                    ): vol.In(
                        {
                            CONNECTION_TYPE_SERIAL: "Serial (RS485)",
                            CONNECTION_TYPE_TCP: "TCP/IP (Ethernet)",
                        }
                    ),
                }
            ),
        )

    async def async_step_serial_reconfigure(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Reconfigure serial connection."""
        if user_input is not None:
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, **user_input, CONF_CONNECTION_TYPE: CONNECTION_TYPE_SERIAL},
            )
            return self.async_create_entry(title="", data={})
        current_data = self.config_entry.data
        return self.async_show_form(
            step_id="serial_reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PORT, default=current_data.get(CONF_PORT, "/dev/ttyUSB0")): str,
                    vol.Optional(CONF_SLAVE, default=current_data.get(CONF_SLAVE, DEFAULT_SLAVE)): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=247)
                    ),
                    vol.Optional(CONF_BAUDRATE, default=current_data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)): vol.In(
                        [9600, 19200, 38400, 57600, 115200]
                    ),
                }
            ),
        )

    async def async_step_tcp_reconfigure(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Reconfigure TCP connection."""
        if user_input is not None:
            user_input[CONF_PORT] = f"{user_input[CONF_HOST]}:{user_input[CONF_TCP_PORT]}"
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, **user_input, CONF_CONNECTION_TYPE: CONNECTION_TYPE_TCP},
            )
            return self.async_create_entry(title="", data={})
        current_data = self.config_entry.data
        current_port_str = current_data.get(CONF_PORT, "")
        if ":" in current_port_str:
            host, port = current_port_str.rsplit(":", 1)
            current_host = host
            current_tcp_port = int(port)
        else:
            current_host = current_data.get(CONF_HOST, "")
            current_tcp_port = current_data.get(CONF_TCP_PORT, DEFAULT_TCP_PORT)
        return self.async_show_form(
            step_id="tcp_reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=current_host): str,
                    vol.Optional(CONF_TCP_PORT, default=current_tcp_port): cv.port,
                    vol.Optional(CONF_SLAVE, default=current_data.get(CONF_SLAVE, DEFAULT_SLAVE)): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=247)
                    ),
                }
            ),
        )

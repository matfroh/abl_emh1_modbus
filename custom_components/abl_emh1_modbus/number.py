"""Number platform for EVSE Modbus integration."""
from homeassistant.components.number import NumberEntity
from homeassistant.const import DEVICE_CLASS_CURRENT, ELECTRIC_CURRENT_AMPERE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType
from .const import DOMAIN, generate_set_current_command
from .modbus import EVSEModbusClient

async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info=None
):
    """Set up the EVSE current control number."""
    if discovery_info is None:
        return

    port = hass.data[DOMAIN][CONF_PORT]
    baudrate = hass.data[DOMAIN][CONF_BAUDRATE]
    
    client = EVSEModbusClient(port=port, baudrate=baudrate)
    async_add_entities([EVSECurrentControl(client)], True)

class EVSECurrentControl(NumberEntity):
    """Representation of an EVSE current control."""

    def __init__(self, client):
        """Initialize the current control."""
        self._client = client
        self._value = None

    @property
    def name(self):
        """Return the name of the current control."""
        return "EVSE Maximum Current"

    @property
    def unique_id(self):
        """Return a unique ID."""
        return "evse_max_current"

    @property
    def device_class(self):
        """Return the device class."""
        return DEVICE_CLASS_CURRENT

    @property
    def native_unit_of_measurement(self):
        """Return the unit of measurement."""
        return ELECTRIC_CURRENT_AMPERE

    @property
    def native_min_value(self):
        """Return the minimum value."""
        return 5  # Adjust based on your EVSE specifications

    @property
    def native_max_value(self):
        """Return the maximum value."""
        return 16  # Adjust based on your EVSE specifications

    @property
    def native_step(self):
        """Return the step value."""
        return 1

    @property
    def native_value(self):
        """Return the current value."""
        return self._value

    async def async_set_native_value(self, value):
        """Update the current value."""
        command = generate_set_current_command(value)
        response = await self._client.send_command("set_current", command)
        if response and response.get("status") == "OK":
            self._value = value

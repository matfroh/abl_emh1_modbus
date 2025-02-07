"""Support for ABL EMH1 Modbus sensors."""
import logging
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import UnitOfElectricCurrent
from .const import DOMAIN
from .modbus_device import ModbusASCIIDevice

_LOGGER = logging.getLogger(__name__)

# Mapping of state codes to descriptions
STATE_DESCRIPTIONS = {
    "A1": "Waiting for EV",
    "B1": "EV is asking for charging",
    "B2": "EV has the permission to charge",
    "C2": "EV is charged",
    "C3": "EV is charged, reduced current (error F16, F17)",
    "C4": "EV is charged, reduced current (imbalance F15)",
    "E0": "Outlet disabled",
    "E1": "Production test",
    "E2": "EVCC setup mode",
    "E3": "Bus idle",
    "F1": "Unintended closed contact (Welding)",
    "F2": "Internal error",
    "F3": "DC residual current detected",
    "F4": "Upstream communication timeout",
    "F5": "Lock of socket failed",
    "F6": "CS out of range",
    "F7": "State D requested by EV",
    "F8": "CP out of range",
    "F9": "Overcurrent detected",
    "F10": "Temperature outside limits",
    "F11": "Unintended opened contact",
}

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the ABL EMH1 Modbus sensors."""
    if discovery_info is None:
        return

    # Retrieve configuration from hass
    port = hass.data[DOMAIN]["port"]
    baudrate = hass.data[DOMAIN]["baudrate"]

    # Create ModbusASCIIDevice instance
    try:
        modbus_device = ModbusASCIIDevice(port=port, baudrate=baudrate)
    except Exception as e:
        _LOGGER.error(f"Failed to initialize Modbus device: {e}")
        return

    # Add sensor entities
    async_add_entities([ABLEmh1CurrentSensor(modbus_device)], True)


class ABLEmh1CurrentSensor(SensorEntity):
    """Representation of an ABL EMH1 Current Sensor."""

    def __init__(self, modbus_device):
        """Initialize the sensor."""
        self._modbus_device = modbus_device
        self._attr_name = "ABL EMH1 Current"
        self._attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
        self._attr_unique_id = "abl_emh1_current"
        self._state_data = None

    async def async_update(self):
        """Fetch new state data for the sensor."""
        try:
            registers = await self.hass.async_add_executor_job(self._modbus_device.read_current)
            if registers:
                # Decode state code
                state_code = registers[0]
                state_description = STATE_DESCRIPTIONS.get(state_code, "Unknown state")

                # Decode other registers
                values = {
                    "state_code": state_code,
                    "state_description": state_description,
                    "max_current": registers[1],  # Max current in amperes
                    "ict1": registers[2],         # Current on ICT1 in amperes
                    "ict2": registers[3],         # Current on ICT2 in amperes
                    "ict3": registers[4],         # Current on ICT3 in amperes
                }

                self._state_data = values
                self._attr_native_value = values["ict1"]  # Default to ICT1 as the primary value
            else:
                _LOGGER.warning("Failed to read registers from Modbus device.")
        except Exception as e:
            _LOGGER.error(f"Error updating sensor: {e}")

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return self._state_data

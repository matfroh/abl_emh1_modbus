"""ModbusASCIIDevice class for EV Charger communication."""
import logging
from typing import Optional
import serial
from .constants import STATE_DESCRIPTIONS

_LOGGER = logging.getLogger(__name__)

class ModbusASCIIDevice:
    """Handles communication with the Modbus ASCII device."""

    def __init__(self, port: str, slave_id: int = 1, baudrate: int = 38400):
        """Initialize the Modbus ASCII device."""
        _LOGGER.info("Initializing ModbusASCIIDevice with port %s", port)
        self.port = port
        self._state_code = None
        self.slave_id = slave_id
        try:
            self.serial = serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=8,
                parity=serial.PARITY_EVEN,
                stopbits=1,
                timeout=1
            )
            _LOGGER.info("Successfully opened serial port %s", port)
        except serial.SerialException as e:
            _LOGGER.error("Failed to open serial port %s: %s", port, str(e))
            raise

    @property
    def state_code(self) -> Optional[int]:
        """Get the current state code."""
        _LOGGER.debug("Getting state_code: 0x%02X", self._state_code if self._state_code is not None else 0)
        return self._state_code

    @state_code.setter
    def state_code(self, value: Optional[int]):
        """Set the current state code."""
        _LOGGER.debug("Setting state_code to: 0x%02X", value if value is not None else 0)
        self._state_code = value

    @property
    def state_description(self) -> str:
        """Get the current state description."""
        desc = "Unknown state" if self._state_code is None else STATE_DESCRIPTIONS.get(self._state_code, "Unknown state")
        _LOGGER.debug("Getting state description: %s", desc)
        return desc

    def update_state(self) -> bool:
        """Update the current state from the device."""
        _LOGGER.debug("Starting update_state()")
        try:
            values = self.read_current()
            _LOGGER.debug("Read values from device: %s", values)
            
            if values and 'state_code' in values:
                hex_str = values['state_code']
                _LOGGER.debug("Found state_code in values: %s", hex_str)
                
                if isinstance(hex_str, str) and hex_str.startswith('0x'):
                    self._state_code = int(hex_str, 16)
                    _LOGGER.info("Updated state code to: 0x%02X", self._state_code)
                    return True
                else:
                    _LOGGER.warning("Invalid state_code format: %s", hex_str)
            else:
                _LOGGER.warning("No state_code in values")
            return False
        except Exception as e:
            _LOGGER.exception("Error updating state: %s", str(e))
            return False
##### start of new ######

    def read_all_data(self) -> dict[str, any]:
        """Read all available data from the device."""
        _LOGGER.debug("Starting read_all_data()")
        
        try:
            # Read current values which includes state and currents
            current_data = self.read_current()
            
            if current_data is None:
                _LOGGER.error("Failed to read data from device")
                return {
                    "available": False,
                    "error": "Failed to read data from device"
                }

            # Structure the data in a way that's easy for sensors to consume
            data = {
                "available": True,
                "state": {
                    "code": current_data["state_code"],
                    "description": current_data["state_description"],
                },
                "charging": {
                    "enabled": self.is_charging_enabled(),
                    "max_current": current_data["max_current"]
                },
                "current_measurements": {
                    "ict1": current_data["ict1"],
                    "ict2": current_data["ict2"],
                    "ict3": current_data["ict3"]
                }
            }
            
            _LOGGER.debug("Read all data: %s", data)
            return data
            
        except Exception as e:
            _LOGGER.exception("Error in read_all_data: %s", str(e))
            return {
                "available": False,
                "error": str(e)
            }
###### end of new ####

    def read_current(self) -> Optional[dict]:
        """Read the EV state and current values."""
        _LOGGER.debug("Starting read_current()")
        try:
            if not self.serial or not self.serial.is_open:
                _LOGGER.error("Serial port %s is not open", self.port)
                return None

            message = bytes([self.slave_id, 0x03, 0x00, 0x33, 0x00, 0x03])
            _LOGGER.debug("Reading current with raw message: %s", message.hex().upper())

            lrc = self._calculate_lrc(message)
            formatted_message = b':' + message.hex().upper().encode() + format(lrc, '02X').encode() + b'\r\n'
            _LOGGER.debug("Sending message: %s", formatted_message)

            self.serial.write(formatted_message)
            raw_response = self.serial.readline()
            _LOGGER.debug("Raw response: %s", raw_response)

            response = raw_response.decode(errors="replace").strip()
            _LOGGER.debug("Decoded response: %s", response)

            if not response.startswith(">") or len(response) < 13:
                _LOGGER.error("Invalid or incomplete response: %s", response)
                return None

            stripped_response = response[1:]
            byte_count = int(stripped_response[4:6], 16)
            data = stripped_response[6:-2]
            lrc = stripped_response[-2:]

            computed_lrc = self._calculate_lrc(bytes.fromhex(stripped_response[:-2]))
            if format(computed_lrc, '02X') != lrc:
                _LOGGER.error("LRC mismatch: computed=%02X, received=%s", computed_lrc, lrc)
                return None

            registers = [int(data[i:i+4], 16) for i in range(0, len(data), 4)]
            _LOGGER.debug("Decoded registers: %s", registers)

            state_code_full = registers[1]
            self.state_code = state_code_full >> 8
            state_code_hex = f"0x{self.state_code:02X}"
            state_description = STATE_DESCRIPTIONS.get(self.state_code, "Unknown state")

            values = {
                "state_code": state_code_hex,
                "state_description": state_description,
                "max_current": registers[0] / 10.0,
                "ict1": registers[2] / 266.0 if len(registers) > 2 else None,
                "ict2": registers[3] / 266.0 if len(registers) > 3 else None,
                "ict3": registers[4] / 266.0 if len(registers) > 4 else None,
            }

            _LOGGER.info("Read current values: %s", values)
            return values
        except Exception as e:
            _LOGGER.exception("Error reading current: %s", str(e))
            return None

    def send_raw_command(self, command: str) -> bool:
        """Send a raw command to the device."""
        try:
            _LOGGER.debug(f"Sending raw command: {command}")
            self.serial.write(command.encode())
            response = self.serial.readline()
            _LOGGER.debug(f"Received raw response: {response}")
            return b'>01' in response
        except Exception as e:
            _LOGGER.error(f"Error sending raw command: {str(e)}")
            return False

    def enable_charging(self) -> bool:
        """Enable charging."""
        return self.send_raw_command(":01100005000102A1A1A5\r\n")

    def disable_charging(self) -> bool:
        """Disable charging."""
        return self.send_raw_command(":01100005000102E0E027\r\n")

    def _calculate_lrc(self, message: bytes) -> int:
        """Calculate LRC for Modbus ASCII message."""
        lrc = 0
        for byte in message:
            lrc = (lrc + byte) & 0xFF
        lrc = ((lrc ^ 0xFF) + 1) & 0xFF
        _LOGGER.debug(f"Calculated LRC: {format(lrc, '02X')} for message: {message.hex().upper()}")
        return lrc

    def write_current(self, current: int) -> bool:
        """Write the maximum current setting."""
        try:
            if current == 0:
                return self.send_raw_command(":0110001400010203E8ED\r\n")

            if not 5 <= current <= 16:
                _LOGGER.error(f"Current value {current}A is outside valid range (0 or 5-16A)")
                return False

            duty_cycle = int(current * 16.6)
            _LOGGER.debug(f"Converting {current}A to duty cycle: {duty_cycle} (0x{duty_cycle:04X})")

            message = bytes([
                self.slave_id, 0x10, 0x00, 0x14, 0x00, 0x01, 0x02, duty_cycle >> 8, duty_cycle & 0xFF
            ])

            lrc = self._calculate_lrc(message)
            formatted_message = b':' + message.hex().upper().encode() + format(lrc, '02X').encode() + b'\r\n'
            
            _LOGGER.debug(f"Sending formatted message: {formatted_message}")
            self.serial.write(formatted_message)
            response = self.serial.readline()
            _LOGGER.debug(f"Received raw response: {response}")

            if b'>01100014' in response:
                _LOGGER.info(f"Successfully set current to {current}A")
                return True
            else:
                _LOGGER.error(f"Unexpected response when setting current to {current}A: {response}")
                return False
        except Exception as e:
            _LOGGER.error(f"Error writing current: {str(e)}, type: {type(e)}")
            return False



    def is_charging_enabled(self) -> bool:
        """Check if charging is enabled."""
        try:
            # Directly access the instance variable for state_code
            self.update_state()
            
            if self.state_code in [0xB1, 0xB2, 0xC2]:
                _LOGGER.debug(f"Charging is enabled. State code: 0x{self.state_code:02X}")
                return True
            else:
                _LOGGER.debug(f"Charging is disabled. State code: 0x{self.state_code:02X}")
                return False
        except Exception as e:
            _LOGGER.error(f"Error checking charging state: {e}")
            return False

    def __del__(self):
        """Clean up serial connection."""
        try:
            if hasattr(self, 'serial') and self.serial.is_open:
                self.serial.close()
                _LOGGER.info(f"Closed serial port {self.port}")
        except Exception as e:
            _LOGGER.error(f"Error closing serial port: {str(e)}")

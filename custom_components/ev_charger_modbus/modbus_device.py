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
        self.port = port
        self.state_code = None  # Initialize state_code as None
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
            _LOGGER.info(f"Successfully opened serial port {port}")
        except serial.SerialException as e:
            _LOGGER.error(f"Failed to open serial port {port}: {str(e)}")
            raise


    @property
    def state_code(self) -> Optional[int]:
        """Get the current state code."""
        return self._state_code

    @state_code.setter
    def state_code(self, value: Optional[int]):
        """Set the current state code."""
        self._state_code = value


    @property
    def state_description(self) -> str:
        """Get the current state description."""
        if self._state_code is None:
            return "Unknown state"
        return STATE_DESCRIPTIONS.get(self._state_code, "Unknown state")

    def update_state(self) -> bool:
        """Update the current state from the device."""
        try:
            values = self.read_current()
            if values and 'state_code' in values:
                # Convert the hex string to int
                hex_str = values['state_code']
                if isinstance(hex_str, str) and hex_str.startswith('0x'):
                    self._state_code = int(hex_str, 16)
                    _LOGGER.debug(f"Updated state code to: 0x{self._state_code:02X}")
                    return True
            return False
        except Exception as e:
            _LOGGER.error(f"Error updating state: {str(e)}")
            return False


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

    def read_current(self) -> Optional[dict]:
        """Read the EV state and current values."""
        try:
            if not self.serial or not self.serial.is_open:
                _LOGGER.error(f"Serial port {self.port} is not open")
                return None

            message = bytes([self.slave_id, 0x03, 0x00, 0x33, 0x00, 0x03])
            _LOGGER.debug(f"Reading current with raw message: {message.hex().upper()}")

            lrc = self._calculate_lrc(message)
            formatted_message = b':' + message.hex().upper().encode() + format(lrc, '02X').encode() + b'\r\n'
            _LOGGER.debug(f"Sending message: {formatted_message}")
            # Log the raw request payload
            _LOGGER.debug(f"Raw request payload: {formatted_message.hex()}")

            self.serial.write(formatted_message)
            raw_response = self.serial.readline()
            # Log the raw response payload
            _LOGGER.debug(f"Raw response payload: {raw_response.hex()}")

            
            response = raw_response.decode(errors="replace").strip()
            _LOGGER.debug(f"Received raw response: {raw_response!r} (decoded: {response})")

            if not response.startswith(">") or len(response) < 13:
                _LOGGER.error(f"Invalid or incomplete response: {response}")
                return None

            stripped_response = response[1:]
            byte_count = int(stripped_response[4:6], 16)
            data = stripped_response[6:-2]
            lrc = stripped_response[-2:]

            computed_lrc = self._calculate_lrc(bytes.fromhex(stripped_response[:-2]))
            if format(computed_lrc, '02X') != lrc:
                _LOGGER.error(f"LRC mismatch: computed={computed_lrc:02X}, received={lrc}")
                return None

            if len(data) < byte_count * 2:
                _LOGGER.error(f"Data length mismatch: expected {byte_count * 2}, got {len(data)}")
                return None

            registers = [int(data[i:i+4], 16) for i in range(0, len(data), 4)]
            _LOGGER.debug(f"Decoded registers: {registers}")

            # Ensure the state code is correctly extracted and mapped
            state_code_full = registers[1]  # Get the full 16-bit register value (e.g., 0xC200)
            self.state_code = state_code_full >> 8  # Extract the high byte, i.e., 0xC2 from 0xC200
            state_code_hex = f"0x{self.state_code:02X}"  # Format it as hex
            state_description = STATE_DESCRIPTIONS.get(self.state_code, "Unknown state")

            values = {
                "state_code": state_code_hex,
                "state_description": state_description,
                "max_current": registers[0] / 10.0,
                "ict1": registers[2] / 10.0 if len(registers) > 2 else None,
                "ict2": registers[3] / 10.0 if len(registers) > 3 else None,
                "ict3": registers[4] / 10.0 if len(registers) > 4 else None,
            }

            _LOGGER.info(f"Read current values: {values}")
            return values
        except Exception as e:
            _LOGGER.error(f"Error reading current: {e}, type: {type(e)}")
            return None

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

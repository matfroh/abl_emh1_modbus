# custom_components/ev_charger_modbus/modbus_device.py
"""ModbusASCIIDevice class for EV Charger communication."""
import logging
from typing import Optional
import serial

_LOGGER = logging.getLogger(__name__)

class ModbusASCIIDevice:
    """Handles communication with the Modbus ASCII device."""
    
    def __init__(self, port: str, slave_id: int = 1, baudrate: int = 38400):
        """Initialize the Modbus ASCII device."""
        self.port = port
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
                # Special command for 0 amperes
                return self.send_raw_command(":0110001400010203E8ED\r\n")
            
            if not 5 <= current <= 16:
                _LOGGER.error(f"Current value {current}A is outside valid range (0 or 5-16A)")
                return False
            
            # Convert current to duty cycle value (current * 16.6)
            duty_cycle = int(current * 16.6)
            _LOGGER.debug(f"Converting {current}A to duty cycle: {duty_cycle} (0x{duty_cycle:04X})")
            
            # Construct message bytes
            message = bytes([
                self.slave_id,     # Slave ID (01)
                0x10,              # Function code (16 in decimal)
                0x00, 0x14,        # Register address (0x0014)
                0x00, 0x01,        # Number of registers (1)
                0x02,              # Byte count (2)
                duty_cycle >> 8,   # High byte of duty cycle
                duty_cycle & 0xFF  # Low byte of duty cycle
            ])
            
            # Calculate LRC and format message
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

    def read_current(self) -> Optional[list]:
        """Read the EV state and current values."""
        try:
            # Command to read registers
            message = bytes([self.slave_id, 0x03, 0x00, 0x33, 0x00, 0x03])
            _LOGGER.debug(f"Reading current with raw message: {message.hex().upper()}")
        
            # Calculate LRC and format message
            lrc = self._calculate_lrc(message)
            formatted_message = b':' + message.hex().upper().encode() + format(lrc, '02X').encode() + b'\r\n'
            _LOGGER.debug(f"Sending message: {formatted_message}")
        
            self.serial.write(formatted_message)
            response = self.serial.readline()
        
            _LOGGER.debug(f"Received raw response: {response}")
        
            # Validate and parse the response
            if not response or len(response) < 13:  # Minimum valid response length
                _LOGGER.error(f"Invalid or incomplete response received: {response}")
                return None
        
            try:
                # Ensure the response starts with ">01"
                if not response.startswith(b'>01'):
                    _LOGGER.error(f"Unexpected response format: {response}")
                    return None
            
                # Extract and parse register values
                registers = [
                    int(response[6:8], 16),  # State code
                    int(response[8:12], 16),  # Max current
                    int(response[12:16], 16),  # ICT1
                    int(response[16:20], 16),  # ICT2
                    int(response[20:24], 16),  # ICT3
                ]
                _LOGGER.debug(f"Parsed registers: {registers}")
                return registers
        
            except (IndexError, ValueError) as e:
                _LOGGER.error(f"Failed to parse response: {response}, Error: {e}")
                return None
        except Exception as e:
            _LOGGER.error(f"Error reading current: {e}")
            return None
    
    def is_charging_enabled(self) -> bool:
        """Check if charging is enabled."""
        try:
            # Read relevant register(s) to determine the charging state
            # For example, use the state register (registers[0]) or another value
            registers = self.read_current()  # Reuse the read_current logic
            if not registers:
                _LOGGER.error("Failed to read registers for charging state.")
                return False
        
            state_code = registers[0]
            _LOGGER.debug(f"State code read: {state_code}")
        
            # Example: Return True for states indicating active charging
            return state_code in ["B1", "B2", "C2"]
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
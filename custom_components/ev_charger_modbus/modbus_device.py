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
            if not 5 <= current <= 16:
                _LOGGER.error(f"Current value {current}A is outside valid range (5-16A)")
                return False
                
            # Convert current to duty cycle value (current * 16.6)
            duty_cycle = int(current * 16.6)  # This will give us the correct value (e.g., 166 for 10A)
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

    def read_current(self) -> Optional[float]:
        """Read the EV current."""
        try:
            # Command to read current (0x03 function, register 0x0033, 3 registers)
            message = bytes([self.slave_id, 0x03, 0x00, 0x33, 0x00, 0x03])
            _LOGGER.debug(f"Reading current with raw message: {message.hex().upper()}")
            
            # Calculate LRC and format message
            lrc = self._calculate_lrc(message)
            formatted_message = b':' + message.hex().upper().encode() + format(lrc, '02X').encode() + b'\r\n'
            
            _LOGGER.debug(f"Sending message: {formatted_message}")
            
            self.serial.write(formatted_message)
            response = self.serial.readline()
            
            _LOGGER.debug(f"Received raw response: {response}")
            
            if response:
                try:
                    # Response format: >0103063380C30A0A00EC
                    # Current value is at position 12-13 (0A in the example = 10A)
                    current_hex = response[12:14]
                    current = int(current_hex, 16)
                    _LOGGER.debug(f"Parsed current value: {current}A from hex: {current_hex}")
                    return current
                except (IndexError, ValueError) as e:
                    _LOGGER.error(f"Failed to parse response: {response}, Error: {str(e)}")
                    return None
            else:
                _LOGGER.error("No response received from device")
                return None
                
        except Exception as e:
            _LOGGER.error(f"Error reading current: {str(e)}, type: {type(e)}")
            return None

    def __del__(self):
        """Clean up serial connection."""
        try:
            if hasattr(self, 'serial') and self.serial.is_open:
                self.serial.close()
                _LOGGER.info(f"Closed serial port {self.port}")
        except Exception as e:
            _LOGGER.error(f"Error closing serial port: {str(e)}")

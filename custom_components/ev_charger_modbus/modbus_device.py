import logging
from typing import Optional
import serial
from .constants import STATE_DESCRIPTIONS
from math import ceil

_LOGGER = logging.getLogger(__name__)

class ModbusASCIIDevice:
    """Handles communication with the Modbus ASCII device."""

    def __init__(self, port: str, slave_id: int = 1, baudrate: int = 19200, max_current: int = 16):
        """Initialize the Modbus ASCII device."""
        _LOGGER.info("Initializing ModbusASCIIDevice with port %s", port)
        self.port = port
        self._state_code = None
        self.slave_id = slave_id
        self.max_current = max_current
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

    def _read_response(self) -> Optional[str]:
        """Read and clean response from serial port, handling garbage characters."""
        try:
            # Read with a reasonable timeout
            raw_response = self.serial.readline()
            if not raw_response:
                return None
                
            _LOGGER.debug("Raw response bytes: %s", raw_response)
            
            # Decode with error handling
            response = raw_response.decode(errors="replace").strip()
            _LOGGER.debug("Initial decoded response: %s", response)
            
            # Find the actual start of the Modbus ASCII response (starts with '>')
            start_pos = response.find('>')
            if start_pos == -1:
                _LOGGER.error("No valid Modbus ASCII start marker found in: %s", response)
                # Clear buffer on error to prevent corruption
                self._clear_serial_buffer()
                return None
                
            # Extract the clean response from the start marker
            clean_response = response[start_pos:]
            _LOGGER.debug("Cleaned response: %s", clean_response)
            
            return clean_response
            
        except Exception as e:
            _LOGGER.exception("Error reading response: %s", e)
            # Clear buffer on error
            self._clear_serial_buffer()
            return None

    def _clear_serial_buffer(self):
        """Clear any remaining data in the serial buffer."""
        try:
            if self.serial and self.serial.is_open:
                # Clear input buffer to remove any stale data
                self.serial.reset_input_buffer()
                _LOGGER.debug("Cleared serial input buffer")
        except Exception as e:
            _LOGGER.warning("Failed to clear serial buffer: %s", e)

    # Helper function to create properly formatted Modbus ASCII commands with dynamic slave_id
    def _create_raw_command(self, command_hex: str) -> str:
        """
        Create a raw Modbus ASCII command with the proper slave_id.
        
        Args:
            command_hex: The hex command string without slave_id and without ':' prefix and '\r\n' suffix
            
        Returns:
            Properly formatted command string with slave_id, LRC, and framing
        """
        # Format slave_id as two hex digits
        slave_id_hex = f"{self.slave_id:02X}"
        
        # Replace the first two characters (usually "01") with the proper slave_id
        full_command = slave_id_hex + command_hex
        
        # Calculate LRC for the complete command
        message_bytes = bytes.fromhex(full_command)
        lrc = self._calculate_lrc(message_bytes)
        
        # Format the complete message with ':' prefix, command, LRC, and CRLF
        formatted_message = f":{full_command}{format(lrc, '02X')}\r\n"
        
        _LOGGER.debug(f"Created raw command: {formatted_message}")
        return formatted_message

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

    def read_serial_number(self) -> Optional[str]:
        """Read the device serial number."""
        _LOGGER.debug("Starting read_serial_number()")
        try:
            if not self.serial or not self.serial.is_open:
                _LOGGER.error("Serial port %s is not open", self.port)
                return None

            # Command to read serial number (0x0050)
            message = bytes([self.slave_id, 0x03, 0x00, 0x50, 0x00, 0x08])
            _LOGGER.debug("Reading serial number with raw message: %s", message.hex().upper())

            lrc = self._calculate_lrc(message)
            formatted_message = b':' + message.hex().upper().encode() + format(lrc, '02X').encode() + b'\r\n'
            _LOGGER.debug("Sending message: %s", formatted_message)

            self.serial.write(formatted_message)
            
            # Use the new helper method to read and clean the response
            response = self._read_response()
            if not response or len(response) < 13:
                _LOGGER.error("Invalid or incomplete response: %s", response)
                return None

            # Extract the serial number from the response
            # Remove the '>' prefix and the CRLF suffix
            data = response[7:-2]  # Skip >0103xx header and LRC at end
            serial_number = bytes.fromhex(data).decode('ascii')
            _LOGGER.debug("Decoded serial number: %s", serial_number)

            return serial_number

        except Exception as e:
            _LOGGER.exception("Error reading serial number: %s", str(e))
            return None

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

    def adjust_current_value(self, value):
        """Return the raw current value without artificial rounding."""
        if value is None or value > 80:
            return 0
        return value  # Return the actual value, don't round it up

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
            
            # Use the new helper method to read and clean the response
            response = self._read_response()
            if not response or len(response) < 13:
                _LOGGER.error("Invalid or incomplete response: %s", response)
                return None
            
            # Remove the leading ">"
            stripped_response = response[1:]
            
            # Verify LRC
            lrc_received = stripped_response[-2:]
            computed_lrc = self._calculate_lrc(bytes.fromhex(stripped_response[:-2]))
            _LOGGER.debug("Calculated LRC: %s for message: %s", format(computed_lrc, '02X'), stripped_response[:-2])
            if format(computed_lrc, '02X') != lrc_received:
                _LOGGER.error("LRC mismatch: computed=%02X, received=%s", computed_lrc, lrc_received)
                return None
            
            # Parse the hex data
            # Format: 0103063380C20E0E0E57
            # 01 - Device ID
            # 03 - Function code
            # 06 - Byte count
            # 3380 - First register (status/max current)
            # C2 - State code
            # 0E - ICT1 current (14A)
            # 0E - ICT2 current (14A)
            # 0E - ICT3 current (14A)
            # 57 - LRC
            
            # Extract the data portion after byte count
            data_part = stripped_response[6:-2]  # '3380C20E0E0E'
            
            # Extract status register (first 4 chars)
            status_register = int(data_part[0:4], 16)  # '3380' -> 13184
            
            # Extract state code (next 2 chars)
            self.state_code = int(data_part[4:6], 16)  # 'C2' -> 194 (0xC2)
            state_code_hex = f"0x{self.state_code:02X}"
            state_description = STATE_DESCRIPTIONS.get(self.state_code, "Unknown state")
            
            # Extract current values for each phase (next 6 chars, 2 chars each)
            ict1 = int(data_part[6:8], 16) if len(data_part) >= 8 else None  # '0E' -> 14
            ict2 = int(data_part[8:10], 16) if len(data_part) >= 10 else None  # '0E' -> 14
            ict3 = int(data_part[10:12], 16) if len(data_part) >= 12 else None  # '0E' -> 14
            
            values = {
                "state_code": state_code_hex,
                "state_description": state_description,
                "max_current": status_register / 10.0,  # Adjust if needed based on your protocol
                "ict1": self.adjust_current_value(ict1) if ict1 is not None else None,
                "ict2": self.adjust_current_value(ict2) if ict2 is not None else None,
                "ict3": self.adjust_current_value(ict3) if ict3 is not None else None,
            }
            _LOGGER.info("Read current values: %s", values)
            return values
        except Exception as e:
            _LOGGER.exception("Error reading current: %s", str(e))
            return None

    def send_raw_command(self, command: str) -> Optional[str]:
        """Send a raw command to the device."""
        try:
            _LOGGER.debug(f"Sending raw command: {command}")
            self.serial.write(command.encode())
            
            # Use the new helper method to read and clean the response
            response = self._read_response()
            if response:
                _LOGGER.debug(f"Received decoded response: {response}")
                # Updated to check for dynamic slave_id instead of hardcoded "01"
                expected_prefix = f">{self.slave_id:02X}"
                if response.startswith(expected_prefix):
                    return response  # Return the response
                else:
                    _LOGGER.warning(f"Unexpected response: {response}, expected prefix: {expected_prefix}")
                    return None  # Unexpected response
            else:
                _LOGGER.warning("No response received from serial port.")
                return None  # No response
        except Exception as e:
            _LOGGER.error(f"Error sending raw command: {str(e)}")
            return None  # Error
        
    def enable_charging(self) -> bool:
        """Enable charging."""
        # Original: ":01100005000102A1A1A5\r\n"
        return self.send_raw_command(self._create_raw_command("100005000102A1A1"))

    def disable_charging(self) -> bool:
        """Disable charging."""
        # Original: ":01100005000102E0E027\r\n"
        return self.send_raw_command(self._create_raw_command("100005000102E0E0"))

    def _calculate_lrc(self, message: bytes) -> int:
        """Calculate LRC for Modbus ASCII message."""
        lrc = 0
        for byte in message:
            lrc = (lrc + byte) & 0xFF
        lrc = ((lrc ^ 0xFF) + 1) & 0xFF
        _LOGGER.debug(f"Calculated LRC: {format(lrc, '02X')} for message: {message.hex().upper()}")
        return lrc

    def write_current(self, current: int) -> bool:
        """Write charging current."""
        if not 5 <= current <= self.max_current:  # Use instance variable instead of hardcoded value
            _LOGGER.error(f"Current must be between 5 and {self.max_current}")
            return False

        try:
            if current == 0:
                # Original: ":0110001400010203E8ED\r\n"
                return self.send_raw_command(self._create_raw_command("10001400010203E8"))

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

            # Updated to check for dynamic slave_id instead of hardcoded "01"
            expected_prefix = f">{self.slave_id:02X}100014".encode()
            if expected_prefix in response:
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
 
    def read_duty_cycle(self) -> Optional[float]:
        """Request and parse the duty cycle from the device."""
        _LOGGER.debug("Starting read_duty_cycle()")
        try:
            # Original: ":0103002E0005C9\r\n"
            response = self.send_raw_command(self._create_raw_command("03002E0005"))
            if not response:
                _LOGGER.error("No response received for duty cycle request")
                return None
    
            # Extract the data part after the header
            # Updated to use dynamic slave_id instead of hardcoded "01"
            expected_header = f">{self.slave_id:02X}030A2E"
            header_pos = response.find(expected_header)
            if header_pos == -1:
                _LOGGER.error(f"Invalid response format: header '{expected_header}' not found")
                return None
    
            data_start = header_pos + len(expected_header)
            data_part = response[data_start:]
            if len(data_part) < 4:
                _LOGGER.error("Invalid response format: data too short")
                return None
    
            # Extract the duty cycle value
            duty_cycle_hex = data_part[4:8]  # Corrected byte extraction
            duty_cycle = int(duty_cycle_hex, 16) / 100.0
    
            _LOGGER.info(f"Duty cycle retrieved: {duty_cycle}%")
            _LOGGER.debug(f"Duty cycle hex: {duty_cycle_hex}")
            return duty_cycle
    
        except Exception as e:
            _LOGGER.error(f"Error reading duty cycle: {str(e)}")
            return None
            
    def calculate_consumption_with_duty_cycle(self) -> Optional[float]:
        """Calculate simplified power consumption including duty cycle adjustment."""
        _LOGGER.debug("Starting calculate_consumption_with_duty_cycle()")
        try:
            # Read current values
            data = self.read_current()
            if not data:
                _LOGGER.error("Failed to read current values for power calculation")
                return None

            # Replace None with 0 and sum ICT values
            ict1 = data.get('ict1', 0)
            ict2 = data.get('ict2', 0)
            ict3 = data.get('ict3', 0)
            total_current = ict1 + ict2 + ict3

            # Retrieve duty cycle
            duty_cycle = self.read_duty_cycle()
            if duty_cycle is None:
                _LOGGER.error("Failed to retrieve duty cycle")
                return None

            # Calculate simplified power
            voltage = 230  # Volts
            power = total_current * voltage

            # Apply duty cycle adjustment - ignoring this for now.
            adjusted_power = power  # * (duty_cycle / 100.0)

            _LOGGER.info(f"Calculated simplified power consumption (adjusted for duty cycle): {adjusted_power:.2f} Watts")
            _LOGGER.debug(f"Power: {power:.2f} Watts, Duty Cycle: {duty_cycle:.2f}%")
            return adjusted_power

        except Exception as e:
            _LOGGER.error(f"Error calculating power consumption: {str(e)}")
            return None
        
    def wake_up_device(self) -> bool:
        """Send wake-up sequence to the device."""
        _LOGGER.info("Attempting to wake up device...")
        
        try:
            if not self.serial or not self.serial.is_open:
                _LOGGER.error("Serial port %s is not open", self.port)
                return False
            
            # Send wake-up messages in sequence
            wake_up_messages = [":000300010002FA\r\n", ":010300010002F9\r\n", ":010300010002F9\r\n"]
            
            for idx, message in enumerate(wake_up_messages):
                _LOGGER.debug("Sending wake-up message %d: %s", idx + 1, message.strip())
                self.serial.write(message.encode())
                
                # Small delay between messages
                import time
                time.sleep(0.5)
                
                # Read and discard any response
                response = self.serial.readline()
                _LOGGER.debug("Response to wake-up message %d: %s", idx + 1, response)
            
            _LOGGER.info("Wake-up sequence completed")
            return True
            
        except Exception as e:
            _LOGGER.exception("Error sending wake-up sequence: %s", str(e))
            return False

    def read_firmware_info(self) -> Optional[dict]:
        """Read the firmware version and hardware info."""
        _LOGGER.debug("Starting read_firmware_info()")
        try:
            if not self.serial or not self.serial.is_open:
                _LOGGER.error("Serial port %s is not open", self.port)
                return None
                
            # Format the Modbus ASCII message for reading registers 0x0001-0x0002
            device_id = format(self.slave_id, '02X')
            function_code = "03"  # Read registers
            register_address = "0001"  # Starting address
            register_count = "0002"  # Number of registers to read
            
            # Build message without LRC
            message_without_lrc = device_id + function_code + register_address + register_count
            
            # Calculate LRC
            lrc = self._calculate_lrc_ascii(message_without_lrc)
            
            # Complete message
            formatted_message = f":{message_without_lrc}{lrc}\r\n".encode()
            
            _LOGGER.debug("Sending message: %s", formatted_message)
            self.serial.write(formatted_message)
            
            # Read response using the new helper method
            response = self._read_response()
            if not response or len(response) < 13:
                _LOGGER.error("Invalid or incomplete response: %s", response)
                return None
                
            # Extract data part (remove '>' prefix and LRC at the end)
            data = response[1:-2]
            
            # Verify response format (should be like "01030401011237")
            if not data.startswith(device_id + "0304"):
                _LOGGER.error("Unexpected response format: %s", response)
                return None
                
            # Extract the register values (bytes 5-8 and 9-12)
            reg1 = int(data[6:10], 16)  # First register value
            reg2 = int(data[10:14], 16) if len(data) >= 14 else 0  # Second register value
            
            # Extract firmware version (based on documentation)
            firmware_major = (reg1 >> 8) & 0xFF  # Should be 1
            firmware_minor = reg1 & 0xFF         # Should be 65 (ASCII 'A')

            
            # Extract hardware version from second register
            hardware_code = (reg2 >> 6) & 0x3
            
            # Map hardware code to PCBA version
            hardware_versions = {
                0: "PCBA 141215",
                1: "PCBA 160307",
                2: "PCBA 170725",
                3: "Not Used"
            }
            
            hardware_version = hardware_versions.get(hardware_code, "Unknown")
            firmware_version = f"V{firmware_major}.{firmware_minor//16}{firmware_minor%16}"
            
            _LOGGER.info(
                "Firmware version: %s, Hardware version: %s (code: %d)",
                firmware_version, hardware_version, hardware_code
            )
            
            return {
                "firmware_version": firmware_version,
                "hardware_version": hardware_version,
                "raw_registers": [reg1, reg2]
            }
        except Exception as e:
            _LOGGER.exception("Error reading firmware info: %s", str(e))
            return None
    
    def _calculate_lrc_ascii(self, message_hex):
        """Calculate LRC for ASCII Modbus message."""
        # Convert hex string to bytes
        message_bytes = bytes.fromhex(message_hex)
        
        # Calculate LRC (sum all bytes and take two's complement)
        lrc = (-sum(message_bytes)) & 0xFF
        
        # Return as hex string
        return format(lrc, '02X')

    def read_serial_number(self) -> Optional[str]:
        """Read the device serial number."""
        _LOGGER.debug("Starting read_serial_number()")
        try:
            if not self.serial or not self.serial.is_open:
                _LOGGER.error("Serial port %s is not open", self.port)
                return None
                
            # Format the Modbus ASCII message for reading 8 registers starting at 0x0050
            device_id = format(self.slave_id, '02X')
            function_code = "03"  # Read registers
            register_address = "0050"  # Starting address
            register_count = "0008"  # Number of registers to read
            
            # Build message without LRC
            message_without_lrc = device_id + function_code + register_address + register_count
            
            # Calculate LRC
            lrc = self._calculate_lrc_ascii(message_without_lrc)
            
            # Complete message
            formatted_message = f":{message_without_lrc}{lrc}\r\n".encode()
            
            _LOGGER.debug("Sending message: %s", formatted_message)
            self.serial.write(formatted_message)
            
            # Read response using the new helper method
            response = self._read_response()
            if not response or len(response) < 21:  # Minimum expected length for valid response
                _LOGGER.error("Invalid or incomplete response: %s", response)
                return None
                
            # Extract data part (remove '>' prefix and LRC at the end)
            data = response[1:-2]
            
            # Verify response format (should be like "0103105000...")
            if not data.startswith(device_id + "031050"):
                _LOGGER.error("Unexpected response format: %s", response)
                return None
                
            # Extract the 16 bytes of serial number data (8 registers = 16 hex characters)
            serial_data = data[8:]  # Skip device_id + "031050"
            
            # Check if all registers are 0xFFFF (no serial number)
            if all(serial_data[i:i+4] == "FFFF" for i in range(0, len(serial_data), 4)):
                _LOGGER.debug("No serial number available (all registers are 0xFFFF)")
                return None
                
            # Convert hex values to ASCII characters
            try:
                # Based on documentation example, format is like: "2W22xy01234567"
                serial_bytes = bytes.fromhex(serial_data)
                serial_number = serial_bytes.decode('ascii', errors='replace')
                
                # Remove any null bytes or non-printable characters
                serial_number = ''.join(char for char in serial_number if char.isprintable())
                
                _LOGGER.debug("Decoded serial number: %s", serial_number)
                return serial_number if serial_number else None
            except Exception as e:
                _LOGGER.error("Error decoding serial number data: %s", str(e))
                return None
        except Exception as e:
            _LOGGER.exception("Error reading serial number: %s", str(e))
            return None
            
            
    def __del__(self):
        """Clean up serial connection."""
        try:
            if hasattr(self, 'serial') and self.serial.is_open:
                self.serial.close()
                _LOGGER.info(f"Closed serial port {self.port}")
        except Exception as e:
            _LOGGER.error(f"Error closing serial port: {str(e)}")
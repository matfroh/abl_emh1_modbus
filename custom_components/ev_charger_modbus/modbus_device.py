import logging
import re
from typing import Optional, Tuple
import asyncio
import serial_asyncio
from .constants import STATE_DESCRIPTIONS
from math import ceil

_LOGGER = logging.getLogger(__name__)

# --- Transport Layer Abstraction ---

class ModbusASCIITransport:
    """Abstract base class for serial and TCP communication."""

    def __init__(self, port_or_host: str, **kwargs):
        """Initialize the transport."""
        self.port_or_host = port_or_host
        self.is_connected = False
        self.socket = None
        self.serial = None

    async def open(self):
        """Opens the connection."""
        raise NotImplementedError

    def close(self):
        """Closes the connection."""
        raise NotImplementedError

    async def write(self, data: bytes):
        """Writes data to the connection."""
        raise NotImplementedError

    async def readline(self) -> bytes:
        """Reads a line from the connection."""
        raise NotImplementedError

    @property
    def is_open(self) -> bool:
        """Returns whether the connection is open."""
        return self.is_connected

class SerialTransport(ModbusASCIITransport):
    """Implementation for local serial connection (RS485)."""
    
    def __init__(self, port: str, baudrate: int):
        super().__init__(port, baudrate=baudrate)
        self.baudrate = baudrate
        self.reader = None
        self.writer = None

    async def open(self):
        try:
            self.reader, self.writer = await serial_asyncio.open_serial_connection(
                url=self.port_or_host,
                baudrate=self.baudrate,
                bytesize=8,
                parity='E',
                stopbits=1,
                timeout=1
            )
            self.is_connected = True
            _LOGGER.info("Successfully opened serial port %s", self.port_or_host)
        except Exception as e:
            self.is_connected = False
            _LOGGER.error("Failed to open serial port %s: %s", self.port_or_host, str(e))
            raise

    def close(self):
        if self.writer and not self.writer.is_closing():
            self.writer.close()
            self.is_connected = False
            _LOGGER.info("Closed serial port %s", self.port_or_host)

    async def write(self, data: bytes):
        if not self.writer or not self.is_connected:
            raise ConnectionError("Serial port not open.")
        self.writer.write(data)
        await self.writer.drain()

    async def readline(self) -> bytes:
        if not self.reader or not self.is_connected:
            return b''
        try:
            # Read until we get \r\n (Modbus ASCII terminator)
            line = await asyncio.wait_for(
                self.reader.readuntil(b'\r\n'), 
                timeout=2.0
            )
            _LOGGER.debug("Serial read received %d bytes: %s", len(line), line)
            return line
        except asyncio.TimeoutError:
            _LOGGER.debug("Serial read timeout - no response within 2 seconds")
            return b''
        except asyncio.IncompleteReadError as e:
            _LOGGER.warning("Incomplete read: got %d bytes: %s", len(e.partial), e.partial)
            return e.partial if e.partial else b''
        except Exception as e:
            _LOGGER.error("Error reading from serial: %s", e)
            return b''

    async def reset_input_buffer(self):
        if self.reader:
            # A way to clear internal buffer for asyncio reader
            self.reader.feed_data(b'') 

    @property
    def is_open(self) -> bool:
        return self.is_connected and self.writer and not self.writer.is_closing()


class TCPTransport(ModbusASCIITransport):
    """Implementation for Modbus TCP (ASCII over Socket), optimized for EW11."""
    
    def __init__(self, host: str, port: int):
        super().__init__(f"{host}:{port}")
        self.host = host
        self.port = port
        self.timeout = 5.0 # Increased timeout for wallbox delay
        self.reader = None
        self.writer = None

    async def open(self):
        try:
            _LOGGER.info("Connecting to TCP device at %s:%d (Timeout: %s)", self.host, self.port, self.timeout)
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
            self.is_connected = True
            _LOGGER.info("Successfully connected to TCP device.")
        except Exception as e:
            self.is_connected = False
            _LOGGER.error("Failed to connect to TCP device %s:%d: %s", self.host, self.port, str(e))
            raise 

    def close(self):
        if self.writer and not self.writer.is_closing():
            self.writer.close()
            self.is_connected = False
            _LOGGER.info("Closed TCP connection to %s:%d", self.host, self.port)

    async def write(self, data: bytes):
        if not self.is_connected:
            raise ConnectionError("TCP connection not open.")
        self.writer.write(data)
        await self.writer.drain()

    async def readline(self) -> bytes:
        """Reads data line by line from the socket, optimized for EW11 gateway delay."""
        try:
            # Read until CRLF or timeout
            buffer = await asyncio.wait_for(self.reader.readuntil(b'\r\n'), timeout=1.0)

            # Clean the buffer to start with '>' or ':'
            if buffer:
                start_index_gt = buffer.find(b'>')
                start_index_col = buffer.find(b':')
                
                valid_start_index = -1
                
                if start_index_gt != -1 and start_index_col != -1:
                    valid_start_index = min(start_index_gt, start_index_col)
                elif start_index_gt != -1:
                    valid_start_index = start_index_gt
                elif start_index_col != -1:
                    valid_start_index = start_index_col
                    
                if valid_start_index > 0:
                    _LOGGER.debug(f"Discarding {valid_start_index} leading garbage bytes.")
                    buffer = buffer[valid_start_index:]
                elif valid_start_index == -1:
                     return b'' 

            return buffer
        except asyncio.TimeoutError:
            _LOGGER.debug("Socket read timeout reached (end of data stream or incomplete frame).")
            return b''
        except Exception as e:
            _LOGGER.error(f"Error reading from TCP socket: {e}")
            return b''

    async def reset_input_buffer(self):
        """With a TCP socket connection, the input buffer is 'cleared' by reading until timeout."""
        pass 


# --- Main Class ModbusASCIIDevice ---

class ModbusASCIIDevice:
    """Handles communication with the Modbus ASCII device (Serial or TCP)."""

    def __init__(self, port: str, slave_id: int = 1, baudrate: int = 19200, max_current: int = 16):
        """Initialize the Modbus ASCII device."""
        self._state_code = None
        self.slave_id = slave_id
        self.max_current = max_current
        self.port = port
        self.baudrate = baudrate
        self.transport: ModbusASCIITransport = None
        self._lock = asyncio.Lock()

    async def connect(self):
        """Connects to the device and initializes the transport."""
        # Determine connection type (Serial vs. TCP)
        if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+$", self.port):
            # TCP connection (e.g., 192.168.1.10:502)
            host, tcp_port = self.port.split(":")
            self.transport = TCPTransport(host, int(tcp_port))
            _LOGGER.info("Initializing ModbusASCIIDevice with TCP host %s:%s", host, tcp_port)
        elif self.port.startswith("/dev/") or self.port.startswith("COM"):
            # Serial connection (e.g., /dev/ttyUSB0 or COM3)
            self.transport = SerialTransport(self.port, self.baudrate)
            _LOGGER.info("Initializing ModbusASCIIDevice with serial port %s", self.port)
        else:
            _LOGGER.error("Invalid port format: %s. Expected /dev/tty... or IP:PORT", self.port)
            raise ValueError(f"Invalid port format: {self.port}")

        # Open the connection on startup
        try:
            await self.transport.open()
        except Exception as e:
            _LOGGER.error("Failed to open communication transport: %s", str(e))
            raise

    async def _read_response(self) -> Optional[str]:
        """Read and clean response from serial/tcp port, handling garbage characters."""
        try:
            raw_response = await self.transport.readline()
            if not raw_response:
                return None
                
            _LOGGER.debug("Raw response bytes: %s", raw_response)
            
            # Decode with error handling
            response = raw_response.decode(errors="replace").strip() 
            _LOGGER.debug("Initial decoded response: %s", response)
            
            # Find the actual start of the Modbus ASCII response (starts with '>' or ':')
            start_pos_gt = response.find('>')
            start_pos_col = response.find(':')
            
            start_pos = -1
            if start_pos_gt != -1 and start_pos_col != -1:
                start_pos = min(start_pos_gt, start_pos_col)
            elif start_pos_gt != -1:
                start_pos = start_pos_gt
            elif start_pos_col != -1:
                start_pos = start_pos_col

            if start_pos == -1:
                _LOGGER.error("No valid Modbus ASCII start marker found in: %s", response)
                await self._clear_input_buffer() 
                return None
                
            # Extract the clean response from the start marker
            clean_response = response[start_pos:]
            _LOGGER.debug("Cleaned response: %s", clean_response)
            
            return clean_response
            
        except Exception as e:
            _LOGGER.exception("Error reading response: %s", e)
            await self._clear_input_buffer()
            return None

    async def _clear_input_buffer(self):
        """Clear any remaining data in the input buffer (Serial/TCP)."""
        try:
            if isinstance(self.transport, SerialTransport):
                await self.transport.reset_input_buffer()
                _LOGGER.debug("Cleared serial input buffer")
            elif isinstance(self.transport, TCPTransport):
                await self.transport.readline() 
                _LOGGER.debug("TCP input buffer reset attempt (read until timeout)")
        except Exception as e:
            _LOGGER.warning("Failed to clear input buffer: %s", str(e))

    def _create_raw_command(self, command_hex: str) -> str:
        """
        Create a raw Modbus ASCII command with the proper slave_id.
        """
        slave_id_hex = f"{self.slave_id:02X}"
        full_command = slave_id_hex + command_hex
        message_bytes = bytes.fromhex(full_command)
        lrc = self._calculate_lrc(message_bytes)
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

    async def update_state(self) -> bool:
        """Update the current state from the device."""
        _LOGGER.debug("Starting update_state()")
        try:
            values = await self.read_current()
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

    async def read_serial_number(self) -> Optional[str]:
        """Read the device serial number."""
        _LOGGER.debug("Starting read_serial_number()")
        async with self._lock:
            try:
                if not self.transport.is_open:
                    _LOGGER.error("Transport %s is not open", self.port)
                    return None

                message = bytes([self.slave_id, 0x03, 0x00, 0x50, 0x00, 0x08])
                _LOGGER.debug("Reading serial number with raw message: %s", message.hex().upper())

                lrc = self._calculate_lrc(message)
                formatted_message = b':' + message.hex().upper().encode() + format(lrc, '02X').encode() + b'\r\n'
                _LOGGER.debug("Sending message: %s", formatted_message)

                await self.transport.write(formatted_message)
                
                # IMPORTANT: Delay after sending
                await asyncio.sleep(0.5)
                
                response = await self._read_response()
                if not response or len(response) < 13:
                    _LOGGER.error("Invalid or incomplete response: %s", response)
                    return None

                data = response[7:-2]
                serial_number = bytes.fromhex(data).decode('ascii', errors='replace')
                if serial_number and all(c in ('\ufffd', '\xff', '\x00') for c in serial_number):
                    _LOGGER.warning("Serial number appears uninitialized (all 0xFF or 0x00)")
                    return None
                
                _LOGGER.debug("Decoded serial number: %s", serial_number)

                return serial_number

            except Exception as e:
                _LOGGER.exception("Error reading serial number: %s", str(e))
                return None

    async def read_all_data(self) -> dict[str, any]:
        """Read all available data from the device."""
        _LOGGER.debug("Starting read_all_data()")
        try:
            current_data = await self.read_current()
            
            if current_data is None:
                _LOGGER.error("Failed to read data from device")
                return {
                    "available": False,
                    "error": "Failed to read data from device"
                }

            data = {
                "available": True,
                "state": {
                    "code": current_data["state_code"],
                    "description": current_data["state_description"],
                },
                "charging": {
                    "enabled": await self.is_charging_enabled(),
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
        return value

    def _process_current_response(self, response: str) -> Optional[dict]:
        """Parse the Modbus response string for current status and values."""
        try:
            # Remove the leading ">" or ":"
            stripped_response = response[1:]
            
            # Verify LRC
            lrc_received = stripped_response[-2:]
            computed_lrc = self._calculate_lrc(bytes.fromhex(stripped_response[:-2]))
            _LOGGER.debug("Calculated LRC: %s for message: %s", format(computed_lrc, '02X'), stripped_response[:-2])
            if format(computed_lrc, '02X') != lrc_received:
                _LOGGER.error("LRC mismatch: computed=%02X, received=%s", computed_lrc, lrc_received)
                return None
            
            # Extract the data portion after byte count
            data_part = stripped_response[6:-2]  
            
            # Extract status register (first 4 chars)
            status_register = int(data_part[0:4], 16) 
            
            # Extract state code (next 2 chars)
            self.state_code = int(data_part[4:6], 16) 
            state_code_hex = f"0x{self.state_code:02X}"
            state_description = STATE_DESCRIPTIONS.get(self.state_code, "Unknown state")
            
            # Extract current values for each phase (next 6 chars, 2 chars each)
            ict1 = int(data_part[6:8], 16) if len(data_part) >= 8 else None  
            ict2 = int(data_part[8:10], 16) if len(data_part) >= 10 else None  
            ict3 = int(data_part[10:12], 16) if len(data_part) >= 12 else None  
            
            values = {
                "state_code": state_code_hex,
                "state_description": state_description,
                "max_current": status_register / 10.0,  
                "ict1": self.adjust_current_value(ict1) if ict1 is not None else None,
                "ict2": self.adjust_current_value(ict2) if ict2 is not None else None,
                "ict3": self.adjust_current_value(ict3) if ict3 is not None else None,
            }
            _LOGGER.info("Read current values: %s", values)
            return values
        except Exception as e:
            _LOGGER.exception("Error processing current response: %s", str(e))
            return None


    async def read_current(self) -> Optional[dict]:
        """Read the EV state and current values."""
        _LOGGER.debug("Starting read_current()")
        async with self._lock:
            try:
                if not self.transport.is_open: 
                    _LOGGER.error("Transport %s is not open", self.port)
                    return None
                
                message = bytes([self.slave_id, 0x03, 0x00, 0x33, 0x00, 0x03])
                _LOGGER.debug("Reading current with raw message: %s", message.hex().upper())
                lrc = self._calculate_lrc(message)
                formatted_message = b':' + message.hex().upper().encode() + format(lrc, '02X').encode() + b'\r\n'
                _LOGGER.debug("Sending message: %s", formatted_message)
                
                await self.transport.write(formatted_message) 
                
                # IMPORTANT: Delay after sending (EW11 compensation)
                await asyncio.sleep(0.5)

                response = await self._read_response()
                
                if not response or len(response) < 13: 
                    _LOGGER.error("Invalid or incomplete response: %s", response)
                    return None
                
                return self._process_current_response(response)

            except Exception as e:
                _LOGGER.exception("Error reading current: %s", str(e))
                return None

    async def send_raw_command(self, command: str) -> Optional[str]:
        """Send a raw command to the device."""
        async with self._lock:
            try:
                _LOGGER.debug(f"Sending raw command: {command}")
                await self.transport.write(command.encode()) 
                
                # IMPORTANT: Delay after sending
                await asyncio.sleep(0.5)
                
                response = await self._read_response()
                if response:
                    _LOGGER.debug(f"Received decoded response: {response}")
                    expected_prefix_gt = f">{self.slave_id:02X}"
                    expected_prefix_col = f":{self.slave_id:02X}"

                    if response.startswith(expected_prefix_gt) or response.startswith(expected_prefix_col):
                        return response
                    else:
                        _LOGGER.warning(f"Unexpected response: {response}, expected prefix: {expected_prefix_gt} or {expected_prefix_col}")
                        return None
                else:
                    _LOGGER.warning("No response received from device.")
                    return None
            except Exception as e:
                _LOGGER.error(f"Error sending raw command: {str(e)}")
                return None

    async def enable_charging(self) -> bool:
        """Enable charging."""
        return await self.send_raw_command(self._create_raw_command("100005000102A1A1"))

    async def disable_charging(self) -> bool:
        """Disable charging."""
        return await self.send_raw_command(self._create_raw_command("100005000102E0E0"))

    def _calculate_lrc(self, message: bytes) -> int:
        """Calculate LRC for Modbus ASCII message."""
        lrc = 0
        for byte in message:
            lrc = (lrc + byte) & 0xFF
        lrc = ((lrc ^ 0xFF) + 1) & 0xFF
        _LOGGER.debug(f"Calculated LRC: {format(lrc, '02X')} for message: {message.hex().upper()}")
        return lrc

    async def write_current(self, current: int) -> bool:
        """Write charging current."""
        async with self._lock:
            if current != 0 and not (5 <= current <= self.max_current):
                _LOGGER.error(f"Current must be 0 or between 5 and {self.max_current}")
                return False
            
            try:
                if current == 0:
                    duty_cycle = 1000
                else:
                    duty_cycle = int(current * 16.6)
            
                _LOGGER.debug(f"Setting duty cycle to: {duty_cycle} (0x{duty_cycle:04X}) for {current}A")
            
                message = bytes([
                    self.slave_id, 0x10, 0x00, 0x14, 0x00, 0x01, 0x02,
                    duty_cycle >> 8, 
                    duty_cycle & 0xFF 
                ])
            
                lrc = self._calculate_lrc(message)
                formatted_message = b':' + message.hex().upper().encode() + format(lrc, '02X').encode() + b'\r\n'
            
                _LOGGER.debug(f"Sending formatted message: {formatted_message}")
                await self.transport.write(formatted_message) 
                
                # IMPORTANT: Delay after sending
                await asyncio.sleep(0.5)

                response = await self.transport.readline() 
                _LOGGER.debug(f"Received raw response: {response}")
            
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
            
    async def is_charging_enabled(self) -> bool:
        """Check if charging is enabled."""
        try:
            await self.update_state()
            
            if self.state_code in [0xB1, 0xB2, 0xC2]:
                _LOGGER.debug(f"Charging is enabled. State code: 0x{self.state_code:02X}")
                return True
            else:
                _LOGGER.debug(f"Charging is disabled. State code: 0x{self.state_code:02X}")
                return False
        except Exception as e:
            _LOGGER.error(f"Error checking charging state: {e}")
            return False

    async def calculate_consumption_with_duty_cycle(self) -> Optional[float]:
        """Calculate simplified power consumption including duty cycle adjustment."""
        _LOGGER.debug("Starting calculate_consumption_with_duty_cycle()")
        try:
            data = await self.read_current()
            if not data:
                _LOGGER.error("Failed to read current values for power calculation")
                return None

            ict1 = data.get('ict1', 0)
            ict2 = data.get('ict2', 0)
            ict3 = data.get('ict3', 0)
            total_current = ict1 + ict2 + ict3

            duty_cycle = await self.read_duty_cycle()
            if duty_cycle is None:
                _LOGGER.error("Failed to retrieve duty cycle")
                return None

            voltage = 230
            power = total_current * voltage

            adjusted_power = power

            _LOGGER.info(f"Calculated simplified power consumption (adjusted for duty cycle): {adjusted_power:.2f} Watts")
            _LOGGER.debug(f"Power: {power:.2f} Watts, Duty Cycle: {duty_cycle:.2f}%")
            return adjusted_power

        except Exception as e:
            _LOGGER.error(f"Error calculating power consumption: {str(e)}")
            return None
        
    async def wake_up_device(self) -> bool:
        """Send wake-up sequence to the device."""
        _LOGGER.info("Attempting to wake up device...")
        async with self._lock:
            try:
                if not self.transport.is_open:
                    _LOGGER.error("Transport %s is not open", self.port)
                    return False
                
                wake_up_messages = [":000300010002FA\r\n", ":010300010002F9\r\n", ":010300010002F9\r\n"]
                
                for idx, message in enumerate(wake_up_messages):
                    _LOGGER.debug("Sending wake-up message %d: %s", idx + 1, message.strip())
                    await self.transport.write(message.encode()) 
                    
                    await asyncio.sleep(0.5)
                    
                    response = await self.transport.readline() 
                    _LOGGER.debug("Response to wake-up message %d: %s", idx + 1, response)
                
                _LOGGER.info("Wake-up sequence completed")
                return True
                
            except Exception as e:
                _LOGGER.exception("Error sending wake-up sequence: %s", str(e))
                return False

    async def read_firmware_info(self) -> Optional[dict]:
        """Read the firmware version and hardware info."""
        _LOGGER.debug("Starting read_firmware_info()")
        async with self._lock:
            try:
                if not self.transport.is_open:
                    _LOGGER.error("Transport %s is not open", self.port)
                    return None
                    
                device_id = format(self.slave_id, '02X')
                function_code = "03" 
                register_address = "0001"
                register_count = "0002"
                
                message_without_lrc = device_id + function_code + register_address + register_count
                lrc = self._calculate_lrc_ascii(message_without_lrc)
                formatted_message = f":{message_without_lrc}{lrc}\r\n".encode()
                
                _LOGGER.debug("Sending message: %s", formatted_message)
                await self.transport.write(formatted_message)
                
                # IMPORTANT: Delay after sending
                await asyncio.sleep(0.5)

                response = await self._read_response()
                if not response or len(response) < 13:
                    _LOGGER.error("Invalid or incomplete response: %s", response)
                    return None
                    
                data = response[1:-2]
                
                if not data.startswith(device_id + "0304"):
                    _LOGGER.error("Unexpected response format: %s", response)
                    return None
                    
                reg1 = int(data[6:10], 16) 
                reg2 = int(data[10:14], 16) if len(data) >= 14 else 0 
                
                firmware_major = (reg1 >> 8) & 0xFF 
                firmware_minor = reg1 & 0xFF        

                hardware_code = (reg2 >> 6) & 0x3
                
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
        message_bytes = bytes.fromhex(message_hex)
        lrc = (-sum(message_bytes)) & 0xFF
        return format(lrc, '02X')
            
    async def read_max_current_setting(self) -> Optional[int]:
        """Read the maximum current setting from register 0x000F."""
        _LOGGER.debug("Starting read_max_current_setting()")
        async with self._lock:
            try:
                if not self.transport.is_open:
                    _LOGGER.error("Transport %s is not open", self.port)
                    return None

                message = bytes([self.slave_id, 0x03, 0x00, 0x0F, 0x00, 0x05]) 
                lrc = self._calculate_lrc(message)
                formatted_message = b':' + message.hex().upper().encode() + format(lrc, '02X').encode() + b'\r\n'
                
                _LOGGER.debug("Sending formatted message: %s", formatted_message)
                await self.transport.write(formatted_message)
                
                # IMPORTANT: Delay after sending
                await asyncio.sleep(0.5)
                
                response = await self._read_response()
                if not response or len(response) < 15: 
                    _LOGGER.error("Invalid or incomplete response: %s", response)
                    return None

                stripped_response = response[1:]
                byte_count = int(stripped_response[4:6], 16)
                
                if byte_count != 10:
                    _LOGGER.error("Unexpected byte count %d, expected 10", byte_count)
                    return None
                
                data_start = 6 
                reg15_hex = stripped_response[data_start:data_start+4] 
                
                if len(reg15_hex) < 4:
                    _LOGGER.error("Insufficient data for register 15: %s", response)
                    return None
                
                reg15_value = int(reg15_hex, 16)
                max_current = round(reg15_value / 244.0)
                
                _LOGGER.info("Max current setting: %dA (raw value: %d from register 0x000F)", max_current, reg15_value)
                return max_current
                
            except Exception as e:
                _LOGGER.exception("Error reading max current setting: %s", str(e))
                return None

    async def read_duty_cycle(self) -> Optional[float]:
        """Read duty cycle from register 0x002E as specified in documentation."""
        _LOGGER.debug("Starting read_duty_cycle()")
        async with self._lock:
            try:
                if not self.transport.is_open:
                    _LOGGER.error("Transport %s is not open", self.port)
                    return None

                message = bytes([self.slave_id, 0x03, 0x00, 0x2E, 0x00, 0x05])
                _LOGGER.debug("Reading full current data with raw message: %s", message.hex().upper())

                lrc = self._calculate_lrc(message)
                formatted_message = b':' + message.hex().upper().encode() + format(lrc, '02X').encode() + b'\r\n'
                _LOGGER.debug("Sending message: %s", formatted_message)

                await self.transport.write(formatted_message)
                
                # IMPORTANT: Delay after sending
                await asyncio.sleep(0.5)

                raw_response = await self.transport.readline()
                _LOGGER.debug("Raw response: %s", raw_response)

                response = raw_response.decode(errors="replace").strip()

                while response and response[0] not in "><0123456789ABCDEF":
                    _LOGGER.debug("Removing invalid character from response start: 0x%04X", ord(response[0]))
                    response = response[1:]
                
                _LOGGER.debug("Cleaned response: %s", response)

                if not response.startswith(">") and not response.startswith(":") or len(response) < 13:
                    _LOGGER.error("Invalid or incomplete response: %s", response)
                    return None

                stripped_response = response[1:]
                
                lrc_received = stripped_response[-2:]
                computed_lrc = self._calculate_lrc(bytes.fromhex(stripped_response[:-2]))
                if format(computed_lrc, '02X') != lrc_received:
                    _LOGGER.error("LRC mismatch: computed=%02X, received=%s", computed_lrc, lrc_received)
                    return None

                data_part = stripped_response[6:-2]
                
                if len(data_part) != 20: 
                    _LOGGER.error("Unexpected data length: expected 20 chars, got %d: %s", len(data_part), data_part)
                    return None

                complete_data = int(data_part, 16)
                duty_cycle_raw = (complete_data >> 48) & 0xFFF
                duty_cycle = duty_cycle_raw / 10.0
                _LOGGER.info("Duty cycle calculated: %.1f%% (raw: %d)", duty_cycle, duty_cycle_raw)
                
                return duty_cycle

            except Exception as e:
                _LOGGER.exception("Error reading duty cycle: %s", str(e))
                return None
            
    def __del__(self):
        """Clean up connection."""
        try:
            if self.transport:
                self.transport.close()
        except Exception as e:
            _LOGGER.error(f"Error closing connection: {str(e)}")

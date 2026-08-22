import logging
import re
from typing import Optional, Tuple
import asyncio
try:
    # Prefer the maintained fork used in Home Assistant
    import serial_asyncio_fast as serial_asyncio
except ImportError:
    # Fallback for environments that still provide the original package
    import serial_asyncio  # type: ignore
from .const import STATE_DESCRIPTIONS, CONF_CONNECTION_TYPE, CONNECTION_TYPE_SERIAL, CONNECTION_TYPE_TCP

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
    
    def __init__(self, port: str, slave_id: int = 1, baudrate: int = 19200, max_current: int = 16, connection_type: str = CONNECTION_TYPE_SERIAL):
        """Initialize the Modbus ASCII device."""
        self._state_code = None
        self.slave_id = slave_id
        self.max_current = max_current
        self.port = port
        self.baudrate = baudrate
        # Default to serial if not specified (backward compatibility)
        self.connection_type = connection_type or CONNECTION_TYPE_SERIAL
        self.transport: ModbusASCIITransport = None
        self._lock = asyncio.Lock()
    
    async def connect(self):
        """Connects to the device and initializes the transport."""
        if self.connection_type == CONNECTION_TYPE_TCP:
            # TCP connection - port should be in format "host:port"
            if ":" in self.port:
                host, tcp_port = self.port.rsplit(":", 1)
                tcp_port_int = int(tcp_port)
            else:
                # Shouldn't happen with proper config flow, but handle gracefully
                host = self.port
                tcp_port_int = 502
            
            self.transport = TCPTransport(host, tcp_port_int)
            _LOGGER.info("Initializing ModbusASCIIDevice with TCP connection to %s:%s", host, tcp_port_int)
        
        elif self.connection_type == CONNECTION_TYPE_SERIAL:
            # Serial connection
            self.transport = SerialTransport(self.port, self.baudrate)
            _LOGGER.info("Initializing ModbusASCIIDevice with serial port %s at %d baud", self.port, self.baudrate)
        
        else:
            _LOGGER.error("Unknown connection type: %s", self.connection_type)
            raise ValueError(f"Unknown connection type: {self.connection_type}")

        # Open the connection
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

                

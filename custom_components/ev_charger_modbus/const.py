# custom_components/ev_charger_modbus/const.py
"""Constants for the EV Charger Modbus integration."""
from typing import Final

DOMAIN: Final = "ev_charger_modbus"
CONF_SERIAL_PORT = "port"
CONF_BAUDRATE = "baudrate"
CONF_MAX_CURRENT = "max_current"
CONF_CONNECTION_TYPE = "connection_type"
CONF_HOST = "host"
CONF_TCP_PORT = "tcp_port"
CONNECTION_TYPE_SERIAL = "serial"
CONNECTION_TYPE_TCP = "tcp"
DEFAULT_TCP_PORT = 502
DEFAULT_NAME = "EV Charger"
DEFAULT_SLAVE = 1
DEFAULT_BAUDRATE = 38400
DEFAULT_MAX_CURRENT = 16
#SCAN_INTERVAL = 120
# State descriptions
STATE_DESCRIPTIONS = {
    0xA1: "Waiting for EV",
    0xB1: "EV is asking for charging",
    0xB2: "EV has the permission to charge",
    0xC2: "EV is charged",
    0xC3: "C2, reduced current (error F16, F17)",
    0xC4: "C2, reduced current (imbalance F15)",
    0xE0: "Outlet disabled",
    0xE1: "Production test",
    0xE2: "EVCC setup mode",
    0xE3: "Bus idle",
    0xF1: "Unintended closed contact (Welding)",
    0xF2: "Internal error",
    0xF3: "DC residual current detected",
    0xF4: "Upstream communication timeout",
    0xF5: "Lock of socket failed",
    0xF6: "CS out of range",
    0xF7: "State D requested by EV",
    0xF8: "CP out of range",
    0xF9: "Overcurrent detected",
    0xFA: "Temperature outside limits",
    0xFB: "Unintended opened contact",
}
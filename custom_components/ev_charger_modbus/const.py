# custom_components/ev_charger_modbus/const.py
"""Constants for the EV Charger Modbus integration."""
from typing import Final

DOMAIN: Final = "ev_charger_modbus"

CONF_SERIAL_PORT = "port"
CONF_BAUDRATE = "baudrate"
CONF_MAX_CURRENT = "max_current"
DEFAULT_NAME = "EV Charger"
DEFAULT_SLAVE = 1
DEFAULT_BAUDRATE = 38400
DEFAULT_MAX_CURRENT = 16
#SCAN_INTERVAL = 120

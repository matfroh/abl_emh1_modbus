"""Constants for the EVSE Modbus integration."""

DOMAIN = "abl_emh1_modbus"

def generate_set_current_command(current):
    """Generate set current command with the specified current value."""
    # Convert current to duty cycle (16.6% for 10A in original command)
    duty_cycle = int((current / 10) * 16.6)
    hex_duty = f"{duty_cycle:04x}"
    # Format command with calculated duty cycle
    command = f":011000140001{hex_duty}"
    # Calculate checksum (simplified - you might need to adjust based on your device)
    # Add proper checksum calculation here
    return command

# EVSE Command definitions
COMMANDS = {
    "read_firmware": {
        "request": ":010300010002F9",
        "description": "Read firmware revision",
        "response_length": 8,
        "parser": lambda data: {
            "version": f"V{data[0]}.{data[1]}",
            "date": f"{data[2:]}",
        }
    },
    "read_ev_current_long": {
        "request": ":0103002E0005C9",
        "description": "Read EV current (long format)",
        "response_length": 20,
        "parser": lambda data: {
            "state": data[0:2],
            "ucp": data[2:6],
            "ict1": int(data[6:10], 16) / 10.0,
            "ict2": int(data[10:14], 16) / 10.0,
            "ict3": int(data[14:18], 16) / 10.0,
        }
    },
    "read_ev_current_short": {
        "request": ":010300330003C6",
        "description": "Read EV current (short format)",
        "response_length": 12,
        "parser": lambda data: {
            "ucp": data[0:2],
            "state": data[2:4],
            "ict1": int(data[4:6], 16),
            "ict2": int(data[6:8], 16),
            "ict3": int(data[8:10], 16),
        }
    },
    "set_current": {
        "description": "Set Icmax of EVSE",
        "response_length": 4,
        "parser": lambda data: {
            "status": "OK" if data == "DA" else "Failed"
        }
    }
}

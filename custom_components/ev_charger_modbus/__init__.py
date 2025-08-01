"""The EV Charger Modbus integration."""
import logging
from typing import Any
from datetime import timedelta
import voluptuous as vol
import async_timeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, CONF_PORT, CONF_SLAVE, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo
from .const import (
    DOMAIN,
    CONF_BAUDRATE,
    CONF_MAX_CURRENT,
    DEFAULT_NAME,
    DEFAULT_SLAVE,
    DEFAULT_BAUDRATE,
    DEFAULT_MAX_CURRENT,
)
from .modbus_device import ModbusASCIIDevice
from datetime import datetime
import asyncio

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [Platform.NUMBER, Platform.SENSOR, Platform.SWITCH]

# Add device specific constants
MANUFACTURER = "ABL"
MODEL = "eMH1"

class EVChargerEntity(CoordinatorEntity):
    """Base class for EV Charger entities."""

    def __init__(self, coordinator: DataUpdateCoordinator, device_name: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        serial_number = getattr(coordinator, "serial_number", None)
        firmware_version = getattr(coordinator, "firmware_version", None)
        hardware_version = getattr(coordinator, "hardware_version", None)

        device_info = {
            "identifiers": {(DOMAIN, device_name)},
            "name": device_name,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
        }

        if serial_number and not all(c == '\uffff' for c in serial_number):
            device_info["identifiers"].add((DOMAIN, serial_number))  # Add as an identifier instead
    
        if firmware_version:
            device_info["sw_version"] = firmware_version
    
        if hardware_version:
            device_info["hw_version"] = hardware_version

        self._attr_device_info = DeviceInfo(**device_info)
        self._attr_has_entity_name = True

SET_CURRENT_SCHEMA = vol.Schema({
    vol.Required("current"): vol.All(
        vol.Coerce(int),
        # Now using the configured max current instead of hardcoded 16
        vol.Range(min=0, max=lambda value: hass.data[DOMAIN][entry.entry_id].get("max_current", 16))
    )
})

async def async_update_data(coordinator, device, device_info, hass):
    """Fetch data from the device."""
    now = datetime.now()
    last_update = device_info.get("last_update", now)
    if (now - last_update).days > 7:
        _LOGGER.debug("Updating serial number and firmware info (weekly)")
        updated_info = await hass.async_add_executor_job(lambda: {
            "serial_number": device.read_serial_number(),
            "firmware_info": device.read_firmware_info(),
        })
        if updated_info["serial_number"]:
            coordinator.serial_number = updated_info["serial_number"]
        if updated_info["firmware_info"]:
            coordinator.firmware_info = updated_info["firmware_info"].get("firmware_version")
            coordinator.hardware_version = updated_info["firmware_info"].get("hardware_version")
        device_info["last_update"] = now

    async with async_timeout.timeout(10):
        data = await hass.async_add_executor_job(device.read_all_data)
        if data is None or not data.get("available", False):
            _LOGGER.debug("Device unavailable, trying wake-up")
            await hass.async_add_executor_job(device.wake_up_device)
            data = await hass.async_add_executor_job(device.read_all_data)
        return data

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the EV Charger Modbus component."""
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up EV Charger from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    device = ModbusASCIIDevice(
        port=entry.data[CONF_PORT],
        slave_id=entry.data.get(CONF_SLAVE, DEFAULT_SLAVE),
        baudrate=entry.data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE),
    )

    await hass.async_add_executor_job(device.wake_up_device)

    device_info = await hass.async_add_executor_job(lambda: {
        "serial_number": device.read_serial_number(),
        "firmware_info": device.read_firmware_info(),
    })

    serial_number = device_info["serial_number"]
    firmware_info = device_info["firmware_info"]

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=lambda: async_update_data(coordinator, device, device_info, hass),
        update_interval=timedelta(seconds=30),
    )

    coordinator.device = device
    coordinator.serial_number = serial_number if serial_number else None
    coordinator.firmware_info = firmware_info  # Store the whole dictionary
    coordinator.firmware_version = firmware_info.get("firmware_version") if firmware_info else None
    coordinator.hardware_version = firmware_info.get("hardware_version") if firmware_info else None
    coordinator.max_current = entry.data.get(CONF_MAX_CURRENT, DEFAULT_MAX_CURRENT)

    await coordinator.async_config_entry_first_refresh()

    device_name = entry.data.get(CONF_NAME, DEFAULT_NAME)
    hass.data[DOMAIN][entry.entry_id] = {
        "device": device,
        "coordinator": coordinator,
        CONF_NAME: device_name,
        "max_current": entry.data.get(CONF_MAX_CURRENT, DEFAULT_MAX_CURRENT),
    }

    async def handle_set_charging_current(call: ServiceCall) -> None:
        """Handle service call to set charging current."""
        current = call.data["current"]
        await hass.async_add_executor_job(device.wake_up_device)
        success = await hass.async_add_executor_job(device.write_current, current)
        if not success:
            _LOGGER.error(f"Failed to set charging current to {current}A")
        else:
            _LOGGER.info(f"Charging current set to {current}A")
            await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        "set_charging_current",
        handle_set_charging_current,
        schema=SET_CURRENT_SCHEMA,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        device = hass.data[DOMAIN][entry.entry_id]["device"]
        if device.serial.is_open:
            device.serial.close()
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok

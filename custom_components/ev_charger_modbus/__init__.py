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
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [Platform.NUMBER, Platform.SENSOR, Platform.SWITCH]

# Add device specific constants
MANUFACTURER = "ABL"
MODEL = "eMH1"

SET_CHARGING_CURRENT_SERVICE = "set_charging_current"
# Update the service schema to enforce that 'target' (if provided) contains an 'entity_id' as a list of strings
# Update service schema to accept entity_id as string or a list of strings
SET_CHARGING_CURRENT_SCHEMA = vol.Schema({
    vol.Optional("target"): vol.Schema({
        vol.Required("entity_id"): vol.All(cv.ensure_list, [cv.string])
    }),
    vol.Required("current"): vol.All(
        vol.Coerce(int),
        vol.Range(min=0, max=32)  # We'll validate the actual max in the handler
    )
}, extra=vol.ALLOW_EXTRA)

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

async def async_update_data(coordinator, device, device_info, hass):
    """Fetch data from the device."""
    now = datetime.now()
    last_update = device_info.get("last_update", now)
    if (now - last_update).days > 7:
        _LOGGER.debug("Updating serial number and firmware info (weekly)")
        updated_info = {
            "serial_number": await device.read_serial_number(),
            "firmware_info": await device.read_firmware_info(),
        }
        if updated_info["serial_number"]:
            coordinator.serial_number = updated_info["serial_number"]
        if updated_info["firmware_info"]:
            coordinator.firmware_info = updated_info["firmware_info"].get("firmware_version")
            coordinator.hardware_version = updated_info["firmware_info"].get("hardware_version")
        device_info["last_update"] = now

    async with async_timeout.timeout(10):
        data = await device.read_all_data()
        if data is None or not data.get("available", False):
            _LOGGER.debug("Device unavailable, trying wake-up")
            await device.wake_up_device()
            data = await device.read_all_data()
            
        data["duty_cycle"] = await device.read_duty_cycle()
        data["power_consumption"] = await device.calculate_consumption_with_duty_cycle()
        
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
        max_current=entry.data.get(CONF_MAX_CURRENT, DEFAULT_MAX_CURRENT),
    )
    
    await device.connect()

    await device.wake_up_device()

    device_info = {
        "serial_number": await device.read_serial_number(),
        "firmware_info": await device.read_firmware_info(),
        "max_current_from_device": await device.read_max_current_setting(),
    }

    serial_number = device_info["serial_number"]
    firmware_info = device_info["firmware_info"]
    
    # Update device max_current with actual reading from device, fallback to config
    device_max_current = device_info["max_current_from_device"]
    if device_max_current:
        device.max_current = device_max_current
        _LOGGER.info("Using max current from device: %dA", device_max_current)
        actual_max_current = device_max_current
    else:
        # Fallback to config value if reading fails
        config_max_current = entry.data.get(CONF_MAX_CURRENT, DEFAULT_MAX_CURRENT)
        device.max_current = config_max_current
        _LOGGER.warning("Could not read max current from device, using config value: %dA", config_max_current)
        actual_max_current = config_max_current

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
    coordinator.max_current = actual_max_current

    await coordinator.async_config_entry_first_refresh()

    device_name = entry.data.get(CONF_NAME, DEFAULT_NAME)
    hass.data[DOMAIN][entry.entry_id] = {
        "device": device,
        "coordinator": coordinator,
        CONF_NAME: device_name,
        "max_current": actual_max_current,
        "entities": {},  # Add this to store entities
    }

    # Update service handler to correctly extract target entity from the service call data
    async def handle_set_charging_current(call: ServiceCall) -> None:
        """Handle setting the charging current."""
        current = int(call.data["current"])
        _LOGGER.debug("Service call data: %s", call.data)
        
        # Extract entity_ids from "target" key if available, else fallback to top-level "entity_id"
        entity_ids = []
        if "target" in call.data and call.data["target"] is not None:
            target = call.data["target"]
            if "entity_id" in target:
                eids = target["entity_id"]
                if isinstance(eids, list):
                    entity_ids = eids
                elif isinstance(eids, str) and eids.strip():
                    entity_ids = [eids.strip()]
        
        if not entity_ids:
            e = call.data.get("entity_id")
            if isinstance(e, list):
                entity_ids = e
            elif isinstance(e, str) and e.strip():
                entity_ids = [e.strip()]
        
        if not entity_ids:
            _LOGGER.error("No target specified. Call data: %s", call.data)
            return
        
        # Instead of looking for entities, use the device directly
        for entry_data in hass.data[DOMAIN].values():
            device = entry_data["device"]
            max_current = entry_data["max_current"]
            if current > max_current:
                _LOGGER.error(
                    "Requested current %d exceeds maximum allowed current %d", 
                    current, max_current
                )
                continue
            try:
 #               result = await hass.async_add_executor_job(device.write_current, current)
                result = await device.write_current(current)
                if result:
                    _LOGGER.info("Successfully set current to %dA", current)
                else:
                    _LOGGER.error("Device did not accept current value %dA", current)
            except Exception as ex:
                _LOGGER.error("Failed to set current: %s", str(ex))

    # Register the service
    hass.services.async_register(
        DOMAIN,
        SET_CHARGING_CURRENT_SERVICE,
        handle_set_charging_current,
        schema=SET_CHARGING_CURRENT_SCHEMA
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

# __init__.py
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
    DEFAULT_NAME,
    DEFAULT_SLAVE,
    DEFAULT_BAUDRATE,
)
from .modbus_device import ModbusASCIIDevice

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
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_name)},
            name=device_name,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )
        self._attr_has_entity_name = True

SET_CURRENT_SCHEMA = vol.Schema({
    vol.Required("current"): vol.All(
        vol.Coerce(int),
        vol.Range(min=0, max=16)
    )
})

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the EV Charger Modbus component."""
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up EV Charger from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    
    # Create ModbusASCIIDevice instance
    device = ModbusASCIIDevice(
        port=entry.data[CONF_PORT],
        slave_id=entry.data.get(CONF_SLAVE, DEFAULT_SLAVE),
        baudrate=entry.data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)
    )

    async def async_update_data():
        """Fetch data from API endpoint."""
        async with async_timeout.timeout(10):
            return await hass.async_add_executor_job(device.read_all_data)

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=async_update_data,
        update_interval=timedelta(seconds=30)
    )

    # Initial data fetch
    await coordinator.async_config_entry_first_refresh()
    
    device_name = entry.data.get(CONF_NAME, DEFAULT_NAME)
    
    # Store the device instance and coordinator
    hass.data[DOMAIN][entry.entry_id] = {
        "device": device,
        "coordinator": coordinator,
        CONF_NAME: device_name,
    }

    async def handle_set_charging_current(call: ServiceCall) -> None:
        """Handle the service call."""
        current = call.data["current"]
        device = hass.data[DOMAIN][entry.entry_id]["device"]
        success = await hass.async_add_executor_job(device.write_current, current)
        
        if not success:
            _LOGGER.error(f"Failed to set charging current to {current}A")
            return
        
        _LOGGER.info(f"Successfully set charging current to {current}A")
        await coordinator.async_request_refresh()

    # Register the service
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
        # Clean up device
        device = hass.data[DOMAIN][entry.entry_id]["device"]
        if device.serial.is_open:
            device.serial.close()
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
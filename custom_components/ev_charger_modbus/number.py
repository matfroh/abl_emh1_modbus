"""Number platform for EV Charger Modbus."""
import logging
from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from . import EVChargerEntity  # Add this import
from .const import DOMAIN, CONF_MAX_CURRENT, DEFAULT_MAX_CURRENT, CONF_NAME

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the EV Charger number platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    device_name = hass.data[DOMAIN][entry.entry_id][CONF_NAME]
    
    # Create the entity
    entity = ChargingCurrentNumber(coordinator, device_name)
    
    # Store the entity reference
    hass.data[DOMAIN][entry.entry_id]["entities"][entity.entity_id] = entity
    
    async_add_entities([entity])

class ChargingCurrentNumber(EVChargerEntity, NumberEntity):
    """Representation of the charging current setting."""

    def __init__(self, coordinator, device_name: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, device_name)
        
        self._attr_name = "Charging Current"
        self._attr_unique_id = f"{device_name}_charging_current"
        self._attr_native_min_value = 5
        self._attr_native_max_value = coordinator.max_current
        self._attr_native_step = 1
        self._attr_native_value = coordinator.data.get("charging_current") if coordinator.data else coordinator.max_current
        self._attr_mode = "slider"
        
        _LOGGER.debug(
            "Initialized slider with name: %s, max current: %s", 
            self._attr_name, 
            self._attr_native_max_value
        )

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        if not 5 <= value <= self._max_current:
            _LOGGER.error(f"Current must be between 5 and {self._max_current}")
            return
            
        await self.coordinator.hass.async_add_executor_job(
            self.coordinator.device.write_current, int(value)
        )
        await self.coordinator.async_request_refresh()

    @property
    def native_value(self):
        """Return the current charging current."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("charging_current")
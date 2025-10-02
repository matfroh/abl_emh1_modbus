"""Number platform for EV Charger Modbus."""
import logging
from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_NAME
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from . import EVChargerEntity
from .const import DOMAIN, CONF_MAX_CURRENT, DEFAULT_MAX_CURRENT

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the EV Charger number platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    device_name = hass.data[DOMAIN][entry.entry_id][CONF_NAME]
    max_current = hass.data[DOMAIN][entry.entry_id]["max_current"]  # Use actual max from device
    
    entity = ChargingCurrentNumber(coordinator, device_name, max_current)
    hass.data[DOMAIN][entry.entry_id].setdefault("entities", {})
    hass.data[DOMAIN][entry.entry_id]["entities"][entity.entity_id] = entity
    
    async_add_entities([entity])

class ChargingCurrentNumber(EVChargerEntity, NumberEntity):
    """Representation of the charging current setting."""

    def __init__(self, coordinator, device_name: str, max_current: int) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, device_name)
        
        self._attr_name = "Charging Current"
        self._attr_unique_id = f"{device_name}_charging_current"
        self._attr_native_min_value = 0
        self._attr_native_max_value = max_current
        self._attr_native_step = 1
        self._attr_native_value = coordinator.data.get("charging_current", max_current) if coordinator.data else max_current
        self._attr_mode = "slider"
        
        _LOGGER.debug(
            "Initialized slider with name: %s, max current: %s", 
            self._attr_name, 
            self._attr_native_max_value
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        _LOGGER.debug("Setting charging current to: %s", value)
        if value != 0 and not (5 <= value <= self._attr_native_max_value):
            _LOGGER.error(f"Current must be 0 or between 5 and {self._attr_native_max_value}")
            return
            
        try:
            success = await self.coordinator.device.write_current(int(value))
            if success:
                self._attr_native_value = value
                _LOGGER.info("Successfully set charging current to %sA", value)
                await self.coordinator.async_request_refresh()
            else:
                _LOGGER.error("Failed to set charging current")
        except Exception as e:
            _LOGGER.exception("Error setting charging current: %s", e)

    @property
    def native_value(self):
        """Return the current charging current."""
        if self.coordinator.data is None:
            return self._attr_native_value
        return self.coordinator.data.get("charging_current", self._attr_native_value)
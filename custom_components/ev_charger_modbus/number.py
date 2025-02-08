import logging
from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

class EVChargerSlider(NumberEntity):
    """Representation of the EV Charger current setting."""

    def __init__(self, device, name):
        """Initialize the number entity."""
        self._device = device
        self._attr_name = f"{name} Charging Current"
        self._attr_unique_id = f"{DOMAIN}_{name.lower()}_charging_current"
        self._attr_native_min_value = 0
        self._attr_native_max_value = 16
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = "A"
        self._attr_native_value = 16  # Default value set to 16 (maximum allowed)
        _LOGGER.debug("EVChargerSlider initialized with default value: %s", self._attr_native_value)

    async def async_update(self) -> None:
        """Do nothing here since the value is updated when the service is called."""
        _LOGGER.debug("Update skipped; current value set by service response.")

    async def async_set_native_value(self, value: float) -> None:
        """Set a new charging current and parse the response."""
        _LOGGER.info("Setting new charging current: %s A", value)
        try:
            # Set charging current via the service call
            response = await self.hass.async_add_executor_job(
                self._device.write_current, int(value)
            )

            # Parse the response to check for success/failure
            if response.startswith(">011000140001DA"):  # Successful response
                self._attr_native_value = value
                _LOGGER.info("Successfully set charging current to %s A", value)
            elif response.startswith(">0190046B"):  # Failure response
                self._attr_native_value = 16  # Default to 16 if failed
                _LOGGER.error("Failed to set charging current, response: %s", response)
            else:
                self._attr_native_value = 16  # Default to 16 if unknown response
                _LOGGER.error("Unknown response received: %s", response)

        except Exception as ex:
            _LOGGER.exception("Error while setting charging current: %s", ex)
            self._attr_native_value = 16  # Default to 16 on error

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the EV Charger number platform."""
    device = hass.data[DOMAIN][entry.entry_id]["device"]  # Use 'entry' here
    name = entry.data[CONF_NAME]
   
    entity = EVChargerSlider(device, name)
    async_add_entities([entity])

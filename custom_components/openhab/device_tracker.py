"""Device Tracker platform for openHAB."""
from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEVICE_TRACKER, ITEMS_MAP
from .entity import OpenHABEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Setup device_tracker platform."""
    coordinator = entry.runtime_data

    async_add_entities(
        OpenHABTracker(hass, coordinator, item)
        for item in coordinator.data.values()
        if item.type_ in ITEMS_MAP[DEVICE_TRACKER]
    )


class OpenHABTracker(OpenHABEntity, TrackerEntity):
    """openHAB device_tracker class."""

    _attr_device_class_map = []

    @property
    def location_name(self):
        """Return the latitude."""
        return self.item.label if len(self.item.label) > 0 else self.item.name

    @property
    def latitude(self):
        """Return the latitude."""
        if (
            self.item._state is not None
            and self.item._state != "NULL"
            and self.item._state != "UNDEF"
        ):
            return float(self.item._state.split(",")[0])
        return None

    @property
    def longitude(self):
        """Return the longitude."""
        if (
            self.item._state is not None
            and self.item._state != "NULL"
            and self.item._state != "UNDEF"
        ):
            return float(self.item._state.split(",")[1])
        return None

    @property
    def source_type(self) -> str:
        """Return the source type, eg gps or router, of the device."""
        return SourceType.GPS

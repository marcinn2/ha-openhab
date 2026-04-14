"""Binary sensor platform for openHAB."""
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import BINARY_SENSOR, ITEMS_MAP
from .device_classes_map import BINARY_SENSOR_DEVICE_CLASS_MAP
from .entity import OpenHABEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_devices: AddEntitiesCallback,
) -> None:
    """Setup binary_sensor platform."""
    coordinator = entry.runtime_data
    
    binary_sensors = []
    for item in coordinator.data.values():
        if (item.type_ex == 'devireg_attr_ui_binary_sensor'):
            binary_sensors.append(OpenHABBinarySensor(hass, coordinator, item))
        elif ((item.type_ex == False) and (item.type_ in ITEMS_MAP[BINARY_SENSOR])):
            binary_sensors.append(OpenHABBinarySensor(hass, coordinator, item))
    
    from .const import LOGGER
    LOGGER.info(f"Binary Sensor platform: Adding {len(binary_sensors)} binary sensor entities")
    async_add_devices(binary_sensors)


class OpenHABBinarySensor(OpenHABEntity, BinarySensorEntity):
    """openHAB binary_sensor class."""

    _attr_device_class_map = BINARY_SENSOR_DEVICE_CLASS_MAP

    @property
    def is_on(self) -> bool:
        """Return true if the binary_sensor is on."""
        return (self.item._state == "OPEN") or (self.item._state == "ON")

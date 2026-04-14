"""Sensor platform for openHAB."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import ITEMS_MAP, SENSOR, LOGGER
from .device_classes_map import SENSOR_DEVICE_CLASS_MAP
from .entity import OpenHABEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Setup sensor platform."""
    coordinator = entry.runtime_data

    # Define group types that have specific platforms
    specific_group_types = {"Switch", "Rollershutter", "Color", "Dimmer", "Contact", "Player"}

    sensors = []
    skipped_untyped_groups = 0
    for item in coordinator.data.values():
        # Skip untyped groups - they will be handled as switches
        if type(item).__name__ == 'GroupItem' and item.type_ is None and (not hasattr(item, 'groupType') or item.groupType is None):
            skipped_untyped_groups += 1
            continue
            
        if (item.type_ex == 'devireg_attr_ui_sensor'):
            sensors.append(OpenHABSensor(hass, coordinator, item))
        elif ((item.type_ex == False) and (item.type_ in ITEMS_MAP[SENSOR])):
            sensors.append(OpenHABSensor(hass, coordinator, item))
        elif (item.type_ == "Group" and (not hasattr(item, 'groupType') or item.groupType not in specific_group_types)):
            sensors.append(OpenHABSensor(hass, coordinator, item))
    
    LOGGER.info(f"Sensor platform: Skipped {skipped_untyped_groups} untyped groups (handled as switches)")
    LOGGER.info(f"Sensor platform: Adding {len(sensors)} sensor entities out of {len(coordinator.data)} total items")
    async_add_entities(sensors)


class OpenHABSensor(OpenHABEntity, SensorEntity):
    """openHAB Sensor class."""

    _attr_device_class_map = SENSOR_DEVICE_CLASS_MAP

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        return self.item._state

"""Switch platform for openHAB."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ITEMS_MAP, SWITCH, LOGGER
from .device_classes_map import SWITCH_DEVICE_CLASS_MAP
from .entity import OpenHABEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_devices: AddEntitiesCallback,
) -> None:
    """Setup sensor platform."""
    coordinator = entry.runtime_data

    # Debug logging
    total_items = len(coordinator.data.values())
    group_items = [item for item in coordinator.data.values() if item.type_ == "Group"]
    switch_groups = [item for item in coordinator.data.values() 
                     if item.type_ == "Group" and hasattr(item, 'groupType') and item.groupType == "Switch"]
    
    LOGGER.info(f"Switch platform: Total items: {total_items}, Groups: {len(group_items)}, Switch groups: {len(switch_groups)}")
    
    # Count how many Switch items we have
    switch_items = [item for item in coordinator.data.values() if item.type_ == "Switch"]
    LOGGER.info(f"Switch items available: {len(switch_items)}")
    
    # Log some group details
    for item in group_items[:5]:  # First 5 groups
        group_type = getattr(item, 'groupType', 'NO_GROUPTYPE')
        LOGGER.info(f"  Group: {item.name}, type: {item.type_}, groupType: {group_type}")

    switches = []
    for item in coordinator.data.values():
        if (item.type_ex == 'devireg_attr_ui_switch'):
            switches.append(OpenHABBinarySwitch(hass, coordinator, item))
        elif (item.type_ex == False) and (item.type_ in ITEMS_MAP[SWITCH]):
            switches.append(OpenHABBinarySwitch(hass, coordinator, item))
        elif item.type_ == "Group" and hasattr(item, 'groupType') and item.groupType == "Switch":
            LOGGER.info(f"  Adding switch group: {item.name}")
            switches.append(OpenHABBinarySwitch(hass, coordinator, item))
        # Treat untyped groups (type_ = None, no groupType) as switches
        elif type(item).__name__ == 'GroupItem' and item.type_ is None and (not hasattr(item, 'groupType') or item.groupType is None):
            LOGGER.info(f"  Adding untyped group as switch: {item.name}")
            switches.append(OpenHABBinarySwitch(hass, coordinator, item))
    
    LOGGER.info(f"Switch platform: Adding {len(switches)} switch entities")
    async_add_devices(switches)


class OpenHABBinarySwitch(OpenHABEntity, SwitchEntity):
    """openHAB switch class."""

    _attr_device_class_map = SWITCH_DEVICE_CLASS_MAP

    async def async_turn_on(self, **kwargs: dict[str, Any]) -> None:
        """Turn on the switch."""
        await self.hass.async_add_executor_job(self.item.on)
        # Don't request refresh - SSE will provide the update

    async def async_turn_off(self, **kwargs: dict[str, Any]) -> None:
        """Turn off the switch."""
        await self.hass.async_add_executor_job(self.item.off)
        # Don't request refresh - SSE will provide the update

    async def async_toggle(self, **kwargs: dict[str, Any]) -> None:
        """Toggle the switch."""
        await self.hass.async_add_executor_job(self.item.toggle)
        # Don't request refresh - SSE will provide the update

    @property
    def is_on(self) -> bool:
        """Return true if the switch is on."""
        return self.item._state == "ON"

"""OpenHABEntity class"""
from __future__ import annotations

import re
from typing import Any, List

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.device_registry import DeviceEntryType

from homeassistant.helpers.update_coordinator import CoordinatorEntity
from openhab import items

from .const import DOMAIN, NAME, VERSION, LOGGER
from .coordinator import OpenHABDataUpdateCoordinator
from .icons_map import ICONS_MAP, ITEM_TYPE_MAP
from .utils import strip_ip


def _slugify(text: str) -> str:
    """Convert text to a valid HA entity ID component.

    Produces a lowercase string containing only [a-z0-9_].
    Consecutive non-word characters are collapsed into a single underscore,
    and leading/trailing underscores are stripped.

    This avoids importing from homeassistant.util.slugify whose internal
    module path changed in HA 2026.x.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug or "unknown"


class OpenHABEntity(CoordinatorEntity):
    """Base openHAB entity."""

    coordinator: OpenHABDataUpdateCoordinator
    _attr_device_class_map: List | None

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: OpenHABDataUpdateCoordinator,
        item: items.Item,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)

        self.coordinator = coordinator
        self.hass = hass
        self.item = item
        self._id = item.name
        self.coordinator.ha_items[self.item.name] = self

        if not self.coordinator.api:
            self._base_url = ""
        self._base_url = self.coordinator.api._base_url
        self._host = strip_ip(self._base_url)
        #self._nameid_prefix = f"{self._host}_"
        self._nameid_prefix = f"oh_"

        # Slugify the item name so the generated entity_id is always a valid
        # HA identifier (lowercase, no spaces, no special characters).
        # HA 2026.2+ enforces strict entity ID validation and rejects raw
        # OpenHAB item names that contain uppercase letters or other characters
        # not permitted in entity IDs.
        self.entity_id = f"{DOMAIN}.{self._nameid_prefix}{_slugify(self.item.name)}"

        if self.item.unit_of_measure:
            self._attr_native_unit_of_measurement = str(self.item.unit_of_measure)

    @property
    def available(self):
        """Return True if entity is available."""
        if self.item.parent_device_name:
            if self.item.parent_device_name in self.coordinator.ha_items:
                return  self.coordinator.ha_items[self.item.parent_device_name].available

        return self.coordinator.is_online

    @property
    def name(self) -> str:
        """Return the name of the switch."""
        return self.item.label if len(self.item.label) > 0 else self.item.name

    @property
    def unique_id(self) -> str | None:
        """Return a unique ID to use for this entity.

        Uses the original (un-slugified) item name so the entity can always
        be looked up unambiguously in the HA entity registry, regardless of
        how the entity_id was slugified.
        """
        return f"{DOMAIN}.{self._nameid_prefix}{self.item.name}"

    @property
    def device_info(self) -> DeviceInfo:
        version = VERSION
        oh_version = self.coordinator.version
        if oh_version is not None:
            version = oh_version

        # Special handling for devireg devices - create separate device per unit
        if self.item.type_ex in ['devireg_attr', 'devireg_attr_ui_sensor', 'devireg_attr_ui_binary_sensor', 'devireg_attr_ui_switch']:
            if self.item.groupNames and len(self.item.groupNames) > 0:
                devi_unit = self.item.groupNames[0]
                LOGGER.debug(f"Creating devireg device for {self.item.name}: {devi_unit}")
                return DeviceInfo(
                    identifiers={(DOMAIN, f"{self._host}_{devi_unit}")}
                )
            else:
                LOGGER.warning(f"Devireg item {self.item.name} has no groupNames - using default device")
        
        # Default device for all other items
        return DeviceInfo(
            identifiers={(DOMAIN, self._host)},
            name=f"{NAME} - {self._host}",
            model=version,
            manufacturer=NAME,
            configuration_url=self._base_url,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def device_class(self):
        """Return the device class"""
        name = self.item.name.lower()
        label = self.item.label.lower()
        device_classes = self._attr_device_class_map

        if bool(device_classes):
            for device_class in device_classes:
                if device_class in name or device_class in label:
                    return device_class

        return None

    @property
    def icon(self) -> str | None:
        """Return the icon of the switch."""
        category = self.item.category
        item_type = self.item.type_
        if category in ICONS_MAP:
            return ICONS_MAP[category]
        if item_type in ITEM_TYPE_MAP:
            return ITEM_TYPE_MAP[item_type]
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return {}

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        new = self.coordinator.data.get(self._id)
        if new is not None:
            try:
                # Avoid using != comparison which may not be implemented for all item types
                self.item = new
            except (NotImplementedError, AttributeError) as e:
                LOGGER.debug(
                    "Could not update item %s: %s", self._id, str(e)
                )
        self.async_write_ha_state()
    
    async def async_added_to_hass(self) -> None:
        """Connect to dispatcher listening for entity data notifications."""
        await super().async_added_to_hass()

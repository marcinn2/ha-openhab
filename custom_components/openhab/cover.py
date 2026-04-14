"""Cover platform for openHAB."""
from typing import Any, cast

from homeassistant.components.cover import ATTR_POSITION, CoverEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import COVER, ITEMS_MAP
from .device_classes_map import COVER_DEVICE_CLASS_MAP
from .entity import OpenHABEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_devices: AddEntitiesCallback,
) -> None:
    """Setup sensor platform."""
    coordinator = entry.runtime_data

    covers = []
    for item in coordinator.data.values():
        if item.type_ in ITEMS_MAP[COVER]:
            covers.append(OpenHABCover(hass, coordinator, item))
        elif (item.type_ == "Group" and hasattr(item, 'groupType') and item.groupType == "Rollershutter"):
            covers.append(OpenHABCover(hass, coordinator, item))
    
    from .const import LOGGER
    LOGGER.info(f"Cover platform: Adding {len(covers)} cover entities")
    async_add_devices(covers)


class OpenHABCover(OpenHABEntity, CoverEntity):
    """openHAB Cover class."""

    _attr_device_class_map = COVER_DEVICE_CLASS_MAP

    @property
    def current_cover_position(self) -> int:
        """Return current position of cover.
        None is unknown, 0 is closed, 100 is fully open.
        """
        if not self.item._state:
            return 0
        return 100 - cast(int, self.item._state)

    async def async_set_cover_position(self, **kwargs: dict[str, Any]) -> None:
        """Move the cover to a specific position."""
        if not self.item:
            return
        await self.hass.async_add_executor_job(
            self.coordinator.api.openhab.req_post,
            f"/items/{self._id}",
            str(kwargs[ATTR_POSITION]),
        )
        # Don't request refresh - SSE will provide the update

    async def async_open_cover(self, **kwargs: dict[str, Any]) -> None:
        """Open the cover."""
        if not self.item:
            return
        await self.hass.async_add_executor_job(
            self.coordinator.api.openhab.req_post, f"/items/{self._id}", "UP"
        )
        # Don't request refresh - SSE will provide the update

    async def async_close_cover(self, **kwargs: dict[str, Any]) -> None:
        """Close cover."""
        if not self.item:
            return
        await self.hass.async_add_executor_job(
            self.coordinator.api.openhab.req_post, f"/items/{self._id}", "DOWN"
        )
        # Don't request refresh - SSE will provide the update

    async def async_stop_cover(self, **kwargs: dict[str, Any]) -> None:
        """Stop cover."""
        if not self.item:
            return
        await self.hass.async_add_executor_job(
            self.coordinator.api.openhab.req_post, f"/items/{self._id}", "STOP"
        )
        # Don't request refresh - SSE will provide the update

    @property
    def is_closed(self) -> bool:
        """Return if the cover is closed or not."""
        return self.current_cover_position == 0

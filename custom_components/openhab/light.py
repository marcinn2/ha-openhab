"""Light platform for openHAB."""

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ITEMS_MAP, LIGHT
from .entity import OpenHABEntity
from .utils import hsv_to_str


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_devices: AddEntitiesCallback,
) -> None:
    """Setup sensor platform."""
    coordinator = entry.runtime_data

    color_lights = []
    for item in coordinator.data.values():
        if item.type_ == ITEMS_MAP[LIGHT][0]:  # Color
            color_lights.append(OpenHABLightColor(hass, coordinator, item))
        elif (item.type_ == "Group" and hasattr(item, 'groupType') and item.groupType == "Color"):
            color_lights.append(OpenHABLightColor(hass, coordinator, item))
    
    dimmer_lights = []
    for item in coordinator.data.values():
        if item.type_ == ITEMS_MAP[LIGHT][1]:  # Dimmer
            dimmer_lights.append(OpenHABLightDimmer(hass, coordinator, item))
        elif (item.type_ == "Group" and hasattr(item, 'groupType') and item.groupType == "Dimmer"):
            dimmer_lights.append(OpenHABLightDimmer(hass, coordinator, item))
    
    from .const import LOGGER
    LOGGER.info(f"Light platform: Adding {len(color_lights)} color lights and {len(dimmer_lights)} dimmer lights")
    async_add_devices(color_lights)
    async_add_devices(dimmer_lights)


class OpenHABLightColor(OpenHABEntity, LightEntity):
    """openHAB Color Light class."""

    _attr_device_class_map = []
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS, ColorMode.HS}

    @property
    def is_on(self):
        """Return true if light is on."""
        return self.item._state[2] > 0

    async def async_turn_on(self, **kwargs):
        """Instruct the light to turn on."""
        if not self.item:
            return
        if ATTR_HS_COLOR in kwargs:
            return print(kwargs[ATTR_HS_COLOR])
        hsv = self.item._state
        await self.hass.async_add_executor_job(
            self.coordinator.api.openhab.req_post,
            f"/items/{self._id}",
            data=hsv_to_str([hsv[0], hsv[1], 100]),
        )
        # Don't request refresh - SSE will provide the update

    async def async_turn_off(self, **kwargs):
        """Instruct the light to turn off."""
        if not self.item:
            return
        hsv = self.item._state
        await self.hass.async_add_executor_job(
            self.coordinator.api.openhab.req_post,
            f"/items/{self._id}",
            data=hsv_to_str([hsv[0], hsv[1], 0]),
        )
        # Don't request refresh - SSE will provide the update

    # @property
    # def color_mode(self) -> str | None:
    #     """Return the color mode of the light."""
    #     return ColorMode.HS

    @property
    def hs_color(self) -> tuple[float, float]:
        """Return the hs color value."""
        hsv = self.item._state
        return [hsv[0], hsv[1]]


class OpenHABLightDimmer(OpenHABEntity, LightEntity):
    """openHAB Dimmer Light class."""

    _attr_device_class_map = []
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    @property
    def is_on(self):
        """Return true if light is on."""
        if self.item._state is None:
            return False
        return self.item._state > 0

    @property
    def brightness(self):
        """Return the brightness of this light between 0..255."""
        return int((self.item._state / 100) * 255)

    async def async_turn_on(self, **kwargs):
        """Instruct the light to turn on."""
        if not self.item:
            return
        if ATTR_BRIGHTNESS in kwargs:
            brightness = int(kwargs[ATTR_BRIGHTNESS] / 255) * 100
            await self.hass.async_add_executor_job(
                self.coordinator.api.openhab.req_post,
                f"/items/{self._id}",
                str(brightness),
            )
            # Don't request refresh - SSE will provide the update
            return
        await self.hass.async_add_executor_job(
            self.coordinator.api.openhab.req_post, f"/items/{self._id}", "ON"
        )
        # Don't request refresh - SSE will provide the update

    async def async_turn_off(self, **kwargs):
        """Instruct the light to turn off."""
        if not self.item:
            return
        await self.hass.async_add_executor_job(
            self.coordinator.api.openhab.req_post, f"/items/{self._id}", "OFF"
        )
        # Don't request refresh - SSE will provide the update

"""
Custom integration to integrate openHAB with Home Assistant.

For more details about this integration, please refer to
https://github.com/kubawolanin/ha-openhab
"""
import functools

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import OpenHABApiClient
from .const import (
    CONF_AUTH_TOKEN,
    CONF_AUTH_TYPE,
    CONF_BASE_URL,
    CONF_PASSWORD,
    CONF_USERNAME,
    LOGGER,
    PLATFORMS,
    STARTUP_MESSAGE,
)
from .coordinator import OpenHABDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Set up this integration using UI."""
    LOGGER.info(STARTUP_MESSAGE)
    # Run the constructor in an executor: OpenHABApiClient.__init__ calls
    # CreateOpenHab() which loads SSL certificates — a blocking operation
    # that must not run on the event loop thread (HA 2026.x enforces this).
    api_client = await hass.async_add_executor_job(
        functools.partial(
            OpenHABApiClient,
            hass,
            entry.data[CONF_BASE_URL],
            entry.data[CONF_AUTH_TYPE],
            entry.data.get(CONF_AUTH_TOKEN, ""),
            entry.data.get(CONF_USERNAME, ""),
            entry.data.get(CONF_PASSWORD, ""),
        )
    )

    if api_client.openhab == False:
        LOGGER.info("OpenHab Recreating Oauth2 Token")
        api_client._creating_token = True
        await api_client.async_get_auth2_token()
        await hass.async_add_executor_job(api_client.CreateOpenHab)

    coordinator = OpenHABDataUpdateCoordinator(hass, api=api_client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    for platform in PLATFORMS:
        if entry.options.get(platform, True):
            coordinator.platforms.append(platform)
            #hass.async_add_job(
            #    hass.config_entries.async_forward_entry_setup(entry, platform)
            #)
    await hass.config_entries.async_forward_entry_setups(entry, coordinator.platforms)

    entry.add_update_listener(async_reload_entry)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the config entry."""
    coordinator: OpenHABDataUpdateCoordinator = entry.runtime_data

    # Shutdown SSE listener before unloading
    await coordinator.async_shutdown()

    return await hass.config_entries.async_unload_platforms(
        entry, [platform for platform in PLATFORMS if platform in coordinator.platforms]
    )


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)

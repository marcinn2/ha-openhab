"""Data update coordinator for integration openHAB."""
from __future__ import annotations

from typing import Any
import asyncio
import aiohttp
import json
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.debounce import Debouncer

from .api import ApiClientException, OpenHABApiClient
from .const import DATA_COORDINATOR_UPDATE_INTERVAL, DOMAIN, LOGGER


class OpenHABDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, api: OpenHABApiClient) -> None:
        """Initialize."""
        self.api = api
        self.platforms: list[str] = []
        self.version: str = ""
        self.is_online = False
        self.ha_items = {}
        self._sse_listener_task = None
        self._stop_sse = False
        self._sse_session = None
        self._sse_started = False

        # Echo suppression: tracks commands explicitly sent by this integration.
        # Populated via track_ha_command() which entity platforms call right
        # before they send a command through the HA REST API.  SSE-based
        # ItemCommandEvents are NOT used for this because the SSE stream does
        # not expose a reliable source field to distinguish HA-originated
        # commands from external ones (openHAB rules, other integrations, etc.).
        self._recent_commands: dict[str, float] = {}
        self._command_ignore_duration = 2.0  # seconds

        # Fallback debouncer: only used when direct SSE state update fails
        # (unknown item, parse error) to trigger a full API refresh.
        self._refresh_debouncer = Debouncer(
            hass,
            LOGGER,
            cooldown=2.0,
            immediate=False,
            function=self._async_refresh_debounced,
        )

        # Start with normal polling; disabled inside _listen_sse_events() only
        # after a confirmed successful SSE connection (HTTP 200).
        super().__init__(
            hass,
            logger=LOGGER,
            name=DOMAIN,
            update_interval=DATA_COORDINATOR_UPDATE_INTERVAL,
        )

    async def _async_refresh_debounced(self) -> None:
        """Debounced full API refresh (fallback path only)."""
        await self.async_request_refresh()

    # ------------------------------------------------------------------
    # Public API for entity platforms
    # ------------------------------------------------------------------

    def track_ha_command(self, item_name: str) -> None:
        """Record that this integration just sent a command for item_name.

        Call this immediately before sending a command via the openHAB REST API
        so that the resulting ItemStateChangedEvent/ItemStateUpdatedEvent from
        the SSE stream can be identified as an echo and suppressed.
        """
        self._recent_commands[item_name] = time.time()
        LOGGER.debug(
            "Echo suppression armed for %s (%.1fs window)",
            item_name,
            self._command_ignore_duration,
        )

    # ------------------------------------------------------------------
    # SSE startup / polling management
    # ------------------------------------------------------------------

    def _start_sse_after_first_refresh(self) -> None:
        """Start SSE listener task after first successful data refresh.

        Polling is NOT disabled here; it is disabled inside _listen_sse_events()
        only after a confirmed HTTP 200 response from the SSE endpoint so that
        polling continues as a fallback if the SSE handshake fails.
        """
        if not self._sse_started and self.api._base_url:
            self._sse_started = True
            self._sse_listener_task = self.hass.async_create_background_task(
                self._listen_sse_events(),
                name="openhab_sse_listener",
            )
            LOGGER.info("SSE listener task created")

    def _enable_polling(self) -> None:
        """Re-enable periodic polling as a fallback while SSE is not connected.

        Called from SSE error paths (non-200 response, connection exception) so
        that entities are kept up-to-date while the SSE listener retries.
        Restoring update_interval alone is not enough - we also trigger an
        immediate refresh so the HA scheduler re-arms itself at the end of that
        refresh cycle.
        """
        if self.update_interval is None:
            self.update_interval = DATA_COORDINATOR_UPDATE_INTERVAL
            LOGGER.info(
                "SSE unavailable - polling re-enabled at %s interval",
                DATA_COORDINATOR_UPDATE_INTERVAL,
            )
            # async_request_refresh() re-schedules the next poll at the end of
            # _async_refresh(), which honours the restored update_interval.
            self.hass.async_create_task(self.async_request_refresh())

    # ------------------------------------------------------------------
    # Direct state injection
    # ------------------------------------------------------------------

    def _update_item_from_sse_payload(self, item_name: str, payload_str: str) -> bool:
        """Parse SSE event payload and update the item state in self.data directly.

        Returns True when the item was found and updated successfully.
        No API call is made; self.data is mutated in-place and callers
        must follow up with async_set_updated_data(self.data).

        Exception handling policy for item._parse_value():
        - NotImplementedError / AttributeError: item type has no _parse_value
          implementation (e.g. bare GroupItem); store raw string as graceful
          degradation and return True so the caller does NOT fall back to a
          full API refresh (the entity will display the raw value).
        - ValueError / TypeError: the value string is present but malformed for
          this item type; propagate to the outer handler so the method returns
          False and the fallback API refresh runs.
        - Any other Exception from json.loads / payload parsing: caught by the
          outer handler; return False to trigger the fallback refresh.
        """
        if not self.data or item_name not in self.data:
            return False

        try:
            payload = json.loads(payload_str)
            raw_value = payload.get("value")
            if raw_value is None:
                return False

            item = self.data[item_name]
            item._raw_state = raw_value

            try:
                # Each Item subclass implements _parse_value() to convert the
                # raw string to the typed _state representation.
                item._state = item._parse_value(raw_value)
            except (NotImplementedError, AttributeError):
                # Item type has no _parse_value; store raw string as fallback.
                item._state = raw_value
            # ValueError / TypeError are intentionally NOT caught here so they
            # propagate to the outer except and cause this method to return False.

            LOGGER.debug("SSE direct update: %s = %s", item_name, raw_value)
            return True

        except Exception as err:  # noqa: BLE001
            LOGGER.debug(
                "Could not parse SSE payload for item %s: %s",
                item_name,
                err,
            )
            return False

    # ------------------------------------------------------------------
    # SSE listener
    # ------------------------------------------------------------------

    async def _listen_sse_events(self) -> None:
        """Listen to openHAB SSE events and update entity states in real-time."""
        sse_url = f"{self.api._rest_url}/events"

        retry_delay = 5
        first_connect = True

        while not self._stop_sse:
            try:
                auth = None
                headers = {}

                if self.api._auth_type == "token" and self.api._auth_token:
                    headers["X-OPENHAB-TOKEN"] = self.api._auth_token
                elif self.api._auth_type == "OAuth2":
                    # Prefer OAuth2 bearer token (required by openHAB 3+).
                    # Fall back to HTTP Basic auth if no token is cached yet.
                    bearer = self.api.get_bearer_token()
                    if bearer:
                        headers["Authorization"] = f"Bearer {bearer}"
                    elif self.api._username:
                        auth = aiohttp.BasicAuth(self.api._username, self.api._password)

                if not self._sse_session:
                    self._sse_session = aiohttp.ClientSession()

                LOGGER.debug("Connecting to SSE endpoint: %s", sse_url)

                async with self._sse_session.get(
                    sse_url,
                    headers=headers,
                    auth=auth,
                    timeout=aiohttp.ClientTimeout(total=None, sock_read=300),
                ) as response:

                    if response.status != 200:
                        error_text = await response.text()
                        LOGGER.error(
                            "SSE connection failed with status %s: %s",
                            response.status,
                            error_text,
                        )
                        # Re-enable polling so entities are updated while retrying.
                        self._enable_polling()
                        await asyncio.sleep(retry_delay)
                        continue

                    # Connection confirmed - disable polling now that SSE is live.
                    if self.update_interval is not None:
                        self.update_interval = None
                        LOGGER.warning(
                            "SSE connection established - polling disabled, "
                            "SSE is the sole update source"
                        )
                    else:
                        LOGGER.warning("SSE reconnected")

                    # After a reconnect, fetch fresh data from the API to catch
                    # any state changes that occurred while SSE was disconnected.
                    if not first_connect:
                        LOGGER.info("SSE reconnected - triggering full refresh")
                        await self._refresh_debouncer.async_call()
                    first_connect = False

                    event_data: dict = {}

                    async for line in response.content:
                        if self._stop_sse:
                            break

                        try:
                            decoded = line.decode("utf-8").strip()

                            if not decoded:
                                # Empty line = end of one SSE event block
                                if event_data:
                                    await self._process_sse_event(event_data)
                                    event_data = {}
                                continue

                            if ":" in decoded:
                                field, _, value = decoded.partition(":")
                                field = field.strip()
                                value = value.strip()

                                if field == "data":
                                    try:
                                        data = json.loads(value)
                                        event_data.update(data)
                                    except json.JSONDecodeError:
                                        pass
                                elif field in ("event", "id"):
                                    event_data[field] = value

                        except Exception as err:  # noqa: BLE001
                            LOGGER.debug("Error processing SSE line: %s", err)

                    # The async-for loop exits when the server closes the connection
                    # cleanly (no exception).  Re-enable polling so items stay fresh
                    # during the reconnect gap, and wait before retrying.
                    if not self._stop_sse:
                        LOGGER.warning(
                            "SSE connection closed by server, reconnecting in %s s",
                            retry_delay,
                        )
                        self._enable_polling()
                        await asyncio.sleep(retry_delay)

            except asyncio.CancelledError:
                LOGGER.info("SSE listener cancelled")
                break

            except Exception as err:  # noqa: BLE001
                if not self._stop_sse:
                    LOGGER.warning(
                        "SSE connection error: %s (retrying in %s seconds)",
                        err,
                        retry_delay,
                    )
                    # Re-enable polling so entities are updated while retrying.
                    self._enable_polling()
                    await asyncio.sleep(retry_delay)

        LOGGER.info("SSE listener stopped")

    # ------------------------------------------------------------------
    # SSE event processing
    # ------------------------------------------------------------------

    def _prune_recent_commands(self) -> None:
        """Remove expired entries from _recent_commands.

        Called at every exit point of _process_sse_event() so timestamps never
        accumulate under high-echo-traffic conditions.
        """
        if not self._recent_commands:
            return
        now = time.time()
        expired = [
            k
            for k, v in self._recent_commands.items()
            if (now - v) > self._command_ignore_duration
        ]
        for k in expired:
            del self._recent_commands[k]

    async def _process_sse_event(self, event_data: dict) -> None:
        """Process a single parsed SSE event from openHAB.

        For ItemStateChangedEvent / ItemStateUpdatedEvent:
          1. Check echo suppression (only for commands tracked via track_ha_command).
          2. Try to update the item state directly in self.data (no API call).
          3. Call async_set_updated_data() so all HA entity listeners fire immediately.
          4. Fall back to a debounced full API refresh when the item is unknown
             or the payload cannot be parsed.

        ItemCommandEvent is intentionally ignored here because the SSE stream
        does not expose a reliable source field; echo suppression is handled
        exclusively through track_ha_command().
        """
        event_type = event_data.get("type", "")
        topic = event_data.get("topic", "")

        # Extract item name from topic, e.g. "openhab/items/MySwitch/statechanged"
        parts = topic.split("/")
        item_name = parts[-2] if len(parts) >= 2 and "items/" in topic else None

        if not item_name:
            return

        # --- State change / update events ---
        # ItemStateChangedEvent  - OH3 + OH4: fires only when value actually changes
        # ItemStateUpdatedEvent  - OH4: fires on every update (even if same value)
        # ItemStateEvent         - OH3: equivalent of OH4's ItemStateUpdatedEvent
        if event_type in ("ItemStateChangedEvent", "ItemStateUpdatedEvent", "ItemStateEvent"):
            # Suppress echo events for commands explicitly sent by this integration.
            cmd_time = self._recent_commands.get(item_name)
            if cmd_time and (time.time() - cmd_time) < self._command_ignore_duration:
                LOGGER.debug(
                    "SSE echo suppressed for %s (%s)",
                    item_name,
                    event_type,
                )
                self._prune_recent_commands()
                return

            payload_str = event_data.get("payload", "")

            if payload_str and self._update_item_from_sse_payload(item_name, payload_str):
                # Notify only the specific entity that changed, not the whole
                # coordinator (which would write HA state for every entity).
                entity = self.ha_items.get(item_name)
                if entity is not None:
                    entity.async_write_ha_state()
                else:
                    # Entity not registered yet — fall back to full coordinator notify.
                    self.async_set_updated_data(self.data)
            else:
                # Fallback: item not yet loaded or payload malformed.
                LOGGER.warning(
                    "SSE direct update failed for %s (type=%s) - falling back to API refresh",
                    item_name,
                    event_type,
                )
                await self._refresh_debouncer.async_call()

        self._prune_recent_commands()

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def async_shutdown(self) -> None:
        """Shutdown the coordinator and stop SSE listener."""
        LOGGER.info("Shutting down openHAB coordinator")
        self._stop_sse = True

        if self._refresh_debouncer is not None:
            self._refresh_debouncer.async_shutdown()

        if self._sse_listener_task and not self._sse_listener_task.done():
            self._sse_listener_task.cancel()
            try:
                await self._sse_listener_task
            except asyncio.CancelledError:
                pass

        if self._sse_session:
            await self._sse_session.close()
            self._sse_session = None

    # ------------------------------------------------------------------
    # Coordinator data fetch (polling path - active until SSE connects)
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        """Update data via library.

        Polling is active until _listen_sse_events() disables it after a
        confirmed SSE connection. After that this method may still be invoked
        explicitly via async_request_refresh() as a fallback (e.g. on reconnect).

        All exceptions - including connection errors and timeouts - are caught
        and re-raised as UpdateFailed so that async_config_entry_first_refresh()
        converts them into ConfigEntryNotReady.  This causes HA to automatically
        retry setup instead of marking the integration as permanently broken
        (setup_error), which is the correct behaviour when openHAB is simply not
        yet reachable at HA startup time (e.g. after a fast HACS-triggered restart
        where openHAB needs a few extra seconds to come up).
        """
        try:
            if self.version is None or len(self.version) == 0:
                self.version = await self.api.async_get_version()

            items = await self.api.async_get_items()
            self.is_online = bool(items)

            LOGGER.info("Coordinator fetched %d items from openHAB", len(items))
            if not items:
                raise UpdateFailed("openHAB returned no items — check openHAB is running and items are configured")

            # Log item type distribution for debugging
            item_types: dict = {}
            items_with_none_type: list = []
            for item_name, item in items.items():
                item_type = item.type_
                item_types[item_type] = item_types.get(item_type, 0) + 1
                if item_type is None:
                    group_type = getattr(item, "groupType", "NO_GROUPTYPE")
                    items_with_none_type.append(
                        f"{item_name} ({type(item).__name__}, groupType={group_type})"
                    )

            LOGGER.info("Item types distribution: %s", item_types)

            if items_with_none_type:
                LOGGER.warning(
                    "Items with None type (first 10): %s",
                    items_with_none_type[:10],
                )

            # Start SSE listener after first successful fetch
            if items and not self._sse_started:
                self._start_sse_after_first_refresh()

            return items

        except ApiClientException as exception:
            raise UpdateFailed(exception) from exception
        except UpdateFailed:
            raise
        except Exception as exception:  # noqa: BLE001
            raise UpdateFailed(
                f"Unexpected error communicating with openHAB: {exception}"
            ) from exception

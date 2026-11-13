"""The BUSY Bar integration."""

from __future__ import annotations

import logging
import time
from typing import Any

import voluptuous as vol
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .api import BusyBarError, BusyBarPriorityError
from .const import (
    ALIGNMENTS,
    ATTR_CONFIG_ENTRY_ID,
    BUSY_SLOTS,
    COUNTDOWN_DIRECTIONS,
    COUNTDOWN_SHOW_HOURS,
    DISPLAY_FRONT,
    DISPLAYS,
    DOMAIN,
    FILL_STYLES,
    FONTS,
    KEYS,
    SERVICE_CLEAR,
    SERVICE_DRAW,
    SERVICE_DRAW_COUNTDOWN,
    SERVICE_DRAW_IMAGE,
    SERVICE_DRAW_RECTANGLE,
    SERVICE_DRAW_TEXT,
    SERVICE_PLAY_SOUND,
    SERVICE_PRESS_KEY,
    SERVICE_START_TIMER,
    SERVICE_STOP_TIMER,
    TIMER_TYPE_INFINITE,
    TIMER_TYPE_INTERVAL,
    TIMER_TYPE_NOT_STARTED,
    TIMER_TYPE_SIMPLE,
)
from .coordinator import BusyBarConfigEntry, BusyBarCoordinator
from .draw import (
    build_countdown_element,
    build_image_element,
    build_payload,
    build_rectangle_element,
    build_text_element,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CAMERA,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TEXT,
]

# Fields that place an element on a panel. Shared by every draw service so the
# same words mean the same thing everywhere.
_PLACEMENT_SCHEMA = {
    vol.Optional("display", default=DISPLAY_FRONT): vol.In(DISPLAYS),
    vol.Optional("align", default="center"): vol.In(ALIGNMENTS),
    vol.Optional("x"): vol.All(vol.Coerce(int), vol.Range(min=-4096, max=4095)),
    vol.Optional("y"): vol.All(vol.Coerce(int), vol.Range(min=-4096, max=4095)),
    vol.Optional("timeout"): cv.positive_int,
    vol.Optional("display_until"): vol.Any(cv.datetime, cv.positive_int, cv.string),
    vol.Optional("z_index"): cv.positive_int,
    vol.Optional("element_id"): cv.string,
    vol.Optional("priority"): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
    vol.Optional("led_color"): cv.string,
    vol.Optional("clear_first", default=False): cv.boolean,
}

_TARGET_SCHEMA = {
    vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    vol.Optional("device_id"): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional("entity_id"): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional("area_id"): vol.All(cv.ensure_list, [cv.string]),
}

DRAW_TEXT_SCHEMA = vol.Schema(
    {
        **_TARGET_SCHEMA,
        **_PLACEMENT_SCHEMA,
        vol.Required("text"): cv.string,
        vol.Optional("font", default="normal"): vol.In(FONTS),
        vol.Optional("color"): cv.string,
        vol.Optional("width"): cv.positive_int,
        vol.Optional("scroll", default=True): cv.boolean,
        vol.Optional("scroll_rate"): cv.positive_int,
        vol.Optional("scroll_start_delay"): cv.positive_int,
        vol.Optional("scroll_repeat_delay"): cv.positive_int,
    }
)

DRAW_COUNTDOWN_SCHEMA = vol.Schema(
    {
        **_TARGET_SCHEMA,
        **_PLACEMENT_SCHEMA,
        vol.Required("timestamp"): vol.Any(cv.datetime, cv.positive_int, cv.string),
        vol.Optional("direction", default="time_left"): vol.In(COUNTDOWN_DIRECTIONS),
        vol.Optional("show_hours", default="when_non_zero"): vol.In(
            COUNTDOWN_SHOW_HOURS
        ),
        vol.Optional("color"): cv.string,
    }
)

DRAW_RECTANGLE_SCHEMA = vol.Schema(
    {
        **_TARGET_SCHEMA,
        **_PLACEMENT_SCHEMA,
        vol.Required("width"): cv.positive_int,
        vol.Required("height"): cv.positive_int,
        vol.Optional("radius"): cv.positive_int,
        vol.Optional("fill", default="solid"): vol.In(FILL_STYLES),
        vol.Optional("fill_colors"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("border_width"): cv.positive_int,
        vol.Optional("border_color"): cv.string,
    }
)

DRAW_IMAGE_SCHEMA = vol.Schema(
    {
        **_TARGET_SCHEMA,
        **_PLACEMENT_SCHEMA,
        vol.Exclusive("path", "source"): cv.string,
        vol.Exclusive("stock_path", "source"): cv.string,
        vol.Optional("animation", default=False): cv.boolean,
        vol.Optional("loop"): cv.boolean,
        vol.Optional("section"): cv.string,
        vol.Optional("opacity"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
    }
)

DRAW_SCHEMA = vol.Schema(
    {
        **_TARGET_SCHEMA,
        vol.Required("elements"): vol.All(cv.ensure_list, [dict], vol.Length(min=1)),
        vol.Optional("priority"): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
        vol.Optional("led_color"): cv.string,
        vol.Optional("clear_first", default=False): cv.boolean,
    }
)

CLEAR_SCHEMA = vol.Schema(
    {
        **_TARGET_SCHEMA,
        vol.Optional("element_ids"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("everything", default=False): cv.boolean,
    }
)

PLAY_SOUND_SCHEMA = vol.Schema(
    {
        **_TARGET_SCHEMA,
        vol.Exclusive("path", "source"): cv.string,
        vol.Exclusive("stock_path", "source"): cv.string,
    }
)

PRESS_KEY_SCHEMA = vol.Schema({**_TARGET_SCHEMA, vol.Required("key"): vol.In(KEYS)})

START_TIMER_SCHEMA = vol.Schema(
    {
        **_TARGET_SCHEMA,
        vol.Optional("slot", default="busy"): vol.In(BUSY_SLOTS),
        vol.Optional("duration"): vol.Any(cv.positive_time_period, cv.positive_int),
    }
)

STOP_TIMER_SCHEMA = vol.Schema(dict(_TARGET_SCHEMA))


async def async_setup_entry(hass: HomeAssistant, entry: BusyBarConfigEntry) -> bool:
    """Set up a BUSY Bar from a config entry."""
    coordinator = BusyBarCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BusyBarConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: BusyBarConfigEntry) -> None:
    """Reload when the options change."""
    await hass.config_entries.async_reload(entry.entry_id)


# -- Target resolution -------------------------------------------------------


def _async_coordinators(hass: HomeAssistant, call: ServiceCall) -> list[BusyBarCoordinator]:
    """Work out which bars a service call is aimed at.

    Any of the usual targets work -- a device, an entity, an area -- and so does
    a bare ``config_entry_id``. With no target at all and exactly one bar set up,
    that one is used, because naming it every time would be ceremony.
    """
    loaded = hass.config_entries.async_loaded_entries(DOMAIN)
    if not loaded:
        raise ServiceValidationError("No BUSY Bar is set up")

    wanted: set[str] = set()

    if entry_id := call.data.get(ATTR_CONFIG_ENTRY_ID):
        wanted.add(entry_id)

    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)

    device_ids = set(call.data.get("device_id") or [])
    for area_id in call.data.get("area_id") or []:
        device_ids.update(
            device.id for device in dr.async_entries_for_area(device_reg, area_id)
        )
    for device_id in device_ids:
        device = device_reg.async_get(device_id)
        if device is None:
            continue
        wanted.update(device.config_entries)

    for entity_id in call.data.get("entity_id") or []:
        entity = entity_reg.async_get(entity_id)
        if entity is not None and entity.config_entry_id:
            wanted.add(entity.config_entry_id)

    if not wanted:
        if len(loaded) == 1:
            return [loaded[0].runtime_data]
        raise ServiceValidationError(
            "Several BUSY Bars are set up, so the call needs a target device"
        )

    coordinators = [entry.runtime_data for entry in loaded if entry.entry_id in wanted]
    if not coordinators:
        raise ServiceValidationError(
            "The target does not resolve to a BUSY Bar that is currently loaded"
        )
    return coordinators


# -- Service helpers ---------------------------------------------------------


def _element_id(call: ServiceCall, fallback: str) -> str:
    """The element id to draw under, defaulting per service."""
    return call.data.get("element_id") or fallback


def _placement(call: ServiceCall) -> dict[str, Any]:
    """Pull the shared placement fields out of a call."""
    return {
        "display": call.data["display"],
        "align": call.data["align"],
        "x": call.data.get("x"),
        "y": call.data.get("y"),
        "timeout": call.data.get("timeout"),
        "display_until": (
            _as_unix_seconds(call.data["display_until"])
            if "display_until" in call.data
            else None
        ),
        "z_index": call.data.get("z_index"),
    }


def _as_unix_seconds(value: Any) -> int:
    """Coerce a timestamp field to Unix seconds.

    Accepts what templates actually produce: an integer timestamp, a datetime
    object, or an ISO string.
    """
    if isinstance(value, (int, float)):
        return int(value)
    if hasattr(value, "timestamp"):
        return int(dt_util.as_utc(value).timestamp())
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    parsed = dt_util.parse_datetime(text)
    if parsed is None:
        raise ServiceValidationError(
            f"{value!r} is not a timestamp; use a datetime or Unix seconds"
        )
    return int(dt_util.as_utc(parsed).timestamp())


def _duration_seconds(value: Any) -> int:
    """Coerce a duration field to whole seconds."""
    if hasattr(value, "total_seconds"):
        return int(value.total_seconds())
    return int(value)


async def _async_draw(
    coordinator: BusyBarCoordinator,
    call: ServiceCall,
    elements: list[dict[str, Any]],
) -> None:
    """Send elements to one bar, optionally wiping our previous ones first."""
    if call.data.get("clear_first"):
        try:
            await coordinator.client.async_clear(app_name=coordinator.app_name)
        except BusyBarError as err:
            _LOGGER.debug("Pre-draw clear on %s failed: %s", coordinator.host, err)

    payload = build_payload(
        coordinator.app_name,
        elements,
        priority=call.data.get("priority") or coordinator.default_priority,
        led_color=call.data.get("led_color"),
    )
    try:
        await coordinator.client.async_draw(payload)
    except BusyBarPriorityError as err:
        raise HomeAssistantError(
            f"{coordinator.host} refused the draw: {err}. Raise priority above "
            "the running app -- an active BUSY session sits at 90."
        ) from err
    except BusyBarError as err:
        raise HomeAssistantError(f"Draw on {coordinator.host} failed: {err}") from err


def _async_register_services(hass: HomeAssistant) -> None:
    """Register the integration-wide services once."""
    if hass.services.has_service(DOMAIN, SERVICE_DRAW_TEXT):
        return

    async def _draw_text(call: ServiceCall) -> None:
        """Put a line of text on a display."""
        for coordinator in _async_coordinators(hass, call):
            element = build_text_element(
                _element_id(call, "ha_message"),
                call.data["text"],
                font=call.data["font"],
                color=call.data.get("color"),
                width=call.data.get("width"),
                scroll=call.data["scroll"],
                scroll_rate=call.data.get("scroll_rate"),
                scroll_start_delay=call.data.get("scroll_start_delay"),
                scroll_repeat_delay=call.data.get("scroll_repeat_delay"),
                **_placement(call),
            )
            await _async_draw(coordinator, call, [element])

    async def _draw_countdown(call: ServiceCall) -> None:
        """Put a clock on a display that the device ticks itself."""
        for coordinator in _async_coordinators(hass, call):
            element = build_countdown_element(
                _element_id(call, "ha_countdown"),
                _as_unix_seconds(call.data["timestamp"]),
                direction=call.data["direction"],
                show_hours=call.data["show_hours"],
                color=call.data.get("color"),
                **_placement(call),
            )
            await _async_draw(coordinator, call, [element])

    async def _draw_rectangle(call: ServiceCall) -> None:
        """Draw a filled or outlined box."""
        for coordinator in _async_coordinators(hass, call):
            element = build_rectangle_element(
                _element_id(call, "ha_rectangle"),
                call.data["width"],
                call.data["height"],
                radius=call.data.get("radius"),
                fill=call.data["fill"],
                fill_colors=call.data.get("fill_colors"),
                border_width=call.data.get("border_width"),
                border_color=call.data.get("border_color"),
                **_placement(call),
            )
            await _async_draw(coordinator, call, [element])

    async def _draw_image(call: ServiceCall) -> None:
        """Draw an uploaded or stock image or animation."""
        for coordinator in _async_coordinators(hass, call):
            element = build_image_element(
                _element_id(call, "ha_image"),
                path=call.data.get("path"),
                stock_path=call.data.get("stock_path"),
                animation=call.data["animation"],
                loop=call.data.get("loop"),
                section=call.data.get("section"),
                opacity=call.data.get("opacity"),
                **_placement(call),
            )
            await _async_draw(coordinator, call, [element])

    async def _draw(call: ServiceCall) -> None:
        """Send raw DisplayElements, for scenes the helpers do not cover."""
        for coordinator in _async_coordinators(hass, call):
            await _async_draw(coordinator, call, list(call.data["elements"]))

    async def _clear(call: ServiceCall) -> None:
        """Remove drawn elements."""
        for coordinator in _async_coordinators(hass, call):
            # Scoping the clear to our own application_name is the safe default:
            # it leaves elements another script or app drew alone.
            app_name = None if call.data["everything"] else coordinator.app_name
            try:
                await coordinator.client.async_clear(
                    app_name=app_name, element_ids=call.data.get("element_ids")
                )
            except BusyBarError as err:
                raise HomeAssistantError(
                    f"Clearing {coordinator.host} failed: {err}"
                ) from err

    async def _play_sound(call: ServiceCall) -> None:
        """Play a sound on the bar."""
        if not call.data.get("path") and not call.data.get("stock_path"):
            raise ServiceValidationError("Either path or stock_path is required")
        for coordinator in _async_coordinators(hass, call):
            try:
                await coordinator.client.async_play_sound(
                    coordinator.app_name,
                    path=call.data.get("path"),
                    stock_path=call.data.get("stock_path"),
                )
            except BusyBarError as err:
                raise HomeAssistantError(
                    f"Playing sound on {coordinator.host} failed: {err}"
                ) from err

    async def _press_key(call: ServiceCall) -> None:
        """Inject a key press."""
        for coordinator in _async_coordinators(hass, call):
            try:
                await coordinator.client.async_press_key(call.data["key"])
            except BusyBarError as err:
                raise HomeAssistantError(
                    f"Key press on {coordinator.host} failed: {err}"
                ) from err
            await coordinator.async_request_refresh()

    async def _start_timer(call: ServiceCall) -> None:
        """Start a BUSY session from one of the device's two profile slots."""
        slot = call.data["slot"]
        duration = (
            _duration_seconds(call.data["duration"])
            if "duration" in call.data
            else None
        )
        for coordinator in _async_coordinators(hass, call):
            try:
                profile = await coordinator.client.async_get_busy_profile(slot)
                snapshot = _snapshot_from_profile(profile, duration)
                await coordinator.client.async_set_busy_snapshot(
                    {
                        "snapshot": snapshot,
                        "snapshot_timestamp_ms": int(time.time() * 1000),
                    }
                )
            except BusyBarError as err:
                raise HomeAssistantError(
                    f"Starting the timer on {coordinator.host} failed: {err}"
                ) from err
            await coordinator.async_request_refresh()

    async def _stop_timer(call: ServiceCall) -> None:
        """End the running session and return the bar to idle."""
        for coordinator in _async_coordinators(hass, call):
            try:
                settings = await _async_bar_settings(coordinator)
                await coordinator.client.async_set_busy_snapshot(
                    {
                        "snapshot": {
                            "type": TIMER_TYPE_NOT_STARTED,
                            "busy_bar_settings": settings,
                        },
                        "snapshot_timestamp_ms": int(time.time() * 1000),
                    }
                )
            except BusyBarError as err:
                raise HomeAssistantError(
                    f"Stopping the timer on {coordinator.host} failed: {err}"
                ) from err
            await coordinator.async_request_refresh()

    for name, handler, schema in (
        (SERVICE_DRAW_TEXT, _draw_text, DRAW_TEXT_SCHEMA),
        (SERVICE_DRAW_COUNTDOWN, _draw_countdown, DRAW_COUNTDOWN_SCHEMA),
        (SERVICE_DRAW_RECTANGLE, _draw_rectangle, DRAW_RECTANGLE_SCHEMA),
        (SERVICE_DRAW_IMAGE, _draw_image, DRAW_IMAGE_SCHEMA),
        (SERVICE_DRAW, _draw, DRAW_SCHEMA),
        (SERVICE_CLEAR, _clear, CLEAR_SCHEMA),
        (SERVICE_PLAY_SOUND, _play_sound, PLAY_SOUND_SCHEMA),
        (SERVICE_PRESS_KEY, _press_key, PRESS_KEY_SCHEMA),
        (SERVICE_START_TIMER, _start_timer, START_TIMER_SCHEMA),
        (SERVICE_STOP_TIMER, _stop_timer, STOP_TIMER_SCHEMA),
    ):
        hass.services.async_register(DOMAIN, name, handler, schema=schema)


async def _async_bar_settings(coordinator: BusyBarCoordinator) -> dict[str, Any]:
    """Find a ``busy_bar_settings`` block to reuse.

    Every snapshot the device accepts carries one, including NOT_STARTED. Reuse
    whatever the running session has so stopping a timer does not silently change
    the theme; fall back to the BUSY profile's own settings when idle.
    """
    snapshot = await coordinator.client.async_get_busy_snapshot()
    inner = snapshot.get("snapshot") or {}
    if settings := inner.get("busy_bar_settings"):
        return settings
    profile = await coordinator.client.async_get_busy_profile("busy")
    return profile.get("busy_bar_settings") or {
        "theme": "on_air",
        "show_work_phase_only": False,
        "trigger_smart_home": True,
    }


def _snapshot_from_profile(
    profile: dict[str, Any], duration: int | None
) -> dict[str, Any]:
    """Turn a stored profile into a snapshot the device will run.

    A ``duration`` overrides whatever the profile says and runs a plain countdown,
    which is what an automation usually wants ("go busy for 25 minutes"). Without
    one, the profile's own timer settings are honoured, interval cycles included.
    """
    card_id = profile.get("id")
    if not card_id:
        raise HomeAssistantError("The profile slot has no card id to start")

    settings = profile.get("busy_bar_settings") or {}
    base: dict[str, Any] = {
        "card_id": card_id,
        "is_paused": False,
        "busy_bar_settings": settings,
    }

    if duration is not None:
        if duration <= 0:
            raise ServiceValidationError("Duration must be longer than zero")
        return {**base, "type": TIMER_TYPE_SIMPLE, "time_left_ms": duration * 1000}

    timer = profile.get("timer_settings") or {}
    timer_type = timer.get("type")

    if timer_type == TIMER_TYPE_INFINITE:
        return {**base, "type": TIMER_TYPE_INFINITE}
    if timer_type == TIMER_TYPE_SIMPLE:
        return {
            **base,
            "type": TIMER_TYPE_SIMPLE,
            "time_left_ms": timer.get("total_time_ms", 0),
        }
    if timer_type == TIMER_TYPE_INTERVAL:
        work_ms = timer.get("interval_work_ms", 0)
        return {
            **base,
            "type": TIMER_TYPE_INTERVAL,
            "current_interval": 1,
            "current_interval_time_total_ms": work_ms,
            "current_interval_time_left_ms": work_ms,
            "interval_settings": timer,
        }
    raise HomeAssistantError(
        f"Profile uses timer type {timer_type!r}, which this integration cannot "
        "start; pass a duration instead"
    )

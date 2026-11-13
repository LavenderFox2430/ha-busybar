"""Polling coordinator for the BUSY Bar integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    BusyBarAuthError,
    BusyBarClient,
    BusyBarError,
)
from .const import (
    CONF_APP_NAME,
    CONF_DEFAULT_PRIORITY,
    DEFAULT_APP_NAME,
    DEFAULT_PORT,
    DEFAULT_PRIORITY,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    TIMER_TYPE_INTERVAL,
    TIMER_TYPE_NOT_STARTED,
    TIMER_TYPE_SIMPLE,
)

_LOGGER = logging.getLogger(__name__)

type BusyBarConfigEntry = ConfigEntry[BusyBarCoordinator]


@dataclass(slots=True)
class BusyBarData:
    """One poll's worth of device state.

    Every block except ``status`` is optional: a device with Wi-Fi off or with a
    broken Matter stack answers 503 on those endpoints, and that should cost us
    a few entities rather than the whole integration.
    """

    device: dict[str, Any] = field(default_factory=dict)
    firmware: dict[str, Any] = field(default_factory=dict)
    system: dict[str, Any] = field(default_factory=dict)
    power: dict[str, Any] = field(default_factory=dict)
    wifi: dict[str, Any] = field(default_factory=dict)
    snapshot: dict[str, Any] = field(default_factory=dict)
    smart_home: dict[str, Any] | None = None
    name: str | None = None
    brightness: str | None = None
    volume: float | None = None
    fetched_at: datetime | None = None

    @property
    def timer_type(self) -> str:
        """The running timer's kind, or NOT_STARTED when idle."""
        return self.snapshot.get("type") or TIMER_TYPE_NOT_STARTED

    @property
    def timer_running(self) -> bool:
        """True while a BUSY or CUSTOM session is active, paused included."""
        return self.timer_type != TIMER_TYPE_NOT_STARTED

    @property
    def timer_paused(self) -> bool:
        """True while an active session is on hold."""
        return bool(self.snapshot.get("is_paused"))

    @property
    def time_left_ms(self) -> int | None:
        """Milliseconds left in the current phase, if the timer has an end.

        SIMPLE reports the whole session, INTERVAL only the current work or rest
        phase, and INFINITE has nothing to report.
        """
        if self.timer_type == TIMER_TYPE_SIMPLE:
            return self.snapshot.get("time_left_ms")
        if self.timer_type == TIMER_TYPE_INTERVAL:
            return self.snapshot.get("current_interval_time_left_ms")
        return None

    @property
    def ends_at(self) -> datetime | None:
        """When the current phase ends, in wall-clock terms.

        Derived from our own receive time rather than the device's
        ``snapshot_timestamp_ms``, so a device whose clock has drifted does not
        produce a timestamp sensor that disagrees with Home Assistant. A paused
        timer has no end time.
        """
        left = self.time_left_ms
        if left is None or self.fetched_at is None or self.timer_paused:
            return None
        return self.fetched_at + timedelta(milliseconds=left)

    @property
    def brightness_is_auto(self) -> bool:
        """True when the ambient light sensor drives the brightness."""
        return self.brightness == "auto"

    @property
    def brightness_value(self) -> int | None:
        """The manual brightness percentage, or None while on auto."""
        if self.brightness is None or self.brightness_is_auto:
            return None
        try:
            return int(self.brightness)
        except ValueError:
            return None


class BusyBarCoordinator(DataUpdateCoordinator[BusyBarData]):
    """Poll one BUSY Bar over its local HTTP API."""

    config_entry: BusyBarConfigEntry

    def __init__(self, hass: HomeAssistant, entry: BusyBarConfigEntry) -> None:
        """Build the client and set the poll interval from the options."""
        self.entry = entry
        interval = int(
            entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {entry.data[CONF_HOST]}",
            update_interval=timedelta(seconds=interval),
            config_entry=entry,
        )
        self.client = BusyBarClient(
            session=async_get_clientsession(hass),
            host=entry.data[CONF_HOST],
            port=entry.data.get(CONF_PORT, DEFAULT_PORT),
            token=entry.data.get(CONF_TOKEN),
        )
        # Remembered so that dragging the brightness slider while the device is
        # on auto has something to switch back to.
        self._last_manual_brightness: int | None = None

    @property
    def host(self) -> str:
        """Host or IP this entry points at."""
        return self.entry.data[CONF_HOST]

    @property
    def app_name(self) -> str:
        """The ``application_name`` we own every drawn element under."""
        return self.entry.options.get(CONF_APP_NAME, DEFAULT_APP_NAME)

    @property
    def default_priority(self) -> int:
        """Draw priority used when a service call does not name one."""
        return int(self.entry.options.get(CONF_DEFAULT_PRIORITY, DEFAULT_PRIORITY))

    @property
    def last_manual_brightness(self) -> int:
        """Best guess at a brightness to restore when leaving auto mode."""
        if self._last_manual_brightness is not None:
            return self._last_manual_brightness
        if self.data is not None and self.data.brightness_value is not None:
            return self.data.brightness_value
        return 50

    def remember_manual_brightness(self, value: int) -> None:
        """Record a brightness the user picked."""
        self._last_manual_brightness = value

    async def _async_update_data(self) -> BusyBarData:
        """Fetch device state.

        Requests go out one at a time -- the client serialises them anyway, and
        a handful of small sequential calls is kinder to the firmware's web
        server than six concurrent ones.
        """
        try:
            status = await self.client.async_get_status()
        except BusyBarAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except BusyBarError as err:
            raise UpdateFailed(str(err)) from err

        data = BusyBarData(
            device=status.get("device") or {},
            firmware=status.get("firmware") or {},
            system=status.get("system") or {},
            power=status.get("power") or {},
            fetched_at=dt_util.utcnow(),
        )

        data.wifi = await self._optional("Wi-Fi status", self.client.async_get_wifi_status)

        snapshot = await self._optional("BUSY snapshot", self.client.async_get_busy_snapshot)
        data.snapshot = snapshot.get("snapshot") or {}

        brightness = await self._optional("brightness", self.client.async_get_brightness)
        data.brightness = brightness.get("value")
        if data.brightness_value is not None:
            self._last_manual_brightness = data.brightness_value

        volume = await self._optional("volume", self.client.async_get_volume)
        if (raw_volume := volume.get("volume")) is not None:
            data.volume = float(raw_volume)

        name = await self._optional("device name", self.client.async_get_name)
        data.name = name.get("name")

        # A device that was never commissioned into a Matter fabric answers 503
        # here, which is a missing feature rather than a failure.
        smart_home = await self._optional(
            "smart home switch", self.client.async_get_smart_home_switch
        )
        data.smart_home = smart_home or None

        return data

    async def _optional(self, label: str, call: Any) -> dict[str, Any]:
        """Run a secondary request, logging and swallowing its failures."""
        try:
            result = await call()
        except BusyBarError as err:
            _LOGGER.debug("%s unavailable on %s: %s", label, self.host, err)
            return {}
        return result if isinstance(result, dict) else {}

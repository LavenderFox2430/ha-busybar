"""Diagnostics for the BUSY Bar integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant

from .api import BusyBarError
from .coordinator import BusyBarConfigEntry

TO_REDACT = {
    CONF_TOKEN,
    "serial_number",
    "usb_mac",
    "wifi_mac",
    "ble_mac",
    "ssid",
    "bssid",
    "address",
    "gateway",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BusyBarConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data

    try:
        version = await coordinator.client.async_get_version()
    except BusyBarError as err:
        version = {"error": str(err)}

    try:
        transport = await coordinator.client.async_get_transport()
    except BusyBarError as err:
        transport = {"error": str(err)}

    data = asdict(coordinator.data) if coordinator.data else {}
    # fetched_at is a datetime, which JSON cannot carry.
    if data.get("fetched_at") is not None:
        data["fetched_at"] = coordinator.data.fetched_at.isoformat()

    return async_redact_data(
        {
            "entry": {
                "data": dict(entry.data),
                "options": dict(entry.options),
            },
            "api_version": version,
            "transport": transport,
            "app_name": coordinator.app_name,
            "default_priority": coordinator.default_priority,
            "last_update_success": coordinator.last_update_success,
            "data": data,
        },
        TO_REDACT,
    )

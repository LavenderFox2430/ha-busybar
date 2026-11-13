"""Shared entity plumbing for the BUSY Bar integration."""

from __future__ import annotations

from collections.abc import Coroutine
from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import BusyBarError, BusyBarPriorityError
from .const import DEFAULT_NAME, DOMAIN, MANUFACTURER
from .coordinator import BusyBarCoordinator


async def async_device_call(action: Coroutine[Any, Any, Any]) -> Any:
    """Await a device call, turning its failures into Home Assistant errors.

    The priority case gets its own wording because it is the one refusal a user
    can act on: the request was well formed, something more important just owns
    the screen right now.
    """
    try:
        return await action
    except BusyBarPriorityError as err:
        raise HomeAssistantError(
            f"The BUSY Bar refused the draw: {err}. Raise the priority above "
            "the running app -- an active BUSY session sits at 90."
        ) from err
    except BusyBarError as err:
        raise HomeAssistantError(str(err)) from err


def base_id(coordinator: BusyBarCoordinator) -> str:
    """Prefix for every unique ID of this entry.

    The config entry's unique ID is the device serial number, so entities keep
    their identity across a reinstall or a change of IP address.
    """
    return coordinator.entry.unique_id or coordinator.entry.entry_id


def build_device_info(coordinator: BusyBarCoordinator) -> DeviceInfo:
    """Describe the bar for the device registry."""
    data = coordinator.data
    info = DeviceInfo(
        identifiers={(DOMAIN, base_id(coordinator))},
        manufacturer=MANUFACTURER,
        name=(data.name if data and data.name else DEFAULT_NAME),
        configuration_url=coordinator.client.base_url,
    )
    if data is None:
        return info
    if model := data.device.get("otp_model"):
        info["model"] = model
    if serial := data.device.get("serial_number"):
        info["serial_number"] = serial
    if version := data.firmware.get("version"):
        info["sw_version"] = version
    macs = (data.device.get("wifi_mac"), data.device.get("usb_mac"))
    connections = {
        (CONNECTION_NETWORK_MAC, format_mac(mac)) for mac in macs if mac
    }
    if connections:
        info["connections"] = connections
    return info


class BusyBarEntity(CoordinatorEntity[BusyBarCoordinator]):
    """Base entity for the single device behind a config entry."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BusyBarCoordinator, key: str) -> None:
        """Initialise the entity with a stable unique ID."""
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{base_id(coordinator)}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Describe the bar this entity belongs to."""
        return build_device_info(self.coordinator)

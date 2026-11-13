"""The emulated smart home switch exposed by the BUSY Bar."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import BusyBarConfigEntry, BusyBarCoordinator
from .entity import BusyBarEntity, async_device_call


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BusyBarConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the BUSY Bar switches.

    The switch only exists on a device whose Matter stack answered, so a bar that
    was never commissioned does not gain a control that cannot work.
    """
    coordinator = entry.runtime_data
    if coordinator.data is not None and coordinator.data.smart_home is not None:
        async_add_entities([BusyBarSmartHomeSwitch(coordinator)])


class BusyBarSmartHomeSwitch(BusyBarEntity, SwitchEntity):
    """The virtual Matter switch the bar presents to a smart home.

    This is the bar's own outward-facing switch, the one other smart home
    controllers see. Flipping it here is the same as flipping it from them.
    """

    _attr_translation_key = "smart_home_switch"

    def __init__(self, coordinator: BusyBarCoordinator) -> None:
        """Initialise the switch."""
        super().__init__(coordinator, "smart_home_switch")

    @property
    def is_on(self) -> bool | None:
        """The switch state as the device reports it."""
        data = self.coordinator.data
        if data is None or data.smart_home is None:
            return None
        return data.smart_home.get("state")

    @property
    def available(self) -> bool:
        """Unavailable when the Matter service stops answering."""
        return (
            super().available
            and self.coordinator.data is not None
            and self.coordinator.data.smart_home is not None
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the emulated switch on."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the emulated switch off."""
        await self._async_set(False)

    async def _async_set(self, state: bool) -> None:
        """Push a new state and refresh."""
        await async_device_call(
            self.coordinator.client.async_set_smart_home_switch(state)
        )
        await self.coordinator.async_request_refresh()

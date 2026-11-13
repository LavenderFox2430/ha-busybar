"""Brightness mode selector for the BUSY Bar integration."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import BusyBarConfigEntry, BusyBarCoordinator
from .entity import BusyBarEntity, async_device_call

MODE_AUTO = "auto"
MODE_MANUAL = "manual"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BusyBarConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the BUSY Bar select entities."""
    async_add_entities([BusyBarBrightnessMode(entry.runtime_data)])


class BusyBarBrightnessMode(BusyBarEntity, SelectEntity):
    """Whether the ambient light sensor drives display brightness.

    The firmware folds the mode and the level into one setting: posting "auto"
    hands brightness to the light sensor, posting a number takes it back. This
    entity is the mode half, so the brightness slider can stay a plain number.
    """

    _attr_translation_key = "brightness_mode"
    _attr_options = [MODE_AUTO, MODE_MANUAL]
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: BusyBarCoordinator) -> None:
        """Initialise the brightness mode selector."""
        super().__init__(coordinator, "brightness_mode")

    @property
    def current_option(self) -> str | None:
        """The active brightness mode."""
        data = self.coordinator.data
        if data is None or data.brightness is None:
            return None
        return MODE_AUTO if data.brightness_is_auto else MODE_MANUAL

    async def async_select_option(self, option: str) -> None:
        """Switch between automatic and manual brightness.

        Going manual restores the last level we saw the device on, so the screen
        does not jump to an arbitrary brightness.
        """
        if option == MODE_AUTO:
            value = MODE_AUTO
        else:
            value = str(self.coordinator.last_manual_brightness)
        await async_device_call(self.coordinator.client.async_set_brightness(value))
        await self.coordinator.async_request_refresh()

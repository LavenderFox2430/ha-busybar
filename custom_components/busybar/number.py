"""Brightness and volume controls for the BUSY Bar integration."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import BusyBarConfigEntry, BusyBarCoordinator
from .entity import BusyBarEntity, async_device_call


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BusyBarConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the BUSY Bar number entities."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            BusyBarBrightness(coordinator),
            BusyBarVolume(coordinator),
        ]
    )


class BusyBarBrightness(BusyBarEntity, NumberEntity):
    """Display brightness, in percent.

    Reads as unknown while the device is on automatic brightness, since the
    firmware reports the mode rather than the level it settled on. Setting a
    value switches the device to manual.
    """

    _attr_translation_key = "brightness"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: BusyBarCoordinator) -> None:
        """Initialise the brightness control."""
        super().__init__(coordinator, "brightness")

    @property
    def native_value(self) -> float | None:
        """The manual brightness level, or None on automatic."""
        if self.coordinator.data is None:
            return None
        value = self.coordinator.data.brightness_value
        return None if value is None else float(value)

    async def async_set_native_value(self, value: float) -> None:
        """Set a manual brightness level."""
        level = int(value)
        await async_device_call(self.coordinator.client.async_set_brightness(str(level)))
        self.coordinator.remember_manual_brightness(level)
        await self.coordinator.async_request_refresh()


class BusyBarVolume(BusyBarEntity, NumberEntity):
    """Speaker volume, in percent."""

    _attr_translation_key = "volume"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: BusyBarCoordinator) -> None:
        """Initialise the volume control."""
        super().__init__(coordinator, "volume")

    @property
    def native_value(self) -> float | None:
        """The current volume."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.volume

    async def async_set_native_value(self, value: float) -> None:
        """Set the volume without the confirmation blip."""
        await async_device_call(
            self.coordinator.client.async_set_volume(int(value), silent=True)
        )
        await self.coordinator.async_request_refresh()

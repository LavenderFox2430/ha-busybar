"""Binary sensors for the BUSY Bar integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import BusyBarConfigEntry, BusyBarCoordinator, BusyBarData
from .entity import BusyBarEntity


@dataclass(frozen=True, kw_only=True)
class BusyBarBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a BUSY Bar binary sensor."""

    value_fn: Callable[[BusyBarData], bool | None]


BINARY_SENSORS: tuple[BusyBarBinarySensorDescription, ...] = (
    BusyBarBinarySensorDescription(
        key="timer_running",
        translation_key="timer_running",
        value_fn=lambda data: data.timer_running,
    ),
    BusyBarBinarySensorDescription(
        key="timer_paused",
        translation_key="timer_paused",
        value_fn=lambda data: data.timer_paused if data.timer_running else False,
    ),
    BusyBarBinarySensorDescription(
        key="charging",
        translation_key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        value_fn=lambda data: (
            None
            if data.power.get("state") is None
            else data.power.get("state") == "charging"
        ),
    ),
    BusyBarBinarySensorDescription(
        key="wifi_connected",
        translation_key="wifi_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: (
            None
            if not data.wifi
            else data.wifi.get("state") == "connected"
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BusyBarConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the BUSY Bar binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        BusyBarBinarySensor(coordinator, description)
        for description in BINARY_SENSORS
    )


class BusyBarBinarySensor(BusyBarEntity, BinarySensorEntity):
    """A yes-or-no reading from the bar."""

    entity_description: BusyBarBinarySensorDescription

    def __init__(
        self,
        coordinator: BusyBarCoordinator,
        description: BusyBarBinarySensorDescription,
    ) -> None:
        """Initialise the binary sensor from its description."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Whether the condition currently holds."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

"""Sensors for the BUSY Bar integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import POWER_STATES, WIFI_STATES
from .coordinator import BusyBarConfigEntry, BusyBarCoordinator, BusyBarData
from .entity import BusyBarEntity

TIMER_TYPE_OPTIONS = ["not_started", "infinite", "simple", "interval"]


@dataclass(frozen=True, kw_only=True)
class BusyBarSensorDescription(SensorEntityDescription):
    """Describes a BUSY Bar sensor."""

    value_fn: Callable[[BusyBarData], Any]


SENSORS: tuple[BusyBarSensorDescription, ...] = (
    BusyBarSensorDescription(
        key="battery_charge",
        translation_key="battery_charge",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda data: data.power.get("battery_charge"),
    ),
    BusyBarSensorDescription(
        key="power_state",
        translation_key="power_state",
        device_class=SensorDeviceClass.ENUM,
        options=POWER_STATES,
        value_fn=lambda data: data.power.get("state"),
    ),
    BusyBarSensorDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        suggested_display_precision=3,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: _milli(data.power.get("battery_voltage")),
    ),
    BusyBarSensorDescription(
        key="battery_current",
        translation_key="battery_current",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        suggested_display_precision=3,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: _milli(data.power.get("battery_current")),
    ),
    BusyBarSensorDescription(
        key="usb_voltage",
        translation_key="usb_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        suggested_display_precision=3,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: _milli(data.power.get("usb_voltage")),
    ),
    BusyBarSensorDescription(
        key="timer_state",
        translation_key="timer_state",
        device_class=SensorDeviceClass.ENUM,
        options=TIMER_TYPE_OPTIONS,
        value_fn=lambda data: data.timer_type.lower(),
    ),
    BusyBarSensorDescription(
        key="timer_time_left",
        translation_key="timer_time_left",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_display_precision=0,
        value_fn=lambda data: (
            None if data.time_left_ms is None else data.time_left_ms / 1000
        ),
    ),
    BusyBarSensorDescription(
        key="timer_ends_at",
        translation_key="timer_ends_at",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.ends_at,
    ),
    BusyBarSensorDescription(
        key="timer_interval",
        translation_key="timer_interval",
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.snapshot.get("current_interval"),
    ),
    BusyBarSensorDescription(
        key="wifi_state",
        translation_key="wifi_state",
        device_class=SensorDeviceClass.ENUM,
        options=WIFI_STATES,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.wifi.get("state"),
    ),
    BusyBarSensorDescription(
        key="wifi_signal",
        translation_key="wifi_signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="dBm",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.wifi.get("rssi"),
    ),
    BusyBarSensorDescription(
        key="wifi_ssid",
        translation_key="wifi_ssid",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.wifi.get("ssid"),
    ),
    BusyBarSensorDescription(
        key="ip_address",
        translation_key="ip_address",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: (data.wifi.get("ip_config") or {}).get("address"),
    ),
    BusyBarSensorDescription(
        key="uptime",
        translation_key="uptime",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _boot_time(data),
    ),
)


def _milli(value: Any) -> float | None:
    """Convert a milli-unit reading from the device into its base unit."""
    if value is None:
        return None
    return value / 1000


def _boot_time(data: BusyBarData) -> datetime | None:
    """Turn the device's boot timestamp into an aware datetime.

    Reported as a timestamp rather than a growing uptime string so the state only
    changes when the device actually reboots.
    """
    boot_time = data.system.get("boot_time")
    if not boot_time:
        return None
    return dt_util.utc_from_timestamp(boot_time)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BusyBarConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the BUSY Bar sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        BusyBarSensor(coordinator, description) for description in SENSORS
    )


class BusyBarSensor(BusyBarEntity, SensorEntity):
    """A single reading from the bar."""

    entity_description: BusyBarSensorDescription

    def __init__(
        self,
        coordinator: BusyBarCoordinator,
        description: BusyBarSensorDescription,
    ) -> None:
        """Initialise the sensor from its description."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """The current reading."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

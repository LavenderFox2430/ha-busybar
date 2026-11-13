"""Buttons for the BUSY Bar integration.

The bar's own keys are exposed as buttons so an automation can drive it exactly
as a person standing in front of it would.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import BusyBarConfigEntry, BusyBarCoordinator
from .entity import BusyBarEntity, async_device_call


@dataclass(frozen=True, kw_only=True)
class BusyBarButtonDescription(ButtonEntityDescription):
    """Describes a BUSY Bar button."""

    press_fn: Callable[[BusyBarCoordinator], Coroutine[Any, Any, Any]]


def _key(key: str) -> Callable[[BusyBarCoordinator], Coroutine[Any, Any, Any]]:
    """Build a press handler that injects one of the device's own keys."""

    def press(coordinator: BusyBarCoordinator) -> Coroutine[Any, Any, Any]:
        return coordinator.client.async_press_key(key)

    return press


BUTTONS: tuple[BusyBarButtonDescription, ...] = (
    BusyBarButtonDescription(
        key="busy",
        translation_key="busy",
        press_fn=_key("busy"),
    ),
    BusyBarButtonDescription(
        key="custom",
        translation_key="custom",
        press_fn=_key("custom"),
    ),
    BusyBarButtonDescription(
        key="off",
        translation_key="off",
        press_fn=_key("off"),
    ),
    BusyBarButtonDescription(
        key="clear_display",
        translation_key="clear_display",
        press_fn=lambda coordinator: coordinator.client.async_clear(
            app_name=coordinator.app_name
        ),
    ),
    BusyBarButtonDescription(
        key="stop_audio",
        translation_key="stop_audio",
        press_fn=lambda coordinator: coordinator.client.async_stop_audio(),
    ),
    # The remaining keys are navigation: useful for scripting the on-device menus,
    # noise on a dashboard, so they ship disabled.
    BusyBarButtonDescription(
        key="start",
        translation_key="start",
        entity_registry_enabled_default=False,
        press_fn=_key("start"),
    ),
    BusyBarButtonDescription(
        key="ok",
        translation_key="ok",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        press_fn=_key("ok"),
    ),
    BusyBarButtonDescription(
        key="back",
        translation_key="back",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        press_fn=_key("back"),
    ),
    BusyBarButtonDescription(
        key="up",
        translation_key="up",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        press_fn=_key("up"),
    ),
    BusyBarButtonDescription(
        key="down",
        translation_key="down",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        press_fn=_key("down"),
    ),
    BusyBarButtonDescription(
        key="apps",
        translation_key="apps",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        press_fn=_key("apps"),
    ),
    BusyBarButtonDescription(
        key="settings",
        translation_key="settings",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        press_fn=_key("settings"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BusyBarConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the BUSY Bar buttons."""
    coordinator = entry.runtime_data
    async_add_entities(
        BusyBarButton(coordinator, description) for description in BUTTONS
    )


class BusyBarButton(BusyBarEntity, ButtonEntity):
    """One press on the bar."""

    entity_description: BusyBarButtonDescription

    def __init__(
        self,
        coordinator: BusyBarCoordinator,
        description: BusyBarButtonDescription,
    ) -> None:
        """Initialise the button from its description."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        """Send the press and pick up whatever it changed."""
        await async_device_call(self.entity_description.press_fn(self.coordinator))
        await self.coordinator.async_request_refresh()

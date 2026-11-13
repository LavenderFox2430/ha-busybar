"""Text entities that draw straight onto the BUSY Bar.

These are the point-and-type route to the display: put a message in the box and
it appears on the bar, clear the box and it goes away. Anything more elaborate --
positioning, colours per call, countdowns, layered elements -- is what the
``busybar.draw_text`` and ``busybar.draw`` services are for.
"""

from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONF_TEXT_COLOR,
    CONF_TEXT_FONT,
    CONF_TEXT_TIMEOUT,
    DEFAULT_TEXT_COLOR,
    DEFAULT_TEXT_FONT,
    DEFAULT_TEXT_TIMEOUT,
    DISPLAY_BACK,
    DISPLAY_FRONT,
    TEXT_ELEMENT_IDS,
)
from .coordinator import BusyBarConfigEntry, BusyBarCoordinator
from .draw import build_payload, build_text_element
from .entity import BusyBarEntity, async_device_call


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BusyBarConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one message box per display."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            BusyBarMessageText(coordinator, DISPLAY_FRONT),
            BusyBarMessageText(coordinator, DISPLAY_BACK),
        ]
    )


class BusyBarMessageText(BusyBarEntity, TextEntity, RestoreEntity):
    """A message drawn on one of the bar's two displays.

    The device has no endpoint for reading back what is on screen, so the value
    here is the last message this entity sent. It is restored across a Home
    Assistant restart because the bar keeps drawing an element with no timeout,
    which means the box still matches the panel after a reload.
    """

    _attr_mode = TextMode.TEXT
    _attr_native_min = 0
    _attr_native_max = 255

    def __init__(self, coordinator: BusyBarCoordinator, display: str) -> None:
        """Initialise the message box for one display."""
        super().__init__(coordinator, f"message_{display}")
        self._display = display
        self._element_id = TEXT_ELEMENT_IDS[display]
        self._attr_translation_key = f"message_{display}"
        self._attr_native_value = ""

    async def async_added_to_hass(self) -> None:
        """Restore the last message we sent."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state not in (None, "unknown", "unavailable"):
                self._attr_native_value = last_state.state

    @property
    def native_value(self) -> str | None:
        """The message currently on this display, as far as we know."""
        return self._attr_native_value

    async def async_set_value(self, value: str) -> None:
        """Draw the message, or clear the display when handed an empty string."""
        options = self.coordinator.entry.options
        if not value.strip():
            await async_device_call(
                self.coordinator.client.async_clear(
                    app_name=self.coordinator.app_name,
                    element_ids=[self._element_id],
                )
            )
            self._attr_native_value = ""
            self.async_write_ha_state()
            return

        element = build_text_element(
            self._element_id,
            value,
            font=options.get(CONF_TEXT_FONT, DEFAULT_TEXT_FONT),
            color=options.get(CONF_TEXT_COLOR, DEFAULT_TEXT_COLOR),
            display=self._display,
            align="center",
            timeout=int(options.get(CONF_TEXT_TIMEOUT, DEFAULT_TEXT_TIMEOUT)),
            scroll=True,
        )
        payload = build_payload(
            self.coordinator.app_name,
            [element],
            priority=self.coordinator.default_priority,
        )
        await async_device_call(self.coordinator.client.async_draw(payload))
        self._attr_native_value = value
        self.async_write_ha_state()

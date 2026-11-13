"""Live mirrors of the BUSY Bar's two displays.

``/api/screen`` hands back base64 of the raw LVGL framebuffer rather than an
image file, so the pixel formats are unpacked here and re-encoded as PNG.
"""

from __future__ import annotations

import io
import logging

from homeassistant.components.camera import Camera
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import BusyBarError
from .const import (
    BACK_HEIGHT,
    BACK_WIDTH,
    DISPLAY_BACK,
    DISPLAY_FRONT,
    FRONT_HEIGHT,
    FRONT_WIDTH,
)
from .coordinator import BusyBarConfigEntry, BusyBarCoordinator
from .entity import build_device_info

_LOGGER = logging.getLogger(__name__)

# The panels are tiny, so scale them up before handing them to the frontend --
# otherwise a 72x16 preview is a smear. Nearest-neighbour keeps the LED grid and
# the bitmap fonts crisp instead of blurring them.
SCALE = {DISPLAY_FRONT: 8, DISPLAY_BACK: 4}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BusyBarConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one camera per display."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            BusyBarScreenCamera(coordinator, DISPLAY_FRONT),
            BusyBarScreenCamera(coordinator, DISPLAY_BACK),
        ]
    )


class BusyBarScreenCamera(Camera):
    """A still image of one display, refreshed on demand."""

    _attr_has_entity_name = True
    _attr_content_type = "image/png"
    # One frame a second: enough to watch a countdown tick without flooding the
    # firmware's web server while a preview is open.
    _attr_frame_interval = 1.0

    def __init__(self, coordinator: BusyBarCoordinator, display: str) -> None:
        """Initialise the camera for one display."""
        super().__init__()
        self._coordinator = coordinator
        self._display = display
        self._attr_translation_key = f"screen_{display}"
        base = coordinator.entry.unique_id or coordinator.entry.entry_id
        self._attr_unique_id = f"{base}_screen_{display}"

    @property
    def device_info(self) -> DeviceInfo:
        """Describe the bar this camera belongs to."""
        return build_device_info(self._coordinator)

    @property
    def available(self) -> bool:
        """Follow the coordinator: a bar we cannot poll cannot be captured."""
        return self._coordinator.last_update_success

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Capture one frame and return it as a PNG."""
        try:
            raw = await self._coordinator.client.async_get_screen(self._display)
        except BusyBarError as err:
            _LOGGER.debug("Could not capture %s display: %s", self._display, err)
            return None
        return await self.hass.async_add_executor_job(_encode_png, self._display, raw)


def _encode_png(display: str, raw: bytes) -> bytes | None:
    """Turn a raw framebuffer into an upscaled PNG.

    Front is ``LV_COLOR_FORMAT_RGB888``, which LVGL stores channel-reversed, so
    the bytes are read as BGR. Back is ``LV_COLOR_FORMAT_L8`` that the firmware
    halves to 4 bits per pixel on the way out: the low nibble of each byte is the
    first pixel, the high nibble the second.
    """
    from PIL import Image

    if display == DISPLAY_FRONT:
        expected = FRONT_WIDTH * FRONT_HEIGHT * 3
        if len(raw) != expected:
            _LOGGER.debug("Front frame was %s bytes, expected %s", len(raw), expected)
            return None
        image = Image.frombytes("RGB", (FRONT_WIDTH, FRONT_HEIGHT), raw, "raw", "BGR")
    else:
        expected = BACK_WIDTH * BACK_HEIGHT // 2
        if len(raw) != expected:
            _LOGGER.debug("Back frame was %s bytes, expected %s", len(raw), expected)
            return None
        unpacked = bytearray(BACK_WIDTH * BACK_HEIGHT)
        for index, byte in enumerate(raw):
            unpacked[2 * index] = (byte & 0x0F) << 4
            unpacked[2 * index + 1] = byte & 0xF0
        image = Image.frombytes("L", (BACK_WIDTH, BACK_HEIGHT), bytes(unpacked))

    scale = SCALE[display]
    image = image.resize(
        (image.width * scale, image.height * scale), Image.Resampling.NEAREST
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()

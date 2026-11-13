"""Building blocks for the display draw API.

Everything that turns Home Assistant input into a ``DisplayElements`` payload
lives here, so the services and the text entities agree on what a sensible
default looks like.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from homeassistant.exceptions import ServiceValidationError

from .const import (
    BACK_HEIGHT,
    BACK_WIDTH,
    DEFAULT_TEXT_COLOR,
    DISPLAY_BACK,
    DISPLAY_FRONT,
    FRONT_HEIGHT,
    FRONT_WIDTH,
)

_ELEMENT_ID_RE = re.compile(r"^[a-zA-Z0-9._-]+$")
_PRINTABLE_ASCII_RE = re.compile(r"^[\x20-\x7E]+$")
_HEX_COLOR_RE = re.compile(r"^#?(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")

DISPLAY_SIZES: dict[str, tuple[int, int]] = {
    DISPLAY_FRONT: (FRONT_WIDTH, FRONT_HEIGHT),
    DISPLAY_BACK: (BACK_WIDTH, BACK_HEIGHT),
}

# The fonts on the device are bitmap ASCII, so anything outside 0x20-0x7E cannot
# be drawn at all. Rather than let the device reject the whole request, fold the
# characters people actually paste -- smart quotes from a text field, an em dash
# from a calendar summary, a degree sign from a weather template -- down to
# something the panel can render.
_TRANSLITERATIONS = {
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    "‘": "'",
    "’": "'",
    "‚": "'",
    "‛": "'",
    "′": "'",
    "“": '"',
    "”": '"',
    "„": '"',
    "″": '"',
    "‐": "-",
    "‑": "-",
    "‒": "-",
    "–": "-",
    "—": "-",
    "―": "-",
    "−": "-",
    "…": "...",
    "°": "*",
    "·": ".",
    "•": "*",
    "«": '"',
    "»": '"',
    "‹": "'",
    "›": "'",
    "×": "x",
    "÷": "/",
    "→": "->",
    "←": "<-",
    "µ": "u",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
    "✓": "v",
    "✗": "x",
    "é": "e",
}

_ANCHOR_FRACTIONS: dict[str, tuple[float, float]] = {
    "top_left": (0.0, 0.0),
    "top_mid": (0.5, 0.0),
    "top_right": (1.0, 0.0),
    "mid_left": (0.0, 0.5),
    "center": (0.5, 0.5),
    "mid_right": (1.0, 0.5),
    "bottom_left": (0.0, 1.0),
    "bottom_mid": (0.5, 1.0),
    "bottom_right": (1.0, 1.0),
}


def sanitize_text(text: str) -> str:
    """Reduce arbitrary text to what the device's bitmap fonts can draw.

    Accented letters are decomposed and stripped of their marks, a table of
    common punctuation is folded to ASCII, and anything still unprintable is
    dropped. Raises when nothing survives, because an empty string fails the
    firmware's own validation.
    """
    folded = "".join(_TRANSLITERATIONS.get(char, char) for char in text)
    decomposed = unicodedata.normalize("NFKD", folded)
    stripped = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    # Newlines and tabs are below 0x20, so they have to become spaces here rather
    # than be dropped -- otherwise "one\ntwo" would come out as "onetwo".
    result = "".join(
        char if 0x20 <= ord(char) <= 0x7E else (" " if char.isspace() else "")
        for char in stripped
    )
    result = re.sub(r"\s+", " ", result).strip()
    if not result:
        raise ServiceValidationError(
            f"Nothing drawable left in {text!r}: the display fonts only cover "
            "printable ASCII"
        )
    return result


def normalize_color(color: str | None, default: str = DEFAULT_TEXT_COLOR) -> str:
    """Normalise a colour to the ``#RRGGBBAA`` the firmware expects.

    Accepts the shapes people actually have on hand: ``#RGB``, ``#RGBA``,
    ``#RRGGBB`` and ``#RRGGBBAA``, with or without the leading hash. Short forms
    are expanded by doubling each digit, and a missing alpha means opaque.
    """
    if not color:
        return default
    candidate = color.strip()
    if not _HEX_COLOR_RE.match(candidate):
        raise ServiceValidationError(
            f"{color!r} is not a hex colour; use #RRGGBB or #RRGGBBAA"
        )
    digits = candidate.lstrip("#")
    if len(digits) in (3, 4):
        digits = "".join(digit * 2 for digit in digits)
    if len(digits) == 6:
        digits += "FF"
    return f"#{digits.upper()}"


def validate_element_id(element_id: str) -> str:
    """Check an element id against the firmware's pattern."""
    if not _ELEMENT_ID_RE.match(element_id):
        raise ServiceValidationError(
            f"{element_id!r} is not a valid element id: letters, digits, dot, "
            "dash and underscore only"
        )
    return element_id


def anchor_position(
    display: str, align: str, x: int | None, y: int | None
) -> tuple[int, int]:
    """Resolve the anchor coordinates, defaulting to the alignment's own spot.

    ``x``/``y`` position the anchor point named by ``align``, so aligning to
    ``center`` without coordinates should mean the middle of the panel rather
    than the top-left corner. Explicit coordinates always win.
    """
    width, height = DISPLAY_SIZES[display]
    fraction_x, fraction_y = _ANCHOR_FRACTIONS.get(align, (0.0, 0.0))
    resolved_x = round(width * fraction_x) if x is None else x
    resolved_y = round(height * fraction_y) if y is None else y
    return resolved_x, resolved_y


def _base_element(
    element_id: str,
    element_type: str,
    display: str,
    align: str,
    x: int | None,
    y: int | None,
    timeout: int | None,
    display_until: int | None,
    z_index: int | None,
) -> dict[str, Any]:
    """Assemble the fields every element type shares."""
    resolved_x, resolved_y = anchor_position(display, align, x, y)
    element: dict[str, Any] = {
        "id": validate_element_id(element_id),
        "type": element_type,
        "display": display,
        "align": align,
        "x": resolved_x,
        "y": resolved_y,
    }
    if display_until is not None:
        if timeout:
            raise ServiceValidationError(
                "Use either timeout or display_until, not both"
            )
        # The firmware wants this timestamp as a string.
        element["display_until"] = str(int(display_until))
    elif timeout is not None:
        element["timeout"] = int(timeout)
    if z_index is not None:
        element["z_index"] = int(z_index)
    return element


def build_text_element(
    element_id: str,
    text: str,
    *,
    font: str,
    color: str | None = None,
    display: str = DISPLAY_FRONT,
    align: str = "center",
    x: int | None = None,
    y: int | None = None,
    timeout: int | None = None,
    display_until: int | None = None,
    z_index: int | None = None,
    width: int | None = None,
    scroll: bool = True,
    scroll_rate: int | None = None,
    scroll_start_delay: int | None = None,
    scroll_repeat_delay: int | None = None,
) -> dict[str, Any]:
    """Build a text element, scrolling by default when it will not fit.

    ``scroll`` is the friendly switch: leaving it on gives the label the panel's
    full width so long text marches across instead of being clipped. Turning it
    off omits every scroll field, which is what you want for a short status word
    that should sit still.
    """
    element = _base_element(
        element_id, "text", display, align, x, y, timeout, display_until, z_index
    )
    element["text"] = sanitize_text(text)
    element["font"] = font
    element["color"] = normalize_color(color)

    panel_width = DISPLAY_SIZES[display][0]
    if width is not None:
        element["width"] = int(width)
    elif scroll:
        # A label needs a bounded width before it has anything to scroll within.
        element["width"] = panel_width

    if scroll:
        element["scroll_rate"] = 1000 if scroll_rate is None else int(scroll_rate)
        element["scroll_start_delay"] = (
            1000 if scroll_start_delay is None else int(scroll_start_delay)
        )
        element["scroll_repeat_delay"] = (
            2500 if scroll_repeat_delay is None else int(scroll_repeat_delay)
        )
    return element


def build_countdown_element(
    element_id: str,
    timestamp: int,
    *,
    direction: str,
    show_hours: str,
    color: str | None = None,
    display: str = DISPLAY_FRONT,
    align: str = "center",
    x: int | None = None,
    y: int | None = None,
    timeout: int | None = None,
    display_until: int | None = None,
    z_index: int | None = None,
) -> dict[str, Any]:
    """Build a countdown element that the device ticks on its own."""
    element = _base_element(
        element_id, "countdown", display, align, x, y, timeout, display_until, z_index
    )
    element["timestamp"] = str(int(timestamp))
    element["direction"] = direction
    element["show_hours"] = show_hours
    element["color"] = normalize_color(color)
    return element


def build_rectangle_element(
    element_id: str,
    width: int,
    height: int,
    *,
    display: str = DISPLAY_FRONT,
    align: str = "top_left",
    x: int | None = None,
    y: int | None = None,
    timeout: int | None = None,
    display_until: int | None = None,
    z_index: int | None = None,
    radius: int | None = None,
    fill: str = "solid",
    fill_colors: list[str] | None = None,
    border_width: int | None = None,
    border_color: str | None = None,
) -> dict[str, Any]:
    """Build a rectangle, handy as a progress bar or a backdrop for text."""
    element = _base_element(
        element_id, "rectangle", display, align, x, y, timeout, display_until, z_index
    )
    element["width"] = int(width)
    element["height"] = int(height)
    element["fill"] = fill
    if radius is not None:
        element["radius"] = int(radius)
    if fill_colors:
        element["fill_colors"] = [normalize_color(color) for color in fill_colors]
    if border_width is not None:
        element["border_width"] = int(border_width)
    if border_color is not None:
        element["border_color"] = normalize_color(border_color)
    return element


def build_image_element(
    element_id: str,
    *,
    path: str | None = None,
    stock_path: str | None = None,
    animation: bool = False,
    display: str = DISPLAY_FRONT,
    align: str = "center",
    x: int | None = None,
    y: int | None = None,
    timeout: int | None = None,
    display_until: int | None = None,
    z_index: int | None = None,
    opacity: int | None = None,
    loop: bool | None = None,
    section: str | None = None,
) -> dict[str, Any]:
    """Build an image or animation element from an uploaded or stock asset."""
    if not path and not stock_path:
        raise ServiceValidationError("Either path or stock_path is required")
    element = _base_element(
        element_id,
        "animation" if animation else "image",
        display,
        align,
        x,
        y,
        timeout,
        display_until,
        z_index,
    )
    if stock_path:
        element["stock_path"] = stock_path
    else:
        element["path"] = path
    if opacity is not None:
        element["opacity"] = int(opacity)
    if animation:
        if loop is not None:
            element["loop"] = bool(loop)
        if section:
            element["section"] = section
    return element


def build_payload(
    app_name: str,
    elements: list[dict[str, Any]],
    *,
    priority: int,
    led_color: str | None = None,
) -> dict[str, Any]:
    """Wrap elements in the request body the draw endpoint expects."""
    if not elements:
        raise ServiceValidationError("At least one element is required")
    payload: dict[str, Any] = {
        "application_name": app_name,
        "priority": int(priority),
        "elements": elements,
    }
    if led_color:
        payload["led_notification_color"] = normalize_color(led_color)
    return payload

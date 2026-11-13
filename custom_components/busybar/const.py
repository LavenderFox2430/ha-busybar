"""Constants for the BUSY Bar integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "busybar"
MANUFACTURER: Final = "BUSY"
DEFAULT_NAME: Final = "BUSY Bar"

DEFAULT_PORT: Final = 80
DEFAULT_SCAN_INTERVAL: Final = 30
MIN_SCAN_INTERVAL: Final = 5
DEFAULT_TIMEOUT: Final = 10

CONF_APP_NAME: Final = "app_name"
CONF_DEFAULT_PRIORITY: Final = "default_priority"
CONF_TEXT_FONT: Final = "text_font"
CONF_TEXT_COLOR: Final = "text_color"
CONF_TEXT_TIMEOUT: Final = "text_timeout"

# Every element this integration draws is owned by this application_name, so a
# `clear` can wipe exactly our elements and leave a running app's alone.
DEFAULT_APP_NAME: Final = "homeassistant"

# The draw API accepts 1-100. A running BUSY/CUSTOM work session sits at 90 and
# ordinary built-in apps at 10, so 50 draws over the clock but politely loses to
# an active session. See DisplayElements.priority in the firmware's OpenAPI.
DEFAULT_PRIORITY: Final = 50
BUSY_SESSION_PRIORITY: Final = 90

# Physical panels, from applications/services/{front,back}_display/*.h.
FRONT_WIDTH: Final = 72
FRONT_HEIGHT: Final = 16
BACK_WIDTH: Final = 160
BACK_HEIGHT: Final = 80

DISPLAY_FRONT: Final = "front"
DISPLAY_BACK: Final = "back"
DISPLAYS: Final = [DISPLAY_FRONT, DISPLAY_BACK]

# Numeric display ids used by /api/screen (the JSON draw API uses the names).
SCREEN_IDS: Final = {DISPLAY_FRONT: 0, DISPLAY_BACK: 1}

FONTS: Final = [
    "tiny",
    "small",
    "normal",
    "condensed",
    "bold",
    "large",
    "extra_large",
    "global",
    "superscript",
]

ALIGNMENTS: Final = [
    "top_left",
    "top_mid",
    "top_right",
    "mid_left",
    "center",
    "mid_right",
    "bottom_left",
    "bottom_mid",
    "bottom_right",
]

FILL_STYLES: Final = ["none", "solid", "gradient_h", "gradient_v"]

COUNTDOWN_DIRECTIONS: Final = ["time_left", "time_since"]
COUNTDOWN_SHOW_HOURS: Final = ["when_non_zero", "always"]

KEYS: Final = [
    "up",
    "down",
    "ok",
    "back",
    "start",
    "busy",
    "custom",
    "off",
    "apps",
    "settings",
]

BUSY_SLOTS: Final = ["busy", "custom"]

TIMER_TYPE_NOT_STARTED: Final = "NOT_STARTED"
TIMER_TYPE_INFINITE: Final = "INFINITE"
TIMER_TYPE_SIMPLE: Final = "SIMPLE"
TIMER_TYPE_INTERVAL: Final = "INTERVAL"

POWER_STATES: Final = ["discharging", "charging", "charged"]
WIFI_STATES: Final = [
    "unknown",
    "disconnected",
    "connected",
    "connecting",
    "disconnecting",
    "reconnecting",
]

DEFAULT_TEXT_COLOR: Final = "#FFFFFFFF"
DEFAULT_TEXT_FONT: Final = "normal"
DEFAULT_TEXT_TIMEOUT: Final = 0

# Element ids reserved for the text entities, so repeated writes replace the
# previous message instead of stacking up.
TEXT_ELEMENT_IDS: Final = {
    DISPLAY_FRONT: "ha_text_front",
    DISPLAY_BACK: "ha_text_back",
}

SERVICE_DRAW_TEXT: Final = "draw_text"
SERVICE_DRAW_COUNTDOWN: Final = "draw_countdown"
SERVICE_DRAW_RECTANGLE: Final = "draw_rectangle"
SERVICE_DRAW_IMAGE: Final = "draw_image"
SERVICE_DRAW: Final = "draw"
SERVICE_CLEAR: Final = "clear"
SERVICE_PLAY_SOUND: Final = "play_sound"
SERVICE_PRESS_KEY: Final = "press_key"
SERVICE_START_TIMER: Final = "start_timer"
SERVICE_STOP_TIMER: Final = "stop_timer"

ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"

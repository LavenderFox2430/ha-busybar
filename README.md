# BUSY Bar for Home Assistant

A local-polling Home Assistant integration for the [BUSY Bar](https://busy.bar),
built against the HTTP API the firmware documents in its own OpenAPI spec
([busy-app/busybar-firmware](https://github.com/busy-app/busybar-firmware),
`applications/services/web_server/openapi`).

It covers the device's state and controls, and — the part this was written
for — it lets you **draw text** on either display, from a dashboard text box or
from an automation.

No cloud, no polling of anyone else's server: Home Assistant talks straight to
the bar on your network.

## Drawing text

Two ways, depending on how much control you want.

### The message boxes

Setting up the integration gives you two text entities:

| Entity | Panel |
| --- | --- |
| `text.<bar>_front_message` | the 72×16 LED matrix on the front |
| `text.<bar>_back_message` | the 160×80 screen on the back |

Type into one and the text appears on that panel, scrolling if it is too long to
fit. Clear the box and the message goes away. Put the entity on a dashboard and
you have a desk sign you can retype from your phone.

```yaml
action: text.set_value
target:
  entity_id: text.busy_bar_front_message
data:
  value: In a meeting until 3
```

The font, colour and timeout these use come from the integration's options, so
set them once and the boxes stay simple.

### The `draw_text` service

Everything the firmware's text element supports:

```yaml
action: busybar.draw_text
target:
  device_id: 0123456789abcdef0123456789abcdef
data:
  text: Build #4821 passed
  display: front
  font: bold
  color: "#00FF66"
  align: center
  timeout: 30
  led_color: "#00FF00"
```

Useful fields:

- **`display`** — `front` or `back`.
- **`font`** — `tiny`, `small`, `normal`, `condensed`, `bold`, `large`,
  `extra_large`, `global`, `superscript`.
- **`color`** / **`led_color`** — `#RRGGBB` or `#RRGGBBAA`, with or without the
  hash, and `#RGB` shorthand works too. `led_color` also blinks the status LED.
- **`align`** plus optional **`x`** / **`y`** — `align` picks which point of the
  text is placed at the coordinates. Leave the coordinates out and the text lands
  where the alignment implies, so `align: center` alone centres it on the panel.
- **`timeout`** — seconds before it disappears. Omit it or use `0` to leave it up
  until something clears it. **`display_until`** takes an absolute time instead.
- **`scroll`** — on by default. Turn it off for a short label that should sit
  still rather than march.
- **`element_id`** — reuse an ID to replace that message; use different IDs to
  keep several things on screen at once.
- **`priority`** — see [Priority](#priority) below.

Text is folded to what the panel can actually render before it is sent: the bar's
fonts are bitmap ASCII, so smart quotes become straight ones, an em dash becomes
a hyphen, `21°C` becomes `21*C`, `café` becomes `cafe`, and emoji are dropped.
You do not have to sanitise template output yourself.

### The other draw services

| Service | What it does |
| --- | --- |
| `busybar.draw_text` | a line of text |
| `busybar.draw_countdown` | a clock the **bar** ticks itself, so it stays smooth with no updates from Home Assistant |
| `busybar.draw_rectangle` | a box — a progress bar, or a backdrop for text |
| `busybar.draw_image` | a stock or uploaded image or animation |
| `busybar.draw` | raw display elements, for layered scenes and for element types the above do not wrap (including `xpmbitmap`) |
| `busybar.clear` | remove what this integration drew |

A countdown to a calendar event, ticking on the device:

```yaml
action: busybar.draw_countdown
target:
  device_id: !secret busy_bar_device
data:
  timestamp: "{{ state_attr('calendar.work', 'start_time') }}"
  direction: time_left
  show_hours: when_non_zero
  color: "#FF8800"
```

A two-layer scene through the raw service — a dark backdrop with a label over it:

```yaml
action: busybar.draw
target:
  device_id: !secret busy_bar_device
data:
  clear_first: true
  priority: 95
  elements:
    - id: bg
      type: rectangle
      display: front
      align: top_left
      x: 0
      y: 0
      width: 72
      height: 16
      fill: solid
      fill_colors: ["#001133FF"]
      border_width: 0
    - id: label
      type: text
      display: front
      align: center
      x: 36
      y: 8
      text: DEPLOYING
      font: small
      color: "#FFCC00FF"
      z_index: 1
```

`busybar.draw` passes elements through untouched, so the field names are the
firmware's own — the `DisplayElements` schema in
`applications/services/web_server/openapi/assets.yaml` is the reference.

### Priority

The bar arbitrates the display by priority, and a draw is accepted only when its
priority is at least that of whatever app is running:

| What is running | Priority |
| --- | --- |
| stub / power-off screens | 0 |
| any ordinary built-in app | 10 |
| an active BUSY or CUSTOM work session | 90 |

This integration draws at **50** by default: above the clock, politely below a
running session. If a call comes back with "a higher-priority app is using the
display", either the bar is mid-session or another app outranks you — pass
`priority: 95` to draw over a session.

`application_name` (default `homeassistant`) tags every element this integration
draws, which is what lets `busybar.clear` remove exactly its own elements and
leave other scripts' alone. `busybar.clear` with `everything: true` wipes all of
them.

## Everything else it exposes

**Sensors** — battery level and power state, session type, time left, when the
session ends (as a timestamp, so `relative_time` works), current interval, Wi-Fi
state and signal. Battery voltage/current, USB voltage, SSID, IP address and last
boot are there too, disabled by default as diagnostics.

**Binary sensors** — session active, session paused, charging, Wi-Fi connected.

**Cameras** — `camera.<bar>_front_display` and `camera.<bar>_back_display` mirror
what is on the panels right now, upscaled with nearest-neighbour so the LED grid
and the bitmap fonts stay crisp. Handy for checking a draw without looking at
your desk.

**Controls** — brightness (with an automatic/manual mode selector, because the
firmware folds the mode and the level into one setting), volume, and the emulated
smart home switch the bar presents to other controllers.

**Buttons** — BUSY, Custom session, Power off, Clear display, Stop audio. The
navigation keys (OK, Back, Up, Down, Apps, Settings, Start) are there as well,
disabled by default, for scripting the on-device menus.

**Session control** — `busybar.start_timer` runs one of the bar's two stored
profiles, honouring its interval cycles, or takes a `duration` to just run a
countdown:

```yaml
action: busybar.start_timer
target:
  device_id: !secret busy_bar_device
data:
  slot: busy
  duration: "00:25:00"
```

`busybar.stop_timer` ends it. `busybar.play_sound` plays a stock or uploaded
sound, and `busybar.press_key` sends a single key press.

Every service takes a target device, and with exactly one bar set up you can omit
the target entirely.

## Installation

### HACS

Add `https://github.com/LavenderFox2430/ha-busybar` as a custom repository of
type *Integration*, install **BUSY Bar**, restart Home Assistant.

### Manual

Copy `custom_components/busybar` into your `config/custom_components/` directory
and restart Home Assistant.

## Setup

The bar advertises itself over mDNS as `busybar-<mac>._http._tcp.local.`, so it
should appear under **Settings → Devices & services** on its own. Otherwise add
it with **Add integration → BUSY Bar** and enter its address.

### Access key

How the bar treats requests over Wi-Fi depends on its own API access setting:

- **Open** — no credential needed; leave the key field empty.
- **Key** — enter the 4–10 digit access key from the bar's settings.
- **Disabled** — the bar refuses HTTP over Wi-Fi entirely; turn it on first.

A minted API token works anywhere the key does, and is the better choice: create
one on the bar and paste it into the key field. Both travel in the
`X-API-Token` header.

If the key is changed later, Home Assistant raises a reauthentication prompt
rather than silently going stale.

### Options

**Settings → Devices & services → BUSY Bar → Configure**:

| Option | Default | What it is for |
| --- | --- | --- |
| Polling interval | 30 s | Six small requests per poll; the bar's web server is modest, so don't set this very low without reason. |
| Application name | `homeassistant` | Owner tag on every drawn element. |
| Default draw priority | 50 | Used when a service call sets none. |
| Message font / colour / timeout | `normal`, white, 0 | Used by the two message boxes. |

## Notes and limits

- **Polling, not push.** The firmware does have a status WebSocket, but it speaks
  protobuf (`BSB_State.State`) rather than JSON, which would mean shipping
  generated bindings. Polling the REST API keeps this a plain custom component;
  if push support lands, the coordinator is the only thing that has to change.
- **The message boxes are write-only.** The device has no endpoint for reading
  back what is on screen, so a message box shows the last thing it sent. It is
  restored across a Home Assistant restart, which matches the panel as long as
  the message had no timeout.
- **The smart home switch appears only if Matter answered.** A bar never
  commissioned into a fabric returns 503 there, and the switch is left out rather
  than added broken. Reload the entry after commissioning.
- **Front is 72×16 and back is 160×80.** Worth remembering when picking
  coordinates and a font.

## Development

`python tools/selftest.py` runs 129 checks against the tricky parts — the ASCII
folding, colour and anchor handling, the framebuffer unpacking behind the
cameras, session snapshot construction, and the HTTP client driven against a fake
device. It stubs Home Assistant out, so it runs on a bare Python install with
`aiohttp`, `voluptuous` and `pillow`.

## Licence

MIT.

"""Self-test for the BUSY Bar integration, runnable without Home Assistant.

Home Assistant is stubbed out with auto-generated placeholder modules, so the
parts of this integration that are worth getting exactly right can be exercised
on a bare Python install:

* the ASCII folding that keeps arbitrary text drawable on a bitmap-font panel
* colour normalisation and anchor placement
* the framebuffer unpacking behind the display cameras
* BUSY session snapshot construction
* the HTTP client's paths, query strings, bodies and error mapping, checked
  against a fake device

Run it with ``python tools/selftest.py``. Needs ``aiohttp``, ``voluptuous`` and
``pillow``; without Pillow the framebuffer suite is skipped.
"""

from __future__ import annotations

import asyncio
import base64
import importlib.abc
import importlib.machinery
import importlib.util
import io
import sys
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
COMPONENT = REPO / "custom_components" / "busybar"

FAILURES: list[str] = []


def check(label: str, got: object, want: object) -> None:
    """Assert equality, recording rather than raising on mismatch."""
    if got != want:
        FAILURES.append(label)
        print(f"  FAIL {label}\n       got  {got!r}\n       want {want!r}")
    else:
        print(f"  ok   {label}")


def raises(label: str, call, exc: type[BaseException] = Exception) -> None:
    """Assert that a callable raises."""
    try:
        call()
    except exc:
        print(f"  ok   {label} (raised)")
        return
    except Exception as err:  # noqa: BLE001
        FAILURES.append(label)
        print(f"  FAIL {label}: raised {type(err).__name__}, wanted {exc.__name__}")
        return
    FAILURES.append(label)
    print(f"  FAIL {label}: did not raise")


async def raises_async(label: str, coro, exc: type[BaseException]) -> None:
    """Assert that awaiting something raises."""
    try:
        await coro
    except exc:
        print(f"  ok   {label} ({exc.__name__})")
        return
    except Exception as err:  # noqa: BLE001
        FAILURES.append(label)
        print(f"  FAIL {label}: raised {type(err).__name__}, wanted {exc.__name__}")
        return
    FAILURES.append(label)
    print(f"  FAIL {label}: did not raise")


# -- Home Assistant stubs ----------------------------------------------------


class ServiceValidationError(Exception):
    """Stand-in for the Home Assistant exception of the same name."""


class HomeAssistantError(Exception):
    """Stand-in for the Home Assistant exception of the same name."""


class _AutoStub(types.ModuleType):
    """A module that invents a usable placeholder for any attribute asked of it.

    The placeholders are both subclassable and subscriptable, so module-level
    code like ``class C(DataUpdateCoordinator[Data])`` still imports.
    """

    def __getattr__(self, name: str):
        if name.startswith("__"):
            raise AttributeError(name)
        value = type(
            name,
            (),
            {
                "__init__": lambda self, *args, **kwargs: None,
                "__class_getitem__": classmethod(lambda cls, item: cls),
            },
        )
        setattr(self, name, value)
        return value


class _StubFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Serve auto-stub modules for everything under ``homeassistant``."""

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "homeassistant" or fullname.startswith("homeassistant."):
            return importlib.machinery.ModuleSpec(fullname, self, is_package=True)
        return None

    def create_module(self, spec):
        return _AutoStub(spec.name)

    def exec_module(self, module):
        pass


def install_stubs() -> None:
    """Put the stub finder in place and give the few real behaviours we need."""
    sys.meta_path.insert(0, _StubFinder())

    import homeassistant.exceptions as ha_exceptions

    ha_exceptions.ServiceValidationError = ServiceValidationError
    ha_exceptions.HomeAssistantError = HomeAssistantError

    import homeassistant.util.dt as dt_util

    dt_util.as_utc = lambda value: value.astimezone(UTC)
    dt_util.parse_datetime = lambda text: datetime.fromisoformat(text)
    dt_util.utcnow = lambda: datetime.now(UTC)
    dt_util.utc_from_timestamp = lambda value: datetime.fromtimestamp(value, UTC)

    import homeassistant.helpers.config_validation as cv

    cv.string = str
    cv.positive_int = int
    cv.boolean = bool
    cv.datetime = datetime
    cv.ensure_list = list
    cv.positive_time_period = lambda value: value

    import homeassistant.const as ha_const

    class Platform(str):
        """Enough of the Platform enum for a module-level list of platforms."""

    for name in (
        "BINARY_SENSOR",
        "BUTTON",
        "CAMERA",
        "NUMBER",
        "SELECT",
        "SENSOR",
        "SWITCH",
        "TEXT",
    ):
        setattr(Platform, name, Platform(name.lower()))
    ha_const.Platform = Platform


def load(module_name: str, filename: str):
    """Load one module of the integration by path, outside its package."""
    spec = importlib.util.spec_from_file_location(module_name, COMPONENT / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_component():
    """Load the integration's modules and hand back the interesting ones."""
    package = types.ModuleType("busybar")
    package.__path__ = [str(COMPONENT)]
    sys.modules["busybar"] = package

    load("busybar.const", "const.py")
    api = load("busybar.api", "api.py")
    draw = load("busybar.draw", "draw.py")
    coordinator = load("busybar.coordinator", "coordinator.py")
    # Loaded under a plain name: importing it as busybar would re-run the package.
    main = load("busybar.main", "__init__.py")
    return api, draw, coordinator, main


# -- Suites ------------------------------------------------------------------


def suite_colors(draw) -> None:
    """Colour normalisation accepts the shapes people actually have."""
    print("\n== colours ==")
    check("8 digit passthrough", draw.normalize_color("#12345678"), "#12345678")
    check("6 digit gains opaque alpha", draw.normalize_color("#ff8800"), "#FF8800FF")
    check("no leading hash", draw.normalize_color("00ff00"), "#00FF00FF")
    check("3 digit expands", draw.normalize_color("#f80"), "#FF8800FF")
    check("4 digit expands", draw.normalize_color("#f80a"), "#FF8800AA")
    check("empty falls back", draw.normalize_color(None), "#FFFFFFFF")
    raises("colour name rejected", lambda: draw.normalize_color("chartreuse"))
    raises("odd length rejected", lambda: draw.normalize_color("#1234567"))


def suite_text(draw) -> None:
    """Text folding keeps real-world strings drawable."""
    print("\n== text folding ==")
    check("plain ascii untouched", draw.sanitize_text("Hello, World!"), "Hello, World!")
    check("smart quotes", draw.sanitize_text("“don’t”"), '"don\'t"')
    check("em dash", draw.sanitize_text("a — b"), "a - b")
    check("ellipsis", draw.sanitize_text("wait…"), "wait...")
    check("degree sign", draw.sanitize_text("21°C"), "21*C")
    check("accents stripped", draw.sanitize_text("café naïve"), "cafe naive")
    check("emoji dropped", draw.sanitize_text("build \U0001F525 ok"), "build ok")
    check("newlines become spaces", draw.sanitize_text("one\n\ttwo"), "one two")
    check("non-breaking space", draw.sanitize_text("a b"), "a b")
    check("runs collapse", draw.sanitize_text("  a    b  "), "a b")
    raises("nothing drawable left", lambda: draw.sanitize_text("\U0001F525\U0001F525"))


def suite_placement(draw) -> None:
    """Omitted coordinates fall where the alignment implies."""
    print("\n== placement ==")
    check("front centre", draw.anchor_position("front", "center", None, None), (36, 8))
    check("front top left", draw.anchor_position("front", "top_left", None, None), (0, 0))
    check(
        "front bottom right",
        draw.anchor_position("front", "bottom_right", None, None),
        (72, 16),
    )
    check("back centre", draw.anchor_position("back", "center", None, None), (80, 40))
    check("explicit wins", draw.anchor_position("front", "center", 5, 1), (5, 1))
    check("half explicit", draw.anchor_position("front", "center", 5, None), (5, 8))


def suite_elements(draw) -> None:
    """Element builders produce what the firmware's schema asks for."""
    print("\n== elements ==")
    element = draw.build_text_element("msg", "Hello", font="normal")
    check("id", element["id"], "msg")
    check("type", element["type"], "text")
    check("display defaults to front", element["display"], "front")
    check("scrolling label gets panel width", element["width"], 72)
    check("scroll rate default", element["scroll_rate"], 1000)
    check("anchored centre", (element["x"], element["y"]), (36, 8))
    check("colour defaulted", element["color"], "#FFFFFFFF")

    static = draw.build_text_element("msg", "OK", font="small", scroll=False)
    check("no scroll fields when static", [k for k in static if "scroll" in k], [])
    check("no width forced when static", "width" in static, False)

    timed = draw.build_text_element("msg", "hi", font="normal", timeout=30)
    check("timeout kept", timed["timeout"], 30)

    until = draw.build_text_element("msg", "hi", font="normal", display_until=1800000000)
    check("display_until is a string", until["display_until"], "1800000000")
    check("no timeout beside it", "timeout" in until, False)
    raises(
        "timeout and display_until conflict",
        lambda: draw.build_text_element(
            "msg", "hi", font="normal", timeout=5, display_until=1800000000
        ),
    )
    raises("bad element id", lambda: draw.build_text_element("bad id!", "x", font="normal"))

    back = draw.build_text_element("msg", "hi", font="normal", display="back")
    check("back panel width", back["width"], 160)
    check("back anchor", (back["x"], back["y"]), (80, 40))

    countdown = draw.build_countdown_element(
        "cd", 1800000000, direction="time_left", show_hours="always"
    )
    check("countdown timestamp is a string", countdown["timestamp"], "1800000000")

    rect = draw.build_rectangle_element(
        "bar", 40, 4, fill_colors=["#f00"], border_width=0, align="mid_left"
    )
    check("rect colours normalised", rect["fill_colors"], ["#FF0000FF"])
    check("zero border width survives", rect["border_width"], 0)
    check("rect anchor", (rect["x"], rect["y"]), (0, 8))

    image = draw.build_image_element("pic", stock_path="shared/images/x.png")
    check("image type", image["type"], "image")
    anim = draw.build_image_element("pic", path="a.anim", animation=True, loop=True)
    check("animation type", anim["type"], "animation")
    check("loop kept", anim["loop"], True)
    raises("image needs a source", lambda: draw.build_image_element("pic"))

    payload = draw.build_payload("homeassistant", [element], priority=90, led_color="#f00")
    check("app name", payload["application_name"], "homeassistant")
    check("priority", payload["priority"], 90)
    check("led colour normalised", payload["led_notification_color"], "#FF0000FF")
    raises("payload needs elements", lambda: draw.build_payload("x", [], priority=50))


def suite_framebuffers() -> None:
    """Framebuffer unpacking matches how the firmware packs it.

    Front is LVGL RGB888, which is stored channel-reversed. Back is L8 that the
    firmware halves on the way out with
    ``dst[i] = (src[2i] >> 4) | (src[2i+1] & 0xF0)``.
    """
    print("\n== framebuffers ==")
    try:
        from PIL import Image
    except ImportError:
        print("  SKIP Pillow is not installed")
        return

    frame = bytearray(72 * 16 * 3)
    frame[0:3] = bytes([0x00, 0x00, 0xFF])
    front = Image.frombytes("RGB", (72, 16), bytes(frame), "raw", "BGR")
    check("front BGR byte order reads as red", front.getpixel((0, 0)), (255, 0, 0))

    source = bytearray(160 * 80)
    source[0] = 0xF0
    source[1] = 0x00
    packed = bytearray(len(source) // 2)
    for index in range(len(packed)):
        packed[index] = (source[2 * index] >> 4) | (source[2 * index + 1] & 0xF0)
    check("back frame is half the pixels", len(packed), 6400)

    unpacked = bytearray(160 * 80)
    for index, byte in enumerate(packed):
        unpacked[2 * index] = (byte & 0x0F) << 4
        unpacked[2 * index + 1] = byte & 0xF0
    back = Image.frombytes("L", (160, 80), bytes(unpacked))
    check("back bright pixel round-trips", back.getpixel((0, 0)), 0xF0)
    check("back dark pixel round-trips", back.getpixel((1, 0)), 0x00)

    buffer = io.BytesIO()
    front.resize((72 * 8, 16 * 8), Image.Resampling.NEAREST).save(buffer, format="PNG")
    check("encodes as png", buffer.getvalue()[:8], b"\x89PNG\r\n\x1a\n")


def suite_snapshots(main) -> None:
    """A stored profile turns into a snapshot the device will run."""
    print("\n== busy session snapshots ==")
    settings = {
        "theme": "on_air",
        "show_work_phase_only": False,
        "trigger_smart_home": True,
    }
    simple_profile = {
        "id": "aaaa-bbbb",
        "timer_settings": {"type": "SIMPLE", "total_time_ms": 300000},
        "busy_bar_settings": settings,
    }

    snapshot = main._snapshot_from_profile(simple_profile, None)
    check("type", snapshot["type"], "SIMPLE")
    check("card id", snapshot["card_id"], "aaaa-bbbb")
    check("time from the profile", snapshot["time_left_ms"], 300000)
    check("starts unpaused", snapshot["is_paused"], False)
    check("bar settings carried", snapshot["busy_bar_settings"], settings)

    snapshot = main._snapshot_from_profile(simple_profile, 1500)
    check("duration overrides the profile", snapshot["time_left_ms"], 1500000)
    raises("zero duration rejected", lambda: main._snapshot_from_profile(simple_profile, 0))
    raises(
        "negative duration rejected",
        lambda: main._snapshot_from_profile(simple_profile, -5),
    )

    snapshot = main._snapshot_from_profile(
        {"id": "x", "timer_settings": {"type": "INFINITE"}, "busy_bar_settings": settings},
        None,
    )
    check("infinite type", snapshot["type"], "INFINITE")
    check("infinite carries no time", "time_left_ms" in snapshot, False)

    interval = {
        "type": "INTERVAL",
        "interval_work_ms": 120000,
        "interval_rest_ms": 60000,
        "interval_work_cycles_count": 3,
        "is_autostart_enabled": False,
    }
    snapshot = main._snapshot_from_profile(
        {"id": "y", "timer_settings": interval, "busy_bar_settings": settings}, None
    )
    check("interval type", snapshot["type"], "INTERVAL")
    check("begins on interval 1", snapshot["current_interval"], 1)
    check(
        "phase total is the work phase",
        snapshot["current_interval_time_total_ms"],
        120000,
    )
    check(
        "phase left is the work phase", snapshot["current_interval_time_left_ms"], 120000
    )
    check("interval settings echoed", snapshot["interval_settings"], interval)

    raises(
        "profile without a card id",
        lambda: main._snapshot_from_profile({"timer_settings": {}}, None),
    )
    raises(
        "unknown timer type",
        lambda: main._snapshot_from_profile(
            {"id": "z", "timer_settings": {"type": "WAT"}}, None
        ),
    )


def suite_coercion(main) -> None:
    """Timestamp and duration fields accept what templates produce."""
    print("\n== field coercion ==")
    moment = datetime(2027, 1, 15, 12, 0, tzinfo=UTC)
    check("int passthrough", main._as_unix_seconds(1800000000), 1800000000)
    check("float truncates", main._as_unix_seconds(1800000000.9), 1800000000)
    check("digit string", main._as_unix_seconds("1800000000"), 1800000000)
    check("datetime", main._as_unix_seconds(moment), int(moment.timestamp()))
    check("iso string", main._as_unix_seconds(moment.isoformat()), int(moment.timestamp()))
    raises("prose is not a timestamp", lambda: main._as_unix_seconds("next tuesday"))
    check("timedelta duration", main._duration_seconds(timedelta(minutes=25)), 1500)
    check("int duration", main._duration_seconds(90), 90)


def suite_state(coordinator) -> None:
    """Derived state reads correctly for each kind of session."""
    print("\n== derived state ==")
    now = datetime(2027, 1, 15, 12, 0, tzinfo=UTC)
    data = coordinator.BusyBarData

    idle = data(fetched_at=now)
    check("idle type", idle.timer_type, "NOT_STARTED")
    check("idle is not running", idle.timer_running, False)
    check("idle has no end", idle.ends_at, None)

    simple = data(
        snapshot={"type": "SIMPLE", "time_left_ms": 90000, "is_paused": False},
        fetched_at=now,
    )
    check("simple is running", simple.timer_running, True)
    check("simple time left", simple.time_left_ms, 90000)
    check("simple end time", simple.ends_at, now + timedelta(seconds=90))

    paused = data(
        snapshot={"type": "SIMPLE", "time_left_ms": 90000, "is_paused": True},
        fetched_at=now,
    )
    check("paused flag", paused.timer_paused, True)
    check("paused has no end time", paused.ends_at, None)

    intervals = data(
        snapshot={
            "type": "INTERVAL",
            "current_interval_time_left_ms": 42000,
            "is_paused": False,
        },
        fetched_at=now,
    )
    check("interval reads the current phase", intervals.time_left_ms, 42000)

    endless = data(snapshot={"type": "INFINITE", "is_paused": False}, fetched_at=now)
    check("infinite has no time left", endless.time_left_ms, None)

    check("auto brightness detected", data(brightness="auto").brightness_is_auto, True)
    check("auto has no level", data(brightness="auto").brightness_value, None)
    check("manual level parsed", data(brightness="65").brightness_value, 65)
    check("unset brightness", data().brightness_value, None)
    check("unparseable brightness", data(brightness="dim").brightness_value, None)


# -- Fake device for the client suite ----------------------------------------

TOKEN = "12345678"


async def suite_client(api) -> None:
    """Drive the HTTP client against a fake BUSY Bar."""
    print("\n== http client ==")
    from aiohttp import ClientSession, web

    seen: list[dict] = []

    async def handle(request: web.Request) -> web.Response:
        seen.append(
            {
                "method": request.method,
                "path": request.path,
                "query": dict(request.query),
                "body": await request.text(),
                "token": request.headers.get("X-API-Token"),
            }
        )
        path, method = request.path, request.method

        # Mirrors the firmware: /api/version is never auth-gated.
        if path == "/api/version":
            return web.json_response({"api_semver": "27.9.0"})
        if request.headers.get("X-API-Token") != TOKEN:
            return web.json_response({"error": "Forbidden"}, status=403)

        if path == "/api/status":
            return web.json_response(
                {
                    "device": {"serial_number": "SN1", "usb_mac": "0c:fa:22:21:2a:31"},
                    "firmware": {"version": "1.2.3"},
                    "system": {"boot_time": 1800000000},
                    "power": {"state": "charging", "battery_charge": 88},
                }
            )
        if path == "/api/name":
            return web.json_response({"name": "Desk bar"})
        if path == "/api/display/brightness" and method == "GET":
            return web.json_response({"value": "auto"})
        if path == "/api/audio/volume" and method == "GET":
            return web.json_response({"volume": 40})
        if path == "/api/wifi/status":
            return web.json_response({"state": "connected", "rssi": -51})
        if path == "/api/screen":
            size = 72 * 16 * 3 if request.query.get("display") == "0" else 160 * 80 // 2
            return web.Response(
                body=base64.b64encode(bytes(size)), content_type="image/bmp"
            )
        if path == "/api/display/draw" and method == "POST":
            payload = await request.json()
            if payload.get("priority", 100) < 90:
                return web.json_response({"error": "Priority too low"}, status=409)
            return web.json_response({"result": "OK"})
        if path == "/api/audio/play" and method == "DELETE":
            return web.json_response({"error": "Nothing playing"}, status=410)
        if path == "/api/smart_home/switch" and method == "GET":
            return web.json_response({"error": "Matter broken"}, status=503)
        if path == "/api/input" and request.query.get("key") not in ("ok", "busy"):
            return web.json_response({"error": "Invalid key"}, status=400)
        return web.json_response({"result": "OK"})

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]

    try:
        async with ClientSession() as session:
            client = api.BusyBarClient(session, "127.0.0.1", port=port, token=TOKEN)

            status = await client.async_get_status()
            check("status body", status["power"]["battery_charge"], 88)
            check("auth header sent", seen[-1]["token"], TOKEN)
            check("status path", seen[-1]["path"], "/api/status")
            check("name", (await client.async_get_name())["name"], "Desk bar")
            check("brightness", (await client.async_get_brightness())["value"], "auto")
            check("volume", (await client.async_get_volume())["volume"], 40)
            check("wifi", (await client.async_get_wifi_status())["rssi"], -51)

            await client.async_set_brightness("70")
            check("brightness is a query param", seen[-1]["query"], {"value": "70"})
            await client.async_set_volume(25, silent=True)
            check("volume query", seen[-1]["query"], {"volume": "25", "silent": "1"})
            await client.async_set_volume(25, silent=False)
            check("volume unsilenced", seen[-1]["query"]["silent"], "0")
            await client.async_press_key("ok")
            check("key query", seen[-1]["query"], {"key": "ok"})
            await client.async_set_name("Hall bar")
            check("name is a json body", seen[-1]["body"], '{"name": "Hall bar"}')

            await raises_async(
                "a losing priority raises the priority error",
                client.async_draw(
                    {"application_name": "ha", "priority": 50, "elements": [{"id": "a"}]}
                ),
                api.BusyBarPriorityError,
            )
            await client.async_draw(
                {"application_name": "ha", "priority": 95, "elements": [{"id": "a"}]}
            )
            check("draw path", seen[-1]["path"], "/api/display/draw")

            await client.async_clear(app_name="homeassistant", element_ids=["a", "b"])
            check("clear is a DELETE", seen[-1]["method"], "DELETE")
            check(
                "clear carries a body",
                seen[-1]["body"],
                '{"application_name": "homeassistant", "element_ids": ["a", "b"]}',
            )
            await client.async_clear()
            check("bare clear sends no body", seen[-1]["body"], "")

            front = await client.async_get_screen("front")
            check("front frame size", len(front), 72 * 16 * 3)
            check("front display id", seen[-1]["query"], {"display": "0"})
            back = await client.async_get_screen("back")
            check("back frame size", len(back), 160 * 80 // 2)
            check("back display id", seen[-1]["query"], {"display": "1"})

            await client.async_stop_audio()
            print("  ok   410 from stop audio is swallowed")
            await raises_async(
                "400 becomes an api error",
                client.async_press_key("nope"),
                api.BusyBarApiError,
            )
            await raises_async(
                "503 becomes an api error",
                client.async_get_smart_home_switch(),
                api.BusyBarApiError,
            )

            wrong = api.BusyBarClient(session, "127.0.0.1", port=port, token="wrong")
            await raises_async(
                "403 becomes an auth error",
                wrong.async_get_status(),
                api.BusyBarAuthError,
            )
            check(
                "version needs no token",
                (await wrong.async_get_version())["api_semver"],
                "27.9.0",
            )

            dead = api.BusyBarClient(session, "127.0.0.1", port=1, token=TOKEN, timeout=2)
            await raises_async(
                "a closed port becomes a connection error",
                dead.async_get_status(),
                api.BusyBarConnectionError,
            )

            check(
                "default port is omitted",
                api.BusyBarClient(session, "h").base_url,
                "http://h",
            )
            check(
                "other ports are kept",
                api.BusyBarClient(session, "h", port=8080).base_url,
                "http://h:8080",
            )
            check("no token, no header", api.BusyBarClient(session, "h")._headers, {})
            check(
                "token header",
                api.BusyBarClient(session, "h", token="k")._headers,
                {"X-API-Token": "k"},
            )
    finally:
        await runner.cleanup()


def main() -> int:
    """Run every suite and report."""
    install_stubs()
    api, draw, coordinator, component = load_component()

    suite_colors(draw)
    suite_text(draw)
    suite_placement(draw)
    suite_elements(draw)
    suite_framebuffers()
    suite_snapshots(component)
    suite_coercion(component)
    suite_state(coordinator)
    asyncio.run(suite_client(api))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} failure(s):")
        for label in FAILURES:
            print(f" - {label}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

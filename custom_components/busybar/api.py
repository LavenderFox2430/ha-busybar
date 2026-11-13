"""Async client for the BUSY Bar HTTP API.

The device runs a small Mongoose server on port 80 and documents itself with an
OpenAPI spec (``applications/services/web_server/openapi`` in busybar-firmware).
Everything here maps one-to-one onto that spec; the only place we second-guess it
is :meth:`BusyBarClient.async_get_screen`, see the note there.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any

import aiohttp

from .const import DEFAULT_PORT, DEFAULT_TIMEOUT, SCREEN_IDS

_LOGGER = logging.getLogger(__name__)


class BusyBarError(Exception):
    """Base error for all BUSY Bar API failures."""


class BusyBarConnectionError(BusyBarError):
    """The device could not be reached."""


class BusyBarAuthError(BusyBarError):
    """The access key or token was rejected."""


class BusyBarPriorityError(BusyBarError):
    """A draw request lost to a higher-priority app (HTTP 409)."""


class BusyBarApiError(BusyBarError):
    """The device answered, but refused the request."""

    def __init__(self, message: str, status: int, error_code: str | None = None) -> None:
        """Keep the HTTP status and the firmware error code alongside the text."""
        super().__init__(message)
        self.status = status
        self.error_code = error_code


class BusyBarClient:
    """Talk to one BUSY Bar."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int = DEFAULT_PORT,
        token: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        """Store connection details; nothing is contacted until a call is made."""
        self._session = session
        self._host = host
        self._port = port
        self._token = token or None
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        # The firmware serves a small number of connections and drops them when
        # overloaded, so serialise our own traffic rather than racing ourselves.
        self._lock = asyncio.Lock()

    @property
    def host(self) -> str:
        """Host or IP of the device."""
        return self._host

    @property
    def base_url(self) -> str:
        """Root URL of the device web UI, for the device page link."""
        if self._port == DEFAULT_PORT:
            return f"http://{self._host}"
        return f"http://{self._host}:{self._port}"

    @property
    def _headers(self) -> dict[str, str]:
        """Auth header, when a key or token is configured.

        Over USB ethernet the device grants access without a token; over Wi-Fi it
        needs either the numeric access key or a minted API token, both sent in
        this same header. We deliberately do not send ``X-API-Sem-Ver``: the
        firmware only version-gates requests that carry it.
        """
        if not self._token:
            return {}
        return {"X-API-Token": self._token}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: Any | None = None,
        data: bytes | None = None,
        raw: bool = False,
    ) -> Any:
        """Make one request and normalise every failure into a BusyBarError."""
        url = f"{self.base_url}{path}"
        async with self._lock:
            try:
                response = await self._session.request(
                    method,
                    url,
                    params=params,
                    json=payload,
                    data=data,
                    headers=self._headers,
                    timeout=self._timeout,
                )
                async with response:
                    body = await response.read()
                    status = response.status
            except TimeoutError as err:
                raise BusyBarConnectionError(
                    f"Timed out talking to {self._host}"
                ) from err
            except aiohttp.ClientError as err:
                raise BusyBarConnectionError(
                    f"Cannot reach {self._host}: {err}"
                ) from err

        if status in (401, 403):
            raise BusyBarAuthError(
                _error_text(body) or "Access key or token rejected"
            )
        if status == 409:
            raise BusyBarPriorityError(
                _error_text(body) or "A higher-priority app is using the display"
            )
        if status >= 400:
            text, code = _error_detail(body)
            raise BusyBarApiError(text or f"HTTP {status}", status, code)
        if raw:
            return body
        if not body:
            return {}
        return _decode_json(body)

    # -- Identity and status -------------------------------------------------

    async def async_get_version(self) -> dict[str, Any]:
        """Read the API semver. This endpoint is never auth-gated."""
        return await self._request("GET", "/api/version")

    async def async_get_status(self) -> dict[str, Any]:
        """Read device, firmware, system and power status in one call."""
        return await self._request("GET", "/api/status")

    async def async_get_device_status(self) -> dict[str, Any]:
        """Read just the device block (serial number, MACs, model)."""
        return await self._request("GET", "/api/status/device")

    async def async_get_transport(self) -> dict[str, Any]:
        """Report whether we are talking over USB or Wi-Fi."""
        return await self._request("GET", "/api/transport")

    async def async_get_wifi_status(self) -> dict[str, Any]:
        """Read Wi-Fi state; SSID, RSSI and IP appear only when connected."""
        return await self._request("GET", "/api/wifi/status")

    async def async_get_name(self) -> dict[str, Any]:
        """Read the user-visible device name."""
        return await self._request("GET", "/api/name")

    async def async_set_name(self, name: str) -> None:
        """Rename the device."""
        await self._request("POST", "/api/name", payload={"name": name})

    # -- BUSY timer ----------------------------------------------------------

    async def async_get_busy_snapshot(self) -> dict[str, Any]:
        """Read the running timer snapshot."""
        return await self._request("GET", "/api/busy/snapshot")

    async def async_set_busy_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Run the timer from the given snapshot."""
        await self._request("PUT", "/api/busy/snapshot", payload=snapshot)

    async def async_get_busy_profile(self, slot: str) -> dict[str, Any]:
        """Read the profile stored in the busy or custom slot."""
        return await self._request("GET", f"/api/busy/profiles/{slot}")

    # -- Settings ------------------------------------------------------------

    async def async_get_brightness(self) -> dict[str, Any]:
        """Read display brightness, reported as auto or as a 0-100 string."""
        return await self._request("GET", "/api/display/brightness")

    async def async_set_brightness(self, value: str) -> None:
        """Set display brightness to auto or to a 0-100 string."""
        await self._request(
            "POST", "/api/display/brightness", params={"value": value}
        )

    async def async_get_volume(self) -> dict[str, Any]:
        """Read the audio volume."""
        return await self._request("GET", "/api/audio/volume")

    async def async_set_volume(self, volume: int, silent: bool = True) -> None:
        """Set the audio volume, by default without the confirmation blip."""
        await self._request(
            "POST",
            "/api/audio/volume",
            params={"volume": volume, "silent": 1 if silent else 0},
        )

    async def async_get_smart_home_switch(self) -> dict[str, Any]:
        """Read the state of the emulated Matter switch."""
        return await self._request("GET", "/api/smart_home/switch")

    async def async_set_smart_home_switch(self, state: bool) -> None:
        """Flip the emulated Matter switch."""
        await self._request(
            "POST", "/api/smart_home/switch", payload={"state": state}
        )

    async def async_get_smart_home_pairing(self) -> dict[str, Any]:
        """Read how many Matter fabrics the device is commissioned into."""
        return await self._request("GET", "/api/smart_home/pairing")

    # -- Display -------------------------------------------------------------

    async def async_draw(self, payload: dict[str, Any]) -> None:
        """Push a DisplayElements payload to the screens."""
        await self._request("POST", "/api/display/draw", payload=payload)

    async def async_clear(
        self,
        app_name: str | None = None,
        element_ids: list[str] | None = None,
    ) -> None:
        """Remove elements drawn through the API.

        With no arguments this clears everything the draw API has put on screen.
        Passing ``app_name`` restricts it to that application's elements, and
        ``element_ids`` to specific ones.
        """
        body: dict[str, Any] = {}
        if app_name:
            body["application_name"] = app_name
        if element_ids:
            body["element_ids"] = element_ids
        await self._request(
            "DELETE", "/api/display/draw", payload=body if body else None
        )

    async def async_get_screen(self, display: str) -> bytes:
        """Grab one frame of a display as a raw framebuffer.

        The OpenAPI spec labels this ``image/bmp``, but the firmware replies with
        base64 of the raw LVGL framebuffer: ``MG_REPLY_IMAGE`` pipes the bytes
        through ``mg_print_base64``. So decode the base64 here and let the caller
        turn the pixels into an image.

        Front is RGB888 at 72x16 -- LVGL stores that channel-reversed, so the
        bytes arrive as B, G, R. Back is 160x80 8-bit greyscale packed down to
        4 bits per pixel, two pixels per byte.
        """
        body = await self._request(
            "GET", "/api/screen", params={"display": SCREEN_IDS[display]}, raw=True
        )
        try:
            return base64.b64decode(body, validate=False)
        except (ValueError, TypeError) as err:
            raise BusyBarError(f"Malformed frame from {self._host}") from err

    # -- Audio, input, assets ------------------------------------------------

    async def async_play_sound(
        self,
        app_name: str,
        path: str | None = None,
        stock_path: str | None = None,
    ) -> None:
        """Play a sound from the app assets or from the stock library."""
        body: dict[str, Any] = {"application_name": app_name}
        if stock_path:
            body["stock_path"] = stock_path
        elif path:
            body["path"] = path
        else:
            raise BusyBarError("Either path or stock_path is required")
        await self._request("POST", "/api/audio/play", payload=body)

    async def async_stop_audio(self) -> None:
        """Stop playback. The device answers 410 when nothing is playing."""
        try:
            await self._request("DELETE", "/api/audio/play")
        except BusyBarApiError as err:
            if err.status != 410:
                raise

    async def async_press_key(self, key: str) -> None:
        """Inject a single key press."""
        await self._request("POST", "/api/input", params={"key": key})

    async def async_upload_asset(self, app_name: str, path: str, data: bytes) -> None:
        """Upload a file into the app asset directory."""
        await self._request(
            "POST",
            "/api/assets/upload",
            params={"application_name": app_name, "file": path},
            data=data,
        )


def _decode_json(body: bytes) -> Any:
    """Parse a JSON body, tolerating the odd endpoint that returns bare text."""
    try:
        return json.loads(body)
    except ValueError:
        return {"raw": body.decode("utf-8", "replace")}


def _error_detail(body: bytes) -> tuple[str | None, str | None]:
    """Pull error and error_code out of an error body."""
    payload = _decode_json(body)
    if isinstance(payload, dict):
        return payload.get("error"), payload.get("error_code")
    return None, None


def _error_text(body: bytes) -> str | None:
    """Pull just the human-readable part of an error body."""
    return _error_detail(body)[0]

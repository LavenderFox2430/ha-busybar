"""Config flow for the BUSY Bar integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL, CONF_TOKEN
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .api import BusyBarAuthError, BusyBarClient, BusyBarError
from .const import (
    CONF_APP_NAME,
    CONF_DEFAULT_PRIORITY,
    CONF_TEXT_COLOR,
    CONF_TEXT_FONT,
    CONF_TEXT_TIMEOUT,
    DEFAULT_APP_NAME,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_PRIORITY,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TEXT_COLOR,
    DEFAULT_TEXT_FONT,
    DEFAULT_TEXT_TIMEOUT,
    DOMAIN,
    FONTS,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

# mDNS advertises the bar as "busybar-<usb mac>._http._tcp.local.". That MAC is
# also a required field of /api/status/device, so both the discovered and the
# manually added flow can agree on one unique ID for the same device.
ZEROCONF_PREFIX = "busybar-"


def _normalize_mac(value: str) -> str:
    """Reduce a MAC to bare lowercase hex, however it was punctuated."""
    return "".join(char for char in value.lower() if char in "0123456789abcdef")


class BusyBarConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle adding a BUSY Bar."""

    VERSION = 1

    def __init__(self) -> None:
        """Start with nothing discovered."""
        self._host: str | None = None
        self._port: int = DEFAULT_PORT
        self._discovered_name: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a bar by address."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = int(user_input.get(CONF_PORT, DEFAULT_PORT))
            token = (user_input.get(CONF_TOKEN) or "").strip()
            info, error = await self._async_probe(host, port, token)
            if error:
                errors["base"] = error
            else:
                return await self._async_finish(host, port, token, info)

        reconfigure = self.source == SOURCE_RECONFIGURE
        defaults: dict[str, Any] = {CONF_HOST: "", CONF_PORT: DEFAULT_PORT}
        if reconfigure:
            entry = self._get_reconfigure_entry()
            defaults = {
                CONF_HOST: entry.data[CONF_HOST],
                CONF_PORT: entry.data.get(CONF_PORT, DEFAULT_PORT),
            }
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=defaults[CONF_HOST]): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    ),
                    vol.Optional(CONF_TOKEN): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Optional(CONF_PORT, default=defaults[CONF_PORT]): NumberSelector(
                        NumberSelectorConfig(min=1, max=65535, mode=NumberSelectorMode.BOX)
                    ),
                }
            ),
            errors=errors,
            description_placeholders={"default_port": str(DEFAULT_PORT)},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the address or the access key of an existing bar."""
        return await self.async_step_user(user_input)

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle a bar announcing itself over mDNS."""
        instance = discovery_info.name.partition(".")[0]
        if not instance.lower().startswith(ZEROCONF_PREFIX):
            return self.async_abort(reason="not_busybar")

        mac = _normalize_mac(instance[len(ZEROCONF_PREFIX) :])
        if not mac:
            return self.async_abort(reason="not_busybar")

        host = str(discovery_info.ip_address)
        await self.async_set_unique_id(mac)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        self._host = host
        self._port = discovery_info.port or DEFAULT_PORT
        properties = discovery_info.properties or {}
        self._discovered_name = properties.get("name") or DEFAULT_NAME
        self.context["title_placeholders"] = {"name": self._discovered_name}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a discovered bar, asking for its access key if it needs one."""
        assert self._host is not None
        errors: dict[str, str] = {}
        token = ""

        if user_input is not None:
            token = (user_input.get(CONF_TOKEN) or "").strip()
            info, error = await self._async_probe(self._host, self._port, token)
            if error:
                errors["base"] = error
            else:
                return await self._async_finish(self._host, self._port, token, info)
        else:
            # A bar reached over USB, or one with Wi-Fi access left open, needs no
            # key at all: check first so the form does not demand one pointlessly.
            info, error = await self._async_probe(self._host, self._port, "")
            if not error:
                return await self._async_finish(self._host, self._port, "", info)

        return self.async_show_form(
            step_id="discovery_confirm",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_TOKEN): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
            description_placeholders={
                "name": self._discovered_name or DEFAULT_NAME,
                "host": self._host,
            },
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """The stored access key stopped working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a fresh access key or API token."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            token = (user_input.get(CONF_TOKEN) or "").strip()
            host = entry.data[CONF_HOST]
            port = entry.data.get(CONF_PORT, DEFAULT_PORT)
            _info, error = await self._async_probe(host, port, token)
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_TOKEN: token}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_TOKEN): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
            description_placeholders={"host": entry.data[CONF_HOST]},
        )

    async def _async_probe(
        self, host: str, port: int, token: str
    ) -> tuple[dict[str, Any], str | None]:
        """Contact the bar and read the fields we key the entry on."""
        client = BusyBarClient(
            session=async_get_clientsession(self.hass),
            host=host,
            port=port,
            token=token or None,
        )
        try:
            device = await client.async_get_device_status()
        except BusyBarAuthError:
            return {}, "invalid_auth"
        except BusyBarError as err:
            _LOGGER.debug("Probe of %s failed: %s", host, err)
            return {}, "cannot_connect"

        if not device.get("usb_mac"):
            return {}, "not_busybar"

        name: str | None = None
        try:
            name = (await client.async_get_name()).get("name")
        except BusyBarError:
            # Cosmetic only: fall back to the product name for the entry title.
            pass
        return {"device": device, "name": name}, None

    async def _async_finish(
        self, host: str, port: int, token: str, info: dict[str, Any]
    ) -> ConfigFlowResult:
        """Create, reconfigure, or bail out on a duplicate."""
        device = info["device"]
        data = {CONF_HOST: host, CONF_PORT: port, CONF_TOKEN: token}
        unique_id = _normalize_mac(device["usb_mac"])
        title = info.get("name") or self._discovered_name or DEFAULT_NAME

        if self.source == SOURCE_RECONFIGURE:
            entry = self._get_reconfigure_entry()
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_mismatch(reason="wrong_device")
            return self.async_update_reload_and_abort(entry, data_updates=data)

        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured(updates=data)
        return self.async_create_entry(title=title, data=data)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: Any) -> BusyBarOptionsFlow:
        """Get the options flow for this handler."""
        return BusyBarOptionsFlow()


class BusyBarOptionsFlow(OptionsFlow):
    """Tune polling and the defaults used when drawing."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and store the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                    CONF_APP_NAME: user_input[CONF_APP_NAME].strip(),
                    CONF_DEFAULT_PRIORITY: int(user_input[CONF_DEFAULT_PRIORITY]),
                    CONF_TEXT_FONT: user_input[CONF_TEXT_FONT],
                    CONF_TEXT_COLOR: user_input[CONF_TEXT_COLOR].strip(),
                    CONF_TEXT_TIMEOUT: int(user_input[CONF_TEXT_TIMEOUT]),
                }
            )

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL,
                            max=600,
                            step=1,
                            unit_of_measurement="seconds",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_APP_NAME,
                        default=options.get(CONF_APP_NAME, DEFAULT_APP_NAME),
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                    vol.Required(
                        CONF_DEFAULT_PRIORITY,
                        default=options.get(CONF_DEFAULT_PRIORITY, DEFAULT_PRIORITY),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1, max=100, step=1, mode=NumberSelectorMode.SLIDER
                        )
                    ),
                    vol.Required(
                        CONF_TEXT_FONT,
                        default=options.get(CONF_TEXT_FONT, DEFAULT_TEXT_FONT),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=FONTS,
                            mode=SelectSelectorMode.DROPDOWN,
                            translation_key="font",
                        )
                    ),
                    vol.Required(
                        CONF_TEXT_COLOR,
                        default=options.get(CONF_TEXT_COLOR, DEFAULT_TEXT_COLOR),
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                    vol.Required(
                        CONF_TEXT_TIMEOUT,
                        default=options.get(CONF_TEXT_TIMEOUT, DEFAULT_TEXT_TIMEOUT),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0,
                            max=86400,
                            step=1,
                            unit_of_measurement="seconds",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )

"""Config flow for Miner."""
from __future__ import annotations

import logging

import pyasic
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from .const import (
    CONF_IP,
    CONF_MAX_POWER,
    CONF_MIN_POWER,
    CONF_RPC_PASSWORD,
    CONF_SSH_PASSWORD,
    CONF_SSH_USERNAME,
    CONF_TITLE,
    CONF_WEB_PASSWORD,
    CONF_WEB_USERNAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _normalize_model_name(miner) -> str:
    """Return friendly miner / firmware model name."""
    try:
        raw_model = str(getattr(miner, "model", "") or "").strip()
        raw_type = str(getattr(miner, "type", "") or "").strip()
        raw_make = str(getattr(miner, "make", "") or "").strip()

        text = " ".join(x for x in [raw_make, raw_model, raw_type] if x).lower()

        if "antminer" in text:
            return raw_model or "Antminer"
        if "whatsminer" in text:
            return raw_model or "WhatsMiner"
        if "avalon" in text:
            return raw_model or "AvalonMiner"
        if "innosilicon" in text:
            return raw_model or "Innosilicon"
        if "goldshell" in text:
            return raw_model or "Goldshell"
        if "auradine" in text:
            return raw_model or "Auradine"
        if "bitaxe" in text:
            return raw_model or "BitAxe"
        if "iceriver" in text:
            return raw_model or "IceRiver"
        if "hammer" in text:
            return raw_model or "Hammer"

        if "braiins" in text:
            return raw_model or "Braiins Firmware"
        if "vnish" in text:
            return raw_model or "Vnish Firmware"
        if "epic" in text:
            return raw_model or "ePIC Firmware"
        if "hiveos" in text:
            return raw_model or "HiveOS Firmware"
        if "luxos" in text:
            return raw_model or "LuxOS Firmware"
        if "mara" in text:
            return raw_model or "Mara Firmware"

        return raw_model or raw_make or raw_type or "Miner"
    except Exception:
        return "Miner"


async def validate_ip_input(
    data: dict[str, str],
) -> tuple[dict[str, str], pyasic.AnyMiner | None]:
    """Validate the user input allows us to connect."""
    miner_ip = data.get(CONF_IP)

    miner = await pyasic.get_miner(miner_ip)
    if miner is None:
        return {"base": "cannot_connect"}, None

    return {}, miner


class MinerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Miner."""

    VERSION = 1

    def __init__(self):
        """Initialize."""
        self._data: dict[str, str | int] = {}
        self._miner = None

    async def _async_get_unique_id(self, miner, host: str) -> str:
        """Build a stable unique ID for the miner."""
        try:
            for attr in ("mac", "mac_address", "serial", "serial_number"):
                value = getattr(miner, attr, None)
                if value:
                    return str(value).lower()
        except Exception:
            pass

        return host.lower()

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo):
        """Handle DHCP discovery."""
        host = discovery_info.ip
        ip_tail = str(host).split(".")[-1]

        miner = await pyasic.get_miner(host)
        if miner is None:
            return self.async_abort(reason="no_devices_found")

        model = _normalize_model_name(miner)
        display_name = f"{model} (ip {ip_tail})"

        self.context["title_placeholders"] = {"name": display_name}

        unique_id = await self._async_get_unique_id(miner, host)
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured(
            updates={CONF_IP: host, CONF_HOST: host}
        )

        self._miner = miner
        self._data.update(
            {
                CONF_IP: host,
                CONF_MIN_POWER: 15,
                CONF_MAX_POWER: 10000,
            }
        )

        return await self.async_step_login()

    async def async_step_user(self, user_input=None):
        """Get miner IP and check if it is available."""
        if user_input is None:
            user_input = {}

        schema = vol.Schema(
            {
                vol.Required(CONF_IP, default=user_input.get(CONF_IP, "")): str,
                vol.Optional(
                    CONF_MIN_POWER,
                    default=user_input.get(CONF_MIN_POWER, 15),
                ): vol.All(vol.Coerce(int), vol.Range(min=15, max=10000)),
                vol.Optional(
                    CONF_MAX_POWER,
                    default=user_input.get(CONF_MAX_POWER, 10000),
                ): vol.All(vol.Coerce(int), vol.Range(min=15, max=10000)),
            }
        )

        if not user_input:
            return self.async_show_form(step_id="user", data_schema=schema)

        errors, miner = await validate_ip_input(user_input)

        if errors:
            return self.async_show_form(
                step_id="user",
                data_schema=schema,
                errors=errors,
            )

        unique_id = await self._async_get_unique_id(miner, user_input[CONF_IP])
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured(
            updates={CONF_IP: user_input[CONF_IP], CONF_HOST: user_input[CONF_IP]}
        )

        self._miner = miner
        self._data.update(user_input)
        return await self.async_step_login()

    async def async_step_login(self, user_input=None):
        """Get miner login credentials."""
        if user_input is None:
            user_input = {}

        schema_data = {}

        if self._miner.rpc is not None:
            if self._miner.rpc.pwd is not None:
                schema_data[
                    vol.Optional(
                        CONF_RPC_PASSWORD,
                        default=user_input.get(
                            CONF_RPC_PASSWORD,
                            self._miner.rpc.pwd
                            if self._miner.api.pwd is not None
                            else "",
                        ),
                    )
                ] = TextSelector(
                    TextSelectorConfig(
                        type=TextSelectorType.PASSWORD,
                        autocomplete="current-password",
                    )
                )

        if self._miner.web is not None:
            schema_data[
                vol.Optional(
                    CONF_WEB_USERNAME,
                    default=user_input.get(CONF_WEB_USERNAME, self._miner.web.username),
                )
            ] = str
            schema_data[
                vol.Optional(
                    CONF_WEB_PASSWORD,
                    default=user_input.get(
                        CONF_WEB_PASSWORD,
                        self._miner.web.pwd if self._miner.web.pwd is not None else "",
                    ),
                )
            ] = TextSelector(
                TextSelectorConfig(
                    type=TextSelectorType.PASSWORD,
                    autocomplete="current-password",
                )
            )

        if self._miner.ssh is not None:
            schema_data[
                vol.Required(
                    CONF_SSH_USERNAME,
                    default=user_input.get(CONF_SSH_USERNAME, self._miner.ssh.username),
                )
            ] = str
            schema_data[
                vol.Optional(
                    CONF_SSH_PASSWORD,
                    default=user_input.get(
                        CONF_SSH_PASSWORD,
                        self._miner.ssh.pwd if self._miner.ssh.pwd is not None else "",
                    ),
                )
            ] = TextSelector(
                TextSelectorConfig(
                    type=TextSelectorType.PASSWORD,
                    autocomplete="current-password",
                )
            )

        schema = vol.Schema(schema_data)

        if not user_input:
            if len(schema_data) == 0:
                return await self.async_step_title()
            return self.async_show_form(step_id="login", data_schema=schema)

        self._data.update(user_input)
        return await self.async_step_title()

    async def async_step_title(self, user_input=None):
        """Get entity title."""
        if self._miner.api is not None:
            if self._miner.api.pwd is not None:
                self._miner.api.pwd = self._data.get(CONF_RPC_PASSWORD, "")

        if self._miner.web is not None:
            self._miner.web.username = self._data.get(CONF_WEB_USERNAME, "")
            self._miner.web.pwd = self._data.get(CONF_WEB_PASSWORD, "")

        if self._miner.ssh is not None:
            self._miner.ssh.username = self._data.get(CONF_SSH_USERNAME, "")
            self._miner.ssh.pwd = self._data.get(CONF_SSH_PASSWORD, "")

        title = await self._miner.get_hostname()

        if user_input is None:
            user_input = {}

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_TITLE,
                    default=user_input.get(CONF_TITLE, title),
                ): str,
            }
        )

        if not user_input:
            return self.async_show_form(step_id="title", data_schema=data_schema)

        self._data.update(user_input)

        return self.async_create_entry(title=self._data[CONF_TITLE], data=self._data)

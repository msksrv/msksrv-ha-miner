"""Config flow for Miner."""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from typing import Any

import pyasic
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.core import split_entity_id
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from .const import (
    CONF_IP,
    CONF_MAX_POWER,
    CONF_MIN_POWER,
    CONF_POWER_SWITCH,
    CONF_RPC_PASSWORD,
    CONF_SELECTED_MINER,
    CONF_SSH_PASSWORD,
    CONF_SSH_USERNAME,
    CONF_SUBNET,
    CONF_TITLE,
    CONF_WEB_PASSWORD,
    CONF_WEB_USERNAME,
    DEFAULT_MAX_POWER,
    DEFAULT_MIN_POWER,
    DEFAULT_SUBNET,
    DOMAIN,
    SCAN_MAX_HOSTS,
)
from .discovery import (
    DiscoveredMiner,
    async_scan_subnet,
    get_stable_identifier,
    normalize_model_name,
)

_LOGGER = logging.getLogger(__name__)


async def validate_ip_input(
    data: dict[str, Any],
) -> tuple[dict[str, str], pyasic.AnyMiner | None]:
    """Validate that the miner is reachable."""
    miner_ip = str(data.get(CONF_IP, "")).strip()

    if not miner_ip:
        return {"base": "cannot_connect"}, None

    try:
        miner = await asyncio.wait_for(pyasic.get_miner(miner_ip), timeout=5)
    except Exception:
        return {"base": "cannot_connect"}, None

    if miner is None:
        return {"base": "cannot_connect"}, None

    return {}, miner


class MinerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Miner."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> MinerOptionsFlow:
        """Return the options flow for this integration."""
        return MinerOptionsFlow()

    def __init__(self) -> None:
        """Initialize flow state."""
        self._data: dict[str, Any] = {}
        self._miner = None
        self._scan_task: asyncio.Task[list[DiscoveredMiner]] | None = None
        self._scan_results: list[DiscoveredMiner] = []
        self._scan_input: dict[str, Any] = {}

    def _default_subnet(self) -> str:
        """Try to detect the most likely local IPv4 /24 subnet."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.connect(("8.8.8.8", 80))
                ip = ipaddress.ip_address(sock.getsockname()[0])
                if isinstance(ip, ipaddress.IPv4Address) and not ip.is_loopback:
                    return str(ipaddress.ip_network(f"{ip}/24", strict=False))
            finally:
                sock.close()
        except Exception:
            pass

        return DEFAULT_SUBNET

    def _scan_schema(self, user_input: dict[str, Any] | None = None) -> vol.Schema:
        """Return scan schema."""
        user_input = user_input or {}

        return vol.Schema(
            {
                vol.Required(
                    CONF_SUBNET,
                    default=user_input.get(CONF_SUBNET, self._default_subnet()),
                ): str,
                vol.Optional(
                    CONF_MIN_POWER,
                    default=user_input.get(CONF_MIN_POWER, DEFAULT_MIN_POWER),
                ): vol.All(vol.Coerce(int), vol.Range(min=15, max=10000)),
                vol.Optional(
                    CONF_MAX_POWER,
                    default=user_input.get(CONF_MAX_POWER, DEFAULT_MAX_POWER),
                ): vol.All(vol.Coerce(int), vol.Range(min=15, max=10000)),
            }
        )

    def _manual_schema(self, user_input: dict[str, Any] | None = None) -> vol.Schema:
        """Return manual input schema."""
        user_input = user_input or {}

        return vol.Schema(
            {
                vol.Required(CONF_IP, default=user_input.get(CONF_IP, "")): str,
                vol.Optional(
                    CONF_MIN_POWER,
                    default=user_input.get(CONF_MIN_POWER, DEFAULT_MIN_POWER),
                ): vol.All(vol.Coerce(int), vol.Range(min=15, max=10000)),
                vol.Optional(
                    CONF_MAX_POWER,
                    default=user_input.get(CONF_MAX_POWER, DEFAULT_MAX_POWER),
                ): vol.All(vol.Coerce(int), vol.Range(min=15, max=10000)),
            }
        )

    def _has_entry_with_host(self, host: str) -> bool:
        """Check if host is already configured."""
        host = str(host).strip()
        for entry in self._async_current_entries():
            if str(entry.data.get(CONF_IP, "")).strip() == host:
                return True
        return False

    async def _async_set_unique_or_match_existing(self, miner, host: str) -> None:
        """Set unique ID if available, otherwise only check by host."""
        stable_id = get_stable_identifier(miner)
        if stable_id:
            await self.async_set_unique_id(stable_id)
            self._abort_if_unique_id_configured(
                updates={CONF_IP: host, CONF_HOST: host}
            )
            return

        if self.source == config_entries.SOURCE_DHCP:
            await self._async_handle_discovery_without_unique_id()
            return

        if self._has_entry_with_host(host):
            raise config_entries.AbortFlow("already_configured")

    async def _async_prepare_miner(
        self, miner, host: str, base_data: dict[str, Any]
    ) -> None:
        """Store common flow data after miner was resolved."""
        await self._async_set_unique_or_match_existing(miner, host)
        self._miner = miner
        self._data.update(base_data)

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo):
        """Handle DHCP discovery."""
        host = str(discovery_info.ip)
        ip_tail = host.split(".")[-1]

        try:
            miner = await asyncio.wait_for(pyasic.get_miner(host), timeout=5)
        except Exception:
            miner = None

        if miner is None:
            return self.async_abort(reason="no_devices_found")

        model = normalize_model_name(miner)
        display_name = f"{model} (ip {ip_tail})"
        self.context["title_placeholders"] = {"name": display_name}

        try:
            await self._async_prepare_miner(
                miner,
                host,
                {
                    CONF_IP: host,
                    CONF_MIN_POWER: DEFAULT_MIN_POWER,
                    CONF_MAX_POWER: DEFAULT_MAX_POWER,
                },
            )
        except config_entries.AbortFlow as err:
            return self.async_abort(reason=err.reason)

        return await self.async_step_login()

    async def async_step_user(self, user_input=None):
        """Show entry mode menu."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["scan", "manual"],
            sort=False,
        )

    async def async_step_manual(self, user_input=None):
        """Manual miner setup by IP."""
        errors: dict[str, str] = {}
        schema = self._manual_schema(user_input)

        if not user_input:
            return self.async_show_form(step_id="manual", data_schema=schema)

        errors, miner = await validate_ip_input(user_input)

        if errors:
            return self.async_show_form(
                step_id="manual",
                data_schema=schema,
                errors=errors,
            )

        host = str(user_input[CONF_IP]).strip()

        try:
            await self._async_prepare_miner(miner, host, user_input)
        except config_entries.AbortFlow as err:
            return self.async_abort(reason=err.reason)

        return await self.async_step_login()

    async def _async_run_scan(self, subnet: str) -> list[DiscoveredMiner]:
        """Background subnet scan."""

        def _progress(value: float) -> None:
            self.async_update_progress(value)

        return await async_scan_subnet(subnet, progress_callback=_progress)

    async def async_step_scan(self, user_input=None):
        """Scan local subnet for miners."""
        errors: dict[str, str] = {}

        if self._scan_task:
            if not self._scan_task.done():
                return self.async_show_progress(
                    step_id="scan",
                    progress_action="network_scan",
                    progress_task=self._scan_task,
                )

            try:
                self._scan_results = self._scan_task.result()
            except ValueError as err:
                _LOGGER.debug("Subnet scan validation failed: %s", err)
                self._scan_task = None
                errors["base"] = "invalid_subnet"
            except Exception as err:
                _LOGGER.exception("Miner subnet scan failed: %s", err)
                self._scan_task = None
                errors["base"] = "scan_failed"
            else:
                self._scan_task = None
                return self.async_show_progress_done(next_step_id="pick_miner")

        schema = self._scan_schema(user_input or self._scan_input)

        if errors:
            return self.async_show_form(
                step_id="scan",
                data_schema=schema,
                errors=errors,
            )

        if not user_input:
            return self.async_show_form(step_id="scan", data_schema=schema)

        subnet = str(user_input[CONF_SUBNET]).strip()

        try:
            network = ipaddress.ip_network(subnet, strict=False)
            if network.version != 4 or network.num_addresses > SCAN_MAX_HOSTS:
                raise ValueError
        except ValueError:
            return self.async_show_form(
                step_id="scan",
                data_schema=schema,
                errors={"base": "invalid_subnet"},
            )

        self._scan_input = dict(user_input)
        self._scan_task = self.hass.async_create_task(self._async_run_scan(subnet))

        return self.async_show_progress(
            step_id="scan",
            progress_action="network_scan",
            progress_task=self._scan_task,
        )

    async def async_step_pick_miner(self, user_input=None):
        """Pick a discovered miner."""
        if not self._scan_results:
            return self.async_show_form(
                step_id="scan",
                data_schema=self._scan_schema(self._scan_input),
                errors={"base": "no_devices_found"},
            )

        options = {
            item.ip: (
                f"{item.model} — {item.ip}"
                + (f" — {item.hostname}" if item.hostname else "")
            )
            for item in self._scan_results
        }

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SELECTED_MINER,
                    default=(
                        user_input.get(CONF_SELECTED_MINER)
                        if user_input
                        else next(iter(options))
                    ),
                ): vol.In(options),
            }
        )

        if not user_input:
            return self.async_show_form(step_id="pick_miner", data_schema=schema)

        selected_ip = str(user_input[CONF_SELECTED_MINER]).strip()

        try:
            miner = await asyncio.wait_for(pyasic.get_miner(selected_ip), timeout=5)
        except Exception:
            miner = None

        if miner is None:
            return self.async_show_form(
                step_id="pick_miner",
                data_schema=schema,
                errors={"base": "cannot_connect"},
            )

        base_data = {
            CONF_IP: selected_ip,
            CONF_MIN_POWER: self._scan_input.get(CONF_MIN_POWER, DEFAULT_MIN_POWER),
            CONF_MAX_POWER: self._scan_input.get(CONF_MAX_POWER, DEFAULT_MAX_POWER),
        }

        try:
            await self._async_prepare_miner(miner, selected_ip, base_data)
        except config_entries.AbortFlow as err:
            return self.async_abort(reason=err.reason)

        model = normalize_model_name(miner)
        self.context["title_placeholders"] = {
            "name": f"{model} ({selected_ip})"
        }

        return await self.async_step_login()

    async def async_step_login(self, user_input=None):
        """Get miner login credentials."""
        if user_input is None:
            user_input = {}

        schema_data = {}

        if self._miner.rpc is not None and self._miner.rpc.pwd is not None:
            schema_data[
                vol.Optional(
                    CONF_RPC_PASSWORD,
                    default=user_input.get(
                        CONF_RPC_PASSWORD,
                        self._miner.rpc.pwd or "",
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
                    default=user_input.get(
                        CONF_WEB_USERNAME,
                        self._miner.web.username,
                    ),
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
                    default=user_input.get(
                        CONF_SSH_USERNAME,
                        self._miner.ssh.username,
                    ),
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
        if self._miner.api is not None and self._miner.api.pwd is not None:
            self._miner.api.pwd = self._data.get(CONF_RPC_PASSWORD, "")

        if self._miner.web is not None:
            self._miner.web.username = self._data.get(CONF_WEB_USERNAME, "")
            self._miner.web.pwd = self._data.get(CONF_WEB_PASSWORD, "")

        if self._miner.ssh is not None:
            self._miner.ssh.username = self._data.get(CONF_SSH_USERNAME, "")
            self._miner.ssh.pwd = self._data.get(CONF_SSH_PASSWORD, "")

        try:
            title = await self._miner.get_hostname()
        except Exception:
            title = None

        if not title:
            title = self._data.get(CONF_IP, "Miner")

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
        return self.async_create_entry(
            title=self._data[CONF_TITLE],
            data=self._data,
        )


class MinerOptionsFlow(config_entries.OptionsFlow):
    """Options for a Miner config entry (e.g. linked power switch)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ):
        """Manage miner options."""
        if user_input is not None:
            new_options = {**self.config_entry.options}
            entity_id = user_input.get(CONF_POWER_SWITCH)
            if entity_id:
                try:
                    ent_domain, _ = split_entity_id(entity_id)
                except ValueError:
                    ent_domain = ""
                registry = er.async_get(self.hass)
                entity = registry.async_get(entity_id)
                if entity is None or ent_domain != "switch":
                    return self.async_show_form(
                        step_id="init",
                        data_schema=self._options_schema(user_input),
                        errors={"base": "invalid_switch"},
                    )
                new_options[CONF_POWER_SWITCH] = entity_id
            else:
                new_options.pop(CONF_POWER_SWITCH, None)

            return self.async_create_entry(title="", data=new_options)

        return self.async_show_form(
            step_id="init",
            data_schema=self._options_schema(),
        )

    def _options_schema(
        self, user_input: dict[str, Any] | None = None
    ) -> vol.Schema:
        """Build options schema (EntitySelector needs suggested_value, not default=None)."""
        user_input = user_input or {}
        stored = self.config_entry.options.get(CONF_POWER_SWITCH)
        suggested = user_input.get(CONF_POWER_SWITCH, stored)
        optional_kwargs: dict[str, Any] = {}
        if suggested:
            optional_kwargs["description"] = {"suggested_value": suggested}
        return vol.Schema(
            {
                vol.Optional(CONF_POWER_SWITCH, **optional_kwargs): EntitySelector(
                    EntitySelectorConfig(domain="switch"),
                ),
            }
        )

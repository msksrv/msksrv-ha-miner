"""Config flow for Miner."""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import logging
import socket
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.selector import (
    DeviceSelector,
    DeviceSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from .config_flow_options import MinerOptionsFlow
from .const import (
    CONF_FARM_DEVICE_IDS,
    CONF_IP,
    CONF_IS_FARM,
    CONF_MAX_POWER,
    CONF_MIN_POWER,
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
from .device_resolution import (
    async_get_miner_config_entry_for_device,
    is_miner_already_configured,
)
from .discovery import (
    DiscoveredMiner,
    async_scan_subnet,
    filter_unconfigured_miners,
    get_stable_identifier,
    normalize_model_name,
)

_LOGGER = logging.getLogger(__name__)

_POWER_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=15,
        max=10000,
        step=1,
        unit_of_measurement="W",
        mode="box",
    )
)

# DHCP discovery: probe miner API a few times (miner may boot slower than DHCP).
_DHCP_PROBE_ATTEMPTS = 3
_DHCP_PROBE_TIMEOUT_SEC = 6
_DHCP_PROBE_BACKOFF_SEC = (2, 5)


async def validate_ip_input(
    data: dict[str, Any],
) -> tuple[dict[str, str], Any]:
    """Validate that the miner is reachable."""
    import pyasic

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

    @classmethod
    @callback
    def async_supports_options_flow(
        cls, config_entry: config_entries.ConfigEntry
    ) -> bool:
        """Farm: room temperature entity links. Miner: power switch + pool.

        Do not call super(): older HA cores have no ConfigFlow.async_supports_options_flow
        and would raise AttributeError (500 on config flow).
        """
        return (
            cls.async_get_options_flow
            is not config_entries.ConfigFlow.async_get_options_flow
        )

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
        self._scan_had_unfiltered: bool = False
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
                    description={
                        "suggested_value": user_input.get(
                            CONF_SUBNET, self._default_subnet()
                        )
                    },
                ): TextSelector(TextSelectorConfig()),
                vol.Optional(
                    CONF_MIN_POWER,
                    description={
                        "suggested_value": user_input.get(
                            CONF_MIN_POWER, DEFAULT_MIN_POWER
                        )
                    },
                ): _POWER_SELECTOR,
                vol.Optional(
                    CONF_MAX_POWER,
                    description={
                        "suggested_value": user_input.get(
                            CONF_MAX_POWER, DEFAULT_MAX_POWER
                        )
                    },
                ): _POWER_SELECTOR,
            }
        )

    def _manual_schema(self, user_input: dict[str, Any] | None = None) -> vol.Schema:
        """Return manual input schema."""
        user_input = user_input or {}
        ip_default = str(user_input.get(CONF_IP, "") or "").strip()
        if not ip_default:
            ip_default = str(self._data.get(CONF_IP, "") or "").strip()

        return vol.Schema(
            {
                vol.Required(
                    CONF_IP,
                    description={"suggested_value": ip_default},
                ): TextSelector(TextSelectorConfig()),
                vol.Optional(
                    CONF_MIN_POWER,
                    description={
                        "suggested_value": user_input.get(
                            CONF_MIN_POWER, DEFAULT_MIN_POWER
                        )
                    },
                ): _POWER_SELECTOR,
                vol.Optional(
                    CONF_MAX_POWER,
                    description={
                        "suggested_value": user_input.get(
                            CONF_MAX_POWER, DEFAULT_MAX_POWER
                        )
                    },
                ): _POWER_SELECTOR,
            }
        )

    def _reconfigure_schema(self, entry_data: dict[str, Any]) -> vol.Schema:
        """Schema for reconfiguring an existing miner connection."""
        return vol.Schema(
            {
                vol.Required(
                    CONF_IP,
                    description={"suggested_value": entry_data.get(CONF_IP, "")},
                ): TextSelector(TextSelectorConfig()),
                vol.Optional(
                    CONF_MIN_POWER,
                    description={
                        "suggested_value": entry_data.get(
                            CONF_MIN_POWER, DEFAULT_MIN_POWER
                        )
                    },
                ): _POWER_SELECTOR,
                vol.Optional(
                    CONF_MAX_POWER,
                    description={
                        "suggested_value": entry_data.get(
                            CONF_MAX_POWER, DEFAULT_MAX_POWER
                        )
                    },
                ): _POWER_SELECTOR,
                vol.Optional(CONF_RPC_PASSWORD): TextSelector(
                    TextSelectorConfig(
                        type=TextSelectorType.PASSWORD,
                        autocomplete="new-password",
                    )
                ),
                vol.Optional(
                    CONF_WEB_USERNAME,
                    description={
                        "suggested_value": entry_data.get(CONF_WEB_USERNAME, "")
                    },
                ): TextSelector(TextSelectorConfig(autocomplete="username")),
                vol.Optional(CONF_WEB_PASSWORD): TextSelector(
                    TextSelectorConfig(
                        type=TextSelectorType.PASSWORD,
                        autocomplete="new-password",
                    )
                ),
                vol.Optional(
                    CONF_SSH_USERNAME,
                    description={
                        "suggested_value": entry_data.get(CONF_SSH_USERNAME, "")
                    },
                ): TextSelector(TextSelectorConfig(autocomplete="username")),
                vol.Optional(CONF_SSH_PASSWORD): TextSelector(
                    TextSelectorConfig(
                        type=TextSelectorType.PASSWORD,
                        autocomplete="new-password",
                    )
                ),
            }
        )

    @staticmethod
    def _merge_secret(value: Any, stored: str) -> str:
        if value is not None and str(value).strip():
            return str(value)
        return stored

    def _has_entry_with_host(self, host: str) -> bool:
        """Check if host is already configured."""
        return is_miner_already_configured(self.hass, ip=str(host).strip())

    @staticmethod
    def _dhcp_mac_hex12(dhcp_mac: str) -> str:
        return dhcp_mac.replace(":", "").replace("-", "").lower()

    def _mac_already_in_miner_integration(self, dhcp_mac: str) -> bool:
        """True if this MAC already belongs to a configured (non-farm) miner entry."""
        return is_miner_already_configured(self.hass, mac=dhcp_mac)

    async def _async_dhcp_probe_miner(self, host: str):
        """Try pyasic.get_miner a few times with backoff."""
        import pyasic

        miner = None
        for attempt in range(_DHCP_PROBE_ATTEMPTS):
            if attempt > 0:
                await asyncio.sleep(_DHCP_PROBE_BACKOFF_SEC[attempt - 1])
            try:
                miner = await asyncio.wait_for(
                    pyasic.get_miner(host),
                    timeout=_DHCP_PROBE_TIMEOUT_SEC,
                )
            except Exception:
                miner = None
            if miner is not None:
                return miner
        return None

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
            raise AbortFlow("already_configured")

    async def _async_prepare_miner(
        self, miner, host: str, base_data: dict[str, Any]
    ) -> None:
        """Store common flow data after miner was resolved."""
        await self._async_set_unique_or_match_existing(miner, host)
        self._miner = miner
        self._data.update(base_data)

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo):
        """Handle DHCP discovery (MAC/OUI match; API probe with limited retries)."""
        host = str(discovery_info.ip)
        ip_tail = host.split(".")[-1]
        mac = discovery_info.macaddress

        if self._has_entry_with_host(host):
            return self.async_abort(reason="already_configured")

        if self._mac_already_in_miner_integration(mac):
            return self.async_abort(reason="already_configured")

        miner = await self._async_dhcp_probe_miner(host)

        if miner is not None:
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
            except AbortFlow as err:
                return self.async_abort(reason=err.reason)

            return await self.async_step_login()

        # Hostname/MAC matched DHCP but pyasic could not identify the miner yet.
        # Still create a discoverable flow so the user can finish setup from Integrations.
        await self.async_set_unique_id(f"miner_dhcp_{discovery_info.macaddress}")
        self._abort_if_unique_id_configured(
            updates={CONF_IP: host, CONF_HOST: host}
        )
        hn = (discovery_info.hostname or "").strip() or f"Miner .{ip_tail}"
        self.context["title_placeholders"] = {"name": hn}
        self._data = {
            CONF_IP: host,
            CONF_MIN_POWER: DEFAULT_MIN_POWER,
            CONF_MAX_POWER: DEFAULT_MAX_POWER,
        }
        _LOGGER.debug(
            "DHCP discovery for %s: API probe failed or timed out, opening manual step",
            host,
        )
        return await self.async_step_manual(user_input=None)

    async def async_step_user(self, user_input=None):
        """Show entry mode menu."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["scan", "manual", "farm"],
            sort=False,
        )

    def _farm_schema(self, user_input: dict[str, Any] | None = None) -> vol.Schema:
        user_input = user_input or {}
        return vol.Schema(
            {
                vol.Required(
                    CONF_TITLE,
                    description={"suggested_value": user_input.get(CONF_TITLE, "")},
                ): TextSelector(TextSelectorConfig()),
                vol.Required(
                    CONF_FARM_DEVICE_IDS,
                    description={
                        "suggested_value": user_input.get(CONF_FARM_DEVICE_IDS)
                    },
                ): DeviceSelector(
                    DeviceSelectorConfig(integration=DOMAIN, multiple=True),
                ),
            }
        )

    async def async_step_farm(self, user_input=None):
        """Add a farm device aggregating existing miner devices."""
        errors: dict[str, str] = {}

        if user_input is None:
            return self.async_show_form(
                step_id="farm",
                data_schema=self._farm_schema(),
            )

        title = str(user_input.get(CONF_TITLE, "")).strip()
        devices = user_input.get(CONF_FARM_DEVICE_IDS)
        if isinstance(devices, str):
            devices = [devices]

        if not title:
            errors["base"] = "farm_no_title"
        if not devices:
            errors["base"] = "farm_no_devices"

        if not errors:
            dev_reg = dr.async_get(self.hass)
            for did in devices:
                dev = dev_reg.async_get(did)
                if dev is None:
                    errors["base"] = "farm_invalid_device"
                    break
                ce = async_get_miner_config_entry_for_device(self.hass, dev)
                if ce is None:
                    errors["base"] = "farm_only_miner_devices"
                    break

        if not errors:
            from .farm_validation import validate_farm_device_algorithms

            algo_error = validate_farm_device_algorithms(self.hass, devices)
            if algo_error:
                errors["base"] = algo_error

        if errors:
            return self.async_show_form(
                step_id="farm",
                data_schema=self._farm_schema(user_input),
                errors=errors,
            )

        key = ",".join(sorted(devices))
        uid_digest = hashlib.sha256(key.encode()).hexdigest()[:20]
        await self.async_set_unique_id(f"farm_{uid_digest}")
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=title,
            data={
                CONF_IS_FARM: True,
                CONF_TITLE: title,
                CONF_FARM_DEVICE_IDS: devices,
            },
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

        if self._has_entry_with_host(host):
            return self.async_show_form(
                step_id="manual",
                data_schema=schema,
                errors={"base": "already_configured"},
            )

        try:
            await self._async_prepare_miner(miner, host, user_input)
        except AbortFlow as err:
            return self.async_abort(reason=err.reason)

        return await self.async_step_login()

    async def _async_run_scan(self, subnet: str) -> list[DiscoveredMiner]:
        """Background subnet scan; omit miners already in Home Assistant."""

        def _progress(value: float) -> None:
            self.async_update_progress(value)

        found = await async_scan_subnet(subnet, progress_callback=_progress)
        self._scan_had_unfiltered = bool(found)
        return filter_unconfigured_miners(self.hass, found)

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
            scan_error = (
                "all_miners_configured"
                if self._scan_had_unfiltered
                else "no_devices_found"
            )
            return self.async_show_form(
                step_id="scan",
                data_schema=self._scan_schema(self._scan_input),
                errors={"base": scan_error},
            )

        options = [
            {
                "value": item.ip,
                "label": (
                    f"{item.model} — {item.ip}"
                    + (f" — {item.hostname}" if item.hostname else "")
                ),
            }
            for item in self._scan_results
        ]
        default_ip = (
            user_input.get(CONF_SELECTED_MINER)
            if user_input
            else self._scan_results[0].ip
        )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SELECTED_MINER,
                    description={"suggested_value": default_ip},
                ): SelectSelector(SelectSelectorConfig(options=options)),
            }
        )

        if not user_input:
            return self.async_show_form(step_id="pick_miner", data_schema=schema)

        selected_ip = str(user_input[CONF_SELECTED_MINER]).strip()

        if self._has_entry_with_host(selected_ip):
            return self.async_show_form(
                step_id="pick_miner",
                data_schema=schema,
                errors={"base": "already_configured"},
            )

        import pyasic

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
        except AbortFlow as err:
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

        api = getattr(self._miner, "api", None) or getattr(self._miner, "rpc", None)
        if api is not None and getattr(api, "pwd", None) is not None:
            schema_data[
                vol.Optional(
                    CONF_RPC_PASSWORD,
                    default=user_input.get(
                        CONF_RPC_PASSWORD,
                        api.pwd or "",
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
                    description={
                        "suggested_value": user_input.get(
                            CONF_WEB_USERNAME,
                            self._miner.web.username,
                        )
                    },
                )
            ] = TextSelector(TextSelectorConfig(autocomplete="username"))
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
                    description={
                        "suggested_value": user_input.get(
                            CONF_SSH_USERNAME,
                            self._miner.ssh.username,
                        )
                    },
                )
            ] = TextSelector(TextSelectorConfig(autocomplete="username"))
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
        api = getattr(self._miner, "api", None) or getattr(self._miner, "rpc", None)
        if api is not None and getattr(api, "pwd", None) is not None:
            api.pwd = self._data.get(CONF_RPC_PASSWORD, "")

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
                    description={"suggested_value": user_input.get(CONF_TITLE, title)},
                ): TextSelector(TextSelectorConfig()),
            }
        )

        if not user_input:
            return self.async_show_form(step_id="title", data_schema=data_schema)

        self._data.update(user_input)
        return self.async_create_entry(
            title=self._data[CONF_TITLE],
            data=self._data,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Reconfigure miner connection settings (IP, credentials, power range)."""
        reconfigure_entry = self._get_reconfigure_entry()
        if reconfigure_entry.data.get(CONF_IS_FARM):
            return self.async_abort(reason="reconfigure_not_supported")

        entry_data = dict(reconfigure_entry.data)
        if user_input is None:
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=self._reconfigure_schema(entry_data),
                description_placeholders={"name": reconfigure_entry.title},
            )

        errors: dict[str, str] = {}
        host = str(user_input.get(CONF_IP, "")).strip()
        if not host:
            errors["base"] = "cannot_connect"
        elif host != str(entry_data.get(CONF_IP, "")).strip():
            if self._has_entry_with_host(host):
                errors["base"] = "already_configured"
            else:
                errors, _miner = await validate_ip_input(user_input)
        else:
            errors, _miner = await validate_ip_input(user_input)

        if errors:
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=self._reconfigure_schema({**entry_data, **user_input}),
                errors=errors,
                description_placeholders={"name": reconfigure_entry.title},
            )

        new_data = {
            CONF_IP: host,
            CONF_HOST: host,
            CONF_MIN_POWER: int(
                user_input.get(CONF_MIN_POWER, entry_data.get(CONF_MIN_POWER, DEFAULT_MIN_POWER))
            ),
            CONF_MAX_POWER: int(
                user_input.get(CONF_MAX_POWER, entry_data.get(CONF_MAX_POWER, DEFAULT_MAX_POWER))
            ),
            CONF_RPC_PASSWORD: self._merge_secret(
                user_input.get(CONF_RPC_PASSWORD),
                str(entry_data.get(CONF_RPC_PASSWORD) or ""),
            ),
            CONF_WEB_USERNAME: str(
                user_input.get(CONF_WEB_USERNAME, entry_data.get(CONF_WEB_USERNAME, ""))
            ),
            CONF_WEB_PASSWORD: self._merge_secret(
                user_input.get(CONF_WEB_PASSWORD),
                str(entry_data.get(CONF_WEB_PASSWORD) or ""),
            ),
            CONF_SSH_USERNAME: str(
                user_input.get(CONF_SSH_USERNAME, entry_data.get(CONF_SSH_USERNAME, ""))
            ),
            CONF_SSH_PASSWORD: self._merge_secret(
                user_input.get(CONF_SSH_PASSWORD),
                str(entry_data.get(CONF_SSH_PASSWORD) or ""),
            ),
        }
        return self.async_update_reload_and_abort(
            reconfigure_entry,
            data_updates=new_data,
        )

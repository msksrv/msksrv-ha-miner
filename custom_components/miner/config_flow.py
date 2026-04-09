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
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.core import callback
from homeassistant.core import split_entity_id
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import BooleanSelector
from homeassistant.helpers.selector import DeviceSelector, DeviceSelectorConfig
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig
from homeassistant.helpers.selector import NumberSelector, NumberSelectorConfig
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from .const import (
    CONF_FARM_AMBIENT_TEMP_ENTITIES,
    CONF_FARM_DEVICE_IDS,
    CONF_FARM_POOL_PRESETS,
    CONF_IP,
    CONF_IS_FARM,
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
from .device_resolution import async_get_miner_config_entry_for_device
from .farm_pool_presets import FARM_POOL_SLOT_COUNT
from .farm_pool_presets import farm_pool_preset_slots
from .farm_pool_presets import farm_pool_slots_from_user_input
from .farm_pool_presets import strip_legacy_farm_pool_keys
from .discovery import (
    DiscoveredMiner,
    async_scan_subnet,
    get_stable_identifier,
    normalize_model_name,
)

_LOGGER = logging.getLogger(__name__)

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
        ip_default = str(user_input.get(CONF_IP, "") or "").strip()
        if not ip_default:
            ip_default = str(self._data.get(CONF_IP, "") or "").strip()

        return vol.Schema(
            {
                vol.Required(CONF_IP, default=ip_default): str,
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

    @staticmethod
    def _dhcp_mac_hex12(dhcp_mac: str) -> str:
        return dhcp_mac.replace(":", "").replace("-", "").lower()

    def _mac_already_in_miner_integration(self, dhcp_mac: str) -> bool:
        """True if this MAC already belongs to a configured (non-farm) miner entry."""
        raw = self._dhcp_mac_hex12(dhcp_mac)
        if len(raw) != 12:
            return False

        dev_reg = dr.async_get(self.hass)
        formatted = format_mac(raw)
        if device := dev_reg.async_get_device(
            connections={(CONNECTION_NETWORK_MAC, formatted)}
        ):
            for eid in device.config_entries:
                entry = self.hass.config_entries.async_get_entry(eid)
                if (
                    entry
                    and entry.domain == DOMAIN
                    and not entry.data.get(CONF_IS_FARM)
                ):
                    return True

        for entry in self._async_current_entries():
            if entry.domain != DOMAIN or entry.data.get(CONF_IS_FARM):
                continue
            uid = (entry.unique_id or "").lower().replace(":", "").replace("-", "")
            if uid == raw:
                return True
        return False

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
                    CONF_TITLE, default=user_input.get(CONF_TITLE, "")
                ): str,
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

        try:
            await self._async_prepare_miner(miner, host, user_input)
        except AbortFlow as err:
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
    """Options for a Miner config entry (power switch, stratum pool)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ):
        """Manage miner options."""
        if self.config_entry.data.get(CONF_IS_FARM):
            return await self.async_step_farm_options(user_input)

        if user_input is not None:
            errors: dict[str, str] = {}
            entity_id = user_input.get(CONF_POWER_SWITCH)
            if entity_id:
                try:
                    ent_domain, _ = split_entity_id(entity_id)
                except ValueError:
                    ent_domain = ""
                registry = er.async_get(self.hass)
                entity = registry.async_get(entity_id)
                if entity is None or ent_domain != "switch":
                    errors["base"] = "invalid_switch"

            pool_action = str(user_input.get("pool_action", "none"))
            if pool_action not in ("none", "replace_primary", "append_backup"):
                pool_action = "none"

            host = (user_input.get("pool_host") or "").strip()
            port_raw = user_input.get("pool_port")
            port_int: int | None = None

            if pool_action != "none":
                if not host or port_raw is None or port_raw == "":
                    errors["pool_host"] = "pool_fields_required"
                else:
                    try:
                        port_int = int(port_raw)
                        if port_int < 1 or port_int > 65535:
                            raise ValueError
                    except (TypeError, ValueError):
                        errors["pool_port"] = "invalid_pool_port"

            if errors:
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._options_schema(user_input),
                    errors=errors,
                )

            new_options = {**self.config_entry.options}
            if entity_id:
                new_options[CONF_POWER_SWITCH] = entity_id
            else:
                new_options.pop(CONF_POWER_SWITCH, None)
            entry_id = self.config_entry.entry_id
            coordinator = self.hass.data.get(DOMAIN, {}).get(entry_id)
            if pool_action != "none" and port_int is not None:
                if coordinator is None:
                    return self.async_show_form(
                        step_id="init",
                        data_schema=self._options_schema(user_input),
                        errors={"base": "miner_not_loaded"},
                    )
                miner = await coordinator.get_miner()
                if miner is None:
                    return self.async_show_form(
                        step_id="init",
                        data_schema=self._options_schema(user_input),
                        errors={"base": "miner_offline"},
                    )
                use_ssl = bool(user_input.get("pool_use_ssl"))
                uname = str(user_input.get("pool_username") or "")
                pwd = str(user_input.get("pool_password") or "")
                try:
                    from . import pool_stratum

                    if pool_action == "replace_primary":
                        ok = await pool_stratum.async_apply_primary_stratum(
                            miner,
                            host,
                            port_int,
                            use_ssl,
                            uname,
                            pwd,
                            force_user_password=True,
                        )
                    else:
                        ok = await pool_stratum.async_append_stratum_pool(
                            miner,
                            host,
                            port_int,
                            use_ssl,
                            uname,
                            pwd,
                        )
                    if not ok:
                        return self.async_show_form(
                            step_id="init",
                            data_schema=self._options_schema(user_input),
                            errors={"base": "pool_apply_failed"},
                        )
                    await coordinator.async_request_refresh()
                except Exception:
                    _LOGGER.exception("Applying pool from options")
                    return self.async_show_form(
                        step_id="init",
                        data_schema=self._options_schema(user_input),
                        errors={"base": "pool_apply_failed"},
                    )

            return self.async_create_entry(title="", data=new_options)

        return self.async_show_form(
            step_id="init",
            data_schema=self._options_schema(),
        )

    async def async_step_farm_options(
        self, user_input: dict[str, Any] | None = None
    ):
        """Farm members, room sensors, and optional stratum apply to all members."""
        errors: dict[str, str] = {}

        if user_input is not None:
            devices = user_input.get(CONF_FARM_DEVICE_IDS)
            if isinstance(devices, str):
                devices = [devices]
            if not devices:
                errors["base"] = "farm_no_devices"
            else:
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

            ents = user_input.get(CONF_FARM_AMBIENT_TEMP_ENTITIES)
            if ents is None:
                ents = []
            if isinstance(ents, str):
                ents = [ents]
            registry = er.async_get(self.hass)
            for eid in ents:
                try:
                    ent_domain, _ = split_entity_id(eid)
                except ValueError:
                    errors["base"] = "invalid_temp_entity"
                    break
                if ent_domain != "sensor":
                    errors["base"] = "invalid_temp_entity"
                    break
                if registry.async_get(eid) is None:
                    errors["base"] = "invalid_temp_entity"
                    break

            opts = self.config_entry.options
            prev_slots = farm_pool_preset_slots(opts)
            new_slots = farm_pool_slots_from_user_input(user_input, prev_slots)

            for i in range(FARM_POOL_SLOT_COUNT):
                h = (user_input.get(f"pool_slot_{i}_host") or "").strip()
                pr = user_input.get(f"pool_slot_{i}_port")
                has_port = pr is not None and str(pr).strip() != ""
                if h and not has_port:
                    errors[f"pool_slot_{i}_port"] = "pool_fields_required"
                elif has_port and not h:
                    errors[f"pool_slot_{i}_host"] = "pool_fields_required"
                elif h and has_port:
                    try:
                        pi = int(pr)
                        if pi < 1 or pi > 65535:
                            raise ValueError
                    except (TypeError, ValueError):
                        errors[f"pool_slot_{i}_port"] = "invalid_pool_port"

            pool_action = str(user_input.get("pool_action", "none"))
            if pool_action not in ("none", "replace_primary", "append_backup"):
                pool_action = "none"

            apply_slot_raw = str(user_input.get("pool_apply_slot", "1"))
            try:
                apply_slot_i = int(apply_slot_raw) - 1
            except (TypeError, ValueError):
                apply_slot_i = 0

            preset_for_apply: dict[str, Any] | None = None
            pool_port_int: int | None = None
            if pool_action != "none":
                if apply_slot_i < 0 or apply_slot_i >= FARM_POOL_SLOT_COUNT:
                    errors["pool_apply_slot"] = "farm_pool_apply_slot_invalid"
                else:
                    cand = new_slots[apply_slot_i]
                    if not cand.get("host"):
                        errors["pool_apply_slot"] = "farm_pool_apply_slot_invalid"
                    else:
                        preset_for_apply = cand
                        pool_port_int = int(cand["port"])

            farm_coord = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)

            if (
                pool_action != "none"
                and not errors
                and devices
                and farm_coord is not None
                and hasattr(farm_coord, "farm_stratum_allowed_for_device_ids")
                and not farm_coord.farm_stratum_allowed_for_device_ids(devices)
            ):
                errors["base"] = "farm_pool_mixed_algorithms"

            new_unique_id = self.config_entry.unique_id
            if not errors and devices:
                key = ",".join(sorted(devices))
                uid_digest = hashlib.sha256(key.encode()).hexdigest()[:20]
                new_unique_id = f"farm_{uid_digest}"
                if new_unique_id != self.config_entry.unique_id:
                    for ent in self.hass.config_entries.async_entries(DOMAIN):
                        if ent.entry_id == self.config_entry.entry_id:
                            continue
                        if ent.unique_id == new_unique_id:
                            errors["base"] = "farm_device_set_conflict"
                            break

            if not errors:
                if (
                    pool_action != "none"
                    and preset_for_apply is not None
                    and pool_port_int is not None
                    and devices
                ):
                    if farm_coord is None or not hasattr(
                        farm_coord, "async_apply_stratum_to_members"
                    ):
                        errors["base"] = "farm_not_loaded"
                    else:
                        use_ssl = bool(preset_for_apply.get("use_ssl", False))
                        uname_eff = str(preset_for_apply.get("username") or "")
                        pwd_eff = str(preset_for_apply.get("password") or "")
                        try:
                            ok, err_key = await farm_coord.async_apply_stratum_to_members(
                                device_ids=devices,
                                replace_primary=pool_action == "replace_primary",
                                host=str(preset_for_apply["host"]),
                                port=pool_port_int,
                                use_ssl=use_ssl,
                                username=uname_eff,
                                password=pwd_eff,
                            )
                            if not ok:
                                errors["base"] = err_key or "farm_pool_apply_failed"
                        except Exception:
                            _LOGGER.exception("Farm stratum from options")
                            errors["base"] = "farm_pool_apply_failed"

            if not errors:
                new_options = {**self.config_entry.options}
                new_options[CONF_FARM_AMBIENT_TEMP_ENTITIES] = list(ents)
                new_options[CONF_FARM_POOL_PRESETS] = new_slots
                strip_legacy_farm_pool_keys(new_options)

                new_data = {**self.config_entry.data, CONF_FARM_DEVICE_IDS: devices}
                update_kw: dict[str, Any] = {
                    "data": new_data,
                    "options": new_options,
                }
                if new_unique_id != self.config_entry.unique_id:
                    update_kw["unique_id"] = new_unique_id
                self.hass.config_entries.async_update_entry(
                    self.config_entry, **update_kw
                )
                return self.async_create_entry(title="", data=new_options)

        return self.async_show_form(
            step_id="farm_options",
            data_schema=self._farm_options_schema(user_input),
            errors=errors,
        )

    def _farm_pool_slots_vol(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[Any, Any]:
        user_input = user_input or {}
        slots = farm_pool_preset_slots(self.config_entry.options)
        out: dict[Any, Any] = {}
        for i in range(FARM_POOL_SLOT_COUNT):
            s = slots[i] if i < len(slots) else {}
            host_s = user_input.get(f"pool_slot_{i}_host", s.get("host", ""))
            port_s = user_input.get(f"pool_slot_{i}_port", s.get("port"))
            if f"pool_slot_{i}_use_ssl" in user_input:
                ssl_def = bool(user_input.get(f"pool_slot_{i}_use_ssl"))
            else:
                ssl_def = bool(s.get("use_ssl", False))
            user_s = user_input.get(f"pool_slot_{i}_username", s.get("username", ""))
            pass_s = user_input.get(f"pool_slot_{i}_password", s.get("password", ""))
            out[
                vol.Optional(
                    f"pool_slot_{i}_host",
                    description={"suggested_value": host_s},
                )
            ] = str
            out[
                vol.Optional(
                    f"pool_slot_{i}_port",
                    description={"suggested_value": port_s},
                )
            ] = NumberSelector(
                NumberSelectorConfig(
                    min=1,
                    max=65535,
                    mode="box",
                ),
            )
            out[
                vol.Optional(
                    f"pool_slot_{i}_use_ssl",
                    default=ssl_def,
                )
            ] = BooleanSelector()
            out[
                vol.Optional(
                    f"pool_slot_{i}_username",
                    description={"suggested_value": user_s},
                )
            ] = str
            out[
                vol.Optional(
                    f"pool_slot_{i}_password",
                    description={"suggested_value": pass_s},
                )
            ] = TextSelector(
                TextSelectorConfig(
                    type=TextSelectorType.PASSWORD,
                    autocomplete="new-password",
                ),
            )
        apply_opts = [str(n) for n in range(1, FARM_POOL_SLOT_COUNT + 1)]
        out[
            vol.Optional(
                "pool_action",
                description={"suggested_value": user_input.get("pool_action", "none")},
            )
        ] = SelectSelector(
            SelectSelectorConfig(
                options=["none", "replace_primary", "append_backup"],
            ),
        )
        out[
            vol.Optional(
                "pool_apply_slot",
                description={
                    "suggested_value": user_input.get("pool_apply_slot", "1"),
                },
            )
        ] = SelectSelector(SelectSelectorConfig(options=apply_opts))
        return out

    def _farm_options_schema(
        self, user_input: dict[str, Any] | None = None
    ) -> vol.Schema:
        user_input = user_input or {}
        stored_devices = self.config_entry.data.get(CONF_FARM_DEVICE_IDS) or []
        if isinstance(stored_devices, str):
            stored_devices = [stored_devices]
        suggested_devices = user_input.get(CONF_FARM_DEVICE_IDS, stored_devices)
        stored = self.config_entry.options.get(CONF_FARM_AMBIENT_TEMP_ENTITIES) or []
        if isinstance(stored, str):
            stored = [stored]
        suggested = user_input.get(CONF_FARM_AMBIENT_TEMP_ENTITIES, stored)
        fields: dict[Any, Any] = {
            vol.Required(
                CONF_FARM_DEVICE_IDS,
                description={"suggested_value": suggested_devices},
            ): DeviceSelector(
                DeviceSelectorConfig(integration=DOMAIN, multiple=True),
            ),
            vol.Optional(
                CONF_FARM_AMBIENT_TEMP_ENTITIES,
                description={"suggested_value": suggested},
            ): EntitySelector(EntitySelectorConfig(domain="sensor", multiple=True)),
        }
        fields.update(self._farm_pool_slots_vol(user_input))
        return vol.Schema(fields)

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

        pool_action_suggested = user_input.get("pool_action", "none")
        pool_host_suggested = user_input.get("pool_host", "")
        pool_port_suggested = user_input.get("pool_port")
        pool_user_suggested = user_input.get("pool_username", "")
        pool_pass_suggested = user_input.get("pool_password", "")

        return vol.Schema(
            {
                vol.Optional(CONF_POWER_SWITCH, **optional_kwargs): EntitySelector(
                    EntitySelectorConfig(domain="switch"),
                ),
                vol.Optional(
                    "pool_action",
                    description={"suggested_value": pool_action_suggested},
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=["none", "replace_primary", "append_backup"],
                    ),
                ),
                vol.Optional(
                    "pool_host",
                    description={"suggested_value": pool_host_suggested},
                ): str,
                vol.Optional(
                    "pool_port",
                    description={"suggested_value": pool_port_suggested},
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=65535,
                        mode="box",
                    ),
                ),
                vol.Optional(
                    "pool_use_ssl",
                    default=bool(user_input.get("pool_use_ssl", False)),
                ): BooleanSelector(),
                vol.Optional(
                    "pool_username",
                    description={"suggested_value": pool_user_suggested},
                ): str,
                vol.Optional(
                    "pool_password",
                    description={"suggested_value": pool_pass_suggested},
                ): TextSelector(
                    TextSelectorConfig(
                        type=TextSelectorType.PASSWORD,
                        autocomplete="new-password",
                    ),
                ),
            }
        )

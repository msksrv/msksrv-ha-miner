"""Miner DataUpdateCoordinator."""
import logging
from datetime import timedelta

import pyasic

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import CONF_IP
from .const import CONF_IS_FARM
from .const import CONF_MIN_POWER
from .const import CONF_MAX_POWER
from .const import CONF_RPC_PASSWORD
from .const import CONF_SSH_PASSWORD
from .const import CONF_SSH_USERNAME
from .const import CONF_WEB_PASSWORD
from .const import CONF_WEB_USERNAME
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_get_miner_from_config_entry(
    entry: ConfigEntry,
) -> pyasic.AnyMiner | None:
    """Open a pyasic connection using stored credentials (coordinator not required)."""
    if (
        entry.domain != DOMAIN
        or entry.data.get(CONF_IS_FARM)
        or not entry.data.get(CONF_IP)
    ):
        return None
    miner_ip = entry.data[CONF_IP]
    miner = await pyasic.get_miner(miner_ip)
    if miner is None:
        return None

    if miner.api is not None and miner.api.pwd is not None:
        miner.api.pwd = entry.data.get(CONF_RPC_PASSWORD, "")

    if miner.web is not None:
        miner.web.username = entry.data.get(CONF_WEB_USERNAME, "")
        miner.web.pwd = entry.data.get(CONF_WEB_PASSWORD, "")

    if miner.ssh is not None:
        miner.ssh.username = entry.data.get(CONF_SSH_USERNAME, "")
        miner.ssh.pwd = entry.data.get(CONF_SSH_PASSWORD, "")

    return miner

REQUEST_REFRESH_DEFAULT_COOLDOWN = 5


def _format_uptime(value) -> str | None:
    """Format uptime seconds to human readable string."""
    try:
        total_seconds = int(value)
    except (TypeError, ValueError):
        return None

    if total_seconds < 60:
        return f"{total_seconds}s"

    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds and not days:
        parts.append(f"{seconds}s")

    return " ".join(parts) if parts else "0s"


def _primary_pool_metrics(pools):
    """Prefer the pool marked active; otherwise the first slot (miner order)."""
    if not pools:
        return None
    for p in pools:
        try:
            if getattr(p, "active", None) is True:
                return p
        except Exception:
            pass
    return pools[0]


def _mining_profile_label(miner_data) -> str | None:
    """Short label for the active mining profile across pyasic ``mining_mode`` types.

    Covers the modes in ``pyasic.config.mining.MiningModeConfig`` as returned per vendor:

    - **Preset** (VNish, LuxOS, …): ``active_preset.name``
    - **Power tune** (WhatsMiner BTMiner, BOS+, …): ``power`` → ``NNN W``
    - **Hashrate tune**: ``hashrate`` (numeric or hashrate type) → ``X.X TH/s`` or ``str(...)``
    - **Manual** (VNish chains, Epic, …): ``global_freq`` / ``global_volt`` → ``Manual (…)``
    - **Normal / Low / High / Sleep** (Antminer, WM, Goldshell levels, …): ``mode`` → title text
    """
    cfg = getattr(miner_data, "config", None)
    if cfg is None:
        return None
    mm = getattr(cfg, "mining_mode", None)
    if mm is None:
        return None

    try:
        preset = mm.active_preset
        name = getattr(preset, "name", None)
        if name is not None and str(name).strip():
            return str(name).strip()
    except AttributeError:
        pass

    power = getattr(mm, "power", None)
    if power is not None:
        try:
            return f"{int(power)} W"
        except (TypeError, ValueError):
            pass

    hashrate = getattr(mm, "hashrate", None)
    if hashrate is not None:
        try:
            hr_f = float(hashrate)
            return f"{hr_f:.1f} TH/s"
        except (TypeError, ValueError):
            hr_s = str(hashrate).strip()
            if hr_s:
                return hr_s

    gf = getattr(mm, "global_freq", None)
    gv = getattr(mm, "global_volt", None)
    if gf is not None or gv is not None:
        try:
            parts: list[str] = []
            if gf is not None and float(gf) > 0:
                parts.append(f"{float(gf):.0f} MHz")
            if gv is not None and float(gv) > 0:
                parts.append(f"{float(gv):.0f} mV")
            if parts:
                return f"Manual ({', '.join(parts)})"
        except (TypeError, ValueError):
            pass
    if getattr(mm, "mode", None) == "manual":
        return "Manual"

    mode = getattr(mm, "mode", None)
    if mode is not None:
        s = str(mode).strip()
        if s:
            return s.replace("_", " ").title()

    return None


DEFAULT_DATA = {
    "hostname": None,
    "mac": None,
    "make": None,
    "model": None,
    "ip": None,
    "is_mining": False,
    "fw_ver": None,
    "uptime": None,
    "uptime_formatted": None,
    "boards_count": 0,
    "pool": None,
    "pool_host": None,
    "pool_port": None,
    "pool_worker": None,
    "accepted_shares": 0,
    "rejected_shares": 0,
    "reject_rate": 0,
    "algorithm": None,
    "miner_sensors": {
        "hashrate": 0,
        "ideal_hashrate": 0,
        "active_preset_name": None,
        "temperature": 0,
        "power_limit": 0,
        "miner_consumption": 0,
        "efficiency": 0.0,
    },
    "board_sensors": {},
    "fan_sensors": {},
    "config": {},
}


class MinerCoordinator(DataUpdateCoordinator):
    """Class to manage fetching update data from the Miner."""

    miner: pyasic.AnyMiner = None

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize MinerCoordinator object."""
        self.miner = None
        self._failure_count = 0
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            config_entry=entry,
            name=entry.title,
            update_interval=timedelta(seconds=10),
            request_refresh_debouncer=Debouncer(
                hass,
                _LOGGER,
                cooldown=REQUEST_REFRESH_DEFAULT_COOLDOWN,
                immediate=True,
            ),
        )

    @property
    def available(self):
        """Return if device is available or not."""
        return self.miner is not None

    async def get_miner(self):
        """Get a valid Miner instance."""
        miner_ip = self.config_entry.data[CONF_IP]
        miner = await pyasic.get_miner(miner_ip)
        if miner is None:
            return None

        self.miner = miner

        if self.miner.api is not None:
            if self.miner.api.pwd is not None:
                self.miner.api.pwd = self.config_entry.data.get(CONF_RPC_PASSWORD, "")

        if self.miner.web is not None:
            self.miner.web.username = self.config_entry.data.get(CONF_WEB_USERNAME, "")
            self.miner.web.pwd = self.config_entry.data.get(CONF_WEB_PASSWORD, "")

        if self.miner.ssh is not None:
            self.miner.ssh.username = self.config_entry.data.get(CONF_SSH_USERNAME, "")
            self.miner.ssh.pwd = self.config_entry.data.get(CONF_SSH_PASSWORD, "")

        return self.miner

    async def _async_update_data(self):
        """Fetch sensors from miners."""
        miner = await self.get_miner()

        if miner is None:
            self._failure_count += 1

            if self._failure_count == 1:
                _LOGGER.warning(
                    "Miner is offline – returning zeroed data (first failure)."
                )
                return {
                    **DEFAULT_DATA,
                    "power_limit_range": {
                        "min": self.config_entry.data.get(CONF_MIN_POWER, 15),
                        "max": self.config_entry.data.get(CONF_MAX_POWER, 10000),
                    },
                }

            raise UpdateFailed("Miner Offline (consecutive failure)")

        try:
            miner_data = await self.miner.get_data(
                include=[
                    pyasic.DataOptions.HOSTNAME,
                    pyasic.DataOptions.MAC,
                    pyasic.DataOptions.IS_MINING,
                    pyasic.DataOptions.FW_VERSION,
                    pyasic.DataOptions.HASHRATE,
                    pyasic.DataOptions.EXPECTED_HASHRATE,
                    pyasic.DataOptions.HASHBOARDS,
                    pyasic.DataOptions.WATTAGE,
                    pyasic.DataOptions.WATTAGE_LIMIT,
                    pyasic.DataOptions.FANS,
                    pyasic.DataOptions.CONFIG,
                    pyasic.DataOptions.POOLS,
                    pyasic.DataOptions.UPTIME,
                ]
            )
        except Exception as err:
            self._failure_count += 1

            if self._failure_count == 1:
                _LOGGER.warning(
                    f"Error fetching miner data: {err} – returning zeroed data (first failure)."
                )
                return {
                    **DEFAULT_DATA,
                    "power_limit_range": {
                        "min": self.config_entry.data.get(CONF_MIN_POWER, 15),
                        "max": self.config_entry.data.get(CONF_MAX_POWER, 10000),
                    },
                }

            _LOGGER.exception(err)
            raise UpdateFailed from err

        self._failure_count = 0

        try:
            hashrate = round(float(miner_data.hashrate), 2)
        except (TypeError, ValueError):
            hashrate = None

        try:
            expected_hashrate = round(float(miner_data.expected_hashrate), 2)
        except (TypeError, ValueError):
            expected_hashrate = None

        active_preset = _mining_profile_label(miner_data)

        try:
            uptime = miner_data.uptime
        except AttributeError:
            uptime = None

        uptime_formatted = _format_uptime(uptime)

        try:
            boards_count = len(miner_data.hashboards)
        except Exception:
            boards_count = 0

        pool = None
        pool_host = None
        pool_port = None
        pool_worker = None
        accepted = None
        rejected = None

        try:
            first_pool = _primary_pool_metrics(miner_data.pools)
            if first_pool is not None:
                pool = getattr(first_pool, "url", None)
                accepted = getattr(first_pool, "accepted", None)
                rejected = getattr(first_pool, "rejected", None)
                raw_user = getattr(first_pool, "user", None)
                if raw_user is not None:
                    pool_worker = str(raw_user).strip() or None

                if pool:
                    pool_no_proto = str(pool).replace("stratum+tcp://", "").replace(
                        "stratum+ssl://", ""
                    )
                    if ":" in pool_no_proto:
                        pool_host, pool_port = pool_no_proto.rsplit(":", 1)
                    else:
                        pool_host = pool_no_proto
                        pool_port = None
        except Exception:
            pass

        try:
            reject_rate = round((float(rejected) / float(accepted)) * 100, 2) if accepted else 0
        except Exception:
            reject_rate = 0

        try:
            algorithm = miner_data.algo
        except Exception:
            algorithm = None
        if algorithm is not None:
            algorithm = str(algorithm).strip() or None

        data = {
            "hostname": miner_data.hostname,
            "mac": miner_data.mac,
            "make": miner_data.make,
            "model": miner_data.model,
            "ip": self.miner.ip,
            "is_mining": miner_data.is_mining,
            "fw_ver": miner_data.fw_ver,
            "uptime": uptime,
            "uptime_formatted": uptime_formatted,
            "boards_count": boards_count,
            "algorithm": algorithm,
            "pool": pool,
            "pool_host": pool_host,
            "pool_port": pool_port,
            "pool_worker": pool_worker,
            "accepted_shares": accepted,
            "rejected_shares": rejected,
            "reject_rate": reject_rate,
            "miner_sensors": {
                "hashrate": hashrate,
                "ideal_hashrate": expected_hashrate,
                "active_preset_name": active_preset,
                "temperature": miner_data.temperature_avg,
                "power_limit": miner_data.wattage_limit,
                "miner_consumption": miner_data.wattage,
                "efficiency": miner_data.efficiency_fract,
            },
            "board_sensors": {
                board.slot: {
                    "board_temperature": board.temp,
                    "chip_temperature": board.chip_temp,
                    "board_hashrate": round(float(board.hashrate or 0), 2),
                    "board_chips": board.chips,
                    "board_expected_chips": board.expected_chips,
                    "board_effective_chips": (
                        min(board.chips, board.expected_chips)
                        if board.chips is not None and board.expected_chips is not None
                        else board.chips
                    ),
                    "board_effective_chips_percent": (
                        round((board.chips / board.expected_chips) * 100, 2)
                        if board.chips is not None
                        and board.expected_chips is not None
                        and board.expected_chips > 0
                        else None
                    ),
                }
                for board in miner_data.hashboards
            },
            "fan_sensors": {
                idx: {"fan_speed": fan.speed} for idx, fan in enumerate(miner_data.fans)
            },
            "config": miner_data.config,
            "power_limit_range": {
                "min": self.config_entry.data.get(CONF_MIN_POWER, 15),
                "max": self.config_entry.data.get(CONF_MAX_POWER, 10000),
            },
        }
        return data

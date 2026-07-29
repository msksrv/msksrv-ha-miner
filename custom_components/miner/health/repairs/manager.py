"""Create, update, and clear Home Assistant repair issues for miners."""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from ...const import CONF_IP, CONF_POWER_SWITCH, DOMAIN
from ..baseline.detector import AnomalyFinding, AnomalyState
from .definitions import (
    BOARD_ANOMALY_REASONS,
    FAN_ANOMALY_REASONS,
    HASHRATE_ANOMALY_REASONS,
    LEARN_MORE_URL,
    ALL_MINER_REPAIR_TYPES,
    MINER_REPAIR_TYPES,
    POOL_ANOMALY_REASONS,
    RECOVERY_ANOMALY_REASONS,
    REJECT_ANOMALY_REASONS,
    REPAIR_DEFINITIONS,
    RepairType,
    miner_issue_id,
)
from .lifecycle import RepairLifecycle, monotonic_now
from .membership import miner_belongs_to_farm
from .registry_sync import sync_open_from_registry
from .timing import resolve_confirm_seconds, resolve_recovery_seconds

if TYPE_CHECKING:
    from ...events.manager import MinerEventManager

_LOGGER = logging.getLogger(__name__)


class RepairManager:
    """Maps health/anomaly state to stable HA repair issues."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        events: MinerEventManager | None = None,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.entry_id = entry.entry_id
        self._events = events
        self._lifecycle = RepairLifecycle(
            recovery_seconds=resolve_recovery_seconds(entry)
        )
        self._open: set[str] = set()
        sync_open_from_registry(
            hass,
            entry.entry_id,
            ALL_MINER_REPAIR_TYPES,
            miner_issue_id,
            self._lifecycle,
            self._open,
        )
        if self._events is not None:
            self._events.async_sync_open_problems(self._open)

    @callback
    def process_update(
        self,
        data: dict[str, Any] | None,
        anomaly: AnomalyState,
        *,
        available: bool,
    ) -> None:
        """Evaluate miner repairs after each coordinator poll."""
        self._lifecycle.set_recovery_seconds(resolve_recovery_seconds(self.entry))
        now = monotonic_now()
        name = self._device_name(data) if data else (self.entry.title or "Miner")
        raw_active: dict[str, bool] = {}

        if not miner_belongs_to_farm(self.hass, self.entry_id):
            raw_active[RepairType.OFFLINE] = not available

        if available and data:
            raw_active.update(
                {
                    RepairType.HASHBOARD: self._hashboard_raw(data, anomaly),
                    RepairType.HASHRATE: self._hashrate_raw(data, anomaly),
                    RepairType.TEMPERATURE: self._temperature_raw(data),
                    RepairType.FAN: self._fan_raw(data, anomaly),
                    RepairType.POOL: self._pool_raw(data, anomaly),
                    RepairType.RECOVERY: self._recovery_raw(anomaly),
                    RepairType.REJECT: self._reject_raw(data, anomaly),
                    RepairType.POWER: self._power_raw(data),
                }
            )
        else:
            for rtype in MINER_REPAIR_TYPES:
                raw_active.setdefault(rtype, False)

        self._sync_open(raw_active, now, data or {}, anomaly, name)

    @callback
    def async_clear_all(self) -> None:
        """Remove all issues for this miner (config entry removal only)."""
        for rtype in ALL_MINER_REPAIR_TYPES:
            ir.async_delete_issue(
                self.hass, DOMAIN, miner_issue_id(self.entry_id, rtype)
            )
        self._open.clear()
        self._lifecycle.reset_all()

    def open_recovery_failed(
        self, data: dict[str, Any], record: Any
    ) -> None:
        """Open repair when automatic recovery attempts are exhausted."""
        rtype = RepairType.RECOVERY_FAILED
        if rtype in self._open:
            return
        name = self._device_name(data)
        ms = data.get("miner_sensors") or {}
        current = _fmt(_f(ms.get("hashrate")), "—")
        expected = _fmt(
            _f(getattr(record, "expected_hashrate", None))
            or _f(ms.get("ideal_hashrate")),
            "—",
        )
        placeholders = {
            "name": name,
            "current_hashrate": current,
            "expected_hashrate": expected,
        }
        self._create_or_update(rtype, "miner_recovery_failed", placeholders)
        self._open.add(rtype)
        if self._events is not None:
            from ..baseline.detector import AnomalyState

            empty = AnomalyState(
                score=0,
                confidence=0,
                detected=False,
                severity=None,
                reason=None,
                message=None,
            )
            self._events.async_emit_problem_detected(rtype, data, empty)

    def open_power_restore_failed(
        self, data: dict[str, Any], record: Any
    ) -> None:
        """Open repair when power-on could not be restored after power-off."""
        rtype = RepairType.POWER_RESTORE_FAILED
        if rtype in self._open:
            return
        name = self._device_name(data)
        switch = self.entry.options.get(CONF_POWER_SWITCH) or "—"
        placeholders = {
            "name": name,
            "power_switch": str(switch),
        }
        self._create_or_update(rtype, "miner_power_restore_failed", placeholders)
        self._open.add(rtype)
        if self._events is not None:
            from ..baseline.detector import AnomalyState

            empty = AnomalyState(
                score=0,
                confidence=0,
                detected=False,
                severity=None,
                reason=None,
                message=None,
            )
            self._events.async_emit_problem_detected(rtype, data or {}, empty)

    def clear_recovery_failed(self) -> None:
        """Close recovery-failed repair after manual reset."""
        rtype = RepairType.RECOVERY_FAILED
        if rtype not in self._open:
            return
        key = miner_issue_id(self.entry_id, rtype)
        ir.async_delete_issue(self.hass, DOMAIN, key)
        self._open.discard(rtype)
        if self._events is not None:
            self._events.async_emit_problem_cleared(rtype)

    def clear_power_restore_failed(self) -> None:
        rtype = RepairType.POWER_RESTORE_FAILED
        if rtype not in self._open:
            return
        key = miner_issue_id(self.entry_id, rtype)
        ir.async_delete_issue(self.hass, DOMAIN, key)
        self._open.discard(rtype)
        if self._events is not None:
            self._events.async_emit_problem_cleared(rtype)

    def dismiss_repair(self, repair_type: str) -> None:
        """User acknowledged via repair flow — reset timers and clear issue."""
        if repair_type not in ALL_MINER_REPAIR_TYPES:
            return
        key = miner_issue_id(self.entry_id, repair_type)
        self._lifecycle.reset_key(key)
        ir.async_delete_issue(self.hass, DOMAIN, key)
        self._open.discard(repair_type)
        if self._events is not None:
            self._events.async_emit_problem_acknowledged(repair_type)

    def _sync_open(
        self,
        raw_active: dict[str, bool],
        now: float,
        data: dict[str, Any],
        anomaly: AnomalyState,
        name: str,
    ) -> None:
        for rtype in MINER_REPAIR_TYPES:
            key = miner_issue_id(self.entry_id, rtype)
            raw = raw_active.get(rtype, False)
            confirm = self._confirm_seconds(rtype, data, anomaly)

            if rtype in self._open:
                if raw:
                    self._lifecycle.cancel_recovery(key)
                    t_key = self._translation_key(rtype, data, anomaly)
                    placeholders = self._placeholders(
                        rtype, data, anomaly, name, key, now
                    )
                    self._create_or_update(rtype, t_key, placeholders)
                elif self._lifecycle.should_clear(key, False, now):
                    ir.async_delete_issue(self.hass, DOMAIN, key)
                    self._open.discard(rtype)
                    self._lifecycle.reset_key(key)
                    if self._events is not None:
                        self._events.async_emit_problem_cleared(rtype)
            elif self._lifecycle.confirmed(key, raw, now, confirm):
                t_key = self._translation_key(rtype, data, anomaly)
                placeholders = self._placeholders(
                    rtype, data, anomaly, name, key, now
                )
                self._create_or_update(rtype, t_key, placeholders)
                self._open.add(rtype)
                if self._events is not None:
                    self._events.async_emit_problem_detected(rtype, data, anomaly)

    def _confirm_seconds(
        self, rtype: str, data: dict[str, Any], anomaly: AnomalyState
    ) -> float:
        if rtype == RepairType.FAN and self._fan_imbalance(anomaly):
            return 0
        if rtype == RepairType.REJECT and self._reject_anomaly_active(anomaly):
            return 0
        if rtype == RepairType.HASHRATE and self._hashrate_anomaly_active(anomaly):
            return 0
        return resolve_confirm_seconds(self.entry, rtype)

    def _create_or_update(
        self,
        rtype: str,
        translation_key: str,
        placeholders: dict[str, str],
    ) -> None:
        key = miner_issue_id(self.entry_id, rtype)
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            key,
            is_fixable=True,
            is_persistent=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=translation_key,
            translation_placeholders=placeholders,
            learn_more_url=LEARN_MORE_URL,
            data={
                "entry_id": self.entry_id,
                "scope": "miner",
                "repair_type": rtype,
            },
        )

    @staticmethod
    def _hashboard_raw(data: dict[str, Any], anomaly: AnomalyState) -> bool:
        if not data.get("is_mining"):
            return False
        flags = (data.get("health") or {}).get("flags") or {}
        if flags.get("board_problem"):
            return True
        if anomaly.detected and anomaly.confidence >= 20:
            if anomaly.reason in BOARD_ANOMALY_REASONS:
                return True
            return any(f.reason in BOARD_ANOMALY_REASONS for f in anomaly.findings)
        return False

    @staticmethod
    def _hashrate_raw(data: dict[str, Any], anomaly: AnomalyState) -> bool:
        if not data.get("is_mining"):
            return False
        flags = (data.get("health") or {}).get("flags") or {}
        if flags.get("hashrate_low"):
            return True
        return RepairManager._hashrate_anomaly_active(anomaly)

    @staticmethod
    def _hashrate_anomaly_active(anomaly: AnomalyState) -> bool:
        if not anomaly.detected or anomaly.confidence < 20:
            return False
        if anomaly.reason in HASHRATE_ANOMALY_REASONS:
            return True
        return any(f.reason in HASHRATE_ANOMALY_REASONS for f in anomaly.findings)

    @staticmethod
    def _power_raw(data: dict[str, Any]) -> bool:
        if not data.get("is_mining"):
            return False
        flags = (data.get("health") or {}).get("flags") or {}
        return bool(flags.get("power_anomaly"))

    @staticmethod
    def _temperature_raw(data: dict[str, Any]) -> bool:
        if not data.get("is_mining"):
            return False
        flags = (data.get("health") or {}).get("flags") or {}
        return bool(flags.get("temperature_high"))

    def _fan_raw(self, data: dict[str, Any], anomaly: AnomalyState) -> bool:
        if not data.get("is_mining"):
            return False
        return self._fan_zero_rpm(data) or self._fan_imbalance(anomaly)

    @staticmethod
    def _pool_raw(data: dict[str, Any], anomaly: AnomalyState) -> bool:
        if not data.get("is_mining"):
            return False
        flags = (data.get("health") or {}).get("flags") or {}
        if flags.get("pool_problem") or flags.get("share_stale"):
            return True
        if not anomaly.detected or anomaly.confidence < 20:
            return False
        if anomaly.reason in POOL_ANOMALY_REASONS:
            return True
        return any(f.reason in POOL_ANOMALY_REASONS for f in anomaly.findings)

    @staticmethod
    def _recovery_raw(anomaly: AnomalyState) -> bool:
        if not anomaly.detected or anomaly.confidence < 20:
            return False
        if anomaly.reason in RECOVERY_ANOMALY_REASONS:
            return True
        return any(f.reason in RECOVERY_ANOMALY_REASONS for f in anomaly.findings)

    @staticmethod
    def _reject_raw(data: dict[str, Any], anomaly: AnomalyState) -> bool:
        if not data.get("is_mining"):
            return False
        if RepairManager._reject_anomaly_active(anomaly):
            return True
        flags = (data.get("health") or {}).get("flags") or {}
        if not flags.get("reject_rate_high"):
            return False
        accepted = _f(data.get("accepted_shares")) or 0
        rejected = _f(data.get("rejected_shares")) or 0
        return (accepted + rejected) >= 100

    @staticmethod
    def _reject_anomaly_active(anomaly: AnomalyState) -> bool:
        if not anomaly.detected or anomaly.confidence < 20:
            return False
        if anomaly.reason in REJECT_ANOMALY_REASONS:
            return True
        return any(f.reason in REJECT_ANOMALY_REASONS for f in anomaly.findings)

    @staticmethod
    def _fan_zero_rpm(data: dict[str, Any]) -> bool:
        flags = (data.get("health") or {}).get("flags") or {}
        return bool(flags.get("fan_problem"))

    @staticmethod
    def _fan_imbalance(anomaly: AnomalyState) -> bool:
        if not anomaly.detected or anomaly.confidence < 20:
            return False
        if anomaly.reason in FAN_ANOMALY_REASONS:
            return True
        return any(f.reason in FAN_ANOMALY_REASONS for f in anomaly.findings)

    def _device_name(self, data: dict[str, Any] | None) -> str:
        if data:
            return (
                self.entry.title
                or data.get("hostname")
                or data.get("model")
                or "Miner"
            )
        return self.entry.title or "Miner"

    def _translation_key(
        self, rtype: str, data: dict[str, Any], anomaly: AnomalyState
    ) -> str:
        if rtype == RepairType.HASHBOARD:
            if _find_finding(anomaly, {"board_hashrate_outlier"}):
                return "miner_hashboard_hashrate"
            if _find_finding(anomaly, {"board_temp_outlier"}):
                return "miner_hashboard_temperature"
            return "miner_hashboard_chips"
        return REPAIR_DEFINITIONS[rtype].translation_key

    def _placeholders(
        self,
        rtype: str,
        data: dict[str, Any],
        anomaly: AnomalyState,
        name: str,
        lifecycle_key: str,
        now: float,
    ) -> dict[str, str]:
        if rtype == RepairType.HASHBOARD:
            return self._hashboard_placeholders(data, anomaly, name)
        if rtype == RepairType.HASHRATE:
            return self._hashrate_placeholders(data, anomaly, name, lifecycle_key, now)
        if rtype == RepairType.TEMPERATURE:
            return self._temperature_placeholders(data, name)
        if rtype == RepairType.OFFLINE:
            return self._offline_placeholders(data, name)
        if rtype == RepairType.POOL:
            return self._pool_placeholders(data, anomaly, name)
        if rtype == RepairType.RECOVERY:
            return self._recovery_placeholders(anomaly, name)
        if rtype == RepairType.REJECT:
            return self._reject_placeholders(data, anomaly, name)
        if rtype == RepairType.POWER:
            return self._power_placeholders(data, name)
        return self._fan_placeholders(data, anomaly, name)

    def _offline_placeholders(self, data: dict[str, Any], name: str) -> dict[str, str]:
        ip = "—"
        if data.get("ip"):
            ip = str(data["ip"])
        elif self.entry.data.get(CONF_IP):
            ip = str(self.entry.data[CONF_IP])
        return {"name": name, "ip": ip}

    def _pool_placeholders(
        self, data: dict[str, Any], anomaly: AnomalyState, name: str
    ) -> dict[str, str]:
        finding = _find_finding(anomaly, POOL_ANOMALY_REASONS)
        secs = _fmt(data.get("seconds_since_share"), "—", decimals=0)
        if finding:
            d = finding.details
            return {
                "name": name,
                "pool_host": str(data.get("pool_host") or "—"),
                "seconds_since_share": _fmt(
                    d.get("seconds_since_share"), secs, decimals=0
                ),
                "baseline_share_interval": _fmt(
                    d.get("baseline_share_interval"), "—", decimals=0
                ),
            }
        return {
            "name": name,
            "pool_host": str(data.get("pool_host") or "—"),
            "seconds_since_share": secs,
            "baseline_share_interval": "—",
        }

    def _recovery_placeholders(
        self, anomaly: AnomalyState, name: str
    ) -> dict[str, str]:
        finding = _find_finding(anomaly, RECOVERY_ANOMALY_REASONS)
        d = finding.details if finding else (anomaly.details or {})
        return {
            "name": name,
            "current_hashrate": _fmt(d.get("current_hashrate"), "—"),
            "baseline_hashrate": _fmt(d.get("baseline_hashrate"), "—"),
            "recovery_pct": _fmt(d.get("recovery_pct"), "—", decimals=0),
        }

    def _reject_placeholders(
        self, data: dict[str, Any], anomaly: AnomalyState, name: str
    ) -> dict[str, str]:
        finding = _find_finding(anomaly, REJECT_ANOMALY_REASONS)
        if finding:
            d = finding.details
            return {
                "name": name,
                "current_reject_rate": _fmt(d.get("current_reject_rate"), "—"),
                "baseline_reject_rate": _fmt(d.get("baseline_reject_rate"), "—"),
            }
        reject = _fmt(data.get("reject_rate"), "—")
        return {"name": name, "current_reject_rate": reject, "baseline_reject_rate": "—"}

    def _power_placeholders(self, data: dict[str, Any], name: str) -> dict[str, str]:
        ms = data.get("miner_sensors") or {}
        learned = (data.get("health") or {}).get("learned_baseline") or {}
        current = _fmt(ms.get("miner_consumption"), "—", decimals=0)
        baseline = _fmt(learned.get("power_w"), "—", decimals=0)
        mode = str(
            learned.get("mode")
            or ms.get("active_preset_name")
            or "—"
        )
        return {
            "name": name,
            "current_power": current,
            "baseline_power": baseline,
            "power_mode": mode,
        }

    def _hashboard_placeholders(
        self, data: dict[str, Any], anomaly: AnomalyState, name: str
    ) -> dict[str, str]:
        hr_finding = _find_finding(anomaly, {"board_hashrate_outlier"})
        if hr_finding:
            d = hr_finding.details
            return {
                "name": name,
                "board": str(d.get("board", "—")),
                "board_hashrate": _fmt(d.get("board_hashrate"), "—"),
                "median_board_hashrate": _fmt(d.get("median_board_hashrate"), "—"),
                "pct_below": _fmt(d.get("pct_below"), "—", decimals=0),
            }
        temp_finding = _find_finding(anomaly, {"board_temp_outlier"})
        if temp_finding:
            d = temp_finding.details
            return {
                "name": name,
                "board": str(d.get("board", "—")),
                "board_temperature": _fmt(d.get("board_temperature"), "—", decimals=0),
                "median_board_temperature": _fmt(
                    d.get("median_board_temperature"), "—", decimals=0
                ),
                "temp_delta": _fmt(d.get("temp_delta"), "—", decimals=0),
            }
        board, chips, expected = _worst_board_stats(data)
        return {
            "name": name,
            "board": board,
            "chips": chips,
            "expected_chips": expected,
        }

    def _hashrate_placeholders(
        self,
        data: dict[str, Any],
        anomaly: AnomalyState,
        name: str,
        lifecycle_key: str,
        now: float,
    ) -> dict[str, str]:
        ms = data.get("miner_sensors") or {}
        current = _fmt(_f(ms.get("hashrate")), "—")
        power = _fmt(_f(ms.get("miner_consumption")), "—", decimals=0)
        baseline = "—"
        finding = _find_finding(anomaly, HASHRATE_ANOMALY_REASONS)
        details = finding.details if finding else (anomaly.details or {})
        if details.get("baseline_hashrate") is not None:
            baseline = _fmt(details.get("baseline_hashrate"), baseline)
        if details.get("current_hashrate") is not None:
            current = _fmt(details.get("current_hashrate"), current)
        if details.get("current_power") is not None:
            power = _fmt(details.get("current_power"), power, decimals=0)
        return {
            "name": name,
            "current_hashrate": current,
            "baseline_hashrate": baseline,
            "power": power,
        }

    def _temperature_placeholders(
        self, data: dict[str, Any], name: str
    ) -> dict[str, str]:
        max_chip, max_board = _max_temps(data)
        return {
            "name": name,
            "chip_temperature": _fmt(max_chip, "—", decimals=0),
            "board_temperature": _fmt(max_board, "—", decimals=0),
        }

    def _fan_placeholders(
        self,
        data: dict[str, Any],
        anomaly: AnomalyState,
        name: str,
    ) -> dict[str, str]:
        finding = _find_finding(anomaly, FAN_ANOMALY_REASONS)
        if finding:
            d = finding.details
            return {
                "name": name,
                "fan": str(d.get("fan", "—")),
                "fan_speed": _fmt(d.get("fan_speed"), "—", decimals=0),
                "median_fan_speed": _fmt(d.get("median_fan_speed"), "—", decimals=0),
                "pct_below": _fmt(d.get("pct_below"), "—", decimals=0),
            }
        fan_idx, fan_speed = _slowest_fan(data)
        return {"name": name, "fan": fan_idx, "fan_speed": fan_speed}


def _find_finding(
    anomaly: AnomalyState | None, reasons: set[str] | frozenset[str]
) -> AnomalyFinding | None:
    if anomaly is None:
        return None
    if anomaly.reason in reasons:
        for finding in anomaly.findings:
            if finding.reason == anomaly.reason:
                return finding
        return AnomalyFinding(
            reason=anomaly.reason or "",
            severity=anomaly.severity or "warning",
            details=dict(anomaly.details or {}),
        )
    return next((f for f in anomaly.findings if f.reason in reasons), None)


def _worst_board_stats(data: dict[str, Any]) -> tuple[str, str, str]:
    boards = data.get("board_sensors") or {}
    worst_slot = "—"
    worst_chips = "—"
    worst_expected = "—"
    worst_pct = 101.0
    for slot, board in boards.items():
        if board.get("board_missing"):
            return str(slot), "0", str(board.get("board_expected_chips") or "—")
        pct = _f(board.get("board_effective_chips_percent"))
        chips = board.get("board_chips")
        expected = board.get("board_expected_chips")
        if pct is not None and pct < worst_pct:
            worst_pct = pct
            worst_slot = str(slot)
            worst_chips = str(chips if chips is not None else "—")
            worst_expected = str(expected if expected is not None else "—")
        elif expected and chips is not None:
            try:
                if int(expected) > 0 and int(chips) < int(expected) * 0.9:
                    ratio = int(chips) / int(expected) * 100
                    if ratio < worst_pct:
                        worst_pct = ratio
                        worst_slot = str(slot)
                        worst_chips = str(chips)
                        worst_expected = str(expected)
            except (TypeError, ValueError):
                pass
    return worst_slot, worst_chips, worst_expected


def _max_temps(data: dict[str, Any]) -> tuple[float | None, float | None]:
    max_chip: float | None = None
    max_board: float | None = None
    for board in (data.get("board_sensors") or {}).values():
        ct = _f(board.get("chip_temperature"))
        bt = _f(board.get("board_temperature"))
        if ct is not None:
            max_chip = ct if max_chip is None else max(max_chip, ct)
        if bt is not None:
            max_board = bt if max_board is None else max(max_board, bt)
    return max_chip, max_board


def _slowest_fan(data: dict[str, Any]) -> tuple[str, str]:
    fans = data.get("fan_sensors") or {}
    slow_idx = "—"
    slow_speed = "—"
    slow_val = None
    for idx, fan in fans.items():
        spd = _f(fan.get("fan_speed"))
        if spd is None:
            continue
        if slow_val is None or spd < slow_val:
            slow_val = spd
            slow_idx = str(idx)
            slow_speed = _fmt(spd, slow_speed, decimals=0)
    return slow_idx, slow_speed


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: Any, default: str, *, decimals: int = 1) -> str:
    f = _f(value)
    if f is None:
        return default
    if decimals == 0:
        return str(int(round(f)))
    return f"{f:.{decimals}f}"

"""Create, update, and clear Home Assistant repair issues for miners."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from ...const import DOMAIN
from ..baseline.detector import AnomalyFinding, AnomalyState
from .definitions import (
    BOARD_ANOMALY_REASONS,
    CONFIRM_FAN_IMBALANCE_SECONDS,
    FAN_ANOMALY_REASONS,
    HASHRATE_ANOMALY_REASONS,
    LEARN_MORE_URL,
    PHASE1_REPAIR_TYPES,
    REPAIR_DEFINITIONS,
    RepairType,
    issue_id,
)
from .lifecycle import RepairLifecycle, monotonic_now

_LOGGER = logging.getLogger(__name__)


class RepairManager:
    """Maps health/anomaly state to stable HA repair issues."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.entry_id = entry.entry_id
        self._lifecycle = RepairLifecycle()
        self._open: set[str] = set()

    @callback
    def process_update(
        self,
        data: dict[str, Any] | None,
        anomaly: AnomalyState,
        *,
        available: bool,
    ) -> None:
        """Evaluate phase-1 repairs after each coordinator poll."""
        if not available or not data:
            return

        now = monotonic_now()
        name = self._device_name(data)
        raw_active = {
            RepairType.HASHBOARD: self._hashboard_raw(data, anomaly),
            RepairType.HASHRATE: self._hashrate_raw(data, anomaly),
            RepairType.TEMPERATURE: self._temperature_raw(data),
            RepairType.FAN: self._fan_raw(data, anomaly),
        }
        self._sync_open(raw_active, now, data, anomaly, name)

    @callback
    def async_clear_all(self) -> None:
        """Remove all issues for this miner (config entry removal only)."""
        for rtype in PHASE1_REPAIR_TYPES:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id(self.entry_id, rtype))
        self._open.clear()
        self._lifecycle.reset_all()

    def dismiss_repair(self, repair_type: str) -> None:
        """User acknowledged via repair flow — reset timers and clear issue."""
        if repair_type not in PHASE1_REPAIR_TYPES:
            return
        key = issue_id(self.entry_id, repair_type)
        self._lifecycle.reset_key(key)
        ir.async_delete_issue(self.hass, DOMAIN, key)
        self._open.discard(repair_type)

    def _sync_open(
        self,
        raw_active: dict[str, bool],
        now: float,
        data: dict[str, Any],
        anomaly: AnomalyState,
        name: str,
    ) -> None:
        for rtype in PHASE1_REPAIR_TYPES:
            key = issue_id(self.entry_id, rtype)
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
            elif self._lifecycle.confirmed(key, raw, now, confirm):
                t_key = self._translation_key(rtype, data, anomaly)
                placeholders = self._placeholders(
                    rtype, data, anomaly, name, key, now
                )
                self._create_or_update(rtype, t_key, placeholders)
                self._open.add(rtype)

    def _confirm_seconds(
        self, rtype: str, data: dict[str, Any], anomaly: AnomalyState
    ) -> float:
        if rtype == RepairType.FAN and self._fan_imbalance(anomaly):
            return CONFIRM_FAN_IMBALANCE_SECONDS
        return REPAIR_DEFINITIONS[rtype].confirm_seconds

    def _create_or_update(
        self,
        rtype: str,
        translation_key: str,
        placeholders: dict[str, str],
    ) -> None:
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id(self.entry_id, rtype),
            is_fixable=True,
            is_persistent=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=translation_key,
            translation_placeholders=placeholders,
            learn_more_url=LEARN_MORE_URL,
            data={
                "entry_id": self.entry_id,
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
        if not anomaly.detected or anomaly.confidence < 20:
            return False
        if anomaly.reason in HASHRATE_ANOMALY_REASONS:
            return True
        return any(f.reason in HASHRATE_ANOMALY_REASONS for f in anomaly.findings)

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

    def _device_name(self, data: dict[str, Any]) -> str:
        return (
            self.entry.title
            or data.get("hostname")
            or data.get("model")
            or "Miner"
        )

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
        return self._fan_placeholders(data, anomaly, name)

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
        duration = self._lifecycle.active_duration_minutes(lifecycle_key, now) or "—"
        return {
            "name": name,
            "current_hashrate": current,
            "baseline_hashrate": baseline,
            "power": power,
            "duration": duration,
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
        return {
            "name": name,
            "fan": fan_idx,
            "fan_speed": fan_speed,
        }


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

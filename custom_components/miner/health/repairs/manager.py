"""Create, update, and clear Home Assistant repair issues for miners."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from ...const import DOMAIN
from ..baseline.detector import AnomalyState
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
        now = monotonic_now()
        if not available or not data:
            return

        desired: set[str] = set()
        name = self._device_name(data)

        if self._evaluate_hashboard(data, anomaly, now):
            desired.add(RepairType.HASHBOARD)
        if self._evaluate_hashrate(data, anomaly, now):
            desired.add(RepairType.HASHRATE)
        if self._evaluate_temperature(data, now):
            desired.add(RepairType.TEMPERATURE)
        if self._evaluate_fan(data, anomaly, now):
            desired.add(RepairType.FAN)

        self._sync_open(desired, data, anomaly, name)

    @callback
    def async_clear_all(self) -> None:
        """Remove all issues for this miner (unload / removal)."""
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
        desired: set[str],
        data: dict[str, Any] | None = None,
        anomaly: AnomalyState | None = None,
        name: str = "Miner",
    ) -> None:
        now = monotonic_now()
        for rtype in PHASE1_REPAIR_TYPES:
            key = issue_id(self.entry_id, rtype)
            want = rtype in desired
            if want:
                placeholders = self._placeholders(rtype, data or {}, anomaly, name)
                self._create_or_update(rtype, placeholders)
                self._open.add(rtype)
            elif rtype in self._open and self._lifecycle.should_clear(key, False, now):
                ir.async_delete_issue(self.hass, DOMAIN, key)
                self._open.discard(rtype)
                self._lifecycle.reset_key(key)

    def _create_or_update(
        self, rtype: str, placeholders: dict[str, str]
    ) -> None:
        definition = REPAIR_DEFINITIONS[rtype]
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id(self.entry_id, rtype),
            is_fixable=True,
            is_persistent=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=definition.translation_key,
            translation_placeholders=placeholders,
            learn_more_url=LEARN_MORE_URL,
            data={
                "entry_id": self.entry_id,
                "repair_type": rtype,
            },
        )

    def _evaluate_hashboard(
        self, data: dict[str, Any], anomaly: AnomalyState, now: float
    ) -> bool:
        if not data.get("is_mining"):
            return False
        condition = self._hashboard_condition(data, anomaly)
        key = issue_id(self.entry_id, RepairType.HASHBOARD)
        confirm = REPAIR_DEFINITIONS[RepairType.HASHBOARD].confirm_seconds
        return self._lifecycle.confirmed(key, condition, now, confirm)

    def _evaluate_hashrate(
        self, data: dict[str, Any], anomaly: AnomalyState, now: float
    ) -> bool:
        if not data.get("is_mining"):
            return False
        condition = self._hashrate_condition(data, anomaly)
        key = issue_id(self.entry_id, RepairType.HASHRATE)
        confirm = REPAIR_DEFINITIONS[RepairType.HASHRATE].confirm_seconds
        return self._lifecycle.confirmed(key, condition, now, confirm)

    def _evaluate_temperature(self, data: dict[str, Any], now: float) -> bool:
        if not data.get("is_mining"):
            return False
        flags = (data.get("health") or {}).get("flags") or {}
        condition = bool(flags.get("temperature_high"))
        key = issue_id(self.entry_id, RepairType.TEMPERATURE)
        confirm = REPAIR_DEFINITIONS[RepairType.TEMPERATURE].confirm_seconds
        return self._lifecycle.confirmed(key, condition, now, confirm)

    def _evaluate_fan(
        self, data: dict[str, Any], anomaly: AnomalyState, now: float
    ) -> bool:
        if not data.get("is_mining"):
            return False
        zero_rpm = self._fan_zero_rpm(data)
        imbalance = self._fan_imbalance(anomaly)
        key = issue_id(self.entry_id, RepairType.FAN)
        condition = zero_rpm or imbalance
        if not condition:
            return self._lifecycle.confirmed(key, False, now, 0)
        confirm = (
            REPAIR_DEFINITIONS[RepairType.FAN].confirm_seconds
            if zero_rpm
            else CONFIRM_FAN_IMBALANCE_SECONDS
        )
        return self._lifecycle.confirmed(key, True, now, confirm)

    @staticmethod
    def _hashboard_condition(data: dict[str, Any], anomaly: AnomalyState) -> bool:
        flags = (data.get("health") or {}).get("flags") or {}
        if flags.get("board_problem"):
            return True
        if anomaly.detected and anomaly.confidence >= 20:
            if anomaly.reason in BOARD_ANOMALY_REASONS:
                return True
            for finding in anomaly.findings:
                if finding.reason in BOARD_ANOMALY_REASONS:
                    return True
        return False

    @staticmethod
    def _hashrate_condition(data: dict[str, Any], anomaly: AnomalyState) -> bool:
        if not anomaly.detected or anomaly.confidence < 20:
            return False
        if anomaly.reason in HASHRATE_ANOMALY_REASONS:
            return True
        return any(f.reason in HASHRATE_ANOMALY_REASONS for f in anomaly.findings)

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

    def _placeholders(
        self,
        rtype: str,
        data: dict[str, Any],
        anomaly: AnomalyState | None,
        name: str,
    ) -> dict[str, str]:
        if rtype == RepairType.HASHBOARD:
            return self._hashboard_placeholders(data, name)
        if rtype == RepairType.HASHRATE:
            return self._hashrate_placeholders(data, anomaly, name)
        if rtype == RepairType.TEMPERATURE:
            return self._temperature_placeholders(data, name)
        return self._fan_placeholders(data, anomaly, name)

    def _hashboard_placeholders(
        self, data: dict[str, Any], name: str
    ) -> dict[str, str]:
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
        anomaly: AnomalyState | None,
        name: str,
    ) -> dict[str, str]:
        ms = data.get("miner_sensors") or {}
        current = _fmt(_f(ms.get("hashrate")), "—")
        power = _fmt(_f(ms.get("miner_consumption")), "—", decimals=0)
        baseline = "—"
        duration = "—"
        if anomaly and anomaly.details:
            baseline = _fmt(anomaly.details.get("baseline_hashrate"), baseline)
            if anomaly.details.get("current_hashrate") is not None:
                current = _fmt(anomaly.details.get("current_hashrate"), current)
            if anomaly.details.get("current_power") is not None:
                power = _fmt(anomaly.details.get("current_power"), power, decimals=0)
        if anomaly and anomaly.detected_at:
            duration = _format_duration_minutes(anomaly.detected_at)
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
        temp = max_chip if max_chip is not None else max_board
        return {
            "name": name,
            "temperature": _fmt(temp, "—", decimals=0),
        }

    def _fan_placeholders(
        self,
        data: dict[str, Any],
        anomaly: AnomalyState | None,
        name: str,
    ) -> dict[str, str]:
        fan_idx, fan_speed = _slowest_fan(data)
        if anomaly and anomaly.details.get("fan") is not None:
            fan_idx = str(anomaly.details.get("fan"))
        if anomaly and anomaly.details.get("fan_speed") is not None:
            fan_speed = _fmt(anomaly.details.get("fan_speed"), fan_speed, decimals=0)
        return {
            "name": name,
            "fan": fan_idx,
            "fan_speed": fan_speed,
        }


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


def _format_duration_minutes(detected_at: str) -> str:
    try:
        started = datetime.fromisoformat(detected_at.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - started.astimezone(timezone.utc)
        minutes = max(1, int(delta.total_seconds() // 60))
        return str(minutes)
    except (TypeError, ValueError):
        return "—"


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(
    value: Any, default: str, *, decimals: int = 1
) -> str:
    f = _f(value)
    if f is None:
        return default
    if decimals == 0:
        return str(int(round(f)))
    return f"{f:.{decimals}f}"

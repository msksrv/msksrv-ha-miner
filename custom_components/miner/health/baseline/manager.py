"""Self-learning baseline manager — per-mode statistics and persistence."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from ...const import DOMAIN
from .detector import AnomalyState, detect_anomalies
from .messages import format_anomaly_message
from .mode import baseline_mode_key
from .stats import RollingStats

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
MAX_SAMPLES = 360
WARMUP_SECONDS = 900
PRELIMINARY_SECONDS = 3600
RELIABLE_SECONDS = 43200
SAVE_INTERVAL_SECONDS = 600
LEARN_INTERVAL_SECONDS = 60
REBOOT_WARMUP_SECONDS = 900
RULE_REBOOT_WINDOW = 1800
MANUAL_SEED_SAMPLES = 30


class BaselineManager:
    """Learns normal operation per power/preset mode; runs anomaly rules."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self._store = Store(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.baseline.{entry_id}",
        )
        self._profiles: dict[str, dict[str, Any]] = {}
        self._current_mode: str | None = None
        self._mode_started_monotonic: float | None = None
        self._mining_started_monotonic: float | None = None
        self._reboot_warmup_until: float | None = None
        self._last_share_at_monotonic: float | None = None
        self._last_accepted_shares: float | None = None
        self._last_learn_monotonic = 0.0
        self._rule_timers: dict[str, float] = {}
        self._last_save_monotonic = 0.0
        self._dirty = False
        self._anomaly_detected_at: str | None = None
        self._anomaly_active_reason: str | None = None
        self._last_anomaly = AnomalyState(
            score=0,
            confidence=0,
            detected=False,
            severity=None,
            reason=None,
            message=None,
        )
        self._last_uptime: int | None = None

    @property
    def anomaly(self) -> AnomalyState:
        return self._last_anomaly

    @property
    def current_mode(self) -> str | None:
        return self._current_mode

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if not isinstance(data, dict):
            return
        self._profiles = data.get("profiles") or {}
        self._current_mode = data.get("current_mode")

    async def async_save(self, *, force: bool = False) -> None:
        if not self._dirty and not force:
            return
        await self._store.async_save(
            {
                "profiles": self._profiles,
                "current_mode": self._current_mode,
            }
        )
        self._dirty = False
        self._last_save_monotonic = time.monotonic()

    def notify_reboot(self) -> None:
        self._reboot_warmup_until = time.monotonic() + REBOOT_WARMUP_SECONDS
        self._rule_timers.clear()
        self._last_accepted_shares = None
        self._last_share_at_monotonic = None

    def reset_all(self) -> None:
        self._profiles.clear()
        self._rule_timers.clear()
        self._mining_started_monotonic = None
        self._mode_started_monotonic = None
        self._anomaly_detected_at = None
        self._anomaly_active_reason = None
        self._dirty = True

    def accept_current(self, data: dict[str, Any]) -> None:
        """Seed baseline with current readings (multiple samples for stability)."""
        mode = baseline_mode_key(data)
        profile = self._ensure_profile(mode)
        now_iso = _utc_now()
        for key, val in self._snapshot_values(data).items():
            if val is None:
                continue
            stats = _get_metric_stats(profile, key)
            for _ in range(MANUAL_SEED_SAMPLES):
                stats.add(float(val), timestamp=now_iso)
            _save_metric_stats(profile, key, stats)
        profile["manually_seeded"] = True
        profile["seeded_at"] = now_iso
        self._dirty = True

    @callback
    def process_update(self, data: dict[str, Any]) -> AnomalyState:
        now = time.monotonic()
        now_iso = _utc_now()
        lang = getattr(self.hass.config, "language", "en")

        uptime_i = _try_int(data.get("uptime"))
        if uptime_i is not None and self._last_uptime is not None and uptime_i + 60 < self._last_uptime:
            self.notify_reboot()
        if uptime_i is not None:
            self._last_uptime = uptime_i

        if not data.get("is_mining"):
            self._mining_started_monotonic = None
            self._clear_anomaly_tracking()
            self._last_anomaly = AnomalyState(
                score=0,
                confidence=self._last_anomaly.confidence,
                detected=False,
                severity=None,
                reason=None,
                message=None,
            )
            return self._last_anomaly

        if self._mining_started_monotonic is None:
            self._mining_started_monotonic = now

        mode = baseline_mode_key(data)
        if mode != self._current_mode:
            self._current_mode = mode
            self._mode_started_monotonic = now
            self._rule_timers.clear()
            self._dirty = True

        profile = self._ensure_profile(mode)
        learning = self._is_learning(now)
        confidence = self._confidence(now, profile)

        poll_data = {**data, "timestamp": now_iso}
        raw_anomaly = detect_anomalies(
            data=poll_data,
            baselines=self._baseline_values(profile),
            timers=self._rule_timers,
            now=now,
            confidence=confidence,
            learning=learning or self._in_reboot_warmup(now),
            reboot_watch=(not self._in_reboot_warmup(now)) and self._reboot_recently(now),
        )
        self._last_anomaly = self._finalize_anomaly(raw_anomaly, lang)

        if (
            not learning
            and not self._in_reboot_warmup(now)
            and self._can_learn(data, self._last_anomaly)
            and now - self._last_learn_monotonic >= LEARN_INTERVAL_SECONDS
        ):
            self._learn_sample(profile, data, now_iso, now)
            self._last_learn_monotonic = now

        if now - self._last_save_monotonic >= SAVE_INTERVAL_SECONDS:
            self.hass.async_create_task(self.async_save())
        return self._last_anomaly

    def _finalize_anomaly(self, state: AnomalyState, language: str) -> AnomalyState:
        if not state.detected:
            self._clear_anomaly_tracking()
            return state

        reason = state.reason or ""
        if reason != self._anomaly_active_reason:
            self._anomaly_active_reason = reason
            self._anomaly_detected_at = _utc_now()
        elif self._anomaly_detected_at is None:
            self._anomaly_detected_at = _utc_now()

        message = format_anomaly_message(reason, state.details, language)
        return AnomalyState(
            score=state.score,
            confidence=state.confidence,
            detected=True,
            severity=state.severity,
            reason=reason,
            message=message,
            findings=state.findings,
            details=state.details,
            detected_at=self._anomaly_detected_at,
        )

    def _clear_anomaly_tracking(self) -> None:
        self._anomaly_detected_at = None
        self._anomaly_active_reason = None

    def _ensure_profile(self, mode: str) -> dict[str, Any]:
        if mode not in self._profiles:
            self._profiles[mode] = {"metrics": {}, "created_at": _utc_now()}
            self._dirty = True
        return self._profiles[mode]

    def _learning_started(self) -> float | None:
        if self._mining_started_monotonic is None:
            return None
        starts = [self._mining_started_monotonic]
        if self._mode_started_monotonic is not None:
            starts.append(self._mode_started_monotonic)
        return max(starts)

    def _is_learning(self, now: float) -> bool:
        started = self._learning_started()
        if started is None:
            return True
        return (now - started) < WARMUP_SECONDS

    def _in_reboot_warmup(self, now: float) -> bool:
        return self._reboot_warmup_until is not None and now < self._reboot_warmup_until

    def _reboot_recently(self, now: float) -> bool:
        if self._reboot_warmup_until is None or now < self._reboot_warmup_until:
            return False
        return now < self._reboot_warmup_until + RULE_REBOOT_WINDOW

    def _confidence(self, now: float, profile: dict[str, Any]) -> int:
        started = self._learning_started()
        if started is None:
            return 0
        elapsed = now - started
        if elapsed < WARMUP_SECONDS:
            return 0
        metrics = profile.get("metrics") or {}
        hr = metrics.get("hashrate") or {}
        samples = min(len(hr.get("samples") or []), MAX_SAMPLES)
        sample_factor = min(samples / 60.0, 1.0)
        if elapsed < PRELIMINARY_SECONDS:
            span = PRELIMINARY_SECONDS - WARMUP_SECONDS
            time_factor = 0.3 + 0.4 * (elapsed - WARMUP_SECONDS) / span
        elif elapsed < RELIABLE_SECONDS:
            span = RELIABLE_SECONDS - PRELIMINARY_SECONDS
            time_factor = 0.7 + 0.25 * (elapsed - PRELIMINARY_SECONDS) / span
        else:
            time_factor = 1.0
        conf = min(100, round(sample_factor * time_factor * 100))
        if profile.get("manually_seeded") and samples >= 10:
            conf = max(conf, 50)
        return conf

    @staticmethod
    def _can_learn(data: dict[str, Any], anomaly: AnomalyState) -> bool:
        if anomaly.detected:
            return False
        if data.get("fault_light"):
            return False
        if data.get("errors"):
            return False
        flags = (data.get("health") or {}).get("flags") or {}
        if flags.get("temperature_high") or flags.get("maintenance_required"):
            return False
        return True

    def _learn_sample(
        self,
        profile: dict[str, Any],
        data: dict[str, Any],
        now_iso: str,
        now_m: float,
    ) -> None:
        for key, val in self._snapshot_values(data).items():
            if val is None:
                continue
            stats = _get_metric_stats(profile, key)
            if stats.is_outlier(float(val)):
                continue
            stats.add(float(val), timestamp=now_iso)
            _save_metric_stats(profile, key, stats)
            self._dirty = True

        accepted_f = _try_float(data.get("accepted_shares"))
        if accepted_f is not None:
            if (
                self._last_accepted_shares is not None
                and accepted_f < self._last_accepted_shares
            ):
                self._last_accepted_shares = accepted_f
                self._last_share_at_monotonic = now_m
            elif (
                self._last_accepted_shares is not None
                and accepted_f > self._last_accepted_shares
                and self._last_share_at_monotonic
            ):
                interval = now_m - self._last_share_at_monotonic
                if 5 <= interval <= 600:
                    stats = _get_metric_stats(profile, "share_interval")
                    if not stats.is_outlier(interval):
                        stats.add(interval, timestamp=now_iso)
                        _save_metric_stats(profile, "share_interval", stats)
                        self._dirty = True
            if (
                self._last_accepted_shares is None
                or accepted_f > self._last_accepted_shares
            ):
                self._last_share_at_monotonic = now_m
            self._last_accepted_shares = accepted_f

    def _baseline_values(self, profile: dict[str, Any]) -> dict[str, float]:
        out: dict[str, float] = {}
        for key, raw in (profile.get("metrics") or {}).items():
            med = RollingStats.from_dict(raw, MAX_SAMPLES).median()
            if med is not None:
                out[key] = med
        return out

    @staticmethod
    def _snapshot_values(data: dict[str, Any]) -> dict[str, Any]:
        ms = data.get("miner_sensors") or {}
        out: dict[str, Any] = {
            "hashrate": _try_float(ms.get("hashrate")),
            "power": _try_float(ms.get("miner_consumption")),
            "efficiency": _try_float(ms.get("efficiency")),
            "reject_rate": _try_float(data.get("reject_rate")),
            "seconds_since_share": _try_float(data.get("seconds_since_share")),
        }
        for slot, board in (data.get("board_sensors") or {}).items():
            bhr = _try_float(board.get("board_hashrate"))
            if bhr is not None:
                out[f"board_hashrate_{slot}"] = bhr
            ct = _try_float(board.get("chip_temperature")) or _try_float(
                board.get("board_temperature")
            )
            if ct is not None:
                out[f"board_temp_{slot}"] = ct
        for idx, fan in (data.get("fan_sensors") or {}).items():
            spd = _try_float(fan.get("fan_speed"))
            if spd is not None:
                out[f"fan_{idx}"] = spd
        return out


def _get_metric_stats(profile: dict[str, Any], key: str) -> RollingStats:
    metrics = profile.setdefault("metrics", {})
    return RollingStats.from_dict(metrics.get(key), MAX_SAMPLES)


def _save_metric_stats(profile: dict[str, Any], key: str, stats: RollingStats) -> None:
    profile.setdefault("metrics", {})[key] = stats.to_dict()


def _try_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _try_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

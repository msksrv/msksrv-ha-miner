"""Localized anomaly message templates (reason code + details)."""

from __future__ import annotations

from typing import Any

_TEMPLATES: dict[str, dict[str, str]] = {
    "hashrate_power_mismatch": {
        "en": (
            "Miner draws {current_power:.0f} W but hashrate is only {current_hashrate:.1f} TH/s "
            "(baseline {baseline_hashrate:.1f} TH/s). Possible board or backend fault."
        ),
        "ru": (
            "Майнер потребляет {current_power:.0f} W, но выдаёт только {current_hashrate:.1f} TH/s "
            "(обычно {baseline_hashrate:.1f} TH/s). Возможна неисправность платы или backend."
        ),
    },
    "hashrate_efficiency_drop": {
        "en": (
            "Hashrate down {hashrate_drop_pct:.0f}% while power changed {power_change_pct:.0f}%."
        ),
        "ru": (
            "Хешрейт снизился на {hashrate_drop_pct:.0f}%, потребление изменилось на {power_change_pct:.0f}%."
        ),
    },
    "board_hashrate_outlier": {
        "en": "Board {board} hashrate {board_hashrate:.1f} TH/s is {pct_below:.0f}% below other boards.",
        "ru": "Хешрейт платы №{board} на {pct_below:.0f}% ниже остальных плат.",
    },
    "board_temp_outlier": {
        "en": "Board {board} is {temp_delta:.0f} °C colder than other boards.",
        "ru": "Плата №{board} на {temp_delta:.0f} °C холоднее остальных.",
    },
    "fan_imbalance": {
        "en": "Fan {fan} speed is {pct_below:.0f}% below other fans.",
        "ru": "Скорость вентилятора №{fan} на {pct_below:.0f}% ниже остальных.",
    },
    "efficiency_degraded": {
        "en": (
            "Efficiency worsened by {degradation_pct:.0f}% "
            "(baseline {baseline_efficiency:.0f} J/TH, now {current_efficiency:.0f} J/TH)."
        ),
        "ru": (
            "Эффективность ухудшилась на {degradation_pct:.0f}% "
            "(обычно {baseline_efficiency:.0f} J/TH, сейчас {current_efficiency:.0f} J/TH)."
        ),
    },
    "reject_rate_high": {
        "en": "Reject rate {current_reject_rate:.2f}% above baseline {baseline_reject_rate:.2f}%.",
        "ru": "Процент отклонений {current_reject_rate:.2f}% выше обычного ({baseline_reject_rate:.2f}%).",
    },
    "share_stale": {
        "en": "No new shares for {seconds_since_share:.0f} s (baseline interval {baseline_share_interval:.0f} s).",
        "ru": "Нет новых шар {seconds_since_share:.0f} с (обычно каждые {baseline_share_interval:.0f} с).",
    },
    "post_reboot_slow_recovery": {
        "en": "After reboot hashrate recovered to {recovery_pct:.0f}% of baseline.",
        "ru": "После перезагрузки хешрейт восстановился только до {recovery_pct:.0f}% обычного значения.",
    },
}


def format_anomaly_message(
    reason: str, details: dict[str, Any], language: str | None
) -> str:
    """Build a human-readable message from reason code and numeric details."""
    lang = "ru" if language and language.startswith("ru") else "en"
    tmpl = _TEMPLATES.get(reason, {}).get(lang) or _TEMPLATES.get(reason, {}).get("en")
    if not tmpl:
        return reason
    try:
        return tmpl.format(**details)
    except (KeyError, TypeError, ValueError):
        return reason

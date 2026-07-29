# MSKSRV ASIC Miner 1.7 — changelog

## v1.7.0b11 (beta)

### Added

- **Repairs (phase 1):** hashboard, hashrate, critical temperature, fan — stable issue ids, confirm/recovery timers, EN/RU text, fix flow (reboot / power off / checked).

---

## v1.7.0b10 (beta)

### Fixed

- **Share interval floor:** learn intervals from **0.5 s** (was 5 s) so fast miners / low-difficulty pools can build a share baseline.

---

## v1.7.0b9 (beta)

Polish after b8 validation.

### Fixed

- **`detected_at`:** preserved from first anomaly until full normalization (primary reason change no longer resets it).
- **Share interval:** when multiple shares arrive between polls, interval is averaged per share (`interval / share_delta`).

### Changed

- **RU localization:** baseline entity names use «эталон» instead of loanword «baseline».

---

## v1.7.0b8 (beta)

Refinements after b7 field validation.

### Fixed

- **Share interval baseline:** accepted-share tracking runs every poll (~10 s); other metrics still learn once per minute.
- **Anomaly score:** overlapping rules deduplicated by group (performance, boards, fans, pool, shares, recovery) — only the most severe rule per group counts toward score; all active findings remain in attributes.
- **Hashrate floor:** critical hashrate/power mismatch uses `<= 20%` of baseline (inclusive boundary).

---

## v1.7.0b7 (beta)

Fixes critical baseline/anomaly bugs in v1.7.0b6.

### Fixed

- **Detector data format:** rules now receive full structured coordinator `data` (hashrate, power, boards, fans work).
- **Binary sensor platform:** `anomaly_detected` registered from `binary_sensor.py`, not `sensor.py`.
- **Mode warmup:** learning window resets on power/preset mode change (`max(mining_start, mode_start)`).
- **Share counter:** accepted-shares decrease after reboot resets interval tracking.
- **Learn order:** detect anomalies first; baseline updates only when clean (no anomaly, errors, fault, critical health).
- **Learn rate:** one sample per 60 s (360 samples ≈ 6 h history at 10 s polls).
- **Rule timers:** board/fan conditions always passed to timer logic (clears when normalized).
- **`detected_at`:** preserved from first trigger until anomaly clears.
- **Messages:** localized from `reason` + details (EN/RU by HA language).
- **Accept baseline:** adds 30 seed samples + `manually_seeded` flag (confidence floor 50 %).

### Note

**v1.7.0b6 is broken** — use b7 or later for anomaly detection.

---

## v1.7.0b6 (beta)

Self-learning statistical baseline and explainable anomaly detection.

### Added

- **Baseline learning** per power/preset mode (median + MAD, bounded window, outlier rejection).
- **Entities:** `sensor.*_anomaly_score`, `sensor.*_baseline_confidence`, `binary_sensor.*_anomaly_detected`.
- **Rules:** hashrate/power mismatch, efficiency drop, board/fan outliers, reject rate, learned share timeout, post-reboot recovery.
- **Buttons:** Reset learned baseline, Accept current as normal.
- Baseline persisted to disk (~every 10 min and on unload).

### Notes

- 15 min warmup after mining start; confidence grows over 1–24 h.
- No ML dependencies — lightweight statistics only.

---

## v1.7.0b5 (beta)

Polish from field review of v1.7.0b4.

### Fixed

- **Health profile selector:** `translation_key` so options show localized labels (Auto / Generic / Custom), not raw keys.
- Same for **pool action** and **farm tariff** selectors.

### Changed

- **Options → health section:** section description and per-field `data_description` (ideal hashrate ratio, chip vs board temps, mining-only metrics, Custom-only numbers).
- **`sensor.*_health_score` attributes:** `profile_name` (e.g. `WhatsMiner M21S`), `temperature_level` (`normal` / `elevated` / `critical`), `is_mining`; technical keys kept for automations.

### Notes

- Built-in manufacturer/model profiles remain **starting recommendations** — verify for your firmware or use Custom thresholds.

---

## v1.7.0b4 (beta)

Configurable health thresholds and model-based defaults.

### Added

- **Options → Miner health thresholds:** profile `Auto` (by make/model), `Generic`, or `Custom` with editable limits.
- **Built-in model profiles** for WhatsMiner, Bitmain/Antminer, Canaan/Avalon, Innosilicon, Goldshell, IceRiver (extensible in code).
- **`sensor.*_health_score`** attribute `threshold_profile` shows which profile was applied (e.g. `auto:whatsminer:m21s`).

### Changed

- Health scoring reads thresholds from profile/options instead of hardcoded globals.
- **Uptime sensor:** state rounded to minutes (no seconds in display) so Activity/logbook is not flooded every poll; exact value in attribute `uptime_seconds`.

---

## v1.7.0b3 (beta)

Temperature thresholds and maintenance logic tuned for real-world models (e.g. WhatsMiner M21S).

### Changed

- **Chip temperature:** warning 90 °C, critical 95 °C (was 75 / 85).
- **Board temperature:** warning 75 °C, critical 85 °C (was 65 / 75).
- **Warning zone:** partial score deduction only; binary sensor «Высокая температура» stays OFF.
- **Critical zone:** zero temp component, «Высокая температура» ON, «Требуется внимание» ON.
- **`sensor.*_health_score`:** attribute `temperature_status` (`ok` / `warning` / `critical`).
- **Renamed (RU):** «Оценка здоровья» → «Состояние майнера»; «Аномалия мощности» → «Проблема с мощностью»; «Требуется обслуживание» → «Требуется внимание».

---

## v1.7.0b2 (beta)

Improvements from field testing and scoring refinements.

### Changed

- **Scoring:** hashrate, fans, power, and shares are skipped (not penalized) when the miner is **not mining**.
- **Temperature:** separate warn/critical thresholds for chip and board; score uses the worst of the two.
- **Power:** draw below the configured limit no longer reduces the score (limit is an upper bound).
- **Errors / fault light:** aggregate score capped at 65 (errors) or 50 (fault light).
- **`sensor.*_health_score`:** new attributes `data_coverage` (% of weighted components available) and `operating_state` (`mining` / `stopped`).
- **`binary_sensor.*_pool_problem`:** device class `PROBLEM` instead of `CONNECTIVITY` (ON = problem exists).

### Added

- **`sensor.farm_*_health_score`** — farm aggregate health with attributes `miners_evaluated`, `miners_offline`, `issues`.

---

## v1.7.0b1 (beta)

**Miner health** — first 1.7 feature set (single beta; later betas will cover other features).

### Added

- **`sensor.*_health_score`** — overall health 0–100 % with attribute breakdown (`components`, `issues`, `seconds_since_share`, `errors`, `fault_light`).
- **Diagnostic binary sensors** (per miner):
  - `hashrate_low`
  - `temperature_high`
  - `fan_problem`
  - `board_problem`
  - `reject_rate_high`
  - `pool_problem`
  - `power_anomaly`
  - `maintenance_required`
- Coordinator now fetches **pyasic** `ERRORS`, `FAULT_LIGHT`, extended **pool metrics** (`active`, `alive`, `get_failures`, `pool_stale_percent`), board **missing/tuned** flags, and tracks **time since last accepted share**.

### Scoring (weights)

| Component | Weight |
|-----------|--------|
| Hashrate vs ideal | 25 % |
| Boards / chips | 20 % |
| Temperature | 15 % |
| Fans | 10 % |
| Reject rate | 10 % |
| Power | 10 % |
| Pool connectivity | 5 % |
| Share freshness | 5 % |

Missing data for a component is excluded from the weighted average (not penalized as zero).

### Not in this beta

- Configurable thresholds (options flow)
- Per-model threshold profiles

---

## Planned for 1.7.0 (stable)

After additional beta cycles for **other** 1.7 features, merge and release stable **v1.7.0**.

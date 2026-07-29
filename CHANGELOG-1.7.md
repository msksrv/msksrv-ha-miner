# MSKSRV ASIC Miner 1.7 — changelog

## v1.7.0b21 (beta)

### Changed

- **`energy_total` state class:** `TOTAL_INCREASING` for miner and farm (monotonic Energy Dashboard totals).
- **Legacy `farm_cost_*`:** auto-disabled in Entity Registry (`disabled_by=integration`) on load unless legacy option enabled.
- **Flat tariff UI:** single currency + price slot; energy cost uses the primary rate only (extra stored slots ignored).

---

## v1.7.0b20 (beta)

### Added (Energy cost — farm UI alignment)

- **Farm cost sensors from energy record:** today, month, total (`total_cost` in Store), previous month.
- **Cost at current power:** `{currency}/h` rate sensor (not MONETARY — monetary speed, not balance).

### Changed

- **Legacy `farm_cost_*` sensors:** disabled by default; optional re-enable in farm energy settings.
- **Legacy sensor labels:** marked «(legacy)» / «(устар.)» to distinguish from energy-based cost sensors.

---

## v1.7.0b19 (beta)

### Added (Energy — point 8, phase 1)

- **`energy/` module:** source selection, trapezoidal power integration, physical-meter reset stitching, HA Store persistence.
- **Per-miner options:** energy source mode (auto / physical / switch power / miner power), optional physical and power sensors.
- **Sensors:** `energy_total` (miner) and `farm_energy_total` — Energy Dashboard compatible (`device_class: energy`, monotonic TOTAL kWh).
- **Farm option:** optional whole-farm physical energy meter (PDU); otherwise sums member totals.
- **Attributes:** active source, estimated flag, data quality %, farm coverage breakdown.
- **Guards:** max integration gap, no integration on missing power, duplicate physical sensor blocked across miners.

### Added (Energy — point 8, phase 2)

- **Period sensors:** today, month, previous month (miner + farm); `TOTAL_INCREASING` with calendar reset.
- **Efficiency:** weighted average J/TH for today and month (energy ÷ delivered terahashes).
- **Cost metrics:** cost per TH/s·hour (farm tariff); farm cost per PH·day.
- **Idle metrics:** lost terahashes and energy saved during downtime (not speculative revenue).
- **Diagnostics:** energy source and data quality % sensors.

### Fixed (Energy — point 8, review round)

- **Persistence:** `mark_dirty()` after every tick; totals, periods, offset, cost, hash work, and quality survive restart.
- **Farm total:** canonical delta accumulator (`member_last_totals`); add/remove miners and PDU↔sum switches no longer jump the total.
- **Physical source switch:** first reading anchors to current canonical total via offset (no false +4900 kWh spike).
- **Physical reset:** only drops >10% stitch offset; small noise ignored.
- **PH·day formula:** `cost × 1000 × 86400 / hash_th` (was ~41.7× too high).
- **Baseline reference:** `"baseline"` hashrate_reference resolves via learned baseline (priority over ideal).
- **Data quality:** every poll registers expected interval; integrated only on valid samples; day-scoped %.
- **Calendar reset:** day/month buckets reset at tick start even without valid energy data.
- **Double tick:** energy runs once on successful poll; failed poll ticks unavailable only in `async_refresh`.
- **Duplicate physical:** registry scans all config entries + auto-resolved entities; farm PDU included; conflict → fallback.
- **Units:** Wh/kWh/MWh and W/kW/MW only; unknown unit → skip read (no silent kWh/W guess).
- **Cost sensors:** composite units use MEASUREMENT without MONETARY device class.

### Fixed (Energy — point 8, review round 2)

- **Offline hashrate:** `last_hashrate_th_s` now stores zero; idle intervals no longer repeat half-rate hash delivery.
- **Lost hash offline:** persisted `last_reference_hashrate_th_s`; used when poll data is unavailable.
- **Farm summed cost:** `record.last_ts` updated each summed tick so tariff integration has a valid interval.
- **Re-added miner:** stale `member_last_totals` entries pruned when miner leaves the farm.
- **Farm PDU conflict:** `physical_sensor_in_use()` blocks duplicate PDU assignment across farms.
- **Data quality:** expected interval uses full elapsed time (no 30 s cap).
- **Storage version:** kept at 2 — new fields load via `from_dict()` defaults.
- **Idle saved:** nominal power tracked from miner telemetry regardless of energy source.

### Fixed (Energy — point 8, review round 3)

- **Farm PDU self-reject:** registry exclude now matches both `entry_id` and `farm_{entry_id}`.
- **Farm PDU form validation:** `_async_farm_save_energy()` rejects sensors already assigned elsewhere.
- **Period vs quality interval:** hash/lost-hash use capped `period_dt_s`; long gaps still degrade data quality.
- **Physical energy after gap:** day/month kWh and cost still recorded when `delta_kwh > 0` even if `period_dt_s = 0`.
- **Store version:** `STORAGE_VERSION = 3` with pass-through migrator for v2 installs.
- **Nominal power:** updated only when hashrate ≥ 75% of reference.

### Fixed (Energy — point 8, review round 4)

- **Store migration:** `EnergyStore` subclass with `_async_migrate_func()` (HA-compatible API).
- **PDU error text:** mentions miner or farm assignment conflict.
- **Tests:** pytest coverage for physical reset/anchor, offline/lost hash, long gap, source switch, farm member prune, store migration.

---

## v1.7.0b18 (beta)

### Added (Automatic recovery — point 7)

- **Strict FSM** in `health/recovery/`: arming → reboot → optional power cycle → lock.
- **Per-miner options:** enable (default off), dwell, post-reboot/power waits, power cycle consent, attempt limits, cooldown.
- **HA Store persistence** for recovery state across reloads.
- **Farm mutex:** at most one auto-recovery per farm.
- **Events:** recovery_started/cancelled/locked, reboot/power cycle success/failure, manual reset.
- **Repair `recovery_failed`** when automatic attempts are exhausted (separate from hashrate repair).
- **Reset recovery lock** button and repair actions.

### Protections

- No auto-recovery for board/temp/fan/power/pool/offline faults.
- Manual reboot/power → cooldown; pool/mode/IP change → temporary block.
- Power cycle only with explicit option + linked switch; switch state verified after commands.

### Fixed (point 7 review)

- **Offline-tolerant wait states:** reboot/power waits continue while miner is unreachable; `POWER_OFF_WAIT` always proceeds to power-on.
- **`POWER_ON_PENDING`:** mandatory turn-on retries (5×) with `power_restore_failed` Repair on failure.
- **Max reboot/cycle settings:** retry until limits before lock or next phase.
- **Cooldown after success** prevents immediate re-entry loops.
- **Strict hashrate recovery check** requires current, expected, and threshold values.
- **Farm slot** re-claimed after HA reload; released on miner unload.
- **Config block** persisted to Store; power-critical states finish restore first.
- **`recovery_reboot_command_sent`** event carries attempt context.

### Fixed (point 7 review — round 2)

- **Disable/unload/remove** during power-critical states restores switch before cancel.
- **Manual power** during `POWER_OFF_WAIT`/`POWER_ON_PENDING` no longer cancels until switch is on.
- **`async_prepare_unload`** for integration reload/delete safety.
- **Config block** ignored during power-critical FSM states.
- **Reboot send failures** count as attempts with retry delay.
- **Event attempt numbers** reflect the upcoming action attempt.
- **Farm lock rollback** when a second farm rejects the claim.
- **Emergency stop** cancels member auto-recovery (intentional off, no power restore).

### Fixed (point 7 review — round 3)

- **Emergency stop ordering:** latch all recovery stores (loaded and unloaded miners) before any `turn_off`; cancel pending FSM actions synchronously.
- **Persisted `emergency_stop_latched`:** blocks `turn_on` in recovery, unload, reload, and entry removal until explicitly cleared.
- **Clear emergency stop** farm button with two-step confirm (30 s); manual switch on does not clear the latch.
- **Farm events:** `emergency_power_off_partial_failure` and `emergency_power_off_failed` with per-switch details.
- **Entry removal:** skip power restore when latched; keep recovery store if power restore fails during critical state.
- **Emergency power off** verifies switch state via `async_power_off` (parallel); `emergency_stop_cleared` and `no_switches` failure event.
- **Farm membership** cannot change while emergency stop is active.
- **Clear emergency stop** resets recovery cooldown; UI refreshes immediately after stop/clear.

---

## v1.7.0b17 (beta)

### Added (Events — point 6)

- **Event entities:** `event.<miner>_activity` and `event.<farm>_activity` with native `event.received` triggers.
- **Integration bus:** `miner_event` for automations across all miners/farms.
- **Miner events:** offline, online, problem_detected/cleared/acknowledged (from Repairs), pool/work mode changes, reboot_command_sent, ip_changed.
- **Farm events:** emergency_power_off, preset_applied, preset_partial_failure, preset_failed.
- **Anti-spam:** seed on first poll, offline after 3 failed polls, stable-read confirmation for pool/mode changes.
- **Unified reboot helper:** button, service, and repair flow all emit `reboot_command_sent`.

### Fixed (point 6 review)

- **Event entity trigger:** use `_trigger_event()` + `async_write_ha_state()` via public `async_trigger()`.
- **problem_cleared** only on automatic Repair recovery; user dismiss → `problem_acknowledged`.
- **Reboot order:** command first, then `notify_reboot()` and event emission.
- **Farm preset logging** and `preset_failed` when all members fail; neutral `apply_failed` reason.
- **Initial offline seed** no longer fakes a prior offline event.
- **problem_detected reason** matched to repair type via `anomaly.findings`.
- **problem_acknowledged** clears `_open_problems` so a later recurrence is not suppressed.

---

## v1.7.0b16 (beta)

### Added (Farm — point 5)

- **Miner classification:** healthy / warning / problem / offline / unknown (mutually exclusive).
- **New farm sensors:** `farm_miners_healthy`, `farm_miners_with_issues`, `farm_expected_hashrate`, `farm_lost_hashrate`, `farm_average_efficiency`, `farm_hottest_miner`, `farm_worst_reject_rate`.
- **Expected hashrate:** per-miner baseline (when ready) or ideal hashrate; offline miners count expected but actual = 0.
- **Lost hashrate:** `max(expected − actual, 0)` with `lost_percent` attribute.
- **Weighted efficiency:** `total_power_w / total_hashrate_th` (J/TH).
- **Mixed algorithms:** expected/lost/efficiency sensors unavailable with `reason: mixed_algorithms`.
- **Farm health score attrs:** status counts, `problem_devices` (max 20), truncation counter.

### Fixed (point 5 review)

- **Mixed algorithms:** blocked when creating a farm and when saving farm members (existing farms still guarded in coordinator).
- **Algorithm validation:** uses last known algorithm from coordinator data (incl. offline); unknown algorithm blocks save.
- **Lost hashrate:** compares expected only against actual from miners with known expected.
- **`problem_devices`:** includes warning, problem, and offline miners; anomaly reason preserved; `status` field added.

---

## v1.7.0b15 (beta)

### Added (Health & Repairs — point 4)

- **Power thresholds:** `power_low_ratio` / `power_high_ratio` vs learned baseline per power mode (fallback to power limit when baseline not ready).
- **Configurable repair timing:** default warning delay (5 min) and recovery (4 min) in options; advanced per-type overrides; temperature/offline keep safer fixed defaults unless overridden.
- **Hashrate repair:** triggers on `health.flags.hashrate_low` with user confirm delay (anomaly rules still instant).
- **Power repair:** new issue type with check power / profile / reboot / thresholds actions.
- **Auto profile hybrid:** model/manufacturer temps + generic performance thresholds; baseline medians exposed on health sensor when learned.

### Fixed (b15 review)

- **Recovery timing** applied on every poll via `set_recovery_seconds()` (no reload required).
- **Hashrate reference:** Auto → learned baseline; Generic/Custom → ideal hashrate (`hashrate_reference` attribute).
- **Fan imbalance:** zero extra confirm in Repairs (detector already waited).
- **Power low ratio** applies via `power_limit × ratio` before baseline is ready.
- **Options sections:** field labels moved to `sections.*.data` (health thresholds, repair timing, etc.).
- Removed unused `CONFIRM_FAN_IMBALANCE_SECONDS`.

---

## v1.7.0b14 (beta)

### Fixed (Repairs blockers)

- **`_open` after reload:** both managers seed open issues from Issue Registry; recovery runs on first poll when the fault cleared; ignored issues are recreated when the fault returns.
- **Retry poll:** dismiss only when `last_update_success` (miner) or all farm members are online after refresh.
- **Thresholds:** native numeric form inside the repair flow; saves to `config_entry.options`; repair stays open.
- **Farm offline dedup:** suppress miner-offline only when the miner belongs to a **loaded** farm entry.
- **Ignore:** removed `recreate_issue_if_ignored()` — ignored issues stay ignored until the fault clears (4 min recovery) or a new separate fault creates a fresh issue.
- **Threshold form:** human-readable field labels and `repairs.error` translations for validation.

### Other

- Remove misleading hashrate **duration** placeholder after reload.
- Delete baseline storage on config entry removal.
- RU copy cleanup (pool, temperature, switch, backend, etc.).

---

## v1.7.0b13 (beta)

### Added (Repairs phase 2)

- **Miner offline** (>10 min unreachable) — suppressed when miner is a farm member.
- **Farm offline** — aggregate repair with truncated miner list (3 + “and N more”).
- **Pool / shares** — `pool_problem`, `share_stale`, anomaly `share_stale`.
- **Slow recovery** — anomaly `post_reboot_slow_recovery`.
- **High reject rate** — health flag (≥100 shares) or anomaly `reject_rate_high`.
- **Fix flow:** retry poll, restart backend, power on, open threshold options; farm retry for offline members.
- **Bugfix:** repair flow parsed issue id `(scope, entry_id, type)` correctly.

---

## v1.7.0b12 (beta)

### Fixed (Repairs)

- **Lifecycle race:** open issues stay active when fault returns during recovery (raw vs confirmed).
- **Unload:** issues no longer deleted on reload; only on config entry removal (`async_remove_entry`).
- **Reboot flow:** abort when miner unavailable; `notify_reboot()` only after successful reboot.
- **Placeholders:** board/hashrate/fan use matching anomaly finding; three hashboard text variants; chip + board temps; hashrate duration from repair timer.
- **Power off:** requires `switch.*` entity; errors abort with translation.
- **Abort reasons:** EN/RU for all repair flow failures.

---

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

# MSKSRV ASIC Miner 1.7 — changelog

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

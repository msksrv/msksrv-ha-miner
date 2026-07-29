# MSKSRV ASIC Miner 1.7 — changelog

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

- Farm-level health aggregate
- Configurable thresholds (options flow)
- Per-model threshold profiles

---

## Planned for 1.7.0 (stable)

After additional beta cycles for **other** 1.7 features, merge and release stable **v1.7.0**.

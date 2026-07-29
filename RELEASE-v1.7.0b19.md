## MSKSRV ASIC Miner v1.7.0b19 (beta)

Energy accounting — **point 8**: canonical monotonic totals, Energy Dashboard compatibility, farm PDU/summed aggregation, and period metrics.

**Install:** HACS → custom repo → branch **`beta`**, or extract `miner.zip` from the release assets into `config/custom_components/miner/`.

### Energy totals (Energy Dashboard)

- Per-miner source selection: auto / physical meter / switch power / miner power
- `energy_total` and `farm_energy_total` — `device_class: energy`, monotonic TOTAL kWh
- Optional whole-farm PDU meter; otherwise delta-sum of member totals (composition changes do not jump the total)
- Physical meter: first-read anchor, reset stitching (>10% drop), duplicate-sensor registry

### Period sensors & metrics

- Today / month / previous month (miner + farm)
- J/TH efficiency, cost per TH/s·hour, farm cost per PH·day (farm tariff)
- Lost terahashes and idle energy saved (not speculative revenue)
- Energy source and data quality % diagnostics

### Reliability fixes (review rounds)

- Store persistence with `EnergyStore._async_migrate_func()` (v2/v3)
- Offline/lost-hash with stored reference; quality vs period interval split
- No double energy tick; calendar reset without valid sample
- Farm summed cost, member baseline prune on re-add, PDU conflict in form + runtime

### Tests

- `pytest tests/test_energy.py` — physical reset/anchor, offline, long gap, source switch, farm prune, store migration

Full changelog: [CHANGELOG-1.7.md](https://github.com/msksrv/msksrv-ha-miner/blob/beta/CHANGELOG-1.7.md)

**Stable:** [`main`](https://github.com/msksrv/msksrv-ha-miner/tree/main) = **v1.6.16**.

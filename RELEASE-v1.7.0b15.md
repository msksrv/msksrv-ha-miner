## MSKSRV ASIC Miner v1.7.0b15 (beta)

Health & Repairs — **point 4**: configurable thresholds, repair timing, power/hashrate repairs, Auto profile hybrid.

**Install:** HACS → custom repo → branch **`beta`**, or extract `miner.zip` into `config/custom_components/miner/`.

### New in b15

- **Power thresholds:** `power_low_ratio` / `power_high_ratio` vs learned baseline (fallback to power limit before baseline is ready).
- **Repair timing:** configurable default confirm delay and recovery in Options; per-type overrides.
- **Hashrate repair** on `hashrate_low`; **Power repair** with check/threshold/reboot actions.
- **Auto profile hybrid:** model temps + generic performance thresholds; baseline on health sensor.

### Fixes

- Recovery timing updates without integration reload.
- Hashrate reference: Auto → baseline, Generic/Custom → ideal hashrate.
- Fan imbalance: no double confirm in Repairs.
- Options section field labels localized (EN/RU).

Full changelog: [CHANGELOG-1.7.md](https://github.com/msksrv/msksrv-ha-miner/blob/beta/CHANGELOG-1.7.md)

**Stable:** [`main`](https://github.com/msksrv/msksrv-ha-miner/tree/main) = **v1.6.16**.

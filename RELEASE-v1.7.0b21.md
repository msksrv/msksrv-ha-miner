## MSKSRV ASIC Miner v1.7.0b21 (beta)

Current **1.7 beta** — energy cost alignment, registry cleanup, Energy Dashboard polish.

**Install:** HACS → custom repo → branch **`beta`**, or extract `miner.zip` from this release.

### Since v1.7.0b20

- **Legacy `farm_cost_*`:** auto-disabled in Entity Registry on load (`disabled_by=integration`); re-enable via farm energy settings if needed.
- **`energy_total`:** `TOTAL_INCREASING` for miner and farm (monotonic canonical total).
- **Flat tariff:** single currency slot; energy cost uses primary rate only.

### Energy module (point 8)

- Canonical monotonic kWh totals (miner + farm, PDU or summed members).
- Cost sensors from same `EnergyRecord`: today, month, total, previous month, cost at current power (`RUB/h`).
- Period metrics: J/TH, cost/TH·h, PH·day, lost hash, idle saved.

Full changelog: [CHANGELOG-1.7.md](https://github.com/msksrv/msksrv-ha-miner/blob/beta/CHANGELOG-1.7.md)

**Stable:** [`main`](https://github.com/msksrv/msksrv-ha-miner/tree/main) = **v1.6.16**.

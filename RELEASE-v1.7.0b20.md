## MSKSRV ASIC Miner v1.7.0b20 (beta)

Energy cost UI — replaces conflicting legacy `farm_cost_*` sensors with energy-record costs.

**Install:** HACS → custom repo → branch **`beta`**, or extract `miner.zip` from release assets.

### New farm cost sensors (from energy module)

- **Electricity cost today / month / total / previous month** — tied to the same energy accounting as `farm_energy_total` (starts from install, consistent totals).
- **Cost at current power draw** — `{currency}/h` (e.g. 25.14 RUB/h = 3.142 kW × 8 RUB/kWh).

### Legacy sensors

- Old **`farm_cost_*`** (power integration + RestoreEntity history) **disabled by default**.
- Re-enable optionally: Farm options → Energy meter → «Legacy power-based cost sensors».
- Legacy entities marked «(legacy)» in the name.

Full changelog: [CHANGELOG-1.7.md](https://github.com/msksrv/msksrv-ha-miner/blob/beta/CHANGELOG-1.7.md)

**Stable:** [`main`](https://github.com/msksrv/msksrv-ha-miner/tree/main) = **v1.6.16**.

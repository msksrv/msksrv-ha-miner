## MSKSRV ASIC Miner v1.7.0b22 (beta)

Current **1.7 beta** — fix for legacy cost sensor enablement on first load.

**Install:** HACS → branch **`beta`**, or extract `miner.zip` into `config/custom_components/miner/`.

### Fixed

- Legacy `farm_cost_*` registry migration now runs **after** sensor platforms are set up. Enabling legacy cost sensors no longer requires a second integration reload.

Includes all **v1.7.0b21** changes (energy cost from `EnergyRecord`, `TOTAL_INCREASING` totals, single-currency flat tariff, auto-disable legacy entities).

Full changelog: [CHANGELOG-1.7.md](https://github.com/msksrv/msksrv-ha-miner/blob/beta/CHANGELOG-1.7.md)

**Stable:** [`main`](https://github.com/msksrv/msksrv-ha-miner/tree/main) = **v1.6.16**.

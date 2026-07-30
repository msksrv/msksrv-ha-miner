## MSKSRV ASIC Miner v1.7.0b23 (beta)

Current **1.7 beta** — farm startup with offline linked miners.

**Install:** HACS → branch **`beta`**, or extract `miner.zip` into `config/custom_components/miner/`.

### Fixed

- Farm no longer crashes when a linked miner coordinator exists but `coord.data is None` (offline / failed poll). Farm loads with correct counts (miners online: 0, health: 0%), offline member in problem list, farm offline Repair after grace period.

Includes **v1.7.0b22** (legacy cost migration after platform setup) and earlier 1.7 beta energy/health work.

Full changelog: [CHANGELOG-1.7.md](https://github.com/msksrv/msksrv-ha-miner/blob/beta/CHANGELOG-1.7.md)

**Stable:** [`main`](https://github.com/msksrv/msksrv-ha-miner/tree/main) = **v1.6.16**.

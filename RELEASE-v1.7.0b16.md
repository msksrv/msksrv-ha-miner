## MSKSRV ASIC Miner v1.7.0b16 (beta)

Farm aggregates — **point 5**: miner classification, lost hashrate, weighted efficiency, strict algorithm validation.

**Install:** HACS → custom repo → branch **`beta`**, or extract `miner.zip` into `config/custom_components/miner/`.

### New farm sensors

- `farm_miners_healthy`, `farm_miners_with_issues`
- `farm_expected_hashrate`, `farm_lost_hashrate` (key metric for daily ops)
- `farm_average_efficiency` (total power / total hashrate, J/TH)
- `farm_hottest_miner`, `farm_worst_reject_rate`
- Extended `farm_health_score` attributes (`problem_devices`, status counts)

### Farm composition rules

- Mixed algorithms blocked at farm create/edit (`farm_mixed_algorithms`)
- Unknown algorithm blocks save until miner connects (`farm_algorithm_unknown`)
- Offline miners use last known algorithm from coordinator data

Full changelog: [CHANGELOG-1.7.md](https://github.com/msksrv/msksrv-ha-miner/blob/beta/CHANGELOG-1.7.md)

**Stable:** [`main`](https://github.com/msksrv/msksrv-ha-miner/tree/main) = **v1.6.16**.

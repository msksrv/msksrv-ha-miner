## MSKSRV ASIC Miner v1.7.0b17 (beta)

Activity events — **point 6**: event entities, integration bus, and repair-aware problem lifecycle.

**Install:** HACS → custom repo → branch **`beta`**, or extract `miner.zip` into `config/custom_components/miner/`.

### Event entities & bus

- `event.<miner>_activity` and `event.<farm>_activity` (HA 2026 `event.received` triggers)
- Integration bus `miner_event` with `device_id`, `entry_id`, `scope`, `type`

### Miner events

- offline / online (3-poll threshold, no spurious online)
- problem_detected / problem_cleared / problem_acknowledged (Repair sync)
- pool_changed, work_mode_changed (2 stable polls)
- reboot_command_sent, ip_changed

### Farm events

- emergency_power_off
- preset_applied, preset_partial_failure, preset_failed

Full changelog: [CHANGELOG-1.7.md](https://github.com/msksrv/msksrv-ha-miner/blob/beta/CHANGELOG-1.7.md)

**Stable:** [`main`](https://github.com/msksrv/msksrv-ha-miner/tree/main) = **v1.6.16**.

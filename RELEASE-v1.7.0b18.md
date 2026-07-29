## MSKSRV ASIC Miner v1.7.0b18 (beta)

Automatic recovery — **point 7**: strict FSM, farm mutex, persisted state, and safe emergency stop.

**Install:** HACS → custom repo → branch **`beta`**, or extract `miner.zip` into `config/custom_components/miner/`.

### Automatic recovery (off by default)

- Strict FSM: arming → reboot → optional power cycle → lock
- Per-miner options: dwell, waits, power-cycle consent, attempt limits, cooldown
- HA Store persistence across reloads; at most one auto-recovery per farm
- Events for all recovery actions; Repair `recovery_failed` when exhausted
- **Reset recovery lock** button and repair actions

### Protections

- No auto-recovery for board/temp/fan/power/pool/offline faults
- Manual reboot/power → cooldown; pool/mode/IP change → temporary block
- Power cycle only with explicit option + linked switch; switch state verified
- Offline-tolerant wait states; mandatory power restore after power cycle
- `power_restore_failed` Repair when turn_on fails after retries

### Farm emergency stop

- Persisted `emergency_stop_latched` on all members (loaded and unloaded) **before** `turn_off`
- Recovery cannot turn power on while latched
- Verified switch off (parallel); events: success / partial failure / failure / cleared
- **Clear emergency stop** button (two-step confirm); membership change blocked while active

Full changelog: [CHANGELOG-1.7.md](https://github.com/msksrv/msksrv-ha-miner/blob/beta/CHANGELOG-1.7.md)

**Stable:** [`main`](https://github.com/msksrv/msksrv-ha-miner/tree/main) = **v1.6.16**.

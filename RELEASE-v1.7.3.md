## MSKSRV ASIC Miner 1.7.3

The Home Assistant event card now shows which problem occurred, for example Overheating, Low hashrate, or Fan problem. Open the event to see the available readings, thresholds, or recovery attempts captured when it was reported. Disconnect events show how many polls failed in a row.

The `miner_event` bus and the bundled alert blueprint still use `type: problem_detected` with `problem_type`. If an automation filters the `event.*` entity attribute `event_type` directly, use the specific value, such as `problem_detected_temperature`, or use the bus event.

Update through HACS and restart Home Assistant.

[Changelog](https://github.com/msksrv/msksrv-ha-miner/blob/v1.7.3/CHANGELOG-1.7.md)

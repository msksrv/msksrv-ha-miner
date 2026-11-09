## MSKSRV ASIC Miner 1.7.2

Miner uptime still updates on the device card, but periodic updates no longer fill Home Assistant Activity. Home Assistant now receives uptime as a duration.

The entity ID and `uptime_seconds` attribute are unchanged. If a template reads the entity state directly, it now receives seconds instead of a string like `1h 36m`.

Install the update from HACS and restart Home Assistant. No YAML changes are needed.

[Changelog](https://github.com/msksrv/msksrv-ha-miner/blob/v1.7.2/CHANGELOG-1.7.md)

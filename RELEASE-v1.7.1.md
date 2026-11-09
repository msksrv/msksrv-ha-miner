## MSKSRV ASIC Miner 1.7.1

- Scheduled polling now publishes connectivity events and updates Repairs, automatic recovery and energy accounting.
- Power restoration resumes even if the first poll fails after a Home Assistant restart. The integration records the pending restoration before issuing an automatic power cut.
- Added diagnostic downloads for miners and farms. The export omits network addresses, credentials and pool configuration.
- Added an [alerts blueprint](https://github.com/msksrv/msksrv-ha-miner/blob/v1.7.1/blueprints/automation/msksrv/miner_alerts.yaml) for offline, overheating and recovery lock notifications.

The power and connectivity regression tests use a local Bitaxe emulator and a simulated switch.

[Changelog](https://github.com/msksrv/msksrv-ha-miner/blob/v1.7.1/CHANGELOG-1.7.md)

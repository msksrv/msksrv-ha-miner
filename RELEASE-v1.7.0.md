## MSKSRV ASIC Miner 1.7.0

- Health scores, learned baselines, Home Assistant Repairs, farm health, and activity events.
- Optional automatic hashrate recovery and power cycling. Farm emergency stop keeps its lock across reloads and takes precedence over an in-flight recovery power command.
- Cumulative kWh for the Energy Dashboard, optional physical meters, and electricity cost for farm tariffs.
- Compatibility with Home Assistant Core 2026.11, including sensor setup and event delivery. Legacy cost sensors are disabled by default and can be re-enabled in farm energy options.

Validated with Home Assistant Core and a loopback Bitaxe Gamma emulator. Power control tests used a simulated switch.

To install manually, extract `miner.zip` into `config/custom_components/miner/` and restart Home Assistant. The release is also available for installation through the repository in Marketplace or HACS.

[Full changelog](https://github.com/msksrv/msksrv-ha-miner/blob/v1.7.0/CHANGELOG-1.7.md)

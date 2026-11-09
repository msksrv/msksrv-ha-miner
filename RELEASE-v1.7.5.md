## MSKSRV ASIC Miner 1.7.5

- **New price from a date.** Choose it directly under **Electricity tariff**, next to the flat, two-zone, and three-zone choices. The form asks for a date and prices. It uses the configured currency and zone hours.
- **Tariff schedule and correction.** A future rate starts at local midnight. Saving a past date recalculates the farm cost totals from Recorder when history covers the requested period.
- **Monthly summary.** Import the [Home Assistant blueprint](https://github.com/msksrv/msksrv-ha-miner/blob/v1.7.5/blueprints/automation/msksrv/farm_monthly_summary.yaml) to receive the farm's previous-month energy use and estimated cost.
- **Farm members.** The picker lists individual miners and preserves existing valid selections.

Update through HACS and restart Home Assistant.

[Changelog](https://github.com/msksrv/msksrv-ha-miner/blob/v1.7.5/CHANGELOG-1.7.md)

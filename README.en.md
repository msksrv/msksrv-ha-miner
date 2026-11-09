# MSKSRV ASIC Miner — Home Assistant integration for ASIC miners

**Language:** [Русский](README.md) · **English**

**MSKSRV ASIC Miner** is a custom [Home Assistant](https://www.home-assistant.io/) integration for local monitoring and control of ASIC miners. It talks to miners on your LAN through [pyasic](https://github.com/UpstreamData/pyasic); no cloud service is required.

Each miner gets its own device (Antminer, WhatsMiner, Avalon, Innosilicon, Goldshell, IceRiver, BitAxe, and others supported by pyasic). Multiple miners can be grouped into a **farm** — a virtual device with shared statistics, pool tools, emergency power-off, and optional **estimated** electricity cost.

[![GitHub Release](https://img.shields.io/github/v/release/msksrv/msksrv-ha-miner?style=for-the-badge)](https://github.com/msksrv/msksrv-ha-miner/releases)
[![License: Source-available](https://img.shields.io/badge/License-Source--available-red?style=for-the-badge)](LICENSE)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)

[![Open your Home Assistant instance and open the repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=msksrv&repository=msksrv-ha-miner&category=integration)

---

## Contents

- [Features](#features)
- [Installation](#installation)
- [Configuration](#configuration)
- [Farm](#farm)
- [Miner entities](#miner-entities)
- [Farm entities](#farm-entities)
- [Health, recovery, and energy](#health-recovery-and-energy)
- [Automations](#automations)
- [Actions](#actions)
- [Discovery](#discovery)
- [Requirements](#requirements)
- [Security](#security)
- [Troubleshooting](#troubleshooting)
- [Reporting bugs](#reporting-bugs)
- [Limitations](#limitations)
- [License](#license)

---

## Features

| Area | Capabilities |
|------|----------------|
| **Discovery** | DHCP (hostname and MAC), subnet scan, manual IP |
| **Miner** | Hashrate, thermal, fans, pools, power limit, mining pause |
| **Farm** | Totals, emergency stop, bulk pool apply, single- or multi-zone tariff |
| **Automation** | Services and device actions for reboot, work mode, pools |

The integration polls miners every **10 seconds** and updates farm metrics every **15 seconds**. Live telemetry becomes unavailable when a miner loses connectivity. The farm keeps updating and includes unreachable members in its health assessment.

[Latest stable release](https://github.com/msksrv/msksrv-ha-miner/releases/latest) · [1.7 changelog](CHANGELOG-1.7.md)

---

## Installation

### Home Assistant 2026.11 or later

1. Open **Settings → Marketplace → Add from link**.
2. Enter `https://github.com/msksrv/msksrv-ha-miner`. Connect GitHub if the Marketplace prompts you.
3. Open **MSKSRV ASIC Miner** and install the stable version. Restart Home Assistant if prompted.

Home Assistant migrates existing HACS repositories and installations when you upgrade. [Marketplace documentation](https://www.home-assistant.io/integrations/marketplace/#custom-repositories)

### Home Assistant 2026.3–2026.10 with HACS

In HACS, open **⋮ → Custom repositories**. Add `https://github.com/msksrv/msksrv-ha-miner` with type **Integration**, then download **MSKSRV ASIC Miner** and restart Home Assistant. [HACS documentation](https://www.hacs.xyz/docs/faq/custom_repositories/)

### Manual installation and updates

Download [miner.zip](https://github.com/msksrv/msksrv-ha-miner/releases/latest/download/miner.zip) from the stable release. Extract its contents into `config/custom_components/miner/` so `manifest.json` sits directly inside `miner`. To update, replace the integration files and keep the existing Home Assistant entries. Restart Home Assistant.

---

## Configuration

Common path: **Settings → Devices & services → Integrations → MSKSRV ASIC Miner**.

Open **Configure** on the miner or farm entry on the Integrations page to change its options.

### Add a miner

1. **Add integration** → **Scan**, **Manual**, or finish after DHCP discovery.
2. Enter **RPC / web / SSH** credentials if prompted.
3. Set a device name.

### Reconfigure

On a single-miner entry: **Reconfigure** (often under **⋯**) — IP, credentials, power range. Leave **password fields empty** to keep stored values.

### Miner options

**Configure** on the miner entry:

- **Power switch** — link a `switch` for power on/off buttons.
- **Energy source** — automatic selection, physical meter, or estimation from power.
- **Miner health thresholds** — automatic model profile, generic thresholds, or custom thresholds.
- **Repair timing** — how long a fault must persist before a Repair opens and how long readings must stay normal before it clears.
- **Automatic recovery** — reboot for sustained low hashrate, with optional power cycling.
- **Stratum pool** — replace the primary pool or add a backup. Confirm the change while the miner is reachable.

---

## Farm

A **farm** groups existing miner devices into one virtual device.

1. In the **MSKSRV ASIC Miner** setup flow, choose **Farm**, enter a name, and select miners that report the same algorithm. If a miner's algorithm is unknown, wait for a successful poll.
2. **Configure** on the farm entry opens a menu:

| Item | Purpose |
|------|---------|
| **Farm members** | Miner device list |
| **Room temperature sensors** | `sensor` with `device_class: temperature` |
| **Pools and workers** | Up to five stratum presets |
| **Electricity tariff** | A single rate or two or three time-of-use periods with separate rates |
| **Farm energy meter** | A shared physical meter and the legacy cost sensor option |
| **Mass actions** | Apply a preset to all members (with confirmation) |

Configure a **power switch** on each member (**Configure** on that miner’s entry) for emergency stop to work.

**Emergency stop** persists a recovery lock for members before turning off linked power switches in parallel. A switch failure does not interrupt the other requests.

**Bulk pool apply** is blocked when members report **different algorithms**. The operation is **not transactional**: if one miner is offline or rejects the change, others may already have been updated.

The integration estimates **electricity cost** using the configured tariff and measured or calculated energy.

After you save farm options, the entry **reloads automatically**.

Preset pool passwords are not shown again in forms; an empty password field keeps the stored value.

---

## Miner entities

| Platform | Purpose |
|----------|---------|
| **sensor** | Miner telemetry, health and anomaly scores, energy, efficiency, and data quality |
| **binary_sensor** | Problems with hashrate, temperature, hashboards, fans, pools, and power |
| **event** | Miner activity, including connectivity changes, pool changes, and recovery actions |
| **switch** | Pause / resume mining (when supported) |
| **number** | Power limit (autotuning) |
| **select** | Power mode; pool priority (≥ 2 pools) |
| **button** | Reboot, linked power switch control, learned baseline controls, and recovery lock reset |

Starting with 1.7.2, the Uptime sensor is displayed as a duration and its updates are excluded from Activity. In templates, its state contains seconds instead of a string such as `1h 36m`; the `uptime_seconds` attribute remains available.

---

## Farm entities

| Platform | Entity | Description |
|----------|--------|-------------|
| **sensor** | Total hashrate | TH/s from online members |
| **sensor** | Total power | kW |
| **sensor** | Miners / online | Member count and reachability |
| **sensor** | Algorithms | Summary from online members; empty if none report an algorithm |
| **sensor** | Effective chips, % | Across online members |
| **sensor** | Room temperature | Linked ambient sensors |
| **sensor** | Farm health and efficiency | Overall score, unreachable or affected members, expected and lost hashrate, and average efficiency |
| **sensor** | Farm energy | Lifetime, today, this month, and previous month |
| **event** | Farm activity | Pool preset and emergency stop results |
| **sensor** | Electricity cost | When a tariff is configured (day, current and previous month, lifetime, and hourly cost at current draw) |
| **select** | Pool preset | Slot used by apply buttons |
| **button** | Apply primary pool | Preset → primary stratum on all members |
| **button** | Append backup pool | Preset → backup slot |
| **button** | Emergency stop | Locks automatic recovery and turns off linked switches |
| **button** | Clear emergency stop | Confirm by pressing twice within 30 seconds |

---

## Health, recovery, and energy

### Health and Repairs

Miner health uses available readings for hashrate, temperatures, fans, hashboards, pools, and reported errors. The integration learns a baseline for the current work mode as readings accumulate. Farm health accounts for unreachable members.

For a persistent issue, open **Settings → System → Repairs**. Actions depend on the issue. For example, a high-temperature Repair can open the threshold form, and a farm connectivity Repair can retry polling. Configure miner-specific delays in the miner options.

### Automatic recovery and emergency stop

Automatic recovery is off by default. It responds to sustained low hashrate by trying a miner reboot first. Power cycling requires a linked Home Assistant switch and separate opt-in.

Farm emergency stop locks automatic recovery for members and turns off linked switches. The lock survives reloads. Press the clear button twice within 30 seconds to remove the lock. Clearing the lock does not turn power on.

### Energy sources and the Energy Dashboard

In **Auto** mode, the integration prefers a physical energy meter, then power from the linked switch's device, then miner-reported power. You can also explicitly select a meter or power sensor. A physical meter uses the `energy` device class and Wh, kWh, or MWh. A power sensor uses the `power` device class and W, kW, or MW.

A farm can sum its members or use a shared meter under **Farm energy meter**. Add a cumulative kWh sensor to **Individual devices** in the Energy Dashboard. If you display the farm and its miners together, set the farm as the upstream device for its miners in the dashboard to avoid double counting. [Home Assistant energy documentation](https://www.home-assistant.io/docs/energy/individual-devices/)

### Date-effective tariffs and monthly summaries

In the farm options, open **Electricity tariff → New price from a date**. Enter the date and prices for the active tariff. The date starts at local midnight in Home Assistant. To apply settings immediately or change the tariff type, choose one of the three types in the menu. Saving a new rate for an existing date replaces that revision. Other dated rates remain in effect at their scheduled times.

A past date reprices the farm's cumulative meter history. The integration uses detailed records when available and falls back to consecutive hourly statistics. Consumption is prorated by time when a rate or zone changes between readings. The form rejects a correction when the history does not cover the date or the historical meter goes backwards. Dated changes use one currency. Before the first tariff revision, the calculation uses the rate that was configured when the schedule was created.

The adjustment updates the farm's cost sensors for today, this month, last month, and all time. The kWh values and previously recorded Home Assistant history are preserved.

Import the [monthly summary blueprint](https://github.com/msksrv/msksrv-ha-miner/blob/main/blueprints/automation/msksrv/farm_monthly_summary.yaml) to receive a notification on the first day of each month. Select the **Energy last month** and **Cost last month** sensors of the same farm. The notification is generated when both sensors contain data for the month that ended.

### Electricity cost sensors when upgrading to 1.7

Costs are calculated from recorded energy and the farm tariff. The upgrade disables existing legacy cost sensors by default. If your automations or dashboards use them, switch to the new entities or enable legacy sensors under **Farm energy meter**. Entities you disabled manually stay disabled.

---

## Automations

To find a `device_id`, open **Developer tools → Actions**, select `miner.reboot` and the miner, then switch to YAML mode. For `miner.set_farm_pool`, select the farm device.

### Reboot a miner

```yaml
action: miner.reboot
data:
  device_id:
    - YOUR_DEVICE_ID
```

### Set primary pool

```yaml
action: miner.set_pool
data:
  device_id:
    - YOUR_DEVICE_ID
  mode: manual
  host: pool.example.com
  port: 3333
  use_ssl: false
  username: account.worker1
```

### Farm-wide pool

In a worker name, `{ip}` expands to the miner IP and `{ip_last}` to the final IPv4 octet.

```yaml
action: miner.set_farm_pool
data:
  device_id:
    - FARM_DEVICE_ID
  mode: manual
  host: pool.example.com
  port: 443
  use_ssl: true
  username: user.{ip_last}
```

### Notify when a miner goes offline

Import the [alerts blueprint](https://github.com/msksrv/msksrv-ha-miner/blob/main/blueprints/automation/msksrv/miner_alerts.yaml) by URL under **Settings → Automations & scenes → Blueprints**. Select a miner when creating the automation. The blueprint creates Home Assistant notifications for loss of connectivity, overheating and recovery locks.

The integration publishes miner and farm activity to the Home Assistant event bus as `miner_event`. The `type` field identifies the event, and `scope` is `miner` or `farm`. The event card shows the specific problem, such as overheating. The `event.*` entity uses an `event_type` such as `problem_detected_temperature` for a new problem. The bus still uses `type: problem_detected` with `problem_type`. This example triggers after three consecutive failed miner polls.

```yaml
alias: Miner offline
triggers:
  - trigger: event
    event_type: miner_event
    event_data:
      scope: miner
      type: offline
      device_id: YOUR_DEVICE_ID
actions:
  - action: persistent_notification.create
    data:
      title: Miner offline
      message: Check the miner's power and network connection.
```

### Miner problem events

The event card names the problem. Open it for readings captured when the problem was reported, where available.

| Event | Meaning and details |
|---|---|
| Miner disconnected | Several consecutive polls failed. The details show how many. |
| Hashboard problem | A board is missing, has no hashrate, has too few working chips, or differs from the other boards in hashrate or temperature. The details show the slot and the relevant readings. |
| Low hashrate | Hashrate is below the expected level or dropped while power draw stayed high. The details show the reading and its reference or threshold, where available. |
| Overheating | A chip or board temperature reached its limit. The details show the readings and their limits. |
| Fan problem | A fan is below the speed limit or runs substantially slower than its peers. The details show its index, speed and limit or median. |
| Mining pool problem | The pool is unavailable, work requests fail, stale shares accumulate, or no share has been accepted recently. The details show pool status, failures and available share readings. |
| High share rejection rate | The rejection rate exceeded its threshold or rose above its baseline. The details show the rate and available counters. |
| Unusual power draw | Power draw left the range based on the learned baseline or the miner's power limit. The details show the reading and range. |
| Slow recovery after reboot | Hashrate did not return to its baseline in time. The details show current and baseline hashrate and the recovery percentage. |
| Automatic recovery failed | The configured attempts were exhausted. The details show reboot and power cycle counts and available hashrate readings. |
| Power could not be restored | The integration could not confirm that the linked switch turned back on. The details show the switch and failed attempt count. |

---

<a id="services"></a>

## Actions

| Action | Description |
|---------|-------------|
| **`miner.reboot`** | Reboot |
| **`miner.restart_backend`** | Restart mining process |
| **`miner.set_work_mode`** | `low` / `normal` / `high` |
| **`miner.set_pool`** | `existing` promotes a pool by zero-based index, `manual` replaces the primary pool, and `append` adds a backup |
| **`miner.set_farm_pool`** | `manual` or `append` for farm members. Provide a host and port |

**`miner.set_farm_pool`**: blocked when algorithms differ. On partial failure (offline miner, firmware reject), some members may already have the new pool — see [Farm](#farm).

Call `miner.set_pool` or `miner.set_farm_pool` for pool changes. The device action picker offers reboot, mining process restart, and work mode.

---

## Discovery

DHCP matches **lowercase hostnames** (`whatsminer*`, `antminer*`…) and known **MAC OUIs** (Bitmain `E0A509`, WhatsMiner `C41025` / `C80831`). For DHCP discovery, the integration makes up to three API probes with a six-second timeout per attempt. Manual scanning accepts IPv4 subnets of up to 1,024 addresses. The integration skips already configured devices.

---

## Requirements

- **Home Assistant** 2026.3.0 or later. Integration release 1.7.0 was tested on Core 2026.3.0 and 2026.11.0 with a Bitaxe emulator.
- **pyasic** `0.78.x` — installed by Home Assistant (`manifest.json`: `pyasic>=0.78.9,<0.79`).

If logs show **`Requirements for miner not found`**: verify Home Assistant can reach **PyPI** and that your Python version is supported. If the error persists, open an [issue](https://github.com/msksrv/msksrv-ha-miner/issues) with the full install log.

---

## Security

- Miner (RPC, web, SSH) and pool passwords are stored in Home Assistant configuration.
- Pool presets and passwords are included in **backups** — protect backups accordingly.
- Miner APIs are meant for the local network; do not expose them to the internet without need.

---

## Troubleshooting

| Symptom | Check |
|--------|--------|
| Miner unavailable | Ping, passwords, firewall, web UI from HA host |
| No farm cost sensors | Tariff under **Configure**; for zones — currency and positive prices in every zone |
| Bulk pool apply fails | Log lines `Farm stratum:` — offline, mixed algorithms, bad preset |
| DHCP never triggers | Check discovered integrations. If the miner is missing, scan its IPv4 subnet or enter the IP manually |
| pyasic install error | Network, proxy, Python; see [Requirements](#requirements) |

---

## Reporting bugs

[GitHub Issues](https://github.com/msksrv/msksrv-ha-miner/issues) — include:

1. Home Assistant version  
2. Integration version from Marketplace, HACS, or `custom_components/miner/manifest.json`
3. Miner model and firmware  
4. pyasic version (from setup log)  
5. Steps to reproduce and a relevant log excerpt. Remove passwords and pool credentials from the log.
6. From 1.7.1, you can attach the file from **Download diagnostics** in the miner or farm entry menu. It contains a limited set of state and telemetry fields and omits addresses, passwords and pool settings.

---

## Limitations

- Entities and controls depend on **pyasic** and firmware for your model.
- **Costs** are estimates based on the tariff and recorded energy. Polling gaps can reduce the energy counted when estimating from power.
- Power off/on drives a linked HA `switch` only, not miner-side shutdown APIs.

Supported hardware: [pyasic docs](https://pyasic.readthedocs.io/en/latest/miners/supported_types/).

---

## License

This project is **source-available**, not open source — see [`LICENSE`](LICENSE). Commercial use requires prior written permission ([Issues](https://github.com/msksrv/msksrv-ha-miner/issues)).

**Credits:** [pyasic](https://github.com/UpstreamData/pyasic); fork lineage from [hass-miner](https://github.com/Schnitzel/hass-miner) (Schnitzel, MIT).

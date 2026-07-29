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
- [Automations](#automations)
- [Services](#services)
- [Discovery](#discovery)
- [Requirements](#requirements)
- [Security](#security)
- [Troubleshooting](#troubleshooting)
- [Reporting bugs](#reporting-bugs)
- [Limitations](#limitations)
- [Screenshots](#screenshots)
- [License](#license)

---

## Features

| Area | Capabilities |
|------|----------------|
| **Discovery** | DHCP (hostname and MAC), subnet scan, manual IP |
| **Miner** | Hashrate, thermal, fans, pools, power limit, mining pause |
| **Farm** | Totals, emergency stop, bulk pool apply, single- or multi-zone tariff |
| **Automation** | Services and device actions for reboot, work mode, pools |

Poll interval: **10 seconds**. Unreachable miners show entities as **unavailable** (no fake zero readings).

---

## Installation

### HACS

1. **HACS → Integrations → Custom repositories** (if needed):  
   `https://github.com/msksrv/msksrv-ha-miner`, category **Integration**.
2. Install **MSKSRV ASIC Miner** and restart Home Assistant.

Or use the HACS button at the top of this README.

### Manual

Copy `custom_components/miner` to `config/custom_components/` and restart Home Assistant.

---

## Configuration

Common path: **Settings → Devices & services → Integrations → MSKSRV ASIC Miner**.

Below, **“Integrations”** means that screen; **“Configure”** is the action on the miner or farm **entry row** (not the device page).

### Add a miner

1. **Add integration** → **Scan**, **Manual**, or finish after DHCP discovery.
2. Enter **RPC / web / SSH** credentials if prompted.
3. Set a device name.

### Reconfigure

On a single-miner entry: **Reconfigure** (often under **⋯**) — IP, credentials, power range. Leave **password fields empty** to keep stored values.

### Miner options

**Configure** on the miner entry:

- **Power switch** — link a `switch` for power on/off buttons.
- **Stratum pool** — replace primary or append backup (host, port, SSL, worker). Confirmation is required before apply; the miner must be reachable.

---

## Farm

A **farm** groups existing miner devices into one virtual device.

1. **Add integration → Farm** → name and miner list.
2. **Configure** on the farm entry opens a menu:

| Item | Purpose |
|------|---------|
| **Farm members** | Miner device list |
| **Room temperature sensors** | `sensor` with `device_class: temperature` |
| **Pools and workers** | Up to five stratum presets |
| **Electricity tariff** | Single-rate or two-/three-zone TOU |
| **Mass actions** | Apply a preset to all members (with confirmation) |

Configure a **power switch** on each member (**Configure** on that miner’s entry) for emergency stop to work.

**Emergency stop** turns off linked power switches **one after another**. A failure on one switch does not stop the rest from being processed.

**Bulk pool apply** is blocked when members report **different algorithms**. The operation is **not transactional**: if one miner is offline or rejects the change, others may already have been updated.

Tariffs provide an **estimate** from current power draw, not meter billing (see [Limitations](#limitations)).

After you save farm options, the entry **reloads automatically**.

Preset pool passwords are not shown again in forms; an empty password field keeps the stored value.

---

## Miner entities

| Platform | Purpose |
|----------|---------|
| **sensor** | Hashrate, temperature, pool, power, diagnostics (IP, MAC, firmware…) |
| **switch** | Pause / resume mining (when supported) |
| **number** | Power limit (autotuning) |
| **select** | Power mode; pool priority (≥ 2 pools) |
| **button** | Reboot; **power on and off** via linked `switch` |

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
| **sensor** | Electricity cost | When a tariff is configured (hour, day, month, lifetime, at current draw) |
| **select** | Pool preset | Slot used by apply buttons |
| **button** | Apply primary pool | Preset → primary stratum on all members |
| **button** | Append backup pool | Preset → backup slot |
| **button** | Emergency stop | Sequential power-off |

---

## Automations

Use `device_id` from **Developer tools → Devices**.

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

Worker string may use `{ip}` or `{ip_last}`.

```yaml
action: miner.set_farm_pool
data:
  device_id:
    - FARM_DEVICE_ID
  mode: manual
  host: stratum.pool.com
  port: 443
  use_ssl: true
  username: user.{ip_last}
```

---

## Services

| Service | Description |
|---------|-------------|
| **`miner.reboot`** | Reboot |
| **`miner.restart_backend`** | Restart mining process |
| **`miner.set_work_mode`** | `low` / `normal` / `high` |
| **`miner.set_pool`** | Change primary or append backup pool |
| **`miner.set_farm_pool`** | Same for all farm members |

**`miner.set_farm_pool`**: blocked when algorithms differ. On partial failure (offline miner, firmware reject), some members may already have the new pool — see [Farm](#farm).

`set_pool` / `set_farm_pool` are services only, not device actions.

---

## Discovery

DHCP matches **lowercase hostnames** (`whatsminer*`, `antminer*`…) and known **MAC OUIs** (Bitmain `E0A509`, WhatsMiner `C41025` / `C80831`). The integration probes the API up to **3 times** (6 s timeout). Already configured miners are skipped by IP, MAC, and `unique_id`.

---

## Requirements

- **Home Assistant** ≥ **2026.3.0** (see `hacs.json`).
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
| DHCP never triggers | Hostname patterns in `manifest.json` are **lowercase** |
| pyasic install error | Network, proxy, Python; see [Requirements](#requirements) |

---

## Reporting bugs

[GitHub Issues](https://github.com/msksrv/msksrv-ha-miner/issues) — include:

1. Home Assistant version  
2. Integration version (integration **⋮ → System → Information**, or release tag)  
3. Miner model and firmware  
4. pyasic version (from setup log)  
5. Integration **diagnostics** (no secrets)  
6. Relevant log excerpt (no passwords or pool credentials unless necessary)

---

## Limitations

- Entities and controls depend on **pyasic** and firmware for your model.
- **Cost sensors** approximate spend from polled power draw; they do not replace utility metering. Missed polls and offline periods are not backfilled.
- Power off/on drives a linked HA `switch` only, not miner-side shutdown APIs.

Supported hardware: [pyasic docs](https://pyasic.readthedocs.io/en/latest/miners/supported_types/).

---

## Screenshots

UI screenshots (setup forms, farm menu, device card) live in [`docs/images/`](docs/images/) when published, or in [release assets](https://github.com/msksrv/msksrv-ha-miner/releases).

---

## License

This project is **source-available**, not open source — see [`LICENSE`](LICENSE). Commercial use requires prior written permission ([Issues](https://github.com/msksrv/msksrv-ha-miner/issues)).

**Credits:** [pyasic](https://github.com/UpstreamData/pyasic); fork lineage from [hass-miner](https://github.com/Schnitzel/hass-miner) (Schnitzel, MIT).

# MSKSRV ASIC Miner

[![GitHub Release](https://img.shields.io/github/v/release/msksrv/msksrv-ha-miner?style=for-the-badge)](https://github.com/msksrv/msksrv-ha-miner/releases)
[![License](https://img.shields.io/github/license/msksrv/msksrv-ha-miner?style=for-the-badge)](LICENSE)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)

**Home Assistant** integration for monitoring and controlling **ASIC Bitcoin miners** on your LAN. Built on [**pyasic**](https://github.com/UpstreamData/pyasic); one **config entry** per miner (IP), with optional credentials and a linked **smart switch** for hard power-off.

---

[![Open your Home Assistant instance and open the repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=msksrv&repository=msksrv-ha-miner&category=integration)

*Adds this repo to HACS so you can install **MSKSRV ASIC Miner** without copying the URL by hand.*

---

## Contents

- [Features](#features)
- [Installation](#installation)
- [Configuration](#configuration)
- [Entities](#entities)
- [Services](#services)
- [Device actions](#device-actions)
- [Discovery](#discovery)
- [Requirements](#requirements)
- [Limitations](#limitations)
- [Credits](#credits)

---

## Features

### Setup & discovery

| Capability | Description |
|------------|-------------|
| **DHCP discovery** | Miners are suggested when their hostname matches known patterns (see [Discovery](#discovery)). |
| **Subnet scan** | Scan an IPv4 subnet (CIDR) with progress UI; pick a discovered host. Subnet size is capped for safety. |
| **Manual IP** | Add a miner by address. |
| **Credentials** | Optional RPC, web UI, and SSH credentials when the miner exposes those APIs. |
| **Power switch (options)** | Link an existing Home Assistant **`switch`** (e.g. smart plug). The **Power off** button calls `switch.turn_off` on it. |

### Monitoring (sensors)

Poll interval is **10 seconds** (`local_polling`). Typical data includes:

- **Performance** — hashrate, ideal hashrate, active preset name (when available), efficiency (J/TH)
- **Power** — consumption, power limit (read-only mirror on sensors where applicable)
- **Thermal** — average temperature; **per-board** board temp, chip temp, hashrate
- **Chips** — per-board chip counts, expected chips, effective chips, effective %
- **Fans** — RPM per fan
- **Pool** — primary pool host/port, accepted/rejected shares, reject rate
- **Device** — model, firmware, uptime (formatted), board count, IP, MAC

When the miner is temporarily unreachable, the integration keeps entities alive with **degraded / zeroed** data on the first failure, then marks the device unavailable on repeated failures.

### Control (platforms)

| Platform | What it does | When it appears |
|----------|----------------|-----------------|
| **`switch`** | **Active** — pause / resume mining (`stop_mining` / `resume_mining`). | Miner reports `supports_shutdown`. |
| **`number`** | **Power limit** (watts, stepped). | Miner reports `supports_autotuning`. |
| **`select`** | **Power mode** — Low / Normal / High. | Power modes supported **and** autotuning **not** used (same rule as upstream pyasic usage). |
| **`select`** | **Pool priority** — reorder configured pool slots so the chosen entry becomes primary. | At least **two** pools in the primary pool group in miner config. |
| **`button`** | **Reboot** — device reboot via pyasic. | Always (per miner). |
| **`button`** | **Power off** — `switch.turn_off` on the switch chosen in **integration options**. | Always listed; **available** only if a valid `switch` entity is configured and present in the state machine. |

### Automation

- **Services** — reboot, restart mining backend, set work mode, set pool (see [Services](#services)).
- **Device actions** — reboot, restart backend, set work mode from the device automation UI (see [Device actions](#device-actions)).

---

## Installation

### HACS (recommended)

1. Open **HACS → Integrations**.
2. Use **Custom repositories** only if the repo is not already listed, then add  
   `https://github.com/msksrv/msksrv-ha-miner` as category **Integration**.
3. Or use the **“Open repository in HACS”** button at the top of this README.
4. Install **MSKSRV ASIC Miner** and **restart Home Assistant**.

### Manual

Copy the `custom_components/miner` folder into your Home Assistant  
`config/custom_components/` directory, then restart.

---

## Configuration

1. **Settings → Devices & services → Add integration → MSKSRV ASIC Miner.**
2. Choose **Scan**, **Manual**, or complete flow from **DHCP discovery**.
3. Enter optional **RPC / Web / SSH** credentials if prompted.
4. Set the **device name** (area / dashboard friendly).

### Integration options (power switch)

Open **Settings → Devices & services → Integrations** (not the “Devices” tab). Find **MSKSRV ASIC Miner**, open the **entry for this miner** (one tile per IP), then **Configure**.

You should see **Power switch** — an entity picker limited to **`switch`** domains. **Power off** stays unavailable until you save a valid switch (or if that entity is removed from HA).

To clear the link, remove the selection in that field and submit again.

---

## Entities

### Sensors (examples)

Naming follows `{device title} …`; board/fan indices depend on hardware.

| Area | Examples |
|------|-----------|
| Miner | Hashrate, ideal hashrate, active preset, temperature, power limit, consumption, efficiency |
| Diagnostics | IP, MAC, ASIC model, firmware, uptime, boards count |
| Pool | Pool host, pool port, accepted/rejected shares, reject rate |
| Per board | Board temperature, chip temperature, board hashrate, chips / expected / effective / % |
| Per fan | Fan speed (RPM) |

### Other platforms

- **`switch.*_active`** — mining on/off where supported.
- **`number.*_power_limit`** — autotuning wattage cap where supported.
- **`select.*_power_mode`** — Low / Normal / High where supported.
- **`select.*_pool_priority`** — pick primary pool among configured slots (≥2 pools).
- **`button.*_reboot`** — software reboot.
- **`button.*_power_off`** — turn off linked smart switch (`switch.turn_off`).

---

## Services

All services accept **`device_id`** (Home Assistant device ID). Most support **multiple** miners in one call.

| Service | Description |
|---------|-------------|
| **`miner.reboot`** | Reboot the miner. |
| **`miner.restart_backend`** | Restart the mining process on the device. |
| **`miner.set_work_mode`** | `mode`: `low` \| `normal` \| `high`. |
| **`miner.set_pool`** | **Existing** — `pool_index` (0-based) becomes primary (reorder). **Manual** — set `host`, `port`, optional `use_ssl`, `username`, `password` on the primary slot. |

Use **Developer tools → Actions** or YAML automations. Pool behaviour depends on **firmware / model** and pyasic support for `get_config` / `send_config`.

---

## Device actions

For automations tied to a **device** (not raw entity IDs), the integration exposes:

- Reboot  
- Restart mining backend  
- Set work mode (with mode)

`set_pool` is **not** exposed as a device action; use the **`miner.set_pool`** service.

---

## Discovery

DHCP-based discovery matches hostnames such as **Antminer**, **WhatsMiner**, **Avalon**, **Innosilicon**, **Goldshell**, **Auradine**, **BitAxe**, **IceRiver**, **Hammer** (case variants), plus **registered_devices** flows where applicable.

---

## Requirements

- **Home Assistant** ≥ **2025.1.0** (see `hacs.json`).
- **Python dependency**: **pyasic** version pinned in [`manifest.json`](custom_components/miner/manifest.json) (installed automatically).

---

## Limitations

- **Not every feature exists on every miner** — switches, power modes, autotuning, pool config, and sensors depend on the driver in pyasic and on firmware.
- **Pool changes** — use **Pool priority** when multiple pools are configured; arbitrary URLs need **`miner.set_pool`** in manual mode.
- **Power off** — only switches a **linked HA `switch`**; it does not replace miner-side shutdown APIs.

Supported device families in pyasic:

https://pyasic.readthedocs.io/en/latest/miners/supported_types/

---

## Credits

- **[pyasic](https://github.com/UpstreamData/pyasic)** — miner communication layer.
- Fork / evolution of ideas from **[hass-miner](https://github.com/Schnitzel/hass-miner)** (Schnitzel).

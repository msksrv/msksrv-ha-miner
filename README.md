# MSKSRV ASIC Miner

[![GitHub Release](https://img.shields.io/github/v/release/msksrv/msksrv-ha-miner?style=for-the-badge)](https://github.com/msksrv/msksrv-ha-miner/releases)
[![License: Non-Commercial](https://img.shields.io/badge/License-Non--Commercial-red?style=for-the-badge)](LICENSE)
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
- [Farm device](#farm-device)
- [Entities](#entities)
- [Services](#services)
- [Device actions](#device-actions)
- [Discovery](#discovery)
- [Requirements](#requirements)
- [Limitations](#limitations)
- [Releases (beta & stable)](#releases-beta--stable)
- [License](#license)
- [Credits](#credits)

---

## Features

### Setup & discovery

| Capability | Description |
|------------|-------------|
| **DHCP discovery** | Home Assistant matches **lowercase DHCP hostname** globs (`whatsminer*`, `antminer*`, …) and/or known **MAC OUIs**; then the integration probes the miner API with limited retries (see [Discovery](#discovery)). |
| **Subnet scan** | Scan an IPv4 subnet (CIDR) with progress UI; pick a discovered host. Subnet size is capped for safety. |
| **Manual IP** | Add a miner by address. |
| **Farm** | Second-level device: select existing **miner** devices → **total hashrate (TH/s)**, **total power (kW)**, **miner count / online**, **algorithm** (SHA256d), **Emergency stop** (calls `switch.turn_off` on each member’s **power switch** from integration options). |
| **Credentials** | Optional RPC, web UI, and SSH credentials when the miner exposes those APIs. |
| **Power switch & pool (options)** | Link a **`switch`** for plug control (**Power off** / **Power on**). Optionally **replace primary stratum** or **append a backup pool** (host, port, SSL, worker) when the miner is online. |

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
2. Choose **Scan**, **Manual**, **Farm** (aggregate), or complete flow from **DHCP discovery**.
3. Enter optional **RPC / Web / SSH** credentials if prompted.
4. Set the **device name** (area / dashboard friendly).

### Integration options (power + stratum)

Open **Settings → Devices & services → Integrations** (not the “Devices” tab). Find **MSKSRV ASIC Miner**, open the **entry for this miner** (one tile per IP), then **Configure**.

- **Power switch** — picker limited to **`switch`**. **Power off** / **Power on** stay unavailable until you save a valid switch (or if that entity is removed). Clear the field and submit to unlink.
- **Stratum pool** — choose **do nothing**, **set primary pool**, or **add backup pool**, then fill **host**, **port**, optional **SSL** and **worker** credentials. The miner must be **reachable** when you submit; up to **3** pools in the primary group (append fails if full).

Pool fields are applied **only when you submit** this form; they are not stored as long-lived options (only the power switch entity id is saved).

### Farm device {#farm-device}

Add **Farm** from the same integration menu, enter a **name**, and multi-select **miner devices** (only entries created as single miners, not other farms).  
**Emergency stop** is **available** only if at least one member has a **power switch** configured under **Configure** and that `switch` exists in HA. It sends **`switch.turn_off`** to **all** such switches (parallel, non-blocking).

To **add or remove miners** on an existing farm, open **Configure** on the **farm** integration entry, update **Miner devices** (multi-select), and save. Finish setting up any **new** miner as its own integration entry first so it appears in the picker.

**Configure** also links **room temperature** sensors: pick one or more **`sensor`** entities (e.g. ZigBee probes). Each appears on the farm device as a temperature sensor whose **name matches the source entity’s friendly name** (and unit follows the source). Saving reloads the entry.

Farm sensors include **total hashrate / power**, **miner count / online**, **algorithm summary** (from pyasic per miner; if miners differ, shown as e.g. `SHA256d (3), Scrypt (1)`; if none report an algorithm, **SHA256d** is assumed as label only), **effective chips %** (sum of working chips vs expected chips across **online** members’ hashboards), and any linked **ambient temperature** sensors.

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
- **`button.*_power_off`** / **`button.*_power_on`** — `switch.turn_off` / `switch.turn_on` on the linked switch.

---

## Services

All services accept **`device_id`** (Home Assistant device ID). Most support **multiple** miners in one call.

| Service | Description |
|---------|-------------|
| **`miner.reboot`** | Reboot the miner. |
| **`miner.restart_backend`** | Restart the mining process on the device. |
| **`miner.set_work_mode`** | `mode`: `low` \| `normal` \| `high`. |
| **`miner.set_pool`** | **Existing** — `pool_index` (0-based) becomes primary (reorder). **Manual** — set primary slot `host` / `port` / optional `use_ssl`, `username`, `password`. **Append** — add a backup slot (same fields; max 3 pools). |

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

DHCP uses **both** paths (as in v1.2.x): **hostname** globs in **lowercase** only — Home Assistant lowercases the DHCP name before `fnmatch`, so e.g. `WhatsMiner` → `whatsminer*` (patterns like `WhatsMiner*` would **not** match). Plus **MAC OUI** prefixes (**Bitmain** `E0A509`, **WhatsMiner-class** `C41025` / `C80831`) for devices with empty or generic hostnames, and **`registered_devices`** when that MAC is already in the device registry.

When a device matches, the integration calls the miner API **up to 3 times** (6 s timeout each, **2 s / 5 s** pause between tries). If the API still does not answer, a discoverable flow opens with the IP **pre-filled** for manual finish. **Already configured** miners are skipped by **IP**, **device-registry MAC**, and **`unique_id`** (non-farm entries only). Add more `hostname` / `macaddress` rows in `manifest.json` → `dhcp` if needed.

---

## Requirements

- **Home Assistant** ≥ **2025.1.0** (see `hacs.json`).
- **Python dependency**: **pyasic** `0.78.x` (range in [`manifest.json`](custom_components/miner/manifest.json); installed automatically by Home Assistant).

If setup logs **`Requirements for miner not found`** for pyasic: the host must reach **PyPI** (or your proxy). On very new HA builds (**Python 3.14**), some wheels may lag; updating Home Assistant or retrying after a day often fixes it. The manifest allows **`pyasic>=0.78.9,<0.79`** so pip can pick a build that installs cleanly.

The integration loads **pyasic only when needed** (single-miner setup, scan, services, etc.). **Farm** setup and the config-flow menu should work even if pyasic failed to install until then — fix pyasic first so **per-IP miners** load again.

---

## Releases (beta & stable)

Farm and other work-in-progress builds ship as **semantic pre-releases** (e.g. **`1.4.0b7`** in `manifest.json`). On GitHub they should be published as **Pre-release** — they still appear on the [Releases](https://github.com/msksrv/msksrv-ha-miner/releases) page and get **`miner.zip`**; only the “latest” badge skips them until you ship a stable tag.

### Automatic (recommended)

Push a tag **`v1.4.0b7`** or **`v1.4.0`**:

1. **Create release from tag** runs → opens a GitHub **Release** for that tag. Betas (`bN`, `aN`, `rc`, `beta` in the version) are marked **Pre-release** automatically; pure **`X.Y.Z`** tags are **full** releases.
2. **Release** runs on publish → writes `manifest.json` **`version`** without the leading **`v`**, zips `custom_components/miner`, uploads **`miner.zip`** to the same release.

### Manual

You can still create a release in the GitHub UI: pick the tag, turn on **Set as a pre-release** for betas, then **Publish** — the ZIP workflow runs the same way.

---

## Limitations

- **Not every feature exists on every miner** — switches, power modes, autotuning, pool config, and sensors depend on the driver in pyasic and on firmware.
- **Pool changes** — use **Pool priority** when multiple pools are configured; arbitrary URLs need **`miner.set_pool`** in manual mode.
- **Power off / on** — only drive a **linked HA `switch`**; they do not replace miner-side shutdown APIs.

Supported device families in pyasic:

https://pyasic.readthedocs.io/en/latest/miners/supported_types/

---

## License

This project is licensed for **non-commercial use only** — see [`LICENSE`](LICENSE). Commercial use requires **prior written permission** from the copyright holders.

---

## Credits

- **[pyasic](https://github.com/UpstreamData/pyasic)** — miner communication layer.
- Fork / evolution of ideas from **[hass-miner](https://github.com/Schnitzel/hass-miner)** (Schnitzel).

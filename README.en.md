# MSKSRV ASIC Miner — Home Assistant integration for ASIC miners

**Language:** [Русский](README.md) · **English**

**MSKSRV ASIC Miner** is a **[Home Assistant](https://www.home-assistant.io/)** custom integration for **local monitoring and control of ASIC Bitcoin miners** (Antminer, WhatsMiner, Avalon, Innosilicon, Goldshell, IceRiver, BitAxe, and others supported by [**pyasic**](https://github.com/UpstreamData/pyasic)). Install via **[HACS](https://www.hacs.xyz/)** or manually; one **config entry per miner IP**, optional **RPC / web / SSH** credentials, **stratum pool** tools, and an optional **farm** device that aggregates hashrate, power, and **bulk pool apply** across many miners.

[![GitHub Release](https://img.shields.io/github/v/release/msksrv/msksrv-ha-miner?style=for-the-badge)](https://github.com/msksrv/msksrv-ha-miner/releases)
[![License: Non-Commercial](https://img.shields.io/badge/License-Non--Commercial-red?style=for-the-badge)](LICENSE)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)

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
- [Automation examples (YAML)](#automation-examples-yaml)
- [Services](#services)
- [Device actions](#device-actions)
- [Discovery](#discovery)
- [Requirements](#requirements)
- [Troubleshooting](#troubleshooting)
- [Limitations](#limitations)
- [Releases](#releases)
- [License](#license)
- [Credits](#credits)

**Search keywords:** Home Assistant miner, HACS ASIC integration, Bitcoin miner dashboard, Antminer Home Assistant, WhatsMiner sensor, hashrate sensor, stratum pool automation, mining farm Home Assistant, pyasic.

---

## Features {#features}

### Setup & discovery

| Capability | Description |
|------------|-------------|
| **DHCP discovery** | Home Assistant matches **lowercase DHCP hostname** globs (`whatsminer*`, `antminer*`, …) and/or known **MAC OUIs**; then the integration probes the miner API with limited retries (see [Discovery](#discovery)). |
| **Subnet scan** | Scan an IPv4 subnet (CIDR) with progress UI; pick a discovered host. Subnet size is capped for safety. |
| **Manual IP** | Add a miner by address. |
| **Farm** | Second-level device: select existing **miner** devices → **total hashrate (TH/s)**, **total power (kW)**, **miner count / online**, **algorithm** summary, **Emergency stop** (calls `switch.turn_off` on each member’s **power switch** set via **⚙️ Configure** on **that member’s** integration tile). **⚙️ Configure** on the **farm** tile can apply the **same stratum primary or backup** to every member when they share one reported algorithm. |
| **Credentials** | Optional RPC, web UI, and SSH credentials when the miner exposes those APIs. |
| **Power switch & pool (options)** | In **⚙️ Configure** on the miner tile: link a **`switch`** for plug control (**Power off** / **Power on**), and optionally **replace primary stratum** or **append a backup pool** (host, port, SSL, worker) when the miner is online. |

### Monitoring (sensors)

Poll interval is **10 seconds** (`local_polling`). Typical data includes:

- **Performance** — hashrate, ideal hashrate, active preset name (when available), efficiency (J/TH)
- **Power** — consumption, power limit (read-only mirror on sensors where applicable)
- **Thermal** — average temperature; **per-board** board temp, chip temp, hashrate
- **Chips** — per-board chip counts, expected chips, effective chips, effective %
- **Fans** — RPM per fan
- **Pool** — primary pool host/port, **pool worker** (stratum user from the active or first pool slot), accepted/rejected shares, reject rate
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
| **`button`** | **Power off** — `switch.turn_off` on the switch chosen via **⚙️ Configure** on the miner tile. | Always listed; **available** only if a valid `switch` entity is configured and present in the state machine. |
| **`select`** | **Farm: preset to apply** — picks which saved stratum slot is used by the farm’s apply buttons. | **Farm** device only; at least one configured preset. |
| **`button`** | **Farm: apply preset as primary / backup** — same logic as bulk stratum via **⚙️ Configure** on the **farm** tile; uses the select above. | **Farm** device; requires presets. |

### Automation

- **Services** — reboot, restart mining backend, set work mode, set pool, set farm pool (see [Services](#services)).
- **Device actions** — reboot, restart backend, set work mode from the device automation UI (see [Device actions](#device-actions)).
- **YAML examples** — [Automation examples (YAML)](#automation-examples-yaml).

---

## Installation {#installation}

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

## Configuration {#configuration}

### Home Assistant UI icons

These match what you see in the HA sidebar and on integration cards:

| Icon | Where to click |
|:----:|----------------|
| ⚙️ | **Settings** (global) — **cog** in the sidebar (often bottom-left). Not the same as **⚙️ Configure** on an integration row (below). |
| 🔌 | **Devices & services** — inside Settings. |
| 🧩 | **Integrations** tab under Devices & services — **not** the “Devices” tab. |
| ➕ | **Add integration** on the Integrations screen. |
| **⚙️ Configure** | On the **MSKSRV ASIC Miner** row under **🧩 Integrations** (one line per IP or **farm**): **Configure** or a **cog** on the row (sometimes via the **⋯** menu). Opens **integration options** — **not** the device page on the “Devices” tab. |
| 👤 | **Profile** (avatar / initials) — **sidebar** customization lives here. |
| 🛠️ | **Developer tools** — **Devices** tab (for `device_id`), **Actions** tab (call services). |

1. **⚙️ Settings → 🔌 Devices & services → 🧩 Integrations → ➕ Add integration → MSKSRV ASIC Miner.**
2. Choose **Scan**, **Manual**, **Farm** (aggregate), or complete flow from **DHCP discovery**.
3. Enter optional **RPC / Web / SSH** credentials if prompted.
4. Set the **device name** (area / dashboard friendly).

### Integration options (power + stratum)

**⚙️ Settings → 🔌 Devices & services → 🧩 Integrations** (this is **not** the “Devices” tab). Find **MSKSRV ASIC Miner**, select the **entry for this miner** (one row per IP), then **⚙️ Configure**.

- **Power switch** — picker limited to **`switch`**. **Power off** / **Power on** stay unavailable until you save a valid switch (or if that entity is removed). Clear the field and submit to unlink.
- **Stratum pool** — choose **do nothing**, **set primary pool**, or **add backup pool**, then fill **host**, **port**, optional **SSL** and **worker** credentials. The miner must be **reachable** when you submit; up to **3** pools in the primary group (append fails if full).

Pool fields are applied **only when you submit** this form; they are not stored as long-lived options (only the power switch entity id is saved).

### Sidebar & dashboards

Use Home Assistant’s **built-in** tools: **👤 Profile** → **sidebar** visibility/order, and/or create a **Lovelace** view with miner cards and enable **Show in sidebar** on that dashboard. This integration does **not** register its own sidebar panel (avoids duplicate menu entries).

### Farm device {#farm-device}

Add **Farm** from the same integration menu, enter a **name**, and multi-select **miner devices** (only entries created as single miners, not other farms).  
**Emergency stop** is **available** only if at least one member has a **power switch** set via **⚙️ Configure** on **that member’s** miner tile and that `switch` exists in HA. It sends **`switch.turn_off`** to **all** such switches (parallel, non-blocking).

To **add or remove miners** on an existing farm, open **⚙️ Configure** on the **farm** integration tile (under **🧩 Integrations**), update **Miner devices** (multi-select), and save. Finish setting up any **new** miner as its own integration entry first so it appears in the picker.

**⚙️ Configure** on the **farm** tile also links **room temperature** sensors: pick one or more **`sensor`** entities (e.g. ZigBee probes). Each appears on the farm device as a temperature sensor whose **name matches the source entity’s friendly name** (and unit follows the source). Saving reloads the entry.

**Stratum (all members)** — up to **five** preset slots per **farm integration entry** (each farm has its **own** list in that entry’s options — independent of other farms). Each slot has host, port, SSL, worker, password. **Clear a slot’s host** (and port) and save to **remove** that preset. Bulk apply from **⚙️ Configure** on the **farm** tile uses the **“which slot (1–5)”** selector plus **replace primary** / **append backup**; behaviour matches **`miner.set_pool`**. **Every** linked miner must accept the change or the form errors. Bulk apply is **blocked** if members report **more than one algorithm** (last successful poll).

- **Worker** — per slot, same rules as before: shared string or **`{ip}`** / **`{ip_last}`** templates (farm-only). Many **Bitcoin-style** pools use `subaccount.workername`; follow your pool’s docs for other coins.
- **Dashboard** — on the **farm** **device page** (“Devices” tab): **Preset to apply** (select) and **Apply preset as primary pool** / **… as backup pool** (buttons) — **without** **⚙️ Configure** under Integrations. Buttons log an error if apply fails (e.g. mixed algorithms, offline miner).
- **Secrets** — presets live in HA **config storage** with the farm entry; include them in your **backup** threat model.

Farm sensors include **total hashrate / power**, **miner count / online**, **algorithm summary** (from pyasic per miner; if miners differ, shown as e.g. `SHA256d (3), Scrypt (1)`; if none report an algorithm, **SHA256d** is assumed as label only), **effective chips %** (sum of working chips vs expected chips across **online** members’ hashboards), and any linked **ambient temperature** sensors.

---

## Entities {#entities}

### Sensors (examples)

Naming follows `{device title} …`; board/fan indices depend on hardware.

| Area | Examples |
|------|-----------|
| Miner | Hashrate, ideal hashrate, active preset, temperature, power limit, consumption, efficiency |
| Diagnostics | IP, MAC, ASIC model, firmware, uptime, boards count |
| Pool | Pool host, pool port, **pool worker** (stratum user), accepted/rejected shares, reject rate |
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

## Automation examples (YAML) {#automation-examples-yaml}

Replace `device_id` values with IDs from **🛠️ Developer tools → Devices** (or use the UI automation editor’s device selector — it fills the correct id).

### Reboot one miner when a helper turns on

```yaml
automation:
  - alias: "Reboot miner from helper"
    triggers:
      - trigger: state
        entity_id: input_boolean.reboot_miner_now
        to: "on"
    actions:
      - action: miner.reboot
        data:
          device_id:
            - abc123yourDeviceIdHere
      - action: input_boolean.turn_off
        target:
          entity_id: input_boolean.reboot_miner_now
```

### Set primary stratum pool (manual mode)

```yaml
automation:
  - alias: "Point miner at new primary pool"
    triggers:
      - trigger: time
        at: "04:00:00"
    actions:
      - action: miner.set_pool
        data:
          device_id:
            - abc123yourDeviceIdHere
          mode: manual
          host: "pool.example.com"
          port: 3333
          use_ssl: false
          username: "account.worker1"
          password: "optional_pool_password"
```

### Farm: same pool on all linked miners

Worker string can use **`{ip}`** or **`{ip_last}`** per miner (e.g. `mypool.{ip_last}`).

```yaml
automation:
  - alias: "Farm pool switch"
    triggers:
      - trigger: state
        entity_id: input_select.farm_pool_choice
    actions:
      - action: miner.set_farm_pool
        data:
          device_id:
            - farmDeviceIdHere
          mode: manual
          host: "stratum.pool.com"
          port: 443
          use_ssl: true
          username: "user.{ip_last}"
          password: ""
```

### Alert when hashrate drops (example pattern)

```yaml
automation:
  - alias: "Low hashrate warning"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.my_miner_hashrate
        below: 50
        for: "00:10:00"
    actions:
      - action: notify.persistent_notification
        data:
          title: "Miner hashrate low"
          message: "Check {{ state_attr('sensor.my_miner_hashrate', 'friendly_name') }}"
```

---

## Services {#services}

All services accept **`device_id`** (Home Assistant device ID). Miner services support **multiple** miners in one call; **`miner.set_farm_pool`** targets **farm** devices (one or more).

| Service | Description |
|---------|-------------|
| **`miner.reboot`** | Reboot the miner. |
| **`miner.restart_backend`** | Restart the mining process on the device. |
| **`miner.set_work_mode`** | `mode`: `low` \| `normal` \| `high`. |
| **`miner.set_pool`** | **Existing** — `pool_index` (0-based) becomes primary (reorder). **Manual** — set primary slot `host` / `port` / optional `use_ssl`, `username`, `password`. **Append** — add a backup slot (same fields; max 3 pools). |
| **`miner.set_farm_pool`** | **`device_id`**: farm aggregate device(s). **`mode`**: `manual` (replace primary on every member) or `append` (backup slot). Same **`host` / `port` / `use_ssl` / `username` / `password`** as `set_pool`. **No-op with error log** if members report **different algorithms** or a miner is unreachable / rejects the change. |

Use **🛠️ Developer tools → Actions** or YAML automations. Pool behaviour depends on **firmware / model** and pyasic support for `get_config` / `send_config`.

---

## Device actions {#device-actions}

For automations tied to a **device** (not raw entity IDs), the integration exposes:

- Reboot  
- Restart mining backend  
- Set work mode (with mode)

`set_pool` and **`set_farm_pool`** are **not** exposed as device actions; call **`miner.set_pool`** or **`miner.set_farm_pool`** from automations.

---

## Discovery {#discovery}

DHCP uses **both** paths (as in v1.2.x): **hostname** globs in **lowercase** only — Home Assistant lowercases the DHCP name before `fnmatch`, so e.g. `WhatsMiner` → `whatsminer*` (patterns like `WhatsMiner*` would **not** match). Plus **MAC OUI** prefixes (**Bitmain** `E0A509`, **WhatsMiner-class** `C41025` / `C80831`) for devices with empty or generic hostnames, and **`registered_devices`** when that MAC is already in the device registry.

When a device matches, the integration calls the miner API **up to 3 times** (6 s timeout each, **2 s / 5 s** pause between tries). If the API still does not answer, a discoverable flow opens with the IP **pre-filled** for manual finish. **Already configured** miners are skipped by **IP**, **device-registry MAC**, and **`unique_id`** (non-farm entries only). Add more `hostname` / `macaddress` rows in `manifest.json` → `dhcp` if needed.

---

## Requirements {#requirements}

- **Home Assistant** ≥ **2025.1.0** (see `hacs.json`).
- **Python dependency**: **pyasic** `0.78.x` (range in [`manifest.json`](custom_components/miner/manifest.json); installed automatically by Home Assistant).

If setup logs **`Requirements for miner not found`** for pyasic: the host must reach **PyPI** (or your proxy). On very new HA builds (**Python 3.14**), some wheels may lag; updating Home Assistant or retrying after a day often fixes it. The manifest allows **`pyasic>=0.78.9,<0.79`** so pip can pick a build that installs cleanly.

The integration loads **pyasic only when needed** (single-miner setup, scan, services, etc.). **Farm** setup and the config-flow menu should work even if pyasic failed to install until then — fix pyasic first so **per-IP miners** load again.

---

## Troubleshooting {#troubleshooting}

| Symptom | What to check |
|--------|----------------|
| **Miner unavailable** | Ping IP; RPC/web passwords; firewall; miner web UI reachable from HA host. |
| **No pool worker sensor value** | Firmware/API may omit stratum user in pool stats; primary/active pool is used when reported. |
| **Farm pool apply fails for one member** | Logs show `Farm stratum:` — offline miner, mixed algorithms, or duplicate device entries on the farm (fix the device list via **⚙️ Configure** on the **farm** tile). |
| **DHCP discovery never starts** | Hostname patterns are **lowercase** in `manifest.json`; HA lowercases DHCP hostnames before match. |
| **Ghost sidebar item “MSKSRV…” after upgrade** | Older betas registered a custom panel; disable it under **👤 Profile → sidebar**, or restart HA after updating to **1.4.x**. |
| **PyPI / pyasic install errors** | Network, corporate proxy, Python version; see [Requirements](#requirements). |

**Issues & feature requests:** [GitHub Issues](https://github.com/msksrv/msksrv-ha-miner/issues).

---

## Limitations {#limitations}

- **Not every feature exists on every miner** — switches, power modes, autotuning, pool config, and sensors depend on the driver in pyasic and on firmware.
- **Pool changes** — use **Pool priority** when multiple pools are configured; arbitrary URLs need **`miner.set_pool`** in manual mode.
- **Power off / on** — only drive a **linked HA `switch`**; they do not replace miner-side shutdown APIs.

Supported device families in pyasic:

https://pyasic.readthedocs.io/en/latest/miners/supported_types/

---

## Releases {#releases}

**Current stable line: 1.4.x** — farm stratum improvements (deduplicated members, fallback when a coordinator is missing), **pool worker** sensor, config-flow fixes for DHCP “already configured”, and removal of the experimental custom sidebar panel (use HA’s own sidebar settings).

### Automatic release (GitHub Actions)

Push a version tag:

- **Stable:** `v1.4.0` → full **Release**, `miner.zip` attached, `manifest.json` version updated in the workflow to match the tag (without leading `v`).
- **Beta / RC:** `v1.5.0b1`, `v1.5.0rc1`, etc. → **Pre-release** (same ZIP workflow).

Workflows: **Create release from tag** (drafts the GitHub release) and **Release** (on publish: patch manifest version in the artifact, zip `custom_components/miner`, upload **`miner.zip`**).

### Manual

You can create a release in the GitHub UI: choose the tag, optionally **Set as a pre-release** for betas, then **Publish** — the ZIP workflow runs the same way.

---

## License {#license}

This project is licensed for **non-commercial use only** — see [`LICENSE`](LICENSE). Commercial use requires **prior written permission** from the copyright holders.

---

## Credits {#credits}

- **[pyasic](https://github.com/UpstreamData/pyasic)** — miner communication layer.
- Fork / evolution of ideas from **[hass-miner](https://github.com/Schnitzel/hass-miner)** (Schnitzel).

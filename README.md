# MSKSRV ASIC Miner

[![GitHub Release](https://img.shields.io/github/release/msksrv/msksrv-ha-miner.svg?style=for-the-badge)](https://github.com/msksrv/msksrv-ha-miner/releases)
[![License](https://img.shields.io/github/license/msksrv/msksrv-ha-miner.svg?style=for-the-badge)](LICENSE)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://hacs.xyz)

Advanced monitoring and control of **ASIC Bitcoin miners** directly from **Home Assistant**.

---

# What it does

## Discovery & setup

- **DHCP discovery** — automatic discovery of miners by hostname (Antminer, WhatsMiner, Avalon, Goldshell, etc.)
- **Network scan** — scan local subnet for miners with smart default subnet detection (hostname, outbound IP, prioritizes LAN ranges, deprioritizes Docker)
- **Manual setup** — add a miner by IP address
- **Credentials** — optional RPC, web, and SSH credentials for full control

## Monitoring

- **Hashrate** — current and ideal hashrate (TH/s)
- **Power** — consumption (W), power limit, efficiency (J/TH)
- **Temperature** — miner average, per-board, per-chip
- **Fans** — speed per fan (RPM)
- **Pool** — host, port, accepted/rejected shares, reject rate
- **Device info** — model, firmware, uptime, boards count, IP, MAC
- **Board diagnostics** — per-board temperature, chip temp, board hashrate

## Control

- **Power limit** — set wattage limit (number entity) where supported
- **Power mode** — select Low / Normal / High (select entity) where supported
- **Start/Stop mining** — switch to pause or resume mining where supported
- **Reboot** — service to reboot miner
- **Restart backend** — service to restart mining process
- **Set work mode** — service to set low/normal/high mode (device actions)

## Automation & services

- **Device actions** — reboot, restart_backend, set_work_mode for automations and scripts
- **Services** — `miner.reboot`, `miner.restart_backend`, `miner.set_work_mode` with device selector
- **Entities** — sensor, number, switch, select platforms for dashboards and triggers

## Use cases

- Heat reuse integration
- Solar mining and power management
- Automated power/load management
- Smart home mining integration
- Mining farm monitoring

---

# Supported miners

- Antminer
- WhatsMiner
- AvalonMiner
- Innosilicon
- Goldshell
- Auradine
- BitAxe
- IceRiver
- Hammer

---

# Supported firmware

- Braiins OS
- Vnish
- ePIC
- HiveOS
- LuxOS
- Mara Firmware

Full list of supported devices is provided by **pyasic**:

https://pyasic.readthedocs.io/en/latest/miners/supported_types/

---

# Features

### Monitoring

- Hashrate
- Ideal hashrate
- Power consumption
- Efficiency (J/TH)
- Temperature
- Fan speed
- Pool
- Accepted shares
- Rejected shares
- ASIC model
- Firmware version
- Uptime
- Boards count
- IP address
- MAC address

### Board diagnostics

- Board temperature
- Chip temperature
- Board hashrate

### Control

- Set miner power limit
- Turn miner on/off
- Reboot miner
- Restart mining backend

---

# Platforms

| Platform | Description |
|--------|-------------|
| `sensor` | Miner metrics (hashrate, power, temp, fans, pool, boards, etc.) |
| `number` | Power limit control (wattage) where autotuning is supported |
| `switch` | Start / stop mining where shutdown is supported |
| `select` | Power mode (Low / Normal / High) where power modes are supported |

---

# Services

| Service | Description |
|-------|-------------|
| `reboot` | Reboot miner |
| `restart_backend` | Restart mining process |
| `set_work_mode` | Set work mode (low, normal, high) |

---

# Installation

Install via **HACS**

1. Open **HACS**
2. Go to **Integrations**
3. Click **Custom repositories**
4. Add repository:
https://github.com/msksrv/msksrv-ha-miner
Category:Integration


5. Install **MSKSRV ASIC Miner**
6. Restart Home Assistant

---

# Credits

This integration uses the excellent **pyasic** library:

https://github.com/UpstreamData/pyasic

Based on the original project:

https://github.com/Schnitzel/hass-miner

# MSKSRV ASIC Miner

[![GitHub Release](https://img.shields.io/github/release/msksrv/msksrv-ha-miner.svg?style=for-the-badge)](https://github.com/msksrv/msksrv-ha-miner/releases)
[![License](https://img.shields.io/github/license/msksrv/msksrv-ha-miner.svg?style=for-the-badge)](LICENSE)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://hacs.xyz)

Advanced monitoring and control of **ASIC Bitcoin miners** directly from **Home Assistant**.

Perfect for:

- Heat reuse
- Solar mining
- Automated power management
- Smart home mining integration
- Mining farms monitoring

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
| `sensor` | Miner metrics |
| `number` | Power limit control |
| `switch` | Start / stop miner |

---

# Services

| Service | Description |
|-------|-------------|
| `reboot` | Reboot miner |
| `restart_backend` | Restart miner backend |

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

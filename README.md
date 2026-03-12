# MSKSRV ASIC Miner

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)

[![hacs][hacsbadge]][hacs]

Advanced monitoring and control of ASIC Bitcoin miners in Home Assistant.

Perfect for:

• Heat reuse  
• Solar mining  
• Automated mining control  
• Energy optimization

---

## Supported miners

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

## Supported firmware

- Braiins
- Vnish
- ePIC
- HiveOS
- LuxOS
- Mara

Full list of supported miners:

https://pyasic.readthedocs.io/en/latest/miners/supported_types/

---

# Features

• Automatic miner discovery  
• Hashrate monitoring  
• Power monitoring  
• Pool monitoring  
• Accepted / Rejected shares  
• Fan monitoring  
• Board diagnostics  
• Firmware information  

---

# Platforms

| Platform | Description |
|--------|-------------|
| sensor | Miner metrics |
| number | Power limit control |
| switch | Start / stop miner |

---

# Services

| Service | Description |
|-------|-------------|
| reboot | Reboot miner |
| restart_backend | Restart miner backend |

---

# Installation

Install via **HACS**

Add custom repository:

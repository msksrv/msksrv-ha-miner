# Brand images for `home-assistant/brands`

HACS and the Home Assistant UI load integration icons from **https://brands.home-assistant.io/**.  
Custom integrations are listed under **`custom_integrations/<domain>/`**.

This folder mirrors what you should add in a PR to **[home-assistant/brands](https://github.com/home-assistant/brands)**:

- `custom_integrations/miner/icon.png` — square icon (here 512×512)
- `custom_integrations/miner/logo.png` — logo for wider placements (same artwork here)

## Quick steps

1. Fork **https://github.com/home-assistant/brands**
2. Create branch from `master`, copy the contents of `custom_integrations/miner/` from this directory into the same path in the fork
3. Open a PR titled e.g. *Add brand images for miner custom integration (MSKSRV ASIC Miner)*  
   Follow [brands PR requirements](https://github.com/home-assistant/brands/blob/master/README.md)
4. After the PR is **merged**, wait for CDN cache (can be hours). Then HACS should show the icon instead of *Icon not available*.
5. Optional: in this repo, remove `ignore: brands` from `.github/workflows/hass-lint.yaml` so HACS Action validates brands too.

Or run **`scripts/submit_brands_pr.ps1`** from the repo root (after cloning `brands` it copies these files into the clone).

---

**RU:** Иконка в каталоге HACS не берётся из твоего репозитория — только с CDN брендов Home Assistant. Нужен **PR в `home-assistant/brands`** с файлами из этой папки; после мержа и обновления кэша иконка появится.

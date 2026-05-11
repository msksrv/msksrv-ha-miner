# Deprecated: no PR to `home-assistant/brands`

Home Assistant **no longer accepts** brand image PRs for custom integrations in [home-assistant/brands](https://github.com/home-assistant/brands). Since **Home Assistant 2026.3.0**, custom integrations ship icons in their own package.

**Announcement:** [Brands proxy API / custom integration brands](https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api)

## Where icons live in this integration

Use the files already in the repo:

- `custom_components/miner/brand/icon.png`
- `custom_components/miner/brand/logo.png`
- `custom_components/miner/icon.png` (legacy fallback)

After installation, Home Assistant serves them via `/api/brands/integration/miner/...`.

**HACS:** the store may still show a placeholder until HACS catches up with local brand resolution; the icon should appear in **Settings → Integrations** after the integration is installed (on HA **2026.3+**).

This folder previously held copies for a brands PR; those files were removed as unnecessary.

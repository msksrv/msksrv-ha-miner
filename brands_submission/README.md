# Submit these brand assets to Home Assistant for HACS icon

To show the **MSKSRV ASIC Miner** icon in the HACS store and in the HA integrations panel (when not using local brand folder), add them to the official brands repo.

## Steps

1. **Fork** [home-assistant/brands](https://github.com/home-assistant/brands).

2. **Clone your fork** and create a branch:
   ```bash
   git clone https://github.com/YOUR_USERNAME/brands.git
   cd brands
   git checkout -b add-miner-custom-integration
   ```

3. **Copy the miner brand folder** into the repo:
   ```bash
   cp -r brands_submission/custom_integrations/miner custom_integrations/
   ```
   Or on Windows (PowerShell):
   ```powershell
   Copy-Item -Recurse brands_submission\custom_integrations\miner custom_integrations\
   ```

4. **Commit and push** to your fork:
   ```bash
   git add custom_integrations/miner
   git commit -m "Add miner custom integration brand (MSKSRV ASIC Miner)"
   git push origin add-miner-custom-integration
   ```

5. **Open a Pull Request** on [home-assistant/brands](https://github.com/home-assistant/brands/compare) from your branch to `master`.  
   Title example: `Add miner custom integration brand (MSKSRV ASIC Miner)`.

## Requirements (from home-assistant/brands)

- `icon.png`: 256×256 px (or 512×512 for `icon@2x.png`).
- `logo.png`: shortest side 128–256 px (or 256–512 for `logo@2x.png`).
- PNG, transparent background preferred.

Once the PR is merged, HACS and the brands CDN will serve this icon for the `miner` integration.

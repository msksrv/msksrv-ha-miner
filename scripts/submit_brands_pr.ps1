# Submit MSKSRV Miner brand to home-assistant/brands for HACS icon.
# Run from repo root. Then add your fork, push, and open PR in browser.

$ErrorActionPreference = "Stop"
$git = "${env:ProgramFiles}\Git\cmd\git.exe"
if (-not (Test-Path $git)) { $git = "${env:ProgramFiles(x86)}\Git\cmd\git.exe" }
if (-not (Test-Path $git)) { Write-Error "Git not found"; exit 1 }

$root = Split-Path $PSScriptRoot -Parent
if (-not (Test-Path (Join-Path $root "brands_submission"))) {
    $root = Get-Location
}
$brandsDir = Join-Path $root "brands"
$submissionDir = Join-Path $root "brands_submission\custom_integrations\miner"

if (-not (Test-Path $submissionDir)) {
    Write-Error "Run from repo root. brands_submission not found."
    exit 1
}

# Clone if needed
if (-not (Test-Path $brandsDir)) {
    Write-Host "Cloning home-assistant/brands..."
    & $git clone --depth 1 https://github.com/home-assistant/brands.git $brandsDir
}
Push-Location $brandsDir
try {
    & $git fetch origin
    & $git checkout -B add-miner-custom-integration origin/master
    $target = Join-Path $brandsDir "custom_integrations\miner"
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    Copy-Item (Join-Path $submissionDir "*") $target -Force
    & $git add "custom_integrations/miner"
    & $git status
    & $git commit -m "Add miner custom integration brand (MSKSRV ASIC Miner)"
    Write-Host ""
    Write-Host "Done. Next steps:"
    Write-Host "  1. Fork https://github.com/home-assistant/brands (if not done)"
    Write-Host "  2. Add your fork: git remote add myfork https://github.com/YOUR_USERNAME/brands.git"
    Write-Host "  3. Push:          git push myfork add-miner-custom-integration"
    Write-Host "  4. Open PR:       https://github.com/home-assistant/brands/compare"
} finally {
    Pop-Location
}

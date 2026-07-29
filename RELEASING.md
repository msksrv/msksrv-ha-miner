# Releasing MSKSRV ASIC Miner

Instructions for maintainers. End users only need [Releases](https://github.com/msksrv/msksrv-ha-miner/releases) and HACS.

## Version

Set the same version in:

- `custom_components/miner/manifest.json` → `"version"`
- Git tag with `v` prefix (e.g. `v1.6.16`)

## Automatic release (GitHub Actions)

Push a version tag. The workflow [`.github/workflows/publish-tag-release.yml`](.github/workflows/publish-tag-release.yml) creates a GitHub Release and attaches `miner.zip`.

| Tag pattern | Release type |
|-------------|--------------|
| `v1.7.0`, `v1.6.16`, … | Stable release |
| `v1.7.0b1`, `v1.7.0rc1`, … | Pre-release |

```bash
git tag v1.6.16
git push origin v1.6.16
```

## Manual release

Create a release in the GitHub UI, select the tag, optionally mark **Pre-release**, publish. HACS uses the tagged tree; `miner.zip` is for manual installs.

## Repository rules

If tag push is rejected (protected refs), adjust [repository rules](https://github.com/msksrv/msksrv-ha-miner/rules) temporarily, update the tag, then restore protection.

## Commits

Avoid automated `Co-authored-by` trailers in published history. Use plain `git commit` or `git commit-tree` if your environment injects attribution trailers.

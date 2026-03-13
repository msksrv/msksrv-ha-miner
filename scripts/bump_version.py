"""Bump the version field in the Miner manifest.json.

Usage:
    python scripts/bump_version.py 1.2.3
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/bump_version.py <new_version>", file=sys.stderr)
        return 1

    new_version = sys.argv[1].strip()
    if not new_version:
        print("Error: new_version must be non-empty", file=sys.stderr)
        return 1

    manifest_path = (
        Path(__file__)
        .resolve()
        .parent.parent
        / "custom_components"
        / "miner"
        / "manifest.json"
    )

    if not manifest_path.is_file():
        print(f"Error: manifest.json not found at {manifest_path}", file=sys.stderr)
        return 1

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["version"] = new_version

    manifest_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Updated manifest version to {new_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


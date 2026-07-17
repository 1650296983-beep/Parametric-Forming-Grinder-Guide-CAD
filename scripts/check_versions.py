#!/usr/bin/env python3
"""Fail when frontend, Tauri, Python, and a requested release tag disagree."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import tomllib


ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")


def versions() -> dict[str, str]:
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    tauri = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    cargo = tomllib.loads((ROOT / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8"))
    namespace: dict[str, object] = {}
    exec((ROOT / "desktop" / "version.py").read_text(encoding="utf-8"), namespace)
    version_info = (ROOT / "packaging" / "windows" / "version_info.txt").read_text(encoding="utf-8")
    version_info_match = re.search(r"StringStruct\('ProductVersion', '([^']+)'\)", version_info)
    if version_info_match is None:
        raise ValueError("Windows version_info.txt lacks ProductVersion")
    return {
        "frontend/package.json": str(package["version"]),
        "src-tauri/tauri.conf.json": str(tauri["version"]),
        "src-tauri/Cargo.toml": str(cargo["package"]["version"]),
        "desktop/version.py": str(namespace["APP_VERSION"]),
        "packaging/windows/version_info.txt": version_info_match.group(1),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", help="Expected release tag, for example v1.0.0")
    args = parser.parse_args()
    found = versions()
    unique = set(found.values())
    if len(unique) != 1:
        raise SystemExit("版本不一致：" + json.dumps(found, ensure_ascii=False))
    version = unique.pop()
    if not SEMVER.fullmatch(version):
        raise SystemExit(f"版本不是有效 SemVer：{version}")
    if args.tag and args.tag != f"v{version}":
        raise SystemExit(f"Release tag {args.tag} 与应用版本 v{version} 不一致。")
    print(json.dumps({"version": version, "sources": found}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

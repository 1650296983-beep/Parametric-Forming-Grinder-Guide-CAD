#!/usr/bin/env python3
"""Create Tauri updater latest.json from a signed NSIS installer."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import quote


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--notes", default="See the GitHub Release notes for details.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    signature_path = Path(f"{args.installer}.sig")
    if not args.installer.is_file() or not signature_path.is_file():
        raise SystemExit("NSIS installer or updater signature is missing; unsigned updates are forbidden.")
    signature = signature_path.read_text(encoding="utf-8").strip()
    if not signature:
        raise SystemExit("Updater signature is empty.")
    tag = f"v{args.version}"
    url = (
        f"https://github.com/{args.repository}/releases/download/{tag}/"
        f"{quote(args.installer.name)}"
    )
    payload = {
        "version": args.version,
        "notes": args.notes,
        "pub_date": datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        "platforms": {
            "windows-x86_64": {"signature": signature, "url": url},
        },
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

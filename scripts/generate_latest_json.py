#!/usr/bin/env python3
"""Create Tauri updater latest.json from a signed NSIS installer."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import quote, urlsplit


SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
GITHUB_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _validated_download_base_url(value: str) -> str:
    base_url = value.rstrip("/")
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Updater download base URL must be an absolute HTTPS URL.")
    if parsed.query or parsed.fragment:
        raise ValueError("Updater download base URL must not contain a query or fragment.")
    return base_url


def build_download_url(
    *,
    version: str,
    installer_name: str,
    repository: str | None,
    download_base_url: str | None,
) -> str:
    if not SEMVER.fullmatch(version):
        raise ValueError(f"Invalid stable SemVer: {version}")
    encoded_name = quote(installer_name, safe="")
    if download_base_url is not None:
        return f"{_validated_download_base_url(download_base_url)}/{encoded_name}"
    if repository is None or not GITHUB_REPOSITORY.fullmatch(repository):
        raise ValueError("GitHub repository must use the owner/repository form.")
    return (
        f"https://github.com/{repository}/releases/download/v{version}/"
        f"{encoded_name}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    location = parser.add_mutually_exclusive_group(required=True)
    location.add_argument("--repository")
    location.add_argument("--download-base-url")
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
    try:
        url = build_download_url(
            version=args.version,
            installer_name=args.installer.name,
            repository=args.repository,
            download_base_url=args.download_base_url,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
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

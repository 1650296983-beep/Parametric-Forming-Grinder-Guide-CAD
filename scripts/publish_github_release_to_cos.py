#!/usr/bin/env python3
"""Download, validate, and publish a stable GitHub Release to Tencent COS."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.generate_latest_json import build_manifest
from scripts.publish_release_to_cos import (
    build_release_plan,
    create_cos_client,
    publish_release,
)


DEFAULT_REPOSITORY = "1650296983-beep/Parametric-Forming-Grinder-Guide-CAD"
DEFAULT_BUCKET = "forming-grinder-guide-cad-1424134622"
DEFAULT_REGION = "ap-shanghai"
KEYCHAIN_ACCOUNT = "cad-release-publisher"
KEYCHAIN_SECRET_ID_SERVICE = "FormingGrinderCAD-COS-SecretId"
KEYCHAIN_SECRET_KEY_SERVICE = "FormingGrinderCAD-COS-SecretKey"
TAG_PATTERN = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
INSTALLER_PATTERN = re.compile(
    r"^Forming-Grinder-CAD_(\d+\.\d+\.\d+)_x64-setup\.exe$"
)
CHECKSUM_PATTERN = re.compile(r"^([0-9a-fA-F]{64})  ([^/\\]+)$")
READ_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class ReleaseAssets:
    tag: str
    published_at: str
    release_url: str
    installer: Path
    signature: Path
    manifest: Path


def _run(
    command: list[str],
    *,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=capture_output,
            text=True,
        )
    except FileNotFoundError as error:
        raise RuntimeError(f"Required command is unavailable: {command[0]}") from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or "").strip()
        message = f"Command failed: {' '.join(command)}"
        if detail:
            message = f"{message}\n{detail}"
        raise RuntimeError(message) from error


def _run_json(command: list[str]) -> dict[str, Any]:
    result = _run(command, capture_output=True)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Command returned invalid JSON: {' '.join(command)}") from error
    if not isinstance(payload, dict):
        raise RuntimeError(f"Command did not return a JSON object: {' '.join(command)}")
    return payload


def _release_metadata(repository: str, requested_tag: str | None) -> dict[str, Any]:
    command = ["gh", "release", "view"]
    if requested_tag:
        command.append(requested_tag)
    command.extend(
        [
            "--repo",
            repository,
            "--json",
            "tagName,isDraft,isPrerelease,publishedAt,url",
        ]
    )
    metadata = _run_json(command)
    tag = metadata.get("tagName")
    if not isinstance(tag, str) or TAG_PATTERN.fullmatch(tag) is None:
        raise RuntimeError(f"Latest GitHub Release is not a stable SemVer tag: {tag!r}")
    if requested_tag and tag != requested_tag:
        raise RuntimeError(f"GitHub returned {tag}, expected {requested_tag}.")
    if metadata.get("isDraft") is not False:
        raise RuntimeError(f"GitHub Release {tag} is still a draft.")
    if metadata.get("isPrerelease") is not False:
        raise RuntimeError(f"GitHub Release {tag} is a prerelease.")
    for field in ("publishedAt", "url"):
        if not isinstance(metadata.get(field), str) or not metadata[field]:
            raise RuntimeError(f"GitHub Release {tag} is missing {field}.")
    return metadata


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(READ_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_checksums(path: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not raw_line:
            continue
        match = CHECKSUM_PATTERN.fullmatch(raw_line)
        if match is None:
            raise RuntimeError(
                f"Invalid SHA256SUMS.txt line {line_number}: {raw_line!r}"
            )
        digest, filename = match.groups()
        if filename in checksums:
            raise RuntimeError(f"Duplicate checksum entry: {filename}")
        checksums[filename] = digest.lower()
    if not checksums:
        raise RuntimeError("SHA256SUMS.txt contains no checksums.")
    return checksums


def _verify_downloaded_assets(download_dir: Path) -> dict[str, str]:
    checksum_file = download_dir / "SHA256SUMS.txt"
    if not checksum_file.is_file():
        raise RuntimeError("GitHub Release is missing SHA256SUMS.txt.")
    checksums = _read_checksums(checksum_file)
    for filename, expected in checksums.items():
        asset = download_dir / filename
        if not asset.is_file():
            raise RuntimeError(f"Checksum references a missing release asset: {filename}")
        actual = _sha256_file(asset)
        if actual != expected:
            raise RuntimeError(
                f"Checksum mismatch for {filename}: expected {expected}, got {actual}"
            )
    return checksums


def _validate_github_manifest(
    manifest_path: Path,
    *,
    version: str,
    installer: Path,
    signature: str,
) -> None:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        platform = payload["platforms"]["windows-x86_64"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise RuntimeError("GitHub latest.json is invalid or incomplete.") from error
    if str(payload.get("version")) != version:
        raise RuntimeError("GitHub latest.json version does not match the release tag.")
    if str(platform.get("signature")) != signature:
        raise RuntimeError("GitHub latest.json signature does not match the installer.")
    if not str(platform.get("url", "")).endswith(f"/{installer.name}"):
        raise RuntimeError("GitHub latest.json points to a different installer.")


def prepare_release_assets(
    *,
    repository: str,
    bucket: str,
    region: str,
    requested_tag: str | None,
    work_dir: Path,
) -> ReleaseAssets:
    metadata = _release_metadata(repository, requested_tag)
    tag = str(metadata["tagName"])
    version = tag.removeprefix("v")
    download_dir = work_dir / "github-release"
    download_dir.mkdir(parents=True, exist_ok=False)
    _run(
        [
            "gh",
            "release",
            "download",
            tag,
            "--repo",
            repository,
            "--dir",
            str(download_dir),
            "--pattern",
            "Forming-Grinder-CAD_*_x64-setup.exe*",
            "--pattern",
            "latest.json",
            "--pattern",
            "SHA256SUMS.txt",
        ]
    )
    _verify_downloaded_assets(download_dir)
    installers = [
        path
        for path in download_dir.iterdir()
        if path.is_file() and INSTALLER_PATTERN.fullmatch(path.name)
    ]
    if len(installers) != 1:
        raise RuntimeError(
            f"Expected exactly one Windows installer, found {len(installers)}."
        )
    installer = installers[0]
    installer_match = INSTALLER_PATTERN.fullmatch(installer.name)
    if installer_match is None or installer_match.group(1) != version:
        raise RuntimeError(f"Installer version does not match {tag}: {installer.name}")
    signature_path = Path(f"{installer}.sig")
    if not signature_path.is_file():
        raise RuntimeError(f"Updater signature is missing: {signature_path.name}")
    signature = signature_path.read_text(encoding="utf-8").strip()
    if not signature:
        raise RuntimeError("Updater signature is empty.")
    _validate_github_manifest(
        download_dir / "latest.json",
        version=version,
        installer=installer,
        signature=signature,
    )

    public_base = (
        f"https://{bucket}.cos.{region}.myqcloud.com/updates/releases/{tag}"
    )
    manifest_path = work_dir / "latest-cos.json"
    manifest = build_manifest(
        version=version,
        installer_name=installer.name,
        signature=signature,
        notes="See the GitHub Release notes for details.",
        repository=None,
        download_base_url=public_base,
        pub_date=str(metadata["publishedAt"]),
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return ReleaseAssets(
        tag=tag,
        published_at=str(metadata["publishedAt"]),
        release_url=str(metadata["url"]),
        installer=installer,
        signature=signature_path,
        manifest=manifest_path,
    )


def _keychain_secret(service: str) -> str:
    if sys.platform != "darwin":
        return ""
    try:
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-a",
                KEYCHAIN_ACCOUNT,
                "-s",
                service,
                "-w",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return ""
    return result.stdout.strip()


def load_publisher_credentials(
    environment: Mapping[str, str] = os.environ,
) -> tuple[str, str]:
    secret_id = environment.get("TENCENT_COS_SECRET_ID", "").strip()
    secret_key = environment.get("TENCENT_COS_SECRET_KEY", "").strip()
    if not secret_id:
        secret_id = _keychain_secret(KEYCHAIN_SECRET_ID_SERVICE)
    if not secret_key:
        secret_key = _keychain_secret(KEYCHAIN_SECRET_KEY_SERVICE)
    if not secret_id or not secret_key:
        raise RuntimeError(
            "Tencent COS publisher credentials are unavailable. Run "
            "scripts/configure_cos_publisher_keychain.sh once, or set "
            "TENCENT_COS_SECRET_ID and TENCENT_COS_SECRET_KEY."
        )
    return secret_id, secret_key


def _summary(
    assets: ReleaseAssets,
    *,
    bucket: str,
    region: str,
    published: bool,
    work_dir: Path,
) -> dict[str, Any]:
    return {
        "release": assets.tag,
        "github_release": assets.release_url,
        "cos_stable_endpoint": (
            f"https://{bucket}.cos.{region}.myqcloud.com/updates/stable/latest.json"
        ),
        "installer": assets.installer.name,
        "installer_size": assets.installer.stat().st_size,
        "installer_sha256": _sha256_file(assets.installer),
        "signature_sha256": _sha256_file(assets.signature),
        "manifest_sha256": _sha256_file(assets.manifest),
        "published": published,
        "work_dir": str(work_dir),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish a signed stable GitHub Release to the CAD Tencent COS mirror."
    )
    parser.add_argument("--tag", help="Stable tag such as v1.0.4; defaults to latest.")
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Download, verify, and prepare the COS manifest without uploading.",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        help="Keep release preparation files in this empty directory.",
    )
    return parser


def _execute(args: argparse.Namespace, work_dir: Path) -> dict[str, Any]:
    assets = prepare_release_assets(
        repository=args.repository,
        bucket=args.bucket,
        region=args.region,
        requested_tag=args.tag,
        work_dir=work_dir,
    )
    if args.dry_run:
        return _summary(
            assets,
            bucket=args.bucket,
            region=args.region,
            published=False,
            work_dir=work_dir,
        )
    secret_id, secret_key = load_publisher_credentials()
    plan = build_release_plan(
        bucket=args.bucket,
        region=args.region,
        tag=assets.tag,
        installer=assets.installer,
        manifest=assets.manifest,
    )
    client = create_cos_client(
        args.region,
        secret_id,
        secret_key,
    )
    publish_release(client, plan)
    return _summary(
        assets,
        bucket=args.bucket,
        region=args.region,
        published=True,
        work_dir=work_dir,
    )


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.tag is not None and TAG_PATTERN.fullmatch(args.tag) is None:
            raise ValueError(f"Invalid stable SemVer tag: {args.tag}")
        if args.work_dir:
            work_dir = args.work_dir.expanduser().resolve()
            if work_dir.exists() and any(work_dir.iterdir()):
                raise RuntimeError(f"Work directory is not empty: {work_dir}")
            work_dir.mkdir(parents=True, exist_ok=True)
            result = _execute(args, work_dir)
        else:
            with tempfile.TemporaryDirectory(prefix="cad-cos-publish-") as temporary:
                result = _execute(args, Path(temporary))
                result["work_dir"] = "temporary directory removed"
    except (RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

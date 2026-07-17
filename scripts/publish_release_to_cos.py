#!/usr/bin/env python3
"""Publish an approved signed desktop release to the Tencent COS update mirror."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


COS_SIMPLE_UPLOAD_MAX_BYTES = 5 * 1024**3
MAX_MANIFEST_BYTES = 1024 * 1024
READ_CHUNK_BYTES = 1024 * 1024
STABLE_MANIFEST_KEY = "updates/stable/latest.json"
IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"
STABLE_CACHE_CONTROL = "no-store, no-cache, must-revalidate, max-age=0"
BUCKET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}-[1-9]\d+$")
REGION_PATTERN = re.compile(r"^[a-z]{2}-[a-z0-9-]+$")
TAG_PATTERN = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


@dataclass(frozen=True)
class RemoteObject:
    sha256: str
    size: int
    content: bytes | None = None


@dataclass(frozen=True)
class PublishObject:
    local_path: Path
    key: str
    content_type: str
    cache_control: str


@dataclass(frozen=True)
class ReleasePlan:
    bucket: str
    region: str
    tag: str
    version: str
    public_origin: str
    immutable_objects: tuple[PublishObject, ...]
    stable_manifest: PublishObject
    manifest_payload: dict[str, Any]


def _stable_version(value: str) -> tuple[int, int, int]:
    match = TAG_PATTERN.fullmatch(f"v{value}")
    if match is None:
        raise ValueError(f"Only stable SemVer releases can be mirrored: {value}")
    return tuple(int(part) for part in match.groups())


def _validate_bucket_and_region(bucket: str, region: str) -> None:
    if not BUCKET_PATTERN.fullmatch(bucket):
        raise ValueError(f"Invalid COS bucket name: {bucket}")
    if not REGION_PATTERN.fullmatch(region):
        raise ValueError(f"Invalid COS region: {region}")


def _object_url(origin: str, key: str) -> str:
    return f"{origin}/{quote(key, safe='/')}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(READ_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_identity(payload: dict[str, Any]) -> tuple[str, str, str]:
    try:
        platform = payload["platforms"]["windows-x86_64"]
        return (
            str(payload["version"]),
            str(platform["url"]),
            str(platform["signature"]),
        )
    except (KeyError, TypeError) as error:
        raise ValueError("Updater manifest is missing the Windows platform fields.") from error


def build_release_plan(
    *,
    bucket: str,
    region: str,
    tag: str,
    installer: Path,
    manifest: Path,
) -> ReleasePlan:
    _validate_bucket_and_region(bucket, region)
    tag_match = TAG_PATTERN.fullmatch(tag)
    if tag_match is None:
        raise ValueError(f"Invalid stable release tag: {tag}")
    version = ".".join(tag_match.groups())

    signature = Path(f"{installer}.sig")
    for required in (installer, signature, manifest):
        if not required.is_file():
            raise ValueError(f"Required release file is missing: {required}")
        if required.stat().st_size <= 0:
            raise ValueError(f"Required release file is empty: {required}")
        if required.stat().st_size > COS_SIMPLE_UPLOAD_MAX_BYTES:
            raise ValueError(f"COS simple upload limit exceeded: {required}")

    signature_text = signature.read_text(encoding="utf-8").strip()
    if not signature_text:
        raise ValueError("Updater signature is empty.")
    try:
        manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("COS updater manifest is not valid UTF-8 JSON.") from error

    public_origin = f"https://{bucket}.cos.{region}.myqcloud.com"
    release_prefix = f"updates/releases/{tag}"
    expected_installer_url = _object_url(
        public_origin,
        f"{release_prefix}/{installer.name}",
    )
    manifest_version, manifest_url, manifest_signature = _manifest_identity(manifest_payload)
    if manifest_version != version:
        raise ValueError(
            f"Manifest version {manifest_version} does not match release {version}."
        )
    if manifest_url != expected_installer_url:
        raise ValueError("Manifest installer URL does not match the COS release path.")
    if manifest_signature != signature_text:
        raise ValueError("Manifest signature does not match the signed installer.")

    immutable_objects = (
        PublishObject(
            local_path=installer,
            key=f"{release_prefix}/{installer.name}",
            content_type="application/vnd.microsoft.portable-executable",
            cache_control=IMMUTABLE_CACHE_CONTROL,
        ),
        PublishObject(
            local_path=signature,
            key=f"{release_prefix}/{signature.name}",
            content_type="text/plain; charset=utf-8",
            cache_control=IMMUTABLE_CACHE_CONTROL,
        ),
        PublishObject(
            local_path=manifest,
            key=f"{release_prefix}/latest.json",
            content_type="application/json; charset=utf-8",
            cache_control=IMMUTABLE_CACHE_CONTROL,
        ),
    )
    return ReleasePlan(
        bucket=bucket,
        region=region,
        tag=tag,
        version=version,
        public_origin=public_origin,
        immutable_objects=immutable_objects,
        stable_manifest=PublishObject(
            local_path=manifest,
            key=STABLE_MANIFEST_KEY,
            content_type="application/json; charset=utf-8",
            cache_control=STABLE_CACHE_CONTROL,
        ),
        manifest_payload=manifest_payload,
    )


def inspect_public_object(
    url: str,
    *,
    capture_content: bool = False,
    timeout_seconds: int = 60,
) -> RemoteObject | None:
    request = Request(
        url,
        headers={
            "Accept": "application/octet-stream",
            "Cache-Control": "no-cache",
            "User-Agent": "forming-grinder-cos-release-audit/1",
        },
    )
    try:
        response = urlopen(request, timeout=timeout_seconds)
    except HTTPError as error:
        if error.code == 404:
            return None
        raise RuntimeError(f"Public COS verification failed with HTTP {error.code}: {url}") from error
    except URLError as error:
        raise RuntimeError(f"Public COS verification could not reach {url}: {error}") from error

    digest = hashlib.sha256()
    size = 0
    captured = bytearray()
    with response:
        for chunk in iter(lambda: response.read(READ_CHUNK_BYTES), b""):
            size += len(chunk)
            digest.update(chunk)
            if capture_content:
                if size > MAX_MANIFEST_BYTES:
                    raise RuntimeError("Remote updater manifest exceeds the 1 MiB safety limit.")
                captured.extend(chunk)
    return RemoteObject(
        sha256=digest.hexdigest(),
        size=size,
        content=bytes(captured) if capture_content else None,
    )


def _upload_object(client: Any, bucket: str, item: PublishObject) -> None:
    size = item.local_path.stat().st_size
    with item.local_path.open("rb") as source:
        client.put_object(
            Bucket=bucket,
            Key=item.key,
            Body=source,
            EnableMD5=True,
            StorageClass="STANDARD",
            ContentType=item.content_type,
            CacheControl=item.cache_control,
            ContentLength=str(size),
        )


def _verify_remote_matches(
    item: PublishObject,
    origin: str,
    inspect: Callable[..., RemoteObject | None],
) -> None:
    expected_sha256 = _sha256_file(item.local_path)
    expected_size = item.local_path.stat().st_size
    url = _object_url(origin, item.key)
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            remote = inspect(url)
            if remote is not None:
                if remote.sha256 != expected_sha256 or remote.size != expected_size:
                    raise RuntimeError(f"Public COS object differs from the local release file: {url}")
                return
        except RuntimeError as error:
            last_error = error
        if attempt < 2:
            time.sleep(attempt + 1)
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Uploaded COS object is not publicly readable: {url}")


def _publish_immutable_object(
    client: Any,
    plan: ReleasePlan,
    item: PublishObject,
    inspect: Callable[..., RemoteObject | None],
) -> None:
    url = _object_url(plan.public_origin, item.key)
    existing = inspect(url)
    if existing is not None:
        if (
            existing.sha256 != _sha256_file(item.local_path)
            or existing.size != item.local_path.stat().st_size
        ):
            raise RuntimeError(f"Refusing to overwrite an existing versioned COS object: {url}")
        print(f"Verified existing immutable COS object: {item.key}")
        return
    _upload_object(client, plan.bucket, item)
    _verify_remote_matches(item, plan.public_origin, inspect)
    print(f"Published immutable COS object: {item.key}")


def _existing_stable_manifest(
    plan: ReleasePlan,
    inspect: Callable[..., RemoteObject | None],
) -> dict[str, Any] | None:
    url = _object_url(plan.public_origin, STABLE_MANIFEST_KEY)
    existing = inspect(url, capture_content=True)
    if existing is None:
        return None
    try:
        payload = json.loads((existing.content or b"").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("Existing COS stable manifest is invalid; refusing to replace it.") from error
    _manifest_identity(payload)
    return payload


def publish_release(
    client: Any,
    plan: ReleasePlan,
    *,
    inspect: Callable[..., RemoteObject | None] = inspect_public_object,
) -> None:
    existing_stable = _existing_stable_manifest(plan, inspect)
    stable_already_current = False
    if existing_stable is not None:
        existing_version = _stable_version(str(existing_stable["version"]))
        requested_version = _stable_version(plan.version)
        if existing_version > requested_version:
            raise RuntimeError(
                f"Refusing to downgrade COS stable from {existing_stable['version']} "
                f"to {plan.version}."
            )
        if existing_version == requested_version:
            if _manifest_identity(existing_stable) != _manifest_identity(plan.manifest_payload):
                raise RuntimeError(
                    "COS stable already contains this version with different release metadata."
                )
            stable_already_current = True

    for item in plan.immutable_objects:
        _publish_immutable_object(client, plan, item, inspect)

    if stable_already_current:
        print(f"COS stable already points to {plan.tag}; no promotion required.")
        return

    _upload_object(client, plan.bucket, plan.stable_manifest)
    _verify_remote_matches(plan.stable_manifest, plan.public_origin, inspect)
    print(f"Promoted COS stable manifest to {plan.tag}.")


def _create_cos_client(region: str, secret_id: str, secret_key: str) -> Any:
    try:
        from qcloud_cos import CosConfig, CosS3Client
    except ImportError as error:
        raise RuntimeError(
            "Tencent COS SDK is missing; install requirements-cos-publish.txt."
        ) from error
    config = CosConfig(
        Region=region,
        SecretId=secret_id,
        SecretKey=secret_key,
        Scheme="https",
    )
    return CosS3Client(config)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    secret_id = os.environ.get("TENCENT_COS_SECRET_ID", "").strip()
    secret_key = os.environ.get("TENCENT_COS_SECRET_KEY", "").strip()
    if not secret_id or not secret_key:
        raise SystemExit("Tencent COS publisher credentials are missing.")

    try:
        plan = build_release_plan(
            bucket=args.bucket,
            region=args.region,
            tag=args.tag,
            installer=args.installer,
            manifest=args.manifest,
        )
        client = _create_cos_client(args.region, secret_id, secret_key)
        publish_release(client, plan)
    except (RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from error

    print(
        json.dumps(
            {
                "release": plan.tag,
                "stable_endpoint": _object_url(plan.public_origin, STABLE_MANIFEST_KEY),
                "publisher_permissions": ["cos:PutObject"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

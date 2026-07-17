from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import unquote

import pytest

from scripts.publish_release_to_cos import (
    RemoteObject,
    STABLE_MANIFEST_KEY,
    build_release_plan,
    publish_release,
)


BUCKET = "forming-grinder-guide-cad-1424134622"
REGION = "ap-shanghai"
TAG = "v1.0.3"
ORIGIN = f"https://{BUCKET}.cos.{REGION}.myqcloud.com"


def _release_files(tmp_path: Path, version: str = "1.0.3") -> tuple[Path, Path]:
    installer = tmp_path / f"Forming-Grinder-CAD_{version}_x64-setup.exe"
    installer.write_bytes(b"signed-installer")
    signature = Path(f"{installer}.sig")
    signature.write_text("trusted-signature", encoding="utf-8")
    manifest = tmp_path / "latest-cos.json"
    manifest.write_text(
        json.dumps(
            {
                "version": version,
                "notes": "release",
                "pub_date": "2026-07-17T00:00:00Z",
                "platforms": {
                    "windows-x86_64": {
                        "signature": "trusted-signature",
                        "url": (
                            f"{ORIGIN}/updates/releases/v{version}/"
                            f"{installer.name}"
                        ),
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return installer, manifest


class _FakeCos:
    def __init__(self, remote: dict[str, bytes]) -> None:
        self.remote = remote
        self.uploaded_keys: list[str] = []

    def put_object(self, **kwargs: object) -> dict[str, str]:
        body = kwargs["Body"]
        assert hasattr(body, "read")
        key = str(kwargs["Key"])
        self.remote[key] = body.read()
        self.uploaded_keys.append(key)
        return {"ETag": "fake"}


def _inspector(remote: dict[str, bytes]):
    def inspect(url: str, *, capture_content: bool = False) -> RemoteObject | None:
        key = unquote(url.split(".myqcloud.com/", 1)[1])
        content = remote.get(key)
        if content is None:
            return None
        return RemoteObject(
            sha256=hashlib.sha256(content).hexdigest(),
            size=len(content),
            content=content if capture_content else None,
        )

    return inspect


def test_release_plan_uses_only_the_configured_updates_prefix(tmp_path: Path) -> None:
    installer, manifest = _release_files(tmp_path)

    plan = build_release_plan(
        bucket=BUCKET,
        region=REGION,
        tag=TAG,
        installer=installer,
        manifest=manifest,
    )

    assert [item.key for item in plan.immutable_objects] == [
        f"updates/releases/{TAG}/{installer.name}",
        f"updates/releases/{TAG}/{installer.name}.sig",
        f"updates/releases/{TAG}/latest.json",
    ]
    assert plan.stable_manifest.key == STABLE_MANIFEST_KEY


def test_release_publisher_promotes_stable_last_and_is_idempotent(tmp_path: Path) -> None:
    installer, manifest = _release_files(tmp_path)
    plan = build_release_plan(
        bucket=BUCKET,
        region=REGION,
        tag=TAG,
        installer=installer,
        manifest=manifest,
    )
    remote: dict[str, bytes] = {}
    client = _FakeCos(remote)
    inspect = _inspector(remote)

    publish_release(client, plan, inspect=inspect)

    assert client.uploaded_keys == [
        f"updates/releases/{TAG}/{installer.name}",
        f"updates/releases/{TAG}/{installer.name}.sig",
        f"updates/releases/{TAG}/latest.json",
        STABLE_MANIFEST_KEY,
    ]
    first_upload_count = len(client.uploaded_keys)

    publish_release(client, plan, inspect=inspect)

    assert len(client.uploaded_keys) == first_upload_count


def test_release_publisher_refuses_to_replace_versioned_content(tmp_path: Path) -> None:
    installer, manifest = _release_files(tmp_path)
    plan = build_release_plan(
        bucket=BUCKET,
        region=REGION,
        tag=TAG,
        installer=installer,
        manifest=manifest,
    )
    installer_key = f"updates/releases/{TAG}/{installer.name}"
    remote = {installer_key: b"different-existing-content"}
    client = _FakeCos(remote)

    with pytest.raises(RuntimeError, match="Refusing to overwrite"):
        publish_release(client, plan, inspect=_inspector(remote))

    assert client.uploaded_keys == []


def test_release_publisher_refuses_a_stable_downgrade(tmp_path: Path) -> None:
    installer, manifest = _release_files(tmp_path)
    plan = build_release_plan(
        bucket=BUCKET,
        region=REGION,
        tag=TAG,
        installer=installer,
        manifest=manifest,
    )
    remote = {
        STABLE_MANIFEST_KEY: json.dumps(
            {
                "version": "9.0.0",
                "platforms": {
                    "windows-x86_64": {
                        "signature": "future-signature",
                        "url": f"{ORIGIN}/updates/releases/v9.0.0/future.exe",
                    }
                },
            }
        ).encode("utf-8")
    }
    client = _FakeCos(remote)

    with pytest.raises(RuntimeError, match="Refusing to downgrade"):
        publish_release(client, plan, inspect=_inspector(remote))

    assert client.uploaded_keys == []

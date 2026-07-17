from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_desktop_versions_are_consistent() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/check_versions.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["version"] == "1.0.3"


def test_tauri_requires_signed_updater_artifacts_and_localhost_endpoint() -> None:
    config = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    assert config["bundle"]["createUpdaterArtifacts"] is True
    assert config["plugins"]["updater"]["pubkey"]
    assert config["plugins"]["updater"]["endpoints"] == [
        "https://forming-grinder-guide-cad-1424134622.cos.ap-shanghai.myqcloud.com/updates/stable/latest.json",
        "https://github.com/1650296983-beep/Parametric-Forming-Grinder-Guide-CAD/releases/latest/download/latest.json"
    ]
    assert "forming-grinder-guide-cad-1424134622.cos.ap-shanghai.myqcloud.com" in (
        config["app"]["security"]["csp"]
    )
    hooks = ROOT / "packaging" / "windows" / "updater_hooks.nsh"
    assert config["bundle"]["windows"]["nsis"]["installerHooks"] == "../packaging/windows/updater_hooks.nsh"
    assert "NSIS_HOOK_PREINSTALL" in hooks.read_text(encoding="utf-8")
    assert "forming_grinder_cad_sidecar.exe" in hooks.read_text(encoding="utf-8")
    rust = (ROOT / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
    assert 'format!("http://127.0.0.1:{port}")' in rust
    assert ".arg(\"0\")" in rust
    assert "engine.stop()" in rust
    assert "fn prepare_for_update" in rust


def test_windows_release_hides_console_and_downloads_use_save_dialog() -> None:
    main = (ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
    rust = (ROOT / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
    capability = json.loads(
        (ROOT / "src-tauri" / "capabilities" / "default.json").read_text(encoding="utf-8")
    )
    app = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")

    assert 'windows_subsystem = "windows"' in main
    assert "tauri_plugin_fs::init()" in rust
    assert "dialog:allow-save" in capability["permissions"]
    assert "fs:allow-write-file" in capability["permissions"]
    assert "await save(" in app
    assert "await writeFile(target, content)" in app
    assert "已保存到：" in app
    assert 'source.protocol !== "http:"' in app
    assert '"127.0.0.1"' in app


def test_windows_ui_uses_native_smooth_chinese_font_stack() -> None:
    styles = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

    assert '"Segoe UI Variable Text"' in styles
    assert '"Microsoft YaHei UI"' in styles
    assert '"Cascadia Mono"' in styles
    assert "font-weight: 800" not in styles


def test_release_workflow_is_tag_gated_and_checks_all_release_blockers() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release-windows.yml").read_text(encoding="utf-8")
    assert 'tags:' in workflow and '"v*"' in workflow
    for required in (
        "python -m pytest",
        "scripts/run_regression_tests.py",
        "total_cases",
        "npm audit",
        "smoke_sidecar.py",
        "TAURI_SIGNING_PRIVATE_KEY",
        "Failed to add bundler type to the binary",
        "does not match the public key",
        "rsign verify",
        "patch_updater_signature_key_id.py",
        "generate_latest_json.py",
        "Forming-Grinder-CAD_${version}_x64-setup.exe",
        "SHA256SUMS.txt",
        '[IO.File]::WriteAllText(',
        '$checksumLines -join "`n"',
    ):
        assert required in workflow


def test_windows_validation_workflow_never_publishes_or_requires_signing_secrets() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "validate-windows-desktop.yml"
    ).read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "pull_request:" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "createUpdaterArtifacts = $false" in workflow
    assert "Failed to add bundler type to the binary" in workflow
    assert "release_created=false" in workflow
    assert "softprops/action-gh-release" not in workflow
    assert "TAURI_SIGNING_PRIVATE_KEY" not in workflow
    assert "push:" not in workflow


def test_cos_workflow_only_mirrors_an_approved_stable_release() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "publish-cos-mirror.yml"
    ).read_text(encoding="utf-8")
    for required in (
        "release:",
        "published",
        "isDraft",
        "isPrerelease",
        "TENCENT_COS_BUCKET",
        "TENCENT_COS_REGION",
        "TENCENT_COS_SECRET_ID",
        "TENCENT_COS_SECRET_KEY",
        "requirements-cos-publish.txt",
        "publish_release_to_cos.py",
        "updates/stable/latest.json",
    ):
        assert required in workflow
    assert "DeleteObject" not in workflow


def test_update_ui_covers_expected_user_visible_states() -> None:
    app = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    for message in (
        "当前已是最新版本",
        "无法访问更新服务；离线 CAD 功能不受影响",
        "更新包签名验证失败，已拒绝安装；当前版本已保留",
        "更新安装完成，正在重新启动应用",
        'invoke("prepare_for_update")',
        "availableUpdate.download(",
        "availableUpdate.install()",
        "relaunch",
    ):
        assert message in app


def test_updater_bridge_signature_changes_only_key_id() -> None:
    import base64

    from scripts.patch_updater_signature_key_id import patch_signature

    source_id = "F3263CB3188BF75C"
    target_id = "F3263C63188BF75C"
    primary = b"ED" + int(source_id, 16).to_bytes(8, "little") + bytes(range(64))
    decoded = "\n".join(
        [
            "untrusted comment: test",
            base64.b64encode(primary).decode("ascii"),
            "trusted comment: test",
            base64.b64encode(bytes(range(64))).decode("ascii"),
        ]
    ) + "\n"
    outer = base64.b64encode(decoded.encode("utf-8")).decode("ascii")

    patched_outer = patch_signature(outer, source_id, target_id)
    patched_lines = base64.b64decode(patched_outer).decode("utf-8").splitlines()
    patched_primary = base64.b64decode(patched_lines[1])

    assert patched_primary[:2] == b"ED"
    assert patched_primary[2:10] == int(target_id, 16).to_bytes(8, "little")
    assert patched_primary[10:] == primary[10:]
    assert patched_lines[2:] == decoded.splitlines()[2:]


def test_latest_json_requires_a_signed_installer(tmp_path: Path) -> None:
    installer = tmp_path / "Forming-Grinder-CAD_1.0.0_x64-setup.exe"
    installer.write_bytes(b"installer")
    output = tmp_path / "latest.json"
    command = [
        sys.executable,
        "scripts/generate_latest_json.py",
        "--version",
        "1.0.0",
        "--repository",
        "owner/repository",
        "--installer",
        str(installer),
        "--output",
        str(output),
    ]

    unsigned = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)

    assert unsigned.returncode != 0
    assert "unsigned updates are forbidden" in unsigned.stderr
    assert not output.exists()

    Path(f"{installer}.sig").write_text("trusted-updater-signature", encoding="utf-8")
    signed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    manifest = json.loads(output.read_text(encoding="utf-8"))

    assert signed.returncode == 0, signed.stderr
    assert manifest["platforms"]["windows-x86_64"]["signature"] == "trusted-updater-signature"
    assert manifest["platforms"]["windows-x86_64"]["url"].endswith(installer.name)

    cos_output = tmp_path / "latest-cos.json"
    cos_command = [
        sys.executable,
        "scripts/generate_latest_json.py",
        "--version",
        "1.0.0",
        "--download-base-url",
        "https://example-1250000000.cos.ap-shanghai.myqcloud.com/updates/releases/v1.0.0",
        "--installer",
        str(installer),
        "--output",
        str(cos_output),
    ]
    cos_result = subprocess.run(
        cos_command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    cos_manifest = json.loads(cos_output.read_text(encoding="utf-8"))

    assert cos_result.returncode == 0, cos_result.stderr
    assert cos_manifest["platforms"]["windows-x86_64"]["url"] == (
        "https://example-1250000000.cos.ap-shanghai.myqcloud.com/"
        f"updates/releases/v1.0.0/{installer.name}"
    )

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

import src.dwg_converter as dwg_converter
from src.dwg_converter import (
    AutoCadInstallation,
    DwgConversionError,
    build_autocad_command,
    convert_release_dxf_to_autocad_2007_dwg,
    find_autocad_installations,
)


def _fake_console(tmp_path: Path) -> Path:
    executable = tmp_path / "AcCoreConsole"
    executable.write_text("test executable", encoding="utf-8")
    executable.chmod(0o755)
    return executable


def test_converter_writes_verified_autocad_2007_dwg(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "release.dxf"
    source.write_text("DXF", encoding="utf-8")

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        script_path = Path(command[4])
        destination = Path(script_path.read_text(encoding="utf-8").splitlines()[4].strip('"'))
        destination.write_bytes(b"AC1021" + b"verified-dwg")
        return subprocess.CompletedProcess(command, 0, stdout="converted", stderr="")

    monkeypatch.setattr(dwg_converter.subprocess, "run", fake_run)

    result = convert_release_dxf_to_autocad_2007_dwg(
        source,
        release_allowed=True,
        executable=_fake_console(tmp_path),
    )

    assert result == tmp_path / "release.dwg"
    assert result.read_bytes().startswith(b"AC1021")


def test_converter_rejects_wrong_dwg_version_and_removes_output(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "release.dxf"
    source.write_text("DXF", encoding="utf-8")

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        script_path = Path(command[4])
        destination = Path(script_path.read_text(encoding="utf-8").splitlines()[4].strip('"'))
        destination.write_bytes(b"AC1032" + b"wrong-version")
        return subprocess.CompletedProcess(command, 0, stdout="converted", stderr="")

    monkeypatch.setattr(dwg_converter.subprocess, "run", fake_run)

    with pytest.raises(DwgConversionError, match="AC1021"):
        convert_release_dxf_to_autocad_2007_dwg(
            source,
            release_allowed=True,
            executable=_fake_console(tmp_path),
        )

    assert not (tmp_path / "release.dwg").exists()


def test_release_gate_blocks_converter_before_process_start(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "release.dxf"
    source.write_text("DXF", encoding="utf-8")
    monkeypatch.setattr(dwg_converter.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("must not run"))

    with pytest.raises(DwgConversionError, match="release gate"):
        convert_release_dxf_to_autocad_2007_dwg(
            source,
            release_allowed=False,
            executable=_fake_console(tmp_path),
        )


def test_command_is_argument_array_for_unicode_spaced_paths(tmp_path: Path) -> None:
    executable = tmp_path / "AutoCAD 2026 (中文)" / "AcCoreConsole.exe"
    source = tmp_path / "任务 图纸.dxf"
    script = tmp_path / "转换 脚本.scr"

    assert build_autocad_command(executable, source, script) == [
        str(executable), "/i", str(source), "/s", str(script), "/l", "en-US"
    ]


def test_converter_reports_timeout_without_creating_dwg(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "release.dxf"
    source.write_text("DXF", encoding="utf-8")

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("AcCoreConsole", 1)

    monkeypatch.setattr(dwg_converter.subprocess, "run", timeout)
    with pytest.raises(DwgConversionError, match="超过 1 秒"):
        convert_release_dxf_to_autocad_2007_dwg(
            source,
            release_allowed=True,
            executable=_fake_console(tmp_path),
            timeout_seconds=1,
        )
    assert not source.with_suffix(".dwg").exists()


def test_windows_discovery_prefers_explicit_then_highest_version(tmp_path: Path, monkeypatch) -> None:
    explicit = tmp_path / "custom" / "AcCoreConsole.exe"
    older = tmp_path / "AutoCAD 2024" / "AcCoreConsole.exe"
    newer = tmp_path / "AutoCAD 2026" / "AcCoreConsole.exe"
    for executable in (explicit, older, newer):
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("exe", encoding="utf-8")
    monkeypatch.setattr(dwg_converter.sys, "platform", "win32")
    monkeypatch.setenv("CAD_AUTOCAD_CORE_CONSOLE", str(explicit))
    monkeypatch.setattr(
        dwg_converter,
        "_windows_registry_installations",
        lambda: [
            AutoCadInstallation(older, "2024", "registry"),
            AutoCadInstallation(newer, "2026", "registry"),
        ],
    )
    monkeypatch.setattr(dwg_converter, "_windows_common_installations", lambda: [])
    monkeypatch.setattr(dwg_converter.shutil, "which", lambda _name: None)

    installations = find_autocad_installations()

    assert [item.executable for item in installations] == [
        explicit.resolve(), newer.resolve(), older.resolve()
    ]


def test_windows_subprocess_hides_console(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "release.dxf"
    source.write_text("DXF", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs)
        script_path = Path(command[4])
        destination = Path(script_path.read_text(encoding="utf-8").splitlines()[4].strip('"'))
        destination.write_bytes(b"AC1021verified")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(dwg_converter.sys, "platform", "win32")
    monkeypatch.setattr(dwg_converter.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(dwg_converter.subprocess, "run", fake_run)

    convert_release_dxf_to_autocad_2007_dwg(
        source,
        release_allowed=True,
        executable=_fake_console(tmp_path),
    )

    assert captured["creationflags"] == 0x08000000

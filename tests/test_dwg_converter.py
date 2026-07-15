from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

import src.dwg_converter as dwg_converter
from src.dwg_converter import DwgConversionError, convert_release_dxf_to_autocad_2007_dwg


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
            executable=_fake_console(tmp_path),
        )

    assert not (tmp_path / "release.dwg").exists()

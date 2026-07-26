from __future__ import annotations

from pathlib import Path
import subprocess

import ezdxf
import pytest

import src.dwg_converter as dwg_converter
from src.dwg_converter import (
    AutoCadInstallation,
    DwgConversionError,
    build_autocad_command,
    convert_release_dxf_to_autocad_2007_dwg,
    convert_release_dxf_to_autocad_2007_dwg_with_audit,
    find_autocad_installations,
)


def _fake_console(tmp_path: Path, *, year: int = 2024) -> Path:
    executable = tmp_path / f"AutoCAD {year}" / "AcCoreConsole"
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text("test executable", encoding="utf-8")
    executable.chmod(0o755)
    return executable


def _write_release_dxf(
    path: Path,
    *,
    version: str = "R2018",
    entity_count: int = 1,
) -> None:
    doc = ezdxf.new(version)
    for index in range(entity_count):
        doc.modelspace().add_line((float(index), 0.0), (float(index) + 1.0, 1.0))
    doc.saveas(path)


def _successful_run(
    *,
    source_entity_count: int = 1,
    dwg_entity_count: int = 1,
    dwg_version: bytes = b"AC1021",
    upgrade_audit_copy: bool = False,
    captured_kwargs: list[dict[str, object]] | None = None,
):
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if captured_kwargs is not None:
            captured_kwargs.append(dict(kwargs))
        working_directory = Path(str(kwargs["cwd"]))
        script_name = Path(command[4]).name
        if script_name == "save_autocad_2007.scr":
            (working_directory / "release.dwg").write_bytes(dwg_version + b"verified-dwg")
            (working_directory / dwg_converter.SOURCE_MODELSPACE_AUDIT_FILENAME).write_text(
                str(source_entity_count),
                encoding="ascii",
            )
        elif script_name == "audit_autocad_2007.scr":
            (working_directory / dwg_converter.DWG_MODELSPACE_AUDIT_FILENAME).write_text(
                str(dwg_entity_count),
                encoding="ascii",
            )
            if upgrade_audit_copy:
                Path(command[2]).write_bytes(b"AC1032upgraded-audit-copy")
        else:
            pytest.fail(f"unexpected AutoCAD script: {script_name}")
        return subprocess.CompletedProcess(command, 0, stdout="completed", stderr="")

    return fake_run


def test_converter_writes_verified_autocad_2007_dwg(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "release.dxf"
    _write_release_dxf(source)
    monkeypatch.setattr(dwg_converter.subprocess, "run", _successful_run())

    result = convert_release_dxf_to_autocad_2007_dwg_with_audit(
        source,
        release_allowed=True,
        executable=_fake_console(tmp_path),
    )

    assert result.path == tmp_path / "release.dwg"
    assert result.source_modelspace_entity_count == 1
    assert result.dwg_modelspace_entity_count == 1
    assert result.release_dxf_version == "AC1032"
    assert result.conversion_dxf_version == "AC1032"
    assert result.compatibility_mode is False
    assert result.autocad_version == "2024"
    assert result.core_console_path is not None
    assert result.path.read_bytes().startswith(b"AC1021")


def test_compatible_converter_api_still_returns_path(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "release.dxf"
    _write_release_dxf(source)
    monkeypatch.setattr(dwg_converter.subprocess, "run", _successful_run())

    result = convert_release_dxf_to_autocad_2007_dwg(
        source,
        release_allowed=True,
        executable=_fake_console(tmp_path),
    )

    assert result == tmp_path / "release.dwg"


def test_reopen_audits_copy_without_upgrading_deliverable(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "release.dxf"
    _write_release_dxf(source)
    monkeypatch.setattr(
        dwg_converter.subprocess,
        "run",
        _successful_run(upgrade_audit_copy=True),
    )

    result = convert_release_dxf_to_autocad_2007_dwg(
        source,
        release_allowed=True,
        executable=_fake_console(tmp_path),
    )

    assert dwg_converter.dwg_version(result) == "AC1021"


def test_converter_rejects_wrong_dwg_version_and_removes_output(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "release.dxf"
    _write_release_dxf(source)
    monkeypatch.setattr(
        dwg_converter.subprocess,
        "run",
        _successful_run(dwg_version=b"AC1032"),
    )

    with pytest.raises(DwgConversionError, match="AC1021"):
        convert_release_dxf_to_autocad_2007_dwg(
            source,
            release_allowed=True,
            executable=_fake_console(tmp_path),
        )

    assert not (tmp_path / "release.dwg").exists()


def test_converter_rejects_blank_dwg_and_removes_output(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "release.dxf"
    _write_release_dxf(source)
    monkeypatch.setattr(
        dwg_converter.subprocess,
        "run",
        _successful_run(source_entity_count=1, dwg_entity_count=0),
    )

    with pytest.raises(DwgConversionError, match="DWG 模型空间没有实体"):
        convert_release_dxf_to_autocad_2007_dwg(
            source,
            release_allowed=True,
            executable=_fake_console(tmp_path),
        )

    assert not source.with_suffix(".dwg").exists()


def test_converter_rejects_partial_dwg_entity_loss(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "release.dxf"
    _write_release_dxf(source, entity_count=2)
    monkeypatch.setattr(
        dwg_converter.subprocess,
        "run",
        _successful_run(source_entity_count=2, dwg_entity_count=1),
    )

    with pytest.raises(DwgConversionError, match=r"DXF=2，DWG=1"):
        convert_release_dxf_to_autocad_2007_dwg(
            source,
            release_allowed=True,
            executable=_fake_console(tmp_path),
        )

    assert not source.with_suffix(".dwg").exists()


def test_converter_rejects_missing_modelspace_audit(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "release.dxf"
    _write_release_dxf(source)

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        working_directory = Path(str(kwargs["cwd"]))
        (working_directory / "release.dwg").write_bytes(b"AC1021verified-dwg")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(dwg_converter.subprocess, "run", fake_run)

    with pytest.raises(DwgConversionError, match="未写出可读取的 转换用 DXF"):
        convert_release_dxf_to_autocad_2007_dwg(
            source,
            release_allowed=True,
            executable=_fake_console(tmp_path),
        )

    assert not source.with_suffix(".dwg").exists()


def test_release_gate_blocks_converter_before_process_start(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "release.dxf"
    _write_release_dxf(source)
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
        str(executable), "/i", str(source), "/s", str(script)
    ]


def test_autocad_2014_rebuilds_r2018_dxf_as_r2013(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "release.dxf"
    _write_release_dxf(source, version="R2018")
    conversion_versions: list[str] = []
    successful_run = _successful_run()

    def inspect_staged_dxf(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        if Path(command[4]).name == "save_autocad_2007.scr":
            conversion_versions.append(ezdxf.readfile(command[2]).dxfversion)
        return successful_run(command, **kwargs)

    monkeypatch.setattr(dwg_converter.subprocess, "run", inspect_staged_dxf)

    result = convert_release_dxf_to_autocad_2007_dwg_with_audit(
        source,
        release_allowed=True,
        executable=_fake_console(tmp_path, year=2014),
    )

    assert conversion_versions == ["AC1027"]
    assert result.release_dxf_version == "AC1032"
    assert result.conversion_dxf_version == "AC1027"
    assert result.release_modelspace_entity_count == 1
    assert result.compatibility_mode is True
    assert result.autocad_version == "2014"


def test_legacy_compatibility_rebuild_preserves_dimension_role(
    tmp_path: Path,
) -> None:
    from src.dimension_roles import get_dimension_role, set_dimension_role

    source = tmp_path / "release.dxf"
    staged = tmp_path / "staged.dxf"
    doc = ezdxf.new("R2018", setup=True)
    dimension = doc.modelspace().add_linear_dim(
        base=(0.0, 2.0),
        p1=(0.0, 0.0),
        p2=(1.0, 0.0),
    )
    dimension.render()
    set_dimension_role(dimension.dimension, "section_center_opening")
    doc.saveas(source)

    result = dwg_converter._prepare_staged_dxf(
        source,
        staged,
        _fake_console(tmp_path, year=2014),
    )
    staged_doc = ezdxf.readfile(staged)
    staged_dimensions = list(staged_doc.modelspace().query("DIMENSION"))

    assert result.staged_version == "AC1027"
    assert len(staged_dimensions) == 1
    assert get_dimension_role(staged_dimensions[0]) == "section_center_opening"


def test_converter_reports_timeout_without_creating_dwg(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "release.dxf"
    _write_release_dxf(source)

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
    _write_release_dxf(source)
    captured: list[dict[str, object]] = []

    monkeypatch.setattr(dwg_converter.sys, "platform", "win32")
    monkeypatch.setattr(dwg_converter.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(
        dwg_converter.subprocess,
        "run",
        _successful_run(captured_kwargs=captured),
    )

    convert_release_dxf_to_autocad_2007_dwg(
        source,
        release_allowed=True,
        executable=_fake_console(tmp_path),
    )

    assert len(captured) == 2
    assert all(item["creationflags"] == 0x08000000 for item in captured)

from __future__ import annotations

import json
from pathlib import Path

from desktop import runtime_paths
from src.web_api import _task_retention_days


def test_desktop_paths_use_configured_unicode_data_root(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "用户数据" / "FormingGrinderCAD"
    monkeypatch.setenv("CAD_DESKTOP_MODE", "1")
    monkeypatch.setenv("CAD_APP_DATA_ROOT", str(root))

    paths = runtime_paths.get_runtime_paths(migrate=False)

    assert paths.tasks == root / "tasks"
    assert paths.output == root / "output"
    assert paths.temp == root / "temp"
    assert paths.logs == root / "logs"
    assert all(path.is_dir() for path in (paths.tasks, paths.output, paths.temp, paths.logs))


def test_legacy_migration_copies_without_deleting_or_overwriting(tmp_path: Path, monkeypatch) -> None:
    resources = tmp_path / "resources"
    legacy = resources / "output" / "web_tasks" / "abc123def456"
    legacy.mkdir(parents=True)
    (legacy / "input.json").write_text("{}", encoding="utf-8")
    data_root = tmp_path / "data"
    monkeypatch.setenv("CAD_DESKTOP_MODE", "1")
    monkeypatch.setenv("CAD_RESOURCE_ROOT", str(resources))
    monkeypatch.setenv("CAD_APP_DATA_ROOT", str(data_root))

    paths = runtime_paths.get_runtime_paths()

    assert (paths.tasks / "abc123def456" / "input.json").is_file()
    assert (legacy / "input.json").is_file()
    marker = json.loads((data_root / ".legacy_tasks_migrated.json").read_text(encoding="utf-8"))
    assert marker["copied_tasks"] == 1
    assert runtime_paths.migrate_legacy_tasks(paths) == 0


def test_temp_cleanup_never_deletes_tasks_or_formal_output(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CAD_DESKTOP_MODE", "1")
    monkeypatch.setenv("CAD_APP_DATA_ROOT", str(tmp_path))
    paths = runtime_paths.get_runtime_paths(migrate=False)
    (paths.temp / "scratch.txt").write_text("temp", encoding="utf-8")
    (paths.tasks / "release.dxf").write_text("formal", encoding="utf-8")
    (paths.output / "report.json").write_text("{}", encoding="utf-8")

    runtime_paths.clear_runtime_temp(paths)

    assert not (paths.temp / "scratch.txt").exists()
    assert (paths.tasks / "release.dxf").is_file()
    assert (paths.output / "report.json").is_file()


def test_desktop_tasks_default_to_long_term_retention(monkeypatch) -> None:
    monkeypatch.setenv("CAD_DESKTOP_MODE", "1")
    monkeypatch.delenv("CAD_TASK_RETENTION_DAYS", raising=False)

    assert _task_retention_days() == 0


def test_application_resource_upgrade_preserves_local_data(tmp_path: Path, monkeypatch) -> None:
    data_root = tmp_path / "用户数据" / "FormingGrinderCAD"
    monkeypatch.setenv("CAD_DESKTOP_MODE", "1")
    monkeypatch.setenv("CAD_APP_DATA_ROOT", str(data_root))
    monkeypatch.setenv("CAD_RESOURCE_ROOT", str(tmp_path / "installed-v1"))
    first = runtime_paths.get_runtime_paths(migrate=False)
    (first.tasks / "existing-task.json").write_text('{"version": 1}', encoding="utf-8")
    runtime_paths.write_settings({"autocad_core_console": "C:/AutoCAD/AcCoreConsole.exe"}, first)

    # An installer/update replaces immutable resources, not the LocalAppData root.
    monkeypatch.setenv("CAD_RESOURCE_ROOT", str(tmp_path / "installed-v2"))
    upgraded = runtime_paths.get_runtime_paths(migrate=False)

    assert upgraded.app_data_root == first.app_data_root
    assert (upgraded.tasks / "existing-task.json").read_text(encoding="utf-8") == '{"version": 1}'
    assert runtime_paths.read_settings(upgraded)["autocad_core_console"].endswith("AcCoreConsole.exe")

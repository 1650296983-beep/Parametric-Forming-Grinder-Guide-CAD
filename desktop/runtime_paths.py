"""Resolve immutable resources and mutable desktop data without using CWD."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import sys


APP_DIRECTORY_NAME = "FormingGrinderCAD"
DESKTOP_MODE_ENV = "CAD_DESKTOP_MODE"
APP_DATA_ROOT_ENV = "CAD_APP_DATA_ROOT"
RESOURCE_ROOT_ENV = "CAD_RESOURCE_ROOT"


@dataclass(frozen=True)
class RuntimePaths:
    resource_root: Path
    app_data_root: Path
    tasks: Path
    output: Path
    temp: Path
    logs: Path
    settings: Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def is_desktop_mode() -> bool:
    return is_frozen() or os.getenv(DESKTOP_MODE_ENV, "").lower() in {"1", "true", "yes"}


def resource_root() -> Path:
    """Return the versioned, read-only application resource directory."""
    configured = os.getenv(RESOURCE_ROOT_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root).resolve()
    return Path(__file__).resolve().parents[1]


def default_app_data_root() -> Path:
    configured = os.getenv(APP_DATA_ROOT_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    if not is_desktop_mode():
        # Preserve the source-development location while avoiding dependence on CWD.
        return resource_root() / "output" / "web_tasks"
    if sys.platform == "win32":
        local_app_data = os.getenv("LOCALAPPDATA")
        if not local_app_data:
            raise RuntimeError("Windows 桌面运行时缺少 LOCALAPPDATA。")
        return Path(local_app_data) / APP_DIRECTORY_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIRECTORY_NAME
    return Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_DIRECTORY_NAME


def get_runtime_paths(*, create: bool = True, migrate: bool = True) -> RuntimePaths:
    root = default_app_data_root()
    if is_desktop_mode():
        paths = RuntimePaths(
            resource_root=resource_root(),
            app_data_root=root,
            tasks=root / "tasks",
            output=root / "output",
            temp=root / "temp",
            logs=root / "logs",
            settings=root / "settings.json",
        )
    else:
        paths = RuntimePaths(
            resource_root=resource_root(),
            app_data_root=root,
            tasks=root,
            output=root,
            temp=root / ".temp",
            logs=root / ".logs",
            settings=root / "settings.json",
        )
    if create:
        for directory in (paths.app_data_root, paths.tasks, paths.output, paths.temp, paths.logs):
            directory.mkdir(parents=True, exist_ok=True)
        if migrate and is_desktop_mode():
            migrate_legacy_tasks(paths)
    return paths


def migrate_legacy_tasks(paths: RuntimePaths) -> int:
    """Copy legacy source-mode tasks once; never remove or overwrite originals."""
    marker = paths.app_data_root / ".legacy_tasks_migrated.json"
    if marker.exists():
        return 0
    legacy_root = paths.resource_root / "output" / "web_tasks"
    copied = 0
    if legacy_root.is_dir() and legacy_root.resolve() != paths.tasks.resolve():
        for source in legacy_root.iterdir():
            if not source.is_dir() or source.is_symlink():
                continue
            destination = paths.tasks / source.name
            if destination.exists():
                continue
            shutil.copytree(source, destination)
            copied += 1
    marker.write_text(
        json.dumps({"source": str(legacy_root), "copied_tasks": copied}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return copied


def read_settings(paths: RuntimePaths | None = None) -> dict[str, object]:
    target = (paths or get_runtime_paths()).settings
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_settings(payload: dict[str, object], paths: RuntimePaths | None = None) -> None:
    target = (paths or get_runtime_paths()).settings
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)


def clear_runtime_temp(paths: RuntimePaths | None = None) -> None:
    """Clear only the disposable temp directory, never tasks or formal output."""
    runtime = paths or get_runtime_paths()
    if runtime.temp.exists():
        for entry in runtime.temp.iterdir():
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink(missing_ok=True)

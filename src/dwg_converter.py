"""Convert release-gated DXF files with an installed AutoCAD Core Console."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Iterable

from desktop.runtime_paths import read_settings


AUTOCAD_2007_DWG_VERSION = "AC1021"
AUTOCAD_2007_FORMAT_LABEL = "AutoCAD 2007/LT 2007 DWG"
DEFAULT_CONVERSION_TIMEOUT_SECONDS = 120
DEFAULT_MAC_CORE_CONSOLE = Path(
    "/Applications/Autodesk/AutoCAD 2024/AutoCAD 2024.app/Contents/Helpers/"
    "AcCoreConsole.app/Contents/MacOS/AcCoreConsole"
)


class DwgConversionError(RuntimeError):
    """Raised when AutoCAD does not produce a verified DWG artifact."""


@dataclass(frozen=True)
class AutoCadInstallation:
    executable: Path
    version: str | None
    source: str


def find_autocad_installations() -> list[AutoCadInstallation]:
    """Return valid installations in explicit-first, then newest-version order."""
    explicit = _explicit_console_path()
    installations: list[AutoCadInstallation] = []
    if explicit is not None:
        installations.append(
            AutoCadInstallation(explicit, _version_from_path(explicit), "configured")
        )

    discovered: list[AutoCadInstallation] = []
    if sys.platform == "win32":
        discovered.extend(_windows_registry_installations())
        discovered.extend(_windows_common_installations())
    elif sys.platform == "darwin":
        candidates = [DEFAULT_MAC_CORE_CONSOLE]
        candidates.extend(
            Path("/Applications/Autodesk").glob(
                "AutoCAD */AutoCAD *.app/Contents/Helpers/AcCoreConsole.app/Contents/MacOS/AcCoreConsole"
            )
        )
        discovered.extend(
            AutoCadInstallation(path, _version_from_path(path), "applications")
            for path in candidates
        )
    command = shutil.which("AcCoreConsole")
    if command:
        path = Path(command)
        discovered.append(AutoCadInstallation(path, _version_from_path(path), "path"))

    discovered.sort(key=lambda item: _version_key(item.version), reverse=True)
    seen: set[str] = set()
    result: list[AutoCadInstallation] = []
    for installation in [*installations, *discovered]:
        path = installation.executable.expanduser()
        key = os.path.normcase(str(path.resolve(strict=False)))
        if key in seen or not _is_executable_file(path):
            continue
        seen.add(key)
        result.append(
            AutoCadInstallation(path.resolve(), installation.version, installation.source)
        )
    return result


def find_autocad_core_console() -> Path | None:
    installations = find_autocad_installations()
    return installations[0].executable if installations else None


def autocad_detection_payload() -> dict[str, object]:
    installations = find_autocad_installations()
    selected = installations[0] if installations else None
    return {
        "available": selected is not None,
        "path": str(selected.executable) if selected else None,
        "version": selected.version if selected else None,
        "source": selected.source if selected else None,
        "detected": [
            {
                "path": str(item.executable),
                "version": item.version,
                "source": item.source,
            }
            for item in installations
        ],
    }


def dwg_conversion_available() -> bool:
    return find_autocad_core_console() is not None


def convert_release_dxf_to_autocad_2007_dwg(
    source_dxf: Path,
    destination_dwg: Path | None = None,
    *,
    release_allowed: bool,
    executable: Path | None = None,
    timeout_seconds: int = DEFAULT_CONVERSION_TIMEOUT_SECONDS,
) -> Path:
    """Convert one validated release DXF and verify its AC1021 file header."""
    if not release_allowed:
        raise DwgConversionError("DXF 未通过 release gate，禁止转换正式 DWG。")
    if timeout_seconds <= 0:
        raise DwgConversionError("DWG 转换超时必须大于 0 秒。")
    source = source_dxf.resolve()
    destination = (destination_dwg or source.with_suffix(".dwg")).resolve()
    if not source.is_file() or source.suffix.lower() != ".dxf":
        raise DwgConversionError("待转换的 release DXF 不存在或格式错误。")
    if destination.suffix.lower() != ".dwg":
        raise DwgConversionError("DWG 输出路径必须使用 .dwg 扩展名。")
    if destination.parent != source.parent:
        raise DwgConversionError("DWG 必须与通过校验的 release DXF 输出在同一目录。")
    core_console = executable or find_autocad_core_console()
    if core_console is None or not _is_executable_file(core_console):
        raise DwgConversionError("未找到可执行的 AutoCAD Core Console；release DXF 仍可使用。")
    destination.unlink(missing_ok=True)

    with TemporaryDirectory(prefix="cad_dwg_export_") as temporary_directory:
        staging_directory = Path(temporary_directory)
        staged_source = staging_directory / "release.dxf"
        staged_destination = staging_directory / "release.dwg"
        script_path = staging_directory / "save_autocad_2007.scr"
        shutil.copy2(source, staged_source)
        script_path.write_text(_save_script(staged_destination), encoding="ascii")
        command = build_autocad_command(core_console, staged_source, script_path)
        try:
            completed = subprocess.run(
                command,
                cwd=staging_directory,
                capture_output=True,
                text=True,
                errors="replace",
                check=False,
                timeout=timeout_seconds,
                creationflags=_subprocess_creation_flags(),
            )
        except subprocess.TimeoutExpired as error:
            raise DwgConversionError(
                f"AutoCAD DWG 转换超过 {timeout_seconds} 秒，已安全终止。"
            ) from error
        except OSError as error:
            raise DwgConversionError("AutoCAD Core Console 无法启动。") from error

        if completed.returncode != 0:
            raise DwgConversionError(
                f"AutoCAD Core Console 转换失败，退出码 {completed.returncode}。"
            )
        if not staged_destination.is_file() or staged_destination.stat().st_size == 0:
            raise DwgConversionError("AutoCAD Core Console 未生成有效 DWG 文件。")
        if dwg_version(staged_destination) != AUTOCAD_2007_DWG_VERSION:
            raise DwgConversionError("生成文件不是 AutoCAD 2007/LT 2007（AC1021）DWG。")
        shutil.move(staged_destination, destination)
    return destination


def build_autocad_command(executable: Path, source: Path, script: Path) -> list[str]:
    """Build a shell-free argument vector safe for Unicode and spaced paths."""
    return [str(executable), "/i", str(source), "/s", str(script), "/l", "en-US"]


def dwg_version(path: Path) -> str:
    with path.open("rb") as stream:
        return stream.read(6).decode("ascii", errors="replace")


def _save_script(destination: Path) -> str:
    return "\n".join(
        (
            "_.FILEDIA",
            "0",
            "_.SAVEAS",
            "2007",
            f'"{destination}"',
            "_.QUIT",
            "_Y",
            "",
        )
    )


def _explicit_console_path() -> Path | None:
    configured = os.getenv("CAD_AUTOCAD_CORE_CONSOLE")
    if not configured:
        setting = read_settings().get("autocad_core_console")
        configured = setting if isinstance(setting, str) else None
    return Path(configured).expanduser() if configured else None


def _windows_registry_installations() -> list[AutoCadInstallation]:
    try:
        import winreg
    except ImportError:
        return []
    roots = (
        r"SOFTWARE\Autodesk\AutoCAD",
        r"SOFTWARE\WOW6432Node\Autodesk\AutoCAD",
    )
    results: list[AutoCadInstallation] = []
    for root in roots:
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for key_path, values in _walk_registry(winreg, hive, root, max_depth=3):
                for value_name in ("AcadLocation", "InstallPath", "Location"):
                    raw = values.get(value_name)
                    if not isinstance(raw, str) or not raw:
                        continue
                    candidate = Path(raw)
                    if candidate.name.lower() != "accoreconsole.exe":
                        candidate /= "AcCoreConsole.exe"
                    results.append(
                        AutoCadInstallation(candidate, _version_from_path(Path(key_path + raw)), "registry")
                    )
    return results


def _walk_registry(winreg: object, hive: object, root: str, *, max_depth: int):
    stack = [(root, 0)]
    while stack:
        key_path, depth = stack.pop()
        try:
            key = winreg.OpenKey(hive, key_path)  # type: ignore[attr-defined]
        except OSError:
            continue
        values: dict[str, object] = {}
        index = 0
        while True:
            try:
                name, value, _ = winreg.EnumValue(key, index)  # type: ignore[attr-defined]
            except OSError:
                break
            values[name] = value
            index += 1
        yield key_path, values
        if depth < max_depth:
            index = 0
            while True:
                try:
                    child = winreg.EnumKey(key, index)  # type: ignore[attr-defined]
                except OSError:
                    break
                stack.append((f"{key_path}\\{child}", depth + 1))
                index += 1
        winreg.CloseKey(key)  # type: ignore[attr-defined]


def _windows_common_installations() -> list[AutoCadInstallation]:
    roots = _unique_paths(
        Path(value) / "Autodesk"
        for variable in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)")
        if (value := os.getenv(variable))
    )
    results: list[AutoCadInstallation] = []
    for root in roots:
        for executable in root.glob("AutoCAD 20??/AcCoreConsole.exe"):
            results.append(
                AutoCadInstallation(executable, _version_from_path(executable), "program_files")
            )
    return results


def _unique_paths(paths: Iterable[Path]) -> list[Path]:
    unique: dict[str, Path] = {}
    for path in paths:
        unique.setdefault(os.path.normcase(str(path)), path)
    return list(unique.values())


def _version_from_path(path: Path) -> str | None:
    matches = re.findall(r"(?<!\d)(20\d{2})(?!\d)", str(path))
    return matches[-1] if matches else None


def _version_key(version: str | None) -> tuple[int, ...]:
    if not version:
        return (0,)
    return tuple(int(part) for part in re.findall(r"\d+", version)) or (0,)


def _is_executable_file(path: Path) -> bool:
    if not path.is_file():
        return False
    return sys.platform == "win32" or os.access(path, os.X_OK)


def _subprocess_creation_flags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if sys.platform == "win32" else 0

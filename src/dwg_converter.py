"""Convert validated release DXF files to genuine AutoCAD 2007 DWG files."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory


AUTOCAD_2007_DWG_VERSION = "AC1021"
AUTOCAD_2007_FORMAT_LABEL = "AutoCAD 2007/LT 2007 DWG"
DEFAULT_MAC_CORE_CONSOLE = Path(
    "/Applications/Autodesk/AutoCAD 2024/AutoCAD 2024.app/Contents/Helpers/"
    "AcCoreConsole.app/Contents/MacOS/AcCoreConsole"
)


class DwgConversionError(RuntimeError):
    """Raised when AutoCAD does not produce the requested DWG artifact."""


def find_autocad_core_console() -> Path | None:
    """Locate an explicitly configured or installed AutoCAD Core Console."""
    configured = os.getenv("CAD_AUTOCAD_CORE_CONSOLE")
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.append(DEFAULT_MAC_CORE_CONSOLE)
    candidates.extend(
        sorted(
            Path("/Applications/Autodesk").glob(
                "AutoCAD */AutoCAD *.app/Contents/Helpers/AcCoreConsole.app/Contents/MacOS/AcCoreConsole"
            ),
            reverse=True,
        )
    )
    command = shutil.which("AcCoreConsole")
    if command:
        candidates.append(Path(command))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    return None


def dwg_conversion_available() -> bool:
    return find_autocad_core_console() is not None


def convert_release_dxf_to_autocad_2007_dwg(
    source_dxf: Path,
    destination_dwg: Path | None = None,
    *,
    executable: Path | None = None,
    timeout_seconds: int = 120,
) -> Path:
    """Convert one release DXF and verify its DWG header is AutoCAD 2007."""
    source = source_dxf.resolve()
    destination = (destination_dwg or source.with_suffix(".dwg")).resolve()
    if not source.is_file() or source.suffix.lower() != ".dxf":
        raise DwgConversionError(f"待转换的 release DXF 不存在：{source}")
    if destination.suffix.lower() != ".dwg":
        raise DwgConversionError("DWG 输出路径必须使用 .dwg 扩展名。")
    if destination.parent != source.parent:
        raise DwgConversionError("DWG 必须与通过校验的 release DXF 输出在同一目录。")
    core_console = (executable or find_autocad_core_console())
    if core_console is None or not core_console.is_file() or not os.access(core_console, os.X_OK):
        raise DwgConversionError("未找到可执行的 AutoCAD Core Console，无法输出真实 DWG。")
    if destination.exists():
        destination.unlink()

    with TemporaryDirectory(prefix="cad_dwg_export_") as temporary_directory:
        staging_directory = Path(temporary_directory)
        staged_source = staging_directory / "release.dxf"
        staged_destination = staging_directory / "release.dwg"
        script_path = staging_directory / "save_autocad_2007.scr"
        shutil.copy2(source, staged_source)
        script_path.write_text(_save_script(staged_destination), encoding="ascii")
        try:
            completed = subprocess.run(
                [
                    str(core_console),
                    "/i",
                    str(staged_source),
                    "/s",
                    str(script_path),
                    "/l",
                    "en-US",
                ],
                cwd=staging_directory,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise DwgConversionError(f"AutoCAD 2007 DWG 转换未完成：{error}") from error

        if completed.returncode != 0:
            raise DwgConversionError(
                f"AutoCAD Core Console 转换失败，退出码 {completed.returncode}。"
            )
        if not staged_destination.is_file() or staged_destination.stat().st_size == 0:
            raise DwgConversionError("AutoCAD Core Console 未生成 DWG 文件。")
        if _dwg_version(staged_destination) != AUTOCAD_2007_DWG_VERSION:
            raise DwgConversionError("生成文件不是 AutoCAD 2007/LT 2007（AC1021）DWG。")
        shutil.move(staged_destination, destination)
    return destination


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


def _dwg_version(path: Path) -> str:
    with path.open("rb") as stream:
        return stream.read(6).decode("ascii", errors="replace")

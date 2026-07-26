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
AUTOCAD_2013_DXF_VERSION = "AC1027"
DEFAULT_CONVERSION_TIMEOUT_SECONDS = 120
SOURCE_MODELSPACE_AUDIT_FILENAME = "source_modelspace_entity_count.txt"
DWG_MODELSPACE_AUDIT_FILENAME = "dwg_modelspace_entity_count.txt"
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


@dataclass(frozen=True)
class DwgConversionResult:
    path: Path
    source_modelspace_entity_count: int
    dwg_modelspace_entity_count: int
    release_dxf_version: str | None = None
    conversion_dxf_version: str | None = None
    release_modelspace_entity_count: int | None = None
    compatibility_mode: bool = False
    expanded_proxy_graphic_entity_count: int = 0
    autocad_version: str | None = None
    core_console_path: str | None = None


@dataclass(frozen=True)
class StagedDxfResult:
    source_version: str
    staged_version: str
    source_entity_count: int
    staged_entity_count: int
    compatibility_mode: bool
    expanded_proxy_graphic_entity_count: int


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
    """Convert one validated release DXF and return a verified DWG path."""
    return convert_release_dxf_to_autocad_2007_dwg_with_audit(
        source_dxf,
        destination_dwg,
        release_allowed=release_allowed,
        executable=executable,
        timeout_seconds=timeout_seconds,
    ).path


def convert_release_dxf_to_autocad_2007_dwg_with_audit(
    source_dxf: Path,
    destination_dwg: Path | None = None,
    *,
    release_allowed: bool,
    executable: Path | None = None,
    timeout_seconds: int = DEFAULT_CONVERSION_TIMEOUT_SECONDS,
) -> DwgConversionResult:
    """Convert DXF, reopen the DWG, and reject empty or incomplete modelspace."""
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
        conversion_script = staging_directory / "save_autocad_2007.scr"
        source_audit_path = staging_directory / SOURCE_MODELSPACE_AUDIT_FILENAME
        dwg_audit_path = staging_directory / DWG_MODELSPACE_AUDIT_FILENAME
        staged_dxf = _prepare_staged_dxf(source, staged_source, core_console)
        conversion_script.write_text(
            _save_script(
                staged_destination.name,
                source_audit_path.name,
            ),
            encoding="ascii",
        )
        conversion_process = _run_core_console(
            build_autocad_command(core_console, staged_source, conversion_script),
            cwd=staging_directory,
            timeout_seconds=timeout_seconds,
            operation="DWG 转换",
        )
        try:
            source_entity_count = _read_modelspace_entity_count(
                source_audit_path,
                artifact_label="转换用 DXF",
            )
        except DwgConversionError as error:
            raise DwgConversionError(
                f"{error} {_core_console_diagnostic(conversion_process)}"
            ) from error
        if source_entity_count != staged_dxf.staged_entity_count:
            raise DwgConversionError(
                "AutoCAD 读取到的转换用 DXF 实体数与兼容文件不一致"
                f"（文件={staged_dxf.staged_entity_count}，"
                f"AutoCAD={source_entity_count}），已拒绝输出。"
            )
        if not staged_destination.is_file() or staged_destination.stat().st_size == 0:
            raise DwgConversionError("AutoCAD Core Console 未生成有效 DWG 文件。")
        if dwg_version(staged_destination) != AUTOCAD_2007_DWG_VERSION:
            raise DwgConversionError("生成文件不是 AutoCAD 2007/LT 2007（AC1021）DWG。")

        # Core Console may upgrade an opened legacy DWG on process shutdown.
        # Audit a disposable copy so the deliverable remains AC1021 byte-for-byte.
        staged_audit_copy = staging_directory / "release_for_audit.dwg"
        shutil.copy2(staged_destination, staged_audit_copy)
        audit_script = staging_directory / "audit_autocad_2007.scr"
        audit_script.write_text(
            _modelspace_audit_script(dwg_audit_path.name),
            encoding="ascii",
        )
        _run_core_console(
            build_autocad_command(core_console, staged_audit_copy, audit_script),
            cwd=staging_directory,
            timeout_seconds=timeout_seconds,
            operation="DWG 重开校验",
        )
        dwg_entity_count = _read_modelspace_entity_count(
            dwg_audit_path,
            artifact_label="DWG",
        )
        if dwg_entity_count != source_entity_count:
            raise DwgConversionError(
                "DWG 模型空间实体数与 release DXF 不一致"
                f"（DXF={source_entity_count}，DWG={dwg_entity_count}），已拒绝输出。"
            )
        if dwg_version(staged_destination) != AUTOCAD_2007_DWG_VERSION:
            raise DwgConversionError("DWG 重开校验后交付文件不再是 AC1021，已拒绝输出。")
        shutil.move(staged_destination, destination)
    return DwgConversionResult(
        path=destination,
        source_modelspace_entity_count=source_entity_count,
        dwg_modelspace_entity_count=dwg_entity_count,
        release_dxf_version=staged_dxf.source_version,
        conversion_dxf_version=staged_dxf.staged_version,
        release_modelspace_entity_count=staged_dxf.source_entity_count,
        compatibility_mode=staged_dxf.compatibility_mode,
        expanded_proxy_graphic_entity_count=(
            staged_dxf.expanded_proxy_graphic_entity_count
        ),
        autocad_version=_version_from_path(core_console),
        core_console_path=str(core_console.resolve()),
    )


def build_autocad_command(executable: Path, source: Path, script: Path) -> list[str]:
    """Build a shell-free argument vector safe for Unicode and spaced paths."""
    return [str(executable), "/i", str(source), "/s", str(script)]


def dwg_version(path: Path) -> str:
    with path.open("rb") as stream:
        return stream.read(6).decode("ascii", errors="replace")


def _save_script(destination_filename: str, audit_filename: str) -> str:
    return "\n".join(
        (
            '(setvar "FILEDIA" 0)',
            *_modelspace_audit_lisp(audit_filename),
            "_.SAVEAS",
            "2007",
            f'"{destination_filename}"',
            "_.QUIT",
            "_Y",
            "",
        )
    )


def _modelspace_audit_script(audit_filename: str) -> str:
    return "\n".join(
        (
            '(setvar "FILEDIA" 0)',
            *_modelspace_audit_lisp(audit_filename),
            "_.QUIT",
            "_N",
            "",
        )
    )


def _modelspace_audit_lisp(audit_filename: str) -> tuple[str, ...]:
    if Path(audit_filename).name != audit_filename or '"' in audit_filename:
        raise ValueError("DWG 审计文件名必须是不含路径的安全文件名。")
    return (
        '(setvar "TILEMODE" 1)',
        (
            '(setq cad-audit-selection '
            '(ssget "_X" (list (cons 410 (getvar "CTAB")))))'
        ),
        f'(setq cad-audit-stream (open "{audit_filename}" "w"))',
        (
            "(write-line "
            "(itoa (if cad-audit-selection (sslength cad-audit-selection) 0)) "
            "cad-audit-stream)"
        ),
        "(close cad-audit-stream)",
    )


def _read_modelspace_entity_count(path: Path, *, artifact_label: str) -> int:
    try:
        raw_count = path.read_text(encoding="ascii").strip()
        count = int(raw_count)
    except (FileNotFoundError, OSError, UnicodeDecodeError, ValueError) as error:
        raise DwgConversionError(
            f"AutoCAD 未写出可读取的 {artifact_label} 模型空间审计结果。"
        ) from error
    if count <= 0:
        raise DwgConversionError(
            f"{artifact_label} 模型空间没有实体，已判定为空白图纸并拒绝输出。"
        )
    return count


def _run_core_console(
    command: list[str],
    *,
    cwd: Path,
    timeout_seconds: int,
    operation: str,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
            timeout=timeout_seconds,
            creationflags=_subprocess_creation_flags(),
        )
    except subprocess.TimeoutExpired as error:
        raise DwgConversionError(
            f"AutoCAD {operation}超过 {timeout_seconds} 秒，已安全终止。"
        ) from error
    except OSError as error:
        raise DwgConversionError(f"AutoCAD Core Console 无法启动{operation}。") from error
    if completed.returncode != 0:
        raise DwgConversionError(
            f"AutoCAD {operation}失败，退出码 {completed.returncode}。"
            f" {_core_console_diagnostic(completed)}"
        )
    return completed


def _prepare_staged_dxf(
    source: Path,
    destination: Path,
    core_console: Path,
) -> StagedDxfResult:
    try:
        import ezdxf

        source_doc = ezdxf.readfile(source)
    except Exception as error:
        raise DwgConversionError("release DXF 无法读取，禁止转换 DWG。") from error

    source_version = str(source_doc.dxfversion)
    source_entity_count = len(list(source_doc.modelspace()))
    if source_entity_count <= 0:
        raise DwgConversionError("release DXF 模型空间没有实体，禁止转换 DWG。")

    target_version = _maximum_dxf_version_for_console(core_console)
    if not _is_dxf_version_newer(source_version, target_version):
        shutil.copy2(source, destination)
        return StagedDxfResult(
            source_version=source_version,
            staged_version=source_version,
            source_entity_count=source_entity_count,
            staged_entity_count=source_entity_count,
            compatibility_mode=False,
            expanded_proxy_graphic_entity_count=0,
        )

    staged_entity_count, expanded_proxy_count = _write_compatible_dxf(
        source_doc,
        destination,
        target_version,
    )
    return StagedDxfResult(
        source_version=source_version,
        staged_version=target_version,
        source_entity_count=source_entity_count,
        staged_entity_count=staged_entity_count,
        compatibility_mode=True,
        expanded_proxy_graphic_entity_count=expanded_proxy_count,
    )


def _maximum_dxf_version_for_console(core_console: Path) -> str:
    version = _version_from_path(core_console)
    if version is None:
        # A manually configured executable may omit the release year from its
        # path. R2013 is the conservative format supported by the user's
        # oldest approved AutoCAD installation.
        return AUTOCAD_2013_DXF_VERSION
    year = int(version)
    if year >= 2018:
        return "AC1032"
    if year >= 2013:
        return AUTOCAD_2013_DXF_VERSION
    if year >= 2010:
        return "AC1024"
    if year >= 2007:
        return AUTOCAD_2007_DWG_VERSION
    raise DwgConversionError("仅支持 AutoCAD 2007 及以上版本转换 DWG。")


def _is_dxf_version_newer(source_version: str, target_version: str) -> bool:
    order = {
        "AC1009": 12,
        "AC1012": 13,
        "AC1014": 14,
        "AC1015": 2000,
        "AC1018": 2004,
        "AC1021": 2007,
        "AC1024": 2010,
        "AC1027": 2013,
        "AC1032": 2018,
    }
    try:
        return order[source_version] > order[target_version]
    except KeyError as error:
        raise DwgConversionError(
            f"无法判断 DXF 版本兼容性：{source_version} -> {target_version}。"
        ) from error


def _write_compatible_dxf(
    source_doc: object,
    destination: Path,
    target_version: str,
) -> tuple[int, int]:
    import ezdxf
    from ezdxf import xref
    from ezdxf.addons import Importer
    from ezdxf.proxygraphic import ProxyGraphic

    release_name = {
        "AC1021": "R2007",
        "AC1024": "R2010",
        "AC1027": "R2013",
    }.get(target_version)
    if release_name is None:
        raise DwgConversionError(f"不支持生成兼容 DXF：{target_version}。")

    target_doc = ezdxf.new(release_name, setup=True)
    loader = xref.Loader(source_doc, target_doc)
    loader.load_modelspace(
        filter_fn=lambda entity: entity.dxftype() != "ACAD_PROXY_ENTITY"
    )
    try:
        loader.execute()
    except Exception as error:
        raise DwgConversionError("无法重建旧版 AutoCAD 兼容 DXF。") from error

    proxy_graphics = []
    for proxy in source_doc.modelspace().query("ACAD_PROXY_ENTITY"):
        try:
            proxy_graphic = ProxyGraphic(proxy.proxy_graphic or b"", source_doc)
            virtual_entities = list(proxy.virtual_entities())
            contains_visible_geometry = _proxy_contains_visible_geometry(proxy_graphic)
        except Exception as error:
            raise DwgConversionError(
                f"代理图元 {proxy.dxf.handle} 无法解析，"
                "已拒绝生成可能缺图的 DWG。"
            ) from error
        if not virtual_entities and contains_visible_geometry:
            raise DwgConversionError(
                f"代理图元 {proxy.dxf.handle} 无法转换为旧版原生几何，"
                "已拒绝生成可能缺图的 DWG。"
            )
        proxy_graphics.extend(virtual_entities)

    if proxy_graphics:
        importer = Importer(source_doc, target_doc)
        before_count = len(list(target_doc.modelspace()))
        importer.import_entities(proxy_graphics, target_doc.modelspace())
        importer.finalize()
        imported_count = len(list(target_doc.modelspace())) - before_count
        if imported_count != len(proxy_graphics):
            raise DwgConversionError(
                "代理图元兼容转换不完整"
                f"（期望={len(proxy_graphics)}，实际={imported_count}），"
                "已拒绝输出。"
            )

    for header_name in (
        "$INSUNITS",
        "$MEASUREMENT",
        "$LUNITS",
        "$LUPREC",
        "$AUNITS",
        "$AUPREC",
    ):
        if header_name in source_doc.header:
            target_doc.header[header_name] = source_doc.header[header_name]
    try:
        target_doc.saveas(destination)
        roundtrip = ezdxf.readfile(destination)
    except Exception as error:
        raise DwgConversionError("旧版 AutoCAD 兼容 DXF 写入失败。") from error
    if str(roundtrip.dxfversion) != target_version:
        raise DwgConversionError(
            f"兼容 DXF 版本错误：期望 {target_version}，"
            f"实际 {roundtrip.dxfversion}。"
        )
    staged_entity_count = len(list(roundtrip.modelspace()))
    if staged_entity_count <= 0:
        raise DwgConversionError("兼容 DXF 模型空间为空，已拒绝输出。")
    return staged_entity_count, len(proxy_graphics)


def _proxy_contains_visible_geometry(proxy_graphic: object) -> bool:
    non_geometry_commands = {
        "PUSH_MATRIX",
        "POP_MATRIX",
        "ATTRIBUTE_COLOR",
        "ATTRIBUTE_FILL",
        "ATTRIBUTE_LAYER",
        "ATTRIBUTE_LINETYPE",
        "ATTRIBUTE_LINEWEIGHT",
        "ATTRIBUTE_LTSCALE",
        "ATTRIBUTE_MARKER",
        "ATTRIBUTE_THICKNESS",
        "ATTRIBUTE_TRUE_COLOR",
    }
    return any(
        command_name not in non_geometry_commands
        for _offset, _size, command_name in proxy_graphic.info()
    )


def _core_console_diagnostic(
    completed: subprocess.CompletedProcess[str],
    *,
    limit: int = 600,
) -> str:
    combined = "\n".join(
        value.strip()
        for value in (completed.stdout, completed.stderr)
        if value and value.strip()
    )
    if not combined:
        return "AutoCAD 未返回诊断文本。"
    compact = " | ".join(line.strip() for line in combined.splitlines() if line.strip())
    return f"AutoCAD 诊断：{compact[-limit:]}"


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

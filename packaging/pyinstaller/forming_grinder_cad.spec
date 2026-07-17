# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules


repo_root = Path(SPECPATH).resolve().parents[1]
matplotlib_datas = collect_data_files(
    "matplotlib",
    excludes=["tests", "tests/**", "testing", "testing/**"],
)
matplotlib_binaries = collect_dynamic_libs("matplotlib")

datas = [
    (str(repo_root / "templates"), "templates"),
    *matplotlib_datas,
]
hiddenimports = sorted(set([
    "ezdxf",
    "ezdxf.addons.drawing",
    "ezdxf.addons.drawing.matplotlib",
    "ezdxf.entities",
    "ezdxf.layouts",
    *collect_submodules("uvicorn"),
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "pydantic.deprecated.decorator",
]))

icon_path = os.getenv("CAD_APP_ICON")
icon = icon_path if icon_path and Path(icon_path).is_file() else None
version_file = repo_root / "packaging" / "windows" / "version_info.txt"

a = Analysis(
    [str(repo_root / "desktop" / "sidecar_entry.py")],
    pathex=[str(repo_root)],
    binaries=matplotlib_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "tkinter"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="forming_grinder_cad_sidecar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=icon,
    version=str(version_file) if os.name == "nt" and version_file.is_file() else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="forming_grinder_cad_sidecar",
)

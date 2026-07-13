from __future__ import annotations

import argparse
from pathlib import Path

from .dxf_writer import write_dxf
from .geometry import TileSection, build_section_profile, build_tile_section
from .preview import write_png_preview
from .spec_parser import parse_company_tile_spec, parse_relief_spec
from .side_view_validator import write_side_view_report
from .validator import validate_profile, validate_tile_section, write_dimension_report, write_geometry_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a parametric tile-section DXF and PNG preview.")
    parser.add_argument("--spec", help="Company format: R_outer*R_inner*chord_width*length*thickness")
    parser.add_argument("--R_outer", "--R-outer", dest="R_outer", type=float)
    parser.add_argument("--R_inner", "--R-inner", dest="R_inner", type=float)
    parser.add_argument("--chord-width", "--chord_width", dest="chord_width", type=float)
    parser.add_argument("--allowance", type=float, default=0.0)
    parser.add_argument("--relief", default="4-1", help="Relief spec, for example 4-1 or 4-0.6")
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--name", default=None)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    name = args.name or _default_name_from_args(args)
    dxf_dir = args.output_dir / "dxf"
    preview_dir = args.output_dir / "preview"
    report_dir = args.output_dir / "reports"
    dxf_dir.mkdir(parents=True, exist_ok=True)
    preview_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    error_report = report_dir / f"{name}_error_report.txt"
    geometry_report = report_dir / f"{name}_geometry_report.txt"
    dimension_report = report_dir / f"{name}_dimension_report.txt"
    side_view_report = report_dir / f"{name}_side_view_report.txt"
    tile_spec = None

    try:
        if args.spec:
            tile_spec = parse_company_tile_spec(args.spec)
            relief = parse_relief_spec(args.relief)
            profile = build_tile_section(tile_spec, allowance=args.allowance, relief=relief)
            validation = validate_tile_section(profile)
        else:
            _require_legacy_args(args)
            profile = build_section_profile(
                R_outer=args.R_outer,
                R_inner=args.R_inner,
                chord_width=args.chord_width,
                allowance=args.allowance,
            )
            validation = validate_profile(profile)
    except Exception as exc:
        error_report.write_text(f"Geometry generation failed:\n{exc}\n", encoding="utf-8")
        print(f"FAILED: wrote error report to {error_report}")
        return 1

    if not validation.ok:
        try:
            write_geometry_report(profile, validation, geometry_report, tile_spec=tile_spec)
        except Exception:
            pass
        error_report.write_text(
            "Geometry validation failed:\n" + "\n".join(f"- {error}" for error in validation.errors) + "\n",
            encoding="utf-8",
        )
        print(f"FAILED: wrote error report to {error_report}")
        return 1

    dxf_path = dxf_dir / f"{name}.dxf"
    debug_dxf_path = dxf_dir / f"{name}_debug.dxf"
    release_dxf_path = dxf_dir / f"{name}_release.dxf"
    png_path = preview_dir / f"{name}.png"

    try:
        if isinstance(profile, TileSection):
            write_dxf(profile, debug_dxf_path, output_mode="debug")
            write_dxf(profile, release_dxf_path, output_mode="release")
            dxf_path = release_dxf_path
        else:
            write_dxf(profile, dxf_path)
        write_png_preview(profile, png_path)
        write_geometry_report(profile, validation, geometry_report, tile_spec=tile_spec)
        if isinstance(profile, TileSection):
            write_dimension_report(profile, dimension_report, dxf_path=release_dxf_path, output_mode="release")
            write_side_view_report(profile, side_view_report, dxf_path=release_dxf_path, output_mode="release")
    except Exception as exc:
        error_report.write_text(f"Output generation failed:\n{exc}\n", encoding="utf-8")
        print(f"FAILED: wrote error report to {error_report}")
        return 1

    if error_report.exists():
        error_report.unlink()

    if isinstance(profile, TileSection):
        print(f"DEBUG_DXF: {debug_dxf_path}")
        print(f"RELEASE_DXF: {release_dxf_path}")
    else:
        print(f"DXF: {dxf_path}")
    print(f"PNG: {png_path}")
    print(f"REPORT: {geometry_report}")
    if dimension_report.exists():
        print(f"DIMENSION_REPORT: {dimension_report}")
    if side_view_report.exists():
        print(f"SIDE_VIEW_REPORT: {side_view_report}")
    return 0


def _default_name(R_outer: float, R_inner: float, chord_width: float) -> str:
    return f"tile_section_Ro{R_outer:g}_Ri{R_inner:g}_CW{chord_width:g}".replace(".", "p")


def _default_name_from_args(args: argparse.Namespace) -> str:
    if args.spec:
        return "tile_" + args.spec.replace("*", "_").replace(".", "p").replace("R", "R")
    if args.R_outer is None or args.R_inner is None or args.chord_width is None:
        return "tile_section"
    return _default_name(args.R_outer, args.R_inner, args.chord_width)


def _require_legacy_args(args: argparse.Namespace) -> None:
    missing = [
        name
        for name in ("R_outer", "R_inner", "chord_width")
        if getattr(args, name) is None
    ]
    if missing:
        raise ValueError("Missing required arguments without --spec: " + ", ".join(missing))


if __name__ == "__main__":
    raise SystemExit(main())

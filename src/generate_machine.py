from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import re

import ezdxf

from .block_geometry import BlockGuideSection, build_block_guide_section
from .dxf_writer import write_dxf
from .dual_guide_release_audit import write_dimension_definition_point_audit
from .guide_design_input import build_single_guide_profile_from_input
from .global_rules import BLOCK_THICKNESS_CLEARANCE
from .geometry import (
    TileSection,
    build_block_to_tile_section,
    build_tile_section,
)
from .machine_config import load_machine_config
from .output_naming import build_machine_output_stem
from .preview import write_block_png_preview, write_png_preview
from .spec_parser import (
    BlockSpec,
    FinishedSpec,
    ProductPreFormTolerance,
    parse_block_spec,
    parse_company_bread_spec,
    parse_company_tile_spec,
    parse_relief_spec,
)
from .side_view import build_side_view_geometry
from .side_view_config import SideViewTemplateConfig
from .validation_report import write_validation_report_json
from .validator import validate_tile_section


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate one machine-specific CAD validation output.")
    parser.add_argument("--machine-id", required=True)
    parser.add_argument("--spec", default=None)
    parser.add_argument(
        "--input-json",
        type=Path,
        default=None,
        help="Explicit dual-spec JSON input; cannot be combined with --spec.",
    )
    parser.add_argument(
        "--preform-spec",
        default=None,
        help="Block preform for block-to-tile grinding, for example 12.4*5.6(-0.035/-0.055)*1.96(+0.01/-0.01)",
    )
    parser.add_argument("--width-tolerance", default=None, help="upper,lower, for example -0.02,-0.04")
    parser.add_argument("--slot-reference", choices=("length", "width"), default="length")
    parser.add_argument("--block-slot-clearance", type=float, default=0.05)
    parser.add_argument("--thickness-clearance", type=float, default=None)
    parser.add_argument("--relief", default="4-1")
    parser.add_argument("--output-dir", type=Path, default=Path("output/machine_validation"))
    parser.add_argument("--name", default=None)
    args = parser.parse_args()
    if bool(args.spec) == bool(args.input_json):
        parser.error("provide exactly one of --spec or --input-json")

    machine = load_machine_config(args.machine_id)
    tolerance = _parse_width_tolerance(args.width_tolerance)
    relief = parse_relief_spec(args.relief)
    output_dir = args.output_dir / args.machine_id
    dxf_dir = output_dir / "dxf"
    preview_dir = output_dir / "preview"
    report_dir = output_dir / "reports"
    dxf_dir.mkdir(parents=True, exist_ok=True)
    preview_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    explicit_input = (
        json.loads(args.input_json.read_text(encoding="utf-8"))
        if args.input_json is not None
        else None
    )
    if explicit_input is not None:
        machine = replace(
            machine,
            wheel_radius=float(explicit_input.get("wheel_radius", machine.wheel_radius)),
        )
    name = _resolve_output_name(args.name, explicit_input, machine.machine_name, args.spec)
    debug_dxf = dxf_dir / f"{name}（调试）.dxf"
    release_dxf = dxf_dir / f"{name}.dxf"
    release_candidate_dxf = dxf_dir / f"{name}（正式候选）.dxf"
    png_path = preview_dir / f"{name}.png"
    report_json = report_dir / f"{name}_report.json"
    dimension_audit_json = report_dir / f"{name}_dimension_definition_point_audit.json"

    input_rule = None
    if explicit_input is not None:
        parsed_spec, _, profile, decision = build_single_guide_profile_from_input(
            explicit_input,
            machine,
        )
        input_rule = decision.as_dict()
    else:
        parsed_spec, profile = _build_profile(
            str(args.spec),
            tolerance,
            relief,
            args.slot_reference,
            args.block_slot_clearance,
            machine=machine,
            block_outer_width=machine.block_outer_width,
            default_block_thickness_clearance=BLOCK_THICKNESS_CLEARANCE,
            thickness_clearance_mid=args.thickness_clearance,
            preform_spec=args.preform_spec,
        )
    if isinstance(profile, TileSection):
        validation = validate_tile_section(profile)
        if not validation.ok:
            raise ValueError("Tile geometry validation failed: " + "; ".join(validation.errors))

    write_dxf(
        profile,
        debug_dxf,
        output_mode="debug",
        machine_id=args.machine_id,
        machine_config_override=machine,
    )
    if release_dxf.exists():
        release_dxf.unlink()
    if release_candidate_dxf.exists():
        release_candidate_dxf.unlink()
    write_dxf(
        profile,
        release_candidate_dxf,
        output_mode="release",
        machine_id=args.machine_id,
        machine_config_override=machine,
    )
    dimension_audit = write_dimension_definition_point_audit(
        release_candidate_dxf,
        profile,
        machine,
        dimension_audit_json,
    )
    if isinstance(profile, TileSection):
        write_png_preview(
            profile,
            png_path,
            side_layout=machine.side_layout,
            machine_name=f"{machine.machine_id} {machine.guide_length:.0f}mm",
        )
    else:
        write_block_png_preview(profile, machine, png_path)
    report = write_validation_report_json(
        profile,
        parsed_spec,
        machine,
        debug_dxf=debug_dxf,
        release_dxf=release_dxf,
        preview_png=png_path,
        report_path=report_json,
        release_inspection_dxf=release_candidate_dxf,
        input_rule=input_rule,
        dimension_definition_point_audit=dimension_audit,
    )
    if report["release_allowed"]:
        release_candidate_dxf.replace(release_dxf)
        write_validation_report_json(
            profile,
            parsed_spec,
            machine,
            debug_dxf=debug_dxf,
            release_dxf=release_dxf,
            preview_png=png_path,
            report_path=report_json,
            release_inspection_dxf=release_dxf,
            input_rule=input_rule,
            dimension_definition_point_audit=dimension_audit,
        )
    else:
        release_candidate_dxf.unlink(missing_ok=True)
        raise ValueError(f"Release validation failed; formal DXF was not written. See report: {report_json}")

    print(f"DEBUG_DXF: {debug_dxf}")
    print(f"RELEASE_DXF: {release_dxf}")
    print(f"PNG: {png_path}")
    print(f"REPORT_JSON: {report_json}")
    print(f"DIMENSION_DEFINITION_POINT_AUDIT_JSON: {dimension_audit_json}")
    return 0


def write_machine_report(
    profile: TileSection | BlockGuideSection,
    parsed_spec: FinishedSpec | BlockSpec,
    machine_id: str,
    debug_dxf: Path,
    release_dxf: Path,
    png_path: Path,
    report_path: Path,
) -> Path:
    machine = load_machine_config(machine_id)
    side = build_side_view_geometry(
        profile,
        template=SideViewTemplateConfig(wheel_radius=machine.wheel_radius),
        layout=machine.side_layout,
    )  # type: ignore[arg-type]
    guide = profile.guide_spec
    release_doc = ezdxf.readfile(release_dxf)
    debug_doc = ezdxf.readfile(debug_dxf)
    payload = {
        "machine_id": machine.machine_id,
        "machine_name": machine.machine_name,
        "guide_length": machine.guide_length,
        "wheel_positions": list(machine.wheel_positions),
        "guide_sections": machine.guide_sections,
        "debug_dxf": str(debug_dxf),
        "release_dxf": str(release_dxf),
        "png_preview": str(png_path),
        "product": _product_report(parsed_spec, profile),
        "derived": {
            "slot_width": round(guide.guide_slot_width, 6),
            "slot_width_tolerance": round(guide.slot_width_tolerance, 6),
            "guide_thickness": round(guide.guide_thickness, 6),
            "side_projected_slot_height": round(side.derived.side_projected_slot_height, 6),
            "side_clearance_height": round(side.derived.side_clearance_height, 6),
            "side_clearance_formula": _side_clearance_formula(profile),
        },
        "checks": {
            "debug_generated": debug_dxf.exists() and debug_dxf.stat().st_size > 0,
            "release_generated": release_dxf.exists() and release_dxf.stat().st_size > 0,
            "png_generated": png_path.exists() and png_path.stat().st_size > 0,
            "release_hides_debug_layers": _release_hides_debug_layers(release_doc),
            "release_hides_debug_formula_text": not _formula_texts_present(release_doc),
            "debug_contains_debug_layer": _contains_debug_layer(debug_doc),
            "wheel_arc_count": _wheel_arc_count(
                release_doc,
                machine.wheel_radius,
            ),
            "guide_length_matches_config": machine.guide_length == 435.0,
            "wheel_positions_match_config": list(machine.wheel_positions),
        },
        "template_comparison": {
            "section_template": str(machine.section_template_path),
            "side_template": str(machine.side_template_path),
            "side_fixed_spans": list(machine.side_fixed_spans),
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


def _build_profile(
    spec: str,
    tolerance: ProductPreFormTolerance | None,
    relief,
    slot_reference: str,
    block_slot_clearance: float,
    machine=None,
    block_outer_width: float = 35.0,
    default_block_thickness_clearance: float = BLOCK_THICKNESS_CLEARANCE,
    thickness_clearance_mid: float | None = None,
    preform_spec: str | None = None,
) -> tuple[FinishedSpec | BlockSpec, TileSection | BlockGuideSection]:
    if spec.strip().upper().startswith("R"):
        is_bread_spec = len([part for part in re.split(r"[*xX×]", spec) if part.strip()]) == 4
        tile_spec = (
            parse_company_bread_spec(spec)
            if is_bread_spec
            else parse_company_tile_spec(spec, require_chord_tolerance=preform_spec is None)
        )
        if preform_spec is not None:
            if machine is None:
                raise ValueError("--preform-spec requires a selected machine configuration.")
            block_preform = parse_block_spec(preform_spec)
            if tile_spec.finished_shape == "bread":
                return tile_spec, build_block_guide_section(
                    block_preform,
                    relief=relief,
                    slot_reference="width",
                    slot_clearance=None,
                    thickness_clearance_mid=(
                        default_block_thickness_clearance
                        if thickness_clearance_mid is None
                        else thickness_clearance_mid
                    ),
                    outer_width=machine.section_outer_width,
                    slot_base_height=machine.section_slot_base_height,
                    center_opening=machine.section_center_opening,
                    finished_spec=tile_spec,
                    process_type="block_to_bread_rectangular",
                )
            first_wheel_side = {
                "上": "upper",
                "下": "lower",
            }.get(machine.wheel_positions[0])
            if first_wheel_side is None:
                raise ValueError("Block-to-tile currently requires an upper or lower first wheel.")
            return tile_spec, build_block_to_tile_section(
                tile_spec,
                block_preform,
                relief=relief,
                thickness_clearance_mid=(
                    default_block_thickness_clearance
                    if thickness_clearance_mid is None
                    else thickness_clearance_mid
                ),
                outer_width=machine.section_outer_width,
                slot_base_height=(
                    27.0
                    - machine.side_layout.block_fixed_top_gap
                    - block_preform.thickness_mid
                    - (
                        default_block_thickness_clearance
                        if thickness_clearance_mid is None
                        else thickness_clearance_mid
                    )
                    if machine.side_layout.block_side_mode == "fixed_top_gap"
                    else machine.section_slot_base_height
                ),
                center_opening=machine.section_center_opening,
                arc_side=first_wheel_side,
            )
        if tolerance is not None:
            tile_spec = replace(
                tile_spec,
                chord_width_tolerance_upper=tolerance.upper,
                chord_width_tolerance_lower=tolerance.lower,
            )
        return tile_spec, build_tile_section(
            tile_spec,
            relief=relief,
            thickness_clearance_mid=thickness_clearance_mid,
            outer_width=33.0 if machine is None else machine.section_outer_width,
            slot_base_height=12.0 if machine is None else machine.section_slot_base_height,
            center_opening=1.5 if machine is None else machine.section_center_opening,
        )
    block_spec = parse_block_spec(spec)
    if tolerance is not None:
        if slot_reference == "length":
            block_spec = replace(
                block_spec,
                length_tolerance_upper=tolerance.upper,
                length_tolerance_lower=tolerance.lower,
            )
        else:
            block_spec = replace(
                block_spec,
                width_tolerance_upper=tolerance.upper,
                width_tolerance_lower=tolerance.lower,
            )
    return block_spec, build_block_guide_section(
        block_spec,
        relief=relief,
        slot_reference=slot_reference,
        slot_clearance=block_slot_clearance,
        outer_width=block_outer_width,
        thickness_clearance_mid=(
            default_block_thickness_clearance
            if thickness_clearance_mid is None
            else thickness_clearance_mid
        ),
    )


def _parse_width_tolerance(value: str | None) -> ProductPreFormTolerance | None:
    if value is None:
        return None
    parts = [part.strip() for part in value.replace("/", ",").split(",") if part.strip()]
    if len(parts) != 2:
        raise ValueError("--width-tolerance must contain upper and lower values, for example -0.02,-0.04")
    return ProductPreFormTolerance(upper=float(parts[0]), lower=float(parts[1]))


def _product_report(parsed_spec: FinishedSpec | BlockSpec, profile: TileSection | BlockGuideSection) -> dict[str, object]:
    if isinstance(parsed_spec, FinishedSpec):
        return {
            "shape": parsed_spec.finished_shape,
            "raw_spec": parsed_spec.raw,
            "R_outer_finished": parsed_spec.R_outer_finished,
            "R_inner_finished": (
                None if parsed_spec.finished_shape == "bread" else parsed_spec.R_inner_finished
            ),
            "chord_width": parsed_spec.chord_width,
            "length": parsed_spec.length,
            "finished_thickness": parsed_spec.finished_thickness,
            "thickness_tolerance_upper": parsed_spec.thickness_tolerance_upper,
            "thickness_tolerance_lower": parsed_spec.thickness_tolerance_lower,
            "preform_thickness_mid": parsed_spec.preform_thickness_mid,
            "R_form": profile.forming_spec.R_form,  # type: ignore[union-attr]
        }
    return {
        "shape": "block",
        "raw_spec": parsed_spec.raw,
        "length": parsed_spec.length,
        "width": parsed_spec.width,
        "thickness": parsed_spec.thickness,
        "slot_reference": profile.slot_reference,
        "slot_reference_value": profile.slot_reference_value,
        "slot_clearance": profile.slot_clearance,
        "length_tolerance_upper": parsed_spec.length_tolerance_upper,
        "length_tolerance_lower": parsed_spec.length_tolerance_lower,
        "width_tolerance_upper": parsed_spec.width_tolerance_upper,
        "width_tolerance_lower": parsed_spec.width_tolerance_lower,
        "R_form": None,
        "spec_rule": "QG38002 方块：长x宽x高；槽宽=选定参考尺寸+上下公差平均值+槽宽余量。",
    }


def _side_clearance_formula(profile: TileSection | BlockGuideSection) -> str:
    if isinstance(profile, BlockGuideSection):
        spec = profile.block_spec
        return f"27.00 - 18.00 - {spec.thickness:.2f} * 0.60"
    guide = profile.guide_spec
    return f"{guide.outer_height:.2f} - {guide.slot_base_height:.2f} - {guide.guide_thickness:.2f} + 0.20"


def _release_hides_debug_layers(doc) -> bool:
    return not any("DEBUG" in entity.dxf.layer or entity.dxf.layer == "REFERENCE_PROFILE" for entity in doc.modelspace())


def _contains_debug_layer(doc) -> bool:
    return any("DEBUG" in entity.dxf.layer for entity in doc.modelspace())


def _formula_texts_present(doc) -> bool:
    needles = ("+0.50=", "+0.20=", "12.0+0.50", "27.0-12.0")
    for entity in doc.modelspace():
        if entity.dxftype() == "TEXT":
            text = entity.dxf.text
        elif entity.dxftype() == "MTEXT":
            text = entity.text
        else:
            continue
        if any(needle in text for needle in needles):
            return True
    return False


def _wheel_arc_count(doc, wheel_radius: float) -> int:
    return sum(
        1
        for entity in doc.modelspace()
        if entity.dxftype() == "ARC"
        and entity.dxf.layer == "SIDE_TEMPLATE"
        and abs(entity.dxf.radius - wheel_radius) < 1e-6
    )


def _artifact_name(raw_spec: str) -> str:
    return raw_spec.replace("*", "_").replace("x", "_").replace("X", "_").replace(".", "p").replace("R", "R")


def _resolve_output_name(
    requested_name: str | None,
    explicit_input: dict[str, object] | None,
    machine_name: str,
    legacy_spec: str | None,
) -> str:
    """Use the mandatory dual-spec naming rule whenever explicit input is used."""
    if explicit_input is None:
        return requested_name or _artifact_name(str(legacy_spec))
    if requested_name:
        raise ValueError("显式双规格输入不支持 --name；输出文件名由规格和机台类型固定生成。")
    finished_spec = _required_input_spec(
        explicit_input,
        "finished_spec",
        "finished_product_spec",
    )
    pre_grinding_spec = _required_input_spec(
        explicit_input,
        "pre_grinding_spec",
        "preform_spec",
    )
    return build_machine_output_stem(finished_spec, pre_grinding_spec, machine_name)


def _required_input_spec(
    explicit_input: dict[str, object],
    canonical_key: str,
    compatibility_key: str,
) -> str:
    value = explicit_input.get(canonical_key, explicit_input.get(compatibility_key))
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"显式输入缺少 {canonical_key}，无法生成输出文件名。")
    return value


if __name__ == "__main__":
    raise SystemExit(main())

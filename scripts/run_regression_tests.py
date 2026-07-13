#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from datetime import date
import getpass
import hashlib
import json
from pathlib import Path
import shutil
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.block_geometry import BlockGuideSection, build_block_guide_section
from src.dual_guide_engine import DualGuideTemplateEngine
from src.dual_guide_input import build_dual_guide_profile_from_input
from src.dual_guide_release_audit import (
    build_release_line_type_audit,
    write_dimension_definition_point_audit,
)
from src.guide_design_input import build_single_guide_profile_from_input
from src.dxf_writer import write_dxf
from src.generate_machine import _build_profile, write_block_png_preview
from src.geometry import TileSection
from src.machine_config import MachineConfig, load_machine_config
from src.preview import write_png_preview
from src.spec_parser import BlockSpec, ProductPreFormTolerance, parse_relief_spec
from src.validation_report import write_validation_report_json
from src.validator import validate_tile_section


REGRESSION_ROOT = REPO_ROOT / "tests" / "regression"
TOLERANCE = 0.01
HIGH_RISK_NUMBERS = {27.0, 40.0, 80.0, 300.0, 379.0, 435.0, 590.0}
HIGH_RISK_KEYS = {"guide_length", "guide_sections", "wheel_positions"}
ARTIFACTS = {
    "release_dxf": ("expected_release.dxf", "actual_release.dxf"),
    "debug_dxf": ("expected_debug.dxf", "actual_debug.dxf"),
    "preview_png": ("expected_preview.png", "actual_preview.png"),
    "report_json": ("expected_report.json", "actual_report.json"),
    "audit_json": ("expected_audit.json", "actual_audit.json"),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run machine CAD regression tests.")
    parser.add_argument("--root", type=Path, default=REGRESSION_ROOT)
    parser.add_argument("--machine", help="Run one machine only.")
    parser.add_argument("--case", help="Run one case directory name, for example case_001.")
    parser.add_argument("--update-baseline", action="store_true", help="Replace expected_* files with actual_* files.")
    parser.add_argument("--change-reason", default="", help="Required with --update-baseline.")
    parser.add_argument("--approved-by", default=getpass.getuser())
    parser.add_argument("--approved-date", default=date.today().isoformat())
    parser.add_argument("--template-version", default=None, help="Optional explicit template version for metadata update.")
    parser.add_argument(
        "--approve-high-risk",
        action="store_true",
        help="Explicit human approval for high-risk template/baseline updates.",
    )
    args = parser.parse_args()

    if args.update_baseline:
        if not args.machine:
            parser.error("--update-baseline requires --machine <machine_id>.")
        if not args.change_reason:
            parser.error("--update-baseline requires --change-reason.")

    cases = discover_cases(args.root, machine=args.machine, case_name=args.case)
    summary = {"total_cases": len(cases), "passed": 0, "failed": 0, "cases": []}

    for case_dir in cases:
        result = run_case(case_dir)
        if args.update_baseline and result["machine_id"] == args.machine:
            update_result = update_baseline(
                case_dir,
                result,
                change_reason=args.change_reason,
                approved_by=args.approved_by,
                approved_date=args.approved_date,
                template_version=args.template_version,
                approve_high_risk=args.approve_high_risk,
            )
            result["baseline_update"] = update_result
            result["status"] = "PASS" if update_result["updated"] else "FAIL"
            result["differences"] = [] if update_result["updated"] else update_result["blocking_reasons"]
        elif args.update_baseline and result["machine_id"] != args.machine:
            result["status"] = "SKIP"
            result["differences"] = [f"Skipped by --machine {args.machine}."]
        else:
            compare = compare_case(case_dir)
            result["status"] = "PASS" if compare["ok"] and result["generation_ok"] else "FAIL"
            result["differences"] = compare["differences"] + result.get("generation_errors", [])

        if result["status"] == "PASS":
            summary["passed"] += 1
        elif result["status"] == "FAIL":
            summary["failed"] += 1
        summary["cases"].append(result)

    args.root.mkdir(parents=True, exist_ok=True)
    summary_path = args.root / "regression_summary.json"
    write_json(summary_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["failed"] == 0 else 1


def discover_cases(root: Path, machine: str | None = None, case_name: str | None = None) -> list[Path]:
    if not root.exists():
        return []
    machine_dirs = [root / machine] if machine else sorted(path for path in root.iterdir() if path.is_dir())
    cases: list[Path] = []
    for machine_dir in machine_dirs:
        if not machine_dir.exists() or machine_dir.name.startswith("."):
            continue
        for case_dir in sorted(path for path in machine_dir.iterdir() if path.is_dir()):
            if case_name and case_dir.name != case_name:
                continue
            if (case_dir / "input.json").exists():
                cases.append(case_dir)
    return cases


def run_case(case_dir: Path) -> dict[str, Any]:
    input_data = read_json(case_dir / "input.json")
    machine_id = str(input_data["machine_id"])
    machine = load_machine_config(machine_id)
    paths = {key: case_dir / actual for key, (_, actual) in ARTIFACTS.items()}
    paths["dimension_audit_json"] = (
        case_dir / "actual_dimension_definition_point_audit.json"
    )
    for path in paths.values():
        path.unlink(missing_ok=True)

    result: dict[str, Any] = {
        "machine_id": machine_id,
        "case": case_dir.name,
        "case_dir": str(case_dir),
        "generation_ok": False,
        "generation_errors": [],
    }
    try:
        if machine.guide_sections == 2:
            report = generate_dual_guide_case(input_data, machine, paths)
        else:
            report = generate_single_guide_case(input_data, machine, paths)
        audit = build_regression_audit(machine, paths["release_dxf"], paths["debug_dxf"], report)
        write_json(paths["audit_json"], audit)
        result["generation_ok"] = True
        result["key_values"] = extract_key_values(report)
    except Exception as exc:
        result["generation_errors"].append(f"Generation failed: {exc}")
    return result


def generate_single_guide_case(input_data: dict[str, Any], machine: MachineConfig, paths: dict[str, Path]) -> dict[str, Any]:
    relief = parse_relief_spec(str(input_data.get("relief", "4-1")))
    input_rule = None
    if "finished_product_spec" in input_data:
        parsed_spec, _, profile, decision = build_single_guide_profile_from_input(
            input_data,
            machine,
        )
        input_rule = decision.as_dict()
    else:
        parsed_spec, profile = _build_profile(
            str(input_data["spec"]),
            tolerance=parse_optional_tolerance(input_data.get("width_tolerance")),
            relief=relief,
            slot_reference=str(input_data.get("slot_reference", "length")),
            block_slot_clearance=float(input_data.get("block_slot_clearance", 0.05)),
            machine=machine,
            block_outer_width=machine.block_outer_width,
            block_thickness_clearance_mid=machine.block_thickness_clearance_mid,
            thickness_clearance_mid=input_data.get("thickness_clearance"),
            preform_spec=input_data.get("preform_spec"),
        )
    if isinstance(profile, TileSection):
        validation = validate_tile_section(profile)
        if not validation.ok:
            raise ValueError("Tile geometry validation failed: " + "; ".join(validation.errors))

    candidate = paths["release_dxf"].with_suffix(".candidate.dxf")
    candidate.unlink(missing_ok=True)
    write_dxf(profile, paths["debug_dxf"], output_mode="debug", machine_id=machine.machine_id)
    write_dxf(profile, candidate, output_mode="release", machine_id=machine.machine_id)
    dimension_audit = write_dimension_definition_point_audit(
        candidate,
        profile,
        machine,
        paths["dimension_audit_json"],
    )
    if isinstance(profile, TileSection):
        write_png_preview(
            profile,
            paths["preview_png"],
            side_layout=machine.side_layout,
            machine_name=f"{machine.machine_id} {machine.guide_length:.0f}mm",
        )
    else:
        write_block_png_preview(profile, machine.machine_id, paths["preview_png"])
    report = write_validation_report_json(
        profile,
        parsed_spec,
        machine,
        debug_dxf=paths["debug_dxf"],
        release_dxf=paths["release_dxf"],
        preview_png=paths["preview_png"],
        report_path=paths["report_json"],
        release_inspection_dxf=candidate,
        input_rule=input_rule,
        dimension_definition_point_audit=dimension_audit,
    )
    if not report["release_allowed"]:
        candidate.unlink(missing_ok=True)
        raise ValueError("Release validation failed; baseline candidate was not promoted.")
    candidate.replace(paths["release_dxf"])
    report = write_validation_report_json(
        profile,
        parsed_spec,
        machine,
        debug_dxf=paths["debug_dxf"],
        release_dxf=paths["release_dxf"],
        preview_png=paths["preview_png"],
        report_path=paths["report_json"],
        release_inspection_dxf=paths["release_dxf"],
        input_rule=input_rule,
        dimension_definition_point_audit=dimension_audit,
    )
    return report


def generate_dual_guide_case(input_data: dict[str, Any], machine: MachineConfig, paths: dict[str, Path]) -> dict[str, Any]:
    engine = DualGuideTemplateEngine(machine)
    if "finished_product_spec" in input_data:
        _, pre_grinding_spec, profile, decision = (
            build_dual_guide_profile_from_input(input_data, machine)
        )
        input_rule = {
            **decision.as_dict(),
            "input_rule_valid": True,
            "input_mode": "explicit_input_json",
        }
    else:
        # Historical regression fixtures intentionally exercise the legacy
        # single-spec API. Keep that compatibility path in the test harness so
        # an input-schema migration is not mistaken for a geometry regression.
        pre_grinding_spec = build_block_spec_for_input(input_data)
        profile = build_block_guide_section(
            pre_grinding_spec,
            relief=parse_relief_spec(str(input_data.get("relief", "4-1"))),
            slot_reference=str(input_data.get("slot_reference", "length")),
            slot_clearance=float(input_data.get("block_slot_clearance", 0.05)),
            outer_width=machine.block_outer_width,
            thickness_clearance_mid=float(
                input_data.get(
                    "thickness_clearance",
                    machine.block_thickness_clearance_mid,
                )
            ),
        )
        input_rule = engine._legacy_input_rule(profile, pre_grinding_spec)

    candidate = paths["release_dxf"].with_suffix(".candidate.dxf")
    dimension_audit_path = paths["dimension_audit_json"]
    debug_result = engine.write_dxf(profile, paths["debug_dxf"], output_mode="debug")
    release_result = engine.write_dxf(profile, candidate, output_mode="release")
    dimension_audit = write_dimension_definition_point_audit(
        candidate,
        profile,
        machine,
        dimension_audit_path,
    )
    line_type_audit = build_release_line_type_audit(candidate)
    release_gate = (
        input_rule["input_rule_valid"]
        and dimension_audit["release_allowed"]
        and line_type_audit["release_allowed"]
        and release_result["release_side_dimensions_match_report"]
        and engine._lower_wheel_release_allowed(profile)
        and release_result["synchronized"]
    )
    if not release_gate:
        candidate.unlink(missing_ok=True)
        raise ValueError("Dual-guide release gate failed.")
    candidate.replace(paths["release_dxf"])
    report = engine._build_report(
        profile,
        pre_grinding_spec,
        paths["debug_dxf"],
        paths["release_dxf"],
        debug_result,
        release_result,
        input_rule=input_rule,
        dimension_audit=dimension_audit,
        line_type_audit=line_type_audit,
        release_gate=release_gate,
    )
    write_json(paths["report_json"], report)
    if isinstance(profile, TileSection):
        write_png_preview(
            profile,
            paths["preview_png"],
            side_layout=machine.side_layout,
            machine_name=f"{machine.machine_id} {machine.guide_length:.0f}mm",
        )
    else:
        write_block_png_preview(profile, machine.machine_id, paths["preview_png"])
    return report


def build_block_spec_for_input(input_data: dict[str, Any]) -> BlockSpec:
    from src.spec_parser import parse_block_spec

    spec = parse_block_spec(str(input_data["spec"]))
    tolerance = parse_optional_tolerance(input_data.get("width_tolerance"))
    if tolerance is None:
        return spec
    if input_data.get("slot_reference", "length") == "length":
        return replace(spec, length_tolerance_upper=tolerance.upper, length_tolerance_lower=tolerance.lower)
    return replace(spec, width_tolerance_upper=tolerance.upper, width_tolerance_lower=tolerance.lower)


def parse_optional_tolerance(value: Any) -> ProductPreFormTolerance | None:
    if value is None:
        return None
    if isinstance(value, str):
        parts = [float(part.strip()) for part in value.replace("/", ",").split(",") if part.strip()]
    else:
        parts = [float(value[0]), float(value[1])]
    if len(parts) != 2:
        raise ValueError("width_tolerance must contain upper and lower tolerance.")
    return ProductPreFormTolerance(upper=parts[0], lower=parts[1])


def build_regression_audit(machine: MachineConfig, release_dxf: Path, debug_dxf: Path, report: dict[str, Any]) -> dict[str, Any]:
    key_values = extract_key_values(report)
    safety = lower_wheel_safety_payload(report)
    audit = {
        "machine_id": machine.machine_id,
        "case_generated_from": {
            "release_dxf": str(release_dxf),
            "debug_dxf": str(debug_dxf),
        },
        "key_values": key_values,
        "release_dxf_summary": summarize_dxf(release_dxf),
        "debug_dxf_summary": summarize_dxf(debug_dxf),
        "template_geometry_summary": summarize_template_geometry(machine),
        "safety_rules": {
            "lower_cavity_notch_opening <= product_length - 0.2": safety["ok"],
            **safety["details"],
        },
    }
    return audit


def extract_key_values(report: dict[str, Any]) -> dict[str, Any]:
    if "machine" in report:
        machine = report["machine"]
        process = report["process_parameters"]
        wheel_notch = report.get("side_view", {}).get("wheel_notch") or {}
        inspection = report.get("inspection", {})
        release_layers = find_inspection_check(inspection, "release_layers")
        dimension_checks = [
            check for check in inspection.get("checks", []) if str(check.get("name", "")).endswith("_dimension")
        ]
        return {
            "machine_id": machine["machine_id"],
            "guide_length": machine["guide_length"],
            "guide_sections": machine["guide_sections"],
            "wheel_positions": machine["wheel_positions"],
            "slot_width": process["slot_width"]["slot_width"],
            "guide_thickness": process["guide_thickness"]["result"],
            "R_form": None if process.get("R_form") is None else process["R_form"]["result"],
            "lower_cavity_notch_opening": wheel_notch.get("lower_cavity_notch_opening"),
            "fixed_template_dimensions": report.get("fixed_template_dimensions"),
            "release_layers": None if release_layers is None else release_layers.get("details", {}).get("layers"),
            "dimension_checks": dimension_checks,
            "required_dimension_roles": report.get("required_dimension_roles", {}),
            "release_allowed": report.get("release_allowed"),
        }
    safety = report.get("lower_wheel_notch_safety", {})
    return {
        "machine_id": report["machine_id"],
        "guide_length": report["guide_length"],
        "guide_sections": report["guide_sections"],
        "wheel_positions": report.get("wheel_positions") or _machine_positions(report["machine_id"]),
        "slot_width": report["shared_parameters"]["slot_width"],
        "guide_thickness": report["shared_parameters"]["guide_thickness"],
        "R_form": report["shared_parameters"].get("R_form"),
        "lower_cavity_notch_opening": safety.get("lower_cavity_notch_opening"),
        "fixed_template_dimensions": report.get("fixed_template_geometry"),
        "release_layers": summarize_dxf(Path(report["release_dxf"]))["layers"] if Path(report["release_dxf"]).exists() else [],
        "dimension_checks": report.get("side_view_dimension_audit", []),
        "required_dimension_roles": report.get(
            "dimension_definition_point_audit",
            {},
        ).get("required_roles", {}),
        "release_allowed": report.get("release_allowed"),
    }


def lower_wheel_safety_payload(report: dict[str, Any]) -> dict[str, Any]:
    if "side_view" in report:
        notch = report["side_view"].get("wheel_notch")
        if not notch:
            return {"ok": True, "details": {"not_applicable": True}}
        opening = notch["lower_cavity_notch_opening"]
        limit = notch["product_length"] - 0.2
        return {
            "ok": opening <= limit + TOLERANCE,
            "details": {
                "product_length": notch["product_length"],
                "lower_cavity_notch_opening": opening,
                "limit": limit,
            },
        }
    safety = report.get("lower_wheel_notch_safety")
    if not safety:
        return {"ok": True, "details": {"not_applicable": True}}
    return {
        "ok": safety["lower_cavity_notch_opening"] <= safety["product_length"] - 0.2 + TOLERANCE,
        "details": {
            "product_length": safety["product_length"],
            "lower_cavity_notch_opening": safety["lower_cavity_notch_opening"],
            "limit": safety["product_length"] - 0.2,
        },
    }


def summarize_dxf(path: Path) -> dict[str, Any]:
    import ezdxf

    doc = ezdxf.readfile(path)
    entities = list(doc.modelspace())
    counts = Counter(entity.dxftype() for entity in entities)
    layers = sorted({entity.dxf.layer for entity in entities})
    layer_counts = Counter(entity.dxf.layer for entity in entities)
    arc_radii = Counter(round(float(entity.dxf.radius), 3) for entity in entities if entity.dxftype() == "ARC")
    summary = {
        "path": str(path),
        "entity_counts": dict(sorted(counts.items())),
        "line_count": counts.get("LINE", 0),
        "arc_count": counts.get("ARC", 0),
        "dimension_count": counts.get("DIMENSION", 0),
        "layers": layers,
        "layer_entity_counts": dict(sorted(layer_counts.items())),
        "key_arc_radii": [{"radius": radius, "count": count} for radius, count in sorted(arc_radii.items())],
        "dimension_measurements": dimension_measurements(doc),
        "extents": dxf_extents(entities),
        "PARAM_SLOT_count": sum(1 for entity in entities if entity.dxf.layer == "PARAM_SLOT"),
        "SIDE_DERIVED_count": sum(1 for entity in entities if entity.dxf.layer == "SIDE_DERIVED"),
    }
    release_count = sum(
        1
        for entity in entities
        if entity.dxf.layer == "SIDE_DERIVED_RELEASE"
    )
    if release_count:
        summary["SIDE_DERIVED_RELEASE_count"] = release_count
    return summary


def summarize_template_geometry(machine: MachineConfig) -> dict[str, Any]:
    paths = sorted({machine.section_template_path, machine.side_template_path})
    summaries = [summarize_dxf(path) for path in paths]
    entity_counts = Counter()
    layer_counts = Counter()
    all_dimensions = []
    all_radii = Counter()
    extents = {"min_x": None, "min_y": None, "max_x": None, "max_y": None}
    for summary in summaries:
        entity_counts.update(summary["entity_counts"])
        layer_counts.update(summary["layer_entity_counts"])
        all_dimensions.extend(summary["dimension_measurements"])
        for item in summary["key_arc_radii"]:
            all_radii[item["radius"]] += item["count"]
        merge_extents(extents, summary["extents"])
    return {
        "template_files": [str(path) for path in paths],
        "sha256": template_sha256(machine),
        "entity_counts": dict(sorted(entity_counts.items())),
        "layer_entity_counts": dict(sorted(layer_counts.items())),
        "layers": sorted(layer_counts),
        "key_arc_radii": [{"radius": radius, "count": count} for radius, count in sorted(all_radii.items())],
        "dimension_measurements": sorted(all_dimensions, key=dimension_sort_key),
        "extents": extents,
    }


def dimension_measurements(doc: Any) -> list[dict[str, Any]]:
    rows = []
    for entity in doc.modelspace().query("DIMENSION"):
        text = entity.dxf.text if entity.dxf.hasattr("text") else ""
        try:
            measurement = float(entity.get_measurement())
        except Exception:
            measurement = None
        rows.append(
            {
                "layer": entity.dxf.layer,
                "text": text,
                "measurement": rounded(measurement),
                "definition_points": {
                    attr: point_payload(entity.dxf.get(attr))
                    for attr in ("defpoint", "defpoint2", "defpoint3", "defpoint4", "text_midpoint")
                    if entity.dxf.hasattr(attr)
                },
            }
        )
    return sorted(rows, key=dimension_sort_key)


def dxf_extents(entities: list[Any]) -> dict[str, float | None]:
    xs: list[float] = []
    ys: list[float] = []
    for entity in entities:
        if entity.dxftype() == "LINE":
            for point in (entity.dxf.start, entity.dxf.end):
                xs.append(float(point.x))
                ys.append(float(point.y))
        elif entity.dxftype() in {"ARC", "CIRCLE"}:
            center = entity.dxf.center
            radius = float(entity.dxf.radius)
            xs.extend([float(center.x) - radius, float(center.x) + radius])
            ys.extend([float(center.y) - radius, float(center.y) + radius])
        elif entity.dxftype() == "DIMENSION":
            for attr in ("defpoint", "defpoint2", "defpoint3", "defpoint4", "text_midpoint"):
                if entity.dxf.hasattr(attr):
                    point = entity.dxf.get(attr)
                    xs.append(float(point.x))
                    ys.append(float(point.y))
    if not xs or not ys:
        return {"min_x": None, "min_y": None, "max_x": None, "max_y": None}
    return {
        "min_x": rounded(min(xs)),
        "min_y": rounded(min(ys)),
        "max_x": rounded(max(xs)),
        "max_y": rounded(max(ys)),
    }


def compare_case(case_dir: Path) -> dict[str, Any]:
    differences: list[str] = []
    for _, (expected_name, actual_name) in ARTIFACTS.items():
        expected_path = case_dir / expected_name
        actual_path = case_dir / actual_name
        if not expected_path.exists():
            differences.append(f"Missing baseline: {expected_path}")
        if not actual_path.exists():
            differences.append(f"Missing actual artifact: {actual_path}")
    if differences:
        return {"ok": False, "differences": differences}
    input_data = read_json(case_dir / "input.json")
    machine = load_machine_config(str(input_data["machine_id"]))
    explicit_dual_input = "finished_product_spec" in input_data
    if machine.guide_sections == 2 and explicit_dual_input:
        for path in (
            case_dir / "expected_dimension_definition_point_audit.json",
            case_dir / "actual_dimension_definition_point_audit.json",
        ):
            if not path.exists():
                differences.append(f"Missing dimension audit artifact: {path}")
        if differences:
            return {"ok": False, "differences": differences}

    expected_report = read_json(case_dir / "expected_report.json")
    actual_report = read_json(case_dir / "actual_report.json")
    compare_values(extract_key_values(expected_report), extract_key_values(actual_report), "report", differences)

    expected_audit = read_json(case_dir / "expected_audit.json")
    actual_audit = read_json(case_dir / "actual_audit.json")
    compare_release_summary(
        expected_audit["release_dxf_summary"],
        actual_audit["release_dxf_summary"],
        "release_dxf",
        differences,
    )
    compare_release_summary(
        expected_audit["debug_dxf_summary"],
        actual_audit["debug_dxf_summary"],
        "debug_dxf",
        differences,
    )
    compare_values(expected_audit["safety_rules"], actual_audit["safety_rules"], "safety_rules", differences)
    if machine.guide_sections == 2 and explicit_dual_input:
        expected_dimension_audit = read_json(
            case_dir / "expected_dimension_definition_point_audit.json"
        )
        actual_dimension_audit = read_json(
            case_dir / "actual_dimension_definition_point_audit.json"
        )
        compare_values(
            expected_dimension_audit["required_roles"],
            actual_dimension_audit["required_roles"],
            "dimension_definition_point_audit.required_roles",
            differences,
        )
        compare_values(
            expected_dimension_audit["release_allowed"],
            actual_dimension_audit["release_allowed"],
            "dimension_definition_point_audit.release_allowed",
            differences,
        )
    if not (case_dir / "actual_preview.png").exists() or (case_dir / "actual_preview.png").stat().st_size == 0:
        differences.append("actual_preview.png was not generated or is empty.")
    return {"ok": not differences, "differences": differences}


def compare_release_summary(expected: dict[str, Any], actual: dict[str, Any], prefix: str, differences: list[str]) -> None:
    for key in (
        "line_count",
        "arc_count",
        "dimension_count",
        "layers",
        "key_arc_radii",
        "PARAM_SLOT_count",
        "SIDE_DERIVED_count",
    ):
        compare_values(expected.get(key), actual.get(key), f"{prefix}.{key}", differences)
    if (
        "SIDE_DERIVED_RELEASE_count" in expected
        or "SIDE_DERIVED_RELEASE_count" in actual
    ):
        compare_values(
            expected.get("SIDE_DERIVED_RELEASE_count"),
            actual.get("SIDE_DERIVED_RELEASE_count"),
            f"{prefix}.SIDE_DERIVED_RELEASE_count",
            differences,
        )
    compare_values(expected.get("extents"), actual.get("extents"), f"{prefix}.extents", differences)
    compare_values(
        expected.get("dimension_measurements"),
        actual.get("dimension_measurements"),
        f"{prefix}.dimension_measurements",
        differences,
    )


def compare_values(expected: Any, actual: Any, path: str, differences: list[str]) -> None:
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        if abs(float(expected) - float(actual)) > TOLERANCE:
            differences.append(f"{path}: expected {expected}, actual {actual}")
        return
    if isinstance(expected, dict) and isinstance(actual, dict):
        keys = sorted(set(expected) | set(actual))
        for key in keys:
            compare_values(expected.get(key), actual.get(key), f"{path}.{key}", differences)
        return
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            differences.append(f"{path}: expected list length {len(expected)}, actual {len(actual)}")
            return
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual)):
            compare_values(expected_item, actual_item, f"{path}[{index}]", differences)
        return
    if expected != actual:
        differences.append(f"{path}: expected {expected!r}, actual {actual!r}")


def update_baseline(
    case_dir: Path,
    result: dict[str, Any],
    change_reason: str,
    approved_by: str,
    approved_date: str,
    template_version: str | None,
    approve_high_risk: bool,
) -> dict[str, Any]:
    machine_id = result["machine_id"]
    old_report = read_json_if_exists(case_dir / "expected_report.json")
    old_audit = read_json_if_exists(case_dir / "expected_audit.json")
    actual_report = read_json(case_dir / "actual_report.json")
    actual_audit = read_json(case_dir / "actual_audit.json")
    old_template_summary = None if old_audit is None else old_audit.get("template_geometry_summary")
    new_template_summary = actual_audit.get("template_geometry_summary")
    change_report = build_template_change_report(
        machine_id=machine_id,
        old_report=old_report,
        new_report=actual_report,
        old_template_summary=old_template_summary,
        new_template_summary=new_template_summary,
        change_reason=change_reason,
    )
    change_report_path = case_dir / "template_change_report.json"
    write_json(change_report_path, change_report)

    blocking_reasons = []
    if change_report["risk_level"] == "high_risk_change" and not approve_high_risk:
        blocking_reasons.append(
            "High-risk template or baseline change detected; rerun with --approve-high-risk after manual review."
        )
    if not result["generation_ok"]:
        blocking_reasons.extend(result.get("generation_errors", []))
    if blocking_reasons:
        return {"updated": False, "blocking_reasons": blocking_reasons, "template_change_report": str(change_report_path)}

    for _, (expected_name, actual_name) in ARTIFACTS.items():
        shutil.copy2(case_dir / actual_name, case_dir / expected_name)
    actual_dimension_audit = (
        case_dir / "actual_dimension_definition_point_audit.json"
    )
    if actual_dimension_audit.exists():
        shutil.copy2(
            actual_dimension_audit,
            case_dir / "expected_dimension_definition_point_audit.json",
        )
    update_template_meta(
        load_machine_config(machine_id),
        change_reason=change_reason,
        approved_by=approved_by,
        approved_date=approved_date,
        explicit_version=template_version,
    )
    return {"updated": True, "blocking_reasons": [], "template_change_report": str(change_report_path)}


def build_template_change_report(
    machine_id: str,
    old_report: dict[str, Any] | None,
    new_report: dict[str, Any],
    old_template_summary: dict[str, Any] | None,
    new_template_summary: dict[str, Any],
    change_reason: str,
) -> dict[str, Any]:
    old_core = None if old_report is None else extract_key_values(old_report)
    new_core = extract_key_values(new_report)
    changed_dimensions = changed_dimension_rows(
        [] if old_template_summary is None else old_template_summary.get("dimension_measurements", []),
        new_template_summary.get("dimension_measurements", []),
    )
    report = {
        "machine_id": machine_id,
        "change_reason": change_reason,
        "old_template_sha256": None if old_template_summary is None else old_template_summary.get("sha256"),
        "new_template_sha256": new_template_summary.get("sha256"),
        "old_geometry_summary": old_template_summary,
        "new_geometry_summary": new_template_summary,
        "changed_dimensions": changed_dimensions,
        "changed_layers": changed_simple(
            None if old_template_summary is None else old_template_summary.get("layers"),
            new_template_summary.get("layers"),
        ),
        "changed_entity_counts": changed_simple(
            None if old_template_summary is None else old_template_summary.get("entity_counts"),
            new_template_summary.get("entity_counts"),
        ),
        "changed_extents": changed_simple(
            None if old_template_summary is None else old_template_summary.get("extents"),
            new_template_summary.get("extents"),
        ),
        "affects_PARAM_SLOT": core_changed(old_core, new_core, "slot_width") or core_changed(old_core, new_core, "R_form"),
        "affects_fixed_template_dimensions": core_changed(old_core, new_core, "fixed_template_dimensions"),
        "affects_release_output": old_core is None or old_core != new_core,
    }
    report["risk_reasons"] = risk_reasons(report, old_core, new_core)
    report["risk_level"] = "high_risk_change" if report["risk_reasons"] else "low_risk_change"
    return report


def changed_dimension_rows(old_rows: list[dict[str, Any]], new_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not old_rows:
        return [{"initial_baseline": True, "new_dimension_count": len(new_rows)}]
    changed = []
    if len(old_rows) != len(new_rows):
        changed.append({"dimension_count": {"old": len(old_rows), "new": len(new_rows)}})
    for index, (old, new) in enumerate(zip(old_rows, new_rows)):
        local: list[str] = []
        compare_values(old, new, f"dimension[{index}]", local)
        if local:
            changed.append({"index": index, "old": old, "new": new, "differences": local})
    return changed[:100]


def changed_simple(old: Any, new: Any) -> dict[str, Any] | None:
    differences: list[str] = []
    compare_values(old, new, "value", differences)
    return None if not differences else {"old": old, "new": new, "differences": differences[:50]}


def risk_reasons(report: dict[str, Any], old_core: dict[str, Any] | None, new_core: dict[str, Any]) -> list[str]:
    reasons = []
    if old_core is None:
        return reasons
    for key in HIGH_RISK_KEYS:
        if old_core.get(key) != new_core.get(key):
            reasons.append(f"{key} changed: {old_core.get(key)} -> {new_core.get(key)}")
    for item in report["changed_dimensions"]:
        payload = json.dumps(item, ensure_ascii=False)
        for value in HIGH_RISK_NUMBERS:
            if str(int(value)) in payload or f"{value:.1f}" in payload or f"R{int(value)}" in payload:
                reasons.append(f"High-risk fixed dimension token changed near {value:g}.")
                break
    if core_changed(old_core, new_core, "lower_cavity_notch_opening"):
        reasons.append("lower wheel notch safety output changed.")
    return sorted(set(reasons))


def update_template_meta(
    machine: MachineConfig,
    change_reason: str,
    approved_by: str,
    approved_date: str,
    explicit_version: str | None,
) -> None:
    path = machine.section_template_path.parent / "template_meta.json"
    old = read_json_if_exists(path) or {}
    version = explicit_version or ("v1.0.0" if not old else bump_patch_version(str(old.get("template_version", "v1.0.0"))))
    payload = {
        "machine_id": machine.machine_id,
        "template_version": version,
        "source_template_file": "; ".join(path.name for path in sorted({machine.section_template_path, machine.side_template_path})),
        "sha256": template_sha256(machine),
        "change_reason": change_reason,
        "approved_by": approved_by,
        "approved_date": approved_date,
    }
    write_json(path, payload)


def template_sha256(machine: MachineConfig) -> str:
    digest = hashlib.sha256()
    for path in sorted({machine.section_template_path, machine.side_template_path}):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def bump_patch_version(version: str) -> str:
    if not version.startswith("v"):
        return version
    parts = version[1:].split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return version
    parts[2] = str(int(parts[2]) + 1)
    return "v" + ".".join(parts)


def find_inspection_check(inspection: dict[str, Any], name: str) -> dict[str, Any] | None:
    for check in inspection.get("checks", []):
        if check.get("name") == name:
            return check
    return None


def core_changed(old_core: dict[str, Any] | None, new_core: dict[str, Any], key: str) -> bool:
    if old_core is None:
        return False
    differences: list[str] = []
    compare_values(old_core.get(key), new_core.get(key), key, differences)
    return bool(differences)


def _machine_positions(machine_id: str) -> list[str]:
    return list(load_machine_config(machine_id).wheel_positions)


def point_payload(point: Any) -> list[float]:
    return [rounded(float(point.x)), rounded(float(point.y)), rounded(float(point.z))]


def rounded(value: float | None) -> float | None:
    return None if value is None else round(float(value), 6)


def dimension_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    points = row.get("definition_points", {})
    first = points.get("defpoint") or points.get("defpoint2") or [0, 0, 0]
    return (row.get("layer", ""), row.get("text", ""), row.get("measurement"), first[0], first[1])


def merge_extents(target: dict[str, float | None], source: dict[str, float | None]) -> None:
    if source["min_x"] is None:
        return
    for key, func in (("min_x", min), ("min_y", min), ("max_x", max), ("max_y", max)):
        target[key] = source[key] if target[key] is None else func(float(target[key]), float(source[key]))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_json_if_exists(path: Path) -> dict[str, Any] | None:
    return read_json(path) if path.exists() else None


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

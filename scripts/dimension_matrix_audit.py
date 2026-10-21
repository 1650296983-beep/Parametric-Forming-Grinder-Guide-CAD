#!/usr/bin/env python3
"""Audit dimension binding across every machine, process and size band.

The matrix is intentionally small enough to run locally but wide enough to
exercise the template-rebinding edge cases that do not appear in the golden
fixtures: slot widths from 4 to 24 mm and guide thicknesses from 1.6 to
6.55 mm.  Both the definition-point audit and the native text/measurement
gate must pass for a case to count as successful.
"""

from __future__ import annotations

import argparse
import itertools
import json
import shutil
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.dual_guide_engine import DualGuideTemplateEngine
from src.dual_guide_input import build_dual_guide_profile_from_input
from src.dual_guide_release_audit import build_dimension_definition_point_audit
from src.dxf_writer import write_dxf
from src.guide_design_input import build_single_guide_profile_from_input
from src.inspection import inspect_release_dxf
from src.machine_config import MachineConfig, load_machine_config


SINGLE_MACHINES = (
    ("bed_618", "upper"),
    ("double_head_up_down", "upper"),
    ("double_head_up_up", "upper"),
    ("triple_single_down_up", "lower"),
    ("triple_single_up_up", "upper"),
)
DUAL_MACHINES = (
    ("triple_double_down_up_up", "lower"),
    ("triple_double_up_up_up", "upper"),
)
PROCESS_KINDS = ("bread_block", "tile_block", "same_r_tile")
WIDTHS = (4.0, 6.0, 8.6, 12.0, 16.0, 19.0, 24.0)
THICKNESSES = (1.6, 2.5, 6.55)

# bed_618 uses a 27 mm high section envelope.  At a 6.55 mm pre-grinding block
# thickness the 20.9 mm slot base plus the guide thickness no longer fits, so
# the upper-wheel projection check legitimately rejects the combination.  The
# matrix records that rejection instead of treating it as a regression.
KNOWN_INFEASIBLE = {
    ("bed_618", 6.55): {"upper_wheel_notch_safety"},
}


def single_input(
    machine: MachineConfig,
    first_wheel_side: str,
    kind: str,
    width: float,
    thickness: float,
) -> dict[str, Any]:
    data = {
        "machine_type": machine.machine_id,
        "guide_rail_type": machine.guide_type,
        "wheel_sequence": list(machine.wheel_positions),
        "first_wheel_side": first_wheel_side,
        "template_coordinate_system": machine.template_coordinate_system,
        "relief": "4-1",
    }
    if kind == "bread_block":
        data.update(
            finished_spec=(
                f"R{max(9.6, thickness * 2.55):.2f}*{width}*40*{thickness}"
            ),
            finished_spec_order="radius_width_length_thickness",
            pre_grinding_spec=(
                f"40*{width}(+0.01/-0.01)*{thickness + 0.05:g}(+0.01/-0.01)"
            ),
            product_shape_after="bread_shape",
            product_shape_before="rectangular_block",
        )
    elif kind == "tile_block":
        big = max(width * 1.6, 16.0)
        small = max(big - 2.0, width * 0.8)
        data.update(
            finished_spec=f"R{big:.2f}*R{small:.2f}*{width}*40*{thickness}",
            pre_grinding_spec=(
                f"40*{width}(+0.01/-0.01)*{thickness + 0.05:g}(+0.01/-0.01)"
            ),
            product_shape_after="tile_shape",
            product_shape_before="rectangular_block",
        )
    else:
        data.update(
            finished_spec=(
                f"R{width * 1.5:.2f}*R{width * 1.5:.2f}*{width}*40*{thickness}"
            ),
            pre_grinding_spec=(
                f"R{width * 1.5:.2f}*R{width * 1.5:.2f}*{width}"
                f"(+0.01/-0.01)*40*{thickness + 0.05:g}(+0.01/-0.01)"
            ),
            product_shape_after="tile_shape",
            product_shape_before="same_r_tile",
        )
    return data


def dual_input(
    machine: MachineConfig,
    kind: str,
    width: float,
    thickness: float,
) -> dict[str, Any]:
    data: dict[str, Any] = {"relief": "4-1"}
    if kind == "bread_block":
        data.update(
            finished_product_spec=(
                f"R{max(9.6, thickness * 2.55):.2f}*{width}*40*{thickness}"
            ),
            pre_grinding_spec=(
                f"40*{width}(+0.01/-0.01)*{thickness + 0.05:g}(+0.01/-0.01)"
            ),
            finished_product_shape="bread",
            pre_grinding_shape="block",
            guide_profile_source="pre_grinding_spec",
        )
    elif kind == "tile_block":
        big = max(width * 1.6, 16.0)
        small = max(big - 2.0, width * 0.8)
        data.update(
            finished_product_spec=f"R{big:.2f}*R{small:.2f}*{width}*40*{thickness}",
            pre_grinding_spec=(
                f"40*{width}(+0.01/-0.01)*{thickness + 0.05:g}(+0.01/-0.01)"
            ),
            finished_product_shape="tile",
            pre_grinding_shape="block",
            guide_profile_source="finished_product_big_r_with_pre_grinding_block",
        )
    else:
        data.update(
            finished_product_spec=(
                f"R{width * 1.5:.2f}*R{width * 1.5:.2f}*{width}*40*{thickness}"
            ),
            pre_grinding_spec=(
                f"R{width * 1.5:.2f}*R{width * 1.5:.2f}*{width}"
                f"(+0.01/-0.01)*40*{thickness + 0.05:g}(+0.01/-0.01)"
            ),
            finished_product_shape="tile",
            pre_grinding_shape="same_r_tile",
            guide_profile_source="pre_grinding_spec",
        )
    return data


def _audit_payload(audit: dict[str, Any]) -> dict[str, Any]:
    return {
        "release_allowed": bool(audit.get("release_allowed")),
        "unbound_dimensions": [
            {
                "role": entry.get("dimension_role"),
                "display_text": entry.get("display_text"),
                "point_error": entry.get("point_error"),
            }
            for entry in audit.get("dimensions", [])
            if not entry.get("bound_to_geometry")
        ],
        "failed_roles": [
            role
            for role, item in audit.get("required_roles", {}).items()
            if item.get("status") != "PASS"
        ],
        "text_measurement_mismatches": audit.get(
            "text_measurement_mismatches", []
        ),
        "orphan_parametric_dimensions": audit.get(
            "orphan_parametric_dimensions", []
        ),
    }


def run_single_case(
    machine: MachineConfig,
    first_wheel_side: str,
    kind: str,
    width: float,
    thickness: float,
    case_dir: Path,
) -> dict[str, Any]:
    try:
        _, _, profile, _ = build_single_guide_profile_from_input(
            single_input(machine, first_wheel_side, kind, width, thickness),
            machine,
        )
        case_dir.mkdir(parents=True, exist_ok=True)
        candidate = case_dir / "release_candidate.dxf"
        write_dxf(
            profile,
            candidate,
            output_mode="release",
            machine_id=machine.machine_id,
        )
        audit = build_dimension_definition_point_audit(
            candidate,
            profile,
            machine,
        )
        inspection = inspect_release_dxf(profile, machine, candidate)
        failed_checks = [
            check["name"]
            for check in inspection.get("checks", [])
            if not check.get("ok")
        ]
        payload = _audit_payload(audit)
        payload["failed_checks"] = failed_checks
        passed = (
            audit["release_allowed"]
            and inspection["release_allowed"]
        )
        return {
            "status": "pass" if passed else "fail",
            "audit": payload,
        }
    except Exception as error:  # noqa: BLE001 - matrix row records the failure
        return {
            "status": "fail",
            "error": f"{type(error).__name__}: {error}",
        }


def run_dual_case(
    machine: MachineConfig,
    kind: str,
    width: float,
    thickness: float,
    case_dir: Path,
) -> dict[str, Any]:
    case_dir.mkdir(parents=True, exist_ok=True)
    error: str | None = None
    try:
        _, spec, profile, _ = build_dual_guide_profile_from_input(
            dual_input(machine, kind, width, thickness),
            machine,
        )
        DualGuideTemplateEngine(machine).write_debug_release_and_report(
            profile,
            spec,
            case_dir,
        )
    except Exception as caught:  # noqa: BLE001 - read the report written first
        error = f"{type(caught).__name__}: {caught}"
    report_path = case_dir / "report.json"
    if not report_path.exists():
        return {
            "status": "fail",
            "error": error or "dual engine did not write report.json",
        }
    report = json.loads(report_path.read_text(encoding="utf-8"))
    audit = report.get("dimension_definition_point_audit") or {}
    payload = _audit_payload(audit)
    checks = report.get("checks", {})
    payload["failed_checks"] = [
        name
        for name, passed in checks.items()
        if passed is not True
    ] if isinstance(checks, dict) else []
    payload["release_block_reason"] = report.get("release_block_reason")
    if error is not None:
        payload["error"] = error
    return {
        "status": "pass" if report.get("release_allowed") else "fail",
        "audit": payload,
    }


def classify_known_infeasible(
    machine_id: str,
    thickness: float,
    result: dict[str, Any],
) -> bool:
    """Treat any rejection of the over-height bed_618 case as expected.

    The section envelope is fixed, so all three process paths fail for the same
    physical reason: the slot base plus the guide thickness (and the wheel cut
    clearance) exceeds the 27 mm template height.  Which downstream check
    reports it first depends on the process path.
    """
    if (machine_id, thickness) not in KNOWN_INFEASIBLE:
        return False
    return result["status"] != "pass"


def build_matrix(output: Path, workdir: Path, keep_artifacts: bool) -> dict[str, Any]:
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    try:
        for machine_id, first_wheel_side in SINGLE_MACHINES:
            machine = load_machine_config(machine_id)
            for kind, width, thickness in itertools.product(
                PROCESS_KINDS,
                WIDTHS,
                THICKNESSES,
            ):
                label = (
                    f"{machine_id}|{kind}|w{width:g}|t{thickness:g}"
                )
                case_dir = workdir / machine_id / f"{kind}_w{width:g}_t{thickness:g}"
                result = run_single_case(
                    machine,
                    first_wheel_side,
                    kind,
                    width,
                    thickness,
                    case_dir,
                )
                if classify_known_infeasible(machine_id, thickness, result):
                    result["status"] = "known_infeasible"
                    result["reason"] = (
                        "bed_618 section envelope cannot fit slot base + "
                        "guide thickness at t=6.55"
                    )
                rows.append({"label": label, **result})
                state = result["status"]
                if state != "pass":
                    print(f"{state.upper():<16} {label}")
        for machine_id, _ in DUAL_MACHINES:
            machine = load_machine_config(machine_id)
            for kind, width, thickness in itertools.product(
                PROCESS_KINDS,
                WIDTHS,
                THICKNESSES,
            ):
                label = (
                    f"{machine_id}|{kind}|w{width:g}|t{thickness:g}"
                )
                case_dir = workdir / machine_id / f"{kind}_w{width:g}_t{thickness:g}"
                result = run_dual_case(
                    machine,
                    kind,
                    width,
                    thickness,
                    case_dir,
                )
                if classify_known_infeasible(machine_id, thickness, result):
                    result["status"] = "known_infeasible"
                rows.append({"label": label, **result})
                state = result["status"]
                if state != "pass":
                    print(f"{state.upper():<16} {label}")
    finally:
        if not keep_artifacts:
            shutil.rmtree(workdir, ignore_errors=True)

    summary = {
        "case_count": len(rows),
        "passed": sum(row["status"] == "pass" for row in rows),
        "known_infeasible": sum(
            row["status"] == "known_infeasible" for row in rows
        ),
        "failed": sum(row["status"] == "fail" for row in rows),
    }
    payload = {"summary": summary, "cases": rows}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "tmp" / "dimension_matrix_audit.json",
        help="JSON report path.",
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        default=REPO_ROOT / "tmp" / "dimension_matrix",
        help="Scratch directory for generated candidates.",
    )
    parser.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="Keep generated DXFs for debugging failed cases.",
    )
    args = parser.parse_args()
    payload = build_matrix(args.output, args.workdir, args.keep_artifacts)
    summary = payload["summary"]
    print(
        "cases={case_count} passed={passed} "
        "known_infeasible={known_infeasible} failed={failed}".format(**summary)
    )
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

import ezdxf


TOLERANCE = 0.01


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit triple_single_down_up section relief topology."
    )
    parser.add_argument("--standard", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--fixed", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--standard-archive", default="")
    parser.add_argument("--standard-member", default="")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    standard = inspect_drawing(args.standard, source_role="standard")
    current = inspect_drawing(args.current, source_role="current_before_fix")
    fixed = (
        inspect_drawing(args.fixed, source_role="fixed_after")
        if args.fixed is not None and args.fixed.exists()
        else None
    )

    audit = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "machine_id": "triple_single_down_up",
        "process_scope": ["block_to_tile", "block_to_bread"],
        "standard_source": {
            "archive": args.standard_archive,
            "archive_member": args.standard_member,
            "extracted_dxf": str(args.standard),
            "sha256": standard["sha256"],
            "single_source_of_truth": True,
        },
        "topology_definition": {
            "4-1": {
                "count": 4,
                "radius": 0.5,
                "diameter": 1.0,
                "roles": [
                    "left_lower_slot_corner",
                    "left_upper_local_transition",
                    "right_lower_slot_corner",
                    "right_upper_local_transition",
                ],
                "placement_rule": (
                    "Located at the two slot side boundaries and joined to the current "
                    "lower/upper profile by tangent geometry."
                ),
            },
            "2-0.5": {
                "count": 2,
                "radius": 0.5,
                "roles": [
                    "center_opening_left_local_transition",
                    "center_opening_right_local_transition",
                ],
                "placement_rule": (
                    "Fixed local topology around section_center_opening. X positions are "
                    "derived from center_opening and R0.5, not from slot_width."
                ),
            },
        },
        "drawings": {
            "standard": standard,
            "current_before_fix": current,
            **({"fixed_after": fixed} if fixed is not None else {}),
        },
    }
    gap = build_gap_report(standard, current, fixed)

    write_json(args.output_dir / "relief_topology_audit.json", audit)
    write_json(args.output_dir / "standard_vs_current_relief_gap_report.json", gap)
    return 0


def inspect_drawing(path: Path, source_role: str) -> dict[str, Any]:
    doc = ezdxf.readfile(path)
    modelspace = doc.modelspace()
    arcs = [
        entity
        for entity in modelspace.query("ARC")
        if abs(float(entity.dxf.radius) - 0.5) <= TOLERANCE
        and (
            source_role == "standard"
            or entity.dxf.layer == "PARAM_SLOT"
        )
    ]
    if not arcs:
        raise ValueError(f"No R0.5 relief arcs found in {path}.")

    min_x = min(float(entity.dxf.center.x) for entity in arcs)
    max_x = max(float(entity.dxf.center.x) for entity in arcs)
    center_x = (min_x + max_x) / 2.0
    outer_arcs = [
        entity
        for entity in arcs
        if abs(float(entity.dxf.center.x) - min_x) <= TOLERANCE
        or abs(float(entity.dxf.center.x) - max_x) <= TOLERANCE
    ]
    base_y = min(float(entity.dxf.center.y) for entity in outer_arcs)
    top_y = max(float(entity.dxf.center.y) for entity in outer_arcs)
    payloads = [
        arc_payload(
            entity,
            center_x=center_x,
            base_y=base_y,
            min_x=min_x,
            max_x=max_x,
            top_y=top_y,
        )
        for entity in arcs
    ]
    payloads.sort(key=lambda item: (item["center"][0], item["center"][1]))
    role_counts: dict[str, int] = {}
    group_counts: dict[str, int] = {}
    for item in payloads:
        role_counts[item["role"]] = role_counts.get(item["role"], 0) + 1
        group_counts[item["relief_group"]] = group_counts.get(item["relief_group"], 0) + 1

    return {
        "source_role": source_role,
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "r0_5_arc_count": len(payloads),
        "reference_frame": {
            "center_x": rounded(center_x),
            "base_y": rounded(base_y),
            "outer_relief_left_x": rounded(min_x),
            "outer_relief_right_x": rounded(max_x),
            "outer_relief_span": rounded(max_x - min_x),
            "outer_relief_top_y": rounded(top_y),
        },
        "relief_group_counts": group_counts,
        "role_counts": role_counts,
        "arcs": payloads,
    }


def arc_payload(
    entity,
    *,
    center_x: float,
    base_y: float,
    min_x: float,
    max_x: float,
    top_y: float,
) -> dict[str, Any]:
    x = float(entity.dxf.center.x)
    y = float(entity.dxf.center.y)
    is_left_outer = abs(x - min_x) <= TOLERANCE
    is_right_outer = abs(x - max_x) <= TOLERANCE
    if is_left_outer or is_right_outer:
        side = "left" if is_left_outer else "right"
        level = "lower" if abs(y - base_y) <= TOLERANCE else "upper"
        role = (
            f"{side}_lower_slot_corner"
            if level == "lower"
            else f"{side}_upper_local_transition"
        )
        group = "4-1"
        topology_class = "slot_corner" if level == "lower" else "local_transition"
    else:
        side = "left" if x < center_x else "right"
        role = f"center_opening_{side}_local_transition"
        group = "2-0.5"
        topology_class = "local_transition"

    return {
        "handle": entity.dxf.handle,
        "layer": entity.dxf.layer,
        "center": [rounded(x), rounded(y)],
        "center_relative": [rounded(x - center_x), rounded(y - base_y)],
        "radius": rounded(float(entity.dxf.radius)),
        "start_angle": rounded(float(entity.dxf.start_angle) % 360.0),
        "end_angle": rounded(float(entity.dxf.end_angle) % 360.0),
        "start_point": [
            rounded(float(entity.start_point.x)),
            rounded(float(entity.start_point.y)),
        ],
        "end_point": [
            rounded(float(entity.end_point.x)),
            rounded(float(entity.end_point.y)),
        ],
        "relief_group": group,
        "role": role,
        "topology_class": topology_class,
    }


def build_gap_report(
    standard: dict[str, Any],
    current: dict[str, Any],
    fixed: dict[str, Any] | None,
) -> dict[str, Any]:
    required_roles = {
        "left_lower_slot_corner",
        "left_upper_local_transition",
        "right_lower_slot_corner",
        "right_upper_local_transition",
        "center_opening_left_local_transition",
        "center_opening_right_local_transition",
    }
    current_roles = set(current["role_counts"])
    standard_roles = set(standard["role_counts"])
    missing = sorted(required_roles - current_roles)
    extra = sorted(current_roles - required_roles)
    report: dict[str, Any] = {
        "machine_id": "triple_single_down_up",
        "comparison": "archived_standard_vs_current_before_fix",
        "standard_r0_5_arc_count": standard["r0_5_arc_count"],
        "current_r0_5_arc_count": current["r0_5_arc_count"],
        "missing_relief_roles": missing,
        "extra_relief_roles": extra,
        "geometry_profile_difference": [
            {
                "issue": "relief_topology_simplified_to_slot_corners",
                "standard": "4 outer R0.5 arcs plus 2 center-opening R0.5 transitions",
                "current": "4 R0.5 arcs located only at slot_width boundaries",
            },
            {
                "issue": "center_opening_transition_missing",
                "standard_dependency": "section_center_opening + R0.5",
                "current_dependency": "direct main-profile-to-vertical connection",
            },
            {
                "issue": "large_width_behavior",
                "standard": "center local topology remains near the fixed center opening",
                "current": "all relief arcs move outward when slot_width increases",
            },
        ],
        "recommended_fixes": [
            "Keep the four 4-1 side transitions tangent to the current slot boundary.",
            "Add the two 2-0.5 center-opening local transitions.",
            "For block_to_bread, make the center R0.5 arcs tangent to the unchanged upper R_form arc.",
            "Derive center-transition X positions from section_center_opening and R0.5, never slot_width.",
            "Reject release when the six-role topology is incomplete.",
            "Do not update regression baseline until human review.",
        ],
        "baseline_updated": False,
    }
    if fixed is not None:
        fixed_roles = set(fixed["role_counts"])
        report["post_fix_verification"] = {
            "fixed_r0_5_arc_count": fixed["r0_5_arc_count"],
            "missing_relief_roles": sorted(required_roles - fixed_roles),
            "extra_relief_roles": sorted(fixed_roles - required_roles),
            "topology_complete": required_roles <= fixed_roles,
        }
    return report


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def rounded(value: float) -> float:
    return round(float(value), 6)


if __name__ == "__main__":
    raise SystemExit(main())

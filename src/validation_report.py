from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .block_geometry import BlockGuideSection
from .geometry import TileSection
from .dimension_precision import build_dimension_precision_file_audit
from .inspection import inspect_release_dxf
from .machine_config import MachineConfig
from .global_rules import WHEEL_CUT_IN_RATIO
from .release_entity_audit import build_parametric_duplicate_audit
from .spec_parser import BlockSpec, FinishedSpec
from .side_view import build_side_view_geometry
from .side_view_config import SideViewTemplateConfig


WORKFLOW_STEPS = (
    "read_config",
    "parse_product_spec",
    "derive_process_parameters",
    "load_machine_template",
    "remove_old_parametric_geometry",
    "rebuild_parametric_slot",
    "rebuild_dimensions",
    "generate_debug_dxf",
    "generate_release_dxf_candidate",
    "render_preview_png",
    "run_validation",
    "write_report_json",
    "promote_release_dxf_after_validation",
)


def write_validation_report_json(
    profile: TileSection | BlockGuideSection,
    parsed_spec: FinishedSpec | BlockSpec,
    machine: MachineConfig,
    debug_dxf: str | Path,
    release_dxf: str | Path,
    preview_png: str | Path,
    report_path: str | Path,
    release_inspection_dxf: str | Path | None = None,
    input_rule: dict[str, Any] | None = None,
    dimension_definition_point_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = build_validation_report_payload(
        profile,
        parsed_spec,
        machine,
        debug_dxf=debug_dxf,
        release_dxf=release_dxf,
        preview_png=preview_png,
        release_inspection_dxf=release_inspection_dxf,
        input_rule=input_rule,
        dimension_definition_point_audit=dimension_definition_point_audit,
    )
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def build_validation_report_payload(
    profile: TileSection | BlockGuideSection,
    parsed_spec: FinishedSpec | BlockSpec,
    machine: MachineConfig,
    debug_dxf: str | Path,
    release_dxf: str | Path,
    preview_png: str | Path,
    release_inspection_dxf: str | Path | None = None,
    input_rule: dict[str, Any] | None = None,
    dimension_definition_point_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    guide = profile.guide_spec
    side = build_side_view_geometry(
        profile,
        template=SideViewTemplateConfig(wheel_radius=machine.wheel_radius),
        layout=machine.side_layout,
    )  # type: ignore[arg-type]
    inspection_path = Path(release_inspection_dxf or release_dxf)
    if inspection_path.exists():
        release_inspection = inspect_release_dxf(profile, machine, inspection_path)
        duplicate_entity_audit = build_parametric_duplicate_audit(
            inspection_path
        )
        dimension_precision_audit = build_dimension_precision_file_audit(
            inspection_path
        )
    else:
        release_inspection = {
            "dxf_path": str(inspection_path),
            "release_allowed": False,
            "checks": [
                {
                    "name": "release_candidate_exists",
                    "ok": False,
                    "details": {"path": str(inspection_path)},
                }
            ],
        }
        duplicate_entity_audit = {
            "audited_entity_count": 0,
            "duplicate_groups": [],
            "release_allowed": False,
        }
        dimension_precision_audit = {
            "checked_dimension_count": 0,
            "invalid_dimensions": [],
            "release_allowed": False,
        }
    required_dimensions = _required_dimension_roles_payload(release_inspection)
    dual_spec_validation = _dual_spec_validation_payload(profile, input_rule)

    release_allowed = bool(release_inspection["release_allowed"])
    release_allowed = release_allowed and bool(
        duplicate_entity_audit["release_allowed"]
    )
    release_allowed = release_allowed and bool(
        dimension_precision_audit["release_allowed"]
    )
    if dimension_definition_point_audit is not None:
        release_allowed = release_allowed and bool(
            dimension_definition_point_audit.get("release_allowed")
        )
    release_allowed = release_allowed and bool(
        dual_spec_validation["all_pass"]
    )

    return {
        "workflow": list(WORKFLOW_STEPS),
        "paths": {
            "debug_dxf": str(debug_dxf),
            "release_dxf": str(release_dxf),
            "release_inspection_dxf": str(inspection_path),
            "preview_png": str(preview_png),
        },
        "machine": {
            "machine_id": machine.machine_id,
            "machine_name": machine.machine_name,
            "guide_length": machine.guide_length,
            "wheel_positions": list(machine.wheel_positions),
            "guide_sections": machine.guide_sections,
            "wheel_radius": machine.wheel_radius,
            "side_fixed_spans": list(machine.side_fixed_spans),
            "section_template_path": str(machine.section_template_path),
            "side_template_path": str(machine.side_template_path),
        },
        "input_rule": input_rule,
        "product_spec": _product_spec_payload(parsed_spec, profile),
        "process_parameters": {
            "R_form": _r_form_payload(profile),
            "slot_width": _slot_width_payload(profile),
            "guide_thickness": {
                "formula": (
                    "preform_block_thickness_mid + global_thickness_clearance"
                    if (
                        isinstance(profile, BlockGuideSection)
                        or isinstance(profile, TileSection)
                        and profile.preform_block_spec is not None
                    )
                    else "preform_thickness_mid + thickness_clearance_mid"
                ),
                "base_thickness": guide.finished_thickness,
                "thickness_clearance_mid": guide.thickness_clearance_mid_value,
                "result": guide.guide_thickness,
            },
            "relief": {
                "relief_count": guide.relief.relief_count,
                "relief_size": guide.relief.relief_size,
                "relief_label": guide.relief.relief_label,
                "topology": _relief_topology_payload(profile, machine),
            },
        },
        "side_view": {
            "slot_base_height": side.derived.slot_base_height,
            "side_cut_in_allowance": side.derived.side_cut_in_allowance,
            "side_projected_slot_height": _side_projected_slot_height_payload(profile, machine),
            "guide_outer_height": side.derived.guide_outer_height,
            "guide_thickness": side.derived.guide_thickness,
            "wheel_cut_allowance": side.derived.wheel_cut_allowance,
            "side_clearance_height": _side_clearance_height_payload(profile, side),
            "wheel_notch": _wheel_notch_payload(profile, machine, side),
        },
        "fixed_template_dimensions": {
            "section": {
                "outer_width": guide.outer_width,
                "outer_height": guide.outer_height,
                "slot_base_height": guide.slot_base_height,
                "center_opening": guide.center_opening,
                "slot_center_offset": guide.slot_center_offset,
            },
            "side": {
                "fixed_spans": list(machine.side_fixed_spans),
                "guide_length": machine.guide_length,
                "wheel_radius": side.template.wheel_radius,
            },
        },
        "required_dimension_roles": required_dimensions,
        "dual_spec_validation": dual_spec_validation,
        "inspection": release_inspection,
        "dimension_definition_point_audit": dimension_definition_point_audit,
        "parametric_duplicate_audit": duplicate_entity_audit,
        "dimension_precision_audit": dimension_precision_audit,
        "release_allowed": release_allowed,
    }


def _dual_spec_validation_payload(
    profile: TileSection | BlockGuideSection,
    input_rule: dict[str, Any] | None,
) -> dict[str, Any]:
    if not input_rule or "groove_profile" not in input_rule:
        return {
            "applicable": False,
            "checks": [],
            "all_pass": True,
        }
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, **details: Any) -> None:
        checks.append({"name": name, "ok": bool(ok), "details": details})

    add(
        "separate_pre_and_finished_specs",
        bool(input_rule.get("pre_grinding_spec"))
        and bool(input_rule.get("finished_spec")),
        pre_grinding_spec=input_rule.get("pre_grinding_spec"),
        finished_spec=input_rule.get("finished_spec"),
    )
    add(
        "centralized_groove_decision",
        input_rule.get("groove_profile")
        in {"rectangular_groove", "flat_arc_groove", "same_r_tile_groove"},
        groove_profile=input_rule.get("groove_profile"),
        confidence=input_rule.get("confidence"),
    )
    add(
        "no_unresolved_warnings",
        not input_rule.get("warnings"),
        warnings=input_rule.get("warnings", []),
    )
    wheel_sequence = input_rule.get("wheel_sequence") or []
    wheel_side_map = {"上": "upper", "下": "lower", "左": "left", "右": "right"}
    configured_first_side = (
        wheel_side_map.get(str(wheel_sequence[0])) if wheel_sequence else None
    )
    add(
        "first_wheel_side_matches_machine_sequence",
        configured_first_side is not None
        and input_rule.get("first_wheel_side") == configured_first_side,
        wheel_sequence=wheel_sequence,
        first_wheel_side=input_rule.get("first_wheel_side"),
        expected_first_wheel_side=configured_first_side,
    )

    if (
        isinstance(profile, TileSection) and profile.preform_block_spec is not None
    ) or (
        isinstance(profile, BlockGuideSection) and profile.finished_spec is not None
    ):
        preform = profile.preform_block_spec
        guide = profile.guide_spec
        finished = (
            profile.finished_spec
            if isinstance(profile, BlockGuideSection)
            else profile.finished_spec
        )
        add(
            "slot_width_uses_pre_grinding_nominal_width",
            abs(guide.chord_width - preform.width) <= 1e-9,
            guide_chord_width=guide.chord_width,
            pre_grinding_width=preform.width,
            finished_width=finished.chord_width,
        )
        add(
            "slot_width_uses_pre_grinding_tolerance",
            abs(guide.preform_tolerance.upper - float(preform.width_tolerance_upper)) <= 1e-9
            and abs(guide.preform_tolerance.lower - float(preform.width_tolerance_lower)) <= 1e-9,
            guide_tolerance=[guide.preform_tolerance.upper, guide.preform_tolerance.lower],
            pre_grinding_tolerance=[preform.width_tolerance_upper, preform.width_tolerance_lower],
        )
        add(
            "guide_thickness_uses_pre_grinding_thickness",
            abs(guide.finished_thickness - preform.thickness_mid) <= 1e-9,
            guide_base_thickness=guide.finished_thickness,
            pre_grinding_thickness_mid=preform.thickness_mid,
            finished_thickness=finished.finished_thickness,
        )
        expected_radius = (
            finished.R_outer_finished
            if finished.finished_shape == "bread"
            else max(
                finished.R_outer_finished,
                finished.R_inner_finished,
            )
        )
        if isinstance(profile, BlockGuideSection):
            add(
                "single_R_block_preform_uses_rectangular_groove",
                finished.finished_shape == "bread"
                and input_rule.get("groove_profile") == "rectangular_groove"
                and input_rule.get("arc_radius") is None
                and profile.process_type == "block_to_bread_rectangular",
                process_type=profile.process_type,
                groove_profile=input_rule.get("groove_profile"),
                finished_target_radius=expected_radius,
            )
        else:
            add(
                "arc_radius_uses_finished_spec",
                abs(profile.forming_spec.R_form - expected_radius) <= 1e-9
                and abs(float(input_rule.get("arc_radius")) - expected_radius) <= 1e-9,
                R_form=profile.forming_spec.R_form,
                expected_finished_radius=expected_radius,
            )
            add(
                "double_R_tile_keeps_tile_classification",
                input_rule.get("product_shape_after") == "tile_shape"
                and profile.process_type == "block_to_tile",
                process_type=profile.process_type,
                product_shape_after=input_rule.get("product_shape_after"),
            )
        opposite = {
            "upper": "lower",
            "lower": "upper",
            "left": "right",
            "right": "left",
        }.get(str(input_rule.get("first_wheel_side")))
        if isinstance(profile, TileSection):
            add(
                "arc_surface_follows_first_wheel",
                input_rule.get("arc_side") == input_rule.get("first_wheel_side"),
                first_wheel_side=input_rule.get("first_wheel_side"),
                arc_side=input_rule.get("arc_side"),
            )
            add(
                "arc_center_opposes_first_wheel",
                opposite is not None
                and input_rule.get("arc_center_side") == opposite,
                first_wheel_side=input_rule.get("first_wheel_side"),
                arc_center_side=input_rule.get("arc_center_side"),
                expected_arc_center_side=opposite,
            )
        first_vector = input_rule.get("first_wheel_vector")
        center_vector = input_rule.get("arc_center_vector")
        vectors_opposite = (
            isinstance(first_vector, list)
            and isinstance(center_vector, list)
            and len(first_vector) == 2
            and len(center_vector) == 2
            and all(
                abs(float(first_vector[index]) + float(center_vector[index])) <= 1e-9
                for index in (0, 1)
            )
        )
        if isinstance(profile, TileSection):
            add(
                "template_coordinate_transform_preserves_opposition",
                vectors_opposite,
                template_coordinate_system=input_rule.get("template_coordinate_system"),
                first_wheel_vector=first_vector,
                arc_center_vector=center_vector,
            )

    return {
        "applicable": True,
        "checks": checks,
        "all_pass": all(check["ok"] for check in checks),
    }


def _required_dimension_roles_payload(inspection: dict[str, Any]) -> dict[str, Any]:
    for check in inspection.get("checks", []):
        if check.get("name") == "required_dimension_roles":
            return dict(check.get("details", {}).get("roles", {}))
    return {}


def _relief_topology_payload(
    profile: TileSection | BlockGuideSection,
    machine: MachineConfig,
) -> dict[str, Any]:
    if (
        machine.machine_id == "triple_single_down_up"
        and profile.process_type
        in {"block_to_tile", "block_to_bread", "block_to_bread_rectangular"}
    ):
        return {
            "source": "archived triple_single_down_up standard CAD",
            "total_local_arcs": 6,
            "groups": {
                "4-1": {
                    "count": 4,
                    "radius": profile.guide_spec.relief.relief_size / 2.0,
                    "dependency": "slot side boundaries and current upper/lower profile tangency",
                },
                "2-0.5": {
                    "count": 2,
                    "radius": 0.5,
                    "dependency": "section_center_opening and local profile tangency",
                    "independent_of_slot_width": True,
                },
            },
        }
    return {
        "total_local_arcs": profile.guide_spec.relief.relief_count,
        "groups": {
            "configured_relief": {
                "count": profile.guide_spec.relief.relief_count,
                "radius": profile.guide_spec.relief.relief_size / 2.0,
            }
        },
    }


def _product_spec_payload(
    parsed_spec: FinishedSpec | BlockSpec,
    profile: TileSection | BlockGuideSection,
) -> dict[str, Any]:
    if isinstance(parsed_spec, FinishedSpec):
        payload = {
            "shape": parsed_spec.finished_shape,
            "process_type": profile.process_type,
            "raw_spec": parsed_spec.raw,
            "R_outer_finished": parsed_spec.R_outer_finished,
            "R_inner_finished": (
                None if parsed_spec.finished_shape == "bread" else parsed_spec.R_inner_finished
            ),
            "nominal_chord_width": parsed_spec.chord_width,
            "product_length": parsed_spec.length,
            "finished_thickness": parsed_spec.finished_thickness,
            "thickness_tolerance_upper": parsed_spec.thickness_tolerance_upper,
            "thickness_tolerance_lower": parsed_spec.thickness_tolerance_lower,
            "preform_thickness_mid": parsed_spec.preform_thickness_mid,
            "preform_upper_tol": parsed_spec.chord_width_tolerance_upper,
            "preform_lower_tol": parsed_spec.chord_width_tolerance_lower,
        }
        if (
            isinstance(profile, TileSection) and profile.preform_block_spec is not None
        ) or (
            isinstance(profile, BlockGuideSection) and profile.finished_spec is not None
        ):
            preform = profile.preform_block_spec
            payload["preform_block"] = {
                "raw_spec": preform.raw,
                "length": preform.length,
                "width": preform.width,
                "width_tolerance_upper": preform.width_tolerance_upper,
                "width_tolerance_lower": preform.width_tolerance_lower,
                "thickness": preform.thickness,
                "thickness_tolerance_upper": preform.thickness_tolerance_upper,
                "thickness_tolerance_lower": preform.thickness_tolerance_lower,
                "thickness_mid": preform.thickness_mid,
            }
        return payload
    return {
        "shape": "block",
        "raw_spec": parsed_spec.raw,
        "length": parsed_spec.length,
        "width": parsed_spec.width,
        "thickness": parsed_spec.thickness,
        "length_tolerance_upper": parsed_spec.length_tolerance_upper,
        "length_tolerance_lower": parsed_spec.length_tolerance_lower,
        "width_tolerance_upper": parsed_spec.width_tolerance_upper,
        "width_tolerance_lower": parsed_spec.width_tolerance_lower,
        "thickness_tolerance_upper": parsed_spec.thickness_tolerance_upper,
        "thickness_tolerance_lower": parsed_spec.thickness_tolerance_lower,
    }


def _r_form_payload(profile: TileSection | BlockGuideSection) -> dict[str, Any] | None:
    if isinstance(profile, BlockGuideSection):
        if profile.finished_spec is None:
            return None
        return {
            "formula": "finished single R is the product target only; guide groove follows the rectangular preform envelope",
            "R_outer_finished": profile.finished_spec.R_outer_finished,
            "R_inner_finished": None,
            "result": None,
            "guide_section_arc_radius": None,
            "lower_surface": "plane",
            "upper_surface": "plane",
        }
    if not isinstance(profile, TileSection):
        return None
    spec = profile.finished_spec
    block_to_tile = profile.process_type == "block_to_tile"
    block_to_bread = profile.process_type == "block_to_bread"
    return {
        "formula": (
            (
                "max finished radius on first-wheel side; opposite surface is plane"
                if profile.process_type == "block_to_tile"
                else "max finished radius for upper arc; lower surface is plane"
            )
            if block_to_tile
            else (
                "single finished bread radius for upper arc; lower surface is plane"
                if block_to_bread
                else "max(R_outer_finished, R_inner_finished)"
            )
        ),
        "R_outer_finished": spec.R_outer_finished,
        "R_inner_finished": None if block_to_bread else spec.R_inner_finished,
        "result": profile.forming_spec.R_form,
        "forming_profile_R_outer": profile.forming_profile.params.R_outer,
        "forming_profile_R_inner": (
            None if block_to_tile or block_to_bread else profile.forming_profile.params.R_inner
        ),
        "lower_surface": (
            "R_form_arc"
            if block_to_tile and profile.arc_side == "lower"
            else "plane"
            if block_to_tile or block_to_bread
            else "R_form_arc"
        ),
        "upper_surface": (
            "R_form_arc"
            if not block_to_tile or profile.arc_side == "upper"
            else "plane"
        ),
    }


def _slot_width_payload(profile: TileSection | BlockGuideSection) -> dict[str, Any]:
    guide = profile.guide_spec
    return {
        "formula": "nominal_chord_width + (preform_upper_tol + preform_lower_tol) / 2 + slot_clearance_mid",
        "nominal_chord_width": guide.chord_width,
        "preform_upper_tol": guide.preform_tolerance.upper,
        "preform_lower_tol": guide.preform_tolerance.lower,
        "preform_width_max": guide.product_preform_width_max,
        "preform_width_min": guide.product_preform_width_min,
        "preform_width_mid": guide.product_preform_width_average,
        "preform_width_tolerance_range": _rounded(
            guide.product_preform_width_max - guide.product_preform_width_min
        ),
        "slot_clearance_mid": guide.tolerance_slot_clearance,
        "slot_width_raw": guide.guide_slot_width_raw,
        "machine_precision": 0.01,
        "rounding": "round_half_up_to_0.01",
        "slot_width": guide.guide_slot_width,
        "slot_width_tolerance": guide.slot_width_tolerance,
        "slot_width_range": [_rounded(guide.slot_width_min), _rounded(guide.slot_width_max)],
        "product_width_range": [_rounded(guide.product_preform_width_min), _rounded(guide.product_preform_width_max)],
        "total_clearance_range": [_rounded(guide.total_clearance_min), _rounded(guide.total_clearance_max)],
        "single_side_clearance_range": [_rounded(guide.side_clearance_min), _rounded(guide.side_clearance_max)],
        "uses_tolerance_based_slot_width": guide.use_tolerance_based_slot_width,
    }


def _side_projected_slot_height_payload(profile: TileSection | BlockGuideSection, machine: MachineConfig) -> dict[str, Any]:
    side = build_side_view_geometry(
        profile,
        template=SideViewTemplateConfig(wheel_radius=machine.wheel_radius),
        layout=machine.side_layout,
    )  # type: ignore[arg-type]
    if isinstance(profile, TileSection) and machine.section_style == "triple_single_down_up_flat_arc":
        return {
            "formula": "fixed_slot_base_height",
            "fixed_slot_base_height": profile.guide_spec.slot_base_height,
            "result": profile.guide_spec.slot_base_height,
            "note": "三头机单导轨（下上）侧面不使用 slot_base_height + 0.50；12.0 为固定型腔下沿。",
        }
    if isinstance(profile, TileSection) and machine.section_style == "bed_618_fixed_base":
        return {
            "formula": "fixed_slot_base_height",
            "fixed_slot_base_height": profile.guide_spec.slot_base_height,
            "result": side.derived.side_projected_slot_height,
            "note": "618磨床导轨型腔下沿高度20.9为固定数值；侧面投影不使用 slot_base_height + 0.50。",
        }
    if (
        isinstance(profile, BlockGuideSection)
        and machine.side_layout.block_side_mode == "slot_base_plus_wheel_cut_in"
    ):
        return {
            "formula": "fixed_machine_slot_base_height",
            "fixed_slot_base_height": profile.guide_spec.slot_base_height,
            "wheel_cut_in_formula": "preform_thickness_mid * 0.6",
            "lower_wheel_cut_in": side.derived.wheel_cut_in_depth,
            "upper_wheel_cut_in": side.derived.wheel_cut_allowance,
            "result": side.derived.side_projected_slot_height,
        }
    if (
        isinstance(profile, BlockGuideSection)
        and machine.side_layout.block_side_mode == "fixed_top_gap"
    ):
        return {
            "formula": "guide_outer_height - block_fixed_top_gap - guide_thickness",
            "guide_outer_height": side.derived.guide_outer_height,
            "block_fixed_top_gap": machine.side_layout.block_fixed_top_gap,
            "guide_thickness": profile.guide_spec.guide_thickness,
            "result": side.derived.side_projected_slot_height,
        }
    if isinstance(profile, BlockGuideSection):
        return {
            "formula": "block_side_projected_slot_height",
            "block_side_projected_slot_height": machine.side_layout.block_side_projected_slot_height,
            "result": side.derived.side_projected_slot_height,
        }
    return {
        "formula": "slot_base_height + side_cut_in_allowance",
        "slot_base_height": side.derived.slot_base_height,
        "side_cut_in_allowance": side.derived.side_cut_in_allowance,
        "result": side.derived.side_projected_slot_height,
    }


def _side_clearance_height_payload(profile: TileSection | BlockGuideSection, side) -> dict[str, Any]:
    if isinstance(profile, BlockGuideSection):
        if side.derived.wheel_cut_allowance > 0.0:
            return {
                "formula": "guide_outer_height - slot_base_height - guide_thickness + upper_wheel_cut_in",
                "guide_outer_height": side.derived.guide_outer_height,
                "slot_base_height": side.derived.slot_base_height,
                "guide_thickness": side.derived.guide_thickness,
                "upper_wheel_cut_in": side.derived.wheel_cut_allowance,
                "result": side.derived.side_clearance_height,
            }
        return {
            "formula": "guide_outer_height - side_projected_slot_height - preform_thickness_mid * 0.6",
            "guide_outer_height": side.derived.guide_outer_height,
            "side_projected_slot_height": side.derived.side_projected_slot_height,
            "preform_thickness_mid": profile.block_spec.thickness_mid,
            "result": side.derived.side_clearance_height,
        }
    return {
        "formula": "guide_outer_height - slot_base_height - guide_thickness + wheel_cut_allowance",
        "guide_outer_height": side.derived.guide_outer_height,
        "slot_base_height": side.derived.slot_base_height,
        "guide_thickness": side.derived.guide_thickness,
        "wheel_cut_allowance": side.derived.wheel_cut_allowance,
        "result": side.derived.side_clearance_height,
    }


def _wheel_notch_payload(
    profile: TileSection | BlockGuideSection,
    machine: MachineConfig,
    side,
) -> dict[str, Any] | None:
    if not isinstance(profile, (TileSection, BlockGuideSection)) or not any(
        position in {"下", "上"} for position in machine.wheel_positions
    ):
        return None
    radius = side.template.wheel_radius
    has_lower_wheel = "下" in machine.wheel_positions
    has_upper_wheel = "上" in machine.wheel_positions
    cut_in_depth = profile.process_thickness * WHEEL_CUT_IN_RATIO
    lower_cavity_opening = side.derived.lower_cavity_notch_opening
    upper_cavity_opening = side.derived.upper_cavity_notch_opening
    effective_cut_in_depth = side.derived.wheel_notch_depth - profile.guide_spec.slot_base_height
    opening_y = machine.side_layout.lower_y + profile.guide_spec.slot_base_height
    natural_wheel_center_y = opening_y + cut_in_depth - radius
    adjusted_wheel_center_y = machine.side_layout.lower_y + side.derived.wheel_notch_depth - radius
    return {
        "natural_cut_in_formula": (
            "preform_block_thickness_mid * 0.6"
            if profile.preform_block_spec is not None
            else "finished_thickness * 0.6"
        ),
        "process_thickness": profile.process_thickness,
        "natural_cut_in_depth": cut_in_depth,
        "natural_opening": 2.0 * (radius * radius - (radius - cut_in_depth) ** 2) ** 0.5,
        "opening_limit_formula": "product_length * 0.6",
        "opening_limit": side.derived.wheel_notch_opening_limit,
        "lower_cavity_notch_opening": lower_cavity_opening,
        "upper_cavity_notch_opening": upper_cavity_opening,
        "upper_opening_limit": side.derived.upper_cavity_notch_opening_limit,
        "upper_effective_cut_in_depth": side.derived.wheel_cut_allowance,
        "effective_cut_in_depth": effective_cut_in_depth,
        "effective_notch_top_height_from_guide_bottom": side.derived.wheel_notch_depth,
        "wheel_radius": radius,
        "product_length": profile.process_length,
        "lower_cavity_notch_opening_less_than_product_length": (
            lower_cavity_opening < profile.process_length if has_lower_wheel else True
        ),
        "lower_cavity_notch_opening_within_limit": (
            lower_cavity_opening <= side.derived.wheel_notch_opening_limit
            if has_lower_wheel and side.derived.wheel_notch_opening_limit is not None
            else True
        ),
        "upper_cavity_notch_opening_less_than_product_length": (
            upper_cavity_opening < profile.process_length if has_upper_wheel else True
        ),
        "upper_cavity_notch_opening_within_limit": (
            upper_cavity_opening <= side.derived.upper_cavity_notch_opening_limit
            if has_upper_wheel and side.derived.upper_cavity_notch_opening_limit is not None
            else True
        ),
        "natural_wheel_center_y": natural_wheel_center_y,
        "adjusted_wheel_center_y": adjusted_wheel_center_y,
        "wheel_center_shift": adjusted_wheel_center_y - natural_wheel_center_y,
        "lower_wheel_center_y": adjusted_wheel_center_y,
        "note": "上下砂轮的目标吃入深度均按成型磨前厚度中值的0.6倍计算；最终缺口开口不得超过 product_length * 0.6，超限时移动对应砂轮圆心并同步更新连接线。",
    }


def _rounded(value: float) -> float:
    return round(float(value), 6)

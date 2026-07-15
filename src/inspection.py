from __future__ import annotations

from dataclasses import dataclass
from math import isclose, sqrt
from pathlib import Path
from typing import Any

from .block_geometry import BlockGuideSection
from .cavity_projection import derive_cavity_projection_profile
from .dimension_writer import DIMENSION_LAYER, TEXT_NOTE_LAYER
from .dimension_roles import (
    LOWER_WHEEL_KEY_PROCESS_HEIGHT,
    LOWER_WHEEL_NOTCH_OPENING,
    REQUIRED_BLOCK_TO_BREAD_DIMENSION_ROLES,
    REQUIRED_BLOCK_TO_TILE_DIMENSION_ROLES,
    SECTION_CENTER_OPENING,
    UPPER_WHEEL_KEY_PROCESS_HEIGHT,
    UPPER_WHEEL_LOCAL_CUT_IN_DEPTH,
    get_dimension_role,
)
from .geometry import TileSection
from .machine_config import MachineConfig
from .relief_arc_audit import build_four_outer_relief_arc_audit
from .side_view import GLOBAL_WHEEL_CUT_IN_RATIO, build_side_view_geometry
from .side_view_config import SideViewTemplateConfig
from .side_view_validator import (
    cavity_projection_matches_pre_grinding_shape,
    measure_side_clearance_consistency,
)
from .side_view_writer import SIDE_DEBUG_LAYER, SIDE_DIMENSION_LAYER


from .global_rules import ENDPOINT_TOLERANCE


TOLERANCE = ENDPOINT_TOLERANCE


def _build_machine_side(profile, machine: MachineConfig):
    return build_side_view_geometry(
        profile,
        template=SideViewTemplateConfig(wheel_radius=machine.wheel_radius),
        layout=machine.side_layout,
    )
RELEASE_ALLOWED_LAYERS = {
    "FIXED_TEMPLATE",
    "SECTION_CENTER",
    "PARAM_SLOT",
    DIMENSION_LAYER,
    TEXT_NOTE_LAYER,
    "SIDE_TEMPLATE",
    "SIDE_DERIVED",
    SIDE_DIMENSION_LAYER,
    "SIDE_CENTER",
}


@dataclass(frozen=True)
class InspectionCheck:
    name: str
    ok: bool
    details: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "details": self.details}


def inspect_release_dxf(
    profile: TileSection | BlockGuideSection,
    machine: MachineConfig,
    dxf_path: str | Path,
) -> dict[str, Any]:
    import ezdxf

    path = Path(dxf_path)
    doc = ezdxf.readfile(path)
    audit = doc.audit()
    checks = [
        _check(
            "dxf_audit",
            len(audit.errors) == 0,
            {"error_count": len(audit.errors)},
        ),
        _check_machine_config(machine),
        _check_release_layers(doc),
        _check_formula_text_absent(doc),
        _check_old_parametric_geometry_absent(doc, profile),
        _check_block_to_tile_main_arc_sweeps(doc, profile),
        _check_block_to_tile_relief_topology(doc, profile),
        _check_four_relief_arcs_are_outer(doc, profile),
        *_dimension_consistency_checks(doc, profile, machine),
    ]
    lower_notch_check = _check_lower_wheel_notch_safety(doc, profile, machine)
    if lower_notch_check is not None:
        checks.append(lower_notch_check)
    upper_notch_check = _check_upper_wheel_notch_safety(doc, profile, machine)
    if upper_notch_check is not None:
        checks.append(upper_notch_check)
    is_down_up_tile = (
        isinstance(profile, TileSection)
        and machine.machine_id == "triple_single_down_up"
    )
    is_down_up_block_bread = (
        isinstance(profile, BlockGuideSection)
        and profile.process_type == "block_to_bread_rectangular"
        and machine.machine_id == "triple_single_down_up"
    )
    if is_down_up_tile or is_down_up_block_bread:
        checks.extend(
            [
                _check_side_r80_dimensions_bound_to_arcs(doc, machine),
                _check_required_process_dimensions(doc, profile, machine),
            ]
        )
    if is_down_up_tile:
        checks.extend(
            [
                _check_upper_wheel_cut_in(doc, profile, machine),
                _check_stale_section_opening_dimension_absent(doc),
            ]
        )
    if is_down_up_block_bread:
        checks.extend(
            [
                _check_block_bread_side_geometry(doc, profile, machine),
                _check_flat_arc_relief_topology(doc, profile),
            ]
        )
    return {
        "dxf_path": str(path),
        "release_allowed": all(check.ok for check in checks),
        "checks": [check.as_dict() for check in checks],
    }


def _check(name: str, ok: bool, details: dict[str, Any]) -> InspectionCheck:
    return InspectionCheck(name=name, ok=bool(ok), details=details)


def _check_block_to_tile_main_arc_sweeps(
    doc,
    profile: TileSection | BlockGuideSection,
) -> InspectionCheck:
    if not isinstance(profile, TileSection) or profile.process_type != "block_to_tile":
        return _check("block_to_tile_main_arc_sweeps", True, {"applicable": False})
    radius = profile.forming_spec.R_form
    sweeps = [
        (float(entity.dxf.end_angle) - float(entity.dxf.start_angle)) % 360.0
        for entity in doc.modelspace().query("ARC")
        if entity.dxf.layer == "PARAM_SLOT"
        and abs(float(entity.dxf.radius) - radius) <= TOLERANCE
    ]
    valid = bool(sweeps) and all(TOLERANCE < sweep < 180.0 - TOLERANCE for sweep in sweeps)
    return _check(
        "block_to_tile_main_arc_sweeps",
        valid,
        {
            "applicable": True,
            "radius": round(radius, 6),
            "sweeps_deg": [round(sweep, 6) for sweep in sweeps],
            "requires_short_production_arc": True,
        },
    )


def _check_machine_config(machine: MachineConfig) -> InspectionCheck:
    fixed_span_sum = sum(machine.side_fixed_spans)
    template_paths = {
        "section_template": str(machine.section_template_path),
        "side_template": str(machine.side_template_path),
    }
    ok = (
        bool(machine.machine_id)
        and machine.section_template_path.exists()
        and machine.side_template_path.exists()
        and machine.guide_length > 0
        and len(machine.wheel_positions) > 0
        and machine.guide_sections > 0
        and isclose(fixed_span_sum, machine.guide_length, abs_tol=TOLERANCE)
    )
    return _check(
        "machine_config",
        ok,
        {
            "machine_id": machine.machine_id,
            "guide_length": machine.guide_length,
            "fixed_span_sum": round(fixed_span_sum, 6),
            "wheel_positions": list(machine.wheel_positions),
            "guide_sections": machine.guide_sections,
            "template_paths": template_paths,
            "templates_exist": {
                "section_template": machine.section_template_path.exists(),
                "side_template": machine.side_template_path.exists(),
            },
        },
    )


def _check_release_layers(doc) -> InspectionCheck:
    layers = sorted({entity.dxf.layer for entity in doc.modelspace()})
    debug_layers = [layer for layer in layers if "DEBUG" in layer or layer in {"REFERENCE_PROFILE", SIDE_DEBUG_LAYER}]
    unexpected_layers = [layer for layer in layers if layer not in RELEASE_ALLOWED_LAYERS]
    return _check(
        "release_layers",
        not debug_layers and not unexpected_layers,
        {
            "layers": layers,
            "debug_layers": debug_layers,
            "unexpected_layers": unexpected_layers,
            "allowed_layers": sorted(RELEASE_ALLOWED_LAYERS),
        },
    )


def _check_formula_text_absent(doc) -> InspectionCheck:
    formula_texts = []
    needles = ("+0.50=", "+0.20=", "12.0+0.50", "27.0-12.0", "formula", "R_form =")
    for entity in doc.modelspace():
        text = _entity_text(entity)
        if text and any(needle in text for needle in needles):
            formula_texts.append(text)
    return _check("formula_text_absent", not formula_texts, {"formula_texts": formula_texts})


def _check_old_parametric_geometry_absent(doc, profile: TileSection | BlockGuideSection) -> InspectionCheck:
    residues = []
    guide = profile.guide_spec
    half_outer = guide.outer_width / 2.0
    slot_center = guide.slot_center_offset
    min_x = slot_center - half_outer
    max_x = slot_center + half_outer
    min_y = 0.0
    max_y = guide.outer_height
    if isinstance(profile, TileSection):
        suspicious_radii = {round(profile.forming_spec.R_form, 6), round(guide.relief.relief_size / 2.0, 6)}
    else:
        suspicious_radii = {round(guide.relief.relief_size / 2.0, 6)}

    for entity in doc.modelspace():
        if entity.dxf.layer != "FIXED_TEMPLATE":
            continue
        if entity.dxftype() == "ARC":
            center = entity.dxf.center
            radius = round(float(entity.dxf.radius), 6)
            if min_x <= center.x <= max_x and min_y - 30.0 <= center.y <= max_y + 5.0:
                if radius in suspicious_radii or radius <= 2.0:
                    residues.append(_entity_summary(entity))
        elif entity.dxftype() == "LINE":
            start = entity.dxf.start
            end = entity.dxf.end
            inside_slot_area = (
                slot_center - 8.0 <= start.x <= slot_center + 8.0
                and slot_center - 8.0 <= end.x <= slot_center + 8.0
                and guide.slot_base_height - 2.0 <= start.y <= guide.outer_height + 0.5
                and guide.slot_base_height - 2.0 <= end.y <= guide.outer_height + 0.5
            )
            is_fixed_frame = (
                abs(start.y - end.y) <= TOLERANCE
                and (abs(start.y) <= TOLERANCE or abs(start.y - guide.outer_height) <= TOLERANCE)
            ) or (
                abs(start.x - end.x) <= TOLERANCE
                and (abs(abs(start.x) - half_outer) <= TOLERANCE)
            )
            if inside_slot_area and not is_fixed_frame:
                residues.append(_entity_summary(entity))
    return _check(
        "old_parametric_geometry_absent",
        not residues,
        {"residue_count": len(residues), "residues": residues[:20]},
    )


def _dimension_consistency_checks(doc, profile: TileSection | BlockGuideSection, machine: MachineConfig) -> list[InspectionCheck]:
    guide = profile.guide_spec
    checks = [
        _linear_dimension_check(
            doc,
            "slot_width",
            DIMENSION_LAYER,
            guide.slot_width_dimension_text,
            guide.guide_slot_width,
            _measure_slot_width_from_param_geometry(doc, profile),
        ),
        _linear_dimension_check(
            doc,
            "guide_thickness",
            DIMENSION_LAYER,
            f"{guide.guide_thickness:.2f}",
            guide.guide_thickness,
            _measure_guide_thickness_from_param_geometry(doc, profile),
        ),
    ]
    if isinstance(profile, TileSection):
        r_expected_count = (
            1
            if profile.process_type == "block_to_tile"
            or machine.section_style == "triple_single_down_up_flat_arc"
            else 2
        )
        checks.append(
            _radius_dimension_check(
                doc,
                "R_form",
                DIMENSION_LAYER,
                f"R{profile.forming_spec.R_form:.2f}",
                profile.forming_spec.R_form,
                _measure_r_form_from_param_geometry(doc, profile.forming_spec.R_form),
                expected_count=r_expected_count,
            )
        )
    if isinstance(profile, TileSection) and machine.section_style != "triple_single_down_up_flat_arc":
        side = _build_machine_side(profile, machine)
        cavity_projection = derive_cavity_projection_profile(
            profile,
            side.derived.guide_thickness,
        )
        cavity_projection_ok = cavity_projection_matches_pre_grinding_shape(
            doc,
            profile,
            side,
        )
        clearance = measure_side_clearance_consistency(doc, side)
        checks.extend(
            [
                _check(
                    "side_cavity_projection_from_pre_grinding_shape",
                    cavity_projection_ok,
                    {
                        "pre_grinding_shape": cavity_projection.pre_grinding_shape,
                        "expected_line_count": cavity_projection.line_count,
                        "surface_roles": list(
                            cavity_projection.surface_roles
                        ),
                    },
                ),
                _check(
                    "side_clearance_height_dimension",
                    clearance.ok,
                    {
                        "expected": round(clearance.expected, 6),
                        "geometry_measured": _round_optional(clearance.measured_geometry),
                        "definition_points_measured": _round_optional(clearance.measured_dimension_points),
                        "dimension_group_42_measured": _round_optional(clearance.measured_dimension_group_42),
                        "display_text": clearance.text_label,
                    },
                ),
            ]
        )
    return checks


def _linear_dimension_check(
    doc,
    name: str,
    layer: str,
    label: str,
    expected: float,
    geometry_measured: float | None,
    expected_count: int = 1,
) -> InspectionCheck:
    dimensions = _dimensions_by_label(doc, layer, label)
    values = [_dimension_value(dimension) for dimension in dimensions]
    displayed = [_dimension_display_text(doc, dimension) for dimension in dimensions]
    normalized_displayed = [_normalize_dimension_display_text(text) for text in displayed]
    ok = (
        len(dimensions) >= expected_count
        and geometry_measured is not None
        and abs(geometry_measured - expected) <= TOLERANCE
        and all(value is not None and abs(value - expected) <= TOLERANCE for value in values[:expected_count])
        and all(text == label for text in normalized_displayed[:expected_count])
    )
    return _check(
        f"{name}_dimension",
        ok,
        {
            "expected": round(expected, 6),
            "geometry_measured": _round_optional(geometry_measured),
            "definition_or_actual_measurements": [_round_optional(value) for value in values],
            "display_texts": displayed,
            "normalized_display_texts": normalized_displayed,
            "label": label,
            "dimension_count": len(dimensions),
            "expected_count": expected_count,
        },
    )


def _radius_dimension_check(
    doc,
    name: str,
    layer: str,
    label: str,
    expected: float,
    geometry_measured: list[float],
    expected_count: int,
) -> InspectionCheck:
    dimensions = _dimensions_by_label(doc, layer, label)
    values = [_dimension_value(dimension) for dimension in dimensions]
    displayed = [_dimension_display_text(doc, dimension) for dimension in dimensions]
    ok = (
        len(dimensions) >= expected_count
        and len(geometry_measured) >= expected_count
        and all(abs(value - expected) <= TOLERANCE for value in geometry_measured[:expected_count])
        and all(value is not None and abs(value - expected) <= TOLERANCE for value in values[:expected_count])
        and all(text == label for text in displayed[:expected_count])
    )
    return _check(
        f"{name}_dimension",
        ok,
        {
            "expected": round(expected, 6),
            "geometry_measured": [round(value, 6) for value in geometry_measured],
            "definition_or_actual_measurements": [_round_optional(value) for value in values],
            "display_texts": displayed,
            "label": label,
            "dimension_count": len(dimensions),
            "expected_count": expected_count,
        },
    )


def _dimensions_by_label(doc, layer: str, label: str):
    return [
        entity
        for entity in doc.modelspace()
        if entity.dxf.layer == layer and entity.dxftype() == "DIMENSION" and entity.dxf.text == label
    ]


def _dimension_value(dimension) -> float | None:
    if dimension.dxf.hasattr("actual_measurement"):
        return float(dimension.dxf.actual_measurement)
    try:
        return float(dimension.get_measurement())
    except Exception:
        return None


def _dimension_display_text(doc, dimension) -> str:
    if dimension.dxf.hasattr("geometry") and dimension.dxf.geometry in doc.blocks:
        for entity in doc.blocks[dimension.dxf.geometry]:
            text = _entity_text(entity)
            if text:
                return text
    return dimension.dxf.text or ""


def _normalize_dimension_display_text(text: str) -> str:
    if "\\S+0.01^ -0.01;" in text:
        prefix = text.split("{", 1)[0].strip()
        return f"{prefix}\u00b10.01"
    return text


def _measure_slot_width_from_param_geometry(doc, profile: TileSection | BlockGuideSection) -> float | None:
    relief_arcs = [
        entity
        for entity in doc.modelspace()
        if entity.dxf.layer == "PARAM_SLOT" and entity.dxftype() == "ARC" and float(entity.dxf.radius) <= 2.0
    ]
    if len(relief_arcs) >= 2:
        return max(arc.dxf.center.x for arc in relief_arcs) - min(arc.dxf.center.x for arc in relief_arcs)
    lines = [entity for entity in doc.modelspace() if entity.dxf.layer == "PARAM_SLOT" and entity.dxftype() == "LINE"]
    xs = []
    for line in lines:
        if abs(line.dxf.start.x - line.dxf.end.x) <= TOLERANCE:
            xs.append(line.dxf.start.x)
    if len(xs) >= 2:
        return max(xs) - min(xs)
    return None


def _measure_guide_thickness_from_param_geometry(doc, profile: TileSection | BlockGuideSection) -> float | None:
    relief_arcs = [
        entity
        for entity in doc.modelspace()
        if entity.dxf.layer == "PARAM_SLOT" and entity.dxftype() == "ARC" and float(entity.dxf.radius) <= 2.0
    ]
    if len(relief_arcs) >= 2:
        edge_centers = {
            min(arc.dxf.center.x for arc in relief_arcs),
            max(arc.dxf.center.x for arc in relief_arcs),
        }
        side_arcs = [
            arc
            for arc in relief_arcs
            if any(abs(arc.dxf.center.x - edge_x) <= TOLERANCE for edge_x in edge_centers)
        ]
        if len(side_arcs) >= 2:
            return max(arc.dxf.center.y for arc in side_arcs) - min(
                arc.dxf.center.y for arc in side_arcs
            )
    lines = [entity for entity in doc.modelspace() if entity.dxf.layer == "PARAM_SLOT" and entity.dxftype() == "LINE"]
    ys = []
    for line in lines:
        if abs(line.dxf.start.y - line.dxf.end.y) <= TOLERANCE:
            ys.append(line.dxf.start.y)
    if len(ys) >= 2:
        return max(ys) - min(ys)
    return None


def _measure_r_form_from_param_geometry(doc, expected: float) -> list[float]:
    values = []
    for entity in doc.modelspace():
        if entity.dxf.layer != "PARAM_SLOT" or entity.dxftype() != "ARC":
            continue
        radius = float(entity.dxf.radius)
        if abs(radius - expected) <= TOLERANCE:
            values.append(radius)
    return values


def _check_lower_wheel_notch_safety(
    doc,
    profile: TileSection | BlockGuideSection,
    machine: MachineConfig,
) -> InspectionCheck | None:
    if not isinstance(profile, TileSection) or "下" not in machine.wheel_positions:
        return None
    side = _build_machine_side(profile, machine)
    measured = _measure_lower_wheel_notch_opening_from_geometry(doc, side, machine)
    expected_report_value = side.derived.lower_cavity_notch_opening
    opening_limit = side.derived.wheel_notch_opening_limit
    difference = None if measured is None else abs(measured - expected_report_value)
    within_limit = measured is not None and opening_limit is not None and measured <= opening_limit + 0.001
    matches_report = measured is not None and difference is not None and difference < 0.01
    return _check(
        "lower_wheel_notch_safety",
        within_limit and matches_report,
        {
            "product_length": round(profile.finished_spec.length, 6),
            "opening_limit": _round_optional(opening_limit),
            "opening_measured_from_geometry": _round_optional(measured),
            "opening_report_value": round(expected_report_value, 6),
            "difference": _round_optional(difference),
            "opening_within_limit": within_limit,
            "geometry_measurement_matches_report": matches_report,
        },
    )


def _check_upper_wheel_notch_safety(
    doc,
    profile: TileSection | BlockGuideSection,
    machine: MachineConfig,
) -> InspectionCheck | None:
    if not isinstance(profile, TileSection) or "上" not in machine.wheel_positions:
        return None
    side = _build_machine_side(profile, machine)
    expected = side.derived.upper_cavity_notch_opening
    opening_limit = side.derived.upper_cavity_notch_opening_limit
    measurements = _measure_upper_wheel_notch_openings_from_geometry(doc, side, machine)
    differences = [abs(measured - expected) for measured in measurements]
    within_limit = (
        bool(measurements)
        and opening_limit is not None
        and all(measured <= opening_limit + TOLERANCE for measured in measurements)
    )
    matches_report = bool(differences) and all(difference < 0.01 for difference in differences)
    return _check(
        "upper_wheel_notch_safety",
        within_limit and matches_report,
        {
            "product_length": round(profile.process_length, 6),
            "opening_limit": _round_optional(opening_limit),
            "openings_measured_from_geometry": [round(value, 6) for value in measurements],
            "opening_report_value": round(expected, 6),
            "differences": [round(value, 6) for value in differences],
            "opening_within_limit": within_limit,
            "geometry_measurement_matches_report": matches_report,
        },
    )


def _check_side_r80_dimensions_bound_to_arcs(doc, machine: MachineConfig) -> InspectionCheck:
    radius = machine.wheel_radius
    arcs = [
        entity
        for entity in doc.modelspace()
        if entity.dxftype() == "ARC"
        and entity.dxf.layer == "SIDE_TEMPLATE"
        and abs(float(entity.dxf.radius) - radius) <= TOLERANCE
        and any(abs(float(entity.dxf.center.x) - center_x) <= 0.05 for center_x in (
            machine.side_layout.center_a_x,
            machine.side_layout.center_b_x,
        ))
    ]
    dimensions = []
    for entity in doc.modelspace():
        if entity.dxftype() != "DIMENSION":
            continue
        try:
            measurement = float(entity.get_measurement())
        except Exception:
            continue
        if abs(measurement - radius) > TOLERANCE:
            continue
        if not (entity.dxf.hasattr("defpoint") and entity.dxf.hasattr("defpoint4")):
            continue
        center = entity.dxf.defpoint
        target = entity.dxf.defpoint4
        target_radius = ((target.x - center.x) ** 2 + (target.y - center.y) ** 2) ** 0.5
        matching_arc = next(
            (
                arc
                for arc in arcs
                if abs(float(arc.dxf.center.x) - float(center.x)) <= TOLERANCE
                and abs(float(arc.dxf.center.y) - float(center.y)) <= TOLERANCE
            ),
            None,
        )
        dimensions.append(
            {
                "center": [round(float(center.x), 6), round(float(center.y), 6)],
                "target": [round(float(target.x), 6), round(float(target.y), 6)],
                "target_radius": round(target_radius, 6),
                "center_matches_arc": matching_arc is not None,
                "target_on_radius": abs(target_radius - radius) <= TOLERANCE,
            }
        )
    ok = len(arcs) == 2 and len(dimensions) == 2 and all(
        item["center_matches_arc"] and item["target_on_radius"] for item in dimensions
    )
    return _check(
        "side_r80_dimensions_bound_to_arcs",
        ok,
        {
            "arc_count": len(arcs),
            "dimension_count": len(dimensions),
            "dimensions": dimensions,
        },
    )


def _check_upper_wheel_cut_in(
    doc,
    profile: TileSection,
    machine: MachineConfig,
) -> InspectionCheck:
    side = _build_machine_side(profile, machine)
    radius = side.template.wheel_radius
    center_x = machine.side_layout.center_b_x
    arc = next(
        (
            entity
            for entity in doc.modelspace()
            if entity.dxftype() == "ARC"
            and entity.dxf.layer == "SIDE_TEMPLATE"
            and abs(float(entity.dxf.radius) - radius) <= TOLERANCE
            and abs(float(entity.dxf.center.x) - center_x) <= 0.05
            and float(entity.dxf.center.y) > machine.side_layout.upper_y
        ),
        None,
    )
    expected = side.derived.wheel_cut_allowance
    slot_top_y = (
        machine.side_layout.lower_y
        + profile.guide_spec.slot_base_height
        + profile.guide_spec.guide_thickness
    )
    measured = None if arc is None else slot_top_y - (float(arc.dxf.center.y) - radius)
    ok = measured is not None and abs(measured - expected) <= TOLERANCE and measured > 0.0
    return _check(
        "upper_wheel_cut_in",
        ok,
        {
            "formula": "min(natural_upper_R80_opening, product_length - 0.2)",
            "process_thickness": profile.process_thickness,
            "cut_in_ratio": GLOBAL_WHEEL_CUT_IN_RATIO,
            "requested_cut_in": profile.process_thickness
            * GLOBAL_WHEEL_CUT_IN_RATIO,
            "expected": round(expected, 6),
            "measured_from_geometry": _round_optional(measured),
            "slot_top_y": round(slot_top_y, 6),
        },
    )


def _check_block_bread_side_geometry(
    doc,
    profile: BlockGuideSection,
    machine: MachineConfig,
) -> InspectionCheck:
    side = _build_machine_side(profile, machine)
    layout = machine.side_layout
    radius = side.template.wheel_radius
    arcs = [
        entity
        for entity in doc.modelspace().query("ARC")
        if entity.dxf.layer == "SIDE_TEMPLATE"
        and abs(float(entity.dxf.radius) - radius) <= TOLERANCE
    ]
    expected_lower_center_y = layout.lower_y + side.derived.wheel_notch_depth - radius
    expected_upper_center_y = layout.upper_y - side.derived.side_clearance_height + radius
    lower_arc = next(
        (
            arc
            for arc in arcs
            if abs(float(arc.dxf.center.x) - layout.center_a_x) <= TOLERANCE
            and abs(float(arc.dxf.center.y) - expected_lower_center_y) <= TOLERANCE
        ),
        None,
    )
    upper_arc = next(
        (
            arc
            for arc in arcs
            if abs(float(arc.dxf.center.x) - layout.center_b_x) <= TOLERANCE
            and abs(float(arc.dxf.center.y) - expected_upper_center_y) <= TOLERANCE
        ),
        None,
    )
    fixed_slot_base = abs(
        side.derived.slot_base_height - profile.guide_spec.slot_base_height
    ) <= TOLERANCE
    return _check(
        "block_bread_side_geometry",
        fixed_slot_base and lower_arc is not None and upper_arc is not None,
        {
            "slot_base_height": round(side.derived.slot_base_height, 6),
            "machine_section_slot_base_height": round(
                profile.guide_spec.slot_base_height,
                6,
            ),
            "slot_base_is_machine_fixed": fixed_slot_base,
            "lower_key_height": round(side.derived.wheel_notch_depth, 6),
            "upper_key_height": round(side.derived.side_clearance_height, 6),
            "expected_lower_r80_center_y": round(expected_lower_center_y, 6),
            "expected_upper_r80_center_y": round(expected_upper_center_y, 6),
            "lower_r80_matches": lower_arc is not None,
            "upper_r80_matches": upper_arc is not None,
        },
    )


def _check_required_process_dimensions(
    doc,
    profile: TileSection | BlockGuideSection,
    machine: MachineConfig,
) -> InspectionCheck:
    side = _build_machine_side(profile, machine)
    expectations = _required_dimension_expectations(doc, profile, machine, side)
    required_roles = (
        REQUIRED_BLOCK_TO_BREAD_DIMENSION_ROLES
        if isinstance(profile, BlockGuideSection)
        else REQUIRED_BLOCK_TO_TILE_DIMENSION_ROLES
    )
    dimensions_by_role: dict[str, list[Any]] = {
        role: [] for role in required_roles
    }
    for entity in doc.modelspace().query("DIMENSION"):
        role = get_dimension_role(entity)
        if role in dimensions_by_role:
            dimensions_by_role[role].append(entity)

    roles: dict[str, Any] = {}
    for role in required_roles:
        expected = expectations[role]
        dimensions = dimensions_by_role[role]
        dimension = dimensions[0] if len(dimensions) == 1 else None
        measurement = None if dimension is None else _raw_dimension_measurement(dimension)
        display_text = None if dimension is None else _dimension_display_text(doc, dimension)
        definition_points = None if dimension is None else _dimension_definition_points(dimension)
        bound = (
            dimension is not None
            and _dimension_points_match(
                dimension,
                expected["point_1"],
                expected["point_2"],
            )
        )
        measurement_ok = (
            measurement is not None
            and abs(measurement - expected["value"]) <= TOLERANCE
        )
        display_ok = display_text == expected["display_text"]
        status = (
            "PASS"
            if len(dimensions) == 1 and measurement_ok and display_ok and bound
            else "FAIL"
        )
        roles[role] = {
            "expected_value": round(expected["value"], 6),
            "actual_dimension_measurement": _round_optional(measurement),
            "display_text": display_text,
            "definition_points": definition_points,
            "bound_to_geometry": bound,
            "status": status,
            "dimension_count": len(dimensions),
            "expected_display_text": expected["display_text"],
        }

    return _check(
        "required_dimension_roles",
        all(item["status"] == "PASS" for item in roles.values()),
        {"roles": roles},
    )


def _check_block_to_tile_relief_topology(
    doc,
    profile: TileSection | BlockGuideSection,
) -> InspectionCheck:
    if not isinstance(profile, TileSection) or profile.process_type != "block_to_tile":
        return _check("relief_topology", True, {"applicable": False})

    return _check_flat_arc_relief_topology(doc, profile)


def _check_four_relief_arcs_are_outer(
    doc,
    profile: TileSection | BlockGuideSection,
) -> InspectionCheck:
    audit = build_four_outer_relief_arc_audit(
        doc.modelspace(),
        profile.guide_spec.relief.relief_size / 2.0,
        tolerance=TOLERANCE,
    )
    return _check("four_relief_arcs_are_outer", audit["release_allowed"], audit)


def _check_flat_arc_relief_topology(
    doc,
    profile: TileSection | BlockGuideSection,
) -> InspectionCheck:
    side_relief_radius = profile.guide_spec.relief.relief_size / 2.0
    center_transition_radius = 0.5
    arcs = [
        entity
        for entity in doc.modelspace()
        if entity.dxftype() == "ARC"
        and entity.dxf.layer == "PARAM_SLOT"
        and (
            abs(float(entity.dxf.radius) - side_relief_radius) <= TOLERANCE
            or abs(float(entity.dxf.radius) - center_transition_radius) <= TOLERANCE
        )
    ]
    if not arcs:
        return _check(
            "relief_topology",
            False,
            {"reason": "No PARAM_SLOT relief arcs found."},
        )

    min_x = min(float(entity.dxf.center.x) for entity in arcs)
    max_x = max(float(entity.dxf.center.x) for entity in arcs)
    center_x = (min_x + max_x) / 2.0
    side_arcs = [
        entity
        for entity in arcs
        if abs(float(entity.dxf.center.x) - min_x) <= TOLERANCE
        or abs(float(entity.dxf.center.x) - max_x) <= TOLERANCE
    ]
    center_arcs = [entity for entity in arcs if entity not in side_arcs]
    base_y = min(float(entity.dxf.center.y) for entity in side_arcs)
    top_y = max(float(entity.dxf.center.y) for entity in side_arcs)
    opening_half = profile.guide_spec.center_opening / 2.0
    expected_center_xs = (
        center_x - opening_half - center_transition_radius,
        center_x + opening_half + center_transition_radius,
    )
    if (
        profile.process_type in {"block_to_tile", "block_to_bread"}
        and profile.arc_side == "upper"
    ):
        radius = profile.forming_spec.R_form
        half_slot = profile.guide_spec.guide_slot_width / 2.0
        upper_center_y = top_y - sqrt(radius**2 - half_slot**2)
        center_offset = opening_half + center_transition_radius
        expected_center_y = upper_center_y + sqrt(
            (radius + center_transition_radius) ** 2 - center_offset**2
        )
    else:
        expected_center_y = top_y + center_transition_radius

    expected_side_centers = (
        (min_x, base_y),
        (min_x, top_y),
        (max_x, base_y),
        (max_x, top_y),
    )
    side_centers = [
        (float(entity.dxf.center.x), float(entity.dxf.center.y))
        for entity in side_arcs
    ]
    center_centers = sorted(
        (
            float(entity.dxf.center.x),
            float(entity.dxf.center.y),
        )
        for entity in center_arcs
    )
    side_ok = len(side_arcs) == 4 and all(
        any(
            abs(actual_x - expected_x) <= TOLERANCE
            and abs(actual_y - expected_y) <= TOLERANCE
            for actual_x, actual_y in side_centers
        )
        for expected_x, expected_y in expected_side_centers
    )
    center_ok = len(center_centers) == 2 and all(
        abs(center_centers[index][0] - expected_center_xs[index]) <= TOLERANCE
        and abs(center_centers[index][1] - expected_center_y) <= TOLERANCE
        for index in range(min(2, len(center_centers)))
    )
    main_arcs = (
        [
            entity
            for entity in doc.modelspace()
            if entity.dxftype() == "ARC"
            and entity.dxf.layer == "PARAM_SLOT"
            and abs(float(entity.dxf.radius) - profile.forming_spec.R_form) <= TOLERANCE
        ]
        if isinstance(profile, TileSection)
        else []
    )
    if isinstance(profile, TileSection) and profile.process_type == "block_to_tile":
        if profile.arc_side == "upper":
            main_arc_side_ok = bool(main_arcs) and all(
                float(entity.dxf.center.y) < top_y - TOLERANCE for entity in main_arcs
            )
            expected_main_arc_count = 2
        else:
            main_arc_side_ok = bool(main_arcs) and all(
                float(entity.dxf.center.y) > base_y + TOLERANCE for entity in main_arcs
            )
            expected_main_arc_count = 1
    else:
        main_arc_side_ok = True
        expected_main_arc_count = None

    return _check(
        "relief_topology",
        (
            len(arcs) == 6
            and side_ok
            and center_ok
            and main_arc_side_ok
            and (
                expected_main_arc_count is None
                or len(main_arcs) == expected_main_arc_count
            )
        ),
        {
            "expected_arc_count": 6,
            "actual_arc_count": len(arcs),
            "4-1": {
                "expected_count": 4,
                "actual_count": len(side_arcs),
                "radius": round(side_relief_radius, 6),
                "centers": [
                    [round(x, 6), round(y, 6)] for x, y in sorted(side_centers)
                ],
            },
            "2-0.5": {
                "expected_count": 2,
                "actual_count": len(center_arcs),
                "radius": center_transition_radius,
                "expected_centers": [
                    [round(x, 6), round(expected_center_y, 6)]
                    for x in expected_center_xs
                ],
                "actual_centers": [
                    [round(x, 6), round(y, 6)] for x, y in center_centers
                ],
                "x_dependency": "section_center_opening + relief_radius",
                "independent_of_slot_width": True,
            },
            "process_type": profile.process_type,
            "main_R": {
                "expected_arc_count": expected_main_arc_count,
                "actual_arc_count": len(main_arcs),
                "arc_side": getattr(profile, "arc_side", None),
                "centers": [
                    [
                        round(float(entity.dxf.center.x), 6),
                        round(float(entity.dxf.center.y), 6),
                    ]
                    for entity in main_arcs
                ],
                "orientation_ok": main_arc_side_ok,
            },
        },
    )


def _required_dimension_expectations(doc, profile, machine, side) -> dict[str, dict[str, Any]]:
    section = _measure_block_to_tile_section_datums(doc)
    layout = machine.side_layout
    derived = side.derived
    base_y = layout.lower_y + derived.slot_base_height
    slot_top_y = base_y + derived.guide_thickness
    upper_low_y = layout.upper_y - derived.side_clearance_height
    lower_opening = derived.lower_cavity_notch_opening
    return {
        SECTION_CENTER_OPENING: {
            "value": profile.guide_spec.center_opening,
            "display_text": _format_dimension_text(profile.guide_spec.center_opening, 1),
            "point_1": (section["opening_left_x"], section["outer_top_y"]),
            "point_2": (section["opening_right_x"], section["outer_top_y"]),
        },
        LOWER_WHEEL_NOTCH_OPENING: {
            "value": lower_opening,
            "display_text": _format_dimension_text(lower_opening, 1),
            "point_1": (layout.center_a_x - lower_opening / 2.0, base_y),
            "point_2": (layout.center_a_x + lower_opening / 2.0, base_y),
        },
        LOWER_WHEEL_KEY_PROCESS_HEIGHT: {
            "value": derived.wheel_notch_depth,
            "display_text": _format_dimension_text(derived.wheel_notch_depth, 2),
            "point_1": (layout.center_a_x, layout.lower_y),
            "point_2": (layout.center_a_x, layout.lower_y + derived.wheel_notch_depth),
        },
        UPPER_WHEEL_KEY_PROCESS_HEIGHT: {
            "value": derived.side_clearance_height,
            "display_text": _format_dimension_text(derived.side_clearance_height, 2),
            "point_1": (layout.center_b_x, upper_low_y),
            "point_2": (layout.center_b_x, layout.upper_y),
        },
        UPPER_WHEEL_LOCAL_CUT_IN_DEPTH: {
            "value": derived.wheel_cut_allowance,
            "display_text": _format_dimension_text(derived.wheel_cut_allowance, 2),
            "point_1": (layout.center_b_x, upper_low_y),
            "point_2": (layout.center_b_x, slot_top_y),
        },
    }


def _measure_block_to_tile_section_datums(doc) -> dict[str, float]:
    relief_arcs = [
        entity
        for entity in doc.modelspace()
        if entity.dxftype() == "ARC"
        and entity.dxf.layer == "PARAM_SLOT"
        and float(entity.dxf.radius) <= 2.0
    ]
    opening_lines = [
        entity
        for entity in doc.modelspace()
        if entity.dxftype() == "LINE"
        and entity.dxf.layer == "PARAM_SLOT"
        and abs(float(entity.dxf.start.x) - float(entity.dxf.end.x)) <= TOLERANCE
    ]
    if len(relief_arcs) < 4 or len(opening_lines) < 4:
        raise ValueError("Cannot derive block-to-tile section datums from PARAM_SLOT geometry.")
    center_xs = sorted(float(entity.dxf.center.x) for entity in relief_arcs)
    ys = sorted(float(entity.dxf.center.y) for entity in relief_arcs)
    central_lines = sorted(
        opening_lines,
        key=lambda entity: abs(float(entity.dxf.start.x) - sum(center_xs) / len(center_xs)),
    )[:2]
    return {
        "right_x": max(center_xs),
        "top_y": max(ys),
        "opening_left_x": min(float(entity.dxf.start.x) for entity in central_lines),
        "opening_right_x": max(float(entity.dxf.start.x) for entity in central_lines),
        "outer_top_y": max(
            max(float(entity.dxf.start.y), float(entity.dxf.end.y))
            for entity in central_lines
        ),
    }


def _raw_dimension_measurement(dimension) -> float | None:
    try:
        return float(dimension.get_measurement())
    except Exception:
        return None


def _dimension_definition_points(dimension) -> dict[str, list[float]]:
    points = {}
    for name in ("defpoint", "defpoint2", "defpoint3", "defpoint4", "text_midpoint"):
        if dimension.dxf.hasattr(name):
            point = dimension.dxf.get(name)
            points[name] = [
                round(float(point.x), 6),
                round(float(point.y), 6),
                round(float(point.z), 6),
            ]
    return points


def _dimension_points_match(
    dimension,
    expected_1: tuple[float, float],
    expected_2: tuple[float, float],
) -> bool:
    if not (dimension.dxf.hasattr("defpoint2") and dimension.dxf.hasattr("defpoint3")):
        return False
    actual_1 = dimension.dxf.defpoint2
    actual_2 = dimension.dxf.defpoint3
    direct = _point_matches(actual_1, expected_1) and _point_matches(actual_2, expected_2)
    reverse = _point_matches(actual_1, expected_2) and _point_matches(actual_2, expected_1)
    return direct or reverse


def _point_matches(actual, expected: tuple[float, float]) -> bool:
    return (
        abs(float(actual.x) - expected[0]) <= TOLERANCE
        and abs(float(actual.y) - expected[1]) <= TOLERANCE
    )


def _format_dimension_text(value: float, digits: int) -> str:
    del digits
    return f"{value:.2f}"


def _check_stale_section_opening_dimension_absent(doc) -> InspectionCheck:
    stale = []
    for dimension in doc.modelspace().query("DIMENSION"):
        measurement = _raw_dimension_measurement(dimension)
        if measurement is None or abs(measurement - 4.0) > TOLERANCE:
            continue
        if not (dimension.dxf.hasattr("defpoint2") and dimension.dxf.hasattr("defpoint3")):
            continue
        p2 = dimension.dxf.defpoint2
        p3 = dimension.dxf.defpoint3
        if abs(float(p2.y) - float(p3.y)) > TOLERANCE:
            continue
        if 3200.0 <= float(p2.x) <= 3300.0 and 3200.0 <= float(p3.x) <= 3300.0:
            stale.append(
                {
                    "handle": dimension.dxf.handle,
                    "measurement": round(measurement, 6),
                    "display_text": _dimension_display_text(doc, dimension),
                    "definition_points": _dimension_definition_points(dimension),
                }
            )
    return _check(
        "stale_section_center_opening_absent",
        not stale,
        {"stale_dimensions": stale},
    )


def _measure_lower_wheel_notch_opening_from_geometry(
    doc,
    side,
    machine: MachineConfig,
) -> float | None:
    lower_index = machine.wheel_positions.index("下")
    center_x = side.layout.center_a_x if lower_index == 0 else side.layout.center_b_x
    base_y = side.layout.lower_y + side.derived.slot_base_height
    radius = side.template.wheel_radius
    arc = _find_lower_wheel_r80_arc(doc, center_x, base_y, radius)
    if arc is None:
        return None
    return _r80_opening_at_y(arc, base_y)


def _measure_upper_wheel_notch_openings_from_geometry(
    doc,
    side,
    machine: MachineConfig,
) -> list[float]:
    radius = side.template.wheel_radius
    openings: list[float] = []
    for index, position in enumerate(machine.wheel_positions):
        if position != "上":
            continue
        center_x = side.layout.center_a_x if index == 0 else side.layout.center_b_x
        slot_top_y = (
            side.layout.lower_y
            + side.derived.slot_base_height
            + side.derived.guide_thickness
        )
        arc = _find_upper_wheel_r80_arc(doc, center_x, slot_top_y, radius)
        if arc is not None:
            opening = _r80_opening_at_y(arc, slot_top_y)
            if opening is not None:
                openings.append(opening)
    return openings


def _find_lower_wheel_r80_arc(doc, center_x: float, base_y: float, radius: float):
    candidates = []
    for entity in doc.modelspace():
        if entity.dxftype() != "ARC" or entity.dxf.layer != "SIDE_TEMPLATE":
            continue
        if abs(float(entity.dxf.radius) - radius) > 0.001:
            continue
        if abs(entity.dxf.center.x - center_x) > 0.05:
            continue
        if not (entity.dxf.center.y - radius - 0.001 <= base_y <= entity.dxf.center.y + radius + 0.001):
            continue
        if entity.dxf.center.y >= base_y:
            continue
        candidates.append(entity)
    if not candidates:
        return None
    return min(candidates, key=lambda entity: abs(entity.dxf.center.x - center_x))


def _find_upper_wheel_r80_arc(doc, center_x: float, opening_y: float, radius: float):
    candidates = []
    for entity in doc.modelspace():
        if entity.dxftype() != "ARC" or entity.dxf.layer != "SIDE_TEMPLATE":
            continue
        if abs(float(entity.dxf.radius) - radius) > TOLERANCE:
            continue
        if abs(float(entity.dxf.center.x) - center_x) > 0.05:
            continue
        if not (
            float(entity.dxf.center.y) - radius - TOLERANCE
            <= opening_y
            <= float(entity.dxf.center.y) + radius + TOLERANCE
        ):
            continue
        if float(entity.dxf.center.y) <= opening_y:
            continue
        candidates.append(entity)
    if not candidates:
        return None
    return min(candidates, key=lambda entity: abs(float(entity.dxf.center.x) - center_x))


def _r80_opening_at_y(arc, y: float) -> float | None:
    radius = float(arc.dxf.radius)
    vertical_offset = y - float(arc.dxf.center.y)
    chord_squared = radius * radius - vertical_offset * vertical_offset
    if chord_squared < -TOLERANCE:
        return None
    return 2.0 * sqrt(max(0.0, chord_squared))


def _find_notch_line_endpoints(doc, center_x: float, base_y: float, arc) -> tuple[float | None, float | None]:
    endpoints: list[float] = []
    radius = float(arc.dxf.radius)
    for entity in doc.modelspace():
        if entity.dxftype() != "LINE" or entity.dxf.layer != "SIDE_DERIVED":
            continue
        if abs(entity.dxf.start.y - base_y) > 0.001 or abs(entity.dxf.end.y - base_y) > 0.001:
            continue
        start_x = float(entity.dxf.start.x)
        end_x = float(entity.dxf.end.x)
        min_x = min(start_x, end_x)
        max_x = max(start_x, end_x)
        if max_x <= center_x:
            endpoint = max_x
        elif min_x >= center_x:
            endpoint = min_x
        else:
            continue
        if _point_on_arc_circle(endpoint, base_y, arc, radius):
            endpoints.append(endpoint)
    left = [value for value in endpoints if value < center_x]
    right = [value for value in endpoints if value > center_x]
    if not left or not right:
        return None, None
    return max(left), min(right)


def _point_on_arc_circle(x: float, y: float, arc, radius: float) -> bool:
    dx = x - float(arc.dxf.center.x)
    dy = y - float(arc.dxf.center.y)
    return abs((dx * dx + dy * dy) ** 0.5 - radius) <= 0.01


def _entity_text(entity) -> str:
    if entity.dxftype() == "TEXT":
        return entity.dxf.text
    if entity.dxftype() == "MTEXT":
        return entity.text
    return ""


def _entity_summary(entity) -> dict[str, Any]:
    summary: dict[str, Any] = {"type": entity.dxftype(), "layer": entity.dxf.layer}
    if entity.dxftype() == "ARC":
        summary.update(
            {
                "center": [round(entity.dxf.center.x, 6), round(entity.dxf.center.y, 6)],
                "radius": round(float(entity.dxf.radius), 6),
            }
        )
    elif entity.dxftype() == "LINE":
        summary.update(
            {
                "start": [round(entity.dxf.start.x, 6), round(entity.dxf.start.y, 6)],
                "end": [round(entity.dxf.end.x, 6), round(entity.dxf.end.y, 6)],
            }
        )
    return summary


def _round_optional(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)

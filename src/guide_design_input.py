from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from math import cos, radians, sin
from typing import Any

from .block_geometry import BlockGuideSection, build_block_guide_section
from .geometry import (
    TileSection,
    build_block_to_tile_section,
    build_tile_section,
)
from .groove_profile import (
    determine_groove_profile,
    normalize_shape,
    resolve_arc_center_side,
)
from .global_rules import (
    BLOCK_THICKNESS_CLEARANCE,
    default_thickness_clearance,
    process_options_from_mapping,
)
from .machine_config import MachineConfig
from .spec_parser import (
    BlockSpec,
    FinishedSpec,
    parse_block_spec,
    parse_company_bread_spec,
    parse_company_tile_spec,
    parse_relief_spec,
)


SUPPORTED_FINISHED_SHAPES = {"bread", "tile"}
SUPPORTED_PRE_GRINDING_SHAPES = {"block", "same_r_tile"}
SIDE_VECTOR = {
    "upper": (0.0, 1.0),
    "lower": (0.0, -1.0),
    "left": (-1.0, 0.0),
    "right": (1.0, 0.0),
}
WHEEL_POSITION_SIDE = {
    "上": "upper",
    "下": "lower",
    "左": "left",
    "右": "right",
    "upper": "upper",
    "lower": "lower",
    "left": "left",
    "right": "right",
}


@dataclass(frozen=True)
class GuideDesignDecision:
    finished_product_spec: str
    pre_grinding_spec: str
    finished_product_shape: str
    finished_spec_order: str
    pre_grinding_shape: str
    guide_profile_source: str
    machine_type: str
    guide_rail_type: str
    wheel_sequence: tuple[str, ...]
    first_wheel_side: str
    template_coordinate_system: str
    first_wheel_vector: tuple[float, float]
    arc_center_side: str | None
    arc_center_vector: tuple[float, float] | None
    flat_side: str | None
    arc_side: str | None
    final_section_profile_type: str
    R_form_source: str
    slot_width_source: str
    guide_thickness_source: str
    groove_profile: str
    arc_radius: float | None
    finished_radii: tuple[float, ...]
    dimension_source: dict[str, str]
    confidence: str
    tolerance: dict[str, float | None]
    process_options: dict[str, Any]
    approved_reference_overrides: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["wheel_sequence"] = list(self.wheel_sequence)
        payload["finished_radii"] = list(self.finished_radii)
        payload["approved_reference_overrides"] = list(
            self.approved_reference_overrides
        )
        payload["first_wheel_vector"] = list(self.first_wheel_vector)
        if self.arc_center_vector is not None:
            payload["arc_center_vector"] = list(self.arc_center_vector)
        payload["finished_spec"] = self.finished_product_spec
        payload["product_shape_before"] = normalize_shape(
            self.pre_grinding_shape
        )
        payload["product_shape_after"] = normalize_shape(
            self.finished_product_shape
        )
        payload["warnings"] = list(self.warnings)
        return payload


def build_single_guide_profile_from_input(
    input_data: dict[str, Any],
    machine: MachineConfig,
) -> tuple[
    FinishedSpec,
    FinishedSpec | BlockSpec,
    TileSection | BlockGuideSection,
    GuideDesignDecision,
]:
    """Build one explicit dual-spec profile through the centralized decision table."""
    normalized = _normalize_dual_spec_input(input_data)
    required = (
        "finished_spec",
        "pre_grinding_spec",
        "product_shape_after",
        "product_shape_before",
        "machine_type",
        "guide_rail_type",
        "wheel_sequence",
        "first_wheel_side",
        "template_coordinate_system",
    )
    missing = [key for key in required if not normalized.get(key)]
    if missing:
        raise ValueError(
            "Explicit dual-spec input requires fields: " + ", ".join(missing)
        )
    if machine.guide_sections != 1:
        raise ValueError("Single-guide input requires a machine with guide_sections = 1.")

    finished_raw = str(normalized["finished_spec"])
    pre_grinding_raw = str(normalized["pre_grinding_spec"])
    finished_shape = _legacy_finished_shape(str(normalized["product_shape_after"]))
    pre_grinding_shape = _legacy_pre_grinding_shape(
        str(normalized["product_shape_before"])
    )
    requested_profile_source = normalized.get("guide_profile_source")
    first_wheel_side = str(normalized["first_wheel_side"]).strip().lower()
    _validate_explicit_metadata(
        normalized,
        machine,
        finished_shape,
        pre_grinding_shape,
        first_wheel_side,
    )

    relief = parse_relief_spec(str(normalized.get("relief", "4-1")))
    process_options = process_options_from_mapping(normalized)
    pre_grinding_spec = (
        parse_block_spec(pre_grinding_raw)
        if pre_grinding_shape == "block"
        else parse_company_tile_spec(pre_grinding_raw)
    )
    finished_spec, finished_spec_order = _parse_finished_spec(
        finished_raw,
        finished_shape,
        normalized.get("finished_spec_order"),
        pre_grinding_spec,
    )
    tolerance = _resolve_tolerance_metadata(
        normalized.get("tolerance"),
        pre_grinding_spec,
    )
    if not isinstance(finished_spec, FinishedSpec):
        raise ValueError("Arc-guide generation requires a bread or tile finished specification.")

    radii = (
        (finished_spec.R_outer_finished,)
        if finished_shape == "bread"
        else (
            finished_spec.R_outer_finished,
            finished_spec.R_inner_finished,
        )
    )
    groove = determine_groove_profile(
        product_shape_before=pre_grinding_shape,
        product_shape_after=finished_shape,
        finished_radius_count=len(radii),
        machine_type=machine.machine_id,
        guide_rail_type=machine.guide_type,
        wheel_sequence=machine.wheel_positions,
        template_rules=machine_template_rules(machine),
        finished_radii=radii,
        first_wheel_side=first_wheel_side,
    )
    if groove.groove_profile == "manual_review":
        raise ValueError("; ".join(groove.warnings))
    profile_source = groove.guide_profile_source
    if profile_source is None:
        raise ValueError("Central groove decision did not produce a profile source.")
    if requested_profile_source not in (None, profile_source):
        raise ValueError(
            "guide_profile_source conflicts with the centralized groove decision: "
            f"expected '{profile_source}'."
        )

    first_vector = side_vector_in_template(first_wheel_side, machine)
    arc_center_side = groove.arc_center_side
    arc_center_vector = (
        tuple(-value for value in first_vector)
        if arc_center_side is not None
        else None
    )

    if pre_grinding_shape == "block":
        if not isinstance(pre_grinding_spec, BlockSpec):
            raise TypeError("rectangular_block pre-grinding input must parse as BlockSpec.")
        thickness_clearance = (
            process_options.thickness_clearance_override
            or BLOCK_THICKNESS_CLEARANCE
        )
        if finished_shape == "bread":
            profile = build_block_guide_section(
                pre_grinding_spec,
                relief=relief,
                slot_reference="width",
                slot_clearance=process_options.slot_clearance_override,
                outer_width=machine.section_outer_width,
                thickness_clearance_mid=thickness_clearance,
                slot_base_height=machine.section_slot_base_height,
                center_opening=machine.section_center_opening,
                finished_spec=finished_spec,
                process_type="block_to_bread_rectangular",
            )
            profile_type = "rectangular_block_preform"
            r_source = "finished_product_target_only_not_guide_profile"
        else:
            if groove.arc_side not in {"upper", "lower"}:
                raise ValueError(
                    "Double-R block preform requires an upper or lower first-wheel side."
                )
            profile = build_block_to_tile_section(
                finished_spec,
                pre_grinding_spec,
                relief=relief,
                thickness_clearance_mid=thickness_clearance,
                tolerance_slot_clearance=process_options.slot_clearance_override,
                outer_width=machine.section_outer_width,
                slot_base_height=_block_to_tile_slot_base_height(
                    pre_grinding_spec,
                    machine,
                    thickness_clearance,
                ),
                center_opening=machine.section_center_opening,
                arc_side=groove.arc_side,
            )
            profile_type = "flat_arc_big_r_block_preform"
            r_source = "max(finished_product_R_outer, finished_product_R_inner)"

        decision = GuideDesignDecision(
            finished_product_spec=finished_raw,
            pre_grinding_spec=pre_grinding_raw,
            finished_product_shape=finished_shape,
            finished_spec_order=finished_spec_order,
            pre_grinding_shape=pre_grinding_shape,
            guide_profile_source=profile_source,
            machine_type=machine.machine_id,
            guide_rail_type=machine.guide_type,
            wheel_sequence=machine.wheel_positions,
            first_wheel_side=first_wheel_side,
            template_coordinate_system=machine.template_coordinate_system,
            first_wheel_vector=first_vector,
            arc_center_side=arc_center_side,
            arc_center_vector=arc_center_vector,
            flat_side=groove.flat_side,
            arc_side=groove.arc_side,
            final_section_profile_type=profile_type,
            R_form_source=r_source,
            slot_width_source="pre_grinding_spec.width_and_tolerance",
            guide_thickness_source="pre_grinding_spec.thickness_mid",
            groove_profile=groove.groove_profile,
            arc_radius=groove.arc_radius,
            finished_radii=tuple(float(value) for value in radii),
            dimension_source=dict(groove.dimension_source),
            confidence=groove.confidence,
            tolerance=tolerance,
            process_options=asdict(process_options),
            approved_reference_overrides=machine.approved_reference_overrides,
            warnings=groove.warnings,
        )
        return finished_spec, pre_grinding_spec, profile, decision

    if not isinstance(pre_grinding_spec, FinishedSpec):
        raise TypeError("same_r_tile pre-grinding input must parse as FinishedSpec.")
    if abs(
        pre_grinding_spec.R_outer_finished
        - pre_grinding_spec.R_inner_finished
    ) > 1e-9:
        raise ValueError(
            "pre_grinding_shape='same_r_tile' requires equal pre-grinding radii."
        )
    profile = build_tile_section(
        pre_grinding_spec,
        relief=relief,
        thickness_clearance_mid=(
            process_options.thickness_clearance_override
            or default_thickness_clearance(
                "same_r_tile",
                pre_grinding_spec.chord_width,
            )
        ),
        tolerance_slot_clearance=process_options.slot_clearance_override,
        outer_width=machine.section_outer_width,
        slot_base_height=machine.section_slot_base_height,
        center_opening=machine.section_center_opening,
    )
    decision = GuideDesignDecision(
        finished_product_spec=finished_raw,
        pre_grinding_spec=pre_grinding_raw,
        finished_product_shape=finished_shape,
        finished_spec_order=finished_spec_order,
        pre_grinding_shape=pre_grinding_shape,
        guide_profile_source=profile_source,
        machine_type=machine.machine_id,
        guide_rail_type=machine.guide_type,
        wheel_sequence=machine.wheel_positions,
        first_wheel_side=first_wheel_side,
        template_coordinate_system=machine.template_coordinate_system,
        first_wheel_vector=first_vector,
        arc_center_side=None,
        arc_center_vector=None,
        flat_side=None,
        arc_side=None,
        final_section_profile_type="same_r_tile",
        R_form_source="pre_grinding_spec_equal_R",
        slot_width_source="pre_grinding_spec.chord_width_and_tolerance",
        guide_thickness_source="pre_grinding_spec.thickness_mid",
        groove_profile=groove.groove_profile,
        arc_radius=groove.arc_radius,
        finished_radii=tuple(float(value) for value in radii),
        dimension_source=dict(groove.dimension_source),
        confidence=groove.confidence,
        tolerance=tolerance,
        process_options=asdict(process_options),
        approved_reference_overrides=machine.approved_reference_overrides,
        warnings=groove.warnings,
    )
    return finished_spec, pre_grinding_spec, profile, decision


def resolve_opposite_side(side: str) -> str:
    return resolve_arc_center_side(side)


def side_vector_in_template(
    side: str,
    machine: MachineConfig,
) -> tuple[float, float]:
    """Resolve a process side through the template transform, not screen direction."""
    try:
        x, y = SIDE_VECTOR[side]
    except KeyError as exc:
        raise ValueError("side must be upper, lower, left, or right.") from exc
    if machine.template_mirror_x:
        x = -x
    if machine.template_mirror_y:
        y = -y
    angle = radians(machine.template_axis_rotation_deg)
    transformed = (
        x * cos(angle) - y * sin(angle),
        x * sin(angle) + y * cos(angle),
    )
    return tuple(round(value, 12) for value in transformed)


def _normalize_dual_spec_input(input_data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(input_data)
    aliases = {
        "finished_spec": "finished_product_spec",
        "product_shape_before": "pre_grinding_shape",
        "product_shape_after": "finished_product_shape",
    }
    for canonical, legacy in aliases.items():
        canonical_value = normalized.get(canonical)
        legacy_value = normalized.get(legacy)
        if canonical_value is not None and legacy_value is not None:
            if canonical == "finished_spec":
                matches = str(canonical_value) == str(legacy_value)
            else:
                matches = normalize_shape(str(canonical_value)) == normalize_shape(
                    str(legacy_value)
                )
            if not matches:
                raise ValueError(
                    f"Conflicting dual-spec aliases: {canonical} and {legacy}."
                )
        if canonical_value is None and legacy_value is not None:
            normalized[canonical] = legacy_value

    if normalized.get("product_shape_before") is not None:
        normalized["product_shape_before"] = normalize_shape(
            str(normalized["product_shape_before"])
        )
    if normalized.get("product_shape_after") is not None:
        normalized["product_shape_after"] = normalize_shape(
            str(normalized["product_shape_after"])
        )
    return normalized


def _legacy_finished_shape(shape: str) -> str:
    normalized = normalize_shape(shape)
    if normalized == "bread_shape":
        return "bread"
    if normalized == "tile_shape":
        return "tile"
    raise ValueError("product_shape_after must be bread_shape or tile_shape.")


def _legacy_pre_grinding_shape(shape: str) -> str:
    normalized = normalize_shape(shape)
    if normalized == "rectangular_block":
        return "block"
    if normalized == "same_r_tile":
        return "same_r_tile"
    raise ValueError(
        "product_shape_before must be rectangular_block or same_r_tile."
    )


def machine_template_rules(machine: MachineConfig) -> dict[str, Any]:
    """Expose template-owned orientation rules to every input adapter."""
    return {
        "block_to_tile_groove_profile": machine.block_to_tile_groove_profile,
        "block_to_bread_groove_profile": machine.block_to_bread_groove_profile,
        "flat_arc_surface_side": machine.flat_arc_surface_side,
        "flat_surface_side": machine.flat_surface_side,
        "flat_arc_center_side": machine.flat_arc_center_side,
        "template_coordinate_system": machine.template_coordinate_system,
        "template_axis_rotation_deg": machine.template_axis_rotation_deg,
        "template_mirror_x": machine.template_mirror_x,
        "template_mirror_y": machine.template_mirror_y,
    }


def _parse_finished_spec(
    raw: str,
    shape: str,
    order: Any,
    pre_grinding_spec: FinishedSpec | BlockSpec,
) -> tuple[FinishedSpec, str]:
    if shape == "bread":
        parsed = parse_company_bread_spec(raw)
        if order is None:
            if not isinstance(pre_grinding_spec, BlockSpec):
                raise ValueError(
                    "Bread finished_spec_order is required when the pre-grinding "
                    "specification cannot disambiguate length and width."
                )
            standard_matches = _bread_dimensions_match_preform(
                parsed.length,
                parsed.chord_width,
                pre_grinding_spec,
            )
            swapped_matches = _bread_dimensions_match_preform(
                parsed.chord_width,
                parsed.length,
                pre_grinding_spec,
            )
            if standard_matches and not swapped_matches:
                order = "radius_length_width_thickness"
            elif swapped_matches and not standard_matches:
                order = "radius_width_length_thickness"
            elif standard_matches and swapped_matches:
                order = "radius_length_width_thickness"
            else:
                raise ValueError(
                    "Bread finished specification length/width cannot be matched to "
                    "the pre-grinding block; provide finished_spec_order explicitly."
                )
        order = str(order)
        if order == "radius_length_width_thickness":
            return parsed, order
        if order == "radius_width_length_thickness":
            return (
                replace(
                    parsed,
                    chord_width=parsed.length,
                    length=parsed.chord_width,
                ),
                order,
            )
        raise ValueError(
            "bread finished_spec_order must be "
            "'radius_length_width_thickness' or "
            "'radius_width_length_thickness'."
        )
    resolved_order = (
        "outer_r_inner_r_width_length_thickness"
        if order is None
        else str(order)
    )
    if resolved_order != "outer_r_inner_r_width_length_thickness":
        raise ValueError(
            "tile finished_spec_order must be "
            "'outer_r_inner_r_width_length_thickness'."
        )
    return (
        parse_company_tile_spec(raw, require_chord_tolerance=False),
        resolved_order,
    )


def _bread_dimensions_match_preform(
    length: float,
    width: float,
    preform: BlockSpec,
) -> bool:
    return (
        abs(length - preform.length) <= 0.01
        and abs(width - preform.width) <= 0.25
    )


def _resolve_tolerance_metadata(
    supplied: Any,
    pre_grinding_spec: FinishedSpec | BlockSpec,
) -> dict[str, float | None]:
    if isinstance(pre_grinding_spec, BlockSpec):
        resolved = {
            "width_upper_deviation": pre_grinding_spec.width_tolerance_upper,
            "width_lower_deviation": pre_grinding_spec.width_tolerance_lower,
            "thickness_upper_deviation": pre_grinding_spec.thickness_tolerance_upper,
            "thickness_lower_deviation": pre_grinding_spec.thickness_tolerance_lower,
        }
    else:
        resolved = {
            "width_upper_deviation": pre_grinding_spec.chord_width_tolerance_upper,
            "width_lower_deviation": pre_grinding_spec.chord_width_tolerance_lower,
            "thickness_upper_deviation": pre_grinding_spec.thickness_tolerance_upper,
            "thickness_lower_deviation": pre_grinding_spec.thickness_tolerance_lower,
        }
    if supplied is None:
        return resolved
    if not isinstance(supplied, dict):
        raise ValueError("tolerance must be an object when provided.")
    for key, actual in resolved.items():
        if key not in supplied:
            continue
        expected = supplied[key]
        if expected is None and actual is None:
            continue
        if expected is None or actual is None or abs(float(expected) - actual) > 1e-9:
            raise ValueError(
                f"tolerance.{key} conflicts with pre_grinding_spec."
            )
    return resolved


def _validate_explicit_metadata(
    input_data: dict[str, Any],
    machine: MachineConfig,
    finished_shape: str,
    pre_grinding_shape: str,
    first_wheel_side: str,
) -> None:
    if finished_shape not in SUPPORTED_FINISHED_SHAPES:
        raise ValueError("finished_product_shape must be 'bread' or 'tile'.")
    if pre_grinding_shape not in SUPPORTED_PRE_GRINDING_SHAPES:
        raise ValueError("pre_grinding_shape must be 'block' or 'same_r_tile'.")
    resolve_opposite_side(first_wheel_side)
    configured_first_side = _machine_first_wheel_side(machine)
    if first_wheel_side != configured_first_side:
        raise ValueError(
            "first_wheel_side does not match the first wheel in the selected "
            f"machine config: expected '{configured_first_side}'."
        )
    if input_data.get("machine_type") not in (None, machine.machine_id):
        raise ValueError("machine_type does not match the selected machine config.")
    if input_data.get("guide_rail_type") not in (None, machine.guide_type):
        raise ValueError("guide_rail_type does not match the selected machine config.")
    wheel_sequence = input_data.get("wheel_sequence")
    if wheel_sequence is not None and tuple(str(item) for item in wheel_sequence) != machine.wheel_positions:
        raise ValueError("wheel_sequence does not match the selected machine config.")
    coordinate_system = input_data.get("template_coordinate_system")
    if coordinate_system not in (None, machine.template_coordinate_system):
        raise ValueError(
            "template_coordinate_system does not match the selected machine config."
        )


def _machine_first_wheel_side(machine: MachineConfig) -> str:
    if not machine.wheel_positions:
        raise ValueError("Machine config must define at least one wheel position.")
    raw = str(machine.wheel_positions[0]).strip().lower()
    try:
        return WHEEL_POSITION_SIDE[raw]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported first wheel position in machine config: {raw!r}."
        ) from exc


def _block_to_tile_slot_base_height(
    preform: BlockSpec,
    machine: MachineConfig,
    thickness_clearance_mid: float,
) -> float:
    top_gap = machine.side_layout.block_fixed_top_gap
    if machine.side_layout.block_side_mode != "fixed_top_gap":
        return machine.section_slot_base_height
    if top_gap is None:
        raise ValueError("fixed_top_gap block side-view mode requires block_fixed_top_gap.")
    guide_thickness = preform.thickness_mid + thickness_clearance_mid
    return 27.0 - top_gap - guide_thickness

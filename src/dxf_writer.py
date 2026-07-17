from __future__ import annotations

from math import atan2, degrees, hypot, sqrt
from pathlib import Path
from typing import Any

from .dimension_writer import (
    DIMENSION_LAYER,
    DIMENSION_TEXT_FALLBACK_LAYER,
    DIMENSION_TEXT_STYLE,
    SlotDimensionGeometry,
    TEXT_NOTE_LAYER,
    add_center_offset_dimension,
    add_fixed_template_dimensions,
    add_bed_618_r_form_dimensions,
    add_guide_thickness_dimension,
    add_linear_dimension_with_text,
    add_radius_dimension_with_text,
    add_r_form_dimension,
    add_relief_dimension,
    add_section_template_dimensions,
    add_slot_width_dimension,
)
from .dimension_precision import normalize_dimension_display_precision
from .dimension_roles import SECTION_CENTER_OPENING, set_dimension_role
from .block_geometry import BlockGuideSection
from .geometry import Point
from .geometry import ArcSegment, LineSegment, SectionProfile, TileSection
from .machine_config import MachineConfig, load_machine_config
from .global_rules import CENTER_TRANSITION_RADIUS
from .side_view_config import DEFAULT_SIDE_VIEW_TEMPLATE
from .side_view_writer import (
    SIDE_CAVITY_LAYER,
    SIDE_CENTER_LAYER,
    SIDE_DEBUG_LAYER,
    SIDE_DERIVED_LAYER,
    SIDE_DERIVED_RELEASE_LAYER,
    SIDE_DIMENSION_LAYER,
    SIDE_TEMPLATE_LAYER,
    add_side_view_to_dxf,
)
from .side_view_validator import assert_side_view_consistency
from .template_paths import legacy_template_path


DEFAULT_TEMPLATE_PATHS = (
    legacy_template_path("standard_guide_template.dxf"),
    legacy_template_path("R17_45XR15_8X6_2X1_65_clean_template_latest.dxf"),
    legacy_template_path("R17_45XR15_8X6_2X1_65_clean_template.dxf"),
)
DEBUG_CONTROL_LAYER = "DEBUG_CONTROL"
DEBUG_POINTS_LAYER = "DEBUG_POINTS"
SECTION_CENTER_LAYER = "SECTION_CENTER"
PARAM_SLOT_COLOR = 7


def write_dxf(
    profile: SectionProfile | TileSection | BlockGuideSection,
    path: str | Path,
    output_mode: str = "debug",
    machine_id: str | None = None,
    machine_config_override: MachineConfig | None = None,
) -> Path:
    try:
        import ezdxf
    except ImportError as exc:
        raise RuntimeError(
            "ezdxf is required for DXF output. Install dependencies with: "
            "python3 -m pip install -r requirements.txt"
        ) from exc

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _validate_output_mode(output_mode)

    machine_config = machine_config_override
    if machine_config is None and machine_id is not None:
        machine_config = load_machine_config(machine_id)
    if isinstance(profile, BlockGuideSection):
        if machine_config is None:
            raise ValueError("Block guide DXF generation requires machine_id.")
        return _write_block_template_based_dxf(profile, output_path, ezdxf, machine_config, output_mode=output_mode)

    template_path = machine_config.section_template_path if machine_config is not None else _resolve_template_path()
    if isinstance(profile, TileSection) and template_path is not None:
        if machine_config is not None and machine_config.section_style == "triple_single_down_up_flat_arc":
            return _write_triple_single_down_up_flat_arc_dxf(
                profile,
                output_path,
                ezdxf,
                machine_config,
                output_mode=output_mode,
            )
        return _write_template_based_dxf(
            profile,
            output_path,
            ezdxf,
            template_path,
            output_mode=output_mode,
            machine_config=machine_config,
        )

    doc = ezdxf.new("R12")
    _ensure_layer(doc, "FIXED_TEMPLATE", color=7)
    _ensure_layer(doc, "PARAM_SLOT", color=PARAM_SLOT_COLOR)
    _ensure_layer(doc, SECTION_CENTER_LAYER, color=1, linetype="CENTER")
    _ensure_layer(doc, DIMENSION_LAYER, color=3)
    _ensure_layer(doc, TEXT_NOTE_LAYER, color=4)
    if output_mode == "debug":
        _ensure_layer(doc, DIMENSION_TEXT_FALLBACK_LAYER, color=2)
        _ensure_layer(doc, DEBUG_CONTROL_LAYER, color=6)
        _ensure_layer(doc, DEBUG_POINTS_LAYER, color=5)
    _ensure_layer(doc, "REFERENCE_PROFILE", color=8)
    _ensure_dimension_text_style(doc)

    modelspace = doc.modelspace()
    if isinstance(profile, TileSection):
        _add_fixed_template_entities(modelspace, profile)
        slot_geometry = _add_param_slot_entities(modelspace, profile)
        _rebuild_section_top_boundary(modelspace, slot_geometry)
        if output_mode == "debug":
            _add_reference_profile_entities(modelspace, profile)
        if output_mode == "debug":
            _add_debug_entities(modelspace, slot_geometry)
        add_section_template_dimensions(doc, modelspace, profile, slot_geometry)
        add_side_view_to_dxf(doc, modelspace, profile, output_mode=output_mode)
        if output_mode == "debug":
            _assert_native_dimensions_present(modelspace, profile)
    else:
        _add_profile_entities(modelspace, profile, "REFERENCE_PROFILE")

    if output_mode == "release":
        _simplify_release_layers(doc)
        if isinstance(profile, TileSection):
            assert_side_view_consistency(doc, profile)
    normalize_dimension_display_precision(doc, modelspace)
    doc.saveas(output_path)
    return output_path


def _resolve_template_path() -> Path | None:
    for path in DEFAULT_TEMPLATE_PATHS:
        if path.exists():
            return path
    return None


def _write_template_based_dxf(
    tile_section: TileSection,
    output_path: Path,
    ezdxf,
    template_path: Path,
    output_mode: str,
    machine_config: MachineConfig | None = None,
) -> Path:
    doc = ezdxf.readfile(template_path)
    modelspace = doc.modelspace()

    _ensure_layer(doc, "FIXED_TEMPLATE", color=7)
    _ensure_layer(doc, "PARAM_SLOT", color=PARAM_SLOT_COLOR)
    _ensure_layer(doc, SECTION_CENTER_LAYER, color=1, linetype="CENTER")
    _ensure_layer(doc, DIMENSION_LAYER, color=3)
    _ensure_layer(doc, TEXT_NOTE_LAYER, color=4)
    if output_mode == "debug":
        _ensure_layer(doc, DIMENSION_TEXT_FALLBACK_LAYER, color=2)
        _ensure_layer(doc, DEBUG_CONTROL_LAYER, color=6)
        _ensure_layer(doc, DEBUG_POINTS_LAYER, color=5)
    _ensure_layer(doc, "REFERENCE_PROFILE", color=8)
    _ensure_dimension_text_style(doc)

    anchor = _extract_template_anchor(modelspace, tile_section)
    to_delete = []
    for entity in list(modelspace):
        if _is_template_param_entity(entity, anchor, tile_section):
            to_delete.append(entity)
        elif _is_section_center_entity(entity):
            entity.dxf.layer = SECTION_CENTER_LAYER
            entity.dxf.color = 256
            entity.dxf.linetype = "BYLAYER"
        else:
            entity.dxf.layer = "FIXED_TEMPLATE"
    for entity in to_delete:
        modelspace.delete_entity(entity)

    if tile_section.process_type == "block_to_tile":
        slot_geometry = _add_block_to_tile_flat_arc_slot_entities(
            modelspace,
            tile_section,
            anchor,
        )
    else:
        slot_geometry = _add_param_slot_entities(
            modelspace,
            tile_section,
            anchor=anchor,
        )
    _rebuild_section_top_boundary(modelspace, slot_geometry)
    if output_mode == "debug":
        _add_reference_profile_entities(modelspace, tile_section, anchor=anchor)
    if output_mode == "debug":
        _add_debug_entities(modelspace, slot_geometry)
    if machine_config is not None and machine_config.section_style == "bed_618_fixed_base":
        add_section_template_dimensions(
            doc,
            modelspace,
            tile_section,
            slot_geometry,
            template_path=template_path,
        )
        add_bed_618_r_form_dimensions(doc, modelspace, tile_section, slot_geometry, template_path=template_path)
    else:
        add_section_template_dimensions(doc, modelspace, tile_section, slot_geometry)
    if (
        machine_config is not None
        and machine_config.section_style == "triple_single_down_up_flat_arc"
        and tile_section.process_type == "block_to_tile"
        and tile_section.arc_side == "lower"
    ):
        _remove_unbound_flat_arc_slot_base_dimension(modelspace, slot_geometry)
    add_side_view_to_dxf(
        doc,
        modelspace,
        tile_section,
        output_mode=output_mode,
        template_path=(
            machine_config.side_template_path
            if machine_config is not None
            else DEFAULT_SIDE_VIEW_TEMPLATE
        ),
        layout=None if machine_config is None else machine_config.side_layout,
        side_style=_side_style_for_machine(machine_config),
        wheel_positions=(
            ("上", "下")
            if machine_config is None
            else machine_config.wheel_positions
        ),
        wheel_radius=(
            80.0 if machine_config is None else machine_config.wheel_radius
        ),
    )
    if output_mode == "debug":
        _assert_native_dimensions_present(modelspace, tile_section)

    if output_mode == "release":
        _simplify_release_layers(doc)
        assert_side_view_consistency(doc, tile_section, machine_config=machine_config)
    normalize_dimension_display_precision(doc, modelspace)
    doc.saveas(output_path)
    return output_path


def _side_style_for_machine(machine_config: MachineConfig | None) -> str:
    if machine_config is None:
        return "standard"
    if machine_config.section_style == "bed_618_fixed_base":
        return "bed_618"
    if machine_config.machine_id == "double_head_up_down":
        return "double_head_up_down"
    return "standard"


def _write_triple_single_down_up_flat_arc_dxf(
    tile_section: TileSection,
    output_path: Path,
    ezdxf,
    machine_config: MachineConfig,
    output_mode: str,
) -> Path:
    doc = ezdxf.readfile(machine_config.section_template_path)
    modelspace = doc.modelspace()

    _ensure_layer(doc, "FIXED_TEMPLATE", color=7)
    _ensure_layer(doc, "PARAM_SLOT", color=PARAM_SLOT_COLOR)
    _ensure_layer(doc, SECTION_CENTER_LAYER, color=1, linetype="CENTER")
    _ensure_layer(doc, DIMENSION_LAYER, color=3)
    _ensure_layer(doc, TEXT_NOTE_LAYER, color=4)
    if output_mode == "debug":
        _ensure_layer(doc, DIMENSION_TEXT_FALLBACK_LAYER, color=2)
        _ensure_layer(doc, DEBUG_CONTROL_LAYER, color=6)
        _ensure_layer(doc, DEBUG_POINTS_LAYER, color=5)
    _ensure_layer(doc, "REFERENCE_PROFILE", color=8)
    _ensure_dimension_text_style(doc)

    anchor = _extract_block_template_anchor(modelspace)
    to_delete = []
    for entity in list(modelspace):
        if _is_down_up_flat_arc_template_param_entity(entity, anchor):
            to_delete.append(entity)
        elif entity.dxftype() == "DIMENSION":
            entity.dxf.layer = DIMENSION_LAYER
        elif _is_section_center_entity(entity):
            entity.dxf.layer = SECTION_CENTER_LAYER
            entity.dxf.color = 256
            entity.dxf.linetype = "BYLAYER"
        else:
            entity.dxf.layer = "FIXED_TEMPLATE"
    for entity in to_delete:
        modelspace.delete_entity(entity)

    if tile_section.process_type == "block_to_tile":
        slot_geometry = _add_block_to_tile_flat_arc_slot_entities(
            modelspace,
            tile_section,
            anchor,
        )
    elif tile_section.process_type == "block_to_bread":
        slot_geometry = _add_down_up_bread_slot_entities(modelspace, tile_section, anchor)
    elif tile_section.process_type == "tile":
        slot_geometry = _add_param_slot_entities(modelspace, tile_section, anchor=anchor)
    else:
        slot_geometry = _add_down_up_flat_arc_slot_entities(modelspace, tile_section, anchor)
    _rebuild_section_top_boundary(modelspace, slot_geometry)
    _update_down_up_flat_arc_template_dimensions(doc, modelspace, tile_section, slot_geometry)
    if tile_section.process_type == "block_to_tile" and tile_section.arc_side == "lower":
        _remove_unbound_flat_arc_slot_base_dimension(modelspace, slot_geometry)
    if output_mode == "debug":
        _add_debug_entities(modelspace, slot_geometry)
    add_side_view_to_dxf(
        doc,
        modelspace,
        tile_section,
        output_mode=output_mode,
        template_path=machine_config.side_template_path,
        layout=machine_config.side_layout,
        side_style="triple_single_down_up",
        wheel_positions=machine_config.wheel_positions,
        wheel_radius=machine_config.wheel_radius,
    )
    if output_mode == "release":
        _simplify_release_layers(doc)
    normalize_dimension_display_precision(doc, modelspace)
    doc.saveas(output_path)
    return output_path


def _is_down_up_flat_arc_template_param_entity(entity, anchor: TemplateAnchor) -> bool:
    if entity.dxftype() == "DIMENSION":
        return False
    if entity.dxftype() == "ARC":
        center = entity.dxf.center
        return anchor.left - 2.0 <= center.x <= anchor.right + 2.0
    if entity.dxftype() == "LINE":
        start = entity.dxf.start
        end = entity.dxf.end
        if _line_is_outer_frame(start, end, anchor):
            return False
        return (
            anchor.left <= start.x <= anchor.right
            and anchor.left <= end.x <= anchor.right
            and anchor.bottom <= start.y <= anchor.top
            and anchor.bottom <= end.y <= anchor.top
        )
    return False


def _add_block_to_tile_flat_arc_slot_entities(
    modelspace,
    tile_section: TileSection,
    anchor: TemplateAnchor,
) -> SlotDimensionGeometry:
    """Build the shared six-relief topology for a block-to-tile section.

    A tile made from a block has one plane and one forming-R surface.  The
    R surface is selected by the first-wheel rule, while the six relief arcs
    remain the same named topology on every machine.  It must never be routed
    through the block-to-bread constructor merely because its R is upper.
    """
    if tile_section.arc_side == "lower":
        return _add_lower_facing_flat_arc_slot_entities(modelspace, tile_section, anchor)
    if tile_section.arc_side == "upper":
        return _add_upper_facing_flat_arc_slot_entities(modelspace, tile_section, anchor)
    raise ValueError(f"Unsupported block-to-tile arc side: {tile_section.arc_side!r}")


def _add_down_up_flat_arc_slot_entities(
    modelspace,
    tile_section: TileSection,
    anchor: TemplateAnchor,
) -> SlotDimensionGeometry:
    """Backward-compatible entry point for callers of the lower-R builder."""
    return _add_block_to_tile_flat_arc_slot_entities(modelspace, tile_section, anchor)


def _add_lower_facing_flat_arc_slot_entities(
    modelspace,
    tile_section: TileSection,
    anchor: TemplateAnchor,
) -> SlotDimensionGeometry:
    guide = tile_section.guide_spec
    radius = tile_section.forming_spec.R_form
    relief_radius = guide.relief.relief_size / 2.0
    center_transition_radius = CENTER_TRANSITION_RADIUS
    half_slot = guide.guide_slot_width / 2.0
    opening_half = guide.center_opening / 2.0
    center_x = anchor.slot_center_x
    base_y = anchor.bottom + guide.slot_base_height
    top_y = base_y + guide.guide_thickness
    left_x = center_x - half_slot
    right_x = center_x + half_slot
    opening_left_x = center_x - opening_half
    opening_right_x = center_x + opening_half

    if half_slot >= radius:
        raise ValueError("slot width must be smaller than 2 * R_form for triple_single_down_up.")
    if guide.guide_thickness <= 2.0 * relief_radius:
        raise ValueError("Guide thickness is too small for relief geometry.")
    if guide.guide_slot_width <= guide.center_opening + 4.0 * relief_radius:
        raise ValueError("Slot width is too small for the configured top opening and relief geometry.")

    arc_base = sqrt(radius**2 - half_slot**2)
    # A lower-facing tile surface must have its radius center above the cavity.
    # This is the physical inverse of the upper-facing case and follows the
    # first-wheel-side rule (first wheel below -> arc below, center above).
    lower_center = Point(center_x, base_y + arc_base)
    center_left_relief = Point(
        opening_left_x - center_transition_radius,
        top_y + center_transition_radius,
    )
    center_right_relief = Point(
        opening_right_x + center_transition_radius,
        top_y + center_transition_radius,
    )
    center_left_vertical_tangent = Point(opening_left_x, center_left_relief.y)
    center_right_vertical_tangent = Point(opening_right_x, center_right_relief.y)

    _add_line(
        modelspace,
        center_left_vertical_tangent.as_tuple(),
        (opening_left_x, anchor.top),
        "PARAM_SLOT",
    )
    _add_line(
        modelspace,
        center_right_vertical_tangent.as_tuple(),
        (opening_right_x, anchor.top),
        "PARAM_SLOT",
    )
    _add_line(
        modelspace,
        (left_x + relief_radius, top_y),
        (center_left_relief.x, top_y),
        "PARAM_SLOT",
    )
    _add_line(
        modelspace,
        (center_right_relief.x, top_y),
        (right_x - relief_radius, top_y),
        "PARAM_SLOT",
    )
    _add_line(modelspace, (left_x, top_y - relief_radius), (left_x, base_y + relief_radius), "PARAM_SLOT")
    _add_line(modelspace, (right_x, base_y + relief_radius), (right_x, top_y - relief_radius), "PARAM_SLOT")

    modelspace.add_arc((left_x, top_y), relief_radius, 0.0, 270.0, dxfattribs={"layer": "PARAM_SLOT"})
    modelspace.add_arc((right_x, top_y), relief_radius, 270.0, 180.0, dxfattribs={"layer": "PARAM_SLOT"})
    _add_relief_arc(
        modelspace,
        center_left_relief,
        center_transition_radius,
        Point(center_left_relief.x, top_y),
        center_left_vertical_tangent,
    )
    _add_relief_arc(
        modelspace,
        center_right_relief,
        center_transition_radius,
        center_right_vertical_tangent,
        Point(center_right_relief.x, top_y),
    )

    lower_left_tangent = Point(left_x, base_y + relief_radius)
    lower_right_tangent = Point(right_x, base_y + relief_radius)
    lower_left_intersection = _select_circle_intersection(lower_center, radius, Point(left_x, base_y), relief_radius, "right")
    lower_right_intersection = _select_circle_intersection(lower_center, radius, Point(right_x, base_y), relief_radius, "left")
    _add_relief_arc(modelspace, Point(left_x, base_y), relief_radius, lower_left_tangent, lower_left_intersection)
    _add_relief_arc(modelspace, Point(right_x, base_y), relief_radius, lower_right_intersection, lower_right_tangent)
    _add_arc_by_points(
        modelspace,
        lower_center,
        radius,
        lower_right_intersection,
        lower_left_intersection,
        # DXF ARC is always counter-clockwise from start_angle to end_angle.
        # For a lower-facing R surface, this ordering must emit the short
        # bottom arc; the opposite ordering draws its almost-complete helper
        # circle instead of the production contour.
        clockwise=True,
        layer="PARAM_SLOT",
    )

    return SlotDimensionGeometry(
        left_x=left_x,
        right_x=right_x,
        base_y=base_y,
        top_y=top_y,
        opening_left_x=opening_left_x,
        opening_right_x=opening_right_x,
        center_x=center_x,
        outer_left=anchor.left,
        outer_right=anchor.right,
        outer_bottom=anchor.bottom,
        outer_top=anchor.top,
        upper_radius_center=(center_x, top_y),
        lower_radius_center=lower_center.as_tuple(),
        relief_radius=relief_radius,
        center_transition_radius=center_transition_radius,
        center_transition_left_center=center_left_relief.as_tuple(),
        center_transition_right_center=center_right_relief.as_tuple(),
    )


def _add_upper_facing_flat_arc_slot_entities(
    modelspace,
    tile_section: TileSection,
    anchor: TemplateAnchor,
) -> SlotDimensionGeometry:
    guide = tile_section.guide_spec
    radius = tile_section.forming_spec.R_form
    relief_radius = guide.relief.relief_size / 2.0
    center_transition_radius = CENTER_TRANSITION_RADIUS
    half_slot = guide.guide_slot_width / 2.0
    opening_half = guide.center_opening / 2.0
    center_x = anchor.slot_center_x
    base_y = anchor.bottom + guide.slot_base_height
    top_y = base_y + guide.guide_thickness
    left_x = center_x - half_slot
    right_x = center_x + half_slot
    opening_left_x = center_x - opening_half
    opening_right_x = center_x + opening_half

    if half_slot >= radius:
        raise ValueError("slot width must be smaller than 2 * R_form for an upper-facing R surface.")
    if guide.guide_thickness <= 2.0 * relief_radius:
        raise ValueError("Guide thickness is too small for relief geometry.")
    if guide.guide_slot_width <= guide.center_opening + 4.0 * relief_radius:
        raise ValueError("Slot width is too small for the configured top opening and relief geometry.")

    arc_base = sqrt(radius**2 - half_slot**2)
    upper_center = Point(center_x, top_y - arc_base)
    upper_left_relief = Point(left_x, top_y)
    upper_right_relief = Point(right_x, top_y)
    upper_left_intersection = _select_circle_intersection(
        upper_center, radius, upper_left_relief, relief_radius, "right"
    )
    upper_right_intersection = _select_circle_intersection(
        upper_center, radius, upper_right_relief, relief_radius, "left"
    )
    center_left_relief = _bread_center_opening_relief_center(
        upper_center,
        radius,
        opening_left_x,
        center_transition_radius,
        side="left",
    )
    center_right_relief = _bread_center_opening_relief_center(
        upper_center,
        radius,
        opening_right_x,
        center_transition_radius,
        side="right",
    )
    center_left_arc_tangent = _external_circle_tangent_point(
        upper_center, radius, center_left_relief, center_transition_radius
    )
    center_right_arc_tangent = _external_circle_tangent_point(
        upper_center, radius, center_right_relief, center_transition_radius
    )
    center_left_vertical_tangent = Point(opening_left_x, center_left_relief.y)
    center_right_vertical_tangent = Point(opening_right_x, center_right_relief.y)

    _add_line(
        modelspace,
        center_left_vertical_tangent.as_tuple(),
        (opening_left_x, anchor.top),
        "PARAM_SLOT",
    )
    _add_line(
        modelspace,
        center_right_vertical_tangent.as_tuple(),
        (opening_right_x, anchor.top),
        "PARAM_SLOT",
    )
    _add_line(
        modelspace,
        (left_x, base_y + relief_radius),
        (left_x, top_y - relief_radius),
        "PARAM_SLOT",
    )
    _add_line(
        modelspace,
        (right_x, base_y + relief_radius),
        (right_x, top_y - relief_radius),
        "PARAM_SLOT",
    )
    _add_line(
        modelspace,
        (left_x + relief_radius, base_y),
        (right_x - relief_radius, base_y),
        "PARAM_SLOT",
    )

    # All four 4-R reliefs retain the outer complement arc.  The endpoints
    # stay unchanged, so dimensions and tangent continuity remain valid.
    _add_outer_relief_arc(
        modelspace,
        Point(left_x, base_y),
        relief_radius,
        Point(left_x + relief_radius, base_y),
        Point(left_x, base_y + relief_radius),
    )
    _add_outer_relief_arc(
        modelspace,
        Point(right_x, base_y),
        relief_radius,
        Point(right_x, base_y + relief_radius),
        Point(right_x - relief_radius, base_y),
    )
    _add_outer_relief_arc(
        modelspace,
        upper_left_relief,
        relief_radius,
        Point(left_x, top_y - relief_radius),
        upper_left_intersection,
    )
    _add_outer_relief_arc(
        modelspace,
        upper_right_relief,
        relief_radius,
        upper_right_intersection,
        Point(right_x, top_y - relief_radius),
    )
    _add_relief_arc(
        modelspace,
        center_left_relief,
        center_transition_radius,
        center_left_arc_tangent,
        center_left_vertical_tangent,
    )
    _add_relief_arc(
        modelspace,
        center_right_relief,
        center_transition_radius,
        center_right_vertical_tangent,
        center_right_arc_tangent,
    )
    _add_arc_by_points(
        modelspace,
        upper_center,
        radius,
        center_left_arc_tangent,
        upper_left_intersection,
        clockwise=False,
        layer="PARAM_SLOT",
    )
    _add_arc_by_points(
        modelspace,
        upper_center,
        radius,
        upper_right_intersection,
        center_right_arc_tangent,
        clockwise=False,
        layer="PARAM_SLOT",
    )

    return SlotDimensionGeometry(
        left_x=left_x,
        right_x=right_x,
        base_y=base_y,
        top_y=top_y,
        opening_left_x=opening_left_x,
        opening_right_x=opening_right_x,
        center_x=center_x,
        outer_left=anchor.left,
        outer_right=anchor.right,
        outer_bottom=anchor.bottom,
        outer_top=anchor.top,
        upper_radius_center=upper_center.as_tuple(),
        lower_radius_center=(center_x, base_y),
        relief_radius=relief_radius,
        center_transition_radius=center_transition_radius,
        center_transition_left_center=center_left_relief.as_tuple(),
        center_transition_right_center=center_right_relief.as_tuple(),
    )


def _add_down_up_bread_slot_entities(
    modelspace,
    tile_section: TileSection,
    anchor: TemplateAnchor,
) -> SlotDimensionGeometry:
    """Build the upper-facing R topology used by the block-to-bread process.

    The geometric primitive is shared with an upper-facing block-to-tile
    section.  Keeping this process-specific entry point makes that shared
    dependency explicit; the block-to-tile dispatch and topology audit guard
    against accidentally treating it as a bread-only rule.
    """
    return _add_upper_facing_flat_arc_slot_entities(modelspace, tile_section, anchor)


def _update_down_up_flat_arc_template_dimensions(
    doc,
    modelspace,
    tile_section: TileSection,
    geometry: SlotDimensionGeometry,
) -> None:
    guide = tile_section.guide_spec
    dimensions = list(modelspace.query("DIMENSION"))
    for dimension in dimensions:
        dimension.dxf.layer = DIMENSION_LAYER

    slot_width_dim = _find_block_slot_width_dimension(dimensions, geometry)
    thickness_dim = _find_down_up_flat_arc_thickness_dimension(dimensions, geometry)
    opening_dim = _find_down_up_flat_arc_opening_dimension(dimensions, geometry)
    relief_size_dim = _find_dimension_by_text(dimensions, "4-<>")
    r_form_dim = _find_down_up_flat_arc_r_dimension(dimensions)

    if slot_width_dim is not None:
        _update_block_slot_width_dimension(doc, slot_width_dim, guide.slot_width_dimension_text, geometry)
    if thickness_dim is not None:
        _update_block_thickness_dimension(doc, thickness_dim, f"{guide.guide_thickness:.2f}", geometry)
    if opening_dim is not None:
        _update_down_up_flat_arc_opening_dimension(doc, opening_dim, geometry)
    if relief_size_dim is not None:
        _update_flat_arc_relief_diameter_dimension(
            doc,
            relief_size_dim,
            geometry,
        )
    if r_form_dim is not None:
        _update_down_up_flat_arc_r_dimension(
            doc,
            r_form_dim,
            tile_section.forming_spec.R_form,
            geometry,
            upper_arc=(
                tile_section.process_type == "tile"
                or tile_section.arc_side == "upper"
            ),
        )


def _find_down_up_flat_arc_opening_dimension(dimensions, geometry: SlotDimensionGeometry):
    for dimension in dimensions:
        if not (dimension.dxf.hasattr("defpoint2") and dimension.dxf.hasattr("defpoint3")):
            continue
        p2 = dimension.dxf.defpoint2
        p3 = dimension.dxf.defpoint3
        if abs(p2.y - p3.y) > 0.001:
            continue
        if abs(p2.y - geometry.outer_top) > 0.01:
            continue
        try:
            measurement = float(dimension.get_measurement())
        except Exception:
            continue
        if 1.0 <= measurement <= 6.0:
            return dimension
    return None


def _update_down_up_flat_arc_opening_dimension(
    doc,
    dimension,
    geometry: SlotDimensionGeometry,
) -> None:
    old_left = min(float(dimension.dxf.defpoint2.x), float(dimension.dxf.defpoint3.x))
    old_right = max(float(dimension.dxf.defpoint2.x), float(dimension.dxf.defpoint3.x))
    new_left = geometry.opening_left_x
    new_right = geometry.opening_right_x
    dimension.dxf.defpoint2 = (new_left, geometry.outer_top, dimension.dxf.defpoint2.z)
    dimension.dxf.defpoint3 = (new_right, geometry.outer_top, dimension.dxf.defpoint3.z)
    label = _format_compact_decimal(geometry.center_opening)
    dimension.dxf.text = label
    _set_dimension_actual_measurement(dimension, geometry.center_opening)
    _transform_dimension_block(
        doc,
        dimension,
        lambda point: (
            (
                new_left
                + (point.x - old_left) / max(old_right - old_left, 1e-9) * (new_right - new_left)
                if old_left - 0.001 <= point.x <= old_right + 0.001
                else point.x
            ),
            point.y,
            point.z,
        ),
    )
    _set_dimension_block_text(doc, dimension, label)
    set_dimension_role(dimension, SECTION_CENTER_OPENING)


def _find_down_up_flat_arc_thickness_dimension(dimensions, geometry: SlotDimensionGeometry):
    for dimension in dimensions:
        if not (dimension.dxf.hasattr("defpoint2") and dimension.dxf.hasattr("defpoint3")):
            continue
        p2 = dimension.dxf.defpoint2
        p3 = dimension.dxf.defpoint3
        if abs(p2.x - p3.x) > 0.001:
            continue
        if abs(p2.x - geometry.right_x) > 5.0:
            continue
        try:
            measurement = float(dimension.get_measurement())
        except Exception:
            continue
        if 1.0 <= measurement <= 15.0:
            return dimension
    return None


def _find_down_up_flat_arc_r_dimension(dimensions):
    for dimension in dimensions:
        if not (dimension.dxf.hasattr("defpoint") and dimension.dxf.hasattr("defpoint4")):
            continue
        try:
            measurement = float(dimension.get_measurement())
        except Exception:
            continue
        if measurement > 20.0:
            return dimension
    return None


def _remove_unbound_flat_arc_slot_base_dimension(modelspace, geometry: SlotDimensionGeometry) -> None:
    """Remove the template's 12 mm datum when a lower-facing arc replaces its point."""
    for dimension in list(modelspace.query("DIMENSION")):
        if not (dimension.dxf.hasattr("defpoint2") and dimension.dxf.hasattr("defpoint3")):
            continue
        try:
            measurement = float(dimension.get_measurement())
        except Exception:
            continue
        if abs(measurement - (geometry.base_y - geometry.outer_bottom)) > 0.01:
            continue
        p2 = dimension.dxf.defpoint2
        p3 = dimension.dxf.defpoint3
        if (
            abs(float(p2.x) - geometry.center_x) <= 0.01
            and abs(float(p2.y) - geometry.base_y) <= 0.01
            and abs(float(p3.y) - geometry.outer_bottom) <= 0.01
        ):
            modelspace.delete_entity(dimension)


def _update_down_up_flat_arc_r_dimension(
    doc,
    dimension,
    radius: float,
    geometry: SlotDimensionGeometry,
    upper_arc: bool = False,
) -> None:
    old_center = dimension.dxf.defpoint
    new_center = geometry.upper_radius_center if upper_arc else geometry.lower_radius_center
    target_dx = min(geometry.slot_width / 2.0 - geometry.relief_radius, radius * 0.95)
    target_y_offset = sqrt(radius * radius - target_dx * target_dx)
    target_points_upward = upper_arc or new_center[1] <= geometry.base_y
    target = (
        geometry.center_x + target_dx,
        new_center[1] + (target_y_offset if target_points_upward else -target_y_offset),
        0.0,
    )
    leader_y = geometry.top_y + 5.0 if upper_arc else geometry.base_y + 7.0
    leader_end = (geometry.outer_right + 1.0, leader_y, 0.0)
    text_insert = (geometry.outer_right + 3.0, leader_y - 0.3, 0.0)
    dimension.dxf.defpoint = (new_center[0], new_center[1], old_center.z)
    dimension.dxf.defpoint4 = target
    dimension.dxf.text_midpoint = text_insert
    label = f"R{radius:.2f}"
    dimension.dxf.text = label
    _set_dimension_actual_measurement(dimension, radius)
    _set_radius_dimension_block_layout(doc, dimension, label, new_center, radius, target, leader_end, text_insert)


def _set_radius_dimension_block_layout(
    doc,
    dimension,
    label: str,
    center: tuple[float, float],
    radius: float,
    target: tuple[float, float, float],
    leader_end: tuple[float, float, float],
    text_insert: tuple[float, float, float],
) -> None:
    if not dimension.dxf.hasattr("geometry") or dimension.dxf.geometry not in doc.blocks:
        return
    line_updated = False
    for entity in doc.blocks[dimension.dxf.geometry]:
        if entity.dxftype() == "TEXT":
            entity.dxf.text = label
            entity.dxf.insert = text_insert
        elif entity.dxftype() == "MTEXT":
            entity.text = label
            entity.dxf.insert = text_insert
        elif entity.dxftype() == "LINE" and not line_updated:
            entity.dxf.start = target
            entity.dxf.end = leader_end
            line_updated = True
        elif entity.dxftype() == "ARC":
            entity.dxf.center = (center[0], center[1], 0.0)
            entity.dxf.radius = radius


def _write_block_template_based_dxf(
    block_section: BlockGuideSection,
    output_path: Path,
    ezdxf,
    machine_config: MachineConfig,
    output_mode: str,
) -> Path:
    doc = ezdxf.readfile(machine_config.section_template_path)
    modelspace = doc.modelspace()

    _ensure_layer(doc, "FIXED_TEMPLATE", color=7)
    _ensure_layer(doc, "PARAM_SLOT", color=PARAM_SLOT_COLOR)
    _ensure_layer(doc, SECTION_CENTER_LAYER, color=1, linetype="CENTER")
    _ensure_layer(doc, DIMENSION_LAYER, color=3)
    _ensure_layer(doc, TEXT_NOTE_LAYER, color=4)
    if output_mode == "debug":
        _ensure_layer(doc, DEBUG_CONTROL_LAYER, color=6)
        _ensure_layer(doc, DEBUG_POINTS_LAYER, color=5)
    _ensure_dimension_text_style(doc)

    anchor = _extract_block_template_anchor(modelspace)
    is_triple_down_up = machine_config.machine_id == "triple_single_down_up"
    is_dual_spec_rectangular = (
        block_section.process_type == "block_to_bread_rectangular"
    )
    use_reference_rectangular_rebuild = (
        is_triple_down_up or is_dual_spec_rectangular
    )
    slot_base_y = (
        anchor.bottom + machine_config.section_slot_base_height
        if is_triple_down_up
        else _extract_existing_block_slot_base_y(modelspace, anchor)
    )
    if machine_config.side_layout.block_side_mode == "fixed_top_gap":
        fixed_top_gap = machine_config.side_layout.block_fixed_top_gap
        if fixed_top_gap is None:
            raise ValueError("fixed_top_gap block side-view mode requires block_fixed_top_gap.")
        slot_base_y = anchor.top - fixed_top_gap - block_section.guide_spec.guide_thickness
    to_delete = []
    for entity in list(modelspace):
        if (
            _is_down_up_flat_arc_template_param_entity(entity, anchor)
            if use_reference_rectangular_rebuild
            else _is_block_template_param_entity(entity, anchor)
        ):
            to_delete.append(entity)
        elif entity.dxftype() == "DIMENSION":
            entity.dxf.layer = DIMENSION_LAYER
        elif _is_section_center_entity(entity):
            entity.dxf.layer = SECTION_CENTER_LAYER
            entity.dxf.color = 256
            entity.dxf.linetype = "BYLAYER"
        else:
            entity.dxf.layer = "FIXED_TEMPLATE"
    for entity in to_delete:
        modelspace.delete_entity(entity)

    slot_geometry = _add_block_slot_entities(modelspace, block_section, anchor, slot_base_y)
    _rebuild_section_top_boundary(modelspace, slot_geometry)
    if use_reference_rectangular_rebuild:
        _update_down_up_rectangular_template_dimensions(
            doc,
            modelspace,
            block_section,
            slot_geometry,
        )
    else:
        _update_block_template_dimensions(doc, modelspace, block_section, slot_geometry)
    if output_mode == "debug":
        _add_debug_entities(modelspace, slot_geometry)
    add_side_view_to_dxf(
        doc,
        modelspace,
        block_section,  # type: ignore[arg-type]
        output_mode=output_mode,
        template_path=machine_config.side_template_path,
        layout=machine_config.side_layout,
        side_style=(
            "triple_single_down_up"
            if is_triple_down_up
            else _side_style_for_machine(machine_config)
        ),
        wheel_positions=machine_config.wheel_positions,
        wheel_radius=machine_config.wheel_radius,
    )
    if output_mode == "release":
        _simplify_release_layers(doc)
        assert_side_view_consistency(
            doc,
            block_section,
            machine_config=machine_config,
        )
    normalize_dimension_display_precision(doc, modelspace)
    doc.saveas(output_path)
    return output_path


class TemplateAnchor:
    def __init__(
        self,
        left: float,
        right: float,
        bottom: float,
        top: float,
        slot_center_x: float,
        slot_base_height: float = 12.0,
    ) -> None:
        self.left = left
        self.right = right
        self.bottom = bottom
        self.top = top
        self.slot_center_x = slot_center_x
        self.slot_base_height = slot_base_height

    @property
    def slot_base_y(self) -> float:
        return self.bottom + self.slot_base_height


def _extract_block_template_anchor(modelspace) -> TemplateAnchor:
    horizontal_candidates = []
    vertical_candidates = []
    for entity in modelspace.query("LINE"):
        start = entity.dxf.start
        end = entity.dxf.end
        dx = abs(end.x - start.x)
        dy = abs(end.y - start.y)
        if _close(dy, 0.0) and 30.0 <= dx <= 40.0:
            horizontal_candidates.append(entity)
        if _close(dx, 0.0) and _close(dy, 27.0):
            vertical_candidates.append(entity)

    if not horizontal_candidates or len(vertical_candidates) < 2:
        raise ValueError("Could not identify block guide template frame in DXF.")

    bottom_line = min(horizontal_candidates, key=lambda entity: entity.dxf.start.y)
    left = min(bottom_line.dxf.start.x, bottom_line.dxf.end.x)
    right = max(bottom_line.dxf.start.x, bottom_line.dxf.end.x)
    bottom = bottom_line.dxf.start.y
    top = bottom + 27.0
    slot_center_x = (left + right) / 2.0
    return TemplateAnchor(left=left, right=right, bottom=bottom, top=top, slot_center_x=slot_center_x)


def _extract_existing_block_slot_base_y(modelspace, anchor: TemplateAnchor) -> float:
    candidates = []
    for entity in modelspace.query("DIMENSION"):
        try:
            measurement = float(entity.get_measurement())
        except Exception:
            continue
        if measurement < 4.0:
            continue
        if not (entity.dxf.hasattr("defpoint2") and entity.dxf.hasattr("defpoint3")):
            continue
        p2 = entity.dxf.defpoint2
        p3 = entity.dxf.defpoint3
        if abs(p2.y - p3.y) < 0.001 and anchor.bottom <= p2.y <= anchor.top:
            candidates.append(p2.y)
    if candidates:
        return min(candidates)
    return anchor.bottom + 21.85


def _is_block_template_param_entity(entity, anchor: TemplateAnchor) -> bool:
    if entity.dxftype() == "DIMENSION":
        return False
    if entity.dxftype() == "ARC":
        center = entity.dxf.center
        return (
            anchor.left - 2.0 <= center.x <= anchor.right + 2.0
            and anchor.bottom <= center.y <= anchor.top + 2.0
            and entity.dxf.radius <= 5.0
        )
    if entity.dxftype() == "LINE":
        start = entity.dxf.start
        end = entity.dxf.end
        if _line_is_outer_frame(start, end, anchor):
            return False
        return (
            anchor.left <= start.x <= anchor.right
            and anchor.left <= end.x <= anchor.right
            and anchor.bottom <= start.y <= anchor.top
            and anchor.bottom <= end.y <= anchor.top
        )
    return False


def _add_block_slot_entities(
    modelspace,
    block_section: BlockGuideSection,
    anchor: TemplateAnchor,
    slot_base_y: float,
) -> SlotDimensionGeometry:
    guide = block_section.guide_spec
    relief_radius = guide.relief.relief_size / 2.0
    center_transition_radius = CENTER_TRANSITION_RADIUS
    half_slot = guide.guide_slot_width / 2.0
    center_x = anchor.slot_center_x
    left_x = center_x - half_slot
    right_x = center_x + half_slot
    bottom_y = slot_base_y
    top_y = slot_base_y + guide.guide_thickness
    neck_width = guide.center_opening
    neck_left_x = center_x - neck_width / 2.0
    neck_right_x = center_x + neck_width / 2.0
    neck_bottom_y = top_y + center_transition_radius
    r = relief_radius

    if top_y - bottom_y <= 2.0 * r:
        raise ValueError("Block guide thickness is too small for relief geometry.")
    if right_x - left_x <= neck_width + 4.0 * r:
        raise ValueError("Block guide slot width is too small for relief geometry.")

    _add_line(modelspace, (neck_left_x, anchor.top), (neck_left_x, neck_bottom_y), "PARAM_SLOT")
    _add_line(modelspace, (neck_right_x, anchor.top), (neck_right_x, neck_bottom_y), "PARAM_SLOT")
    _add_line(modelspace, (left_x + r, bottom_y), (right_x - r, bottom_y), "PARAM_SLOT")
    _add_line(modelspace, (right_x, bottom_y + r), (right_x, top_y - r), "PARAM_SLOT")
    _add_line(modelspace, (right_x - r, top_y), (neck_right_x + center_transition_radius, top_y), "PARAM_SLOT")
    _add_line(modelspace, (neck_left_x - center_transition_radius, top_y), (left_x + r, top_y), "PARAM_SLOT")
    _add_line(modelspace, (left_x, top_y - r), (left_x, bottom_y + r), "PARAM_SLOT")
    modelspace.add_arc((neck_right_x + center_transition_radius, neck_bottom_y), center_transition_radius, 180.0, 270.0, dxfattribs={"layer": "PARAM_SLOT"})
    modelspace.add_arc((neck_left_x - center_transition_radius, neck_bottom_y), center_transition_radius, 270.0, 0.0, dxfattribs={"layer": "PARAM_SLOT"})
    modelspace.add_arc((right_x, top_y), r, 270.0, 180.0, dxfattribs={"layer": "PARAM_SLOT"})
    modelspace.add_arc((right_x, bottom_y), r, 180.0, 90.0, dxfattribs={"layer": "PARAM_SLOT"})
    modelspace.add_arc((left_x, top_y), r, 0.0, 270.0, dxfattribs={"layer": "PARAM_SLOT"})
    modelspace.add_arc((left_x, bottom_y), r, 90.0, 0.0, dxfattribs={"layer": "PARAM_SLOT"})

    return SlotDimensionGeometry(
        left_x=left_x,
        right_x=right_x,
        base_y=bottom_y,
        top_y=top_y,
        opening_left_x=neck_left_x,
        opening_right_x=neck_right_x,
        center_x=center_x,
        outer_left=anchor.left,
        outer_right=anchor.right,
        outer_bottom=anchor.bottom,
        outer_top=anchor.top,
        upper_radius_center=(center_x, top_y),
        lower_radius_center=(center_x, bottom_y),
        relief_radius=relief_radius,
        center_transition_radius=center_transition_radius,
        center_transition_left_center=(
            neck_left_x - center_transition_radius,
            neck_bottom_y,
        ),
        center_transition_right_center=(
            neck_right_x + center_transition_radius,
            neck_bottom_y,
        ),
    )


def _add_block_slot_dimensions(
    modelspace,
    block_section: BlockGuideSection,
    geometry: SlotDimensionGeometry,
    include_debug: bool,
) -> None:
    guide = block_section.guide_spec
    add_linear_dimension_with_text(
        modelspace,
        (geometry.left_x, geometry.base_y),
        (geometry.right_x, geometry.base_y),
        (geometry.left_x, geometry.base_y - 13.2),
        (geometry.right_x, geometry.base_y - 13.2),
        guide.slot_width_dimension_text,
        (geometry.center_x - 2.4, geometry.base_y - 15.2),
        angle=0.0,
        include_fallback=include_debug,
        include_native=True,
    )
    add_linear_dimension_with_text(
        modelspace,
        (geometry.right_x, geometry.base_y),
        (geometry.right_x, geometry.top_y),
        (geometry.right_x + 12.0, geometry.base_y),
        (geometry.right_x + 12.0, geometry.top_y),
        f"{guide.guide_thickness:.2f}",
        (geometry.right_x + 13.6, (geometry.base_y + geometry.top_y) / 2.0 - 0.35),
        angle=90.0,
        text_rotation=90.0,
        include_fallback=include_debug,
        include_native=True,
    )
    _add_block_fixed_relief_dimensions(modelspace, block_section, geometry, include_debug=include_debug)


def _add_block_fixed_relief_dimensions(
    modelspace,
    block_section: BlockGuideSection,
    geometry: SlotDimensionGeometry,
    include_debug: bool,
) -> None:
    relief_radius = geometry.relief_radius
    relief_size = relief_radius * 2.0
    upper_left_center = (geometry.left_x + relief_radius, geometry.top_y - relief_radius)
    add_radius_dimension_with_text(
        modelspace,
        (upper_left_center[0] - relief_radius * 0.6, upper_left_center[1] + relief_radius * 0.6),
        (upper_left_center[0] - 2.0, upper_left_center[1] + 1.8),
        "2-<>",
        (upper_left_center[0] - 3.8, upper_left_center[1] + 2.0),
        center=upper_left_center,
        radius=relief_radius,
        angle=135.0,
        include_fallback=include_debug,
        include_native=True,
    )


def _update_block_template_dimensions(
    doc,
    modelspace,
    block_section: BlockGuideSection,
    geometry: SlotDimensionGeometry,
) -> None:
    guide = block_section.guide_spec
    dimensions = list(modelspace.query("DIMENSION"))
    slot_width_dim = _find_block_slot_width_dimension(dimensions, geometry)
    thickness_dim = _find_block_thickness_dimension(dimensions, geometry)
    relief_radius_dim = _find_dimension_by_text(dimensions, "2-<>")
    relief_size_dim = _find_dimension_by_text(dimensions, "4-<>")
    top_gap_dim = _find_block_top_gap_dimension(dimensions, geometry)
    height_dim = _find_dimension_by_text(dimensions, "18")

    for dimension in dimensions:
        dimension.dxf.layer = DIMENSION_LAYER

    if slot_width_dim is not None:
        _update_block_slot_width_dimension(doc, slot_width_dim, guide.slot_width_dimension_text, geometry)
    if thickness_dim is not None:
        _update_block_thickness_dimension(doc, thickness_dim, f"{guide.guide_thickness:.2f}", geometry)
    if relief_radius_dim is not None:
        _update_block_relief_radius_dimension(doc, relief_radius_dim, geometry)
    if relief_size_dim is not None:
        _update_block_relief_size_dimension(
            doc,
            relief_size_dim,
            geometry,
            bind_as_diameter=True,
        )
    if top_gap_dim is not None:
        _update_block_top_gap_dimension(doc, top_gap_dim, geometry)
    if height_dim is not None:
        _set_dimension_actual_measurement(height_dim, geometry.slot_base_height)
        height_dim.dxf.text = _format_compact_decimal(geometry.slot_base_height)
        _set_dimension_block_text(doc, height_dim, _format_compact_decimal(geometry.slot_base_height))


def _update_down_up_rectangular_template_dimensions(
    doc,
    modelspace,
    block_section: BlockGuideSection,
    geometry: SlotDimensionGeometry,
) -> None:
    """Rebind the archived down/up dimensions to a rectangular groove."""
    guide = block_section.guide_spec
    dimensions = list(modelspace.query("DIMENSION"))
    slot_width_dim = _find_block_slot_width_dimension(dimensions, geometry)
    thickness_dim = _find_down_up_flat_arc_thickness_dimension(
        dimensions,
        geometry,
    )
    if thickness_dim is None:
        thickness_dim = _find_rectangular_thickness_dimension(
            dimensions,
            geometry,
        )
    opening_dim = _find_down_up_flat_arc_opening_dimension(
        dimensions,
        geometry,
    )
    relief_size_dim = _find_dimension_by_text(dimensions, "4-<>")
    relief_radius_dim = _find_dimension_by_text(dimensions, "2-<>")
    radius_dimensions = [
        dimension
        for dimension in dimensions
        if dimension.dxf.hasattr("defpoint")
        and dimension.dxf.hasattr("defpoint4")
        and 5.0 < float(dimension.get_measurement()) < 200.0
        and _dimension_near_geometry(dimension, geometry)
    ]

    for dimension in dimensions:
        dimension.dxf.layer = DIMENSION_LAYER
    if slot_width_dim is not None:
        _update_block_slot_width_dimension(
            doc,
            slot_width_dim,
            guide.slot_width_dimension_text,
            geometry,
        )
    if thickness_dim is not None:
        _update_block_thickness_dimension(
            doc,
            thickness_dim,
            f"{guide.guide_thickness:.2f}",
            geometry,
        )
    if opening_dim is not None:
        _update_down_up_flat_arc_opening_dimension(
            doc,
            opening_dim,
            geometry,
        )
    if relief_size_dim is not None:
        _update_flat_arc_relief_diameter_dimension(
            doc,
            relief_size_dim,
            geometry,
        )
    if relief_radius_dim is not None:
        _update_block_relief_radius_dimension(
            doc,
            relief_radius_dim,
            geometry,
        )
    for dimension in radius_dimensions:
        modelspace.delete_entity(dimension)


def _dimension_near_geometry(
    dimension,
    geometry: SlotDimensionGeometry,
) -> bool:
    points = []
    for name in ("defpoint", "defpoint4", "text_midpoint"):
        if dimension.dxf.hasattr(name):
            point = dimension.dxf.get(name)
            points.append((float(point.x), float(point.y)))
    return any(
        geometry.outer_left - 30.0 <= x <= geometry.outer_right + 30.0
        and geometry.outer_bottom - 130.0 <= y <= geometry.outer_top + 40.0
        for x, y in points
    )


def _find_rectangular_thickness_dimension(
    dimensions,
    geometry: SlotDimensionGeometry,
):
    candidates = []
    for dimension in dimensions:
        if not (
            dimension.dxf.hasattr("defpoint2")
            and dimension.dxf.hasattr("defpoint3")
        ):
            continue
        try:
            measurement = float(dimension.get_measurement())
        except Exception:
            continue
        if not (0.5 <= measurement <= 5.0):
            continue
        p2 = dimension.dxf.defpoint2
        p3 = dimension.dxf.defpoint3
        points = (p2, p3)
        distance = min(
            hypot(
                float(point.x) - geometry.right_x,
                float(point.y) - geometry.base_y,
            )
            for point in points
        )
        if distance <= 5.0:
            candidates.append((distance, dimension))
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[0])[1]


def _find_block_slot_width_dimension(dimensions, geometry: SlotDimensionGeometry):
    for dimension in dimensions:
        if not (dimension.dxf.hasattr("defpoint2") and dimension.dxf.hasattr("defpoint3")):
            continue
        p2 = dimension.dxf.defpoint2
        p3 = dimension.dxf.defpoint3
        if abs(p2.y - p3.y) > 0.001:
            continue
        try:
            measurement = float(dimension.get_measurement())
        except Exception:
            continue
        if not (4.0 <= measurement <= 20.0):
            continue
        text = dimension.dxf.text if dimension.dxf.hasattr("text") else ""
        if "\\S+0" in text or "±" in text:
            return dimension
        if abs(p2.y - geometry.base_y) <= 1.0 and abs(measurement - geometry.slot_width) <= 5.0:
            return dimension
    return None


def _find_block_thickness_dimension(dimensions, geometry: SlotDimensionGeometry):
    for dimension in dimensions:
        if not (dimension.dxf.hasattr("defpoint2") and dimension.dxf.hasattr("defpoint3")):
            continue
        p2 = dimension.dxf.defpoint2
        p3 = dimension.dxf.defpoint3
        if abs(p2.x - p3.x) > 0.001:
            continue
        if abs(p2.x - geometry.right_x) > 5.0 and abs(p3.x - geometry.right_x) > 5.0:
            continue
        try:
            measurement = float(dimension.get_measurement())
        except Exception:
            continue
        if 0.5 <= measurement <= 5.0:
            return dimension
    return None


def _find_block_top_gap_dimension(dimensions, geometry: SlotDimensionGeometry):
    for dimension in dimensions:
        text = dimension.dxf.text if dimension.dxf.hasattr("text") else ""
        if not (dimension.dxf.hasattr("defpoint2") and dimension.dxf.hasattr("defpoint3")):
            continue
        p2 = dimension.dxf.defpoint2
        p3 = dimension.dxf.defpoint3
        try:
            measurement = float(dimension.get_measurement())
        except Exception:
            continue
        if not (1.0 <= measurement <= 10.0):
            continue
        if abs(p2.y - p3.y) <= 0.001:
            continue
        if text and text not in {"6.85", "5.75"}:
            continue
        touches_outer_top = abs(p2.y - geometry.outer_top) <= 0.001 or abs(p3.y - geometry.outer_top) <= 0.001
        if touches_outer_top:
            return dimension
    return None


def _find_dimension_by_text(dimensions, text: str):
    for dimension in dimensions:
        if dimension.dxf.hasattr("text") and dimension.dxf.text == text:
            return dimension
    return None


def _update_block_slot_width_dimension(doc, dimension, label: str, geometry: SlotDimensionGeometry) -> None:
    old_left = dimension.dxf.defpoint2.x
    old_right = dimension.dxf.defpoint3.x
    old_base = dimension.dxf.defpoint2.y
    dimension.dxf.defpoint2 = (geometry.left_x, geometry.base_y, dimension.dxf.defpoint2.z)
    dimension.dxf.defpoint3 = (geometry.right_x, geometry.base_y, dimension.dxf.defpoint3.z)
    dimension.dxf.text = label
    _set_dimension_actual_measurement(dimension, geometry.slot_width)
    _transform_dimension_block(
        doc,
        dimension,
        lambda point: _map_slot_dimension_point(
            point,
            old_left,
            old_right,
            geometry.left_x,
            geometry.right_x,
            old_base,
            geometry.base_y,
        ),
    )
    slot_text = label.replace("\u00b10.01", r"{\H0.7x;\S+0.01^ -0.01;} ")
    _set_dimension_block_text(doc, dimension, slot_text)


def _update_block_thickness_dimension(doc, dimension, label: str, geometry: SlotDimensionGeometry) -> None:
    old_x = dimension.dxf.defpoint2.x
    old_y1 = dimension.dxf.defpoint2.y
    old_y2 = dimension.dxf.defpoint3.y
    old_bottom = min(old_y1, old_y2)
    old_top = max(old_y1, old_y2)
    dimension.dxf.defpoint2 = (geometry.right_x, geometry.top_y, dimension.dxf.defpoint2.z)
    dimension.dxf.defpoint3 = (geometry.right_x, geometry.base_y, dimension.dxf.defpoint3.z)
    dimension.dxf.text = label
    _set_dimension_actual_measurement(dimension, geometry.guide_thickness)
    _transform_dimension_block(
        doc,
        dimension,
        lambda point: _map_thickness_dimension_point(
            point,
            old_x,
            geometry.right_x,
            old_bottom,
            old_top,
            geometry.base_y,
            geometry.top_y,
        ),
    )
    _set_dimension_block_text(doc, dimension, label)


def _update_block_relief_radius_dimension(doc, dimension, geometry: SlotDimensionGeometry) -> None:
    old_center = dimension.dxf.defpoint
    old_target = dimension.dxf.defpoint4
    new_center = geometry.center_transition_right_center or (
        geometry.opening_right_x + geometry.center_transition_radius,
        geometry.top_y + geometry.center_transition_radius,
    )
    dimension.dxf.defpoint = (new_center[0], new_center[1], old_center.z)
    dimension.dxf.defpoint4 = (
        new_center[0],
        new_center[1] - geometry.center_transition_radius,
        old_target.z,
    )
    dimension.dxf.text = "2-<>"
    _set_dimension_actual_measurement(dimension, geometry.center_transition_radius)
    _transform_dimension_block(
        doc,
        dimension,
        lambda point: (point.x + new_center[0] - old_center.x, point.y + new_center[1] - old_center.y, point.z),
    )
    _set_dimension_block_text(
        doc,
        dimension,
        f"2-R{geometry.center_transition_radius:.2f}",
    )


def _update_block_relief_size_dimension(
    doc,
    dimension,
    geometry: SlotDimensionGeometry,
    bind_as_diameter: bool = False,
) -> None:
    if bind_as_diameter:
        _update_flat_arc_relief_diameter_dimension(doc, dimension, geometry)
        return
    old_point = dimension.dxf.defpoint
    old_target = dimension.dxf.defpoint4
    new_point = (geometry.left_x, geometry.top_y - geometry.relief_radius)
    dx = old_target.x - old_point.x
    dy = old_target.y - old_point.y
    dimension.dxf.defpoint = (new_point[0], new_point[1], old_point.z)
    dimension.dxf.defpoint4 = (new_point[0] + dx, new_point[1] + dy, old_target.z)
    dimension.dxf.text = "4-<>"
    _set_dimension_actual_measurement(dimension, geometry.relief_radius * 2.0)
    _transform_dimension_block(
        doc,
        dimension,
        lambda point: (point.x + new_point[0] - old_point.x, point.y + new_point[1] - old_point.y, point.z),
    )
    _set_dimension_block_text(doc, dimension, f"4-\u2205{geometry.relief_radius * 2.0:.2f}")


def _update_flat_arc_relief_diameter_dimension(
    doc,
    dimension,
    geometry: SlotDimensionGeometry,
) -> None:
    old_point = dimension.dxf.defpoint
    old_target = dimension.dxf.defpoint4
    old_center = (
        (float(old_point.x) + float(old_target.x)) / 2.0,
        (float(old_point.y) + float(old_target.y)) / 2.0,
    )
    new_center = (geometry.left_x, geometry.top_y)
    dx = float(old_target.x) - float(old_point.x)
    dy = float(old_target.y) - float(old_point.y)
    length = hypot(dx, dy)
    if length <= 1e-9:
        raise ValueError("Relief diameter dimension has coincident definition points.")
    ux = dx / length
    uy = dy / length
    radius = geometry.relief_radius
    dimension.dxf.defpoint = (
        new_center[0] - ux * radius,
        new_center[1] - uy * radius,
        old_point.z,
    )
    dimension.dxf.defpoint4 = (
        new_center[0] + ux * radius,
        new_center[1] + uy * radius,
        old_target.z,
    )
    dimension.dxf.text = "4-<>"
    _set_dimension_actual_measurement(dimension, radius * 2.0)
    _transform_dimension_block(
        doc,
        dimension,
        lambda point: (
            point.x + new_center[0] - old_center[0],
            point.y + new_center[1] - old_center[1],
            point.z,
        ),
    )
    _set_dimension_block_text(doc, dimension, f"4-\u2205{radius * 2.0:.2f}")


def _update_block_top_gap_dimension(doc, dimension, geometry: SlotDimensionGeometry) -> None:
    old_x = dimension.dxf.defpoint2.x
    old_y = dimension.dxf.defpoint2.y
    top_gap = geometry.outer_top - geometry.top_y
    dimension.dxf.defpoint2 = (geometry.right_x, geometry.top_y, dimension.dxf.defpoint2.z)
    dimension.dxf.defpoint3 = (geometry.outer_right, geometry.outer_top, dimension.dxf.defpoint3.z)
    label = _format_compact_decimal(top_gap)
    dimension.dxf.text = label
    _set_dimension_actual_measurement(dimension, top_gap)
    _transform_dimension_block(
        doc,
        dimension,
        lambda point: _map_top_gap_dimension_point(point, old_x, geometry.right_x, old_y, geometry.top_y),
    )
    _set_dimension_block_text(doc, dimension, label)


def _map_slot_dimension_point(point, old_left, old_right, new_left, new_right, old_base, new_base):
    x = point.x
    if old_left - 0.001 <= point.x <= old_right + 0.001:
        ratio = (point.x - old_left) / (old_right - old_left)
        x = new_left + ratio * (new_right - new_left)
    elif abs(point.x - old_left) <= 0.001:
        x = new_left
    elif abs(point.x - old_right) <= 0.001:
        x = new_right
    y = new_base + (point.y - old_base) if abs(point.y - old_base) <= 20.0 else point.y
    return (x, y, point.z)


def _map_thickness_dimension_point(point, old_x, new_x, old_bottom, old_top, new_bottom, new_top):
    x = new_x if abs(point.x - old_x) <= 0.001 else point.x
    y = point.y
    if abs(point.y - old_bottom) <= 0.001:
        y = new_bottom
    elif abs(point.y - old_top) <= 0.001:
        y = new_top
    elif old_bottom <= point.y <= old_top:
        ratio = (point.y - old_bottom) / (old_top - old_bottom)
        y = new_bottom + ratio * (new_top - new_bottom)
    return (x, y, point.z)


def _map_top_gap_dimension_point(point, old_x, new_x, old_y, new_y):
    x = new_x if abs(point.x - old_x) <= 0.001 else point.x
    y = new_y if abs(point.y - old_y) <= 0.001 else point.y
    return (x, y, point.z)


def _transform_dimension_block(doc, dimension, transform) -> None:
    if not dimension.dxf.hasattr("geometry") or dimension.dxf.geometry not in doc.blocks:
        return
    for entity in doc.blocks[dimension.dxf.geometry]:
        for name in ("start", "end", "center", "insert", "location"):
            if entity.dxf.hasattr(name):
                entity.dxf.set(name, transform(entity.dxf.get(name)))
        if entity.dxftype() == "SOLID":
            for name in ("vtx0", "vtx1", "vtx2", "vtx3"):
                if entity.dxf.hasattr(name):
                    entity.dxf.set(name, transform(entity.dxf.get(name)))


def _set_dimension_block_text(doc, dimension, text: str) -> None:
    if not dimension.dxf.hasattr("geometry") or dimension.dxf.geometry not in doc.blocks:
        return
    for entity in doc.blocks[dimension.dxf.geometry]:
        if entity.dxftype() == "TEXT":
            entity.dxf.text = text
        elif entity.dxftype() == "MTEXT":
            entity.text = text


def _set_dimension_actual_measurement(dimension, value: float) -> None:
    dimension.dxf.actual_measurement = value


def _format_compact_decimal(value: float) -> str:
    return f"{value:.2f}"
    add_linear_dimension_with_text(
        modelspace,
        (geometry.left_x, geometry.top_y - relief_radius),
        (geometry.left_x + relief_size, geometry.top_y - relief_radius),
        (geometry.left_x - 1.5, geometry.top_y - relief_radius + 2.0),
        (geometry.left_x + relief_size - 1.5, geometry.top_y - relief_radius + 2.0),
        "4-<>",
        (geometry.left_x - 4.2, geometry.top_y - relief_radius + 2.2),
        angle=0.0,
        include_fallback=include_debug,
        include_native=True,
    )


def _extract_template_anchor(modelspace, tile_section: TileSection) -> TemplateAnchor:
    guide = tile_section.guide_spec
    width = guide.outer_width
    height = guide.outer_height
    horizontal_candidates = []
    vertical_candidates = []
    for entity in modelspace.query("LINE"):
        start = entity.dxf.start
        end = entity.dxf.end
        dx = abs(end.x - start.x)
        dy = abs(end.y - start.y)
        if _close(dy, 0.0) and _close(dx, width):
            horizontal_candidates.append(entity)
        if _close(dx, 0.0) and _close(dy, height):
            vertical_candidates.append(entity)

    if not horizontal_candidates or len(vertical_candidates) < 2:
        raise ValueError("Could not identify fixed 33 x 27 guide template frame in DXF.")

    bottom_line = min(horizontal_candidates, key=lambda entity: entity.dxf.start.y)
    left = min(bottom_line.dxf.start.x, bottom_line.dxf.end.x)
    right = max(bottom_line.dxf.start.x, bottom_line.dxf.end.x)
    bottom = bottom_line.dxf.start.y
    top = bottom + height
    slot_center_x = (left + right) / 2.0
    return TemplateAnchor(
        left=left,
        right=right,
        bottom=bottom,
        top=top,
        slot_center_x=slot_center_x,
        slot_base_height=guide.slot_base_height,
    )


def _is_template_param_entity(entity, anchor: TemplateAnchor, tile_section: TileSection) -> bool:
    if entity.dxftype() == "ARC":
        center = entity.dxf.center
        radius = entity.dxf.radius
        if _arc_is_inside_slot_work_area(center, radius, anchor):
            return True
    if entity.dxftype() == "LINE":
        start = entity.dxf.start
        end = entity.dxf.end
        if _line_is_inside_slot_work_area(start, end, anchor):
            if _line_is_outer_frame(start, end, anchor):
                return False
            if _line_is_top_fixed_segment(start, end, anchor):
                return False
            return True
    if entity.dxftype() == "DIMENSION":
        return True
    return False


def _arc_is_inside_slot_work_area(center, radius: float, anchor: TemplateAnchor) -> bool:
    min_x = anchor.slot_center_x - 8.0
    max_x = anchor.slot_center_x + 8.0
    min_y = anchor.bottom - 30.0
    max_y = anchor.top + 5.0
    param_radius = radius <= 2.0 or 5.0 <= radius <= 80.0
    return min_x <= center.x <= max_x and min_y <= center.y <= max_y and param_radius


def _line_is_inside_slot_work_area(start, end, anchor: TemplateAnchor) -> bool:
    min_x = anchor.slot_center_x - 5.0
    max_x = anchor.slot_center_x + 5.0
    min_y = anchor.slot_base_y - 2.0
    max_y = anchor.top + 0.5
    return (
        min_x <= start.x <= max_x
        and min_x <= end.x <= max_x
        and min_y <= start.y <= max_y
        and min_y <= end.y <= max_y
    )


def _line_is_outer_frame(start, end, anchor: TemplateAnchor) -> bool:
    xs = sorted((start.x, end.x))
    ys = sorted((start.y, end.y))
    return (
        (_close(start.y, end.y) and (_close(start.y, anchor.bottom) or _close(start.y, anchor.top)))
        or (_close(start.x, end.x) and (_close(start.x, anchor.left) or _close(start.x, anchor.right)))
        or (_close(xs[0], anchor.left) and _close(xs[1], anchor.right))
        or (_close(ys[0], anchor.bottom) and _close(ys[1], anchor.top))
    )


def _line_is_top_fixed_segment(start, end, anchor: TemplateAnchor) -> bool:
    return _close(start.y, anchor.top) and _close(end.y, anchor.top)


def _is_section_center_entity(entity) -> bool:
    if entity.dxftype() != "LINE":
        return False
    layer = entity.dxf.layer
    linetype = getattr(entity.dxf, "linetype", "")
    return "中心" in layer or layer.upper() in {"CENTER", "CENTERLINE"} or linetype.upper() == "CENTER"


def _add_fixed_template_entities(modelspace, tile_section: TileSection) -> None:
    guide = tile_section.guide_spec
    half_outer = guide.outer_width / 2.0
    base_y = guide.slot_base_height

    _add_line(modelspace, (-half_outer, 0.0), (half_outer, 0.0), "FIXED_TEMPLATE")
    _add_line(modelspace, (half_outer, 0.0), (half_outer, guide.outer_height), "FIXED_TEMPLATE")
    _add_line(modelspace, (half_outer, guide.outer_height), (-half_outer, guide.outer_height), "FIXED_TEMPLATE")
    _add_line(modelspace, (-half_outer, guide.outer_height), (-half_outer, 0.0), "FIXED_TEMPLATE")
    _add_line(modelspace, (-half_outer, base_y), (half_outer, base_y), "FIXED_TEMPLATE")
    _add_line(
        modelspace,
        (guide.slot_center_offset, 0.0),
        (guide.slot_center_offset, guide.outer_height),
        SECTION_CENTER_LAYER,
    )
    _add_line(
        modelspace,
        (-half_outer, guide.outer_height / 2.0),
        (half_outer, guide.outer_height / 2.0),
        SECTION_CENTER_LAYER,
    )


def _add_param_slot_entities(
    modelspace,
    tile_section: TileSection,
    anchor: TemplateAnchor | None = None,
) -> SlotDimensionGeometry:
    guide = tile_section.guide_spec
    R_form = tile_section.forming_spec.R_form
    relief_radius = guide.relief.relief_size / 2.0
    center_transition_radius = CENTER_TRANSITION_RADIUS
    half_slot = guide.guide_slot_width / 2.0
    base_y = guide.slot_base_height if anchor is None else anchor.slot_base_y
    top_y = base_y + guide.guide_thickness
    x_center = guide.slot_center_offset if anchor is None else anchor.slot_center_x
    opening_half = guide.center_opening / 2.0
    base = sqrt(R_form**2 - half_slot**2)
    lower_center = Point(x_center, base_y - base)
    upper_center = Point(x_center, top_y - base)
    lower_left_relief = Point(x_center - half_slot, base_y)
    lower_right_relief = Point(x_center + half_slot, base_y)
    upper_left_relief = Point(x_center - half_slot, top_y)
    upper_right_relief = Point(x_center + half_slot, top_y)

    lower_left_intersection = _select_circle_intersection(lower_center, R_form, lower_left_relief, relief_radius, "right")
    lower_right_intersection = _select_circle_intersection(lower_center, R_form, lower_right_relief, relief_radius, "left")
    upper_left_intersection = _select_circle_intersection(upper_center, R_form, upper_left_relief, relief_radius, "right")
    upper_right_intersection = _select_circle_intersection(upper_center, R_form, upper_right_relief, relief_radius, "left")
    opening_left_x = x_center - opening_half
    opening_right_x = x_center + opening_half
    center_left_relief = _bread_center_opening_relief_center(
        upper_center,
        R_form,
        opening_left_x,
        center_transition_radius,
        side="left",
    )
    center_right_relief = _bread_center_opening_relief_center(
        upper_center,
        R_form,
        opening_right_x,
        center_transition_radius,
        side="right",
    )
    center_left_arc_tangent = _external_circle_tangent_point(
        upper_center,
        R_form,
        center_left_relief,
        center_transition_radius,
    )
    center_right_arc_tangent = _external_circle_tangent_point(
        upper_center,
        R_form,
        center_right_relief,
        center_transition_radius,
    )
    center_left_vertical_tangent = Point(opening_left_x, center_left_relief.y)
    center_right_vertical_tangent = Point(opening_right_x, center_right_relief.y)

    _add_arc_by_points(modelspace, lower_center, R_form, lower_right_intersection, lower_left_intersection, clockwise=False, layer="PARAM_SLOT")
    _add_arc_by_points(modelspace, upper_center, R_form, center_left_arc_tangent, upper_left_intersection, clockwise=False, layer="PARAM_SLOT")
    _add_arc_by_points(modelspace, upper_center, R_form, upper_right_intersection, center_right_arc_tangent, clockwise=False, layer="PARAM_SLOT")

    _add_relief_arc(modelspace, upper_left_relief, relief_radius, upper_left_intersection, Point(upper_left_relief.x, upper_left_relief.y - relief_radius))
    _add_relief_arc(modelspace, lower_left_relief, relief_radius, Point(lower_left_relief.x, lower_left_relief.y + relief_radius), lower_left_intersection)
    _add_relief_arc(modelspace, lower_right_relief, relief_radius, lower_right_intersection, Point(lower_right_relief.x, lower_right_relief.y + relief_radius))
    _add_relief_arc(modelspace, upper_right_relief, relief_radius, Point(upper_right_relief.x, upper_right_relief.y - relief_radius), upper_right_intersection)
    _add_relief_arc(
        modelspace,
        center_left_relief,
        center_transition_radius,
        center_left_arc_tangent,
        center_left_vertical_tangent,
    )
    _add_relief_arc(
        modelspace,
        center_right_relief,
        center_transition_radius,
        center_right_vertical_tangent,
        center_right_arc_tangent,
    )

    _add_line(modelspace, (lower_left_relief.x, lower_left_relief.y + relief_radius), (upper_left_relief.x, upper_left_relief.y - relief_radius), "PARAM_SLOT")
    _add_line(modelspace, (lower_right_relief.x, lower_right_relief.y + relief_radius), (upper_right_relief.x, upper_right_relief.y - relief_radius), "PARAM_SLOT")
    if anchor is not None:
        _add_top_opening_connector_lines(
            modelspace,
            center_left_vertical_tangent,
            center_right_vertical_tangent,
            anchor,
        )
    return SlotDimensionGeometry(
        left_x=lower_left_relief.x,
        right_x=lower_right_relief.x,
        base_y=base_y,
        top_y=top_y,
        opening_left_x=opening_left_x,
        opening_right_x=opening_right_x,
        center_x=x_center,
        outer_left=(-tile_section.guide_spec.outer_width / 2.0 if anchor is None else anchor.left),
        outer_right=(tile_section.guide_spec.outer_width / 2.0 if anchor is None else anchor.right),
        outer_bottom=(0.0 if anchor is None else anchor.bottom),
        outer_top=(tile_section.guide_spec.outer_height if anchor is None else anchor.top),
        upper_radius_center=upper_center.as_tuple(),
        lower_radius_center=lower_center.as_tuple(),
        relief_radius=relief_radius,
        center_transition_radius=center_transition_radius,
        center_transition_left_center=center_left_relief.as_tuple(),
        center_transition_right_center=center_right_relief.as_tuple(),
    )


def _add_top_opening_connector_lines(modelspace, opening_left: Point, opening_right: Point, anchor: TemplateAnchor) -> None:
    _add_line(modelspace, opening_left.as_tuple(), (opening_left.x, anchor.top), "PARAM_SLOT")
    _add_line(modelspace, opening_right.as_tuple(), (opening_right.x, anchor.top), "PARAM_SLOT")


def _rebuild_section_top_boundary(
    modelspace: Any,
    geometry: SlotDimensionGeometry,
) -> None:
    """Join the fixed guide top to the final cavity mouth without stale gaps."""
    for entity in list(modelspace.query("LINE")):
        if entity.dxf.layer != "FIXED_TEMPLATE":
            continue
        start = entity.dxf.start
        end = entity.dxf.end
        if not (
            _close(start.y, geometry.outer_top)
            and _close(end.y, geometry.outer_top)
        ):
            continue
        min_x = min(float(start.x), float(end.x))
        max_x = max(float(start.x), float(end.x))
        if (
            min_x >= geometry.outer_left - 0.001
            and max_x <= geometry.outer_right + 0.001
        ):
            modelspace.delete_entity(entity)

    _add_line(
        modelspace,
        (geometry.outer_left, geometry.outer_top),
        (geometry.opening_left_x, geometry.outer_top),
        "FIXED_TEMPLATE",
    )
    _add_line(
        modelspace,
        (geometry.opening_right_x, geometry.outer_top),
        (geometry.outer_right, geometry.outer_top),
        "FIXED_TEMPLATE",
    )


def _add_reference_profile_entities(modelspace, tile_section: TileSection, anchor: TemplateAnchor | None = None) -> None:
    guide = tile_section.guide_spec
    dx = guide.slot_center_offset if anchor is None else anchor.slot_center_x
    dy = guide.slot_base_height if anchor is None else anchor.slot_base_y
    _add_profile_entities(modelspace, tile_section.forming_profile, "REFERENCE_PROFILE", dx=dx, dy=dy)


def _add_debug_entities(modelspace, geometry: SlotDimensionGeometry) -> None:
    lower_center = geometry.lower_radius_center
    upper_center = geometry.upper_radius_center
    slot_points = (
        (geometry.left_x, geometry.base_y),
        (geometry.right_x, geometry.base_y),
        (geometry.left_x, geometry.top_y),
        (geometry.right_x, geometry.top_y),
        (geometry.opening_left_x, geometry.outer_top),
        (geometry.opening_right_x, geometry.outer_top),
        lower_center,
        upper_center,
    )
    for point in slot_points:
        modelspace.add_point(point, dxfattribs={"layer": DEBUG_POINTS_LAYER})

    _add_line(modelspace, lower_center, upper_center, DEBUG_CONTROL_LAYER)
    _add_line(modelspace, lower_center, (geometry.left_x, geometry.base_y), DEBUG_CONTROL_LAYER)
    _add_line(modelspace, lower_center, (geometry.right_x, geometry.base_y), DEBUG_CONTROL_LAYER)
    _add_line(modelspace, upper_center, (geometry.left_x, geometry.top_y), DEBUG_CONTROL_LAYER)
    _add_line(modelspace, upper_center, (geometry.right_x, geometry.top_y), DEBUG_CONTROL_LAYER)


def _add_param_dimension_entities(
    modelspace,
    tile_section: TileSection,
    anchor: TemplateAnchor | None = None,
    slot_geometry: SlotDimensionGeometry | None = None,
    include_fallback: bool = True,
    include_native: bool = True,
) -> None:
    if slot_geometry is None:
        raise ValueError("slot_geometry is required for dimension generation.")
    add_slot_width_dimension(
        modelspace,
        tile_section,
        slot_geometry,
        include_fallback=include_fallback,
        include_native=include_native,
    )
    add_guide_thickness_dimension(
        modelspace,
        tile_section,
        slot_geometry,
        include_fallback=include_fallback,
        include_native=include_native,
    )
    add_r_form_dimension(
        modelspace,
        tile_section,
        slot_geometry,
        include_fallback=include_fallback,
        include_native=include_native,
    )
    add_relief_dimension(
        modelspace,
        tile_section,
        slot_geometry,
        include_fallback=include_fallback,
        include_native=include_native,
    )
    add_center_offset_dimension(
        modelspace,
        tile_section,
        slot_geometry,
        include_fallback=include_fallback,
        include_native=include_native,
    )
    add_fixed_template_dimensions(
        modelspace,
        tile_section,
        slot_geometry,
        include_fallback=include_fallback,
        include_native=include_native,
    )


def _add_profile_entities(modelspace, profile: SectionProfile, layer: str, dx: float = 0.0, dy: float = 0.0) -> None:
    for segment in profile.segments:
        if isinstance(segment, LineSegment):
            modelspace.add_line(
                _offset_tuple(segment.start, dx, dy),
                _offset_tuple(segment.end, dx, dy),
                dxfattribs={"layer": layer},
            )
        elif isinstance(segment, ArcSegment):
            start_angle, end_angle = _dxf_arc_angles(segment)
            modelspace.add_arc(
                center=_offset_tuple(segment.center, dx, dy),
                radius=segment.radius,
                start_angle=start_angle,
                end_angle=end_angle,
                dxfattribs={"layer": layer},
            )


def _add_arc_by_points(
    modelspace,
    center: Point,
    radius: float,
    start: Point,
    end: Point,
    clockwise: bool,
    layer: str,
) -> None:
    arc = ArcSegment("slot_arc", start=start, end=end, center=center, radius=radius, clockwise=clockwise)
    start_angle, end_angle = _dxf_arc_angles(arc)
    modelspace.add_arc(
        center=center.as_tuple(),
        radius=radius,
        start_angle=start_angle,
        end_angle=end_angle,
        dxfattribs={"layer": layer},
    )


def _add_relief_arc(modelspace, center: Point, radius: float, start: Point, end: Point) -> None:
    modelspace.add_arc(
        center=center.as_tuple(),
        radius=radius,
        start_angle=_angle_deg(center, start),
        end_angle=_angle_deg(center, end),
        dxfattribs={"layer": "PARAM_SLOT"},
    )


def _add_outer_relief_arc(
    modelspace,
    center: Point,
    radius: float,
    inner_start: Point,
    inner_end: Point,
) -> None:
    """Emit the complement of the inner relief arc.

    DXF ARC entities are always counter-clockwise.  Reversing the two tangent
    points preserves their geometry while selecting the outer segment, which
    prevents a 4-R relief from cutting back through the product cavity.
    """
    _add_relief_arc(modelspace, center, radius, inner_end, inner_start)


def _add_line(modelspace, start: tuple[float, float], end: tuple[float, float], layer: str) -> None:
    modelspace.add_line(start, end, dxfattribs={"layer": layer})


def _add_text(modelspace, text: str, insert: tuple[float, float], layer: str, height: float = 1.0) -> None:
    modelspace.add_text(text, dxfattribs={"layer": layer, "height": height, "insert": insert})


def _offset_tuple(point: Point, dx: float, dy: float) -> tuple[float, float]:
    return (point.x + dx, point.y + dy)


def _dxf_arc_angles(segment: ArcSegment) -> tuple[float, float]:
    if segment.clockwise:
        return (segment.end_angle_deg, segment.start_angle_deg)
    return (segment.start_angle_deg, segment.end_angle_deg)


def _point_on_upper_slot_arc(center: Point, radius: float, x: float) -> Point:
    return Point(x, center.y + sqrt(radius**2 - (x - center.x) ** 2))


def _bread_center_opening_relief_center(
    upper_center: Point,
    radius: float,
    opening_x: float,
    relief_radius: float,
    side: str,
) -> Point:
    center_x = (
        opening_x - relief_radius
        if side == "left"
        else opening_x + relief_radius
    )
    dx = center_x - upper_center.x
    center_y = upper_center.y + sqrt((radius + relief_radius) ** 2 - dx**2)
    return Point(center_x, center_y)


def _external_circle_tangent_point(
    main_center: Point,
    main_radius: float,
    relief_center: Point,
    relief_radius: float,
) -> Point:
    scale = main_radius / (main_radius + relief_radius)
    return Point(
        main_center.x + (relief_center.x - main_center.x) * scale,
        main_center.y + (relief_center.y - main_center.y) * scale,
    )


def _select_circle_intersection(
    center_a: Point,
    radius_a: float,
    center_b: Point,
    radius_b: float,
    side: str,
) -> Point:
    dx = center_b.x - center_a.x
    dy = center_b.y - center_a.y
    distance = sqrt(dx * dx + dy * dy)
    if distance == 0:
        raise ValueError("Cannot intersect concentric circles.")
    a = (radius_a**2 - radius_b**2 + distance**2) / (2 * distance)
    h_sq = radius_a**2 - a**2
    if h_sq < -1e-9:
        raise ValueError("Slot relief circle does not intersect R_form arc.")
    h = sqrt(max(0.0, h_sq))
    x2 = center_a.x + a * dx / distance
    y2 = center_a.y + a * dy / distance
    rx = -dy / distance
    ry = dx / distance
    candidates = (
        Point(x2 + h * rx, y2 + h * ry),
        Point(x2 - h * rx, y2 - h * ry),
    )
    if side == "left":
        return min(candidates, key=lambda point: point.x)
    if side == "right":
        return max(candidates, key=lambda point: point.x)
    raise ValueError(f"Unknown intersection side: {side}")


def _angle_deg(center: Point, point: Point) -> float:
    return degrees(atan2(point.y - center.y, point.x - center.x)) % 360.0


def _ensure_layer(doc, name: str, color: int, linetype: str = "Continuous") -> None:
    _ensure_linetype(doc, linetype)
    if name not in doc.layers:
        doc.layers.add(name, color=color, linetype=linetype)
    else:
        layer = doc.layers.get(name)
        layer.dxf.color = color
        layer.dxf.linetype = linetype


def _ensure_linetype(doc, name: str) -> None:
    if name in doc.linetypes:
        return
    if name == "CENTER":
        doc.linetypes.add("CENTER", pattern=[2.0, 1.25, -0.25, 0.25, -0.25], description="Center ____ _ ____ _")
    elif name == "DASHED":
        doc.linetypes.add("DASHED", pattern=[0.75, 0.5, -0.25], description="Dashed __ __ __")


def _simplify_release_layers(doc) -> None:
    keep_layers = {"0", "FIXED_TEMPLATE", "PARAM_SLOT", SECTION_CENTER_LAYER, DIMENSION_LAYER}
    keep_layers.update({
        SIDE_TEMPLATE_LAYER,
        SIDE_DERIVED_LAYER,
        SIDE_DERIVED_RELEASE_LAYER,
        SIDE_CAVITY_LAYER,
        SIDE_DIMENSION_LAYER,
        SIDE_CENTER_LAYER,
    })
    _ensure_layer(doc, "FIXED_TEMPLATE", color=7)
    _ensure_layer(doc, "PARAM_SLOT", color=PARAM_SLOT_COLOR)
    _ensure_layer(doc, SECTION_CENTER_LAYER, color=1, linetype="CENTER")
    _ensure_layer(doc, DIMENSION_LAYER, color=3)

    for entity in _iter_all_entities(doc):
        layer = entity.dxf.layer
        if layer in {
            "PARAM_SLOT",
            SECTION_CENTER_LAYER,
            DIMENSION_LAYER,
            SIDE_TEMPLATE_LAYER,
            SIDE_DERIVED_LAYER,
            SIDE_DERIVED_RELEASE_LAYER,
            SIDE_CAVITY_LAYER,
            SIDE_DIMENSION_LAYER,
            SIDE_CENTER_LAYER,
        }:
            continue
        entity.dxf.layer = "FIXED_TEMPLATE"

    used_layers = {entity.dxf.layer for entity in _iter_all_entities(doc)}
    for layer in list(doc.layers):
        name = layer.dxf.name
        if name == SIDE_CAVITY_LAYER and name not in used_layers:
            doc.layers.remove(name)
            continue
        if name in keep_layers:
            continue
        if name not in used_layers:
            doc.layers.remove(name)


def _iter_all_entities(doc):
    for layout in doc.layouts:
        yield from layout
    for block in doc.blocks:
        yield from block


def _hide_layer(doc, name: str) -> None:
    if name in doc.layers:
        doc.layers.get(name).off()


def _ensure_dimension_text_style(doc) -> None:
    if DIMENSION_TEXT_STYLE not in doc.styles:
        doc.styles.add(DIMENSION_TEXT_STYLE, font="Arial.ttf")


def _assert_native_dimensions_present(modelspace, tile_section: TileSection) -> None:
    dimension_texts = [
        entity.dxf.text
        for entity in modelspace
        if entity.dxf.layer == DIMENSION_LAYER and entity.dxftype() == "DIMENSION"
    ]
    guide = tile_section.guide_spec
    r_text = f"R{tile_section.forming_spec.R_form:.2f}"
    expected = [
        guide.slot_width_dimension_text,
        f"{guide.guide_thickness:.2f}",
        f"{guide.center_opening:.2f}",
        f"{guide.outer_width:.2f}",
        f"{guide.outer_height:.2f}",
        f"{guide.slot_base_height:.2f}",
    ]
    expected_r_dimension_count = _expected_r_form_dimension_count(tile_section)
    if expected_r_dimension_count:
        expected.append(r_text)
    missing = [text for text in expected if text not in dimension_texts]
    actual_r_dimension_count = dimension_texts.count(r_text)
    if actual_r_dimension_count < expected_r_dimension_count:
        missing.append(
            f"R_form dimensions {actual_r_dimension_count}/{expected_r_dimension_count} ({r_text})"
        )
    if missing:
        raise RuntimeError("Native DIMENSION generation failed; missing: " + ", ".join(missing))


def _expected_r_form_dimension_count(tile_section: TileSection) -> int:
    """Return the R_form callout count required by the rebuilt cavity topology."""
    return sum(
        1
        for segment in tile_section.forming_profile.segments
        if isinstance(segment, ArcSegment)
        and abs(segment.radius - tile_section.forming_spec.R_form) <= 1e-9
    )


def _validate_output_mode(output_mode: str) -> None:
    if output_mode not in {"debug", "release"}:
        raise ValueError("output_mode must be 'debug' or 'release'.")


def _close(left: float, right: float, tolerance: float = 0.001) -> bool:
    return abs(left - right) <= tolerance

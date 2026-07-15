from __future__ import annotations

from math import atan2, cos, hypot, radians, sin
from pathlib import Path

from .block_geometry import BlockGuideSection
from .cavity_projection import (
    derive_cavity_projection_profile,
    horizontal_arc_gap,
)
from .dimension_writer import (
    DIMENSION_TEXT_STYLE,
    TEMPLATE_DIMENSION_STYLE,
    TEMPLATE_DIMENSION_TEXT_HEIGHT,
    TEXT_HEIGHT,
    add_linear_dimension_with_text,
    copy_template_dimension_without_associations,
)
from .dimension_roles import (
    LOWER_WHEEL_KEY_PROCESS_HEIGHT,
    LOWER_WHEEL_NOTCH_OPENING,
    UPPER_WHEEL_KEY_PROCESS_HEIGHT,
    UPPER_WHEEL_LOCAL_CUT_IN_DEPTH,
)
from .geometry import TileSection
from .side_view import SideViewGeometry, build_side_view_geometry
from .side_view_config import SideViewLayoutConfig
from .side_view_config import DEFAULT_SIDE_VIEW_TEMPLATE, SideViewTemplateConfig
from .global_rules import DEFAULT_WHEEL_RADIUS


SIDE_TEMPLATE_LAYER = "SIDE_TEMPLATE"
SIDE_DERIVED_LAYER = "SIDE_DERIVED"
SIDE_DERIVED_RELEASE_LAYER = "SIDE_DERIVED_RELEASE"
SIDE_CAVITY_LAYER = "SIDE_CAVITY"
SIDE_DIMENSION_LAYER = "SIDE_DIMENSION"
SIDE_DEBUG_LAYER = "SIDE_DEBUG"
SIDE_CENTER_LAYER = "SIDE_CENTER"


def add_side_view_to_dxf(
    doc,
    modelspace,
    tile_section: TileSection | BlockGuideSection,
    output_mode: str,
    template_path: str | Path = DEFAULT_SIDE_VIEW_TEMPLATE,
    layout: SideViewLayoutConfig | None = None,
    side_style: str = "standard",
    wheel_positions: tuple[str, ...] = ("上", "下"),
    wheel_radius: float = DEFAULT_WHEEL_RADIUS,
) -> SideViewGeometry:
    geometry = build_side_view_geometry(
        tile_section,
        template=SideViewTemplateConfig(wheel_radius=wheel_radius),
        layout=layout,
    )
    _ensure_side_layers(doc, output_mode)
    _copy_side_template_entities(
        doc,
        modelspace,
        Path(template_path),
        geometry,
        side_style=side_style,
    )
    if side_style != "triple_single_down_up":
        _add_side_derived_entities(modelspace, geometry, output_mode)
    _finalize_side_cavity_lines(
        modelspace,
        geometry,
        tile_section,
        side_style,
        wheel_positions,
    )
    if side_style == "bed_618":
        _add_bed_618_projected_height_dimension(modelspace, geometry)
    elif side_style == "triple_single_down_up":
        if (
            isinstance(tile_section, BlockGuideSection)
            and tile_section.process_type == "block_to_bread_rectangular"
        ):
            _add_triple_single_down_up_block_bread_process_dimensions(
                modelspace,
                geometry,
            )
        else:
            _add_triple_single_down_up_process_dimensions(modelspace, geometry)
    elif (
        tile_section.process_type == "block_to_tile"
        and not _has_dimension_measurement(
            modelspace,
            geometry.derived.side_projected_slot_height,
        )
    ):
        _add_block_projected_height_dimensions(
            modelspace,
            geometry,
            output_mode,
        )
    return geometry


def _has_dimension_measurement(modelspace, expected: float) -> bool:
    for dimension in modelspace.query("DIMENSION"):
        try:
            if abs(float(dimension.get_measurement()) - expected) <= 0.01:
                return True
        except Exception:
            continue
    return False


def _add_triple_single_down_up_process_dimensions(modelspace, geometry: SideViewGeometry) -> None:
    layout = geometry.layout
    derived = geometry.derived
    base_y = layout.lower_y + derived.slot_base_height
    slot_top_y = base_y + derived.guide_thickness
    lower_opening = derived.lower_cavity_notch_opening
    lower_left = layout.center_a_x - lower_opening / 2.0
    lower_right = layout.center_a_x + lower_opening / 2.0
    lower_dim_y = base_y - 4.7
    add_linear_dimension_with_text(
        modelspace,
        (lower_left, base_y),
        (lower_right, base_y),
        (lower_left, lower_dim_y),
        (lower_right, lower_dim_y),
        _format_dimension_value(lower_opening, digits=1),
        (layout.center_a_x, lower_dim_y - 0.8),
        layer=SIDE_DIMENSION_LAYER,
        include_fallback=False,
        include_native=True,
        role=LOWER_WHEEL_NOTCH_OPENING,
        dimstyle=TEMPLATE_DIMENSION_STYLE,
        dimension_text_height=TEMPLATE_DIMENSION_TEXT_HEIGHT,
    )
    lower_top_y = layout.lower_y + derived.wheel_notch_depth
    lower_dim_x = layout.center_a_x + 49.5
    add_linear_dimension_with_text(
        modelspace,
        (layout.center_a_x, layout.lower_y),
        (layout.center_a_x, lower_top_y),
        (lower_dim_x, layout.lower_y),
        (lower_dim_x, lower_top_y),
        _format_dimension_value(derived.wheel_notch_depth),
        (lower_dim_x + 1.4, (layout.lower_y + lower_top_y) / 2.0),
        angle=90.0,
        text_rotation=90.0,
        layer=SIDE_DIMENSION_LAYER,
        include_fallback=False,
        include_native=True,
        role=LOWER_WHEEL_KEY_PROCESS_HEIGHT,
        dimstyle=TEMPLATE_DIMENSION_STYLE,
        dimension_text_height=TEMPLATE_DIMENSION_TEXT_HEIGHT,
    )

    upper_low_y = layout.upper_y - derived.side_clearance_height
    upper_height_dim_x = layout.center_b_x - 52.7
    add_linear_dimension_with_text(
        modelspace,
        (layout.center_b_x, upper_low_y),
        (layout.center_b_x, layout.upper_y),
        (upper_height_dim_x, upper_low_y),
        (upper_height_dim_x, layout.upper_y),
        _format_dimension_value(derived.side_clearance_height),
        (upper_height_dim_x - 1.4, (upper_low_y + layout.upper_y) / 2.0),
        angle=90.0,
        text_rotation=90.0,
        layer=SIDE_DIMENSION_LAYER,
        include_fallback=False,
        include_native=True,
        role=UPPER_WHEEL_KEY_PROCESS_HEIGHT,
        dimstyle=TEMPLATE_DIMENSION_STYLE,
        dimension_text_height=TEMPLATE_DIMENSION_TEXT_HEIGHT,
    )

    upper_cut_in = derived.wheel_cut_allowance
    upper_dim_x = layout.center_b_x + 11.5
    add_linear_dimension_with_text(
        modelspace,
        (layout.center_b_x, upper_low_y),
        (layout.center_b_x, slot_top_y),
        (upper_dim_x, upper_low_y),
        (upper_dim_x, slot_top_y),
        _format_dimension_value(upper_cut_in),
        (upper_dim_x + 1.4, (upper_low_y + slot_top_y) / 2.0),
        angle=90.0,
        text_rotation=90.0,
        layer=SIDE_DIMENSION_LAYER,
        include_fallback=False,
        include_native=True,
        role=UPPER_WHEEL_LOCAL_CUT_IN_DEPTH,
        dimstyle=TEMPLATE_DIMENSION_STYLE,
        dimension_text_height=TEMPLATE_DIMENSION_TEXT_HEIGHT,
    )


def _add_triple_single_down_up_block_bread_process_dimensions(
    modelspace,
    geometry: SideViewGeometry,
) -> None:
    """Add only the process dimensions present on the block-to-bread production drawing."""
    layout = geometry.layout
    derived = geometry.derived
    lower_top_y = layout.lower_y + derived.wheel_notch_depth
    lower_dim_x = layout.center_a_x + 49.5
    add_linear_dimension_with_text(
        modelspace,
        (layout.center_a_x, layout.lower_y),
        (layout.center_a_x, lower_top_y),
        (lower_dim_x, layout.lower_y),
        (lower_dim_x, lower_top_y),
        _format_dimension_value(derived.wheel_notch_depth),
        (lower_dim_x + 1.4, (layout.lower_y + lower_top_y) / 2.0),
        angle=90.0,
        text_rotation=90.0,
        layer=SIDE_DIMENSION_LAYER,
        include_fallback=False,
        include_native=True,
        role=LOWER_WHEEL_KEY_PROCESS_HEIGHT,
        dimstyle=TEMPLATE_DIMENSION_STYLE,
        dimension_text_height=TEMPLATE_DIMENSION_TEXT_HEIGHT,
    )

    upper_low_y = layout.upper_y - derived.side_clearance_height
    upper_dim_x = layout.center_b_x - 52.7
    add_linear_dimension_with_text(
        modelspace,
        (layout.center_b_x, upper_low_y),
        (layout.center_b_x, layout.upper_y),
        (upper_dim_x, upper_low_y),
        (upper_dim_x, layout.upper_y),
        _format_dimension_value(derived.side_clearance_height),
        (upper_dim_x - 1.4, (upper_low_y + layout.upper_y) / 2.0),
        angle=90.0,
        text_rotation=90.0,
        layer=SIDE_DIMENSION_LAYER,
        include_fallback=False,
        include_native=True,
        role=UPPER_WHEEL_KEY_PROCESS_HEIGHT,
        dimstyle=TEMPLATE_DIMENSION_STYLE,
        dimension_text_height=TEMPLATE_DIMENSION_TEXT_HEIGHT,
    )


def _format_dimension_value(value: float, digits: int = 2) -> str:
    del digits
    return f"{value:.2f}"


def _ensure_side_layers(doc, output_mode: str) -> None:
    _ensure_layer(doc, SIDE_TEMPLATE_LAYER, color=7)
    _ensure_layer(doc, SIDE_DERIVED_LAYER, color=3, linetype="DASHED")
    _ensure_layer(doc, SIDE_CAVITY_LAYER, color=3, linetype="DASHED")
    _ensure_layer(doc, SIDE_DIMENSION_LAYER, color=3)
    _ensure_layer(doc, SIDE_CENTER_LAYER, color=1, linetype="CENTER")
    if output_mode == "debug":
        _ensure_layer(doc, SIDE_DEBUG_LAYER, color=6)
    if DIMENSION_TEXT_STYLE not in doc.styles:
        doc.styles.add(DIMENSION_TEXT_STYLE, font="Arial.ttf")


def _copy_side_template_entities(
    doc,
    modelspace,
    template_path: Path,
    geometry: SideViewGeometry,
    side_style: str,
) -> None:
    if not template_path.exists():
        raise FileNotFoundError(f"Side view template not found: {template_path}")
    import ezdxf

    source_doc = ezdxf.readfile(template_path)
    for entity in source_doc.modelspace():
        if not _is_copyable_side_template_entity(entity):
            continue
        if entity.dxftype() == "DIMENSION":
            copied = copy_template_dimension_without_associations(entity)
        else:
            try:
                copied = entity.copy()
            except Exception:
                copied = None
        if copied is None:
            continue
        copied.dxf.layer = _side_layer_for_template_entity(entity)
        if side_style == "triple_single_down_up":
            _update_triple_single_down_up_side_geometry(copied, geometry)
        elif side_style == "double_head_up_down":
            _update_double_head_up_down_side_geometry(copied, geometry)
        elif side_style == "bed_618":
            _update_bed_618_side_geometry(copied, geometry)
        else:
            _update_side_template_geometry(copied, geometry)
        if copied.dxf.layer in {SIDE_DERIVED_LAYER, SIDE_CAVITY_LAYER}:
            # Template hidden lines often carry explicit colors.  Once mapped
            # to a controlled cavity layer they must inherit the configured
            # green/dashed appearance instead of retaining stale cyan values.
            copied.dxf.color = 256
            copied.dxf.linetype = "BYLAYER"
        derived_dimension_updated = False
        if copied.dxftype() == "DIMENSION":
            derived_dimension_updated = _update_derived_dimension(copied, geometry, side_style=side_style)
        try:
            modelspace.add_entity(copied)
        except Exception:
            continue
        if derived_dimension_updated:
            try:
                copied.render()
            except Exception:
                pass
            _sync_dimension_block_text(copied)
    _bind_r80_dimensions_to_formal_arcs(modelspace, geometry)


def _bind_r80_dimensions_to_formal_arcs(
    modelspace,
    geometry: SideViewGeometry,
) -> None:
    radius = geometry.template.wheel_radius
    arcs = [
        entity
        for entity in modelspace.query("ARC")
        if entity.dxf.layer == SIDE_TEMPLATE_LAYER
        and abs(float(entity.dxf.radius) - radius) <= 0.001
    ]
    if not arcs:
        return
    for dimension in modelspace.query("DIMENSION"):
        if dimension.dxf.layer != SIDE_DIMENSION_LAYER or not (
            dimension.dxf.hasattr("defpoint")
            and dimension.dxf.hasattr("defpoint4")
        ):
            continue
        try:
            measurement = float(dimension.get_measurement())
        except Exception:
            continue
        if not _is_source_or_target_wheel_radius(measurement, radius):
            continue
        old_center = dimension.dxf.defpoint
        old_target = dimension.dxf.defpoint4
        arc = min(
            arcs,
            key=lambda item: hypot(
                float(item.dxf.center.x) - float(old_center.x),
                float(item.dxf.center.y) - float(old_center.y),
            ),
        )
        start_angle = float(arc.dxf.start_angle) % 360.0
        sweep = (float(arc.dxf.end_angle) - start_angle) % 360.0
        angle = radians((start_angle + sweep / 2.0) % 360.0)
        center = arc.dxf.center
        dimension.dxf.defpoint = (
            float(center.x),
            float(center.y),
            float(old_center.z),
        )
        dimension.dxf.defpoint4 = (
            float(center.x) + radius * cos(angle),
            float(center.y) + radius * sin(angle),
            float(old_target.z),
        )
        _set_actual_measurement(dimension, radius)
        dimension.dxf.text = f"R{radius:.2f}"
        try:
            dimension.render()
        except Exception:
            pass
        _sync_dimension_block_text(dimension)


def _is_copyable_side_template_entity(entity) -> bool:
    return entity.dxftype() in {
        "LINE",
        "ARC",
        "CIRCLE",
        "LWPOLYLINE",
        "HATCH",
        "INSERT",
        "DIMENSION",
        "TEXT",
        "MTEXT",
    }


def _side_layer_for_template_entity(entity) -> str:
    if _is_center_entity(entity):
        return SIDE_CENTER_LAYER
    if entity.dxftype() == "DIMENSION":
        return SIDE_DIMENSION_LAYER
    return SIDE_TEMPLATE_LAYER


def _is_center_entity(entity) -> bool:
    return "中心" in entity.dxf.layer or entity.dxf.layer == "3中心线层"


def _update_side_template_geometry(entity, geometry: SideViewGeometry) -> None:
    if entity.dxftype() == "ARC":
        _update_upper_left_r80_arc(entity, geometry)
    elif entity.dxftype() == "LINE":
        _update_upper_left_r80_top_connectors(entity, geometry)
        _update_block_reference_lines(entity, geometry)


def _update_triple_single_down_up_side_geometry(entity, geometry: SideViewGeometry) -> None:
    if entity.dxftype() == "ARC":
        _update_down_up_r80_arc(entity, geometry)
    elif entity.dxftype() == "LINE":
        _update_down_up_surface_connectors(entity, geometry)
        _update_down_up_slot_projection_lines(entity, geometry)


def _update_double_head_up_down_side_geometry(entity, geometry: SideViewGeometry) -> None:
    if entity.dxftype() == "ARC":
        _update_double_head_up_down_r80_arc(entity, geometry)
    elif entity.dxftype() == "LINE":
        _update_upper_left_r80_top_connectors(entity, geometry)
        _update_double_head_up_down_lower_connectors(entity, geometry)
        _update_double_head_up_down_slot_projection_lines(entity, geometry)


def _update_bed_618_side_geometry(entity, geometry: SideViewGeometry) -> None:
    if entity.dxftype() == "ARC":
        _update_bed_618_r80_arc(entity, geometry)
    elif entity.dxftype() == "LINE":
        _update_bed_618_r80_top_connectors(entity, geometry)
        _update_bed_618_slot_projection_lines(entity, geometry)


def _update_bed_618_r80_arc(entity, geometry: SideViewGeometry) -> None:
    layout = geometry.layout
    if not _is_source_or_target_wheel_radius(
        float(entity.dxf.radius),
        geometry.template.wheel_radius,
    ):
        return
    if abs(entity.dxf.center.x - layout.center_a_x) > 0.01:
        return
    if entity.dxf.center.y < layout.upper_y:
        return
    center_y = _upper_left_r80_center_y(geometry)
    half_chord = _upper_left_r80_top_half_chord(geometry)
    entity.dxf.radius = geometry.template.wheel_radius
    entity.dxf.center = (layout.center_a_x, center_y, entity.dxf.center.z)
    entity.dxf.start_angle = _angle_deg(-half_chord, layout.upper_y - center_y)
    entity.dxf.end_angle = _angle_deg(half_chord, layout.upper_y - center_y)


def _update_bed_618_r80_top_connectors(entity, geometry: SideViewGeometry) -> None:
    if abs(entity.dxf.start.y - entity.dxf.end.y) > 1e-6:
        return
    layout = geometry.layout
    if abs(entity.dxf.start.y - layout.upper_y) > 1e-3:
        return
    radius = geometry.template.wheel_radius
    old_center_y = _old_bed_618_r80_center_y(geometry)
    old_half = _upper_left_r80_top_half_chord_from_center_y(radius, layout.upper_y, old_center_y)
    new_half = _upper_left_r80_top_half_chord(geometry)
    replacements = (
        (layout.center_a_x - old_half, layout.center_a_x - new_half),
        (layout.center_a_x + old_half, layout.center_a_x + new_half),
    )
    for attr in ("start", "end"):
        point = getattr(entity.dxf, attr)
        for old_x, new_x in replacements:
            if abs(point.x - old_x) <= 0.05:
                entity.dxf.set(attr, (new_x, point.y, point.z))
                break


def _update_bed_618_slot_projection_lines(entity, geometry: SideViewGeometry) -> None:
    if abs(entity.dxf.start.y - entity.dxf.end.y) > 1e-6:
        return
    layout = geometry.layout
    base_y = layout.lower_y + geometry.derived.slot_base_height
    top_y = base_y + geometry.derived.guide_thickness
    old_base_y = layout.lower_y + geometry.derived.slot_base_height
    old_top_y = layout.lower_y + geometry.derived.slot_base_height + 1.2
    y = entity.dxf.start.y
    if abs(y - old_base_y) <= 0.3:
        entity.dxf.start = (entity.dxf.start.x, base_y, entity.dxf.start.z)
        entity.dxf.end = (entity.dxf.end.x, base_y, entity.dxf.end.z)
        entity.dxf.layer = SIDE_DERIVED_LAYER
    elif abs(y - old_top_y) <= 0.3:
        entity.dxf.start = (entity.dxf.start.x, top_y, entity.dxf.start.z)
        entity.dxf.end = (entity.dxf.end.x, top_y, entity.dxf.end.z)
        entity.dxf.layer = SIDE_DERIVED_LAYER


def _finalize_side_cavity_lines(
    modelspace,
    geometry: SideViewGeometry,
    tile_section: TileSection | BlockGuideSection,
    side_style: str,
    wheel_positions: tuple[str, ...],
) -> None:
    projection = derive_cavity_projection_profile(
        tile_section,
        geometry.derived.guide_thickness,
    )
    base_y = geometry.layout.lower_y + geometry.derived.slot_base_height
    if side_style == "bed_618":
        opening = geometry.derived.upper_cavity_notch_opening
        _rebuild_cavity_projection_lines(
            modelspace,
            geometry,
            tuple(
                (
                    base_y + offset,
                    geometry.layout.center_a_x,
                    opening,
                )
                for offset in projection.offsets
            ),
        )
        return

    projected_offset = (
        geometry.derived.side_projected_slot_height
        - geometry.derived.slot_base_height
    )
    if side_style == "double_head_up_down" and not any(
        abs(offset - projected_offset) <= 0.001
        for offset in projection.offsets
    ):
        _remove_side_dimension_by_measurement(
            modelspace,
            geometry.derived.side_projected_slot_height,
        )
    centers = (
        geometry.layout.center_a_x,
        geometry.layout.center_b_x,
    )
    _rebuild_cavity_projection_lines(
        modelspace,
        geometry,
        tuple(
            (
                base_y + offset,
                tuple(
                    center_x
                    for center_x, position in zip(
                        centers,
                        wheel_positions,
                    )
                    if position
                    == ("下" if role.startswith("lower_") else "上")
                ),
                geometry.derived.lower_cavity_notch_opening
                if role.startswith("lower_")
                else geometry.derived.upper_cavity_notch_opening,
            )
            for offset, role in zip(
                projection.offsets,
                projection.surface_roles,
            )
        ),
    )


def _remove_side_dimension_by_measurement(
    modelspace,
    measurement: float,
) -> None:
    for dimension in list(modelspace.query("DIMENSION")):
        if dimension.dxf.layer != SIDE_DIMENSION_LAYER:
            continue
        try:
            current = float(dimension.get_measurement())
        except Exception:
            continue
        if abs(current - measurement) <= 0.01:
            modelspace.delete_entity(dimension)


def _rebuild_cavity_projection_lines(
    modelspace,
    geometry: SideViewGeometry,
    boundaries: tuple[tuple[float, tuple[float, ...] | float, float], ...],
) -> None:
    layout = geometry.layout
    y_values = tuple(boundary[0] for boundary in boundaries)
    lower_y = min(y_values) - 0.6
    upper_y = max(y_values) + 0.6
    for entity in list(modelspace.query("LINE")):
        if entity.dxf.layer not in {SIDE_DERIVED_LAYER, SIDE_CAVITY_LAYER}:
            continue
        if abs(float(entity.dxf.start.y) - float(entity.dxf.end.y)) > 0.001:
            continue
        y = float(entity.dxf.start.y)
        if not lower_y <= y <= upper_y:
            continue
        if max(float(entity.dxf.start.x), float(entity.dxf.end.x)) < layout.left_x - 0.01:
            continue
        if min(float(entity.dxf.start.x), float(entity.dxf.end.x)) > layout.right_x + 0.01:
            continue
        modelspace.delete_entity(entity)

    attributes = {
        "layer": SIDE_DERIVED_LAYER,
        "color": 256,
        "linetype": "BYLAYER",
    }
    wheel_arcs = [
        entity
        for entity in modelspace.query("ARC")
        if entity.dxf.layer == SIDE_TEMPLATE_LAYER
        and abs(
            float(entity.dxf.radius) - geometry.template.wheel_radius
        )
        <= 0.001
        and layout.left_x - 0.01
        <= float(entity.dxf.center.x)
        <= layout.right_x + 0.01
    ]
    for y, _centers, _opening in boundaries:
        gaps = [
            gap
            for arc in wheel_arcs
            if (gap := horizontal_arc_gap(arc, y)) is not None
        ]
        for start_x, end_x in _subtract_side_gaps(
            layout.left_x,
            layout.right_x,
            gaps,
        ):
            modelspace.add_line(
                (start_x, y),
                (end_x, y),
                dxfattribs=attributes,
            )


def _subtract_side_gaps(
    start_x: float,
    end_x: float,
    gaps: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    segments = [(start_x, end_x)]
    for gap_start, gap_end in sorted(gaps):
        next_segments = []
        for segment_start, segment_end in segments:
            if gap_end <= segment_start or gap_start >= segment_end:
                next_segments.append((segment_start, segment_end))
                continue
            if segment_start < gap_start:
                next_segments.append((segment_start, gap_start))
            if gap_end < segment_end:
                next_segments.append((gap_end, segment_end))
        segments = next_segments
    return segments


def _update_down_up_r80_arc(entity, geometry: SideViewGeometry) -> None:
    layout = geometry.layout
    radius = geometry.template.wheel_radius
    if not _is_source_or_target_wheel_radius(float(entity.dxf.radius), radius):
        return
    depth = geometry.derived.wheel_notch_depth
    if depth <= 0.0 or depth >= radius:
        return
    half_chord = _wheel_notch_half_chord(radius, depth)
    if abs(entity.dxf.center.x - layout.center_a_x) <= 0.01 and entity.dxf.center.y < layout.lower_y:
        center_y = layout.lower_y + depth - radius
        entity.dxf.radius = radius
        entity.dxf.center = (layout.center_a_x, center_y, entity.dxf.center.z)
        entity.dxf.start_angle = _angle_deg(half_chord, radius - depth)
        entity.dxf.end_angle = _angle_deg(-half_chord, radius - depth)
    elif abs(entity.dxf.center.x - layout.center_b_x) <= 0.01 and entity.dxf.center.y > layout.upper_y:
        center_y = layout.upper_y - geometry.derived.side_clearance_height + radius
        entity.dxf.radius = radius
        half_chord = _upper_left_r80_top_half_chord_from_center_y(radius, layout.upper_y, center_y)
        entity.dxf.center = (layout.center_b_x, center_y, entity.dxf.center.z)
        entity.dxf.start_angle = _angle_deg(-half_chord, layout.upper_y - center_y)
        entity.dxf.end_angle = _angle_deg(half_chord, layout.upper_y - center_y)


def _update_double_head_up_down_r80_arc(entity, geometry: SideViewGeometry) -> None:
    layout = geometry.layout
    radius = geometry.template.wheel_radius
    if not _is_source_or_target_wheel_radius(float(entity.dxf.radius), radius):
        return
    if abs(entity.dxf.center.x - layout.center_a_x) <= 0.01 and entity.dxf.center.y > layout.upper_y:
        center_y = _upper_left_r80_center_y(geometry)
        entity.dxf.radius = radius
        half_chord = _upper_left_r80_top_half_chord(geometry)
        entity.dxf.center = (layout.center_a_x, center_y, entity.dxf.center.z)
        entity.dxf.start_angle = _angle_deg(-half_chord, layout.upper_y - center_y)
        entity.dxf.end_angle = _angle_deg(half_chord, layout.upper_y - center_y)
        return
    if abs(entity.dxf.center.x - layout.center_b_x) <= 0.01 and entity.dxf.center.y < layout.lower_y:
        depth = geometry.derived.wheel_notch_depth
        if depth <= 0.0 or depth >= radius:
            return
        center_y = layout.lower_y + depth - radius
        entity.dxf.radius = radius
        half_chord = _wheel_notch_half_chord(radius, depth)
        entity.dxf.center = (layout.center_b_x, center_y, entity.dxf.center.z)
        entity.dxf.start_angle = _angle_deg(half_chord, radius - depth)
        entity.dxf.end_angle = _angle_deg(-half_chord, radius - depth)


def _update_down_up_surface_connectors(entity, geometry: SideViewGeometry) -> None:
    if abs(entity.dxf.start.y - entity.dxf.end.y) > 1e-6:
        return
    layout = geometry.layout
    radius = geometry.template.wheel_radius
    depth = geometry.derived.wheel_notch_depth
    if depth <= 0.0 or depth >= radius:
        return
    y = entity.dxf.start.y
    if abs(y - layout.lower_y) <= 1e-3:
        center_y = layout.lower_y + depth - radius
        half_chord = _wheel_notch_half_chord_at_y(radius, center_y, layout.lower_y)
        _replace_endpoint_near(entity, layout.center_a_x, layout.center_a_x - half_chord, layout.center_a_x + half_chord)
    elif abs(y - layout.upper_y) <= 1e-3:
        center_y = layout.upper_y - geometry.derived.side_clearance_height + radius
        half_chord = _wheel_notch_half_chord_at_y(radius, center_y, layout.upper_y)
        _connect_horizontal_segments_to_gap(
            entity,
            layout.center_b_x,
            layout.center_b_x - half_chord,
            layout.center_b_x + half_chord,
        )


def _update_double_head_up_down_lower_connectors(entity, geometry: SideViewGeometry) -> None:
    if abs(entity.dxf.start.y - entity.dxf.end.y) > 1e-6:
        return
    layout = geometry.layout
    radius = geometry.template.wheel_radius
    depth = geometry.derived.wheel_notch_depth
    if depth <= 0.0 or depth >= radius:
        return
    y = entity.dxf.start.y
    if abs(y - layout.lower_y) <= 1e-3:
        center_y = layout.lower_y + depth - radius
        half_chord = _wheel_notch_half_chord_at_y(radius, center_y, layout.lower_y)
        _replace_endpoint_near(entity, layout.center_b_x, layout.center_b_x - half_chord, layout.center_b_x + half_chord)


def _update_down_up_slot_projection_lines(entity, geometry: SideViewGeometry) -> None:
    if abs(entity.dxf.start.y - entity.dxf.end.y) > 1e-6:
        return
    layout = geometry.layout
    base_y = layout.lower_y + geometry.derived.slot_base_height
    top_y = base_y + geometry.derived.guide_thickness
    old_top_y = layout.lower_y + 17.45
    y = entity.dxf.start.y
    if abs(y - old_top_y) <= 0.6:
        entity.dxf.start = (entity.dxf.start.x, top_y, entity.dxf.start.z)
        entity.dxf.end = (entity.dxf.end.x, top_y, entity.dxf.end.z)
        entity.dxf.layer = SIDE_DERIVED_LAYER
        upper_center_y = layout.upper_y - geometry.derived.side_clearance_height + geometry.template.wheel_radius
        upper_half_chord = _wheel_notch_half_chord_at_y(
            geometry.template.wheel_radius,
            upper_center_y,
            top_y,
        )
        _connect_horizontal_segments_to_gap(
            entity,
            layout.center_b_x,
            layout.center_b_x - upper_half_chord,
            layout.center_b_x + upper_half_chord,
        )
    elif abs(y - base_y) <= 0.2:
        entity.dxf.start = (entity.dxf.start.x, base_y, entity.dxf.start.z)
        entity.dxf.end = (entity.dxf.end.x, base_y, entity.dxf.end.z)
        entity.dxf.layer = SIDE_DERIVED_LAYER
        _split_down_up_lower_cavity_notch_line(entity, geometry)


def _update_double_head_up_down_slot_projection_lines(entity, geometry: SideViewGeometry) -> None:
    if abs(entity.dxf.start.y - entity.dxf.end.y) > 1e-6:
        return
    if abs(
        geometry.derived.side_projected_slot_height
        - geometry.derived.slot_base_height
    ) > 0.001:
        _update_double_head_up_down_tile_slot_projection_lines(entity, geometry)
        return
    if str(entity.dxf.linetype).upper() != "DASHED":
        return
    layout = geometry.layout
    base_y = layout.lower_y + geometry.derived.slot_base_height
    top_y = base_y + geometry.derived.guide_thickness
    y = float(entity.dxf.start.y)
    if not base_y - 0.1 <= y <= top_y + 0.6:
        return
    entity.dxf.layer = SIDE_DERIVED_LAYER
    entity.dxf.color = 256
    entity.dxf.linetype = "BYLAYER"


def _update_double_head_up_down_tile_slot_projection_lines(
    entity,
    geometry: SideViewGeometry,
) -> None:
    layout = geometry.layout
    base_y = layout.lower_y + geometry.derived.slot_base_height
    projected_y = layout.lower_y + geometry.derived.side_projected_slot_height
    top_y = base_y + geometry.derived.guide_thickness
    y = entity.dxf.start.y
    if abs(y - base_y) <= 0.05:
        entity.dxf.start = (entity.dxf.start.x, base_y, entity.dxf.start.z)
        entity.dxf.end = (entity.dxf.end.x, base_y, entity.dxf.end.z)
        entity.dxf.layer = SIDE_DERIVED_LAYER
        _split_lower_cavity_notch_line(entity, geometry, layout.center_b_x)
    elif abs(y - projected_y) <= 0.6:
        entity.dxf.start = (entity.dxf.start.x, projected_y, entity.dxf.start.z)
        entity.dxf.end = (entity.dxf.end.x, projected_y, entity.dxf.end.z)
        entity.dxf.layer = SIDE_DERIVED_LAYER
    elif abs(y - top_y) <= 0.6:
        entity.dxf.start = (entity.dxf.start.x, top_y, entity.dxf.start.z)
        entity.dxf.end = (entity.dxf.end.x, top_y, entity.dxf.end.z)
        entity.dxf.layer = SIDE_DERIVED_LAYER


def _replace_endpoint_near(entity, center_x: float, new_left: float, new_right: float) -> None:
    for attr in ("start", "end"):
        point = getattr(entity.dxf, attr)
        distance = point.x - center_x
        if 8.0 <= abs(distance) <= 70.0:
            target_x = new_left if distance < 0 else new_right
            entity.dxf.set(attr, (target_x, point.y, point.z))


def _connect_horizontal_segments_to_gap(entity, center_x: float, left_gap: float, right_gap: float) -> None:
    start = entity.dxf.start
    end = entity.dxf.end
    min_x = min(start.x, end.x)
    max_x = max(start.x, end.x)
    if max_x < center_x and center_x - max_x <= 70.0:
        if start.x >= end.x:
            entity.dxf.start = (left_gap, start.y, start.z)
        else:
            entity.dxf.end = (left_gap, end.y, end.z)
    elif min_x > center_x and min_x - center_x <= 70.0:
        if start.x <= end.x:
            entity.dxf.start = (right_gap, start.y, start.z)
        else:
            entity.dxf.end = (right_gap, end.y, end.z)


def _wheel_notch_half_chord(radius: float, depth: float) -> float:
    return max(0.0, radius * radius - (radius - depth) ** 2) ** 0.5


def _wheel_notch_half_chord_at_y(radius: float, center_y: float, y: float) -> float:
    return max(0.0, radius * radius - (y - center_y) ** 2) ** 0.5


def _split_down_up_lower_cavity_notch_line(entity, geometry: SideViewGeometry) -> None:
    _split_lower_cavity_notch_line(entity, geometry, geometry.layout.center_a_x)


def _split_lower_cavity_notch_line(entity, geometry: SideViewGeometry, center_x: float) -> None:
    opening = geometry.derived.lower_cavity_notch_opening
    if opening <= 0.0:
        return
    left_gap = center_x - opening / 2.0
    right_gap = center_x + opening / 2.0
    start = entity.dxf.start
    end = entity.dxf.end
    min_x = min(start.x, end.x)
    max_x = max(start.x, end.x)
    if max_x < center_x:
        if start.x <= end.x:
            entity.dxf.end = (left_gap, end.y, end.z)
        else:
            entity.dxf.start = (left_gap, start.y, start.z)
    elif min_x > center_x:
        if start.x <= end.x:
            entity.dxf.start = (right_gap, start.y, start.z)
        else:
            entity.dxf.end = (right_gap, end.y, end.z)


def _update_upper_left_r80_arc(entity, geometry: SideViewGeometry) -> None:
    layout = geometry.layout
    if not _is_source_or_target_wheel_radius(
        float(entity.dxf.radius),
        geometry.template.wheel_radius,
    ):
        return
    upper_wheel_centers = (layout.center_a_x, layout.center_b_x)
    if all(abs(entity.dxf.center.x - center_x) > 0.01 for center_x in upper_wheel_centers):
        return
    if entity.dxf.center.y < layout.upper_y:
        return
    center_x = entity.dxf.center.x
    radius = geometry.template.wheel_radius
    entity.dxf.radius = radius
    center_y = _upper_left_r80_center_y(geometry)
    half_chord = _upper_left_r80_top_half_chord(geometry)
    entity.dxf.center = (center_x, center_y, entity.dxf.center.z)
    entity.dxf.start_angle = _angle_deg(-half_chord, layout.upper_y - center_y)
    entity.dxf.end_angle = _angle_deg(half_chord, layout.upper_y - center_y)


def _is_source_or_target_wheel_radius(value: float, target: float) -> bool:
    return (
        abs(value - DEFAULT_WHEEL_RADIUS) <= 0.001
        or abs(value - target) <= 0.001
    )


def _update_upper_left_r80_top_connectors(entity, geometry: SideViewGeometry) -> None:
    layout = geometry.layout
    if abs(entity.dxf.start.y - entity.dxf.end.y) > 1e-6:
        return
    if abs(entity.dxf.start.y - layout.upper_y) > 1e-3:
        return
    if abs(entity.dxf.end.x - entity.dxf.start.x) < 10.0:
        return
    mid_x = (layout.center_a_x + layout.center_b_x) / 2.0
    half_chord = _upper_left_r80_top_half_chord(geometry)
    replacements = (
        (layout.left_x, layout.center_a_x, layout.center_a_x - half_chord),
        (layout.center_a_x, mid_x, layout.center_a_x + half_chord),
        (mid_x, layout.center_b_x, layout.center_b_x - half_chord),
        (layout.center_b_x, layout.right_x, layout.center_b_x + half_chord),
    )
    for attr in ("start", "end"):
        point = getattr(entity.dxf, attr)
        for lower, upper, target_x in replacements:
            if lower + 1.0 < point.x < upper - 1.0:
                entity.dxf.set(attr, (target_x, point.y, point.z))
                break

    # Backward compatibility for old clean templates whose top-line endpoints
    # still use the original 3.85 clearance geometry.
    for center_x in (layout.center_a_x, layout.center_b_x):
        old_center_y = _old_r80_center_y_for_layout(geometry)
        old_left = center_x - _upper_left_r80_top_half_chord_from_center_y(
            geometry.template.wheel_radius,
            layout.upper_y,
            old_center_y,
        )
        old_right = center_x + _upper_left_r80_top_half_chord_from_center_y(
            geometry.template.wheel_radius,
            layout.upper_y,
            old_center_y,
        )
        new_left = center_x - _upper_left_r80_top_half_chord(geometry)
        new_right = center_x + _upper_left_r80_top_half_chord(geometry)
        start = entity.dxf.start
        end = entity.dxf.end
        if abs(start.x - old_left) < 0.02:
            entity.dxf.start = (new_left, start.y, start.z)
        if abs(end.x - old_left) < 0.02:
            entity.dxf.end = (new_left, end.y, end.z)
        if abs(start.x - old_right) < 0.02:
            entity.dxf.start = (new_right, start.y, start.z)
        if abs(end.x - old_right) < 0.02:
            entity.dxf.end = (new_right, end.y, end.z)


def _update_block_reference_lines(entity, geometry: SideViewGeometry) -> None:
    if abs(entity.dxf.start.y - entity.dxf.end.y) > 1e-6:
        return
    layout = geometry.layout
    old_projected_y = layout.lower_y + 21.85
    old_working_y = layout.lower_y + 24.0
    standard_projected_y = layout.lower_y + 18.0
    standard_working_y = layout.upper_y - 7.8
    projected_y = layout.lower_y + geometry.derived.side_projected_slot_height
    working_y = layout.upper_y - geometry.derived.side_clearance_height
    start = entity.dxf.start
    end = entity.dxf.end
    if abs(start.y - old_projected_y) < 0.6 or abs(start.y - standard_projected_y) < 0.6:
        entity.dxf.start = (start.x, projected_y, start.z)
        entity.dxf.end = (end.x, projected_y, end.z)
        entity.dxf.layer = SIDE_DERIVED_LAYER
    elif abs(start.y - old_working_y) < 0.6 or abs(start.y - standard_working_y) < 0.6:
        entity.dxf.start = (start.x, working_y, start.z)
        entity.dxf.end = (end.x, working_y, end.z)
        entity.dxf.layer = SIDE_DERIVED_LAYER


def _update_derived_dimension(entity, geometry: SideViewGeometry, side_style: str = "standard") -> bool:
    try:
        measurement = float(entity.get_measurement())
    except Exception:
        return False
    derived = geometry.derived
    if (
        side_style == "double_head_up_down"
        and 10.0 <= measurement <= 16.0
        and entity.dxf.hasattr("defpoint2")
        and entity.dxf.hasattr("defpoint3")
    ):
        return _bind_double_head_up_down_wheel_dimension(entity, geometry)
    if (
        side_style == "triple_single_down_up"
        and abs(measurement - geometry.template.wheel_radius) < 0.05
        and entity.dxf.hasattr("defpoint")
        and entity.dxf.hasattr("defpoint4")
    ):
        _bind_down_up_r80_dimension_to_arc(entity, geometry)
        _set_actual_measurement(entity, geometry.template.wheel_radius)
        return True
    if abs(measurement - derived.side_projected_slot_height) < 0.05:
        _set_vertical_dimension_measurement(entity, derived.side_projected_slot_height)
        _set_actual_measurement(entity, derived.side_projected_slot_height)
        entity.dxf.text = f"{derived.side_projected_slot_height:.2f}"
        return True
    elif side_style == "bed_618" and 2.0 <= measurement <= 8.0:
        _set_bed_618_side_clearance_dimension_points(entity, geometry)
        _set_actual_measurement(entity, derived.side_clearance_height)
        entity.dxf.text = f"{derived.side_clearance_height:.2f}"
        return True
    elif derived.side_projected_slot_height >= 18.0 and 2.0 <= measurement <= 8.0:
        _set_block_side_clearance_dimension_points(entity, geometry)
        _set_actual_measurement(entity, derived.side_clearance_height)
        entity.dxf.text = f"{derived.side_clearance_height:.2f}"
        return True
    elif 12.8 <= measurement <= 13.8:
        _set_side_clearance_dimension_points(entity, geometry)
        _set_actual_measurement(entity, derived.side_clearance_height)
        entity.dxf.text = f"{derived.side_clearance_height:.2f}"
        return True
    return False


def _bind_double_head_up_down_wheel_dimension(
    entity,
    geometry: SideViewGeometry,
) -> bool:
    layout = geometry.layout
    p2 = entity.dxf.defpoint2
    p3 = entity.dxf.defpoint3
    lower_distance = min(
        abs(float(p2.x) - layout.center_b_x),
        abs(float(p3.x) - layout.center_b_x),
    )
    upper_distance = min(
        abs(float(p2.x) - layout.center_a_x),
        abs(float(p3.x) - layout.center_a_x),
    )
    if lower_distance <= upper_distance:
        center_x = layout.center_b_x
        crown_y = layout.lower_y + geometry.derived.wheel_notch_depth
        datum_y = layout.lower_y
    else:
        center_x = layout.center_a_x
        crown_y = layout.upper_y - geometry.derived.side_clearance_height
        datum_y = layout.upper_y
    measured = abs(datum_y - crown_y)
    entity.dxf.defpoint2 = (center_x, crown_y, p2.z)
    entity.dxf.defpoint3 = (center_x, datum_y, p3.z)
    if entity.dxf.hasattr("defpoint"):
        dimline = entity.dxf.defpoint
        entity.dxf.defpoint = (dimline.x, datum_y, dimline.z)
    _set_actual_measurement(entity, measured)
    entity.dxf.text = f"{measured:.2f}"
    return True


def _bind_down_up_r80_dimension_to_arc(entity, geometry: SideViewGeometry) -> None:
    layout = geometry.layout
    radius = geometry.template.wheel_radius
    old_center = entity.dxf.defpoint
    old_target = entity.dxf.defpoint4
    if abs(old_center.x - layout.center_a_x) <= abs(old_center.x - layout.center_b_x):
        center = (
            layout.center_a_x,
            layout.lower_y + geometry.derived.wheel_notch_depth - radius,
            old_center.z,
        )
    else:
        center = (
            layout.center_b_x,
            layout.upper_y - geometry.derived.side_clearance_height + radius,
            old_center.z,
        )
    dx = float(old_target.x) - float(old_center.x)
    dy = float(old_target.y) - float(old_center.y)
    length = max((dx * dx + dy * dy) ** 0.5, 1e-9)
    target = (
        center[0] + radius * dx / length,
        center[1] + radius * dy / length,
        old_target.z,
    )
    entity.dxf.defpoint = center
    entity.dxf.defpoint4 = target


def _set_vertical_dimension_measurement(entity, target: float) -> None:
    if not (entity.dxf.hasattr("defpoint2") and entity.dxf.hasattr("defpoint3")):
        return
    first = entity.dxf.defpoint2
    second = entity.dxf.defpoint3
    if abs(first.y - second.y) < 1e-9:
        return
    if first.y >= second.y:
        entity.dxf.defpoint3 = (second.x, first.y - target, second.z)
    else:
        entity.dxf.defpoint3 = (second.x, first.y + target, second.z)


def _set_actual_measurement(entity, target: float) -> None:
    entity.dxf.actual_measurement = target


def _set_side_clearance_dimension_points(entity, geometry: SideViewGeometry) -> None:
    layout = geometry.layout
    target_y = layout.upper_y - geometry.derived.side_clearance_height
    left_x = layout.center_a_x - _upper_left_r80_top_half_chord(geometry)
    if entity.dxf.hasattr("defpoint"):
        point = entity.dxf.defpoint
        entity.dxf.defpoint = (point.x, target_y, point.z)
    if entity.dxf.hasattr("defpoint2"):
        point = entity.dxf.defpoint2
        entity.dxf.defpoint2 = (left_x, layout.upper_y, point.z)
    if entity.dxf.hasattr("defpoint3"):
        point = entity.dxf.defpoint3
        entity.dxf.defpoint3 = (layout.center_a_x, target_y, point.z)


def _set_block_side_clearance_dimension_points(entity, geometry: SideViewGeometry) -> None:
    layout = geometry.layout
    target_y = layout.upper_y - geometry.derived.side_clearance_height
    half_chord = _upper_left_r80_top_half_chord(geometry)
    if entity.dxf.hasattr("defpoint") and entity.dxf.defpoint.x < layout.center_a_x:
        center_x = layout.center_a_x
        top_x = center_x - half_chord
    elif entity.dxf.hasattr("defpoint") and entity.dxf.defpoint.x > layout.center_b_x:
        center_x = layout.center_b_x
        top_x = center_x + half_chord
    else:
        center_x = entity.dxf.defpoint2.x if entity.dxf.hasattr("defpoint2") else layout.center_a_x
        top_x = center_x
    if entity.dxf.hasattr("defpoint"):
        point = entity.dxf.defpoint
        entity.dxf.defpoint = (point.x, target_y, point.z)
    if entity.dxf.hasattr("defpoint2"):
        point = entity.dxf.defpoint2
        entity.dxf.defpoint2 = (top_x, layout.upper_y, point.z)
    if entity.dxf.hasattr("defpoint3"):
        point = entity.dxf.defpoint3
        entity.dxf.defpoint3 = (center_x, target_y, point.z)


def _set_bed_618_side_clearance_dimension_points(entity, geometry: SideViewGeometry) -> None:
    layout = geometry.layout
    target_y = layout.upper_y - geometry.derived.side_clearance_height
    dim_x = layout.right_x + 32.0
    if entity.dxf.hasattr("defpoint"):
        point = entity.dxf.defpoint
        entity.dxf.defpoint = (dim_x, target_y, point.z)
    if entity.dxf.hasattr("defpoint2"):
        point = entity.dxf.defpoint2
        entity.dxf.defpoint2 = (layout.right_x, layout.upper_y, point.z)
    if entity.dxf.hasattr("defpoint3"):
        point = entity.dxf.defpoint3
        entity.dxf.defpoint3 = (layout.right_x, target_y, point.z)
    if entity.dxf.hasattr("text_midpoint"):
        midpoint_y = (layout.upper_y + target_y) / 2.0
        entity.dxf.text_midpoint = (dim_x + 5.0, midpoint_y, 0.0)


def _upper_left_r80_center_y(geometry: SideViewGeometry) -> float:
    return geometry.layout.upper_y - geometry.derived.side_clearance_height + geometry.template.wheel_radius


def _old_r80_center_y_for_layout(geometry: SideViewGeometry) -> float:
    layout = geometry.layout
    if layout.upper_y < 0:
        return -168.89191569522243
    return 129.5272535341328


def _old_bed_618_r80_center_y(geometry: SideViewGeometry) -> float:
    return geometry.layout.upper_y - 5.1 + geometry.template.wheel_radius


def _upper_left_r80_top_half_chord(geometry: SideViewGeometry) -> float:
    return _upper_left_r80_top_half_chord_from_center_y(
        geometry.template.wheel_radius,
        geometry.layout.upper_y,
        _upper_left_r80_center_y(geometry),
    )


def _upper_left_r80_top_half_chord_from_center_y(radius: float, top_y: float, center_y: float) -> float:
    return max(0.0, radius * radius - (top_y - center_y) ** 2) ** 0.5


def _angle_deg(dx: float, dy: float) -> float:
    from math import atan2, degrees

    return degrees(atan2(dy, dx)) % 360.0


def _sync_dimension_block_text(entity) -> None:
    if not entity.dxf.text or not entity.dxf.hasattr("geometry"):
        return
    doc = getattr(entity, "doc", None)
    if doc is None or entity.dxf.geometry not in doc.blocks:
        return
    for block_entity in doc.blocks[entity.dxf.geometry]:
        if block_entity.dxftype() == "TEXT":
            block_entity.dxf.text = entity.dxf.text
        elif block_entity.dxftype() == "MTEXT":
            block_entity.text = entity.dxf.text


def _add_side_derived_entities(modelspace, geometry: SideViewGeometry, output_mode: str) -> None:
    layout = geometry.layout
    derived = geometry.derived
    x0 = layout.left_x
    projected_y = layout.lower_y + derived.side_projected_slot_height
    clearance_y = layout.upper_y - derived.side_clearance_height
    if output_mode == "debug":
        _add_text(
            modelspace,
            (
                f"{derived.slot_base_height:.1f}+{derived.side_cut_in_allowance:.2f}="
                f"{derived.side_projected_slot_height:.2f}"
            ),
            (x0 + 8.0, projected_y + 3.0),
            SIDE_DEBUG_LAYER,
        )
        _add_text(
            modelspace,
            (
                f"{derived.guide_outer_height:.1f}-{derived.slot_base_height:.1f}-"
                f"{derived.guide_thickness:.2f}+{derived.wheel_cut_allowance:.2f}="
                f"{derived.side_clearance_height:.2f}"
            ),
            (x0 + 8.0, clearance_y - 5.0),
            SIDE_DEBUG_LAYER,
        )


def _add_text(modelspace, text: str, insert: tuple[float, float], layer: str) -> None:
    modelspace.add_text(
        text,
        dxfattribs={
            "layer": layer,
            "height": TEXT_HEIGHT,
            "insert": insert,
            "style": _dimension_text_style(modelspace),
        },
    )


def _add_block_projected_height_dimensions(modelspace, geometry: SideViewGeometry, output_mode: str) -> None:
    layout = geometry.layout
    projected_y = layout.lower_y + geometry.derived.side_projected_slot_height
    for center_x, side in ((layout.center_a_x, -1.0), (layout.center_b_x, 1.0)):
        dim_x = center_x + side * 28.0
        add_linear_dimension_with_text(
            modelspace,
            (center_x, layout.lower_y),
            (center_x, projected_y),
            (dim_x, layout.lower_y),
            (dim_x, projected_y),
            f"{geometry.derived.side_projected_slot_height:.2f}",
            (dim_x + side * 1.5, (layout.lower_y + projected_y) / 2.0),
            angle=90.0,
            text_rotation=90.0,
            layer=SIDE_DIMENSION_LAYER,
            include_fallback=False,
            include_native=True,
        )


def _add_bed_618_projected_height_dimension(modelspace, geometry: SideViewGeometry) -> None:
    layout = geometry.layout
    projected_y = layout.lower_y + geometry.derived.side_projected_slot_height
    dim_x = layout.right_x + 18.0
    add_linear_dimension_with_text(
        modelspace,
        (layout.right_x, layout.lower_y),
        (layout.right_x, projected_y),
        (dim_x, layout.lower_y),
        (dim_x, projected_y),
        f"{geometry.derived.side_projected_slot_height:.2f}",
        (dim_x + 1.5, (layout.lower_y + projected_y) / 2.0),
        angle=90.0,
        text_rotation=90.0,
        layer=SIDE_DIMENSION_LAYER,
        include_fallback=False,
        include_native=True,
    )


def _dimension_text_style(modelspace) -> str:
    doc = getattr(modelspace, "doc", None)
    if doc is not None and DIMENSION_TEXT_STYLE in doc.styles:
        return DIMENSION_TEXT_STYLE
    return "Standard"


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

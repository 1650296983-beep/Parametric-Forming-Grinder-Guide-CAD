from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, radians, sin
from pathlib import Path

from .geometry import TileSection
from .dimension_roles import set_dimension_role
from .global_rules import CENTER_TRANSITION_RADIUS, format_dimension


SECTION_DIMENSION_TEMPLATE_PATH = Path("section_dimension_template.dxf")
DIMENSION_LAYER = "DIMENSION"
DIMENSION_TEXT_FALLBACK_LAYER = "DIMENSION_TEXT_FALLBACK"
TEXT_NOTE_LAYER = "TEXT_NOTE"
DIMENSION_TEXT_STYLE = "CAD_DIM_TEXT"
TEXT_HEIGHT = 1.4
TEMPLATE_DIMENSION_STYLE = "TH_GBDIM"
TEMPLATE_DIMENSION_TEXT_HEIGHT = 3.5
DIMENSION_OVERRIDES = {
    "dimtxt": TEXT_HEIGHT,
    "dimclrt": 3,
    "dimclrd": 3,
    "dimclre": 3,
    "dimasz": 1.0,
    "dimexe": 0.8,
    "dimexo": 0.3,
}


@dataclass(frozen=True)
class SlotDimensionGeometry:
    left_x: float
    right_x: float
    base_y: float
    top_y: float
    opening_left_x: float
    opening_right_x: float
    center_x: float
    outer_left: float
    outer_right: float
    outer_bottom: float
    outer_top: float
    upper_radius_center: tuple[float, float]
    lower_radius_center: tuple[float, float]
    relief_radius: float
    center_transition_radius: float = CENTER_TRANSITION_RADIUS
    center_transition_left_center: tuple[float, float] | None = None
    center_transition_right_center: tuple[float, float] | None = None

    @property
    def slot_width(self) -> float:
        return self.right_x - self.left_x

    @property
    def guide_thickness(self) -> float:
        return self.top_y - self.base_y

    @property
    def center_opening(self) -> float:
        return self.opening_right_x - self.opening_left_x

    @property
    def outer_width(self) -> float:
        return self.outer_right - self.outer_left

    @property
    def outer_height(self) -> float:
        return self.outer_top - self.outer_bottom

    @property
    def slot_base_height(self) -> float:
        return self.base_y - self.outer_bottom


def add_text_label(
    modelspace,
    text: str,
    insert: tuple[float, float],
    layer: str = DIMENSION_TEXT_FALLBACK_LAYER,
    height: float = TEXT_HEIGHT,
    rotation: float = 0.0,
) -> None:
    """Add one visible fallback text label for CAD viewers."""
    if layer not in (DIMENSION_LAYER, DIMENSION_TEXT_FALLBACK_LAYER, TEXT_NOTE_LAYER):
        raise ValueError("dimension text must be placed on DIMENSION, DIMENSION_TEXT_FALLBACK, or TEXT_NOTE layer.")

    dxfattribs = {
        "layer": layer,
        "height": height,
        "insert": insert,
        "style": _dimension_text_style(modelspace),
        "rotation": rotation,
    }
    text_entity = modelspace.add_text(text, dxfattribs=dxfattribs)
    text_entity.set_placement(insert)


def add_linear_dimension_with_text(
    modelspace,
    start: tuple[float, float],
    end: tuple[float, float],
    dimension_line_start: tuple[float, float],
    dimension_line_end: tuple[float, float],
    text: str,
    text_insert: tuple[float, float],
    angle: float = 0.0,
    text_rotation: float | None = None,
    layer: str = DIMENSION_LAYER,
    fallback_layer: str = DIMENSION_TEXT_FALLBACK_LAYER,
    include_fallback: bool = True,
    include_native: bool = True,
    role: str | None = None,
    dimstyle: str = "Standard",
    dimension_text_height: float = TEXT_HEIGHT,
):
    native_dimension = None
    if include_native:
        native_dimension = _add_native_linear_dimension(
            modelspace,
            start,
            end,
            dimension_line_start,
            text,
            text_insert,
            angle=angle,
            text_rotation=text_rotation,
            layer=layer,
            dimstyle=dimstyle,
            dimension_text_height=dimension_text_height,
        )
        if role is not None:
            set_dimension_role(native_dimension, role)
    if include_fallback:
        _add_line(modelspace, start, dimension_line_start, layer=fallback_layer)
        _add_line(modelspace, end, dimension_line_end, layer=fallback_layer)
        _add_line(modelspace, dimension_line_start, dimension_line_end, layer=fallback_layer)
        add_text_label(
            modelspace,
            text,
            text_insert,
            layer=fallback_layer,
            rotation=0.0 if text_rotation is None else text_rotation,
        )
    if not include_native and not include_fallback:
        add_text_label(
            modelspace,
            text,
            text_insert,
            layer=layer,
            rotation=0.0 if text_rotation is None else text_rotation,
        )
    return native_dimension


def add_radius_dimension_with_text(
    modelspace,
    leader_start: tuple[float, float],
    leader_end: tuple[float, float],
    text: str,
    text_insert: tuple[float, float],
    center: tuple[float, float] | None = None,
    radius: float | None = None,
    angle: float | None = None,
    layer: str = DIMENSION_LAYER,
    fallback_layer: str = DIMENSION_TEXT_FALLBACK_LAYER,
    include_fallback: bool = True,
    include_native: bool = True,
) -> None:
    if include_native and center is not None and radius is not None and angle is not None:
        _add_native_radius_dimension(
            modelspace,
            center=center,
            radius=radius,
            angle=angle,
            text=text,
            location=text_insert,
            layer=layer,
        )
    if include_fallback:
        _add_line(modelspace, leader_start, leader_end, layer=fallback_layer)
        add_text_label(modelspace, text, text_insert, layer=fallback_layer)
    if not include_native and not include_fallback:
        add_text_label(modelspace, text, text_insert, layer=layer)


def add_slot_width_dimension(
    modelspace,
    tile_section: TileSection,
    geometry: SlotDimensionGeometry,
    include_fallback: bool = True,
    include_native: bool = True,
) -> None:
    y = geometry.base_y - 19.2
    add_linear_dimension_with_text(
        modelspace,
        (geometry.left_x, geometry.base_y),
        (geometry.right_x, geometry.base_y),
        (geometry.left_x, y + 1.0),
        (geometry.right_x, y + 1.0),
        tile_section.guide_spec.slot_width_dimension_text,
        (geometry.center_x - 2.4, y - 1.0),
        angle=0.0,
        include_fallback=include_fallback,
        include_native=include_native,
    )


def add_guide_thickness_dimension(
    modelspace,
    tile_section: TileSection,
    geometry: SlotDimensionGeometry,
    include_fallback: bool = True,
    include_native: bool = True,
) -> None:
    x = geometry.right_x + 27.45
    add_linear_dimension_with_text(
        modelspace,
        (geometry.right_x, geometry.base_y),
        (geometry.right_x, geometry.top_y),
        (x - 1.0, geometry.base_y),
        (x - 1.0, geometry.top_y),
        f"{geometry.guide_thickness:.2f}",
        (x + 0.4, (geometry.base_y + geometry.top_y) / 2.0 - 0.35),
        angle=90.0,
        text_rotation=90.0,
        include_fallback=include_fallback,
        include_native=include_native,
    )


def add_r_form_dimension(
    modelspace,
    tile_section: TileSection,
    geometry: SlotDimensionGeometry,
    include_fallback: bool = True,
    include_native: bool = True,
) -> None:
    r_text = f"R{tile_section.forming_spec.R_form:.2f}"
    add_radius_dimension_with_text(
        modelspace,
        (geometry.center_x + 1.4, geometry.top_y + 0.2),
        (geometry.right_x + 4.0, geometry.top_y + 4.0),
        r_text,
        (geometry.right_x + 4.3, geometry.top_y + 4.0),
        center=geometry.upper_radius_center,
        radius=tile_section.forming_spec.R_form,
        angle=32.0,
        include_fallback=include_fallback,
        include_native=include_native,
    )
    add_radius_dimension_with_text(
        modelspace,
        (geometry.center_x - 1.4, geometry.base_y + 0.2),
        (geometry.left_x - 7.0, geometry.base_y - 3.0),
        r_text,
        (geometry.left_x - 11.5, geometry.base_y - 3.7),
        center=geometry.lower_radius_center,
        radius=tile_section.forming_spec.R_form,
        angle=145.0,
        include_fallback=include_fallback,
        include_native=include_native,
    )


def add_radius_dimension(modelspace, tile_section: TileSection, geometry: SlotDimensionGeometry) -> None:
    add_r_form_dimension(modelspace, tile_section, geometry)


def add_relief_note(modelspace, tile_section: TileSection, geometry: SlotDimensionGeometry) -> None:
    _add_line(
        modelspace,
        (geometry.left_x, geometry.top_y - geometry.relief_radius),
        (geometry.left_x - 8.4, geometry.top_y + 1.2),
        layer=TEXT_NOTE_LAYER,
    )
    add_text_label(
        modelspace,
        tile_section.guide_spec.relief.relief_label,
        (geometry.left_x - 10.8, geometry.top_y + 1.0),
        layer=TEXT_NOTE_LAYER,
    )


def add_relief_dimension(
    modelspace,
    tile_section: TileSection,
    geometry: SlotDimensionGeometry,
    include_fallback: bool = True,
    include_native: bool = True,
) -> None:
    add_radius_dimension_with_text(
        modelspace,
        (geometry.left_x, geometry.top_y - geometry.relief_radius),
        (geometry.left_x - 8.4, geometry.top_y + 1.2),
        tile_section.guide_spec.relief.relief_label,
        (geometry.left_x - 10.8, geometry.top_y + 1.0),
        center=(geometry.left_x, geometry.top_y),
        radius=geometry.relief_radius,
        angle=180.0,
        include_fallback=include_fallback,
        include_native=include_native,
    )


def add_center_offset_dimension(
    modelspace,
    tile_section: TileSection,
    geometry: SlotDimensionGeometry,
    include_fallback: bool = True,
    include_native: bool = True,
) -> None:
    y = geometry.outer_top + 4.9
    add_linear_dimension_with_text(
        modelspace,
        (geometry.opening_left_x, geometry.outer_top),
        (geometry.opening_right_x, geometry.outer_top),
        (geometry.opening_left_x, y - 0.6),
        (geometry.opening_right_x, y - 0.6),
        format_dimension(geometry.center_opening),
        (geometry.center_x - 0.55, y + 0.4),
        angle=0.0,
        include_fallback=include_fallback,
        include_native=include_native,
    )


def add_fixed_template_dimensions(
    modelspace,
    tile_section: TileSection,
    geometry: SlotDimensionGeometry,
    include_fallback: bool = True,
    include_native: bool = True,
) -> None:
    _add_outer_width_dimension(modelspace, geometry, include_fallback=include_fallback, include_native=include_native)
    _add_outer_height_dimension(modelspace, geometry, include_fallback=include_fallback, include_native=include_native)
    _add_slot_base_dimension(modelspace, geometry, include_fallback=include_fallback, include_native=include_native)


def add_section_template_dimensions(
    doc,
    modelspace,
    tile_section: TileSection,
    geometry: SlotDimensionGeometry,
    template_path: str | Path = SECTION_DIMENSION_TEMPLATE_PATH,
    skip_secondary_relief_dimension: bool = False,
) -> None:
    try:
        import ezdxf
    except ImportError as exc:
        raise RuntimeError("ezdxf is required for native section dimensions.") from exc

    path = Path(template_path)
    if not path.exists():
        raise FileNotFoundError(f"Section dimension template not found: {path}")
    source_doc = ezdxf.readfile(path)
    source_dimensions = list(source_doc.modelspace().query("DIMENSION"))
    flat_arc_radius_dimensions = [
        entity
        for entity in source_dimensions
        if entity.dimtype == 4
        and (_safe_measurement(entity) or 0.0) > 5.0
    ]
    selected_flat_arc_radius = None
    if tile_section.process_type == "block_to_tile" and flat_arc_radius_dimensions:
        selected_flat_arc_radius = (
            min(
                flat_arc_radius_dimensions,
                key=lambda entity: float(entity.dxf.defpoint.y),
            )
            if tile_section.arc_side == "lower"
            else max(
                flat_arc_radius_dimensions,
                key=lambda entity: float(entity.dxf.defpoint.y),
            )
        )
    for entity in source_doc.modelspace():
        if entity.dxftype() != "DIMENSION":
            continue
        if (
            selected_flat_arc_radius is not None
            and entity in flat_arc_radius_dimensions
            and entity is not selected_flat_arc_radius
        ):
            continue
        if skip_secondary_relief_dimension and _dimension_text(entity).startswith("2-"):
            continue
        copied = copy_template_dimension_without_associations(entity)
        copied.dxf.layer = DIMENSION_LAYER
        _update_section_dimension(copied, tile_section, geometry)
        _sync_actual_measurement(copied)
        try:
            modelspace.add_entity(copied)
        except Exception:
            continue
        try:
            copied.render()
        except Exception:
            pass
        _sync_custom_dimension_block_layout(copied)
        _sync_dimension_block_text(copied)


def _safe_measurement(entity) -> float | None:
    try:
        return float(entity.get_measurement())
    except Exception:
        return None


def add_bed_618_r_form_dimensions(
    doc,
    modelspace,
    tile_section: TileSection,
    geometry: SlotDimensionGeometry,
    template_path: str | Path,
) -> None:
    try:
        import ezdxf
    except ImportError as exc:
        raise RuntimeError("ezdxf is required for native section dimensions.") from exc

    source_doc = ezdxf.readfile(template_path)
    source_radius_dimensions = [
        entity
        for entity in source_doc.modelspace().query("DIMENSION")
        if entity.dimtype == 4 and _dimension_text(entity).startswith("2-")
    ]
    if not source_radius_dimensions:
        return
    source = source_radius_dimensions[0]
    sides = (
        (tile_section.arc_side == "lower",)
        if tile_section.process_type == "block_to_tile"
        else (True, False)
    )
    for is_lower in sides:
        copied = copy_template_dimension_without_associations(source)
        copied.dxf.layer = DIMENSION_LAYER
        center = geometry.lower_radius_center if is_lower else geometry.upper_radius_center
        target, text_midpoint = _r_form_dimension_layout(
            geometry,
            tile_section.forming_spec.R_form,
            is_lower=is_lower,
        )
        _set_radius_definition_to_target(copied, center, target)
        copied._cad_custom_dimension_layout = {
            "kind": "radius",
            "target": target,
            "text_midpoint": text_midpoint,
        }
        copied.dxf.text = f"R{tile_section.forming_spec.R_form:.2f}"
        copied.dxf.text_midpoint = (text_midpoint[0], text_midpoint[1], 0.0)
        copied.dxf.actual_measurement = tile_section.forming_spec.R_form
        try:
            modelspace.add_entity(copied)
        except Exception:
            continue
        try:
            copied.render()
        except Exception:
            pass
        _sync_custom_dimension_block_layout(copied)
        _sync_dimension_block_text(copied)


def copy_template_dimension_without_associations(entity):
    """Copy a template DIMENSION without stale AutoCAD association objects.

    Template dimensions are used for their drawing style and annotation layout,
    but their DIMASSOC data points to geometry that is replaced during this
    generation.  Carrying that relationship into the new document is both
    invalid and unsupported by ezdxf, so the copied dimension is deliberately
    detached before its definition points are rebuilt.
    """
    from ezdxf.entities.copy import CopySettings, CopyStrategy

    try:
        strategy = CopyStrategy(CopySettings(copy_extension_dict=False))
        return entity.copy(copy_strategy=strategy)
    except Exception as exc:
        raise RuntimeError("Failed to copy template DIMENSION without DIMASSOC.") from exc


def add_template_dimensions(modelspace, tile_section: TileSection, geometry: SlotDimensionGeometry) -> None:
    add_fixed_template_dimensions(modelspace, tile_section, geometry)


def _add_outer_width_dimension(
    modelspace,
    geometry: SlotDimensionGeometry,
    include_fallback: bool = True,
    include_native: bool = True,
) -> None:
    y = geometry.outer_top + 19.2
    add_linear_dimension_with_text(
        modelspace,
        (geometry.outer_left, geometry.outer_top),
        (geometry.outer_right, geometry.outer_top),
        (geometry.outer_left, y - 0.7),
        (geometry.outer_right, y - 0.7),
        format_dimension(geometry.outer_width),
        (geometry.center_x - 0.8, y + 0.4),
        angle=0.0,
        include_fallback=include_fallback,
        include_native=include_native,
    )


def _add_outer_height_dimension(
    modelspace,
    geometry: SlotDimensionGeometry,
    include_fallback: bool = True,
    include_native: bool = True,
) -> None:
    x = geometry.outer_left - 21.0
    add_linear_dimension_with_text(
        modelspace,
        (geometry.outer_left, geometry.outer_bottom),
        (geometry.outer_left, geometry.outer_top),
        (x + 0.8, geometry.outer_bottom),
        (x + 0.8, geometry.outer_top),
        format_dimension(geometry.outer_height),
        (x - 2.5, (geometry.outer_bottom + geometry.outer_top) / 2.0),
        angle=90.0,
        text_rotation=90.0,
        include_fallback=include_fallback,
        include_native=include_native,
    )


def _add_slot_base_dimension(
    modelspace,
    geometry: SlotDimensionGeometry,
    include_fallback: bool = True,
    include_native: bool = True,
) -> None:
    x = geometry.outer_right + 6.6
    add_linear_dimension_with_text(
        modelspace,
        (geometry.right_x, geometry.base_y),
        (geometry.outer_right, geometry.outer_bottom),
        (x - 0.9, geometry.base_y),
        (x - 0.9, geometry.outer_bottom),
        format_dimension(geometry.slot_base_height),
        (x + 0.4, (geometry.outer_bottom + geometry.base_y) / 2.0),
        angle=90.0,
        text_rotation=90.0,
        include_fallback=include_fallback,
        include_native=include_native,
    )


def _add_line(modelspace, start: tuple[float, float], end: tuple[float, float], layer: str = DIMENSION_LAYER) -> None:
    modelspace.add_line(start, end, dxfattribs={"layer": layer})


def _update_section_dimension(entity, tile_section: TileSection, geometry: SlotDimensionGeometry) -> None:
    measurement = float(entity.get_measurement())
    text = entity.dxf.text
    if abs(measurement - geometry.outer_height) < 0.05:
        _set_linear_definition(entity, (geometry.outer_left, geometry.outer_top), (geometry.outer_left, geometry.outer_bottom))
        _set_dimension_text(entity, format_dimension(geometry.outer_height))
    elif abs(measurement - geometry.outer_width) < 0.05 or (
        _is_horizontal_linear_dimension(entity) and 25.0 <= measurement <= 45.0
    ):
        _set_linear_definition(entity, (geometry.outer_left, geometry.outer_top), (geometry.outer_right, geometry.outer_top))
        _set_dimension_text(entity, format_dimension(geometry.outer_width))
    elif abs(measurement - geometry.slot_base_height) < 0.05 or (
        _is_verticalish_linear_dimension(entity)
        and 5.0 <= measurement <= 25.0
    ):
        _set_linear_definition(entity, (geometry.outer_right, geometry.base_y), (geometry.outer_right, geometry.outer_bottom))
        _set_dimension_text(entity, format_dimension(geometry.slot_base_height))
    elif _is_horizontal_linear_dimension(entity) and (
        abs(measurement - geometry.center_opening) < 0.05
        or 1.0 <= measurement <= 4.0
    ):
        _set_linear_definition(entity, (geometry.opening_left_x, geometry.outer_top), (geometry.opening_right_x, geometry.outer_top))
        _set_dimension_text(entity, format_dimension(geometry.center_opening))
    elif _is_slot_width_dimension(entity, measurement, text, geometry):
        _set_linear_definition(entity, (geometry.left_x, geometry.base_y), (geometry.right_x, geometry.base_y))
        _set_dimension_text(
            entity,
            tile_section.guide_spec.slot_width_dimension_text,
        )
    elif _is_guide_thickness_dimension(entity, measurement, geometry):
        _set_linear_definition(entity, (geometry.right_x, geometry.top_y), (geometry.right_x, geometry.base_y))
        _set_dimension_text(entity, f"{geometry.guide_thickness:.2f}")
    elif text.startswith("4-") or text.startswith("2-") or measurement < 1.0:
        old_center = entity.dxf.defpoint if entity.dxf.hasattr("defpoint") else None
        old_text_midpoint = entity.dxf.text_midpoint if entity.dxf.hasattr("text_midpoint") else None
        is_center_transition = text.startswith("2-")
        new_center = _relief_dimension_center(
            entity,
            geometry,
            center_transition=is_center_transition,
        )
        _set_relief_radius_definition(
            entity,
            new_center,
            geometry,
            center_transition=is_center_transition,
        )
        if old_center is not None and old_text_midpoint is not None and entity.dxf.hasattr("text_midpoint"):
            text_midpoint = (
                new_center[0] + (old_text_midpoint.x - old_center.x),
                new_center[1] + (old_text_midpoint.y - old_center.y),
                0.0,
            )
            entity.dxf.text_midpoint = text_midpoint
            entity._cad_custom_dimension_layout = {
                "kind": "relief_text",
                "text_midpoint": (text_midpoint[0], text_midpoint[1]),
            }
        if is_center_transition:
            _set_dimension_text(
                entity,
                f"2-R{format_dimension(geometry.center_transition_radius)}",
            )
        else:
            _set_dimension_text(entity, tile_section.guide_spec.relief.relief_label)
    elif abs(measurement - 17.45) < 0.05:
        is_lower = (
            tile_section.arc_side == "lower"
            if tile_section.process_type == "block_to_tile"
            else entity.dxf.defpoint.y < 31.7
        )
        center = geometry.lower_radius_center if is_lower else geometry.upper_radius_center
        target, text_midpoint = _r_form_dimension_layout(
            geometry,
            tile_section.forming_spec.R_form,
            is_lower=is_lower,
        )
        _set_radius_definition_to_target(entity, center, target)
        entity._cad_custom_dimension_layout = {
            "kind": "radius",
            "target": target,
            "text_midpoint": text_midpoint,
        }
        if entity.dxf.hasattr("text_midpoint"):
            entity.dxf.text_midpoint = (text_midpoint[0], text_midpoint[1], 0.0)
        _set_dimension_text(entity, f"R{tile_section.forming_spec.R_form:.2f}")


def _sync_actual_measurement(entity) -> None:
    try:
        entity.dxf.actual_measurement = float(entity.get_measurement())
    except Exception:
        pass


def _dimension_text(entity) -> str:
    return entity.dxf.text if entity.dxf.hasattr("text") else ""


def _format_compact_decimal(value: float) -> str:
    return format_dimension(value)


def _is_horizontal_linear_dimension(entity) -> bool:
    if not (entity.dxf.hasattr("defpoint2") and entity.dxf.hasattr("defpoint3")):
        return False
    return abs(entity.dxf.defpoint2.y - entity.dxf.defpoint3.y) <= 0.001


def _is_verticalish_linear_dimension(entity) -> bool:
    if not (entity.dxf.hasattr("defpoint2") and entity.dxf.hasattr("defpoint3")):
        return False
    return abs(entity.dxf.defpoint2.y - entity.dxf.defpoint3.y) > 0.001


def _is_slot_width_dimension(
    entity,
    measurement: float,
    text: str,
    geometry: SlotDimensionGeometry,
) -> bool:
    if not _is_horizontal_linear_dimension(entity):
        return False
    if "±" in text or "<>" in text:
        return True
    if not (3.0 <= measurement <= 20.0):
        return False
    return abs(entity.dxf.defpoint2.y - geometry.base_y) <= 2.0


def _is_guide_thickness_dimension(
    entity,
    measurement: float,
    geometry: SlotDimensionGeometry,
) -> bool:
    if not _is_verticalish_linear_dimension(entity):
        return False
    if not (0.5 <= measurement <= 5.0):
        return False
    if abs(measurement - geometry.center_opening) <= 0.05:
        return False
    return True


def _set_linear_definition(entity, first: tuple[float, float], second: tuple[float, float]) -> None:
    if entity.dxf.hasattr("defpoint2"):
        entity.dxf.defpoint2 = (first[0], first[1], 0.0)
    if entity.dxf.hasattr("defpoint3"):
        entity.dxf.defpoint3 = (second[0], second[1], 0.0)


def _set_radius_definition(entity, center: tuple[float, float], radius: float) -> None:
    if not entity.dxf.hasattr("defpoint4"):
        return
    old_center = entity.dxf.defpoint
    old_point = entity.dxf.defpoint4
    angle = atan2(old_point.y - old_center.y, old_point.x - old_center.x)
    entity.dxf.defpoint = (center[0], center[1], 0.0)
    entity.dxf.defpoint4 = (
        center[0] + radius * cos(angle),
        center[1] + radius * sin(angle),
        0.0,
    )


def _set_relief_radius_definition(
    entity,
    center: tuple[float, float],
    geometry: SlotDimensionGeometry,
    *,
    center_transition: bool = False,
) -> None:
    if not entity.dxf.hasattr("defpoint4"):
        return
    radius = (
        geometry.center_transition_radius
        if center_transition
        else geometry.relief_radius
    )
    if center_transition:
        direction = 1.0 if center[0] < geometry.center_x else -1.0
        entity.dxf.defpoint = (center[0], center[1], 0.0)
        entity.dxf.defpoint4 = (
            center[0] + direction * radius,
            center[1],
            0.0,
        )
        return
    slot_mid_y = (geometry.base_y + geometry.top_y) / 2.0
    direction = -1.0 if center[1] >= slot_mid_y else 1.0
    entity.dxf.defpoint = (center[0], center[1], 0.0)
    entity.dxf.defpoint4 = (
        center[0],
        center[1] + direction * radius,
        0.0,
    )


def _set_radius_definition_to_target(
    entity,
    center: tuple[float, float],
    target: tuple[float, float],
) -> None:
    if not entity.dxf.hasattr("defpoint4"):
        return
    entity.dxf.defpoint = (center[0], center[1], 0.0)
    entity.dxf.defpoint4 = (target[0], target[1], 0.0)


def _r_form_dimension_layout(
    geometry: SlotDimensionGeometry,
    radius: float,
    is_lower: bool,
) -> tuple[tuple[float, float], tuple[float, float]]:
    half_slot = geometry.slot_width / 2.0
    half_opening = geometry.center_opening / 2.0
    if is_lower:
        center = geometry.lower_radius_center
        dx = -min(max(half_slot * 0.78, 0.1), max(half_slot - geometry.relief_radius * 0.25, 0.1))
        text_midpoint = (geometry.left_x - 17.0, geometry.base_y - 3.0)
    else:
        center = geometry.upper_radius_center
        dx = -min(max((half_slot + half_opening) / 2.0, 0.1), max(half_slot - geometry.relief_radius * 0.25, 0.1))
        text_midpoint = (geometry.left_x - 13.0, geometry.top_y + 5.2)
    y = center[1] + (radius * radius - dx * dx) ** 0.5
    return (center[0] + dx, y), text_midpoint


def _radius_dimension_center(entity, geometry: SlotDimensionGeometry) -> tuple[float, float]:
    if entity.dxf.defpoint.y < 31.7:
        return geometry.lower_radius_center
    return geometry.upper_radius_center


def _relief_dimension_center(
    entity,
    geometry: SlotDimensionGeometry,
    *,
    center_transition: bool = False,
) -> tuple[float, float]:
    source = entity.dxf.defpoint
    if center_transition:
        if source.x < geometry.center_x:
            if geometry.center_transition_left_center is not None:
                return geometry.center_transition_left_center
            return (
                geometry.opening_left_x - geometry.center_transition_radius,
                geometry.top_y + geometry.center_transition_radius,
            )
        if geometry.center_transition_right_center is not None:
            return geometry.center_transition_right_center
        return (
            geometry.opening_right_x + geometry.center_transition_radius,
            geometry.top_y + geometry.center_transition_radius,
        )
    if source.x < (geometry.left_x + geometry.right_x) / 2.0:
        x = geometry.left_x
    else:
        x = geometry.right_x
    if source.y > (geometry.base_y + geometry.top_y) / 2.0:
        y = geometry.top_y
    else:
        y = geometry.base_y
    return (x, y)


def _set_dimension_text(entity, text: str) -> None:
    entity.dxf.text = text


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


def _sync_custom_dimension_block_layout(entity) -> None:
    layout = getattr(entity, "_cad_custom_dimension_layout", None)
    if not layout:
        return
    doc = getattr(entity, "doc", None)
    if doc is None or not entity.dxf.hasattr("geometry") or entity.dxf.geometry not in doc.blocks:
        return
    if layout.get("kind") == "relief_text":
        text_midpoint = layout["text_midpoint"]
        entity.dxf.text_midpoint = (text_midpoint[0], text_midpoint[1], 0.0)
        for block_entity in doc.blocks[entity.dxf.geometry]:
            if block_entity.dxftype() == "MTEXT":
                block_entity.dxf.insert = (text_midpoint[0], text_midpoint[1], 0.0)
            elif block_entity.dxftype() == "TEXT":
                block_entity.dxf.insert = (text_midpoint[0], text_midpoint[1], 0.0)
        return
    if layout.get("kind") != "radius":
        return
    target = layout["target"]
    text_midpoint = layout["text_midpoint"]
    entity.dxf.text_midpoint = (text_midpoint[0], text_midpoint[1], 0.0)
    center = entity.dxf.defpoint
    radial_line_done = False
    leader_line_done = False
    for block_entity in doc.blocks[entity.dxf.geometry]:
        if block_entity.dxftype() == "MTEXT":
            block_entity.dxf.insert = (text_midpoint[0], text_midpoint[1], 0.0)
        elif block_entity.dxftype() == "TEXT":
            block_entity.dxf.insert = (text_midpoint[0], text_midpoint[1], 0.0)
        elif block_entity.dxftype() == "LINE":
            if not radial_line_done:
                block_entity.dxf.start = (center.x, center.y, center.z)
                block_entity.dxf.end = (target[0], target[1], 0.0)
                radial_line_done = True
            elif not leader_line_done:
                block_entity.dxf.start = (target[0], target[1], 0.0)
                block_entity.dxf.end = (text_midpoint[0], text_midpoint[1], 0.0)
                leader_line_done = True


def _add_native_linear_dimension(
    modelspace,
    start: tuple[float, float],
    end: tuple[float, float],
    dimension_line_start: tuple[float, float],
    text: str,
    text_insert: tuple[float, float],
    angle: float,
    text_rotation: float | None,
    layer: str,
    dimstyle: str,
    dimension_text_height: float,
):
    override = dict(DIMENSION_OVERRIDES)
    override["dimtxt"] = dimension_text_height
    if text_rotation is not None:
        override["dimtih"] = 0
        override["dimtoh"] = 0
    dimension = modelspace.add_linear_dim(
        base=dimension_line_start,
        p1=start,
        p2=end,
        location=text_insert,
        text=text,
        angle=angle,
        text_rotation=text_rotation,
        dimstyle=dimstyle,
        override=override,
        dxfattribs={"layer": layer},
    )
    dimension.render()
    dimension.dimension.dxf.actual_measurement = _projected_distance(start, end, angle)
    return dimension.dimension


def _add_native_radius_dimension(
    modelspace,
    center: tuple[float, float],
    radius: float,
    angle: float,
    text: str,
    location: tuple[float, float],
    layer: str,
) -> None:
    dimension = modelspace.add_radius_dim(
        center=center,
        radius=radius,
        angle=angle,
        location=location,
        text=text,
        override=DIMENSION_OVERRIDES,
        dxfattribs={"layer": layer},
    )
    dimension.render()
    dimension.dimension.dxf.actual_measurement = radius


def _dimension_text_style(modelspace) -> str:
    doc = getattr(modelspace, "doc", None)
    if doc is not None and DIMENSION_TEXT_STYLE in doc.styles:
        return DIMENSION_TEXT_STYLE
    return "Standard"


def _projected_distance(start: tuple[float, float], end: tuple[float, float], angle: float) -> float:
    theta = radians(angle)
    return abs((end[0] - start[0]) * cos(theta) + (end[1] - start[1]) * sin(theta))

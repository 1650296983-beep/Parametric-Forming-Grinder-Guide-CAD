from __future__ import annotations

import json
from math import atan2, cos, degrees, hypot, radians, sin, sqrt
from pathlib import Path
from typing import Any

from .block_geometry import BlockGuideSection
from .dimension_roles import get_dimension_role
from .geometry import TileSection
from .global_rules import (
    DIMENSION_POINT_BINDING_TOLERANCE,
    WHEEL_CUT_IN_RATIO,
)
from .machine_config import MachineConfig
from .side_view_writer import SIDE_CAVITY_LAYER, SIDE_DERIVED_RELEASE_LAYER


POINT_TOLERANCE = DIMENSION_POINT_BINDING_TOLERANCE
FORMAL_GEOMETRY_LAYERS = {
    "FIXED_TEMPLATE",
    "PARAM_SLOT",
    "SIDE_TEMPLATE",
    SIDE_CAVITY_LAYER,
    SIDE_DERIVED_RELEASE_LAYER,
    "SIDE_CENTER",
}


def write_dimension_definition_point_audit(
    dxf_path: str | Path,
    profile: TileSection | BlockGuideSection,
    machine: MachineConfig,
    output_path: str | Path,
) -> dict[str, Any]:
    payload = build_dimension_definition_point_audit(
        dxf_path,
        profile,
        machine,
    )
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def build_dimension_definition_point_audit(
    dxf_path: str | Path,
    profile: TileSection | BlockGuideSection,
    machine: MachineConfig,
) -> dict[str, Any]:
    import ezdxf

    doc = ezdxf.readfile(dxf_path)
    modelspace = doc.modelspace()
    geometry = [
        entity
        for entity in modelspace
        if entity.dxftype() in {"LINE", "ARC", "CIRCLE"}
        and entity.dxf.layer in FORMAL_GEOMETRY_LAYERS
    ]
    entries = []
    for dimension in modelspace.query("DIMENSION"):
        measurement = _measurement(dimension)
        display_text = _dimension_display_text(doc, dimension)
        role = _dimension_role(
            dimension,
            display_text,
            measurement,
            profile,
            machine,
        )
        if dimension.dxf.hasattr("defpoint2") and dimension.dxf.hasattr(
            "defpoint3"
        ):
            point_1 = dimension.dxf.defpoint2
            point_2 = dimension.dxf.defpoint3
            nearest_1 = _nearest_geometry_point(point_1, geometry)
            nearest_2 = _nearest_geometry_point(point_2, geometry)
            point_error = max(nearest_1["distance"], nearest_2["distance"])
            expected_1 = nearest_1["point"]
            expected_2 = nearest_2["point"]
            defpoint2 = _point_payload(point_1)
            defpoint3 = _point_payload(point_2)
            binding_mode = "entity_point"
            if _rounded_slot_virtual_datum_is_valid(
                point_1,
                point_2,
                nearest_1,
                nearest_2,
                measurement,
                role,
                profile,
            ):
                # Rounded reliefs remove the sharp envelope corner. The dimension
                # remains bound to the exact intersection of the two tangent
                # extensions that define slot width/thickness.
                point_error = 0.0
                expected_1 = defpoint2
                expected_2 = defpoint3
                binding_mode = "rounded_slot_tangent_envelope"
            elif _rounded_corner_virtual_datum_is_valid(
                nearest_1,
                nearest_2,
                profile,
            ):
                point_error = 0.0
                expected_1 = defpoint2
                expected_2 = defpoint3
                binding_mode = "rounded_corner_tangent_envelope"
        elif dimension.dxf.hasattr("defpoint") and dimension.dxf.hasattr(
            "defpoint4"
        ):
            center = dimension.dxf.defpoint
            target = dimension.dxf.defpoint4
            target_measurement = measurement
            is_diameter_annotation = (
                (int(dimension.dxf.dimtype) & 15) == 3
                and ("∅" in display_text or "DIA" in display_text.upper())
            )
            if is_diameter_annotation:
                endpoint_1 = center
                endpoint_2 = target
                center, _ = _diameter_center_and_endpoint(endpoint_1, endpoint_2)
                if measurement is not None:
                    target_measurement = measurement / 2.0
                matches = [
                    _nearest_radius_geometry(
                        center,
                        endpoint,
                        target_measurement,
                        geometry,
                    )
                    for endpoint in (endpoint_1, endpoint_2)
                ]
                radius_match = min(matches, key=lambda item: item["distance"])
                target = endpoint_1 if radius_match is matches[0] else endpoint_2
            else:
                radius_match = _nearest_radius_geometry(
                    center,
                    target,
                    target_measurement,
                    geometry,
                )
            point_error = radius_match["distance"]
            expected_1 = radius_match["center"]
            expected_2 = radius_match["target"]
            defpoint2 = _point_payload(center)
            defpoint3 = _point_payload(target)
            binding_mode = "radius_or_diameter_entity"
        else:
            point_error = float("inf")
            expected_1 = None
            expected_2 = None
            defpoint2 = None
            defpoint3 = None
            binding_mode = "unresolved"

        annotation_block_bound = None
        if (
            machine.guide_sections == 2
            and role == "relief"
            and dimension.dxf.hasattr("defpoint4")
        ):
            annotation_block_bound = _dimension_block_references_point(
                doc,
                dimension,
                dimension.dxf.defpoint4,
            )
            if not annotation_block_bound:
                point_error = max(point_error, POINT_TOLERANCE + 1.0)

        entries.append(
            {
                "dimension_handle": dimension.dxf.handle,
                "dimension_role": role,
                "measurement": _round_optional(measurement),
                "display_text": display_text,
                "defpoint2": defpoint2,
                "defpoint3": defpoint3,
                "expected_geometry_point_1": expected_1,
                "expected_geometry_point_2": expected_2,
                "point_error": (
                    None
                    if point_error == float("inf")
                    else round(point_error, 6)
                ),
                "binding_mode": binding_mode,
                "annotation_block_bound": annotation_block_bound,
                "bound_to_geometry": point_error <= POINT_TOLERANCE,
            }
        )

    role_audit = _required_role_audit(entries, profile, machine)
    all_bound = bool(entries) and all(
        entry["bound_to_geometry"] for entry in entries
    )
    return {
        "dxf_path": str(dxf_path),
        "point_tolerance": POINT_TOLERANCE,
        "dimension_count": len(entries),
        "dimensions": entries,
        "required_roles": role_audit,
        "all_dimensions_bound_to_geometry": all_bound,
        "all_required_roles_pass": all(
            item["status"] == "PASS" for item in role_audit.values()
        ),
        "release_allowed": all_bound
        and all(item["status"] == "PASS" for item in role_audit.values()),
    }


def build_release_line_type_audit(dxf_path: str | Path) -> dict[str, Any]:
    import ezdxf

    doc = ezdxf.readfile(dxf_path)
    modelspace = doc.modelspace()
    cavity_lines = [
        entity
        for entity in modelspace.query("LINE")
        if entity.dxf.layer == SIDE_CAVITY_LAYER
    ]
    derived_release_lines = [
        entity
        for entity in modelspace.query("LINE")
        if entity.dxf.layer == SIDE_DERIVED_RELEASE_LAYER
    ]
    invalid_cavity_lines = [
        {
            "handle": entity.dxf.handle,
            "linetype": entity.dxf.linetype,
            "effective_linetype": _effective_linetype(doc, entity),
            "effective_color": _effective_color(doc, entity),
        }
        for entity in cavity_lines
        if _effective_linetype(doc, entity).upper() != "DASHED"
        or _effective_color(doc, entity) != 3
    ]
    invalid_release_lines = [
        {
            "handle": entity.dxf.handle,
            "linetype": entity.dxf.linetype,
            "effective_linetype": _effective_linetype(doc, entity),
        }
        for entity in derived_release_lines
        if _effective_linetype(doc, entity).upper() != "CONTINUOUS"
    ]
    legacy_formal_lines = [
        entity.dxf.handle
        for entity in modelspace.query("LINE")
        if entity.dxf.layer == "SIDE_DERIVED"
    ]
    dashed_formal_lines = [
        {
            "handle": entity.dxf.handle,
            "layer": entity.dxf.layer,
            "linetype": _effective_linetype(doc, entity),
        }
        for entity in modelspace.query("LINE")
        if entity.dxf.layer in {SIDE_DERIVED_RELEASE_LAYER, "SIDE_TEMPLATE"}
        and _effective_linetype(doc, entity).upper() == "DASHED"
    ]
    duplicate_cavity_lines = _duplicate_line_handles(cavity_lines)
    release_allowed = (
        bool(cavity_lines)
        and not invalid_cavity_lines
        and not duplicate_cavity_lines
        and not invalid_release_lines
        and not legacy_formal_lines
        and not dashed_formal_lines
    )
    return {
        "release_layer": SIDE_CAVITY_LAYER,
        "release_line_count": len(cavity_lines),
        "cavity_line_count": len(cavity_lines),
        "invalid_cavity_lines": invalid_cavity_lines,
        "duplicate_cavity_lines": duplicate_cavity_lines,
        "derived_release_line_count": len(derived_release_lines),
        "invalid_release_lines": invalid_release_lines,
        "legacy_SIDE_DERIVED_lines": legacy_formal_lines,
        "dashed_formal_lines": dashed_formal_lines,
        "release_allowed": release_allowed,
    }


def _duplicate_line_handles(lines: list[Any]) -> list[list[str]]:
    handles_by_geometry: dict[
        tuple[tuple[float, float], tuple[float, float]], list[str]
    ] = {}
    for line in lines:
        start = (
            round(float(line.dxf.start.x), 6),
            round(float(line.dxf.start.y), 6),
        )
        end = (
            round(float(line.dxf.end.x), 6),
            round(float(line.dxf.end.y), 6),
        )
        key = tuple(sorted((start, end)))
        handles_by_geometry.setdefault(key, []).append(str(line.dxf.handle))
    return [
        handles
        for handles in handles_by_geometry.values()
        if len(handles) > 1
    ]


def _dimension_role(
    dimension: Any,
    display_text: str,
    measurement: float | None,
    profile: TileSection | BlockGuideSection,
    machine: MachineConfig,
) -> str:
    explicit_role = get_dimension_role(dimension)
    if explicit_role is not None:
        return explicit_role
    normalized = display_text.replace(" ", "")
    guide = profile.guide_spec
    r_form = profile.forming_spec.R_form if isinstance(profile, TileSection) else None
    if (
        ("±0.01" in normalized or "\\S+0.01^-0.01;" in normalized)
        and _close(measurement, guide.guide_slot_width)
    ):
        return "slot_width"
    if r_form is not None and normalized.startswith(f"R{r_form:.2f}"):
        return "R_form"
    if _close(measurement, guide.guide_thickness) and normalized == f"{guide.guide_thickness:.2f}":
        return "guide_thickness"
    if _close(measurement, _lower_wheel_crown_depth(profile, machine)):
        return "lower_wheel_crown_depth"
    if _close(measurement, 12.70):
        return "upper_wheel_related"
    opening = min(
        _natural_opening(
            profile.process_thickness
            if isinstance(profile, TileSection)
            else profile.block_spec.thickness_mid,
            machine.wheel_radius,
        ),
        (profile.process_length if isinstance(profile, TileSection) else profile.block_spec.length) - 0.2,
    )
    if _close(measurement, opening):
        return "lower_cavity_notch_opening"
    if _close(measurement, machine.guide_length):
        return "fixed_guide_length_590"
    for value in (99.0, 90.0, 180.0, 131.0):
        if _close(measurement, value):
            return f"fixed_span_{value:g}"
    if _close(measurement, machine.wheel_radius):
        return "wheel_radius"
    if _close(measurement, 40.0):
        return "fixed_section_width_40"
    if _close(measurement, 27.0):
        return "fixed_section_height_27"
    if _close(measurement, 12.0):
        return "fixed_slot_base_12"
    if normalized.startswith(("4-", "2-")):
        return "relief"
    return "other_release_dimension"


def _required_role_audit(
    entries: list[dict[str, Any]],
    profile: TileSection | BlockGuideSection,
    machine: MachineConfig,
) -> dict[str, Any]:
    requirements = {
        "slot_width": (
            profile.guide_spec.guide_slot_width,
            machine.guide_sections,
        ),
        "guide_thickness": (
            profile.guide_spec.guide_thickness,
            machine.guide_sections,
        ),
    }
    if machine.guide_sections == 2:
        requirements.update(
            {
                "section_center_opening": (
                    machine.section_center_opening,
                    machine.guide_sections,
                ),
                "relief": (
                    profile.guide_spec.relief.relief_size / 2.0,
                    machine.guide_sections,
                ),
            }
        )
    if machine.machine_id == "triple_double_down_up_up":
        requirements.update({
        "lower_wheel_crown_depth": (
            _lower_wheel_crown_depth(profile, machine),
            2,
        ),
        "upper_wheel_related": (12.70, 4),
        "lower_cavity_notch_opening": (
            min(
                _natural_opening(
                    profile.process_thickness
                    if isinstance(profile, TileSection)
                    else profile.block_spec.thickness_mid,
                    machine.wheel_radius,
                ),
                (
                    profile.process_length
                    if isinstance(profile, TileSection)
                    else profile.block_spec.length
                )
                - 0.2,
            ),
            1,
        ),
        "fixed_guide_length_590": (machine.guide_length, 1),
        "fixed_span_99": (99.0, 2),
        "fixed_span_90": (90.0, 4),
        "fixed_span_180": (180.0, 2),
        "fixed_span_131": (131.0, 2),
        })
    if (
        isinstance(profile, TileSection)
        and machine.machine_id == "triple_double_down_up_up"
    ):
        requirements["R_form"] = (profile.forming_spec.R_form, 2)
    payload = {}
    for role, (expected, minimum_count) in requirements.items():
        matched = [entry for entry in entries if entry["dimension_role"] == role]
        values_ok = all(
            entry["measurement"] is not None
            and abs(entry["measurement"] - expected) <= POINT_TOLERANCE
            for entry in matched
        )
        bound = all(entry["bound_to_geometry"] for entry in matched)
        status = (
            "PASS"
            if len(matched) >= minimum_count and values_ok and bound
            else "FAIL"
        )
        payload[role] = {
            "expected_measurement": round(expected, 6),
            "minimum_count": minimum_count,
            "actual_count": len(matched),
            "all_bound_to_geometry": bound,
            "status": status,
        }
    return payload


def _dimension_block_references_point(doc: Any, dimension: Any, point: Any) -> bool:
    """Confirm that a rendered annotation still reaches its geometric target."""
    if not dimension.dxf.hasattr("geometry"):
        return False
    block_name = dimension.dxf.geometry
    if block_name not in doc.blocks:
        return False
    target = (float(point.x), float(point.y))
    for entity in doc.blocks[block_name]:
        for attribute in (
            "start",
            "end",
            "center",
            "insert",
            "location",
            "vtx0",
            "vtx1",
            "vtx2",
            "vtx3",
        ):
            if not entity.dxf.hasattr(attribute):
                continue
            candidate = entity.dxf.get(attribute)
            if hypot(float(candidate.x) - target[0], float(candidate.y) - target[1]) <= POINT_TOLERANCE:
                return True
    return False


def _diameter_center_and_endpoint(
    endpoint_1: Any,
    endpoint_2: Any,
) -> tuple[Any, Any]:
    from ezdxf.math import Vec3

    center = Vec3(
        (float(endpoint_1.x) + float(endpoint_2.x)) / 2.0,
        (float(endpoint_1.y) + float(endpoint_2.y)) / 2.0,
        (float(endpoint_1.z) + float(endpoint_2.z)) / 2.0,
    )
    return center, endpoint_2


def _nearest_geometry_point(point: Any, geometry: list[Any]) -> dict[str, Any]:
    best = {
        "distance": float("inf"),
        "point": None,
    }
    px = float(point.x)
    py = float(point.y)
    for entity in geometry:
        if entity.dxftype() == "LINE":
            nearest = _nearest_point_on_line(px, py, entity)
        else:
            nearest = _nearest_point_on_circle_or_arc(px, py, entity)
        distance = hypot(px - nearest[0], py - nearest[1])
        if distance < best["distance"]:
            best = {
                "distance": distance,
                "point": [round(nearest[0], 6), round(nearest[1], 6), 0.0],
            }
    return best


def _nearest_radius_geometry(
    center: Any,
    target: Any,
    measurement: float | None,
    geometry: list[Any],
) -> dict[str, Any]:
    best = {
        "distance": float("inf"),
        "center": None,
        "target": None,
    }
    for entity in geometry:
        if entity.dxftype() not in {"ARC", "CIRCLE"}:
            continue
        radius = float(entity.dxf.radius)
        if measurement is None or abs(radius - measurement) > POINT_TOLERANCE:
            continue
        candidate_center = entity.dxf.center
        nearest_target = _nearest_point_on_circle_or_arc(
            float(target.x),
            float(target.y),
            entity,
        )
        center_error = hypot(
            float(center.x) - float(candidate_center.x),
            float(center.y) - float(candidate_center.y),
        )
        target_error = hypot(
            float(target.x) - nearest_target[0],
            float(target.y) - nearest_target[1],
        )
        error = max(center_error, target_error)
        if error < best["distance"]:
            best = {
                "distance": error,
                "center": _point_payload(candidate_center),
                "target": [
                    round(nearest_target[0], 6),
                    round(nearest_target[1], 6),
                    0.0,
                ],
            }
    return best


def _rounded_slot_virtual_datum_is_valid(
    point_1: Any,
    point_2: Any,
    nearest_1: dict[str, Any],
    nearest_2: dict[str, Any],
    measurement: float | None,
    role: str,
    profile: TileSection | BlockGuideSection,
) -> bool:
    if role not in {"slot_width", "guide_thickness"}:
        return False
    if measurement is None:
        return False
    expected = (
        profile.guide_spec.guide_slot_width
        if role == "slot_width"
        else profile.guide_spec.guide_thickness
    )
    if abs(measurement - expected) > POINT_TOLERANCE:
        return False
    relief_radius = profile.guide_spec.relief.relief_size / 2.0
    distances = (nearest_1["distance"], nearest_2["distance"])
    if any(distance > relief_radius + POINT_TOLERANCE for distance in distances):
        return False
    dx = abs(float(point_2.x) - float(point_1.x))
    dy = abs(float(point_2.y) - float(point_1.y))
    if role == "slot_width":
        return dy <= POINT_TOLERANCE and abs(dx - expected) <= POINT_TOLERANCE
    return dx <= POINT_TOLERANCE and abs(dy - expected) <= POINT_TOLERANCE


def _rounded_corner_virtual_datum_is_valid(
    nearest_1: dict[str, Any],
    nearest_2: dict[str, Any],
    profile: TileSection | BlockGuideSection,
) -> bool:
    relief_radius = profile.guide_spec.relief.relief_size / 2.0
    distances = (nearest_1["distance"], nearest_2["distance"])
    if any(distance > relief_radius + POINT_TOLERANCE for distance in distances):
        return False
    # At least one definition point must already touch formal geometry.  The
    # other may use the exact tangent-envelope corner removed by the relief.
    return any(distance <= POINT_TOLERANCE for distance in distances)


def _nearest_point_on_line(px: float, py: float, entity: Any) -> tuple[float, float]:
    start = entity.dxf.start
    end = entity.dxf.end
    dx = float(end.x) - float(start.x)
    dy = float(end.y) - float(start.y)
    denominator = dx * dx + dy * dy
    if denominator <= 1e-12:
        return float(start.x), float(start.y)
    t = (
        (px - float(start.x)) * dx
        + (py - float(start.y)) * dy
    ) / denominator
    t = max(0.0, min(1.0, t))
    return float(start.x) + t * dx, float(start.y) + t * dy


def _nearest_point_on_circle_or_arc(
    px: float,
    py: float,
    entity: Any,
) -> tuple[float, float]:
    center = entity.dxf.center
    radius = float(entity.dxf.radius)
    angle = degrees(atan2(py - float(center.y), px - float(center.x))) % 360.0
    if entity.dxftype() == "CIRCLE" or _angle_on_arc(
        angle,
        float(entity.dxf.start_angle),
        float(entity.dxf.end_angle),
    ):
        return (
            float(center.x) + radius * cos(radians(angle)),
            float(center.y) + radius * sin(radians(angle)),
        )
    endpoints = []
    for endpoint_angle in (
        float(entity.dxf.start_angle),
        float(entity.dxf.end_angle),
    ):
        endpoints.append(
            (
                float(center.x) + radius * cos(radians(endpoint_angle)),
                float(center.y) + radius * sin(radians(endpoint_angle)),
            )
        )
    return min(endpoints, key=lambda item: hypot(px - item[0], py - item[1]))


def _angle_on_arc(angle: float, start: float, end: float) -> bool:
    return (angle - start) % 360.0 <= (end - start) % 360.0 + 1e-9


def _dimension_display_text(doc: Any, dimension: Any) -> str:
    if dimension.dxf.hasattr("geometry") and dimension.dxf.geometry in doc.blocks:
        for entity in doc.blocks[dimension.dxf.geometry]:
            if entity.dxftype() == "TEXT" and entity.dxf.text:
                return entity.dxf.text
            if entity.dxftype() == "MTEXT" and entity.text:
                return entity.text
    return dimension.dxf.text if dimension.dxf.hasattr("text") else ""


def _effective_linetype(doc: Any, entity: Any) -> str:
    linetype = entity.dxf.linetype
    if linetype.upper() == "BYLAYER":
        return doc.layers.get(entity.dxf.layer).dxf.linetype
    return linetype


def _effective_color(doc: Any, entity: Any) -> int:
    color = int(entity.dxf.color)
    if color == 256:
        return int(doc.layers.get(entity.dxf.layer).dxf.color)
    return color


def _measurement(dimension: Any) -> float | None:
    try:
        return float(dimension.get_measurement())
    except Exception:
        return None


def _point_payload(point: Any) -> list[float]:
    return [
        round(float(point.x), 6),
        round(float(point.y), 6),
        round(float(point.z), 6),
    ]


def _round_optional(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def _natural_opening(thickness: float, radius: float) -> float:
    depth = thickness * WHEEL_CUT_IN_RATIO
    return 2.0 * sqrt(max(0.0, radius * radius - (radius - depth) ** 2))


def _lower_wheel_crown_depth(
    profile: TileSection | BlockGuideSection,
    machine: MachineConfig,
) -> float:
    thickness = (
        profile.process_thickness
        if isinstance(profile, TileSection)
        else profile.block_spec.thickness_mid
    )
    product_length = (
        profile.process_length
        if isinstance(profile, TileSection)
        else profile.block_spec.length
    )
    radius = machine.wheel_radius
    opening = min(
        _natural_opening(thickness, radius),
        product_length - 0.2,
    )
    effective_depth = radius - sqrt(
        max(0.0, radius * radius - (opening / 2.0) ** 2)
    )
    return machine.section_slot_base_height + effective_depth


def _close(
    value: float | None,
    expected: float,
    tolerance: float = POINT_TOLERANCE,
) -> bool:
    return value is not None and abs(value - expected) <= tolerance

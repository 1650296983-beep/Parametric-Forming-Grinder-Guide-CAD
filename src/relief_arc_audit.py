from __future__ import annotations

from math import cos, radians
from typing import Any


OUTER_RELIEF_MIN_SWEEP_DEGREES = 180.0


def build_four_outer_relief_arc_audit(
    modelspace: Any,
    relief_radius: float,
    *,
    left_x: float | None = None,
    right_x: float | None = None,
    base_y: float | None = None,
    top_y: float | None = None,
    tolerance: float = 0.001,
) -> dict[str, Any]:
    """Audit that the four side reliefs retain their outer DXF arc segments.

    A relief's two tangent endpoints define a short inner arc and a long outer
    complement.  The production contour must keep the latter.  Optional slot
    bounds isolate one section when a dual-guide drawing contains two sections
    at the same X coordinates.
    """
    candidates = [
        entity
        for entity in modelspace.query("ARC")
        if entity.dxf.layer == "PARAM_SLOT"
        and abs(float(entity.dxf.radius) - relief_radius) <= tolerance
    ]
    if base_y is not None and top_y is not None:
        candidates = [
            entity
            for entity in candidates
            if base_y - relief_radius - tolerance
            <= float(entity.dxf.center.y)
            <= top_y + relief_radius + tolerance
        ]
    if not candidates:
        return {
            "release_allowed": False,
            "reason": "No PARAM_SLOT relief arcs found.",
            "expected_count": 4,
            "actual_count": 0,
            "arcs": [],
        }

    expected_left_x = (
        min(float(entity.dxf.center.x) for entity in candidates)
        if left_x is None
        else left_x
    )
    expected_right_x = (
        max(float(entity.dxf.center.x) for entity in candidates)
        if right_x is None
        else right_x
    )
    left_arcs = [
        entity
        for entity in candidates
        if abs(float(entity.dxf.center.x) - expected_left_x) <= tolerance
    ]
    right_arcs = [
        entity
        for entity in candidates
        if abs(float(entity.dxf.center.x) - expected_right_x) <= tolerance
    ]
    side_arcs = [*left_arcs, *right_arcs]
    entries = [
        _outer_relief_arc_entry(entity, "left", tolerance)
        for entity in left_arcs
    ] + [
        _outer_relief_arc_entry(entity, "right", tolerance)
        for entity in right_arcs
    ]
    return {
        "release_allowed": len(side_arcs) == 4
        and all(entry["is_outer_segment"] for entry in entries),
        "expected_count": 4,
        "actual_count": len(side_arcs),
        "relief_radius": round(relief_radius, 6),
        "arcs": entries,
    }


def _outer_relief_arc_entry(entity: Any, side: str, tolerance: float) -> dict[str, Any]:
    center = entity.dxf.center
    start_angle = float(entity.dxf.start_angle) % 360.0
    end_angle = float(entity.dxf.end_angle) % 360.0
    sweep = (end_angle - start_angle) % 360.0
    midpoint_angle = start_angle + sweep / 2.0
    midpoint_x = float(center.x) + float(entity.dxf.radius) * cos(
        radians(midpoint_angle)
    )
    outside = (
        midpoint_x < float(center.x) - tolerance
        if side == "left"
        else midpoint_x > float(center.x) + tolerance
    )
    return {
        "handle": entity.dxf.handle,
        "side": side,
        "center": [round(float(center.x), 6), round(float(center.y), 6)],
        "start_angle": round(start_angle, 6),
        "end_angle": round(end_angle, 6),
        "sweep": round(sweep, 6),
        "midpoint_x": round(midpoint_x, 6),
        "is_outer_segment": sweep > OUTER_RELIEF_MIN_SWEEP_DEGREES + tolerance
        and outside,
    }

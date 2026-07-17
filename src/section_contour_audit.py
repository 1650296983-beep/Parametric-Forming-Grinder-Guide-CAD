from __future__ import annotations

from math import hypot
from pathlib import Path
from typing import Any

from .global_rules import ENDPOINT_TOLERANCE


def build_section_contour_closure_audit(
    dxf_path: str | Path,
    *,
    expected_sections: int,
    tolerance: float = ENDPOINT_TOLERANCE,
) -> dict[str, Any]:
    import ezdxf

    doc = ezdxf.readfile(dxf_path)
    return build_modelspace_section_contour_closure_audit(
        doc.modelspace(),
        expected_sections=expected_sections,
        tolerance=tolerance,
    )


def build_modelspace_section_contour_closure_audit(
    modelspace: Any,
    *,
    expected_sections: int,
    tolerance: float = ENDPOINT_TOLERANCE,
) -> dict[str, Any]:
    """Audit each cavity chain and both joins to the fixed guide top boundary."""
    parametric_entities = [
        entity
        for entity in modelspace
        if entity.dxf.layer == "PARAM_SLOT"
        and entity.dxftype() in {"LINE", "ARC"}
    ]
    fixed_lines = [
        entity
        for entity in modelspace.query("LINE")
        if entity.dxf.layer == "FIXED_TEMPLATE"
    ]
    if not parametric_entities:
        return {
            "expected_section_count": expected_sections,
            "actual_section_count": 0,
            "endpoint_tolerance": tolerance,
            "sections": [],
            "release_allowed": False,
            "reason": "No PARAM_SLOT line or arc entities were found.",
        }

    nodes: list[dict[str, Any]] = []
    entity_nodes: list[tuple[int, int]] = []
    for entity_index, entity in enumerate(parametric_entities):
        endpoints = _entity_endpoints(entity)
        node_indexes = tuple(
            _find_or_add_node(
                nodes,
                point,
                entity_index=entity_index,
                handle=str(entity.dxf.handle),
                tolerance=tolerance,
            )
            for point in endpoints
        )
        entity_nodes.append(node_indexes)

    components = _entity_components(entity_nodes)
    section_results = [
        _audit_component(
            component,
            nodes,
            entity_nodes,
            parametric_entities,
            fixed_lines,
            tolerance,
        )
        for component in components
    ]
    release_allowed = (
        len(section_results) == expected_sections
        and all(section["closed"] for section in section_results)
    )
    return {
        "expected_section_count": expected_sections,
        "actual_section_count": len(section_results),
        "endpoint_tolerance": tolerance,
        "sections": section_results,
        "release_allowed": release_allowed,
    }


def _audit_component(
    component: set[int],
    nodes: list[dict[str, Any]],
    entity_nodes: list[tuple[int, int]],
    entities: list[Any],
    fixed_lines: list[Any],
    tolerance: float,
) -> dict[str, Any]:
    node_indexes = sorted(
        {
            node_index
            for entity_index in component
            for node_index in entity_nodes[entity_index]
        }
    )
    node_entries = []
    mouth_entries = []
    invalid_nodes = []
    maximum_parametric_gap = 0.0
    for node_index in node_indexes:
        node = nodes[node_index]
        occurrences = [
            occurrence
            for occurrence in node["occurrences"]
            if occurrence["entity_index"] in component
        ]
        degree = len(occurrences)
        point_gap = _maximum_point_gap(
            [occurrence["point"] for occurrence in occurrences]
        )
        maximum_parametric_gap = max(maximum_parametric_gap, point_gap)
        entry = {
            "point": _rounded_point(node["point"]),
            "degree": degree,
            "point_gap": round(point_gap, 9),
            "entity_handles": [
                occurrence["handle"] for occurrence in occurrences
            ],
        }
        node_entries.append(entry)
        if degree == 1:
            mouth_entries.append(
                _fixed_boundary_connection(
                    node["point"],
                    fixed_lines,
                    tolerance,
                )
            )
        elif degree != 2:
            invalid_nodes.append(entry)

    mouth_entries.sort(key=lambda item: item["point"][0])
    fixed_line_bridges_mouth = (
        len(mouth_entries) == 2
        and _fixed_line_bridges_opening(
            fixed_lines,
            mouth_entries[0]["point"],
            mouth_entries[1]["point"],
            tolerance,
        )
    )
    maximum_fixed_join_gap = max(
        (
            entry["nearest_fixed_endpoint_distance"]
            for entry in mouth_entries
            if entry["nearest_fixed_endpoint_distance"] is not None
        ),
        default=None,
    )
    closed = (
        len(mouth_entries) == 2
        and not invalid_nodes
        and maximum_parametric_gap <= tolerance
        and all(entry["connected"] for entry in mouth_entries)
        and not fixed_line_bridges_mouth
    )
    return {
        "entity_count": len(component),
        "entity_handles": sorted(
            str(entities[index].dxf.handle) for index in component
        ),
        "node_count": len(node_entries),
        "mouth_count": len(mouth_entries),
        "mouth_connections": mouth_entries,
        "invalid_nodes": invalid_nodes,
        "maximum_parametric_endpoint_gap": round(
            maximum_parametric_gap,
            9,
        ),
        "maximum_fixed_join_gap": (
            None
            if maximum_fixed_join_gap is None
            else round(maximum_fixed_join_gap, 9)
        ),
        "fixed_line_bridges_mouth": fixed_line_bridges_mouth,
        "closed": closed,
    }


def _fixed_boundary_connection(
    point: tuple[float, float],
    fixed_lines: list[Any],
    tolerance: float,
) -> dict[str, Any]:
    candidates = []
    for line in fixed_lines:
        start = (float(line.dxf.start.x), float(line.dxf.start.y))
        end = (float(line.dxf.end.x), float(line.dxf.end.y))
        if abs(start[1] - end[1]) > tolerance:
            continue
        for endpoint in (start, end):
            candidates.append(
                (
                    _distance(point, endpoint),
                    str(line.dxf.handle),
                    endpoint,
                )
            )
    nearest = min(candidates, default=None, key=lambda item: item[0])
    matching = [
        candidate
        for candidate in candidates
        if candidate[0] <= tolerance
    ]
    return {
        "point": _rounded_point(point),
        "connected": len(matching) == 1,
        "matching_fixed_endpoint_count": len(matching),
        "matching_fixed_line_handles": sorted(
            candidate[1] for candidate in matching
        ),
        "nearest_fixed_endpoint": (
            None if nearest is None else _rounded_point(nearest[2])
        ),
        "nearest_fixed_endpoint_distance": (
            None if nearest is None else nearest[0]
        ),
    }


def _fixed_line_bridges_opening(
    fixed_lines: list[Any],
    left: tuple[float, float],
    right: tuple[float, float],
    tolerance: float,
) -> bool:
    if abs(left[1] - right[1]) > tolerance:
        return True
    for line in fixed_lines:
        start = (float(line.dxf.start.x), float(line.dxf.start.y))
        end = (float(line.dxf.end.x), float(line.dxf.end.y))
        if (
            abs(start[1] - left[1]) > tolerance
            or abs(end[1] - left[1]) > tolerance
        ):
            continue
        line_left = min(start[0], end[0])
        line_right = max(start[0], end[0])
        if (
            line_left <= left[0] + tolerance
            and line_right >= right[0] - tolerance
        ):
            return True
    return False


def _find_or_add_node(
    nodes: list[dict[str, Any]],
    point: tuple[float, float],
    *,
    entity_index: int,
    handle: str,
    tolerance: float,
) -> int:
    for index, node in enumerate(nodes):
        if _distance(point, node["point"]) <= tolerance:
            node["occurrences"].append(
                {
                    "entity_index": entity_index,
                    "handle": handle,
                    "point": point,
                }
            )
            return index
    nodes.append(
        {
            "point": point,
            "occurrences": [
                {
                    "entity_index": entity_index,
                    "handle": handle,
                    "point": point,
                }
            ],
        }
    )
    return len(nodes) - 1


def _entity_components(
    entity_nodes: list[tuple[int, int]],
) -> list[set[int]]:
    node_entities: dict[int, set[int]] = {}
    for entity_index, node_indexes in enumerate(entity_nodes):
        for node_index in node_indexes:
            node_entities.setdefault(node_index, set()).add(entity_index)

    remaining = set(range(len(entity_nodes)))
    components = []
    while remaining:
        seed = remaining.pop()
        component = {seed}
        stack = [seed]
        while stack:
            entity_index = stack.pop()
            neighbours = set()
            for node_index in entity_nodes[entity_index]:
                neighbours.update(node_entities[node_index])
            new_neighbours = neighbours & remaining
            remaining.difference_update(new_neighbours)
            component.update(new_neighbours)
            stack.extend(new_neighbours)
        components.append(component)
    return components


def _entity_endpoints(entity: Any) -> tuple[tuple[float, float], tuple[float, float]]:
    if entity.dxftype() == "LINE":
        return (
            (float(entity.dxf.start.x), float(entity.dxf.start.y)),
            (float(entity.dxf.end.x), float(entity.dxf.end.y)),
        )
    return (
        (float(entity.start_point.x), float(entity.start_point.y)),
        (float(entity.end_point.x), float(entity.end_point.y)),
    )


def _maximum_point_gap(points: list[tuple[float, float]]) -> float:
    return max(
        (
            _distance(left, right)
            for index, left in enumerate(points)
            for right in points[index + 1 :]
        ),
        default=0.0,
    )


def _distance(
    left: tuple[float, float],
    right: tuple[float, float],
) -> float:
    return hypot(left[0] - right[0], left[1] - right[1])


def _rounded_point(point: tuple[float, float]) -> list[float]:
    return [round(point[0], 6), round(point[1], 6)]

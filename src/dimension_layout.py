from __future__ import annotations

from dataclasses import dataclass
from math import atan2, degrees
from typing import Any

from ezdxf import bbox
from ezdxf.math import Vec3


# A little air between neighbouring annotations; drawings are read at plot
# scale, so boxes that merely touch still look crowded.
TEXT_OVERLAP_MARGIN = 1.2
MAX_LAYOUT_MOVES = 40
MAX_LAYOUT_SHIFT = 24.0


@dataclass(frozen=True)
class DimensionText:
    handle: str
    measurement: float | None
    text: str
    bounds: tuple[float, float, float, float]
    axis: str | None
    movable: bool

    def shifted(self, delta: float) -> tuple[float, float, float, float]:
        left, bottom, right, top = self.bounds
        if self.axis == "x":
            return (left + delta, bottom, right + delta, top)
        return (left, bottom + delta, right, top + delta)


def _dimension_text(doc: Any, dimension: Any) -> str:
    name = dimension.dxf.get("geometry")
    if not name or name not in doc.blocks:
        return ""
    for entity in doc.blocks[name]:
        if entity.dxftype() == "TEXT":
            return str(entity.dxf.text or "")
        if entity.dxftype() == "MTEXT":
            return str(entity.text or "")
    return ""


def _text_bounds(doc: Any, dimension: Any) -> tuple[float, float, float, float] | None:
    name = dimension.dxf.get("geometry")
    if not name or name not in doc.blocks:
        return None
    boxes = []
    for entity in doc.blocks[name]:
        if entity.dxftype() not in {"TEXT", "MTEXT"}:
            continue
        text = (
            str(entity.dxf.text or "")
            if entity.dxftype() == "TEXT"
            else str(entity.text or "")
        )
        if not text.strip():
            continue
        extent = bbox.extents([entity])
        if extent.has_data:
            boxes.append(
                (
                    float(extent.extmin.x),
                    float(extent.extmin.y),
                    float(extent.extmax.x),
                    float(extent.extmax.y),
                )
            )
    if not boxes:
        return None
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _movement_axis(dimension: Any) -> str | None:
    """Return the axis perpendicular to the dimension line.

    Only linear dimensions are safe to translate: group 10 locates their
    dimension line, while defpoint2/defpoint3 stay on the measured geometry.
    Radius, diameter and angular dimensions use group 10 as a geometry anchor.
    """
    dimtype = int(dimension.dxf.dimtype) & 15
    if dimtype not in {0, 1} or not dimension.dxf.hasattr("defpoint"):
        return None
    try:
        angle = float(dimension.dxf.angle)
    except (AttributeError, ValueError):
        angle = 0.0
        if dimension.dxf.hasattr("defpoint2") and dimension.dxf.hasattr(
            "defpoint3"
        ):
            point_2 = dimension.dxf.defpoint2
            point_3 = dimension.dxf.defpoint3
            angle = degrees(
                atan2(
                    float(point_3.y) - float(point_2.y),
                    float(point_3.x) - float(point_2.x),
                )
            )
    angle %= 180.0
    return "x" if 45.0 < angle < 135.0 else "y"


def collect_dimension_texts(doc: Any) -> list[DimensionText]:
    items = []
    for dimension in doc.modelspace().query("DIMENSION"):
        bounds = _text_bounds(doc, dimension)
        if bounds is None:
            continue
        try:
            measurement = float(dimension.get_measurement())
        except Exception:
            measurement = None
        axis = _movement_axis(dimension)
        items.append(
            DimensionText(
                handle=str(dimension.dxf.handle),
                measurement=measurement,
                text=_dimension_text(doc, dimension),
                bounds=bounds,
                axis=axis,
                movable=axis is not None,
            )
        )
    return items


def _overlaps(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
    margin: float,
) -> bool:
    """True when two text boxes are closer than ``margin`` on both axes."""
    return (
        first[0] < second[2] + margin
        and second[0] < first[2] + margin
        and first[1] < second[3] + margin
        and second[1] < first[3] + margin
    )


def find_dimension_text_overlaps(
    doc: Any,
    margin: float = TEXT_OVERLAP_MARGIN,
) -> list[dict[str, Any]]:
    items = collect_dimension_texts(doc)
    overlaps = []
    for index, first in enumerate(items):
        for second in items[index + 1 :]:
            if not _overlaps(first.bounds, second.bounds, margin):
                continue
            overlaps.append(
                {
                    "first_handle": first.handle,
                    "first_text": first.text,
                    "first_measurement": first.measurement,
                    "second_handle": second.handle,
                    "second_text": second.text,
                    "second_measurement": second.measurement,
                }
            )
    return overlaps


def _shift_toward(
    item: DimensionText,
    other: tuple[float, float, float, float],
    direction: int,
    margin: float,
) -> float | None:
    """Smallest signed shift that moves ``item`` clear of ``other``."""
    if item.axis == "x":
        if direction > 0:
            delta = other[2] + margin - item.bounds[0]
        else:
            delta = other[0] - margin - item.bounds[2]
    elif item.axis == "y":
        if direction > 0:
            delta = other[3] + margin - item.bounds[1]
        else:
            delta = other[1] - margin - item.bounds[3]
    else:
        return None
    if delta * direction <= 0.0:
        return None
    return delta


def _best_move(
    overlaps: list[tuple[DimensionText, DimensionText]],
    items: list[DimensionText],
    margin: float,
) -> tuple[DimensionText, float] | None:
    best: tuple[float, DimensionText, float] | None = None
    for first, second in overlaps:
        for item, partner in ((first, second), (second, first)):
            if not item.movable or item.axis is None:
                continue
            for direction in (1, -1):
                required = _shift_toward(item, partner.bounds, direction, margin)
                if required is None:
                    continue
                for extra in (0.0, 1.0, 2.0, 4.0):
                    delta = required + direction * extra
                    if abs(delta) > MAX_LAYOUT_SHIFT:
                        continue
                    moved = item.shifted(delta)
                    if any(
                        other is not item
                        and _overlaps(moved, other.bounds, margin)
                        for other in items
                    ):
                        continue
                    # Prefer the smaller move; when two dimensions can both
                    # clear the collision by the same amount, move the larger
                    # (usually the fixed datum) rather than a small parameter.
                    measurement = item.measurement or 0.0
                    score = abs(delta) - 0.01 * min(measurement, 100.0)
                    if best is None or score < best[0]:
                        best = (score, item, delta)
                    break
    if best is None:
        return None
    return best[1], best[2]


def _capture_texts(doc: Any, dimension: Any) -> list[tuple[str, str]]:
    name = dimension.dxf.get("geometry")
    if not name or name not in doc.blocks:
        return []
    payload = []
    for entity in doc.blocks[name]:
        if entity.dxftype() == "TEXT":
            payload.append(("TEXT", str(entity.dxf.text or "")))
        elif entity.dxftype() == "MTEXT":
            payload.append(("MTEXT", str(entity.text or "")))
    return payload


def _restore_texts(doc: Any, dimension: Any, payload: list[tuple[str, str]]) -> None:
    name = dimension.dxf.get("geometry")
    if not name or name not in doc.blocks or not payload:
        return
    entities = [
        entity
        for entity in doc.blocks[name]
        if entity.dxftype() in {"TEXT", "MTEXT"}
    ]
    for (kind, text), entity in zip(payload, entities):
        if entity.dxftype() != kind:
            continue
        if kind == "TEXT":
            entity.dxf.text = text
        else:
            entity.text = text


def _translate_dimension(doc: Any, handle: str, delta: float, axis: str) -> bool:
    dimension = doc.modelspace().query(f'DIMENSION[handle=="{handle}"]')
    if not dimension:
        return False
    dimension = dimension[0]
    if not dimension.dxf.hasattr("defpoint"):
        return False
    text_payload = _capture_texts(doc, dimension)
    point = dimension.dxf.defpoint
    if axis == "x":
        dimension.dxf.defpoint = Vec3(point.x + delta, point.y, point.z)
    else:
        dimension.dxf.defpoint = Vec3(point.x, point.y + delta, point.z)
    try:
        dimension.render()
    except Exception:
        # Leave the drawing unchanged when a template dimension cannot be
        # re-rendered; the overlap audit will keep release blocked.
        dimension.dxf.defpoint = point
        return False
    _restore_texts(doc, dimension, text_payload)
    return True


def resolve_dimension_text_overlaps(
    doc: Any,
    margin: float = TEXT_OVERLAP_MARGIN,
    max_moves: int = MAX_LAYOUT_MOVES,
) -> dict[str, Any]:
    """Offset colliding dimension lines until annotation text is readable.

    Linear dimension lines are translated along the axis perpendicular to their
    own direction.  Their extension points are left untouched, so measurements
    and definition-point binding stay valid; only the annotation offset moves.
    """
    initial = find_dimension_text_overlaps(doc, margin)
    initial_count = len(initial)
    moves = []
    for _ in range(max_moves):
        items = collect_dimension_texts(doc)
        by_handle = {item.handle: item for item in items}
        overlaps = []
        for index, first in enumerate(items):
            for second in items[index + 1 :]:
                if _overlaps(first.bounds, second.bounds, margin):
                    overlaps.append((first, second))
        if not overlaps:
            break
        choice = _best_move(overlaps, items, margin)
        if choice is None:
            break
        item, delta = choice
        if not _translate_dimension(doc, item.handle, delta, item.axis or "y"):
            break
        updated = by_handle.get(item.handle)
        moves.append(
            {
                "handle": item.handle,
                "text": item.text,
                "axis": item.axis,
                "delta": round(delta, 6),
                "before": list(item.bounds),
                "after": list(updated.shifted(delta)) if updated else None,
            }
        )
    remaining = find_dimension_text_overlaps(doc, margin)
    return {
        "margin": margin,
        "initial_overlap_count": initial_count,
        "moves": moves,
        "remaining_overlaps": remaining,
        "release_allowed": not remaining,
    }

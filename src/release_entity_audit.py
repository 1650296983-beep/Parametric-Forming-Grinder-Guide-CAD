from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .global_rules import DUPLICATE_ENTITY_TOLERANCE


PARAMETRIC_RELEASE_LAYERS = {
    "PARAM_SLOT",
    "SECTION_CENTER",
    "SIDE_CAVITY",
    "SIDE_DERIVED",
    "SIDE_DERIVED_RELEASE",
    "SIDE_CENTER",
}


def build_parametric_duplicate_audit(
    dxf_path: str | Path,
) -> dict[str, Any]:
    import ezdxf

    doc = ezdxf.readfile(dxf_path)
    return build_modelspace_parametric_duplicate_audit(doc.modelspace())


def build_modelspace_parametric_duplicate_audit(
    modelspace: Any,
) -> dict[str, Any]:
    groups: dict[tuple[Any, ...], list[str]] = defaultdict(list)
    audited_count = 0
    for entity in modelspace:
        if entity.dxf.layer not in PARAMETRIC_RELEASE_LAYERS:
            continue
        key = _entity_key(entity)
        if key is None:
            continue
        audited_count += 1
        groups[key].append(str(entity.dxf.handle))

    duplicates = [
        {"entity_key": list(key), "handles": handles}
        for key, handles in groups.items()
        if len(handles) > 1
    ]
    return {
        "audited_entity_count": audited_count,
        "duplicate_groups": duplicates,
        "release_allowed": not duplicates,
    }


def _entity_key(entity: Any) -> tuple[Any, ...] | None:
    scale = 1.0 / DUPLICATE_ENTITY_TOLERANCE

    def q(value: float) -> int:
        return round(float(value) * scale)

    entity_type = entity.dxftype()
    layer = str(entity.dxf.layer)
    if entity_type == "LINE":
        start = (q(entity.dxf.start.x), q(entity.dxf.start.y))
        end = (q(entity.dxf.end.x), q(entity.dxf.end.y))
        return (layer, entity_type, *sorted((start, end)))
    if entity_type == "ARC":
        return (
            layer,
            entity_type,
            q(entity.dxf.center.x),
            q(entity.dxf.center.y),
            q(entity.dxf.radius),
            q(float(entity.dxf.start_angle) % 360.0),
            q(float(entity.dxf.end_angle) % 360.0),
        )
    if entity_type == "CIRCLE":
        return (
            layer,
            entity_type,
            q(entity.dxf.center.x),
            q(entity.dxf.center.y),
            q(entity.dxf.radius),
        )
    return None

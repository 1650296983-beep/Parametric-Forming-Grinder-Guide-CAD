from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_DOUBLE_GUIDE_TEMPLATE_DIR = Path("/Users/wrd/Desktop/各种机台干净模板")


@dataclass(frozen=True)
class GuideSection:
    section_id: str
    slot_geometry: dict[str, Any]
    slot_width: float | None
    slot_depth: float | None
    relief_geometry: dict[str, Any]
    dimension_entities: list[dict[str, Any]]
    centerline_entities: list[dict[str, Any]]
    bounding_box: dict[str, float]


@dataclass(frozen=True)
class MachineTemplateConfig:
    machine_id: str
    machine_name: str
    guide_length: float
    wheel_positions: tuple[str, ...]
    guide_sections: int
    guide_section_1: GuideSection
    guide_section_2: GuideSection
    dual_product_mode: bool = False


@dataclass(frozen=True)
class DoubleGuideTemplateSpec:
    machine_id: str
    machine_name: str
    guide_length: float
    wheel_positions: tuple[str, ...]
    guide_sections: int
    filename: str


DOUBLE_GUIDE_TEMPLATE_SPECS: tuple[DoubleGuideTemplateSpec, ...] = (
    DoubleGuideTemplateSpec(
        machine_id="triple_double_down_up_up",
        machine_name="三头机双导轨（下上上）",
        guide_length=590.0,
        wheel_positions=("下", "上", "上"),
        guide_sections=2,
        filename="6）R23.57XR21.53X6.56X13.73X2.04（R23.57X6.6X2.4)三机头双导轨砂轮下、上、上.dxf",
    ),
    DoubleGuideTemplateSpec(
        machine_id="triple_double_up_up_up",
        machine_name="三头机双导轨（上上上）",
        guide_length=590.0,
        wheel_positions=("上", "上", "上"),
        guide_sections=2,
        filename="7）3.3X1.9X0.94X1.01（3.33X2)三机头双导轨(砂轮上、上、上).dxf",
    ),
)


def generate_double_guide_template_reports(
    output_dir: str | Path = ".",
    template_dir: str | Path = DEFAULT_DOUBLE_GUIDE_TEMPLATE_DIR,
) -> dict[str, Path]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    reports = build_double_guide_template_reports(Path(template_dir))
    paths = {
        "template_audit_report": output_path / "template_audit_report.json",
        "fixed_template_geometry": output_path / "fixed_template_geometry.json",
        "guide_section_analysis": output_path / "guide_section_analysis.json",
    }
    for key, path in paths.items():
        _write_json(path, reports[key])
    return paths


def build_double_guide_template_reports(
    template_dir: Path = DEFAULT_DOUBLE_GUIDE_TEMPLATE_DIR,
) -> dict[str, dict[str, Any]]:
    audits = [_audit_one_template(spec, template_dir / spec.filename) for spec in DOUBLE_GUIDE_TEMPLATE_SPECS]
    generated_at = datetime.now().isoformat(timespec="seconds")
    return {
        "template_audit_report": {
            "report_name": "template_audit_report",
            "generated_at": generated_at,
            "scope": "read-only DXF template audit; no template edits, slot rebuild, release DXF, or machining drawing generation",
            "template_directory": str(template_dir),
            "templates": [audit["template_audit"] for audit in audits],
        },
        "fixed_template_geometry": {
            "report_name": "fixed_template_geometry",
            "generated_at": generated_at,
            "scope": "fixed geometry recognition from source templates",
            "templates": [audit["fixed_template_geometry"] for audit in audits],
        },
        "guide_section_analysis": {
            "report_name": "guide_section_analysis",
            "generated_at": generated_at,
            "scope": "guide_sections=2 architecture recognition; both sections are constrained to one shared product parameter set",
            "data_structure": _data_structure_payload(),
            "templates": [audit["guide_section_analysis"] for audit in audits],
        },
    }


def _audit_one_template(spec: DoubleGuideTemplateSpec, template_path: Path) -> dict[str, dict[str, Any]]:
    try:
        import ezdxf
    except ImportError as exc:
        raise RuntimeError("ezdxf is required for template auditing.") from exc

    if not template_path.exists():
        raise FileNotFoundError(f"Double guide template not found: {template_path}")

    doc = ezdxf.readfile(template_path)
    modelspace = doc.modelspace()
    entities = list(modelspace)
    entity_counts = Counter(entity.dxftype() for entity in entities)
    layer_counts = Counter(entity.dxf.layer for entity in entities)
    span_groups = _fixed_span_groups(entities)
    assembly_group = _assembly_span_group(span_groups, spec.guide_length)
    local_groups = _local_section_span_groups(span_groups)
    sections = _build_guide_sections(entities, local_groups, spec.wheel_positions)
    spacing = _guide_section_spacing(sections)
    machine_template_config = MachineTemplateConfig(
        machine_id=spec.machine_id,
        machine_name=spec.machine_name,
        guide_length=spec.guide_length,
        wheel_positions=spec.wheel_positions,
        guide_sections=spec.guide_sections,
        guide_section_1=sections[0],
        guide_section_2=sections[1],
    )

    arc_summary = _arc_radius_summary(entities)
    dimension_summary = _dimension_summary(entities)
    text_summary = _text_summary(entities)
    template_extents = _template_extents(entities)

    template_audit = {
        "machine_id": spec.machine_id,
        "machine_name": spec.machine_name,
        "guide_length": spec.guide_length,
        "guide_sections": spec.guide_sections,
        "wheel_positions": list(spec.wheel_positions),
        "template_file": str(template_path),
        "entity_counts": {
            "total_modelspace_entities": len(entities),
            **dict(sorted(entity_counts.items())),
        },
        "layers": _layer_summary(doc, layer_counts),
        "template_extents": template_extents,
        "arc_radius_summary": arc_summary,
        "dimension_summary": dimension_summary,
        "text_summary": text_summary,
            "warnings": _template_warnings(entity_counts, text_summary),
    }
    fixed_template_geometry = {
        "machine_id": spec.machine_id,
        "machine_name": spec.machine_name,
        "guide_length": {
            "expected": spec.guide_length,
            "measured_from_dimension_chain": round(assembly_group["total"], 3),
            "matches_expected": abs(assembly_group["total"] - spec.guide_length) <= 0.001,
        },
        "side_fixed_spans": [item["measurement"] for item in assembly_group["dimensions"]],
        "guide_section_spans": [
            {
                "section_id": "section_1",
                "x_min": local_groups[0]["x_min"],
                "x_max": local_groups[0]["x_max"],
                "length": local_groups[0]["total"],
                "fixed_spans": [item["measurement"] for item in local_groups[0]["dimensions"]],
            },
            {
                "section_id": "section_2",
                "x_min": local_groups[1]["x_min"],
                "x_max": local_groups[1]["x_max"],
                "length": local_groups[1]["total"],
                "fixed_spans": [item["measurement"] for item in local_groups[1]["dimensions"]],
            },
        ],
        "assembly_view": assembly_group,
        "guide_section_spacing": spacing,
        "r80_wheel_notches": _r80_arc_payloads(entities),
        "fixed_hole_positions": _circle_payloads(entities),
        "fixed_fillets": _fixed_fillet_payloads(entities),
        "fixed_centerlines": _centerline_payloads(entities),
        "fixed_dimensions": dimension_summary["dimensions"],
        "fixed_text": text_summary["texts"],
        "proxy_entities": {
            "count": int(entity_counts.get("ACAD_PROXY_ENTITY", 0)),
            "note": "ACAD_PROXY_ENTITY objects are counted but not interpreted as parametric geometry.",
        },
        "future_parametric_regions": _future_parametric_regions(sections),
    }
    guide_section_analysis = {
        "machine_id": spec.machine_id,
        "machine_name": spec.machine_name,
        "guide_length": spec.guide_length,
        "wheel_positions": list(spec.wheel_positions),
        "guide_sections": spec.guide_sections,
        "dual_product_mode": False,
        "dual_section_mode": "synchronized",
        "shared_product_parameter_policy": {
            "R_form": "shared",
            "slot_width": "shared",
            "guide_thickness": "shared",
            "relief": "shared",
            "slot_depth": "shared",
            "dual_product_mode_allowed": False,
        },
        "shared_parameters": ["R_form", "slot_width", "guide_thickness", "relief", "slot_depth"],
        "machine_template_config": asdict(machine_template_config),
        "section_relationship": _section_relationship(sections),
        "guide_section_spacing": spacing,
        "section_1_center": spacing["cross_section_centerline_midpoints"]["section_1"],
        "section_2_center": spacing["cross_section_centerline_midpoints"]["section_2"],
        "is_symmetric": _section_relationship(sections)["fully_symmetric"],
        "sections": [asdict(section) for section in sections],
    }
    return {
        "template_audit": template_audit,
        "fixed_template_geometry": fixed_template_geometry,
        "guide_section_analysis": guide_section_analysis,
    }


def _fixed_span_groups(entities: list[Any]) -> list[dict[str, Any]]:
    dimensions: list[dict[str, Any]] = []
    for entity in entities:
        if entity.dxftype() != "DIMENSION":
            continue
        if not (entity.dxf.hasattr("defpoint2") and entity.dxf.hasattr("defpoint3")):
            continue
        measurement = float(entity.get_measurement())
        if round(measurement, 3) not in {99.0, 90.0, 180.0, 131.0}:
            continue
        points = [
            entity.dxf.get(attr)
            for attr in ("defpoint", "defpoint2", "defpoint3", "text_midpoint")
            if entity.dxf.hasattr(attr)
        ]
        x1, x2 = sorted((float(entity.dxf.defpoint2.x), float(entity.dxf.defpoint3.x)))
        center_y = sum(float(point.y) for point in points) / len(points)
        dimensions.append(
            {
                "handle": entity.dxf.handle,
                "measurement": round(measurement, 3),
                "x_min": round(x1, 3),
                "x_max": round(x2, 3),
                "center_y": round(center_y, 3),
            }
        )
    groups: list[list[dict[str, Any]]] = []
    for dimension in sorted(dimensions, key=lambda item: item["center_y"], reverse=True):
        for group in groups:
            if abs(group[0]["center_y"] - dimension["center_y"]) < 30.0:
                group.append(dimension)
                break
        else:
            groups.append([dimension])
    payload = []
    for group in groups:
        ordered = sorted(group, key=lambda item: item["x_min"])
        payload.append(
            {
                "center_y": round(sum(item["center_y"] for item in ordered) / len(ordered), 3),
                "x_min": round(min(item["x_min"] for item in ordered), 3),
                "x_max": round(max(item["x_max"] for item in ordered), 3),
                "total": round(sum(item["measurement"] for item in ordered), 3),
                "dimensions": ordered,
            }
        )
    return sorted(payload, key=lambda item: item["center_y"], reverse=True)


def _assembly_span_group(groups: list[dict[str, Any]], guide_length: float) -> dict[str, Any]:
    for group in groups:
        if abs(group["total"] - guide_length) <= 0.001:
            return group
    raise ValueError(f"Cannot identify {guide_length:g} mm assembly dimension chain.")


def _local_section_span_groups(groups: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    local_groups = [group for group in groups if abs(group["total"] - 590.0) > 0.001]
    section_1 = next((group for group in local_groups if abs(group["total"] - 189.0) <= 0.001), None)
    section_2 = next((group for group in local_groups if abs(group["total"] - 401.0) <= 0.001), None)
    if section_1 is None or section_2 is None:
        raise ValueError("Cannot identify local 189 mm and 401 mm guide-section dimension chains.")
    return section_1, section_2


def _build_guide_sections(
    entities: list[Any],
    local_groups: tuple[dict[str, Any], dict[str, Any]],
    wheel_positions: tuple[str, ...],
) -> tuple[GuideSection, GuideSection]:
    cross_centerlines = _cross_section_centerlines(entities)
    side_centerlines = _side_centerline_groups(entities, local_groups)
    section_specs = (
        {
            "section_id": "section_1",
            "cross_centerline": cross_centerlines[0],
            "span_group": local_groups[0],
            "side_centerlines": side_centerlines[0],
            "wheel_positions": wheel_positions[:1],
        },
        {
            "section_id": "section_2",
            "cross_centerline": cross_centerlines[1],
            "span_group": local_groups[1],
            "side_centerlines": side_centerlines[1],
            "wheel_positions": wheel_positions[1:],
        },
    )
    return tuple(_guide_section(entities, spec) for spec in section_specs)  # type: ignore[return-value]


def _guide_section(entities: list[Any], section_spec: dict[str, Any]) -> GuideSection:
    cross_centerline = section_spec["cross_centerline"]
    span_group = section_spec["span_group"]
    side_centerlines = section_spec["side_centerlines"]
    wheel_positions = section_spec["wheel_positions"]
    section_entities = [
        entity
        for entity in entities
        if _is_cross_entity_in_section(entity, cross_centerline)
        or _is_side_entity_in_section(entity, span_group)
    ]
    slot_entities = [
        entity
        for entity in section_entities
        if entity.dxftype() in {"LINE", "ARC", "LWPOLYLINE"}
        and entity.dxf.layer in {"0", "2细线层", "3中心线层"}
    ]
    relief_arcs = _section_relief_arcs(entities, cross_centerline, side_centerlines, wheel_positions)
    dimensions = [entity for entity in section_entities if entity.dxftype() == "DIMENSION"]
    centerlines = [
        cross_centerline,
        *side_centerlines,
    ]
    boxes = [_bbox(entity) for entity in [*section_entities, *relief_arcs] if _bbox(entity) is not None]
    return GuideSection(
        section_id=section_spec["section_id"],
        slot_geometry={
            "entity_count": len(slot_entities),
            "line_count": sum(1 for entity in slot_entities if entity.dxftype() == "LINE"),
            "arc_count": sum(1 for entity in slot_entities if entity.dxftype() == "ARC"),
            "lwpolyline_count": sum(1 for entity in slot_entities if entity.dxftype() == "LWPOLYLINE"),
            "entities": [_compact_entity_payload(entity) for entity in slot_entities],
            "note": "Template geometry only. Future product slot geometry must be rebuilt parametrically.",
        },
        slot_width=None,
        slot_depth=None,
        relief_geometry={
            "independent_relief_detected": bool(relief_arcs),
            "r80_arc_count": sum(
                1
                for entity in relief_arcs
                if entity.dxftype() == "ARC" and abs(float(entity.dxf.radius) - 80.0) <= 0.001
            ),
            "small_relief_arc_count": sum(
                1 for entity in relief_arcs if entity.dxftype() == "ARC" and float(entity.dxf.radius) < 1.0
            ),
            "entities": [_arc_payload(entity) for entity in relief_arcs],
        },
        dimension_entities=[_dimension_payload(entity) for entity in dimensions],
        centerline_entities=[_line_payload(entity) for entity in centerlines],
        bounding_box={
            "min_x": round(min((box["min_x"] for box in boxes), default=0.0), 3),
            "max_x": round(max((box["max_x"] for box in boxes), default=0.0), 3),
            "min_y": round(min((box["min_y"] for box in boxes), default=0.0), 3),
            "max_y": round(max((box["max_y"] for box in boxes), default=0.0), 3),
        },
    )


def _cross_section_centerlines(entities: list[Any]) -> tuple[Any, Any]:
    centerlines = [
        entity
        for entity in entities
        if entity.dxftype() == "LINE"
        and entity.dxf.layer == "0"
        and abs(float(entity.dxf.start.x) - float(entity.dxf.end.x)) <= 0.001
        and 3200.0 <= float(entity.dxf.start.x) <= 3300.0
        and float(entity.dxf.start.distance(entity.dxf.end)) > 30.0
    ]
    centerlines = sorted(centerlines, key=lambda entity: _entity_center(entity)[1], reverse=True)
    if len(centerlines) < 2:
        raise ValueError("Cannot identify two cross-section centerlines.")
    return centerlines[0], centerlines[1]


def _side_centerline_groups(
    entities: list[Any],
    local_groups: tuple[dict[str, Any], dict[str, Any]],
) -> tuple[list[Any], list[Any]]:
    groups = []
    for span_group in local_groups:
        centerlines = [
            entity
            for entity in entities
            if entity.dxftype() == "LINE"
            and entity.dxf.layer == "3中心线层"
            and span_group["x_min"] - 0.001 <= float(entity.dxf.start.x) <= span_group["x_max"] + 0.001
            and abs(_entity_center(entity)[1] - span_group["center_y"]) < 45.0
        ]
        groups.append(sorted(centerlines, key=lambda entity: float(entity.dxf.start.x)))
    return groups[0], groups[1]


def _is_cross_entity_in_section(entity: Any, cross_centerline: Any) -> bool:
    bbox = _bbox(entity)
    if bbox is None:
        return False
    center_x, center_y = _bbox_center(bbox)
    _, cross_y = _entity_center(cross_centerline)
    return 3180.0 <= center_x <= 3290.0 and abs(center_y - cross_y) <= 48.0


def _is_side_entity_in_section(entity: Any, span_group: dict[str, Any]) -> bool:
    bbox = _bbox(entity)
    if bbox is None:
        return False
    center_x, center_y = _bbox_center(bbox)
    return (
        span_group["x_min"] - 0.001 <= center_x <= span_group["x_max"] + 0.001
        and abs(center_y - span_group["center_y"]) <= 70.0
    )


def _section_relief_arcs(
    entities: list[Any],
    cross_centerline: Any,
    side_centerlines: list[Any],
    wheel_positions: tuple[str, ...],
) -> list[Any]:
    _, cross_y = _entity_center(cross_centerline)
    small_relief_arcs = [
        entity
        for entity in entities
        if entity.dxftype() == "ARC"
        and float(entity.dxf.radius) < 1.0
        and abs(_entity_center(entity)[1] - cross_y) <= 48.0
        and 3180.0 <= _entity_center(entity)[0] <= 3290.0
    ]
    r80_arcs = [entity for entity in entities if entity.dxftype() == "ARC" and abs(float(entity.dxf.radius) - 80.0) <= 0.001]
    selected_r80 = []
    for centerline, wheel_position in zip(side_centerlines, wheel_positions):
        cx, cy = _entity_center(centerline)
        same_x = [arc for arc in r80_arcs if abs(float(arc.dxf.center.x) - cx) <= 0.01]
        if wheel_position == "上":
            candidates = [arc for arc in same_x if float(arc.dxf.center.y) > cy]
        else:
            candidates = [arc for arc in same_x if float(arc.dxf.center.y) < cy]
        if candidates:
            selected_r80.append(min(candidates, key=lambda arc: abs(float(arc.dxf.center.y) - cy)))
    return [*small_relief_arcs, *selected_r80]


def _guide_section_spacing(sections: tuple[GuideSection, GuideSection]) -> dict[str, Any]:
    section_1_centers = [line["start"][0] for line in sections[0].centerline_entities]
    section_2_centers = [line["start"][0] for line in sections[1].centerline_entities]
    section_1_side_centers = section_1_centers[1:]
    section_2_side_centers = section_2_centers[1:]
    section_1_primary = section_1_side_centers[0] if section_1_side_centers else None
    section_2_primary = section_2_side_centers[0] if section_2_side_centers else None
    section_2_group_center = (
        round(sum(section_2_centers) / len(section_2_centers), 3) if section_2_centers else None
    )
    bbox_1_center = (sections[0].bounding_box["min_x"] + sections[0].bounding_box["max_x"]) / 2.0
    bbox_2_center = (sections[1].bounding_box["min_x"] + sections[1].bounding_box["max_x"]) / 2.0
    cross_1 = sections[0].centerline_entities[0]
    cross_2 = sections[1].centerline_entities[0]
    cross_1_mid = [
        round((cross_1["start"][0] + cross_1["end"][0]) / 2.0, 3),
        round((cross_1["start"][1] + cross_1["end"][1]) / 2.0, 3),
    ]
    cross_2_mid = [
        round((cross_2["start"][0] + cross_2["end"][0]) / 2.0, 3),
        round((cross_2["start"][1] + cross_2["end"][1]) / 2.0, 3),
    ]
    return {
        "cross_section_centerline_midpoints": {
            "section_1": cross_1_mid,
            "section_2": cross_2_mid,
        },
        "cross_section_centerline_to_centerline": round(
            ((cross_2_mid[0] - cross_1_mid[0]) ** 2 + (cross_2_mid[1] - cross_1_mid[1]) ** 2) ** 0.5,
            3,
        ),
        "section_1_centerline_x_values": section_1_centers,
        "section_2_centerline_x_values": section_2_centers,
        "section_1_side_centerline_x_values": section_1_side_centers,
        "section_2_side_centerline_x_values": section_2_side_centers,
        "primary_centerline_to_primary_centerline": (
            round(section_2_primary - section_1_primary, 3)
            if section_1_primary is not None and section_2_primary is not None
            else None
        ),
        "section_1_to_section_2_centerline_group_center": (
            round(section_2_group_center - section_1_primary, 3)
            if section_1_primary is not None and section_2_group_center is not None
            else None
        ),
        "bbox_center_to_bbox_center": round(bbox_2_center - bbox_1_center, 3),
        "note": "cross_section_centerline_to_centerline is the rail-section spacing in the template; side-view spacing is also retained for fixed layout recognition.",
    }


def _section_relationship(sections: tuple[GuideSection, GuideSection]) -> dict[str, Any]:
    lengths = [
        round(section.bounding_box["max_x"] - section.bounding_box["min_x"], 3)
        for section in sections
    ]
    centerline_counts = [len(section.centerline_entities) for section in sections]
    r80_counts = [section.relief_geometry["r80_arc_count"] for section in sections]
    return {
        "composed_of_two_sections": True,
        "fully_symmetric": lengths[0] == lengths[1]
        and centerline_counts[0] == centerline_counts[1]
        and r80_counts[0] == r80_counts[1],
        "section_lengths": lengths,
        "centerline_counts": centerline_counts,
        "r80_relief_counts": r80_counts,
        "dimension_chain": "shared_continuous_590_chain_with_local_section_dimensions",
    }


def _future_parametric_regions(sections: tuple[GuideSection, GuideSection]) -> list[dict[str, Any]]:
    regions = []
    for section in sections:
        regions.append(
            {
                "section_id": section.section_id,
                "bounding_box": section.bounding_box,
                "future_parametric_entities": {
                    "slot_geometry": "rebuild from shared product parameters",
                    "slot_width": "shared across section_1 and section_2",
                    "slot_depth_or_projected_height": "shared rule, recomputed per machine style",
                    "relief_geometry": "same relief parameter set; placed at each section wheel notch",
                    "dimension_entities": "rebuild/update from generated geometry; do not keep stale product dimensions",
                },
            }
        )
    return regions


def _template_warnings(entity_counts: Counter[str], text_summary: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if entity_counts.get("ACAD_PROXY_ENTITY", 0):
        warnings.append("Template contains ACAD_PROXY_ENTITY; counted but not geometrically interpreted.")
    if text_summary["suspected_product_texts"]:
        warnings.append("Template contains suspected product-size MTEXT remnants; future release cleanup must remove them.")
    return warnings


def _arc_radius_summary(entities: list[Any]) -> dict[str, Any]:
    radii = Counter(
        round(float(entity.dxf.radius), 3)
        for entity in entities
        if entity.dxftype() == "ARC"
    )
    return {
        "by_radius": [{"radius": radius, "count": count} for radius, count in sorted(radii.items())],
        "arcs": [_arc_payload(entity) for entity in entities if entity.dxftype() == "ARC"],
    }


def _dimension_summary(entities: list[Any]) -> dict[str, Any]:
    dimensions = [_dimension_payload(entity) for entity in entities if entity.dxftype() == "DIMENSION"]
    measurements = Counter(round(item["measurement"], 3) for item in dimensions)
    return {
        "count": len(dimensions),
        "measurements": [
            {"measurement": measurement, "count": count}
            for measurement, count in sorted(measurements.items())
        ],
        "dimensions": dimensions,
    }


def _text_summary(entities: list[Any]) -> dict[str, Any]:
    texts = [_text_payload(entity) for entity in entities if entity.dxftype() in {"TEXT", "MTEXT"}]
    suspected = [
        text for text in texts if any(marker in text["text"] for marker in ("S:", "JL:", "PL:"))
    ]
    return {
        "count": len(texts),
        "suspected_product_texts": suspected,
        "texts": texts,
    }


def _layer_summary(doc: Any, layer_counts: Counter[str]) -> list[dict[str, Any]]:
    layers = []
    for layer in doc.layers:
        layers.append(
            {
                "name": layer.dxf.name,
                "entity_count": int(layer_counts.get(layer.dxf.name, 0)),
                "color": int(layer.dxf.color),
                "linetype": layer.dxf.linetype,
            }
        )
    return sorted(layers, key=lambda item: (-item["entity_count"], item["name"]))


def _template_extents(entities: list[Any]) -> dict[str, float | None]:
    boxes = [_bbox(entity) for entity in entities]
    boxes = [box for box in boxes if box is not None]
    if not boxes:
        return {"min_x": None, "min_y": None, "max_x": None, "max_y": None}
    return {
        "min_x": round(min(box["min_x"] for box in boxes), 3),
        "min_y": round(min(box["min_y"] for box in boxes), 3),
        "max_x": round(max(box["max_x"] for box in boxes), 3),
        "max_y": round(max(box["max_y"] for box in boxes), 3),
    }


def _r80_arc_payloads(entities: list[Any]) -> list[dict[str, Any]]:
    return [
        _arc_payload(entity)
        for entity in entities
        if entity.dxftype() == "ARC" and abs(float(entity.dxf.radius) - 80.0) <= 0.001
    ]


def _circle_payloads(entities: list[Any]) -> list[dict[str, Any]]:
    return [_circle_payload(entity) for entity in entities if entity.dxftype() == "CIRCLE"]


def _fixed_fillet_payloads(entities: list[Any]) -> list[dict[str, Any]]:
    return []


def _centerline_payloads(entities: list[Any]) -> list[dict[str, Any]]:
    return [
        _line_payload(entity)
        for entity in entities
        if entity.dxftype() == "LINE"
        and entity.dxf.layer == "3中心线层"
    ]


def _compact_entity_payload(entity: Any) -> dict[str, Any]:
    if entity.dxftype() == "LINE":
        return _line_payload(entity)
    if entity.dxftype() == "ARC":
        return _arc_payload(entity)
    return {
        "handle": entity.dxf.handle,
        "type": entity.dxftype(),
        "layer": entity.dxf.layer,
        "bbox": _bbox(entity),
    }


def _line_payload(entity: Any) -> dict[str, Any]:
    return {
        "handle": entity.dxf.handle,
        "type": "LINE",
        "layer": entity.dxf.layer,
        "start": _point(entity.dxf.start),
        "end": _point(entity.dxf.end),
        "length": round(float(entity.dxf.start.distance(entity.dxf.end)), 3),
    }


def _arc_payload(entity: Any) -> dict[str, Any]:
    return {
        "handle": entity.dxf.handle,
        "type": "ARC",
        "layer": entity.dxf.layer,
        "center": _point(entity.dxf.center),
        "radius": round(float(entity.dxf.radius), 3),
        "start_angle": round(float(entity.dxf.start_angle), 3),
        "end_angle": round(float(entity.dxf.end_angle), 3),
    }


def _circle_payload(entity: Any) -> dict[str, Any]:
    return {
        "handle": entity.dxf.handle,
        "type": "CIRCLE",
        "layer": entity.dxf.layer,
        "center": _point(entity.dxf.center),
        "radius": round(float(entity.dxf.radius), 3),
    }


def _dimension_payload(entity: Any) -> dict[str, Any]:
    points = {}
    for attr in ("defpoint", "defpoint2", "defpoint3", "defpoint4", "defpoint5", "text_midpoint"):
        if entity.dxf.hasattr(attr):
            points[attr] = _point(entity.dxf.get(attr))
    return {
        "handle": entity.dxf.handle,
        "type": "DIMENSION",
        "layer": entity.dxf.layer,
        "text": entity.dxf.text,
        "measurement": round(float(entity.get_measurement()), 3),
        "points": points,
    }


def _text_payload(entity: Any) -> dict[str, Any]:
    text = entity.dxf.text if entity.dxftype() == "TEXT" else entity.text
    insert = entity.dxf.insert if entity.dxf.hasattr("insert") else None
    return {
        "handle": entity.dxf.handle,
        "type": entity.dxftype(),
        "layer": entity.dxf.layer,
        "text": str(text)[:200],
        "insert": _point(insert) if insert is not None else None,
    }


def _bbox(entity: Any) -> dict[str, float] | None:
    entity_type = entity.dxftype()
    if entity_type == "LINE":
        xs = [float(entity.dxf.start.x), float(entity.dxf.end.x)]
        ys = [float(entity.dxf.start.y), float(entity.dxf.end.y)]
    elif entity_type == "ARC":
        center = entity.dxf.center
        radius = float(entity.dxf.radius)
        xs = [float(center.x) - radius, float(center.x) + radius]
        ys = [float(center.y) - radius, float(center.y) + radius]
    elif entity_type == "CIRCLE":
        center = entity.dxf.center
        radius = float(entity.dxf.radius)
        xs = [float(center.x) - radius, float(center.x) + radius]
        ys = [float(center.y) - radius, float(center.y) + radius]
    elif entity_type == "DIMENSION":
        points = []
        for attr in ("defpoint", "defpoint2", "defpoint3", "defpoint4", "defpoint5", "text_midpoint"):
            if entity.dxf.hasattr(attr):
                point = entity.dxf.get(attr)
                points.append((float(point.x), float(point.y)))
        if not points:
            return None
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
    elif entity_type in {"TEXT", "MTEXT"} and entity.dxf.hasattr("insert"):
        insert = entity.dxf.insert
        xs = [float(insert.x)]
        ys = [float(insert.y)]
    else:
        return None
    return {
        "min_x": round(min(xs), 3),
        "min_y": round(min(ys), 3),
        "max_x": round(max(xs), 3),
        "max_y": round(max(ys), 3),
    }


def _entity_center(entity: Any) -> tuple[float, float]:
    bbox = _bbox(entity)
    if bbox is None:
        return 0.0, 0.0
    return _bbox_center(bbox)


def _bbox_center(bbox: dict[str, float]) -> tuple[float, float]:
    return (bbox["min_x"] + bbox["max_x"]) / 2.0, (bbox["min_y"] + bbox["max_y"]) / 2.0


def _point(point: Any) -> list[float]:
    return [round(float(point.x), 3), round(float(point.y), 3)]


def _data_structure_payload() -> dict[str, Any]:
    return {
        "GuideSection": {
            "section_id": "str",
            "slot_geometry": "dict",
            "slot_width": "float | None",
            "slot_depth": "float | None",
            "relief_geometry": "dict",
            "dimension_entities": "list[dict]",
            "centerline_entities": "list[dict]",
            "bounding_box": "dict",
        },
        "MachineTemplateConfig": {
            "guide_sections": "int",
            "guide_section_1": "GuideSection",
            "guide_section_2": "GuideSection",
            "dual_product_mode": "False in current phase",
        },
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    import json

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    generate_double_guide_template_reports()

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable


TOLERANCE = 0.01
COMPARISON_TOLERANCE = 0.001


@dataclass(frozen=True)
class ReferenceSectionAudit:
    source_path: str
    sha256: str
    outer_width: float
    outer_height: float
    slot_base_height: float
    center_opening: float
    slot_width: float
    guide_thickness: float
    section_profile: str
    section_arc_radii: tuple[float, ...]
    section_arc_side: str | None
    section_flat_side: str | None
    section_arc_center_side: str | None
    product_radii: tuple[float, ...]
    fixed_dimensions: tuple[float, ...]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["section_arc_radii"] = list(self.section_arc_radii)
        payload["product_radii"] = list(self.product_radii)
        payload["fixed_dimensions"] = list(self.fixed_dimensions)
        return payload


def audit_reference_dxf(path: str | Path) -> ReferenceSectionAudit:
    import ezdxf

    source = Path(path)
    doc = ezdxf.readfile(source)
    modelspace = doc.modelspace()
    frame = _find_section_frame(modelspace.query("LINE"))
    left, right, bottom, top = frame
    dimensions = [
        entity
        for entity in modelspace.query("DIMENSION")
        if _dimension_is_near_section(entity, left, right, bottom, top)
    ]
    measurements = [
        value
        for value in (_measurement(entity) for entity in dimensions)
        if value is not None
    ]
    slot_width = _find_slot_width(dimensions)
    slot_base_height = _find_measurement(measurements, 12.0)
    base_y = bottom + slot_base_height
    guide_thickness = _find_guide_thickness(dimensions, base_y, slot_width)
    center_opening = _find_center_opening(dimensions, top)
    section_arc_radii = tuple(
        sorted(
            {
                round(float(entity.dxf.radius), 6)
                for entity in modelspace.query("ARC")
                if left <= float(entity.dxf.center.x) <= right
                and bottom <= float(entity.dxf.center.y) <= top + 30.0
                and float(entity.dxf.radius) > 1.0
                and float(entity.dxf.radius) < 70.0
            }
        )
    )
    section_arc_side = None
    section_flat_side = None
    section_arc_center_side = None
    if section_arc_radii:
        main_arcs = [
            entity
            for entity in modelspace.query("ARC")
            if left <= float(entity.dxf.center.x) <= right
            and bottom <= float(entity.dxf.center.y) <= top + 30.0
            and abs(float(entity.dxf.radius) - max(section_arc_radii)) <= TOLERANCE
        ]
        if len(main_arcs) != 1:
            raise ValueError(
                "Expected one main guide-section arc, found "
                f"{len(main_arcs)} for radius {max(section_arc_radii):g}."
            )
        cavity_mid_y = base_y + guide_thickness / 2.0
        arc_center_y = float(main_arcs[0].dxf.center.y)
        section_arc_center_side = (
            "upper" if arc_center_y > cavity_mid_y else "lower"
        )
        # A circular boundary lies on the side opposite its circle center.
        section_arc_side = (
            "lower" if section_arc_center_side == "upper" else "upper"
        )
        section_flat_side = (
            "upper" if section_arc_side == "lower" else "lower"
        )
    product_radii = tuple(
        sorted(
            {
                round(float(entity.dxf.radius), 6)
                for entity in modelspace.query("ARC")
                if 1.0 < float(entity.dxf.radius) < 70.0
            }
        )
    )
    fixed_dimensions = tuple(
        sorted(
            {
                round(value, 6)
                for value in (
                    _measurement(entity)
                    for entity in modelspace.query("DIMENSION")
                )
                if value is not None
                and any(abs(value - expected) <= TOLERANCE for expected in (12.0, 27.0, 40.0, 80.0, 99.0, 100.0, 180.0))
            }
        )
    )
    return ReferenceSectionAudit(
        source_path=str(source),
        sha256=_sha256(source),
        outer_width=round(right - left, 6),
        outer_height=round(top - bottom, 6),
        slot_base_height=round(slot_base_height, 6),
        center_opening=round(center_opening, 6),
        slot_width=round(slot_width, 6),
        guide_thickness=round(guide_thickness, 6),
        section_profile=("flat_arc_groove" if section_arc_radii else "rectangular_groove"),
        section_arc_radii=section_arc_radii,
        section_arc_side=section_arc_side,
        section_flat_side=section_flat_side,
        section_arc_center_side=section_arc_center_side,
        product_radii=product_radii,
        fixed_dimensions=fixed_dimensions,
    )


def compare_reference_to_generated(
    reference: ReferenceSectionAudit,
    generated_report: dict[str, Any],
) -> dict[str, Any]:
    process = generated_report["process_parameters"]
    fixed = generated_report["fixed_template_dimensions"]["section"]
    rule = generated_report.get("input_rule") or {}
    generated_slot_width = float(process["slot_width"]["slot_width"])
    generated_thickness = float(process["guide_thickness"]["result"])
    generated_opening = float(fixed["center_opening"])
    generated_profile = str(rule.get("groove_profile", "unknown"))
    generated_arc_radius = rule.get("arc_radius")
    generated_arc_side = rule.get("arc_side")
    generated_flat_side = rule.get("flat_side")
    generated_arc_center_side = rule.get("arc_center_side")
    finished_radii = tuple(float(value) for value in rule.get("finished_radii", ()))
    approved_overrides = {
        str(value) for value in rule.get("approved_reference_overrides", ())
    }
    checks = {
        "outer_width": _comparison(reference.outer_width, float(fixed["outer_width"])),
        "outer_height": _comparison(reference.outer_height, float(fixed.get("outer_height", 27.0))),
        "slot_base_height": _comparison(reference.slot_base_height, float(fixed["slot_base_height"])),
        "slot_width": _comparison(reference.slot_width, generated_slot_width),
        "guide_thickness": _comparison(reference.guide_thickness, generated_thickness),
        "center_opening": _comparison(reference.center_opening, generated_opening),
        "section_profile": {
            "reference": reference.section_profile,
            "generated": generated_profile,
            "status": (
                "MATCH"
                if reference.section_profile == generated_profile
                else "RULE_CONFLICT"
            ),
        },
        "guide_section_arc_radius": _arc_radius_comparison(
            reference.section_arc_radii,
            generated_arc_radius,
        ),
        "section_arc_side": _optional_rule_comparison(
            reference.section_arc_side,
            generated_arc_side,
        ),
        "section_flat_side": _optional_rule_comparison(
            reference.section_flat_side,
            generated_flat_side,
        ),
        "section_arc_center_side": _optional_rule_comparison(
            reference.section_arc_center_side,
            generated_arc_center_side,
        ),
        "product_drawing_radius_evidence": {
            "reference_product_radii": list(reference.product_radii),
            "generated_finished_radii": list(finished_radii),
            "status": (
                "PASS"
                if finished_radii
                and all(
                    any(abs(radius - value) <= TOLERANCE for value in reference.product_radii)
                    for radius in finished_radii
                )
                else "FAIL"
            ),
        },
        "release_allowed": bool(generated_report.get("release_allowed")),
    }
    hard_failures = [
        name
        for name in ("outer_width", "outer_height", "slot_base_height")
        if checks[name]["status"] != "MATCH"
    ]
    if not checks["release_allowed"]:
        hard_failures.append("release_allowed")
    if checks["product_drawing_radius_evidence"]["status"] != "PASS":
        hard_failures.append("product_drawing_radius_evidence")
    for name in approved_overrides:
        check = checks.get(name)
        if isinstance(check, dict) and check.get("status") == "RULE_DELTA":
            check["status"] = "APPROVED_RULE_OVERRIDE"
    documented_deltas = [
        name
        for name in ("slot_width", "guide_thickness", "center_opening", "section_profile")
        if checks[name]["status"] != "MATCH"
    ]
    unresolved_rule_conflicts = [
        name
        for name in documented_deltas
        if checks[name]["status"] != "APPROVED_RULE_OVERRIDE"
    ]
    if checks["guide_section_arc_radius"]["status"] == "RULE_CONFLICT":
        unresolved_rule_conflicts.append("guide_section_arc_radius")
    if reference.section_profile == "flat_arc_groove":
        for name in (
            "section_arc_side",
            "section_flat_side",
            "section_arc_center_side",
        ):
            if checks[name]["status"] == "RULE_CONFLICT":
                unresolved_rule_conflicts.append(name)
    return {
        "reference": reference.as_dict(),
        "generated": {
            "report_path": generated_report.get("paths", {}).get("release_dxf"),
            "slot_width": generated_slot_width,
            "guide_thickness": generated_thickness,
            "center_opening": generated_opening,
            "groove_profile": generated_profile,
            "arc_radius": generated_arc_radius,
            "arc_side": generated_arc_side,
            "flat_side": generated_flat_side,
            "arc_center_side": generated_arc_center_side,
        },
        "checks": checks,
        "hard_failures": hard_failures,
        "documented_rule_deltas": documented_deltas,
        "approved_rule_overrides": sorted(
            name
            for name in documented_deltas
            if checks[name]["status"] == "APPROVED_RULE_OVERRIDE"
        ),
        "unresolved_rule_conflicts": unresolved_rule_conflicts,
        "status": (
            "FAIL"
            if hard_failures
            else "UNRESOLVED_RULE_CONFLICT"
            if unresolved_rule_conflicts
            else "PASS"
        ),
    }


def write_reference_comparison(
    reference_path: str | Path,
    generated_report_path: str | Path,
    output_path: str | Path,
) -> Path:
    report_path = Path(generated_report_path)
    generated_report = json.loads(report_path.read_text(encoding="utf-8"))
    payload = compare_reference_to_generated(
        audit_reference_dxf(reference_path),
        generated_report,
    )
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _find_section_frame(lines: Iterable[Any]) -> tuple[float, float, float, float]:
    horizontal: list[tuple[float, float, float]] = []
    vertical: list[tuple[float, float, float]] = []
    for entity in lines:
        start = entity.dxf.start
        end = entity.dxf.end
        dx = abs(float(end.x) - float(start.x))
        dy = abs(float(end.y) - float(start.y))
        if dy <= 1e-6 and abs(dx - 40.0) <= TOLERANCE:
            horizontal.append((min(float(start.x), float(end.x)), max(float(start.x), float(end.x)), float(start.y)))
        if dx <= 1e-6 and abs(dy - 27.0) <= TOLERANCE:
            vertical.append((float(start.x), min(float(start.y), float(end.y)), max(float(start.y), float(end.y))))
    for left, right, y in horizontal:
        matching = [item for item in vertical if abs(item[0] - left) <= TOLERANCE or abs(item[0] - right) <= TOLERANCE]
        if matching:
            bottom = min(item[1] for item in matching)
            top = max(item[2] for item in matching)
            if bottom - TOLERANCE <= y <= top + TOLERANCE:
                return left, right, bottom, top
    raise ValueError("Could not locate the 40 x 27 reference section frame.")


def _dimension_is_near_section(entity: Any, left: float, right: float, bottom: float, top: float) -> bool:
    point = entity.dxf.get("defpoint", None)
    if point is None:
        return False
    return left - 50.0 <= float(point.x) <= right + 50.0 and bottom - 30.0 <= float(point.y) <= top + 40.0


def _find_slot_width(dimensions: Iterable[Any]) -> float:
    matched = []
    for entity in dimensions:
        text = str(entity.dxf.get("text", ""))
        measurement = _measurement(entity)
        if measurement is not None and 3.0 <= measurement <= 20.0 and "S+0.01" in text:
            matched.append(measurement)
    if len(matched) != 1:
        raise ValueError(f"Expected one reference slot-width dimension, found {matched}.")
    return matched[0]


def _find_guide_thickness(dimensions: Iterable[Any], base_y: float, slot_width: float) -> float:
    matched = []
    for entity in dimensions:
        if not (entity.dxf.hasattr("defpoint2") and entity.dxf.hasattr("defpoint3")):
            continue
        p2 = entity.dxf.defpoint2
        p3 = entity.dxf.defpoint3
        measurement = _measurement(entity)
        if measurement is None or not (0.5 <= measurement <= 5.0):
            continue
        if abs(float(p2.x) - float(p3.x)) > TOLERANCE:
            continue
        ys = (float(p2.y), float(p3.y))
        if min(abs(value - base_y) for value in ys) <= TOLERANCE and abs(measurement - slot_width) > TOLERANCE:
            matched.append(measurement)
    if len(matched) != 1:
        raise ValueError(f"Expected one reference guide-thickness dimension, found {matched}.")
    return matched[0]


def _find_center_opening(dimensions: Iterable[Any], top_y: float) -> float:
    matched = []
    for entity in dimensions:
        if not (entity.dxf.hasattr("defpoint2") and entity.dxf.hasattr("defpoint3")):
            continue
        p2 = entity.dxf.defpoint2
        p3 = entity.dxf.defpoint3
        measurement = _measurement(entity)
        if measurement is None or not (1.0 <= measurement <= 3.0):
            continue
        if abs(float(p2.y) - top_y) <= TOLERANCE and abs(float(p3.y) - top_y) <= TOLERANCE:
            matched.append(measurement)
    if len(matched) != 1:
        raise ValueError(f"Expected one reference center-opening dimension, found {matched}.")
    return matched[0]


def _find_measurement(values: Iterable[float], expected: float) -> float:
    matched = [value for value in values if abs(value - expected) <= TOLERANCE]
    if not matched:
        raise ValueError(f"Reference dimension {expected:g} was not found.")
    return matched[0]


def _measurement(entity: Any) -> float | None:
    try:
        return float(entity.get_measurement())
    except Exception:
        return None


def _comparison(reference: float, generated: float) -> dict[str, Any]:
    delta = generated - reference
    return {
        "reference": round(reference, 6),
        "generated": round(generated, 6),
        "delta": round(delta, 6),
        "status": (
            "MATCH"
            if abs(delta) <= COMPARISON_TOLERANCE
            else "RULE_DELTA"
        ),
    }


def _arc_radius_comparison(
    reference_radii: tuple[float, ...],
    generated_radius: Any,
) -> dict[str, Any]:
    generated = None if generated_radius is None else float(generated_radius)
    if not reference_radii and generated is None:
        status = "MATCH"
    elif reference_radii and generated is not None and any(
        abs(generated - radius) <= COMPARISON_TOLERANCE
        for radius in reference_radii
    ):
        status = "MATCH"
    else:
        status = "RULE_CONFLICT"
    return {
        "reference": list(reference_radii),
        "generated": generated,
        "status": status,
    }


def _optional_rule_comparison(reference: Any, generated: Any) -> dict[str, Any]:
    if reference is None:
        status = "NOT_APPLICABLE"
    else:
        status = "MATCH" if reference == generated else "RULE_CONFLICT"
    return {
        "reference": reference,
        "generated": generated,
        "status": status,
    }


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare one generated guide report with an archived reference DXF.")
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    target = write_reference_comparison(args.reference, args.report, args.output)
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

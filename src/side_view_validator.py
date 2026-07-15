from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass

from .block_geometry import BlockGuideSection
from .cavity_projection import derive_cavity_projection_profile
from .geometry import TileSection
from .machine_config import MachineConfig
from .side_view import SideViewGeometry, build_side_view_geometry
from .side_view_config import DEFAULT_SIDE_VIEW_TEMPLATE, SideViewTemplateConfig
from .side_view_writer import (
    SIDE_CENTER_LAYER,
    SIDE_DEBUG_LAYER,
    SIDE_DERIVED_LAYER,
    SIDE_DIMENSION_LAYER,
    SIDE_TEMPLATE_LAYER,
)


@dataclass(frozen=True)
class SideClearanceConsistency:
    expected: float
    measured_geometry: float | None
    measured_dimension_points: float | None
    measured_dimension_group_42: float | None
    text_label: str

    @property
    def ok(self) -> bool:
        if (
            self.measured_geometry is None
            or self.measured_dimension_points is None
            or self.measured_dimension_group_42 is None
        ):
            return False
        return (
            abs(self.measured_geometry - self.expected) <= 0.001
            and abs(self.measured_dimension_points - self.expected) <= 0.001
            and abs(self.measured_dimension_group_42 - self.expected) <= 0.001
            and self.text_label == f"{self.expected:.2f}"
        )


def assert_side_view_consistency(
    doc,
    tile_section: TileSection | BlockGuideSection,
    machine_config: MachineConfig | None = None,
) -> None:
    geometry = build_side_view_geometry(
        tile_section,
        template=(
            None
            if machine_config is None
            else SideViewTemplateConfig(
                wheel_radius=machine_config.wheel_radius
            )
        ),
        layout=None if machine_config is None else machine_config.side_layout,
    )
    projected = measure_side_projected_slot_consistency(doc, geometry)
    clearance = measure_side_clearance_consistency(doc, geometry)
    cavity_projection_ok = cavity_projection_matches_pre_grinding_shape(
        doc,
        tile_section,
        geometry,
    )
    if not cavity_projection_ok or not clearance.ok:
        raise ValueError(
            "Side view derived dimension validation failed: "
            f"projected(expected={projected.expected:.6f}, "
            f"geometry={_fmt_optional(projected.measured_geometry)}, "
            f"dimension_points={_fmt_optional(projected.measured_dimension_points)}, "
            f"group_42={_fmt_optional(projected.measured_dimension_group_42)}, "
            f"text_label={projected.text_label!r}); "
            f"clearance(expected={clearance.expected:.6f}, "
            f"geometry={_fmt_optional(clearance.measured_geometry)}, "
            f"dimension_points={_fmt_optional(clearance.measured_dimension_points)}, "
            f"group_42={_fmt_optional(clearance.measured_dimension_group_42)}, "
            f"text_label={clearance.text_label!r})."
            f" cavity_projection_matches_pre_grinding_shape={cavity_projection_ok}."
        )


def cavity_projection_matches_pre_grinding_shape(
    doc,
    section: TileSection | BlockGuideSection,
    geometry: SideViewGeometry,
) -> bool:
    projection = derive_cavity_projection_profile(
        section,
        geometry.derived.guide_thickness,
    )
    base_y = geometry.layout.lower_y + geometry.derived.slot_base_height
    expected = sorted(
        round(base_y + offset, 6)
        for offset in projection.offsets
    )
    observed = sorted(
        {
            round(float(entity.dxf.start.y), 6)
            for entity in doc.modelspace().query("LINE")
            if entity.dxf.layer == SIDE_DERIVED_LAYER
            and abs(
                float(entity.dxf.start.y) - float(entity.dxf.end.y)
            )
            <= 0.001
            and geometry.layout.left_x - 0.001
            <= (
                float(entity.dxf.start.x) + float(entity.dxf.end.x)
            )
            / 2.0
            <= geometry.layout.right_x + 0.001
            and any(
                abs(float(entity.dxf.start.y) - expected_y) <= 0.001
                for expected_y in expected
            )
        }
    )
    return observed == expected


def write_side_view_report(
    tile_section: TileSection,
    path: str | Path,
    dxf_path: str | Path | None = None,
    output_mode: str = "debug",
) -> Path:
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    geometry = build_side_view_geometry(tile_section)
    spec = tile_section.finished_spec
    guide = tile_section.guide_spec
    release_hides_debug = True
    release_hides_formula_text = True
    side_view_present = False
    dimension_texts_present = False
    r80_count_matches_template = False
    fixed_template_entities_preserved = False
    no_full_length_derived_lines = False
    template_counts: dict[str, int] = {}
    target_counts: dict[str, int] = {}
    template_r80_count = 0
    target_r80_count = 0
    projected_consistency = SideClearanceConsistency(
        expected=geometry.derived.side_projected_slot_height,
        measured_geometry=None,
        measured_dimension_points=None,
        measured_dimension_group_42=None,
        text_label="",
    )
    clearance_consistency = SideClearanceConsistency(
        expected=geometry.derived.side_clearance_height,
        measured_geometry=None,
        measured_dimension_points=None,
        measured_dimension_group_42=None,
        text_label="",
    )
    if dxf_path is not None:
        try:
            import ezdxf

            doc = ezdxf.readfile(dxf_path)
            template_doc = ezdxf.readfile(DEFAULT_SIDE_VIEW_TEMPLATE)
            layers = {entity.dxf.layer for entity in doc.modelspace()}
            release_hides_debug = output_mode != "release" or SIDE_DEBUG_LAYER not in layers
            release_hides_formula_text = output_mode != "release" or not _formula_texts_present(doc)
            side_view_present = (
                "PARAM_SLOT" in layers
                and SIDE_TEMPLATE_LAYER in layers
                and SIDE_DIMENSION_LAYER in layers
            )
            labels = _side_dimension_labels(doc)
            dimension_texts_present = (
                f"{geometry.derived.side_projected_slot_height:.2f}" in labels
                and f"{geometry.derived.side_clearance_height:.2f}" in labels
            )
            template_counts = _fixed_entity_counts(template_doc)
            target_counts = _target_side_fixed_entity_counts(doc)
            fixed_template_entities_preserved = all(
                target_counts.get(entity_type, 0) >= template_counts.get(entity_type, 0)
                for entity_type in ("LINE", "ARC", "LWPOLYLINE")
            )
            template_r80_count = _r80_arc_count(template_doc, template_layers=None)
            target_r80_count = _r80_arc_count(doc, template_layers={SIDE_TEMPLATE_LAYER})
            r80_count_matches_template = target_r80_count == template_r80_count
            no_full_length_derived_lines = not _has_full_length_derived_line(doc, geometry.template.fixed_435)
            projected_consistency = measure_side_projected_slot_consistency(doc, geometry)
            clearance_consistency = measure_side_clearance_consistency(doc, geometry)
        except Exception:
            release_hides_debug = False
            release_hides_formula_text = False

    lines = [
        "Side view validation report",
        f"Output mode: {output_mode}",
        "",
        "product_spec:",
        f"  R_outer_finished: {spec.R_outer_finished:.6f}",
        f"  R_inner_finished: {spec.R_inner_finished:.6f}",
        f"  chord_width: {spec.chord_width:.6f}",
        f"  product_length: {spec.length:.6f}",
        f"  finished_thickness: {spec.finished_thickness:.6f}",
        "",
        "guide_section_derived:",
        f"  R_form: max({spec.R_outer_finished:.6f}, {spec.R_inner_finished:.6f}) = {tile_section.forming_spec.R_form:.6f}",
        (
            "  guide_thickness: "
            f"{spec.finished_thickness:.6f} + {guide.thickness_clearance_mid_value:.6f} = "
            f"{guide.guide_thickness:.6f}"
        ),
        "",
        "side_template_fixed:",
        f"  fixed_90: {geometry.template.fixed_90:.6f}",
        f"  fixed_200: {geometry.template.fixed_200:.6f}",
        f"  fixed_145: {geometry.template.fixed_145:.6f}",
        f"  fixed_435: {geometry.template.fixed_435:.6f}",
        f"  wheel_radius: {geometry.template.wheel_radius:.6f}",
        "",
        "side_derived:",
        f"  side_projected_slot_height: {geometry.derived.side_projected_slot_height:.6f}",
        (
            "  side_projected_slot_height_formula: "
            f"{geometry.derived.slot_base_height:.6f} + "
            f"{geometry.derived.side_cut_in_allowance:.6f} = "
            f"{geometry.derived.side_projected_slot_height:.6f}"
        ),
        f"  side_clearance_height: {geometry.derived.side_clearance_height:.6f}",
        (
            "  side_clearance_height_formula: "
            f"{geometry.derived.guide_outer_height:.6f} - "
            f"{geometry.derived.slot_base_height:.6f} - "
            f"{geometry.derived.guide_thickness:.6f} + "
            f"{geometry.derived.wheel_cut_allowance:.6f} = "
            f"{geometry.derived.side_clearance_height:.6f}"
        ),
        "",
        "side_projected_slot_consistency:",
        f"  expected_side_projected_slot_height: {projected_consistency.expected:.6f}",
        (
            "  measured_side_projected_slot_height_from_geometry: "
            f"{_fmt_optional(projected_consistency.measured_geometry)}"
        ),
        (
            "  measured_side_projected_slot_height_from_dimension_points: "
            f"{_fmt_optional(projected_consistency.measured_dimension_points)}"
        ),
        (
            "  measured_side_projected_slot_height_from_dimension_group_42: "
            f"{_fmt_optional(projected_consistency.measured_dimension_group_42)}"
        ),
        f"  text_label: {projected_consistency.text_label or '(missing)'}",
        f"  status: {'PASS' if projected_consistency.ok else 'FAIL'}",
        "",
        "side_clearance_consistency:",
        f"  expected_side_clearance_height: {clearance_consistency.expected:.6f}",
        (
            "  measured_side_clearance_height_from_geometry: "
            f"{_fmt_optional(clearance_consistency.measured_geometry)}"
        ),
        (
            "  measured_side_clearance_height_from_dimension_points: "
            f"{_fmt_optional(clearance_consistency.measured_dimension_points)}"
        ),
        (
            "  measured_side_clearance_height_from_dimension_group_42: "
            f"{_fmt_optional(clearance_consistency.measured_dimension_group_42)}"
        ),
        f"  text_label: {clearance_consistency.text_label or '(missing)'}",
        f"  status: {'PASS' if clearance_consistency.ok else 'FAIL'}",
        "",
        "checks:",
        f"  projected_height_formula: {'PASS' if _projected_formula_ok(geometry) else 'FAIL'}",
        f"  clearance_height_formula: {'PASS' if _clearance_formula_ok(geometry) else 'FAIL'}",
        f"  R80_unchanged: {'PASS' if geometry.template.wheel_radius == 80.0 else 'FAIL'}",
        (
            "  R80_arc_count_matches_template: "
            f"{'PASS' if r80_count_matches_template else 'FAIL'} "
            f"(template={template_r80_count}, output={target_r80_count})"
        ),
        f"  fixed_lengths_unchanged: {'PASS' if _fixed_lengths_ok(geometry) else 'FAIL'}",
        (
            "  fixed_LINE_ARC_LWPOLYLINE_preserved: "
            f"{'PASS' if fixed_template_entities_preserved else 'FAIL'} "
            f"(template={template_counts}, output={target_counts})"
        ),
        f"  no_full_length_SIDE_DERIVED_lines: {'PASS' if no_full_length_derived_lines else 'FAIL'}",
        f"  release_hides_debug: {'PASS' if release_hides_debug else 'FAIL'}",
        f"  release_hides_formula_text: {'PASS' if release_hides_formula_text else 'FAIL'}",
        f"  side_view_combined_with_section: {'PASS' if side_view_present else 'FAIL'}",
        f"  derived_dimension_texts_present: {'PASS' if dimension_texts_present else 'FAIL'}",
        f"  side_projected_geometry_dimension_text_consistent: {'PASS' if projected_consistency.ok else 'FAIL'}",
        f"  side_clearance_geometry_dimension_text_consistent: {'PASS' if clearance_consistency.ok else 'FAIL'}",
    ]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def _projected_formula_ok(geometry: SideViewGeometry) -> bool:
    derived = geometry.derived
    return abs(
        derived.side_projected_slot_height
        - (derived.slot_base_height + derived.side_cut_in_allowance)
    ) < 1e-9


def _clearance_formula_ok(geometry: SideViewGeometry) -> bool:
    derived = geometry.derived
    return abs(
        derived.side_clearance_height
        - (
            derived.guide_outer_height
            - derived.slot_base_height
            - derived.guide_thickness
            + derived.wheel_cut_allowance
        )
    ) < 1e-9


def _fixed_lengths_ok(geometry: SideViewGeometry) -> bool:
    template = geometry.template
    return (
        template.fixed_90 == 90.0
        and template.fixed_200 == 200.0
        and template.fixed_145 == 145.0
        and template.fixed_435 == 435.0
    )


def measure_side_clearance_consistency(doc, geometry: SideViewGeometry) -> SideClearanceConsistency:
    expected = geometry.derived.side_clearance_height
    label = f"{expected:.2f}"
    return SideClearanceConsistency(
        expected=expected,
        measured_geometry=_measure_side_clearance_from_geometry(doc, geometry),
        measured_dimension_points=_measure_side_clearance_from_dimension_points(doc, label),
        measured_dimension_group_42=_measure_side_dimension_group_42(doc, label),
        text_label=_side_dimension_display_text(doc, label),
    )


def measure_side_projected_slot_consistency(doc, geometry: SideViewGeometry) -> SideClearanceConsistency:
    expected = geometry.derived.side_projected_slot_height
    label = f"{expected:.2f}"
    return SideClearanceConsistency(
        expected=expected,
        measured_geometry=_measure_side_projected_slot_from_geometry(doc, geometry),
        measured_dimension_points=_measure_side_clearance_from_dimension_points(doc, label),
        measured_dimension_group_42=_measure_side_dimension_group_42(doc, label),
        text_label=_side_dimension_display_text(doc, label),
    )


def _measure_side_projected_slot_from_geometry(doc, geometry: SideViewGeometry) -> float | None:
    line_candidates = []
    expected_y = geometry.layout.lower_y + geometry.derived.side_projected_slot_height
    for entity in doc.modelspace():
        if entity.dxf.layer != SIDE_DERIVED_LAYER or entity.dxftype() != "LINE":
            continue
        if abs(entity.dxf.start.y - entity.dxf.end.y) > 1e-6:
            continue
        if abs(entity.dxf.start.y - expected_y) <= 0.001:
            line_candidates.append(entity.dxf.start.y - geometry.layout.lower_y)
    if line_candidates:
        return min(line_candidates, key=lambda value: abs(value - geometry.derived.side_projected_slot_height))

    candidates = []
    for entity in doc.modelspace():
        if entity.dxf.layer != SIDE_TEMPLATE_LAYER or entity.dxftype() != "ARC":
            continue
        if abs(entity.dxf.radius - geometry.template.wheel_radius) > 1e-6:
            continue
        if abs(entity.dxf.center.x - geometry.layout.center_b_x) > 0.01:
            continue
        if entity.dxf.center.y > geometry.layout.lower_y:
            continue
        candidates.append(entity.dxf.center.y + entity.dxf.radius - geometry.layout.lower_y)
    if not candidates:
        return None
    return min(candidates, key=lambda value: abs(value - geometry.derived.side_projected_slot_height))


def _measure_side_clearance_from_geometry(doc, geometry: SideViewGeometry) -> float | None:
    candidates = []
    for entity in doc.modelspace():
        if entity.dxf.layer != SIDE_TEMPLATE_LAYER or entity.dxftype() != "ARC":
            continue
        if abs(entity.dxf.radius - geometry.template.wheel_radius) > 1e-6:
            continue
        if min(
            abs(entity.dxf.center.x - geometry.layout.center_a_x),
            abs(entity.dxf.center.x - geometry.layout.center_b_x),
        ) > 0.01:
            continue
        if entity.dxf.center.y < geometry.layout.upper_y:
            continue
        candidates.append(geometry.layout.upper_y - (entity.dxf.center.y - entity.dxf.radius))
    if not candidates:
        return None
    return min(candidates, key=lambda value: abs(value - geometry.derived.side_clearance_height))


def _measure_side_clearance_from_dimension_points(doc, label: str) -> float | None:
    for entity in doc.modelspace():
        if entity.dxf.layer != SIDE_DIMENSION_LAYER or entity.dxftype() != "DIMENSION":
            continue
        if entity.dxf.text != label:
            continue
        if entity.dxf.hasattr("defpoint2") and entity.dxf.hasattr("defpoint3"):
            return abs(entity.dxf.defpoint2.y - entity.dxf.defpoint3.y)
        try:
            return float(entity.get_measurement())
        except Exception:
            return None
    return None


def _measure_side_dimension_group_42(doc, label: str) -> float | None:
    for entity in doc.modelspace():
        if entity.dxf.layer != SIDE_DIMENSION_LAYER or entity.dxftype() != "DIMENSION":
            continue
        if entity.dxf.text != label:
            continue
        if entity.dxf.hasattr("actual_measurement"):
            return float(entity.dxf.actual_measurement)
        return None
    return None


def _side_dimension_display_text(doc, label: str) -> str:
    for entity in doc.modelspace():
        if entity.dxf.layer != SIDE_DIMENSION_LAYER or entity.dxftype() != "DIMENSION":
            continue
        if entity.dxf.text != label:
            continue
        if entity.dxf.hasattr("geometry") and entity.dxf.geometry in doc.blocks:
            for block_entity in doc.blocks[entity.dxf.geometry]:
                if block_entity.dxftype() == "TEXT":
                    return block_entity.dxf.text
                if block_entity.dxftype() == "MTEXT":
                    return block_entity.text
        return entity.dxf.text
    return ""


def _fmt_optional(value: float | None) -> str:
    if value is None:
        return "(missing)"
    return f"{value:.6f}"


def _fixed_entity_counts(doc) -> dict[str, int]:
    counts = {"LINE": 0, "ARC": 0, "LWPOLYLINE": 0}
    for entity in doc.modelspace():
        if entity.dxftype() in counts:
            counts[entity.dxftype()] += 1
    return counts


def _target_side_fixed_entity_counts(doc) -> dict[str, int]:
    counts = {"LINE": 0, "ARC": 0, "LWPOLYLINE": 0}
    fixed_layers = {SIDE_TEMPLATE_LAYER, SIDE_CENTER_LAYER}
    for entity in doc.modelspace():
        if entity.dxf.layer in fixed_layers and entity.dxftype() in counts:
            counts[entity.dxftype()] += 1
    return counts


def _r80_arc_count(doc, template_layers: set[str] | None) -> int:
    count = 0
    for entity in doc.modelspace():
        if entity.dxftype() != "ARC":
            continue
        if template_layers is not None and entity.dxf.layer not in template_layers:
            continue
        if abs(entity.dxf.radius - 80.0) < 1e-6:
            count += 1
    return count


def _side_dimension_labels(doc) -> set[str]:
    labels: set[str] = set()
    for entity in doc.modelspace():
        if entity.dxf.layer != SIDE_DIMENSION_LAYER:
            continue
        if entity.dxftype() == "DIMENSION":
            if entity.dxf.text:
                labels.add(entity.dxf.text)
            try:
                measurement = entity.get_measurement()
            except Exception:
                continue
            labels.add(f"{measurement:.0f}")
            labels.add(f"{measurement:.1f}")
            labels.add(f"{measurement:.2f}")
            if abs(measurement - 80.0) < 1e-6:
                labels.add("R80")
        elif entity.dxftype() == "TEXT":
            labels.add(entity.dxf.text)
        elif entity.dxftype() == "MTEXT":
            labels.add(entity.text)
    return labels


def _has_full_length_derived_line(doc, fixed_435: float) -> bool:
    for entity in doc.modelspace():
        if entity.dxf.layer != SIDE_DERIVED_LAYER or entity.dxftype() != "LINE":
            continue
        start = entity.dxf.start
        end = entity.dxf.end
        if abs(start.y - end.y) < 1e-6 and abs(abs(end.x - start.x) - fixed_435) < 0.01:
            return True
    return False


def _formula_texts_present(doc) -> bool:
    needles = ("+0.50=", "+0.20=", "12.0+0.50", "27.0-12.0")
    for entity in doc.modelspace():
        if entity.dxftype() == "TEXT":
            text = entity.dxf.text
        elif entity.dxftype() == "MTEXT":
            text = entity.text
        else:
            continue
        if any(needle in text for needle in needles):
            return True
    return False

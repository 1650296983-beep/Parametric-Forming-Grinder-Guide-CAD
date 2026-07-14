from dataclasses import replace
from math import sqrt

import ezdxf
import pytest

from src.block_geometry import build_block_guide_section
from src.dxf_writer import write_dxf
from src.side_view import build_side_view_geometry
from src.machine_config import load_machine_config
from src.spec_parser import parse_block_spec


def test_double_head_up_up_block_spec_uses_selected_slot_reference(tmp_path):
    machine = load_machine_config("double_head_up_up")
    spec = replace(
        parse_block_spec("8.94*3*2"),
        length_tolerance_upper=0.02,
        length_tolerance_lower=0.02,
    )
    profile = build_block_guide_section(
        spec,
        slot_reference="length",
        slot_clearance=0.05,
        thickness_clearance_mid=machine.block_thickness_clearance_mid,
    )
    side = build_side_view_geometry(profile, layout=machine.side_layout)
    release_path = tmp_path / "block_release.dxf"

    write_dxf(profile, release_path, output_mode="release", machine_id="double_head_up_up")
    doc = ezdxf.readfile(release_path)
    measurements = _dimension_measurements_by_text(doc)

    assert profile.guide_spec.guide_slot_width == pytest.approx(9.01)
    assert profile.guide_spec.guide_thickness == pytest.approx(2.09)
    assert side.derived.side_projected_slot_height == pytest.approx(18.0)
    expected_opening = spec.length - 0.2
    expected_cut_in = 80.0 - sqrt(80.0**2 - (expected_opening / 2.0) ** 2)
    assert side.derived.side_clearance_height == pytest.approx(
        profile.guide_spec.outer_height - 18.0 - expected_cut_in
    )
    assert measurements["9.01±0.01"][0] == pytest.approx(9.01)
    assert measurements["2.09"][0] == pytest.approx(2.09)
    assert measurements["2-<>"][0] == pytest.approx(0.5)
    assert measurements["4-<>"][0] == pytest.approx(1.0)
    clearance_label = f"{side.derived.side_clearance_height:.2f}"
    assert measurements[clearance_label] == pytest.approx(
        [side.derived.side_clearance_height] * 2
    )
    assert "18.00" not in measurements
    assert _section_dimension_block_text(doc, "9.01±0.01").startswith("9.01{\\H0.7x;\\S+0.01^ -0.01;}")

    r80_centers = [
        entity.dxf.center
        for entity in doc.modelspace()
        if entity.dxf.layer == "SIDE_TEMPLATE"
        and entity.dxftype() == "ARC"
        and entity.dxf.radius == pytest.approx(80.0)
    ]
    assert len(r80_centers) == 2
    assert r80_centers[0].y == pytest.approx(r80_centers[1].y)
    assert r80_centers[0].y - 80.0 == pytest.approx(
        machine.side_layout.upper_y - side.derived.side_clearance_height
    )
    _assert_r80_top_gaps_match_arcs(doc, machine.side_layout.upper_y)
    _assert_section_has_standard_2mm_neck(doc)
    assert not any("DEBUG" in entity.dxf.layer for entity in doc.modelspace())


def test_block_slot_width_uses_zero_tolerance_when_not_provided():
    spec = parse_block_spec("9.1*4*3")
    profile = build_block_guide_section(spec, slot_reference="length", slot_clearance=0.05)

    assert spec.width_tolerance_upper is None
    assert spec.width_tolerance_lower is None
    assert profile.guide_spec.preform_tolerance.upper == pytest.approx(0.0)
    assert profile.guide_spec.preform_tolerance.lower == pytest.approx(0.0)
    assert profile.guide_spec.guide_slot_width == pytest.approx(9.15)


def test_block_side_view_rejects_missing_machine_recipe():
    machine = load_machine_config("double_head_up_up")
    profile = build_block_guide_section(
        parse_block_spec("9.1*4*3"),
        slot_reference="length",
        slot_clearance=0.05,
    )

    with pytest.raises(ValueError, match="Block side-view configuration is required"):
        build_side_view_geometry(
            profile,
            layout=replace(machine.side_layout, block_side_mode=None),
        )


def test_block_slot_width_uses_explicit_tolerance_average():
    spec = parse_block_spec("9.1*4(-0.05/-0.02)*3")
    profile = build_block_guide_section(spec, slot_reference="width", slot_clearance=0.05)

    assert profile.guide_spec.guide_slot_width == pytest.approx(4.02)


def test_block_guide_thickness_uses_asymmetric_preform_thickness_midpoint():
    spec = parse_block_spec("41*7(+0.01/-0.01)*1.7(+0.02/+0)")
    profile = build_block_guide_section(
        spec,
        slot_reference="width",
        slot_clearance=None,
        thickness_clearance_mid=0.12,
    )

    assert spec.thickness_mid == pytest.approx(1.71)
    assert profile.guide_spec.guide_thickness == pytest.approx(1.83)


def test_block_slot_width_uses_length_tolerance_for_length_reference():
    spec = parse_block_spec("9.02(-0.02/-0.05)*6*1.2")
    profile = build_block_guide_section(spec, slot_reference="length", slot_clearance=0.05)

    assert profile.guide_spec.preform_tolerance.upper == pytest.approx(-0.02)
    assert profile.guide_spec.preform_tolerance.lower == pytest.approx(-0.05)
    assert profile.guide_spec.guide_slot_width == pytest.approx(9.04)


def test_double_head_up_up_side_r80_closes_for_variable_thickness(tmp_path):
    machine = load_machine_config("double_head_up_up")
    spec = parse_block_spec("9.1*4*3")
    profile = build_block_guide_section(
        spec,
        slot_reference="length",
        slot_clearance=0.05,
        thickness_clearance_mid=machine.block_thickness_clearance_mid,
    )
    side = build_side_view_geometry(profile, layout=machine.side_layout)
    release_path = tmp_path / "block_9p1_release.dxf"

    write_dxf(profile, release_path, output_mode="release", machine_id="double_head_up_up")
    doc = ezdxf.readfile(release_path)

    expected_opening = spec.length - 0.2
    expected_cut_in = 80.0 - sqrt(80.0**2 - (expected_opening / 2.0) ** 2)
    assert side.derived.side_clearance_height == pytest.approx(
        profile.guide_spec.outer_height - 18.0 - expected_cut_in
    )
    _assert_r80_top_gaps_match_arcs(doc, machine.side_layout.upper_y)
    working_y = machine.side_layout.upper_y - side.derived.side_clearance_height
    working_lines = [
        entity
        for entity in doc.modelspace()
        if entity.dxf.layer == "SIDE_DERIVED"
        and entity.dxftype() == "LINE"
        and entity.dxf.start.y == pytest.approx(working_y, abs=0.001)
        and entity.dxf.end.y == pytest.approx(working_y, abs=0.001)
    ]
    assert len(working_lines) == 3


def _dimension_measurements_by_text(doc) -> dict[str, list[float]]:
    measurements = {}
    for dimension in doc.modelspace():
        if dimension.dxftype() == "DIMENSION" and dimension.dxf.text:
            measurements.setdefault(dimension.dxf.text, []).append(dimension.get_measurement())
    return measurements


def _section_dimension_block_text(doc, dxf_text: str) -> str:
    for dimension in doc.modelspace():
        if dimension.dxftype() != "DIMENSION" or dimension.dxf.text != dxf_text:
            continue
        if not dimension.dxf.hasattr("geometry") or dimension.dxf.geometry not in doc.blocks:
            return ""
        for entity in doc.blocks[dimension.dxf.geometry]:
            if entity.dxftype() == "TEXT":
                return entity.dxf.text
            if entity.dxftype() == "MTEXT":
                return entity.text
    return ""


def _assert_r80_top_gaps_match_arcs(doc, upper_y: float) -> None:
    arcs = [
        entity
        for entity in doc.modelspace()
        if entity.dxf.layer == "SIDE_TEMPLATE"
        and entity.dxftype() == "ARC"
        and entity.dxf.radius == pytest.approx(80.0)
    ]
    top_line_xs = []
    for entity in doc.modelspace():
        if entity.dxf.layer != "SIDE_TEMPLATE" or entity.dxftype() != "LINE":
            continue
        if entity.dxf.start.y == pytest.approx(upper_y, abs=0.001) and entity.dxf.end.y == pytest.approx(
            upper_y, abs=0.001
        ):
            top_line_xs.extend([entity.dxf.start.x, entity.dxf.end.x])

    for arc in arcs:
        radius = arc.dxf.radius
        dy = upper_y - arc.dxf.center.y
        half_chord = (radius * radius - dy * dy) ** 0.5
        assert any(x == pytest.approx(arc.dxf.center.x - half_chord, abs=0.001) for x in top_line_xs)
        assert any(x == pytest.approx(arc.dxf.center.x + half_chord, abs=0.001) for x in top_line_xs)


def _assert_section_has_standard_2mm_neck(doc) -> None:
    neck_lines = []
    for entity in doc.modelspace():
        if entity.dxf.layer != "PARAM_SLOT" or entity.dxftype() != "LINE":
            continue
        if abs(entity.dxf.start.x - entity.dxf.end.x) <= 0.001 and entity.dxf.start.y > entity.dxf.end.y:
            neck_lines.append(entity)
    top_neck_lines = [
        line
        for line in neck_lines
        if line.dxf.start.y == pytest.approx(-245.0417181848652, abs=0.001)
        and line.dxf.end.y > -252.5
    ]
    assert len(top_neck_lines) == 2
    xs = sorted(line.dxf.start.x for line in top_neck_lines)
    assert xs[1] - xs[0] == pytest.approx(2.0)
    section_arcs = [
        entity
        for entity in doc.modelspace()
        if entity.dxf.layer == "PARAM_SLOT"
        and entity.dxftype() == "ARC"
        and entity.dxf.radius == pytest.approx(0.5)
        and 3220 <= entity.dxf.center.x <= 3255
        and -260 <= entity.dxf.center.y <= -245
    ]
    assert len(section_arcs) == 6

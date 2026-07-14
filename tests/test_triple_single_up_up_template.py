from math import sqrt

import ezdxf
import pytest

from src.block_geometry import build_block_guide_section
from src.dxf_writer import write_dxf
from src.machine_config import load_machine_config
from src.side_view import build_side_view_geometry
from src.spec_parser import parse_block_spec


def test_triple_single_up_up_config_matches_clean_template():
    machine = load_machine_config("triple_single_up_up")

    assert machine.guide_length == pytest.approx(379.0)
    assert machine.side_fixed_spans == pytest.approx((99.0, 180.0, 100.0))
    assert machine.wheel_positions == ("上", "上")
    assert machine.guide_sections == 1
    assert machine.block_outer_width == pytest.approx(40.0)
    assert machine.block_thickness_clearance_mid == pytest.approx(0.09)
    assert machine.side_layout.block_fixed_top_gap == pytest.approx(3.0)
    assert machine.section_template_path.exists()
    assert machine.side_template_path.exists()


def test_triple_single_up_up_block_release_updates_native_dimensions(tmp_path):
    machine = load_machine_config("triple_single_up_up")
    spec = parse_block_spec("9.1*4*2.5")
    profile = build_block_guide_section(
        spec,
        slot_reference="length",
        slot_clearance=0.05,
        outer_width=40.0,
        thickness_clearance_mid=machine.block_thickness_clearance_mid,
    )
    release_path = tmp_path / "triple_single_up_up_release.dxf"

    write_dxf(profile, release_path, output_mode="release", machine_id="triple_single_up_up")
    doc = ezdxf.readfile(release_path)
    measurements = _dimension_measurements_by_text(doc)
    side = build_side_view_geometry(profile, layout=machine.side_layout)

    assert profile.guide_spec.guide_slot_width == pytest.approx(9.15)
    assert profile.guide_spec.guide_thickness == pytest.approx(2.59)
    assert side.derived.side_projected_slot_height == pytest.approx(21.41)
    expected_opening = spec.length - 0.2
    expected_cut_in = 80.0 - sqrt(80.0**2 - (expected_opening / 2.0) ** 2)
    expected_clearance = (
        profile.guide_spec.outer_height
        - side.derived.side_projected_slot_height
        - expected_cut_in
    )
    assert side.derived.side_clearance_height == pytest.approx(expected_clearance)
    assert measurements["9.15±0.01"][0] == pytest.approx(9.15)
    assert measurements["2.59"][0] == pytest.approx(2.59)
    assert measurements["3"][0] == pytest.approx(3.0)
    clearance_label = f"{expected_clearance:.2f}"
    assert measurements[clearance_label] == pytest.approx(
        [expected_clearance, expected_clearance]
    )
    _assert_r80_bottom_matches_clearance(doc, machine.side_layout.upper_y, side.derived.side_clearance_height)
    assert not any("DEBUG" in entity.dxf.layer for entity in doc.modelspace())


def _dimension_measurements_by_text(doc) -> dict[str, list[float]]:
    measurements = {}
    for dimension in doc.modelspace():
        if dimension.dxftype() == "DIMENSION" and dimension.dxf.text:
            measurements.setdefault(dimension.dxf.text, []).append(dimension.get_measurement())
    return measurements


def _assert_r80_bottom_matches_clearance(doc, upper_y: float, clearance: float) -> None:
    arcs = [
        entity
        for entity in doc.modelspace()
        if entity.dxf.layer == "SIDE_TEMPLATE" and entity.dxftype() == "ARC" and entity.dxf.radius == pytest.approx(80.0)
    ]
    assert len(arcs) == 2
    for arc in arcs:
        assert arc.dxf.center.y - arc.dxf.radius == pytest.approx(upper_y - clearance)

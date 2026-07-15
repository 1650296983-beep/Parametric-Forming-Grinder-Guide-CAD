import logging

import ezdxf
import pytest

from src.block_geometry import build_block_guide_section
from src.dxf_writer import write_dxf
from src.geometry import build_block_to_tile_section, build_tile_section
from src.machine_config import load_machine_config
from src.side_view import build_side_view_geometry
from src.spec_parser import (
    parse_block_spec,
    parse_company_bread_spec,
    parse_company_tile_spec,
)


def test_bed_618_config_matches_clean_template():
    machine = load_machine_config("bed_618")

    assert machine.guide_length == pytest.approx(300.0)
    assert machine.side_fixed_spans == pytest.approx((170.0, 130.0))
    assert machine.wheel_positions == ("上",)
    assert machine.guide_sections == 1
    assert machine.section_style == "bed_618_fixed_base"
    assert machine.section_outer_width == pytest.approx(40.0)
    assert machine.section_center_opening == pytest.approx(2.0)
    assert machine.section_slot_base_height == pytest.approx(20.9)
    assert machine.side_layout.fixed_tile_side_projected_slot_height == pytest.approx(20.9)
    assert machine.section_template_path.exists()
    assert machine.side_template_path.exists()


def test_bed_618_release_uses_fixed_20p9_slot_base_and_single_upper_wheel(tmp_path):
    machine = load_machine_config("bed_618")
    spec = parse_company_tile_spec("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65")
    profile = build_tile_section(
        spec,
        outer_width=machine.section_outer_width,
        center_opening=machine.section_center_opening,
        slot_base_height=machine.section_slot_base_height,
    )
    side = build_side_view_geometry(profile, layout=machine.side_layout)
    release_path = tmp_path / "bed_618_release.dxf"

    write_dxf(profile, release_path, output_mode="release", machine_id="bed_618")
    doc = ezdxf.readfile(release_path)
    measurements = _dimension_measurements_by_text(doc)

    assert profile.guide_spec.outer_width == pytest.approx(40.0)
    assert profile.guide_spec.center_opening == pytest.approx(2.0)
    assert profile.guide_spec.slot_base_height == pytest.approx(20.9)
    assert profile.guide_spec.guide_thickness == pytest.approx(1.83)
    assert side.derived.side_projected_slot_height == pytest.approx(20.9)
    assert side.derived.side_clearance_height == pytest.approx(4.636605623)

    assert measurements["20.90"][0] == pytest.approx(20.9)
    assert measurements["20.90"][0] == pytest.approx(20.9)
    assert measurements["2.00"][0] == pytest.approx(2.0)
    assert measurements["40.00"][0] == pytest.approx(40.0)
    assert measurements["1.83"][0] == pytest.approx(1.83)
    assert measurements["4.64"][0] == pytest.approx(4.636605623)
    side_clearance_dim = _dimension_by_text(doc, "4.64")
    assert side_clearance_dim.dxf.defpoint.x > machine.side_layout.right_x
    assert side_clearance_dim.dxf.defpoint2.x == pytest.approx(machine.side_layout.right_x)
    assert side_clearance_dim.dxf.defpoint3.x == pytest.approx(machine.side_layout.right_x)
    assert abs(side_clearance_dim.dxf.defpoint2.y - side_clearance_dim.dxf.defpoint3.y) == pytest.approx(4.636605623)
    for label in {"27.00", "2.00", "40.00", "20.90", "1.83", "6.21±0.01", "R17.45"}:
        assert _dimension_by_text(doc, label).dxf.dimstyle == "TH_GBDIM"
    secondary_relief_dim = _dimension_by_text(doc, "2-R0.50")
    assert secondary_relief_dim.dxf.dimstyle == "TH_GBDIM"
    assert secondary_relief_dim.dxf.text_midpoint.x - secondary_relief_dim.dxf.defpoint.x == pytest.approx(
        3247.827 - 3242.602,
        abs=0.01,
    )
    assert secondary_relief_dim.dxf.text_midpoint.y - secondary_relief_dim.dxf.defpoint.y == pytest.approx(
        62.252 - 58.200,
        abs=0.01,
    )
    slot_base_dim = _dimension_by_text(doc, "20.90")
    assert _dimension_block_has_horizontal_line_at_y(doc, "20.90", slot_base_dim.dxf.defpoint2.y)
    assert _dimension_block_has_horizontal_line_at_y(doc, "20.90", slot_base_dim.dxf.defpoint3.y)
    _assert_r_dimensions_target_visible_slot_arcs(doc, profile)

    r80_arcs = [
        entity
        for entity in doc.modelspace().query("ARC")
        if entity.dxf.layer == "SIDE_TEMPLATE" and entity.dxf.radius == pytest.approx(80.0)
    ]
    r15_arcs = [
        entity
        for entity in doc.modelspace().query("ARC")
        if entity.dxf.layer == "SIDE_TEMPLATE" and entity.dxf.radius == pytest.approx(15.0)
    ]
    assert len(r80_arcs) == 1
    assert r80_arcs[0].dxf.center.x == pytest.approx(machine.side_layout.center_a_x)
    assert len(r15_arcs) == 1

    assert _has_side_derived_horizontal_line(doc, machine.side_layout.lower_y + 20.9)
    assert _has_side_derived_horizontal_line(doc, machine.side_layout.lower_y + 20.9 + 1.83)
    assert not any("DEBUG" in entity.dxf.layer for entity in doc.modelspace())


def test_bed_618_debug_keeps_one_r_form_dimension_for_block_to_tile(tmp_path, caplog):
    machine = load_machine_config("bed_618")
    finished = parse_company_tile_spec(
        "R9.6*R9.6*8.6(-0.07/-0.09)*42.6*2.1(+0.01/-0.01)"
    )
    preform = parse_block_spec("42.6*8.6(-0.07/-0.09)*2.1(+0.01/-0.01)")
    profile = build_block_to_tile_section(
        finished,
        preform,
        outer_width=machine.section_outer_width,
        center_opening=machine.section_center_opening,
        slot_base_height=machine.section_slot_base_height,
        arc_side="upper",
    )
    debug_path = tmp_path / "block_to_tile_debug.dxf"

    caplog.set_level(logging.WARNING)
    write_dxf(profile, debug_path, output_mode="debug", machine_id=machine.machine_id)
    doc = ezdxf.readfile(debug_path)
    dimension_texts = [
        entity.dxf.text
        for entity in doc.modelspace().query("DIMENSION")
        if entity.dxf.layer == "DIMENSION"
    ]

    assert profile.process_type == "block_to_tile"
    assert dimension_texts.count("R9.60") == 1
    assert not any(
        "copy process ignored DIMASSOC" in record.getMessage()
        for record in caplog.records
    )


def test_bed_618_debug_keeps_two_r_form_dimensions_for_same_r_tile(tmp_path):
    machine = load_machine_config("bed_618")
    spec = parse_company_tile_spec(
        "R9.6*R9.6*8.6(-0.07/-0.09)*42.6*2.1(+0.01/-0.01)"
    )
    profile = build_tile_section(
        spec,
        outer_width=machine.section_outer_width,
        center_opening=machine.section_center_opening,
        slot_base_height=machine.section_slot_base_height,
    )
    debug_path = tmp_path / "same_r_tile_debug.dxf"

    write_dxf(profile, debug_path, output_mode="debug", machine_id=machine.machine_id)
    doc = ezdxf.readfile(debug_path)
    dimension_texts = [
        entity.dxf.text
        for entity in doc.modelspace().query("DIMENSION")
        if entity.dxf.layer == "DIMENSION"
    ]

    assert dimension_texts.count("R9.60") == 2


def test_bed_618_rectangular_block_groove_has_no_finished_r_form_dimension(tmp_path):
    machine = load_machine_config("bed_618")
    finished = parse_company_bread_spec("R9.6*42.6*8.6*2.1")
    preform = parse_block_spec("42.6*8.6(-0.07/-0.09)*2.1(+0.01/-0.01)")
    profile = build_block_guide_section(
        preform,
        slot_reference="width",
        slot_clearance=None,
        outer_width=machine.section_outer_width,
        slot_base_height=machine.section_slot_base_height,
        center_opening=machine.section_center_opening,
        finished_spec=finished,
        process_type="block_to_bread_rectangular",
    )
    debug_path = tmp_path / "rectangular_block_debug.dxf"

    write_dxf(profile, debug_path, output_mode="debug", machine_id=machine.machine_id)
    doc = ezdxf.readfile(debug_path)
    dimension_texts = [
        entity.dxf.text
        for entity in doc.modelspace().query("DIMENSION")
        if entity.dxf.layer == "DIMENSION"
    ]

    assert "R9.60" not in dimension_texts


def _dimension_measurements_by_text(doc) -> dict[str, list[float]]:
    measurements = {}
    for dimension in doc.modelspace():
        if dimension.dxftype() == "DIMENSION" and dimension.dxf.text:
            measurements.setdefault(dimension.dxf.text, []).append(dimension.get_measurement())
    return measurements


def _has_side_derived_horizontal_line(doc, y: float) -> bool:
    return any(
        entity.dxf.layer == "SIDE_DERIVED"
        and entity.dxftype() == "LINE"
        and entity.dxf.start.y == pytest.approx(y, abs=0.001)
        and entity.dxf.end.y == pytest.approx(y, abs=0.001)
        for entity in doc.modelspace()
    )


def _dimension_block_has_horizontal_line_at_y(doc, text: str, y: float) -> bool:
    for dimension in doc.modelspace().query("DIMENSION"):
        if dimension.dxf.text != text:
            continue
        if not dimension.dxf.hasattr("geometry") or dimension.dxf.geometry not in doc.blocks:
            return False
        return any(
            entity.dxftype() == "LINE"
            and entity.dxf.start.y == pytest.approx(y, abs=0.001)
            and entity.dxf.end.y == pytest.approx(y, abs=0.001)
            for entity in doc.blocks[dimension.dxf.geometry]
        )
    return False


def _dimension_by_text(doc, text: str):
    for dimension in doc.modelspace().query("DIMENSION"):
        if dimension.dxf.text == text:
            return dimension
    raise AssertionError(f"Missing dimension: {text}")


def _assert_r_dimensions_target_visible_slot_arcs(doc, profile) -> None:
    guide = profile.guide_spec
    center_x = 3241.3518694284135
    left_x = center_x - guide.guide_slot_width / 2.0
    right_x = center_x + guide.guide_slot_width / 2.0
    radius = profile.forming_spec.R_form
    dimensions = [
        dimension
        for dimension in doc.modelspace().query("DIMENSION")
        if dimension.dxf.text == f"R{radius:.2f}"
    ]
    assert len(dimensions) >= 2
    for dimension in dimensions:
        target = dimension.dxf.defpoint4
        assert left_x <= target.x <= right_x
        assert dimension.dxf.defpoint.y < target.y
        assert dimension.dxf.text_midpoint.x < left_x
        assert _dimension_block_has_radial_line_to_target(doc, dimension)


def _dimension_block_has_radial_line_to_target(doc, dimension) -> bool:
    if not dimension.dxf.hasattr("geometry") or dimension.dxf.geometry not in doc.blocks:
        return False
    center = dimension.dxf.defpoint
    target = dimension.dxf.defpoint4
    return any(
        entity.dxftype() == "LINE"
        and entity.dxf.start.x == pytest.approx(center.x, abs=0.001)
        and entity.dxf.start.y == pytest.approx(center.y, abs=0.001)
        and entity.dxf.end.x == pytest.approx(target.x, abs=0.001)
        and entity.dxf.end.y == pytest.approx(target.y, abs=0.001)
        for entity in doc.blocks[dimension.dxf.geometry]
    )

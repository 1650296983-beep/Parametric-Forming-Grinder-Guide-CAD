import pytest

from src.geometry import (
    ArcSegment,
    LineSegment,
    build_forming_spec,
    build_tile_section,
    calculate_guide_spec,
)
from src.spec_parser import ProductPreFormTolerance, ReliefSpec, parse_company_tile_spec


def test_build_tile_section_from_first_spec_rebuilds_control_points():
    spec = parse_company_tile_spec("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65")
    tile_section = build_tile_section(spec)
    profile = tile_section.finished_profile

    assert profile.params.R_outer == pytest.approx(17.45)
    assert profile.params.R_inner == pytest.approx(15.8)
    assert profile.params.chord_width == pytest.approx(6.2)
    assert profile.params.length == pytest.approx(15.5)
    assert profile.params.thickness == pytest.approx(1.65)

    assert profile.outer_left.x == pytest.approx(-3.1)
    assert profile.inner_left.x == pytest.approx(-3.1)
    assert profile.outer_right.x == pytest.approx(3.1)
    assert profile.inner_right.x == pytest.approx(3.1)
    assert tile_section.forming_radius_mode == "same_R_big_R"


def test_tile_section_has_outer_line_inner_line_closed_sequence():
    spec = parse_company_tile_spec("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65")
    profile = build_tile_section(spec).forming_profile

    assert len(profile.segments) == 4
    assert isinstance(profile.segments[0], ArcSegment)
    assert profile.segments[0].name == "outer_arc"
    assert isinstance(profile.segments[1], LineSegment)
    assert profile.segments[1].name == "right_side"
    assert isinstance(profile.segments[2], ArcSegment)
    assert profile.segments[2].name == "inner_arc"
    assert isinstance(profile.segments[3], LineSegment)
    assert profile.segments[3].name == "left_side"


def test_build_tile_section_requires_parsed_company_spec():
    with pytest.raises(TypeError):
        build_tile_section("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65")


def test_build_tile_section_allows_eccentric_different_r_with_explicit_thickness():
    spec = parse_company_tile_spec("R13.73*R17.13*4.50(-0.02/-0.05)*9.6*1.6")
    tile_section = build_tile_section(spec)

    finished = tile_section.finished_profile
    right_side = finished.segments[1]
    left_side = finished.segments[3]

    assert tile_section.forming_spec.R_form == pytest.approx(17.13)
    assert tile_section.guide_spec.guide_thickness == pytest.approx(1.78)
    assert isinstance(right_side, LineSegment)
    assert isinstance(left_side, LineSegment)
    assert right_side.length == pytest.approx(1.6)
    assert left_side.length == pytest.approx(1.6)


def test_build_tile_section_uses_explicit_wall_thickness_even_when_r_difference_differs():
    spec = parse_company_tile_spec("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.60")
    tile_section = build_tile_section(spec)
    finished = tile_section.finished_profile

    assert finished.segments[1].length == pytest.approx(1.60)
    assert finished.segments[3].length == pytest.approx(1.60)


def test_forming_profile_uses_same_big_r_and_thickness_gap():
    spec = parse_company_tile_spec("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65")
    forming = build_tile_section(spec).forming_profile

    outer_arc = forming.segments[0]
    right_side = forming.segments[1]
    inner_arc = forming.segments[2]
    left_side = forming.segments[3]

    assert outer_arc.radius == pytest.approx(17.45)
    assert inner_arc.radius == pytest.approx(17.45)
    assert forming.params.R_outer == pytest.approx(17.45)
    assert forming.params.R_inner == pytest.approx(17.45)
    assert forming.params.profile_type == "forming"
    assert forming.params.forming_radius_mode == "same_R_big_R"
    assert right_side.length == pytest.approx(1.65)
    assert left_side.length == pytest.approx(1.65)


def test_forming_spec_uses_larger_finished_radius():
    spec = parse_company_tile_spec("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65")
    forming_spec = build_forming_spec(spec)

    assert forming_spec.R_form == pytest.approx(17.45)
    assert forming_spec.R_form_outer == pytest.approx(17.45)
    assert forming_spec.R_form_inner == pytest.approx(17.45)


def test_guide_thickness_defaults_to_small_tile_clearance():
    spec = parse_company_tile_spec("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65")
    guide_spec = calculate_guide_spec(spec)
    tile_section = build_tile_section(spec)

    assert guide_spec.guide_thickness == pytest.approx(1.83)
    assert tile_section.guide_spec.guide_thickness == pytest.approx(1.83)


def test_guide_slot_width_uses_standard_clearance_for_0p02_width_tolerance():
    spec = parse_company_tile_spec("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65")
    guide_spec = calculate_guide_spec(spec)

    assert guide_spec.preform_tolerance.upper == pytest.approx(-0.02)
    assert guide_spec.preform_tolerance.lower == pytest.approx(-0.04)
    assert guide_spec.tolerance_slot_clearance == pytest.approx(0.04)
    assert guide_spec.guide_slot_width_raw == pytest.approx(6.21)
    assert guide_spec.guide_slot_width == pytest.approx(6.21)
    assert guide_spec.slot_width_tolerance == pytest.approx(0.01)
    assert guide_spec.slot_width_min == pytest.approx(6.20)
    assert guide_spec.slot_width_max == pytest.approx(6.22)


def test_guide_slot_width_uses_preform_tolerance_average_plus_clearance_when_input():
    spec = parse_company_tile_spec("R13.73*R17.13*4.50(-0.02/-0.05)*9.6*1.6")
    guide_spec = calculate_guide_spec(spec)

    assert guide_spec.preform_tolerance.upper == pytest.approx(-0.02)
    assert guide_spec.preform_tolerance.lower == pytest.approx(-0.05)
    assert guide_spec.product_preform_width_average == pytest.approx(4.465)
    assert guide_spec.tolerance_slot_clearance == pytest.approx(0.05)
    assert guide_spec.guide_slot_width_raw == pytest.approx(4.515)
    assert guide_spec.guide_slot_width == pytest.approx(4.52)
    assert guide_spec.slot_width_min == pytest.approx(4.51)
    assert guide_spec.slot_width_max == pytest.approx(4.53)
    assert guide_spec.slot_width_dimension_text == "4.52±0.01"


def test_product_preform_tolerance_and_actual_clearance_defaults():
    spec = parse_company_tile_spec("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65")
    guide_spec = calculate_guide_spec(spec)

    assert isinstance(guide_spec.preform_tolerance, ProductPreFormTolerance)
    assert guide_spec.preform_tolerance.upper == pytest.approx(-0.02)
    assert guide_spec.preform_tolerance.lower == pytest.approx(-0.04)
    assert guide_spec.product_preform_width_max == pytest.approx(6.18)
    assert guide_spec.product_preform_width_min == pytest.approx(6.16)
    assert guide_spec.total_clearance_min == pytest.approx(0.02)
    assert guide_spec.total_clearance_max == pytest.approx(0.06)
    assert guide_spec.side_clearance_min == pytest.approx(0.01)
    assert guide_spec.side_clearance_max == pytest.approx(0.03)


def test_relief_defaults_to_4_1_and_can_be_overridden():
    spec = parse_company_tile_spec("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65")
    default_guide = calculate_guide_spec(spec)
    custom_guide = calculate_guide_spec(spec, relief=ReliefSpec(relief_count=4, relief_size=0.6))

    assert default_guide.relief.relief_count == 4
    assert default_guide.relief.relief_size == pytest.approx(1.0)
    assert default_guide.relief.relief_label == "4-r0.5"
    assert custom_guide.relief.relief_label == "4-r0.3"


def test_guide_template_fixed_dimensions_are_retained():
    spec = parse_company_tile_spec("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65")
    guide_spec = calculate_guide_spec(spec)

    assert guide_spec.outer_width == pytest.approx(33.0)
    assert guide_spec.outer_height == pytest.approx(27.0)
    assert guide_spec.slot_base_height == pytest.approx(12.0)
    assert guide_spec.center_opening == pytest.approx(1.5)
    assert guide_spec.slot_center_offset == pytest.approx(0.0)

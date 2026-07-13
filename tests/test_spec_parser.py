import pytest

from src.spec_parser import (
    FinishedSpec,
    parse_block_spec,
    parse_company_bread_spec,
    parse_company_tile_spec,
    parse_relief_spec,
    validate_company_tile_spec,
)


def test_parse_first_company_tile_spec():
    spec = parse_company_tile_spec("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65")

    assert isinstance(spec, FinishedSpec)
    assert spec.R_outer_finished == pytest.approx(17.45)
    assert spec.R_inner_finished == pytest.approx(15.8)
    assert spec.R_outer == pytest.approx(17.45)
    assert spec.R_inner == pytest.approx(15.8)
    assert spec.chord_width == pytest.approx(6.2)
    assert spec.chord_width_tolerance_upper == pytest.approx(-0.02)
    assert spec.chord_width_tolerance_lower == pytest.approx(-0.04)
    assert spec.length == pytest.approx(15.5)
    assert spec.finished_thickness == pytest.approx(1.65)
    assert spec.computed_finished_thickness == pytest.approx(1.65)
    assert validate_company_tile_spec(spec) == ()


def test_parse_company_tile_spec_accepts_standard_x_separators():
    spec = parse_company_tile_spec("R46.3 XR46.3 x33(-0.02/-0.04)x34.5 x4")

    assert spec.R_outer_finished == pytest.approx(46.3)
    assert spec.R_inner_finished == pytest.approx(46.3)
    assert spec.chord_width == pytest.approx(33.0)
    assert spec.length == pytest.approx(34.5)
    assert spec.finished_thickness == pytest.approx(4.0)


def test_parse_company_bread_spec_uses_four_part_qg38002_order():
    spec = parse_company_bread_spec("R40.75*30*22*3.3")

    assert spec.finished_shape == "bread"
    assert spec.R_outer_finished == pytest.approx(40.75)
    assert spec.chord_width == pytest.approx(22.0)
    assert spec.length == pytest.approx(30.0)
    assert spec.finished_thickness == pytest.approx(3.3)
    assert spec.computed_finished_thickness == pytest.approx(3.3)


def test_parse_company_tile_spec_accepts_chord_width_tolerance():
    spec = parse_company_tile_spec("R13.73*R17.13*4.50(-0.02/-0.05)*9.6*1.6")

    assert spec.chord_width == pytest.approx(4.50)
    assert spec.chord_width_tolerance_upper == pytest.approx(-0.02)
    assert spec.chord_width_tolerance_lower == pytest.approx(-0.05)
    assert spec.has_chord_width_tolerance


def test_parse_company_tile_spec_accepts_thickness_tolerance():
    spec = parse_company_tile_spec(
        "R30*R30*17.4(+0/-0.02)*23.5*3.95(+0.02/-0.02)"
    )

    assert spec.thickness_tolerance_upper == pytest.approx(0.02)
    assert spec.thickness_tolerance_lower == pytest.approx(-0.02)
    assert spec.has_thickness_tolerance
    assert spec.preform_thickness_mid == pytest.approx(3.95)


def test_parse_rejects_wrong_format():
    with pytest.raises(ValueError):
        parse_company_tile_spec("17.45*15.8*6.2*15.5*1.65")


def test_parse_rejects_chord_width_without_tolerance():
    with pytest.raises(ValueError, match="chord_width must include upper/lower tolerance"):
        parse_company_tile_spec("R17.45*R15.8*6.2*15.5*1.65")


def test_parse_keeps_chord_width_distinct_from_length():
    spec = parse_company_tile_spec("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65")

    assert spec.chord_width == pytest.approx(6.2)
    assert spec.length == pytest.approx(15.5)
    assert spec.chord_width != spec.length


def test_spec_validation_allows_wall_thickness_independent_from_r_difference():
    spec = parse_company_tile_spec("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.60")

    errors = validate_company_tile_spec(spec)
    assert errors == ()


def test_parse_relief_spec_supports_default_and_custom_labels():
    default_relief = parse_relief_spec("4-1")
    custom_relief = parse_relief_spec("4-0.6")

    assert default_relief.relief_count == 4
    assert default_relief.relief_size == pytest.approx(1.0)
    assert default_relief.relief_label == "4-r0.5"
    assert custom_relief.relief_count == 4
    assert custom_relief.relief_size == pytest.approx(0.6)
    assert custom_relief.relief_label == "4-r0.3"


def test_parse_block_spec_accepts_length_tolerance():
    spec = parse_block_spec("9.02(-0.02/-0.05)*6*1.2")

    assert spec.length == pytest.approx(9.02)
    assert spec.length_tolerance_upper == pytest.approx(-0.02)
    assert spec.length_tolerance_lower == pytest.approx(-0.05)
    assert spec.width == pytest.approx(6.0)
    assert spec.thickness == pytest.approx(1.2)
    assert spec.has_length_tolerance


def test_parse_block_spec_accepts_width_and_thickness_tolerances():
    spec = parse_block_spec("12.4*5.6(-0.035/-0.055)*1.96(+0.01/-0.01)")

    assert spec.width_tolerance_upper == pytest.approx(-0.035)
    assert spec.width_tolerance_lower == pytest.approx(-0.055)
    assert spec.thickness_tolerance_upper == pytest.approx(0.01)
    assert spec.thickness_tolerance_lower == pytest.approx(-0.01)
    assert spec.has_width_tolerance
    assert spec.has_thickness_tolerance
    assert spec.thickness_mid == pytest.approx(1.96)


def test_parse_finished_tile_without_width_tolerance_when_process_supplies_preform():
    spec = parse_company_tile_spec(
        "R15.9*R14.25*5.6*12.4*1.65",
        require_chord_tolerance=False,
    )

    assert spec.chord_width == pytest.approx(5.6)
    assert not spec.has_chord_width_tolerance

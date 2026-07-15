import pytest

from src.geometry import build_tile_section
from src.side_view import build_side_view_geometry
from src.spec_parser import parse_company_tile_spec


def test_side_projected_slot_height_is_12p50_from_formula():
    tile_section = build_tile_section(parse_company_tile_spec("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65"))
    side_view = build_side_view_geometry(tile_section)
    derived = side_view.derived

    assert derived.side_projected_slot_height == pytest.approx(12.50)
    assert derived.side_projected_slot_height == pytest.approx(
        derived.slot_base_height + derived.side_cut_in_allowance
    )


def test_side_clearance_height_uses_global_cut_in_and_opening_limit():
    tile_section = build_tile_section(parse_company_tile_spec("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65"))
    side_view = build_side_view_geometry(tile_section)
    derived = side_view.derived

    assert derived.guide_thickness == pytest.approx(1.83)
    assert derived.wheel_cut_allowance == pytest.approx(0.366605623)
    assert derived.side_clearance_height == pytest.approx(13.536605623)
    assert derived.side_clearance_height == pytest.approx(
        derived.guide_outer_height
        - derived.slot_base_height
        - derived.guide_thickness
        + derived.wheel_cut_allowance
    )


def test_side_clearance_height_changes_with_guide_thickness():
    thin = build_tile_section(parse_company_tile_spec("R12.50*R11.30*5.50(-0.02/-0.04)*12.0*1.20"))
    thick = build_tile_section(parse_company_tile_spec("R25.00*R22.80*8.50(-0.02/-0.04)*20.0*2.20"))

    thin_clearance = build_side_view_geometry(thin).derived.side_clearance_height
    thick_clearance = build_side_view_geometry(thick).derived.side_clearance_height

    assert thin_clearance == pytest.approx(13.837859141)
    assert thick_clearance == pytest.approx(13.234925836)
    assert thin_clearance > thick_clearance


def test_side_fixed_template_dimensions_do_not_change_with_product_spec():
    first = build_side_view_geometry(
        build_tile_section(parse_company_tile_spec("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65"))
    ).template
    second = build_side_view_geometry(
        build_tile_section(parse_company_tile_spec("R25.00*R22.80*8.50(-0.02/-0.04)*20.0*2.20"))
    ).template

    assert first == second
    assert first.wheel_radius == pytest.approx(80.0)

from dataclasses import replace

from src.block_geometry import build_block_guide_section
from src.cavity_projection import derive_cavity_projection_profile
from src.geometry import build_block_to_bread_section, build_tile_section
from src.spec_parser import (
    parse_block_spec,
    parse_company_bread_spec,
    parse_company_tile_spec,
)


def test_projection_line_count_uses_pre_grinding_shape_not_finished_shape():
    finished_bread = parse_company_bread_spec("R9.6*8.6*42.6*2.1")
    pre_grinding_block = parse_block_spec(
        "42.6*8.6(-0.07/-0.09)*2.1(+0.01/-0.01)"
    )
    block_profile = build_block_guide_section(
        pre_grinding_block,
        slot_reference="width",
        finished_spec=finished_bread,
        process_type="block_to_bread_rectangular",
    )

    projection = derive_cavity_projection_profile(
        block_profile,
        block_profile.guide_spec.guide_thickness,
    )

    assert projection.pre_grinding_shape == "block"
    assert projection.line_count == 2
    assert projection.surface_roles == ("lower_plane", "upper_plane")


def test_projection_line_count_is_three_for_pre_grinding_bread_shape():
    finished_bread = parse_company_bread_spec("R30*23.5*17.4*3.95")
    pre_grinding_block = parse_block_spec(
        "23.5*17.4(-0.07/-0.09)*3.95(+0.01/-0.01)"
    )
    bread_geometry = build_block_to_bread_section(
        finished_bread,
        pre_grinding_block,
    )
    pre_grinding_bread = replace(
        bread_geometry,
        preform_block_spec=None,
        process_type="tile",
    )

    projection = derive_cavity_projection_profile(
        pre_grinding_bread,
        pre_grinding_bread.guide_spec.guide_thickness,
    )

    assert projection.pre_grinding_shape == "bread"
    assert projection.line_count == 3


def test_projection_line_count_is_four_for_pre_grinding_tile_shape():
    pre_grinding_tile_spec = parse_company_tile_spec(
        "R30*R30*17.4(+0/-0.02)*23.5*3.95(+0.02/-0.02)"
    )
    pre_grinding_tile = build_tile_section(pre_grinding_tile_spec)

    projection = derive_cavity_projection_profile(
        pre_grinding_tile,
        pre_grinding_tile.guide_spec.guide_thickness,
    )

    assert projection.pre_grinding_shape == "tile"
    assert projection.line_count == 4

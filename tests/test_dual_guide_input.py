import pytest

from src.block_geometry import BlockGuideSection
from src.dual_guide_input import build_dual_guide_profile_from_input
from src.geometry import TileSection
from src.machine_config import load_machine_config


def test_bread_finished_with_block_pregrinding_uses_block_profile():
    machine = load_machine_config("triple_double_down_up_up")
    finished, pre_grinding, profile, decision = (
        build_dual_guide_profile_from_input(
            {
                "finished_product_spec": "R40*23.5*17.4*3.95",
                "pre_grinding_spec": "23.5*17.4(+0/-0.02)*3.95(+0.02/-0.02)",
                "finished_product_shape": "bread",
                "pre_grinding_shape": "block",
                "guide_profile_source": "pre_grinding_spec",
                "slot_reference": "width",
            },
            machine,
        )
    )

    assert finished.finished_shape == "bread"
    assert pre_grinding.width == pytest.approx(17.4)
    assert isinstance(profile, BlockGuideSection)
    assert profile.process_type == "block_to_bread_rectangular"
    assert profile.guide_spec.guide_slot_width == pytest.approx(17.43)
    assert decision.final_section_profile_type == "rectangular_block"
    assert decision.R_form_source == "finished_product_target_only_not_guide_profile"


def test_tile_finished_with_block_pregrinding_uses_big_r_bread_profile():
    machine = load_machine_config("triple_double_down_up_up")
    _, _, profile, decision = build_dual_guide_profile_from_input(
        {
            "finished_product_spec": "R30*R28*17.4*23.5*3.95",
            "pre_grinding_spec": "23.5*17.4(+0/-0.02)*3.95(+0.02/-0.02)",
            "finished_product_shape": "tile",
            "pre_grinding_shape": "block",
            "guide_profile_source": "finished_product_big_r_with_pre_grinding_block",
        },
        machine,
    )

    assert isinstance(profile, TileSection)
    assert profile.process_type == "block_to_tile"
    assert profile.arc_side == "lower"
    assert profile.forming_spec.R_form == pytest.approx(30.0)
    assert decision.final_section_profile_type == "flat_arc_lower_big_r_block_preform"
    assert decision.R_form_source == "max(finished_product_R_outer, finished_product_R_inner)"


def test_same_r_tile_requires_explicit_pregrinding_shape():
    machine = load_machine_config("triple_double_down_up_up")
    _, _, profile, decision = build_dual_guide_profile_from_input(
        {
            "finished_product_spec": "R30*R30*17.4*23.5*3.95",
            "pre_grinding_spec": "R30*R30*17.4(+0/-0.02)*23.5*3.95(+0.02/-0.02)",
            "finished_product_shape": "tile",
            "pre_grinding_shape": "same_r_tile",
            "guide_profile_source": "pre_grinding_spec",
        },
        machine,
    )

    assert isinstance(profile, TileSection)
    assert profile.process_type == "tile"
    assert decision.final_section_profile_type == "same_r_tile"

    with pytest.raises(ValueError):
        build_dual_guide_profile_from_input(
            {
                "finished_product_spec": "R30*R30*17.4*23.5*3.95",
                "pre_grinding_spec": "R30*R30*17.4(+0/-0.02)*23.5*3.95(+0.02/-0.02)",
                "finished_product_shape": "tile",
                "pre_grinding_shape": "block",
                "guide_profile_source": "pre_grinding_spec",
            },
            machine,
        )

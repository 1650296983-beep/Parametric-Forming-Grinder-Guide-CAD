from dataclasses import replace

import pytest

from src.guide_design_input import (
    build_single_guide_profile_from_input,
    resolve_opposite_side,
    side_vector_in_template,
)
from src.machine_config import load_machine_config


def _base_input(**overrides):
    payload = {
        "machine_type": "triple_single_down_up",
        "guide_rail_type": "single_guide",
        "wheel_sequence": ["下", "上"],
        "first_wheel_side": "lower",
        "template_coordinate_system": "section_xy_y_up",
        "finished_product_shape": "bread",
        "pre_grinding_shape": "block",
        "guide_profile_source": "pre_grinding_spec_rectangular_envelope",
        "finished_spec_order": "radius_width_length_thickness",
        "relief": "4-1",
    }
    payload.update(overrides)
    return payload


def test_example_1_keeps_double_r_finished_shape_separate_from_block_envelope():
    machine = load_machine_config("triple_single_down_up")
    finished, preform, profile, decision = build_single_guide_profile_from_input(
        _base_input(
            finished_product_spec="R16.3*R14.3*5*20*2",
            pre_grinding_spec="20*5(-0.01/-0.03)*2.25(+0.01/-0.01)",
            finished_product_shape="tile",
            finished_spec_order="outer_r_inner_r_width_length_thickness",
            guide_profile_source="finished_product_big_r_with_pre_grinding_block",
        ),
        machine,
    )

    assert finished.R_outer_finished == pytest.approx(16.3)
    assert finished.R_inner_finished == pytest.approx(14.3)
    assert preform.width == pytest.approx(5.0)
    assert profile.process_type == "block_to_tile"
    assert profile.guide_spec.chord_width == pytest.approx(5.0)
    assert profile.guide_spec.guide_slot_width == pytest.approx(5.02)
    assert profile.guide_spec.guide_thickness == pytest.approx(2.37)
    assert profile.forming_spec.R_form == pytest.approx(16.3)
    assert profile.arc_side == "lower"
    assert decision.arc_side == "lower"
    assert decision.flat_side == "upper"
    assert decision.arc_center_side == "upper"
    assert decision.final_section_profile_type == "flat_arc_big_r_block_preform"
    assert decision.R_form_source == "max(finished_product_R_outer, finished_product_R_inner)"


def test_example_2_builds_rectangular_groove_from_block_preform():
    machine = load_machine_config("triple_single_down_up")
    finished, preform, profile, decision = build_single_guide_profile_from_input(
        _base_input(
            finished_product_spec="R9.6*8.6*42.6*2.1",
            pre_grinding_spec="42.6*8.6(-0.07/-0.09)*2.1(+0.01/-0.01)",
        ),
        machine,
    )

    assert finished.chord_width == pytest.approx(8.6)
    assert finished.length == pytest.approx(42.6)
    assert preform.width == pytest.approx(8.6)
    assert profile.process_type == "block_to_bread_rectangular"
    assert profile.guide_spec.chord_width == pytest.approx(8.6)
    assert profile.guide_spec.guide_slot_width == pytest.approx(8.56)
    assert profile.finished_spec.R_outer_finished == pytest.approx(9.6)
    assert decision.groove_profile == "rectangular_groove"
    assert decision.arc_radius is None
    assert decision.flat_side is None
    assert decision.arc_side is None
    assert decision.arc_center_side is None


def test_example_3_does_not_replace_preform_width_with_finished_width():
    machine = load_machine_config("triple_single_down_up")
    finished, preform, profile, decision = build_single_guide_profile_from_input(
        _base_input(
            finished_product_spec="R24.7*12*46*2.1",
            pre_grinding_spec="46*12.2(-0.09/-0.11)*2.1(+0.01/-0.01)",
        ),
        machine,
    )

    assert finished.chord_width == pytest.approx(12.0)
    assert finished.length == pytest.approx(46.0)
    assert preform.width == pytest.approx(12.2)
    assert profile.guide_spec.chord_width == pytest.approx(12.2)
    assert profile.guide_spec.guide_slot_width == pytest.approx(12.14)
    assert profile.finished_spec.R_outer_finished == pytest.approx(24.7)
    assert profile.process_length == pytest.approx(46.0)
    assert decision.warnings == ()
    assert "split" not in str(decision.as_dict()).lower()
    assert "two_pieces" not in str(decision.as_dict()).lower()


def test_first_wheel_opposite_side_uses_template_transform():
    machine = load_machine_config("triple_single_down_up")
    transformed = replace(
        machine,
        template_axis_rotation_deg=90.0,
        template_mirror_x=True,
    )

    first_vector = side_vector_in_template("upper", transformed)
    center_vector = tuple(-value for value in first_vector)

    assert resolve_opposite_side("upper") == "lower"
    assert first_vector == pytest.approx((-1.0, 0.0))
    assert center_vector == pytest.approx((1.0, 0.0))


def test_canonical_dual_spec_input_auto_resolves_bread_width_length_order():
    machine = load_machine_config("triple_single_down_up")
    finished, preform, profile, decision = build_single_guide_profile_from_input(
        {
            "machine_type": "triple_single_down_up",
            "guide_rail_type": "single_guide",
            "wheel_sequence": ["下", "上"],
            "first_wheel_side": "lower",
            "template_coordinate_system": "section_xy_y_up",
            "pre_grinding_spec": "46*12.2(-0.09/-0.11)*2.1(+0.01/-0.01)",
            "finished_spec": "R24.7*12*46*2.1",
            "product_shape_before": "rectangular_block",
            "product_shape_after": "bread_shape",
            "tolerance": {
                "width_upper_deviation": -0.09,
                "width_lower_deviation": -0.11,
                "thickness_upper_deviation": 0.01,
                "thickness_lower_deviation": -0.01,
            },
        },
        machine,
    )

    assert finished.length == pytest.approx(46.0)
    assert finished.chord_width == pytest.approx(12.0)
    assert preform.width == pytest.approx(12.2)
    assert profile.process_length == pytest.approx(46.0)
    assert decision.finished_spec_order == "radius_width_length_thickness"
    assert decision.groove_profile == "rectangular_groove"
    assert decision.arc_radius is None
    assert decision.dimension_source["slot_width"].startswith("pre_grinding_spec")
    assert decision.as_dict()["finished_spec"] == "R24.7*12*46*2.1"
    assert decision.as_dict()["product_shape_before"] == "rectangular_block"
    assert "split" not in str(decision.as_dict()).lower()


def test_tolerance_metadata_cannot_override_pre_grinding_spec():
    machine = load_machine_config("triple_single_down_up")
    with pytest.raises(ValueError, match="tolerance.width_upper_deviation conflicts"):
        build_single_guide_profile_from_input(
            {
                "machine_type": "triple_single_down_up",
                "guide_rail_type": "single_guide",
                "wheel_sequence": ["下", "上"],
                "first_wheel_side": "lower",
                "template_coordinate_system": "section_xy_y_up",
                "pre_grinding_spec": "46*12.2(-0.09/-0.11)*2.1(+0.01/-0.01)",
                "finished_spec": "R24.7*12*46*2.1",
                "product_shape_before": "rectangular_block",
                "product_shape_after": "bread_shape",
                "tolerance": {"width_upper_deviation": -0.08},
            },
            machine,
        )


def test_explicit_input_rejects_shape_inference_and_direction_conflicts():
    machine = load_machine_config("triple_single_down_up")
    with pytest.raises(ValueError, match="requires fields"):
        build_single_guide_profile_from_input(
            {"finished_product_spec": "R24.7*12*46*2.1"},
            machine,
        )

    with pytest.raises(ValueError, match="does not match"):
        build_single_guide_profile_from_input(
            _base_input(
                finished_product_spec="R24.7*12*46*2.1",
                pre_grinding_spec="46*12.2(-0.09/-0.11)*2.1(+0.01/-0.01)",
                first_wheel_side="upper",
            ),
            machine,
        )

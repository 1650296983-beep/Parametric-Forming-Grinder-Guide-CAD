import pytest

from src.groove_profile import (
    determine_groove_profile,
    resolve_arc_center_side,
)


def _rules(**overrides):
    rules = {
        "block_to_tile_groove_profile": "flat_arc_groove",
        "block_to_bread_groove_profile": "rectangular_groove",
        "flat_arc_surface_side": "lower",
        "flat_surface_side": "upper",
        "flat_arc_center_side": "upper",
    }
    rules.update(overrides)
    return rules


def test_single_r_bread_with_block_preform_uses_rectangular_envelope():
    decision = determine_groove_profile(
        "rectangular_block",
        "bread_shape",
        1,
        "triple_single_down_up",
        "single_guide",
        ["下", "上"],
        _rules(),
        finished_radii=[9.6],
        first_wheel_side="lower",
    )

    assert decision.groove_profile == "rectangular_groove"
    assert decision.arc_radius is None
    assert decision.flat_side is None
    assert decision.arc_side is None
    assert decision.arc_center_side is None
    assert decision.dimension_source["slot_width"].startswith("pre_grinding_spec")
    assert decision.dimension_source["finished_target_radius"] == "finished_spec.single_R"
    assert decision.confidence == "high"
    assert decision.warnings == ()


def test_double_r_tile_rule_applies_without_machine_specific_profile_guessing():
    decision = determine_groove_profile(
        "rectangular_block",
        "tile_shape",
        2,
        "unapproved_machine",
        "single_guide",
        ["下", "上"],
        _rules(block_to_tile_groove_profile=None),
        finished_radii=[16.3, 14.3],
        first_wheel_side="lower",
    )

    assert decision.groove_profile == "flat_arc_groove"
    assert decision.arc_side == "lower"
    assert decision.arc_center_side == "upper"


def test_double_r_tile_uses_configured_flat_arc_and_larger_finished_radius():
    decision = determine_groove_profile(
        "block",
        "tile",
        2,
        "triple_single_down_up",
        "single_guide",
        ["下", "上"],
        _rules(),
        finished_radii=[16.3, 14.3],
        first_wheel_side="lower",
    )

    assert decision.groove_profile == "flat_arc_groove"
    assert decision.arc_radius == pytest.approx(16.3)
    assert decision.arc_side == "lower"
    assert decision.flat_side == "upper"
    assert decision.arc_center_side == "upper"
    assert decision.guide_profile_source == "finished_product_big_r_with_pre_grinding_block"


@pytest.mark.parametrize(
    ("first_wheel_side", "expected"),
    (("upper", "lower"), ("lower", "upper"), ("left", "right"), ("right", "left")),
)
def test_arc_center_side_is_opposite_first_wheel(first_wheel_side, expected):
    assert resolve_arc_center_side(first_wheel_side) == expected


def test_conflicting_template_direction_requires_manual_review():
    decision = determine_groove_profile(
        "rectangular_block",
        "tile_shape",
        2,
        "triple_single_down_up",
        "single_guide",
        ["下", "上"],
        _rules(flat_arc_center_side="lower"),
        finished_radii=[24.7, 22.7],
        first_wheel_side="lower",
    )

    assert decision.groove_profile == "manual_review"
    assert "conflicts" in decision.warnings[0]

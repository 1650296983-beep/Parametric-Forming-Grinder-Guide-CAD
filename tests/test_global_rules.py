from dataclasses import replace

import ezdxf
import pytest

from src.dual_guide_engine import DualGuideTemplateEngine
from src.dxf_writer import write_dxf
from src.global_rules import (
    BLOCK_THICKNESS_CLEARANCE,
    HIGH_REQUIREMENT_THICKNESS_CLEARANCE,
    ProcessOptions,
    WHEEL_NOTCH_OPENING_RATIO,
    wheel_notch_opening_limit,
)
from src.guide_design_input import build_single_guide_profile_from_input
from src.machine_config import load_machine_config
from src.web_api import DesignInput, _build_profile_for_design


BASE_INPUT = {
    "finished_spec": "R9.6*8.6*42.6*2.1",
    "pre_grinding_spec": "42.6*8.6(-0.07/-0.09)*2.1(+0.01/-0.01)",
    "product_shape_after": "bread_shape",
    "product_shape_before": "rectangular_block",
    "relief": "4-0.6",
}


def test_wheel_notch_opening_limit_is_sixty_percent_of_product_length() -> None:
    assert WHEEL_NOTCH_OPENING_RATIO == pytest.approx(0.6)
    assert wheel_notch_opening_limit(1.0) == pytest.approx(0.6)
    assert wheel_notch_opening_limit(9.1) == pytest.approx(5.46)
    with pytest.raises(ValueError, match="大于 0"):
        wheel_notch_opening_limit(0.0)


def test_explicit_process_options_control_clearances_globally() -> None:
    machine = load_machine_config("double_head_up_up")
    common = {
        **BASE_INPUT,
        "machine_type": machine.machine_id,
        "guide_rail_type": machine.guide_type,
        "wheel_sequence": list(machine.wheel_positions),
        "first_wheel_side": "upper",
        "template_coordinate_system": machine.template_coordinate_system,
    }
    _, _, normal, _ = build_single_guide_profile_from_input(common, machine)
    _, _, high_requirement, _ = build_single_guide_profile_from_input(
        {**common, "single_side_or_high_requirement": True},
        machine,
    )
    _, _, high_symmetry, _ = build_single_guide_profile_from_input(
        {**common, "high_symmetry_requirement": True},
        machine,
    )
    _, _, large_tile, _ = build_single_guide_profile_from_input(
        {**common, "large_tile_clearance": True},
        machine,
    )

    assert normal.guide_spec.thickness_clearance_mid_value == pytest.approx(
        BLOCK_THICKNESS_CLEARANCE
    )
    assert high_requirement.guide_spec.thickness_clearance_mid_value == pytest.approx(
        HIGH_REQUIREMENT_THICKNESS_CLEARANCE
    )
    assert high_symmetry.guide_spec.tolerance_slot_clearance == pytest.approx(0.03)
    assert large_tile.guide_spec.tolerance_slot_clearance == pytest.approx(0.08)


def test_slot_clearance_options_are_mutually_exclusive() -> None:
    with pytest.raises(ValueError, match="不能同时选择"):
        ProcessOptions(
            high_symmetry_requirement=True,
            large_tile_clearance=True,
        )


def test_custom_wheel_radius_updates_single_and_dual_outputs(tmp_path) -> None:
    radius = 90.0
    single_machine = replace(
        load_machine_config("double_head_up_down"),
        wheel_radius=radius,
    )
    single_input = {
        **BASE_INPUT,
        "machine_type": single_machine.machine_id,
        "guide_rail_type": single_machine.guide_type,
        "wheel_sequence": list(single_machine.wheel_positions),
        "first_wheel_side": "upper",
        "template_coordinate_system": single_machine.template_coordinate_system,
        "wheel_radius": radius,
    }
    _, _, single_profile, _ = build_single_guide_profile_from_input(
        single_input,
        single_machine,
    )
    single_path = tmp_path / "single_r90.dxf"
    write_dxf(
        single_profile,
        single_path,
        output_mode="release",
        machine_config_override=single_machine,
    )
    assert _wheel_arc_count(single_path, radius) == 2
    assert _wheel_radius_dimension_count(single_path, radius) == 2

    dual_machine = replace(
        load_machine_config("triple_double_up_up_up"),
        wheel_radius=radius,
    )
    design = DesignInput(
        machine_type=dual_machine.machine_id,
        guide_rail_type=dual_machine.guide_type,
        wheel_sequence=list(dual_machine.wheel_positions),
        first_wheel_side="upper",
        template_coordinate_system=dual_machine.template_coordinate_system,
        finished_spec=BASE_INPUT["finished_spec"],
        pre_grinding_spec=BASE_INPUT["pre_grinding_spec"],
        product_shape_after="bread_shape",
        product_shape_before="rectangular_block",
        relief=BASE_INPUT["relief"],
        wheel_radius=radius,
    )
    _, _, dual_profile, _ = _build_profile_for_design(
        design,
        dual_machine,
    )
    dual_path = tmp_path / "dual_r90.dxf"
    result = DualGuideTemplateEngine(dual_machine).write_dxf(
        dual_profile,
        dual_path,
        output_mode="release",
    )
    assert _wheel_arc_count(dual_path, radius) == 6
    assert _wheel_radius_dimension_count(dual_path, radius) == 6
    assert result["parametric_duplicate_audit"]["release_allowed"] is True


def _wheel_arc_count(path, radius: float) -> int:
    doc = ezdxf.readfile(path)
    return len(
        [
            arc
            for arc in doc.modelspace().query("ARC")
            if arc.dxf.layer == "SIDE_TEMPLATE"
            and float(arc.dxf.radius) == pytest.approx(radius)
        ]
    )


def _wheel_radius_dimension_count(path, radius: float) -> int:
    doc = ezdxf.readfile(path)
    return len(
        [
            dimension
            for dimension in doc.modelspace().query("DIMENSION")
            if dimension.dxf.text == f"R{radius:.2f}"
            and float(dimension.get_measurement()) == pytest.approx(radius)
        ]
    )

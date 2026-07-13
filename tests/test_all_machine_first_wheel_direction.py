from pathlib import Path

import ezdxf
import pytest

from src.block_geometry import BlockGuideSection
from src.dxf_writer import write_dxf
from src.dual_guide_engine import DualGuideTemplateEngine
from src.dual_guide_input import build_dual_guide_profile_from_input
from src.dual_guide_release_audit import build_dimension_definition_point_audit
from src.guide_design_input import build_single_guide_profile_from_input
from src.inspection import inspect_release_dxf
from src.machine_config import load_machine_config


SINGLE_GUIDE_MACHINES = (
    ("bed_618", "upper"),
    ("double_head_up_down", "upper"),
    ("double_head_up_up", "upper"),
    ("triple_single_down_up", "lower"),
    ("triple_single_up_up", "upper"),
)

DUAL_GUIDE_MACHINES = (
    ("triple_double_down_up_up", "lower"),
    ("triple_double_up_up_up", "upper"),
)


@pytest.mark.parametrize(("machine_id", "first_wheel_side"), SINGLE_GUIDE_MACHINES)
def test_single_r_bread_with_block_preform_is_rectangular_on_every_single_guide_machine(
    tmp_path: Path,
    machine_id: str,
    first_wheel_side: str,
) -> None:
    machine = load_machine_config(machine_id)
    _, _, profile, decision = build_single_guide_profile_from_input(
        {
            "machine_type": machine.machine_id,
            "guide_rail_type": machine.guide_type,
            "wheel_sequence": list(machine.wheel_positions),
            "first_wheel_side": first_wheel_side,
            "template_coordinate_system": machine.template_coordinate_system,
            "finished_spec": "R9.6*8.6*42.6*2.1",
            "finished_spec_order": "radius_width_length_thickness",
            "pre_grinding_spec": "42.6*8.6(-0.07/-0.09)*2.1(+0.01/-0.01)",
            "product_shape_after": "bread_shape",
            "product_shape_before": "rectangular_block",
        },
        machine,
    )

    assert isinstance(profile, BlockGuideSection)
    assert profile.process_type == "block_to_bread_rectangular"
    assert decision.groove_profile == "rectangular_groove"
    assert decision.arc_radius is None

    release = tmp_path / f"{machine_id}_bread.dxf"
    write_dxf(profile, release, output_mode="release", machine_id=machine_id)
    dimension_audit = build_dimension_definition_point_audit(
        release,
        profile,
        machine,
    )
    inspection = inspect_release_dxf(profile, machine, release)
    assert dimension_audit["release_allowed"] is True
    assert inspection["release_allowed"] is True


@pytest.mark.parametrize(("machine_id", "expected_arc_side"), SINGLE_GUIDE_MACHINES)
def test_double_r_block_preform_follows_first_wheel_on_every_single_guide_machine(
    tmp_path: Path,
    machine_id: str,
    expected_arc_side: str,
) -> None:
    machine = load_machine_config(machine_id)
    finished, _, profile, decision = build_single_guide_profile_from_input(
        {
            "machine_type": machine.machine_id,
            "guide_rail_type": machine.guide_type,
            "wheel_sequence": list(machine.wheel_positions),
            "first_wheel_side": expected_arc_side,
            "template_coordinate_system": machine.template_coordinate_system,
            "finished_spec": "R16.3*R14.3*5*20*2",
            "pre_grinding_spec": "20*5(-0.01/-0.03)*2.25(+0.01/-0.01)",
            "product_shape_after": "tile_shape",
            "product_shape_before": "rectangular_block",
        },
        machine,
    )

    assert finished.finished_shape == "tile"
    assert profile.arc_side == expected_arc_side
    assert decision.arc_side == expected_arc_side
    assert decision.arc_center_side != expected_arc_side

    release = tmp_path / f"{machine_id}.dxf"
    write_dxf(profile, release, output_mode="release", machine_id=machine_id)
    dimension_audit = build_dimension_definition_point_audit(
        release,
        profile,
        machine,
    )
    inspection = inspect_release_dxf(profile, machine, release)
    assert dimension_audit["release_allowed"] is True
    assert inspection["release_allowed"] is True
    _assert_main_r_arcs_are_short_production_segments(release, profile.forming_spec.R_form)


@pytest.mark.parametrize(("machine_id", "expected_arc_side"), DUAL_GUIDE_MACHINES)
def test_double_r_block_preform_follows_first_wheel_on_every_dual_guide_machine(
    tmp_path: Path,
    machine_id: str,
    expected_arc_side: str,
) -> None:
    machine = load_machine_config(machine_id)
    _, _, profile, _ = build_dual_guide_profile_from_input(
        {
            "finished_product_spec": "R30*R28*17.4*23.5*3.95",
            "pre_grinding_spec": "23.5*17.4(+0/-0.02)*3.95(+0.02/-0.02)",
            "finished_product_shape": "tile",
            "pre_grinding_shape": "block",
            "guide_profile_source": "finished_product_big_r_with_pre_grinding_block",
        },
        machine,
    )

    assert profile.arc_side == expected_arc_side
    release = tmp_path / f"{machine_id}.dxf"
    result = DualGuideTemplateEngine(machine).write_dxf(
        profile,
        release,
        output_mode="release",
    )
    dimension_audit = build_dimension_definition_point_audit(
        release,
        profile,
        machine,
    )
    assert result["synchronized"] is True
    assert dimension_audit["release_allowed"] is True
    _assert_main_r_arcs_are_short_production_segments(release, profile.forming_spec.R_form)


def _assert_main_r_arcs_are_short_production_segments(release: Path, radius: float) -> None:
    doc = ezdxf.readfile(release)
    sweeps = [
        (float(arc.dxf.end_angle) - float(arc.dxf.start_angle)) % 360.0
        for arc in doc.modelspace().query("ARC")
        if arc.dxf.layer == "PARAM_SLOT" and abs(float(arc.dxf.radius) - radius) <= 0.001
    ]
    assert sweeps
    assert all(0.001 < sweep < 180.0 for sweep in sweeps)

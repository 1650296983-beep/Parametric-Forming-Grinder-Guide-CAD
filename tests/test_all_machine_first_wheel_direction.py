from pathlib import Path
from math import cos, radians, sqrt

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
    _assert_block_to_tile_relief_topology(release, profile)


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
    _assert_block_to_tile_relief_topology(release, profile)


def _assert_main_r_arcs_are_short_production_segments(release: Path, radius: float) -> None:
    doc = ezdxf.readfile(release)
    sweeps = [
        (float(arc.dxf.end_angle) - float(arc.dxf.start_angle)) % 360.0
        for arc in doc.modelspace().query("ARC")
        if arc.dxf.layer == "PARAM_SLOT" and abs(float(arc.dxf.radius) - radius) <= 0.001
    ]
    assert sweeps
    assert all(0.001 < sweep < 180.0 for sweep in sweeps)


def _assert_block_to_tile_relief_topology(release: Path, profile) -> None:
    """Verify the process-owned 4-1 + 2-R0.50 topology on every machine."""
    doc = ezdxf.readfile(release)
    slot_arcs = [
        arc
        for arc in doc.modelspace().query("ARC")
        if arc.dxf.layer == "PARAM_SLOT"
    ]
    relief_arcs = [arc for arc in slot_arcs if abs(float(arc.dxf.radius) - 0.5) <= 0.001]
    main_arcs = [
        arc
        for arc in slot_arcs
        if abs(float(arc.dxf.radius) - profile.forming_spec.R_form) <= 0.001
    ]

    assert main_arcs
    relief_groups = _group_relief_arcs_by_section(relief_arcs, profile.guide_spec.outer_width)
    for relief_group in relief_groups:
        assert len(relief_group) == 6
        min_x = min(float(arc.dxf.center.x) for arc in relief_group)
        max_x = max(float(arc.dxf.center.x) for arc in relief_group)
        center_x = (min_x + max_x) / 2.0
        side_arcs = [
            arc
            for arc in relief_group
            if abs(float(arc.dxf.center.x) - min_x) <= 0.001
            or abs(float(arc.dxf.center.x) - max_x) <= 0.001
        ]
        center_arcs = [arc for arc in relief_group if arc not in side_arcs]
        assert len(side_arcs) == 4
        assert len(center_arcs) == 2
        for arc in side_arcs:
            sweep = (float(arc.dxf.end_angle) - float(arc.dxf.start_angle)) % 360.0
            midpoint_x = float(arc.dxf.center.x) + float(arc.dxf.radius) * cos(
                radians(float(arc.dxf.start_angle) + sweep / 2.0)
            )
            assert sweep > 180.0
            if abs(float(arc.dxf.center.x) - min_x) <= 0.001:
                assert midpoint_x < min_x - 0.001
            else:
                assert midpoint_x > max_x + 0.001

        base_y = min(float(arc.dxf.center.y) for arc in side_arcs)
        top_y = max(float(arc.dxf.center.y) for arc in side_arcs)
        opening_half = profile.guide_spec.center_opening / 2.0
        expected_center_xs = sorted(
            (
                center_x - opening_half - 0.5,
                center_x + opening_half + 0.5,
            )
        )
        if profile.arc_side == "upper":
            half_slot = profile.guide_spec.guide_slot_width / 2.0
            main_center_y = top_y - sqrt(profile.forming_spec.R_form**2 - half_slot**2)
            expected_center_y = main_center_y + sqrt(
                (profile.forming_spec.R_form + 0.5) ** 2 - (opening_half + 0.5) ** 2
            )
            main_group = [
                arc
                for arc in main_arcs
                if float(arc.dxf.center.x) == pytest.approx(center_x, abs=0.001)
                and float(arc.dxf.center.y) == pytest.approx(main_center_y, abs=0.001)
            ]
            assert len(main_group) == 2
            assert all(float(arc.dxf.center.y) < top_y - 0.001 for arc in main_group)
        else:
            expected_center_y = top_y + 0.5
            main_center_y = base_y + sqrt(
                profile.forming_spec.R_form**2 - (profile.guide_spec.guide_slot_width / 2.0) ** 2
            )
            main_group = [
                arc
                for arc in main_arcs
                if float(arc.dxf.center.x) == pytest.approx(center_x, abs=0.001)
                and float(arc.dxf.center.y) == pytest.approx(main_center_y, abs=0.001)
            ]
            assert len(main_group) == 1
            assert all(float(arc.dxf.center.y) > base_y + 0.001 for arc in main_group)

        actual_center_arcs = sorted(center_arcs, key=lambda arc: float(arc.dxf.center.x))
        for expected_x, arc in zip(expected_center_xs, actual_center_arcs):
            assert float(arc.dxf.center.x) == pytest.approx(expected_x, abs=0.001)
            assert float(arc.dxf.center.y) == pytest.approx(expected_center_y, abs=0.001)


def _group_relief_arcs_by_section(arcs, outer_width: float):
    sorted_arcs = sorted(arcs, key=lambda arc: float(arc.dxf.center.x))
    groups = []
    for arc in sorted_arcs:
        if not groups:
            groups.append([arc])
            continue
        previous_x = float(groups[-1][-1].dxf.center.x)
        if float(arc.dxf.center.x) - previous_x > outer_width:
            groups.append([])
        groups[-1].append(arc)
    if len(groups) > 1:
        return groups

    # Dual-guide templates stack their two sections vertically at the same X
    # coordinates.  Split those otherwise-overlapping X groups by their relief
    # band; a single section spans at most guide thickness plus both R0.50
    # transition allowances.
    sorted_by_y = sorted(arcs, key=lambda arc: float(arc.dxf.center.y))
    y_groups = []
    threshold = max(outer_width / 2.0, 1.0)
    for arc in sorted_by_y:
        if not y_groups:
            y_groups.append([arc])
            continue
        previous_y = float(y_groups[-1][-1].dxf.center.y)
        if float(arc.dxf.center.y) - previous_y > threshold:
            y_groups.append([])
        y_groups[-1].append(arc)
    return y_groups


def test_upper_block_to_tile_single_guide_does_not_route_through_bread_builder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.dxf_writer as dxf_writer

    machine = load_machine_config("double_head_up_down")
    _, _, profile, _ = build_single_guide_profile_from_input(
        {
            "machine_type": machine.machine_id,
            "guide_rail_type": machine.guide_type,
            "wheel_sequence": list(machine.wheel_positions),
            "first_wheel_side": "upper",
            "template_coordinate_system": machine.template_coordinate_system,
            "finished_spec": "R16.3*R14.3*5*20*2",
            "pre_grinding_spec": "20*5(-0.01/-0.03)*2.25(+0.01/-0.01)",
            "product_shape_after": "tile_shape",
            "product_shape_before": "rectangular_block",
        },
        machine,
    )

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("block_to_tile must not route through the bread entry point")

    monkeypatch.setattr(dxf_writer, "_add_down_up_bread_slot_entities", fail_if_called)
    write_dxf(profile, tmp_path / "upper_single_tile.dxf", output_mode="release", machine_id=machine.machine_id)


def test_upper_block_to_tile_dual_guide_does_not_route_through_bread_builder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.dual_guide_engine as dual_guide_engine

    machine = load_machine_config("triple_double_up_up_up")
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

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("block_to_tile must not route through the bread entry point")

    monkeypatch.setattr(dual_guide_engine, "_add_down_up_bread_slot_entities", fail_if_called)
    DualGuideTemplateEngine(machine).write_dxf(
        profile,
        tmp_path / "upper_dual_tile.dxf",
        output_mode="release",
    )

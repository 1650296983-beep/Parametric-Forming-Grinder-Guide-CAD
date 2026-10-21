import ezdxf
import pytest

from src.dual_guide_release_audit import (
    _dimension_text_measurement_mismatches,
    build_dimension_definition_point_audit,
)
from src.dxf_writer import write_dxf
from src.guide_design_input import build_single_guide_profile_from_input
from src.machine_config import load_machine_config


def test_text_measurement_gate_rejects_rotated_side_dimension():
    """A rotated side dim can bind geometry yet display the wrong value."""
    mismatches = _dimension_text_measurement_mismatches(
        [
            {
                "dimension_handle": "A",
                "dimension_role": "other_release_dimension",
                "display_text": "7.24",
                "measurement": 33.246,
            },
            {
                "dimension_handle": "B",
                "dimension_role": "slot_width",
                "display_text": "19.04±0.01",
                "measurement": 19.04,
            },
            {
                "dimension_handle": "C",
                "dimension_role": "relief",
                "display_text": "4-∅1.00",
                "measurement": 1.0,
            },
            {
                "dimension_handle": "D",
                "dimension_role": "fixed_section_height_27",
                "display_text": "<>",
                "measurement": 27.0,
            },
        ]
    )

    assert [item["dimension_handle"] for item in mismatches] == ["A"]


def _wide_bread_block_profile(machine):
    _, _, profile, _ = build_single_guide_profile_from_input(
        {
            "machine_type": machine.machine_id,
            "guide_rail_type": machine.guide_type,
            "wheel_sequence": list(machine.wheel_positions),
            "first_wheel_side": "upper",
            "template_coordinate_system": machine.template_coordinate_system,
            "finished_spec": "R16.7*19*40*6.5",
            "pre_grinding_spec": "40*19(+0.01/-0.01)*6.55(+0.01/-0.01)",
            "product_shape_after": "bread_shape",
            "product_shape_before": "rectangular_block",
            "relief": "4-1",
        },
        machine,
    )
    return profile


def test_unclassified_dimension_inside_rebuilt_slot_blocks_release(tmp_path):
    """Old template values must not survive without a bound role."""
    machine = load_machine_config("double_head_up_down")
    profile = _wide_bread_block_profile(machine)
    path = tmp_path / "slot.dxf"
    write_dxf(profile, path, output_mode="release", machine_id=machine.machine_id)
    audit = build_dimension_definition_point_audit(path, profile, machine)
    slot = next(
        entry
        for entry in audit["dimensions"]
        if entry["dimension_role"] == "slot_width"
    )
    thickness = next(
        entry
        for entry in audit["dimensions"]
        if entry["dimension_role"] == "guide_thickness"
    )
    left, right = sorted((slot["defpoint2"][0], slot["defpoint3"][0]))
    bottom, top = sorted(
        (thickness["defpoint2"][1], thickness["defpoint3"][1])
    )
    middle_y = (bottom + top) / 2.0

    doc = ezdxf.readfile(path)
    dimension = doc.modelspace().add_linear_dim(
        base=((left + right) / 2.0, middle_y + 1.0),
        p1=(left + 1.0, middle_y),
        p2=(left + 3.0, middle_y),
        angle=0,
        text="2.00",
    )
    dimension.render()
    doc.saveas(path)

    audit = build_dimension_definition_point_audit(path, profile, machine)

    assert audit["orphan_parametric_dimensions"], "stale in-slot dim not flagged"
    assert not audit["release_allowed"]

from dataclasses import replace

import ezdxf
import pytest

from src.dual_guide_release_audit import build_dimension_definition_point_audit
from src.dxf_writer import write_dxf
from src.guide_design_input import build_single_guide_profile_from_input
from src.machine_config import load_machine_config


@pytest.mark.parametrize(
    ("machine_id", "base_height"),
    (("double_head_up_down", 12.0), ("double_head_up_up", 12.0), ("double_head_up_up", 18.0)),
)
@pytest.mark.parametrize("relief", ("4-0.5", "4-0.25"))
def test_narrow_block_rebinds_template_dimensions(tmp_path, machine_id, base_height, relief):
    machine = replace(load_machine_config(machine_id), section_slot_base_height=base_height)
    _, _, profile, _ = build_single_guide_profile_from_input(
        {
            "machine_type": machine.machine_id,
            "guide_rail_type": machine.guide_type,
            "wheel_sequence": list(machine.wheel_positions),
            "first_wheel_side": "upper",
            "template_coordinate_system": machine.template_coordinate_system,
            "finished_spec": "R13.2*3.05*5.6*0.9",
            "pre_grinding_spec": "5.6*3.05（-0.04/-0.055）*0.93（+0.01/-0.01）",
            "product_shape_after": "bread_shape",
            "product_shape_before": "rectangular_block",
            "high_symmetry_requirement": True,
            "relief": relief,
        },
        machine,
    )
    candidate = tmp_path / "candidate.dxf"
    write_dxf(profile, candidate, output_mode="release", machine_config_override=machine)

    audit = build_dimension_definition_point_audit(candidate, profile, machine)
    assert audit["release_allowed"], [d for d in audit["dimensions"] if not d["bound_to_geometry"]]
    assert profile.guide_spec.guide_slot_width == pytest.approx(3.03)
    assert profile.guide_spec.guide_thickness == pytest.approx(1.05)

    doc = ezdxf.readfile(candidate)
    source_handle = "202C7DF" if machine_id == "double_head_up_down" else "202AB5F"
    base_dimension = doc.entitydb[source_handle]
    assert base_dimension.get_measurement() == pytest.approx(base_height)
    assert abs(base_dimension.dxf.defpoint2.y - base_dimension.dxf.defpoint3.y) == pytest.approx(base_height)
    # The visible extension lines must start at the rebuilt definition points.
    lines = list(doc.blocks[base_dimension.dxf.geometry].query("LINE"))
    for point in (base_dimension.dxf.defpoint2, base_dimension.dxf.defpoint3):
        assert any(
            abs(line.dxf.start.x - point.x) < 0.001 or abs(line.dxf.end.x - point.x) < 0.001
            for line in lines
        )

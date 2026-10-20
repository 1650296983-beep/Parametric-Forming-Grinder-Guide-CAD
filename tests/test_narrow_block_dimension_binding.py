from dataclasses import replace

import ezdxf
import pytest
from fastapi import HTTPException

from src.block_geometry import BlockReliefGeometryError, build_block_guide_section
from src.dual_guide_release_audit import build_dimension_definition_point_audit
from src.dxf_writer import write_dxf
from src.guide_design_input import build_single_guide_profile_from_input
from src.machine_config import load_machine_config
from src.spec_parser import parse_block_spec
from src.web_api import DesignInput, GenerationRequest, generate_design, validate_design
import src.web_api as web_api


@pytest.mark.parametrize("machine_id", ("double_head_up_up", "double_head_up_down"))
def test_default_relief_is_rejected_before_subprocess_or_output(tmp_path, monkeypatch, machine_id):
    machine = load_machine_config(machine_id)
    design = DesignInput(
        machine_type=machine.machine_id,
        guide_rail_type=machine.guide_type,
        wheel_sequence=list(machine.wheel_positions),
        first_wheel_side="upper",
        template_coordinate_system=machine.template_coordinate_system,
        finished_spec="R13.2*2.55*5.6*0.9",
        pre_grinding_spec="5.6*2.55（-0.04/-0.055）*0.93（+0.01/-0.01）",
        product_shape_after="bread_shape",
        product_shape_before="rectangular_block",
        high_symmetry_requirement=True,
        relief="4-1",
    )
    monkeypatch.setattr(web_api, "WEB_OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(web_api.subprocess, "run", lambda *a, **kw: pytest.fail("invalid geometry started a child"))
    for call in (lambda: validate_design(design), lambda: generate_design(GenerationRequest(design=design))):
        with pytest.raises(HTTPException) as rejection:
            call()
        assert rejection.value.status_code == 422
        assert "槽宽 2.53 mm" in rejection.value.detail
        assert "直径 1.00 mm（R0.50）" in rejection.value.detail
        limit = 0.75 + 2.0
        assert f"槽宽大于 {limit:.2f} mm" in rejection.value.detail
    assert list(tmp_path.iterdir()) == []


def test_block_relief_thickness_limit_is_checked_during_input():
    with pytest.raises(BlockReliefGeometryError, match="导轨厚度 0.62 mm"):
        build_block_guide_section(parse_block_spec("8*6(-0.01/-0.02)*0.5"))


@pytest.mark.parametrize("relief", ("4-0.5", "4-0.25"))
def test_fixed_center_reliefs_still_reject_overlap_after_scaling_opening(relief):
    from src.spec_parser import parse_relief_spec

    with pytest.raises(BlockReliefGeometryError, match="中心固定 R0.50"):
        build_block_guide_section(
            parse_block_spec("5.6*1.75(-0.04/-0.055)*0.93(+0.01/-0.01)"),
            slot_reference="width",
            slot_clearance=0.03,
            center_opening=2.0,
            relief=parse_relief_spec(relief),
        )


@pytest.mark.parametrize(
    ("machine_id", "base_height", "nominal_width", "slot_width"),
    (("double_head_up_down", 12.0, 3.05, 3.03), ("double_head_up_up", 12.0, 3.65, 3.63), ("double_head_up_up", 18.0, 3.65, 3.63)),
)
@pytest.mark.parametrize("relief", ("4-0.5", "4-0.25"))
def test_narrow_block_rebinds_template_dimensions(tmp_path, machine_id, base_height, nominal_width, slot_width, relief):
    machine = replace(load_machine_config(machine_id), section_slot_base_height=base_height)
    _, _, profile, _ = build_single_guide_profile_from_input(
        {
            "machine_type": machine.machine_id,
            "guide_rail_type": machine.guide_type,
            "wheel_sequence": list(machine.wheel_positions),
            "first_wheel_side": "upper",
            "template_coordinate_system": machine.template_coordinate_system,
            "finished_spec": f"R13.2*{nominal_width}*5.6*0.9",
            "pre_grinding_spec": f"5.6*{nominal_width}（-0.04/-0.055）*0.93（+0.01/-0.01）",
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
    assert profile.guide_spec.guide_slot_width == pytest.approx(slot_width)
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

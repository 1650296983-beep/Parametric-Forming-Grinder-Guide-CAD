from dataclasses import replace
from math import sqrt

import ezdxf
import pytest

from src.block_geometry import build_block_guide_section
from src.cavity_projection import derive_cavity_projection_profile, horizontal_arc_gap
from src.dual_guide_engine import DualGuideTemplateEngine
from src.dual_guide_input import build_dual_guide_profile_from_input
from src.dual_guide_release_audit import build_dimension_definition_point_audit
from src.dimension_roles import SECTION_CENTER_OPENING, get_dimension_role
from src.dxf_writer import write_dxf
from src.global_rules import section_center_opening
from src.machine_config import load_machine_config
from src.spec_parser import parse_block_spec
from src.web_api import DesignInput, validate_design, _build_profile_for_design


@pytest.mark.parametrize("maximum", (1.0, 1.5, 2.0))
@pytest.mark.parametrize("width", (0.85, 1.67, 3.03, 3.33, 3.34, 5.0, 6.66, 6.67, 12.0))
def test_scaled_opening_respects_ratio_rounding_and_machine_cap(width, maximum):
    opening = section_center_opening(width, maximum)
    assert opening < width / 3.0
    assert opening <= maximum
    assert opening <= width * 0.30 + 1e-10
    assert min(maximum, width * 0.30) - opening < 0.01 + 1e-10
    assert opening * 100 == pytest.approx(round(opening * 100))
    if width == 3.03:
        assert opening == 0.90


@pytest.mark.parametrize("value", (0, -1, float("nan"), float("inf")))
def test_opening_rejects_invalid_width_and_cap(value):
    with pytest.raises(ValueError):
        section_center_opening(value)
    with pytest.raises(ValueError):
        section_center_opening(3.03, value)


@pytest.mark.parametrize("machine_id", (
    "bed_618", "double_head_up_up", "double_head_up_down",
    "triple_single_up_up", "triple_single_down_up",
    "triple_double_up_up_up", "triple_double_down_up_up",
))
def test_all_machine_inputs_calculate_narrow_opening_and_retain_original_caps(machine_id, tmp_path):
    machine = load_machine_config(machine_id)
    design = DesignInput(
        machine_type=machine_id, guide_rail_type=machine.guide_type,
        wheel_sequence=list(machine.wheel_positions),
        first_wheel_side="lower" if machine.wheel_positions[0] == "下" else "upper",
        template_coordinate_system=machine.template_coordinate_system,
        finished_spec="R13.2*3.05*5.6*0.9",
        pre_grinding_spec="5.6*3.05(-0.04/-0.055)*0.93(+0.01/-0.01)",
        product_shape_after="bread_shape", product_shape_before="rectangular_block",
        high_symmetry_requirement=True, relief="4-1",
    )
    result = validate_design(design)
    assert result["derived"]["slot_width"] == 3.03
    assert result["derived"]["center_opening"] == 0.90
    assert result["machine"]["section_center_opening_max"] == machine.section_center_opening
    assert result["machine"]["section_center_opening_ratio"] == 0.30
    _, spec, profile, _ = _build_profile_for_design(design, machine)
    wide = replace(profile.guide_spec, chord_width=12.0)
    assert wide.center_opening == machine.section_center_opening
    if machine.guide_sections == 2:
        generated = DualGuideTemplateEngine(machine).write_debug_release_and_report(profile, spec, tmp_path)
        path = generated["release_dxf"]
    else:
        path = tmp_path / "candidate.dxf"
        write_dxf(profile, path, output_mode="release", machine_config_override=machine)
    audit = build_dimension_definition_point_audit(path, profile, machine)
    assert audit["release_allowed"], [item for item in audit["dimensions"] if not item["bound_to_geometry"]]
    doc = ezdxf.readfile(path)
    openings = [dim for dim in doc.modelspace().query("DIMENSION") if get_dimension_role(dim) == SECTION_CENTER_OPENING]
    # Older single-guide dimensions may be identified by their measurement.
    if not openings:
        openings = [dim for dim in doc.modelspace().query("DIMENSION") if abs(float(dim.get_measurement()) - 0.90) < 0.001]
    assert len(openings) == machine.guide_sections
    assert all(float(dim.get_measurement()) == pytest.approx(0.90) for dim in openings)


@pytest.mark.parametrize("profile_type", ("block", "block_to_tile", "same_r_tile"))
@pytest.mark.parametrize("length,radius", ((9.1, 80.0), (200.0, 90.0)))
def test_down_up_up_upper_wheels_reach_cavity_in_section_two_and_assembly(tmp_path, profile_type, length, radius):
    machine = replace(load_machine_config("triple_double_down_up_up"), wheel_radius=radius)
    engine = DualGuideTemplateEngine(machine)
    if profile_type == "block":
        spec = parse_block_spec(f"{length}*4*3")
        profile = build_block_guide_section(spec, slot_reference="width", outer_width=machine.section_outer_width)
    else:
        data = {
            "finished_product_spec": f"R30*R28*6*{length}*2",
            "pre_grinding_spec": f"{length}*6(-0.01/-0.02)*3(+0.01/-0.01)",
            "finished_product_shape": "tile", "pre_grinding_shape": "block",
            "guide_profile_source": "finished_product_big_r_with_pre_grinding_block",
        }
        if profile_type == "same_r_tile":
            data.update(pre_grinding_spec=f"R30*R30*6(-0.01/-0.02)*{length}*3", pre_grinding_shape="same_r_tile", guide_profile_source="pre_grinding_spec")
        _, spec, profile, _ = build_dual_guide_profile_from_input(data, machine)
    result = engine.write_debug_release_and_report(profile, spec, tmp_path)
    doc = ezdxf.readfile(result["release_dxf"])
    projection = derive_cavity_projection_profile(profile, profile.guide_spec.guide_thickness)
    expected_opening = min(2 * sqrt(radius**2 - (radius - profile.process_thickness * 0.6)**2), length * 0.6)
    expected_depth = radius - sqrt(radius**2 - (expected_opening / 2)**2)
    template = engine.build_template()
    upper_views = (
        (template.guide_section_2.side_bounds, template.guide_section_2.side_centerline_x_values),
        (template.assembly_side_bounds, template.assembly_side_centerline_x_values[1:]),
    )
    for bounds, centers in upper_views:
        cavity_y = bounds[2] + machine.section_slot_base_height + max(projection.offsets)
        for center_x in centers:
            arc = next(arc for arc in doc.modelspace().query('ARC[layer=="SIDE_TEMPLATE"]') if abs(arc.dxf.center.x - center_x) < 0.001 and arc.dxf.center.y > bounds[3])
            assert cavity_y - (arc.dxf.center.y - arc.dxf.radius) == pytest.approx(expected_depth, abs=0.000001)
            gap = horizontal_arc_gap(arc, cavity_y)
            assert gap is not None
            assert gap[1] - gap[0] == pytest.approx(expected_opening, abs=0.001)
            for line in doc.modelspace().query('LINE[layer=="SIDE_CAVITY"]'):
                if abs(line.dxf.start.y - cavity_y) <= 0.001:
                    lo, hi = sorted((line.dxf.start.x, line.dxf.end.x))
                    assert hi <= gap[0] + 0.001 or lo >= gap[1] - 0.001
    audit = result["report"]["wheel_notch_geometry_audit"]
    assert len(audit["wheels"]) == 6
    assert audit["release_allowed"]
    assert result["report"]["dimension_definition_point_audit"]["release_allowed"]


def test_missing_upper_wheel_update_cannot_promote_release(tmp_path, monkeypatch):
    machine = load_machine_config("triple_double_down_up_up")
    spec = parse_block_spec("9.1*4*3")
    profile = build_block_guide_section(spec)
    engine = DualGuideTemplateEngine(machine)
    monkeypatch.setattr(engine, "_update_side_r80_arcs", lambda *args: None)
    with pytest.raises(ValueError):
        engine.write_debug_release_and_report(profile, spec, tmp_path)
    assert not (tmp_path / "release.dxf").exists()

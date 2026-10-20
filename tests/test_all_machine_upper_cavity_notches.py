"""Regress the short same-R crown gap and exercise block/long wheel paths."""
from dataclasses import replace
from math import sqrt

import ezdxf
import pytest

from src.cavity_projection import derive_cavity_projection_profile
from src.dual_guide_engine import DualGuideTemplateEngine
from src.dual_guide_input import build_dual_guide_profile_from_input
from src.dual_guide_release_audit import build_dimension_definition_point_audit
from src.dxf_writer import write_dxf
from src.guide_design_input import build_single_guide_profile_from_input
from src.inspection import inspect_release_dxf, audit_upper_wheel_projection_openings
from src.machine_config import load_machine_config
from src.side_view import build_side_view_geometry
from src.side_view_config import SideViewTemplateConfig

MACHINES = (
    "bed_618", "double_head_up_down", "double_head_up_up",
    "triple_single_down_up", "triple_single_up_up",
    "triple_double_up_up_up", "triple_double_down_up_up",
)


def _profile(machine, kind, length):
    data = {
        "finished_product_spec": f"R30*R28*6*{length}*2",
        "pre_grinding_spec": f"{length}*6(-0.01/-0.02)*2.25(+0.01/-0.01)",
        "finished_product_shape": "tile", "pre_grinding_shape": "block",
        "guide_profile_source": "finished_product_big_r_with_pre_grinding_block",
        "relief": "4-1",
        "machine_type": machine.machine_id, "guide_rail_type": machine.guide_type,
        "wheel_sequence": list(machine.wheel_positions),
        "first_wheel_side": "lower" if machine.wheel_positions[0] == "下" else "upper",
        "template_coordinate_system": machine.template_coordinate_system,
    }
    if kind == "same_r_tile":
        data.update(pre_grinding_spec=f"R30*R30*6(-0.01/-0.02)*{length}*2.25(+0.01/-0.01)", pre_grinding_shape="same_r_tile", guide_profile_source="pre_grinding_spec")
    elif kind == "block_bread":
        data.update(finished_product_spec=f"R30*{length}*6*2", finished_product_shape="bread", guide_profile_source="pre_grinding_spec")
    if machine.guide_sections == 1:
        data.pop("guide_profile_source")
    builder = build_dual_guide_profile_from_input if machine.guide_sections == 2 else build_single_guide_profile_from_input
    _, spec, profile, _ = builder(data, machine)
    return spec, profile


@pytest.mark.parametrize("machine_id", MACHINES)
@pytest.mark.parametrize("kind", ("block_bread", "block_tile", "same_r_tile"))
@pytest.mark.parametrize("length,radius", ((9.1, 80.0), (120.0, 90.0)))
def test_every_machine_upper_wheel_is_limited_at_all_actual_cavity_projections(tmp_path, machine_id, kind, length, radius):
    machine = replace(load_machine_config(machine_id), wheel_radius=radius)
    spec, profile = _profile(machine, kind, length)
    if machine.guide_sections == 2:
        result = DualGuideTemplateEngine(machine).write_debug_release_and_report(profile, spec, tmp_path)
        candidate = result["release_dxf"]
        audits = [wheel["projection_opening_audit"] for wheel in result["report"]["wheel_notch_geometry_audit"]["wheels"]]
    else:
        candidate = tmp_path / "candidate.dxf"
        write_dxf(profile, candidate, output_mode="release", machine_config_override=machine)
        inspection = inspect_release_dxf(profile, machine, candidate)
        assert inspection["release_allowed"], [check for check in inspection["checks"] if not check["ok"]]
        doc = ezdxf.readfile(candidate)
        audits = audit_upper_wheel_projection_openings(doc, profile, machine)
        side = build_side_view_geometry(profile, template=SideViewTemplateConfig(wheel_radius=radius), layout=machine.side_layout)
        top_y = side.layout.lower_y + side.derived.slot_base_height + max(derive_cavity_projection_profile(profile, side.derived.guide_thickness).offsets)
        expected = min(2 * sqrt(radius**2 - (radius - profile.process_thickness * 0.6)**2), length * 0.6)
        for audit in audits:
            top = max(audit["projection_levels"], key=lambda entry: entry["cavity_y"])
            assert top["cavity_y"] == pytest.approx(top_y, abs=1e-6)
            assert top["opening"] == pytest.approx(expected, abs=1e-5)
    assert audits and all(audit["release_allowed"] for audit in audits)
    expected_count = derive_cavity_projection_profile(profile, profile.guide_spec.guide_thickness).line_count
    assert all(len(audit["projection_levels"]) == expected_count for audit in audits)
    assert all(level["opening"] is None or level["opening"] <= length * 0.6 + 0.001 for audit in audits for level in audit["projection_levels"])
    dimensions = build_dimension_definition_point_audit(candidate, profile, machine)
    assert dimensions["release_allowed"], [item for item in dimensions["dimensions"] if not item["bound_to_geometry"]]


@pytest.mark.parametrize("machine_id", MACHINES)
def test_old_endpoint_only_upper_wheel_is_rejected_at_crown(tmp_path, machine_id):
    machine = load_machine_config(machine_id)
    spec, profile = _profile(machine, "same_r_tile", 9.1)
    if machine.guide_sections == 2:
        engine = DualGuideTemplateEngine(machine)
        result = engine.write_debug_release_and_report(profile, spec, tmp_path)
        doc = ezdxf.readfile(result["release_dxf"])
    else:
        candidate = tmp_path / "candidate.dxf"
        write_dxf(profile, candidate, output_mode="release", machine_config_override=machine)
        doc = ezdxf.readfile(candidate)
    sagitta = max(derive_cavity_projection_profile(profile, profile.guide_spec.guide_thickness).offsets) - profile.guide_spec.guide_thickness
    # Reintroduce the exact defect: limit at the upper arc endpoint instead of crown.
    for arc in doc.modelspace().query('ARC[layer=="SIDE_TEMPLATE"]'):
        if arc.dxf.center.y > machine.side_layout.upper_y:
            arc.dxf.center = (arc.dxf.center.x, arc.dxf.center.y - sagitta, 0)
    if machine.guide_sections == 2:
        audit = engine._audit_wheel_notch_geometry(doc.modelspace(), profile)
        assert not audit["release_allowed"]
        audits = [entry["projection_opening_audit"] for entry in audit["wheels"] if entry["wheel_position"] == "上"]
        assert any(not item["release_allowed"] for item in audits)
    else:
        audits = audit_upper_wheel_projection_openings(doc, profile, machine)
        assert any(not audit["release_allowed"] for audit in audits)
        doc.saveas(candidate)
        inspection = inspect_release_dxf(profile, machine, candidate)
        upper_check = next(check for check in inspection["checks"] if check["name"] == "upper_wheel_notch_safety")
        assert not upper_check["ok"]

    # The endpoint measurement still satisfies the old gate, while the crown
    # exceeds it. Reject for that precise reason, rather than a missing entity.
    for audit in audits:
        levels = sorted(audit["projection_levels"], key=lambda entry: entry["cavity_y"])
        assert levels[-2]["opening"] == pytest.approx(5.46, abs=0.001)
        assert levels[-1]["opening"] > 5.46 + 0.001
        assert not levels[-1]["within_limit"]

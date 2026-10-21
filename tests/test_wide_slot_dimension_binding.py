import pytest

from src.dual_guide_engine import DualGuideTemplateEngine
from src.dual_guide_input import build_dual_guide_profile_from_input
from src.dual_guide_release_audit import build_dimension_definition_point_audit
from src.dxf_writer import write_dxf
from src.guide_design_input import build_single_guide_profile_from_input
from src.machine_config import load_machine_config


def _write_and_audit(tmp_path, machine, profile):
    path = tmp_path / f"{machine.machine_id}.dxf"
    write_dxf(profile, path, output_mode="release", machine_id=machine.machine_id)
    return build_dimension_definition_point_audit(path, profile, machine)


def _roles(audit):
    return {
        entry["dimension_role"]: entry
        for entry in audit["dimensions"]
        if entry["dimension_role"] != "other_release_dimension"
    }


@pytest.mark.parametrize(
    ("machine_id", "first_wheel_side"),
    (
        ("double_head_up_down", "upper"),
        ("double_head_up_up", "upper"),
        ("triple_single_down_up", "lower"),
        ("triple_single_up_up", "upper"),
    ),
)
def test_wide_bread_block_keeps_real_guide_thickness_dimension(
    tmp_path,
    machine_id,
    first_wheel_side,
):
    """A slot far wider than the template's must not leave the old 2.10 dim.

    The archived thickness dimension sits at a fixed offset from the historical
    slot edge.  Once the new slot is more than 5 mm wider, matching by that
    offset missed it, so the old ``2.10`` stayed and the real 6.67 thickness
    dimension was never created.
    """
    machine = load_machine_config(machine_id)
    _, _, profile, _ = build_single_guide_profile_from_input(
        {
            "machine_type": machine.machine_id,
            "guide_rail_type": machine.guide_type,
            "wheel_sequence": list(machine.wheel_positions),
            "first_wheel_side": first_wheel_side,
            "template_coordinate_system": machine.template_coordinate_system,
            "finished_spec": "R16.7*19*40*6.5",
            "pre_grinding_spec": "40*19(+0.01/-0.01)*6.55(+0.01/-0.01)",
            "product_shape_after": "bread_shape",
            "product_shape_before": "rectangular_block",
            "relief": "4-1",
        },
        machine,
    )
    audit = _write_and_audit(tmp_path, machine, profile)

    assert audit["release_allowed"], [
        entry for entry in audit["dimensions"] if not entry["bound_to_geometry"]
    ]
    assert profile.guide_spec.guide_slot_width == pytest.approx(19.04)
    assert profile.guide_spec.guide_thickness == pytest.approx(6.67)
    thickness = _roles(audit)["guide_thickness"]
    assert thickness["measurement"] == pytest.approx(6.67)
    assert thickness["display_text"] == "6.67"
    assert not [
        entry
        for entry in audit["dimensions"]
        if entry["measurement"] is not None
        and abs(entry["measurement"] - 2.10) < 0.01
    ]


def test_narrow_same_r_radius_dimension_stays_on_retained_arc(tmp_path):
    """The radius leader must not overshoot the arc trimmed by the relief."""
    machine = load_machine_config("double_head_up_up")
    _, _, profile, _ = build_single_guide_profile_from_input(
        {
            "machine_type": machine.machine_id,
            "guide_rail_type": machine.guide_type,
            "wheel_sequence": list(machine.wheel_positions),
            "first_wheel_side": "upper",
            "template_coordinate_system": machine.template_coordinate_system,
            "finished_spec": "R6*R6*4*40*2.5",
            "pre_grinding_spec": "R6*R6*4(+0.01/-0.01)*40*2.55(+0.01/-0.01)",
            "product_shape_after": "tile_shape",
            "product_shape_before": "same_r_tile",
            "relief": "4-1",
        },
        machine,
    )
    audit = _write_and_audit(tmp_path, machine, profile)

    assert audit["release_allowed"], [
        entry for entry in audit["dimensions"] if not entry["bound_to_geometry"]
    ]
    assert _roles(audit)["R_form"]["bound_to_geometry"]


def test_same_r_tile_fixed_slot_base_uses_machine_datum(tmp_path):
    """The fixed 12 mm base is a datum line, not a point on the arc cavity."""
    machine = load_machine_config("triple_single_down_up")
    _, _, profile, _ = build_single_guide_profile_from_input(
        {
            "machine_type": machine.machine_id,
            "guide_rail_type": machine.guide_type,
            "wheel_sequence": list(machine.wheel_positions),
            "first_wheel_side": "lower",
            "template_coordinate_system": machine.template_coordinate_system,
            "finished_spec": "R12.9*R12.9*8.6*40*6.55",
            "pre_grinding_spec": (
                "R12.9*R12.9*8.6(+0.01/-0.01)*40*6.6(+0.01/-0.01)"
            ),
            "product_shape_after": "tile_shape",
            "product_shape_before": "same_r_tile",
            "relief": "4-1",
        },
        machine,
    )
    audit = _write_and_audit(tmp_path, machine, profile)

    assert audit["release_allowed"], [
        entry for entry in audit["dimensions"] if not entry["bound_to_geometry"]
    ]
    slot_base = _roles(audit)["fixed_slot_base_12"]
    assert slot_base["measurement"] == pytest.approx(12.0)
    assert slot_base["binding_mode"] == "fixed_machine_slot_base_datum"


@pytest.mark.parametrize("kind", ("bread_block", "same_r_tile"))
def test_dual_upper_upper_wide_slot_has_no_stale_small_dimension(tmp_path, kind):
    """Wide slots must still select the slot thickness dim, not the outer step."""
    machine = load_machine_config("triple_double_up_up_up")
    if kind == "bread_block":
        data = {
            "finished_product_spec": "R16*24*40*2.5",
            "pre_grinding_spec": "40*24(+0.01/-0.01)*2.55(+0.01/-0.01)",
            "finished_product_shape": "bread",
            "pre_grinding_shape": "block",
            "guide_profile_source": "pre_grinding_spec",
        }
    else:
        data = {
            "finished_product_spec": "R36*R36*24*40*2.5",
            "pre_grinding_spec": (
                "R36*R36*24(+0.01/-0.01)*40*2.55(+0.01/-0.01)"
            ),
            "finished_product_shape": "tile",
            "pre_grinding_shape": "same_r_tile",
            "guide_profile_source": "pre_grinding_spec",
        }
    data["relief"] = "4-1"
    _, spec, profile, _ = build_dual_guide_profile_from_input(data, machine)
    output = tmp_path / kind
    result = DualGuideTemplateEngine(machine).write_debug_release_and_report(
        profile,
        spec,
        output,
    )
    report = result["report"]
    audit = report["dimension_definition_point_audit"]

    assert report["release_allowed"], report.get("release_block_reason")
    assert audit["all_dimensions_bound_to_geometry"], [
        entry for entry in audit["dimensions"] if not entry["bound_to_geometry"]
    ]
    assert not [
        entry
        for entry in audit["dimensions"]
        if entry["measurement"] is not None
        and abs(entry["measurement"] - 2.0) < 0.01
    ]
    expected_thickness = 2.67 if kind == "bread_block" else 2.80
    assert report["shared_parameters"]["guide_thickness"] == pytest.approx(
        expected_thickness
    )

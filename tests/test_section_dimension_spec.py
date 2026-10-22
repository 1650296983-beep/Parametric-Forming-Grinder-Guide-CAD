import ezdxf
import pytest

from src.dimension_roles import (
    SECTION_CENTER_OPENING,
    SECTION_DIMENSION_ROLES,
    SECTION_FIXED_HEIGHT,
    SECTION_FIXED_WIDTH,
    SECTION_GUIDE_THICKNESS,
    SECTION_R_FORM,
    SECTION_SLOT_BASE_HEIGHT,
    SECTION_SLOT_WIDTH,
    get_dimension_role,
)
from src.dxf_writer import write_dxf
from src.guide_design_input import build_single_guide_profile_from_input
from src.machine_config import load_machine_config
from src.section_dimension_spec import (
    DimensionSpec,
    DimensionSpecError,
    SectionFrame,
    emit_section_dimensions,
    index_section_dimensions,
    infer_section_frame,
)

SINGLE_GUIDE_MACHINES = (
    "bed_618",
    "double_head_up_down",
    "double_head_up_up",
    "triple_single_down_up",
    "triple_single_up_up",
)


def _template_dimensions(machine):
    doc = ezdxf.readfile(machine.section_template_path)
    return list(doc.modelspace().query("DIMENSION"))


@pytest.mark.parametrize("machine_id", SINGLE_GUIDE_MACHINES)
def test_template_dimensions_are_classified_by_their_own_geometry(machine_id):
    machine = load_machine_config(machine_id)
    dimensions = _template_dimensions(machine)
    frame = infer_section_frame(dimensions)
    index = index_section_dimensions(dimensions, frame)

    assert index.unclassified == []
    assert frame.width == pytest.approx(machine.section_outer_width)
    assert frame.height == pytest.approx(27.0)
    for role in (
        SECTION_FIXED_WIDTH,
        SECTION_FIXED_HEIGHT,
        SECTION_SLOT_WIDTH,
        SECTION_GUIDE_THICKNESS,
    ):
        assert len(index.entities(role)) == 1, role


def test_classification_ignores_the_current_product_parameters():
    """The carrier is chosen by its historical family, never by a new value."""
    machine = load_machine_config("double_head_up_up")
    dimensions = _template_dimensions(machine)
    index = index_section_dimensions(dimensions, infer_section_frame(dimensions))

    slot_width = index.entities(SECTION_SLOT_WIDTH)[0]
    assert slot_width.get_measurement() == pytest.approx(8.94)
    assert slot_width.get_measurement() != pytest.approx(19.04)


def test_emit_rejects_a_missing_role_carrier():
    doc = ezdxf.new()
    modelspace = doc.modelspace()
    for x in (0.0, 1.0):
        modelspace.add_linear_dim(
            base=(0.0, 0.0), p1=(x, 0.0), p2=(x, 10.0), text="<>"
        ).render()
    index = index_section_dimensions(
        list(modelspace.query("DIMENSION")),
        SectionFrame(left=0.0, right=1.0, bottom=0.0, top=10.0, center_x=0.5),
    )

    with pytest.raises(DimensionSpecError, match="slot_width"):
        emit_section_dimensions(
            doc,
            modelspace,
            index,
            [DimensionSpec(SECTION_SLOT_WIDTH, "linear", 1.0, "1.00", slot=2)],
            geometry=None,
            apply_spec=lambda *args: None,
        )


def _generate(tmp_path, machine_id, first_wheel_side, kind):
    machine = load_machine_config(machine_id)
    if kind == "bread_block":
        finished, after, before = "R16.7*19*40*6.5", "bread_shape", "rectangular_block"
        pre_grinding = "40*19(+0.01/-0.01)*6.55(+0.01/-0.01)"
    else:
        finished, after, before = "R15.9*R14.25*5.6*12.4*1.65", "tile_shape", "rectangular_block"
        pre_grinding = "12.4*5.6(-0.035/-0.055)*1.96(+0.01/-0.01)"
    _, _, profile, _ = build_single_guide_profile_from_input(
        {
            "machine_type": machine.machine_id,
            "guide_rail_type": machine.guide_type,
            "wheel_sequence": list(machine.wheel_positions),
            "first_wheel_side": first_wheel_side,
            "template_coordinate_system": machine.template_coordinate_system,
            "finished_spec": finished,
            "pre_grinding_spec": pre_grinding,
            "product_shape_after": after,
            "product_shape_before": before,
            "relief": "4-1",
        },
        machine,
    )
    path = tmp_path / f"{machine_id}.dxf"
    write_dxf(profile, path, output_mode="release", machine_id=machine_id)
    return profile, ezdxf.readfile(path)


def _roles(doc):
    return {
        get_dimension_role(entity): entity
        for entity in doc.modelspace().query("DIMENSION")
        if get_dimension_role(entity) is not None
    }


def test_rectangular_groove_drops_the_archived_radius_carrier(tmp_path):
    profile, doc = _generate(tmp_path, "double_head_up_up", "upper", "bread_block")
    roles = _roles(doc)

    assert SECTION_R_FORM not in roles
    assert set(roles) <= SECTION_DIMENSION_ROLES | {
        "lower_wheel_notch_opening",
        "lower_wheel_key_process_height",
        "upper_wheel_key_process_height",
        "upper_wheel_local_cut_in_depth",
    }
    for role in (
        SECTION_SLOT_WIDTH,
        SECTION_GUIDE_THICKNESS,
        SECTION_CENTER_OPENING,
        SECTION_SLOT_BASE_HEIGHT,
    ):
        assert role in roles
    assert roles[SECTION_SLOT_WIDTH].get_measurement() == pytest.approx(
        profile.guide_spec.guide_slot_width
    )
    assert roles[SECTION_GUIDE_THICKNESS].get_measurement() == pytest.approx(
        profile.guide_spec.guide_thickness
    )
    assert roles[SECTION_CENTER_OPENING].get_measurement() == pytest.approx(
        profile.guide_spec.center_opening
    )


def test_flat_arc_center_opening_is_reread_from_the_current_proportion(tmp_path):
    profile, doc = _generate(tmp_path, "triple_single_down_up", "lower", "tile_block")
    roles = _roles(doc)

    slot_width = profile.guide_spec.guide_slot_width
    expected = round(min(slot_width * 0.30, profile.guide_spec.center_opening), 2)
    assert profile.guide_spec.center_opening == pytest.approx(expected)
    assert roles[SECTION_CENTER_OPENING].get_measurement() == pytest.approx(expected)
    assert roles[SECTION_CENTER_OPENING].dxf.text == f"{expected:.2f}"
    assert roles[SECTION_R_FORM].get_measurement() == pytest.approx(
        profile.forming_spec.R_form
    )

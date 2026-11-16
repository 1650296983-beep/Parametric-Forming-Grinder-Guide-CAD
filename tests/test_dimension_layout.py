import ezdxf
import pytest

from src.dimension_layout import (
    find_dimension_text_overlaps,
    resolve_dimension_text_overlaps,
)
from src.dual_guide_release_audit import build_dimension_definition_point_audit
from src.dxf_writer import write_dxf
from src.guide_design_input import build_single_guide_profile_from_input
from src.machine_config import load_machine_config


def _build_profile(machine_id, first_wheel_side):
    machine = load_machine_config(machine_id)
    _, _, profile, _ = build_single_guide_profile_from_input(
        {
            "machine_type": machine.machine_id,
            "guide_rail_type": machine.guide_type,
            "wheel_sequence": list(machine.wheel_positions),
            "first_wheel_side": first_wheel_side,
            "template_coordinate_system": machine.template_coordinate_system,
            "finished_spec": "R16.7*19*40*2.5",
            "pre_grinding_spec": "40*19(+0.01/-0.01)*2.55(+0.01/-0.01)",
            "product_shape_after": "bread_shape",
            "product_shape_before": "rectangular_block",
            "relief": "4-1",
        },
        machine,
    )
    return machine, profile


def test_resolver_separates_overlapping_linear_dimensions():
    doc = ezdxf.new("R2010")
    modelspace = doc.modelspace()
    modelspace.add_linear_dim(
        base=(50, 3), p1=(10, 0), p2=(90, 0), angle=0
    ).render()
    modelspace.add_linear_dim(
        base=(50, 5), p1=(10, 10), p2=(90, 10), angle=0
    ).render()
    original_points = [
        (
            dimension.dxf.handle,
            tuple(dimension.dxf.defpoint2),
            tuple(dimension.dxf.defpoint3),
        )
        for dimension in modelspace.query("DIMENSION")
    ]

    assert find_dimension_text_overlaps(doc)

    result = resolve_dimension_text_overlaps(doc)

    assert result["release_allowed"]
    assert not result["remaining_overlaps"]
    assert result["moves"]
    for handle, point_2, point_3 in original_points:
        dimension = modelspace.query(f'DIMENSION[handle=="{handle}"]')[0]
        assert tuple(dimension.dxf.defpoint2) == point_2
        assert tuple(dimension.dxf.defpoint3) == point_3


@pytest.mark.parametrize(
    ("machine_id", "first_wheel_side"),
    (("triple_single_down_up", "lower"), ("triple_single_up_up", "upper")),
)
def test_generated_section_annotations_have_clearance(
    tmp_path,
    machine_id,
    first_wheel_side,
):
    machine, profile = _build_profile(machine_id, first_wheel_side)
    path = tmp_path / f"{machine_id}.dxf"
    write_dxf(profile, path, output_mode="release", machine_id=machine_id)

    doc = ezdxf.readfile(path)
    assert find_dimension_text_overlaps(doc) == []

    audit = build_dimension_definition_point_audit(path, profile, machine)
    assert audit["dimension_text_overlaps"] == []
    assert audit["release_allowed"]


def test_overlap_audit_blocks_release_when_text_collides(tmp_path):
    machine, profile = _build_profile("triple_single_down_up", "lower")
    path = tmp_path / "collision.dxf"
    write_dxf(profile, path, output_mode="release", machine_id=machine.machine_id)

    doc = ezdxf.readfile(path)
    modelspace = doc.modelspace()
    target = next(
        dimension
        for dimension in modelspace.query("DIMENSION")
        if abs(float(dimension.get_measurement()) - 12.0) <= 0.01
    )
    point = target.dxf.defpoint
    target.dxf.defpoint = (point.x + 6.0, point.y, point.z)
    target.render()
    doc.saveas(path)

    audit = build_dimension_definition_point_audit(path, profile, machine)

    assert audit["dimension_text_overlaps"]
    assert not audit["release_allowed"]


def test_layout_shifts_use_outward_drafting_increments():
    doc = ezdxf.new('R2010')
    for y in (3, 5):
        doc.modelspace().add_linear_dim(base=(50, y), p1=(10, 0), p2=(90, 0)).render()
    result = resolve_dimension_text_overlaps(doc)
    assert result['release_allowed']
    assert result['moves']
    assert all(move['delta'] * 2 == pytest.approx(round(move['delta'] * 2)) for move in result['moves'])


def test_resolver_separates_overlapping_radial_dimension_texts():
    doc = ezdxf.new("R2010")
    modelspace = doc.modelspace()
    modelspace.add_radius_dim(
        center=(0, 0), radius=10, angle=30, location=(14, 8), text="4-R0.50"
    ).render()
    modelspace.add_radius_dim(
        center=(0, 1), radius=10, angle=30, location=(14, 8.5), text="2-R0.50"
    ).render()

    assert find_dimension_text_overlaps(doc)
    result = resolve_dimension_text_overlaps(doc)

    assert result["release_allowed"]
    assert not result["remaining_overlaps"]
    assert result["moves"]


@pytest.mark.parametrize(
    ("machine_id", "first_wheel_side"),
    (
        ("double_head_up_up", "upper"),
        ("double_head_up_down", "upper"),
        ("triple_single_up_up", "upper"),
        ("triple_single_down_up", "lower"),
    ),
)
def test_slot_width_and_side_clearance_extend_outside_geometry(
    tmp_path,
    machine_id,
    first_wheel_side,
):
    machine, profile = _build_profile(machine_id, first_wheel_side)
    path = tmp_path / f"{machine_id}_outside.dxf"
    write_dxf(profile, path, output_mode="release", machine_id=machine_id)

    doc = ezdxf.readfile(path)
    slot_dim = next(
        d
        for d in doc.modelspace().query("DIMENSION")
        if d.dxf.layer == "DIMENSION" and "±" in (d.dxf.text or "")
    )
    right_slot_x = max(float(slot_dim.dxf.defpoint2.x), float(slot_dim.dxf.defpoint3.x))
    assert float(slot_dim.dxf.text_midpoint.x) > right_slot_x
    dim_y = float(slot_dim.dxf.defpoint.y)
    assert any(
        e.dxftype() == "LINE"
        and abs(float(e.dxf.start.y) - dim_y) < 1e-3
        and abs(float(e.dxf.end.y) - dim_y) < 1e-3
        and max(float(e.dxf.start.x), float(e.dxf.end.x)) > float(slot_dim.dxf.text_midpoint.x)
        for e in doc.blocks[slot_dim.dxf.geometry]
    )

    upper_y = machine.side_layout.upper_y
    lower_y = machine.side_layout.lower_y
    side_clearance_dims = [
        d
        for d in doc.modelspace().query("DIMENSION")
        if d.dxf.layer == "SIDE_DIMENSION"
        and d.dxf.hasattr("defpoint2")
        and d.dxf.hasattr("defpoint3")
        and abs(float(d.dxf.defpoint2.y) - float(d.dxf.defpoint3.y)) > 1.0
        and float(d.get_measurement()) < 20.0
        and (
            abs(max(float(d.dxf.defpoint2.y), float(d.dxf.defpoint3.y)) - upper_y) < 1e-3
            or abs(min(float(d.dxf.defpoint2.y), float(d.dxf.defpoint3.y)) - lower_y) < 1e-3
        )
    ]
    assert side_clearance_dims
    for side_dim in side_clearance_dims:
        y2 = float(side_dim.dxf.defpoint2.y)
        y3 = float(side_dim.dxf.defpoint3.y)
        if abs(max(y2, y3) - upper_y) < 1e-3:
            assert float(side_dim.dxf.text_midpoint.y) > upper_y
        else:
            assert float(side_dim.dxf.text_midpoint.y) < lower_y



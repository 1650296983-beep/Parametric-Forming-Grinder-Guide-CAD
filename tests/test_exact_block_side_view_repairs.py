from __future__ import annotations

from math import sqrt

import ezdxf
import pytest

from src.dual_guide_engine import DualGuideTemplateEngine
from src.dual_guide_release_audit import build_dimension_definition_point_audit
from src.dxf_writer import write_dxf
from src.machine_config import load_machine_config
from src.side_view import build_side_view_geometry
from src.web_api import DesignInput, _build_profile_for_design


FINISHED_SPEC = "R9.6*8.6*42.6*2.1"
PRE_GRINDING_SPEC = "42.6*8.6(-0.07/-0.09)*2.1(+0.01/-0.01)"
EXPECTED_CUT_IN = 2.1 * 0.6
EXPECTED_OPENING = 2.0 * sqrt(80.0**2 - (80.0 - EXPECTED_CUT_IN) ** 2)


@pytest.mark.parametrize(
    ("machine_id", "wheel_sequence", "first_wheel_side"),
    (
        ("bed_618", ["上"], "upper"),
        ("double_head_up_down", ["上", "下"], "upper"),
        ("double_head_up_up", ["上", "上"], "upper"),
        ("triple_double_down_up_up", ["下", "上", "上"], "lower"),
        ("triple_double_up_up_up", ["上", "上", "上"], "upper"),
    ),
)
def test_exact_block_spec_uses_ratio_cut_in_and_expected_side_styles(
    tmp_path,
    machine_id: str,
    wheel_sequence: list[str],
    first_wheel_side: str,
) -> None:
    machine = load_machine_config(machine_id)
    design = DesignInput(
        machine_type=machine_id,
        guide_rail_type=machine.guide_type,
        wheel_sequence=wheel_sequence,
        first_wheel_side=first_wheel_side,
        template_coordinate_system=machine.template_coordinate_system,
        finished_spec=FINISHED_SPEC,
        pre_grinding_spec=PRE_GRINDING_SPEC,
        product_shape_after="bread_shape",
        product_shape_before="rectangular_block",
        tolerance=(
            {}
            if machine.guide_sections == 2
            else {
                "width_upper_deviation": -0.07,
                "width_lower_deviation": -0.09,
                "thickness_upper_deviation": 0.01,
                "thickness_lower_deviation": -0.01,
            }
        ),
    )
    _, _, profile, _ = _build_profile_for_design(design, machine)
    release_path = tmp_path / f"{machine_id}.dxf"

    if machine.guide_sections == 2:
        DualGuideTemplateEngine(machine).write_dxf(
            profile,
            release_path,
            output_mode="release",
        )
    else:
        side = build_side_view_geometry(profile, layout=machine.side_layout)
        assert side.derived.wheel_cut_in_depth == pytest.approx(EXPECTED_CUT_IN)
        assert side.derived.lower_cavity_notch_opening == pytest.approx(
            EXPECTED_OPENING
        )
        assert side.derived.upper_cavity_notch_opening == pytest.approx(
            EXPECTED_OPENING
        )
        write_dxf(
            profile,
            release_path,
            output_mode="release",
            machine_id=machine_id,
        )

    doc = ezdxf.readfile(release_path)
    expected_layer = "SIDE_CAVITY" if machine.guide_sections == 2 else "SIDE_DERIVED"
    cavity_lines = _side_horizontal_lines(doc, expected_layer)
    assert cavity_lines
    assert all(_effective_color(doc, line) == 3 for line in cavity_lines)
    assert all(_effective_linetype(doc, line) == "DASHED" for line in cavity_lines)

    if machine_id in {"bed_618", "double_head_up_down"}:
        _assert_two_cavity_boundaries_with_wheel_gaps(
            cavity_lines,
            EXPECTED_OPENING,
            require_every_boundary_split=(
                machine_id == "double_head_up_down"
            ),
        )

    if machine_id == "double_head_up_down":
        upper_arc = next(
            arc
            for arc in doc.modelspace().query("ARC")
            if arc.dxf.layer == "SIDE_TEMPLATE"
            and arc.dxf.radius == pytest.approx(80.0)
            and arc.dxf.center.x == pytest.approx(machine.side_layout.center_a_x)
        )
        cavity_top = max(float(line.dxf.start.y) for line in cavity_lines)
        assert cavity_top - (float(upper_arc.dxf.center.y) - 80.0) == pytest.approx(
            EXPECTED_CUT_IN
        )
        lower_dimension = next(
            dimension
            for dimension in doc.modelspace().query("DIMENSION")
            if float(dimension.get_measurement())
            == pytest.approx(12.0 + EXPECTED_CUT_IN)
        )
        assert float(lower_dimension.dxf.defpoint2.x) == pytest.approx(
            float(lower_dimension.dxf.defpoint3.x)
        )
        assert float(lower_dimension.dxf.defpoint2.y) == pytest.approx(
            machine.side_layout.lower_y
            + machine.section_slot_base_height
            + EXPECTED_CUT_IN
        )
        assert float(lower_dimension.dxf.defpoint3.y) == pytest.approx(
            machine.side_layout.lower_y
        )

    if machine.guide_sections == 2:
        outline_lines = _side_horizontal_lines(doc, "SIDE_TEMPLATE")
        assert outline_lines
        assert all(_effective_color(doc, line) == 7 for line in outline_lines)
        assert all(_effective_linetype(doc, line) == "CONTINUOUS" for line in outline_lines)
        _assert_no_exact_duplicate_cavity_lines(cavity_lines)
        _assert_r80_dimensions_and_process_dimensions_hit_crowns(doc)

    audit = build_dimension_definition_point_audit(
        release_path,
        profile,
        machine,
    )
    assert audit["release_allowed"] is True
    assert all(item["point_error"] <= 0.01 for item in audit["dimensions"])

    if machine_id == "triple_double_up_up_up":
        _assert_upper_r80_arcs_join_outer_surface(doc)
        slot_dimensions = [
            dimension
            for dimension in doc.modelspace().query("DIMENSION")
            if float(dimension.get_measurement()) == pytest.approx(8.56)
        ]
        assert len(slot_dimensions) == 2
        assert all(
            abs(float(dimension.dxf.defpoint.y) - float(dimension.dxf.defpoint2.y))
            < 15.0
            for dimension in slot_dimensions
        )


def _side_horizontal_lines(doc, layer: str):
    return [
        line
        for line in doc.modelspace().query("LINE")
        if line.dxf.layer == layer
        and min(float(line.dxf.start.x), float(line.dxf.end.x)) > 3300.0
        and abs(float(line.dxf.start.y) - float(line.dxf.end.y)) <= 0.001
    ]


def _effective_color(doc, entity) -> int:
    color = int(entity.dxf.color)
    return int(doc.layers.get(entity.dxf.layer).dxf.color) if color == 256 else color


def _effective_linetype(doc, entity) -> str:
    linetype = str(entity.dxf.linetype).upper()
    if linetype == "BYLAYER":
        return str(doc.layers.get(entity.dxf.layer).dxf.linetype).upper()
    return linetype


def _assert_upper_r80_arcs_join_outer_surface(doc) -> None:
    outer_lines = _side_horizontal_lines(doc, "SIDE_TEMPLATE")
    outer_points = [
        (float(point.x), float(point.y))
        for line in outer_lines
        for point in (line.dxf.start, line.dxf.end)
    ]
    arcs = [
        arc
        for arc in doc.modelspace().query("ARC")
        if arc.dxf.layer == "SIDE_TEMPLATE"
        and arc.dxf.radius == pytest.approx(80.0)
        and float(arc.dxf.center.x) > 3300.0
    ]
    assert len(arcs) == 6
    for arc in arcs:
        for endpoint in (arc.start_point, arc.end_point):
            assert min(
                sqrt(
                    (float(endpoint.x) - x) ** 2
                    + (float(endpoint.y) - y) ** 2
                )
                for x, y in outer_points
            ) <= 0.001


def _assert_two_cavity_boundaries_with_wheel_gaps(
    cavity_lines,
    expected_opening: float,
    *,
    require_every_boundary_split: bool = True,
) -> None:
    lines_by_y = {}
    for line in cavity_lines:
        lines_by_y.setdefault(round(float(line.dxf.start.y), 3), []).append(
            line
        )
    assert len(lines_by_y) == 2
    for lines in lines_by_y.values():
        if not require_every_boundary_split and len(lines) == 1:
            continue
        assert len(lines) == 2
        ordered = sorted(lines, key=lambda line: float(line.dxf.start.x))
        gap = min(
            float(ordered[1].dxf.start.x),
            float(ordered[1].dxf.end.x),
        ) - max(
            float(ordered[0].dxf.start.x),
            float(ordered[0].dxf.end.x),
        )
        assert gap == pytest.approx(expected_opening, abs=0.001)


def _assert_no_exact_duplicate_cavity_lines(cavity_lines) -> None:
    keys = []
    for line in cavity_lines:
        start = (
            round(float(line.dxf.start.x), 6),
            round(float(line.dxf.start.y), 6),
        )
        end = (
            round(float(line.dxf.end.x), 6),
            round(float(line.dxf.end.y), 6),
        )
        keys.append(tuple(sorted((start, end))))
    assert len(keys) == len(set(keys))


def _assert_r80_dimensions_and_process_dimensions_hit_crowns(doc) -> None:
    arcs = [
        arc
        for arc in doc.modelspace().query("ARC")
        if arc.dxf.layer == "SIDE_TEMPLATE"
        and float(arc.dxf.radius) == pytest.approx(80.0)
    ]
    crowns = [
        (
            float(arc.dxf.center.x),
            _expected_crown_y(arc),
        )
        for arc in arcs
    ]
    radius_dimensions = []
    process_dimensions = []
    for dimension in doc.modelspace().query("DIMENSION"):
        measurement = float(dimension.get_measurement())
        if measurement == pytest.approx(80.0) and dimension.dxf.hasattr(
            "defpoint4"
        ):
            radius_dimensions.append(dimension)
        elif (
            1.0 <= measurement <= 20.0
            and dimension.dxf.hasattr("defpoint2")
            and float(dimension.dxf.defpoint2.x) > 3300.0
        ):
            process_dimensions.append(dimension)
    assert radius_dimensions
    assert process_dimensions
    for dimension in radius_dimensions:
        target = dimension.dxf.defpoint4
        assert min(
            sqrt(
                (float(target.x) - x) ** 2
                + (float(target.y) - y) ** 2
            )
            for x, y in crowns
        ) <= 0.001
    for dimension in process_dimensions:
        crown_point = dimension.dxf.defpoint2
        datum_point = dimension.dxf.defpoint3
        assert min(
            sqrt(
                (float(crown_point.x) - x) ** 2
                + (float(crown_point.y) - y) ** 2
            )
            for x, y in crowns
        ) <= 0.001
        assert float(datum_point.x) == pytest.approx(
            float(crown_point.x),
            abs=0.001,
        )


def _expected_crown_y(arc) -> float:
    midpoint = (
        (float(arc.dxf.start_angle) + float(arc.dxf.end_angle)) / 2.0
    ) % 360.0
    return float(arc.dxf.center.y) + (
        80.0 if 0.0 <= midpoint <= 180.0 else -80.0
    )

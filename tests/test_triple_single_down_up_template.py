import ezdxf
import pytest
from math import sqrt

from src.dxf_writer import write_dxf
from src.dimension_roles import (
    LOWER_WHEEL_KEY_PROCESS_HEIGHT,
    LOWER_WHEEL_NOTCH_OPENING,
    REQUIRED_BLOCK_TO_TILE_DIMENSION_ROLES,
    SECTION_CENTER_OPENING,
    UPPER_WHEEL_KEY_PROCESS_HEIGHT,
    UPPER_WHEEL_LOCAL_CUT_IN_DEPTH,
    get_dimension_role,
)
from src.geometry import (
    build_block_to_tile_section,
    build_tile_section,
)
from src.guide_design_input import build_single_guide_profile_from_input
from src.global_rules import WHEEL_CUT_IN_RATIO, wheel_notch_opening_limit
from src.inspection import inspect_release_dxf
from src.machine_config import load_machine_config
from src.side_view import build_side_view_geometry
from src.spec_parser import (
    parse_block_spec,
    parse_company_tile_spec,
    parse_relief_spec,
)
from src.validation_report import write_validation_report_json


def test_triple_single_down_up_config_matches_clean_template():
    machine = load_machine_config("triple_single_down_up")

    assert machine.guide_length == pytest.approx(379.0)
    assert machine.side_fixed_spans == pytest.approx((99.0, 180.0, 100.0))
    assert machine.wheel_positions == ("下", "上")
    assert machine.guide_sections == 1
    assert machine.section_style == "triple_single_down_up_flat_arc"
    assert machine.section_outer_width == pytest.approx(40.0)
    assert machine.section_center_opening == pytest.approx(2.0)
    assert machine.section_slot_base_height == pytest.approx(12.0)
    assert machine.side_layout.fixed_tile_side_projected_slot_height == pytest.approx(12.0)
    assert WHEEL_CUT_IN_RATIO == pytest.approx(0.6)
    assert machine.side_layout.block_side_mode == "slot_base_plus_wheel_cut_in"
    assert machine.block_to_tile_groove_profile == "flat_arc_groove"
    assert machine.block_to_bread_groove_profile == "rectangular_groove"
    assert machine.section_template_path.exists()
    assert machine.side_template_path.exists()


def test_triple_single_down_up_release_updates_native_dimensions(tmp_path):
    machine = load_machine_config("triple_single_down_up")
    spec = parse_company_tile_spec(
        "R15.9*R14.25*5.6*12.4*1.65",
        require_chord_tolerance=False,
    )
    preform = parse_block_spec("12.4*5.6(-0.035/-0.055)*1.96(+0.01/-0.01)")
    profile = build_block_to_tile_section(
        spec,
        preform,
        outer_width=machine.section_outer_width,
        center_opening=machine.section_center_opening,
        slot_base_height=machine.section_slot_base_height,
        arc_side="lower",
    )
    release_path = tmp_path / "triple_single_down_up_release.dxf"

    write_dxf(profile, release_path, output_mode="release", machine_id="triple_single_down_up")
    doc = ezdxf.readfile(release_path)
    measurements = _dimension_measurements_by_text(doc)

    assert profile.process_type == "block_to_tile"
    assert profile.forming_spec.R_form == pytest.approx(15.9)
    assert profile.guide_spec.guide_slot_width == pytest.approx(5.60)
    assert profile.guide_spec.guide_thickness == pytest.approx(2.08)
    assert profile.guide_spec.center_opening == pytest.approx(2.0)
    assert profile.guide_spec.outer_width == pytest.approx(40.0)
    assert measurements["5.60±0.01"][0] == pytest.approx(5.60)
    assert measurements["2.08"][0] == pytest.approx(2.08)
    assert measurements["R15.90"][0] == pytest.approx(15.9)
    assert measurements["4-<>"][0] == pytest.approx(1.0)
    assert "4.0" not in measurements
    assert len(list(doc.modelspace().query("DIMENSION"))) == 16
    _assert_required_process_dimensions(doc, profile, machine)
    _assert_required_process_dimensions_are_visible(doc)
    assert _r_form_arc_count(doc, 15.9) == 1
    assert _r_dimension_text_is_right_of_arc_target(doc, "R15.90")
    assert _r_dimension_text_is_outside_section(doc, "R15.90", outer_right=3261.351869428413)
    _assert_standard_relief_topology(doc, profile)
    _assert_side_lower_wheel_uses_thickness_cut_and_cavity_opening_limit(
        doc,
        machine,
        preform.thickness_mid,
        preform.length,
        profile.guide_spec.guide_thickness,
    )
    _assert_upper_wheel_uses_thickness_cut(
        doc,
        machine,
        preform.thickness_mid,
        preform.length,
        profile.guide_spec.guide_thickness,
    )


def test_lower_first_wheel_places_block_to_tile_radius_center_above_cavity_and_limits_both_openings(tmp_path):
    machine = load_machine_config("triple_single_down_up")
    finished = parse_company_tile_spec(
        "R16.3*R14.3*5*20*2",
        require_chord_tolerance=False,
    )
    preform = parse_block_spec("20*5(-0.01/-0.03)*2.25(+0.01/-0.01)")
    profile = build_block_to_tile_section(
        finished,
        preform,
        outer_width=machine.section_outer_width,
        center_opening=machine.section_center_opening,
        slot_base_height=machine.section_slot_base_height,
        arc_side="lower",
    )
    release_path = tmp_path / "lower_first_block_to_tile_release.dxf"

    write_dxf(profile, release_path, output_mode="release", machine_id=machine.machine_id)
    doc = ezdxf.readfile(release_path)
    main_arc = next(
        arc
        for arc in doc.modelspace().query("ARC")
        if arc.dxf.layer == "PARAM_SLOT" and arc.dxf.radius == pytest.approx(16.3)
    )
    slot_base_y = machine.side_layout.lower_y + profile.guide_spec.slot_base_height
    side = build_side_view_geometry(profile, layout=machine.side_layout)
    inspection = inspect_release_dxf(profile, machine, release_path)
    arc_sweep = (float(main_arc.dxf.end_angle) - float(main_arc.dxf.start_angle)) % 360.0

    assert main_arc.dxf.center.y > slot_base_y
    assert arc_sweep < 180.0
    assert side.derived.lower_cavity_notch_opening < preform.length
    assert side.derived.upper_cavity_notch_opening < preform.length
    assert _inspection_check(inspection, "lower_wheel_notch_safety")["ok"]
    assert _inspection_check(inspection, "upper_wheel_notch_safety")["ok"]
    assert inspection["release_allowed"]
    _assert_r80_dimensions_target_current_arcs(doc, machine)
    _assert_side_slot_base_and_top_lines(doc, machine, profile.guide_spec.guide_thickness)
    assert not any("DEBUG" in entity.dxf.layer for entity in doc.modelspace())
    assert not _fixed_template_arc_radius_present(doc, 110.0)


def test_triple_single_down_up_same_r_preform_uses_toleranced_midpoint(tmp_path):
    machine = load_machine_config("triple_single_down_up")
    spec = parse_company_tile_spec(
        "R30*R30*17.4(+0/-0.02)*23.5*3.95(+0.02/-0.02)"
    )
    profile = build_tile_section(
        spec,
        outer_width=machine.section_outer_width,
        center_opening=machine.section_center_opening,
        slot_base_height=machine.section_slot_base_height,
    )
    release_path = tmp_path / "same_r_release.dxf"

    write_dxf(profile, release_path, output_mode="release", machine_id=machine.machine_id)
    inspection = inspect_release_dxf(profile, machine, release_path)

    assert profile.process_type == "tile"
    assert profile.process_thickness == pytest.approx(3.95)
    assert profile.forming_spec.R_form == pytest.approx(30.0)
    assert profile.guide_spec.guide_slot_width == pytest.approx(17.43)
    assert profile.guide_spec.guide_thickness == pytest.approx(4.20)
    assert _r_form_arc_count(ezdxf.readfile(release_path), 30.0) == 3
    assert inspection["release_allowed"]


def test_triple_single_down_up_bread_with_block_preform_uses_rectangular_groove(tmp_path):
    machine = load_machine_config("triple_single_down_up")
    _, _, profile, decision = build_single_guide_profile_from_input(
        {
            "machine_type": machine.machine_id,
            "guide_rail_type": machine.guide_type,
            "wheel_sequence": ["下", "上"],
            "first_wheel_side": "lower",
            "template_coordinate_system": machine.template_coordinate_system,
            "finished_spec": "R40.75*30*22*3.3",
            "finished_spec_order": "radius_length_width_thickness",
            "pre_grinding_spec": "30*22(-0.10/-0.12)*3.35(+0.01/-0.01)",
            "product_shape_after": "bread_shape",
            "product_shape_before": "rectangular_block",
        },
        machine,
    )
    release_path = tmp_path / "triple_single_down_up_bread_release.dxf"

    write_dxf(profile, release_path, output_mode="release", machine_id=machine.machine_id)
    doc = ezdxf.readfile(release_path)
    measurements = _dimension_measurements_by_text(doc)
    param_arcs = [
        entity
        for entity in doc.modelspace()
        if entity.dxftype() == "ARC" and entity.dxf.layer == "PARAM_SLOT"
    ]
    relief_arcs = [arc for arc in param_arcs if abs(float(arc.dxf.radius) - 0.5) < 1e-6]
    assert profile.process_type == "block_to_bread_rectangular"
    assert profile.finished_spec.finished_shape == "bread"
    assert profile.guide_spec.guide_slot_width == pytest.approx(21.93)
    assert profile.guide_spec.guide_thickness == pytest.approx(3.47)
    assert decision.groove_profile == "rectangular_groove"
    assert not any(text.startswith("R40.75") for text in measurements)
    assert len(relief_arcs) == 6
    assert len(param_arcs) == 6

    side = build_side_view_geometry(profile, layout=machine.side_layout)
    assert side.derived.slot_base_height == pytest.approx(12.0)
    expected_opening = wheel_notch_opening_limit(profile.block_spec.length)
    expected_effective_cut_in = 80.0 - sqrt(
        80.0**2 - (expected_opening / 2.0) ** 2
    )
    assert side.derived.wheel_notch_depth == pytest.approx(
        12.0 + expected_effective_cut_in
    )
    assert side.derived.side_clearance_height == pytest.approx(
        27.0 - 12.0 - profile.guide_spec.guide_thickness + expected_effective_cut_in
    )

    inspection = inspect_release_dxf(profile, machine, release_path)
    assert inspection["release_allowed"]
    side_check = next(
        check
        for check in inspection["checks"]
        if check["name"] == "block_bread_side_geometry"
    )
    assert side_check["ok"]


def test_triple_single_down_up_tile_with_block_preform_uses_big_r_bread_profile():
    machine = load_machine_config("triple_single_down_up")
    spec = parse_company_tile_spec(
        "R14.25*R15.9*5.6*12.4*1.65",
        require_chord_tolerance=False,
    )
    preform = parse_block_spec("12.4*5.6(-0.035/-0.055)*1.96(+0.01/-0.01)")

    profile = build_block_to_tile_section(
        spec,
        preform,
        outer_width=machine.section_outer_width,
        center_opening=machine.section_center_opening,
        slot_base_height=machine.section_slot_base_height,
        arc_side="lower",
    )

    assert profile.forming_spec.R_form == pytest.approx(15.9)
    assert profile.forming_spec.forming_radius_mode == "block_to_tile_bread_profile_big_R"
    assert profile.forming_profile.params.profile_shape == "bread"
    assert profile.forming_profile.params.R_outer == pytest.approx(15.9)


def test_triple_single_down_up_center_transitions_remain_r0_5_with_custom_relief(tmp_path):
    machine = load_machine_config("triple_single_down_up")
    spec = parse_company_tile_spec(
        "R15.9*R14.25*5.6*12.4*1.65",
        require_chord_tolerance=False,
    )
    preform = parse_block_spec("12.4*5.6(-0.035/-0.055)*1.96(+0.01/-0.01)")
    profile = build_block_to_tile_section(
        spec,
        preform,
        relief=parse_relief_spec("4-0.6"),
        outer_width=machine.section_outer_width,
        center_opening=machine.section_center_opening,
        slot_base_height=machine.section_slot_base_height,
        arc_side="lower",
    )
    release_path = tmp_path / "custom_relief_release.dxf"

    write_dxf(profile, release_path, output_mode="release", machine_id=machine.machine_id)
    doc = ezdxf.readfile(release_path)
    section_arcs = [
        entity
        for entity in doc.modelspace()
        if entity.dxftype() == "ARC" and entity.dxf.layer == "PARAM_SLOT"
    ]

    assert sum(float(arc.dxf.radius) == pytest.approx(0.3) for arc in section_arcs) == 4
    assert sum(float(arc.dxf.radius) == pytest.approx(0.5) for arc in section_arcs) == 2
    inspection = inspect_release_dxf(profile, machine, release_path)
    assert _inspection_check(inspection, "relief_topology")["ok"]
    assert inspection["release_allowed"]


def test_triple_single_down_up_report_exposes_required_dimension_roles(tmp_path):
    machine, spec, profile = _build_current_profile()
    release_path = tmp_path / "release.dxf"
    report_path = tmp_path / "report.json"
    write_dxf(profile, release_path, output_mode="release", machine_id=machine.machine_id)

    report = write_validation_report_json(
        profile,
        spec,
        machine,
        debug_dxf=release_path,
        release_dxf=release_path,
        preview_png=tmp_path / "preview.png",
        report_path=report_path,
    )

    assert report["release_allowed"]
    assert set(report["required_dimension_roles"]) == set(REQUIRED_BLOCK_TO_TILE_DIMENSION_ROLES)
    assert all(
        item["status"] == "PASS"
        and item["bound_to_geometry"]
        and item["actual_dimension_measurement"] == pytest.approx(item["expected_value"])
        for item in report["required_dimension_roles"].values()
    )


def test_release_validation_rejects_missing_required_dimension(tmp_path):
    machine, _, profile = _build_current_profile()
    release_path = tmp_path / "missing_dimension.dxf"
    write_dxf(profile, release_path, output_mode="release", machine_id=machine.machine_id)
    doc = ezdxf.readfile(release_path)
    missing = _dimension_by_role(doc, LOWER_WHEEL_NOTCH_OPENING)
    doc.modelspace().delete_entity(missing)
    doc.saveas(release_path)

    inspection = inspect_release_dxf(profile, machine, release_path)
    role_check = _inspection_check(inspection, "required_dimension_roles")

    assert not inspection["release_allowed"]
    assert role_check["details"]["roles"][LOWER_WHEEL_NOTCH_OPENING]["status"] == "FAIL"
    assert role_check["details"]["roles"][LOWER_WHEEL_NOTCH_OPENING]["dimension_count"] == 0


def test_release_validation_rejects_dimension_measurement_mismatch(tmp_path):
    machine, _, profile = _build_current_profile()
    release_path = tmp_path / "measurement_mismatch.dxf"
    write_dxf(profile, release_path, output_mode="release", machine_id=machine.machine_id)
    doc = ezdxf.readfile(release_path)
    dimension = _dimension_by_role(doc, UPPER_WHEEL_LOCAL_CUT_IN_DEPTH)
    point = dimension.dxf.defpoint3
    dimension.dxf.defpoint3 = (point.x, point.y + 0.5, point.z)
    doc.saveas(release_path)

    inspection = inspect_release_dxf(profile, machine, release_path)
    role = _inspection_check(inspection, "required_dimension_roles")["details"]["roles"][
        UPPER_WHEEL_LOCAL_CUT_IN_DEPTH
    ]

    assert not inspection["release_allowed"]
    assert role["status"] == "FAIL"
    assert not role["bound_to_geometry"]
    assert role["actual_dimension_measurement"] != pytest.approx(role["expected_value"])


def test_release_validation_rejects_stale_four_mm_opening(tmp_path):
    machine, _, profile = _build_current_profile()
    release_path = tmp_path / "stale_opening.dxf"
    write_dxf(profile, release_path, output_mode="release", machine_id=machine.machine_id)
    doc = ezdxf.readfile(release_path)
    dimension = _dimension_by_role(doc, SECTION_CENTER_OPENING)
    p2 = dimension.dxf.defpoint2
    p3 = dimension.dxf.defpoint3
    dimension.dxf.defpoint3 = (p2.x + 4.0, p3.y, p3.z)
    dimension.dxf.text = "4.0"
    doc.saveas(release_path)

    inspection = inspect_release_dxf(profile, machine, release_path)
    stale_check = _inspection_check(inspection, "stale_section_center_opening_absent")

    assert not inspection["release_allowed"]
    assert not stale_check["ok"]
    assert stale_check["details"]["stale_dimensions"][0]["measurement"] == pytest.approx(4.0)


def _build_current_profile():
    machine = load_machine_config("triple_single_down_up")
    spec = parse_company_tile_spec(
        "R15.9*R14.25*5.6*12.4*1.65",
        require_chord_tolerance=False,
    )
    preform = parse_block_spec("12.4*5.6(-0.035/-0.055)*1.96(+0.01/-0.01)")
    profile = build_block_to_tile_section(
        spec,
        preform,
        outer_width=machine.section_outer_width,
        center_opening=machine.section_center_opening,
        slot_base_height=machine.section_slot_base_height,
        arc_side="lower",
    )
    return machine, spec, profile


def _assert_required_process_dimensions(doc, profile, machine) -> None:
    dimensions = {
        get_dimension_role(entity): entity
        for entity in doc.modelspace().query("DIMENSION")
        if get_dimension_role(entity) is not None
    }
    derived = build_side_view_geometry(profile, layout=machine.side_layout).derived
    expected = {
        SECTION_CENTER_OPENING: 2.0,
        LOWER_WHEEL_NOTCH_OPENING: derived.lower_cavity_notch_opening,
        LOWER_WHEEL_KEY_PROCESS_HEIGHT: derived.wheel_notch_depth,
        UPPER_WHEEL_KEY_PROCESS_HEIGHT: derived.side_clearance_height,
        UPPER_WHEEL_LOCAL_CUT_IN_DEPTH: derived.wheel_cut_allowance,
    }
    assert set(dimensions) == set(REQUIRED_BLOCK_TO_TILE_DIMENSION_ROLES)
    for role, value in expected.items():
        assert dimensions[role].get_measurement() == pytest.approx(value)
    assert dimensions[SECTION_CENTER_OPENING].dxf.text == "2.00"
    for role, value in expected.items():
        assert dimensions[role].dxf.text == f"{value:.2f}"


def _assert_required_process_dimensions_are_visible(doc) -> None:
    dimensions = {
        get_dimension_role(entity): entity
        for entity in doc.modelspace().query("DIMENSION")
        if get_dimension_role(entity) is not None
    }
    for role in REQUIRED_BLOCK_TO_TILE_DIMENSION_ROLES:
        dimension = dimensions[role]
        assert dimension.dxf.dimstyle == "TH_GBDIM"
        assert dimension.dxf.text
        assert not dimension.dxf.get("invisible", 0)
        assert not doc.layers.get(dimension.dxf.layer).is_off()
        assert not doc.layers.get(dimension.dxf.layer).is_frozen()

        block_texts = [
            entity
            for entity in doc.blocks[dimension.dxf.geometry]
            if entity.dxftype() in {"TEXT", "MTEXT"}
        ]
        assert len(block_texts) == 1
        block_text = block_texts[0]
        assert block_text.dxf.style == "TH_GBDIM"
        assert block_text.text == dimension.dxf.text
        assert block_text.dxf.char_height == pytest.approx(3.5)


def _dimension_by_role(doc, role: str):
    return next(
        entity
        for entity in doc.modelspace().query("DIMENSION")
        if get_dimension_role(entity) == role
    )


def _inspection_check(inspection, name: str):
    return next(check for check in inspection["checks"] if check["name"] == name)


def _dimension_measurements_by_text(doc) -> dict[str, list[float]]:
    measurements = {}
    for dimension in doc.modelspace():
        if dimension.dxftype() == "DIMENSION" and dimension.dxf.text:
            measurements.setdefault(dimension.dxf.text, []).append(dimension.get_measurement())
    return measurements


def _r_form_arc_count(doc, radius: float) -> int:
    return sum(
        1
        for entity in doc.modelspace()
        if entity.dxf.layer == "PARAM_SLOT"
        and entity.dxftype() == "ARC"
        and entity.dxf.radius == pytest.approx(radius)
    )


def _assert_standard_relief_topology(doc, profile) -> None:
    side_relief_radius = profile.guide_spec.relief.relief_size / 2.0
    center_transition_radius = 0.5
    arcs = [
        entity
        for entity in doc.modelspace()
        if entity.dxftype() == "ARC"
        and entity.dxf.layer == "PARAM_SLOT"
        and (
            entity.dxf.radius == pytest.approx(side_relief_radius)
            or entity.dxf.radius == pytest.approx(center_transition_radius)
        )
    ]
    assert len(arcs) == 6
    min_x = min(float(arc.dxf.center.x) for arc in arcs)
    max_x = max(float(arc.dxf.center.x) for arc in arcs)
    center_x = (min_x + max_x) / 2.0
    side_arcs = [
        arc
        for arc in arcs
        if float(arc.dxf.center.x) == pytest.approx(min_x)
        or float(arc.dxf.center.x) == pytest.approx(max_x)
    ]
    center_arcs = sorted(
        [arc for arc in arcs if arc not in side_arcs],
        key=lambda arc: float(arc.dxf.center.x),
    )
    assert len(side_arcs) == 4
    assert len(center_arcs) == 2
    assert all(
        float(arc.dxf.radius) == pytest.approx(side_relief_radius)
        for arc in side_arcs
    )
    assert all(
        float(arc.dxf.radius) == pytest.approx(center_transition_radius)
        for arc in center_arcs
    )
    expected_offset = (
        profile.guide_spec.center_opening / 2.0 + center_transition_radius
    )
    assert float(center_arcs[0].dxf.center.x) == pytest.approx(center_x - expected_offset)
    assert float(center_arcs[1].dxf.center.x) == pytest.approx(center_x + expected_offset)
    assert expected_offset < profile.guide_spec.guide_slot_width / 2.0

    top_y = max(float(arc.dxf.center.y) for arc in side_arcs)
    if (
        profile.process_type in {"block_to_tile", "block_to_bread"}
        and profile.arc_side == "upper"
    ):
        radius = profile.forming_spec.R_form
        half_slot = profile.guide_spec.guide_slot_width / 2.0
        upper_center_y = top_y - sqrt(radius**2 - half_slot**2)
        expected_y = upper_center_y + sqrt(
            (radius + center_transition_radius) ** 2 - expected_offset**2
        )
    else:
        expected_y = top_y + center_transition_radius
    assert all(float(arc.dxf.center.y) == pytest.approx(expected_y) for arc in center_arcs)


def _fixed_template_arc_radius_present(doc, radius: float) -> bool:
    return any(
        entity.dxf.layer == "FIXED_TEMPLATE"
        and entity.dxftype() == "ARC"
        and entity.dxf.radius == pytest.approx(radius)
        for entity in doc.modelspace()
    )


def _r_dimension_text_is_right_of_arc_target(doc, label: str) -> bool:
    for dimension in doc.modelspace().query("DIMENSION"):
        if dimension.dxf.text != label:
            continue
        if not dimension.dxf.hasattr("geometry") or dimension.dxf.geometry not in doc.blocks:
            return False
        target = dimension.dxf.defpoint4
        for entity in doc.blocks[dimension.dxf.geometry]:
            if entity.dxftype() == "TEXT":
                insert = entity.dxf.insert
                return insert.x > target.x and insert.y > target.y
            if entity.dxftype() == "MTEXT":
                insert = entity.dxf.insert
                return insert.x > target.x and insert.y > target.y
    return False


def _r_dimension_text_is_outside_section(doc, label: str, outer_right: float) -> bool:
    for dimension in doc.modelspace().query("DIMENSION"):
        if dimension.dxf.text != label:
            continue
        if not dimension.dxf.hasattr("geometry") or dimension.dxf.geometry not in doc.blocks:
            return False
        for entity in doc.blocks[dimension.dxf.geometry]:
            if entity.dxftype() in {"TEXT", "MTEXT"}:
                return entity.dxf.insert.x > outer_right
    return False


def _assert_side_lower_wheel_uses_thickness_cut_and_cavity_opening_limit(
    doc,
    machine,
    finished_thickness: float,
    product_length: float,
    guide_thickness: float,
) -> None:
    layout = machine.side_layout
    radius = machine.wheel_radius
    natural_depth = finished_thickness * WHEEL_CUT_IN_RATIO
    natural_opening = 2.0 * sqrt(radius * radius - (radius - natural_depth) ** 2)
    expected_opening = min(natural_opening, wheel_notch_opening_limit(product_length))
    effective_depth = radius - sqrt(radius * radius - (expected_opening / 2.0) ** 2)
    notch_top_height = 12.0 + effective_depth
    arcs = [
        entity
        for entity in doc.modelspace().query("ARC")
        if entity.dxf.layer == "SIDE_TEMPLATE" and entity.dxf.radius == pytest.approx(radius)
    ]
    assert len(arcs) == 2
    lower = next(arc for arc in arcs if arc.dxf.center.x == pytest.approx(layout.center_a_x))
    center_y = layout.lower_y + notch_top_height - radius
    assert lower.dxf.center.y == pytest.approx(center_y)
    lower_surface_half_opening = sqrt(radius * radius - (layout.lower_y - center_y) ** 2)
    assert lower.dxf.start_angle == pytest.approx(_angle_deg(lower_surface_half_opening, layout.lower_y - center_y))
    assert _side_gap_width(doc, layout.lower_y + 12.0, "SIDE_DERIVED") == pytest.approx(
        expected_opening,
        abs=0.001,
    )


def _assert_side_slot_base_and_top_lines(doc, machine, guide_thickness: float) -> None:
    layout = machine.side_layout
    base_y = layout.lower_y + 12.0
    top_y = base_y + guide_thickness
    assert _has_horizontal_side_line(doc, base_y, "SIDE_DERIVED")
    assert _has_horizontal_side_line(doc, top_y, "SIDE_DERIVED")
    assert not _has_horizontal_side_line(doc, layout.lower_y + 12.5, "SIDE_DERIVED")


def _assert_upper_wheel_uses_thickness_cut(
    doc,
    machine,
    finished_thickness: float,
    product_length: float,
    guide_thickness: float,
) -> None:
    layout = machine.side_layout
    radius = machine.wheel_radius
    slot_top_y = layout.lower_y + 12.0 + guide_thickness
    requested_cut_in = finished_thickness * WHEEL_CUT_IN_RATIO
    requested_opening = 2.0 * sqrt(radius**2 - (radius - requested_cut_in) ** 2)
    controlled_opening = min(requested_opening, wheel_notch_opening_limit(product_length))
    expected_cut_in = radius - sqrt(radius**2 - (controlled_opening / 2.0) ** 2)
    upper = next(
        arc
        for arc in doc.modelspace().query("ARC")
        if arc.dxf.layer == "SIDE_TEMPLATE"
        and arc.dxf.radius == pytest.approx(radius)
        and arc.dxf.center.x == pytest.approx(layout.center_b_x)
        and arc.dxf.center.y > layout.upper_y
    )
    assert slot_top_y - (upper.dxf.center.y - radius) == pytest.approx(expected_cut_in)
    expected_half_chord = sqrt(radius**2 - (radius - expected_cut_in) ** 2)
    assert _side_gap_width_at_center(doc, slot_top_y, layout.center_b_x, "SIDE_DERIVED") == pytest.approx(
        2.0 * expected_half_chord
    )


def _assert_r80_dimensions_target_current_arcs(doc, machine) -> None:
    arcs = [
        arc
        for arc in doc.modelspace().query("ARC")
        if arc.dxf.layer == "SIDE_TEMPLATE"
        and arc.dxf.radius == pytest.approx(80.0)
        and any(
            arc.dxf.center.x == pytest.approx(center_x, abs=0.01)
            for center_x in (machine.side_layout.center_a_x, machine.side_layout.center_b_x)
        )
    ]
    dimensions = [
        dimension
        for dimension in doc.modelspace().query("DIMENSION")
        if dimension.get_measurement() == pytest.approx(80.0)
        and dimension.dxf.hasattr("defpoint")
        and dimension.dxf.hasattr("defpoint4")
    ]
    assert len(arcs) == 2
    assert len(dimensions) == 2
    for dimension in dimensions:
        center = dimension.dxf.defpoint
        target = dimension.dxf.defpoint4
        assert any(
            arc.dxf.center.x == pytest.approx(center.x, abs=0.001)
            and arc.dxf.center.y == pytest.approx(center.y, abs=0.001)
            for arc in arcs
        )
        assert sqrt((target.x - center.x) ** 2 + (target.y - center.y) ** 2) == pytest.approx(80.0)


def _has_horizontal_side_line(doc, y: float, layer: str) -> bool:
    return any(
        entity.dxf.layer == layer
        and entity.dxftype() == "LINE"
        and entity.dxf.start.y == pytest.approx(y, abs=0.001)
        and entity.dxf.end.y == pytest.approx(y, abs=0.001)
        for entity in doc.modelspace()
    )


def _side_gap_width(doc, y: float, layer: str) -> float:
    unique = {
        tuple(round(value, 3) for value in sorted((entity.dxf.start.x, entity.dxf.end.x)))
        for entity in doc.modelspace()
        if entity.dxf.layer == layer
        and entity.dxftype() == "LINE"
        and entity.dxf.start.y == pytest.approx(y, abs=0.001)
        and entity.dxf.end.y == pytest.approx(y, abs=0.001)
    }
    segments = sorted(unique, key=lambda values: values[0])
    assert len(segments) == 2
    return segments[1][0] - segments[0][1]


def _side_gap_width_at_center(doc, y: float, center_x: float, layer: str) -> float:
    segments = sorted(
        {
            tuple(round(value, 6) for value in sorted((entity.dxf.start.x, entity.dxf.end.x)))
            for entity in doc.modelspace()
            if entity.dxf.layer == layer
            and entity.dxftype() == "LINE"
            and entity.dxf.start.y == pytest.approx(y, abs=0.001)
            and entity.dxf.end.y == pytest.approx(y, abs=0.001)
        }
    )
    left = max(segment for segment in segments if segment[1] <= center_x)
    right = min(segment for segment in segments if segment[0] >= center_x)
    return right[0] - left[1]


def _angle_deg(dx: float, dy: float) -> float:
    from math import atan2, degrees

    return degrees(atan2(dy, dx)) % 360.0

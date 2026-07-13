import json
from pathlib import Path

import ezdxf
import pytest

from src.block_geometry import build_block_guide_section
from src.dual_guide_engine import DualGuideTemplateEngine
from src.dual_guide_input import build_dual_guide_profile_from_input
from src.machine_config import load_machine_config
from src.spec_parser import parse_block_spec, parse_relief_spec
from src.template_audit import build_double_guide_template_reports


def test_guide_section_analysis_exports_dual_synchronized_fields():
    reports = build_double_guide_template_reports()
    analysis = {
        item["machine_id"]: item for item in reports["guide_section_analysis"]["templates"]
    }["triple_double_up_up_up"]

    assert analysis["dual_section_mode"] == "synchronized"
    assert analysis["section_1_center"] == pytest.approx([3242.768, -106.095])
    assert analysis["section_2_center"] == pytest.approx([3242.768, -201.729])
    assert analysis["is_symmetric"] is False
    assert analysis["shared_parameters"] == [
        "R_form",
        "slot_width",
        "guide_thickness",
        "relief",
        "slot_depth",
    ]


def test_dual_guide_engine_updates_both_sections_synchronously(tmp_path):
    machine = load_machine_config("triple_double_up_up_up")
    spec = parse_block_spec("9.1*4*3")
    profile = build_block_guide_section(
        spec,
        relief=parse_relief_spec("4-1"),
        slot_reference="length",
        slot_clearance=0.05,
        outer_width=machine.block_outer_width,
        thickness_clearance_mid=machine.block_thickness_clearance_mid,
    )

    result = DualGuideTemplateEngine(machine).write_debug_release_and_report(profile, spec, tmp_path)
    release_doc = ezdxf.readfile(result["release_dxf"])
    report = result["report"]

    assert report["shared_parameters"]["slot_width"] == pytest.approx(9.15)
    assert report["shared_parameters"]["guide_thickness"] == pytest.approx(3.09)
    assert report["formulas"]["slot_width"] == "9.10 + 0.05 = 9.15"
    assert report["formulas"]["guide_thickness"] == "3.00 + 0.09 = 3.09"
    assert report["formulas"]["slot_depth"] == "27.00 - 3.00 - 3.09 = 20.91"
    assert report["thickness_clearance"] == pytest.approx(0.09)
    assert report["shared_parameters"]["relief_size"] == pytest.approx(1.0)
    assert report["shared_parameters"]["relief_radius"] == pytest.approx(0.5)
    assert report["shared_parameters"]["relief_equivalent"] == "4-1"
    assert report["checks"]["synchronized_parameters"] is True
    assert report["checks"]["section_1.slot_width == section_2.slot_width"] is True
    assert report["checks"]["section_1.guide_thickness == section_2.guide_thickness"] is True
    assert report["checks"]["section_1.relief == section_2.relief"] is True
    assert report["checks"]["section_1.slot_depth == section_2.slot_depth"] is True
    assert report["checks"]["release_hides_unqualified_product_thickness"] is True
    assert report["checks"]["fixed_590_not_parameterized"] is True
    assert report["checks"]["fixed_27_height"] is True
    assert report["checks"]["fixed_40_width"] is True
    assert not _debug_layers(release_doc)

    slots = _param_slot_bounds_by_section(release_doc)
    assert set(slots) == {"section_1", "section_2"}
    for bounds in slots.values():
        assert bounds["slot_width"] == pytest.approx(9.15)
    for section in report["sections"]:
        assert section["guide_thickness"] == pytest.approx(3.09)
        assert section["slot_depth"] == pytest.approx(20.91)
    measurements = _dimension_measurements_by_text(release_doc)
    assert measurements["9.15±0.01"] == pytest.approx([9.15, 9.15])
    assert measurements["3.09"] == pytest.approx([3.09, 3.09])
    assert "4.29" not in measurements
    assert measurements["6.09"] == pytest.approx([6.09] * 6)
    assert "1.80" not in measurements
    assert "3" not in measurements
    assert "PRODUCT_REFERENCE" not in {entity.dxf.layer for entity in release_doc.modelspace()}
    assert _side_derived_min_x(release_doc) >= 3300.0
    assert report["checks"]["side_view_dimensions_bound_to_r80_wheel_crowns"] is True
    assert len(report["side_view_dimension_audit"]) == 6
    for item in report["side_view_dimension_audit"]:
        assert item["wheel_radius"] == pytest.approx(80.0)
        assert item["dimension_defpoint"] == pytest.approx(item["expected_wheel_crown_point"])
        assert item["measured_value"] == pytest.approx(6.09)
        assert item["is_bound_to_wheel_crown"] is True
    assert report["checks"]["no_legacy_4p29_dimension"] is True
    assert report["checks"]["no_unexplained_1p80_dimension"] is True
    assert report["checks"]["release_side_dimensions_match_report"] is True
    assert report["release_cleanup"]["removed_unexplained_side_dimensions"] == [
        {"handle": "203CE44", "text": "1.80", "measurement": 1.8, "block_texts": ["1.80"]},
        {"handle": "203D034", "text": "1.80", "measurement": 1.8, "block_texts": ["1.80"]},
    ]
    assert not _legacy_text_in_dimension_blocks(release_doc)

    debug_doc = ezdxf.readfile(result["debug_dxf"])
    debug_measurements = _dimension_measurements_by_text(debug_doc)
    assert debug_measurements["产品厚度 3（参考）"] == pytest.approx([3.0, 3.0])
    assert {entity.dxf.layer for entity in debug_doc.modelspace() if entity.dxftype() == "DIMENSION" and entity.dxf.text == "产品厚度 3（参考）"} == {
        "PRODUCT_REFERENCE"
    }
    assert len(list(Path(tmp_path).glob("*.dxf"))) == 2


def test_dual_guide_engine_down_up_up_enforces_lower_wheel_notch_safety(tmp_path):
    machine = load_machine_config("triple_double_down_up_up")
    spec = parse_block_spec("9.1*4*3")
    profile = build_block_guide_section(
        spec,
        relief=parse_relief_spec("4-1"),
        slot_reference="length",
        slot_clearance=0.05,
        outer_width=machine.block_outer_width,
        thickness_clearance_mid=machine.block_thickness_clearance_mid,
    )

    result = DualGuideTemplateEngine(machine).write_debug_release_and_report(profile, spec, tmp_path)
    release_doc = ezdxf.readfile(result["release_dxf"])
    report = result["report"]

    assert machine.section_profile.profile_type == "rectangular_block"
    assert machine.section_profile.bottom_surface_type == "plane"
    assert machine.section_profile.top_surface_type == "plane"
    assert machine.section_profile.bottom_radius is None
    assert report["guide_length"] == pytest.approx(590.0)
    assert report["guide_sections"] == 2
    assert report["dual_section_mode"] == "synchronized"
    assert report["section_profile_type"] == "rectangular_block"
    assert report["bottom_surface_type"] == "plane"
    assert report["top_surface_type"] == "plane"
    assert report["bottom_radius"] is None
    assert report["top_radius"] is None
    assert report["section_1_profile"] == report["section_2_profile"]
    assert report["product"]["product_length"] == pytest.approx(9.1)
    safety = report["lower_wheel_notch_safety"]
    assert safety["product_length"] == pytest.approx(9.1)
    assert safety["natural_cut_in_formula"] == "thickness * 0.6"
    assert safety["natural_cut_in_depth"] == pytest.approx(1.8)
    assert safety["opening_limit_formula"] == "product_length - 0.2"
    assert safety["opening_limit"] == pytest.approx(8.9)
    assert safety["lower_cavity_notch_opening"] == pytest.approx(8.9)
    assert safety["effective_cut_in_depth"] == pytest.approx(0.123862, abs=0.000001)
    assert safety["lower_wheel_center_y"] == pytest.approx(-685.354811, abs=0.000001)
    assert safety["lower_cavity_notch_opening_less_than_product_length"] is True
    assert safety["lower_cavity_notch_opening_within_limit"] is True
    assert report["shared_parameters"]["slot_width"] == pytest.approx(9.15)
    assert report["shared_parameters"]["guide_thickness"] == pytest.approx(3.09)
    assert report["shared_parameters"]["lower_cavity_notch_opening"] == pytest.approx(8.9)
    assert report["formulas"]["slot_width"] == "9.10 + 0.05 = 9.15"
    assert report["formulas"]["guide_thickness"] == "3.00 + 0.09 = 3.09"
    assert report["formulas"]["slot_depth"] == "fixed section_slot_base_height = 12.00"
    assert report["checks"]["section_1.slot_width == section_2.slot_width"] is True
    assert report["checks"]["section_1.guide_thickness == section_2.guide_thickness"] is True
    assert report["checks"]["section_1.profile_type == section_2.profile_type"] is True
    assert report["checks"]["side_view_dimensions_bound_to_r80_wheel_crowns"] is True
    assert report["checks"]["release_side_dimensions_match_report"] is True
    assert report["checks"]["lower_wheel_notch_opening <= product_length - 0.2"] is True
    assert report["checks"]["lower_cavity_notch_opening_less_than_product_length"] is True
    assert report["checks"]["fixed_590_not_parameterized"] is True

    slots = _param_slot_bounds_by_section(release_doc)
    assert set(slots) == {"section_1", "section_2"}
    for bounds in slots.values():
        assert bounds["slot_width"] == pytest.approx(9.15)
    assert _param_slot_arc_count(release_doc, 23.57) == 0

    measurements = _dimension_measurements_by_text(release_doc)
    assert measurements["9.15±0.01"] == pytest.approx([9.15, 9.15])
    assert measurements["3.09"] == pytest.approx([3.09, 3.09])
    assert "R23.57" not in measurements
    assert not any("6.6" in text or "2.4" in text or "2.46" in text for text in measurements)
    assert not _legacy_substrings_in_dimension_blocks(release_doc, ("R23.57", "6.6", "2.4", "2.46"))
    assert len(report["side_view_dimension_audit"]) == 6
    for item in report["side_view_dimension_audit"]:
        assert item["wheel_radius"] == pytest.approx(80.0)
        assert item["dimension_defpoint"] == pytest.approx(item["expected_wheel_crown_point"])
        assert item["is_bound_to_wheel_crown"] is True

    lower_arc_centers = [
        (round(entity.dxf.center.x, 3), round(entity.dxf.center.y, 3))
        for entity in release_doc.modelspace().query('ARC[layer=="SIDE_TEMPLATE"]')
        if entity.dxf.radius == pytest.approx(80.0)
        and round(((entity.dxf.start_angle + entity.dxf.end_angle) / 2.0) % 360.0, 3) == pytest.approx(90.0)
    ]
    assert (3459.205, -187.871) in lower_arc_centers
    assert (3488.454, -685.355) in lower_arc_centers
    assert _side_gap_width_at_center(release_doc, -107.995, 3459.205, "SIDE_DERIVED_RELEASE") == pytest.approx(8.9)
    assert _side_gap_width_at_center(release_doc, -605.479, 3488.454, "SIDE_DERIVED_RELEASE") == pytest.approx(8.9)


def test_dual_guide_engine_down_up_up_supports_same_r_tile(tmp_path):
    machine = load_machine_config("triple_double_down_up_up")
    input_data = {
        "finished_product_spec": "R30*R30*17.4*23.5*3.95",
        "pre_grinding_spec": (
            "R30*R30*17.4(+0/-0.02)*23.5*3.95(+0.02/-0.02)"
        ),
        "finished_product_shape": "tile",
        "pre_grinding_shape": "same_r_tile",
        "guide_profile_source": "pre_grinding_spec",
        "relief": "4-1",
    }
    _, spec, profile, decision = build_dual_guide_profile_from_input(
        input_data,
        machine,
    )

    result = DualGuideTemplateEngine(machine).write_debug_release_and_report(
        profile,
        spec,
        tmp_path,
        input_rule={
            **decision.as_dict(),
            "input_rule_valid": True,
            "input_mode": "explicit_input_json",
        },
    )
    release_doc = ezdxf.readfile(result["release_dxf"])
    report = result["report"]
    measurements = _dimension_measurements_by_text(release_doc)

    assert "same_r_tile" in machine.supported_section_profiles
    assert report["release_allowed"]
    assert report["formulas"]["slot_width"] == "17.39 + 0.04 = 17.43"
    assert report["formulas"]["guide_thickness"] == "3.95 + 0.25 = 4.20"
    assert report["shared_parameters"]["R_form"] == pytest.approx(30.0)
    assert report["shared_parameters"]["slot_width"] == pytest.approx(17.43)
    assert report["shared_parameters"]["guide_thickness"] == pytest.approx(4.20)
    assert report["section_profile_type"] == "same_r_tile"
    assert report["finished_product_shape"] == "tile"
    assert report["pre_grinding_shape"] == "same_r_tile"
    assert report["guide_profile_source"] == "pre_grinding_spec"
    assert report["final_section_profile_type"] == "same_r_tile"
    assert report["R_form_source"] == "pre_grinding_spec_equal_R"
    assert report["bottom_radius"] == pytest.approx(30.0)
    assert report["top_radius"] == pytest.approx(30.0)
    assert measurements["17.43±0.01"] == pytest.approx([17.43, 17.43])
    assert measurements["R30.00"] == pytest.approx([30.0, 30.0])
    assert _param_slot_arc_count(release_doc, 30.0) == 6
    assert _param_slot_arc_count(release_doc, 23.57) == 0
    assert not _legacy_substrings_in_dimension_blocks(
        release_doc,
        ("R23.57", "6.6", "2.4", "2.46"),
    )
    assert not list(release_doc.modelspace().query('*[layer=="SIDE_DERIVED"]'))
    release_lines = list(
        release_doc.modelspace().query(
            'LINE[layer=="SIDE_DERIVED_RELEASE"]'
        )
    )
    assert release_lines
    assert all(
        release_doc.layers.get(entity.dxf.layer).dxf.linetype
        == "Continuous"
        for entity in release_lines
    )
    dimension_audit = json.loads(
        result["dimension_definition_point_audit_json"].read_text(
            encoding="utf-8"
        )
    )
    assert dimension_audit["release_allowed"] is True
    assert dimension_audit["all_dimensions_bound_to_geometry"] is True
    assert dimension_audit["all_required_roles_pass"] is True
    assert all(
        item["point_error"] <= 0.01
        for item in dimension_audit["dimensions"]
    )
    for role in (
        "slot_width",
        "R_form",
        "guide_thickness",
        "lower_wheel_crown_depth",
        "upper_wheel_related",
        "lower_cavity_notch_opening",
        "fixed_guide_length_590",
        "fixed_span_99",
        "fixed_span_90",
        "fixed_span_180",
        "fixed_span_131",
    ):
        assert dimension_audit["required_roles"][role]["status"] == "PASS"
    assert len(list(Path(tmp_path).glob("release.candidate.dxf"))) == 0


def _param_slot_bounds_by_section(doc) -> dict[str, dict[str, float]]:
    sections = {
        "section_1": {"ys": [], "xs": []},
        "section_2": {"ys": [], "xs": []},
    }
    for entity in doc.modelspace().query('LINE[layer=="PARAM_SLOT"]'):
        y_mid = (entity.dxf.start.y + entity.dxf.end.y) / 2.0
        section_id = "section_1" if y_mid > -150.0 else "section_2"
        sections[section_id]["ys"].extend([entity.dxf.start.y, entity.dxf.end.y])
        sections[section_id]["xs"].extend([entity.dxf.start.x, entity.dxf.end.x])
    return {
        section_id: {
            "slot_width": round(max(values["xs"]) - min(values["xs"]), 3),
        }
        for section_id, values in sections.items()
        if values["xs"] and values["ys"]
    }


def _debug_layers(doc) -> list[str]:
    return sorted(layer for layer in {entity.dxf.layer for entity in doc.modelspace()} if "DEBUG" in layer)


def _dimension_measurements_by_text(doc) -> dict[str, list[float]]:
    measurements = {}
    for dimension in doc.modelspace().query("DIMENSION"):
        text = dimension.dxf.text if dimension.dxf.hasattr("text") else ""
        if not text:
            continue
        measurements.setdefault(text, []).append(round(float(dimension.get_measurement()), 3))
    return measurements


def _side_derived_min_x(doc) -> float:
    min_x = None
    for entity in doc.modelspace().query('*[layer=="SIDE_DERIVED_RELEASE"]'):
        if entity.dxftype() != "LINE":
            continue
        entity_min = min(entity.dxf.start.x, entity.dxf.end.x)
        min_x = entity_min if min_x is None else min(min_x, entity_min)
    assert min_x is not None
    return min_x


def _legacy_text_in_dimension_blocks(doc) -> bool:
    for block in doc.blocks:
        for entity in block:
            text = None
            if entity.dxftype() == "TEXT":
                text = entity.dxf.text
            elif entity.dxftype() == "MTEXT":
                text = entity.text
            if text in {"4.29", "1.80"}:
                return True
    return False


def _legacy_substrings_in_dimension_blocks(doc, needles: tuple[str, ...]) -> bool:
    for block in doc.blocks:
        for entity in block:
            text = None
            if entity.dxftype() == "TEXT":
                text = entity.dxf.text
            elif entity.dxftype() == "MTEXT":
                text = entity.text
            if text and any(needle in text for needle in needles):
                return True
    return False


def _param_slot_arc_count(doc, radius: float) -> int:
    return sum(
        1
        for entity in doc.modelspace().query('ARC[layer=="PARAM_SLOT"]')
        if entity.dxf.radius == pytest.approx(radius)
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
            tuple(round(value, 3) for value in sorted((entity.dxf.start.x, entity.dxf.end.x)))
            for entity in doc.modelspace()
            if entity.dxf.layer == layer
            and entity.dxftype() == "LINE"
            and entity.dxf.start.y == pytest.approx(y, abs=0.001)
            and entity.dxf.end.y == pytest.approx(y, abs=0.001)
        },
        key=lambda values: values[0],
    )
    left = max(segment for segment in segments if segment[1] <= center_x)
    right = min(segment for segment in segments if segment[0] >= center_x)
    return right[0] - left[1]

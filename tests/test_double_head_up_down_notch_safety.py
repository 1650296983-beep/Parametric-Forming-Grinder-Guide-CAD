from math import sqrt

import ezdxf
import pytest

from src.dxf_writer import write_dxf
from src.geometry import build_tile_section
from src.global_rules import wheel_notch_opening_limit
from src.inspection import inspect_release_dxf
from src.machine_config import load_machine_config
from src.side_view import build_side_view_geometry
from src.spec_parser import parse_company_tile_spec
from src.validation_report import write_validation_report_json


def test_double_head_up_down_applies_lower_wheel_notch_safety_to_geometry(tmp_path):
    machine = load_machine_config("double_head_up_down")
    spec = parse_company_tile_spec("R13.73*R17.13*4.50(-0.02/-0.05)*9.6*1.6")
    profile = build_tile_section(
        spec,
        outer_width=machine.section_outer_width,
        center_opening=machine.section_center_opening,
        slot_base_height=machine.section_slot_base_height,
    )
    release_path = tmp_path / "double_head_up_down_release.dxf"

    write_dxf(profile, release_path, output_mode="release", machine_id=machine.machine_id)

    doc = ezdxf.readfile(release_path)
    side = build_side_view_geometry(profile, layout=machine.side_layout)
    expected_opening = wheel_notch_opening_limit(spec.length)
    assert side.derived.lower_cavity_notch_opening == pytest.approx(expected_opening)
    assert _lower_notch_opening_from_lines(doc, machine, side) == pytest.approx(expected_opening)

    lower_arc = _lower_r80_arc(doc, machine)
    expected_effective_depth = 80.0 - sqrt(80.0**2 - (expected_opening / 2.0) ** 2)
    expected_center_y = machine.side_layout.lower_y + 12.0 + expected_effective_depth - 80.0
    assert lower_arc.dxf.center.y == pytest.approx(expected_center_y)

    inspection = inspect_release_dxf(profile, machine, release_path)
    lower_check = next(check for check in inspection["checks"] if check["name"] == "lower_wheel_notch_safety")
    assert inspection["release_allowed"] is True
    assert lower_check["ok"] is True
    assert lower_check["details"]["opening_measured_from_geometry"] == pytest.approx(5.76)
    assert lower_check["details"]["opening_report_value"] == pytest.approx(5.76)


def test_double_head_up_down_report_outputs_lower_wheel_shift_payload(tmp_path):
    machine = load_machine_config("double_head_up_down")
    spec = parse_company_tile_spec("R13.73*R17.13*4.50(-0.02/-0.05)*9.6*1.6")
    profile = build_tile_section(
        spec,
        outer_width=machine.section_outer_width,
        center_opening=machine.section_center_opening,
        slot_base_height=machine.section_slot_base_height,
    )
    debug_path = tmp_path / "debug.dxf"
    release_path = tmp_path / "release.dxf"
    preview_path = tmp_path / "preview.png"
    report_path = tmp_path / "report.json"
    write_dxf(profile, debug_path, output_mode="debug", machine_id=machine.machine_id)
    write_dxf(profile, release_path, output_mode="release", machine_id=machine.machine_id)

    report = write_validation_report_json(
        profile,
        spec,
        machine,
        debug_dxf=debug_path,
        release_dxf=release_path,
        preview_png=preview_path,
        report_path=report_path,
        release_inspection_dxf=release_path,
    )

    notch = report["side_view"]["wheel_notch"]
    assert report["release_allowed"] is True
    assert notch["product_length"] == pytest.approx(9.6)
    assert notch["opening_limit"] == pytest.approx(5.76)
    assert notch["lower_cavity_notch_opening"] == pytest.approx(5.76)
    assert notch["effective_cut_in_depth"] > 0.05
    assert notch["wheel_center_shift"] < -0.9
    assert notch["adjusted_wheel_center_y"] == pytest.approx(notch["lower_wheel_center_y"])


def _lower_r80_arc(doc, machine):
    return next(
        entity
        for entity in doc.modelspace().query("ARC")
        if entity.dxf.layer == "SIDE_TEMPLATE"
        and entity.dxf.radius == pytest.approx(80.0)
        and entity.dxf.center.x == pytest.approx(machine.side_layout.center_b_x)
        and entity.dxf.center.y < machine.side_layout.lower_y
    )


def _lower_notch_opening_from_lines(doc, machine, side) -> float:
    center_x = machine.side_layout.center_b_x
    base_y = machine.side_layout.lower_y + side.derived.slot_base_height
    segments = sorted(
        {
            tuple(round(value, 3) for value in sorted((entity.dxf.start.x, entity.dxf.end.x)))
            for entity in doc.modelspace()
            if entity.dxf.layer == "SIDE_DERIVED"
            and entity.dxftype() == "LINE"
            and entity.dxf.start.y == pytest.approx(base_y, abs=0.001)
            and entity.dxf.end.y == pytest.approx(base_y, abs=0.001)
            and (
                max(entity.dxf.start.x, entity.dxf.end.x) <= center_x
                or min(entity.dxf.start.x, entity.dxf.end.x) >= center_x
            )
        }
    )
    left = max(segment for segment in segments if segment[1] < center_x)
    right = min(segment for segment in segments if segment[0] > center_x)
    return right[0] - left[1]

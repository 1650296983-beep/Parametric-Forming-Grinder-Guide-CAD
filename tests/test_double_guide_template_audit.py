from pathlib import Path

import pytest

from src.template_audit import (
    DEFAULT_DOUBLE_GUIDE_TEMPLATE_DIR,
    DOUBLE_GUIDE_TEMPLATE_SPECS,
    build_double_guide_template_reports,
    generate_double_guide_template_reports,
)


def test_double_guide_audit_uses_version_controlled_templates():
    for spec in DOUBLE_GUIDE_TEMPLATE_SPECS:
        template_path = DEFAULT_DOUBLE_GUIDE_TEMPLATE_DIR / spec.machine_id / spec.template_filename
        assert template_path.is_file()
        assert template_path.stat().st_size > 0


def test_double_guide_audit_identifies_590_templates_and_two_sections():
    reports = build_double_guide_template_reports()
    audit_templates = {
        item["machine_id"]: item for item in reports["template_audit_report"]["templates"]
    }
    analysis_templates = {
        item["machine_id"]: item for item in reports["guide_section_analysis"]["templates"]
    }
    fixed_templates = {
        item["machine_id"]: item for item in reports["fixed_template_geometry"]["templates"]
    }

    assert set(audit_templates) == {
        "triple_double_down_up_up",
        "triple_double_up_up_up",
    }
    for machine_id, audit in audit_templates.items():
        assert audit["guide_length"] == pytest.approx(590.0)
        assert audit["guide_sections"] == 2

        fixed = fixed_templates[machine_id]
        assert fixed["guide_length"]["measured_from_dimension_chain"] == pytest.approx(590.0)
        assert fixed["side_fixed_spans"] == pytest.approx([99.0, 90.0, 90.0, 180.0, 131.0])
        assert [item["length"] for item in fixed["guide_section_spans"]] == pytest.approx([189.0, 401.0])

        analysis = analysis_templates[machine_id]
        assert analysis["dual_product_mode"] is False
        assert analysis["shared_product_parameter_policy"]["slot_width"] == "shared"
        assert analysis["section_relationship"]["composed_of_two_sections"] is True
        assert analysis["section_relationship"]["fully_symmetric"] is False
        assert len(analysis["sections"]) == 2
        assert [section["relief_geometry"]["independent_relief_detected"] for section in analysis["sections"]] == [
            True,
            True,
        ]

    assert audit_templates["triple_double_down_up_up"]["entity_counts"]["DIMENSION"] == 41
    assert audit_templates["triple_double_down_up_up"]["arc_radius_summary"]["by_radius"] == [
        {"radius": 0.5, "count": 12},
        {"radius": 23.57, "count": 2},
        {"radius": 80.0, "count": 6},
    ]
    assert audit_templates["triple_double_up_up_up"]["entity_counts"]["DIMENSION"] == 38
    assert audit_templates["triple_double_up_up_up"]["arc_radius_summary"]["by_radius"] == [
        {"radius": 0.25, "count": 8},
        {"radius": 80.0, "count": 6},
    ]
    assert fixed_templates["triple_double_down_up_up"]["guide_section_spacing"][
        "cross_section_centerline_to_centerline"
    ] == pytest.approx(80.706)
    assert fixed_templates["triple_double_up_up_up"]["guide_section_spacing"][
        "cross_section_centerline_to_centerline"
    ] == pytest.approx(95.634)


def test_double_guide_audit_distinguishes_lower_and_upper_wheel_reliefs():
    reports = build_double_guide_template_reports()
    fixed_by_machine = {
        item["machine_id"]: item for item in reports["fixed_template_geometry"]["templates"]
    }

    down_up_up = fixed_by_machine["triple_double_down_up_up"]
    down_centers_y = [arc["center"][1] for arc in down_up_up["r80_wheel_notches"]]
    assert min(down_centers_y) == pytest.approx(-685.379)
    assert max(down_centers_y) == pytest.approx(-106.388)

    up_up_up = fixed_by_machine["triple_double_up_up_up"]
    up_centers_y = [arc["center"][1] for arc in up_up_up["r80_wheel_notches"]]
    assert sorted(up_centers_y) == pytest.approx(
        [-401.484, -401.484, -401.484, -112.429, -112.429, -16.795],
        abs=0.001,
    )
    assert len(up_up_up["fixed_hole_positions"]) == 4


def test_double_guide_report_writer_outputs_only_json(tmp_path):
    paths = generate_double_guide_template_reports(output_dir=tmp_path)

    assert set(paths) == {
        "template_audit_report",
        "fixed_template_geometry",
        "guide_section_analysis",
    }
    for path in paths.values():
        assert Path(path).suffix == ".json"
        assert Path(path).exists()
    assert not list(tmp_path.glob("*.dxf"))
    assert not list(tmp_path.glob("*.png"))

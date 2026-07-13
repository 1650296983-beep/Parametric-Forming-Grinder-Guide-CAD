import json
from pathlib import Path

import pytest

from src.dxf_writer import write_dxf
from src.dual_guide_release_audit import build_dimension_definition_point_audit
from src.guide_design_input import build_single_guide_profile_from_input
from src.machine_config import load_machine_config
from src.reference_dxf_audit import (
    audit_reference_dxf,
    compare_reference_to_generated,
)
from src.validation_report import build_validation_report_payload


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    (
        "case_number",
        "reference_slot_width",
        "reference_guide_thickness",
        "reference_profile",
        "reference_product_radii",
        "expected_approved_overrides",
    ),
    (
        (
            1,
            5.02,
            2.35,
            "flat_arc_groove",
            (14.3, 16.3),
            {"guide_thickness"},
        ),
        (
            2,
            8.56,
            2.20,
            "rectangular_groove",
            (9.6,),
            {"guide_thickness"},
        ),
        (
            3,
            12.15,
            2.20,
            "rectangular_groove",
            (24.7,),
            {"slot_width", "guide_thickness"},
        ),
    ),
)
def test_three_dual_spec_examples_generate_valid_release_and_compare_to_archived_dxf(
    tmp_path,
    case_number,
    reference_slot_width,
    reference_guide_thickness,
    reference_profile,
    reference_product_radii,
    expected_approved_overrides,
):
    machine = load_machine_config("triple_single_down_up")
    input_data = json.loads(
        (ROOT / f"examples/dual_spec/example_{case_number}.json").read_text(
            encoding="utf-8"
        )
    )
    finished_spec, _, profile, decision = build_single_guide_profile_from_input(
        input_data,
        machine,
    )
    release_path = tmp_path / f"example_{case_number}_release.dxf"
    write_dxf(
        profile,
        release_path,
        output_mode="release",
        machine_id=machine.machine_id,
    )
    dimension_audit = build_dimension_definition_point_audit(
        release_path,
        profile,
        machine,
    )

    assert release_path.exists()
    assert dimension_audit["release_allowed"] is True
    assert all(
        item["point_error"] is not None and item["point_error"] <= 0.01
        for item in dimension_audit["dimensions"]
    )
    validation_report = build_validation_report_payload(
        profile,
        finished_spec,
        machine,
        debug_dxf=release_path,
        release_dxf=release_path,
        preview_png=tmp_path / "preview.png",
        release_inspection_dxf=release_path,
        input_rule=decision.as_dict(),
        dimension_definition_point_audit=dimension_audit,
    )
    assert validation_report["dual_spec_validation"]["all_pass"] is True
    assert validation_report["release_allowed"] is True

    reference = audit_reference_dxf(
        ROOT / f"tests/reference_drawings/instance_{case_number}_reference.dxf"
    )
    assert reference.slot_width == pytest.approx(reference_slot_width)
    assert reference.guide_thickness == pytest.approx(reference_guide_thickness)
    assert reference.center_opening == pytest.approx(2.0)
    assert reference.section_profile == reference_profile
    assert reference.product_radii == pytest.approx(reference_product_radii)
    if case_number == 1:
        assert reference.section_arc_radii == pytest.approx((16.3,))
        assert reference.section_arc_side == "lower"
        assert reference.section_flat_side == "upper"
        assert reference.section_arc_center_side == "upper"
    else:
        assert reference.section_arc_radii == ()
        assert reference.section_arc_side is None
        assert reference.section_flat_side is None
        assert reference.section_arc_center_side is None

    generated_report = {
        "paths": {"release_dxf": str(release_path)},
        "input_rule": decision.as_dict(),
        "process_parameters": {
            "slot_width": {"slot_width": profile.guide_spec.guide_slot_width},
            "guide_thickness": {"result": profile.guide_spec.guide_thickness},
        },
        "fixed_template_dimensions": {
            "section": {
                "outer_width": machine.section_outer_width,
                "outer_height": profile.guide_spec.outer_height,
                "slot_base_height": machine.section_slot_base_height,
                "center_opening": machine.section_center_opening,
            }
        },
        "release_allowed": dimension_audit["release_allowed"],
    }
    comparison = compare_reference_to_generated(reference, generated_report)

    assert comparison["status"] == "PASS"
    assert comparison["hard_failures"] == []
    assert comparison["unresolved_rule_conflicts"] == []
    assert set(comparison["approved_rule_overrides"]) == expected_approved_overrides
    assert comparison["checks"]["product_drawing_radius_evidence"]["status"] == "PASS"

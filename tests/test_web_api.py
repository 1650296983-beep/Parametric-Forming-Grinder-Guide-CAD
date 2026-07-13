from __future__ import annotations

from pathlib import Path

from src.web_api import DesignInput, _task_file_payload, list_machines, validate_design


def _triple_single_block_request() -> DesignInput:
    return DesignInput(
        machine_type="triple_single_down_up",
        guide_rail_type="single_guide",
        wheel_sequence=["下", "上"],
        first_wheel_side="lower",
        template_coordinate_system="section_xy_y_up",
        finished_spec="R9.6*8.6*42.6*2.1",
        pre_grinding_spec="42.6*8.6(-0.07/-0.09)*2.1(+0.01/-0.01)",
        product_shape_after="bread_shape",
        product_shape_before="rectangular_block",
        tolerance={
            "width_upper_deviation": -0.07,
            "width_lower_deviation": -0.09,
            "thickness_upper_deviation": 0.01,
            "thickness_lower_deviation": -0.01,
        },
    )


def test_web_api_lists_template_derived_machines() -> None:
    machines = list_machines()

    triple_single = next(machine for machine in machines if machine["id"] == "triple_single_down_up")
    assert triple_single["guide_length"] == 379.0
    assert triple_single["wheel_positions"] == ["下", "上"]


def test_web_api_calculates_from_existing_dual_spec_rules() -> None:
    result = validate_design(_triple_single_block_request())

    assert result["decision"]["groove_profile"] == "rectangular_groove"
    assert result["derived"]["slot_width"] == 8.56
    assert result["derived"]["guide_thickness"] == 2.22
    assert result["release_ready"] is False


def test_task_file_payload_only_exposes_generated_task_files(tmp_path: Path) -> None:
    task_dir = tmp_path / "abc123def456"
    preview = task_dir / "artifacts" / "preview" / "guide.png"
    report = task_dir / "artifacts" / "reports" / "guide_report.json"
    preview.parent.mkdir(parents=True)
    report.parent.mkdir(parents=True)
    preview.write_bytes(b"preview")
    report.write_text("{}", encoding="utf-8")

    payload = _task_file_payload(
        "abc123def456",
        task_dir,
        {"paths": {"preview_png": str(preview)}},
    )

    assert payload["preview_png"]["url"].endswith("/artifacts/preview/guide.png")
    assert payload["report_json"]["name"] == "guide_report.json"

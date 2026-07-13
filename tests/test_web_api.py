from __future__ import annotations

from pathlib import Path

import src.web_api as web_api
from src.web_api import (
    DesignInput,
    GenerationRequest,
    _task_file_payload,
    generate_design,
    list_machines,
    validate_design,
)


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


def _triple_double_tile_request() -> DesignInput:
    return DesignInput(
        machine_type="triple_double_down_up_up",
        guide_rail_type="double_guide",
        wheel_sequence=["下", "上", "上"],
        first_wheel_side="lower",
        template_coordinate_system="section_xy_y_up",
        finished_spec="R30*R28*17.4*23.5*3.95",
        pre_grinding_spec="23.5*17.4(+0/-0.02)*3.95(+0.02/-0.02)",
        product_shape_after="tile_shape",
        product_shape_before="rectangular_block",
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


def test_web_api_calculates_dual_guide_with_centralized_profile_rule() -> None:
    result = validate_design(_triple_double_tile_request())

    assert result["machine"]["supported_by_web_generation"] is True
    assert result["decision"]["groove_profile"] == "flat_arc_groove"
    assert result["decision"]["guide_profile_source"] == "finished_product_big_r_with_pre_grinding_block"
    assert result["derived"]["slot_width"] == 17.43


def test_web_api_generates_release_gated_dual_guide_artifacts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(web_api, "WEB_OUTPUT_ROOT", tmp_path)

    result = generate_design(GenerationRequest(design=_triple_double_tile_request()))

    assert result["ok"] is True
    assert result["release_allowed"] is True
    assert result["report"]["checks"]["synchronized_parameters"] is True
    assert result["report"]["dimension_definition_point_audit"]["release_allowed"] is True
    assert result["files"]["release_dxf"]["name"] == (
        "R30×R28×17.4×23.5×3.95（23.5×17.4×3.95）三头机双导轨（下上上）.dxf"
    )
    assert Path(result["report"]["paths"]["release_dxf"]).is_file()
    assert Path(result["report"]["paths"]["preview_png"]).is_file()


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

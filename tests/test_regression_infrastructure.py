from pathlib import Path
import importlib.util
import json


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_regression_tests.py"
MACHINE_IDS = {
    "bed_618",
    "double_head_up_down",
    "double_head_up_up",
    "triple_single_down_up",
    "triple_single_up_up",
    "triple_double_down_up_up",
    "triple_double_up_up_up",
}


def _load_regression_script():
    spec = importlib.util.spec_from_file_location("run_regression_tests", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_regression_cases_have_required_baseline_files():
    for machine_id in MACHINE_IDS:
        case_dir = REPO_ROOT / "tests" / "regression" / machine_id / "case_001"
        assert (case_dir / "input.json").exists()
        for filename in (
            "expected_report.json",
            "expected_release.dxf",
            "expected_debug.dxf",
            "expected_preview.png",
            "expected_audit.json",
        ):
            path = case_dir / filename
            assert path.exists(), f"missing {path}"
            assert path.stat().st_size > 0


def test_template_meta_files_exist_with_required_fields():
    required = {
        "machine_id",
        "template_version",
        "source_template_file",
        "sha256",
        "change_reason",
        "approved_by",
        "approved_date",
    }
    for machine_id in MACHINE_IDS:
        path = REPO_ROOT / "templates" / machine_id / "template_meta.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert required <= set(payload)
        assert payload["machine_id"] == machine_id
        assert payload["template_version"].startswith("v")
        assert len(payload["sha256"]) == 64


def test_high_risk_change_detection_catches_fixed_machine_fields():
    regression = _load_regression_script()
    report = {"changed_dimensions": []}
    old_core = {"guide_length": 435.0, "guide_sections": 1, "wheel_positions": ["上", "下"]}
    new_core = {"guide_length": 590.0, "guide_sections": 2, "wheel_positions": ["下", "上", "上"]}

    reasons = regression.risk_reasons(report, old_core, new_core)

    assert any("guide_length changed" in reason for reason in reasons)
    assert any("guide_sections changed" in reason for reason in reasons)
    assert any("wheel_positions changed" in reason for reason in reasons)

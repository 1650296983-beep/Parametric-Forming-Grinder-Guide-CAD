"""Frozen fixtures survive approved rules without waiving physical DXF checks."""

from pathlib import Path
import hashlib
import importlib.util
import json
import shutil

import ezdxf
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def generated_migration_cases(tmp_path_factory):
    spec = importlib.util.spec_from_file_location(
        "approved_rule_regression", REPO_ROOT / "scripts" / "run_regression_tests.py"
    )
    regression = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(regression)
    root = tmp_path_factory.mktemp("approved-rule-regression") / "regression"
    shutil.copytree(regression.REGRESSION_ROOT, root)
    cases = regression.discover_cases(root)
    frozen_before = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("expected_*")
    }
    for case in cases:
        result = regression.run_case(case)
        assert result["generation_ok"], result["generation_errors"]
    yield regression, root, cases
    assert frozen_before == {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("expected_*")
    }


def test_all_seven_frozen_cases_pass_only_the_exact_rule_migration(generated_migration_cases):
    regression, _, cases = generated_migration_cases
    assert len(cases) == 7
    for case in cases:
        result = regression.compare_case(case)
        assert result["ok"], (case.parent.name, result["differences"])


def _copied_case(generated, tmp_path):
    regression, root, _ = generated
    source = root / "bed_618" / "case_001"
    case = tmp_path / "bed_618" / "case_001"
    shutil.copytree(source, case)
    return regression, case


def test_rule_migration_rejects_changed_fixed_dimension(generated_migration_cases, tmp_path):
    regression, case = _copied_case(generated_migration_cases, tmp_path)
    path = case / "actual_release.dxf"
    doc = ezdxf.readfile(path)
    fixed = next(entity for entity in doc.modelspace().query("DIMENSION") if entity.dxf.text == "27.00")
    fixed.dxf.text = "28.00"
    doc.saveas(path)

    result = regression.compare_case(case)

    assert not result["ok"]
    assert any("text" in difference and "28.00" in difference for difference in result["differences"])


@pytest.mark.parametrize("mode", ["release", "debug"])
def test_rule_migration_rejects_displaced_actual_wheel_even_with_passed_report(
    generated_migration_cases, tmp_path, mode
):
    regression, case = _copied_case(generated_migration_cases, tmp_path)
    path = case / f"actual_{mode}.dxf"
    doc = ezdxf.readfile(path)
    wheel = next(arc for arc in doc.modelspace().query("ARC") if abs(arc.dxf.radius - 80) < 0.001)
    wheel.dxf.center = (wheel.dxf.center.x, wheel.dxf.center.y - 1.0, 0)
    doc.saveas(path)
    # Persisted success is deliberately kept unchanged. Compare must re-read DXF.
    report = json.loads((case / "actual_report.json").read_text(encoding="utf-8"))
    assert report["release_allowed"]

    result = regression.compare_case(case)

    assert not result["ok"]
    assert any("live upper wheel projection audit failed" in difference for difference in result["differences"])


def test_rule_migration_rejects_unbound_opening_definition_point(generated_migration_cases, tmp_path):
    regression, case = _copied_case(generated_migration_cases, tmp_path)
    path = case / "actual_release.dxf"
    doc = ezdxf.readfile(path)
    opening = next(entity for entity in doc.modelspace().query("DIMENSION") if entity.dxf.text == "1.86")
    point = opening.dxf.defpoint2
    opening.dxf.defpoint2 = (point.x + 50.123, point.y + 50.123, point.z)
    doc.saveas(path)

    result = regression.compare_case(case)

    assert not result["ok"]
    assert any("live dimension definition-point audit failed" in difference for difference in result["differences"])


def test_rule_migration_rejects_any_modified_frozen_source(generated_migration_cases, tmp_path):
    regression, case = _copied_case(generated_migration_cases, tmp_path)
    path = case / "expected_report.json"
    path.write_bytes(path.read_bytes() + b"\n")

    result = regression.compare_case(case)

    assert not result["ok"]
    assert result["differences"] == ["Rule migration source hash changed: expected_report.json"]


def test_rule_migration_requires_exact_source_leaf(generated_migration_cases):
    regression, _, _ = generated_migration_cases
    with pytest.raises(ValueError, match="source value changed"):
        regression.apply_exact_rule_migration(
            {"dimension": 27.0},
            [{"path": ["dimension"], "before": 26.0, "after": 28.0}],
        )

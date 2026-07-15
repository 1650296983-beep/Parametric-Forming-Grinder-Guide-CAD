from __future__ import annotations

from src.dimension_writer import SECTION_DIMENSION_TEMPLATE_PATH
from src.dxf_writer import DEFAULT_TEMPLATE_PATHS
from src.side_view_config import DEFAULT_SIDE_VIEW_TEMPLATE
from src.template_paths import LEGACY_TEMPLATE_ROOT


REQUIRED_LEGACY_TEMPLATE_FILENAMES = {
    "section_dimension_template.dxf",
    "standard_guide_template.dxf",
    "R17_45XR15_8X6_2X1_65_clean_template.dxf",
    "R17_45XR15_8X6_2X1_65_clean_template_latest.dxf",
    "导轨长度投影（干净模板）.dxf",
    "导轨长度，codex.dxf",
}


def test_legacy_templates_are_versioned_under_templates_directory() -> None:
    """Required CAD source assets must not depend on ignored root-level files."""
    assert LEGACY_TEMPLATE_ROOT.name == "legacy_reference"
    assert {
        path.name for path in LEGACY_TEMPLATE_ROOT.glob("*.dxf")
    } == REQUIRED_LEGACY_TEMPLATE_FILENAMES
    for template_path in LEGACY_TEMPLATE_ROOT.glob("*.dxf"):
        assert template_path.stat().st_size > 1_000_000


def test_legacy_template_consumers_use_project_managed_paths() -> None:
    assert SECTION_DIMENSION_TEMPLATE_PATH.parent == LEGACY_TEMPLATE_ROOT
    assert DEFAULT_SIDE_VIEW_TEMPLATE.parent == LEGACY_TEMPLATE_ROOT
    assert {path.name for path in DEFAULT_TEMPLATE_PATHS} == {
        "standard_guide_template.dxf",
        "R17_45XR15_8X6_2X1_65_clean_template.dxf",
        "R17_45XR15_8X6_2X1_65_clean_template_latest.dxf",
    }

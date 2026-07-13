from pathlib import Path

import ezdxf

from src.dxf_writer import write_dxf
from src.geometry import build_tile_section
from src.preview import write_png_preview
from src.side_view_validator import write_side_view_report
from src.spec_parser import parse_company_tile_spec


def test_side_view_outputs_dxf_png_and_report(tmp_path):
    tile_section = build_tile_section(parse_company_tile_spec("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65"))
    dxf_path = tmp_path / "combined.dxf"
    png_path = tmp_path / "combined.png"
    report_path = tmp_path / "side_report.txt"

    write_dxf(tile_section, dxf_path, output_mode="release")
    write_png_preview(tile_section, png_path)
    write_side_view_report(tile_section, report_path, dxf_path=dxf_path, output_mode="release")

    assert dxf_path.exists() and dxf_path.stat().st_size > 0
    assert png_path.exists() and png_path.stat().st_size > 0
    assert report_path.exists() and report_path.stat().st_size > 0

    doc = ezdxf.readfile(dxf_path)
    layers = {entity.dxf.layer for entity in doc.modelspace()}
    assert "PARAM_SLOT" in layers
    assert "SIDE_TEMPLATE" in layers
    assert "SIDE_DIMENSION" in layers

    report = Path(report_path).read_text(encoding="utf-8")
    assert "side_projected_slot_height_formula: 12.000000 + 0.500000 = 12.500000" in report
    assert "side_clearance_height_formula: 27.000000 - 12.000000 - 1.830000 + 0.200000 = 13.370000" in report
    assert "measured_side_clearance_height_from_dimension_group_42: 13.370000" in report
    assert "side_view_combined_with_section: PASS" in report
    assert "derived_dimension_texts_present: PASS" in report
    assert "R80_arc_count_matches_template: PASS" in report
    assert "fixed_LINE_ARC_LWPOLYLINE_preserved: PASS" in report
    assert "no_full_length_SIDE_DERIVED_lines: PASS" in report
    assert "release_hides_formula_text: PASS" in report
    assert "side_projected_geometry_dimension_text_consistent: PASS" in report
    assert "side_clearance_geometry_dimension_text_consistent: PASS" in report

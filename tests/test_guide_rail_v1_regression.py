import ezdxf
import pytest

from src.dxf_writer import write_dxf
from src.geometry import build_tile_section
from src.preview import write_png_preview
from src.spec_parser import parse_company_tile_spec
from src.validator import validate_tile_section, write_geometry_report


V1_SPECS = [
    "R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65",
    "R20.00*R18.20*7.00(-0.02/-0.04)*18.0*1.80",
    "R12.50*R11.30*5.50(-0.02/-0.04)*12.0*1.20",
    "R25.00*R22.80*8.50(-0.02/-0.04)*20.0*2.20",
    "R16.20*R14.95*6.00(-0.02/-0.04)*14.0*1.25",
]


@pytest.mark.parametrize("raw_spec", V1_SPECS)
def test_v1_multi_spec_outputs_are_generated(tmp_path, raw_spec):
    tile_spec = parse_company_tile_spec(raw_spec)
    tile_section = build_tile_section(tile_spec)
    validation = validate_tile_section(tile_section)
    name = _artifact_name(raw_spec)
    dxf_path = tmp_path / f"{name}.dxf"
    png_path = tmp_path / f"{name}.png"
    report_path = tmp_path / f"{name}_geometry_report.txt"

    write_dxf(tile_section, dxf_path, output_mode="release")
    write_png_preview(tile_section, png_path)
    write_geometry_report(tile_section, validation, report_path, tile_spec=tile_spec)

    assert dxf_path.exists()
    assert png_path.exists()
    assert report_path.exists()
    assert dxf_path.stat().st_size > 0
    assert png_path.stat().st_size > 0
    assert report_path.stat().st_size > 0
    assert validation.ok, validation.errors


@pytest.mark.parametrize("raw_spec", V1_SPECS)
def test_v1_parametric_rules_and_release_annotations(tmp_path, raw_spec):
    tile_spec = parse_company_tile_spec(raw_spec)
    tile_section = build_tile_section(tile_spec)
    guide = tile_section.guide_spec
    dxf_path = tmp_path / f"{_artifact_name(raw_spec)}_release.dxf"

    write_dxf(tile_section, dxf_path, output_mode="release")
    doc = ezdxf.readfile(dxf_path)
    entities = list(doc.modelspace())

    assert not doc.audit().errors
    assert tile_section.forming_spec.R_form == pytest.approx(
        max(tile_spec.R_outer_finished, tile_spec.R_inner_finished)
    )
    assert guide.guide_slot_width == pytest.approx(tile_spec.chord_width + 0.01)
    assert guide.guide_thickness == pytest.approx(tile_spec.finished_thickness + 0.18)
    assert guide.outer_width == pytest.approx(33.0)
    assert guide.outer_height == pytest.approx(27.0)
    assert guide.slot_base_height == pytest.approx(12.0)
    assert guide.center_opening == pytest.approx(1.5)
    assert guide.relief.relief_count == 4
    assert guide.relief.relief_size / 2.0 == pytest.approx(0.5)

    validation = validate_tile_section(tile_section)
    assert validation.ok, validation.errors
    _assert_profile_closed(tile_section.finished_profile)
    _assert_profile_closed(tile_section.forming_profile)

    slot_arcs = [entity for entity in entities if entity.dxf.layer == "PARAM_SLOT" and entity.dxftype() == "ARC"]
    r_form_arcs = [arc for arc in slot_arcs if arc.dxf.radius == pytest.approx(tile_section.forming_spec.R_form)]
    relief_arcs = [arc for arc in slot_arcs if arc.dxf.radius == pytest.approx(0.5)]
    assert len(r_form_arcs) >= 2
    assert len(relief_arcs) == 4

    dimension_texts = [
        entity.dxf.text
        for entity in entities
        if entity.dxf.layer == "DIMENSION" and entity.dxftype() == "DIMENSION"
    ]
    displayed_texts = _dimension_block_texts(doc)
    dimension_measurements = _dimension_measurements_by_text(doc)
    assert guide.slot_width_dimension_text in dimension_texts
    assert f"R{tile_section.forming_spec.R_form:.2f}" in dimension_texts
    assert f"{guide.guide_thickness:.2f}" in dimension_texts
    assert f"{guide.center_opening:.1f}" in dimension_texts
    assert f"{guide.slot_base_height:.1f}" in dimension_texts
    assert f"{guide.outer_width:.0f}" in dimension_texts
    assert f"{guide.outer_height:.1f}" in dimension_texts
    assert guide.slot_width_dimension_text in displayed_texts
    assert f"{guide.guide_thickness:.2f}" in displayed_texts
    assert f"R{tile_section.forming_spec.R_form:.2f}" in displayed_texts
    assert dimension_measurements[guide.slot_width_dimension_text][0] == pytest.approx(guide.guide_slot_width)
    assert dimension_measurements[f"{guide.guide_thickness:.2f}"][0] == pytest.approx(guide.guide_thickness)
    assert dimension_measurements[f"R{tile_section.forming_spec.R_form:.2f}"] == pytest.approx(
        [tile_section.forming_spec.R_form, tile_section.forming_spec.R_form]
    )
    assert dimension_measurements[f"{guide.center_opening:.1f}"][0] == pytest.approx(guide.center_opening)
    assert dimension_measurements[f"{guide.slot_base_height:.1f}"][0] == pytest.approx(guide.slot_base_height)
    assert dimension_measurements[f"{guide.outer_width:.0f}"][0] == pytest.approx(guide.outer_width)
    assert dimension_measurements[f"{guide.outer_height:.1f}"][0] == pytest.approx(guide.outer_height)

    assert not any(entity.dxf.layer == "DEBUG_CONTROL" for entity in entities)
    assert not any(entity.dxf.layer == "DEBUG_POINTS" for entity in entities)
    assert not any(entity.dxf.layer == "DIMENSION_TEXT_FALLBACK" for entity in entities)
    assert not any(entity.dxf.layer == "REFERENCE_PROFILE" for entity in entities)
    assert {entity.dxf.layer for entity in entities} <= {
        "FIXED_TEMPLATE",
        "SECTION_CENTER",
        "PARAM_SLOT",
        "DIMENSION",
        "SIDE_TEMPLATE",
        "SIDE_DERIVED",
        "SIDE_DIMENSION",
        "SIDE_CENTER",
    }


def test_debug_output_contains_reference_control_fallback_and_debug_points(tmp_path):
    tile_spec = parse_company_tile_spec(V1_SPECS[0])
    tile_section = build_tile_section(tile_spec)
    dxf_path = tmp_path / "debug.dxf"

    write_dxf(tile_section, dxf_path, output_mode="debug")
    doc = ezdxf.readfile(dxf_path)
    layers = {entity.dxf.layer for entity in doc.modelspace()}

    assert "REFERENCE_PROFILE" in layers
    assert "DEBUG_CONTROL" in layers
    assert "DEBUG_POINTS" in layers
    assert "DIMENSION" in layers
    assert "DIMENSION_TEXT_FALLBACK" not in layers
    assert any(entity.dxftype() == "POINT" for entity in doc.modelspace() if entity.dxf.layer == "DEBUG_POINTS")


def test_single_real_company_spec_r16_release_output(tmp_path):
    tile_spec = parse_company_tile_spec("R16*R14.3*5.00(-0.02/-0.04)*14*1.7")
    tile_section = build_tile_section(tile_spec)
    guide = tile_section.guide_spec
    dxf_path = tmp_path / "single_real_r16_release.dxf"

    write_dxf(tile_section, dxf_path, output_mode="release")
    doc = ezdxf.readfile(dxf_path)
    entities = list(doc.modelspace())

    assert not doc.audit().errors
    assert tile_section.forming_spec.R_form == pytest.approx(16.0)
    assert guide.guide_slot_width == pytest.approx(5.01)
    assert guide.guide_thickness == pytest.approx(1.88)
    assert guide.outer_width == pytest.approx(33.0)
    assert guide.outer_height == pytest.approx(27.0)
    assert guide.slot_base_height == pytest.approx(12.0)
    assert guide.center_opening == pytest.approx(1.5)

    measurements = _dimension_measurements_by_text(doc)
    group_42 = _dimension_group_42_by_text(doc)
    displayed = _dimension_block_texts(doc)
    assert measurements["5.01±0.01"][0] == pytest.approx(5.01)
    assert measurements["1.88"][0] == pytest.approx(1.88)
    assert measurements["R16.00"] == pytest.approx([16.0, 16.0])
    assert measurements["4-r0.5"][0] == pytest.approx(0.5)
    assert group_42["5.01±0.01"][0] == pytest.approx(5.01)
    assert group_42["1.88"][0] == pytest.approx(1.88)
    assert group_42["R16.00"] == pytest.approx([16.0, 16.0])
    assert group_42["4-r0.5"][0] == pytest.approx(0.5)
    section_geometry = _section_geometry_measurements(entities)
    assert section_geometry["slot_width"] == pytest.approx(5.01)
    assert section_geometry["guide_thickness"] == pytest.approx(1.88)
    assert section_geometry["relief_radius"] == pytest.approx(0.5)
    assert section_geometry["r_form_radii"] == pytest.approx([16.0, 16.0, 16.0])
    assert "6.25±0.01" not in displayed
    assert "1.90" not in displayed
    assert "R17.45" not in displayed

    side_measurements = _side_dimension_measurements_by_text(doc)
    side_group_42 = _side_dimension_group_42_by_text(doc)
    assert side_measurements["12.50"][0] == pytest.approx(12.50)
    assert side_measurements["13.32"][0] == pytest.approx(13.32)
    assert side_group_42["12.50"][0] == pytest.approx(12.50)
    assert side_group_42["13.32"][0] == pytest.approx(13.32)
    side_geometry = _side_geometry_measurements(entities)
    assert side_geometry["projected_slot_height"] == pytest.approx(12.50, abs=0.001)
    assert side_geometry["clearance_height"] == pytest.approx(13.32, abs=0.001)
    assert side_geometry["fixed_spans"] == pytest.approx([90.0, 200.0, 145.0, 435.0])
    assert side_geometry["r80_count"] == 2
    assert "13.30" not in _side_dimension_block_texts(doc)

    slot_arcs = [entity for entity in entities if entity.dxf.layer == "PARAM_SLOT" and entity.dxftype() == "ARC"]
    assert sum(1 for arc in slot_arcs if arc.dxf.radius == pytest.approx(16.0)) == 3
    assert sum(1 for arc in slot_arcs if arc.dxf.radius == pytest.approx(0.5)) == 4
    assert not any(
        entity.dxf.layer == "FIXED_TEMPLATE"
        and entity.dxftype() == "ARC"
        and entity.dxf.radius == pytest.approx(17.45)
        for entity in entities
    )
    assert sum(
        1
        for entity in entities
        if entity.dxf.layer == "SIDE_TEMPLATE"
        and entity.dxftype() == "ARC"
        and entity.dxf.radius == pytest.approx(80.0)
    ) == 2
    assert not any("DEBUG" in entity.dxf.layer for entity in entities)


def _assert_profile_closed(profile):
    for index, current in enumerate(profile.segments):
        following = profile.segments[(index + 1) % len(profile.segments)]
        assert current.end.distance_to(following.start) < 0.001


def _artifact_name(raw_spec: str) -> str:
    return raw_spec.replace("*", "_").replace(".", "p")


def _dimension_block_texts(doc) -> list[str]:
    texts = []
    for dimension in doc.modelspace():
        if dimension.dxf.layer != "DIMENSION" or dimension.dxftype() != "DIMENSION":
            continue
        if not dimension.dxf.hasattr("geometry") or dimension.dxf.geometry not in doc.blocks:
            continue
        for entity in doc.blocks[dimension.dxf.geometry]:
            if entity.dxftype() == "TEXT":
                texts.append(entity.dxf.text)
            elif entity.dxftype() == "MTEXT":
                texts.append(entity.text)
    return texts


def _dimension_measurements_by_text(doc) -> dict[str, list[float]]:
    measurements = {}
    for dimension in doc.modelspace():
        if dimension.dxf.layer == "DIMENSION" and dimension.dxftype() == "DIMENSION":
            measurements.setdefault(dimension.dxf.text, []).append(dimension.get_measurement())
    return measurements


def _dimension_group_42_by_text(doc) -> dict[str, list[float]]:
    measurements = {}
    for dimension in doc.modelspace():
        if (
            dimension.dxf.layer == "DIMENSION"
            and dimension.dxftype() == "DIMENSION"
            and dimension.dxf.hasattr("actual_measurement")
        ):
            measurements.setdefault(dimension.dxf.text, []).append(dimension.dxf.actual_measurement)
    return measurements


def _side_dimension_measurements_by_text(doc) -> dict[str, list[float]]:
    measurements = {}
    for dimension in doc.modelspace():
        if dimension.dxf.layer == "SIDE_DIMENSION" and dimension.dxftype() == "DIMENSION" and dimension.dxf.text:
            measurements.setdefault(dimension.dxf.text, []).append(dimension.get_measurement())
    return measurements


def _side_dimension_group_42_by_text(doc) -> dict[str, list[float]]:
    measurements = {}
    for dimension in doc.modelspace():
        if (
            dimension.dxf.layer == "SIDE_DIMENSION"
            and dimension.dxftype() == "DIMENSION"
            and dimension.dxf.text
            and dimension.dxf.hasattr("actual_measurement")
        ):
            measurements.setdefault(dimension.dxf.text, []).append(dimension.dxf.actual_measurement)
    return measurements


def _side_dimension_block_texts(doc) -> list[str]:
    texts = []
    for dimension in doc.modelspace():
        if dimension.dxf.layer != "SIDE_DIMENSION" or dimension.dxftype() != "DIMENSION":
            continue
        if not dimension.dxf.hasattr("geometry") or dimension.dxf.geometry not in doc.blocks:
            continue
        for entity in doc.blocks[dimension.dxf.geometry]:
            if entity.dxftype() == "TEXT":
                texts.append(entity.dxf.text)
            elif entity.dxftype() == "MTEXT":
                texts.append(entity.text)
    return texts


def _section_geometry_measurements(entities) -> dict[str, object]:
    arcs = [entity for entity in entities if entity.dxf.layer == "PARAM_SLOT" and entity.dxftype() == "ARC"]
    relief = [arc for arc in arcs if arc.dxf.radius == pytest.approx(0.5)]
    r_form = [arc.dxf.radius for arc in arcs if arc.dxf.radius == pytest.approx(16.0)]
    return {
        "slot_width": max(arc.dxf.center.x for arc in relief) - min(arc.dxf.center.x for arc in relief),
        "guide_thickness": max(arc.dxf.center.y for arc in relief) - min(arc.dxf.center.y for arc in relief),
        "relief_radius": relief[0].dxf.radius,
        "r_form_radii": r_form,
    }


def _side_geometry_measurements(entities) -> dict[str, object]:
    r80_arcs = [
        entity
        for entity in entities
        if entity.dxf.layer == "SIDE_TEMPLATE" and entity.dxftype() == "ARC" and entity.dxf.radius == pytest.approx(80.0)
    ]
    lower = [arc for arc in r80_arcs if arc.dxf.center.y < 35.84968472437504][0]
    upper = [arc for arc in r80_arcs if arc.dxf.center.y > 62.84968472437504][0]
    vertical_lines = [
        entity
        for entity in entities
        if entity.dxf.layer in {"SIDE_TEMPLATE", "SIDE_CENTER"}
        and entity.dxftype() == "LINE"
        and entity.dxf.start.x == pytest.approx(entity.dxf.end.x)
        and min(entity.dxf.start.y, entity.dxf.end.y) <= 35.9
        and max(entity.dxf.start.y, entity.dxf.end.y) >= 62.8
    ]
    xs = sorted(round(line.dxf.start.x, 6) for line in vertical_lines)
    left, center_a, center_b, right = xs[0], xs[1], xs[2], xs[-1]
    return {
        "projected_slot_height": lower.dxf.center.y + lower.dxf.radius - 35.84968472437504,
        "clearance_height": 62.84968472437504 - (upper.dxf.center.y - upper.dxf.radius),
        "fixed_spans": [center_a - left, center_b - center_a, right - center_b, right - left],
        "r80_count": len(r80_arcs),
    }

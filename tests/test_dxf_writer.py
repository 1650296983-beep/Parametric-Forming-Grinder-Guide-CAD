import ezdxf
import pytest

from src.dxf_writer import write_dxf
from src.geometry import build_tile_section
from src.spec_parser import parse_company_tile_spec


def test_guide_slot_is_arc_based_not_rectangular(tmp_path):
    spec = parse_company_tile_spec("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65")
    tile_section = build_tile_section(spec)
    path = tmp_path / "guide_slot.dxf"

    write_dxf(tile_section, path)
    doc = ezdxf.readfile(path)
    auditor = doc.audit()

    assert not auditor.errors
    by_layer = {}
    for entity in doc.modelspace():
        by_layer.setdefault(entity.dxf.layer, []).append(entity)

    assert set(by_layer) == {
        "FIXED_TEMPLATE",
        "SECTION_CENTER",
        "PARAM_SLOT",
        "DIMENSION",
        "DEBUG_CONTROL",
        "DEBUG_POINTS",
        "REFERENCE_PROFILE",
        "SIDE_TEMPLATE",
        "SIDE_DIMENSION",
        "SIDE_DEBUG",
        "SIDE_CENTER",
    }
    assert "SIDE_DERIVED" in {layer.dxf.name for layer in doc.layers}
    _assert_drawing_standard_layers(doc)
    assert not doc.layers.get("DIMENSION_TEXT_FALLBACK").is_off()
    slot_entities = by_layer["PARAM_SLOT"]
    slot_arcs = [entity for entity in slot_entities if entity.dxftype() == "ARC"]
    slot_lines = [entity for entity in slot_entities if entity.dxftype() == "LINE"]
    r_form_arcs = [arc for arc in slot_arcs if arc.dxf.radius == pytest.approx(17.45)]
    relief_arcs = [arc for arc in slot_arcs if arc.dxf.radius == pytest.approx(0.5)]

    assert len(slot_arcs) >= 7
    assert len(r_form_arcs) >= 3
    assert len(relief_arcs) == 4
    assert not _has_short_center_opening_arc(r_form_arcs, tile_section.guide_spec.center_opening / 2.0)
    assert _has_center_opening_lines(slot_lines, width=1.5)
    assert _slot_width_from_relief_centers(relief_arcs) == pytest.approx(6.21)
    assert _guide_thickness_from_relief_centers(relief_arcs) == pytest.approx(1.83)
    assert len(slot_lines) >= 4
    assert not _has_horizontal_slot_surface_line(slot_lines, y=12.0, width=6.21, center_x=0.0)
    assert not _has_horizontal_slot_surface_line(slot_lines, y=13.9, width=6.21, center_x=0.0)


def test_fixed_template_and_dimension_entities_are_present(tmp_path):
    spec = parse_company_tile_spec("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65")
    tile_section = build_tile_section(spec)
    path = tmp_path / "guide_slot.dxf"

    write_dxf(tile_section, path)
    doc = ezdxf.readfile(path)
    entities = list(doc.modelspace())

    fixed_lines = [entity for entity in entities if entity.dxf.layer == "FIXED_TEMPLATE" and entity.dxftype() == "LINE"]
    native_dimension_texts = [
        entity.dxf.text
        for entity in entities
        if entity.dxf.layer == "DIMENSION" and entity.dxftype() == "DIMENSION"
    ]
    displayed_texts = _dimension_block_texts(doc)

    assert len(fixed_lines) >= 6
    assert any("6.21±0.01" in text for text in native_dimension_texts)
    assert any("1.83" in text for text in native_dimension_texts)
    assert native_dimension_texts.count("R17.45") == 2
    assert any("1.5" in text for text in native_dimension_texts)
    assert any("12.0" in text for text in native_dimension_texts)
    assert any(text == "33" for text in native_dimension_texts)
    assert any("27.0" in text for text in native_dimension_texts)
    assert any("6.21±0.01" in text for text in displayed_texts)
    assert any("1.83" in text for text in displayed_texts)
    assert displayed_texts.count("R17.45") == 2
    assert any("1.5" in text for text in displayed_texts)
    assert any("12.0" in text for text in displayed_texts)
    assert any(text == "33" for text in displayed_texts)
    assert any("27.0" in text for text in displayed_texts)
    assert any("4-r0.5" in text for text in displayed_texts)


def test_release_dxf_has_only_native_dimensions_and_text_notes(tmp_path):
    spec = parse_company_tile_spec("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65")
    tile_section = build_tile_section(spec)
    path = tmp_path / "guide_slot_release.dxf"

    write_dxf(tile_section, path, output_mode="release")
    doc = ezdxf.readfile(path)
    entities = list(doc.modelspace())

    assert not doc.audit().errors
    assert not any(entity.dxf.layer == "DIMENSION_TEXT_FALLBACK" for entity in entities)
    assert not any(entity.dxf.layer == "DEBUG_CONTROL" for entity in entities)
    assert not any(entity.dxf.layer == "DEBUG_POINTS" for entity in entities)
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
    assert {layer.dxf.name for layer in doc.layers} <= {
        "0",
        "Defpoints",
        "FIXED_TEMPLATE",
        "SECTION_CENTER",
        "PARAM_SLOT",
        "DIMENSION",
        "SIDE_TEMPLATE",
        "SIDE_DERIVED",
        "SIDE_DIMENSION",
        "SIDE_CENTER",
    }
    dimension_texts = [
        entity.dxf.text
        for entity in entities
        if entity.dxf.layer == "DIMENSION" and entity.dxftype() == "DIMENSION"
    ]
    displayed_texts = _dimension_block_texts(doc)

    assert any("6.21±0.01" in text for text in dimension_texts)
    assert any("1.83" in text for text in dimension_texts)
    assert dimension_texts.count("R17.45") == 2
    assert any("1.5" in text for text in dimension_texts)
    assert any("12.0" in text for text in dimension_texts)
    assert any(text == "33" for text in dimension_texts)
    assert any("27.0" in text for text in dimension_texts)
    assert any("4-r0.5" in text for text in dimension_texts)
    assert any("6.21±0.01" in text for text in displayed_texts)
    assert any("4-r0.5" in text for text in displayed_texts)
    _assert_drawing_standard_layers(doc)


def test_relief_override_changes_corner_arc_radius(tmp_path):
    spec = parse_company_tile_spec("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65")
    from src.spec_parser import ReliefSpec

    tile_section = build_tile_section(spec, relief=ReliefSpec(relief_count=4, relief_size=0.6))
    path = tmp_path / "guide_slot_relief_0p6.dxf"

    write_dxf(tile_section, path)
    doc = ezdxf.readfile(path)
    relief_arcs = [
        entity
        for entity in doc.modelspace()
        if entity.dxf.layer == "PARAM_SLOT"
        and entity.dxftype() == "ARC"
        and entity.dxf.radius == pytest.approx(0.3)
    ]

    assert len(relief_arcs) == 4


def _has_horizontal_slot_surface_line(lines, y: float, width: float, center_x: float) -> bool:
    left = center_x - width / 2.0
    right = center_x + width / 2.0
    for line in lines:
        start = line.dxf.start
        end = line.dxf.end
        if start.y == pytest.approx(y) and end.y == pytest.approx(y):
            xs = sorted((start.x, end.x))
            if xs[0] == pytest.approx(left) and xs[1] == pytest.approx(right):
                return True
    return False


def _has_center_opening_lines(lines, width: float) -> bool:
    vertical_xs = sorted(
        round(line.dxf.start.x, 6)
        for line in lines
        if line.dxf.start.x == pytest.approx(line.dxf.end.x)
        and abs(line.dxf.end.y - line.dxf.start.y) > 5
    )
    for left, right in zip(vertical_xs, vertical_xs[1:]):
        if right - left == pytest.approx(width):
            return True
    return False


def _slot_width_from_relief_centers(relief_arcs) -> float:
    xs = sorted(round(arc.dxf.center.x, 6) for arc in relief_arcs)
    return xs[-1] - xs[0]


def _guide_thickness_from_relief_centers(relief_arcs) -> float:
    ys = sorted(round(arc.dxf.center.y, 6) for arc in relief_arcs)
    return ys[-1] - ys[0]


def _has_short_center_opening_arc(arcs, length: float) -> bool:
    for arc in arcs:
        sweep = abs(arc.dxf.end_angle - arc.dxf.start_angle)
        if sweep > 180.0:
            sweep = 360.0 - sweep
        arc_length = arc.dxf.radius * sweep * 3.141592653589793 / 180.0
        if arc_length == pytest.approx(length, abs=0.01):
            return True
    return False


def _assert_drawing_standard_layers(doc) -> None:
    assert doc.layers.get("SECTION_CENTER").dxf.color == 1
    assert doc.layers.get("SECTION_CENTER").dxf.linetype == "CENTER"
    assert doc.layers.get("SIDE_CENTER").dxf.color == 1
    assert doc.layers.get("SIDE_CENTER").dxf.linetype == "CENTER"
    assert doc.layers.get("SIDE_DERIVED").dxf.color == 3
    assert doc.layers.get("SIDE_DERIVED").dxf.linetype == "DASHED"
    assert any(entity.dxftype() == "LINE" and entity.dxf.layer == "SECTION_CENTER" for entity in doc.modelspace())


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

import ezdxf
import pytest

from src.dxf_writer import write_dxf
from src.geometry import build_tile_section
from src.spec_parser import parse_company_tile_spec


def test_side_view_geometry_is_present_in_release_dxf(tmp_path):
    tile_section = build_tile_section(parse_company_tile_spec("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65"))
    path = tmp_path / "side_release.dxf"

    write_dxf(tile_section, path, output_mode="release")
    doc = ezdxf.readfile(path)
    entities = list(doc.modelspace())

    assert not doc.audit().errors
    assert any(entity.dxf.layer == "SIDE_TEMPLATE" for entity in entities)
    assert "SIDE_DERIVED" in {layer.dxf.name for layer in doc.layers}
    assert any(entity.dxf.layer == "SIDE_CENTER" for entity in entities)
    assert not any(entity.dxf.layer == "SIDE_DEBUG" for entity in entities)
    assert doc.layers.get("SIDE_CENTER").dxf.color == 1
    assert doc.layers.get("SIDE_CENTER").dxf.linetype == "CENTER"
    assert doc.layers.get("SIDE_DERIVED").dxf.color == 3
    assert doc.layers.get("SIDE_DERIVED").dxf.linetype == "DASHED"
    assert sum(
        entity.dxftype() == "ARC"
        and entity.dxf.layer == "SIDE_TEMPLATE"
        and entity.dxf.radius == pytest.approx(80.0)
        for entity in entities
    ) == 2
    cavity_lines = [
        entity
        for entity in entities
        if entity.dxf.layer == "SIDE_DERIVED"
        and entity.dxftype() == "LINE"
    ]
    assert cavity_lines
    assert len(
        {round(float(entity.dxf.start.y), 6) for entity in cavity_lines}
    ) == 4


def test_side_view_dimensions_preserve_template_positions_and_update_derived_text(tmp_path):
    tile_section = build_tile_section(parse_company_tile_spec("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65"))
    path = tmp_path / "side_release.dxf"

    write_dxf(tile_section, path, output_mode="release")
    doc = ezdxf.readfile(path)
    labels = _side_dimension_labels(doc)

    for expected in ("90", "200", "145", "435", "R80", "12.50", "13.54"):
        assert expected in labels
    measurements_by_text = {
        entity.dxf.text: entity.get_measurement()
        for entity in doc.modelspace()
        if entity.dxf.layer == "SIDE_DIMENSION"
        and entity.dxftype() == "DIMENSION"
        and entity.dxf.text in {"12.50", "13.54"}
    }
    assert measurements_by_text["12.50"] == pytest.approx(12.50)
    assert measurements_by_text["13.54"] == pytest.approx(13.536605623)
    displayed_texts = [
        text
        for entity in doc.modelspace()
        if entity.dxf.layer == "SIDE_DIMENSION" and entity.dxftype() == "DIMENSION"
        for text in _dimension_block_texts(doc, entity)
    ]
    assert "13.54" in displayed_texts
    assert "13.30" not in displayed_texts


def test_side_debug_layer_only_exists_in_debug_output(tmp_path):
    tile_section = build_tile_section(parse_company_tile_spec("R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65"))
    debug_path = tmp_path / "debug.dxf"
    release_path = tmp_path / "release.dxf"

    write_dxf(tile_section, debug_path, output_mode="debug")
    write_dxf(tile_section, release_path, output_mode="release")
    debug_doc = ezdxf.readfile(debug_path)
    release_doc = ezdxf.readfile(release_path)

    assert any(entity.dxf.layer == "SIDE_DEBUG" for entity in debug_doc.modelspace())
    assert not any(entity.dxf.layer == "SIDE_DEBUG" for entity in release_doc.modelspace())


def _side_dimension_labels(doc) -> set[str]:
    labels = set()
    for entity in doc.modelspace():
        if entity.dxf.layer != "SIDE_DIMENSION":
            continue
        if entity.dxftype() == "DIMENSION":
            if entity.dxf.text:
                labels.add(entity.dxf.text)
            measurement = entity.get_measurement()
            labels.add(f"{measurement:.0f}")
            if measurement == pytest.approx(80.0):
                labels.add("R80")
        elif entity.dxftype() == "TEXT":
            labels.add(entity.dxf.text)
    return labels


def _dimension_block_texts(doc, dimension) -> list[str]:
    if not dimension.dxf.hasattr("geometry") or dimension.dxf.geometry not in doc.blocks:
        return []
    texts = []
    for entity in doc.blocks[dimension.dxf.geometry]:
        if entity.dxftype() == "TEXT":
            texts.append(entity.dxf.text)
        elif entity.dxftype() == "MTEXT":
            texts.append(entity.text)
    return texts

import ezdxf

from src.section_contour_audit import (
    build_modelspace_section_contour_closure_audit,
)


def _build_section_modelspace(*, right_mouth_x: float = 1.0, bridge: bool = False):
    doc = ezdxf.new("R12")
    doc.layers.add("FIXED_TEMPLATE", color=7)
    doc.layers.add("PARAM_SLOT", color=7)
    modelspace = doc.modelspace()
    modelspace.add_line((-5.0, 10.0), (-1.0, 10.0), dxfattribs={"layer": "FIXED_TEMPLATE"})
    modelspace.add_line((1.0, 10.0), (5.0, 10.0), dxfattribs={"layer": "FIXED_TEMPLATE"})
    if bridge:
        modelspace.add_line((-5.0, 10.0), (5.0, 10.0), dxfattribs={"layer": "FIXED_TEMPLATE"})
    modelspace.add_line((-1.0, 10.0), (-1.0, 5.0), dxfattribs={"layer": "PARAM_SLOT"})
    modelspace.add_line((-1.0, 5.0), (1.0, 5.0), dxfattribs={"layer": "PARAM_SLOT"})
    modelspace.add_line((1.0, 5.0), (right_mouth_x, 10.0), dxfattribs={"layer": "PARAM_SLOT"})
    return modelspace


def test_section_contour_audit_accepts_exactly_joined_cavity() -> None:
    audit = build_modelspace_section_contour_closure_audit(
        _build_section_modelspace(),
        expected_sections=1,
    )

    assert audit["release_allowed"] is True
    assert audit["sections"][0]["maximum_fixed_join_gap"] == 0.0


def test_section_contour_audit_rejects_open_mouth_over_tolerance() -> None:
    audit = build_modelspace_section_contour_closure_audit(
        _build_section_modelspace(right_mouth_x=1.002),
        expected_sections=1,
    )

    assert audit["release_allowed"] is False
    assert audit["sections"][0]["mouth_connections"][1]["connected"] is False


def test_section_contour_audit_rejects_fixed_line_across_cavity_mouth() -> None:
    audit = build_modelspace_section_contour_closure_audit(
        _build_section_modelspace(bridge=True),
        expected_sections=1,
    )

    assert audit["release_allowed"] is False
    assert audit["sections"][0]["fixed_line_bridges_mouth"] is True


def test_section_contour_audit_rejects_exact_mouth_bridge() -> None:
    modelspace = _build_section_modelspace()
    modelspace.add_line(
        (-1.0, 10.0),
        (1.0, 10.0),
        dxfattribs={"layer": "FIXED_TEMPLATE"},
    )

    audit = build_modelspace_section_contour_closure_audit(
        modelspace,
        expected_sections=1,
    )

    assert audit["release_allowed"] is False
    assert audit["sections"][0]["fixed_line_bridges_mouth"] is True

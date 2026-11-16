from __future__ import annotations

import ezdxf

from src.drawing_scene import scene_from_document
from src.machine_config import load_machine_config


def test_scene_preserves_text_alignment_and_mtext_direction() -> None:
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_line((0, 0), (40, 0), dxfattribs={"layer": "PARAM_SLOT"})
    msp.add_line((0, 0), (0, 27), dxfattribs={"layer": "PARAM_SLOT"})
    msp.add_line((40, 27), (0, 27), dxfattribs={"layer": "PARAM_SLOT"})

    txt = msp.add_text(
        "0.01",
        height=2.5,
        dxfattribs={
            "layer": "DIMENSION",
            "insert": (1, 2),
            "halign": 1,
            "valign": 2,
            "align_point": (10.0, 20.0, 0.0),
        },
    )
    assert txt.dxf.halign == 1
    mtext = msp.add_mtext("R80.00", dxfattribs={"layer": "DIMENSION", "insert": (25.0, 15.0)})
    mtext.dxf.attachment_point = 5
    mtext.dxf.text_direction = (0.0, 1.0, 0.0)

    machine = load_machine_config("double_head_up_up")
    scene = scene_from_document(doc, machine, source="test")
    texts = {
        item["text"]: item
        for view in scene["views"]
        for item in view["primitives"]
        if item["kind"] == "text"
    }
    assert texts["0.01"]["anchor"] == "middle"
    assert texts["0.01"]["baseline"] == "central"
    assert texts["0.01"]["position"] == [10.0, -20.0]
    assert texts["R80.00"]["anchor"] == "middle"
    assert texts["R80.00"]["baseline"] == "central"
    assert texts["R80.00"]["rotation"] == -90.0

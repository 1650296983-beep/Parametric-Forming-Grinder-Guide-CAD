from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.generate_machine import _resolve_output_name
from src.output_naming import build_machine_output_stem


def test_machine_output_stem_uses_calculated_slot_dimensions() -> None:
    stem = build_machine_output_stem(
        "8.85*20*2",
        8.89,
        2.07,
        "双头机（上下）",
    )

    assert stem == "8.85×20×2（8.89×2.07）双头机（上下）"


@pytest.mark.parametrize(
    ("arc_count", "expected"),
    (
        (1, "R32.95×6.81×2.82"),
        (2, "2-R32.95×6.81×2.82"),
    ),
)
def test_machine_output_stem_includes_real_cavity_arc_topology(
    arc_count: int,
    expected: str,
) -> None:
    stem = build_machine_output_stem(
        "R9.25*R32.95*6.8*33*2.5",
        6.81,
        2.82,
        "三头机单导轨（下上）",
        forming_arc_count=arc_count,
        forming_radius=32.95,
    )

    assert f"（{expected}）" in stem


def test_explicit_input_cannot_override_required_output_name() -> None:
    explicit_input = {
        "finished_spec": "R20.15*7*41*1.65",
        "pre_grinding_spec": "41*7(+0.01/-0.01)*1.7(+0.02/+0)",
    }
    profile = SimpleNamespace(
        guide_spec=SimpleNamespace(guide_slot_width=7.04, guide_thickness=1.82)
    )

    assert _resolve_output_name(
        None,
        explicit_input,
        "双头机（上下）",
        None,
        profile=profile,
    ).endswith("双头机（上下）")
    with pytest.raises(ValueError, match="不支持 --name"):
        _resolve_output_name("custom", explicit_input, "双头机（上下）", None)

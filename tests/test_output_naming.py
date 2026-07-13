from __future__ import annotations

import pytest

from src.generate_machine import _resolve_output_name
from src.output_naming import build_machine_output_stem


def test_machine_output_stem_uses_finished_preform_and_machine_name() -> None:
    stem = build_machine_output_stem(
        "R20.15*7*41*1.65",
        "41*7(+0.01/-0.01)*1.7(+0.02/+0)",
        "双头机（上下）",
    )

    assert stem == "R20.15×7×41×1.65（41×7（+0.01／-0.01）×1.7（+0.02／+0））双头机（上下）"


def test_explicit_input_cannot_override_required_output_name() -> None:
    explicit_input = {
        "finished_spec": "R20.15*7*41*1.65",
        "pre_grinding_spec": "41*7(+0.01/-0.01)*1.7(+0.02/+0)",
    }

    assert _resolve_output_name(None, explicit_input, "双头机（上下）", None).endswith("双头机（上下）")
    with pytest.raises(ValueError, match="不支持 --name"):
        _resolve_output_name("custom", explicit_input, "双头机（上下）", None)

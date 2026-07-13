"""Stable, operator-readable names for generated CAD deliverables."""

from __future__ import annotations

import re


_FILENAME_TRANSLATION = str.maketrans(
    {
        "*": "×",
        "/": "／",
        "\\": "＼",
        ":": "：",
        '"': "＂",
        "<": "＜",
        ">": "＞",
        "|": "｜",
        "?": "？",
        "(": "（",
        ")": "）",
    }
)
_MAX_FILENAME_BYTES = 220
_TOLERANCE_ANNOTATION = re.compile(r"[（(][^（）()]*[+-]\s*(?:\d|\.)[^（）()]*[）)]")


def build_machine_output_stem(
    finished_spec: str,
    pre_grinding_spec: str,
    machine_name: str,
) -> str:
    """Build the required output stem from the two explicit specs and machine.

    The displayed structure is ``成品规格（磨前规格）机台类型``. Tolerance
    annotations remain in the input, CAD dimensions, and validation report, but
    are excluded from the filename. Specs use ``*``; its full-width equivalent
    remains portable across macOS and Windows download destinations.
    """
    finished = _normalize_spec(finished_spec, "成品规格")
    pre_grinding = _normalize_spec(pre_grinding_spec, "磨前规格")
    machine = _normalize_component(machine_name, "机台类型")
    stem = f"{finished}（{pre_grinding}）{machine}"
    if len(stem.encode("utf-8")) > _MAX_FILENAME_BYTES:
        raise ValueError("输出文件名过长，请缩短成品规格、磨前规格或机台类型。")
    return stem


def _normalize_spec(value: str, label: str) -> str:
    without_tolerance = _TOLERANCE_ANNOTATION.sub("", value)
    return _normalize_component(re.sub(r"\s+", "", without_tolerance), label)


def _normalize_component(value: str, label: str) -> str:
    normalized = value.strip().translate(_FILENAME_TRANSLATION)
    normalized = "".join(character for character in normalized if ord(character) >= 32)
    if not normalized:
        raise ValueError(f"{label}不能为空，无法生成输出文件名。")
    return normalized.rstrip(". ")

"""Stable, operator-readable names for generated CAD deliverables."""

from __future__ import annotations

from math import isfinite
import re

from .block_geometry import BlockGuideSection
from .geometry import ArcSegment, TileSection


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
    slot_width: float,
    guide_thickness: float,
    machine_name: str,
    *,
    forming_arc_count: int = 0,
    forming_radius: float | None = None,
) -> str:
    """Build the output stem from the finished spec and calculated geometry.

    The displayed structure is ``成品规格（型腔参数）机台类型``. A rectangular
    cavity uses ``槽宽×导轨厚度``; one main arc prepends ``R``; two main arcs
    prepend ``2-R``. Values come from the same profile used to rebuild and
    validate the real slot geometry.
    """
    finished = _normalize_spec(finished_spec, "成品规格")
    calculated = _format_cavity_parameters(
        slot_width,
        guide_thickness,
        forming_arc_count=forming_arc_count,
        forming_radius=forming_radius,
    )
    machine = _normalize_component(machine_name, "机台类型")
    stem = f"{finished}（{calculated}）{machine}"
    if len(stem.encode("utf-8")) > _MAX_FILENAME_BYTES:
        raise ValueError("输出文件名过长，请缩短成品规格或机台类型。")
    return stem


def build_profile_output_stem(
    finished_spec: str,
    profile: BlockGuideSection | TileSection,
    machine_name: str,
) -> str:
    """Build a stem whose arc count and radius are read from final geometry."""
    forming_arc_count = 0
    forming_radius = None
    if isinstance(profile, TileSection):
        forming_arc_count = sum(
            isinstance(segment, ArcSegment)
            for segment in profile.forming_profile.segments
        )
        forming_radius = profile.forming_spec.R_form
    return build_machine_output_stem(
        finished_spec,
        profile.guide_spec.guide_slot_width,
        profile.guide_spec.guide_thickness,
        machine_name,
        forming_arc_count=forming_arc_count,
        forming_radius=forming_radius,
    )


def _format_cavity_parameters(
    slot_width: float,
    guide_thickness: float,
    *,
    forming_arc_count: int,
    forming_radius: float | None,
) -> str:
    if forming_arc_count not in {0, 1, 2}:
        raise ValueError("型腔主弧数量只能是 0、1 或 2，无法生成输出文件名。")
    values = [
        _format_calculated_dimension(slot_width, "槽宽"),
        _format_calculated_dimension(guide_thickness, "导轨厚度"),
    ]
    if forming_arc_count == 0:
        if forming_radius is not None:
            raise ValueError("无主弧型腔不能提供成型 R，无法生成输出文件名。")
        return "×".join(values)
    if forming_radius is None:
        raise ValueError("带主弧型腔缺少成型 R，无法生成输出文件名。")
    radius = _format_calculated_dimension(forming_radius, "成型 R")
    prefix = "R" if forming_arc_count == 1 else "2-R"
    return "×".join((f"{prefix}{radius}", *values))


def _format_calculated_dimension(value: float, label: str) -> str:
    numeric = float(value)
    if not isfinite(numeric) or numeric <= 0.0:
        raise ValueError(f"{label}必须是大于 0 的有限数值，无法生成输出文件名。")
    return f"{numeric:.2f}"


def _normalize_spec(value: str, label: str) -> str:
    without_tolerance = _TOLERANCE_ANNOTATION.sub("", value)
    return _normalize_component(re.sub(r"\s+", "", without_tolerance), label)


def _normalize_component(value: str, label: str) -> str:
    normalized = value.strip().translate(_FILENAME_TRANSLATION)
    normalized = "".join(character for character in normalized if ord(character) >= 32)
    if not normalized:
        raise ValueError(f"{label}不能为空，无法生成输出文件名。")
    return normalized.rstrip(". ")

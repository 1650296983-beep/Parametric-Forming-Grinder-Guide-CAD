from __future__ import annotations

from dataclasses import dataclass

from .spec_parser import (
    BlockSpec,
    FinishedSpec,
    GuideSpec,
    ProductPreFormTolerance,
    ReliefSpec,
)
from .global_rules import BLOCK_THICKNESS_CLEARANCE, CENTER_TRANSITION_RADIUS


@dataclass(frozen=True)
class BlockGuideSection:
    block_spec: BlockSpec
    guide_spec: GuideSpec
    slot_reference: str
    slot_reference_value: float
    slot_clearance: float | None
    finished_spec: FinishedSpec | None = None
    process_type: str = "block"

    @property
    def spec(self) -> BlockSpec:
        return self.block_spec

    @property
    def preform_block_spec(self) -> BlockSpec:
        return self.block_spec

    @property
    def process_length(self) -> float:
        return self.block_spec.length

    @property
    def process_thickness(self) -> float:
        return self.block_spec.thickness_mid


class BlockReliefGeometryError(ValueError):
    """The explicit rectangular groove/relief combination cannot be generated."""


def validate_block_relief_geometry(guide: GuideSpec) -> None:
    """Reject relief overlap before constructing any rectangular DXF entities."""
    diameter = guide.relief.relief_size
    if guide.guide_thickness <= diameter:
        raise BlockReliefGeometryError(
            f"导轨厚度 {guide.guide_thickness:.2f} mm 无法容纳当前避空："
            f"{guide.relief.relief_count} 处直径 {diameter:.2f} mm（R{diameter / 2:.2f}）。"
            f"当前几何要求导轨厚度大于 {diameter:.2f} mm。请由工艺确认适用的避空方案。"
        )
    minimum_width = guide.center_opening + max(
        2.0 * diameter,
        2.0 * CENTER_TRANSITION_RADIUS + diameter,
    )
    if guide.guide_slot_width <= minimum_width:
        raise BlockReliefGeometryError(
            f"槽宽 {guide.guide_slot_width:.2f} mm 无法容纳当前避空："
            f"中心开口 {guide.center_opening:.2f} mm，"
            f"中心固定 R{CENTER_TRANSITION_RADIUS:.2f}，"
            f"{guide.relief.relief_count} 处直径 {diameter:.2f} mm（R{diameter / 2:.2f}），"
            f"当前几何要求槽宽大于 {minimum_width:.2f} mm。"
            "请核对规格，或由工艺确认适用的窄槽避空方案；程序不会自动改变尺寸。"
        )


def build_block_guide_section(
    spec: BlockSpec,
    relief: ReliefSpec | None = None,
    machining_allowance: float = 0.18,
    guide_extra_clearance: float = 0.07,
    thickness_clearance_mid: float | None = None,
    slot_width_tolerance: float = 0.01,
    slot_reference: str = "length",
    slot_clearance: float | None = 0.05,
    outer_width: float = 35.0,
    slot_base_height: float = 12.0,
    center_opening: float = 2.0,
    finished_spec: FinishedSpec | None = None,
    process_type: str = "block",
) -> BlockGuideSection:
    if slot_reference not in {"length", "width"}:
        raise ValueError("slot_reference must be 'length' or 'width'.")
    slot_reference_value = getattr(spec, slot_reference)
    preform_tolerance = ProductPreFormTolerance(upper=0.0, lower=0.0)
    if slot_reference == "length" and spec.has_length_tolerance:
        preform_tolerance = ProductPreFormTolerance(
            upper=spec.length_tolerance_upper,
            lower=spec.length_tolerance_lower,
        )
    elif slot_reference == "width" and spec.has_width_tolerance:
        preform_tolerance = ProductPreFormTolerance(
            upper=spec.width_tolerance_upper,
            lower=spec.width_tolerance_lower,
        )
    guide_spec = GuideSpec(
        # QG thickness clearance is based on the actual preform thickness
        # midpoint, so asymmetric incoming tolerances must affect the groove.
        finished_thickness=spec.thickness_mid,
        chord_width=slot_reference_value,
        machining_allowance=machining_allowance,
        guide_extra_clearance=guide_extra_clearance,
        thickness_clearance_mid=(
            BLOCK_THICKNESS_CLEARANCE
            if thickness_clearance_mid is None
            else thickness_clearance_mid
        ),
        slot_width_tolerance=slot_width_tolerance,
        preform_tolerance=preform_tolerance,
        relief=relief,
        outer_width=outer_width,
        slot_base_height=slot_base_height,
        center_offset=center_opening,
        tolerance_slot_clearance=slot_clearance,
        use_tolerance_based_slot_width=True,
    )
    validate_block_relief_geometry(guide_spec)
    return BlockGuideSection(
        block_spec=spec,
        guide_spec=guide_spec,
        slot_reference=slot_reference,
        slot_reference_value=slot_reference_value,
        slot_clearance=slot_clearance,
        finished_spec=finished_spec,
        process_type=process_type,
    )

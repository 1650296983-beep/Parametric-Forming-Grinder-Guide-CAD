from __future__ import annotations

from dataclasses import dataclass

from .spec_parser import (
    BlockSpec,
    FinishedSpec,
    GuideSpec,
    ProductPreFormTolerance,
    ReliefSpec,
)
from .global_rules import BLOCK_THICKNESS_CLEARANCE


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
    return BlockGuideSection(
        block_spec=spec,
        guide_spec=guide_spec,
        slot_reference=slot_reference,
        slot_reference_value=slot_reference_value,
        slot_clearance=slot_clearance,
        finished_spec=finished_spec,
        process_type=process_type,
    )

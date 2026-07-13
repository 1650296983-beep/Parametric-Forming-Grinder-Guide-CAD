from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .block_geometry import BlockGuideSection, build_block_guide_section
from .geometry import (
    TileSection,
    build_block_to_tile_section,
    build_tile_section,
)
from .machine_config import MachineConfig
from .spec_parser import (
    BlockSpec,
    FinishedSpec,
    parse_block_spec,
    parse_company_bread_spec,
    parse_company_tile_spec,
    parse_relief_spec,
)


@dataclass(frozen=True)
class DualGuideInputDecision:
    finished_product_spec: str
    pre_grinding_spec: str
    finished_product_shape: str
    pre_grinding_shape: str
    guide_profile_source: str
    final_section_profile_type: str
    R_form_source: str

    def as_dict(self) -> dict[str, str]:
        return {
            "finished_product_spec": self.finished_product_spec,
            "pre_grinding_spec": self.pre_grinding_spec,
            "finished_product_shape": self.finished_product_shape,
            "pre_grinding_shape": self.pre_grinding_shape,
            "guide_profile_source": self.guide_profile_source,
            "final_section_profile_type": self.final_section_profile_type,
            "R_form_source": self.R_form_source,
        }


def build_dual_guide_profile_from_input(
    input_data: dict[str, Any],
    machine: MachineConfig,
) -> tuple[
    FinishedSpec,
    FinishedSpec | BlockSpec,
    TileSection | BlockGuideSection,
    DualGuideInputDecision,
]:
    required = (
        "finished_product_spec",
        "pre_grinding_spec",
        "finished_product_shape",
        "pre_grinding_shape",
        "guide_profile_source",
    )
    missing = [key for key in required if not input_data.get(key)]
    if missing:
        raise ValueError(
            "Dual-guide input requires explicit fields: " + ", ".join(missing)
        )

    finished_raw = str(input_data["finished_product_spec"])
    pre_grinding_raw = str(input_data["pre_grinding_spec"])
    finished_shape = str(input_data["finished_product_shape"])
    pre_grinding_shape = str(input_data["pre_grinding_shape"])
    profile_source = str(input_data["guide_profile_source"])
    relief = parse_relief_spec(str(input_data.get("relief", "4-1")))

    if finished_shape == "bread":
        finished_spec = parse_company_bread_spec(finished_raw)
    elif finished_shape == "tile":
        finished_spec = parse_company_tile_spec(
            finished_raw,
            require_chord_tolerance=False,
        )
    else:
        raise ValueError(
            "finished_product_shape must be 'bread' or 'tile'."
        )

    if pre_grinding_shape == "block":
        pre_grinding_spec = parse_block_spec(pre_grinding_raw)
        if profile_source in {
            "pre_grinding_spec",
            "pre_grinding_spec_rectangular_envelope",
        } and finished_shape == "bread":
            profile = build_block_guide_section(
                pre_grinding_spec,
                relief=relief,
                slot_reference=str(input_data.get("slot_reference", "width")),
                slot_clearance=None,
                outer_width=machine.section_outer_width,
                thickness_clearance_mid=machine.block_thickness_clearance_mid,
                slot_base_height=machine.section_slot_base_height,
                center_opening=machine.section_center_opening,
                finished_spec=finished_spec,
                process_type="block_to_bread_rectangular",
            )
            decision = DualGuideInputDecision(
                finished_product_spec=finished_raw,
                pre_grinding_spec=pre_grinding_raw,
                finished_product_shape=finished_shape,
                pre_grinding_shape=pre_grinding_shape,
                guide_profile_source="pre_grinding_spec_rectangular_envelope",
                final_section_profile_type="rectangular_block",
                R_form_source="finished_product_target_only_not_guide_profile",
            )
            return finished_spec, pre_grinding_spec, profile, decision

        if (
            profile_source
            == "finished_product_big_r_with_pre_grinding_block"
            and finished_shape == "tile"
        ):
            arc_side = _first_wheel_side(machine)
            profile = build_block_to_tile_section(
                finished_spec,
                pre_grinding_spec,
                relief=relief,
                thickness_clearance_mid=machine.block_thickness_clearance_mid,
                outer_width=machine.section_outer_width,
                slot_base_height=_block_to_tile_slot_base_height(
                    pre_grinding_spec,
                    machine,
                ),
                center_opening=machine.section_center_opening,
                arc_side=arc_side,
            )
            decision = DualGuideInputDecision(
                finished_product_spec=finished_raw,
                pre_grinding_spec=pre_grinding_raw,
                finished_product_shape=finished_shape,
                pre_grinding_shape=pre_grinding_shape,
                guide_profile_source=profile_source,
                final_section_profile_type=f"flat_arc_{arc_side}_big_r_block_preform",
                R_form_source="max(finished_product_R_outer, finished_product_R_inner)",
            )
            return finished_spec, pre_grinding_spec, profile, decision

        raise ValueError(
            "Invalid explicit block pre-grinding rule combination."
        )

    if pre_grinding_shape == "same_r_tile":
        if profile_source != "pre_grinding_spec":
            raise ValueError(
                "same_r_tile requires guide_profile_source='pre_grinding_spec'."
            )
        pre_grinding_spec = parse_company_tile_spec(pre_grinding_raw)
        if abs(
            pre_grinding_spec.R_outer_finished
            - pre_grinding_spec.R_inner_finished
        ) > 1e-9:
            raise ValueError(
                "pre_grinding_shape='same_r_tile' requires equal pre-grinding radii."
            )
        profile = build_tile_section(
            pre_grinding_spec,
            relief=relief,
            outer_width=machine.section_outer_width,
            slot_base_height=machine.section_slot_base_height,
            center_opening=machine.section_center_opening,
        )
        decision = DualGuideInputDecision(
            finished_product_spec=finished_raw,
            pre_grinding_spec=pre_grinding_raw,
            finished_product_shape=finished_shape,
            pre_grinding_shape=pre_grinding_shape,
            guide_profile_source=profile_source,
            final_section_profile_type="same_r_tile",
            R_form_source="pre_grinding_spec_equal_R",
        )
        return finished_spec, pre_grinding_spec, profile, decision

    raise ValueError(
        "pre_grinding_shape must be 'block' or 'same_r_tile'."
    )


def _first_wheel_side(machine: MachineConfig) -> str:
    if not machine.wheel_positions:
        raise ValueError("Machine config must define at least one wheel position.")
    side = {"上": "upper", "下": "lower"}.get(machine.wheel_positions[0])
    if side is None:
        raise ValueError("Dual-guide flat-arc geometry requires an upper or lower first wheel.")
    return side


def _block_to_tile_slot_base_height(
    preform: BlockSpec,
    machine: MachineConfig,
) -> float:
    top_gap = machine.side_layout.block_fixed_top_gap
    if machine.side_layout.block_side_mode != "fixed_top_gap":
        return machine.section_slot_base_height
    if top_gap is None:
        raise ValueError("fixed_top_gap block side-view mode requires block_fixed_top_gap.")
    guide_thickness = preform.thickness_mid + machine.block_thickness_clearance_mid
    return 27.0 - top_gap - guide_thickness

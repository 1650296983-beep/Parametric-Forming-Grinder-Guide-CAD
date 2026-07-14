from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

from .block_geometry import BlockGuideSection
from .geometry import TileSection
from .side_view_config import SideViewLayoutConfig, SideViewTemplateConfig


@dataclass(frozen=True)
class SideViewDerivedSpec:
    slot_base_height: float
    side_cut_in_allowance: float
    side_projected_slot_height: float
    guide_outer_height: float
    guide_thickness: float
    wheel_cut_allowance: float
    side_clearance_height: float
    wheel_notch_depth: float
    wheel_cut_in_depth: float
    wheel_notch_opening: float
    wheel_notch_opening_limit: float | None
    lower_cavity_notch_opening: float
    upper_cavity_notch_opening: float
    upper_cavity_notch_opening_limit: float | None


@dataclass(frozen=True)
class SideViewGeometry:
    template: SideViewTemplateConfig
    layout: SideViewLayoutConfig
    derived: SideViewDerivedSpec


def build_side_view_geometry(
    tile_section: TileSection | BlockGuideSection,
    template: SideViewTemplateConfig | None = None,
    layout: SideViewLayoutConfig | None = None,
    side_cut_in_allowance: float = 0.50,
    wheel_cut_allowance: float = 0.20,
) -> SideViewGeometry:
    template = template or SideViewTemplateConfig()
    layout = layout or SideViewLayoutConfig()
    guide = tile_section.guide_spec
    if isinstance(tile_section, BlockGuideSection):
        return _build_block_side_view_geometry(tile_section, template, layout)
    fixed_projected_height = (
        0.0 if layout is None else layout.fixed_tile_side_projected_slot_height
    )
    if fixed_projected_height > 0.0:
        side_projected_slot_height = fixed_projected_height
        effective_side_cut_in_allowance = fixed_projected_height - guide.slot_base_height
    else:
        side_projected_slot_height = guide.slot_base_height + side_cut_in_allowance
        effective_side_cut_in_allowance = side_cut_in_allowance
    lower_requested_cut_in, upper_requested_cut_in = _tile_wheel_cut_ins(
        tile_section,
        layout,
        wheel_cut_allowance,
    )
    opening_limit = max(tile_section.process_length - 0.2, 0.1)
    lower_cavity_notch_opening, effective_lower_cut_in = _limited_r80_opening(
        template.wheel_radius,
        lower_requested_cut_in,
        opening_limit,
    )
    upper_cavity_notch_opening, effective_upper_cut_in = _limited_r80_opening(
        template.wheel_radius,
        upper_requested_cut_in,
        opening_limit,
    )
    side_clearance_height = (
        guide.outer_height
        - guide.slot_base_height
        - guide.guide_thickness
        + effective_upper_cut_in
    )
    derived = SideViewDerivedSpec(
        slot_base_height=guide.slot_base_height,
        side_cut_in_allowance=effective_side_cut_in_allowance,
        side_projected_slot_height=side_projected_slot_height,
        guide_outer_height=guide.outer_height,
        guide_thickness=guide.guide_thickness,
        wheel_cut_allowance=effective_upper_cut_in,
        side_clearance_height=side_clearance_height,
        wheel_notch_depth=guide.slot_base_height + effective_lower_cut_in,
        wheel_cut_in_depth=effective_lower_cut_in,
        wheel_notch_opening=0.0,
        wheel_notch_opening_limit=opening_limit,
        lower_cavity_notch_opening=lower_cavity_notch_opening,
        upper_cavity_notch_opening=upper_cavity_notch_opening,
        upper_cavity_notch_opening_limit=opening_limit,
    )
    return SideViewGeometry(template=template, layout=layout, derived=derived)


def _build_block_side_view_geometry(
    section: BlockGuideSection,
    template: SideViewTemplateConfig,
    layout: SideViewLayoutConfig,
) -> SideViewGeometry:
    guide = section.guide_spec
    mode = layout.block_side_mode
    process_thickness = section.process_thickness
    opening_limit = max(section.process_length - 0.2, 0.1)
    lower_requested_cut_in = _configured_block_cut_in(
        layout.block_lower_wheel_cut_in,
        layout.block_lower_wheel_cut_in_ratio,
        process_thickness,
    )
    upper_requested_cut_in = _configured_block_cut_in(
        layout.block_upper_wheel_cut_in,
        layout.block_upper_wheel_cut_in_ratio,
        process_thickness,
    )
    lower_opening, effective_lower_cut_in = _limited_r80_opening(
        template.wheel_radius,
        lower_requested_cut_in,
        opening_limit,
    )
    upper_opening, effective_upper_cut_in = _limited_r80_opening(
        template.wheel_radius,
        upper_requested_cut_in,
        opening_limit,
    )

    if mode == "fixed_projected_height":
        projected_height = _require_layout_value(
            layout.block_side_projected_slot_height,
            "block_side_projected_slot_height",
        )
        projected_top_height = (
            guide.guide_thickness
            if layout.block_projected_top_mode == "guide_thickness"
            else effective_upper_cut_in
        )
        side_clearance = guide.outer_height - projected_height - projected_top_height
        if layout.block_projected_top_mode == "guide_thickness":
            side_clearance += effective_upper_cut_in
        derived = SideViewDerivedSpec(
            slot_base_height=projected_height,
            side_cut_in_allowance=0.0,
            side_projected_slot_height=projected_height,
            guide_outer_height=guide.outer_height,
            guide_thickness=projected_top_height,
            wheel_cut_allowance=effective_upper_cut_in,
            side_clearance_height=side_clearance,
            wheel_notch_depth=projected_height + effective_lower_cut_in,
            wheel_cut_in_depth=effective_lower_cut_in,
            wheel_notch_opening=lower_opening,
            wheel_notch_opening_limit=opening_limit,
            lower_cavity_notch_opening=lower_opening,
            upper_cavity_notch_opening=upper_opening,
            upper_cavity_notch_opening_limit=opening_limit,
        )
        return SideViewGeometry(template=template, layout=layout, derived=derived)

    if mode == "fixed_top_gap":
        fixed_top_gap = _require_layout_value(
            layout.block_fixed_top_gap,
            "block_fixed_top_gap",
        )
        projected_height = guide.outer_height - fixed_top_gap - guide.guide_thickness
        wheel_depth = effective_upper_cut_in
        side_clearance = guide.outer_height - projected_height - wheel_depth
        derived = SideViewDerivedSpec(
            slot_base_height=projected_height,
            side_cut_in_allowance=0.0,
            side_projected_slot_height=projected_height,
            guide_outer_height=guide.outer_height,
            guide_thickness=wheel_depth,
            wheel_cut_allowance=0.0,
            side_clearance_height=side_clearance,
            wheel_notch_depth=wheel_depth,
            wheel_cut_in_depth=wheel_depth,
            wheel_notch_opening=lower_opening,
            wheel_notch_opening_limit=opening_limit,
            lower_cavity_notch_opening=lower_opening,
            upper_cavity_notch_opening=upper_opening,
            upper_cavity_notch_opening_limit=opening_limit,
        )
        return SideViewGeometry(template=template, layout=layout, derived=derived)

    if mode == "slot_base_plus_wheel_cut_in":
        slot_base_height = guide.slot_base_height
        lower_key_height = slot_base_height + effective_lower_cut_in
        upper_key_height = (
            guide.outer_height
            - slot_base_height
            - guide.guide_thickness
            + effective_upper_cut_in
        )
        derived = SideViewDerivedSpec(
            slot_base_height=slot_base_height,
            side_cut_in_allowance=effective_lower_cut_in,
            side_projected_slot_height=slot_base_height,
            guide_outer_height=guide.outer_height,
            guide_thickness=guide.guide_thickness,
            wheel_cut_allowance=effective_upper_cut_in,
            side_clearance_height=upper_key_height,
            wheel_notch_depth=lower_key_height,
            wheel_cut_in_depth=effective_lower_cut_in,
            wheel_notch_opening=lower_opening,
            wheel_notch_opening_limit=opening_limit,
            lower_cavity_notch_opening=lower_opening,
            upper_cavity_notch_opening=upper_opening,
            upper_cavity_notch_opening_limit=opening_limit,
        )
        return SideViewGeometry(template=template, layout=layout, derived=derived)

    raise ValueError(
        "Block side-view configuration is required; expected one of "
        "'fixed_projected_height', 'fixed_top_gap', or "
        "'slot_base_plus_wheel_cut_in', got "
        f"{mode!r}."
    )


def _configured_block_cut_in(
    fixed_value: float | None,
    ratio: float | None,
    process_thickness: float,
) -> float:
    if fixed_value is not None:
        return fixed_value
    if ratio is not None:
        return process_thickness * ratio
    # Existing configurations without a dedicated block value use the shared
    # process rule rather than a product-specific magic number.
    return process_thickness * 0.6


def _require_layout_value(value: float | None, name: str) -> float:
    if value is None:
        raise ValueError(f"Block side-view configuration is missing {name}.")
    return value


def _r80_opening_from_depth(radius: float, depth: float) -> float:
    if depth <= 0.0:
        return 0.0
    return 2.0 * sqrt(max(0.0, radius * radius - (radius - depth) ** 2))


def _tile_wheel_cut_ins(
    tile_section: TileSection,
    layout: SideViewLayoutConfig,
    default_upper_cut_in: float,
) -> tuple[float, float]:
    if tile_section.process_type == "block_to_tile":
        lower = layout.block_to_tile_lower_wheel_cut_in
        upper = layout.block_to_tile_upper_wheel_cut_in
        lower_ratio = layout.block_to_tile_lower_wheel_cut_in_ratio
        upper_ratio = layout.block_to_tile_upper_wheel_cut_in_ratio
        if lower is None and lower_ratio is not None:
            lower = tile_section.process_thickness * lower_ratio
        if upper is None and upper_ratio is not None:
            upper = tile_section.process_thickness * upper_ratio
        if lower is None or upper is None:
            raise ValueError(
                "block_to_tile requires explicit lower and upper wheel cut-ins "
                "or cut-in ratios in the selected machine configuration."
            )
        return lower, upper
    upper = (
        tile_section.process_thickness * layout.tile_upper_wheel_cut_in_ratio
        if layout.tile_upper_wheel_cut_in_ratio > 0.0
        else default_upper_cut_in
    )
    return tile_section.process_thickness * 0.6, upper


def _limited_r80_opening(
    radius: float,
    requested_depth: float,
    opening_limit: float,
) -> tuple[float, float]:
    natural_opening = _r80_opening_from_depth(radius, requested_depth)
    opening = min(natural_opening, opening_limit)
    return opening, _r80_depth_from_opening(radius, opening)


def _r80_depth_from_opening(radius: float, opening: float) -> float:
    half_opening = max(opening, 0.0) / 2.0
    if half_opening >= radius:
        return radius
    return radius - sqrt(max(0.0, radius * radius - half_opening * half_opening))

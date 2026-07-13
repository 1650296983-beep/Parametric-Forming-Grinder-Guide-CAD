from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_SIDE_VIEW_TEMPLATE = Path("导轨长度投影（干净模板）.dxf")


@dataclass(frozen=True)
class SideViewTemplateConfig:
    fixed_90: float = 90.0
    fixed_200: float = 200.0
    fixed_145: float = 145.0
    fixed_435: float = 435.0
    wheel_radius: float = 80.0


@dataclass(frozen=True)
class SideViewLayoutConfig:
    left_x: float = 3354.438679920512
    center_a_x: float = 3444.438679920512
    center_b_x: float = 3644.438679920512
    right_x: float = 3789.438679920512
    lower_y: float = 35.84968457837181
    center_y: float = 47.84968457837181
    upper_y: float = 62.84968457837181
    template_min_x: float = 3350.0
    template_min_y: float = -120.0
    template_max_y: float = 150.0
    # Block side-view behavior must be selected by the machine configuration.
    # None is intentional: falling back to another machine's 18 mm layout is unsafe.
    block_side_mode: str | None = None
    block_side_projected_slot_height: float | None = None
    block_fixed_top_gap: float | None = None
    block_lower_wheel_cut_in: float | None = None
    block_upper_wheel_cut_in: float | None = None
    fixed_tile_side_projected_slot_height: float = 0.0
    tile_upper_wheel_cut_in_ratio: float = 0.0
    block_to_tile_lower_wheel_cut_in: float | None = None
    block_to_tile_upper_wheel_cut_in: float | None = None
    block_to_tile_lower_wheel_cut_in_ratio: float | None = None
    block_to_tile_upper_wheel_cut_in_ratio: float | None = None

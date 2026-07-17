from __future__ import annotations

from dataclasses import dataclass


WHEEL_CUT_IN_RATIO = 0.6
WHEEL_NOTCH_OPENING_RATIO = 0.6
DEFAULT_WHEEL_RADIUS = 80.0
CENTER_TRANSITION_RADIUS = 0.5
DIMENSION_DECIMAL_PLACES = 2

ENDPOINT_TOLERANCE = 0.001
GEOMETRY_MEASUREMENT_TOLERANCE = 0.001
DIMENSION_MEASUREMENT_TOLERANCE = 0.001
DIMENSION_POINT_BINDING_TOLERANCE = 0.01
DUPLICATE_ENTITY_TOLERANCE = 0.001

BLOCK_THICKNESS_CLEARANCE = 0.12
HIGH_REQUIREMENT_THICKNESS_CLEARANCE = 0.09
SMALL_TILE_THICKNESS_CLEARANCE = 0.18
LARGE_TILE_THICKNESS_CLEARANCE = 0.25
LARGE_TILE_WIDTH_THRESHOLD = 15.0

HIGH_SYMMETRY_SLOT_CLEARANCE = 0.03
LARGE_TILE_SLOT_CLEARANCE = 0.08


@dataclass(frozen=True)
class ProcessOptions:
    """Explicit process choices shared by every machine type."""

    single_side_or_high_requirement: bool = False
    high_symmetry_requirement: bool = False
    large_tile_clearance: bool = False
    wheel_radius: float = DEFAULT_WHEEL_RADIUS

    def __post_init__(self) -> None:
        if self.high_symmetry_requirement and self.large_tile_clearance:
            raise ValueError(
                "高对称度槽宽和大瓦放宽槽宽不能同时选择。"
            )
        if self.wheel_radius <= 0.0:
            raise ValueError("砂轮半径必须大于 0。")

    @property
    def thickness_clearance_override(self) -> float | None:
        if self.single_side_or_high_requirement:
            return HIGH_REQUIREMENT_THICKNESS_CLEARANCE
        return None

    @property
    def slot_clearance_override(self) -> float | None:
        if self.high_symmetry_requirement:
            return HIGH_SYMMETRY_SLOT_CLEARANCE
        if self.large_tile_clearance:
            return LARGE_TILE_SLOT_CLEARANCE
        return None


def process_options_from_mapping(data: dict[str, object]) -> ProcessOptions:
    return ProcessOptions(
        single_side_or_high_requirement=bool(
            data.get("single_side_or_high_requirement", False)
        ),
        high_symmetry_requirement=bool(
            data.get("high_symmetry_requirement", False)
        ),
        large_tile_clearance=bool(data.get("large_tile_clearance", False)),
        wheel_radius=float(data.get("wheel_radius", DEFAULT_WHEEL_RADIUS)),
    )


def default_thickness_clearance(pre_grinding_shape: str, width: float) -> float:
    if pre_grinding_shape == "block":
        return BLOCK_THICKNESS_CLEARANCE
    if width > LARGE_TILE_WIDTH_THRESHOLD:
        return LARGE_TILE_THICKNESS_CLEARANCE
    return SMALL_TILE_THICKNESS_CLEARANCE


def format_dimension(value: float) -> str:
    return f"{value:.{DIMENSION_DECIMAL_PLACES}f}"


def wheel_notch_opening_limit(product_length: float) -> float:
    """Return the shared maximum wheel-notch opening for every machine."""
    length = float(product_length)
    if length <= 0.0:
        raise ValueError("产品长度必须大于 0。")
    return length * WHEEL_NOTCH_OPENING_RATIO

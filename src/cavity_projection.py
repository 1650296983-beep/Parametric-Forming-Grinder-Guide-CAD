from __future__ import annotations

from dataclasses import dataclass
from math import atan2, degrees, sqrt
from typing import Any

from .block_geometry import BlockGuideSection
from .geometry import TileSection


@dataclass(frozen=True)
class CavityProjectionProfile:
    pre_grinding_shape: str
    offsets: tuple[float, ...]
    surface_roles: tuple[str, ...]

    @property
    def line_count(self) -> int:
        return len(self.offsets)


def derive_cavity_projection_profile(
    section: TileSection | BlockGuideSection,
    guide_thickness: float,
) -> CavityProjectionProfile:
    """Derive side-view cavity lines exclusively from the pre-grinding shape."""
    if isinstance(section, BlockGuideSection) or section.preform_block_spec is not None:
        return CavityProjectionProfile(
            pre_grinding_shape="block",
            offsets=(0.0, guide_thickness),
            surface_roles=("lower_plane", "upper_plane"),
        )

    profile = section.forming_profile
    if profile.params.profile_shape == "bread":
        sagitta = _sagitta(
            profile.params.R_outer,
            profile.params.chord_width,
        )
        if section.arc_side == "lower":
            return CavityProjectionProfile(
                pre_grinding_shape="bread",
                offsets=(-sagitta, 0.0, guide_thickness),
                surface_roles=(
                    "lower_arc_crown",
                    "lower_arc_endpoint",
                    "upper_plane",
                ),
            )
        return CavityProjectionProfile(
            pre_grinding_shape="bread",
            offsets=(0.0, guide_thickness, guide_thickness + sagitta),
            surface_roles=(
                "lower_plane",
                "upper_arc_endpoint",
                "upper_arc_crown",
            ),
        )

    inner_sagitta = _sagitta(
        profile.params.R_inner,
        profile.params.chord_width,
    )
    outer_sagitta = _sagitta(
        profile.params.R_outer,
        profile.params.chord_width,
    )
    return CavityProjectionProfile(
        pre_grinding_shape="tile",
        offsets=(
            0.0,
            inner_sagitta,
            guide_thickness,
            guide_thickness + outer_sagitta,
        ),
        surface_roles=(
            "lower_arc_endpoint",
            "lower_arc_crown",
            "upper_arc_endpoint",
            "upper_arc_crown",
        ),
    )


def _sagitta(radius: float, chord_width: float) -> float:
    half_chord = chord_width / 2.0
    if radius <= 0.0 or half_chord >= radius:
        raise ValueError(
            "Pre-grinding cavity radius must be greater than half its chord width."
        )
    return radius - sqrt(radius * radius - half_chord * half_chord)


def horizontal_arc_gap(arc: Any, y: float) -> tuple[float, float] | None:
    """Return the horizontal interval occupied by an actual DXF arc at ``y``."""
    center_x = float(arc.dxf.center.x)
    center_y = float(arc.dxf.center.y)
    radius = float(arc.dxf.radius)
    dy = y - center_y
    if abs(dy) > radius + 0.001:
        return None
    half_chord = sqrt(max(0.0, radius * radius - dy * dy))
    left_x = center_x - half_chord
    right_x = center_x + half_chord
    left_angle = degrees(atan2(dy, -half_chord)) % 360.0
    right_angle = degrees(atan2(dy, half_chord)) % 360.0
    start = float(arc.dxf.start_angle) % 360.0
    end = float(arc.dxf.end_angle) % 360.0
    if not (
        angle_is_on_arc(left_angle, start, end)
        and angle_is_on_arc(right_angle, start, end)
    ):
        return None
    return left_x, right_x


def angle_is_on_arc(angle: float, start: float, end: float) -> bool:
    if start <= end:
        return start - 0.001 <= angle <= end + 0.001
    return angle >= start - 0.001 or angle <= end + 0.001

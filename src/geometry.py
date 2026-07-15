from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, degrees, pi, sin, sqrt
from typing import Iterable, Literal, Union

from .global_rules import (
    LARGE_TILE_THICKNESS_CLEARANCE,
    LARGE_TILE_WIDTH_THRESHOLD,
    SMALL_TILE_THICKNESS_CLEARANCE,
)

from .spec_parser import (
    BlockSpec,
    FinishedSpec,
    FormingSpec,
    GuideSpec,
    ProductPreFormTolerance,
    ReliefSpec,
    validate_company_tile_spec,
)


EPSILON = 1e-9


@dataclass(frozen=True)
class SectionParameters:
    R_outer: float
    R_inner: float
    chord_width: float
    length: float | None = None
    thickness: float | None = None
    allowance: float = 0.0
    profile_type: Literal["finished", "forming"] = "finished"
    forming_radius_mode: str | None = None
    guide_thickness: float | None = None
    profile_shape: Literal["tile", "bread"] = "tile"

    @property
    def chord(self) -> float:
        return self.chord_width


@dataclass(frozen=True)
class Point:
    x: float
    y: float

    def as_tuple(self) -> tuple[float, float]:
        return (self.x, self.y)

    def distance_to(self, other: "Point") -> float:
        return sqrt((self.x - other.x) ** 2 + (self.y - other.y) ** 2)


@dataclass(frozen=True)
class LineSegment:
    name: str
    start: Point
    end: Point
    kind: Literal["line"] = "line"

    @property
    def length(self) -> float:
        return self.start.distance_to(self.end)


@dataclass(frozen=True)
class ArcSegment:
    name: str
    start: Point
    end: Point
    center: Point
    radius: float
    clockwise: bool
    kind: Literal["arc"] = "arc"

    @property
    def start_angle_deg(self) -> float:
        return _angle_deg(self.center, self.start)

    @property
    def end_angle_deg(self) -> float:
        return _angle_deg(self.center, self.end)

    @property
    def sweep_rad(self) -> float:
        return _sweep_radians(self.start_angle_deg, self.end_angle_deg, self.clockwise)

    @property
    def length(self) -> float:
        return self.radius * self.sweep_rad


Segment = Union[LineSegment, ArcSegment]


@dataclass(frozen=True)
class SectionProfile:
    params: SectionParameters
    center: Point
    outer_left: Point
    outer_right: Point
    inner_right: Point
    inner_left: Point
    segments: tuple[Segment, ...]

    def points(self) -> tuple[Point, Point, Point, Point]:
        return (self.outer_left, self.outer_right, self.inner_right, self.inner_left)


@dataclass(frozen=True)
class TileSection:
    finished_spec: FinishedSpec
    forming_spec: FormingSpec
    guide_spec: GuideSpec
    finished_profile: SectionProfile
    forming_profile: SectionProfile
    process_type: Literal["tile", "block_to_tile", "block_to_bread"] = "tile"
    preform_block_spec: BlockSpec | None = None
    arc_side: Literal["upper", "lower"] | None = None

    @property
    def spec(self) -> FinishedSpec:
        return self.finished_spec

    @property
    def forming_radius_mode(self) -> str:
        return self.forming_spec.forming_radius_mode

    @property
    def default_profile(self) -> SectionProfile:
        return self.forming_profile

    @property
    def process_thickness(self) -> float:
        if self.preform_block_spec is not None:
            return self.preform_block_spec.thickness_mid
        return self.finished_spec.preform_thickness_mid

    @property
    def process_length(self) -> float:
        if self.preform_block_spec is not None:
            return self.preform_block_spec.length
        return self.finished_spec.length


def build_section_profile(
    R_outer: float,
    R_inner: float,
    chord_width: float,
    length: float | None = None,
    thickness: float | None = None,
    allowance: float = 0.0,
) -> SectionProfile:
    params = SectionParameters(
        R_outer=float(R_outer),
        R_inner=float(R_inner),
        chord_width=float(chord_width),
        length=None if length is None else float(length),
        thickness=None if thickness is None else float(thickness),
        allowance=float(allowance),
        profile_type="finished",
    )
    _validate_input(params)

    half_chord = params.chord_width / 2.0
    outer_base_y = sqrt(params.R_outer**2 - half_chord**2)
    inner_base_y = sqrt(params.R_inner**2 - half_chord**2)

    inner_y = 0.0
    outer_y = params.thickness if params.thickness is not None else outer_base_y - inner_base_y
    inner_center = Point(0.0, inner_y - inner_base_y)
    outer_center = Point(0.0, outer_y - outer_base_y)

    outer_left = Point(-half_chord, outer_y)
    outer_right = Point(half_chord, outer_y)
    inner_right = Point(half_chord, inner_y)
    inner_left = Point(-half_chord, inner_y)

    segments: tuple[Segment, ...] = (
        ArcSegment(
            name="outer_arc",
            start=outer_left,
            end=outer_right,
            center=outer_center,
            radius=params.R_outer,
            clockwise=True,
        ),
        LineSegment(name="right_side", start=outer_right, end=inner_right),
        ArcSegment(
            name="inner_arc",
            start=inner_right,
            end=inner_left,
            center=inner_center,
            radius=params.R_inner,
            clockwise=False,
        ),
        LineSegment(name="left_side", start=inner_left, end=outer_left),
    )

    return SectionProfile(
        params=params,
        center=inner_center,
        outer_left=outer_left,
        outer_right=outer_right,
        inner_right=inner_right,
        inner_left=inner_left,
        segments=segments,
    )


def build_tile_section(
    spec: FinishedSpec,
    allowance: float = 0.0,
    relief: ReliefSpec | None = None,
    preform_tolerance: ProductPreFormTolerance | None = None,
    thickness_clearance_mid: float | None = None,
    tolerance_slot_clearance: float | None = None,
    outer_width: float = 33.0,
    slot_base_height: float = 12.0,
    center_opening: float = 1.5,
) -> TileSection:
    if not isinstance(spec, FinishedSpec):
        raise TypeError("build_tile_section() requires a FinishedSpec from parse_company_tile_spec().")

    spec_errors = validate_company_tile_spec(spec)
    if spec_errors:
        raise ValueError("\n".join(spec_errors))

    finished_profile = build_finished_profile(spec, allowance=allowance)
    forming_spec = build_forming_spec(spec)
    guide_spec = calculate_guide_spec(
        spec,
        relief=relief,
        preform_tolerance=preform_tolerance,
        thickness_clearance_mid=thickness_clearance_mid,
        tolerance_slot_clearance=tolerance_slot_clearance,
        outer_width=outer_width,
        slot_base_height=slot_base_height,
        center_opening=center_opening,
    )
    forming_profile = build_forming_profile(forming_spec, allowance=allowance, guide_spec=guide_spec)
    return TileSection(
        finished_spec=spec,
        forming_spec=forming_spec,
        guide_spec=guide_spec,
        finished_profile=finished_profile,
        forming_profile=forming_profile,
    )


def build_block_to_tile_section(
    finished_spec: FinishedSpec,
    preform_spec: BlockSpec,
    relief: ReliefSpec | None = None,
    thickness_clearance_mid: float = 0.12,
    tolerance_slot_clearance: float | None = None,
    outer_width: float = 40.0,
    slot_base_height: float = 12.0,
    center_opening: float = 1.8,
    arc_side: Literal["upper", "lower"] = "upper",
) -> TileSection:
    if not preform_spec.has_width_tolerance:
        raise ValueError("Block-to-tile preform width must include upper/lower tolerance.")
    if not preform_spec.has_thickness_tolerance:
        raise ValueError("Block-to-tile preform thickness must include upper/lower tolerance.")
    if abs(preform_spec.length - finished_spec.length) > 0.01:
        raise ValueError(
            "Block-to-tile preform length must match finished product length within 0.01 mm."
        )

    finished_profile = build_finished_profile(finished_spec)
    forming_spec = FormingSpec(
        R_form=max(finished_spec.R_outer_finished, finished_spec.R_inner_finished),
        chord_width=preform_spec.width,
        length=preform_spec.length,
        finished_thickness=preform_spec.thickness_mid,
        forming_radius_mode="block_to_tile_bread_profile_big_R",
    )
    guide_spec = GuideSpec(
        finished_thickness=preform_spec.thickness_mid,
        chord_width=preform_spec.width,
        thickness_clearance_mid=thickness_clearance_mid,
        slot_width_tolerance=0.01,
        preform_tolerance=ProductPreFormTolerance(
            upper=preform_spec.width_tolerance_upper,
            lower=preform_spec.width_tolerance_lower,
        ),
        relief=relief,
        outer_width=outer_width,
        slot_base_height=slot_base_height,
        center_offset=center_opening,
        tolerance_slot_clearance=tolerance_slot_clearance,
        use_tolerance_based_slot_width=True,
    )
    forming_profile = build_flat_arc_profile(
        radius=forming_spec.R_form,
        chord_width=forming_spec.chord_width,
        length=forming_spec.length,
        thickness=forming_spec.finished_thickness,
        profile_type="forming",
        arc_side=arc_side,
    )
    return TileSection(
        finished_spec=finished_spec,
        forming_spec=forming_spec,
        guide_spec=guide_spec,
        finished_profile=finished_profile,
        forming_profile=forming_profile,
        process_type="block_to_tile",
        preform_block_spec=preform_spec,
        arc_side=arc_side,
    )


def build_block_to_bread_section(
    finished_spec: FinishedSpec,
    preform_spec: BlockSpec,
    relief: ReliefSpec | None = None,
    thickness_clearance_mid: float = 0.12,
    tolerance_slot_clearance: float | None = None,
    outer_width: float = 40.0,
    slot_base_height: float = 12.0,
    center_opening: float = 1.8,
    arc_side: Literal["upper", "lower"] = "upper",
) -> TileSection:
    if finished_spec.finished_shape != "bread":
        raise ValueError("Block-to-bread requires a four-part bread product specification.")
    if not preform_spec.has_width_tolerance:
        raise ValueError("Block-to-bread preform width must include upper/lower tolerance.")
    if not preform_spec.has_thickness_tolerance:
        raise ValueError("Block-to-bread preform thickness must include upper/lower tolerance.")
    if abs(preform_spec.length - finished_spec.length) > 0.01:
        raise ValueError(
            "Block-to-bread preform length must match finished product length within 0.01 mm."
        )

    finished_profile = build_bread_profile(
        radius=finished_spec.R_outer_finished,
        chord_width=finished_spec.chord_width,
        length=finished_spec.length,
        thickness=finished_spec.finished_thickness,
        profile_type="finished",
    )
    forming_spec = FormingSpec(
        R_form=finished_spec.R_outer_finished,
        chord_width=preform_spec.width,
        length=preform_spec.length,
        finished_thickness=preform_spec.thickness_mid,
        forming_radius_mode="block_to_bread_lower_plane_upper_R",
    )
    guide_spec = GuideSpec(
        finished_thickness=preform_spec.thickness_mid,
        chord_width=preform_spec.width,
        thickness_clearance_mid=thickness_clearance_mid,
        slot_width_tolerance=0.01,
        preform_tolerance=ProductPreFormTolerance(
            upper=preform_spec.width_tolerance_upper,
            lower=preform_spec.width_tolerance_lower,
        ),
        relief=relief,
        outer_width=outer_width,
        slot_base_height=slot_base_height,
        center_offset=center_opening,
        tolerance_slot_clearance=tolerance_slot_clearance,
        use_tolerance_based_slot_width=True,
    )
    forming_profile = build_flat_arc_profile(
        radius=forming_spec.R_form,
        chord_width=forming_spec.chord_width,
        length=forming_spec.length,
        thickness=forming_spec.finished_thickness,
        profile_type="forming",
        arc_side=arc_side,
    )
    return TileSection(
        finished_spec=finished_spec,
        forming_spec=forming_spec,
        guide_spec=guide_spec,
        finished_profile=finished_profile,
        forming_profile=forming_profile,
        process_type="block_to_bread",
        preform_block_spec=preform_spec,
        arc_side=arc_side,
    )


def build_bread_profile(
    radius: float,
    chord_width: float,
    length: float,
    thickness: float,
    profile_type: Literal["finished", "forming"],
) -> SectionProfile:
    return build_flat_arc_profile(
        radius=radius,
        chord_width=chord_width,
        length=length,
        thickness=thickness,
        profile_type=profile_type,
        arc_side="upper",
    )


def build_flat_arc_profile(
    radius: float,
    chord_width: float,
    length: float,
    thickness: float,
    profile_type: Literal["finished", "forming"],
    arc_side: Literal["upper", "lower"],
) -> SectionProfile:
    if chord_width >= 2.0 * radius:
        raise ValueError("Flat-arc profile width must be smaller than 2 * radius.")
    if arc_side not in {"upper", "lower"}:
        raise ValueError("arc_side must be 'upper' or 'lower'.")
    half_chord = chord_width / 2.0
    arc_base = sqrt(radius**2 - half_chord**2)
    lower_y = 0.0
    upper_endpoint_y = thickness
    center = Point(
        0.0,
        upper_endpoint_y - arc_base if arc_side == "upper" else arc_base,
    )
    upper_left = Point(-half_chord, upper_endpoint_y)
    upper_right = Point(half_chord, upper_endpoint_y)
    lower_right = Point(half_chord, lower_y)
    lower_left = Point(-half_chord, lower_y)
    params = SectionParameters(
        R_outer=radius,
        R_inner=radius,
        chord_width=chord_width,
        length=length,
        thickness=thickness,
        profile_type=profile_type,
        forming_radius_mode=(
            "single_R_upper_arc_lower_plane"
            if arc_side == "upper"
            else "single_R_lower_arc_upper_plane"
        ),
        profile_shape="bread",
    )
    if arc_side == "upper":
        segments: tuple[Segment, ...] = (
            ArcSegment(
                name="outer_arc",
                start=upper_left,
                end=upper_right,
                center=center,
                radius=radius,
                clockwise=True,
            ),
            LineSegment(name="right_side", start=upper_right, end=lower_right),
            LineSegment(name="bottom_plane", start=lower_right, end=lower_left),
            LineSegment(name="left_side", start=lower_left, end=upper_left),
        )
    else:
        segments = (
            LineSegment(name="top_plane", start=upper_left, end=upper_right),
            LineSegment(name="right_side", start=upper_right, end=lower_right),
            ArcSegment(
                name="outer_arc",
                start=lower_right,
                end=lower_left,
                center=center,
                radius=radius,
                clockwise=True,
            ),
            LineSegment(name="left_side", start=lower_left, end=upper_left),
        )
    return SectionProfile(
        params=params,
        center=center,
        outer_left=upper_left,
        outer_right=upper_right,
        inner_right=lower_right,
        inner_left=lower_left,
        segments=segments,
    )


def build_finished_profile(spec: FinishedSpec, allowance: float = 0.0) -> SectionProfile:
    if spec.finished_shape == "bread":
        return build_bread_profile(
            radius=spec.R_outer_finished,
            chord_width=spec.chord_width,
            length=spec.length,
            thickness=spec.finished_thickness,
            profile_type="finished",
        )
    return build_section_profile(
        R_outer=spec.R_outer_finished,
        R_inner=spec.R_inner_finished,
        chord_width=spec.chord_width,
        length=spec.length,
        thickness=spec.finished_thickness,
        allowance=allowance,
    )


def build_forming_spec(spec: FinishedSpec) -> FormingSpec:
    return FormingSpec(
        R_form=max(spec.R_outer_finished, spec.R_inner_finished),
        chord_width=spec.chord_width,
        length=spec.length,
        finished_thickness=spec.preform_thickness_mid,
        forming_radius_mode="same_R_big_R",
    )


def calculate_guide_spec(
    spec: FinishedSpec,
    machining_allowance: float = 0.18,
    guide_extra_clearance: float = 0.07,
    thickness_clearance_mid: float | None = None,
    slot_width_tolerance: float = 0.01,
    tolerance_slot_clearance: float | None = None,
    preform_tolerance: ProductPreFormTolerance | None = None,
    relief: ReliefSpec | None = None,
    outer_width: float = 33.0,
    slot_base_height: float = 12.0,
    center_opening: float = 1.5,
) -> GuideSpec:
    if spec.has_chord_width_tolerance:
        preform_tolerance = ProductPreFormTolerance(
            upper=spec.chord_width_tolerance_upper,
            lower=spec.chord_width_tolerance_lower,
        )
    elif preform_tolerance is None:
        raise ValueError("chord_width tolerance is required for guide slot width calculation.")
    return GuideSpec(
        finished_thickness=spec.preform_thickness_mid,
        chord_width=spec.chord_width,
        machining_allowance=machining_allowance,
        guide_extra_clearance=guide_extra_clearance,
        thickness_clearance_mid=(
            _tile_thickness_clearance_mid(spec)
            if thickness_clearance_mid is None
            else thickness_clearance_mid
        ),
        slot_width_tolerance=slot_width_tolerance,
        preform_tolerance=preform_tolerance,
        relief=relief,
        outer_width=outer_width,
        slot_base_height=slot_base_height,
        center_offset=center_opening,
        tolerance_slot_clearance=tolerance_slot_clearance,
        use_tolerance_based_slot_width=True,
    )


def _tile_thickness_clearance_mid(spec: FinishedSpec) -> float:
    if spec.chord_width > LARGE_TILE_WIDTH_THRESHOLD:
        return LARGE_TILE_THICKNESS_CLEARANCE
    return SMALL_TILE_THICKNESS_CLEARANCE


def build_forming_profile(
    spec: FormingSpec,
    allowance: float = 0.0,
    guide_spec: GuideSpec | None = None,
) -> SectionProfile:
    R_form = spec.R_form
    half_chord = spec.chord_width / 2.0
    if half_chord >= R_form:
        raise ValueError("chord_width must be smaller than 2 * R_form.")

    base_y = sqrt(R_form**2 - half_chord**2)
    inner_y = 0.0
    outer_y = spec.finished_thickness
    inner_center = Point(0.0, inner_y - base_y)
    outer_center = Point(0.0, outer_y - base_y)

    outer_left = Point(-half_chord, outer_y)
    outer_right = Point(half_chord, outer_y)
    inner_right = Point(half_chord, inner_y)
    inner_left = Point(-half_chord, inner_y)

    params = SectionParameters(
        R_outer=R_form,
        R_inner=R_form,
        chord_width=spec.chord_width,
        length=spec.length,
        thickness=spec.finished_thickness,
        allowance=allowance,
        profile_type="forming",
        forming_radius_mode=spec.forming_radius_mode,
        guide_thickness=None if guide_spec is None else guide_spec.guide_thickness,
    )
    segments: tuple[Segment, ...] = (
        ArcSegment(
            name="outer_arc",
            start=outer_left,
            end=outer_right,
            center=outer_center,
            radius=R_form,
            clockwise=True,
        ),
        LineSegment(name="right_side", start=outer_right, end=inner_right),
        ArcSegment(
            name="inner_arc",
            start=inner_right,
            end=inner_left,
            center=inner_center,
            radius=R_form,
            clockwise=False,
        ),
        LineSegment(name="left_side", start=inner_left, end=outer_left),
    )

    return SectionProfile(
        params=params,
        center=inner_center,
        outer_left=outer_left,
        outer_right=outer_right,
        inner_right=inner_right,
        inner_left=inner_left,
        segments=segments,
    )


def build_section_profile_from_company_spec(tile_spec: FinishedSpec, allowance: float = 0.0) -> SectionProfile:
    return build_tile_section(tile_spec, allowance=allowance).finished_profile


def sample_segment(segment: Segment, samples: int = 48) -> list[Point]:
    if segment.kind == "line":
        return [segment.start, segment.end]

    count = max(2, samples)
    start_rad = _angle_rad(segment.center, segment.start)
    sweep = segment.sweep_rad
    if segment.clockwise:
        sweep = -sweep

    points: list[Point] = []
    for index in range(count):
        t = index / (count - 1)
        angle = start_rad + sweep * t
        points.append(
            Point(
                segment.center.x + segment.radius * cos(angle),
                segment.center.y + segment.radius * sin(angle),
            )
        )
    return points


def sample_profile(profile: SectionProfile, arc_samples: int = 64) -> list[Point]:
    sampled: list[Point] = []
    for segment in profile.segments:
        points = sample_segment(segment, arc_samples)
        if sampled:
            points = points[1:]
        sampled.extend(points)
    return sampled


def _validate_input(params: SectionParameters) -> None:
    if params.R_outer <= 0:
        raise ValueError("R_outer must be greater than 0.")
    if params.R_inner <= 0:
        raise ValueError("R_inner must be greater than 0.")
    if params.chord_width <= 0:
        raise ValueError("chord_width must be greater than 0.")

    half_chord = params.chord_width / 2.0
    if half_chord >= params.R_inner:
        raise ValueError("chord_width must be smaller than 2 * R_inner.")
    if half_chord >= params.R_outer:
        raise ValueError("chord_width must be smaller than 2 * R_outer.")


def _angle_rad(center: Point, point: Point) -> float:
    return atan2(point.y - center.y, point.x - center.x)


def _angle_deg(center: Point, point: Point) -> float:
    angle = degrees(_angle_rad(center, point))
    return angle % 360.0


def _sweep_radians(start_deg: float, end_deg: float, clockwise: bool) -> float:
    if clockwise:
        sweep_deg = (start_deg - end_deg) % 360.0
    else:
        sweep_deg = (end_deg - start_deg) % 360.0
    if sweep_deg <= EPSILON:
        sweep_deg = 360.0
    return sweep_deg * pi / 180.0


def segment_endpoints(segments: Iterable[Segment]) -> list[tuple[Point, Point]]:
    return [(segment.start, segment.end) for segment in segments]

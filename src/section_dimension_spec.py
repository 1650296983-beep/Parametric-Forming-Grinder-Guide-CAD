"""Explicit specification and emission of section dimensions.

Template dimensions are used only as a carrier for drawing style and
annotation layout.  Which template entity carries which role is decided once
from its *own* geometry family, never from the current slot width, a fixed
offset from a new edge, or a mutable text value.  The current measurement,
text and geometry anchors always come from ``SlotDimensionGeometry``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal

from .dimension_roles import (
    SECTION_CENTER_OPENING,
    SECTION_FIXED_HEIGHT,
    SECTION_FIXED_WIDTH,
    SECTION_GUIDE_THICKNESS,
    SECTION_R_FORM,
    SECTION_RELIEF_DIAMETER,
    SECTION_RELIEF_RADIUS,
    SECTION_SLOT_BASE_HEIGHT,
    SECTION_SLOT_WIDTH,
    SECTION_TOP_GAP,
    set_dimension_role,
)


class DimensionSpecError(ValueError):
    """A required dimension role cannot be emitted from the current drawing."""


@dataclass(frozen=True)
class SectionFrame:
    left: float
    right: float
    bottom: float
    top: float
    center_x: float

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.top - self.bottom


@dataclass(frozen=True)
class DimensionSpec:
    """One parametric dimension expressed in current-geometry terms.

    ``slot`` selects among several template carriers for the same role.
    ``measurement`` and ``text`` are the values the final drawing must show;
    they are built from geometry, not copied from the template.
    """

    role: str
    kind: Literal["linear", "radius", "diameter"]
    measurement: float
    text: str
    slot: int = 0
    variant: str | None = None


@dataclass
class SectionDimensionIndex:
    roles: dict[str, list[Any]] = field(default_factory=dict)
    unclassified: list[Any] = field(default_factory=list)

    def entities(self, role: str) -> list[Any]:
        return self.roles.get(role, [])


def _measurement(dimension: Any) -> float | None:
    try:
        return float(dimension.get_measurement())
    except Exception:
        return None


def _text(dimension: Any) -> str:
    return str(dimension.dxf.text) if dimension.dxf.hasattr("text") else ""


def _linear_points(dimension: Any):
    if not (
        dimension.dxf.hasattr("defpoint2")
        and dimension.dxf.hasattr("defpoint3")
    ):
        return None
    return dimension.dxf.defpoint2, dimension.dxf.defpoint3


def infer_section_frame(dimensions: Iterable[Any]) -> SectionFrame | None:
    """Infer the historical section frame from template dimension geometry.

    The archived dimension set always contains one full-height linear dimension
    and one full-width linear dimension.  Their own extension points give a
    frame that is independent of the new product parameters.
    """
    vertical: list[tuple[float, Any, Any]] = []
    horizontal: list[tuple[float, Any, Any]] = []
    for dimension in dimensions:
        points = _linear_points(dimension)
        if points is None:
            continue
        first, second = points
        measurement = _measurement(dimension)
        if measurement is None:
            continue
        if abs(float(first.y) - float(second.y)) <= 0.01:
            horizontal.append((measurement, first, second))
        elif abs(float(first.x) - float(second.x)) <= 0.01:
            vertical.append((measurement, first, second))
    if not vertical or not horizontal:
        return None
    height, height_first, height_second = max(vertical, key=lambda item: item[0])
    width, width_first, width_second = max(horizontal, key=lambda item: item[0])
    top = max(float(height_first.y), float(height_second.y))
    bottom = min(float(height_first.y), float(height_second.y))
    left = min(float(width_first.x), float(width_second.x))
    right = max(float(width_first.x), float(width_second.x))
    return SectionFrame(
        left=left,
        right=right,
        bottom=bottom,
        top=top,
        center_x=(left + right) / 2.0,
    )


def _classify(dimension: Any, frame: SectionFrame) -> str | None:
    dimtype = int(dimension.dxf.dimtype) & 15
    text = _text(dimension)
    measurement = _measurement(dimension)

    if dimtype in {3, 4}:
        if text.startswith("2-") or (
            dimtype == 4 and measurement is not None and measurement <= 5.0
        ):
            return SECTION_RELIEF_RADIUS
        if text.startswith("4-") or dimtype == 3:
            return SECTION_RELIEF_DIAMETER
        if measurement is not None and measurement > 5.0:
            return SECTION_R_FORM
        return None

    if dimtype not in {0, 1} or measurement is None:
        return None
    points = _linear_points(dimension)
    if points is None:
        return None
    first, second = points
    low_y = min(float(first.y), float(second.y))
    high_y = max(float(first.y), float(second.y))
    horizontal = high_y - low_y <= 0.01

    if horizontal:
        if (
            abs(measurement - frame.width) <= 0.05
            and abs(low_y - frame.top) <= 1.0
        ):
            return SECTION_FIXED_WIDTH
        if abs(low_y - frame.top) <= 3.0 and 0.5 <= measurement <= 8.0:
            return SECTION_CENTER_OPENING
        if (
            frame.bottom + 2.0 <= low_y <= frame.top - 2.0
            and 3.0 <= measurement <= 30.0
        ):
            return SECTION_SLOT_WIDTH
        return None

    if abs(measurement - frame.height) <= 0.05:
        return SECTION_FIXED_HEIGHT
    if abs(low_y - frame.bottom) <= 0.05 and 4.0 <= measurement <= 25.0:
        return SECTION_SLOT_BASE_HEIGHT
    return None


def index_section_dimensions(
    dimensions: Iterable[Any],
    frame: SectionFrame,
) -> SectionDimensionIndex:
    """Group template dimensions by geometry family.

    The classification uses only each dimension's own definition points and
    measurement, so it is stable when the product slot width or thickness
    changes.  Ambiguous small linear dimensions are resolved by elimination:
    the smallest remaining one is the guide thickness, and a remaining one
    that touches the outer top is the top gap.
    """
    index = SectionDimensionIndex()
    pending: list[Any] = []
    for dimension in dimensions:
        role = _classify(dimension, frame)
        if role is None:
            pending.append(dimension)
        else:
            index.roles.setdefault(role, []).append(dimension)

    thickness_candidates = []
    top_gap_candidates = []
    unknown = []
    for dimension in pending:
        measurement = _measurement(dimension)
        if measurement is None:
            unknown.append(dimension)
            continue
        if 0.3 <= measurement <= 8.0:
            thickness_candidates.append((measurement, dimension))
            continue
        top_gap_candidates.append(dimension)
    if thickness_candidates:
        _, thickness = min(thickness_candidates, key=lambda item: item[0])
        index.roles.setdefault(SECTION_GUIDE_THICKNESS, []).append(thickness)
        thickness_candidates = [
            item for item in thickness_candidates if item[1] is not thickness
        ]
        top_gap_candidates.extend(item[1] for item in thickness_candidates)
    for dimension in top_gap_candidates:
        points = _linear_points(dimension)
        if points is None:
            unknown.append(dimension)
            continue
        high_y = max(float(points[0].y), float(points[1].y))
        if abs(high_y - frame.top) <= 0.05:
            index.roles.setdefault(SECTION_TOP_GAP, []).append(dimension)
        else:
            unknown.append(dimension)
    index.unclassified = unknown
    return index


def frame_from_anchor(anchor: Any) -> SectionFrame:
    return SectionFrame(
        left=float(anchor.left),
        right=float(anchor.right),
        bottom=float(anchor.bottom),
        top=float(anchor.top),
        center_x=float(anchor.slot_center_x),
    )


ApplySpec = Callable[[Any, Any, DimensionSpec, Any], None]


def emit_section_dimensions(
    doc: Any,
    modelspace: Any,
    index: SectionDimensionIndex,
    specs: list[DimensionSpec],
    geometry: Any,
    apply_spec: ApplySpec,
    *,
    drop_roles: Iterable[str] = (),
) -> None:
    """Apply every spec to its template carrier and reject missing roles.

    Carriers that no spec claims are removed, so an archived parameter
    dimension cannot survive a topology change (for example a second R
    dimension after switching to a rectangular groove).  ``drop_roles``
    removes a role entirely when the final topology has no such feature.
    """
    spec_roles = {spec.role for spec in specs}
    dropped = set(drop_roles)
    used: dict[str, set[int]] = defaultdict(set)
    for spec in specs:
        carriers = index.entities(spec.role)
        if spec.slot >= len(carriers):
            raise DimensionSpecError(
                f"Dimension role {spec.role!r} slot {spec.slot} is missing; "
                f"found {len(carriers)} carrier(s)."
            )
        dimension = carriers[spec.slot]
        apply_spec(doc, dimension, spec, geometry)
        set_dimension_role(dimension, spec.role)
        used[spec.role].add(spec.slot)

    for role in spec_roles | dropped:
        for slot, dimension in enumerate(index.entities(role)):
            if role in dropped or slot not in used.get(role, set()):
                modelspace.delete_entity(dimension)

    if index.unclassified:
        handles = ", ".join(
            str(dimension.dxf.handle) for dimension in index.unclassified
        )
        raise DimensionSpecError(
            "Unclassified section dimension(s) would remain in release: "
            f"{handles}"
        )


def _format(value: float) -> str:
    return f"{value:.2f}"


def block_section_specs(
    block_section: Any,
    geometry: Any,
    index: SectionDimensionIndex,
) -> list[DimensionSpec]:
    guide = block_section.guide_spec
    specs: list[DimensionSpec] = []
    if index.entities(SECTION_SLOT_WIDTH):
        specs.append(
            DimensionSpec(
                SECTION_SLOT_WIDTH,
                "linear",
                geometry.slot_width,
                guide.slot_width_dimension_text,
            )
        )
    if index.entities(SECTION_GUIDE_THICKNESS):
        specs.append(
            DimensionSpec(
                SECTION_GUIDE_THICKNESS,
                "linear",
                geometry.guide_thickness,
                _format(geometry.guide_thickness),
            )
        )
    if index.entities(SECTION_CENTER_OPENING):
        specs.append(
            DimensionSpec(
                SECTION_CENTER_OPENING,
                "linear",
                geometry.center_opening,
                _format(geometry.center_opening),
            )
        )
    if index.entities(SECTION_RELIEF_DIAMETER):
        specs.append(
            DimensionSpec(
                SECTION_RELIEF_DIAMETER,
                "diameter",
                geometry.relief_radius * 2.0,
                f"4-∅{geometry.relief_radius * 2.0:.2f}",
            )
        )
    if index.entities(SECTION_RELIEF_RADIUS):
        specs.append(
            DimensionSpec(
                SECTION_RELIEF_RADIUS,
                "radius",
                geometry.center_transition_radius,
                f"2-R{geometry.center_transition_radius:.2f}",
            )
        )
    if index.entities(SECTION_SLOT_BASE_HEIGHT):
        specs.append(
            DimensionSpec(
                SECTION_SLOT_BASE_HEIGHT,
                "linear",
                geometry.slot_base_height,
                _format(geometry.slot_base_height),
            )
        )
    if index.entities(SECTION_TOP_GAP):
        specs.append(
            DimensionSpec(
                SECTION_TOP_GAP,
                "linear",
                geometry.outer_top - geometry.top_y,
                _format(geometry.outer_top - geometry.top_y),
            )
        )
    return specs


def flat_arc_section_specs(
    tile_section: Any,
    geometry: Any,
    index: SectionDimensionIndex,
    *,
    include_slot_base: bool,
    r_form_slots: int,
) -> list[DimensionSpec]:
    guide = tile_section.guide_spec
    specs: list[DimensionSpec] = []
    if index.entities(SECTION_SLOT_WIDTH):
        specs.append(
            DimensionSpec(
                SECTION_SLOT_WIDTH,
                "linear",
                geometry.slot_width,
                guide.slot_width_dimension_text,
            )
        )
    if index.entities(SECTION_GUIDE_THICKNESS):
        specs.append(
            DimensionSpec(
                SECTION_GUIDE_THICKNESS,
                "linear",
                geometry.guide_thickness,
                _format(geometry.guide_thickness),
            )
        )
    if index.entities(SECTION_CENTER_OPENING):
        specs.append(
            DimensionSpec(
                SECTION_CENTER_OPENING,
                "linear",
                geometry.center_opening,
                _format(geometry.center_opening),
            )
        )
    if index.entities(SECTION_RELIEF_DIAMETER):
        specs.append(
            DimensionSpec(
                SECTION_RELIEF_DIAMETER,
                "diameter",
                geometry.relief_radius * 2.0,
                f"4-∅{geometry.relief_radius * 2.0:.2f}",
            )
        )
    if index.entities(SECTION_RELIEF_RADIUS):
        specs.append(
            DimensionSpec(
                SECTION_RELIEF_RADIUS,
                "radius",
                geometry.center_transition_radius,
                f"2-R{geometry.center_transition_radius:.2f}",
            )
        )
    if include_slot_base and index.entities(SECTION_SLOT_BASE_HEIGHT):
        specs.append(
            DimensionSpec(
                SECTION_SLOT_BASE_HEIGHT,
                "linear",
                geometry.slot_base_height,
                _format(geometry.slot_base_height),
            )
        )
    if index.entities(SECTION_TOP_GAP):
        specs.append(
            DimensionSpec(
                SECTION_TOP_GAP,
                "linear",
                geometry.outer_top - geometry.top_y,
                _format(geometry.outer_top - geometry.top_y),
            )
        )
    for slot in range(min(r_form_slots, len(index.entities(SECTION_R_FORM)))):
        r_form = tile_section.forming_spec.R_form
        specs.append(
            DimensionSpec(
                SECTION_R_FORM,
                "radius",
                r_form,
                f"R{r_form:.2f}",
                slot=slot,
                variant=(
                    "upper"
                    if tile_section.process_type == "tile"
                    or tile_section.arc_side == "upper"
                    else "lower"
                ),
            )
        )
    return specs

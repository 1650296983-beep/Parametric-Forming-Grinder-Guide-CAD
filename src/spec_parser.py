from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from math import isclose


THICKNESS_TOLERANCE = 0.001


@dataclass(frozen=True)
class FinishedSpec:
    raw: str
    R_outer_finished: float
    R_inner_finished: float
    chord_width: float
    length: float
    finished_thickness: float
    chord_width_tolerance_upper: float | None = None
    chord_width_tolerance_lower: float | None = None
    thickness_tolerance_upper: float | None = None
    thickness_tolerance_lower: float | None = None
    finished_shape: str = "tile"

    @property
    def computed_finished_thickness(self) -> float:
        if self.finished_shape == "bread":
            return self.finished_thickness
        return abs(self.R_outer_finished - self.R_inner_finished)

    @property
    def computed_thickness(self) -> float:
        return self.computed_finished_thickness

    @property
    def R_outer(self) -> float:
        return self.R_outer_finished

    @property
    def R_inner(self) -> float:
        return self.R_inner_finished

    @property
    def thickness(self) -> float:
        return self.finished_thickness

    @property
    def width(self) -> float:
        return self.chord_width

    @property
    def has_chord_width_tolerance(self) -> bool:
        return self.chord_width_tolerance_upper is not None and self.chord_width_tolerance_lower is not None

    @property
    def has_thickness_tolerance(self) -> bool:
        return self.thickness_tolerance_upper is not None and self.thickness_tolerance_lower is not None

    @property
    def preform_thickness_mid(self) -> float:
        if not self.has_thickness_tolerance:
            return self.finished_thickness
        return self.finished_thickness + (
            self.thickness_tolerance_upper + self.thickness_tolerance_lower
        ) / 2.0


@dataclass(frozen=True)
class BlockSpec:
    raw: str
    length: float
    width: float
    thickness: float
    length_tolerance_upper: float | None = None
    length_tolerance_lower: float | None = None
    width_tolerance_upper: float | None = None
    width_tolerance_lower: float | None = None
    thickness_tolerance_upper: float | None = None
    thickness_tolerance_lower: float | None = None

    @property
    def has_length_tolerance(self) -> bool:
        return self.length_tolerance_upper is not None and self.length_tolerance_lower is not None

    @property
    def has_width_tolerance(self) -> bool:
        return self.width_tolerance_upper is not None and self.width_tolerance_lower is not None

    @property
    def has_thickness_tolerance(self) -> bool:
        return self.thickness_tolerance_upper is not None and self.thickness_tolerance_lower is not None

    @property
    def thickness_mid(self) -> float:
        if not self.has_thickness_tolerance:
            return self.thickness
        return self.thickness + (
            self.thickness_tolerance_upper + self.thickness_tolerance_lower
        ) / 2.0


@dataclass(frozen=True)
class FormingSpec:
    R_form: float
    chord_width: float
    length: float
    finished_thickness: float
    forming_radius_mode: str = "same_R_big_R"

    @property
    def R_form_outer(self) -> float:
        return self.R_form

    @property
    def R_form_inner(self) -> float:
        return self.R_form


@dataclass(frozen=True)
class GuideSpec:
    finished_thickness: float
    chord_width: float
    machining_allowance: float = 0.18
    guide_extra_clearance: float = 0.07
    thickness_clearance_mid: float | None = None
    slot_width_tolerance: float = 0.01
    preform_tolerance: "ProductPreFormTolerance" = None
    relief: "ReliefSpec" = None
    outer_width: float = 33.0
    outer_height: float = 27.0
    slot_base_height: float = 12.0
    center_offset: float = 1.5
    slot_center_offset: float = 0.0
    tolerance_slot_clearance: float | None = None
    use_tolerance_based_slot_width: bool = False

    def __post_init__(self) -> None:
        if self.preform_tolerance is None:
            object.__setattr__(self, "preform_tolerance", ProductPreFormTolerance())
        if self.relief is None:
            object.__setattr__(self, "relief", ReliefSpec())
        if self.tolerance_slot_clearance is None:
            object.__setattr__(
                self,
                "tolerance_slot_clearance",
                _standard_width_clearance(self.chord_width, self.preform_tolerance),
            )

    @property
    def guide_thickness(self) -> float:
        return self.finished_thickness + self.thickness_clearance_mid_value

    @property
    def thickness_clearance_mid_value(self) -> float:
        if self.thickness_clearance_mid is not None:
            return self.thickness_clearance_mid
        return self.machining_allowance + self.guide_extra_clearance

    @property
    def guide_slot_width(self) -> float:
        if self.use_tolerance_based_slot_width:
            return _round_half_up(self.guide_slot_width_raw, digits=2)
        return self.chord_width

    @property
    def guide_slot_width_raw(self) -> float:
        tolerance_average = (self.preform_tolerance.upper + self.preform_tolerance.lower) / 2.0
        return self.chord_width + tolerance_average + self.tolerance_slot_clearance

    @property
    def slot_width_dimension_text(self) -> str:
        return f"{_format_dimension_value(self.guide_slot_width)}±{self.slot_width_tolerance:.2f}"

    @property
    def slot_width_nominal(self) -> float:
        return self.guide_slot_width

    @property
    def slot_width_min(self) -> float:
        return self.slot_width_nominal - self.slot_width_tolerance

    @property
    def slot_width_max(self) -> float:
        return self.slot_width_nominal + self.slot_width_tolerance

    @property
    def product_preform_width_max(self) -> float:
        return self.chord_width + self.preform_tolerance.upper

    @property
    def product_preform_width_min(self) -> float:
        return self.chord_width + self.preform_tolerance.lower

    @property
    def product_preform_width_average(self) -> float:
        return (self.product_preform_width_max + self.product_preform_width_min) / 2.0

    @property
    def total_clearance_min(self) -> float:
        return self.slot_width_min - self.product_preform_width_max

    @property
    def total_clearance_max(self) -> float:
        return self.slot_width_max - self.product_preform_width_min

    @property
    def side_clearance_min(self) -> float:
        return self.total_clearance_min / 2.0

    @property
    def side_clearance_max(self) -> float:
        return self.total_clearance_max / 2.0

    @property
    def center_opening(self) -> float:
        return self.center_offset


@dataclass(frozen=True)
class ReliefSpec:
    relief_count: int = 4
    relief_size: float = 1.0

    @property
    def relief_label(self) -> str:
        return f"{self.relief_count}-r{self.relief_size / 2.0:g}"


@dataclass(frozen=True)
class ProductPreFormTolerance:
    upper: float = 0.0
    lower: float = 0.0


CompanyTileSpec = FinishedSpec


def parse_relief_spec(label: str) -> ReliefSpec:
    pattern = re.compile(r"^\s*(?P<count>\d+)\s*-\s*(?P<size>\d+(?:\.\d+)?)\s*$")
    match = pattern.match(label)
    if not match:
        raise ValueError("Relief spec must use format count-size, for example 4-1 or 4-0.6.")
    count = int(match.group("count"))
    size = float(match.group("size"))
    if count <= 0:
        raise ValueError("relief_count must be greater than 0.")
    if size <= 0:
        raise ValueError("relief_size must be greater than 0.")
    return ReliefSpec(relief_count=count, relief_size=size)


def parse_company_tile_spec(spec: str, require_chord_tolerance: bool = True) -> FinishedSpec:
    """Parse company format: R_outer * R_inner * chord_width * length * thickness."""
    sep = r"\s*[*xX×]\s*"
    number = r"[+-]?\d+(?:\.\d+)?"
    chord_width = (
        r"(?P<chord_width>\d+(?:\.\d+)?)"
        r"(?:\s*[（(]\s*(?P<tol_upper>"
        + number
        + r")\s*[/／]\s*(?P<tol_lower>"
        + number
        + r")\s*[）)])?"
    )
    thickness = (
        r"(?P<thickness>\d+(?:\.\d+)?)"
        r"(?:\s*[（(]\s*(?P<thickness_tol_upper>"
        + number
        + r")\s*[/／]\s*(?P<thickness_tol_lower>"
        + number
        + r")\s*[）)])?"
    )
    pattern = re.compile(
        r"^\s*R(?P<R_outer>\d+(?:\.\d+)?)"
        + sep
        + r"R(?P<R_inner>\d+(?:\.\d+)?)"
        + sep
        + chord_width
        + sep
        + r"(?P<length>\d+(?:\.\d+)?)"
        + sep
        + thickness
        + r"\s*$",
        re.IGNORECASE,
    )
    match = pattern.match(spec)
    if not match:
        raise ValueError(
            "Specification must use format: R_outer*R_inner*chord_width*length*thickness, "
            "and chord_width must include upper/lower tolerance, "
            "for example R17.45*R15.8*6.20(-0.02/-0.04)*15.5*1.65."
        )

    values = {name: (None if value is None else float(value)) for name, value in match.groupdict().items()}
    tile_spec = FinishedSpec(
        raw=spec,
        R_outer_finished=values["R_outer"],
        R_inner_finished=values["R_inner"],
        chord_width=values["chord_width"],
        length=values["length"],
        finished_thickness=values["thickness"],
        chord_width_tolerance_upper=values.get("tol_upper"),
        chord_width_tolerance_lower=values.get("tol_lower"),
        thickness_tolerance_upper=values.get("thickness_tol_upper"),
        thickness_tolerance_lower=values.get("thickness_tol_lower"),
    )

    for field_name in ("R_outer_finished", "R_inner_finished", "chord_width", "length", "finished_thickness"):
        if getattr(tile_spec, field_name) <= 0:
            raise ValueError(f"{field_name} must be greater than 0.")

    if require_chord_tolerance and not tile_spec.has_chord_width_tolerance:
        raise ValueError(
            "chord_width must include upper/lower tolerance, "
            "for example 6.20(-0.02/-0.04)."
        )

    return tile_spec


def parse_company_bread_spec(spec: str) -> FinishedSpec:
    """Parse bread/mantou format: R * length * width * thickness."""
    sep = r"\s*[*xX×]\s*"
    pattern = re.compile(
        r"^\s*R(?P<radius>\d+(?:\.\d+)?)"
        + sep
        + r"(?P<length>\d+(?:\.\d+)?)"
        + sep
        + r"(?P<width>\d+(?:\.\d+)?)"
        + sep
        + r"(?P<thickness>\d+(?:\.\d+)?)\s*$",
        re.IGNORECASE,
    )
    match = pattern.match(spec)
    if not match:
        raise ValueError(
            "Bread specification must use format R*length*width*thickness, "
            "for example R40.75*30*22*3.3."
        )
    values = {name: float(value) for name, value in match.groupdict().items()}
    for field_name, value in values.items():
        if value <= 0:
            raise ValueError(f"{field_name} must be greater than 0.")
    return FinishedSpec(
        raw=spec,
        R_outer_finished=values["radius"],
        R_inner_finished=values["radius"],
        chord_width=values["width"],
        length=values["length"],
        finished_thickness=values["thickness"],
        finished_shape="bread",
    )


def parse_block_spec(spec: str) -> BlockSpec:
    """Parse QG 38002 block format: length * width * thickness."""
    sep = r"\s*[*xX×]\s*"
    number = r"[+-]?\d+(?:\.\d+)?"
    length = (
        r"(?P<length>\d+(?:\.\d+)?)"
        r"(?:\s*[（(]\s*(?P<length_tol_upper>"
        + number
        + r")\s*[/／]\s*(?P<length_tol_lower>"
        + number
        + r")\s*[）)])?"
    )
    width = (
        r"(?P<width>\d+(?:\.\d+)?)"
        r"(?:\s*[（(]\s*(?P<width_tol_upper>"
        + number
        + r")\s*[/／]\s*(?P<width_tol_lower>"
        + number
        + r")\s*[）)])?"
    )
    thickness = (
        r"(?P<thickness>\d+(?:\.\d+)?)"
        r"(?:\s*[（(]\s*(?P<thickness_tol_upper>"
        + number
        + r")\s*[/／]\s*(?P<thickness_tol_lower>"
        + number
        + r")\s*[）)])?"
    )
    pattern = re.compile(
        r"^\s*"
        + length
        + sep
        + width
        + sep
        + thickness
        + r"\s*$",
        re.IGNORECASE,
    )
    match = pattern.match(spec)
    if not match:
        raise ValueError("Block specification must use format: length*width*thickness, for example 8.94*3*2.5.")
    values = {name: (None if value is None else float(value)) for name, value in match.groupdict().items()}
    block_spec = BlockSpec(
        raw=spec,
        length=values["length"],
        width=values["width"],
        thickness=values["thickness"],
        length_tolerance_upper=values.get("length_tol_upper"),
        length_tolerance_lower=values.get("length_tol_lower"),
        width_tolerance_upper=values.get("width_tol_upper"),
        width_tolerance_lower=values.get("width_tol_lower"),
        thickness_tolerance_upper=values.get("thickness_tol_upper"),
        thickness_tolerance_lower=values.get("thickness_tol_lower"),
    )
    for field_name in ("length", "width", "thickness"):
        if getattr(block_spec, field_name) <= 0:
            raise ValueError(f"{field_name} must be greater than 0.")
    return block_spec


def validate_company_tile_spec(
    tile_spec: FinishedSpec,
    tolerance: float = THICKNESS_TOLERANCE,
) -> tuple[str, ...]:
    return ()


def _format_dimension_value(value: float) -> str:
    if isclose(value * 100.0, round(value * 100.0), abs_tol=1e-9):
        return f"{value:.2f}"
    return f"{value:.3f}"


def _round_half_up(value: float, digits: int = 2) -> float:
    quantum = Decimal("1").scaleb(-digits)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def _standard_width_clearance(chord_width: float, preform_tolerance: ProductPreFormTolerance) -> float:
    width_tolerance_range = abs(preform_tolerance.upper - preform_tolerance.lower)
    if width_tolerance_range <= 0.02 + 1e-9:
        return 0.04
    return 0.05

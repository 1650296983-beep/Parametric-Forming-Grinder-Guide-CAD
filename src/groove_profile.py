from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Mapping, Sequence


Confidence = Literal["high", "medium", "low"]


SHAPE_ALIASES = {
    "block": "rectangular_block",
    "rectangular_block": "rectangular_block",
    "bread": "bread_shape",
    "bread_shape": "bread_shape",
    "tile": "tile_shape",
    "tile_shape": "tile_shape",
    "same_r_tile": "same_r_tile",
    "arc_segment": "same_r_tile",
    "unknown": "unknown",
}

OPPOSITE_SIDE = {
    "upper": "lower",
    "lower": "upper",
    "left": "right",
    "right": "left",
}


@dataclass(frozen=True)
class GrooveProfileDecision:
    groove_profile: str
    flat_side: str | None
    arc_side: str | None
    arc_radius: float | None
    arc_center_side: str | None
    dimension_source: Mapping[str, str]
    confidence: Confidence
    guide_profile_source: str | None
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["dimension_source"] = dict(self.dimension_source)
        payload["warnings"] = list(self.warnings)
        return payload


def determine_groove_profile(
    product_shape_before: str,
    product_shape_after: str,
    finished_radius_count: int,
    machine_type: str,
    guide_rail_type: str,
    wheel_sequence: Sequence[str],
    template_rules: Mapping[str, Any],
    *,
    finished_radii: Sequence[float] = (),
    first_wheel_side: str | None = None,
) -> GrooveProfileDecision:
    """Return one explicit, auditable groove decision without drawing geometry."""
    before = normalize_shape(product_shape_before)
    after = normalize_shape(product_shape_after)
    warnings: list[str] = []
    common_sources = {
        "slot_width": "pre_grinding_spec.width_and_tolerance",
        "slot_height": "pre_grinding_spec.thickness_and_tolerance",
        "positioning_envelope": "pre_grinding_spec",
        "machine_layout": "machine_template_config",
    }

    if before == "unknown" or after == "unknown":
        warnings.append(
            "Insufficient shape metadata; formal groove geometry requires manual confirmation."
        )
        return _manual_review(common_sources, warnings)

    if before == "rectangular_block" and after == "rectangular_block":
        return GrooveProfileDecision(
            groove_profile="rectangular_groove",
            flat_side=None,
            arc_side=None,
            arc_radius=None,
            arc_center_side=None,
            dimension_source={
                **common_sources,
                "profile": "pre_grinding_spec.rectangular_envelope",
            },
            confidence="high",
            guide_profile_source="pre_grinding_spec",
        )

    if before == "rectangular_block" and after == "bread_shape":
        if finished_radius_count != 1 or len(finished_radii) != 1:
            warnings.append(
                "Bread-shape finished product must provide exactly one finished radius."
            )
            return _manual_review(common_sources, warnings)
        return GrooveProfileDecision(
            groove_profile="rectangular_groove",
            flat_side=None,
            arc_side=None,
            arc_radius=None,
            arc_center_side=None,
            dimension_source={
                **common_sources,
                "profile": "pre_grinding_spec.rectangular_envelope",
                "finished_target_radius": "finished_spec.single_R",
            },
            confidence="high",
            guide_profile_source="pre_grinding_spec_rectangular_envelope",
        )

    if before == "rectangular_block" and after == "tile_shape":
        if finished_radius_count != 2 or len(finished_radii) != 2:
            warnings.append(
                "Tile-shape finished product must provide exactly two finished radii."
            )
            return _manual_review(common_sources, warnings)
        orientation = _flat_arc_orientation(template_rules, first_wheel_side, warnings)
        if orientation is None:
            return _manual_review(common_sources, warnings)
        flat_side, arc_side, arc_center_side = orientation
        return GrooveProfileDecision(
            groove_profile="flat_arc_groove",
            flat_side=flat_side,
            arc_side=arc_side,
            arc_radius=max(float(value) for value in finished_radii),
            arc_center_side=arc_center_side,
            dimension_source={
                **common_sources,
                "arc_radius": "max(finished_spec.outer_radius, finished_spec.inner_radius)",
                "arc_orientation": "first_wheel_side_and_template_coordinate_system",
            },
            confidence="high",
            guide_profile_source="finished_product_big_r_with_pre_grinding_block",
        )

    if before == "same_r_tile" and after == "tile_shape":
        return GrooveProfileDecision(
            groove_profile="same_r_tile_groove",
            flat_side=None,
            arc_side=None,
            arc_radius=None,
            arc_center_side=None,
            dimension_source={
                **common_sources,
                "profile": "pre_grinding_spec.equal_R_profile",
            },
            confidence="high",
            guide_profile_source="pre_grinding_spec",
        )

    warnings.append(
        f"Unsupported groove combination: before={before}, after={after}; manual confirmation required."
    )
    return _manual_review(common_sources, warnings)


def normalize_shape(value: str) -> str:
    normalized = str(value).strip().lower()
    return SHAPE_ALIASES.get(normalized, "unknown")


def resolve_arc_center_side(first_wheel_side: str) -> str:
    try:
        return OPPOSITE_SIDE[str(first_wheel_side).strip().lower()]
    except KeyError as exc:
        raise ValueError("first_wheel_side must be upper, lower, left, or right.") from exc


def _flat_arc_orientation(
    template_rules: Mapping[str, Any],
    first_wheel_side: str | None,
    warnings: list[str],
) -> tuple[str, str, str] | None:
    if first_wheel_side is None:
        warnings.append("first_wheel_side is required for flat-arc groove orientation.")
        return None
    arc_side = str(first_wheel_side).strip().lower()
    arc_center_side = resolve_arc_center_side(arc_side)
    flat_side = arc_center_side
    configured_flat = _optional_string(template_rules.get("flat_surface_side"))
    configured_arc = _optional_string(template_rules.get("flat_arc_surface_side"))
    configured_center = _optional_string(template_rules.get("flat_arc_center_side"))
    configured = {
        "flat_surface_side": (configured_flat, flat_side),
        "flat_arc_surface_side": (configured_arc, arc_side),
        "flat_arc_center_side": (configured_center, arc_center_side),
    }
    conflicts = [
        name
        for name, (actual, expected) in configured.items()
        if actual is not None and actual != expected
    ]
    if conflicts:
        warnings.append(
            "first_wheel_side conflicts with the approved template orientation: "
            + ", ".join(conflicts)
        )
        return None
    return flat_side, arc_side, arc_center_side


def _manual_review(
    dimension_source: Mapping[str, str],
    warnings: Sequence[str],
) -> GrooveProfileDecision:
    return GrooveProfileDecision(
        groove_profile="manual_review",
        flat_side=None,
        arc_side=None,
        arc_radius=None,
        arc_center_side=None,
        dimension_source=dimension_source,
        confidence="low",
        guide_profile_source=None,
        warnings=tuple(warnings),
    )


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None

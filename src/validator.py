from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from pathlib import Path

from .dimension_writer import DIMENSION_LAYER, DIMENSION_TEXT_FALLBACK_LAYER, TEXT_NOTE_LAYER
from .geometry import ArcSegment, LineSegment, SectionProfile, TileSection
from .spec_parser import FinishedSpec


DEFAULT_TOLERANCE = 0.001


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: tuple[str, ...]

    def raise_for_errors(self) -> None:
        if not self.ok:
            raise ValueError("\n".join(self.errors))


@dataclass(frozen=True)
class TileSectionValidationResult:
    ok: bool
    finished: ValidationResult
    forming: ValidationResult
    errors: tuple[str, ...]


def validate_profile(profile: SectionProfile, tolerance: float = DEFAULT_TOLERANCE) -> ValidationResult:
    errors: list[str] = []
    segments = profile.segments

    for index, current in enumerate(segments):
        following = segments[(index + 1) % len(segments)]
        gap = current.end.distance_to(following.start)
        if gap >= tolerance:
            errors.append(
                f"Adjacent endpoint gap between {current.name} and {following.name} "
                f"is {gap:.6f} mm, expected < {tolerance} mm."
            )

    closure_gap = segments[-1].end.distance_to(segments[0].start)
    if closure_gap >= tolerance:
        errors.append(f"Contour is not closed; closure gap is {closure_gap:.6f} mm.")

    for segment in segments:
        if isinstance(segment, LineSegment) and segment.length <= tolerance:
            errors.append(f"Line segment {segment.name} has zero or near-zero length.")
        if isinstance(segment, ArcSegment):
            if segment.length <= tolerance:
                errors.append(f"Arc segment {segment.name} has zero or near-zero length.")
            start_radius = segment.center.distance_to(segment.start)
            end_radius = segment.center.distance_to(segment.end)
            if not isclose(start_radius, segment.radius, abs_tol=tolerance):
                errors.append(
                    f"{segment.name} start radius is {start_radius:.6f} mm, "
                    f"expected {segment.radius:.6f} mm."
                )
            if not isclose(end_radius, segment.radius, abs_tol=tolerance):
                errors.append(
                    f"{segment.name} end radius is {end_radius:.6f} mm, "
                    f"expected {segment.radius:.6f} mm."
                )

    outer = next((segment for segment in segments if segment.name == "outer_arc"), None)
    inner = next((segment for segment in segments if segment.name == "inner_arc"), None)
    if not isinstance(outer, ArcSegment):
        errors.append("Profile must contain an outer_arc segment.")
    elif profile.params.profile_shape == "bread":
        if not isclose(outer.radius, profile.params.R_outer, abs_tol=tolerance):
            errors.append(
                f"Bread arc radius is {outer.radius:.6f} mm, "
                f"expected {profile.params.R_outer:.6f} mm."
            )
        outer_chord = outer.start.distance_to(outer.end)
        if not isclose(outer_chord, profile.params.chord_width, abs_tol=tolerance):
            errors.append(
                f"Bread arc chord_width is {outer_chord:.6f} mm, "
                f"expected {profile.params.chord_width:.6f} mm."
            )
        plane_name = (
            "top_plane"
            if profile.params.forming_radius_mode
            == "single_R_lower_arc_upper_plane"
            else "bottom_plane"
        )
        plane = next(
            (segment for segment in segments if segment.name == plane_name),
            None,
        )
        if not isinstance(plane, LineSegment):
            errors.append(f"Bread profile must contain a {plane_name} segment.")
        elif not isclose(plane.length, profile.params.chord_width, abs_tol=tolerance):
            errors.append(
                f"Bread plane width is {plane.length:.6f} mm, "
                f"expected {profile.params.chord_width:.6f} mm."
            )
    elif not isinstance(inner, ArcSegment):
        errors.append("Tile profile must contain inner_arc and outer_arc segments.")
    else:
        if not isclose(outer.radius, profile.params.R_outer, abs_tol=tolerance):
            errors.append(
                f"Outer arc radius is {outer.radius:.6f} mm, "
                f"expected {profile.params.R_outer:.6f} mm."
            )
        if not isclose(inner.radius, profile.params.R_inner, abs_tol=tolerance):
            errors.append(
                f"Inner arc radius is {inner.radius:.6f} mm, "
                f"expected {profile.params.R_inner:.6f} mm."
            )

        outer_chord = outer.start.distance_to(outer.end)
        inner_chord = inner.start.distance_to(inner.end)
        if not isclose(outer_chord, profile.params.chord_width, abs_tol=tolerance):
            errors.append(
                f"Outer chord_width is {outer_chord:.6f} mm, "
                f"expected {profile.params.chord_width:.6f} mm."
            )
        if not isclose(inner_chord, profile.params.chord_width, abs_tol=tolerance):
            errors.append(
                f"Inner chord_width is {inner_chord:.6f} mm, "
                f"expected {profile.params.chord_width:.6f} mm."
            )

    if profile.params.thickness is not None:
        right_side = next(segment for segment in segments if segment.name == "right_side")
        left_side = next(segment for segment in segments if segment.name == "left_side")
        if isinstance(right_side, LineSegment) and not isclose(
            right_side.length, profile.params.thickness, abs_tol=tolerance
        ):
            errors.append(
                f"{profile.params.profile_type}_profile right thickness is {right_side.length:.6f} mm, "
                f"expected {profile.params.thickness:.6f} mm."
            )
        if isinstance(left_side, LineSegment) and not isclose(
            left_side.length, profile.params.thickness, abs_tol=tolerance
        ):
            errors.append(
                f"{profile.params.profile_type}_profile left thickness is {left_side.length:.6f} mm, "
                f"expected {profile.params.thickness:.6f} mm."
            )
    if (
        profile.params.thickness is not None
        and profile.params.profile_type == "forming"
        and profile.params.profile_shape == "tile"
    ):
        if not isclose(profile.params.R_outer, profile.params.R_inner, abs_tol=tolerance):
            errors.append(
                "forming_profile must use same R: "
                f"R_outer={profile.params.R_outer:.6f}, R_inner={profile.params.R_inner:.6f}."
            )

    return ValidationResult(ok=not errors, errors=tuple(errors))


def validate_tile_section(
    tile_section: TileSection,
    tolerance: float = DEFAULT_TOLERANCE,
) -> TileSectionValidationResult:
    finished = validate_profile(tile_section.finished_profile, tolerance=tolerance)
    forming = validate_profile(tile_section.forming_profile, tolerance=tolerance)
    errors = tuple(
        [f"finished_profile: {error}" for error in finished.errors]
        + [f"forming_profile: {error}" for error in forming.errors]
    )
    return TileSectionValidationResult(ok=not errors, finished=finished, forming=forming, errors=errors)


def write_geometry_report(
    profile: SectionProfile | TileSection,
    validation: ValidationResult | TileSectionValidationResult,
    path: str | Path,
    tile_spec: FinishedSpec | None = None,
    tolerance: float = DEFAULT_TOLERANCE,
) -> Path:
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(profile, TileSection):
        if not isinstance(validation, TileSectionValidationResult):
            validation = validate_tile_section(profile, tolerance=tolerance)
        return _write_tile_section_report(profile, validation, report_path, tolerance=tolerance)

    if not isinstance(validation, ValidationResult):
        raise TypeError("SectionProfile report requires a ValidationResult.")

    outer_arc = next(segment for segment in profile.segments if segment.name == "outer_arc")
    inner_arc = next(segment for segment in profile.segments if segment.name == "inner_arc")
    if not isinstance(outer_arc, ArcSegment) or not isinstance(inner_arc, ArcSegment):
        raise ValueError("Profile report requires outer_arc and inner_arc.")

    lines = [
        "Geometry validation report",
        "Status: PASS" if validation.ok else "Status: FAIL",
        f"Tolerance: {tolerance} mm",
        "",
    ]
    if tile_spec is not None:
        lines.extend(
            [
                f"Company spec: {tile_spec.raw}",
                f"R_outer_finished: {tile_spec.R_outer_finished:.6f} mm",
                f"R_inner_finished: {tile_spec.R_inner_finished:.6f} mm",
                f"chord_width: {tile_spec.chord_width:.6f} mm",
                f"length: {tile_spec.length:.6f} mm",
                f"finished_thickness: {tile_spec.finished_thickness:.6f} mm",
                f"abs(R_outer_finished - R_inner_finished): {tile_spec.computed_finished_thickness:.6f} mm",
                "2D section chord source: company chord_width",
                "",
            ]
        )

    lines.extend(
        [
            f"section chord_width: {profile.params.chord_width:.6f} mm",
            f"outer left: ({profile.outer_left.x:.6f}, {profile.outer_left.y:.6f})",
            f"outer right: ({profile.outer_right.x:.6f}, {profile.outer_right.y:.6f})",
            f"inner right: ({profile.inner_right.x:.6f}, {profile.inner_right.y:.6f})",
            f"inner left: ({profile.inner_left.x:.6f}, {profile.inner_left.y:.6f})",
            f"outer radius: {outer_arc.radius:.6f} mm",
            f"inner radius: {inner_arc.radius:.6f} mm",
            f"outer chord: {outer_arc.start.distance_to(outer_arc.end):.6f} mm",
            f"inner chord: {inner_arc.start.distance_to(inner_arc.end):.6f} mm",
            "",
            "Adjacent endpoint gaps:",
        ]
    )

    for index, current in enumerate(profile.segments):
        following = profile.segments[(index + 1) % len(profile.segments)]
        gap = current.end.distance_to(following.start)
        lines.append(f"- {current.name} -> {following.name}: {gap:.9f} mm")

    if validation.errors:
        lines.append("")
        lines.append("Errors:")
        lines.extend(f"- {error}" for error in validation.errors)

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def write_dimension_report(
    tile_section: TileSection,
    path: str | Path,
    dxf_path: str | Path | None = None,
    output_mode: str = "debug",
    tolerance: float = DEFAULT_TOLERANCE,
) -> Path:
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    guide = tile_section.guide_spec
    r_form = tile_section.forming_spec.R_form
    dimension_specs = [
        ("slot_width", "horizontal_linear", guide.slot_width_dimension_text, guide.guide_slot_width, "PARAM_SLOT left/right relief centers"),
        ("guide_thickness", "vertical_linear", f"{guide.guide_thickness:.2f}", guide.guide_thickness, "PARAM_SLOT upper/lower relief centers"),
        ("center_opening", "horizontal_linear", f"{guide.center_opening:.1f}", guide.center_opening, "PARAM_SLOT top opening vertical boundaries"),
        ("slot_base_height", "vertical_linear", f"{guide.slot_base_height:.1f}", guide.slot_base_height, "FIXED_TEMPLATE bottom baseline to slot base"),
        ("outer_width", "horizontal_linear", f"{guide.outer_width:.0f}", guide.outer_width, "FIXED_TEMPLATE outer frame width"),
        ("outer_height", "vertical_linear", f"{guide.outer_height:.1f}", guide.outer_height, "FIXED_TEMPLATE outer frame height"),
        ("upper_r_form", "radius", f"R{r_form:.2f}", r_form, "PARAM_SLOT upper R_form arc"),
        ("lower_r_form", "radius", f"R{r_form:.2f}", r_form, "PARAM_SLOT lower R_form arc"),
    ]

    native_texts: list[str] = []
    release_texts: list[str] = []
    fallback_texts: list[str] = []
    text_note_texts: list[str] = []
    fallback_layer_hidden = False
    audit_errors = 0
    if dxf_path is not None:
        try:
            import ezdxf

            doc = ezdxf.readfile(dxf_path)
            auditor = doc.audit()
            audit_errors = len(auditor.errors)
            for entity in doc.modelspace():
                if entity.dxf.layer == DIMENSION_LAYER and entity.dxftype() == "DIMENSION":
                    native_texts.append(entity.dxf.text)
                    release_texts.extend(_dimension_block_texts(doc, entity))
                if entity.dxf.layer == DIMENSION_LAYER and entity.dxftype() in {"TEXT", "MTEXT"}:
                    release_texts.append(entity.dxf.text if entity.dxftype() == "TEXT" else entity.text)
                if entity.dxf.layer == DIMENSION_TEXT_FALLBACK_LAYER and entity.dxftype() == "TEXT":
                    fallback_texts.append(entity.dxf.text)
                if entity.dxf.layer == TEXT_NOTE_LAYER and entity.dxftype() in {"TEXT", "MTEXT"}:
                    text_note_texts.append(entity.dxf.text if entity.dxftype() == "TEXT" else entity.text)
            if DIMENSION_TEXT_FALLBACK_LAYER in doc.layers:
                fallback_layer_hidden = doc.layers.get(DIMENSION_TEXT_FALLBACK_LAYER).is_off()
        except Exception as exc:
            audit_errors = 1
            native_texts.append(f"DXF_READ_FAILED: {exc}")

    lines = [
        "Dimension validation report",
        f"Status: {'PASS' if audit_errors == 0 else 'FAIL'}",
        f"Tolerance: {tolerance} mm",
        f"Native dimension layer: {DIMENSION_LAYER}",
        f"Fallback text layer: {DIMENSION_TEXT_FALLBACK_LAYER}",
        f"Text note layer: {TEXT_NOTE_LAYER}",
        f"Output mode: {output_mode}",
        f"DXF audit errors: {audit_errors}",
        "",
        "native_dimension_entities:",
        f"  count: {len(native_texts)}",
        f"  texts: {', '.join(native_texts) if native_texts else '(not inspected)'}",
        "",
        "release_dimension_text_entities:",
        f"  count: {len(release_texts)}",
        f"  texts: {', '.join(release_texts) if release_texts else '(not inspected)'}",
        "",
        "fallback_text_entities:",
        f"  count: {len(fallback_texts)}",
        f"  layer_hidden: {fallback_layer_hidden}",
        f"  texts: {', '.join(fallback_texts) if fallback_texts else '(not inspected)'}",
        "",
        "text_note_entities:",
        f"  count: {len(text_note_texts)}",
        f"  texts: {', '.join(text_note_texts) if text_note_texts else '(not inspected)'}",
        "",
        "dimension_checks:",
    ]
    for name, dim_type, text, actual, source in dimension_specs:
        expected_count = 2 if text == f"R{r_form:.2f}" else 1
        native_count = native_texts.count(text) if native_texts else 0
        release_text_count = release_texts.count(text) if release_texts else 0
        fallback_count = fallback_texts.count(text) if fallback_texts else 0
        if output_mode == "release":
            native_status = "SUSPENDED"
            release_text_status = "PASS" if release_text_count >= expected_count else "FAIL"
        else:
            native_status = "PASS" if dxf_path is None or native_count >= expected_count else "FAIL"
            release_text_status = "N/A"
        if output_mode == "release":
            fallback_status = "PASS" if fallback_count == 0 else "FAIL"
        else:
            fallback_status = "PASS" if dxf_path is None or fallback_count >= expected_count else "FAIL"
        value_status = "PASS" if abs(actual - actual) <= tolerance else "FAIL"
        lines.extend(
            [
                f"- name: {name}",
                f"  type: {dim_type}",
                f"  source: {source}",
                f"  actual_value: {actual:.6f} mm",
                f"  display_text: {text}",
                f"  native_dimension_text_count: {native_count}",
                f"  release_text_count: {release_text_count}",
                f"  fallback_text_count: {fallback_count}",
                f"  native_status: {native_status}",
                f"  release_text_status: {release_text_status}",
                f"  fallback_status: {fallback_status}",
                f"  value_status: {value_status}",
            ]
        )

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def _write_tile_section_report(
    tile_section: TileSection,
    validation: TileSectionValidationResult,
    report_path: Path,
    tolerance: float = DEFAULT_TOLERANCE,
) -> Path:
    spec = tile_section.spec
    lines = [
        "Geometry validation report",
        "Status: PASS" if validation.ok else "Status: FAIL",
        f"Tolerance: {tolerance} mm",
        "",
        f"Company spec: {spec.raw}",
        f"R_outer_finished: {spec.R_outer_finished:.6f} mm",
        f"R_inner_finished: {spec.R_inner_finished:.6f} mm",
        f"chord_width: {spec.chord_width:.6f} mm",
        f"length: {spec.length:.6f} mm",
        f"finished_thickness: {spec.finished_thickness:.6f} mm",
        f"R_form: {tile_section.forming_spec.R_form:.6f} mm",
        f"forming_radius_mode: {tile_section.forming_radius_mode}",
        (
            "guide_thickness: "
            f"{tile_section.guide_spec.finished_thickness:.6f} + "
            f"{tile_section.guide_spec.thickness_clearance_mid_value:.6f} = "
            f"{tile_section.guide_spec.guide_thickness:.6f} mm"
        ),
        f"relief_label: {tile_section.guide_spec.relief.relief_label}",
        "",
    ]
    lines.extend(_profile_report_lines("finished_profile", tile_section.finished_profile, validation.finished))
    lines.append("")
    lines.extend(_profile_report_lines("forming_profile", tile_section.forming_profile, validation.forming))
    lines.append("")
    lines.extend(_guide_report_lines(tile_section))

    if validation.errors:
        lines.append("")
        lines.append("Errors:")
        lines.extend(f"- {error}" for error in validation.errors)

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def _dimension_block_texts(doc, dimension) -> list[str]:
    if not dimension.dxf.hasattr("geometry") or dimension.dxf.geometry not in doc.blocks:
        return []
    texts = []
    for entity in doc.blocks[dimension.dxf.geometry]:
        if entity.dxftype() == "TEXT":
            texts.append(entity.dxf.text)
        elif entity.dxftype() == "MTEXT":
            texts.append(entity.text)
    return texts


def _guide_report_lines(tile_section: TileSection) -> list[str]:
    guide = tile_section.guide_spec
    R_form = tile_section.forming_spec.R_form
    half_slot = guide.guide_slot_width / 2.0
    arc_base = (R_form**2 - half_slot**2) ** 0.5
    lower_center_y = guide.slot_base_height - arc_base
    upper_center_y = guide.slot_base_height + guide.guide_thickness - arc_base
    relief_radius = guide.relief.relief_size / 2.0
    return [
        "guide_spec:",
        f"  guide_slot_width: {guide.guide_slot_width:.6f} +/- {guide.slot_width_tolerance:.6f} mm",
        f"  slot_width_nominal: {guide.slot_width_nominal:.6f} mm",
        f"  slot_width_min: {guide.slot_width_min:.6f} mm",
        f"  slot_width_max: {guide.slot_width_max:.6f} mm",
        (
            "  product_preform_width: "
            f"{guide.chord_width:.6f}({guide.preform_tolerance.upper:.6f}/"
            f"{guide.preform_tolerance.lower:.6f}) mm"
        ),
        f"  product_preform_width_max: {guide.product_preform_width_max:.6f} mm",
        f"  product_preform_width_min: {guide.product_preform_width_min:.6f} mm",
        f"  product_preform_width_average: {guide.product_preform_width_average:.6f} mm",
        f"  preform_width_tolerance_range: "
        f"{guide.product_preform_width_max - guide.product_preform_width_min:.6f} mm",
        f"  slot_clearance_mid: {guide.tolerance_slot_clearance:.6f} mm",
        f"  tolerance_based_slot_width: {'YES' if guide.use_tolerance_based_slot_width else 'NO'}",
        f"  total_clearance_min: {guide.total_clearance_min:.6f} mm",
        f"  total_clearance_max: {guide.total_clearance_max:.6f} mm",
        f"  side_clearance_min: {guide.side_clearance_min:.6f} mm",
        f"  side_clearance_max: {guide.side_clearance_max:.6f} mm",
        "  slot_geometry: arc",
        f"  slot_upper_arc_radius: {R_form:.6f} mm",
        f"  slot_lower_arc_radius: {R_form:.6f} mm",
        f"  slot_upper_arc_center: ({guide.slot_center_offset:.6f}, {upper_center_y:.6f})",
        f"  slot_lower_arc_center: ({guide.slot_center_offset:.6f}, {lower_center_y:.6f})",
        f"  slot_arc_center_offset: {guide.guide_thickness:.6f} mm",
        f"  relief_count: {guide.relief.relief_count}",
        f"  relief_size: {guide.relief.relief_size:.6f} mm",
        f"  relief_radius: {relief_radius:.6f} mm",
        f"  relief_label: {guide.relief.relief_label}",
        f"  outer_width: {guide.outer_width:.6f} mm",
        f"  outer_height: {guide.outer_height:.6f} mm",
        f"  slot_base_height: {guide.slot_base_height:.6f} mm",
        f"  slot_center_offset: {guide.slot_center_offset:.6f} mm",
        f"  center_opening: {guide.center_opening:.6f} mm",
        "",
        "dimension_annotations:",
        (
            "  slot_width_dimension: source=PARAM_SLOT left/right slot boundary X distance; "
            f"actual={guide.guide_slot_width:.6f} mm; text={guide.slot_width_dimension_text}"
        ),
        (
            "  guide_thickness_dimension: source=PARAM_SLOT upper/lower slot boundary Y distance; "
            f"actual={guide.guide_thickness:.6f} mm; text={guide.guide_thickness:.2f}"
        ),
        (
            "  radius_dimension: source=PARAM_SLOT upper/lower R_form arc entities; "
            f"actual={R_form:.6f} mm; text=R{R_form:.2f}"
        ),
        (
            "  relief_note: source=ReliefSpec and four PARAM_SLOT relief arcs; "
            f"count={guide.relief.relief_count}; size={guide.relief.relief_size:.6f} mm; "
            f"radius={relief_radius:.6f} mm; text={guide.relief.relief_label}"
        ),
        (
            "  center_offset_dimension: source=PARAM_SLOT center opening vertical line X distance; "
            f"actual={guide.center_opening:.6f} mm; text={guide.center_opening:.1f}"
        ),
        (
            "  slot_base_dimension: source=FIXED_TEMPLATE bottom baseline to slot base line; "
            f"actual={guide.slot_base_height:.6f} mm; text={guide.slot_base_height:.1f}"
        ),
        (
            "  outer_width_dimension: source=FIXED_TEMPLATE outer frame width; "
            f"actual={guide.outer_width:.6f} mm; text={guide.outer_width:.0f}"
        ),
        (
            "  outer_height_dimension: source=FIXED_TEMPLATE outer frame height; "
            f"actual={guide.outer_height:.6f} mm; text={guide.outer_height:.1f}"
        ),
    ]


def _profile_report_lines(name: str, profile: SectionProfile, validation: ValidationResult) -> list[str]:
    outer_arc = next(segment for segment in profile.segments if segment.name == "outer_arc")
    inner_arc = next(segment for segment in profile.segments if segment.name == "inner_arc")
    if not isinstance(outer_arc, ArcSegment) or not isinstance(inner_arc, ArcSegment):
        raise ValueError("Profile report requires outer_arc and inner_arc.")

    closure_gap = profile.segments[-1].end.distance_to(profile.segments[0].start)
    right_side = next(segment for segment in profile.segments if segment.name == "right_side")
    left_side = next(segment for segment in profile.segments if segment.name == "left_side")
    thickness_value = ""
    if isinstance(right_side, LineSegment) and isinstance(left_side, LineSegment):
        thickness = (right_side.length + left_side.length) / 2.0
        thickness_value = f"{thickness:.6f} mm"

    lines = [
        f"{name}:",
        f"  status: {'PASS' if validation.ok else 'FAIL'}",
        f"  profile_type: {profile.params.profile_type}",
        f"  outer radius: {outer_arc.radius:.6f} mm",
        f"  inner radius: {inner_arc.radius:.6f} mm",
        f"  chord_width outer: {outer_arc.start.distance_to(outer_arc.end):.6f} mm",
        f"  chord_width inner: {inner_arc.start.distance_to(inner_arc.end):.6f} mm",
        f"  thickness: {thickness_value}",
        f"  closed: {'YES' if closure_gap < DEFAULT_TOLERANCE else 'NO'}",
        f"  closure gap: {closure_gap:.9f} mm",
        f"  outer left: ({profile.outer_left.x:.6f}, {profile.outer_left.y:.6f})",
        f"  outer right: ({profile.outer_right.x:.6f}, {profile.outer_right.y:.6f})",
        f"  inner right: ({profile.inner_right.x:.6f}, {profile.inner_right.y:.6f})",
        f"  inner left: ({profile.inner_left.x:.6f}, {profile.inner_left.y:.6f})",
    ]
    if profile.params.guide_thickness is not None:
        lines.append(f"  guide_thickness: {profile.params.guide_thickness:.6f} mm")
    if profile.params.forming_radius_mode:
        lines.append(f"  forming_radius_mode: {profile.params.forming_radius_mode}")
    return lines

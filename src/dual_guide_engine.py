from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
from math import atan2, cos, degrees, hypot, radians, sin, sqrt
from pathlib import Path
from typing import Any, Union

from .block_geometry import BlockGuideSection
from .cavity_projection import (
    derive_cavity_projection_profile,
    horizontal_arc_gap,
)
from .dimension_writer import (
    DIMENSION_LAYER,
    TEMPLATE_DIMENSION_STYLE,
    TEMPLATE_DIMENSION_TEXT_HEIGHT,
    add_linear_dimension_with_text,
)
from .dimension_roles import SECTION_CENTER_OPENING
from .dimension_precision import (
    build_dimension_precision_audit,
    normalize_dimension_display_precision,
)
from .dxf_writer import (
    DEBUG_CONTROL_LAYER,
    DEBUG_POINTS_LAYER,
    SECTION_CENTER_LAYER,
    TemplateAnchor,
    _add_block_to_tile_flat_arc_slot_entities,
    _add_block_slot_entities,
    _add_debug_entities,
    _add_down_up_bread_slot_entities,
    _add_param_slot_entities,
    _ensure_dimension_text_style,
    _ensure_layer,
    _find_block_thickness_dimension,
    _find_block_slot_width_dimension,
    _find_block_top_gap_dimension,
    _find_dimension_by_text,
    _is_block_template_param_entity,
    _set_dimension_actual_measurement,
    _set_dimension_block_text,
    _simplify_release_layers,
    _update_down_up_flat_arc_opening_dimension,
    _update_block_relief_size_dimension,
    _update_block_slot_width_dimension,
    _update_block_thickness_dimension,
    _update_block_top_gap_dimension,
    _update_down_up_flat_arc_r_dimension,
)
from .geometry import TileSection
from .global_rules import DEFAULT_WHEEL_RADIUS, WHEEL_CUT_IN_RATIO
from .machine_config import MachineConfig
from .release_entity_audit import (
    build_modelspace_parametric_duplicate_audit,
)
from .relief_arc_audit import build_four_outer_relief_arc_audit
from .dual_guide_release_audit import (
    build_release_line_type_audit,
    write_dimension_definition_point_audit,
)
from .side_view_writer import (
    SIDE_CAVITY_LAYER,
    SIDE_CENTER_LAYER,
    SIDE_DERIVED_RELEASE_LAYER,
    SIDE_DIMENSION_LAYER,
    SIDE_TEMPLATE_LAYER,
)
from .spec_parser import BlockSpec, FinishedSpec


PRODUCT_REFERENCE_LAYER = "PRODUCT_REFERENCE"
SIDE_DEBUG_LAYER = "SIDE_DEBUG"
DualGuideProfile = Union[BlockGuideSection, TileSection]
DualGuideParsedSpec = Union[BlockSpec, FinishedSpec]


@dataclass(frozen=True)
class GuideSectionInstance:
    section_id: str
    anchor: TemplateAnchor
    fixed_spans: tuple[float, ...]
    side_bounds: tuple[float, float, float, float]
    side_centerline_x_values: tuple[float, ...]
    wheel_positions: tuple[str, ...]

    @property
    def center(self) -> tuple[float, float]:
        return (
            round(self.anchor.slot_center_x, 3),
            round((self.anchor.bottom + self.anchor.top) / 2.0, 3),
        )


@dataclass(frozen=True)
class TemplateFixedGeometry:
    guide_length: float
    side_fixed_spans: tuple[float, ...]
    outer_height: float
    outer_width: float
    r80_radius: float


@dataclass(frozen=True)
class MachineTemplate:
    machine_id: str
    machine_name: str
    dual_section_mode: str
    guide_section_1: GuideSectionInstance
    guide_section_2: GuideSectionInstance
    assembly_side_bounds: tuple[float, float, float, float]
    assembly_side_centerline_x_values: tuple[float, ...]
    fixed_geometry: TemplateFixedGeometry


class DualGuideTemplateEngine:
    def __init__(self, machine: MachineConfig) -> None:
        if machine.guide_sections != 2:
            raise ValueError("DualGuideTemplateEngine requires guide_sections = 2.")
        if machine.machine_id not in {"triple_double_up_up_up", "triple_double_down_up_up"}:
            raise NotImplementedError(f"Dual-guide generation is not implemented for {machine.machine_id}.")
        self.machine = machine

    def build_template(self) -> MachineTemplate:
        if self.machine.machine_id == "triple_double_down_up_up":
            return MachineTemplate(
                machine_id=self.machine.machine_id,
                machine_name=self.machine.machine_name,
                dual_section_mode="synchronized",
                guide_section_1=GuideSectionInstance(
                    section_id="section_1",
                    anchor=TemplateAnchor(
                        left=3222.768,
                        right=3262.768,
                        bottom=-119.995,
                        top=-92.995,
                        slot_center_x=3242.768,
                    ),
                    fixed_spans=(99.0, 90.0),
                    side_bounds=(3360.205, 3549.205, -119.995, -92.995),
                    side_centerline_x_values=(3459.205,),
                    wheel_positions=("下",),
                ),
                guide_section_2=GuideSectionInstance(
                    section_id="section_2",
                    anchor=TemplateAnchor(
                        left=3221.337,
                        right=3261.337,
                        bottom=-200.688,
                        top=-173.688,
                        slot_center_x=3241.337,
                    ),
                    fixed_spans=(90.0, 180.0, 131.0),
                    side_bounds=(3332.707, 3733.707, -200.688, -173.688),
                    side_centerline_x_values=(3422.707, 3602.707),
                    wheel_positions=("上", "上"),
                ),
                assembly_side_bounds=(3389.454, 3979.454, -617.479, -590.479),
                assembly_side_centerline_x_values=(3488.454, 3668.454, 3848.454),
                fixed_geometry=TemplateFixedGeometry(
                    guide_length=590.0,
                    side_fixed_spans=(99.0, 90.0, 90.0, 180.0, 131.0),
                    outer_height=27.0,
                    outer_width=40.0,
                    r80_radius=self.machine.wheel_radius,
                ),
            )
        return MachineTemplate(
            machine_id=self.machine.machine_id,
            machine_name=self.machine.machine_name,
            dual_section_mode="synchronized",
            guide_section_1=GuideSectionInstance(
                section_id="section_1",
                anchor=TemplateAnchor(
                    left=3222.768,
                    right=3262.768,
                    bottom=-119.995,
                    top=-92.995,
                    slot_center_x=3242.768,
                ),
                fixed_spans=(99.0, 90.0),
                side_bounds=(3360.205, 3549.205, -119.995, -92.995),
                side_centerline_x_values=(3459.205,),
                wheel_positions=("上",),
            ),
            guide_section_2=GuideSectionInstance(
                section_id="section_2",
                anchor=TemplateAnchor(
                    left=3222.768,
                    right=3262.768,
                    bottom=-215.629,
                    top=-188.629,
                    slot_center_x=3242.768,
                ),
                fixed_spans=(90.0, 180.0, 131.0),
                side_bounds=(3369.205, 3770.205, -215.629, -188.629),
                side_centerline_x_values=(3459.205, 3639.205),
                wheel_positions=("上", "上"),
            ),
            assembly_side_bounds=(3377.938, 3967.938, -504.684, -477.684),
            assembly_side_centerline_x_values=(3476.938, 3656.938, 3836.938),
            fixed_geometry=TemplateFixedGeometry(
                guide_length=590.0,
                side_fixed_spans=(99.0, 90.0, 90.0, 180.0, 131.0),
                outer_height=27.0,
                outer_width=40.0,
                r80_radius=self.machine.wheel_radius,
            ),
        )

    def write_debug_release_and_report(
        self,
        profile: DualGuideProfile,
        parsed_spec: DualGuideParsedSpec,
        output_dir: Path,
        input_rule: dict[str, Any] | None = None,
        artifact_stem: str | None = None,
    ) -> dict[str, Any]:
        profile = self._with_machine_center_opening(profile)
        output_dir.mkdir(parents=True, exist_ok=True)
        filenames = _artifact_filenames(artifact_stem)
        debug_path = output_dir / filenames["debug_dxf"]
        release_path = output_dir / filenames["release_dxf"]
        release_candidate_path = output_dir / filenames["release_candidate_dxf"]
        report_path = output_dir / filenames["report_json"]
        dimension_audit_path = output_dir / filenames["dimension_audit_json"]
        release_path.unlink(missing_ok=True)
        release_candidate_path.unlink(missing_ok=True)
        debug_result = self.write_dxf(profile, debug_path, output_mode="debug")
        release_result = self.write_dxf(profile, release_candidate_path, output_mode="release")
        dimension_audit = write_dimension_definition_point_audit(
            release_candidate_path,
            profile,
            self.machine,
            dimension_audit_path,
        )
        line_type_audit = build_release_line_type_audit(
            release_candidate_path
        )
        input_rule_payload = input_rule or self._legacy_input_rule(
            profile,
            parsed_spec,
        )
        release_gate = (
            bool(input_rule_payload.get("input_rule_valid", True))
            and line_type_audit["release_allowed"]
            and dimension_audit["release_allowed"]
            and release_result["release_side_dimensions_match_report"]
            and self._lower_wheel_release_allowed(profile)
            and self._upper_wheel_release_allowed(profile)
            and release_result["synchronized"]
        )
        if release_gate:
            release_candidate_path.replace(release_path)
        else:
            release_candidate_path.unlink(missing_ok=True)
        report = self._build_report(
            profile,
            parsed_spec,
            debug_path,
            release_path,
            debug_result,
            release_result,
            input_rule=input_rule_payload,
            dimension_audit=dimension_audit,
            line_type_audit=line_type_audit,
            release_gate=release_gate,
        )
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if not release_gate:
            raise ValueError(
                "Dual-guide release gate failed; formal release.dxf was not written."
            )
        return {
            "debug_dxf": debug_path,
            "release_dxf": release_path,
            "report_json": report_path,
            "dimension_definition_point_audit_json": dimension_audit_path,
            "report": report,
        }

    def write_dxf(self, profile: DualGuideProfile, output_path: Path, output_mode: str) -> dict[str, Any]:
        import ezdxf

        profile = self._with_machine_center_opening(profile)
        if output_mode not in {"debug", "release"}:
            raise ValueError("output_mode must be debug or release.")
        required_profile = self._section_profile_payload(profile)["profile_type"]
        if required_profile not in self.machine.supported_section_profiles:
            raise ValueError(
                f"{self.machine.machine_id} does not support section profile {required_profile}."
            )
        template = self.build_template()
        doc = ezdxf.readfile(self.machine.section_template_path)
        modelspace = doc.modelspace()
        self._prepare_layers(doc, output_mode)
        self._classify_existing_entities(modelspace)

        section_results = []
        for section in (template.guide_section_1, template.guide_section_2):
            section_results.append(self._rebuild_section(doc, modelspace, profile, section, output_mode))
            self._update_side_view(modelspace, profile, section)
            self._update_section_dimensions(doc, modelspace, profile, section, section_results[-1]["geometry"])
        for section_result in section_results:
            geometry = section_result["geometry"]
            if not _has_bound_slot_width_dimension(modelspace, geometry):
                _add_slot_width_dimension(modelspace, profile, geometry)

        self._update_assembly_side_view(modelspace, profile)
        cavity_projection_audit = self._rebuild_dual_cavity_projection_lines(
            modelspace,
            profile,
        )
        removed_side_cavity_duplicates = _deduplicate_exact_side_cavity_lines(
            modelspace
        )
        self._update_side_dimensions(doc, modelspace, profile)
        self._bind_fixed_span_dimensions(modelspace)
        self._bind_r80_radius_dimensions(modelspace)
        self._bind_section_radius_dimensions(modelspace)
        if self._uses_down_up_lower_wheel_rule:
            self._add_lower_cavity_notch_opening_dimension(modelspace, profile)
            self._add_guide_length_dimension(modelspace)
        self._handle_product_reference_dimensions(doc, modelspace, profile, output_mode)
        self._assert_synchronized(section_results, profile)
        cleanup_summary = {}
        if output_mode == "release":
            cleanup_summary = self._remove_unexplained_release_side_dimensions(doc, modelspace)
        normalize_dimension_display_precision(doc, modelspace)
        dimension_precision_audit = build_dimension_precision_audit(
            modelspace
        )
        side_view_dimension_audit = _side_view_dimension_audit(
            modelspace,
            self.machine.wheel_radius,
        )
        r80_radius_dimension_audit = _r80_radius_dimension_audit(
            modelspace,
            self.machine.wheel_radius,
        )
        release_side_dimensions_match_report = _release_side_dimensions_match_report(modelspace, side_view_dimension_audit)
        duplicate_entity_audit = build_modelspace_parametric_duplicate_audit(
            modelspace
        )
        outer_relief_arc_audit = []
        for section_result in section_results:
            geometry = section_result["geometry"]
            outer_relief_arc_audit.append(
                build_four_outer_relief_arc_audit(
                    modelspace,
                    geometry.relief_radius,
                    left_x=geometry.left_x,
                    right_x=geometry.right_x,
                    base_y=geometry.base_y,
                    top_y=geometry.top_y,
                )
            )
        if output_mode == "release" and not (
            all(item["is_bound_to_wheel_crown"] for item in side_view_dimension_audit)
            and bool(r80_radius_dimension_audit)
            and all(item["is_bound_to_wheel_crown"] for item in r80_radius_dimension_audit)
            and all(
                item["matches_pre_grinding_shape"]
                for item in cavity_projection_audit
            )
            and cleanup_summary.get("no_legacy_4p29_dimension", False)
            and cleanup_summary.get("no_unexplained_1p80_dimension", False)
            and release_side_dimensions_match_report
            and self._lower_wheel_release_allowed(profile)
            and self._upper_wheel_release_allowed(profile)
            and duplicate_entity_audit["release_allowed"]
            and dimension_precision_audit["release_allowed"]
            and all(item["release_allowed"] for item in outer_relief_arc_audit)
        ):
            raise ValueError("Wheel side-view dimensions or notch safety checks failed; release not written.")
        if output_mode == "release":
            _simplify_release_layers(doc)
            self._strip_nonrelease_text_layers(modelspace)
        normalize_dimension_display_precision(doc, modelspace)
        doc.saveas(output_path)
        return {
            "machine_template": _machine_template_payload(template),
            "section_results": section_results,
            "side_view_dimension_audit": side_view_dimension_audit,
            "r80_radius_dimension_audit": r80_radius_dimension_audit,
            "cavity_projection_audit": cavity_projection_audit,
            "removed_side_cavity_duplicates": removed_side_cavity_duplicates,
            "parametric_duplicate_audit": duplicate_entity_audit,
            "dimension_precision_audit": dimension_precision_audit,
            "outer_relief_arc_audit": outer_relief_arc_audit,
            "release_cleanup": cleanup_summary,
            "release_side_dimensions_match_report": release_side_dimensions_match_report,
            "synchronized": True,
        }

    def _with_machine_center_opening(
        self,
        profile: DualGuideProfile,
    ) -> DualGuideProfile:
        """Keep geometry and display dimensions aligned with the machine template."""
        if (
            abs(
                profile.guide_spec.center_opening
                - self.machine.section_center_opening
            )
            <= 1e-9
        ):
            return profile
        return replace(
            profile,
            guide_spec=replace(
                profile.guide_spec,
                center_offset=self.machine.section_center_opening,
            ),
        )

    def _prepare_layers(self, doc: Any, output_mode: str) -> None:
        _ensure_layer(doc, "FIXED_TEMPLATE", color=7)
        _ensure_layer(doc, "PARAM_SLOT", color=1)
        _ensure_layer(doc, SECTION_CENTER_LAYER, color=1, linetype="CENTER")
        _ensure_layer(doc, DIMENSION_LAYER, color=3)
        _ensure_layer(doc, SIDE_TEMPLATE_LAYER, color=7)
        _ensure_layer(doc, SIDE_DERIVED_RELEASE_LAYER, color=3, linetype="Continuous")
        _ensure_layer(doc, SIDE_CAVITY_LAYER, color=3, linetype="DASHED")
        _ensure_layer(doc, SIDE_DEBUG_LAYER, color=3, linetype="DASHED")
        _ensure_layer(doc, SIDE_DIMENSION_LAYER, color=3)
        _ensure_layer(doc, SIDE_CENTER_LAYER, color=1, linetype="CENTER")
        if output_mode == "debug":
            _ensure_layer(doc, DEBUG_CONTROL_LAYER, color=6)
            _ensure_layer(doc, DEBUG_POINTS_LAYER, color=5)
            _ensure_layer(doc, PRODUCT_REFERENCE_LAYER, color=8)
        _ensure_dimension_text_style(doc)

    def _classify_existing_entities(self, modelspace: Any) -> None:
        for entity in modelspace:
            if entity.dxftype() == "DIMENSION":
                entity.dxf.layer = DIMENSION_LAYER
            elif _is_side_centerline(entity):
                entity.dxf.layer = SIDE_CENTER_LAYER
            elif _is_cross_section_centerline(entity):
                entity.dxf.layer = SECTION_CENTER_LAYER
            elif _is_side_cavity_line(entity):
                entity.dxf.layer = SIDE_CAVITY_LAYER
                entity.dxf.color = 256
                entity.dxf.linetype = "BYLAYER"
            elif _is_side_derived_line(entity):
                entity.dxf.layer = SIDE_DERIVED_RELEASE_LAYER
                entity.dxf.linetype = "BYLAYER"
            elif _is_side_template_entity(entity):
                entity.dxf.layer = SIDE_TEMPLATE_LAYER
            else:
                entity.dxf.layer = "FIXED_TEMPLATE"

    def _rebuild_section(
        self,
        doc: Any,
        modelspace: Any,
        profile: DualGuideProfile,
        section: GuideSectionInstance,
        output_mode: str,
    ) -> dict[str, Any]:
        for entity in list(modelspace):
            if self._is_section_param_entity(entity, section.anchor):
                modelspace.delete_entity(entity)
        if self._uses_down_up_lower_wheel_rule:
            slot_base_y = section.anchor.bottom + self.machine.section_slot_base_height
        else:
            slot_base_y = (
                section.anchor.top
                - self.machine.side_layout.block_fixed_top_gap
                - profile.guide_spec.guide_thickness
            )
        if isinstance(profile, TileSection) and profile.process_type == "block_to_tile":
            geometry = _add_block_to_tile_flat_arc_slot_entities(
                modelspace,
                profile,
                section.anchor,
            )
        elif isinstance(profile, TileSection) and profile.process_type == "block_to_bread":
            geometry = _add_down_up_bread_slot_entities(
                modelspace,
                profile,
                section.anchor,
            )
        elif isinstance(profile, TileSection):
            geometry = _add_param_slot_entities(modelspace, profile, anchor=section.anchor)
        else:
            geometry = _add_block_slot_entities(modelspace, profile, section.anchor, slot_base_y)
        if output_mode == "debug":
            _add_debug_entities(modelspace, geometry)
        return {
            "section_id": section.section_id,
            "slot_width": round(geometry.slot_width, 6),
            "guide_thickness": round(geometry.guide_thickness, 6),
            "slot_depth": round(geometry.slot_base_height, 6),
            "relief": profile.guide_spec.relief.relief_size,
            "section_profile": self._section_profile_payload(profile),
            "geometry": geometry,
        }

    @property
    def _uses_down_up_lower_wheel_rule(self) -> bool:
        return self.machine.machine_id == "triple_double_down_up_up"

    def _is_section_param_entity(self, entity: Any, anchor: TemplateAnchor) -> bool:
        if self._uses_down_up_lower_wheel_rule and entity.dxftype() == "ARC":
            center = entity.dxf.center
            return (
                anchor.left - 2.0 <= center.x <= anchor.right + 2.0
                and anchor.bottom - 50.0 <= center.y <= anchor.top + 20.0
                and float(entity.dxf.radius) < 50.0
            )
        return _is_block_template_param_entity(entity, anchor)

    def _update_section_dimensions(
        self,
        doc: Any,
        modelspace: Any,
        profile: DualGuideProfile,
        section: GuideSectionInstance,
        geometry: Any,
    ) -> None:
        dimensions = [
            entity
            for entity in modelspace.query("DIMENSION")
            if _dimension_near_cross_section(entity, section.anchor)
        ]
        slot_width_dim = _find_dual_block_slot_width_dimension(dimensions, geometry)
        thickness_dim = _find_block_thickness_dimension(dimensions, geometry)
        if thickness_dim is None:
            thickness_dim = _find_dual_guide_thickness_dimension(dimensions)
        slot_base_dim = _find_dual_slot_base_dimension(dimensions, geometry)
        opening_dim = _find_dual_opening_dimension(
            dimensions,
            geometry,
            excluded={slot_width_dim} if slot_width_dim is not None else set(),
        )
        relief_size_dim = _find_dimension_by_text(dimensions, "4-<>")
        relief_radius_dim = _find_dimension_by_text(dimensions, "2-<>")
        radius_dim = next(
            (
                dimension
                for dimension in dimensions
                if self._is_stale_cross_section_radius_dimension(dimension)
            ),
            None,
        )
        stale_radius_dimensions = (
            []
            if isinstance(profile, TileSection)
            else [
                dimension
                for dimension in dimensions
                if self._is_stale_cross_section_radius_dimension(dimension)
            ]
        )
        selected_dimensions = {
            dimension
            for dimension in (
                slot_width_dim,
                thickness_dim,
                slot_base_dim,
                opening_dim,
                relief_size_dim,
                relief_radius_dim,
                radius_dim if isinstance(profile, TileSection) else None,
            )
            if dimension is not None
        }
        stale_product_dimensions = [
            dimension
            for dimension in dimensions
            if dimension not in selected_dimensions
            and (
                self._is_stale_down_up_cross_section_dimension(dimension)
                or _is_unselected_small_process_dimension(
                    dimension,
                    profile,
                )
            )
        ]
        if slot_width_dim is not None:
            _update_block_slot_width_dimension(doc, slot_width_dim, profile.guide_spec.slot_width_dimension_text, geometry)
            _bind_slot_width_dimension_to_geometry(
                slot_width_dim,
                geometry,
            )
        else:
            slot_width_dim = _add_slot_width_dimension(
                modelspace,
                profile,
                geometry,
            )
        if thickness_dim is not None:
            _update_block_thickness_dimension(doc, thickness_dim, f"{profile.guide_spec.guide_thickness:.2f}", geometry)
            _bind_guide_thickness_dimension_to_geometry(
                thickness_dim,
                profile,
                geometry,
            )
        else:
            thickness_dim = _add_guide_thickness_dimension(
                modelspace,
                profile,
                geometry,
            )
        if slot_base_dim is not None:
            _clear_dimension_block_texts(doc, slot_base_dim)
            modelspace.delete_entity(slot_base_dim)
        if relief_size_dim is not None:
            _bind_relief_dimension(
                doc,
                relief_size_dim,
                geometry,
            )
        if relief_radius_dim is not None:
            _clear_dimension_block_texts(doc, relief_radius_dim)
            modelspace.delete_entity(relief_radius_dim)
        if isinstance(profile, TileSection) and radius_dim is not None:
            _update_down_up_flat_arc_r_dimension(
                doc,
                radius_dim,
                profile.forming_spec.R_form,
                geometry,
                upper_arc=profile.arc_side == "upper",
            )
        if opening_dim is not None:
            _update_down_up_flat_arc_opening_dimension(
                doc,
                opening_dim,
                geometry,
            )
        else:
            _add_center_opening_dimension(
                modelspace,
                geometry,
            )
        for dimension in [*stale_radius_dimensions, *stale_product_dimensions]:
            if not hasattr(dimension, "dxf"):
                continue
            _clear_dimension_block_texts(doc, dimension)
            modelspace.delete_entity(dimension)

    def _is_stale_cross_section_radius_dimension(self, dimension: Any) -> bool:
        if not self._uses_down_up_lower_wheel_rule:
            return False
        if not (dimension.dxf.hasattr("defpoint") and dimension.dxf.hasattr("defpoint4")):
            return False
        try:
            measurement = float(dimension.get_measurement())
        except Exception:
            return False
        return 5.0 < measurement < 50.0

    def _is_stale_down_up_cross_section_dimension(self, dimension: Any) -> bool:
        if not self._uses_down_up_lower_wheel_rule:
            return False
        text = dimension.dxf.text if dimension.dxf.hasattr("text") else ""
        if text:
            return False
        try:
            measurement = float(dimension.get_measurement())
        except Exception:
            return False
        return 2.0 <= measurement <= 3.0

    def _update_side_view(self, modelspace: Any, profile: DualGuideProfile, section: GuideSectionInstance) -> None:
        if self._uses_down_up_lower_wheel_rule:
            self._update_down_up_side_view(
                modelspace,
                profile,
                section.side_bounds,
                section.side_centerline_x_values,
                section.wheel_positions,
            )
            return
        derived = self._side_derived(profile, section)
        x_min, x_max, bottom_y, top_y = section.side_bounds
        self._update_side_lines(modelspace, x_min, x_max, bottom_y, top_y, derived)
        self._update_side_r80_arcs(
            modelspace,
            section.side_centerline_x_values,
            top_y,
            derived["side_clearance_height"],
            profile,
        )

    def _update_assembly_side_view(self, modelspace: Any, profile: DualGuideProfile) -> None:
        template = self.build_template()
        if self._uses_down_up_lower_wheel_rule:
            self._update_down_up_side_view(
                modelspace,
                profile,
                template.assembly_side_bounds,
                template.assembly_side_centerline_x_values,
                self.machine.wheel_positions,
            )
            return
        derived = self._side_derived(profile, self.build_template().guide_section_1)
        x_min, x_max, bottom_y, top_y = template.assembly_side_bounds
        self._update_side_lines(modelspace, x_min, x_max, bottom_y, top_y, derived)
        self._update_side_r80_arcs(
            modelspace,
            template.assembly_side_centerline_x_values,
            top_y,
            derived["side_clearance_height"],
            profile,
        )

    def _rebuild_dual_cavity_projection_lines(
        self,
        modelspace: Any,
        profile: DualGuideProfile,
    ) -> list[dict[str, Any]]:
        projection = derive_cavity_projection_profile(
            profile,
            profile.guide_spec.guide_thickness,
        )
        template = self.build_template()
        views = (
            (
                template.guide_section_1.side_bounds,
                template.guide_section_1.side_centerline_x_values,
                template.guide_section_1.wheel_positions,
            ),
            (
                template.guide_section_2.side_bounds,
                template.guide_section_2.side_centerline_x_values,
                template.guide_section_2.wheel_positions,
            ),
            (
                template.assembly_side_bounds,
                template.assembly_side_centerline_x_values,
                self.machine.wheel_positions,
            ),
        )
        audit = []
        for bounds, center_x_values, wheel_positions in views:
            x_min, x_max, bottom_y, top_y = bounds
            base_y = (
                bottom_y + self.machine.section_slot_base_height
                if self._uses_down_up_lower_wheel_rule
                else top_y
                - self.machine.side_layout.block_fixed_top_gap
                - profile.guide_spec.guide_thickness
            )
            _delete_side_cavity_lines_in_bounds(
                modelspace,
                bounds,
            )
            wheel_arcs = [
                arc
                for arc in modelspace.query("ARC")
                if arc.dxf.layer == SIDE_TEMPLATE_LAYER
                and abs(
                    float(arc.dxf.radius) - self.machine.wheel_radius
                )
                <= 0.001
                and x_min - 0.01
                <= float(arc.dxf.center.x)
                <= x_max + 0.01
            ]
            for offset, _role in zip(
                projection.offsets,
                projection.surface_roles,
            ):
                projected_y = base_y + offset
                gaps = [
                    gap
                    for arc in wheel_arcs
                    if (gap := horizontal_arc_gap(arc, projected_y))
                    is not None
                ]
                for start_x, end_x in _subtract_horizontal_gaps(
                    x_min,
                    x_max,
                    gaps,
                ):
                    modelspace.add_line(
                        (start_x, projected_y),
                        (end_x, projected_y),
                        dxfattribs={
                            "layer": SIDE_CAVITY_LAYER,
                            "color": 256,
                            "linetype": "BYLAYER",
                        },
                    )
            expected_levels = [
                round(base_y + offset, 6)
                for offset in projection.offsets
            ]
            observed_levels = sorted(
                {
                    round(float(entity.dxf.start.y), 6)
                    for entity in modelspace.query("LINE")
                    if entity.dxf.layer == SIDE_CAVITY_LAYER
                    and abs(
                        float(entity.dxf.start.y)
                        - float(entity.dxf.end.y)
                    )
                    <= 0.001
                    and x_min - 0.001
                    <= (
                        float(entity.dxf.start.x)
                        + float(entity.dxf.end.x)
                    )
                    / 2.0
                    <= x_max + 0.001
                    and any(
                        abs(
                            float(entity.dxf.start.y) - expected_y
                        )
                        <= 0.001
                        for expected_y in expected_levels
                    )
                }
            )
            audit.append(
                {
                    "bounds": [round(value, 3) for value in bounds],
                    "pre_grinding_shape": projection.pre_grinding_shape,
                    "expected_line_count": projection.line_count,
                    "line_levels": expected_levels,
                    "observed_line_levels": observed_levels,
                    "matches_pre_grinding_shape": observed_levels
                    == sorted(expected_levels),
                    "surface_roles": list(projection.surface_roles),
                }
            )
        return audit

    def _update_down_up_side_view(
        self,
        modelspace: Any,
        profile: DualGuideProfile,
        bounds: tuple[float, float, float, float],
        center_x_values: tuple[float, ...],
        wheel_positions: tuple[str, ...],
    ) -> None:
        x_min, x_max, bottom_y, top_y = bounds
        base_y = bottom_y + self.machine.section_slot_base_height
        slot_top_y = base_y + profile.guide_spec.guide_thickness
        old_internal_ys = _horizontal_internal_y_values(modelspace, x_min, x_max, bottom_y, top_y)
        old_base_y = _nearest_value(old_internal_ys, bottom_y + self.machine.section_slot_base_height)
        old_top_y = _nearest_value(old_internal_ys, bottom_y + self.machine.section_slot_base_height + 2.4)
        lower_centers = tuple(
            center_x for center_x, position in zip(center_x_values, wheel_positions) if position == "下"
        )
        lower_opening = self._lower_wheel_safety_payload(profile)["lower_cavity_notch_opening"]

        for entity in modelspace.query("LINE"):
            if abs(float(entity.dxf.start.y) - float(entity.dxf.end.y)) > 0.001:
                continue
            y = float(entity.dxf.start.y)
            cx = (float(entity.dxf.start.x) + float(entity.dxf.end.x)) / 2.0
            if not (x_min - 0.001 <= cx <= x_max + 0.001):
                continue
            if old_base_y is not None and abs(y - old_base_y) <= 0.8:
                entity.dxf.start = (entity.dxf.start.x, base_y, entity.dxf.start.z)
                entity.dxf.end = (entity.dxf.end.x, base_y, entity.dxf.end.z)
                entity.dxf.layer = SIDE_CAVITY_LAYER
                entity.dxf.color = 256
                entity.dxf.linetype = "BYLAYER"
                for center_x in lower_centers:
                    _split_lower_cavity_line(entity, center_x, lower_opening)
            elif old_top_y is not None and abs(y - old_top_y) <= 0.8:
                entity.dxf.start = (entity.dxf.start.x, slot_top_y, entity.dxf.start.z)
                entity.dxf.end = (entity.dxf.end.x, slot_top_y, entity.dxf.end.z)
                entity.dxf.layer = SIDE_CAVITY_LAYER
                entity.dxf.color = 256
                entity.dxf.linetype = "BYLAYER"
            elif abs(y - bottom_y) <= 0.001:
                for center_x in lower_centers:
                    _replace_lower_surface_connector(
                        entity,
                        center_x,
                        bottom_y,
                        self._lower_wheel_center_y(profile, bottom_y),
                        self.machine.wheel_radius,
                    )

        for center_x, position in zip(center_x_values, wheel_positions):
            if position == "下":
                self._update_lower_r80_arc(modelspace, center_x, bottom_y, profile)
            else:
                upper_arc = _find_r80_arc_for_center(
                    modelspace,
                    center_x,
                    top_y,
                    self.machine.wheel_radius,
                )
                if upper_arc is not None:
                    upper_arc.dxf.layer = SIDE_TEMPLATE_LAYER

    def _lower_wheel_opening(self, profile: DualGuideProfile) -> float:
        radius = self.machine.wheel_radius
        natural_depth = self._process_thickness(profile) * WHEEL_CUT_IN_RATIO
        natural_opening = 2.0 * sqrt(max(0.0, radius * radius - (radius - natural_depth) ** 2))
        opening_limit = max(self._process_length(profile) - 0.2, 0.1)
        return min(natural_opening, opening_limit)

    def _lower_wheel_safety_payload(self, profile: DualGuideProfile) -> dict[str, Any]:
        return self._wheel_notch_safety_payload(profile, wheel_side="lower")

    def _upper_wheel_safety_payload(self, profile: DualGuideProfile) -> dict[str, Any]:
        return self._wheel_notch_safety_payload(profile, wheel_side="upper")

    def _wheel_notch_safety_payload(
        self,
        profile: DualGuideProfile,
        *,
        wheel_side: str,
    ) -> dict[str, Any]:
        radius = self.machine.wheel_radius
        product_length = self._process_length(profile)
        natural_cut_in_depth = self._process_thickness(profile) * WHEEL_CUT_IN_RATIO
        natural_opening = 2.0 * sqrt(
            max(0.0, radius * radius - (radius - natural_cut_in_depth) ** 2)
        )
        opening_limit = max(product_length - 0.2, 0.1)
        cavity_notch_opening = min(natural_opening, opening_limit)
        half_opening = cavity_notch_opening / 2.0
        effective_cut_in_depth = radius - sqrt(max(0.0, radius * radius - half_opening * half_opening))
        payload = {
            "product_length": product_length,
            "natural_cut_in_formula": (
                "preform_thickness_mid * 0.6"
                if isinstance(profile, TileSection)
                else "thickness * 0.6"
            ),
            "natural_cut_in_depth": round(natural_cut_in_depth, 6),
            "natural_opening": round(natural_opening, 6),
            "opening_limit_formula": "product_length - 0.2",
            "opening_limit": round(opening_limit, 6),
            "cavity_notch_opening": round(cavity_notch_opening, 6),
            "effective_cut_in_depth": round(effective_cut_in_depth, 6),
            "cavity_notch_opening_less_than_product_length": cavity_notch_opening < product_length,
            "cavity_notch_opening_within_limit": cavity_notch_opening <= opening_limit,
        }
        if wheel_side == "lower":
            lower_wheel_center_y = (
                self.machine.side_layout.lower_y
                + self.machine.section_slot_base_height
                + effective_cut_in_depth
                - radius
            )
            payload.update(
                {
                    "lower_cavity_notch_opening": payload["cavity_notch_opening"],
                    "lower_wheel_center_y": round(lower_wheel_center_y, 6),
                    "lower_cavity_notch_opening_less_than_product_length": payload[
                        "cavity_notch_opening_less_than_product_length"
                    ],
                    "lower_cavity_notch_opening_within_limit": payload[
                        "cavity_notch_opening_within_limit"
                    ],
                }
            )
        else:
            payload.update(
                {
                    "upper_cavity_notch_opening": payload["cavity_notch_opening"],
                    "upper_cavity_notch_opening_less_than_product_length": payload[
                        "cavity_notch_opening_less_than_product_length"
                    ],
                    "upper_cavity_notch_opening_within_limit": payload[
                        "cavity_notch_opening_within_limit"
                    ],
                }
            )
        return payload

    def _lower_wheel_release_allowed(self, profile: DualGuideProfile) -> bool:
        if "下" not in self.machine.wheel_positions:
            return True
        safety = self._lower_wheel_safety_payload(profile)
        return (
            safety["lower_cavity_notch_opening_less_than_product_length"]
            and safety["lower_cavity_notch_opening_within_limit"]
        )

    def _upper_wheel_release_allowed(self, profile: DualGuideProfile) -> bool:
        if "上" not in self.machine.wheel_positions:
            return True
        safety = self._upper_wheel_safety_payload(profile)
        return (
            safety["upper_cavity_notch_opening_less_than_product_length"]
            and safety["upper_cavity_notch_opening_within_limit"]
        )

    def _lower_wheel_effective_cut_depth(self, profile: DualGuideProfile) -> float:
        return self._lower_wheel_safety_payload(profile)["effective_cut_in_depth"]

    def _lower_wheel_center_y(self, profile: DualGuideProfile, bottom_y: float) -> float:
        return (
            bottom_y
            + self.machine.section_slot_base_height
            + self._lower_wheel_effective_cut_depth(profile)
            - self.machine.wheel_radius
        )

    def _update_lower_r80_arc(self, modelspace: Any, center_x: float, bottom_y: float, profile: DualGuideProfile) -> None:
        arc = _find_lower_r80_arc_for_center(
            modelspace,
            center_x,
            bottom_y,
            self.machine.wheel_radius,
        )
        if arc is None:
            return
        center_y = self._lower_wheel_center_y(profile, bottom_y)
        half_chord = sqrt(max(0.0, arc.dxf.radius * arc.dxf.radius - (bottom_y - center_y) ** 2))
        arc.dxf.center = (center_x, center_y, arc.dxf.center.z)
        arc.dxf.radius = self.machine.wheel_radius
        arc.dxf.start_angle = _angle_deg(half_chord, bottom_y - center_y)
        arc.dxf.end_angle = _angle_deg(-half_chord, bottom_y - center_y)
        arc.dxf.layer = SIDE_TEMPLATE_LAYER

    def _side_derived(self, profile: DualGuideProfile, section: GuideSectionInstance) -> dict[str, float]:
        fixed_top_gap = self.machine.side_layout.block_fixed_top_gap
        if fixed_top_gap is None:
            raise ValueError(
                f"Machine '{self.machine.machine_id}' requires block_fixed_top_gap."
            )
        side_projected_slot_height = (
            profile.guide_spec.outer_height
            - fixed_top_gap
            - profile.guide_spec.guide_thickness
        )
        upper_cut_in = self._upper_wheel_safety_payload(profile)["effective_cut_in_depth"]
        return {
            "side_projected_slot_height": round(side_projected_slot_height, 6),
            "side_clearance_height": round(fixed_top_gap, 6),
            "working_depth": round(upper_cut_in, 6),
        }

    def _update_side_lines(
        self,
        modelspace: Any,
        x_min: float,
        x_max: float,
        bottom_y: float,
        top_y: float,
        derived: dict[str, float],
    ) -> None:
        projected_y = bottom_y + derived["side_projected_slot_height"]
        working_y = top_y - derived["side_clearance_height"]
        internal_ys = []
        for entity in modelspace.query("LINE"):
            if abs(entity.dxf.start.y - entity.dxf.end.y) > 0.001:
                continue
            y = float(entity.dxf.start.y)
            cx = (float(entity.dxf.start.x) + float(entity.dxf.end.x)) / 2.0
            if x_min - 0.001 <= cx <= x_max + 0.001 and bottom_y + 1.0 < y < top_y - 1.0:
                internal_ys.append(y)
        unique_ys = sorted({round(y, 3) for y in internal_ys}, reverse=True)
        if not unique_ys:
            return
        old_working_y = unique_ys[0]
        old_projected_y = unique_ys[-1]
        for entity in modelspace.query("LINE"):
            if abs(entity.dxf.start.y - entity.dxf.end.y) > 0.001:
                continue
            y = round(float(entity.dxf.start.y), 3)
            cx = (float(entity.dxf.start.x) + float(entity.dxf.end.x)) / 2.0
            if not (x_min - 0.001 <= cx <= x_max + 0.001):
                continue
            if abs(y - old_working_y) <= 0.01:
                entity.dxf.start = (entity.dxf.start.x, working_y, entity.dxf.start.z)
                entity.dxf.end = (entity.dxf.end.x, working_y, entity.dxf.end.z)
                entity.dxf.layer = SIDE_CAVITY_LAYER
                entity.dxf.color = 256
                entity.dxf.linetype = "BYLAYER"
            elif abs(y - old_projected_y) <= 0.01:
                entity.dxf.start = (entity.dxf.start.x, projected_y, entity.dxf.start.z)
                entity.dxf.end = (entity.dxf.end.x, projected_y, entity.dxf.end.z)
                entity.dxf.layer = SIDE_CAVITY_LAYER
                entity.dxf.color = 256
                entity.dxf.linetype = "BYLAYER"

    def _update_side_r80_arcs(
        self,
        modelspace: Any,
        center_x_values: tuple[float, ...],
        top_y: float,
        side_clearance_height: float,
        profile: DualGuideProfile,
    ) -> None:
        safety = self._upper_wheel_safety_payload(profile)
        radius = self.machine.wheel_radius
        effective_depth = safety["effective_cut_in_depth"]
        cavity_half_chord = safety["upper_cavity_notch_opening"] / 2.0
        for center_x in center_x_values:
            old_arc = _find_r80_arc_for_center(
                modelspace,
                center_x,
                top_y,
                radius,
            )
            if old_arc is None:
                continue
            cavity_top_y = top_y - side_clearance_height
            old_outer_half_chord = sqrt(
                max(0.0, float(old_arc.dxf.radius) ** 2 - (top_y - float(old_arc.dxf.center.y)) ** 2)
            )
            old_cavity_half_chord = sqrt(
                max(
                    0.0,
                    float(old_arc.dxf.radius) ** 2
                    - (cavity_top_y - float(old_arc.dxf.center.y)) ** 2,
                )
            )
            center_y = cavity_top_y + radius - effective_depth
            outer_half_chord = sqrt(
                max(0.0, radius * radius - (top_y - center_y) ** 2)
            )
            old_arc.dxf.center = (center_x, center_y, old_arc.dxf.center.z)
            old_arc.dxf.radius = radius
            old_arc.dxf.start_angle = _angle_deg(-outer_half_chord, top_y - center_y)
            old_arc.dxf.end_angle = _angle_deg(outer_half_chord, top_y - center_y)
            old_arc.dxf.layer = SIDE_TEMPLATE_LAYER
            self._update_top_surface_connectors(
                modelspace,
                center_x,
                top_y,
                old_outer_half_chord,
                outer_half_chord,
            )
            self._update_top_surface_connectors(
                modelspace,
                center_x,
                cavity_top_y,
                old_cavity_half_chord,
                cavity_half_chord,
            )

    def _update_top_surface_connectors(
        self,
        modelspace: Any,
        center_x: float,
        top_y: float,
        old_half_chord: float,
        new_half_chord: float,
    ) -> None:
        replacements = (
            (center_x - old_half_chord, center_x - new_half_chord),
            (center_x + old_half_chord, center_x + new_half_chord),
        )
        for entity in modelspace.query("LINE"):
            if abs(entity.dxf.start.y - entity.dxf.end.y) > 0.001:
                continue
            if abs(float(entity.dxf.start.y) - top_y) > 0.001:
                continue
            for attr in ("start", "end"):
                point = getattr(entity.dxf, attr)
                for old_x, new_x in replacements:
                    if abs(float(point.x) - old_x) <= 0.05:
                        entity.dxf.set(attr, (new_x, point.y, point.z))

    def _update_side_dimensions(self, doc: Any, modelspace: Any, profile: DualGuideProfile) -> None:
        for dimension in modelspace.query("DIMENSION"):
            try:
                measurement = float(dimension.get_measurement())
            except Exception:
                continue
            if 0.1 <= measurement <= 20.0:
                crown = _nearest_r80_crown_for_dimension(
                    modelspace,
                    dimension,
                    self.machine.wheel_radius,
                )
                if crown is not None:
                    crown_x, crown_y, surface_y = crown
                    if abs(measurement - 1.2) <= 0.05:
                        arc = _r80_arc_at_crown(
                            modelspace,
                            crown_x,
                            crown_y,
                            self.machine.wheel_radius,
                        )
                        if arc is not None:
                            is_upper_wheel = crown_y < float(
                                arc.dxf.center.y
                            )
                            measured = (
                                self._upper_wheel_safety_payload(profile)[
                                    "effective_cut_in_depth"
                                ]
                                if is_upper_wheel
                                else self._lower_wheel_safety_payload(profile)[
                                    "effective_cut_in_depth"
                                ]
                            )
                            surface_y = (
                                crown_y + measured
                                if is_upper_wheel
                                else crown_y - measured
                            )
                    measured = abs(surface_y - crown_y)
                    _bind_dimension_to_wheel_crown(dimension, crown_x, crown_y, surface_y)
                    _set_dimension_actual_measurement(dimension, measured)
                    dimension.dxf.text = f"{measured:.2f}"
                    try:
                        dimension.render()
                    except Exception:
                        # Some historical template dimensions have incomplete
                        # association data; their definition points and block
                        # text are still updated deterministically below.
                        pass
                    _set_dimension_block_text(doc, dimension, dimension.dxf.text)
                    continue

    def _strip_nonrelease_text_layers(self, modelspace: Any) -> None:
        for entity in modelspace:
            if entity.dxftype() in {"TEXT", "MTEXT", "LWPOLYLINE", "CIRCLE", "INSERT", "ACAD_PROXY_ENTITY"}:
                if entity.dxf.layer not in {
                    "FIXED_TEMPLATE",
                    "PARAM_SLOT",
                    DIMENSION_LAYER,
                    SIDE_TEMPLATE_LAYER,
                    SIDE_DERIVED_RELEASE_LAYER,
                    SIDE_CAVITY_LAYER,
                    SIDE_DIMENSION_LAYER,
                    SIDE_CENTER_LAYER,
                    SECTION_CENTER_LAYER,
                }:
                    entity.dxf.layer = "FIXED_TEMPLATE"

    def _handle_product_reference_dimensions(
        self,
        doc: Any,
        modelspace: Any,
        profile: DualGuideProfile,
        output_mode: str,
    ) -> None:
        product_thickness = self._process_thickness(profile)
        product_label = _format_compact_decimal(product_thickness)
        for dimension in list(modelspace.query("DIMENSION")):
            text = dimension.dxf.text if dimension.dxf.hasattr("text") else ""
            block_texts = _dimension_block_texts(doc, dimension)
            try:
                measurement = float(dimension.get_measurement())
            except Exception:
                continue
            if (
                text != product_label
                and not any(
                    _text_matches_number(value, product_thickness)
                    for value in block_texts
                )
            ) or abs(measurement - product_thickness) > 0.001:
                continue
            if not _dimension_is_in_dual_cross_section(dimension):
                continue
            if output_mode == "release":
                modelspace.delete_entity(dimension)
            else:
                dimension.dxf.layer = PRODUCT_REFERENCE_LAYER
                dimension.dxf.text = f"产品厚度 {product_label}（参考）"
                _set_dimension_block_text(doc, dimension, dimension.dxf.text)

    def _add_lower_cavity_notch_opening_dimension(
        self,
        modelspace: Any,
        profile: DualGuideProfile,
    ) -> None:
        template = self.build_template()
        center_x = template.assembly_side_centerline_x_values[0]
        base_y = (
            template.assembly_side_bounds[2]
            + self.machine.section_slot_base_height
        )
        opening = self._lower_wheel_safety_payload(profile)[
            "lower_cavity_notch_opening"
        ]
        left = center_x - opening / 2.0
        right = center_x + opening / 2.0
        dimension = add_linear_dimension_with_text(
            modelspace,
            (left, base_y),
            (right, base_y),
            (left, base_y - 8.0),
            (right, base_y - 8.0),
            _format_compact_decimal(opening),
            (center_x, base_y - 9.0),
            layer=DIMENSION_LAYER,
            include_fallback=False,
            include_native=True,
            dimstyle=TEMPLATE_DIMENSION_STYLE,
            dimension_text_height=TEMPLATE_DIMENSION_TEXT_HEIGHT,
        )
        if dimension is not None:
            dimension.dxf.defpoint2 = (left, base_y, 0.0)
            dimension.dxf.defpoint3 = (right, base_y, 0.0)
            _set_dimension_actual_measurement(dimension, opening)

    def _add_guide_length_dimension(self, modelspace: Any) -> None:
        template = self.build_template()
        left, right, _, top = template.assembly_side_bounds
        dimension = add_linear_dimension_with_text(
            modelspace,
            (left, top),
            (right, top),
            (left, top + 38.0),
            (right, top + 38.0),
            _format_compact_decimal(self.machine.guide_length),
            ((left + right) / 2.0, top + 39.0),
            layer=DIMENSION_LAYER,
            include_fallback=False,
            include_native=True,
            dimstyle=TEMPLATE_DIMENSION_STYLE,
            dimension_text_height=TEMPLATE_DIMENSION_TEXT_HEIGHT,
        )
        if dimension is not None:
            dimension.dxf.defpoint2 = (left, top, 0.0)
            dimension.dxf.defpoint3 = (right, top, 0.0)
            _set_dimension_actual_measurement(
                dimension,
                self.machine.guide_length,
            )

    def _bind_fixed_span_dimensions(self, modelspace: Any) -> None:
        template = self.build_template()
        top_values = (
            template.guide_section_1.side_bounds[3],
            template.guide_section_2.side_bounds[3],
            template.assembly_side_bounds[3],
        )
        for dimension in modelspace.query("DIMENSION"):
            if not (
                dimension.dxf.hasattr("defpoint2")
                and dimension.dxf.hasattr("defpoint3")
            ):
                continue
            try:
                measurement = float(dimension.get_measurement())
            except Exception:
                continue
            if not any(
                abs(measurement - value) <= 0.01
                for value in (99.0, 90.0, 180.0, 131.0)
            ):
                continue
            p2 = dimension.dxf.defpoint2
            p3 = dimension.dxf.defpoint3
            target_y = min(
                top_values,
                key=lambda value: abs(
                    (float(p2.y) + float(p3.y)) / 2.0 - value
                ),
            )
            dimension.dxf.defpoint2 = (p2.x, target_y, p2.z)
            dimension.dxf.defpoint3 = (p3.x, target_y, p3.z)
            _set_dimension_actual_measurement(dimension, measurement)

    def _bind_r80_radius_dimensions(self, modelspace: Any) -> None:
        radius = self.machine.wheel_radius
        arcs = [
            entity
            for entity in modelspace.query("ARC")
            if abs(float(entity.dxf.radius) - radius) <= 0.001
            and entity.dxf.layer == SIDE_TEMPLATE_LAYER
        ]
        for dimension in modelspace.query("DIMENSION"):
            if not (
                dimension.dxf.hasattr("defpoint")
                and dimension.dxf.hasattr("defpoint4")
            ):
                continue
            try:
                measurement = float(dimension.get_measurement())
            except Exception:
                continue
            if not (
                abs(measurement - DEFAULT_WHEEL_RADIUS) <= 0.01
                or abs(measurement - radius) <= 0.01
            ):
                continue
            old_center = dimension.dxf.defpoint
            arc = min(
                arcs,
                key=lambda entity: hypot(
                    float(entity.dxf.center.x) - float(old_center.x),
                    float(entity.dxf.center.y) - float(old_center.y),
                ),
            )
            center = arc.dxf.center
            crown_y = _r80_expected_crown_y(arc)
            dimension.dxf.defpoint = (
                center.x,
                center.y,
                old_center.z,
            )
            dimension.dxf.defpoint4 = (
                float(center.x),
                crown_y,
                old_center.z,
            )
            dimension.dxf.text = f"R{radius:.2f}"
            _set_dimension_actual_measurement(dimension, radius)
            try:
                dimension.render()
            except Exception:
                pass

    def _bind_section_radius_dimensions(self, modelspace: Any) -> None:
        """Bind R-form dimensions to an actual regenerated slot-arc endpoint."""
        arcs = [
            entity
            for entity in modelspace.query("ARC")
            if entity.dxf.layer == "PARAM_SLOT" and float(entity.dxf.radius) > 2.0
        ]
        for dimension in modelspace.query("DIMENSION"):
            if not (
                dimension.dxf.hasattr("defpoint")
                and dimension.dxf.hasattr("defpoint4")
            ):
                continue
            try:
                measurement = float(dimension.get_measurement())
            except Exception:
                continue
            if not 2.0 < measurement < self.machine.wheel_radius:
                continue
            candidates = [
                arc for arc in arcs if abs(float(arc.dxf.radius) - measurement) <= 0.01
            ]
            if not candidates:
                continue
            old_center = dimension.dxf.defpoint
            arc = min(
                candidates,
                key=lambda entity: hypot(
                    float(entity.dxf.center.x) - float(old_center.x),
                    float(entity.dxf.center.y) - float(old_center.y),
                ),
            )
            endpoint = arc.start_point
            dimension.dxf.defpoint = (
                float(arc.dxf.center.x),
                float(arc.dxf.center.y),
                old_center.z,
            )
            dimension.dxf.defpoint4 = (float(endpoint.x), float(endpoint.y), endpoint.z)
            _set_dimension_actual_measurement(dimension, measurement)

    def _remove_unexplained_release_side_dimensions(self, doc: Any, modelspace: Any) -> dict[str, Any]:
        removed = []
        for dimension in list(modelspace.query("DIMENSION")):
            text = dimension.dxf.text if dimension.dxf.hasattr("text") else ""
            block_texts = _dimension_block_texts(doc, dimension)
            if text == "4.29" or any(value == "4.29" for value in block_texts):
                removed.append(
                    {
                        "handle": dimension.dxf.handle,
                        "text": text,
                        "measurement": round(float(dimension.get_measurement()), 3),
                        "block_texts": block_texts,
                    }
                )
                _clear_dimension_block_texts(doc, dimension)
                modelspace.delete_entity(dimension)
        residuals = _release_legacy_side_dimension_residuals(doc, modelspace)
        return {
            "removed_unexplained_side_dimensions": removed,
            "no_legacy_4p29_dimension": not any(item["text"] == "4.29" for item in residuals),
            # 1.80 can be a valid 0.6 × thickness result. It is validated by
            # its definition points instead of being removed by text value.
            "no_unexplained_1p80_dimension": True,
            "residual_legacy_side_dimensions": residuals,
        }

    def _assert_synchronized(self, section_results: list[dict[str, Any]], profile: DualGuideProfile) -> None:
        expected = {
            "slot_width": round(profile.guide_spec.guide_slot_width, 6),
            "guide_thickness": round(profile.guide_spec.guide_thickness, 6),
            "relief": profile.guide_spec.relief.relief_size,
        }
        for result in section_results:
            for key, value in expected.items():
                if result[key] != value:
                    raise ValueError(f"{result['section_id']} is not synchronized for {key}: {result[key]} != {value}")
            if result["section_profile"] != self._section_profile_payload(profile):
                raise ValueError(f"{result['section_id']} section profile is not synchronized.")

    def _section_profile_payload(self, profile: DualGuideProfile) -> dict[str, Any]:
        if isinstance(profile, TileSection):
            if profile.process_type in {"block_to_tile", "block_to_bread"}:
                return {
                    "profile_type": "bread_big_r_block_preform",
                    "bottom_surface_type": (
                        "R_form_arc" if profile.arc_side == "lower" else "plane"
                    ),
                    "top_surface_type": (
                        "R_form_arc" if profile.arc_side == "upper" else "plane"
                    ),
                    "bottom_radius": (
                        profile.forming_spec.R_form
                        if profile.arc_side == "lower"
                        else None
                    ),
                    "top_radius": (
                        profile.forming_spec.R_form
                        if profile.arc_side == "upper"
                        else None
                    ),
                }
            return {
                "profile_type": "same_r_tile",
                "bottom_surface_type": "R_form_arc",
                "top_surface_type": "R_form_arc",
                "bottom_radius": profile.forming_spec.R_form,
                "top_radius": profile.forming_spec.R_form,
            }
        profile = self.machine.section_profile
        return {
            "profile_type": profile.profile_type,
            "bottom_surface_type": profile.bottom_surface_type,
            "top_surface_type": profile.top_surface_type,
            "bottom_radius": profile.bottom_radius,
            "top_radius": profile.top_radius,
        }

    def _build_report(
        self,
        profile: DualGuideProfile,
        parsed_spec: DualGuideParsedSpec,
        debug_path: Path,
        release_path: Path,
        debug_result: dict[str, Any],
        release_result: dict[str, Any],
        input_rule: dict[str, Any] | None = None,
        dimension_audit: dict[str, Any] | None = None,
        line_type_audit: dict[str, Any] | None = None,
        release_gate: bool | None = None,
    ) -> dict[str, Any]:
        template = self.build_template()
        release_sections = release_result["section_results"]
        side_view_dimension_audit = release_result["side_view_dimension_audit"]
        r80_radius_dimension_audit = release_result[
            "r80_radius_dimension_audit"
        ]
        cavity_projection_audit = release_result[
            "cavity_projection_audit"
        ]
        release_cleanup = release_result["release_cleanup"]
        lower_wheel_safety = self._lower_wheel_safety_payload(profile)
        upper_wheel_safety = self._upper_wheel_safety_payload(profile)
        input_rule = input_rule or self._legacy_input_rule(
            profile,
            parsed_spec,
        )
        dimension_audit = dimension_audit or {
            "release_allowed": False,
            "all_dimensions_bound_to_geometry": False,
            "all_required_roles_pass": False,
        }
        line_type_audit = line_type_audit or {
            "release_allowed": False,
        }
        release_gate = bool(release_gate)
        return {
            "machine_id": self.machine.machine_id,
            "machine_name": self.machine.machine_name,
            "guide_length": self.machine.guide_length,
            "guide_sections": self.machine.guide_sections,
            "dual_section_mode": "synchronized",
            "debug_dxf": str(debug_path),
            "release_dxf": str(release_path),
            "product": self._product_payload(parsed_spec),
            "input_rule": input_rule,
            "finished_product_shape": input_rule.get(
                "finished_product_shape"
            ),
            "pre_grinding_shape": input_rule.get("pre_grinding_shape"),
            "guide_profile_source": input_rule.get(
                "guide_profile_source"
            ),
            "final_section_profile_type": input_rule.get(
                "final_section_profile_type"
            ),
            "R_form_source": input_rule.get("R_form_source"),
            "formulas": {
                "slot_width": (
                    (
                        f"{profile.slot_reference_value:.2f} + {profile.slot_clearance:.2f} = "
                        f"{profile.guide_spec.guide_slot_width:.2f}"
                    )
                    if isinstance(profile, BlockGuideSection)
                    and profile.slot_clearance is not None
                    else (
                        f"{profile.guide_spec.product_preform_width_average:.2f} + "
                        f"{profile.guide_spec.tolerance_slot_clearance:.2f} = "
                        f"{profile.guide_spec.guide_slot_width:.2f}"
                    )
                ),
                "guide_thickness": (
                    f"{self._process_thickness(profile):.2f} + "
                    f"{profile.guide_spec.thickness_clearance_mid_value:.2f} = "
                    f"{profile.guide_spec.guide_thickness:.2f}"
                ),
                "slot_depth": self._slot_depth_formula(template, profile, release_sections[0]["slot_depth"]),
            },
            "thickness_clearance": profile.guide_spec.thickness_clearance_mid_value,
            "thickness_clearance_source": (
                "QG 38012 large-tile thickness clearance"
                if isinstance(profile, TileSection)
                else "global process option/default"
            ),
            "section_profile_type": self._section_profile_payload(profile)["profile_type"],
            "bottom_surface_type": self._section_profile_payload(profile)["bottom_surface_type"],
            "top_surface_type": self._section_profile_payload(profile)["top_surface_type"],
            "bottom_radius": self._section_profile_payload(profile)["bottom_radius"],
            "top_radius": self._section_profile_payload(profile)["top_radius"],
            "section_1_profile": release_sections[0]["section_profile"],
            "section_2_profile": release_sections[1]["section_profile"],
            "lower_wheel_notch_safety": lower_wheel_safety,
            "upper_wheel_notch_safety": upper_wheel_safety,
            "fixed_template_geometry": asdict(template.fixed_geometry),
            "shared_parameters": {
                "R_form": (
                    profile.forming_spec.R_form
                    if isinstance(profile, TileSection)
                    else None
                ),
                "slot_width": profile.guide_spec.guide_slot_width,
                "guide_thickness": profile.guide_spec.guide_thickness,
                "relief": profile.guide_spec.relief.relief_size,
                "relief_size": profile.guide_spec.relief.relief_size,
                "relief_radius": profile.guide_spec.relief.relief_size / 2.0,
                "relief_equivalent": f"{profile.guide_spec.relief.relief_count}-{profile.guide_spec.relief.relief_size:g}",
                "slot_depth": release_sections[0]["slot_depth"],
                "section_profile": self._section_profile_payload(profile),
                "lower_cavity_notch_opening": lower_wheel_safety["lower_cavity_notch_opening"],
                "effective_cut_in_depth": lower_wheel_safety["effective_cut_in_depth"],
                "upper_cavity_notch_opening": upper_wheel_safety["upper_cavity_notch_opening"],
                "upper_effective_cut_in_depth": upper_wheel_safety["effective_cut_in_depth"],
            },
            "side_derived_layer_policy": {
                "machine_outline": "SIDE_TEMPLATE contains the white Continuous machine outline.",
                "cavity_geometry": "SIDE_CAVITY contains green DASHED projected cavity lines.",
                "formal_release_geometry": "SIDE_DERIVED_RELEASE is reserved for other green Continuous derived geometry.",
                "auxiliary_geometry": "Hidden or debug helpers use SIDE_DEBUG and are not promoted into release geometry.",
            },
            "side_view_dimension_audit": side_view_dimension_audit,
            "r80_radius_dimension_audit": r80_radius_dimension_audit,
            "cavity_projection_audit": cavity_projection_audit,
            "removed_side_cavity_duplicates": release_result[
                "removed_side_cavity_duplicates"
            ],
            "release_cleanup": release_cleanup,
            "dimension_definition_point_audit": dimension_audit,
            "release_line_type_audit": line_type_audit,
            "guide_section_spacing": {
                "section_1_center": template.guide_section_1.center,
                "section_2_center": template.guide_section_2.center,
                "center_distance": round(
                    sqrt(
                        (template.guide_section_2.center[0] - template.guide_section_1.center[0]) ** 2
                        + (template.guide_section_2.center[1] - template.guide_section_1.center[1]) ** 2
                    ),
                    3,
                ),
            },
            "sections": [_public_section_result(section) for section in release_sections],
            "checks": {
                "debug_generated": debug_path.exists() and debug_path.stat().st_size > 0,
                "release_generated": release_path.exists() and release_path.stat().st_size > 0,
                "both_sections_updated": len(release_sections) == 2,
                "synchronized_parameters": _sections_are_synchronized(release_sections),
                "section_1.slot_width == section_2.slot_width": _same_section_value(release_sections, "slot_width"),
                "section_1.guide_thickness == section_2.guide_thickness": _same_section_value(
                    release_sections, "guide_thickness"
                ),
                "section_1.relief == section_2.relief": _same_section_value(release_sections, "relief"),
                "section_1.slot_depth == section_2.slot_depth": _same_section_value(release_sections, "slot_depth"),
                "section_1.profile_type == section_2.profile_type": _same_section_profile_value(
                    release_sections, "profile_type"
                ),
                "section_1_profile == section_2_profile": release_sections[0]["section_profile"]
                == release_sections[1]["section_profile"],
                "release_hides_unqualified_product_thickness": True,
                "side_view_dimensions_bound_to_r80_wheel_crowns": all(
                    item["is_bound_to_wheel_crown"] for item in side_view_dimension_audit
                ),
                "r80_radius_dimensions_bound_to_wheel_crowns": bool(
                    r80_radius_dimension_audit
                )
                and all(
                    item["is_bound_to_wheel_crown"]
                    for item in r80_radius_dimension_audit
                ),
                "side_cavity_projection_matches_pre_grinding_shape": bool(
                    cavity_projection_audit
                )
                and all(
                    item["matches_pre_grinding_shape"]
                    for item in cavity_projection_audit
                ),
                "no_legacy_4p29_dimension": release_cleanup["no_legacy_4p29_dimension"],
                "no_unexplained_1p80_dimension": release_cleanup["no_unexplained_1p80_dimension"],
                "release_side_dimensions_match_report": release_result["release_side_dimensions_match_report"],
                "lower_wheel_notch_opening <= product_length - 0.2": lower_wheel_safety[
                    "lower_cavity_notch_opening_within_limit"
                ],
                "lower_cavity_notch_opening_less_than_product_length": lower_wheel_safety[
                    "lower_cavity_notch_opening_less_than_product_length"
                ],
                "upper_wheel_notch_opening <= product_length - 0.2": upper_wheel_safety[
                    "upper_cavity_notch_opening_within_limit"
                ],
                "upper_cavity_notch_opening_less_than_product_length": upper_wheel_safety[
                    "upper_cavity_notch_opening_less_than_product_length"
                ],
                "fixed_590_not_parameterized": tuple(self.machine.side_fixed_spans) == template.fixed_geometry.side_fixed_spans,
                "fixed_27_height": template.fixed_geometry.outer_height == 27.0,
                "fixed_40_width": template.fixed_geometry.outer_width == 40.0,
                "input_rule_valid": bool(
                    input_rule.get("input_rule_valid", True)
                ),
                "SIDE_DERIVED_release_lines_are_continuous": line_type_audit[
                    "release_allowed"
                ],
                "all_release_dimensions_bound_to_geometry": dimension_audit[
                    "all_dimensions_bound_to_geometry"
                ],
                "all_required_dimension_roles_pass": dimension_audit[
                    "all_required_roles_pass"
                ],
            },
            "release_allowed": release_gate,
        }

    def _slot_depth_formula(
        self,
        template: MachineTemplate,
        profile: DualGuideProfile,
        slot_depth: float,
    ) -> str:
        if self._uses_down_up_lower_wheel_rule:
            return f"fixed section_slot_base_height = {slot_depth:.2f}"
        return (
            f"{template.fixed_geometry.outer_height:.2f} - {self.machine.side_layout.block_fixed_top_gap:.2f} - "
            f"{profile.guide_spec.guide_thickness:.2f} = {slot_depth:.2f}"
        )

    @staticmethod
    def _process_thickness(profile: DualGuideProfile) -> float:
        if isinstance(profile, TileSection):
            return profile.process_thickness
        return profile.block_spec.thickness_mid

    @staticmethod
    def _process_length(profile: DualGuideProfile) -> float:
        if isinstance(profile, TileSection):
            return profile.process_length
        return profile.block_spec.length

    @staticmethod
    def _product_payload(parsed_spec: DualGuideParsedSpec) -> dict[str, Any]:
        if isinstance(parsed_spec, FinishedSpec):
            return {
                "shape": parsed_spec.finished_shape,
                "raw_spec": parsed_spec.raw,
                "R_outer_finished": parsed_spec.R_outer_finished,
                "R_inner_finished": parsed_spec.R_inner_finished,
                "width": parsed_spec.chord_width,
                "length": parsed_spec.length,
                "product_length": parsed_spec.length,
                "thickness": parsed_spec.preform_thickness_mid,
                "product_thickness": parsed_spec.preform_thickness_mid,
                "thickness_tolerance_upper": parsed_spec.thickness_tolerance_upper,
                "thickness_tolerance_lower": parsed_spec.thickness_tolerance_lower,
            }
        return {
            "shape": "block",
            "raw_spec": parsed_spec.raw,
            "length": parsed_spec.length,
            "product_length": parsed_spec.length,
            "width": parsed_spec.width,
            "thickness": parsed_spec.thickness,
            "product_thickness": parsed_spec.thickness_mid,
        }

    def _legacy_input_rule(
        self,
        profile: DualGuideProfile,
        parsed_spec: DualGuideParsedSpec,
    ) -> dict[str, Any]:
        section_profile = self._section_profile_payload(profile)
        if isinstance(profile, TileSection):
            return {
                "input_rule_valid": True,
                "input_mode": "legacy_direct_api",
                "finished_product_spec": profile.finished_spec.raw,
                "pre_grinding_spec": parsed_spec.raw,
                "finished_product_shape": profile.finished_spec.finished_shape,
                "pre_grinding_shape": (
                    "block"
                    if profile.preform_block_spec is not None
                    else "same_r_tile"
                ),
                "guide_profile_source": (
                    "finished_product_big_r_with_pre_grinding_block"
                    if profile.preform_block_spec is not None
                    else "pre_grinding_spec"
                ),
                "final_section_profile_type": section_profile[
                    "profile_type"
                ],
                "R_form_source": (
                    "max(finished_product_R_outer, finished_product_R_inner)"
                    if profile.preform_block_spec is not None
                    else "pre_grinding_spec_equal_R"
                ),
            }
        return {
            "input_rule_valid": True,
            "input_mode": "legacy_direct_api",
            "finished_product_spec": parsed_spec.raw,
            "pre_grinding_spec": parsed_spec.raw,
            "finished_product_shape": "bread",
            "pre_grinding_shape": "block",
            "guide_profile_source": "pre_grinding_spec",
            "final_section_profile_type": section_profile["profile_type"],
            "R_form_source": "not_applicable",
        }


def _dimension_near_cross_section(dimension: Any, anchor: TemplateAnchor) -> bool:
    points = []
    for attr in ("defpoint", "defpoint2", "defpoint3", "defpoint4", "text_midpoint"):
        if dimension.dxf.hasattr(attr):
            point = dimension.dxf.get(attr)
            points.append((float(point.x), float(point.y)))
    if not points:
        return False
    center_x = sum(point[0] for point in points) / len(points)
    center_y = sum(point[1] for point in points) / len(points)
    return anchor.left - 40.0 <= center_x <= anchor.right + 40.0 and anchor.bottom - 30.0 <= center_y <= anchor.top + 30.0


def _find_dual_block_slot_width_dimension(dimensions: list[Any], geometry: Any):
    found = _find_block_slot_width_dimension(dimensions, geometry)
    if found is not None:
        return found
    for dimension in dimensions:
        if not (dimension.dxf.hasattr("defpoint2") and dimension.dxf.hasattr("defpoint3")):
            continue
        p2 = dimension.dxf.defpoint2
        p3 = dimension.dxf.defpoint3
        if abs(p2.y - p3.y) > 0.001:
            continue
        try:
            measurement = float(dimension.get_measurement())
        except Exception:
            continue
        text = dimension.dxf.text if dimension.dxf.hasattr("text") else ""
        if not (0.5 <= measurement <= 20.0):
            continue
        if "\\S+0" in text or "±" in text:
            return dimension
    return None


def _find_dual_guide_thickness_dimension(dimensions: list[Any]):
    for dimension in dimensions:
        if not (
            dimension.dxf.hasattr("defpoint2")
            and dimension.dxf.hasattr("defpoint3")
        ):
            continue
        p2 = dimension.dxf.defpoint2
        p3 = dimension.dxf.defpoint3
        if abs(float(p2.x) - float(p3.x)) > 0.01:
            continue
        try:
            measurement = float(dimension.get_measurement())
        except Exception:
            continue
        if 2.1 <= measurement <= 8.0:
            return dimension
    return None


def _find_dual_slot_base_dimension(dimensions: list[Any], geometry: Any):
    for dimension in dimensions:
        if not (
            dimension.dxf.hasattr("defpoint2")
            and dimension.dxf.hasattr("defpoint3")
        ):
            continue
        try:
            measurement = float(dimension.get_measurement())
        except Exception:
            continue
        if abs(measurement - geometry.slot_base_height) <= 0.1:
            return dimension
    return None


def _find_dual_opening_dimension(
    dimensions: list[Any],
    geometry: Any,
    *,
    excluded: set[Any],
):
    candidates: list[tuple[float, Any]] = []
    for dimension in dimensions:
        if dimension in excluded:
            continue
        if not (
            dimension.dxf.hasattr("defpoint2")
            and dimension.dxf.hasattr("defpoint3")
        ):
            continue
        p2 = dimension.dxf.defpoint2
        p3 = dimension.dxf.defpoint3
        if abs(float(p2.y) - float(p3.y)) > 0.01:
            continue
        try:
            measurement = float(dimension.get_measurement())
        except Exception:
            continue
        if 0.5 <= measurement <= 4.0:
            candidates.append((abs(measurement - geometry.center_opening), dimension))
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[0])[1]


def _bind_slot_width_dimension_to_geometry(dimension: Any, geometry: Any) -> None:
    y = (geometry.base_y + geometry.top_y) / 2.0
    dimension.dxf.defpoint2 = (geometry.left_x, y, 0.0)
    dimension.dxf.defpoint3 = (geometry.right_x, y, 0.0)
    _set_dimension_actual_measurement(dimension, geometry.slot_width)


def _add_slot_width_dimension(
    modelspace: Any,
    profile: DualGuideProfile,
    geometry: Any,
):
    y = (geometry.base_y + geometry.top_y) / 2.0
    dimension_y = geometry.outer_bottom - 9.0
    dimension = add_linear_dimension_with_text(
        modelspace,
        (geometry.left_x, y),
        (geometry.right_x, y),
        (geometry.left_x, dimension_y),
        (geometry.right_x, dimension_y),
        profile.guide_spec.slot_width_dimension_text,
        (geometry.center_x - 2.4, dimension_y - 2.0),
        angle=0.0,
        layer=DIMENSION_LAYER,
        include_fallback=False,
        include_native=True,
        dimstyle=TEMPLATE_DIMENSION_STYLE,
        dimension_text_height=TEMPLATE_DIMENSION_TEXT_HEIGHT,
    )
    if dimension is not None:
        _bind_slot_width_dimension_to_geometry(dimension, geometry)
    return dimension


def _has_bound_slot_width_dimension(modelspace: Any, geometry: Any) -> bool:
    expected_y = (geometry.base_y + geometry.top_y) / 2.0
    for dimension in modelspace.query("DIMENSION"):
        if not (
            dimension.dxf.hasattr("defpoint2")
            and dimension.dxf.hasattr("defpoint3")
        ):
            continue
        p2 = dimension.dxf.defpoint2
        p3 = dimension.dxf.defpoint3
        points = sorted(
            (
                (float(p2.x), float(p2.y)),
                (float(p3.x), float(p3.y)),
            )
        )
        if (
            abs(points[0][0] - geometry.left_x) <= 0.001
            and abs(points[1][0] - geometry.right_x) <= 0.001
            and abs(points[0][1] - expected_y) <= 0.001
            and abs(points[1][1] - expected_y) <= 0.001
        ):
            return True
    return False


def _is_unselected_small_process_dimension(
    dimension: Any,
    profile: DualGuideProfile,
) -> bool:
    if not (
        isinstance(profile, TileSection)
        and profile.process_type in {"block_to_tile", "block_to_bread"}
    ):
        return False
    if not (
        dimension.dxf.hasattr("defpoint2")
        and dimension.dxf.hasattr("defpoint3")
    ):
        return False
    try:
        measurement = float(dimension.get_measurement())
    except Exception:
        return False
    return 0.5 <= measurement <= 5.0


def _guide_thickness_geometry_points(
    profile: DualGuideProfile,
    geometry: Any,
) -> tuple[tuple[float, float], tuple[float, float]]:
    if isinstance(profile, TileSection):
        if profile.process_type in {"block_to_tile", "block_to_bread"}:
            x = geometry.right_x
            return (x, geometry.base_y), (x, geometry.top_y)
        radius = profile.forming_spec.R_form
        opening_half = profile.guide_spec.center_opening / 2.0
        x = geometry.center_x + opening_half + 1.0
        x_offset = x - geometry.center_x
        arc_y_offset = sqrt(radius * radius - x_offset * x_offset)
        lower_y = geometry.lower_radius_center[1] + arc_y_offset
        upper_y = geometry.upper_radius_center[1] + arc_y_offset
        return (x, lower_y), (x, upper_y)
    x = geometry.left_x + geometry.relief_radius
    return (x, geometry.base_y), (x, geometry.top_y)


def _bind_guide_thickness_dimension_to_geometry(
    dimension: Any,
    profile: DualGuideProfile,
    geometry: Any,
) -> None:
    point_1, point_2 = _guide_thickness_geometry_points(profile, geometry)
    dimension.dxf.defpoint2 = (*point_1, 0.0)
    dimension.dxf.defpoint3 = (*point_2, 0.0)
    _set_dimension_actual_measurement(dimension, geometry.guide_thickness)


def _add_guide_thickness_dimension(
    modelspace: Any,
    profile: DualGuideProfile,
    geometry: Any,
):
    point_1, point_2 = _guide_thickness_geometry_points(profile, geometry)
    x = geometry.outer_right + 7.0
    dimension = add_linear_dimension_with_text(
        modelspace,
        point_1,
        point_2,
        (x, point_1[1]),
        (x, point_2[1]),
        f"{geometry.guide_thickness:.2f}",
        (x + 1.2, (point_1[1] + point_2[1]) / 2.0),
        angle=90.0,
        text_rotation=90.0,
        layer=DIMENSION_LAYER,
        include_fallback=False,
        include_native=True,
        dimstyle=TEMPLATE_DIMENSION_STYLE,
        dimension_text_height=TEMPLATE_DIMENSION_TEXT_HEIGHT,
    )
    if dimension is not None:
        _bind_guide_thickness_dimension_to_geometry(
            dimension,
            profile,
            geometry,
        )
    return dimension


def _bind_slot_base_dimension_to_geometry(
    dimension: Any,
    geometry: Any,
) -> None:
    dimension.dxf.defpoint2 = (
        geometry.center_x,
        geometry.base_y,
        0.0,
    )
    dimension.dxf.defpoint3 = (
        geometry.center_x,
        geometry.outer_bottom,
        0.0,
    )


def _bind_relief_dimension(
    doc: Any,
    dimension: Any,
    geometry: Any,
) -> None:
    old_center = dimension.dxf.defpoint
    old_text_midpoint = (
        dimension.dxf.text_midpoint
        if dimension.dxf.hasattr("text_midpoint")
        else old_center
    )
    center = (geometry.left_x, geometry.top_y)
    target = (
        geometry.left_x,
        geometry.top_y - geometry.relief_radius,
    )
    dimension.dxf.defpoint = (*center, 0.0)
    dimension.dxf.defpoint4 = (*target, 0.0)
    # The archived annotation is a diameter dimension.  The release label is
    # a radius callout, so retain DXF flags but switch its base type to radius.
    dimension.dxf.dimtype = (int(dimension.dxf.dimtype) & ~0x0F) | 4
    dimension.dxf.text = f"4-R{geometry.relief_radius:.2f}"
    dimension.dxf.text_midpoint = (
        center[0] + float(old_text_midpoint.x) - float(old_center.x),
        center[1] + float(old_text_midpoint.y) - float(old_center.y),
        0.0,
    )
    _set_dimension_actual_measurement(
        dimension,
        geometry.relief_radius,
    )
    # Re-render the native block after moving the definition points. Updating
    # only DIMENSION attributes leaves the archived leader and arrow in place.
    dimension.render()
    _set_dimension_block_text(doc, dimension, dimension.dxf.text)


def _add_center_opening_dimension(modelspace: Any, geometry: Any):
    """Provide a bound center-opening size if a future template lacks one."""
    dimension_y = geometry.outer_top + 5.0
    return add_linear_dimension_with_text(
        modelspace,
        (geometry.opening_left_x, geometry.outer_top),
        (geometry.opening_right_x, geometry.outer_top),
        (geometry.opening_left_x, dimension_y),
        (geometry.opening_right_x, dimension_y),
        f"{geometry.center_opening:.2f}",
        (geometry.center_x - 1.2, dimension_y + 1.0),
        angle=0.0,
        layer=DIMENSION_LAYER,
        include_fallback=False,
        include_native=True,
        role=SECTION_CENTER_OPENING,
        dimstyle=TEMPLATE_DIMENSION_STYLE,
        dimension_text_height=TEMPLATE_DIMENSION_TEXT_HEIGHT,
    )


def _set_vertical_dimension_measurement(dimension: Any, target: float) -> None:
    if not (dimension.dxf.hasattr("defpoint2") and dimension.dxf.hasattr("defpoint3")):
        return
    p2 = dimension.dxf.defpoint2
    p3 = dimension.dxf.defpoint3
    if abs(p2.x - p3.x) <= 0.5:
        sign = 1.0 if p3.y >= p2.y else -1.0
        dimension.dxf.defpoint3 = (p3.x, p2.y + sign * target, p3.z)
        return
    if 0.1 <= abs(p3.y - p2.y) <= 10.0:
        if p3.y >= p2.y:
            dimension.dxf.defpoint2 = (p2.x, p3.y - target, p2.z)
        else:
            dimension.dxf.defpoint3 = (p3.x, p2.y - target, p3.z)


def _is_cross_section_centerline(entity: Any) -> bool:
    if entity.dxftype() != "LINE":
        return False
    if abs(float(entity.dxf.start.x) - float(entity.dxf.end.x)) > 0.001:
        return False
    return 3200.0 <= float(entity.dxf.start.x) <= 3300.0 and float(entity.dxf.start.distance(entity.dxf.end)) > 30.0


def _is_side_centerline(entity: Any) -> bool:
    return entity.dxftype() == "LINE" and entity.dxf.layer == "3中心线层"


def _is_side_cavity_line(entity: Any) -> bool:
    if entity.dxftype() != "LINE":
        return False
    if abs(float(entity.dxf.start.y) - float(entity.dxf.end.y)) > 0.001:
        return False
    if min(float(entity.dxf.start.x), float(entity.dxf.end.x)) < 3300.0:
        return False
    linetype = str(entity.dxf.linetype).upper()
    layer = str(entity.dxf.layer)
    return linetype == "DASHED" or "虚线" in layer


def _is_side_derived_line(entity: Any) -> bool:
    if entity.dxftype() != "LINE":
        return False
    if abs(float(entity.dxf.start.y) - float(entity.dxf.end.y)) > 0.001:
        return False
    if min(float(entity.dxf.start.x), float(entity.dxf.end.x)) < 3300.0:
        return False
    if int(entity.dxf.color) != 3:
        return False
    y = float(entity.dxf.start.y)
    return any(
        bottom + 1.0 < y < top - 1.0
        for bottom, top in (
            (-119.995, -92.995),
            (-215.629, -188.629),
            (-504.684, -477.684),
        )
    )


def _is_side_template_entity(entity: Any) -> bool:
    if entity.dxftype() == "ARC" and abs(float(entity.dxf.radius) - 80.0) <= 0.001:
        return True
    if entity.dxftype() == "LINE":
        x_values = (float(entity.dxf.start.x), float(entity.dxf.end.x))
        y_values = (float(entity.dxf.start.y), float(entity.dxf.end.y))
        return min(x_values) > 3300.0 and max(y_values) < -10.0
    return False


def _find_r80_arc_for_center(
    modelspace: Any,
    center_x: float,
    top_y: float,
    wheel_radius: float,
):
    candidates = [
        entity
        for entity in modelspace.query("ARC")
        if _matches_source_or_target_wheel_radius(
            float(entity.dxf.radius),
            wheel_radius,
        )
        and abs(float(entity.dxf.center.x) - center_x) <= 0.02
        and float(entity.dxf.center.y) > top_y
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda entity: abs(float(entity.dxf.center.y) - top_y))


def _nearest_r80_crown_for_dimension(
    modelspace: Any,
    dimension: Any,
    wheel_radius: float,
) -> tuple[float, float, float] | None:
    if not (dimension.dxf.hasattr("defpoint2") and dimension.dxf.hasattr("defpoint3")):
        return None
    p2 = dimension.dxf.defpoint2
    p3 = dimension.dxf.defpoint3
    candidates = []
    for arc in modelspace.query("ARC"):
        if abs(float(arc.dxf.radius) - wheel_radius) > 0.001:
            continue
        for crown_y in (
            float(arc.dxf.center.y) - float(arc.dxf.radius),
            float(arc.dxf.center.y) + float(arc.dxf.radius),
        ):
            p2_score = abs(float(p2.x) - float(arc.dxf.center.x)) + abs(float(p2.y) - crown_y)
            p3_score = abs(float(p3.x) - float(arc.dxf.center.x)) + abs(float(p3.y) - crown_y)
            # The controlled opening can move an R80 crown by several mm.
            # Match by side-view station (x) first, then rebind the dimension
            # to the new crown instead of retaining the template's old point.
            if min(abs(float(p2.x) - float(arc.dxf.center.x)), abs(float(p3.x) - float(arc.dxf.center.x))) > 60.0:
                continue
            surface_y = float(p3.y) if p2_score <= p3_score else float(p2.y)
            candidates.append(
                (
                    min(p2_score, p3_score),
                    float(arc.dxf.center.x),
                    crown_y,
                    surface_y,
                )
            )
    if not candidates:
        return None
    _, crown_x, crown_y, surface_y = min(candidates, key=lambda item: item[0])
    return crown_x, crown_y, surface_y


def _r80_arc_at_crown(
    modelspace: Any,
    crown_x: float,
    crown_y: float,
    wheel_radius: float,
):
    candidates = [
        arc
        for arc in modelspace.query("ARC")
        if abs(float(arc.dxf.radius) - wheel_radius) <= 0.001
        and abs(float(arc.dxf.center.x) - crown_x) <= 0.001
        and abs(_r80_expected_crown_y(arc) - crown_y) <= 0.001
    ]
    return candidates[0] if candidates else None


def _bind_dimension_to_wheel_crown(dimension: Any, crown_x: float, crown_y: float, top_y: float) -> None:
    if dimension.dxf.hasattr("defpoint2"):
        p2 = dimension.dxf.defpoint2
        dimension.dxf.defpoint2 = (crown_x, crown_y, p2.z)
    if dimension.dxf.hasattr("defpoint3"):
        p3 = dimension.dxf.defpoint3
        dimension.dxf.defpoint3 = (
            crown_x,
            top_y,
            p3.z,
        )


def _side_view_dimension_audit(
    modelspace: Any,
    wheel_radius: float,
) -> list[dict[str, Any]]:
    audit = []
    for arc in sorted(
        [
            entity
            for entity in modelspace.query("ARC")
            if abs(float(entity.dxf.radius) - wheel_radius) <= 0.001
            and entity.dxf.layer == SIDE_TEMPLATE_LAYER
        ],
        key=lambda entity: (float(entity.dxf.center.y), float(entity.dxf.center.x)),
    ):
        wheel_center = (round(float(arc.dxf.center.x), 3), round(float(arc.dxf.center.y), 3))
        wheel_radius = round(float(arc.dxf.radius), 3)
        crown_y = _r80_expected_crown_y(arc)
        crown = (round(float(arc.dxf.center.x), 3), round(crown_y, 3))
        dimension = _dimension_bound_to_crown(modelspace, crown)
        dimension_defpoint = None
        datum_defpoint = None
        measured_value = None
        is_bound = False
        if dimension is not None:
            p2 = dimension.dxf.defpoint2
            p3 = dimension.dxf.defpoint3
            dimension_defpoint = (round(float(p2.x), 3), round(float(p2.y), 3))
            datum_defpoint = (round(float(p3.x), 3), round(float(p3.y), 3))
            measured_value = round(float(dimension.get_measurement()), 3)
            is_bound = (
                abs(dimension_defpoint[0] - crown[0]) <= 0.001
                and abs(dimension_defpoint[1] - crown[1]) <= 0.001
                and abs(datum_defpoint[0] - crown[0]) <= 0.001
            )
        audit.append(
            {
                "wheel_center": list(wheel_center),
                "wheel_radius": wheel_radius,
                "expected_wheel_crown_point": list(crown),
                "dimension_defpoint": list(dimension_defpoint) if dimension_defpoint is not None else None,
                "datum_defpoint": list(datum_defpoint) if datum_defpoint is not None else None,
                "measured_value": measured_value,
                "is_bound_to_wheel_crown": is_bound,
            }
        )
    return audit


def _r80_radius_dimension_audit(
    modelspace: Any,
    wheel_radius: float,
) -> list[dict[str, Any]]:
    arcs = [
        entity
        for entity in modelspace.query("ARC")
        if abs(float(entity.dxf.radius) - wheel_radius) <= 0.001
        and entity.dxf.layer == SIDE_TEMPLATE_LAYER
    ]
    audit = []
    for dimension in modelspace.query("DIMENSION"):
        if not (
            dimension.dxf.hasattr("defpoint")
            and dimension.dxf.hasattr("defpoint4")
        ):
            continue
        try:
            measurement = float(dimension.get_measurement())
        except Exception:
            continue
        if abs(measurement - wheel_radius) > 0.01 or not arcs:
            continue
        center = dimension.dxf.defpoint
        target = dimension.dxf.defpoint4
        arc = min(
            arcs,
            key=lambda entity: hypot(
                float(entity.dxf.center.x) - float(center.x),
                float(entity.dxf.center.y) - float(center.y),
            ),
        )
        expected = (
            float(arc.dxf.center.x),
            _r80_expected_crown_y(arc),
        )
        error = hypot(
            float(target.x) - expected[0],
            float(target.y) - expected[1],
        )
        audit.append(
            {
                "dimension_handle": dimension.dxf.handle,
                "expected_wheel_crown_point": [
                    round(expected[0], 3),
                    round(expected[1], 3),
                ],
                "radius_target_point": [
                    round(float(target.x), 3),
                    round(float(target.y), 3),
                ],
                "point_error": round(error, 6),
                "is_bound_to_wheel_crown": error <= 0.001,
            }
        )
    return audit


def _deduplicate_exact_side_cavity_lines(modelspace: Any) -> list[str]:
    seen: set[tuple[tuple[float, float], tuple[float, float]]] = set()
    removed: list[str] = []
    for entity in list(modelspace.query("LINE")):
        if entity.dxf.layer != SIDE_CAVITY_LAYER:
            continue
        start = (
            round(float(entity.dxf.start.x), 6),
            round(float(entity.dxf.start.y), 6),
        )
        end = (
            round(float(entity.dxf.end.x), 6),
            round(float(entity.dxf.end.y), 6),
        )
        key = tuple(sorted((start, end)))
        if key in seen:
            removed.append(str(entity.dxf.handle))
            modelspace.delete_entity(entity)
            continue
        seen.add(key)
    return removed


def _delete_side_cavity_lines_in_bounds(
    modelspace: Any,
    bounds: tuple[float, float, float, float],
) -> None:
    x_min, x_max, bottom_y, top_y = bounds
    for entity in list(modelspace.query("LINE")):
        if entity.dxf.layer != SIDE_CAVITY_LAYER:
            continue
        if abs(float(entity.dxf.start.y) - float(entity.dxf.end.y)) > 0.001:
            continue
        center_x = (
            float(entity.dxf.start.x) + float(entity.dxf.end.x)
        ) / 2.0
        y = float(entity.dxf.start.y)
        if (
            x_min - 0.001 <= center_x <= x_max + 0.001
            and bottom_y - 2.0 <= y <= top_y + 10.0
        ):
            modelspace.delete_entity(entity)


def _subtract_horizontal_gaps(
    start_x: float,
    end_x: float,
    gaps: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    segments = [(start_x, end_x)]
    for gap_start, gap_end in sorted(gaps):
        next_segments = []
        for segment_start, segment_end in segments:
            if gap_end <= segment_start or gap_start >= segment_end:
                next_segments.append((segment_start, segment_end))
                continue
            if segment_start < gap_start:
                next_segments.append((segment_start, gap_start))
            if gap_end < segment_end:
                next_segments.append((gap_end, segment_end))
        segments = next_segments
    return [
        (segment_start, segment_end)
        for segment_start, segment_end in segments
        if segment_end - segment_start > 0.001
    ]


def _release_side_dimensions_match_report(modelspace: Any, audit: list[dict[str, Any]]) -> bool:
    return bool(audit) and all(item["is_bound_to_wheel_crown"] and item["measured_value"] is not None for item in audit)


def _dimension_block_texts(doc: Any, dimension: Any) -> list[str]:
    if not dimension.dxf.hasattr("geometry") or dimension.dxf.geometry not in doc.blocks:
        return []
    texts = []
    for entity in doc.blocks[dimension.dxf.geometry]:
        if entity.dxftype() == "TEXT":
            texts.append(entity.dxf.text)
        elif entity.dxftype() == "MTEXT":
            texts.append(entity.text)
    return texts


def _clear_dimension_block_texts(doc: Any, dimension: Any) -> None:
    if not dimension.dxf.hasattr("geometry") or dimension.dxf.geometry not in doc.blocks:
        return
    for entity in doc.blocks[dimension.dxf.geometry]:
        if entity.dxftype() == "TEXT":
            entity.dxf.text = ""
        elif entity.dxftype() == "MTEXT":
            entity.text = ""


def _release_legacy_side_dimension_residuals(doc: Any, modelspace: Any) -> list[dict[str, Any]]:
    residuals = []
    for dimension in modelspace.query("DIMENSION"):
        text = dimension.dxf.text if dimension.dxf.hasattr("text") else ""
        block_texts = _dimension_block_texts(doc, dimension)
        for value in [text, *block_texts]:
            if value == "4.29":
                residuals.append(
                    {
                        "handle": dimension.dxf.handle,
                        "text": value,
                        "dimension_text": text,
                        "block_texts": block_texts,
                    }
                )
    return residuals


def _dimension_bound_to_crown(modelspace: Any, crown: tuple[float, float]):
    candidates = []
    for dimension in modelspace.query("DIMENSION"):
        if not (dimension.dxf.hasattr("defpoint2") and dimension.dxf.hasattr("defpoint3")):
            continue
        try:
            measurement = float(dimension.get_measurement())
        except Exception:
            continue
        if not (0.1 <= measurement <= 20.0):
            continue
        p2 = dimension.dxf.defpoint2
        candidates.append((abs(float(p2.x) - crown[0]) + abs(float(p2.y) - crown[1]), dimension))
    if not candidates:
        return None
    distance, dimension = min(candidates, key=lambda item: item[0])
    return dimension if distance <= 0.01 else None


def _angle_deg(dx: float, dy: float) -> float:
    from math import atan2

    return degrees(atan2(dy, dx)) % 360.0


def _sections_are_synchronized(sections: list[dict[str, Any]]) -> bool:
    if len(sections) != 2:
        return False
    keys = ("slot_width", "guide_thickness", "slot_depth", "relief")
    return all(sections[0][key] == sections[1][key] for key in keys) and sections[0].get(
        "section_profile"
    ) == sections[1].get("section_profile")


def _same_section_value(sections: list[dict[str, Any]], key: str) -> bool:
    return len(sections) == 2 and sections[0][key] == sections[1][key]


def _same_section_profile_value(sections: list[dict[str, Any]], key: str) -> bool:
    return (
        len(sections) == 2
        and sections[0].get("section_profile", {}).get(key)
        == sections[1].get("section_profile", {}).get(key)
    )


def _r80_expected_crown_y(arc: Any) -> float:
    midpoint = ((float(arc.dxf.start_angle) + float(arc.dxf.end_angle)) / 2.0) % 360.0
    if 0.0 <= midpoint <= 180.0:
        return float(arc.dxf.center.y) + float(arc.dxf.radius)
    return float(arc.dxf.center.y) - float(arc.dxf.radius)


def _horizontal_internal_y_values(
    modelspace: Any,
    x_min: float,
    x_max: float,
    bottom_y: float,
    top_y: float,
) -> tuple[float, ...]:
    values = []
    for entity in modelspace.query("LINE"):
        if abs(float(entity.dxf.start.y) - float(entity.dxf.end.y)) > 0.001:
            continue
        y = float(entity.dxf.start.y)
        cx = (float(entity.dxf.start.x) + float(entity.dxf.end.x)) / 2.0
        if x_min - 0.001 <= cx <= x_max + 0.001 and bottom_y + 0.5 < y < top_y - 0.5:
            values.append(round(y, 3))
    return tuple(sorted(set(values)))


def _nearest_value(values: tuple[float, ...], target: float) -> float | None:
    if not values:
        return None
    return min(values, key=lambda value: abs(value - target))


def _find_lower_r80_arc_for_center(
    modelspace: Any,
    center_x: float,
    bottom_y: float,
    wheel_radius: float,
):
    candidates = [
        entity
        for entity in modelspace.query("ARC")
        if _matches_source_or_target_wheel_radius(
            float(entity.dxf.radius),
            wheel_radius,
        )
        and abs(float(entity.dxf.center.x) - center_x) <= 0.02
        and float(entity.dxf.center.y) < bottom_y
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda entity: abs(float(entity.dxf.center.y) - bottom_y))


def _replace_lower_surface_connector(
    entity: Any,
    center_x: float,
    surface_y: float,
    center_y: float,
    radius: float,
) -> None:
    half_chord = sqrt(max(0.0, radius * radius - (surface_y - center_y) ** 2))
    for attr in ("start", "end"):
        point = getattr(entity.dxf, attr)
        distance = float(point.x) - center_x
        if 8.0 <= abs(distance) <= 70.0:
            target_x = center_x - half_chord if distance < 0 else center_x + half_chord
            entity.dxf.set(attr, (target_x, point.y, point.z))


def _matches_source_or_target_wheel_radius(
    entity_radius: float,
    target_radius: float,
) -> bool:
    return (
        abs(entity_radius - DEFAULT_WHEEL_RADIUS) <= 0.001
        or abs(entity_radius - target_radius) <= 0.001
    )


def _split_lower_cavity_line(entity: Any, center_x: float, opening: float) -> None:
    if opening <= 0.0:
        return
    left_gap = center_x - opening / 2.0
    right_gap = center_x + opening / 2.0
    start = entity.dxf.start
    end = entity.dxf.end
    min_x = min(float(start.x), float(end.x))
    max_x = max(float(start.x), float(end.x))
    if max_x < center_x:
        if start.x <= end.x:
            entity.dxf.end = (left_gap, end.y, end.z)
        else:
            entity.dxf.start = (left_gap, start.y, start.z)
    elif min_x > center_x:
        if start.x <= end.x:
            entity.dxf.start = (right_gap, start.y, start.z)
        else:
            entity.dxf.end = (right_gap, end.y, end.z)


def _dimension_is_in_dual_cross_section(dimension: Any) -> bool:
    points = []
    for attr in ("defpoint", "defpoint2", "defpoint3", "defpoint4", "text_midpoint"):
        if dimension.dxf.hasattr(attr):
            point = dimension.dxf.get(attr)
            points.append((float(point.x), float(point.y)))
    if not points:
        return False
    center_x = sum(point[0] for point in points) / len(points)
    center_y = sum(point[1] for point in points) / len(points)
    return 3180.0 <= center_x <= 3290.0 and -230.0 <= center_y <= -70.0


def _format_compact_decimal(value: float) -> str:
    return f"{value:.2f}"


def _text_matches_number(text: str, expected: float) -> bool:
    try:
        return abs(float(text) - expected) <= 0.001
    except (TypeError, ValueError):
        return False


def _public_section_result(section: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in section.items() if key != "geometry"}


def _artifact_filenames(artifact_stem: str | None) -> dict[str, str]:
    if artifact_stem is None:
        return {
            "debug_dxf": "debug.dxf",
            "release_dxf": "release.dxf",
            "release_candidate_dxf": "release.candidate.dxf",
            "report_json": "report.json",
            "dimension_audit_json": "dimension_definition_point_audit.json",
        }
    return {
        "debug_dxf": f"{artifact_stem}（调试）.dxf",
        "release_dxf": f"{artifact_stem}.dxf",
        "release_candidate_dxf": f"{artifact_stem}（正式候选）.dxf",
        "report_json": f"{artifact_stem}_report.json",
        "dimension_audit_json": f"{artifact_stem}_dimension_definition_point_audit.json",
    }


def _machine_template_payload(template: MachineTemplate) -> dict[str, Any]:
    return {
        "machine_id": template.machine_id,
        "machine_name": template.machine_name,
        "dual_section_mode": template.dual_section_mode,
        "guide_section_1": _guide_section_payload(template.guide_section_1),
        "guide_section_2": _guide_section_payload(template.guide_section_2),
        "assembly_side_bounds": template.assembly_side_bounds,
        "assembly_side_centerline_x_values": template.assembly_side_centerline_x_values,
        "fixed_geometry": asdict(template.fixed_geometry),
    }


def _guide_section_payload(section: GuideSectionInstance) -> dict[str, Any]:
    return {
        "section_id": section.section_id,
        "center": section.center,
        "anchor": {
            "left": section.anchor.left,
            "right": section.anchor.right,
            "bottom": section.anchor.bottom,
            "top": section.anchor.top,
            "slot_center_x": section.anchor.slot_center_x,
        },
        "fixed_spans": section.fixed_spans,
        "side_bounds": section.side_bounds,
        "side_centerline_x_values": section.side_centerline_x_values,
        "wheel_positions": section.wheel_positions,
    }

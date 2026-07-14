from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import ast

from .side_view_config import SideViewLayoutConfig


TEMPLATE_ROOT = Path("templates")


@dataclass(frozen=True)
class SectionProfileConfig:
    profile_type: str = "rectangular_block"
    bottom_surface_type: str = "plane"
    top_surface_type: str = "plane"
    bottom_radius: float | None = None
    top_radius: float | None = None


@dataclass(frozen=True)
class MachineConfig:
    machine_id: str
    machine_name: str
    guide_length: float
    wheel_positions: tuple[str, ...]
    guide_sections: int
    side_fixed_spans: tuple[float, ...]
    section_template_path: Path
    side_template_path: Path
    side_layout: SideViewLayoutConfig
    block_outer_width: float = 35.0
    block_thickness_clearance_mid: float = 0.12
    section_style: str = "standard"
    section_outer_width: float = 33.0
    section_center_opening: float = 1.5
    section_slot_base_height: float = 12.0
    section_profile: SectionProfileConfig = SectionProfileConfig()
    supported_section_profiles: tuple[str, ...] = ("rectangular_block",)
    guide_type: str = "single_guide"
    template_coordinate_system: str = "section_xy_y_up"
    template_axis_rotation_deg: float = 0.0
    template_mirror_x: bool = False
    template_mirror_y: bool = False
    flat_arc_surface_side: str | None = None
    flat_surface_side: str | None = None
    flat_arc_center_side: str | None = None
    block_to_tile_groove_profile: str | None = None
    block_to_bread_groove_profile: str | None = None
    approved_reference_overrides: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        mode = self.side_layout.block_side_mode
        valid_modes = {
            "fixed_projected_height",
            "fixed_top_gap",
            "slot_base_plus_wheel_cut_in",
        }
        if mode not in valid_modes:
            raise ValueError(
                f"Machine '{self.machine_id}' must define a valid block_side_mode; "
                f"got {mode!r}."
            )
        if (
            mode == "fixed_projected_height"
            and self.side_layout.block_side_projected_slot_height is None
        ):
            raise ValueError(
                f"Machine '{self.machine_id}' requires block_side_projected_slot_height."
            )
        if self.side_layout.block_projected_top_mode not in {
            "wheel_cut_depth",
            "guide_thickness",
        }:
            raise ValueError(
                f"Machine '{self.machine_id}' has invalid block_projected_top_mode "
                f"{self.side_layout.block_projected_top_mode!r}."
            )
        if mode == "fixed_top_gap" and self.side_layout.block_fixed_top_gap is None:
            raise ValueError(
                f"Machine '{self.machine_id}' requires block_fixed_top_gap."
            )
        if mode == "slot_base_plus_wheel_cut_in" and (
            (
                self.side_layout.block_lower_wheel_cut_in is None
                and self.side_layout.block_lower_wheel_cut_in_ratio is None
            )
            or (
                self.side_layout.block_upper_wheel_cut_in is None
                and self.side_layout.block_upper_wheel_cut_in_ratio is None
            )
        ):
            raise ValueError(
                f"Machine '{self.machine_id}' requires lower and upper block wheel cut-ins."
            )
        lower_cut_in_defined = (
            self.side_layout.block_to_tile_lower_wheel_cut_in is not None
            or self.side_layout.block_to_tile_lower_wheel_cut_in_ratio is not None
        )
        upper_cut_in_defined = (
            self.side_layout.block_to_tile_upper_wheel_cut_in is not None
            or self.side_layout.block_to_tile_upper_wheel_cut_in_ratio is not None
        )
        if not lower_cut_in_defined or not upper_cut_in_defined:
            raise ValueError(
                f"Machine '{self.machine_id}' requires explicit block-to-tile lower "
                "and upper wheel cut-ins or cut-in ratios."
            )


def load_machine_config(machine_id: str) -> MachineConfig:
    config_dir = TEMPLATE_ROOT / machine_id
    config_path = config_dir / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"Machine config not found: {config_path}")
    raw = _parse_simple_yaml(config_path)
    layout_raw = raw.get("layout", {})
    return MachineConfig(
        machine_id=str(raw["machine_id"]),
        machine_name=str(raw["machine_name"]),
        guide_length=float(raw["guide_length"]),
        wheel_positions=tuple(str(value) for value in raw["wheel_positions"]),
        guide_sections=int(raw["guide_sections"]),
        side_fixed_spans=tuple(float(value) for value in raw.get("side_fixed_spans", ())),
        section_template_path=config_dir / str(raw["section_template"]),
        side_template_path=config_dir / str(raw["side_template"]),
        side_layout=SideViewLayoutConfig(
            left_x=float(layout_raw["left_x"]),
            center_a_x=float(layout_raw["center_a_x"]),
            center_b_x=float(layout_raw["center_b_x"]),
            right_x=float(layout_raw["right_x"]),
            lower_y=float(layout_raw["lower_y"]),
            upper_y=float(layout_raw["upper_y"]),
            template_min_x=float(layout_raw.get("template_min_x", 3350.0)),
            template_min_y=float(layout_raw.get("template_min_y", -120.0)),
            template_max_y=float(layout_raw.get("template_max_y", 150.0)),
            block_side_mode=_optional_string(layout_raw.get("block_side_mode")),
            block_side_projected_slot_height=_optional_float(
                layout_raw.get("block_side_projected_slot_height")
            ),
            block_projected_top_mode=str(
                layout_raw.get("block_projected_top_mode", "wheel_cut_depth")
            ),
            block_fixed_top_gap=_optional_float(layout_raw.get("block_fixed_top_gap")),
            block_lower_wheel_cut_in=_optional_float(
                layout_raw.get("block_lower_wheel_cut_in")
            ),
            block_upper_wheel_cut_in=_optional_float(
                layout_raw.get("block_upper_wheel_cut_in")
            ),
            block_lower_wheel_cut_in_ratio=_optional_float(
                layout_raw.get("block_lower_wheel_cut_in_ratio")
            ),
            block_upper_wheel_cut_in_ratio=_optional_float(
                layout_raw.get("block_upper_wheel_cut_in_ratio")
            ),
            fixed_tile_side_projected_slot_height=float(
                layout_raw.get("fixed_tile_side_projected_slot_height", 0.0)
            ),
            tile_upper_wheel_cut_in_ratio=float(
                layout_raw.get("tile_upper_wheel_cut_in_ratio", 0.0)
            ),
            block_to_tile_lower_wheel_cut_in=_optional_float(
                layout_raw.get("block_to_tile_lower_wheel_cut_in")
            ),
            block_to_tile_upper_wheel_cut_in=_optional_float(
                layout_raw.get("block_to_tile_upper_wheel_cut_in")
            ),
            block_to_tile_lower_wheel_cut_in_ratio=_optional_float(
                layout_raw.get("block_to_tile_lower_wheel_cut_in_ratio")
            ),
            block_to_tile_upper_wheel_cut_in_ratio=_optional_float(
                layout_raw.get("block_to_tile_upper_wheel_cut_in_ratio")
            ),
        ),
        block_outer_width=float(raw.get("block_outer_width", 35.0)),
        block_thickness_clearance_mid=float(raw.get("block_thickness_clearance_mid", 0.12)),
        section_style=str(raw.get("section_style", "standard")),
        section_outer_width=float(raw.get("section_outer_width", 33.0)),
        section_center_opening=float(raw.get("section_center_opening", 1.5)),
        section_slot_base_height=float(raw.get("section_slot_base_height", 12.0)),
        section_profile=SectionProfileConfig(
            profile_type=str(raw.get("section_profile_type", "rectangular_block")),
            bottom_surface_type=str(raw.get("bottom_surface_type", "plane")),
            top_surface_type=str(raw.get("top_surface_type", "plane")),
            bottom_radius=_optional_float(raw.get("bottom_radius")),
            top_radius=_optional_float(raw.get("top_radius")),
        ),
        supported_section_profiles=tuple(
            str(value)
            for value in raw.get("supported_section_profiles", ("rectangular_block",))
        ),
        guide_type=str(raw.get("guide_type", "single_guide")),
        template_coordinate_system=str(
            raw.get("template_coordinate_system", "section_xy_y_up")
        ),
        template_axis_rotation_deg=float(
            raw.get("template_axis_rotation_deg", 0.0)
        ),
        template_mirror_x=bool(raw.get("template_mirror_x", False)),
        template_mirror_y=bool(raw.get("template_mirror_y", False)),
        flat_arc_surface_side=_optional_string(raw.get("flat_arc_surface_side")),
        flat_surface_side=_optional_string(raw.get("flat_surface_side")),
        flat_arc_center_side=_optional_string(raw.get("flat_arc_center_side")),
        block_to_tile_groove_profile=_optional_string(
            raw.get("block_to_tile_groove_profile")
        ),
        block_to_bread_groove_profile=_optional_string(
            raw.get("block_to_bread_groove_profile")
        ),
        approved_reference_overrides=tuple(
            str(value)
            for value in raw.get("approved_reference_overrides", ())
        ),
    )


def _parse_simple_yaml(path: Path) -> dict[str, object]:
    result: dict[str, object] = {}
    current_section: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if line.startswith("  ") and current_section:
            key, value = _split_key_value(line.strip(), path)
            section = result.setdefault(current_section, {})
            if not isinstance(section, dict):
                raise ValueError(f"Invalid nested YAML section in {path}: {current_section}")
            section[key] = _parse_scalar(value)
            continue
        key, value = _split_key_value(line, path)
        if value == "":
            result[key] = {}
            current_section = key
        else:
            result[key] = _parse_scalar(value)
            current_section = None
    return result


def _split_key_value(line: str, path: Path) -> tuple[str, str]:
    if ":" not in line:
        raise ValueError(f"Invalid YAML line in {path}: {line}")
    key, value = line.split(":", 1)
    return key.strip(), value.strip()


def _parse_scalar(value: str) -> object:
    if value == "":
        return ""
    if value.lower() in {"null", "none"}:
        return None
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value.startswith("[") and value.endswith("]"):
        return ast.literal_eval(value)
    if value.startswith('"') and value.endswith('"'):
        return ast.literal_eval(value)
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return str(value)

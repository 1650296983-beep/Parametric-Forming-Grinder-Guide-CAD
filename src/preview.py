from __future__ import annotations

import os
from math import sqrt
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/cad_matplotlib_cache")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Arc

from .block_geometry import BlockGuideSection
from .geometry import Point, SectionProfile, TileSection, sample_profile
from .machine_config import MachineConfig
from .side_view_config import SideViewLayoutConfig


def write_png_preview(
    profile: SectionProfile | TileSection,
    path: str | Path,
    side_layout: SideViewLayoutConfig | None = None,
    machine_name: str | None = None,
) -> Path:
    """Render a dimensioned guide-rail section for operator review.

    The preview intentionally contains no side projection.  Side-view geometry
    is an implementation detail of the DXF and made the former split preview
    too small to use as a release check.
    """
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(profile, TileSection):
        fig, ax = plt.subplots(figsize=(8.2, 8.0), dpi=180)
        _draw_guide_control(ax, profile)
        title = _section_title(profile, machine_name)
    else:
        fig, ax = plt.subplots(figsize=(7.2, 6.8), dpi=180)
        _draw_legacy_profile(ax, profile)
        title = "Guide rail section preview"

    # Kept as optional compatibility arguments for callers outside this
    # project.  The intentionally section-only preview does not use them.
    del side_layout
    ax.set_aspect("equal", adjustable="box")
    ax.set_axis_off()
    ax.set_title(title, fontsize=12, fontweight="bold", pad=16)
    ax.margins(x=0.18, y=0.20)
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)
    return output_path


def write_block_png_preview(
    profile: BlockGuideSection,
    machine: MachineConfig,
    path: str | Path,
) -> Path:
    """Render the complete dimensioned block-guide section for review."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8.2, 8.0), dpi=180)
    _draw_block_guide_control(ax, profile)
    ax.set_aspect("equal", adjustable="box")
    ax.set_axis_off()
    ax.set_title(f"Guide rail section preview · {machine.machine_id}", fontsize=12, fontweight="bold", pad=16)
    ax.margins(x=0.18, y=0.20)
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)
    return output_path


def _section_title(profile: TileSection, machine_name: str | None) -> str:
    title = "Guide rail section preview"
    if machine_name:
        return f"{title} · {machine_name}"
    return title


def _draw_legacy_profile(ax: plt.Axes, profile: SectionProfile) -> None:
    """Retain a useful section-only preview for the legacy single-profile API."""
    points = sample_profile(profile, arc_samples=128)
    closed_points = points + [points[0]]
    ax.plot(
        [point.x for point in closed_points],
        [point.y for point in closed_points],
        color="#1f2937",
        linewidth=2.0,
    )
    _draw_centerline(ax, points)


def _draw_guide_control(ax: plt.Axes, tile_section: TileSection) -> None:
    guide = tile_section.guide_spec
    half_outer = guide.outer_width / 2.0
    half_slot = guide.guide_slot_width / 2.0
    base_y = guide.slot_base_height
    top_y = guide.slot_base_height + guide.guide_thickness
    x_center = guide.slot_center_offset
    r_form = tile_section.forming_spec.R_form
    arc_base = sqrt(r_form**2 - half_slot**2)
    lower_center_y = base_y - arc_base
    xs = [x_center - half_slot + guide.guide_slot_width * index / 80 for index in range(81)]
    if tile_section.process_type in {"block_to_tile", "block_to_bread"}:
        if tile_section.arc_side == "lower":
            lower_center_y = base_y + arc_base
            lower_ys = [
                lower_center_y - sqrt(r_form**2 - (x - x_center) ** 2)
                for x in xs
            ]
            upper_ys = [top_y for _ in xs]
            upper_label = "upper slot plane"
            lower_label = "lower slot arc"
        else:
            lower_ys = [base_y for _ in xs]
            upper_center_y = top_y - arc_base
            upper_ys = [upper_center_y + sqrt(r_form**2 - (x - x_center) ** 2) for x in xs]
            upper_label = "upper slot arc"
            lower_label = "lower slot plane"
    else:
        lower_ys = [lower_center_y + sqrt(r_form**2 - (x - x_center) ** 2) for x in xs]
        upper_center_y = top_y - arc_base
        upper_ys = [upper_center_y + sqrt(r_form**2 - (x - x_center) ** 2) for x in xs]
        upper_label = "upper slot arc"
        lower_label = "lower slot arc"

    ax.plot([-half_outer, half_outer, half_outer, -half_outer, -half_outer], [0, 0, guide.outer_height, guide.outer_height, 0], color="#505050", linewidth=1.0, label="fixed_template")
    ax.plot([-half_outer, half_outer], [base_y, base_y], color="#505050", linewidth=1.0, linestyle="--")
    ax.plot([x_center, x_center], [0, guide.outer_height], color="#505050", linewidth=1.0, linestyle=":")
    ax.plot(
        xs,
        upper_ys,
        color="#2ca02c",
        linewidth=1.6,
        label=upper_label,
    )
    ax.plot(
        xs,
        lower_ys,
        color="#2ca02c",
        linewidth=1.6,
        label=lower_label,
    )
    ax.plot(
        [x_center - half_slot, x_center - half_slot],
        [base_y, top_y],
        color="#2ca02c",
        linewidth=1.0,
        linestyle=":",
    )
    ax.plot([x_center + half_slot, x_center + half_slot], [base_y, top_y], color="#2ca02c", linewidth=1.0, linestyle=":")
    opening_half = guide.center_opening / 2.0
    ax.plot(
        [x_center - opening_half, x_center - opening_half],
        [top_y, guide.outer_height],
        color="#2ca02c",
        linewidth=0.9,
        linestyle="-.",
    )
    ax.plot(
        [x_center + opening_half, x_center + opening_half],
        [top_y, guide.outer_height],
        color="#2ca02c",
        linewidth=0.9,
        linestyle="-.",
    )
    _draw_dimension_annotations(
        ax,
        tile_section,
        half_outer=half_outer,
        half_slot=half_slot,
        base_y=base_y,
        top_y=top_y,
        x_center=x_center,
    )


def _draw_block_guide_control(ax: plt.Axes, block_section: BlockGuideSection) -> None:
    """Draw the block-preform guide with the same review dimensions as release."""
    guide = block_section.guide_spec
    half_outer = guide.outer_width / 2.0
    half_slot = guide.guide_slot_width / 2.0
    base_y = guide.slot_base_height
    top_y = base_y + guide.guide_thickness
    x_center = guide.slot_center_offset
    left_x = x_center - half_slot
    right_x = x_center + half_slot
    corner_radius = guide.relief.relief_size / 2.0
    opening_half = guide.center_opening / 2.0
    outline_color = "#1f2937"
    cavity_color = "#146c94"

    ax.plot(
        [-half_outer, half_outer, half_outer, -half_outer, -half_outer],
        [0.0, 0.0, guide.outer_height, guide.outer_height, 0.0],
        color=outline_color,
        linewidth=1.7,
    )
    ax.plot([x_center, x_center], [0.0, guide.outer_height], color="#bc3a42", linewidth=0.9, linestyle="--")
    ax.plot([left_x, left_x], [base_y + corner_radius, top_y - corner_radius], color=cavity_color, linewidth=1.7)
    ax.plot([right_x, right_x], [base_y + corner_radius, top_y - corner_radius], color=cavity_color, linewidth=1.7)
    ax.plot([left_x + corner_radius, right_x - corner_radius], [base_y, base_y], color=cavity_color, linewidth=1.7)
    ax.plot([left_x + corner_radius, right_x - corner_radius], [top_y, top_y], color=cavity_color, linewidth=1.7)
    for center_x, center_y, start_angle, end_angle in (
        (left_x + corner_radius, base_y + corner_radius, 180, 270),
        (right_x - corner_radius, base_y + corner_radius, 270, 360),
        (right_x - corner_radius, top_y - corner_radius, 0, 90),
        (left_x + corner_radius, top_y - corner_radius, 90, 180),
    ):
        ax.add_patch(
            Arc(
                (center_x, center_y),
                2 * corner_radius,
                2 * corner_radius,
                theta1=start_angle,
                theta2=end_angle,
                color=cavity_color,
                linewidth=1.7,
            )
        )
    ax.plot(
        [x_center - opening_half, x_center - opening_half],
        [top_y, guide.outer_height],
        color=cavity_color,
        linewidth=1.1,
        linestyle="-.",
    )
    ax.plot(
        [x_center + opening_half, x_center + opening_half],
        [top_y, guide.outer_height],
        color=cavity_color,
        linewidth=1.1,
        linestyle="-.",
    )
    _draw_dimension_annotations(
        ax,
        block_section,
        half_outer=half_outer,
        half_slot=half_slot,
        base_y=base_y,
        top_y=top_y,
        x_center=x_center,
    )


def _draw_dimension_annotations(
    ax: plt.Axes,
    section: TileSection | BlockGuideSection,
    half_outer: float,
    half_slot: float,
    base_y: float,
    top_y: float,
    x_center: float,
) -> None:
    guide = section.guide_spec
    color = "#0b7f55"
    text_style = {"color": color, "fontsize": 9}
    left_x = x_center - half_slot
    right_x = x_center + half_slot

    slot_dim_y = base_y - 5.6
    _plot_dimension_line(ax, (left_x, base_y), (left_x, slot_dim_y), color)
    _plot_dimension_line(ax, (right_x, base_y), (right_x, slot_dim_y), color)
    _plot_dimension_line(ax, (left_x, slot_dim_y), (right_x, slot_dim_y), color)
    ax.text(
        x_center,
        slot_dim_y - 0.5,
        guide.slot_width_dimension_text,
        ha="center",
        va="top",
        **text_style,
    )

    thickness_x = half_outer + 4.0
    _plot_dimension_line(ax, (right_x, base_y), (thickness_x, base_y), color)
    _plot_dimension_line(ax, (right_x, top_y), (thickness_x, top_y), color)
    _plot_dimension_line(ax, (thickness_x, base_y), (thickness_x, top_y), color)
    ax.text(thickness_x + 0.45, (base_y + top_y) / 2.0, f"{guide.guide_thickness:.2f}", va="center", **text_style)

    if isinstance(section, TileSection) and section.process_type in {"tile", "block_to_tile", "block_to_bread"}:
        ax.plot(
            [x_center + 1.2, right_x + 3.8],
            [top_y + 0.2, top_y + 3.2],
            color=color,
            linewidth=1.0,
        )
        ax.text(
            right_x + 4.1,
            top_y + 3.2,
            f"R{section.forming_spec.R_form:.2f}",
            va="center",
            **text_style,
        )
    if isinstance(section, TileSection) and section.process_type == "tile":
        ax.plot(
            [x_center - 1.2, left_x - 5.2],
            [base_y + 0.2, base_y - 2.2],
            color=color,
            linewidth=1.0,
        )
        ax.text(left_x - 5.6, base_y - 2.2, f"R{section.forming_spec.R_form:.2f}", ha="right", va="center", **text_style)

    ax.plot([left_x, left_x - 6.4], [top_y - guide.relief.relief_size / 2.0, top_y + 1.0], color=color, linewidth=1.0)
    ax.text(left_x - 6.8, top_y + 1.0, guide.relief.relief_label, ha="right", va="center", **text_style)

    opening_half = guide.center_opening / 2.0
    opening_dim_y = guide.outer_height + 3.0
    _plot_dimension_line(ax, (x_center - opening_half, guide.outer_height), (x_center - opening_half, opening_dim_y), color)
    _plot_dimension_line(ax, (x_center + opening_half, guide.outer_height), (x_center + opening_half, opening_dim_y), color)
    _plot_dimension_line(ax, (x_center - opening_half, opening_dim_y), (x_center + opening_half, opening_dim_y), color)
    ax.text(x_center, opening_dim_y + 0.45, f"{guide.center_opening:.2f}", ha="center", va="bottom", **text_style)

    outer_width_y = guide.outer_height + 7.2
    _plot_dimension_line(ax, (-half_outer, guide.outer_height), (-half_outer, outer_width_y), color)
    _plot_dimension_line(ax, (half_outer, guide.outer_height), (half_outer, outer_width_y), color)
    _plot_dimension_line(ax, (-half_outer, outer_width_y), (half_outer, outer_width_y), color)
    ax.text(x_center, outer_width_y + 0.45, f"{guide.outer_width:.2f}", ha="center", va="bottom", **text_style)

    outer_height_x = -half_outer - 5.2
    _plot_dimension_line(ax, (-half_outer, 0.0), (outer_height_x, 0.0), color)
    _plot_dimension_line(ax, (-half_outer, guide.outer_height), (outer_height_x, guide.outer_height), color)
    _plot_dimension_line(ax, (outer_height_x, 0.0), (outer_height_x, guide.outer_height), color)
    ax.text(outer_height_x - 0.45, guide.outer_height / 2.0, f"{guide.outer_height:.2f}", ha="right", va="center", **text_style)

    slot_base_x = half_outer + 7.0
    _plot_dimension_line(ax, (half_outer, 0.0), (slot_base_x, 0.0), color)
    _plot_dimension_line(ax, (right_x, base_y), (slot_base_x, base_y), color)
    _plot_dimension_line(ax, (slot_base_x, 0.0), (slot_base_x, base_y), color)
    ax.text(slot_base_x + 0.45, base_y / 2.0, f"{guide.slot_base_height:.2f}", va="center", **text_style)


def _plot_dimension_line(ax: plt.Axes, start: tuple[float, float], end: tuple[float, float], color: str) -> None:
    ax.plot([start[0], end[0]], [start[1], end[1]], color=color, linewidth=0.9)


def _draw_centerline(ax: plt.Axes, points: list[Point]) -> None:
    min_y = min(point.y for point in points)
    max_y = max(point.y for point in points)
    padding = max((max_y - min_y) * 0.08, 0.5)
    ax.plot(
        [0.0, 0.0],
        [min_y - padding, max_y + padding],
        color="#888888",
        linewidth=1.0,
        linestyle="--",
    )

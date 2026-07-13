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
from .side_view import build_side_view_geometry
from .side_view_config import SideViewLayoutConfig


def write_png_preview(
    profile: SectionProfile | TileSection,
    path: str | Path,
    side_layout: SideViewLayoutConfig | None = None,
    machine_name: str | None = None,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    profiles = _profiles_for_preview(profile)
    all_points: list[Point] = []
    for item, _, _, _, dx, dy in profiles:
        all_points.extend(_offset_points(sample_profile(item, arc_samples=128), dx, dy))

    is_bread = isinstance(profile, TileSection) and profile.process_type in {
        "block_to_tile",
        "block_to_bread",
    }
    fig, ax = plt.subplots(figsize=((10, 6) if is_bread else (7, 7)), dpi=160)
    for item, label, color, linestyle, dx, dy in profiles:
        points = _offset_points(sample_profile(item, arc_samples=128), dx, dy)
        closed_points = points + [points[0]]
        xs = [point.x for point in closed_points]
        ys = [point.y for point in closed_points]
        ax.plot(xs, ys, color=color, linewidth=2.0, linestyle=linestyle, label=label)
        ax.scatter(
            [item.outer_left.x, item.outer_right.x, item.inner_right.x, item.inner_left.x],
            [item.outer_left.y, item.outer_right.y, item.inner_right.y, item.inner_left.y],
            color=color,
            s=18,
            zorder=3,
        )

    if isinstance(profile, TileSection):
        _draw_guide_control(ax, profile)
        _draw_side_view_preview(ax, profile, side_layout=side_layout)

    _draw_centerline(ax, all_points)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("" if is_bread else "X (mm)")
    ax.set_ylabel("Y (mm)")
    if isinstance(profile, TileSection):
        side = build_side_view_geometry(profile, layout=side_layout)
        title_prefix = (
            "Block-to-tile guide"
            if profile.process_type == "block_to_tile"
            else (
                "Block-to-bread guide"
                if profile.process_type == "block_to_bread"
                else "Tile section profiles"
            )
        )
        ax.set_title(
            "\n".join(
                [
                    title_prefix,
                    (
                        f"R_form={profile.forming_spec.R_form:g} mm, "
                        f"slot_width={profile.guide_spec.guide_slot_width:g} mm, "
                        f"guide_thickness={profile.guide_spec.guide_thickness:g} mm"
                    ),
                    (
                        f"side_projected={side.derived.side_projected_slot_height:g} mm, "
                        f"side_clearance={side.derived.side_clearance_height:g} mm"
                    ),
                    *([machine_name] if machine_name else []),
                ]
            ),
            fontsize=10,
        )
    else:
        ax.set_title("Tile section profile")
    if is_bread:
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=3)
    else:
        ax.legend(loc="best")
    ax.grid(True, color="#d0d0d0", linewidth=0.7)
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)
    return output_path


def write_block_png_preview(
    profile: BlockGuideSection,
    machine: MachineConfig,
    path: str | Path,
) -> Path:
    """Render the block-guide section and side view for a generated task."""
    output_path = Path(path)
    guide = profile.guide_spec
    side = build_side_view_geometry(profile, layout=machine.side_layout)  # type: ignore[arg-type]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig, (ax_section, ax_side) = plt.subplots(1, 2, figsize=(11, 4.5))

    slot_width = guide.guide_slot_width
    thickness = guide.guide_thickness
    radius = guide.relief.relief_size / 2.0
    left = -slot_width / 2.0
    right = slot_width / 2.0
    bottom = 0.0
    top = thickness
    ax_section.plot([left + radius, right - radius], [bottom, bottom], color="#1f77b4")
    ax_section.plot([right, right], [bottom + radius, top - radius], color="#1f77b4")
    ax_section.plot([right - radius, left + radius], [top, top], color="#1f77b4")
    ax_section.plot([left, left], [top - radius, bottom + radius], color="#1f77b4")
    for center_x, center_y, start_angle, end_angle in (
        (left + radius, bottom + radius, 180, 270),
        (right - radius, bottom + radius, 270, 360),
        (right - radius, top - radius, 0, 90),
        (left + radius, top - radius, 90, 180),
    ):
        ax_section.add_patch(
            Arc(
                (center_x, center_y),
                2 * radius,
                2 * radius,
                theta1=start_angle,
                theta2=end_angle,
                color="#1f77b4",
            )
        )
    ax_section.set_aspect("equal", adjustable="box")
    ax_section.set_title(f"slot {slot_width:.2f} x {thickness:.2f}")
    ax_section.grid(True, linewidth=0.3)

    layout = side.layout
    ax_side.plot([layout.left_x, layout.right_x], [layout.lower_y, layout.lower_y], color="#444444")
    ax_side.plot([layout.left_x, layout.right_x], [layout.upper_y, layout.upper_y], color="#444444")
    for center_x in (layout.left_x, layout.center_a_x, layout.center_b_x, layout.right_x):
        ax_side.plot([center_x, center_x], [layout.lower_y, layout.upper_y], color="#777777", linewidth=0.8)
    upper_center_y = layout.upper_y - side.derived.side_clearance_height + side.template.wheel_radius
    for center_x in (layout.center_a_x, layout.center_b_x):
        ax_side.add_patch(Arc((center_x, upper_center_y), 160, 160, theta1=200, theta2=340, color="#1f77b4"))
    ax_side.set_aspect("equal", adjustable="box")
    ax_side.set_title(f"{machine.machine_id} {machine.guide_length:.0f} mm")
    ax_side.grid(True, linewidth=0.3)

    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)
    return output_path


def _profiles_for_preview(profile: SectionProfile | TileSection):
    if isinstance(profile, TileSection):
        guide = profile.guide_spec
        if profile.preform_block_spec is not None:
            return (
                (profile.finished_profile, "finished_profile", "#7a7a7a", "--", 0.0, 0.0),
            )
        return (
            (profile.finished_profile, "finished_profile", "#7a7a7a", "--", 0.0, 0.0),
            (
                profile.forming_profile,
                "forming_profile in slot",
                "#d62728",
                "-",
                guide.slot_center_offset,
                guide.slot_base_height,
            ),
        )
    return ((profile, profile.params.profile_type, "#202020", "-", 0.0, 0.0),)


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


def _draw_dimension_annotations(
    ax: plt.Axes,
    tile_section: TileSection,
    half_outer: float,
    half_slot: float,
    base_y: float,
    top_y: float,
    x_center: float,
) -> None:
    guide = tile_section.guide_spec
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

    if tile_section.process_type in {"tile", "block_to_tile", "block_to_bread"}:
        ax.plot(
            [x_center + 1.2, right_x + 3.8],
            [top_y + 0.2, top_y + 3.2],
            color=color,
            linewidth=1.0,
        )
        ax.text(
            right_x + 4.1,
            top_y + 3.2,
            f"R{tile_section.forming_spec.R_form:.2f}",
            va="center",
            **text_style,
        )
    if tile_section.process_type == "tile":
        ax.plot(
            [x_center - 1.2, left_x - 5.2],
            [base_y + 0.2, base_y - 2.2],
            color=color,
            linewidth=1.0,
        )
        ax.text(left_x - 5.6, base_y - 2.2, f"R{tile_section.forming_spec.R_form:.2f}", ha="right", va="center", **text_style)

    ax.plot([left_x, left_x - 6.4], [top_y - guide.relief.relief_size / 2.0, top_y + 1.0], color=color, linewidth=1.0)
    ax.text(left_x - 6.8, top_y + 1.0, guide.relief.relief_label, ha="right", va="center", **text_style)

    opening_half = guide.center_opening / 2.0
    opening_dim_y = guide.outer_height + 3.0
    _plot_dimension_line(ax, (x_center - opening_half, guide.outer_height), (x_center - opening_half, opening_dim_y), color)
    _plot_dimension_line(ax, (x_center + opening_half, guide.outer_height), (x_center + opening_half, opening_dim_y), color)
    _plot_dimension_line(ax, (x_center - opening_half, opening_dim_y), (x_center + opening_half, opening_dim_y), color)
    ax.text(x_center, opening_dim_y + 0.45, f"{guide.center_opening:.1f}", ha="center", va="bottom", **text_style)

    outer_width_y = guide.outer_height + 7.2
    _plot_dimension_line(ax, (-half_outer, guide.outer_height), (-half_outer, outer_width_y), color)
    _plot_dimension_line(ax, (half_outer, guide.outer_height), (half_outer, outer_width_y), color)
    _plot_dimension_line(ax, (-half_outer, outer_width_y), (half_outer, outer_width_y), color)
    ax.text(x_center, outer_width_y + 0.45, f"{guide.outer_width:.0f}", ha="center", va="bottom", **text_style)

    outer_height_x = -half_outer - 5.2
    _plot_dimension_line(ax, (-half_outer, 0.0), (outer_height_x, 0.0), color)
    _plot_dimension_line(ax, (-half_outer, guide.outer_height), (outer_height_x, guide.outer_height), color)
    _plot_dimension_line(ax, (outer_height_x, 0.0), (outer_height_x, guide.outer_height), color)
    ax.text(outer_height_x - 0.45, guide.outer_height / 2.0, f"{guide.outer_height:.1f}", ha="right", va="center", **text_style)

    slot_base_x = half_outer + 7.0
    _plot_dimension_line(ax, (half_outer, 0.0), (slot_base_x, 0.0), color)
    _plot_dimension_line(ax, (right_x, base_y), (slot_base_x, base_y), color)
    _plot_dimension_line(ax, (slot_base_x, 0.0), (slot_base_x, base_y), color)
    ax.text(slot_base_x + 0.45, base_y / 2.0, f"{guide.slot_base_height:.1f}", va="center", **text_style)


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


def _draw_side_view_preview(
    ax: plt.Axes,
    tile_section: TileSection,
    side_layout: SideViewLayoutConfig | None = None,
) -> None:
    side = build_side_view_geometry(tile_section, layout=side_layout)
    layout = side.layout
    derived = side.derived
    color = "#3b5f9b"
    dim_color = "#6a3d9a"
    dx = 45.0 - layout.left_x
    tx = lambda x: x + dx
    xs = [tx(layout.left_x), tx(layout.right_x), tx(layout.right_x), tx(layout.left_x), tx(layout.left_x)]
    ys = [layout.lower_y, layout.lower_y, layout.upper_y, layout.upper_y, layout.lower_y]
    ax.plot(xs, ys, color=color, linewidth=1.2, label="side_view")
    ax.plot([tx(layout.center_a_x), tx(layout.center_a_x)], [layout.lower_y - 3.0, layout.upper_y + 3.0], color=color, linestyle=":", linewidth=0.9)
    ax.plot([tx(layout.center_b_x), tx(layout.center_b_x)], [layout.lower_y - 3.0, layout.upper_y + 3.0], color=color, linestyle=":", linewidth=0.9)
    ax.plot([tx(layout.left_x), tx(layout.right_x)], [layout.center_y, layout.center_y], color=color, linestyle="--", linewidth=0.9)
    projected_y = layout.lower_y + derived.side_projected_slot_height
    clearance_y = layout.upper_y - derived.side_clearance_height
    spans = (
        layout.center_a_x - layout.left_x,
        layout.center_b_x - layout.center_a_x,
        layout.right_x - layout.center_b_x,
    )
    span_centers = (
        (layout.left_x + layout.center_a_x) / 2.0,
        (layout.center_a_x + layout.center_b_x) / 2.0,
        (layout.center_b_x + layout.right_x) / 2.0,
    )
    for span, center_x in zip(spans, span_centers):
        ax.text(
            tx(center_x),
            layout.upper_y + 8.0,
            f"{span:.0f}",
            color=dim_color,
            fontsize=8,
            ha="center",
        )
    ax.text(
        tx((layout.left_x + layout.right_x) / 2.0),
        layout.lower_y - 10.0,
        f"{layout.right_x - layout.left_x:.0f}",
        color=dim_color,
        fontsize=8,
        ha="center",
    )
    ax.text(tx(layout.center_b_x + 18.0), layout.lower_y - 22.0, "R80", color=dim_color, fontsize=8)
    ax.text(tx(layout.left_x - 18.0), projected_y, f"{derived.side_projected_slot_height:.2f}", color=dim_color, fontsize=8, va="center")
    ax.text(tx(layout.right_x + 8.0), clearance_y, f"{derived.side_clearance_height:.2f}", color=dim_color, fontsize=8, va="center")


def _offset_points(points: list[Point], dx: float, dy: float) -> list[Point]:
    return [Point(point.x + dx, point.y + dy) for point in points]

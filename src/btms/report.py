"""Static trade-off chart for a design study (matplotlib, PNG/SVG).

Panel A: every design on mass overhead vs auxiliary energy. Feasible designs
are filled, infeasible ones hollow; the trade-off front is drawn through the
feasible non-dominated designs and the three picks are labelled.
Panel B: peak cell temperature for every cooling option x PCM thickness, so
each point in panel A can be traced to its design.

Colours follow the dataviz reference palette: categorical slots 1-3 for the
three cooling kinds (validated all-pairs), a one-hue blue ramp for temperature.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .design import StudyResult

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#e1e0d9"
KIND_COLOR = {"natural": "#2a78d6", "air": "#eb6834", "liquid": "#1baf7a"}
BLUE_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
PICK_LABEL = {"lightest": "Lightest", "lowest_energy": "Lowest energy", "balanced": "Balanced"}


def _design_name(row) -> str:
    pcm = "no PCM" if row.pcm_mm == 0 else f"{row.pcm_mm:g} mm PCM"
    return f"{row.cooling}, {pcm}"


def plot_tradeoff(result: StudyResult, path: str | Path | None = None):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.lines import Line2D

    t = result.table
    s = result.study
    plt.rcParams.update(
        {
            "font.size": 10,
            "axes.edgecolor": GRID,
            "axes.labelcolor": TEXT_2,
            "xtick.color": TEXT_2,
            "ytick.color": TEXT_2,
            "axes.titlecolor": TEXT,
        }
    )
    fig, (ax, hx) = plt.subplots(1, 2, figsize=(14, 6.2), gridspec_kw={"width_ratios": [1.15, 1]})
    fig.patch.set_facecolor(SURFACE)
    for a in (ax, hx):
        a.set_facecolor(SURFACE)

    # ---- Panel A: trade-off scatter -------------------------------------
    ax.grid(True, color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for kind, color in KIND_COLOR.items():
        sub = t[t.cooling_kind == kind]
        ok = sub[sub.feasible]
        bad = sub[~sub.feasible]
        ax.scatter(
            ok.mass_overhead_pct, ok.aux_energy_pct, s=70, color=color, edgecolors=SURFACE, linewidths=2, zorder=3
        )
        ax.scatter(
            bad.mass_overhead_pct,
            bad.aux_energy_pct,
            s=70,
            facecolors=SURFACE,
            edgecolors=color,
            linewidths=1.6,
            zorder=3,
        )
    front = result.front.sort_values("mass_overhead_pct")
    if len(front) > 1:
        # Staircase: everything above-right of it is dominated.
        xs, ys = [], []
        for _, r in front.iterrows():
            if xs:
                xs.append(r.mass_overhead_pct)
                ys.append(ys[-1])
            xs.append(r.mass_overhead_pct)
            ys.append(r.aux_energy_pct)
        ax.plot(xs, ys, color=TEXT_2, linewidth=2, zorder=2)
    # Label each distinct pick once.
    labelled: dict[int, list[str]] = {}
    for key, row in result.picks.items():
        labelled.setdefault(row.name, []).append(PICK_LABEL[key])
    x_span = max(t.mass_overhead_pct.max() - t.mass_overhead_pct.min(), 1)
    y_span = max(t.aux_energy_pct.max() - t.aux_energy_pct.min(), 0.1)
    for i, names in labelled.items():
        r = t.loc[i]
        ax.scatter(
            [r.mass_overhead_pct], [r.aux_energy_pct], s=260, facecolors="none", edgecolors=TEXT, linewidths=2, zorder=4
        )
        dx = 0.04 * x_span
        dy = 0.06 * y_span
        ax.annotate(
            f"{' / '.join(names)}\n{_design_name(r)}\n{r.T_peak_C:.1f} °C peak",
            (r.mass_overhead_pct, r.aux_energy_pct),
            xytext=(r.mass_overhead_pct + dx, r.aux_energy_pct + dy),
            fontsize=9,
            color=TEXT,
            arrowprops={"arrowstyle": "-", "color": TEXT_2, "linewidth": 1},
            zorder=5,
        )
    ax.set_xlabel("Mass added per cell (PCM + sleeve + cooling hardware), % of cell mass")
    ax.set_ylabel("Fan/pump energy, % of energy moved by the cell")
    ax.set_title("A  Trade-off: lower-left is better", loc="left", fontweight="bold")
    handles = [Line2D([], [], marker="o", linestyle="", markersize=8, color=c, label=k) for k, c in KIND_COLOR.items()]
    handles += [
        Line2D([], [], marker="o", linestyle="", markersize=8, color=TEXT_2, label="meets limits"),
        Line2D(
            [],
            [],
            marker="o",
            linestyle="",
            markersize=8,
            markerfacecolor=SURFACE,
            markeredgecolor=TEXT_2,
            label="fails limits",
        ),
        Line2D([], [], color=TEXT_2, linewidth=2, label="trade-off front"),
    ]
    ax.legend(handles=handles, loc="upper right", frameon=False, fontsize=9, labelcolor=TEXT)

    # ---- Panel B: peak temperature grid ----------------------------------
    rows = list(dict.fromkeys(t.cooling))
    cols = sorted(t.pcm_mm.unique())
    grid = t.pivot(index="cooling", columns="pcm_mm", values="T_peak_C").loc[rows, cols]
    feas = t.pivot(index="cooling", columns="pcm_mm", values="feasible").loc[rows, cols]
    reason = t.pivot(index="cooling", columns="pcm_mm", values="fail_reason").loc[rows, cols]
    cmap = LinearSegmentedColormap.from_list("blue", BLUE_RAMP)
    vmin = s.requirements.T_env_C
    vmax = max(float(np.nanmax(grid.values)), t.T_limit_C.iloc[0] + 1)
    hx.imshow(grid.values, cmap=cmap, vmin=vmin, vmax=vmax, aspect="auto")
    # 2px surface gaps between cells.
    hx.set_xticks(np.arange(-0.5, len(cols)), minor=True)
    hx.set_yticks(np.arange(-0.5, len(rows)), minor=True)
    hx.grid(which="minor", color=SURFACE, linewidth=2)
    hx.tick_params(which="minor", length=0)
    for sp in hx.spines.values():
        sp.set_visible(False)
    for yi, rname in enumerate(rows):
        for xi, c in enumerate(cols):
            val = grid.iat[yi, xi]
            frac = (val - vmin) / (vmax - vmin)
            ink = "#ffffff" if frac > 0.45 else TEXT
            if feas.iat[yi, xi]:
                hx.text(xi, yi, f"{val:.1f}", ha="center", va="center", fontsize=9, color=ink)
            else:
                hx.text(xi, yi - 0.12, f"{val:.1f} ✕", ha="center", va="center", fontsize=9, color=ink)
                hx.text(xi, yi + 0.2, reason.iat[yi, xi], ha="center", va="center", fontsize=7, color=ink)
    for i in labelled:
        r = t.loc[i]
        yi, xi = rows.index(r.cooling), cols.index(r.pcm_mm)
        hx.add_patch(
            matplotlib.patches.Rectangle((xi - 0.47, yi - 0.47), 0.94, 0.94, fill=False, edgecolor=TEXT, linewidth=2)
        )
    hx.set_xticks(range(len(cols)), [f"{c:g}" for c in cols])
    hx.set_yticks(range(len(rows)), rows)
    hx.set_xlabel(
        "PCM thickness, mm\n✕ fails: hot = peak over limit · uneven = in-cell ΔT over limit · slow = not ready in time"
    )
    hx.set_title(
        "B  Peak cell temperature, °C",
        loc="left",
        fontweight="bold",
    )

    fig.suptitle(
        f"{s.cell.name}: {s.duty.name}, {s.requirements.T_env_C:g} °C ambient",
        x=0.01,
        ha="left",
        fontsize=13,
        fontweight="bold",
        color=TEXT,
    )
    fig.text(
        0.01,
        0.005,
        f"Limits: peak ≤ {t.T_limit_C.iloc[0]:g} °C, in-cell ΔT ≤ {s.requirements.dT_cell_max_C:g} °C, "
        f"{result._recovery_text()}. Picks re-checked at R0 = {s.cell.R0_range[1] * 1e3:g} mΩ. "
        f"Fan/pump power per cell assumes a {s.cells_in_pack}-cell pack.",
        fontsize=8.5,
        color=TEXT_2,
    )
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))
    if path is not None:
        fig.savefig(path, dpi=150, facecolor=SURFACE)
    return fig

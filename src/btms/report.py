"""Static trade-off chart for a design study (matplotlib, PNG/SVG).

Panel A: every design on mass overhead vs auxiliary energy. Feasible designs
are filled, infeasible ones hollow; chilled-liquid designs are squares. The
trade-off front is drawn through the feasible non-dominated designs and the
picks are labelled.
Panel B: peak cell temperature for every cooling option x PCM choice, so
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
    return f"{row.cooling}, {row.pcm}"


def _upper(ax, y) -> bool:
    """Is data value y in the upper half of the axes (any y scale)?"""
    ax.figure.canvas.draw_idle()
    lo, hi = ax.get_ylim()
    f = ax.transScale.transform
    a, b, c = f((0, lo))[1], f((0, hi))[1], f((0, y))[1]
    return (c - a) / (b - a) > 0.55 if b != a else False


def plot_tradeoff(result: StudyResult, path: str | Path | None = None):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.lines import Line2D
    from matplotlib.patches import Rectangle

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
    rows = list(dict.fromkeys(t.cooling))
    cols = list(dict.fromkeys(t.pcm))
    grid_w = max(6.5, 0.9 * len(cols) + 1.5)
    height = max(6.4, 0.34 * len(rows) + 2.6)
    fig, (ax, hx) = plt.subplots(1, 2, figsize=(8.0 + grid_w, height), gridspec_kw={"width_ratios": [8.0, grid_w]})
    fig.patch.set_facecolor(SURFACE)
    for a in (ax, hx):
        a.set_facecolor(SURFACE)

    # ---- Panel A: trade-off scatter -------------------------------------
    ax.grid(True, color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    chilled = t.chilled.to_numpy() if "chilled" in t else np.zeros(len(t), dtype=bool)
    for kind, color in KIND_COLOR.items():
        for is_chilled, marker in ((False, "o"), (True, "s")):
            sub = t[(t.cooling_kind == kind).to_numpy() & (chilled == is_chilled)]
            ok, bad = sub[sub.feasible], sub[~sub.feasible]
            kw = {"s": 55, "marker": marker, "zorder": 3}
            ax.scatter(ok.mass_overhead_pct, ok.aux_energy_pct, color=color, edgecolors=SURFACE, linewidths=2, **kw)
            ax.scatter(
                bad.mass_overhead_pct, bad.aux_energy_pct, facecolors=SURFACE, edgecolors=color, linewidths=1.4, **kw
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
    ax.set_xlabel(result.mass_axis_label)
    ax.set_ylabel("Fan, pump and chiller energy, % of energy moved by the cell")
    pos = t.aux_energy_pct[t.aux_energy_pct > 0]
    if len(pos) and t.aux_energy_pct.max() > 20 * max(pos.min(), 1e-4):
        lin = 10.0 ** np.floor(np.log10(max(pos.min(), 1e-4)))
        ax.set_yscale("symlog", linthresh=lin)
        ax.set_ylabel(ax.get_ylabel() + f" (log above {lin:g})")
    labelled: dict[int, list[str]] = {}
    for key, row in result.picks.items():
        labelled.setdefault(row.name, []).append(PICK_LABEL[key])
    for k, (i, names) in enumerate(labelled.items()):
        r = t.loc[i]
        ax.scatter(
            [r.mass_overhead_pct], [r.aux_energy_pct], s=240, facecolors="none", edgecolors=TEXT, linewidths=2, zorder=4
        )
        ax.annotate(
            f"{' / '.join(names)}\n{_design_name(r)}\n{r.T_peak_C:.1f} °C peak",
            (r.mass_overhead_pct, r.aux_energy_pct),
            # Labels go below-right of picks in the upper half of the axes,
            # above-right otherwise, so they stay inside the plot.
            xytext=(18, (-62 - 44 * k) if _upper(ax, r.aux_energy_pct) else (28 + 44 * k)),
            textcoords="offset points",
            fontsize=9,
            color=TEXT,
            arrowprops={"arrowstyle": "-", "color": TEXT_2, "linewidth": 1},
            zorder=5,
        )
    ax.set_title("A  Trade-off: lower-left is better", loc="left", fontweight="bold")
    names = result.kind_names
    handles = [
        Line2D([], [], marker="o", linestyle="", markersize=8, color=c, label=names.get(k, k))
        for k, c in KIND_COLOR.items()
        if (t.cooling_kind == k).any()
    ]
    if chilled.any():
        handles.append(
            Line2D([], [], marker="s", linestyle="", markersize=8, color=KIND_COLOR["liquid"], label="liquid + chiller")
        )
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
    ax.legend(
        handles=handles,
        loc="lower right",
        ncol=2,
        framealpha=0.92,
        facecolor=SURFACE,
        edgecolor=GRID,
        fontsize=8.5,
        labelcolor=TEXT,
        handletextpad=0.3,
        columnspacing=1.0,
    )

    # ---- Panel B: peak temperature grid ----------------------------------
    grid = t.pivot(index="cooling", columns="pcm", values="T_peak_C").loc[rows, cols]
    feas = t.pivot(index="cooling", columns="pcm", values="feasible").loc[rows, cols]
    reason = t.pivot(index="cooling", columns="pcm", values="fail_reason").loc[rows, cols]
    cmap = LinearSegmentedColormap.from_list("blue", BLUE_RAMP)
    vmin = min(s.requirements.T_env_C, float(np.nanmin(grid.values)))
    vmax = max(float(np.nanmax(grid.values)), t.T_limit_C.iloc[0] + 1)
    hx.imshow(grid.values.astype(float), cmap=cmap, vmin=vmin, vmax=vmax, aspect="auto")
    # 2px surface gaps between cells.
    hx.set_xticks(np.arange(-0.5, len(cols)), minor=True)
    hx.set_yticks(np.arange(-0.5, len(rows)), minor=True)
    hx.grid(which="minor", color=SURFACE, linewidth=2)
    hx.tick_params(which="minor", length=0)
    for sp in hx.spines.values():
        sp.set_visible(False)
    compact = len(rows) > 9
    for yi in range(len(rows)):
        for xi in range(len(cols)):
            val = grid.iat[yi, xi]
            if not np.isfinite(val):
                hx.add_patch(Rectangle((xi - 0.5, yi - 0.5), 1, 1, color=SURFACE, zorder=2))
                hx.text(xi, yi, "n/a", ha="center", va="center", fontsize=7.5, color=TEXT_2, zorder=3)
                continue
            ink = "#ffffff" if (val - vmin) / (vmax - vmin) > 0.45 else TEXT
            if feas.iat[yi, xi]:
                hx.text(xi, yi, f"{val:.1f}", ha="center", va="center", fontsize=8 if compact else 9, color=ink)
            elif compact:
                hx.text(xi, yi, f"{val:.1f} ✕ {reason.iat[yi, xi]}", ha="center", va="center", fontsize=6.5, color=ink)
            else:
                hx.text(xi, yi - 0.12, f"{val:.1f} ✕", ha="center", va="center", fontsize=9, color=ink)
                hx.text(xi, yi + 0.2, reason.iat[yi, xi], ha="center", va="center", fontsize=7, color=ink)
    for i in labelled:
        r = t.loc[i]
        yi, xi = rows.index(r.cooling), cols.index(r.pcm)
        hx.add_patch(Rectangle((xi - 0.47, yi - 0.47), 0.94, 0.94, fill=False, edgecolor=TEXT, linewidth=2))
    hx.set_xticks(range(len(cols)), cols, rotation=35, ha="right")
    hx.set_yticks(range(len(rows)), rows)
    hx.set_xlabel(
        f"{result.filler_axis_label}\n✕ fails: hot = peak over limit · uneven = in-cell ΔT over limit\n"
        "slow = not ready in time"
        + (" · spread = inlet-to-outlet over limit" if "spread" in "".join(t.fail_reason) else "")
    )
    hx.set_title("B  Peak cell temperature, °C", loc="left", fontweight="bold")

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
        f"{result._recovery_text()}. {result.footnote()}",
        fontsize=8.5,
        color=TEXT_2,
    )
    fig.tight_layout(rect=(0, 0.03, 1, 0.96))
    if path is not None:
        fig.savefig(path, dpi=140, facecolor=SURFACE)
    return fig

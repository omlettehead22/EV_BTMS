"""Draw docs/figures/fields_2d.png: temperature inside one M50 cell's share.

Three moments from the 2D models (v0.4.8, v0.4.9), each re-run to the instant
that matters so the field shown is the field at that time:

A  bottom plate, 1.5C full discharge at 25 degC, outlet cell, at peak temperature
B  bottom plate with a 15 degC chiller on a 35 degC day, 0.45C discharge, at the
   largest in-cell spread (pull-down of a hot-soaked pack)
C  side ribbon, 1.5C full discharge at 25 degC, outlet cell, at peak temperature
   (radius x angle, mirrored to a full top view)

Run: python docs/figures/make_fields.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

from packtherm.cells import LG_M50
from packtherm.design import DutyCycle
from packtherm.module import BottomPlate, Coolant, Layout, Module, SideRibbon, simulate_module
from packtherm.params import KELVIN

TEXT, TEXT_2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e1e0d9", "#fcfcfb"
COOL = "#1baf7a"
BLUES = LinearSegmentedColormap.from_list(
    "blues", ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
)
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 9.5,
        "text.color": TEXT,
        "axes.labelcolor": TEXT_2,
        "xtick.color": TEXT_2,
        "ytick.color": TEXT_2,
        "axes.edgecolor": GRID,
    }
)


def at_moment(cell, module, duty, T_amb, pick):
    """Run once to find the moment, then re-run to it so res.T is that field."""
    prof = duty.profile(cell)
    kw = {"soc0": duty.soc0, "soc_limits": duty.soc_limits}
    full = simulate_module(cell, module, prof, duty.event_duration(), T_amb, **kw)
    t_star = float(full.res.t[pick(full)])
    snap = simulate_module(cell, module, prof, max(t_star, 2.0), T_amb, **kw)
    return snap, t_star


def main() -> Path:
    cell = LG_M50
    dis15 = DutyCycle.constant(1.5, "discharge")
    plate = Module(Layout("hex", 2.0), None, BottomPlate())
    chilled = Module(Layout("hex", 2.0), None, BottomPlate(coolant=Coolant(inlet_C=15.0)))
    ribbon = Module(Layout("hex", 3.5), None, SideRibbon())

    A, tA = at_moment(cell, plate, dis15, 25.0, lambda r: int(np.argmax(r.res.T_max)))
    B, tB = at_moment(
        cell, chilled, DutyCycle.constant(0.45, "discharge"), 35.0, lambda r: int(np.argmax(r.res.dT_cell))
    )
    C, tC = at_moment(cell, ribbon, dis15, 25.0, lambda r: int(np.argmax(r.res.T_max)))

    fig = plt.figure(figsize=(12.5, 5.4), facecolor=SURFACE)
    gs = fig.add_gridspec(1, 3, width_ratios=[1, 1, 1.3], wspace=0.6)
    r_cell = cell.radius * 1e3
    L = cell.height * 1e3

    def rz_panel(ax, res, title, sub, t_s):
        r = res.res.r * 1e3
        nz = res.res.T.shape[1]
        T = res.res.T - KELVIN  # radius x height
        r_edges = np.r_[0, 0.5 * (r[1:] + r[:-1]), r[-1] + (r[-1] - r[-2]) / 2]
        z_edges = np.linspace(0, L, nz + 1)
        m = ax.pcolormesh(r_edges, z_edges, T.T, cmap=BLUES, shading="flat")
        ax.axvline(r_cell, color=TEXT, lw=0.8, ls=(0, (3, 2)))
        ax.add_patch(plt.Rectangle((0, -4.2), r_edges[-1], 3.6, color=COOL, clip_on=False))
        ax.text(
            r_edges[-1] / 2, -2.4, "cold plate", ha="center", va="center", color="white", fontsize=8, fontweight="bold"
        )
        ax.set_xlim(0, r_edges[-1])
        ax.set_ylim(0, L)
        ax.set_xlabel("radius [mm]", labelpad=4)
        ax.tick_params(axis="x", pad=16)
        ax.set_ylabel("height [mm]")
        ax.set_title(title, loc="left", fontsize=10.5, fontweight="bold", color=TEXT, pad=20)
        ax.text(0, 1.02, sub + f", t = {t_s / 60:.0f} min", transform=ax.transAxes, fontsize=8.5, color=TEXT_2)
        cb = fig.colorbar(m, ax=ax, fraction=0.06, pad=0.04)
        cb.set_label("°C")
        cb.outline.set_visible(False)
        top, base = T[: np.searchsorted(r, r_cell), -1].max(), T[: np.searchsorted(r, r_cell), 0].min()
        ax.text(r_cell * 0.5, L - 4, f"top {top:.1f} °C", ha="center", va="top", fontsize=8.5, color="white")
        ax.text(r_cell * 0.5, 4, f"bottom layer {base:.1f} °C", ha="center", va="bottom", fontsize=8.5, color=TEXT)

    rz_panel(fig.add_subplot(gs[0]), A, "A  Bottom plate, at peak", "1.5C at 25 °C, outlet cell", tA)
    rz_panel(
        fig.add_subplot(gs[1]),
        B,
        "B  Chilled plate, pull-down",
        "15 °C coolant, 35 °C day, 0.45C",
        tB,
    )

    ax = fig.add_subplot(gs[2], projection="polar")
    r = C.res.r * 1e3
    T = C.res.T - KELVIN  # radius x angle over half the circle, theta = 0 under the ribbon
    nt = T.shape[1]
    th_half = np.linspace(0, np.pi, nt + 1)
    th_edges = np.r_[-th_half[::-1], th_half[1:]]
    T_full = np.concatenate([T[:, ::-1], T], axis=1)
    r_edges = np.r_[0, 0.5 * (r[1:] + r[:-1]), r[-1] + (r[-1] - r[-2]) / 2]
    m = ax.pcolormesh(th_edges, r_edges, T_full, cmap=BLUES, shading="flat")
    contact = ribbon.cooling.contact_fraction * np.pi
    ax.plot(np.linspace(-contact, contact, 40), np.full(40, r_cell + 0.9), color=COOL, lw=5, solid_capstyle="butt")
    ax.plot(np.linspace(-np.pi, np.pi, 200), np.full(200, r_cell), color=TEXT, lw=0.8, ls=(0, (3, 2)))
    ax.set_theta_zero_location("E")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.spines["polar"].set_color(GRID)
    ax.set_ylim(0, r_edges[-1] + 1.2)
    ax.set_title("C  Side ribbon, at peak (top view)", loc="left", fontsize=10.5, fontweight="bold", color=TEXT, pad=30)
    ax.text(
        -0.02,
        1.07,
        f"1.5C at 25 °C, outlet cell, t = {tC / 60:.0f} min",
        transform=ax.transAxes,
        fontsize=8.5,
        color=TEXT_2,
    )
    i_can = int(np.searchsorted(r, r_cell)) - 1
    near, far = T[i_can, 0], T[i_can, -1]
    core = T[0, :].max()
    ax.text(
        0.42,
        -0.08,
        f"ribbon side {near:.1f} °C  ·  far side {far:.1f} °C  ·  centre {core:.1f} °C\n"
        "green arc: ribbon contact (a quarter of the can)",
        transform=ax.transAxes,
        ha="center",
        va="top",
        fontsize=8.5,
        color=TEXT_2,
    )
    cb = fig.colorbar(m, ax=ax, fraction=0.05, pad=0.12)
    cb.set_label("°C")
    cb.outline.set_visible(False)

    fig.text(
        0.01,
        -0.03,
        "LG M50, hex packing, air in the gaps, so each field is the cell itself (dashed line: can wall). "
        "Separate colour scales per panel.",
        fontsize=8,
        color=TEXT_2,
    )
    out = Path(__file__).with_name("fields_2d.png")
    fig.savefig(out, dpi=180, bbox_inches="tight", facecolor=SURFACE)
    print(f"Wrote {out}: A t={tA:.0f}s, B t={tB:.0f}s, C t={tC:.0f}s")
    return out


if __name__ == "__main__":
    main()

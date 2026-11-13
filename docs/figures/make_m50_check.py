"""Draw docs/validation/m50_vs_dfn.png from validation/m50_vs_dfn.csv.

Irreversible heat of the derived M50 circuit and the old lumped model, each
divided by the physics model's (PyBaMM DFN, ORegan2022). Produce the CSV with
python validation/check_m50_ecm.py (needs pybamm).
Run: python docs/figures/make_m50_check.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

TEXT, TEXT_2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e1e0d9", "#fcfcfb"
CIRCUIT, LUMPED = "#2a78d6", "#eb6834"
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
ROOT = Path(__file__).resolve().parents[2]


def main() -> Path:
    d = pd.read_csv(ROOT / "validation" / "m50_vs_dfn.csv")
    labels = [f"{r.case}, {r.ambient_C:g} °C" for r in d.itertuples()]
    y = np.arange(len(d))[::-1]
    fig, ax = plt.subplots(figsize=(7.5, 5.2), facecolor=SURFACE)
    ax.axvspan(0.9, 1.1, color="#f0efec", zorder=0)
    ax.axvline(1.0, color=TEXT_2, lw=1, zorder=1)
    for yi, a, b in zip(y, d.ratio_circuit, d.ratio_lumped):
        ax.plot([a, b], [yi, yi], color=GRID, lw=1.5, zorder=1)
    ax.scatter(
        d.ratio_lumped,
        y,
        s=46,
        color=LUMPED,
        edgecolor=SURFACE,
        linewidth=1.5,
        zorder=3,
        label="lumped resistance (old)",
    )
    ax.scatter(
        d.ratio_circuit,
        y,
        s=46,
        color=CIRCUIT,
        edgecolor=SURFACE,
        linewidth=1.5,
        zorder=4,
        label="derived circuit (v0.4.11)",
    )
    ax.set_yticks(y, labels)
    ax.set_xlabel("irreversible heat ÷ physics model (1.0 = agrees; shaded ±10 %)")
    ax.set_xlim(0.85, 1.48)
    ax.grid(axis="x", color=GRID, lw=0.8, zorder=0)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(length=0)
    ax.legend(frameon=False, loc="lower right", fontsize=8.5)
    ax.set_title("LG M50 heat: derived circuit vs the old lumped model", loc="left", fontsize=10.5, fontweight="bold")
    fig.text(
        0.01,
        -0.02,
        "Physics model: PyBaMM DFN with the ORegan2022 parameter set (measured on the LG M50T), self-heating.\n"
        "Both packtherm models follow its temperature path. Derived from a model, not from cell tests.",
        fontsize=8,
        color=TEXT_2,
    )
    fig.tight_layout()
    out = ROOT / "docs" / "validation" / "m50_vs_dfn.png"
    fig.savefig(out, dpi=180, bbox_inches="tight", facecolor=SURFACE)
    print(f"Wrote {out}")
    return out


if __name__ == "__main__":
    main()

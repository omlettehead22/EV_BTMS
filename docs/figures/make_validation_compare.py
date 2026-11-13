"""Draw docs/validation/cold_weather.png: blind validation before and after v0.4.10.

Reads docs/validation/summary_v0.4.9.csv (results before the cold-weather laws)
and docs/validation/summary.csv (current). Predictive mode, the 48 blind tests.
Run: python docs/figures/make_validation_compare.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

TEXT, TEXT_2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e1e0d9", "#fcfcfb"
BEFORE, AFTER = "#b9b8b1", "#2a78d6"
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
VAL = Path(__file__).resolve().parents[1] / "validation"


def load(name):
    d = pd.read_csv(VAL / name)
    return d[(d.role != "calibration") & (d["mode"] == "predictive")]


def main() -> Path:
    old, new = load("summary_v0.4.9.csv"), load("summary.csv")
    amb = [25.0, 10.0, 0.0, -10.0, -20.0]
    metrics = [
        ("T_rmse_K", "Temperature error (median RMSE, K)", "{:.2f}"),
        ("V_rmse_pre_knee_mV", "Voltage error (median RMSE before the knee, mV)", "{:.0f}"),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.9), facecolor=SURFACE)
    x = np.arange(len(amb))
    w = 0.36
    for ax, (col, title, fmt) in zip(axes, metrics):
        a = [old[old.ambient_C == T][col].median() for T in amb]
        b = [new[new.ambient_C == T][col].median() for T in amb]
        ax.bar(x - w / 2 - 0.01, a, w, color=BEFORE, label="v0.4.9", zorder=2)
        ax.bar(x + w / 2 + 0.01, b, w, color=AFTER, label="v0.4.10 (cold-weather laws)", zorder=2)
        for xi, v in zip(x, b):
            ax.text(xi + w / 2 + 0.01, v, fmt.format(v), ha="center", va="bottom", fontsize=8, color=TEXT)
        for xi, v in zip(x, a):
            ax.text(xi - w / 2 - 0.01, v, fmt.format(v), ha="center", va="bottom", fontsize=8, color=TEXT_2)
        ax.set_xticks(x, [f"{T:g} °C" for T in amb])
        ax.set_title(title, loc="left", fontsize=10, fontweight="bold", color=TEXT)
        ax.grid(axis="y", color=GRID, lw=0.8, zorder=0)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.tick_params(length=0)
        ax.set_xlabel("chamber temperature")
    axes[0].legend(frameon=False, loc="upper left", fontsize=8.5)
    w_old, w_new = (old.T_rmse_K <= 1).mean() * 100, (new.T_rmse_K <= 1).mean() * 100
    fig.text(
        0.01,
        -0.04,
        f"Panasonic NCR18650PF, 48 blind tests, current in, voltage and temperature out. "
        f"Tests within 1 K: {w_old:.0f} % before, {w_new:.0f} % after.",
        fontsize=8.5,
        color=TEXT_2,
    )
    fig.tight_layout()
    out = VAL / "cold_weather.png"
    fig.savefig(out, dpi=180, bbox_inches="tight", facecolor=SURFACE)
    print(f"Wrote {out}")
    return out


if __name__ == "__main__":
    main()

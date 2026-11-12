"""Run the full Panasonic NCR18650PF validation and write the report figures.

Usage:
    python validation/run_panasonic.py [--recalibrate]

Writes docs/validation/summary.csv and three figures:
    traces.png   measured vs modelled temperature, US06 at every ambient
    errors.png   temperature RMSE of every test, both modes
    charge.png   1C CC-CV charge: current, voltage and temperature
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from packtherm.validation import H_CHAMBER, RD_25C, TAU_D, calibrate, load_tests, validate

OUT = Path(__file__).resolve().parents[1] / "docs" / "validation"
SURFACE, TEXT, TEXT_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e1e0d9"
MEAS = "#0b0b0b"
MODE_COLOR = {"thermal": "#2a78d6", "predictive": "#eb6834"}
MODE_LABEL = {"thermal": "model, heat from measured voltage", "predictive": "model, current only (fully predictive)"}


def style(ax):
    ax.set_facecolor(SURFACE)
    ax.grid(True, color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=TEXT_2)
    ax.xaxis.label.set_color(TEXT_2)
    ax.yaxis.label.set_color(TEXT_2)


def traces(results, path):
    names = ["25C_US06", "10C_US06", "0C_US06", "m10C_US06", "m20C_US06"]
    fig, axes = plt.subplots(1, len(names), figsize=(18, 4.2), sharey=False)
    fig.patch.set_facecolor(SURFACE)
    for ax, name in zip(axes, names):
        style(ax)
        rs = {r["mode"]: r for r in results if r["name"] == name}
        s = rs["thermal"]["series"]
        ax.plot(s["t"] / 60, s["T_meas"], color=MEAS, linewidth=2, label="measured (case thermocouple)")
        for mode in ("thermal", "predictive"):
            sm = rs[mode]["series"]
            ax.plot(sm["t"] / 60, sm["T_model"], color=MODE_COLOR[mode], linewidth=2, label=MODE_LABEL[mode])
        amb = rs["thermal"]["ambient_C"]
        ax.set_title(
            f"US06 at {amb:g} °C\nRMSE {rs['thermal']['T_rmse_K']:.2f} K / {rs['predictive']['T_rmse_K']:.2f} K",
            loc="left",
            fontsize=10,
            color=TEXT,
        )
        ax.set_xlabel("time, min")
    axes[0].set_ylabel("cell surface temperature, °C")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3, frameon=False, fontsize=9.5, labelcolor=TEXT)
    fig.suptitle(
        "Panasonic NCR18650PF, US06 drive cycle: blind predictions (h calibrated on one 25 °C 1C discharge)",
        x=0.01,
        ha="left",
        fontweight="bold",
        color=TEXT,
    )
    fig.tight_layout(rect=(0, 0.08, 1, 0.94))
    fig.savefig(path, dpi=140, facecolor=SURFACE)


def errors(table, path):
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.6))
    fig.patch.set_facecolor(SURFACE)
    temps = sorted(table.ambient_C.unique(), reverse=True)
    for ax, (col, label) in zip(
        axes, (("T_rmse_K", "temperature RMSE, K"), ("peak_error_K", "peak temperature error (model − measured), K"))
    ):
        style(ax)
        for k, mode in enumerate(("thermal", "predictive")):
            sub = table[table["mode"] == mode]
            x = np.array([temps.index(a) for a in sub.ambient_C]) + (k - 0.5) * 0.28
            jitter = (np.arange(len(sub)) % 5 - 2) * 0.03
            ax.scatter(
                x + jitter,
                sub[col],
                s=36,
                color=MODE_COLOR[mode],
                edgecolors=SURFACE,
                linewidths=1.5,
                label=MODE_LABEL[mode],
                zorder=3,
            )
        if col == "peak_error_K":
            ax.axhline(0, color=TEXT_2, linewidth=1)
        ax.set_xticks(range(len(temps)), [f"{t:g} °C" for t in temps])
        ax.set_xlabel("chamber temperature")
        ax.set_ylabel(label)
    axes[0].legend(loc="upper left", frameon=False, fontsize=9, labelcolor=TEXT)
    n = table.name.nunique()
    fig.suptitle(
        f"Every test ({n} tests × 2 modes): one calibration test, the rest blind",
        x=0.01,
        ha="left",
        fontweight="bold",
        color=TEXT,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(path, dpi=140, facecolor=SURFACE)


def charge(results, path):
    r = next(x for x in results if x["name"] == "25C_1C_CCCV_charge" and x["mode"] == "predictive")
    th = next(x for x in results if x["name"] == "25C_1C_CCCV_charge" and x["mode"] == "thermal")
    s = r["series"]
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.2))
    fig.patch.set_facecolor(SURFACE)
    panels = (
        (s["t_V"], -s["I_meas"], -s["I_model"], "charge current, A"),
        (s["t_V"], s["V_meas"], s["V_model"], "terminal voltage, V"),
        (s["t"], s["T_meas"], s["T_model"], "surface temperature, °C"),
    )
    for ax, (t, meas, model, label) in zip(axes, panels):
        style(ax)
        ax.plot(t / 60, meas, color=MEAS, linewidth=2, label="measured")
        ax.plot(t / 60, model, color=MODE_COLOR["predictive"], linewidth=2, label=MODE_LABEL["predictive"])
        ax.set_xlabel("time, min")
        ax.set_ylabel(label)
    axes[2].plot(
        th["series"]["t"] / 60,
        th["series"]["T_model"],
        color=MODE_COLOR["thermal"],
        linewidth=2,
        label=MODE_LABEL["thermal"],
    )
    axes[2].legend(loc="upper right", frameon=False, fontsize=8.5, labelcolor=TEXT)
    fig.suptitle(
        f"1C CC-CV charge at 25 °C: the model produces the CV taper itself (current RMSE {r['I_rmse_A']:.2f} A, peak error {r['peak_error_K']:+.1f} K)",
        x=0.01,
        ha="left",
        fontweight="bold",
        color=TEXT,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(path, dpi=140, facecolor=SURFACE)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recalibrate", action="store_true")
    args = ap.parse_args(argv)
    tests = load_tests()
    if args.recalibrate:
        print("calibration:", calibrate(tests))
    print(f"constants: h = {H_CHAMBER} W/m2K, Rd = {RD_25C * 1e3:.1f} mOhm, tau_d = {TAU_D:g} s")
    table, results = validate(tests)
    OUT.mkdir(parents=True, exist_ok=True)
    table.round(4).to_csv(OUT / "summary.csv", index=False)
    traces(results, OUT / "traces.png")
    errors(table, OUT / "errors.png")
    charge(results, OUT / "charge.png")
    g = table.groupby(["mode", "ambient_C"])
    print(
        g.agg(
            tests=("T_rmse_K", "size"),
            T_rmse_median=("T_rmse_K", "median"),
            T_rmse_max=("T_rmse_K", "max"),
            peak_err_abs_max=("peak_error_K", lambda x: x.abs().max()),
            V_pre_knee_median_mV=("V_rmse_pre_knee_mV", "median"),
        ).round(2)
    )


if __name__ == "__main__":
    main()

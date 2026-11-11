"""Command line interface.

btms thesis                      # the four MSc thesis scenarios
btms cell M50 --mode discharge --c-rate 1.5 --cooling air --level high --pcm-mm 3
btms cells                       # list the cell library
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

from .cells import CELLS, get_cell
from .electrothermal import check_limits, constant_current, simulate_cell
from .metrics import summarise_result, summary_table
from .params import DEFAULT_AUX_POWER, DEFAULT_H, KELVIN, default_params
from .scenarios import run_scenario, thesis_scenarios


def _thesis(args) -> None:
    P = default_params()
    pairs = []
    for sc in thesis_scenarios(P):
        t0 = time.perf_counter()
        res = run_scenario(P, sc)
        print(f"{sc.name:<20} T_peak={res.T_max.max() - KELVIN:6.2f} degC  ({time.perf_counter() - t0:.1f}s)")
        pairs.append((sc, res))
    df = summary_table(pairs)
    cols = ["Scenario", "T_peak_C", "MaxCellDifference_C", "PCM_utilisation", "E_aux_Wh", "BalanceError_pct"]
    with pd.option_context("display.width", 120, "display.precision", 4):
        print(df[cols].to_string(index=False))
    if args.out:
        df.to_csv(args.out, index=False)
        print(f"Wrote {args.out}")


def _cells(args) -> None:
    rows = [
        {
            "key": k,
            "name": c.name,
            "Ah": c.capacity_Ah,
            "R0_mOhm": c.R0_25C * 1e3,
            "mass_g": c.mass * 1e3,
            "max_chg_C": c.max_charge_C,
            "max_dis_C": round(c.max_discharge_C, 2) if c.max_discharge_C else None,
        }
        for k, c in CELLS.items()
    ]
    print(pd.DataFrame(rows).to_string(index=False))


def _cell(args) -> None:
    cell = get_cell(args.cell)
    h = args.h if args.h is not None else DEFAULT_H[args.cooling][args.level]
    T_env = args.t_env + KELVIN
    soc0 = args.soc0 if args.soc0 is not None else (1.0 if args.mode == "discharge" else 0.1)
    limits = (args.soc_min, args.soc_max)
    duration = args.duration or 3600 * (abs(limits[1] - limits[0]) / args.c_rate) * 1.05
    res, load = simulate_cell(
        cell,
        constant_current(cell, args.c_rate, args.mode),
        duration,
        h,
        T_env,
        pcm_thickness=args.pcm_mm * 1e-3,
        case_thickness=args.case_mm * 1e-3,
        soc0=soc0,
        soc_limits=limits,
    )
    m = summarise_result(res, aux_power_W=DEFAULT_AUX_POWER.get(args.cooling, {}).get(args.level, 0.0))
    a = load.arrays()
    print(f"{cell.name}: {args.mode} at {args.c_rate}C, {args.cooling} h={h:g} W/m2K, PCM {args.pcm_mm} mm")
    print(f"  SOC {soc0:.2f} -> {load.soc:.2f} in {duration / 60:.1f} min")
    print(f"  Peak cell temperature   {m['T_peak_C']:.2f} degC (at {m['TimeToPeak_s'] / 60:.1f} min)")
    print(f"  Max in-cell difference  {m['MaxCellDifference_C']:.2f} degC")
    print(
        f"  Heat generated          {res.E_generated / 1e3:.2f} kJ (reversible {a['Q_rev_W'].sum() / max(a['Q_irr_W'].sum(), 1e-12):+.0%} of irreversible)"
    )
    print(f"  PCM peak liquid frac    {m['PCM_fraction_peak']:.2f}")
    print(f"  Energy balance error    {res.balance_error_pct:.1e} %")
    for w in check_limits(cell, load, res):
        print(f"  WARNING: {w}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="btms", description="Battery thermal management design toolkit.")
    sub = ap.add_subparsers(dest="cmd")

    t = sub.add_parser("thesis", help="Run the four MSc thesis scenarios.")
    t.add_argument("--out", type=Path, help="Write summary CSV here.")
    t.set_defaults(func=_thesis)

    c = sub.add_parser("cells", help="List the cell library.")
    c.set_defaults(func=_cells)

    e = sub.add_parser("cell", help="Electro-thermal run of one cell at constant C-rate.")
    e.add_argument("cell", help=f"Cell key: {', '.join(CELLS)}")
    e.add_argument("--mode", choices=["charge", "discharge"], default="discharge")
    e.add_argument("--c-rate", type=float, default=1.0)
    e.add_argument("--cooling", choices=["air", "liquid", "none"], default="air")
    e.add_argument("--level", choices=["low", "mid", "high"], default="mid")
    e.add_argument("--h", type=float, help="Override convective coefficient [W/m2K].")
    e.add_argument("--pcm-mm", type=float, default=3.0)
    e.add_argument("--case-mm", type=float, default=1.0)
    e.add_argument("--t-env", type=float, default=25.0, help="Ambient/coolant [degC].")
    e.add_argument("--soc0", type=float)
    e.add_argument("--soc-min", type=float, default=0.0)
    e.add_argument("--soc-max", type=float, default=1.0)
    e.add_argument("--duration", type=float, help="Seconds (default: time to cross the SOC window +5%%).")
    e.set_defaults(func=_cell)

    args = ap.parse_args(argv)
    if args.cmd is None:
        args = ap.parse_args(["thesis", *(argv or [])])
    args.func(args)


if __name__ == "__main__":
    main()

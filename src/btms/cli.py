"""Command line entry point: ``btms`` runs the four thesis scenarios."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

from .metrics import summary_table
from .params import default_params
from .scenarios import run_scenario, thesis_scenarios


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Run the BTMS thesis scenarios.")
    ap.add_argument("--out", type=Path, help="Write summary CSV here.")
    args = ap.parse_args(argv)

    P = default_params()
    pairs = []
    for sc in thesis_scenarios(P):
        t0 = time.perf_counter()
        res = run_scenario(P, sc)
        print(f"{sc.name:<20} T_peak={res.T_max.max() - 273.15:6.2f} degC  ({time.perf_counter() - t0:.1f}s)")
        pairs.append((sc, res))
    df = summary_table(pairs)
    cols = ["Scenario", "T_peak_C", "MaxCellDifference_C", "PCM_utilisation", "E_aux_Wh", "BalanceError_pct"]
    with pd.option_context("display.width", 120, "display.precision", 4):
        print(df[cols].to_string(index=False))
    if args.out:
        df.to_csv(args.out, index=False)
        print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()

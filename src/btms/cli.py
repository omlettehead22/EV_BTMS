"""Command line interface.

btms thesis                      # the four MSc thesis scenarios
btms cell M50 --mode discharge --c-rate 1.5 --cooling air --level high --pcm-mm 3 --pcm-grade RT42
btms cells                       # list the cell library
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

from .cells import CELLS, get_cell
from .electrothermal import check_limits, constant_current, simulate_cell
from .materials import PCM_LIBRARY
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
    from .materials import get_pcm, melt_midpoint_C
    from .params import Params

    pcm = get_pcm(args.pcm_grade)
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
        base=Params(pcm=pcm),
    )
    m = summarise_result(res, aux_power_W=DEFAULT_AUX_POWER.get(args.cooling, {}).get(args.level, 0.0))
    a = load.arrays()
    pcm_text = (
        f"{args.pcm_grade} {args.pcm_mm:g} mm (melts ~{melt_midpoint_C(pcm):.0f} degC)" if args.pcm_mm > 0 else "none"
    )
    print(f"{cell.name}: {args.mode} at {args.c_rate}C, {args.cooling} h={h:g} W/m2K, PCM {pcm_text}")
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


def _design(args) -> None:
    import re

    from .design import DesignStudy, DutyCycle, Requirements, cooling_options, run_study, thesis_cooling_options
    from .ev import Pack, Vehicle, road_trip_duty, wltc_duty
    from .report import plot_tradeoff

    cell = get_cell(args.cell)
    rest = args.rest_h * 3600
    if args.duty == "constant":
        duty = DutyCycle.constant(
            args.c_rate, args.mode, soc0=args.soc0, soc_limits=(args.soc_min, args.soc_max), rest_after_s=rest
        )
        stem = f"{args.cell.lower()}_{args.mode}_{args.c_rate:g}C"
    else:
        pack = Pack.for_energy(cell, args.pack_kwh, args.pack_v)
        vehicle = Vehicle()
        if args.duty == "wltc":
            duty = wltc_duty(cell, pack, vehicle, cycles=args.cycles, rest_after_s=rest)
            stem = f"{args.cell.lower()}_wltc{args.cycles}"
        else:
            duty = road_trip_duty(
                cell, pack, vehicle, speed_kmh=args.speed, charge_c_rate=args.charge_c, rest_after_s=rest
            )
            stem = f"{args.cell.lower()}_roadtrip_{args.speed:g}kmh"
    stem += f"_{args.t_env:g}C"
    req = Requirements(
        T_max_C=args.t_max, dT_cell_max_C=args.dt_max, T_env_C=args.t_env, recovery_max_min=args.recovery_max_min
    )
    hw = {"air": args.air_kg_per_kwh, "liquid": args.liquid_kg_per_kwh}
    if args.thesis_levels:
        options = thesis_cooling_options(hw)
    else:
        options = cooling_options(
            air_h=tuple(args.air_h),
            liquid_h=tuple(args.liquid_h),
            chiller_setpoints_C=tuple(sp for sp in args.chiller_c if sp < args.t_env),
            hardware_kg_per_kWh=hw,
        )
    study = DesignStudy(
        cell,
        duty,
        req,
        cooling_options=tuple(options),
        pcm_grades=tuple(args.pcm_grades),
        pcm_thicknesses_mm=tuple(x for x in args.pcm_mm if x > 0),
        case_thickness_mm=args.case_mm,
        cells_in_pack=args.cells_in_pack,
        chiller_cop=args.cop,
        resistance_margin=args.r_margin,
    )
    n = len(options) * len(study.pcm_choices())
    print(f"Simulating {n} designs...")
    t0 = time.perf_counter()
    result = run_study(study, workers=args.workers)
    print(result.summary())
    print(f"({time.perf_counter() - t0:.0f}s)")
    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^a-z0-9_.]+", "_", stem.lower())
        result.table.to_csv(args.out_dir / f"{stem}_designs.csv", index=False)
        plot_tradeoff(result, args.out_dir / f"{stem}_tradeoff.png")
        print(f"Wrote {stem}_designs.csv and {stem}_tradeoff.png to {args.out_dir}")


def _build_duty(args, cell):
    from .design import DutyCycle
    from .ev import Pack, Vehicle, road_trip_duty, wltc_duty

    rest = getattr(args, "rest_h", 0.0) * 3600
    if args.duty == "constant":
        return DutyCycle.constant(
            args.c_rate, args.mode, soc0=args.soc0, soc_limits=(args.soc_min, args.soc_max), rest_after_s=rest
        )
    pack = Pack.for_energy(cell, args.pack_kwh, args.pack_v)
    if args.duty == "wltc":
        return wltc_duty(cell, pack, Vehicle(), cycles=args.cycles, rest_after_s=rest)
    return road_trip_duty(cell, pack, Vehicle(), speed_kmh=args.speed, charge_c_rate=args.charge_c, rest_after_s=rest)


def _module(args) -> None:
    import pandas as pd

    from .module import AirFlow, BottomPlate, Coolant, Interface, Layout, Module, SideRibbon, compare_modules

    cell = get_cell(args.cell)
    duty = _build_duty(args, cell)
    coolant = Coolant(flow_g_s_per_cell=args.flow, inlet_C=args.inlet_c)
    tim = Interface(args.tim_mm, args.tim_k)
    layout = Layout(args.packing, args.gap)

    def cooling_for(kind):
        return {
            "none": None,
            "air": AirFlow(flow_g_s_per_cell=args.air_flow),
            "bottom": BottomPlate(coolant=coolant, tim=tim),
            "ribbon": SideRibbon(coolant=coolant, tim=tim, contact_fraction=args.contact),
        }[kind]

    if args.compare:
        modules = [Module(layout, None, None), Module(layout, None, AirFlow(flow_g_s_per_cell=args.air_flow))]
        for kind in ("bottom", "ribbon"):
            for filler in (None, *args.fillers):
                modules.append(Module(layout, filler, cooling_for(kind)))
    else:
        filler = None if args.filler in (None, "air", "none") else args.filler
        modules = [Module(layout, filler, cooling_for(args.cooling))]
    print(f"{cell.name}, {duty.name}, ambient {args.t_env:g} degC, {layout.packing} packing, {args.gap:g} mm gap")
    rows = compare_modules(cell, modules, duty, args.t_env)
    df = pd.DataFrame(rows)
    cols = [
        "cooling",
        "filler",
        "T_peak_inlet_C",
        "T_peak_outlet_C",
        "cell_to_cell_K",
        "dT_cell_outlet_K",
        "coolant_rise_max_K",
        "pump_mW_per_cell",
        "filler_mass_pct",
    ]
    with pd.option_context("display.width", 160):
        print(df[cols].round(2).to_string(index=False))
    if args.out:
        df.to_csv(args.out, index=False)
        print(f"Wrote {args.out}")


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
    e.add_argument("--pcm-grade", default="RT31", help=f"PCM grade: {', '.join(PCM_LIBRARY)}")
    e.add_argument("--case-mm", type=float, default=1.0)
    e.add_argument("--t-env", type=float, default=25.0, help="Ambient/coolant [degC].")
    e.add_argument("--soc0", type=float)
    e.add_argument("--soc-min", type=float, default=0.0)
    e.add_argument("--soc-max", type=float, default=1.0)
    e.add_argument("--duration", type=float, help="Seconds (default: time to cross the SOC window +5%%).")
    e.set_defaults(func=_cell)

    d = sub.add_parser("design", help="Sweep cooling x PCM choices and chart the trade-off.")
    d.add_argument("cell", help=f"Cell key: {', '.join(CELLS)}")
    g = d.add_argument_group("duty")
    g.add_argument("--duty", choices=["constant", "wltc", "roadtrip"], default="constant")
    g.add_argument("--mode", choices=["charge", "discharge"], default="discharge", help="constant duty")
    g.add_argument("--c-rate", type=float, default=1.0, help="constant duty")
    g.add_argument("--soc0", type=float, help="constant duty")
    g.add_argument("--soc-min", type=float, default=0.0, help="constant duty")
    g.add_argument("--soc-max", type=float, default=1.0, help="constant duty")
    g.add_argument("--cycles", type=int, default=3, help="wltc: back-to-back cycles")
    g.add_argument("--speed", type=float, default=130.0, help="roadtrip: motorway speed [km/h]")
    g.add_argument("--charge-c", type=float, help="roadtrip: charge C-rate (default: cell maximum)")
    g.add_argument("--pack-kwh", type=float, default=60.0, help="EV duties: pack energy")
    g.add_argument("--pack-v", type=float, default=350.0, help="EV duties: nominal pack voltage")
    g.add_argument("--rest-h", type=float, default=3.0, help="Rest simulated after the event [h].")
    r = d.add_argument_group("requirements")
    r.add_argument("--t-env", type=float, default=25.0, help="Ambient [degC].")
    r.add_argument("--t-max", type=float, help="Peak limit [degC] (default min(45, datasheet)).")
    r.add_argument("--dt-max", type=float, default=5.0, help="In-cell spread limit [degC].")
    r.add_argument("--recovery-max-min", type=float, help="Must be ready again within this many minutes.")
    v = d.add_argument_group("design space")
    v.add_argument("--air-h", type=float, nargs="+", default=[10, 15, 22, 33, 45, 60])
    v.add_argument("--liquid-h", type=float, nargs="+", default=[100, 180, 330, 600])
    v.add_argument(
        "--chiller-c", type=float, nargs="*", default=[15.0], help="Chiller setpoints [degC]; none to disable."
    )
    v.add_argument("--thesis-levels", action="store_true", help="Use the discrete thesis cooling levels instead.")
    v.add_argument("--pcm-grades", nargs="*", default=["RT28HC", "RT31", "OM35", "RT42"])
    v.add_argument("--pcm-mm", type=float, nargs="+", default=[2, 4], help="PCM thicknesses (no PCM always included).")
    v.add_argument("--case-mm", type=float, default=1.0)
    a = d.add_argument_group("assumptions")
    a.add_argument("--cells-in-pack", type=int, default=100, help="Cells sharing the anchor fan/pump power.")
    a.add_argument("--air-kg-per-kwh", type=float, default=0.5)
    a.add_argument("--liquid-kg-per-kwh", type=float, default=1.0)
    a.add_argument("--cop", type=float, default=3.0, help="Chiller COP.")
    a.add_argument("--r-margin", type=float, default=0.2, help="Worst-case resistance margin over the published max.")
    d.add_argument("--workers", type=int)
    d.add_argument("--out-dir", type=Path)
    d.set_defaults(func=_design)

    mo = sub.add_parser("module", help="Simulate a cell inside a packed module (inlet and outlet cell).")
    mo.add_argument("cell", help=f"Cell key: {', '.join(CELLS)}")
    mo.add_argument("--compare", action="store_true", help="Compare all cooling topologies x fillers.")
    mo.add_argument("--cooling", choices=["none", "air", "bottom", "ribbon"], default="ribbon")
    mo.add_argument(
        "--filler", default=None, help=f"Gap filler: air (default) or a PCM grade: {', '.join(PCM_LIBRARY)}"
    )
    mo.add_argument("--fillers", nargs="*", default=["RT31", "RT31-EG", "RT42-EG"], help="Fillers for --compare.")
    mo.add_argument("--packing", choices=["hex", "square"], default="hex")
    mo.add_argument("--gap", type=float, default=2.0, help="Can-to-can gap [mm].")
    mo.add_argument("--flow", type=float, default=0.05, help="Coolant flow per cell [g/s].")
    mo.add_argument("--inlet-c", type=float, help="Coolant inlet [degC] (default ambient; lower = chiller).")
    mo.add_argument("--contact", type=float, default=0.25, help="Ribbon contact fraction of the circumference.")
    mo.add_argument("--tim-mm", type=float, default=0.5)
    mo.add_argument("--tim-k", type=float, default=2.0)
    mo.add_argument("--air-flow", type=float, default=0.3, help="Air flow per cell for --cooling air [g/s].")
    mo.add_argument("--duty", choices=["constant", "wltc", "roadtrip"], default="constant")
    mo.add_argument("--mode", choices=["charge", "discharge"], default="discharge")
    mo.add_argument("--c-rate", type=float, default=1.0)
    mo.add_argument("--soc0", type=float)
    mo.add_argument("--soc-min", type=float, default=0.0)
    mo.add_argument("--soc-max", type=float, default=1.0)
    mo.add_argument("--cycles", type=int, default=3)
    mo.add_argument("--speed", type=float, default=130.0)
    mo.add_argument("--charge-c", type=float)
    mo.add_argument("--pack-kwh", type=float, default=60.0)
    mo.add_argument("--pack-v", type=float, default=350.0)
    mo.add_argument("--t-env", type=float, default=25.0)
    mo.add_argument("--out", type=Path, help="Write results CSV here.")
    mo.set_defaults(func=_module)

    args = ap.parse_args(argv)
    if args.cmd is None:
        args = ap.parse_args(["thesis", *(argv or [])])
    args.func(args)


if __name__ == "__main__":
    main()

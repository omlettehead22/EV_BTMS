"""Validation against measured cell temperatures (Panasonic NCR18650PF dataset).

Two modes:

* ``thermal``: heat comes from the measured record, Q = I (OCV - V_measured).
  Only the thermal model is tested; one parameter (the chamber's convective
  h) is calibrated.
* ``predictive``: only the measured current goes in. The equivalent-circuit
  model predicts voltage and heat, and the thermal model predicts temperature,
  with resistance feeding back from temperature every step. The CC-CV charge
  test is driven by the charge *request* (constant 1C), so the model must
  produce the CV taper itself.

Calibration uses one test only (25 degC 1C discharge #1): h from its
temperature (thermal mode), then the slow polarisation branch (Rd, tau_d) from
its voltage (predictive mode). Every other test is a blind prediction.
"""

from __future__ import annotations

import gzip
import json
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

from .cells import PANASONIC_NCR18650PF, Cell, params_for_cell
from .electrothermal import ElectroThermalLoad, MeasuredHeatLoad
from .model import simulate
from .params import KELVIN

DEFAULT_DATA = Path(__file__).resolve().parents[2] / "validation" / "data" / "panasonic_18650pf"

# Calibrated on 25C_1C_discharge_1 by `calibrate()`; reproduced by the tests.
# Rd and tau_d are stored on the cell (btms.cells.NCR18650PF_ECM).
H_CHAMBER = 38.7  # W/(m^2 K)
RD_25C = PANASONIC_NCR18650PF.ecm.Rd_25C
TAU_D = PANASONIC_NCR18650PF.ecm.tau_d


@dataclass
class TestRecord:
    name: str
    kind: str
    role: str
    setpoint_C: float
    ambient_C: float
    soc0: float
    t: np.ndarray
    current_A: np.ndarray
    voltage_V: np.ndarray
    T_cell_C: np.ndarray


def load_tests(data_dir: str | Path | None = None, names: list[str] | None = None) -> list[TestRecord]:
    data_dir = Path(data_dir or DEFAULT_DATA)
    manifest = json.loads((data_dir / "manifest.json").read_text())
    out = []
    for m in manifest:
        if names is not None and m["name"] not in names:
            continue
        with gzip.open(data_dir / m["file"], "rt") as f:
            arr = np.loadtxt(f, delimiter=",", skiprows=1)
        out.append(
            TestRecord(m["name"], m["kind"], m["role"], m["setpoint_C"], m["ambient_C"], m["soc0"], *arr.T.copy())
        )
    return out


def calibrated_cell(cell: Cell = PANASONIC_NCR18650PF, Rd: float = RD_25C, tau_d: float = TAU_D) -> Cell:
    return replace(cell, ecm=replace(cell.ecm, Rd_25C=Rd, tau_d=tau_d))


def run_test(
    test: TestRecord, cell: Cell | None = None, h: float = H_CHAMBER, mode: str = "thermal", dt: float = 2.0
) -> dict:
    """Simulate one test; returns metrics and the time series on the model grid."""
    cell = cell or calibrated_cell()
    duration = float(test.t[-1])
    P = params_for_cell(cell, pcm_thickness=0.0, case_thickness=0.0)
    P = P.with_(T_initial=test.T_cell_C[0] + KELVIN, solver=replace(P.solver, dt=dt, store_every=10_000))
    T_amb = test.ambient_C + KELVIN
    if mode == "thermal":
        load = MeasuredHeatLoad(
            test.t, test.current_A, test.voltage_V, cell.ecm.ocv, cell.capacity_Ah, soc0=test.soc0, dUdT=cell.dUdT
        )
    elif mode == "predictive":
        if test.kind == "cccv_charge":
            # Drive with the charge request; the model must produce the CV taper.
            i_req = -float(np.max(np.abs(test.current_A)))
            t_on = float(test.t[np.argmax(np.abs(test.current_A) > 0.05)])
            profile = lambda t: i_req if t >= t_on else 0.0
            c = cell
        else:
            # Drive with the measured current; voltage limits are the tester's
            # business here (the record already ends at cut-off).
            profile = lambda t: float(np.interp(t, test.t, test.current_A))
            c = replace(cell, ecm=replace(cell.ecm, V_min=-1e9, V_max=1e9))
        load = ElectroThermalLoad(c, profile, soc0=test.soc0)
    else:
        raise ValueError("mode must be 'thermal' or 'predictive'")
    res = simulate(P, duration=duration, h=h, T_env=T_amb, load=load)
    T_model = res.T_surface - KELVIN
    T_meas = np.interp(res.t, test.t, test.T_cell_C)
    err = T_model - T_meas
    out = {
        "name": test.name,
        "kind": test.kind,
        "role": test.role,
        "ambient_C": test.ambient_C,
        "mode": mode,
        "duration_min": duration / 60.0,
        "T_rmse_K": float(np.sqrt(np.mean(err**2))),
        "T_maxabs_K": float(np.max(np.abs(err))),
        "T_peak_meas_C": float(T_meas.max()),
        "T_peak_model_C": float(T_model.max()),
        "peak_error_K": float(T_model.max() - T_meas.max()),
        "rise_meas_K": float(T_meas.max() - test.ambient_C),
        "rise_model_K": float(T_model.max() - test.ambient_C),
        "series": {"t": res.t, "T_model": T_model, "T_meas": T_meas},
    }
    if mode == "predictive":
        a = load.arrays()
        t_l = a["t"]
        V_meas = np.interp(t_l, test.t, test.voltage_V)
        active = np.abs(np.interp(t_l, test.t, test.current_A)) > 0.05
        if test.kind == "cccv_charge":
            active = np.ones_like(t_l, dtype=bool)
        dv = (a["V"] - V_meas)[active]
        out["V_rmse_mV"] = float(1e3 * np.sqrt(np.mean(dv**2))) if dv.size else np.nan
        # Before the end-of-discharge knee (measured V > 3.2 V): cold capacity
        # loss makes the last minutes before cut-off the least reliable part.
        knee = active & (V_meas > 3.2)
        dk = (a["V"] - V_meas)[knee]
        out["V_rmse_pre_knee_mV"] = float(1e3 * np.sqrt(np.mean(dk**2))) if dk.size else np.nan
        out["series"].update({"t_V": t_l, "V_model": a["V"], "V_meas": V_meas, "I_model": a["current_A"]})
        if test.kind == "cccv_charge":
            I_meas = -np.interp(t_l, test.t, test.current_A)  # + charge
            out["I_rmse_A"] = float(np.sqrt(np.mean((-a["current_A"] - I_meas) ** 2)))
            out["series"]["I_meas"] = -I_meas
    return out


def _run(args):
    test, cell, h, mode, dt = args
    return run_test(test, cell, h, mode, dt)


def validate(
    tests: list[TestRecord] | None = None,
    modes: tuple[str, ...] = ("thermal", "predictive"),
    cell: Cell | None = None,
    h: float = H_CHAMBER,
    dt: float = 2.0,
    workers: int | None = None,
) -> tuple[pd.DataFrame, list[dict]]:
    tests = tests if tests is not None else load_tests()
    cell = cell or calibrated_cell()
    jobs = [(t, cell, h, m, dt) for m in modes for t in tests]
    workers = workers if workers is not None else min(len(jobs), os.cpu_count() or 1)
    if workers > 1:
        with ProcessPoolExecutor(workers) as ex:
            results = list(ex.map(_run, jobs))
    else:
        results = [_run(j) for j in jobs]
    table = pd.DataFrame([{k: v for k, v in r.items() if k != "series"} for r in results])
    return table, results


def calibrate(tests: list[TestRecord] | None = None, dt: float = 2.0) -> dict:
    """Fit h (thermal mode) then Rd, tau_d (predictive voltage) on the calibration test."""
    from scipy.optimize import minimize, minimize_scalar

    tests = tests if tests is not None else load_tests()
    cal = next(t for t in tests if t.role == "calibration")
    base = PANASONIC_NCR18650PF
    r = minimize_scalar(
        lambda h: run_test(cal, base, h, "thermal", dt)["T_rmse_K"],
        bounds=(5.0, 150.0),
        method="bounded",
        options={"xatol": 0.05},
    )
    h = float(r.x)

    def v_rmse(x):
        Rd, tau = 10 ** x[0], 10 ** x[1]
        return run_test(cal, calibrated_cell(base, Rd, tau), h, "predictive", dt)["V_rmse_mV"]

    best = minimize(
        v_rmse, x0=[np.log10(0.015), np.log10(400.0)], method="Nelder-Mead", options={"xatol": 1e-3, "fatol": 0.05}
    )
    Rd, tau_d = 10 ** best.x[0], 10 ** best.x[1]
    return {"h": h, "T_rmse_K": float(r.fun), "Rd_25C": float(Rd), "tau_d": float(tau_d), "V_rmse_mV": float(best.fun)}

"""Scenario summary metrics (port of summarise_scenario_metrics.m)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .model import SimulationResult
from .params import KELVIN
from .scenarios import Scenario

T_LIMIT_C = 40.0


def summarise(sc: Scenario, res: SimulationResult) -> dict:
    t = res.t
    T = res.T_max - KELVIN
    dT = res.dT_cell
    phi = res.pcm_fraction
    dur = t[-1] - t[0]
    i_peak = int(np.argmax(T))
    rate = np.gradient(T, t) * 60
    n0 = min(max(2, round(0.10 * t.size)), t.size)
    init_rate = np.polyfit(t[:n0], T[:n0], 1)[0] * 60

    above = np.nonzero(T >= T_LIMIT_C)[0]
    t40 = np.nan
    if above.size:
        j = above[0]
        t40 = t[0] if j == 0 else t[j - 1] + (T_LIMIT_C - T[j - 1]) * (t[j] - t[j - 1]) / (T[j] - T[j - 1])

    P_aux = sc.aux_power()
    E_aux = P_aux * dur
    Eg, Er, Es = res.E_generated, res.E_rejected, res.E_stored
    return {
        "Scenario": sc.name,
        "ScenarioType": sc.event,
        "CoolingType": sc.cooling,
        "CoolingLevel": sc.level,
        "Duration_s": dur,
        "T_initial_C": T[0],
        "T_peak_C": T[i_peak],
        "TimeToPeak_s": t[i_peak],
        "T_end_C": T[-1],
        "TemperatureRise_C": T[i_peak] - T[0],
        "T_mean_C": np.trapezoid(T, t) / dur,
        "ThermalDose_Cs": np.trapezoid(np.maximum(T - T[0], 0), t),
        "MaxCellDifference_C": dT.max(),
        "MeanCellDifference_C": np.trapezoid(dT, t) / dur,
        "InitialRate_Cmin": init_rate,
        "MaxHeatingRate_Cmin": rate.max(),
        "MaxCoolingRate_Cmin": rate.min(),
        "PCM_fraction_peak": phi.max(),
        "PCM_fraction_end": phi[-1],
        "PCM_utilisation": np.trapezoid(phi, t) / dur,
        "P_aux_W": P_aux,
        "E_aux_kJ": E_aux / 1e3,
        "E_aux_Wh": E_aux / 3600,
        "E_generated_kJ": Eg / 1e3,
        "E_rejected_kJ": Er / 1e3,
        "E_stored_kJ": Es / 1e3,
        "E_cell_kJ": res.dE_cell.sum() / 1e3,
        "E_PCM_kJ": res.dE_pcm.sum() / 1e3,
        "E_case_kJ": res.dE_case.sum() / 1e3,
        "HeatRejected_pct": 100 * Er / Eg if Eg else np.nan,
        "EnergyStored_pct": 100 * Es / Eg if Eg else np.nan,
        "BalanceError_pct": res.balance_error_pct,
        "TimeTo40C_s": t40,
        "SafetyMargin40_C": T_LIMIT_C - T[i_peak],
    }


def summary_table(pairs: list[tuple[Scenario, SimulationResult]]) -> pd.DataFrame:
    return pd.DataFrame([summarise(sc, res) for sc, res in pairs])

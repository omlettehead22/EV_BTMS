"""The Python port must reproduce the MATLAB thesis results."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from btms import default_params, run_scenario, thesis_scenarios
from btms.metrics import summary_table
from btms.params import KELVIN
from btms.scenarios import Scenario

RESULTS = Path(__file__).resolve().parents[1] / "matlab" / "results"


@pytest.fixture(scope="module")
def python_summary():
    P = default_params()
    return summary_table([(sc, run_scenario(P, sc)) for sc in thesis_scenarios(P)]).set_index("Scenario")


def test_summary_matches_matlab(python_summary):
    ref = pd.read_csv(RESULTS / "BTMS_results_summary.csv").set_index("Scenario")
    cols = [c for c in python_summary.select_dtypes("number").columns if c in ref.select_dtypes("number").columns]
    assert len(cols) > 25
    pd.testing.assert_frame_equal(python_summary[cols], ref[cols], rtol=1e-8, atol=1e-8, check_dtype=False)


def test_time_step_study_matches_matlab():
    ref = pd.read_csv(RESULTS / "time_step_verification.csv")
    P0 = default_params()
    sc = Scenario("charge-liquid-mid", "charge", "liquid", "mid", P0.T_coolant)
    for dt, T_ref in zip(ref.TimeStep_s[:2], ref.PeakTemperature_C[:2]):
        P = P0.with_(solver=replace(P0.solver, dt=dt))
        assert run_scenario(P, sc).T_max.max() - KELVIN == pytest.approx(T_ref, abs=1e-8)


@pytest.mark.parametrize("n_cells", [65, 130, 260])
def test_mesh_study_matches_matlab(n_cells):
    ref = pd.read_csv(RESULTS / "mesh_verification.csv").set_index("Nx")
    P0 = default_params()
    P = P0.with_(geometry=replace(P0.geometry, n_cells=n_cells))
    sc = Scenario("mesh", "charge", "air", "high", P0.T_ambient_mild)
    res = run_scenario(P, sc, duration=600, heat_source=lambda t: 9.4e4)
    assert res.T_max.max() - KELVIN == pytest.approx(ref.loc[n_cells, "PeakTemperature_C"], abs=1e-8)
    assert np.isclose(res.balance_error_pct, ref.loc[n_cells, "BalanceError_pct"], atol=1e-8)

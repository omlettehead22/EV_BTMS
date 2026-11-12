"""Validation against measured temperatures (Panasonic NCR18650PF, Kollmeyer 2018, CC BY 4.0).

These are regression gates on the published validation: if a model change
makes any of them fail, the README's validation claims are no longer true.
"""

import numpy as np
import pytest

from packtherm.validation import DEFAULT_DATA, H_CHAMBER, RD_25C, TAU_D, calibrate, load_tests, run_test

pytestmark = pytest.mark.skipif(not DEFAULT_DATA.exists(), reason="validation data not present")

# One representative test per ambient, plus the charge.
GATE = ["25C_US06", "10C_Cycle_2", "0C_US06", "m10C_Cycle_3", "m20C_Cycle_1", "25C_1C_CCCV_charge"]


@pytest.fixture(scope="module")
def tests():
    return {t.name: t for t in load_tests(names=GATE + ["25C_1C_discharge_1"])}


def test_dataset_loads(tests):
    t = tests["25C_US06"]
    assert t.t[0] == 0 and np.all(np.diff(t.t) == 1.0)
    assert t.current_A.max() > 15  # US06 peaks (discharge positive)
    assert {x.role for x in tests.values()} == {"calibration", "validation"}


def test_calibration_reproduces_constants(tests):
    cal = calibrate([tests["25C_1C_discharge_1"]], dt=2.0)
    assert cal["h"] == pytest.approx(H_CHAMBER, abs=0.5)
    assert cal["Rd_25C"] == pytest.approx(RD_25C, rel=0.1)
    assert cal["tau_d"] == pytest.approx(TAU_D, rel=0.15)
    assert cal["T_rmse_K"] < 0.5


@pytest.mark.parametrize("name", GATE)
def test_thermal_model_within_1K(tests, name):
    r = run_test(tests[name], mode="thermal", dt=2.0)
    assert r["T_rmse_K"] < 1.0
    assert abs(r["peak_error_K"]) < 1.5


@pytest.mark.parametrize("name", GATE)
def test_fully_predictive_model(tests, name):
    r = run_test(tests[name], mode="predictive", dt=2.0)
    assert r["T_rmse_K"] < 1.5
    assert abs(r["peak_error_K"]) < 2.5
    if tests[name].ambient_C >= 10:
        assert r["V_rmse_pre_knee_mV"] < 40


def test_charge_cv_taper_predicted(tests):
    r = run_test(tests["25C_1C_CCCV_charge"], mode="predictive", dt=2.0)
    assert r["I_rmse_A"] < 0.3

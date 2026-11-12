import math
from dataclasses import replace

import numpy as np
import pytest

from btms.cells import LG_M50, PANASONIC_NCR18650PF
from btms.ecm import ECM, ECMState
from btms.electrothermal import ElectroThermalLoad, MeasuredHeatLoad, constant_current, simulate_cell

PF = PANASONIC_NCR18650PF
ECM_PF = PF.ecm
T25 = 298.15


def flat_ecm(**kw):
    base = {
        "ocv_soc": (0.0, 1.0),
        "ocv_V": (3.0, 4.2),
        "R0_25C": 0.02,
        "Ea_R0": 0.0,
        "I0_25C": 1e6,  # charge transfer negligible
        "Ea_I0": 0.0,
        "gamma": 1.0,
        "Rd_25C": 0.0,
    }
    base.update(kw)
    return ECM(**base)


def test_ohmic_only_voltage_and_heat():
    ecm = flat_ecm()
    st = ECMState()
    current, V = st.apply(ecm, 2.0, 0.5, T25, 1.0)
    assert current == 2.0
    assert V == pytest.approx(3.6 - 2.0 * 0.02, abs=1e-6)


def test_butler_volmer_is_odd_and_sublinear():
    a, b = ECM_PF.eta_ss(2.0, 263.15), ECM_PF.eta_ss(-2.0, 263.15)
    assert a == pytest.approx(-b)
    # Apparent charge-transfer resistance falls with current.
    assert ECM_PF.eta_ss(6.0, 263.15) / 6.0 < ECM_PF.eta_ss(1.0, 263.15) / 1.0


def test_kinetics_slow_down_in_the_cold():
    assert ECM_PF.eta_ss(2.9, 253.15) > 5 * ECM_PF.eta_ss(2.9, T25)
    assert ECM_PF.Rd(253.15) > ECM_PF.Rd(T25)


def test_rc_branch_relaxes():
    ecm = flat_ecm(Rd_25C=0.01, tau_d=100.0)
    st = ECMState()
    for _ in range(1000):
        st.apply(ecm, 1.0, 0.5, T25, 1.0)
    assert st.V_d == pytest.approx(0.01, rel=1e-3)  # steady state R I
    for _ in range(1000):
        st.apply(ecm, 0.0, 0.5, T25, 1.0)
    assert abs(st.V_d) < 1e-6


def test_discharge_cutoff_latches():
    ecm = flat_ecm(V_min=3.5)
    st = ECMState()
    current, _ = st.apply(ecm, 5.0, 0.3, T25, 1.0)  # OCV 3.36 < V_min
    assert current == 0.0 and st.cutoff
    current, _ = st.apply(ecm, 5.0, 0.9, T25, 1.0)
    assert current == 0.0


def test_cv_phase_holds_vmax_and_tapers():
    load = ElectroThermalLoad(PF, constant_current(PF, 1.0, "charge"), soc0=0.05)
    for k in range(3 * 3600):
        load.power(float(k), 1.0, T25)
        if load.ecm_state.charge_done:
            break
    a = load.arrays()
    assert np.nanmax(a["V"]) <= PF.ecm.V_max + 1e-4
    cv = a["V"] > PF.ecm.V_max - 1e-3
    assert cv.any()
    i_cv = -a["current_A"][cv]
    assert i_cv[0] > 1.0 and i_cv[-1] < 0.1  # tapers from ~1C towards the cut-off
    assert np.all(np.diff(i_cv) <= 1e-3)  # monotonic taper (to 1 mA: thermal feedback)
    assert load.soc > 0.95


def test_heat_is_current_times_overpotential():
    load = ElectroThermalLoad(PF, constant_current(PF, 1.0), soc0=0.8, entropic=False)
    q = load.power(0.0, 1.0, T25)
    a = load.arrays()
    soc_mid = 0.8 - 0.5 * a["current_A"][0] / (3600 * PF.capacity_Ah)
    assert q == pytest.approx(a["current_A"][0] * (PF.ecm.ocv(soc_mid) - a["V"][0]), rel=1e-9)


def test_legacy_cells_unchanged():
    """Cells without an ECM keep the lumped I^2 R path (no voltage)."""
    assert LG_M50.ecm is None
    _, load = simulate_cell(LG_M50, constant_current(LG_M50, 1.0), 60.0, h=30.0, T_env=T25)
    assert np.isnan(load.arrays()["V"]).all()


def test_measured_heat_load():
    t = np.arange(0.0, 101.0)
    current = np.full_like(t, 2.0)
    V = np.full_like(t, 3.5)
    load = MeasuredHeatLoad(t, current, V, lambda s: 3.6, capacity_Ah=3.0)
    assert load.power(10.0, 1.0, T25) == pytest.approx(2.0 * 0.1)
    assert load._soc[-1] == pytest.approx(1 - 200 / 3600 / 3.0)


def test_pf_cell_runs_through_design_path():
    res, load = simulate_cell(PF, constant_current(PF, 1.0), 4000.0, h=40.0, T_env=T25, pcm_thickness=0.0)
    a = load.arrays()
    # Discharge ends at the 2.5 V cut-off before the SOC window is exhausted.
    assert np.nanmin(a["V"][a["current_A"] > 0]) >= PF.ecm.V_min - 1e-6
    assert load.ecm_state.cutoff
    assert 0.0 < load.soc < 0.15
    assert math.isfinite(res.T_max.max())


def test_ecm_is_frozen_and_replaceable():
    e2 = replace(ECM_PF, Rd_25C=0.05)
    assert e2.Rd(T25) == pytest.approx(0.05)

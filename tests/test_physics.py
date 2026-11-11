"""Physics sanity checks independent of the MATLAB reference."""

from dataclasses import replace

import numpy as np
import pytest

from btms import default_params, simulate
from btms.params import KELVIN, PCM


def test_adiabatic_no_melt_matches_lumped_energy_balance():
    """No cooling, PCM never melts: mean temperature rise = Q / (sum rho cp V)."""
    P0 = default_params()
    # Push the melt range far above anything reached so PCM is a plain solid.
    P = P0.with_(pcm=replace(P0.pcm, T_solidus=200 + KELVIN, T_liquidus=205 + KELVIN))
    q, dur = 5e4, 300.0
    res = simulate(P, lambda t: q, dur, h=0.0, T_env=P.T_initial)
    rho = np.select([res.region == 1, res.region == 2], [P.cell.rho, P.pcm.rho], P.case.rho)
    cp = np.select([res.region == 1, res.region == 2], [P.cell.cp, P.pcm.cp_solid], P.case.cp)
    heat_cap = np.sum(rho * cp * res.volume)
    Q = q * res.volume[res.region == 1].sum() * dur
    T_mean = np.sum(rho * cp * res.volume * res.T[:, -1]) / heat_cap
    assert T_mean - P.T_initial == pytest.approx(Q / heat_cap, rel=1e-7)
    assert res.E_rejected == 0.0


def test_no_heat_no_change():
    P = default_params()
    res = simulate(P, lambda t: 0.0, 60.0, h=300.0, T_env=P.T_initial)
    assert np.allclose(res.T, P.T_initial, atol=1e-10)


@pytest.mark.parametrize("h", [10.0, 300.0])
def test_energy_balance_tight(h):
    P = default_params()
    res = simulate(P, lambda t: 9.4e4, 1200.0, h=h, T_env=P.T_initial)
    # Default enthalpy-Newton scheme: every step converges and energy is
    # conserved to round-off.
    assert res.converged and res.unconverged_steps == 0
    assert res.balance_error_pct < 1e-6
    assert res.iterations[1:].mean() < 4


def test_thesis_scheme_still_available():
    P0 = default_params()
    P = P0.with_(solver=replace(P0.solver, scheme="thesis"))
    res = simulate(P, lambda t: 9.4e4, 600.0, h=60.0, T_env=P.T_initial)
    assert res.balance_error_pct < 0.1


def test_enthalpy_scheme_agrees_with_thesis_scheme():
    P0 = default_params()
    Pt = P0.with_(solver=replace(P0.solver, scheme="thesis"))
    a = simulate(P0, lambda t: 9.4e4, 3600.0, h=60.0, T_env=P0.T_initial)
    b = simulate(Pt, lambda t: 9.4e4, 3600.0, h=60.0, T_env=P0.T_initial)
    assert abs(a.T_max.max() - b.T_max.max()) < 1e-3
    assert abs(a.pcm_fraction[-1] - b.pcm_fraction[-1]) < 1e-3


def test_more_cooling_is_cooler():
    P = default_params()
    peaks = [simulate(P, lambda t: 9.4e4, 600.0, h=h, T_env=P.T_initial).T_max.max() for h in (10, 60, 600)]
    assert peaks[0] > peaks[1] > peaks[2]


def test_pcm_validation():
    with pytest.raises(ValueError):
        PCM(T_solidus=310, T_liquidus=305)

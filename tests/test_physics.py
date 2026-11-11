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
    assert res.balance_error_pct < 0.1
    # Known limitation of the thesis scheme (fixed in v0.2): a handful of
    # melt-front steps hit the iteration cap. Keep it to < 2% of steps.
    assert res.unconverged_steps < 0.02 * (res.t.size - 1)


def test_more_cooling_is_cooler():
    P = default_params()
    peaks = [simulate(P, lambda t: 9.4e4, 600.0, h=h, T_env=P.T_initial).T_max.max() for h in (10, 60, 600)]
    assert peaks[0] > peaks[1] > peaks[2]


def test_pcm_validation():
    with pytest.raises(ValueError):
        PCM(T_solidus=310, T_liquidus=305)

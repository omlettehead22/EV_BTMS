from dataclasses import replace

import numpy as np
import pytest

from packtherm.cells import (
    LG_M50,
    LG_M50_LUMPED,
    LG_MJ1,
    get_cell,
    nmc811_graphite_dUdT,
    nmc811_jellyroll_properties,
    params_for_cell,
)
from packtherm.cli import main
from packtherm.electrothermal import (
    ElectroThermalLoad,
    check_limits,
    constant_current,
    segments,
    simulate_cell,
)
from packtherm.params import KELVIN

T25 = 25 + KELVIN
# Constant-resistance M50: no SOC or temperature dependence, for hand checks.
FLAT = replace(LG_M50_LUMPED, Ea_R=0.0, soc_factor=lambda soc: 1.0)


def test_joule_heat_matches_hand_calculation():
    """Adiabatic, no entropic term: E = I^2 R t exactly."""
    duration = 600.0
    res, _load = simulate_cell(FLAT, constant_current(FLAT, 1.0), duration, h=0.0, T_env=T25, entropic=False)
    current = FLAT.current(1.0)
    assert res.E_generated == pytest.approx(current**2 * FLAT.R0_25C * duration, rel=1e-12)
    assert res.balance_error_pct < 1e-6


def test_coulomb_counting():
    _res, load = simulate_cell(LG_M50, constant_current(LG_M50, 1.0), 1800.0, h=30.0, T_env=T25, soc0=1.0)
    assert load.soc == pytest.approx(0.5, abs=1e-9)


def test_soc_window_stops_charge():
    res, load = simulate_cell(
        LG_M50, constant_current(LG_M50, 1.0, "charge"), 3600.0, h=30.0, T_env=T25, soc0=0.1, soc_limits=(0.0, 0.8)
    )
    a = load.arrays()
    assert load.soc == pytest.approx(0.8, abs=1e-12)
    t_full = 0.7 * 3600  # 70 % at 1C
    assert np.all(a["current_A"][a["t"] > t_full + 1] == 0.0)
    # Heat stops when current stops, so the cell cools afterwards.
    assert res.T_max[-1] < res.T_max.max()


def test_reversible_heat_sign():
    """Bernardi: Q_rev = -I T dU/dT. Opposite sign on charge vs discharge."""
    soc = 0.9
    assert nmc811_graphite_dUdT(soc) > 0
    dis = ElectroThermalLoad(LG_M50, constant_current(LG_M50, 1.0, "discharge"), soc0=soc)
    chg = ElectroThermalLoad(LG_M50, constant_current(LG_M50, 1.0, "charge"), soc0=soc)
    dis.power(0.0, 0.5, T25)
    chg.power(0.0, 0.5, T25)
    assert dis.log["Q_rev_W"][0] < 0 < chg.log["Q_rev_W"][0]
    assert dis.log["Q_rev_W"][0] == pytest.approx(-chg.log["Q_rev_W"][0], rel=1e-3)


def test_entropic_coefficient_magnitude():
    vals = np.array([nmc811_graphite_dUdT(s) for s in np.linspace(0, 1, 101)])
    assert np.all(np.abs(vals) < 1e-3)  # |dU/dT| below 1 mV/K for NMC/graphite


def test_cold_cell_heats_more():
    assert LG_M50.resistance(0.5, 273.15) > 1.8 * LG_M50.resistance(0.5, T25)
    assert LG_M50.resistance(0.02, T25) > LG_M50.resistance(0.5, T25)


def test_segments_profile():
    prof = segments(LG_M50, [(10, 1.0), (5, 0.0), (10, -0.5)], repeat=True)
    assert prof(0) == pytest.approx(5.0)
    assert prof(12) == 0.0
    assert prof(20) == pytest.approx(-2.5)
    assert prof(25 + 3) == pytest.approx(5.0)
    once = segments(LG_M50, [(10, 1.0)])
    assert once(11) == 0.0


def test_limit_warnings():
    res, load = simulate_cell(LG_M50, constant_current(LG_M50, 2.5), 300.0, h=10.0, T_env=T25)
    assert any("continuous rating" in w for w in check_limits(LG_M50, load, res))
    res, load = simulate_cell(LG_M50, constant_current(LG_M50, 0.5), 300.0, h=30.0, T_env=T25)
    assert check_limits(LG_M50, load, res) == []


def test_cell_library_physical():
    rho, cp, k = nmc811_jellyroll_properties()
    assert 2500 < rho < 3200 and 700 < cp < 1100 and 0.5 < k < 2.0
    for cell in (LG_M50, LG_MJ1):
        assert 2400 < cell.density < 3000
        lo, hi = cell.R0_range
        assert lo <= cell.R0_25C <= hi
    assert get_cell("m50") is LG_M50
    with pytest.raises(KeyError):
        get_cell("nope")


def test_params_for_cell_geometry():
    P = params_for_cell(LG_M50, pcm_thickness=0.0)
    assert P.geometry.r_pcm == P.geometry.r_cell == LG_M50.radius
    assert P.geometry.r_case - P.geometry.r_cell == pytest.approx(1e-3)
    assert P.geometry.r_case / P.geometry.n_cells <= 1e-4 + 1e-12


def test_pcm_insulates_under_strong_cooling_and_helps_under_weak():
    """The design trade-off the advisor (v0.3) will optimise."""

    def peak(h, pcm):
        res, _ = simulate_cell(LG_M50, constant_current(LG_M50, 1.5), 2400.0, h=h, T_env=T25, pcm_thickness=pcm)
        return res.T_max.max()

    assert peak(10.0, 3e-3) < peak(10.0, 0.0)  # weak air: PCM buffers
    assert peak(300.0, 3e-3) > peak(300.0, 0.0)  # liquid: PCM insulates


def test_cli_smoke(capsys):
    main(["cells"])
    main(["cell", "MJ1", "--c-rate", "1", "--duration", "120"])
    out = capsys.readouterr().out
    assert "LG INR18650 MJ1" in out and "Peak cell temperature" in out


def test_cli_pcm_grade(capsys):
    main(
        [
            "cell",
            "M50",
            "--c-rate",
            "1.5",
            "--cooling",
            "air",
            "--level",
            "low",
            "--pcm-grade",
            "RT42",
            "--duration",
            "600",
        ]
    )
    hot = capsys.readouterr().out
    main(
        [
            "cell",
            "M50",
            "--c-rate",
            "1.5",
            "--cooling",
            "air",
            "--level",
            "low",
            "--pcm-grade",
            "RT28HC",
            "--duration",
            "600",
        ]
    )
    cool = capsys.readouterr().out
    assert "RT42 3 mm (melts ~40 degC)" in hot and "RT28HC" in cool
    peak = lambda out: float(out.split("Peak cell temperature")[1].split()[0])
    assert peak(cool) < peak(hot)  # RT28HC starts melting below this peak; RT42 never does
    with pytest.raises(SystemExit) as e:  # a clean CLI error, not a traceback
        main(["cell", "M50", "--pcm-grade", "nope"])
    assert e.value.code == 2
    assert "Unknown PCM 'nope'" in capsys.readouterr().err


def test_temperature_limits_judged_per_phase():
    """A hot discharge followed by a cool charge is not a charging-limit breach."""
    from packtherm.electrothermal import segments

    cell = replace(LG_M50, T_max_charge_C=30.0, T_max_discharge_C=60.0)
    prof = segments(cell, [(1800, 1.5), (3600, 0.0), (300, -0.1)])
    res, load = simulate_cell(cell, prof, 5700, h=0.5, T_env=298.15, pcm_thickness=0, case_thickness=0, soc0=1.0)
    T_peak = res.T_max.max() - 273.15
    assert T_peak > 30.0  # the discharge is hot
    w = check_limits(cell, load, res)
    a = load.arrays()
    T_charge = (res.T_max[1:] - 273.15)[a["current_A"] < 0].max()
    assert any("while charging" in x for x in w) == (T_charge > 30.0)
    cool = segments(cell, [(1800, 1.5), (5 * 3600, 0.0), (300, -0.1)])
    res2, load2 = simulate_cell(cell, cool, 5 * 3600 + 2100, h=10.0, T_env=298.15, soc0=1.0)
    assert res2.T_max.max() - 273.15 > 30.0  # hot discharge, then cooled before charging
    assert not any("charging" in x for x in check_limits(cell, load2, res2))


def test_datasheet_limits_are_currents():
    """C-rate limits convert back to the datasheet currents through the model's capacity."""
    from packtherm.cells import LG_MJ1
    from packtherm.cells import PANASONIC_NCR18650PF as PF

    assert PF.max_discharge_C * PF.capacity_Ah == pytest.approx(10.0)
    assert PF.max_charge_C * PF.capacity_Ah == pytest.approx(1.375)
    assert LG_MJ1.max_charge_C * LG_MJ1.capacity_Ah == pytest.approx(3.4)
    assert LG_MJ1.T_max_charge_C == 45.0

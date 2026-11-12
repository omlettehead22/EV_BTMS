"""Module-level model: geometry, analytic steady states, energy, stability."""

import math
from dataclasses import replace

import numpy as np
import pytest

from btms.cells import LG_M50
from btms.electrothermal import constant_current, simulate_cell
from btms.materials import PCM_LIBRARY, composite_pcm, get_pcm
from btms.module import (
    AirFlow,
    BottomPlate,
    Coolant,
    Interface,
    Layout,
    Module,
    SideRibbon,
    module_mass_per_cell_kg,
    pcm_volume_fraction,
    simulate_module,
)
from btms.params import KELVIN

# Constant heat: flat resistance, no entropic term -> Q = I^2 R exactly.
FLAT = replace(LG_M50, Ea_R=0.0, soc_factor=lambda soc: 1.0)
I = FLAT.current(1.0)
Q = I**2 * FLAT.R0_25C  # 0.75 W


def steady(module, position="inlet", hours=1.2):
    prof = constant_current(FLAT, 1.0)
    return simulate_module(
        FLAT, module, prof, hours * 3600, 25.0, position=position, soc0=1.0, soc_limits=(0.0, 1.0), entropic=False
    )


def test_layout_geometry():
    lay_h, lay_s = Layout("hex", 2.0), Layout("square", 2.0)
    p = LG_M50.diameter + 2e-3
    assert lay_h.unit_radius(LG_M50) == pytest.approx(p * math.sqrt(math.sqrt(3) / (2 * math.pi)))
    assert lay_s.unit_radius(LG_M50) == pytest.approx(p / math.sqrt(math.pi))
    assert lay_h.cells_per_m2(LG_M50) > lay_s.cells_per_m2(LG_M50)  # hex packs denser
    # Hex at zero gap: the classic 1 - pi/(2 sqrt 3) = 9.3 % void.
    assert pcm_volume_fraction(LG_M50, Module(Layout("hex", 0.0), "RT31", None)) == pytest.approx(
        1 - math.pi / (2 * math.sqrt(3))
    )
    with pytest.raises(ValueError):
        Layout("triangle")


def test_composite_pcm():
    base = get_pcm("RT31")
    c = PCM_LIBRARY["RT31-EG"]
    assert c.k == pytest.approx(3.85) and c.latent_heat == pytest.approx(0.86 * base.latent_heat)
    assert (c.T_solidus, c.T_liquidus) == (base.T_solidus, base.T_liquidus)
    assert composite_pcm(base, k=8.0, paraffin_mass_fraction=0.8).latent_heat == pytest.approx(0.8 * base.latent_heat)
    with pytest.raises(ValueError):
        composite_pcm(base, paraffin_mass_fraction=0.0)


def test_coolant_scaling():
    c = Coolant()
    c2 = replace(c, flow_g_s_per_cell=0.1)
    assert c2.h == pytest.approx(c.h * 2**0.8)
    assert c2.pump_power_W_per_cell == pytest.approx(c.pump_power_W_per_cell * 8)  # P ~ flow^3
    assert c.rise_K(1.0) == pytest.approx(1.0 / (5e-5 * 3500))


def test_air_flow_module_equals_bare_cell_model():
    """No filler + forced air is exactly the v0.3 bare-cell model."""
    m = Module(filler=None, cooling=AirFlow(30.0, flow_g_s_per_cell=None))
    a = simulate_module(LG_M50, m, constant_current(LG_M50, 1.5), 900, 25.0)
    b, _ = simulate_cell(
        LG_M50, constant_current(LG_M50, 1.5), 900, 30.0, 298.15, pcm_thickness=0, case_thickness=0, base=None
    )
    assert np.allclose(a.res.T_max, b.T_max)


def test_uncooled_interior_cell_is_adiabatic():
    r = simulate_module(
        FLAT, Module(filler=None, cooling=None), constant_current(FLAT, 1.0), 1800, 25.0, entropic=False
    )
    heat = r.res.E_generated
    rise = r.res.T_max[-1] - r.res.T_max[0]
    assert r.res.E_rejected == 0.0
    assert rise == pytest.approx(
        heat / (LG_M50.mass * 0 + FLAT.material.rho * math.pi * FLAT.radius**2 * FLAT.height * FLAT.cp), rel=1e-3
    )


def test_bottom_plate_steady_state_matches_analytic():
    """Uniform generation, inlet coolant: mean T - T_c = q (L^2/(3k) + L R_path)."""
    plate = BottomPlate(coolant=Coolant(), tim=Interface(), R_end=5e-4)
    r = steady(Module(filler=None, cooling=plate))
    L, k = FLAT.height, FLAT.k_axial
    R = plate.R_end + plate.tim.R + 1 / plate.coolant.h
    V_model = r.res.volume[r.res.region == 1].sum()
    q = Q / V_model
    expected = q * (L * L / (3 * k) + L * R)
    # Quasi-steady plateau 50 min into the 1C discharge (it ends at 60 min).
    i = np.searchsorted(r.res.t, 50 * 60)
    mean_rise = r.res.T_max[i] - (25.0 + KELVIN)
    assert mean_rise == pytest.approx(expected, rel=0.03)
    # Coolant at the inlet stays at the inlet temperature.
    assert np.allclose(r.T_coolant, 25.0 + KELVIN)
    # Axial estimate: top - bottom = q L^2 / (2k) while current flows.
    assert r.dT_axial[i] == pytest.approx(Q / (math.pi * FLAT.radius**2 * L) * L * L / (2 * k), rel=1e-6)


def test_outlet_coolant_rise_balances_heat():
    """At quasi-steady state the outlet coolant has risen by Q / (m cp)."""
    c = Coolant()
    r = steady(Module(filler=None, cooling=SideRibbon(coolant=c)), position="outlet")
    i = np.searchsorted(r.res.t, 50 * 60)
    assert r.Q_coolant[i] == pytest.approx(Q, rel=0.01)
    # Coolant temperature is set from the start-of-step state: ppm-level lag.
    assert r.T_coolant[i] - (25.0 + KELVIN) == pytest.approx(c.rise_K(r.Q_coolant[i]), rel=1e-4)


def test_air_warms_along_the_flow():
    prof = constant_current(LG_M50, 1.5)
    m = Module(filler=None, cooling=AirFlow(30.0, flow_g_s_per_cell=0.3))
    a = simulate_module(LG_M50, m, prof, 1800, 25.0, position="inlet")
    b = simulate_module(LG_M50, m, prof, 1800, 25.0, position="outlet")
    # Inlet cell sees ambient air: identical to the bare-cell model with h = 30.
    c = simulate_module(LG_M50, Module(filler=None, cooling=AirFlow(30.0, None)), prof, 1800, 25.0)
    assert np.allclose(a.res.T_max, c.res.T_max, atol=1e-9)
    assert b.T_peak_C > a.T_peak_C + 1.0
    assert b.res.balance_error_pct < 1e-6


def test_inlet_cell_is_cooler_than_outlet():
    m = Module(filler=None, cooling=BottomPlate())
    prof = constant_current(LG_M50, 1.5)
    a = simulate_module(LG_M50, m, prof, 1800, 25.0, position="inlet")
    b = simulate_module(LG_M50, m, prof, 1800, 25.0, position="outlet")
    assert a.T_peak_C < b.T_peak_C


def test_strong_contact_and_weak_flow_stay_stable():
    """Contact conductance >> coolant capacity flow must not oscillate."""
    c = Coolant(flow_g_s_per_cell=0.002)
    m = Module(filler=None, cooling=SideRibbon(coolant=c, contact_fraction=1.0, tim=Interface(0.05, 5.0)))
    r = simulate_module(LG_M50, m, constant_current(LG_M50, 1.5), 1800, 25.0)
    assert np.all(np.isfinite(r.res.T_max)) and r.res.T_max.max() < 400
    assert r.res.balance_error_pct < 1e-6
    assert np.all(np.diff(r.T_coolant[1:]) > -1e-6) or r.T_coolant.max() < r.res.T_max.max()


def test_side_ribbon_beats_bottom_plate_for_tall_cells():
    prof = constant_current(LG_M50, 1.5)
    rib = simulate_module(LG_M50, Module(filler=None, cooling=SideRibbon()), prof, 2400, 25.0, position="inlet")
    bot = simulate_module(LG_M50, Module(filler=None, cooling=BottomPlate()), prof, 2400, 25.0, position="inlet")
    assert rib.T_peak_C < bot.T_peak_C
    assert rib.dT_cell_max < bot.dT_cell_max


def test_composite_beats_plain_pcm_conduction():
    prof = constant_current(LG_M50, 1.5)
    plain = simulate_module(LG_M50, Module(filler="RT42", cooling=BottomPlate()), prof, 2400, 25.0)
    comp = simulate_module(LG_M50, Module(filler="RT42-EG", cooling=BottomPlate()), prof, 2400, 25.0)
    assert comp.T_peak_C < plain.T_peak_C


def test_filler_mass():
    m = Module(Layout("hex", 2.0), "RT31-EG", None)
    vol = (Layout("hex", 2.0).area_per_cell(LG_M50) - math.pi * LG_M50.radius**2) * LG_M50.height
    assert module_mass_per_cell_kg(LG_M50, m) == pytest.approx(vol * PCM_LIBRARY["RT31-EG"].rho)
    assert module_mass_per_cell_kg(LG_M50, Module(filler=None, cooling=None)) == 0.0
    with pytest.raises(ValueError):
        Module(filler="RT31", cooling=AirFlow())

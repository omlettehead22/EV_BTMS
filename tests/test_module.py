"""Module-level model: geometry, analytic steady states, energy, stability."""

import math
from dataclasses import replace

import numpy as np
import pytest

from packtherm.cells import LG_M50, LG_M50_LUMPED
from packtherm.electrothermal import constant_current, simulate_cell
from packtherm.materials import PCM_LIBRARY, composite_pcm, get_pcm
from packtherm.module import (
    AirFlow,
    BottomPlate,
    Chiller,
    Coolant,
    Interface,
    Layout,
    Module,
    RibbonGeometry,
    SideRibbon,
    Wall,
    module_mass_per_cell_kg,
    pcm_volume_fraction,
    simulate_module,
)
from packtherm.params import KELVIN

# Room for the default ribbon (2.5 mm tube + two 0.5 mm bonds).
RIBBON_GAP = Layout("hex", 3.5)

# Constant heat: flat resistance, no entropic term -> Q = I^2 R exactly.
FLAT = replace(LG_M50_LUMPED, Ea_R=0.0, soc_factor=lambda soc: 1.0)
I = FLAT.current(1.0)
Q = I**2 * FLAT.R0_25C  # 0.75 W


def steady(module, position="inlet", hours=1.2, **kw):
    prof = constant_current(FLAT, 1.0)
    return simulate_module(
        FLAT, module, prof, hours * 3600, 25.0, position=position, soc0=1.0, soc_limits=(0.0, 1.0), entropic=False, **kw
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


def test_air_flow_sets_h_and_fan_power():
    a, b = AirFlow(), AirFlow(flow_g_s_per_cell=0.6)
    assert a.h == pytest.approx(30.0)
    # Cross-flow over the bank of cans: h ~ v^0.6, dp ~ v^1.8, fan power ~ flow^2.8.
    assert b.h == pytest.approx(30.0 * 2**0.6)
    assert b.pump_power_W_per_cell == pytest.approx(2**2.8 * a.pump_power_W_per_cell)
    assert AirFlow.with_h(45.0).h == pytest.approx(45.0)
    with pytest.raises(ValueError):
        AirFlow(flow_g_s_per_cell=0.0)


def test_ribbon_needs_room():
    with pytest.raises(ValueError):
        Module(Layout("hex", 1.0), None, SideRibbon())
    thin = SideRibbon(tube=RibbonGeometry(thickness_mm=1.0, wall_mm=0.2), tim=Interface(0.1, 2.0))
    assert thin.min_gap_mm == pytest.approx(1.2)
    Module(Layout("hex", 1.2), None, thin)
    assert SideRibbon().min_gap_mm == pytest.approx(2.5 + 2 * 0.5)


def test_chiller_energy_counts_heat_to_cold_coolant():
    prof = constant_current(LG_M50, 1.0)
    warm = simulate_module(LG_M50, Module(layout=RIBBON_GAP, filler=None, cooling=SideRibbon()), prof, 1800, 25.0)
    cold = simulate_module(
        LG_M50,
        Module(layout=RIBBON_GAP, filler=None, cooling=SideRibbon(coolant=Coolant(inlet_C=15.0))),
        prof,
        1800,
        25.0,
    )
    assert warm.chiller_energy_Wh(3.0) == 0.0
    dt = np.diff(cold.res.t, prepend=0.0)
    heat_J = np.sum(np.clip(cold.Q_coolant, 0, None) * dt)
    no_leak = Chiller(cop=3.0, pack_time_constant_h=math.inf)
    assert cold.chiller_energy_Wh(no_leak) == pytest.approx(heat_J / 3.0 / 3600)
    # The heat leaking in from a 10 K warmer day is charged on top.
    leak_J = LG_M50.mass * LG_M50.cp / (9 * 3600) * 10.0 * dt.sum()
    assert cold.chiller_energy_Wh(3.0) == pytest.approx((heat_J + leak_J) / 3.0 / 3600)
    assert cold.T_peak_C < warm.T_peak_C


def test_chiller_cop_falls_on_hot_days():
    c = Chiller()
    set_K = 15.0 + KELVIN
    assert c.cop_at(set_K, 35.0 + KELVIN) == pytest.approx(3.0, abs=0.05)
    assert c.cop_at(set_K, 45.0 + KELVIN) < c.cop_at(set_K, 35.0 + KELVIN) < c.cop_at(set_K, 25.0 + KELVIN)
    assert Chiller(cop=2.5).cop_at(set_K, 45.0 + KELVIN) == 2.5
    assert c.leak_W_per_cell(LG_M50, set_K, 10.0 + KELVIN) == 0.0


def test_chiller_hands_back_to_radiator():
    """With chiller_until_s the inlet returns to ambient and chiller energy stops."""
    prof = constant_current(LG_M50, 1.0)
    run = lambda until: simulate_module(
        LG_M50,
        Module(RIBBON_GAP, None, SideRibbon(coolant=Coolant(inlet_C=15.0, chiller_until_s=until))),
        prof,
        3600,
        35.0,
        position="inlet",
    )
    always, half = run(None), run(1800.0)
    i = np.searchsorted(half.res.t, 1800.0)
    assert half.T_coolant[i - 1] == pytest.approx(15.0 + KELVIN)
    assert half.T_coolant[-1] == pytest.approx(35.0 + KELVIN)
    assert half.chiller_energy_Wh() == pytest.approx(always.chiller_energy_Wh(until_s=half.res.t[i - 1]), rel=1e-6)
    assert half.chiller_energy_Wh() < always.chiller_energy_Wh()


def test_coolant_scaling():
    """Laminar channels: h nearly flat with flow (plate 1/3 power, ribbon none)."""
    c = Coolant()
    c2 = replace(c, flow_g_s_per_cell=0.1)
    assert c2.h == pytest.approx(c.h * 2 ** (1 / 3))  # alone: developing flow
    plate = BottomPlate(coolant=c2)
    ribbon = SideRibbon(coolant=c2)
    assert plate.coolant.h == pytest.approx(1500.0 * 2 ** (1 / 3))
    assert ribbon.coolant.h == pytest.approx(1500.0)  # fully developed in the ports
    assert BottomPlate(coolant=Coolant(h_flow_exponent=0.8)).coolant.h_flow_exponent == 0.8  # explicit wins
    with pytest.raises(ValueError):
        Coolant(flow_g_s_per_cell=0.0)
    assert c.rise_K(1.0) == pytest.approx(1.0 / (5e-5 * 3500))


def test_air_flow_module_equals_bare_cell_model():
    """No filler + forced air is exactly the v0.3 bare-cell model."""
    m = Module(filler=None, cooling=AirFlow(track_rise=False))
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
    """Radial model (nz=0), uniform generation, inlet coolant: mean T - T_c = q (L^2/(3k) + L R_path)."""
    plate = BottomPlate(coolant=Coolant(), tim=Interface(), R_end=5e-4)
    r = steady(Module(filler=None, cooling=plate), nz=0)
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
    # Axial estimate: top - bottom = q L^2 / (2k) while current flows (q from the
    # heat reaching the coolant, which is a hair below generation at quasi-steady).
    assert r.dT_axial[i] == pytest.approx(Q / (math.pi * FLAT.radius**2 * L) * L * L / (2 * k), rel=2e-3)
    assert r.dT_axial[i] <= Q / (math.pi * FLAT.radius**2 * L) * L * L / (2 * k)


def test_bottom_plate_2d_matches_analytic():
    """2D r-z model, no filler, uniform generation, cooled base, adiabatic top:
    T(z) - T_c = q (L z - z^2/2)/k + q L R, so top - T_c = q (L^2/(2k) + L R)
    and the in-cell spread top - base = q L^2 / (2k). The coolest point is on
    the roll's base face (z = 0), not at the bottom node centre."""
    plate = BottomPlate(coolant=Coolant(), tim=Interface(), R_end=5e-4)
    L, k = FLAT.height, FLAT.k_axial
    R = plate.R_end + plate.tim.R + 1 / plate.coolant.h
    for nz in (8, 16):
        r = steady(Module(filler=None, cooling=plate), nz=nz)
        i = np.searchsorted(r.res.t, 50 * 60)
        q = r.res.heat_W[i] / (math.pi * FLAT.radius**2 * L)
        # Node centres sit dz/2 inside the faces: compare with the analytic value there.
        dz = L / nz
        z_top = L - dz / 2
        top = q * (L * z_top - z_top**2 / 2) / k + q * L * R
        assert r.T_top[i] - (25.0 + KELVIN) == pytest.approx(top, rel=0.01)
        spread = q * (L * z_top - z_top**2 / 2) / k  # top node centre to the base face
        # Radial spread is ~0 here (no side losses), so dT_cell is the axial spread.
        assert r.res.dT_cell[i] == pytest.approx(spread, rel=0.01)
        assert r.res.balance_error_pct < 1e-6


def test_outlet_coolant_rise_balances_heat():
    """At quasi-steady state the outlet coolant has risen by Q / (m cp)."""
    c = Coolant()
    r = steady(Module(layout=RIBBON_GAP, filler=None, cooling=SideRibbon(coolant=c)), position="outlet")
    i = np.searchsorted(r.res.t, 50 * 60)
    assert r.Q_coolant[i] == pytest.approx(Q, rel=0.01)
    # Coolant temperature is set from the start-of-step state: ppm-level lag.
    assert r.T_coolant[i] - (25.0 + KELVIN) == pytest.approx(c.rise_K(r.Q_coolant[i]), rel=1e-4)


def test_air_warms_along_the_flow():
    prof = constant_current(LG_M50, 1.5)
    m = Module(filler=None, cooling=AirFlow())
    a = simulate_module(LG_M50, m, prof, 1800, 25.0, position="inlet")
    b = simulate_module(LG_M50, m, prof, 1800, 25.0, position="outlet")
    # Inlet cell sees ambient air: identical to the bare-cell model with h = 30.
    c = simulate_module(LG_M50, Module(filler=None, cooling=AirFlow(track_rise=False)), prof, 1800, 25.0)
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
    m = Module(
        layout=RIBBON_GAP, filler=None, cooling=SideRibbon(coolant=c, contact_fraction=1.0, tim=Interface(0.05, 5.0))
    )
    r = simulate_module(LG_M50, m, constant_current(LG_M50, 1.5), 1800, 25.0)
    assert np.all(np.isfinite(r.res.T_max)) and r.res.T_max.max() < 400
    assert r.res.balance_error_pct < 1e-6
    assert np.all(np.diff(r.T_coolant[1:]) > -1e-6) or r.T_coolant.max() < r.res.T_max.max()


def test_side_ribbon_beats_bottom_plate_for_tall_cells():
    prof = constant_current(LG_M50, 1.5)
    rib = simulate_module(
        LG_M50, Module(layout=RIBBON_GAP, filler=None, cooling=SideRibbon()), prof, 2400, 25.0, position="inlet"
    )
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


def test_pump_covers_whole_loop():
    c = Coolant()
    q = c.mdot / c.rho  # m^3/s per cell
    assert c.pump_power_W_per_cell == pytest.approx(q * (20e3 + 30e3) / 0.3)
    # Module channels laminar (dp ~ flow), the rest of the loop turbulent (dp ~ flow^2).
    doubled = Coolant(flow_g_s_per_cell=0.1)
    assert doubled.pump_power_W_per_cell == pytest.approx(2 * q * (2 * 20e3 + 4 * 30e3) / 0.3)


def test_radiator_fan_charged_on_rejected_heat():
    prof = constant_current(LG_M50, 1.0)
    r = simulate_module(LG_M50, Module(RIBBON_GAP, None, SideRibbon()), prof, 1800, 25.0)
    heat_J = np.sum(np.clip(r.Q_coolant, 0, None) * np.diff(r.res.t, prepend=0.0))
    assert r.radiator_fan_energy_Wh() == pytest.approx(0.03 * heat_J / 3600)
    # No radiator fan while the chiller carries the heat; it starts when the chiller hands back.
    chilled = simulate_module(
        LG_M50,
        Module(RIBBON_GAP, None, SideRibbon(coolant=Coolant(inlet_C=15.0, chiller_until_s=900.0))),
        prof,
        1800,
        25.0,
    )
    i = np.searchsorted(chilled.res.t, 900.0)
    assert chilled.radiator_fan_energy_Wh(until_s=chilled.res.t[i - 1]) == 0.0
    assert chilled.radiator_fan_energy_Wh() > 0.0


def test_edge_cell_exchanges_heat_with_ambient():
    prof = constant_current(LG_M50, 1.5)
    sealed = Module(Layout("hex", 2.0), "RT31", None)
    interior = simulate_module(LG_M50, sealed, prof, 1800, 25.0)
    edge = simulate_module(LG_M50, sealed, prof, 1800, 25.0, edge=True)
    # A sealed interior cell is adiabatic; the edge cell loses heat through the wall.
    assert edge.T_peak_C < interior.T_peak_C
    Q = edge.res.Q_sinks["wall"]
    assert Q[-1] > 0
    # No wall, no difference.
    bare = Module(Layout("hex", 2.0), "RT31", None, Wall(U=0.0))
    same = simulate_module(LG_M50, bare, prof, 1800, 25.0, edge=True)
    assert np.allclose(same.res.T_max, interior.res.T_max)
    with pytest.raises(ValueError):
        Wall(fraction=1.5)


def test_edge_cell_of_chilled_module_runs_warm():
    """Chilled coolant on a hot day: the wall leaks heat in, so the edge cell is the hottest."""
    prof = constant_current(LG_M50, 0.3)
    m = Module(RIBBON_GAP, None, SideRibbon(coolant=Coolant(inlet_C=15.0)))
    interior = simulate_module(LG_M50, m, prof, 3600, 40.0, position="inlet")
    edge = simulate_module(LG_M50, m, prof, 3600, 40.0, position="inlet", edge=True)
    assert edge.res.T_max[-1] > interior.res.T_max[-1]


def test_coolant_holdup_matches_hardware_mass():
    from packtherm.hardware import hardware_mass_per_cell
    from packtherm.module import coolant_holdup_kg

    for m in (Module(Layout(), None, BottomPlate()), Module(RIBBON_GAP, None, SideRibbon())):
        assert coolant_holdup_kg(LG_M50, m) == hardware_mass_per_cell(LG_M50, m)["coolant"] > 0
    assert coolant_holdup_kg(LG_M50, Module(Layout(), None, AirFlow())) == 0.0


def test_coolant_temperature_lags_by_holdup_over_flow():
    """Fixed cell temperature, step on: Tc approaches the steady value with
    the implicit-Euler recurrence of tau = M cp / (m cp + G)."""
    from packtherm.module import _coolant_temperature

    c, M, dt = Coolant(), 1.0e-3, 1.0
    T = _coolant_temperature(300.0, c, "outlet", holdup_kg=M)
    G, nodes = np.array([0.5]), np.array([320.0])
    flow = c.mdot * c.cp
    b = M * c.cp / dt
    steady = (flow * 300.0 + 0.5 * 320.0) / (flow + 0.5)
    Tc = T(0.0, nodes, G)
    assert Tc == pytest.approx(steady)  # first call: no history, steady balance
    T2 = _coolant_temperature(300.0, c, "outlet", holdup_kg=M)
    T2(0.0, np.array([300.0]), G)  # coolant starts at the inlet temperature
    prev = 300.0
    for k in range(1, 200):
        Tc = T2(k * dt, nodes, G)
        assert Tc == pytest.approx((b * prev + flow * 300.0 + 0.5 * 320.0) / (b + flow + 0.5))
        prev = Tc
    assert Tc == pytest.approx(steady, rel=1e-6)
    # The inlet never lags.
    assert _coolant_temperature(300.0, c, "inlet", holdup_kg=M)(5.0, nodes, G) == 300.0


def test_coolant_mass_only_shifts_transients():
    prof = constant_current(LG_M50, 2.0)
    m = Module(RIBBON_GAP, None, SideRibbon())
    with_mass = simulate_module(LG_M50, m, prof, 1500, 25.0)
    without = simulate_module(LG_M50, m, prof, 1500, 25.0, coolant_mass=False)
    i = np.searchsorted(with_mass.res.t, 30.0)
    assert with_mass.T_coolant[i] < without.T_coolant[i]  # still filling with warm coolant
    assert with_mass.T_peak_C == pytest.approx(without.T_peak_C, abs=0.2)
    assert with_mass.res.balance_error_pct < 1e-6


def test_bottom_plate_2d_with_pcm_and_edge():
    prof = constant_current(LG_M50, 1.5)
    m = Module(Layout("hex", 2.0), "RT31", BottomPlate())
    inner = simulate_module(LG_M50, m, prof, 1800, 25.0)
    edge = simulate_module(LG_M50, m, prof, 1800, 25.0, edge=True)
    for r in (inner, edge):
        assert r.res.converged and r.res.balance_error_pct < 1e-6
        assert r.res.pcm_fraction.max() > 0  # the PCM melts somewhere
    assert edge.T_peak_C < inner.T_peak_C
    assert edge.res.Q_sinks["wall"][-1] > 0


def test_ribbon_strip_contact():
    """Radius x angle model: a full wrap matches the radial model; a strip runs
    hotter, with the far side of the can warmest, and the result converges."""
    full = Module(RIBBON_GAP, None, SideRibbon(contact_fraction=1.0))
    radial = steady(full, nz=0, n_theta=0, hours=0.9)
    wrap = steady(full, n_theta=12, hours=0.9)
    assert wrap.T_peak_C == pytest.approx(radial.T_peak_C, abs=0.02)
    strip = Module(RIBBON_GAP, None, SideRibbon(contact_fraction=0.25))
    coarse, fine = steady(strip, n_theta=12, hours=0.9), steady(strip, n_theta=24, hours=0.9)
    assert coarse.T_peak_C > wrap.T_peak_C + 0.5
    assert coarse.T_peak_C == pytest.approx(fine.T_peak_C, abs=0.05)
    i = np.searchsorted(coarse.res.t, 2700)
    assert coarse.res.dT_cell[i] > 1.5 * radial.res.dT_cell[i]
    for r in (wrap, coarse):
        assert r.res.balance_error_pct < 1e-6
        # Heat into the coolant matches generation at quasi-steady state (whole-cell accounting).
        assert r.Q_coolant[i] == pytest.approx(r.res.heat_W[i], rel=0.01)


def test_air_gap_sets_h_and_fan_power():
    """Fixed mass flow through a narrower gap: faster air between the cans, v ~ 1/gap."""
    ref = Module(Layout("hex", 2.0), None, AirFlow())
    narrow = Module(Layout("hex", 1.0), None, AirFlow())
    assert ref.cooling.h == pytest.approx(30.0)
    assert narrow.cooling.gap_mm == 1.0
    assert narrow.cooling.h == pytest.approx(2**0.6 * ref.cooling.h)
    assert narrow.cooling.pump_power_W_per_cell == pytest.approx(2**1.8 * ref.cooling.pump_power_W_per_cell)
    prof = constant_current(LG_M50, 1.5)
    T = [simulate_module(LG_M50, m, prof, 1200, 25.0).T_peak_C for m in (narrow, ref)]
    assert T[0] < T[1]


def test_coolant_rise_is_measured_from_the_inlet():
    """With the chiller handing back to the radiator, the rise is above the inlet at each time."""
    from packtherm.module import _coolant_rise_max

    c = Coolant(inlet_C=15.0, chiller_until_s=600.0)
    m = Module(layout=RIBBON_GAP, filler=None, cooling=SideRibbon(coolant=c))
    r = simulate_module(LG_M50, m, constant_current(LG_M50, 1.0), 1800, 25.0, position="outlet")
    T_in = np.array([c.inlet_K(t, r.T_ambient) for t in r.res.t])
    rise = _coolant_rise_max(r)
    assert rise == pytest.approx(float(np.max(r.T_coolant - T_in)))
    # The chilled coolant is warmed straight away by the 25 degC cell, so a rise
    # measured from the first-step coolant temperature (the old method) hides
    # most of it, and the inlet's 10 K step at hand-back confuses it further.
    assert 5.0 < rise < 10.0
    assert abs(float(r.T_coolant.max() - r.T_coolant[1]) - rise) > 2.0

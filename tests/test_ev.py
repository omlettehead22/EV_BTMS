import numpy as np
import pytest

from btms.cells import LG_M50, LG_MJ1
from btms.ev import (
    Pack,
    Vehicle,
    consumption_Wh_per_km,
    motorway_c_rate,
    road_trip_duty,
    speed_trace_c_rate,
    wltc_class3b,
    wltc_duty,
)
from btms.materials import PCM_LIBRARY, get_pcm


def test_wltc_trace_matches_regulation():
    t, v = wltc_class3b()
    assert t.size == 1801 and t[-1] == 1800
    assert v.sum() == pytest.approx(83758.6, abs=0.05)  # GTR 15 checksum
    assert v.sum() / 3600 == pytest.approx(23.27, abs=0.01)  # 23.27 km
    assert v.max() == pytest.approx(131.3)


def test_pack_sizing():
    p = Pack.for_energy(LG_M50, 60.0, 350.0)
    assert p.n_series == 96
    assert 60.0 <= p.energy_kWh(LG_M50) < 62.0
    assert Pack.for_energy(LG_MJ1).n_parallel > p.n_parallel


def test_vehicle_consumption_plausible():
    """A C-segment EV uses roughly 130-200 Wh/km at the battery on WLTC."""
    wh_km = consumption_Wh_per_km(LG_M50, Pack.for_energy(LG_M50), Vehicle())
    assert 130 < wh_km < 200


def test_road_load_physics():
    veh = Vehicle(aux_kW=0.0)
    # Constant 100 km/h: aero + rolling, over drivetrain efficiency.
    v = 100 / 3.6
    expected = (0.5 * 1.2 * veh.cda_m2 * v**2 + veh.crr * veh.mass_kg * 9.81) * v / veh.eta_drive
    assert veh.battery_power_W(np.array([v]), np.zeros(1))[0] == pytest.approx(expected)
    # Hard braking is capped at the regen limit.
    assert veh.battery_power_W(np.array([v]), np.array([-8.0]))[0] == pytest.approx(-veh.regen_max_kW * 1e3)


def test_c_rates_and_duties():
    pack = Pack.for_energy(LG_M50)
    _, v = wltc_class3b()
    c = speed_trace_c_rate(LG_M50, pack, Vehicle(), v)
    assert 0.5 < c.max() < 1.5 and c.min() < 0  # traction peaks and regen
    assert 0.3 < motorway_c_rate(LG_M50, pack, Vehicle(), 130) < 0.7
    d = wltc_duty(LG_M50, pack, cycles=2)
    assert d.event_duration() == pytest.approx(2 * 1801)
    assert d.is_mixed
    trip = road_trip_duty(LG_M50, pack)
    (t_drive, c_drive), (t_chg, c_chg) = trip.steps
    assert c_chg == pytest.approx(-LG_M50.max_charge_C)
    assert t_drive * c_drive / 3600 == pytest.approx(0.8, abs=0.01)  # 90 -> 10 %
    assert t_chg * -c_chg / 3600 == pytest.approx(0.7, abs=0.01)  # 10 -> 80 %


def test_pcm_library():
    assert get_pcm("RT31") == PCM_LIBRARY["RT31"]
    melts = [p.T_solidus for p in PCM_LIBRARY.values()]
    assert melts == sorted(melts)
    for p in PCM_LIBRARY.values():
        assert 100e3 < p.latent_heat < 300e3 and 700 < p.rho < 1000
    with pytest.raises(KeyError):
        get_pcm("unobtainium")

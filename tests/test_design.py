import math
from dataclasses import replace

import numpy as np
import pytest

from btms.cells import LG_M50
from btms.cli import main
from btms.design import (
    AIR_FAN,
    CoolingOption,
    DesignStudy,
    DutyCycle,
    FanLaw,
    Requirements,
    _sleeve_masses,
    cooling_options,
    evaluate_design,
    pareto_mask,
    run_study,
    thesis_cooling_options,
)
from btms.materials import PCM_LIBRARY

# Short, fast duty for tests: 1.5C for 10 min then 20 min rest.
SHORT = DutyCycle.constant(1.5, "discharge", duration=600, rest_after_s=1200)
OPTS = {o.name: o for o in thesis_cooling_options()}


def small_study(**kw):
    defaults = {
        "cooling_options": (OPTS["natural"], OPTS["air-mid"], OPTS["liquid-mid"]),
        "pcm_grades": ("RT31",),
        "pcm_thicknesses_mm": (3.0,),
        "requirements": Requirements(recovery_max_min=math.inf),
        "dt": 5.0,
    }
    defaults.update(kw)
    return DesignStudy(LG_M50, SHORT, **defaults)


def test_pareto_mask():
    a = np.array([1, 2, 3, 2, 1])
    b = np.array([3, 2, 1, 3, 3])
    # (2,3) is dominated by (2,2) and (1,3); the duplicate (1,3) points keep each other.
    assert pareto_mask(a, b).tolist() == [True, True, True, False, True]


def test_sleeve_mass_matches_geometry():
    study = small_study()
    m_pcm, m_case = _sleeve_masses(study, "RT28HC", 3.0)
    r, L = LG_M50.radius, LG_M50.height
    assert m_pcm == pytest.approx(PCM_LIBRARY["RT28HC"].rho * math.pi * ((r + 3e-3) ** 2 - r**2) * L)
    assert m_case == pytest.approx(2700 * math.pi * ((r + 4e-3) ** 2 - (r + 3e-3) ** 2) * L)
    assert _sleeve_masses(study, None, 0.0)[0] == 0.0


def test_fan_law():
    law = FanLaw(30.0, 20.0)
    assert law.power(30.0) == pytest.approx(20.0)
    assert law.power(60.0) == pytest.approx(20.0 * 2**3.75)
    opts = cooling_options(air_h=(30.0,), liquid_h=(300.0,), chiller_setpoints_C=(15.0,))
    names = [o.name for o in opts]
    assert names == ["natural", "air h=30", "liquid h=300", "liquid h=300 @15°C"]
    assert opts[1].aux_power_pack_W == pytest.approx(AIR_FAN.power(30.0))
    assert opts[3].chilled and opts[3].hardware_kg_per_kWh > opts[2].hardware_kg_per_kWh


def test_design_metrics_consistent():
    study = small_study()
    opt = CoolingOption("air-test", "air", 30.0, aux_power_pack_W=20.0, hardware_kg_per_kWh=0.5)
    row = evaluate_design(study, opt, None, 0.0)
    # Throughput: 1.5C for 10 min at nominal voltage.
    assert row["throughput_Wh"] == pytest.approx(7.5 * 600 / 3600 * LG_M50.V_nominal, rel=1e-6)
    # Fans run until the cell is ready again, not just during the event.
    t_ready_s = 600 + row["recovery_min"] * 60
    assert row["fan_pump_Wh"] == pytest.approx(20.0 / 100 * t_ready_s / 3600, rel=0.02)
    assert row["fan_pump_Wh"] > 20.0 / 100 * 600 / 3600
    assert row["chiller_Wh"] == 0.0
    assert row["mass_hardware_g"] == pytest.approx(0.5 * 5.0 * 3.63)
    assert row["mass_overhead_g"] == pytest.approx(row["mass_pcm_g"] + row["mass_case_g"] + row["mass_hardware_g"])
    assert row["pcm"] == "no PCM"


def test_chiller_lowers_temperature_and_costs_energy():
    study = small_study()
    radiator = CoolingOption("liq", "liquid", 300.0, 40.0, 1.0)
    chilled = replace(radiator, name="liq chilled", coolant_C=15.0)
    a = evaluate_design(study, radiator, None, 0.0)
    b = evaluate_design(study, chilled, None, 0.0)
    assert b["T_peak_C"] < a["T_peak_C"]
    assert b["chiller_Wh"] > 0 and a["chiller_Wh"] == 0
    assert b["coolant_C"] == pytest.approx(15.0)


def test_pcm_grade_changes_result():
    study = small_study()
    low = evaluate_design(study, OPTS["natural"], "RT28HC", 3.0)
    high = evaluate_design(study, OPTS["natural"], "RT42", 3.0)
    assert low["pcm_melt_C"] < high["pcm_melt_C"]
    assert low["T_peak_C"] != pytest.approx(high["T_peak_C"], abs=1e-3)


def test_feasibility_follows_limits():
    study = small_study(requirements=Requirements(T_max_C=20.0, recovery_max_min=math.inf))
    result = run_study(study, workers=1, robustness=False)
    assert not result.table.feasible.any()
    assert result.picks == {}
    assert "No feasible design" in result.summary()
    assert (result.table.fail_reason.str.contains("hot")).all()


def test_study_front_and_picks():
    result = run_study(small_study(), workers=1)
    t = result.table
    assert len(t) == 6
    front = t[t.pareto]
    assert len(front) >= 1 and front.feasible.all() and front.robust.all()
    # No non-fragile feasible design dominates a front design.
    feas = t[t.feasible & ~t.fragile]
    for _, f in front.iterrows():
        better = (feas.mass_overhead_pct <= f.mass_overhead_pct) & (feas.aux_energy_pct <= f.aux_energy_pct)
        strictly = (feas.mass_overhead_pct < f.mass_overhead_pct) | (feas.aux_energy_pct < f.aux_energy_pct)
        assert not (better & strictly).any()
    assert set(result.picks) == {"lightest", "lowest_energy", "balanced"}
    # Front designs were re-run at worst-case resistance (published max + margin) and got hotter.
    assert (front.T_peak_worst_C > front.T_peak_C).all()
    assert front.R0_worst_mOhm.iloc[0] == pytest.approx(36.0 * 1.2)


def test_fragile_designs_are_replaced_on_the_front():
    """A limit between nominal and worst-case peak makes the lightest design fragile."""
    base = run_study(small_study(), workers=1, robustness=False).table
    lightest = base.loc[base.mass_overhead_pct.idxmin()]
    T_lim = lightest.T_peak_C + 0.05  # passes at nominal R0, fails when hotter
    result = run_study(small_study(requirements=Requirements(T_max_C=T_lim, recovery_max_min=math.inf)), workers=1)
    t = result.table
    assert t.fragile.any()
    assert not t[t.pareto].fragile.any()
    for pick in result.picks.values():
        assert pick.robust
    assert "Not picked" in result.summary()


def test_recovery_requirement_rejects_slow_designs():
    """Natural cooling cannot shed the heat in a 20-minute rest."""
    study = small_study(requirements=Requirements(recovery_max_min=None))
    t = run_study(study, workers=1, robustness=False).table
    nat = t[t.cooling == "natural"]
    assert (~nat.feasible).all()
    assert nat.fail_reason.str.contains("slow").all()


def test_rating_warning_reported():
    duty = DutyCycle.constant(2.5, "discharge", duration=300, rest_after_s=300)
    study = replace(small_study(cooling_options=(OPTS["liquid-mid"],), pcm_grades=()), duty=duty)
    result = run_study(study, workers=1, robustness=False)
    assert any("continuous rating" in w for w in result.warnings)


def test_parallel_matches_serial():
    study = small_study(pcm_grades=())
    a = run_study(study, workers=1, robustness=False).table
    b = run_study(study, workers=2, robustness=False).table
    assert np.allclose(a.T_peak_C, b.T_peak_C)


def test_duty_defaults():
    d = DutyCycle.constant(0.5, "charge", soc_limits=(0.2, 0.8))
    assert d.soc0 == 0.2 and d.is_charge
    assert d.event_duration() == pytest.approx(3600 * 0.6 / 0.5 * 1.05)
    assert Requirements().T_limit(LG_M50, charging=True) == 45.0
    assert Requirements(T_max_C=40).T_limit(LG_M50, charging=False) == 40.0


def test_cli_design_writes_chart(tmp_path, capsys):
    main(
        [
            "design",
            "M50",
            "--c-rate",
            "1.5",
            "--air-h",
            "30",
            "--liquid-h",
            "300",
            "--chiller-c",
            "--pcm-grades",
            "RT31",
            "--pcm-mm",
            "3",
            "--rest-h",
            "0.5",
            "--workers",
            "1",
            "--out-dir",
            str(tmp_path),
        ]
    )
    out = capsys.readouterr().out
    assert "trade-off front" in out
    pngs = list(tmp_path.glob("*_tradeoff.png"))
    assert len(pngs) == 1 and pngs[0].stat().st_size > 10_000
    assert len(list(tmp_path.glob("*_designs.csv"))) == 1

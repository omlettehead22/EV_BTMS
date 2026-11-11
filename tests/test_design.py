import math

import numpy as np
import pytest

from btms.cells import LG_M50
from btms.cli import main
from btms.design import (
    CoolingOption,
    DesignStudy,
    DutyCycle,
    Requirements,
    _sleeve_masses,
    default_cooling_options,
    evaluate_design,
    pareto_mask,
    run_study,
)

# Short, fast duty for tests: 1.5C for 10 min then 20 min rest.
SHORT = DutyCycle.constant(1.5, "discharge", duration=600, rest_after_s=1200)


def small_study(**kw):
    opts = {o.name: o for o in default_cooling_options()}
    defaults = {
        "cooling_options": (opts["natural"], opts["air-mid"], opts["liquid-mid"]),
        "pcm_thicknesses_mm": (0.0, 3.0),
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
    m_pcm, m_case = _sleeve_masses(study, 3.0)
    r, L = LG_M50.radius, LG_M50.height
    assert m_pcm == pytest.approx(830 * math.pi * ((r + 3e-3) ** 2 - r**2) * L)
    assert m_case == pytest.approx(2700 * math.pi * ((r + 4e-3) ** 2 - (r + 3e-3) ** 2) * L)
    assert _sleeve_masses(study, 0.0)[0] == 0.0


def test_design_metrics_consistent():
    study = small_study()
    opt = CoolingOption("air-test", "air", 30.0, aux_power_pack_W=20.0, hardware_kg_per_kWh=0.5)
    row = evaluate_design(study, opt, 0.0)
    # Throughput: 1.5C for 10 min at nominal voltage.
    assert row["throughput_Wh"] == pytest.approx(7.5 * 600 / 3600 * LG_M50.V_nominal, rel=1e-6)
    assert row["aux_energy_Wh"] == pytest.approx(20.0 / 100 * 600 / 3600)
    assert row["mass_hardware_g"] == pytest.approx(0.5 * 5.0 * 3.63)
    assert row["mass_overhead_g"] == pytest.approx(row["mass_pcm_g"] + row["mass_case_g"] + row["mass_hardware_g"])
    assert np.isfinite(row["recovery_min"])  # cools back within the rest


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
    assert len(front) >= 1 and front.feasible.all()
    # No feasible design dominates a front design.
    feas = t[t.feasible]
    for _, f in front.iterrows():
        better = (feas.mass_overhead_pct <= f.mass_overhead_pct) & (feas.aux_energy_pct <= f.aux_energy_pct)
        strictly = (feas.mass_overhead_pct < f.mass_overhead_pct) | (feas.aux_energy_pct < f.aux_energy_pct)
        assert not (better & strictly).any()
    assert set(result.picks) == {"lightest", "lowest_energy", "balanced"}
    light = result.picks["lightest"]
    assert light.mass_overhead_pct == feas.mass_overhead_pct.min()
    # Front designs were re-run at the worst-case resistance and got hotter.
    assert (front.T_peak_worst_C > front.T_peak_C).all()
    assert (front.R0_worst_mOhm == LG_M50.R0_range[1] * 1e3).all()


def test_recovery_requirement_rejects_slow_designs():
    """Natural cooling cannot shed the heat in a 20-minute rest."""
    study = small_study(requirements=Requirements(recovery_max_min=None))
    t = run_study(study, workers=1, robustness=False).table
    nat = t[t.cooling == "natural"]
    assert (~nat.feasible).all()
    assert nat.fail_reason.str.contains("slow").all()


def test_parallel_matches_serial():
    study = small_study(pcm_thicknesses_mm=(0.0,))
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
            "--pcm-mm",
            "0",
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
    assert (tmp_path / "m50_discharge_1.5C_tradeoff.png").stat().st_size > 10_000
    assert (tmp_path / "m50_discharge_1.5C_designs.csv").exists()

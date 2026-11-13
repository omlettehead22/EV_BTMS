import numpy as np
import pytest

from packtherm.cells import LG_M50
from packtherm.design import DutyCycle, Requirements
from packtherm.module import Chiller
from packtherm.module_design import ModuleDesign, ModuleStudy, evaluate_module_design, run_module_study
from packtherm.report import plot_tradeoff

DUTY = DutyCycle.constant(2.0, "discharge", soc0=1.0, soc_limits=(0.5, 1.0), rest_after_s=3600)


def small_study(**kw):
    base = {
        "topologies": ("none", "air", "ribbon"),
        "air_flows_g_s": (0.3,),
        "coolant_flows_g_s": (0.05,),
        "fillers": (None, "RT31"),
        "dt": 4.0,
    }
    base.update(kw)
    return ModuleStudy(LG_M50, DUTY, Requirements(T_env_C=25.0), **base)


def test_design_space():
    s = small_study(gaps_mm=(1.0, 2.0))
    ds = s.designs()
    # Air never gets a filler; the ribbon does not fit a 1 mm gap.
    assert all(d.filler is None for d in ds if d.topology == "air")
    assert not any(d.topology == "ribbon" and d.gap_mm < 1.5 for d in ds)
    # Chiller only below ambient.
    assert {d.inlet_C for d in ds if d.topology == "ribbon"} == {None, 15.0}
    warm = ModuleStudy(LG_M50, DUTY, Requirements(T_env_C=10.0), topologies=("ribbon",), chiller_inlets_C=(15.0,))
    assert all(d.inlet_C is None for d in warm.designs())


def test_costs_are_physical():
    s = small_study()
    plain = evaluate_module_design(s, ModuleDesign("ribbon", 0.05, None, None))
    cold = evaluate_module_design(s, ModuleDesign("ribbon", 0.05, 15.0, None))
    air = evaluate_module_design(s, ModuleDesign("air", 0.3))
    sealed = evaluate_module_design(s, ModuleDesign("none", 0.0, None, "RT31"))
    assert plain["chiller_Wh"] == 0.0 and cold["chiller_Wh"] > 0.0
    assert cold["T_peak_C"] < plain["T_peak_C"]
    # Pump power from flow and pressure drop: liquid is far cheaper than air.
    assert plain["pump_mW_per_cell"] < 0.05 * air["pump_mW_per_cell"]
    assert sealed["aux_energy_Wh"] == 0.0 and sealed["mass_hardware_g"] == 0.0
    assert sealed["mass_filler_g"] > 0.0
    assert cold["mass_hardware_g"] > plain["mass_hardware_g"]
    # Coolant warms along the channel, so the outlet cell is hotter.
    assert plain["cell_to_cell_K"] > 0.0


def test_spread_limit():
    loose = evaluate_module_design(small_study(), ModuleDesign("ribbon", 0.05))
    tight = evaluate_module_design(small_study(cell_to_cell_max_K=0.01), ModuleDesign("ribbon", 0.05))
    assert "spread" not in loose["fail_reason"]
    assert "spread" in tight["fail_reason"] and not tight["feasible"]


def test_run_study_front_and_plot(tmp_path):
    r = run_module_study(small_study(), workers=1)
    t = r.table
    assert len(t) == len(small_study().designs())
    assert t.pareto.any() and set(r.picks) == {"lightest", "lowest_energy", "balanced"}
    front = t[t.pareto]
    assert front.feasible.all() and front.robust.all()
    assert np.isfinite(front.T_peak_worst_C).all()
    assert "hottest cell" in r.footnote()
    plot_tradeoff(r, tmp_path / "t.png")
    assert (tmp_path / "t.png").stat().st_size > 10_000


def test_unknown_topology():
    with pytest.raises(ValueError):
        small_study(topologies=("immersion",)).designs()


def test_chiller_policy():
    """Chiller only during the event costs less than running it through the rest."""
    d = ModuleDesign("ribbon", 0.05, 15.0, None)
    event = evaluate_module_design(small_study(), d)
    always = evaluate_module_design(small_study(chiller_runs="always"), d)
    assert 0.0 < event["chiller_Wh"] <= always["chiller_Wh"]
    # Fixed COP is still available.
    fixed = evaluate_module_design(small_study(chiller=Chiller(cop=6.0)), d)
    assert fixed["chiller_Wh"] < event["chiller_Wh"]


def test_edge_cells_in_the_score():
    s = small_study()
    row = evaluate_module_design(s, ModuleDesign("ribbon", 0.05, 15.0, None))
    assert np.isfinite(row["T_peak_edge_outlet_C"]) and np.isfinite(row["T_peak_edge_inlet_C"])
    assert row["T_peak_C"] == max(row["T_peak_interior_C"], row["T_peak_edge_outlet_C"])
    coolest = min(row["T_peak_inlet_C"], row["T_peak_edge_inlet_C"])
    assert row["cell_to_cell_K"] == pytest.approx(row["T_peak_C"] - coolest)
    off = evaluate_module_design(small_study(edge_cells=False), ModuleDesign("ribbon", 0.05, 15.0, None))
    assert np.isnan(off["T_peak_edge_outlet_C"]) and off["T_peak_C"] == off["T_peak_interior_C"]


def test_gaps_below_ribbon_minimum_do_not_duplicate_designs():
    s = small_study(topologies=("ribbon",), gaps_mm=(1.5, 2.0, 3.0), chiller_inlets_C=())
    ds = s.designs()
    assert len(ds) == len(set(ds)) == len(s.fillers)  # all widen to the same 3.5 mm gap
    assert {d.gap_mm for d in ds} == {3.5}


def test_summary_when_feasible_designs_are_not_robust():
    from packtherm.design import Requirements
    from packtherm.module_design import ModuleStudy, run_module_study

    # A tight limit that nominal designs meet but the worst-case re-check breaks.
    s = small_study(topologies=("ribbon",), fillers=(None,), chiller_inlets_C=(), edge_cells=False)
    probe = evaluate_module_design(s, ModuleDesign("ribbon", 0.05, None, None, 3.5))
    req = Requirements(T_env_C=25.0, T_max_C=probe["T_peak_C"] + 0.2)
    r = run_module_study(
        ModuleStudy(
            LG_M50,
            DUTY,
            req,
            **{
                k: getattr(s, k)
                for k in ("topologies", "coolant_flows_g_s", "fillers", "chiller_inlets_C", "edge_cells", "dt")
            },
        ),
        workers=1,
    )
    text = r.summary()
    assert r.table.feasible.any() and not r.picks
    assert "No robust design" in text and "No feasible design" not in text
    assert "nominal" in text

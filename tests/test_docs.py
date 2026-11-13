"""The README quotes numbers from the example studies and validation; check they agree.

If one of these fails, the model changed and the README (or the committed
examples, regenerated with `packtherm run docs/examples/<study>.yaml`) is stale.
"""

import json
import re
from pathlib import Path

import pandas as pd
import pytest

import packtherm

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
EX = ROOT / "docs" / "examples"


def _results(stem: str) -> dict:
    return json.loads((EX / f"module_m50_{stem}_results.json").read_text(encoding="utf-8"))


def _table(header: str) -> list[list[str]]:
    """Rows of the markdown table whose header line starts with ``header``."""
    lines = README.splitlines()
    i = next(k for k, line in enumerate(lines) if line.startswith(header))
    rows = []
    for line in lines[i + 2 :]:
        if not line.startswith("|"):
            break
        rows.append([c.replace("**", "").strip() for c in line.strip("|").split("|")])
    return rows


def _num(text: str) -> float:
    return float(re.search(r"[-+]?\d+(?:\.\d+)?", text.replace("−", "-")).group())


def test_version_matches_roadmap_and_changelog():
    current = [r for r in _table("| Version | Scope |") if "(current)" in r[0]]
    assert len(current) == 1
    assert current[0][0].split()[0] == f"v{packtherm.__version__}"
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(r"^## (\S+)", changelog, re.MULTILINE).group(1) == packtherm.__version__


def test_headline_picks_match_the_road_trip_results():
    res = _results("roadtrip_130kmh_35c")
    s = res["summary"]
    assert f"**{s['designs']} designs, {s['feasible']} feasible**" in README
    picks = {p["pick"]: p for p in res["picks"]}
    names = {"Lightest": "lightest", "Lowest energy": "lowest_energy", "Balanced": "balanced"}
    rows = _table("| Pick | Design |")
    assert [r[0] for r in rows] == list(names)
    for label, design, hottest, mass, energy in rows:
        p = picks[names[label]]
        flow = re.search(r"\d+(?:\.\d+)? g/s", p["design"]).group()
        assert flow in design, (label, design, p["design"])
        assert _num(hottest) == pytest.approx(round(p["T_peak_C"], 1)), label
        assert _num(mass) == pytest.approx(round(p["mass_overhead_pct"], 1)), label
        assert _num(energy) == pytest.approx(round(p["aux_energy_pct"], 2)), label


def test_road_trip_claims():
    d = pd.DataFrame(_results("roadtrip_130kmh_35c")["designs"]).set_index("design")
    sealed = d.loc["sealed (no cooling), no filler", "T_peak_C"]
    assert f"An uncooled pack reaches {sealed:.0f} °C" in README
    chilled = d[d.chilled]
    assert f"costs {chilled.aux_energy_pct.min():.1f}–{chilled.aux_energy_pct.max():.1f} %" in README
    rt31 = d[d.filler == "RT31"]
    assert not rt31[~rt31.chilled].feasible.any()  # "every RT31 design without a chiller fails"


def test_wltc_claims():
    d = pd.DataFrame(_results("wltc3_35c")["designs"])
    cooled = d[d.cooling_kind != "natural"]
    sealed = d[d.cooling_kind == "natural"]
    assert cooled.T_peak_C.max() - 35.0 <= 0.4 + 1e-9  # "within 0.4 K of the 35 °C ambient"
    assert f"even a sealed pack peaks at {sealed.T_peak_C.max():.0f} °C" in README


def test_module_table_matches_the_comparison_csv():
    c = pd.read_csv(EX / "m50_module_1.5c_25c.csv").set_index(["cooling", "filler"])
    rows = _table("| Cooling | Filler |")
    assert len(rows) >= 5
    for row in rows:  # the README shows a selection of the rows
        ref = c.loc[(row[0].split(",")[0].replace("forced air", "air"), row[1])]
        for text, col in zip(
            row[2:7], ["T_peak_inlet_C", "T_peak_outlet_C", "cell_to_cell_K", "dT_cell_outlet_K", "pump_mW_per_cell"]
        ):
            want = round(ref[col], 0 if col == "pump_mW_per_cell" and ref[col] >= 100 else 1)
            assert _num(text) == pytest.approx(want, abs=1e-9), (row, col)


def test_validation_numbers_match_the_per_test_results():
    v = pd.read_csv(ROOT / "docs" / "validation" / "summary.csv")
    blind = v[v.role != "calibration"]
    pred, therm = blind[blind["mode"] == "predictive"], blind[blind["mode"] == "thermal"]
    assert len(pred) == 48 and "48 blind tests" in README
    assert f"**{pred.T_rmse_K.median():.2f} K RMSE**" in README
    assert f"{(pred.T_rmse_K <= 1).mean() * 100:.0f} % of tests within 1 K" in README
    assert (
        f"**{therm.T_rmse_K.median():.2f} K** median, {(therm.T_rmse_K <= 1).mean() * 100:.0f} % within 1 K" in README
    )

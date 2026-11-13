"""Re-run the example studies in fast mode against their committed (normal-mode) results.

The README test (test_docs.py) checks the README against the committed results;
this checks the committed results against the model as it is now. A change that
moves a result fails here until the examples are regenerated with
``packtherm run docs/examples/<study>.yaml``. Tolerances are fast mode's measured
differences from normal mode (docs/FAST_MODE.md) with some headroom.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from packtherm.study import StudySpec, file_stem, load_study

EX = Path(__file__).resolve().parents[1] / "docs" / "examples"
STUDIES = ["m50_roadtrip_35c", "m50_discharge_1.5c_25c", "m50_wltc3_35c"]


@pytest.mark.parametrize("name", STUDIES)
def test_example_study_reproduces_in_fast_mode(name):
    spec = load_study(EX / f"{name}.yaml").spec
    stored = json.loads((EX / f"{file_stem(spec)}_results.json").read_text(encoding="utf-8"))
    assert stored["study"] == spec, "the committed results were not made from this study file"
    run = StudySpec({**spec, "mode": "fast"}).run()
    now = pd.DataFrame(run.to_json()["designs"]).set_index("design")
    ref = pd.DataFrame(stored["designs"]).set_index("design")
    assert list(now.index) == list(ref.index)
    bad = now.index[now.feasible != ref.feasible]
    assert not len(bad), f"verdict changed: {list(bad)}"
    for col, tol in (("T_peak_C", 0.3), ("dT_cell_C", 0.3), ("cell_to_cell_K", 0.4), ("recovery_min", 3.0)):
        a, b = now[col].astype(float), ref[col].astype(float)
        both = a.notna() & b.notna()
        assert (a.isna() == b.isna()).all(), col
        worst = (a[both] - b[both]).abs()
        assert worst.max() <= tol, f"{col}: {worst.idxmax()} differs by {worst.max():.3f}"
    aux = (now.aux_energy_pct - ref.aux_energy_pct).abs() / ref.aux_energy_pct.where(ref.aux_energy_pct > 0)
    assert np.nanmax(aux.to_numpy(float), initial=0.0) <= 0.02
    assert np.allclose(now.mass_overhead_pct, ref.mass_overhead_pct)
    picks = {p["pick"]: p["design"] for p in stored["picks"]}
    assert {p["pick"]: p["design"] for p in run.to_json()["picks"]} == picks

"""User-defined cells from datasheet values."""

from pathlib import Path

import pytest

from packtherm import LG_MJ1, Cell
from packtherm.cells import get_cell
from packtherm.design import DutyCycle, Requirements
from packtherm.module_design import ModuleStudy, evaluate_module_design
from packtherm.study import StudyError, StudySpec, parse
from packtherm.user_cells import CELL_KEYS, CellError, load_cell, validate_cell

EX = Path(__file__).resolve().parents[1] / "docs" / "examples"
BASE = {"name": "t", "format": 21700, "capacity_Ah": 5.0, "V_nominal": 3.6, "mass_g": 69, "DCIR_mOhm": 22}


def test_mj1_from_its_datasheet_is_the_library_mj1():
    """Every value the model uses is identical, so every result is identical."""
    u = load_cell(EX / "user_cell_mj1.yaml")
    for f in (
        "capacity_Ah",
        "V_nominal",
        "diameter",
        "height",
        "mass",
        "R0_25C",
        "cp",
        "k_radial",
        "k_axial",
        "Ea_R",
        "max_charge_C",
        "max_discharge_C",
        "T_max_charge_C",
        "T_max_discharge_C",
    ):
        assert getattr(u, f) == getattr(LG_MJ1, f), f
    assert u.R0_range[1] == LG_MJ1.R0_range[1]  # the worst case uses the maximum
    assert u.dUdT is LG_MJ1.dUdT and u.soc_factor is LG_MJ1.soc_factor and u.ecm is None
    assert u.user_defined and u.model_label == "user-defined, lumped DCIR"
    study = lambda cell: ModuleStudy(
        cell,
        DutyCycle.constant(1.0),
        Requirements(),
        topologies=("ribbon",),
        coolant_flows_g_s=(0.05,),
        chiller_inlets_C=(),
        fillers=(None,),
        mode="fast",
    )
    d = study(LG_MJ1).designs()[0]
    assert evaluate_module_design(study(u), d) == evaluate_module_design(study(LG_MJ1), d)


def test_cell_files_work_wherever_a_cell_name_does():
    assert get_cell(str(EX / "user_cell_mj1.yaml")).name == "LG INR18650 MJ1 (from datasheet)"
    c = Cell.from_datasheet(**BASE)
    assert c.diameter == 21.1e-3 and c.height == 70.1e-3 and c.mass == 0.069 and c.R0_25C == 0.022


@pytest.mark.parametrize(
    "change, err",
    [
        ({"mass_g": 0.069}, "mass_g is in grams"),
        ({"DCIR_mOhm": 0.022}, "DCIR_mOhm is in milliohms"),
        ({"capacity_Ah": 5000}, "not mAh"),
        ({"V_nominal": 12}, "V_nominal"),
        ({"DCIR_max_mOhm": 10}, "DCIR_max_mOhm: 10 is below"),
        ({"format": 1865}, "format: must be one of"),
        ({"format": None}, "give a format"),
        ({"chemistry": "LTO"}, "chemistry: must be one of"),
        ({"V_nominal": 3.2}, "is this chemistry: LFP"),
        ({"chemistry": "LFP"}, "is the chemistry right"),  # 3.6 V labelled LFP
        ({"chemistry": "LFP", "V_nominal": 3.3, "capacity_Ah": 13}, "outside 100-600 Wh/L for LFP"),
        ({"T_max_charge_C": 450}, "T_max_charge_C"),
        ({"capacity": 5}, "unknown key"),
        ({"mass_g": True}, "mass_g: must be a number"),
    ],
)
def test_implausible_or_invalid_cells_are_rejected(change, err):
    with pytest.raises(CellError, match=err):
        validate_cell({**BASE, **change})


def test_unusual_values_warn_and_nca_has_no_entropic_heat():
    _, w = validate_cell({**BASE, "V_nominal": 4.1})
    assert any("unusual" in x for x in w)
    spec, w = validate_cell({**BASE, "chemistry": "nca"})
    assert any("entropic" in x for x in w)
    c = Cell.from_datasheet(**{**BASE, "chemistry": "NCA"})
    assert c.dUdT(0.5) == 0.0
    assert validate_cell({**BASE, "chemistry": "NCA", "entropic": False})[1] == []
    assert validate_cell(spec)[0] == spec  # validation accepts its own output


def test_study_with_an_inline_cell_or_a_cell_file(tmp_path):
    inline = parse(
        "packtherm_study: 1\nduty: {type: constant, c_rate: 1}\ncell:\n"
        + "".join(f"  {k}: {v}\n" for k, v in BASE.items())
    )
    assert inline["cell"]["name"] == "t" and inline["cell"]["diameter_mm"] == 21.1
    (tmp_path / "cells").mkdir()
    (tmp_path / "cells" / "c.yaml").write_text((EX / "user_cell_mj1.yaml").read_text())
    s = parse("packtherm_study: 1\ncell: cells/c.yaml\nduty: {type: constant}\n", base_dir=tmp_path)
    assert s["cell"]["DCIR_mOhm"] == 60  # read relative to the study and inlined
    assert StudySpec(s).build().cell.user_defined
    with pytest.raises(StudyError, match="cell.mass_g"):
        parse(
            "packtherm_study: 1\nduty: {type: constant}\ncell: {name: x, format: 18650, capacity_Ah: 3, "
            "V_nominal: 3.6, mass_g: 0.045, DCIR_mOhm: 30}\n"
        )
    with pytest.raises(StudyError, match="cell file not found"):
        parse("packtherm_study: 1\ncell: nope.yaml\nduty: {type: constant}\n", base_dir=tmp_path)


def test_every_cell_key_is_documented():
    doc = (EX.parent / "STUDY_FILES.md").read_text(encoding="utf-8")
    for k in CELL_KEYS:
        assert f"`{k}`" in doc, k


def test_charging_without_a_datasheet_limit_is_noted():
    import pandas as pd

    from packtherm.ev import road_trip_duty
    from packtherm.module_design import ModuleStudyResult

    t = pd.DataFrame({"chilled": [False], "topology": ["air"], "fail_reason": [""], "cooling_kind": ["air"]})
    c = Cell.from_datasheet(**BASE)

    def notes(cell, duty):
        return [n for n in ModuleStudyResult(ModuleStudy(cell, duty, Requirements()), t, {}).notes() if "limit" in n]

    assert "1C charge is not checked" in notes(c, road_trip_duty(c))[0]
    assert notes(c, DutyCycle.constant(1.0)) == []
    assert notes(LG_MJ1, road_trip_duty(LG_MJ1)) == []


def test_lfp_cell_from_its_datasheet():
    """A real LFP power cell passes cleanly and gets the LFP properties and entropic heat."""
    from packtherm.cells import LFP_CP, LFP_K_AXIAL, LFP_K_RADIAL, lfp_graphite_dUdT

    _, warnings = validate_cell(read_example("user_cell_lfp_26650.yaml"))
    assert warnings == []
    c = load_cell(EX / "user_cell_lfp_26650.yaml")
    assert (c.cp, c.k_radial, c.k_axial) == (LFP_CP, LFP_K_RADIAL, LFP_K_AXIAL)
    assert c.dUdT is lfp_graphite_dUdT and c.chemistry == "LFP / graphite"
    assert c.k_radial < Cell.from_datasheet(**BASE).k_radial / 3  # about a third of NMC's


def test_lfp_entropic_profile_matches_the_literature():
    """Within the reported -0.42..+0.17 mV/K; heat-absorbing on discharge from about 30 % SOC."""
    from packtherm.cells import lfp_graphite_dUdT

    mv = [lfp_graphite_dUdT(i / 100) * 1e3 for i in range(101)]
    assert -0.42 <= min(mv) and max(mv) <= 0.17
    assert all(v > 0 for v in mv[32:76])  # positive (absorbs heat on discharge) across 32-75 %
    assert min(mv[:20]) < -0.3  # strongly exothermic on discharge near empty


def read_example(name):
    from packtherm.user_cells import read_cell_file

    return read_cell_file(EX / name)

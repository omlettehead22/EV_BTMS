"""Study files: validation, equivalence with the design command, results JSON."""

import json
from pathlib import Path

import pytest

from packtherm.cli import _study_doc, main, parser
from packtherm.study import TEMPLATE, StudyError, load_study, parse, validate

EXAMPLES = Path(__file__).resolve().parents[1] / "docs" / "examples"

# Each example study file and the design command it stands for.
EQUIVALENT = {
    "m50_roadtrip_35c.yaml": ["design", "M50", "--duty", "roadtrip", "--t-env", "35"],
    "m50_discharge_1.5c_25c.yaml": ["design", "M50", "--c-rate", "1.5"],
    "m50_wltc3_35c.yaml": ["design", "M50", "--duty", "wltc", "--cycles", "3", "--t-env", "35"],
}


def _strip_name(spec: dict) -> dict:
    return {k: v for k, v in spec.items() if k != "name"}


@pytest.mark.parametrize("name, argv", EQUIVALENT.items())
def test_example_files_equal_the_design_command(name, argv):
    """The example study files describe exactly what the design command runs."""
    from_file = load_study(EXAMPLES / name)
    from_flags = validate(_study_doc(parser().parse_args(argv)))
    assert _strip_name(from_file.spec) == _strip_name(from_flags)
    assert from_file.build() == type(from_file)(from_flags).build()


def test_template_is_a_valid_study():
    spec = parse(TEMPLATE)
    assert spec["cell"] == "M50" and spec["duty"]["type"] == "roadtrip"
    defaults = validate({"packtherm_study": 1, "cell": "M50", "duty": {"type": "roadtrip"}})
    # Every value in the template is the default.
    assert _strip_name(spec) == _strip_name(defaults)


def test_json_study_is_accepted(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"packtherm_study": 1, "cell": "pf", "duty": {"type": "constant", "c_rate": 1}}))
    spec = load_study(p).spec
    assert spec["cell"] == "PF" and spec["duty"]["c_rate"] == 1.0


def test_every_problem_is_reported_with_its_field():
    doc = {
        "packtherm_study": 1,
        "cell": "M51",
        "mode": "quick",
        "duty": {"type": "wltc", "speed_kmh": 100},
        "requirements": {"T_maxx_C": 40},
        "design_space": {"coolant_flows_g_s": [0.02, -0.05], "fillers": ["RT99"]},
        "options": {"edge_cells": "yes"},
    }
    with pytest.raises(StudyError) as e:
        validate(doc)
    msg = str(e.value)
    for field in (
        "cell: unknown cell 'M51'",
        "mode: must be one of",
        "duty.speed_kmh: not used by a wltc duty",
        "requirements.T_maxx_C: unknown key",
        "design_space.coolant_flows_g_s[1]: must be > 0",
        "design_space.fillers[0]: unknown filler 'RT99'",
        "options.edge_cells: must be true or false",
    ):
        assert field in msg


@pytest.mark.parametrize(
    "doc, err",
    [
        ({"cell": "M50", "duty": {"type": "constant"}}, "packtherm_study: required"),
        ({"packtherm_study": 2, "cell": "M50", "duty": {"type": "constant"}}, "reads format 1"),
        ({"packtherm_study": 1, "cell": "M50", "duty": {}}, "duty.type: required"),
        ({"packtherm_study": 1, "cell": "M50", "duty": {"type": "segments"}}, "duty.steps: required"),
        (
            {"packtherm_study": 1, "cell": "M50", "duty": {"type": "constant", "soc_min": 0.8, "soc_max": 0.2}},
            "soc_min: must be below",
        ),
        ({"packtherm_study": 1, "cell": "M50", "duty": {"type": "constant", "c_rate": True}}, "must be a number"),
        ([1, 2], "must be a mapping"),
    ],
)
def test_invalid_documents(doc, err):
    with pytest.raises(StudyError, match=err):
        validate(doc)


def test_run_writes_strict_json_with_picks_and_assumptions(tmp_path, capsys):
    study = tmp_path / "s.yaml"
    study.write_text(
        "packtherm_study: 1\n"
        "cell: M50\n"
        "mode: fast\n"
        "duty: {type: segments, steps: [[1200, 1.5], [600, -0.5]], rest_h: 0.5}\n"
        "design_space: {topologies: [air, ribbon], air_flows_g_s: [0.3], coolant_flows_g_s: [0.05],\n"
        "               chiller_C: [], fillers: [none]}\n"
        "options: {edge_cells: false}\n"
    )
    main(["run", str(study), "--out-dir", str(tmp_path / "out")])
    files = sorted(p.name for p in (tmp_path / "out").iterdir())
    assert files == [
        "module_m50_segments_25c_designs.csv",
        "module_m50_segments_25c_results.json",
        "module_m50_segments_25c_tradeoff.png",
    ]
    doc = json.loads((tmp_path / "out" / files[1]).read_text())  # strict: NaN would not parse back as null
    assert doc["packtherm_results"] == 1
    assert doc["summary"]["designs"] == len(doc["designs"]) == 2
    assert doc["study"]["mode"] == "fast" and doc["assumptions"]["resolution"]["name"] == "fast"
    assert {p["pick"] for p in doc["picks"]} <= {"lightest", "lowest_energy", "balanced"}
    assert "Wrote" in capsys.readouterr().out


def test_bad_study_file_exits_cleanly(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("packtherm_study: 1\ncell: M50\nduty: {type: constant, c_rate: -1}\n")
    with pytest.raises(SystemExit) as e:
        main(["run", str(bad)])
    assert e.value.code == 2
    assert "duty.c_rate: must be > 0" in capsys.readouterr().err


def test_every_key_is_documented():
    """docs/STUDY_FILES.md names every key the format accepts."""
    from pathlib import Path

    from packtherm.study import SECTIONS, TOP_KEYS

    doc = (Path(__file__).resolve().parents[1] / "docs" / "STUDY_FILES.md").read_text(encoding="utf-8")
    for name, keys in {"": TOP_KEYS, **SECTIONS}.items():
        if name:
            assert f"## `{name}`" in doc, name
        for k in keys:
            assert f"`{k}`" in doc, f"{name}.{k}" if name else k

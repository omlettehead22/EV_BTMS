"""Study files: one YAML or JSON document that fully describes a module design study.

The command line (``packtherm run study.yaml``), Python (``load_study``) and,
later, the HTTP API and web app all run the same file, so they cannot drift
apart. ``packtherm design --level module`` builds the same document from its
flags, then runs it.

Format version 1 (``packtherm template`` prints a commented example)::

    packtherm_study: 1
    cell: M50
    mode: normal                    # or fast
    ambient_C: 35
    duty: {type: roadtrip, speed_kmh: 130}
    requirements: {T_max_C: 45}
    design_space: {topologies: [air, bottom, ribbon]}
    options: {edge_cells: true}

Every key is optional except ``packtherm_study``, ``cell`` and ``duty.type``;
defaults are those of ``packtherm design``. Unknown keys, wrong types and
out-of-range values are rejected before anything runs, naming the field.
"""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FORMAT_VERSION = 1


class StudyError(ValueError):
    """A study document that cannot be run; the message lists every problem."""


# ---------------------------------------------------------------------------
# Schema: (type, default, check) per key. A check returns an error or None.
# ---------------------------------------------------------------------------


def _rule(**info):
    """Attach a machine-readable description to a check (used by ``schema()``)."""

    def wrap(check):
        check.info = info
        return check

    return wrap


@_rule(min=0, exclusive=True)
def _pos(x):
    return None if x > 0 else "must be > 0"


@_rule(min=0)
def _nonneg(x):
    return None if x >= 0 else "must be >= 0"


@_rule(min=0, max=1)
def _fraction(x):
    return None if 0 <= x <= 1 else "must be between 0 and 1"


def _choice(*opts):
    @_rule(choices=list(opts))
    def check(x):
        return None if x in opts else f"must be one of: {', '.join(map(str, opts))}"

    return check


def _optional(check):
    """The same check, with null allowed."""

    @_rule(**getattr(check, "info", {}))
    def opt(x):
        return None if x is None else check(x)

    return opt


NUM = (int, float)
OPT_NUM = (int, float, type(None))

DUTY_KEYS = {
    "type": (str, None, _choice("constant", "wltc", "roadtrip", "segments")),
    # constant
    "c_rate": (NUM, 1.0, _pos),
    "direction": (str, "discharge", _choice("discharge", "charge")),
    "soc0": (OPT_NUM, None, _optional(_fraction)),
    "soc_min": (NUM, 0.0, _fraction),
    "soc_max": (NUM, 1.0, _fraction),
    # wltc
    "cycles": (int, 3, _pos),
    # roadtrip
    "speed_kmh": (NUM, 130.0, _pos),
    "charge_c_rate": (OPT_NUM, None, _optional(_pos)),
    # EV duties
    "pack_kWh": (NUM, 60.0, _pos),
    "pack_V": (NUM, 350.0, _pos),
    # segments: [[duration_s, c_rate], ...], positive C-rate discharges
    "steps": (list, None, None),
    "name": (str, None, None),
    # all
    "rest_h": (NUM, 3.0, _nonneg),
}
# pack_kWh is allowed everywhere: it also sizes the pack-level cooling hardware.
DUTY_USES = {
    "constant": {"c_rate", "direction", "soc0", "soc_min", "soc_max", "pack_kWh"},
    "wltc": {"cycles", "pack_kWh", "pack_V"},
    "roadtrip": {"speed_kmh", "charge_c_rate", "pack_kWh", "pack_V"},
    "segments": {"steps", "name", "soc0", "soc_min", "soc_max", "pack_kWh"},
}

REQ_KEYS = {
    "T_max_C": (OPT_NUM, None, None),  # None: min(45, datasheet)
    "dT_cell_max_C": (NUM, 5.0, _pos),
    "recovery_max_min": (OPT_NUM, None, _optional(_nonneg)),
    "cell_to_cell_max_K": (OPT_NUM, None, _optional(_pos)),
}

SPACE_KEYS = {
    "topologies": (list, ["none", "air", "bottom", "ribbon"], None),
    "air_flows_g_s": (list, [0.15, 0.3, 0.6], None),
    "coolant_flows_g_s": (list, [0.02, 0.05], None),
    "chiller_C": (list, [15.0], None),
    "fillers": (list, ["none", "RT31", "RT42", "RT31-EG"], None),
    "gaps_mm": (list, [2.0], None),
    "packing": (str, "hex", _choice("hex", "square")),
}
SPACE_ITEMS = {  # per-item type and check for the lists
    "topologies": (str, _choice("none", "air", "bottom", "ribbon")),
    "air_flows_g_s": (NUM, _pos),
    "coolant_flows_g_s": (NUM, _pos),
    "chiller_C": (NUM, None),
    "fillers": (str, None),  # checked against the PCM library
    "gaps_mm": (NUM, _nonneg),
}

OPTION_KEYS = {
    "edge_cells": (bool, True, None),
    "wall_U": (NUM, 5.0, _nonneg),
    "r_margin": (NUM, 0.2, _nonneg),
    "chiller_cop": (OPT_NUM, None, _optional(_pos)),
    "chiller_runs": (str, "event", _choice("event", "always")),
    "liquid_loop_kg": (NUM, 3.0, _nonneg),
    "air_system_kg": (NUM, 4.0, _nonneg),
    "chiller_kg": (NUM, 4.0, _nonneg),
}

TOP_KEYS = {
    "packtherm_study": (int, None, None),
    "name": (str, None, None),
    "cell": ((str, dict), None, None),  # library key, cell file, or an inline definition
    "mode": (str, "normal", _choice("normal", "fast")),
    "ambient_C": (NUM, 25.0, None),
}
SECTIONS = {"duty": DUTY_KEYS, "requirements": REQ_KEYS, "design_space": SPACE_KEYS, "options": OPTION_KEYS}


def _type_ok(value, types) -> bool:
    if isinstance(value, bool) and bool not in (types if isinstance(types, tuple) else (types,)):
        return False  # true/false is not a number
    return isinstance(value, types)


def _type_name(types) -> str:
    names = {
        int: "an integer",
        float: "a number",
        str: "text",
        list: "a list",
        bool: "true or false",
        dict: "a mapping",
    }
    ts = types if isinstance(types, tuple) else (types,)
    if float in ts:
        base = "a number"
    else:
        base = " or ".join(names.get(t, t.__name__) for t in ts if t is not type(None))
    return base + (" or null" if type(None) in ts else "")


def _check_section(doc: dict, keys: dict, where: str, errors: list[str]) -> dict:
    out = {}
    for k in doc:
        if k not in keys:
            errors.append(f"{where}{k}: unknown key (allowed: {', '.join(keys)})")
    for k, (types, default, check) in keys.items():
        if k not in doc:
            out[k] = default
            continue
        v = doc[k]
        if not _type_ok(v, types):
            errors.append(f"{where}{k}: must be {_type_name(types)}, got {v!r}")
            continue
        if isinstance(v, float) and not math.isfinite(v):
            errors.append(f"{where}{k}: must be finite")
            continue
        msg = check(v) if check else None
        if msg:
            errors.append(f"{where}{k}: {msg}, got {v!r}")
            continue
        out[k] = float(v) if isinstance(v, int) and float in (types if isinstance(types, tuple) else ()) else v
    return out


def validate(doc: Any, base_dir: str | Path | None = None) -> dict:
    """Check a study document and return it with every default filled in.

    ``cell`` may be a library key, a cell file (.yaml/.yml/.json, relative to
    ``base_dir``) or an inline definition; a file is read and inlined, so the
    results carry the full cell. Raises StudyError listing every problem,
    each naming its field.
    """
    from .cells import CELLS as CELL_LIBRARY
    from .materials import PCM_LIBRARY

    errors: list[str] = []
    if not isinstance(doc, dict):
        raise StudyError("A study must be a mapping of keys to values (YAML or a JSON object).")
    top = {k: v for k, v in doc.items() if k not in SECTIONS}
    spec = _check_section(top, TOP_KEYS, "", errors)
    for k in ("packtherm_study", "cell"):
        if k not in doc:
            errors.append(f"{k}: required")
    if "packtherm_study" in doc and doc["packtherm_study"] != FORMAT_VERSION:
        errors.append(f"packtherm_study: this version reads format {FORMAT_VERSION}, got {doc['packtherm_study']!r}")
    cell = spec.get("cell")
    if isinstance(cell, str) and cell.lower().endswith((".yaml", ".yml", ".json")):
        from .user_cells import read_cell_file

        path = Path(cell) if base_dir is None or Path(cell).is_absolute() else Path(base_dir) / cell
        try:
            cell = spec["cell"] = read_cell_file(path)
        except FileNotFoundError:
            errors.append(f"cell: cell file not found: {path}")
            cell = None
        except ValueError as e:
            errors.append(f"cell: {e}")
            cell = None
    if isinstance(cell, dict):
        from .user_cells import CellError, validate_cell

        try:
            spec["cell"], _ = validate_cell(cell, "cell.")
        except CellError as e:
            errors.extend(line.strip() for line in str(e).splitlines()[1:])
    elif isinstance(cell, str) and cell.upper() not in {c.upper() for c in CELL_LIBRARY}:
        errors.append(
            f"cell: unknown cell {cell!r} (choose from {', '.join(CELL_LIBRARY)}, a cell file, or a definition)"
        )

    for name, keys in SECTIONS.items():
        sec = doc.get(name, {})
        if sec is None:
            sec = {}
        if not isinstance(sec, dict):
            errors.append(f"{name}: must be a mapping")
            sec = {}
        spec[name] = _check_section(sec, keys, f"{name}.", errors)

    duty, raw_duty = spec["duty"], doc.get("duty") or {}
    if isinstance(raw_duty, dict):
        if "type" not in raw_duty:
            errors.append("duty.type: required (constant, wltc, roadtrip or segments)")
        elif duty.get("type") in DUTY_USES:
            unused = set(raw_duty) - DUTY_USES[duty["type"]] - {"type", "rest_h"}
            for k in sorted(unused & set(DUTY_KEYS)):
                errors.append(f"duty.{k}: not used by a {duty['type']} duty")
            if duty["type"] == "segments":
                _check_steps(raw_duty.get("steps"), errors)
        if duty.get("soc_min", 0) >= duty.get("soc_max", 1):
            errors.append("duty.soc_min: must be below duty.soc_max")

    space, raw_space = spec["design_space"], doc.get("design_space") or {}
    for k, (types, check) in SPACE_ITEMS.items():
        v = space.get(k)
        if not isinstance(v, list):
            continue
        if k != "chiller_C" and not v:
            errors.append(f"design_space.{k}: must not be empty")
        for i, x in enumerate(v):
            if not _type_ok(x, types):
                errors.append(f"design_space.{k}[{i}]: must be {_type_name(types)}, got {x!r}")
            elif check and (msg := check(x)):
                errors.append(f"design_space.{k}[{i}]: {msg}, got {x!r}")
            elif k == "fillers" and x not in ("none", "air") and x not in PCM_LIBRARY:
                errors.append(f"design_space.fillers[{i}]: unknown filler {x!r} (none or {', '.join(PCM_LIBRARY)})")
        if all(_type_ok(x, types) for x in v) and types is NUM:
            space[k] = [float(x) for x in v]
    del raw_space

    if errors:
        raise StudyError("Invalid study:\n  " + "\n  ".join(errors))
    if isinstance(spec["cell"], str):
        spec["cell"] = next(c for c in CELL_LIBRARY if c.upper() == spec["cell"].upper())
    return spec


def _check_steps(steps, errors: list[str]) -> None:
    if not isinstance(steps, list) or not steps:
        errors.append("duty.steps: required for a segments duty: a list of [duration_s, c_rate]")
        return
    for i, s in enumerate(steps):
        ok = isinstance(s, list) and len(s) == 2 and all(_type_ok(x, NUM) for x in s)
        if not ok:
            errors.append(f"duty.steps[{i}]: must be [duration_s, c_rate], got {s!r}")
        elif s[0] <= 0:
            errors.append(f"duty.steps[{i}]: duration must be > 0, got {s[0]!r}")


# ---------------------------------------------------------------------------
# Machine-readable description of the format (the web app builds forms from it)
# ---------------------------------------------------------------------------


def _type_names(types) -> list[str]:
    ts = types if isinstance(types, tuple) else (types,)
    names = {int: "integer", float: "number", str: "string", list: "list", bool: "boolean", dict: "object"}
    out = [names[t] for t in ts if t is not type(None)]
    if "number" in out:
        out = [t for t in out if t != "integer"]
    return out + (["null"] if type(None) in ts else [])


def _describe(keys: dict) -> dict:
    out = {}
    for k, (types, default, check) in keys.items():
        d = {"type": _type_names(types), "default": default}
        d.update(getattr(check, "info", {}) if check else {})
        out[k] = d
    return out


def schema() -> dict:
    """The study format as data: every key's type, default and allowed values.

    ``required`` lists the keys without a default; ``duty.uses`` says which
    duty keys each duty type reads; ``design_space.items`` describes list items;
    ``cell`` describes an inline user-defined cell; ``library`` lists the cells
    and filler grades that names may refer to.
    """
    from .cells import CELLS as CELL_LIBRARY
    from .materials import PCM_LIBRARY
    from .user_cells import CELL_KEYS, FORMATS, REQUIRED

    top = _describe(TOP_KEYS)
    top["cell"]["type"] = ["string", "object"]
    space = _describe(SPACE_KEYS)
    for k, (types, check) in SPACE_ITEMS.items():
        space[k]["items"] = {"type": _type_names(types), **(getattr(check, "info", {}) if check else {})}
    space["fillers"]["items"]["choices"] = ["none", *PCM_LIBRARY]
    return {
        "packtherm_study": FORMAT_VERSION,
        "required": ["packtherm_study", "cell", "duty.type"],
        "top": top,
        "duty": {"keys": _describe(DUTY_KEYS), "uses": {t: sorted(u | {"rest_h"}) for t, u in DUTY_USES.items()}},
        "requirements": _describe(REQ_KEYS),
        "design_space": space,
        "options": _describe(OPTION_KEYS),
        "cell": {
            "keys": _describe(CELL_KEYS),
            "required": list(REQUIRED),
            "formats_mm": {k: {"diameter": d, "height": h} for k, (d, h) in FORMATS.items()},
        },
        "library": {
            "cells": {k: {"name": c.name, "model": c.model_label} for k, c in CELL_LIBRARY.items()},
            "fillers": list(PCM_LIBRARY),
        },
    }


# ---------------------------------------------------------------------------
# Loading and building
# ---------------------------------------------------------------------------


def parse(text: str, fmt: str = "yaml", base_dir: str | Path | None = None) -> dict:
    """Parse YAML (a superset of JSON) or JSON text into a validated study."""
    if fmt == "json":
        try:
            doc = json.loads(text)
        except json.JSONDecodeError as e:
            raise StudyError(f"Not valid JSON: {e}") from None
    else:
        import yaml

        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError as e:
            raise StudyError(f"Not valid YAML: {e}") from None
    return validate(doc, base_dir)


def load_study(path: str | Path) -> StudySpec:
    """Read a study file (.yaml, .yml or .json)."""
    path = Path(path)
    fmt = "json" if path.suffix.lower() == ".json" else "yaml"
    return StudySpec(parse(path.read_text(encoding="utf-8"), fmt, base_dir=path.parent))


def _duty(spec: dict, cell):
    from .design import DutyCycle
    from .ev import Pack, Vehicle, road_trip_duty, wltc_duty

    d = spec["duty"]
    rest = d["rest_h"] * 3600
    if d["type"] == "constant":
        return DutyCycle.constant(
            d["c_rate"], d["direction"], soc0=d["soc0"], soc_limits=(d["soc_min"], d["soc_max"]), rest_after_s=rest
        )
    if d["type"] == "segments":
        steps = tuple((float(a), float(b)) for a, b in d["steps"])
        soc0 = 1.0 if d["soc0"] is None else d["soc0"]
        return DutyCycle(
            d["name"] or "custom segments",
            steps=steps,
            soc0=soc0,
            soc_limits=(d["soc_min"], d["soc_max"]),
            rest_after_s=rest,
        )
    pack = Pack.for_energy(cell, d["pack_kWh"], d["pack_V"])
    if d["type"] == "wltc":
        return wltc_duty(cell, pack, Vehicle(), cycles=d["cycles"], rest_after_s=rest)
    return road_trip_duty(
        cell, pack, Vehicle(), speed_kmh=d["speed_kmh"], charge_c_rate=d["charge_c_rate"], rest_after_s=rest
    )


def file_stem(spec: dict) -> str:
    """Output file stem, the same as ``packtherm design`` uses."""
    d = spec["duty"]
    cell = (
        spec["cell"].lower()
        if isinstance(spec["cell"], str)
        else re.sub(r"\W+", "_", spec["cell"]["name"].lower()).strip("_")
    )
    if d["type"] == "constant":
        stem = f"{cell}_{d['direction']}_{d['c_rate']:g}C"
    elif d["type"] == "wltc":
        stem = f"{cell}_wltc{d['cycles']}"
    elif d["type"] == "roadtrip":
        stem = f"{cell}_roadtrip_{d['speed_kmh']:g}kmh"
    else:
        stem = f"{cell}_segments"
    stem = f"module_{stem}_{spec['ambient_C']:g}C"
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9_.]+", "_", stem.lower()))


@dataclass
class StudySpec:
    """A validated study document."""

    spec: dict

    def build(self):
        """The ModuleStudy this document describes."""
        from .cells import get_cell
        from .design import Requirements
        from .hardware import PackHardware
        from .module import Chiller, Wall
        from .module_design import ModuleStudy

        s = self.spec
        cell = get_cell(s["cell"]) if isinstance(s["cell"], str) else self.cell()
        r, sp, o = s["requirements"], s["design_space"], s["options"]
        req = Requirements(
            T_max_C=r["T_max_C"],
            dT_cell_max_C=r["dT_cell_max_C"],
            T_env_C=s["ambient_C"],
            recovery_max_min=r["recovery_max_min"],
        )
        return ModuleStudy(
            cell,
            _duty(s, cell),
            req,
            topologies=tuple(sp["topologies"]),
            air_flows_g_s=tuple(sp["air_flows_g_s"]),
            coolant_flows_g_s=tuple(sp["coolant_flows_g_s"]),
            chiller_inlets_C=tuple(sp["chiller_C"]),
            fillers=tuple(None if f in ("none", "air") else f for f in sp["fillers"]),
            gaps_mm=tuple(sp["gaps_mm"]),
            packing=sp["packing"],
            cell_to_cell_max_K=r["cell_to_cell_max_K"],
            edge_cells=o["edge_cells"],
            wall=Wall(U=o["wall_U"]),
            pack=PackHardware(
                pack_kWh=s["duty"]["pack_kWh"],
                liquid_loop_kg=o["liquid_loop_kg"],
                air_system_kg=o["air_system_kg"],
                chiller_kg=o["chiller_kg"],
            ),
            chiller=Chiller(cop=o["chiller_cop"]),
            chiller_runs=o["chiller_runs"],
            resistance_margin=o["r_margin"],
            mode=s["mode"],
        )

    def cell(self):
        """The study's cell (a library cell, or the user-defined one)."""
        from .cells import get_cell
        from .user_cells import cell_from_spec

        c = self.spec["cell"]
        return get_cell(c) if isinstance(c, str) else cell_from_spec(c)

    def cell_warnings(self) -> list[str]:
        """Plausibility warnings for a user-defined cell (none for a library cell)."""
        from .user_cells import validate_cell

        c = self.spec["cell"]
        return [] if isinstance(c, str) else validate_cell(c, "cell.")[1]

    def run(self, workers: int | None = None, progress=None) -> StudyRun:
        """Run the study. progress(stage, done, total) is called as designs finish."""
        from .module_design import run_module_study

        study = self.build()
        t0 = time.perf_counter()
        result = run_module_study(study, workers=workers, progress=progress)
        return StudyRun(self, study, result, time.perf_counter() - t0)


@dataclass
class StudyRun:
    """A study and its result, with the JSON results document."""

    spec: StudySpec
    study: Any
    result: Any
    elapsed_s: float
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def to_json(self) -> dict:
        """The results document (also the API's response format)."""
        from . import __version__

        res, st = self.result, self.study
        t = res.table
        picks = []
        for key, row in res.picks.items():
            picks.append({"pick": key, **_row(row)})
        n_feasible = int(t.feasible.sum())
        return {
            "packtherm_results": FORMAT_VERSION,
            "packtherm_version": __version__,
            "created": self.created,
            "elapsed_s": round(self.elapsed_s, 2),
            "study": self.spec.spec,
            "summary": {
                "cell": st.cell.name,
                "cell_model": st.cell.model_label,
                "duty": st.duty.name,
                "mode": st.mode,
                "designs": len(t),
                "feasible": n_feasible,
                "on_front": len(res.front),
                "T_limit_C": _num(t.T_limit_C.iloc[0]) if len(t) else None,
                "text": res.summary(),
            },
            "picks": picks,
            "notes": list(res.warnings) + list(res.notes()) + [f"WARNING: {w}" for w in self.spec.cell_warnings()],
            "assumptions": _assumptions(st),
            "designs": [_row(r) for _, r in t.iterrows()],
        }

    def write(self, out_dir: str | Path) -> dict[str, Path]:
        """Write results.json, the designs CSV and the trade-off chart."""
        from .report import plot_tradeoff

        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        stem = file_stem(self.spec.spec)
        paths = {
            "json": out / f"{stem}_results.json",
            "csv": out / f"{stem}_designs.csv",
            "chart": out / f"{stem}_tradeoff.png",
        }
        paths["json"].write_text(json.dumps(self.to_json(), indent=1, allow_nan=False), encoding="utf-8")
        self.result.table.to_csv(paths["csv"], index=False)
        plot_tradeoff(self.result, paths["chart"])
        return paths


def _num(x):
    """JSON-safe value: NaN and infinities become null, numpy scalars plain."""
    if x is None:
        return None
    if hasattr(x, "item"):
        x = x.item()
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return x


def _row(row) -> dict:
    return {k: _num(v) for k, v in row.items()}


def _assumptions(st) -> dict:
    """The labelled assumptions behind every number, so a results file carries them."""
    c, a = st.coolant, st.air
    return {
        "resolution": {k: v for k, v in vars(st.resolution).items()},
        "coolant": {
            "flow_ref_g_s_per_cell": c.flow_ref_g_s,
            "h_ref_W_m2K": c.h_ref,
            "dp_module_ref_Pa": c.dp_ref_Pa,
            "dp_loop_ref_Pa": c.dp_loop_ref_Pa,
            "pump_efficiency": c.pump_efficiency,
            "radiator_fan_W_per_W": c.radiator_fan_W_per_W,
        },
        "air": {
            "flow_ref_g_s_per_cell": a.flow_ref_g_s,
            "h_ref_W_m2K": a.h_ref,
            "dp_ref_Pa": a.dp_ref_Pa,
            "fan_efficiency": a.fan_efficiency,
            "gap_ref_mm": a.gap_ref_mm,
        },
        "chiller": {k: v for k, v in vars(st.chiller).items()},
        "wall_U_W_m2K": st.wall.U,
        "resistance_margin": st.resistance_margin,
        "pack_hardware": {k: v for k, v in vars(st.pack).items()},
    }


TEMPLATE = """\
# PackTherm study file, format 1. Every key below shows its default;
# delete what you don't need. Run with: packtherm run study.yaml --out-dir results/
packtherm_study: 1
name: my study                  # optional label
cell: M50                       # packtherm cells lists the library
mode: normal                    # normal, or fast (about 5x quicker; docs/FAST_MODE.md)
ambient_C: 25

duty:
  type: roadtrip                # constant, wltc, roadtrip or segments
  speed_kmh: 130                # roadtrip: motorway speed, 90% -> 10%, then a rapid charge
  charge_c_rate: null           # roadtrip: null = the cell's maximum charge rate
  pack_kWh: 60                  # pack size: sets the EV duties' current and sizes pack hardware
  pack_V: 350
  rest_h: 3                     # rest simulated after the event, for recovery
  # constant: c_rate: 1.0, direction: discharge, soc0: null, soc_min: 0, soc_max: 1
  # wltc: cycles: 3
  # segments: steps: [[600, 1.0], [300, -0.5]]   (seconds, C-rate; negative charges)

requirements:
  T_max_C: null                 # null = min(45 degC, datasheet limit)
  dT_cell_max_C: 5              # in-cell spread
  recovery_max_min: null        # null = within the rest window
  cell_to_cell_max_K: null      # null = report only

design_space:
  topologies: [none, air, bottom, ribbon]
  air_flows_g_s: [0.15, 0.3, 0.6]       # per cell
  coolant_flows_g_s: [0.02, 0.05]       # per cell
  chiller_C: [15]                       # chiller set-points; [] = no chiller
  fillers: [none, RT31, RT42, RT31-EG]  # between the cans
  gaps_mm: [2]                          # ribbons widen to their minimum
  packing: hex                          # or square

options:
  edge_cells: true              # also simulate cells on the module wall
  wall_U: 5                     # module wall, W/m2K
  r_margin: 0.2                 # worst-case resistance margin above the datasheet maximum
  chiller_cop: null             # null = from ambient (Carnot fraction)
  chiller_runs: event           # event (then radiator) or always
  liquid_loop_kg: 3
  air_system_kg: 4
  chiller_kg: 4
"""

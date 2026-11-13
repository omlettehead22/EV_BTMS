"""User-defined cylindrical cells from datasheet values.

A cell is described by what a datasheet gives: size, mass, capacity, nominal
voltage, DC resistance and limits. It uses the lumped resistance model (as the
library's LG MJ1): heat I^2 R(SOC, T) plus entropic heat, with no voltage
model, so no voltage cut-off or constant-voltage charge taper. Results on it
are labelled "user-defined, lumped DCIR" and are less accurate than the
validated cells.

Chemistries (v0.5.2):

* ``NMC``: NMC/graphite. Jelly-roll heat capacity and conductivities from the
  layer properties behind the LG M50 (O'Regan 2022), NMC811/graphite entropic
  heat.
* ``NCA``: NCA/graphite. The same jelly-roll properties (an assumption); no
  entropic heat, as for the validated Panasonic NCA cell, because published
  NCA entropic profiles disagree even on sign.

Values are checked for plausibility so a unit slip (mass in kg, resistance in
ohms) fails loudly; values that are possible but unusual give warnings.

YAML example::

    name: My 21700 cell
    format: 21700
    chemistry: NMC
    capacity_Ah: 5.0
    V_nominal: 3.6
    mass_g: 69
    DCIR_mOhm: 22
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .cells import (
    Cell,
    nmc811_graphite_dUdT,
    nmc811_jellyroll_k_axial,
    nmc811_jellyroll_properties,
)

# Nominal can sizes [mm] (diameter, height). Override with diameter_mm and height_mm.
FORMATS = {"18650": (18.4, 65.0), "21700": (21.1, 70.1), "26650": (26.2, 65.2), "4680": (46.0, 80.0)}
CHEMISTRIES = ("NMC", "NCA")


class CellError(ValueError):
    """A cell definition that cannot be used; the message lists every problem."""


def _pos(x):
    return None if x > 0 else "must be > 0"


NUM = (int, float)
OPT_NUM = (int, float, type(None))


def _opt_pos(x):
    return None if x is None else _pos(x)


CELL_KEYS = {
    "name": (str, None, None),
    # (int, str): YAML reads an unquoted 21700 as a number
    "format": (
        (str, int, type(None)),
        None,
        lambda x: None if x is None or str(x) in FORMATS else f"must be one of: {', '.join(FORMATS)}",
    ),
    "diameter_mm": (OPT_NUM, None, _opt_pos),
    "height_mm": (OPT_NUM, None, _opt_pos),
    "chemistry": (
        str,
        "NMC",
        lambda x: None if x.upper() in CHEMISTRIES else f"must be one of: {', '.join(CHEMISTRIES)}",
    ),
    "capacity_Ah": (NUM, None, _pos),
    "V_nominal": (NUM, None, _pos),
    "mass_g": (NUM, None, _pos),
    "DCIR_mOhm": (NUM, None, _pos),
    "DCIR_max_mOhm": (OPT_NUM, None, _opt_pos),
    "max_discharge_A": (OPT_NUM, None, _opt_pos),
    "max_charge_A": (OPT_NUM, None, _opt_pos),
    "T_max_charge_C": (OPT_NUM, None, None),
    "T_max_discharge_C": (OPT_NUM, None, None),
    # Optional overrides for anyone with better data
    "cp_J_kgK": (OPT_NUM, None, _opt_pos),
    "k_radial_W_mK": (OPT_NUM, None, _opt_pos),
    "k_axial_W_mK": (OPT_NUM, None, _opt_pos),
    "Ea_kJ_mol": (OPT_NUM, None, lambda x: None if x is None or x >= 0 else "must be >= 0"),
    "entropic": (bool, True, None),
    "source": ((str, type(None)), None, None),
}
REQUIRED = ("name", "capacity_Ah", "V_nominal", "mass_g", "DCIR_mOhm")


def validate_cell(doc: Any, where: str = "cell.") -> tuple[dict, list[str]]:
    """Check a cell definition; return it with defaults filled in, and warnings.

    Raises CellError listing every problem, each naming its field.
    """
    from .study import _check_section

    errors: list[str] = []
    if not isinstance(doc, dict):
        raise CellError(f"{where.rstrip('.')}: a cell definition must be a mapping of keys to values")
    spec = _check_section(doc, CELL_KEYS, where, errors)
    for k in REQUIRED:
        if k not in doc:
            errors.append(f"{where}{k}: required")
    if spec.get("format") is None and (spec.get("diameter_mm") is None or spec.get("height_mm") is None):
        errors.append(f"{where}format: give a format ({', '.join(FORMATS)}) or both diameter_mm and height_mm")
    if errors:
        raise CellError("Invalid cell:\n  " + "\n  ".join(errors))

    spec["chemistry"] = spec["chemistry"].upper()
    if spec["format"] is not None:
        spec["format"] = str(spec["format"])
    d, h = FORMATS.get(spec["format"] or "", (None, None))
    spec["diameter_mm"] = spec["diameter_mm"] if spec["diameter_mm"] is not None else d
    spec["height_mm"] = spec["height_mm"] if spec["height_mm"] is not None else h
    warnings = _plausibility(spec, where, errors)
    if errors:
        raise CellError("Implausible cell (check the units):\n  " + "\n  ".join(errors))
    return spec, warnings


def _plausibility(s: dict, where: str, errors: list[str]) -> list[str]:
    """Errors for values no real cylindrical Li-ion cell has (usually a unit slip); warnings for unusual ones."""
    warn: list[str] = []
    dia, hgt = s["diameter_mm"], s["height_mm"]
    if not 8 <= dia <= 60:
        errors.append(f"{where}diameter_mm: {dia:g} mm is outside 8-60 mm for a cylindrical cell")
    if not 30 <= hgt <= 200:
        errors.append(f"{where}height_mm: {hgt:g} mm is outside 30-200 mm for a cylindrical cell")
    if errors:
        return warn
    vol_cm3 = math.pi * (dia / 20) ** 2 * (hgt / 10)
    rho = s["mass_g"] / vol_cm3
    if not 1.5 <= rho <= 4.0:
        hint = " (mass_g is in grams)" if rho < 1.5 else ""
        errors.append(f"{where}mass_g: gives a density of {rho:.2f} g/cm3, outside 1.5-4.0{hint}")
    elif not 2.2 <= rho <= 3.2:
        warn.append(f"{where}mass_g: density {rho:.2f} g/cm3 is unusual (most cells 2.2-3.2)")
    if not 2.5 <= s["V_nominal"] <= 4.2:
        errors.append(f"{where}V_nominal: {s['V_nominal']:g} V is outside 2.5-4.2 V for NMC/NCA")
    elif not 3.4 <= s["V_nominal"] <= 3.8:
        warn.append(f"{where}V_nominal: {s['V_nominal']:g} V is unusual for NMC/NCA (most 3.6-3.7 V)")
    wh_l = s["capacity_Ah"] * s["V_nominal"] / (vol_cm3 / 1000)
    if not 100 <= wh_l <= 1000:
        hint = " (capacity_Ah is in amp-hours, not mAh)" if wh_l > 10_000 else ""
        errors.append(f"{where}capacity_Ah: gives {wh_l:.0f} Wh/L, outside 100-1000 Wh/L{hint}")
    elif wh_l > 800:
        warn.append(f"{where}capacity_Ah: {wh_l:.0f} Wh/L is above any production cell (about 800)")
    r = s["DCIR_mOhm"]
    if not 0.5 <= r <= 500:
        hint = " (DCIR_mOhm is in milliohms)" if r < 0.5 else ""
        errors.append(f"{where}DCIR_mOhm: {r:g} mOhm is outside 0.5-500{hint}")
    rmax = s["DCIR_max_mOhm"]
    if rmax is not None and rmax < r:
        errors.append(f"{where}DCIR_max_mOhm: {rmax:g} is below DCIR_mOhm ({r:g})")
    for k in ("max_discharge_A", "max_charge_A"):
        if s[k] is not None and s[k] / s["capacity_Ah"] > 20:
            warn.append(f"{where}{k}: {s[k] / s['capacity_Ah']:.0f}C is very high")
    for k in ("T_max_charge_C", "T_max_discharge_C"):
        if s[k] is not None and not 20 <= s[k] <= 90:
            errors.append(f"{where}{k}: {s[k]:g} degC is outside 20-90 degC")
    if s["chemistry"] == "NCA" and s["entropic"]:
        warn.append(
            f"{where}chemistry: NCA has no entropic heat in PackTherm (published profiles disagree); "
            "set entropic: false to silence this"
        )
    return warn


def _milli(x: float) -> float:
    """x / 1000, by moving the decimal point: float("65.1e-3") is exactly the literal
    65.1e-3, where 65.1 / 1000 is one unit in the last place off."""
    return float(f"{float(x)!r}e-3")


def _zero(_soc: float) -> float:
    return 0.0


def cell_from_spec(spec: dict) -> Cell:
    """Build a Cell from a validated definition (see ``validate_cell``)."""
    _, cp_jr, k_jr = nmc811_jellyroll_properties()
    entropic = spec["entropic"] and spec["chemistry"] == "NMC"
    cap = float(spec["capacity_Ah"])
    r0 = _milli(spec["DCIR_mOhm"])
    rmax = _milli(spec["DCIR_max_mOhm"] or spec["DCIR_mOhm"])
    kw = {}
    if spec["Ea_kJ_mol"] is not None:
        kw["Ea_R"] = spec["Ea_kJ_mol"] * 1e3
    return Cell(
        name=spec["name"],
        form_factor=spec["format"] or f"{spec['diameter_mm']:g} x {spec['height_mm']:g} mm",
        chemistry=f"{spec['chemistry']} / graphite",
        capacity_Ah=cap,
        V_nominal=float(spec["V_nominal"]),
        diameter=_milli(spec["diameter_mm"]),
        height=_milli(spec["height_mm"]),
        mass=_milli(spec["mass_g"]),
        R0_25C=r0,
        R0_range=(r0, rmax),
        cp=spec["cp_J_kgK"] or cp_jr,
        k_radial=spec["k_radial_W_mK"] or k_jr,
        k_axial=spec["k_axial_W_mK"] or nmc811_jellyroll_k_axial(),
        dUdT=nmc811_graphite_dUdT if entropic else _zero,
        max_charge_C=None if spec["max_charge_A"] is None else spec["max_charge_A"] / cap,
        max_discharge_C=None if spec["max_discharge_A"] is None else spec["max_discharge_A"] / cap,
        T_max_charge_C=spec["T_max_charge_C"],
        T_max_discharge_C=spec["T_max_discharge_C"],
        sources=(spec["source"] or "user datasheet",),
        model_label="user-defined, lumped DCIR",
        user_defined=True,
        **kw,
    )


def read_cell_file(path: str | Path) -> dict:
    """The raw definition in a .yaml/.yml/.json cell file."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise CellError(f"{path}: not valid JSON: {e}") from None
    import yaml

    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise CellError(f"{path}: not valid YAML: {e}") from None


def load_cell(path: str | Path) -> Cell:
    """A user-defined cell from a file (warnings are ignored; ``validate_cell`` returns them)."""
    spec, _ = validate_cell(read_cell_file(path))
    return cell_from_spec(spec)


def from_datasheet(**values) -> Cell:
    """A user-defined cell from keyword arguments, e.g. ``from_datasheet(name=..., format="21700", ...)``."""
    spec, _ = validate_cell(values)
    return cell_from_spec(spec)

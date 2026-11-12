"""Design advisor: sweep cooling and PCM choices for one cell and duty, find the trade-off.

Design variables
----------------
* cooling: natural convection, forced air at a range of h, liquid at a range
  of h, optionally with a chiller holding the coolant below ambient
* PCM: none, or a grade from :mod:`packtherm.materials` at a range of thicknesses

Each design is scored on two costs:

* **mass overhead**: PCM + casing + cooling hardware as % of cell mass
* **auxiliary energy**: fan/pump electricity plus chiller electricity, as % of
  the energy the cell moves. Cooling runs until the cell is ready again, so
  slow recovery costs energy.

A design is *feasible* if the peak cell temperature and in-cell spread stay
within the requirements and it recovers in time for the next event (within
1 K of ambient, PCM re-solidified). The feasible designs that no other
feasible design beats on both costs form the Pareto front; three picks are
made from it (lightest, lowest-energy, balanced). Every front design is
re-checked at worst-case resistance: the top of the published spread plus a
margin for ageing.
"""

from __future__ import annotations

import math
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field, replace
from typing import ClassVar

import numpy as np
import pandas as pd

from .cells import Cell, with_R0
from .electrothermal import CurrentProfile, check_limits, segments, simulate_cell
from .materials import PCM_LIBRARY, melt_midpoint_C
from .params import DEFAULT_AUX_POWER, DEFAULT_H, KELVIN, Params

# ---------------------------------------------------------------------------
# Cooling options
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FanLaw:
    """Fan/pump electrical power needed to reach a convective coefficient h.

    Forced convection gives Nu ~ Re^0.8 (Dittus-Boelter), so h ~ v^0.8, while
    fan/pump power ~ pressure drop x flow ~ v^3. Hence P ~ h^(3/0.8) = h^3.75.
    Anchored at one (h, power) pair; the thesis mid levels are the default
    anchors. Valid near the anchor; h is best swept within the thesis range.
    """

    h_ref: float  # W/(m^2 K)
    P_ref_W: float  # pack-level electrical power at h_ref
    exponent: float = 3.75

    def power(self, h: float) -> float:
        return self.P_ref_W * (h / self.h_ref) ** self.exponent


AIR_FAN = FanLaw(DEFAULT_H["air"]["mid"], DEFAULT_AUX_POWER["air"]["mid"])
LIQUID_PUMP = FanLaw(DEFAULT_H["liquid"]["mid"], DEFAULT_AUX_POWER["liquid"]["mid"])

# ASSUMPTION: cooling hardware mass. Industry figures put cooling-system mass
# at roughly 0.5-5 kg per kWh of capacity depending on architecture
# (e-Mobility Engineering, issue 33). Air (fans, ducts) is taken at the low end
# and liquid (cold plates, coolant, pump) at 1 kg/kWh. A chiller adds more.
HARDWARE_KG_PER_KWH = {"natural": 0.0, "air": 0.5, "liquid": 1.0, "chiller": 0.3}

# Vapour-compression chillers typically reach a COP of about 2.4-3.5.
DEFAULT_CHILLER_COP = 3.0


@dataclass(frozen=True)
class CoolingOption:
    name: str
    kind: str  # "natural" | "air" | "liquid"
    h: float  # W/(m^2 K), on the cell sleeve's outer surface
    aux_power_pack_W: float  # fan/pump electrical power for the whole pack
    hardware_kg_per_kWh: float = 0.0  # ducts, fans, cold plates, coolant per kWh of cells
    coolant_C: float | None = None  # chiller setpoint; None = coolant/air at ambient

    @property
    def chilled(self) -> bool:
        return self.coolant_C is not None


def cooling_options(
    air_h: tuple[float, ...] = (10.0, 15.0, 22.0, 33.0, 45.0, 60.0),
    liquid_h: tuple[float, ...] = (100.0, 180.0, 330.0, 600.0),
    chiller_setpoints_C: tuple[float, ...] = (15.0,),
    include_natural: bool = True,
    air_law: FanLaw = AIR_FAN,
    liquid_law: FanLaw = LIQUID_PUMP,
    hardware_kg_per_kWh: dict[str, float] | None = None,
) -> list[CoolingOption]:
    """Continuous-h cooling options with fan-law auxiliary power.

    Every liquid h is offered at ambient (radiator) and at each chiller setpoint.
    """
    hw = {**HARDWARE_KG_PER_KWH, **(hardware_kg_per_kWh or {})}
    opts = []
    if include_natural:
        opts.append(CoolingOption("natural", "natural", 5.0, 0.0, hw["natural"]))
    for h in air_h:
        opts.append(CoolingOption(f"air h={h:g}", "air", h, air_law.power(h), hw["air"]))
    for h in liquid_h:
        opts.append(CoolingOption(f"liquid h={h:g}", "liquid", h, liquid_law.power(h), hw["liquid"]))
        for sp in chiller_setpoints_C:
            opts.append(
                CoolingOption(
                    f"liquid h={h:g} @{sp:g}°C", "liquid", h, liquid_law.power(h), hw["liquid"] + hw["chiller"], sp
                )
            )
    return opts


def thesis_cooling_options(hardware_kg_per_kWh: dict[str, float] | None = None) -> list[CoolingOption]:
    """The original discrete thesis levels (natural + air/liquid low/mid/high)."""
    hw = {**HARDWARE_KG_PER_KWH, **(hardware_kg_per_kWh or {})}
    opts = [CoolingOption("natural", "natural", 5.0, 0.0, hw["natural"])]
    for kind in ("air", "liquid"):
        for level in ("low", "mid", "high"):
            opts.append(
                CoolingOption(f"{kind}-{level}", kind, DEFAULT_H[kind][level], DEFAULT_AUX_POWER[kind][level], hw[kind])
            )
    return opts


default_cooling_options = cooling_options


# ---------------------------------------------------------------------------
# Duty cycles and requirements
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DutyCycle:
    """A picklable current-profile recipe (so studies can run in parallel)."""

    name: str
    c_rate: float = 1.0
    mode: str = "discharge"  # for constant duties
    steps: tuple[tuple[float, float], ...] = ()  # (duration_s, c_rate) for segment duties
    repeat: bool = False
    duration: float | None = None  # s; default: time to cross the SOC window +5 %
    soc0: float = 1.0
    soc_limits: tuple[float, float] = (0.0, 1.0)
    # Rest simulated after the event to measure recovery (cool-down and PCM
    # re-solidification) before the next event.
    rest_after_s: float = 3 * 3600.0

    @classmethod
    def constant(cls, c_rate: float, mode: str = "discharge", soc0: float | None = None, soc_limits=(0.0, 1.0), **kw):
        if soc0 is None:
            soc0 = soc_limits[1] if mode == "discharge" else soc_limits[0]
        name = kw.pop("name", f"{mode} {c_rate:g}C {soc_limits[0]:.0%}-{soc_limits[1]:.0%}")
        return cls(name=name, c_rate=c_rate, mode=mode, soc0=soc0, soc_limits=soc_limits, **kw)

    @property
    def is_charge(self) -> bool:
        if self.steps:
            return any(c < 0 for _, c in self.steps)
        return self.mode == "charge"

    @property
    def is_mixed(self) -> bool:
        return bool(self.steps) and any(c < 0 for _, c in self.steps) and any(c > 0 for _, c in self.steps)

    def profile(self, cell: Cell) -> CurrentProfile:
        """Current profile; zero after the event so the rest period is a true rest."""
        if self.steps:
            return segments(cell, list(self.steps), repeat=self.repeat)
        sign = 1.0 if self.mode == "discharge" else -1.0
        return segments(cell, [(self.event_duration(), sign * self.c_rate)])

    def event_duration(self) -> float:
        if self.duration is not None:
            return self.duration
        if self.steps:
            return float(sum(d for d, _ in self.steps))
        window = self.soc_limits[1] - self.soc_limits[0]
        return 3600.0 * window / self.c_rate * 1.05


@dataclass(frozen=True)
class Requirements:
    """Design limits. ``T_max_C=None`` means min(45 degC, datasheet limit).

    45 degC is a common pack design target for cycle life; datasheet limits
    (50-60 degC) are abuse limits, not design targets.
    """

    T_max_C: float | None = None
    dT_cell_max_C: float = 5.0
    T_env_C: float = 25.0
    # Max time after the current stops until the cell is within 1 K of ambient
    # and the PCM has re-solidified, i.e. ready for an identical event.
    # None = must recover within the duty's simulated rest window;
    # math.inf = report only, never reject.
    recovery_max_min: float | None = None

    def T_limit(self, cell: Cell, charging: bool) -> float:
        if self.T_max_C is not None:
            return self.T_max_C
        datasheet = cell.T_max_charge_C if charging else cell.T_max_discharge_C
        return min(45.0, datasheet) if datasheet is not None else 45.0


@dataclass(frozen=True)
class DesignStudy:
    cell: Cell
    duty: DutyCycle
    requirements: Requirements = field(default_factory=Requirements)
    cooling_options: tuple[CoolingOption, ...] = field(default_factory=lambda: tuple(cooling_options()))
    pcm_grades: tuple[str, ...] = ("RT28HC", "RT31", "OM35", "RT42")
    pcm_thicknesses_mm: tuple[float, ...] = (2.0, 4.0)  # "no PCM" is always included
    case_thickness_mm: float = 1.0
    # ASSUMPTION: converts the pack-level fan/pump powers to per cell.
    cells_in_pack: int = 100
    case_density: float = 2700.0  # Al 6061
    chiller_cop: float = DEFAULT_CHILLER_COP
    # ASSUMPTION: worst-case resistance = top of published spread x (1 + margin),
    # covering end-of-life growth. Front designs are re-checked at it.
    resistance_margin: float = 0.2
    dt: float = 2.0  # s; within 0.01 degC of dt = 0.5 s on peak temperature

    def pcm_choices(self) -> list[tuple[str | None, float]]:
        return [(None, 0.0)] + [(g, mm) for g in self.pcm_grades for mm in self.pcm_thicknesses_mm if mm > 0]

    @property
    def R0_worst(self) -> float:
        return max(self.cell.R0_range[1], self.cell.R0_25C) * (1.0 + self.resistance_margin)


def pcm_label(grade: str | None, mm: float) -> str:
    return "no PCM" if not grade or mm == 0 else f"{grade} {mm:g} mm"


def _sleeve_masses(study: DesignStudy, grade: str | None, pcm_mm: float) -> tuple[float, float]:
    """PCM and casing mass per cell [kg]."""
    r_c = study.cell.radius
    r_p = r_c + pcm_mm * 1e-3
    r_o = r_p + study.case_thickness_mm * 1e-3
    L = study.cell.height
    rho_pcm = PCM_LIBRARY[grade].rho if grade else 0.0
    m_pcm = rho_pcm * math.pi * (r_p**2 - r_c**2) * L
    m_case = study.case_density * math.pi * (r_o**2 - r_p**2) * L
    return m_pcm, m_case


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def evaluate_design(
    study: DesignStudy, cooling: CoolingOption, grade: str | None, pcm_mm: float, R0: float | None = None
) -> dict:
    """Simulate one design and return its metrics row."""
    if grade is None or pcm_mm == 0:
        grade, pcm_mm = None, 0.0
    cell = study.cell if R0 is None else with_R0(study.cell, R0)
    duty = study.duty
    req = study.requirements
    T_amb = req.T_env_C + KELVIN
    T_sink = T_amb if cooling.coolant_C is None else min(cooling.coolant_C + KELVIN, T_amb)
    pcm = PCM_LIBRARY[grade] if grade else PCM_LIBRARY["RT31"]  # unused when thickness is 0
    base = Params(pcm=pcm, T_initial=T_amb)
    base = base.with_(solver=replace(base.solver, dt=study.dt, store_every=max(1, int(60 / study.dt))))
    event = duty.event_duration()
    duration = event + (0.0 if duty.repeat else duty.rest_after_s)
    res, load = simulate_cell(
        cell,
        duty.profile(cell),
        duration,
        cooling.h,
        T_sink,
        pcm_thickness=pcm_mm * 1e-3,
        case_thickness=study.case_thickness_mm * 1e-3,
        soc0=duty.soc0,
        soc_limits=duty.soc_limits,
        base=base,
        T_initial=T_amb,
    )
    a = load.arrays()
    dt = np.diff(res.t)
    throughput_Wh = float(np.sum(np.abs(a["current_A"]) * dt)) * cell.V_nominal / 3600.0

    # Recovery: first time after the current stops with T_max within 1 K of
    # ambient and the PCM (almost) fully solid.
    active = np.flatnonzero(np.abs(a["current_A"]) > 0)
    t_stop = float(a["t"][active[-1]] + study.dt) if active.size else 0.0
    after = res.t >= t_stop - 1e-9
    ready = after & (res.T_max - T_amb < 1.0) & (res.pcm_fraction < 0.01)
    recovered = bool(ready.any()) and not duty.repeat
    recovery_min = float((res.t[ready][0] - t_stop) / 60.0) if recovered else np.nan
    t_ready = t_stop + recovery_min * 60.0 if recovered else float(res.t[-1])
    i_ready = int(np.searchsorted(res.t, t_ready, side="right"))

    # Cooling runs until the cell is ready again.
    fan_pump_Wh = cooling.aux_power_pack_W / study.cells_in_pack * t_ready / 3600.0
    chiller_Wh = 0.0
    if cooling.chilled and T_sink < T_amb:
        heat_out_J = float(np.clip(res.dE_boundary[:i_ready], 0.0, None).sum())
        chiller_Wh = heat_out_J / study.chiller_cop / 3600.0
    aux_Wh = fan_pump_Wh + chiller_Wh

    m_pcm, m_case = _sleeve_masses(study, grade, pcm_mm)
    cell_kWh = cell.capacity_Ah * cell.V_nominal / 1e3
    m_hw = cooling.hardware_kg_per_kWh * cell_kWh
    m_over = m_pcm + m_case + m_hw

    T_limit = req.T_limit(study.cell, duty.is_charge)
    T_peak = float(res.T_max.max() - KELVIN)
    dT = float(res.dT_cell.max())
    if duty.repeat or req.recovery_max_min == math.inf:
        rec_ok = True
    elif req.recovery_max_min is None:
        rec_ok = recovered
    else:
        rec_ok = recovered and recovery_min <= req.recovery_max_min
    rating = [w for w in check_limits(cell, load, res) if "rating" in w]
    return {
        "design": f"{cooling.name}, {pcm_label(grade, pcm_mm)}",
        "cooling": cooling.name,
        "cooling_kind": cooling.kind,
        "chilled": cooling.chilled,
        "h_W_m2K": cooling.h,
        "coolant_C": T_sink - KELVIN,
        "pcm_grade": grade or "none",
        "pcm_mm": pcm_mm,
        "pcm_melt_C": melt_midpoint_C(PCM_LIBRARY[grade]) if grade else np.nan,
        "pcm": pcm_label(grade, pcm_mm),
        "R0_mOhm": cell.R0_25C * 1e3,
        "T_peak_C": T_peak,
        "dT_cell_C": dT,
        "pcm_peak_liquid_fraction": float(res.pcm_fraction.max()),
        "heat_kJ": res.E_generated / 1e3,
        "throughput_Wh": throughput_Wh,
        "fan_pump_Wh": fan_pump_Wh,
        "chiller_Wh": chiller_Wh,
        "aux_energy_Wh": aux_Wh,
        "aux_energy_pct": 100.0 * aux_Wh / throughput_Wh if throughput_Wh > 0 else np.nan,
        "mass_pcm_g": 1e3 * m_pcm,
        "mass_case_g": 1e3 * m_case,
        "mass_hardware_g": 1e3 * m_hw,
        "mass_overhead_g": 1e3 * m_over,
        "mass_overhead_pct": 100.0 * m_over / cell.mass,
        "recovery_min": recovery_min,
        "T_limit_C": T_limit,
        "T_margin_C": T_limit - T_peak,
        "feasible": bool(T_peak <= T_limit and dT <= req.dT_cell_max_C and rec_ok),
        # hot = peak above limit, uneven = in-cell spread above limit,
        # slow = not ready for the next event in time
        "fail_reason": " · ".join(
            r for r, bad in (("hot", T_peak > T_limit), ("uneven", dT > req.dT_cell_max_C), ("slow", not rec_ok)) if bad
        ),
        "rating_warning": "; ".join(rating),
    }


def _evaluate_args(args):
    return evaluate_design(*args)


def _map(fn, jobs: list, workers: int | None):
    workers = workers if workers is not None else min(len(jobs), os.cpu_count() or 1)
    if workers <= 1 or len(jobs) <= 1:
        return [fn(j) for j in jobs]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, jobs, chunksize=max(1, len(jobs) // (4 * workers))))


def pareto_mask(cost_a: np.ndarray, cost_b: np.ndarray) -> np.ndarray:
    """True where no other point is <= on both costs and < on at least one."""
    n = len(cost_a)
    mask = np.ones(n, dtype=bool)
    for i in range(n):
        dominated = (cost_a <= cost_a[i]) & (cost_b <= cost_b[i]) & ((cost_a < cost_a[i]) | (cost_b < cost_b[i]))
        mask[i] = not dominated.any()
    return mask


@dataclass
class StudyResult:
    study: DesignStudy
    table: pd.DataFrame  # one row per design
    picks: dict[str, pd.Series]  # "lightest", "lowest_energy", "balanced" (front designs)

    mass_axis_label: ClassVar[str] = "Mass added per cell (PCM + sleeve + cooling hardware), % of cell mass"
    filler_axis_label: ClassVar[str] = "PCM"
    kind_names: ClassVar[dict[str, str]] = {"natural": "natural", "air": "air", "liquid": "liquid"}

    @property
    def front(self) -> pd.DataFrame:
        return self.table[self.table.pareto].sort_values("mass_overhead_pct")

    @property
    def warnings(self) -> list[str]:
        w = self.table.rating_warning
        return sorted({x for x in w[w != ""]})

    def _recovery_text(self) -> str:
        r, d = self.study.requirements.recovery_max_min, self.study.duty
        if d.repeat or r == math.inf:
            return "recovery not required"
        if r is None:
            return f"ready again within {d.rest_after_s / 60:.0f} min"
        return f"ready again within {r:g} min"

    def footnote(self) -> str:
        s = self.study
        return (
            f"Picks re-checked at worst-case R0 = {s.R0_worst * 1e3:.0f} mΩ. "
            f"Fan/pump power ∝ h^3.75, per {s.cells_in_pack}-cell pack; chiller COP {s.chiller_cop:g}."
        )

    def notes(self) -> list[str]:
        if (self.table.feasible & (self.table.cooling_kind == "natural")).any():
            return [
                (
                    "NOTE: natural convection is modelled for an isolated cell in free air; inside a packed module "
                    "neighbouring cells block most of that path, so treat natural-cooling results as optimistic."
                )
            ]
        return []

    def summary(self) -> str:
        s, t = self.study, self.table
        lines = [
            f"{s.cell.name}, {s.duty.name}, ambient {s.requirements.T_env_C:g} degC",
            (
                f"Limits: T_peak <= {t.T_limit_C.iloc[0]:g} degC, in-cell dT <= {s.requirements.dT_cell_max_C:g} degC, "
                f"{self._recovery_text()}"
            ),
            f"{len(t)} designs, {int(t.feasible.sum())} feasible, {int(t.pareto.sum())} on the trade-off front",
        ]
        if "cell_to_cell_limit_K" in t and np.isfinite(t.cell_to_cell_limit_K.iloc[0]):
            lines[1] += f", cell-to-cell <= {t.cell_to_cell_limit_K.iloc[0]:g} K"
        lines += [f"WARNING: {w}" for w in self.warnings]
        lines += self.notes()
        if not self.picks and t.feasible.any():
            lines.append("No robust design: every feasible design fails at worst-case resistance.")
        if not self.picks:
            best = t.loc[t.T_peak_C.idxmin()]
            lines.append(
                f"No feasible design. Coolest: {best.design} at {best.T_peak_C:.1f} degC ({best.fail_reason}). "
                "Reduce the load, raise the limit, or add stronger cooling."
            )
            return "\n".join(lines)
        for key, label in (("lightest", "Lightest"), ("lowest_energy", "Lowest energy"), ("balanced", "Balanced")):
            r = self.picks[key]
            robust = (
                ""
                if r.robust
                else f"  (fails at worst-case R0 = {r.R0_worst_mOhm:.0f} mOhm: {r.T_peak_worst_C:.1f} degC)"
            )
            rec = f"{r.recovery_min:.0f} min" if np.isfinite(r.recovery_min) else "n/a"
            lines.append(
                f"{label:<14} {r.design}: T_peak {r.T_peak_C:.1f} degC, +{r.mass_overhead_pct:.1f}% mass, "
                f"aux {r.aux_energy_pct:.2f}% of energy, recovery {rec}{robust}"
            )
        fragile = self.table[self.table.fragile].sort_values("mass_overhead_pct")
        for _, r in fragile.iterrows():
            lines.append(
                f"Not picked     {r.design}: +{r.mass_overhead_pct:.1f}% mass, aux {r.aux_energy_pct:.2f}%, "
                f"but fails ({r.worst_fail_reason}) at worst-case R0 = {r.R0_worst_mOhm:.0f} mOhm "
                f"(peak {r.T_peak_worst_C:.1f} degC)"
            )
        return "\n".join(lines)


def select_front(table: pd.DataFrame, recheck, check: bool) -> dict[str, pd.Series]:
    """Mark the Pareto front, re-check it at worst case, and make the picks.

    ``recheck(indices)`` returns, for each row index, a dict with ``R0_mOhm``,
    ``T_peak_C``, ``fail_reason`` and ``feasible`` at worst-case resistance.
    Front designs that fail are marked fragile and removed, then the front is
    rebuilt from what remains until every front design is robust. ``table``
    is updated in place.
    """
    table["pareto"] = False
    table["fragile"] = False
    table["R0_worst_mOhm"] = np.nan
    table["T_peak_worst_C"] = np.nan
    table["worst_fail_reason"] = ""
    table["robust"] = table.feasible.copy()
    for _ in range(20):
        cand = np.flatnonzero(table.feasible.to_numpy() & ~table.fragile.to_numpy())
        table["pareto"] = False
        if cand.size == 0:
            break
        front = pareto_mask(table.mass_overhead_pct.to_numpy()[cand], table.aux_energy_pct.to_numpy()[cand])
        rows = table.index[cand[front]]
        table.loc[rows, "pareto"] = True
        if not check:
            break
        todo = [i for i in rows if np.isnan(table.at[i, "T_peak_worst_C"])]
        if not todo:
            break
        for i, w in zip(todo, recheck(todo)):
            table.at[i, "R0_worst_mOhm"] = w["R0_mOhm"]
            table.at[i, "T_peak_worst_C"] = w["T_peak_C"]
            table.at[i, "worst_fail_reason"] = w["fail_reason"]
            table.at[i, "robust"] = w["feasible"]
            table.at[i, "fragile"] = not w["feasible"]
        if not table.loc[rows, "fragile"].any():
            break

    picks: dict[str, pd.Series] = {}
    pool = table[table.pareto]
    if len(pool):
        picks["lightest"] = pool.sort_values(["mass_overhead_pct", "aux_energy_pct"]).iloc[0]
        picks["lowest_energy"] = pool.sort_values(["aux_energy_pct", "mass_overhead_pct"]).iloc[0]
        m, e = pool.mass_overhead_pct, pool.aux_energy_pct
        norm = lambda x: (x - x.min()) / (x.max() - x.min()) if x.max() > x.min() else x * 0
        dist = np.hypot(norm(m), norm(e)).round(9)
        # Ties (e.g. a two-point front) go to the larger temperature margin.
        ranked = pool.assign(_d=dist).sort_values(["_d", "T_margin_C"], ascending=[True, False])
        picks["balanced"] = ranked.drop(columns="_d").iloc[0]
    return picks


def run_study(study: DesignStudy, workers: int | None = None, robustness: bool = True) -> StudyResult:
    """Single-cell study (v0.3): an isolated cell in a PCM sleeve and casing."""
    jobs = [(study, c, g, mm) for c in study.cooling_options for g, mm in study.pcm_choices()]
    table = pd.DataFrame(_map(_evaluate_args, jobs, workers))
    by_name = {c.name: c for c in study.cooling_options}
    R_worst = study.R0_worst

    def recheck(idx):
        return _map(
            _evaluate_args,
            [
                (
                    study,
                    by_name[table.at[i, "cooling"]],
                    None if table.at[i, "pcm_grade"] == "none" else table.at[i, "pcm_grade"],
                    table.at[i, "pcm_mm"],
                    R_worst,
                )
                for i in idx
            ],
            workers,
        )

    picks = select_front(table, recheck, robustness and R_worst > study.cell.R0_25C)
    return StudyResult(study, table, picks)

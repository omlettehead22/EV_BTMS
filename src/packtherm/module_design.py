"""Module-level design advisor: cooling topology, flow, chiller, filler and gap.

This is the v0.4.1 successor of the single-cell advisor in :mod:`packtherm.design`.
Each design is a :class:`packtherm.module.Module`, scored on the hottest of four
cells: interior and edge (on the module wall), at the coolant inlet and outlet.
The cell-to-cell spread along the channel is known and can be limited.

Design variables
----------------
* topology: ``none`` (sealed module, no cooling), ``air`` (forced air between
  the cans), ``bottom`` (cold plate under the cells), ``ribbon`` (serpentine
  tube along the cans)
* flow per cell (air or coolant): sets h, the coolant temperature rise along
  the channel and the fan/pump power, all from :mod:`packtherm.module`
* coolant inlet: ambient (radiator) or a chiller set-point below ambient
* filler between the cans: none, a PCM grade or a PCM/expanded-graphite
  composite (``-EG``)
* gap between cans (a side ribbon widens it to fit the tube and its bonds)

Cells simulated per design: the interior cell at the coolant outlet (scored,
with recovery), the interior inlet cell, and edge cells on the module wall at
both ends (``edge_cells``). Feasibility uses the hottest of them; the
cell-to-cell spread is hottest minus coolest.

Costs, per cell:

* **mass overhead**: filler + cooling hardware built up from geometry
  (:mod:`packtherm.hardware`) as % of cell mass
* **auxiliary energy**: fan or pump electricity computed from flow and
  pressure drop, plus chiller electricity (heat taken by sub-ambient coolant /
  COP), until the cell is ready again, as % of the energy the cell moves

Feasibility: peak and in-cell spread of the hottest of those cells within the
requirements (plate and ribbon designs from their 2D fields), recovery in time
(interior outlet cell), and optionally the cell-to-cell spread within a limit. The front,
worst-case-resistance re-check and picks are shared with the single-cell
advisor (:func:`packtherm.design.select_front`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import ClassVar

import numpy as np
import pandas as pd

from .cells import Cell, with_R0
from .design import (
    DutyCycle,
    Requirements,
    StudyResult,
    _map,
    select_front,
)
from .electrothermal import check_limits
from .hardware import PackHardware, hardware_mass_per_cell
from .materials import get_pcm, melt_midpoint_C
from .module import (
    RESOLUTIONS,
    AirFlow,
    BottomPlate,
    Chiller,
    Coolant,
    Interface,
    Layout,
    Module,
    PlateGeometry,
    Resolution,
    RibbonGeometry,
    SideRibbon,
    Wall,
    module_mass_per_cell_kg,
    simulate_module,
)
from .params import KELVIN, Params

TOPOLOGIES = ("none", "air", "bottom", "ribbon")
KIND = {"none": "natural", "air": "air", "bottom": "liquid", "ribbon": "liquid"}


@dataclass(frozen=True)
class ModuleDesign:
    """One point of the sweep."""

    topology: str
    flow_g_s: float = 0.0  # per cell; air or coolant
    inlet_C: float | None = None  # coolant inlet; None = ambient
    filler: str | None = None
    gap_mm: float = 2.0

    @property
    def chilled(self) -> bool:
        return self.inlet_C is not None

    def cooling_label(self, show_gap: bool = False) -> str:
        """Row label: cooling, plus the gap when it varies (rows keep fillers aligned)."""
        if self.topology == "none":
            s = "sealed (no cooling)"
        else:
            s = f"{self.topology} {self.flow_g_s:g} g/s"
            s += f", chiller {self.inlet_C:g} °C" if self.chilled else ""
        return s + (f", {self.gap_mm:g} mm gap" if show_gap else "")

    def filler_label(self) -> str:
        return self.filler or "no filler"


@dataclass(frozen=True)
class ModuleStudy:
    cell: Cell
    duty: DutyCycle
    requirements: Requirements = field(default_factory=Requirements)
    topologies: tuple[str, ...] = TOPOLOGIES
    air_flows_g_s: tuple[float, ...] = (0.15, 0.3, 0.6)
    coolant_flows_g_s: tuple[float, ...] = (0.02, 0.05)
    # Chiller set-points; only those below ambient are used. Empty = no chiller.
    chiller_inlets_C: tuple[float, ...] = (15.0,)
    fillers: tuple[str | None, ...] = (None, "RT31", "RT42", "RT31-EG")
    gaps_mm: tuple[float, ...] = (2.0,)
    packing: str = "hex"
    coolant: Coolant = field(default_factory=Coolant)  # flow and inlet are swept
    air: AirFlow = field(default_factory=AirFlow)  # flow is swept
    tim: Interface = field(default_factory=Interface)
    contact_fraction: float = 0.25
    # Hottest-to-coolest cell peak difference; None = report only.
    cell_to_cell_max_K: float | None = None
    # Also simulate cells on the module wall (edge cells) at both ends of the
    # channel; the hottest and coolest cells then include them.
    edge_cells: bool = True
    wall: Wall = field(default_factory=Wall)
    plate: PlateGeometry = field(default_factory=PlateGeometry)
    ribbon: RibbonGeometry = field(default_factory=RibbonGeometry)
    pack: PackHardware = field(default_factory=PackHardware)
    chiller: Chiller = field(default_factory=Chiller)
    # "event": the chiller runs while the duty runs, then the loop returns to the
    # radiator for recovery. "always": the chiller keeps running through the rest.
    chiller_runs: str = "event"
    resistance_margin: float = 0.2
    mode: str = "normal"  # numerical resolution: "normal" or "fast" (RESOLUTIONS)
    dt: float | None = None  # thermal step [s]; None = the mode's

    def __post_init__(self) -> None:
        if self.mode not in RESOLUTIONS:
            raise ValueError(f"Unknown mode {self.mode!r}; choose from {', '.join(RESOLUTIONS)}")

    @property
    def resolution(self) -> Resolution:
        return RESOLUTIONS[self.mode]

    @property
    def time_step(self) -> float:
        return self.resolution.dt if self.dt is None else self.dt

    @property
    def R0_worst(self) -> float:
        return max(self.cell.R0_range[1], self.cell.R0_25C) * (1.0 + self.resistance_margin)

    def designs(self) -> list[ModuleDesign]:
        out: list[ModuleDesign] = []
        inlets = [None] + [c for c in self.chiller_inlets_C if c < self.requirements.T_env_C]
        ribbon_gap = SideRibbon(tim=self.tim, tube=self.ribbon).min_gap_mm
        for gap in self.gaps_mm:
            for topo in self.topologies:
                if topo == "none":
                    out += [ModuleDesign("none", 0.0, None, f, gap) for f in self.fillers]
                elif topo == "air":
                    # Air needs open gaps: no filler.
                    out += [ModuleDesign("air", q, None, None, gap) for q in self.air_flows_g_s]
                elif topo in ("bottom", "ribbon"):
                    # The ribbon needs room between the cans: widen the gap to fit it.
                    g = max(gap, ribbon_gap) if topo == "ribbon" else gap
                    out += [
                        ModuleDesign(topo, q, t, f, g)
                        for q in self.coolant_flows_g_s
                        for t in inlets
                        for f in self.fillers
                    ]
                else:
                    raise ValueError(f"Unknown topology {topo!r}; choose from {TOPOLOGIES}")
        # Gaps below the ribbon's minimum all widen to it: keep one of each design.
        return list(dict.fromkeys(out))

    def module(self, d: ModuleDesign) -> Module:
        gap = d.gap_mm
        if d.topology == "ribbon":
            gap = max(gap, SideRibbon(tim=self.tim, tube=self.ribbon).min_gap_mm)
        layout = Layout(self.packing, gap)
        if d.topology == "none":
            cooling = None
        elif d.topology == "air":
            cooling = replace(self.air, flow_g_s_per_cell=d.flow_g_s)
        else:
            until = self.duty.event_duration() if (d.chilled and self.chiller_runs == "event") else None
            coolant = replace(self.coolant, flow_g_s_per_cell=d.flow_g_s, inlet_C=d.inlet_C, chiller_until_s=until)
            if d.topology == "bottom":
                cooling = BottomPlate(coolant=coolant, tim=self.tim, plate=self.plate)
            else:
                cooling = SideRibbon(
                    coolant=coolant, tim=self.tim, contact_fraction=self.contact_fraction, tube=self.ribbon
                )
        return Module(layout, d.filler, cooling, self.wall)


def _base(study: ModuleStudy) -> Params:
    base = Params()
    return base.with_(solver=replace(base.solver, dt=study.time_step, store_every=max(1, int(60 / study.time_step))))


def evaluate_module_design(study: ModuleStudy, d: ModuleDesign, R0: float | None = None, inlet: bool = True) -> dict:
    """Simulate the outlet cell (and the inlet cell if ``inlet``) of one design."""
    cell = study.cell if R0 is None else with_R0(study.cell, R0)
    duty, req = study.duty, study.requirements
    T_amb = req.T_env_C + KELVIN
    module = study.module(d)
    event = duty.event_duration()
    duration = event + (0.0 if duty.repeat else duty.rest_after_s)
    res_ = study.resolution
    kw = {
        "soc0": duty.soc0,
        "soc_limits": duty.soc_limits,
        "base": _base(study),
        "dr_mm": res_.dr_mm,
        "nz": res_.nz,
        "n_theta": res_.n_theta,
        "electrical_dt": res_.electrical_dt,
        "exact_volumes": res_.exact_volumes,
    }
    r = simulate_module(cell, module, duty.profile(cell), duration, req.T_env_C, position="outlet", **kw)
    res = r.res
    a = r.load.arrays()
    dt = np.diff(res.t)
    throughput_Wh = float(np.sum(a["I_abs_A"] * dt)) * cell.V_nominal / 3600.0

    # Recovery: as in the single-cell advisor, on the outlet cell.
    active = np.flatnonzero(a["I_abs_A"] > 0)
    t_stop = float(a["t"][active[-1]] + study.time_step) if active.size else 0.0
    after = res.t >= t_stop - 1e-9
    ready = after & (r.T_top - T_amb < 1.0) & (res.pcm_fraction < 0.01)
    recovered = bool(ready.any()) and not duty.repeat
    recovery_min = float((res.t[ready][0] - t_stop) / 60.0) if recovered else np.nan
    t_ready = t_stop + recovery_min * 60.0 if recovered else float(res.t[-1])

    radiator_fan_Wh = r.radiator_fan_energy_Wh(until_s=t_ready)
    fan_pump_Wh = r.pump_W_per_cell * t_ready / 3600.0 + radiator_fan_Wh
    chiller_Wh = r.chiller_energy_Wh(study.chiller, until_s=t_ready)
    aux_Wh = fan_pump_Wh + chiller_Wh

    hw = hardware_mass_per_cell(cell, module, study.pack, chilled=d.chilled)
    m_hw = hw["total"]
    m_fill = module_mass_per_cell_kg(cell, module)
    m_over = m_hw + m_fill
    pitch_area = module.layout.area_per_cell(cell)
    vol_over_pct = 100.0 * (pitch_area / (math.pi * cell.radius**2) - 1.0)

    T_limit = req.T_limit(study.cell, duty.is_charge)
    T_interior = r.T_peak_C
    dT = r.dT_cell_max
    sim = lambda pos, edge: simulate_module(
        cell, module, duty.profile(cell), event, req.T_env_C, position=pos, edge=edge, **kw
    )
    flows = d.topology != "none"  # without a coolant, inlet and outlet cells are the same
    T_peak_inlet = (sim("inlet", False).T_peak_C if flows else T_interior) if inlet else np.nan
    T_edge_out = T_edge_in = np.nan
    if study.edge_cells:
        re = sim("outlet", True)
        T_edge_out, dT = re.T_peak_C, max(dT, re.dT_cell_max)
        if inlet:
            T_edge_in = sim("inlet", True).T_peak_C if flows else T_edge_out
    T_peak = float(np.nanmax([T_interior, T_edge_out]))
    c2c = T_peak - float(np.nanmin([T_peak_inlet, T_edge_in])) if inlet else np.nan
    c2c_lim = study.cell_to_cell_max_K
    c2c_ok = c2c_lim is None or not np.isfinite(c2c) or c2c <= c2c_lim

    if duty.repeat or req.recovery_max_min == math.inf:
        rec_ok = True
    elif req.recovery_max_min is None:
        rec_ok = recovered
    else:
        rec_ok = recovered and recovery_min <= req.recovery_max_min
    fails = (
        ("hot", T_peak > T_limit),
        ("uneven", dT > req.dT_cell_max_C),
        ("slow", not rec_ok),
        ("spread", not c2c_ok),
    )
    rating = [w for w in check_limits(cell, r.load, res) if "rating" in w]
    show_gap = len(study.gaps_mm) > 1 or d.gap_mm not in study.gaps_mm
    cooling = d.cooling_label(show_gap)
    filler = d.filler_label()
    coolant_max = float(r.T_coolant.max() - KELVIN) if r.T_coolant is not None else req.T_env_C
    return {
        "design": f"{cooling}, {filler}",
        "cooling": cooling,
        "topology": d.topology,
        "cooling_kind": KIND[d.topology],
        "chilled": d.chilled,
        "flow_g_s_per_cell": d.flow_g_s,
        "inlet_C": d.inlet_C if d.chilled else req.T_env_C,
        "h_W_m2K": getattr(module.cooling, "h", np.nan)
        if isinstance(module.cooling, AirFlow)
        else (module.cooling.coolant.h if module.cooling is not None else 0.0),
        "filler": d.filler or "none",
        "pcm": filler,
        "pcm_melt_C": melt_midpoint_C(get_pcm(d.filler)) if d.filler else np.nan,
        "gap_mm": d.gap_mm,
        "R0_mOhm": cell.R0_25C * 1e3,
        "T_peak_C": T_peak,
        "T_peak_interior_C": T_interior,
        "T_peak_inlet_C": T_peak_inlet,
        "T_peak_edge_outlet_C": T_edge_out,
        "T_peak_edge_inlet_C": T_edge_in,
        "hottest_cell": "edge" if np.isfinite(T_edge_out) and T_edge_out > T_interior else "interior",
        "cell_to_cell_K": c2c,
        "cell_to_cell_limit_K": np.inf if c2c_lim is None else c2c_lim,
        "dT_cell_C": dT,
        "coolant_out_max_C": coolant_max,
        "pcm_peak_liquid_fraction": float(res.pcm_fraction.max()),
        "heat_kJ": res.E_generated / 1e3,
        "throughput_Wh": throughput_Wh,
        "pump_mW_per_cell": 1e3 * r.pump_W_per_cell,
        "fan_pump_Wh": fan_pump_Wh,
        "radiator_fan_Wh": radiator_fan_Wh,
        "chiller_Wh": chiller_Wh,
        "aux_energy_Wh": aux_Wh,
        "aux_energy_pct": 100.0 * aux_Wh / throughput_Wh if throughput_Wh > 0 else np.nan,
        "mass_filler_g": 1e3 * m_fill,
        "mass_hardware_g": 1e3 * m_hw,
        "mass_hw_aluminium_g": 1e3 * hw["aluminium"],
        "mass_hw_coolant_g": 1e3 * hw["coolant"],
        "mass_hw_interface_g": 1e3 * hw["interface"],
        "mass_hw_pack_share_g": 1e3 * hw["pack_share"],
        "mass_overhead_g": 1e3 * m_over,
        "mass_overhead_pct": 100.0 * m_over / cell.mass,
        "volume_overhead_pct": vol_over_pct,
        "recovery_min": recovery_min,
        "T_limit_C": T_limit,
        "T_margin_C": T_limit - T_peak,
        "feasible": not any(bad for _, bad in fails),
        # hot = peak over limit, uneven = in-cell spread over limit,
        # slow = not ready in time, spread = inlet-to-outlet over limit
        "fail_reason": " · ".join(r_ for r_, bad in fails if bad),
        "rating_warning": "; ".join(rating),
    }


def _eval_args(args):
    return evaluate_module_design(*args)


@dataclass
class ModuleStudyResult(StudyResult):
    mass_axis_label: ClassVar[str] = "Mass added per cell (filler + cooling hardware), % of cell mass"
    filler_axis_label: ClassVar[str] = "Filler between the cans"
    kind_names: ClassVar[dict[str, str]] = {"natural": "no cooling", "air": "forced air", "liquid": "liquid"}

    def _chiller_text(self) -> str:
        s = self.study
        when = "during the event" if s.chiller_runs == "event" else "throughout"
        if s.chiller.cop is not None:
            return f"chiller COP {s.chiller.cop:g}, on {when}"
        cops = sorted(
            {
                s.chiller.cop_at(t + KELVIN, s.requirements.T_env_C + KELVIN)
                for t in s.chiller_inlets_C
                if t < s.requirements.T_env_C
            }
        )
        cop = f"COP {cops[0]:.1f}" if len(cops) == 1 else "COP from temperatures"
        return f"chiller {cop} at this ambient, on {when}, incl. heat leak"

    def footnote(self) -> str:
        s = self.study
        return (
            f"Scored on the hottest cell ({'interior and edge' if s.edge_cells else 'interior'}), {s.packing} packing. Picks re-checked at worst-case "
            f"R0 = {s.R0_worst * 1e3:.0f} mΩ. Fan/pump power from flow and pressure drop; {self._chiller_text()}."
        )

    def notes(self) -> list[str]:
        t = self.table
        out = []
        pulled = t.chilled & (t.topology == "bottom") & t.fail_reason.fillna("").str.contains("uneven")
        if pulled.any():
            out.append(
                "NOTE: bottom plates are solved in 2D (radius x height). A chiller pulling a hot-soaked pack down "
                "through its base opens large top-to-bottom gradients while it does so."
            )
        cell, duty = self.study.cell, self.study.duty
        if cell.max_charge_C is None and duty.is_charge:
            rates = [-c for _, c in duty.steps if c < 0] or [duty.c_rate]
            trip = (
                " The road trip charges at 1C by default; set its charge rate to change it."
                if "km/h" in duty.name
                else ""
            )
            out.append(
                f"NOTE: {cell.name} has no datasheet charge limit, so the {max(rates):.2g}C charge is not checked "
                f"against one.{trip}"
            )
        if self.study.cell.user_defined:
            out.append(
                "NOTE: user-defined cell: lumped resistance from datasheet values, with no voltage model (no cut-off "
                "or constant-voltage charge taper). Less accurate than the validated cells."
            )
        liquid = t[t.cooling_kind == "liquid"]
        if len(liquid):
            out.append(
                f"NOTE: liquid pump power covers the whole loop ({liquid.pump_mW_per_cell.max():.1f} mW/cell at most) "
                "and the radiator fan is charged at 3 % of the heat it rejects; chiller idle losses are not included."
            )
        return out


def run_module_study(study: ModuleStudy, workers: int | None = None, robustness: bool = True) -> ModuleStudyResult:
    designs = study.designs()
    table = pd.DataFrame(_map(_eval_args, [(study, d) for d in designs], workers))
    R_worst = study.R0_worst

    def recheck(idx):
        # The inlet cell only matters for the spread limit.
        need_inlet = study.cell_to_cell_max_K is not None
        return _map(_eval_args, [(study, designs[i], R_worst, need_inlet) for i in idx], workers)

    picks = select_front(table, recheck, robustness and R_worst > study.cell.R0_25C)
    return ModuleStudyResult(study, table, picks)


__all__ = [
    "RESOLUTIONS",
    "TOPOLOGIES",
    "ModuleDesign",
    "ModuleStudy",
    "ModuleStudyResult",
    "Resolution",
    "evaluate_module_design",
    "run_module_study",
]

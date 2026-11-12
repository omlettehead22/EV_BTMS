"""Module-level thermal model: one cell inside a packed array.

Unit cell
---------
In a large square or hexagonal array of identical cells, symmetry means no
heat crosses the boundary between one cell's share of the module and its
neighbour's. Each cell is therefore modelled with the area it owns, turned
into an equivalent annulus (same area, outer radius r_u) with an **adiabatic**
outer edge:

    square packing:   pi r_u^2 = p^2
    hexagonal:        pi r_u^2 = (sqrt(3)/2) p^2,    p = 2 r_cell + gap

The gap between cells holds the *filler*: air (nothing conducts; any heat
leaves through forced air on the can or through a cold plate), plain PCM, or
expanded-graphite composite PCM.

Heat leaves through one cooling topology:

* ``AirFlow``: forced air through the gaps, h on the can surface (air filler only).
* ``BottomPlate``: cells stand on a cold plate. Heat travels down the cell
  (axial conductivity of the winding, ``Cell.k_axial``), across the
  roll-to-can end resistance, the thermal interface (bond-line / k) and into
  the coolant. In the radial model this is a distributed sink: each ring of
  height L and footprint A has the mean-temperature conductance
      G = V / (L^2 / (3 k_ax) + L (R_end + R_tim + 1/h))
  (exact for uniform generation; the top of the cell runs hotter than the
  mean by q L^2 / (6 k_ax), reported as ``T_top``).
* ``SideRibbon``: a cooling tube bonded along each can, touching a fraction
  of its circumference (a sink on the can surface).
* No cooling: an interior cell of a packed, uncooled module is adiabatic.
  Free-air natural convection does not exist inside a pack.

Coolant (plate or ribbon) warms as it passes cells. With flow m per cell,
the outlet coolant is T_in + Q_cell / (m cp), solved in balance with the
heat the cell rejects each step (unconditionally stable). The cell at the outlet is the
hottest; ``position="inlet"`` runs the coldest one. Flow sets h through
Dittus-Boelter scaling (h ~ m^0.8) and pump power through P = (m/rho) dp / eta
with dp ~ m^2, so flow is the single cooling design variable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .cells import Cell, params_for_cell
from .electrothermal import CurrentProfile, ElectroThermalLoad
from .materials import get_pcm
from .model import CELL, PCM_REGION, SimulationResult, Sink, simulate
from .params import KELVIN, Params

# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Layout:
    packing: str = "hex"  # "hex" | "square"
    gap_mm: float = 2.0  # surface-to-surface gap between neighbouring cans

    def __post_init__(self) -> None:
        if self.packing not in ("hex", "square"):
            raise ValueError("packing must be 'hex' or 'square'")
        if self.gap_mm < 0:
            raise ValueError("gap_mm must be >= 0")

    def pitch(self, cell: Cell) -> float:
        return cell.diameter + self.gap_mm * 1e-3

    def area_per_cell(self, cell: Cell) -> float:
        p = self.pitch(cell)
        return p * p if self.packing == "square" else math.sqrt(3) / 2 * p * p

    def unit_radius(self, cell: Cell) -> float:
        return math.sqrt(self.area_per_cell(cell) / math.pi)

    def cells_per_m2(self, cell: Cell) -> float:
        return 1.0 / self.area_per_cell(cell)


# ---------------------------------------------------------------------------
# Coolant and cooling topologies
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Coolant:
    """Liquid coolant (50/50 water-glycol) shared along a channel.

    ASSUMPTIONS (all overridable): reference flow 0.05 g/s per cell (about
    13 L/min for a 4,400-cell pack), h_ref at that flow, pressure drop
    20 kPa at that flow, pump efficiency 0.5.
    """

    flow_g_s_per_cell: float = 0.05
    inlet_C: float | None = None  # None = ambient (radiator); below ambient needs a chiller
    cp: float = 3500.0  # J/(kg K), 50/50 water-glycol
    rho: float = 1060.0  # kg/m^3
    h_ref: float = 1500.0  # W/(m^2 K) at flow_ref, per cooled area
    flow_ref_g_s: float = 0.05
    dp_ref_Pa: float = 20e3
    pump_efficiency: float = 0.5

    @property
    def mdot(self) -> float:
        return self.flow_g_s_per_cell * 1e-3

    @property
    def h(self) -> float:
        """Convective coefficient at this flow (Dittus-Boelter: h ~ flow^0.8)."""
        return self.h_ref * (self.flow_g_s_per_cell / self.flow_ref_g_s) ** 0.8

    @property
    def pump_power_W_per_cell(self) -> float:
        dp = self.dp_ref_Pa * (self.flow_g_s_per_cell / self.flow_ref_g_s) ** 2
        return self.mdot / self.rho * dp / self.pump_efficiency

    def rise_K(self, Q_W_per_cell: float) -> float:
        """Inlet-to-outlet coolant temperature rise along the channel."""
        return Q_W_per_cell / (self.mdot * self.cp)


@dataclass(frozen=True)
class Interface:
    """Thermal interface material: R = bond-line thickness / k.

    ASSUMPTION: 0.5 mm of 2 W/mK gap filler (EV gap fillers reach ~3.5 W/mK).
    """

    bond_line_mm: float = 0.5
    k: float = 2.0

    @property
    def R(self) -> float:  # m^2 K / W
        return self.bond_line_mm * 1e-3 / self.k


@dataclass(frozen=True)
class AirFlow:
    """Forced air through the gaps between cans.

    Flow is the design variable: it sets h on the can (h ~ flow^0.8), the air
    temperature rise along the flow, and fan power ((flow/rho) dp / eta with
    dp ~ flow^2). ASSUMPTIONS: h = 30 W/m^2K at 0.3 g/s of air per cell (about
    2 m/s through a 2 mm x 70 mm gap per cell), 200 Pa pack pressure drop at
    that flow, fan efficiency 0.3. ``track_rise=False`` ignores the air
    temperature rise (every cell sees ambient air).
    """

    flow_g_s_per_cell: float = 0.3
    h_ref: float = 30.0  # W/(m^2 K) at flow_ref_g_s
    flow_ref_g_s: float = 0.3
    cp: float = 1005.0  # J/(kg K)
    rho: float = 1.18  # kg/m^3
    dp_ref_Pa: float = 200.0
    fan_efficiency: float = 0.3
    track_rise: bool = True
    name: str = "air"

    def __post_init__(self) -> None:
        if self.flow_g_s_per_cell <= 0:
            raise ValueError("Air flow must be positive.")

    @property
    def h(self) -> float:
        return self.h_ref * (self.flow_g_s_per_cell / self.flow_ref_g_s) ** 0.8

    @property
    def mdot(self) -> float:
        return self.flow_g_s_per_cell * 1e-3

    @property
    def pump_power_W_per_cell(self) -> float:
        dp = self.dp_ref_Pa * (self.flow_g_s_per_cell / self.flow_ref_g_s) ** 2
        return self.mdot / self.rho * dp / self.fan_efficiency

    def rise_K(self, Q_W_per_cell: float) -> float:
        return Q_W_per_cell / (self.mdot * self.cp) if self.track_rise else 0.0

    @classmethod
    def with_h(cls, h: float, **kw) -> AirFlow:
        """The air flow that gives convective coefficient ``h``."""
        ref = cls(**kw)
        return cls(flow_g_s_per_cell=ref.flow_ref_g_s * (h / ref.h_ref) ** 1.25, **kw)


@dataclass(frozen=True)
class BottomPlate:
    coolant: Coolant = field(default_factory=Coolant)
    tim: Interface = field(default_factory=Interface)
    # ASSUMPTION: roll-to-can-bottom resistance (insulating end disc, single
    # tab): ~0.1 mm of polymer. The largest uncertainty in bottom cooling.
    R_end: float = 5e-4  # m^2 K / W
    name: str = "bottom plate"


@dataclass(frozen=True)
class SideRibbon:
    coolant: Coolant = field(default_factory=Coolant)
    tim: Interface = field(default_factory=Interface)
    # ASSUMPTION: share of the can circumference bonded to the ribbon.
    contact_fraction: float = 0.25
    # ASSUMPTION: the ribbon tube must fit between neighbouring cans.
    min_gap_mm: float = 1.5
    name: str = "side ribbon"


Cooling = AirFlow | BottomPlate | SideRibbon | None


@dataclass(frozen=True)
class Module:
    layout: Layout = field(default_factory=Layout)
    filler: str | None = None  # PCM grade from btms.materials, or None for air
    cooling: Cooling = field(default_factory=BottomPlate)

    def __post_init__(self) -> None:
        if isinstance(self.cooling, AirFlow) and self.filler is not None:
            raise ValueError("AirFlow needs open gaps: use filler=None.")
        if isinstance(self.cooling, SideRibbon) and self.layout.gap_mm < self.cooling.min_gap_mm:
            raise ValueError(
                f"A side ribbon needs at least {self.cooling.min_gap_mm:g} mm between cans "
                f"(layout has {self.layout.gap_mm:g} mm)."
            )

    def describe(self) -> str:
        cool = "uncooled" if self.cooling is None else self.cooling.name
        if isinstance(self.cooling, AirFlow):
            cool += f" {self.cooling.flow_g_s_per_cell:g} g/s/cell (h={self.cooling.h:.0f})"
        elif self.cooling is not None:
            c = self.cooling.coolant
            cool += f" {c.flow_g_s_per_cell:g} g/s/cell"
            if c.inlet_C is not None:
                cool += f" @{c.inlet_C:g}°C"
        fill = self.filler or "air gaps"
        return f"{self.layout.packing} {self.layout.gap_mm:g} mm gap, {fill}, {cool}"


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------


def module_params(cell: Cell, module: Module, base: Params | None = None) -> Params:
    base = base or Params()
    if module.filler is None:
        P = params_for_cell(cell, pcm_thickness=0.0, case_thickness=0.0, base=base)
    else:
        r_u = module.layout.unit_radius(cell)
        P = params_for_cell(
            cell, pcm_thickness=r_u - cell.radius, case_thickness=0.0, base=base.with_(pcm=get_pcm(module.filler))
        )
    return P


@dataclass
class ModuleResult:
    cell: Cell
    module: Module
    position: str
    res: SimulationResult
    load: ElectroThermalLoad
    T_ambient: float  # K
    T_coolant: np.ndarray | None  # K, coolant at this cell, every step
    Q_coolant: np.ndarray | None  # W per cell into the coolant
    T_top: np.ndarray  # K, estimated hottest point (top of cell for bottom cooling)
    dT_axial: np.ndarray  # K, estimated top-to-bottom difference inside the roll

    @property
    def T_peak_C(self) -> float:
        return float(self.T_top.max() - KELVIN)

    @property
    def dT_cell_max(self) -> float:
        """Largest in-cell spread: radial (model) plus axial (estimate)."""
        return float(np.max(self.res.dT_cell + self.dT_axial))

    def chiller_energy_Wh(self, cop: float, until_s: float | None = None) -> float:
        """Chiller electricity per cell: heat taken by sub-ambient coolant / COP."""
        c = self.module.cooling
        if not isinstance(c, (BottomPlate, SideRibbon)) or c.coolant.inlet_C is None:
            return 0.0
        if c.coolant.inlet_C + KELVIN >= self.T_ambient or self.Q_coolant is None:
            return 0.0
        n = self.res.t.size if until_s is None else int(np.searchsorted(self.res.t, until_s, side="right"))
        dt = np.diff(self.res.t[:n], prepend=0.0)
        return float(np.sum(np.clip(self.Q_coolant[:n], 0.0, None) * dt)) / cop / 3600.0

    @property
    def pump_W_per_cell(self) -> float:
        c = self.module.cooling
        if isinstance(c, (BottomPlate, SideRibbon)):
            return c.coolant.pump_power_W_per_cell
        if isinstance(c, AirFlow):
            return c.pump_power_W_per_cell
        return 0.0


def _coolant_temperature(T_in: float, coolant, position: str):
    """Coolant temperature at this cell, in balance with the heat it absorbs.

    T_c = T_in + frac Q / (m cp) with Q = sum G (T - T_c), solved for T_c:
    T_c = (T_in + a sum(G T)) / (1 + a sum(G)),  a = frac / (m cp).
    Stable for any ratio of contact conductance to coolant capacity flow.
    """
    frac = {"outlet": 1.0, "inlet": 0.0, "mean": 0.5}[position]
    a = frac / (coolant.mdot * coolant.cp)

    def T(t: float, T_nodes: np.ndarray, G: np.ndarray) -> float:
        return float((T_in + a * np.dot(G, T_nodes)) / (1.0 + a * G.sum()))

    return T


def simulate_module(
    cell: Cell,
    module: Module,
    profile: CurrentProfile,
    duration: float,
    T_ambient_C: float = 25.0,
    *,
    position: str = "outlet",
    soc0: float = 1.0,
    soc_limits: tuple[float, float] = (0.0, 1.0),
    base: Params | None = None,
    entropic: bool = True,
) -> ModuleResult:
    """Simulate one cell of the module (the coolant-outlet cell by default)."""
    T_amb = T_ambient_C + KELVIN
    base = (base or Params()).with_(T_initial=T_amb)
    P = module_params(cell, module, base)
    L = cell.height
    cooling = module.cooling
    sinks: list[Sink] = []
    h_outer = 0.0
    if isinstance(cooling, AirFlow):
        if cooling.track_rise:
            area = 2.0 * math.pi * cell.radius * L

            def G_air(grid, params, h=cooling.h, area=area):
                G = np.zeros(grid.r.size)
                # Half-cell conduction to the can surface in series with convection,
                # as for the outer boundary of the bare-cell model.
                k_out = cell.k_radial
                G[-1] = area / (grid.dr / (2.0 * k_out) + 1.0 / h)
                return G

            sinks.append(Sink(G_air, _coolant_temperature(T_amb, cooling, position), "coolant"))
        else:
            h_outer = cooling.h
    elif isinstance(cooling, (BottomPlate, SideRibbon)):
        c = cooling.coolant
        T_in = T_amb if c.inlet_C is None else c.inlet_C + KELVIN
        T_sink = _coolant_temperature(T_in, c, position)
        R_path = cooling.tim.R + 1.0 / c.h
        if isinstance(cooling, BottomPlate):
            k_fill = P.pcm.k

            def G_bottom(grid, params, R_end=cooling.R_end, R_path=R_path):
                k_ax = np.where(grid.region == CELL, cell.k_axial, k_fill)
                R_e = np.where(grid.region == CELL, R_end, 0.0)
                g = 1.0 / (L * L / (3.0 * k_ax) + L * (R_e + R_path))
                return grid.volume * g

            sinks.append(Sink(G_bottom, T_sink, "coolant"))
        else:

            def G_ribbon(grid, params, f=cooling.contact_fraction, R_path=R_path):
                G = np.zeros(grid.r.size)
                i = int(np.flatnonzero(grid.region == CELL)[-1])
                G[i] = f * 2.0 * math.pi * cell.radius * L / R_path
                return G

            sinks.append(Sink(G_ribbon, T_sink, "coolant"))
    load = ElectroThermalLoad(cell, profile, soc0=soc0, soc_limits=soc_limits, entropic=entropic)
    res = simulate(P, duration=duration, h=h_outer, T_env=T_amb, load=load, sinks=sinks)

    T_coolant = res.T_sinks.get("coolant") if sinks else None
    Q_coolant = res.Q_sinks.get("coolant") if sinks else None
    if T_coolant is not None:
        T_coolant = T_coolant.copy()
        T_coolant[0] = T_coolant[1] if T_coolant.size > 1 else T_coolant[0]
    if isinstance(cooling, BottomPlate):
        # Quasi-steady axial profile for uniform generation q with a cooled base:
        # top - mean = q L^2/(6k), top - bottom = q L^2/(2k).
        V_cell = math.pi * cell.radius**2 * L
        q = np.maximum(res.heat_W, 0.0) / V_cell
        dT_axial = q * L * L / (2.0 * cell.k_axial)
        T_top = res.T_max + q * L * L / (6.0 * cell.k_axial)
    else:
        dT_axial = np.zeros_like(res.t)
        T_top = res.T_max.copy()
    return ModuleResult(cell, module, position, res, load, T_amb, T_coolant, Q_coolant, T_top, dT_axial)


def module_mass_per_cell_kg(cell: Cell, module: Module) -> float:
    """Filler mass per cell (gap volume x density); cooling hardware excluded."""
    if module.filler is None:
        return 0.0
    vol = (module.layout.area_per_cell(cell) - math.pi * cell.radius**2) * cell.height
    return get_pcm(module.filler).rho * vol


def pcm_volume_fraction(cell: Cell, module: Module) -> float:
    return 1.0 - math.pi * cell.radius**2 / module.layout.area_per_cell(cell)


__all__ = [
    "PCM_REGION",
    "AirFlow",
    "BottomPlate",
    "Coolant",
    "Interface",
    "Layout",
    "Module",
    "ModuleResult",
    "SideRibbon",
    "module_mass_per_cell_kg",
    "module_params",
    "pcm_volume_fraction",
    "simulate_module",
]


def compare_modules(
    cell: Cell,
    modules: list[Module],
    duty,
    T_ambient_C: float = 25.0,
    dt: float = 2.0,
) -> list[dict]:
    """Inlet and outlet cell of each module design for one duty cycle (a design.DutyCycle)."""
    from dataclasses import replace as _replace

    base = Params()
    base = base.with_(solver=_replace(base.solver, dt=dt, store_every=max(1, int(60 / dt))))
    duration = duty.event_duration()
    rows = []
    for m in modules:
        out = {"module": m.describe(), "cooling": m.cooling.name if m.cooling else "none", "filler": m.filler or "air"}
        for pos in ("inlet", "outlet"):
            r = simulate_module(
                cell,
                m,
                duty.profile(cell),
                duration,
                T_ambient_C,
                position=pos,
                soc0=duty.soc0,
                soc_limits=duty.soc_limits,
                base=base,
            )
            out[f"T_peak_{pos}_C"] = r.T_peak_C
            out[f"dT_cell_{pos}_K"] = r.dT_cell_max
            if pos == "outlet":
                out["coolant_rise_max_K"] = (
                    float(r.T_coolant.max() - r.T_coolant[0]) if r.T_coolant is not None else 0.0
                )
                out["pump_mW_per_cell"] = 1e3 * r.pump_W_per_cell
                out["filler_g_per_cell"] = 1e3 * module_mass_per_cell_kg(cell, m)
                out["filler_mass_pct"] = 100 * module_mass_per_cell_kg(cell, m) / cell.mass
        out["cell_to_cell_K"] = out["T_peak_outlet_C"] - out["T_peak_inlet_C"]
        rows.append(out)
    return rows

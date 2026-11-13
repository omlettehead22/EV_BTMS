"""Passenger-EV duty cycles: speed traces -> pack power -> per-cell C-rate.

A quasi-static longitudinal model turns vehicle speed into battery power:

    F = m_eff a + 1/2 rho_air CdA v^2 + Crr m g
    P_wheel = F v
    P_batt = P_wheel / eta_drive + P_aux            (traction, P_wheel > 0)
    P_batt = max(P_wheel * eta_regen, -P_regen_max) + P_aux   (braking)

Pack power is shared equally by Ns x Np cells, and each cell's current is its
power divided by nominal voltage. The resulting C-rate trace becomes a
:class:`packtherm.design.DutyCycle`.

Drive cycle: WLTC Class 3b, UN GTR No. 15 Annex 1 (``data/wltc_class3b.csv``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

import numpy as np

from .cells import Cell
from .design import DutyCycle

G = 9.81
RHO_AIR = 1.2


@dataclass(frozen=True)
class Vehicle:
    """ASSUMPTION: a generic C-segment EV; every field is overridable."""

    name: str = "C-segment EV"
    mass_kg: float = 1900.0  # test mass incl. driver
    cda_m2: float = 0.65  # Cd 0.28 x frontal area 2.3 m^2
    crr: float = 0.009
    rot_inertia_factor: float = 1.05
    eta_drive: float = 0.90  # battery -> wheel
    eta_regen: float = 0.70  # wheel -> battery (incl. friction-brake blending)
    regen_max_kW: float = 80.0
    aux_kW: float = 0.5  # low-voltage loads, HVAC off

    def battery_power_W(self, speed_ms: np.ndarray, accel_ms2: np.ndarray, grade: float = 0.0) -> np.ndarray:
        m = self.mass_kg
        force = (
            self.rot_inertia_factor * m * accel_ms2
            + 0.5 * RHO_AIR * self.cda_m2 * speed_ms**2
            + self.crr * m * G * math.cos(grade) * (speed_ms > 0)
            + m * G * math.sin(grade)
        )
        p_wheel = force * speed_ms
        p_batt = np.where(
            p_wheel >= 0, p_wheel / self.eta_drive, np.maximum(p_wheel * self.eta_regen, -self.regen_max_kW * 1e3)
        )
        return p_batt + self.aux_kW * 1e3


@dataclass(frozen=True)
class Pack:
    n_series: int
    n_parallel: int

    @property
    def n_cells(self) -> int:
        return self.n_series * self.n_parallel

    def energy_kWh(self, cell: Cell) -> float:
        return self.n_cells * cell.capacity_Ah * cell.V_nominal / 1e3

    def voltage(self, cell: Cell) -> float:
        return self.n_series * cell.V_nominal

    @classmethod
    def for_energy(cls, cell: Cell, energy_kWh: float = 60.0, voltage: float = 350.0) -> Pack:
        ns = max(1, round(voltage / cell.V_nominal))
        npar = max(1, math.ceil(energy_kWh * 1e3 / (ns * cell.capacity_Ah * cell.V_nominal)))
        return cls(ns, npar)


@lru_cache(maxsize=1)
def wltc_class3b() -> tuple[np.ndarray, np.ndarray]:
    """(time_s, speed_kmh) at 1 Hz, 1801 points, 23.27 km."""
    text = resources.files("packtherm").joinpath("data/wltc_class3b.csv").read_text()
    rows = [line.split(",") for line in text.splitlines() if line and not line.startswith(("#", "time"))]
    arr = np.array(rows, dtype=float)
    return arr[:, 0], arr[:, 1]


def cell_c_rate(cell: Cell, pack: Pack, p_batt_W: np.ndarray) -> np.ndarray:
    """Per-cell C-rate (+ discharge) from pack battery power."""
    current = p_batt_W / pack.n_cells / cell.V_nominal
    return current / cell.capacity_Ah


def speed_trace_c_rate(cell: Cell, pack: Pack, vehicle: Vehicle, speed_kmh: np.ndarray, dt: float = 1.0) -> np.ndarray:
    v = np.asarray(speed_kmh) / 3.6
    a = np.gradient(v, dt)
    return cell_c_rate(cell, pack, vehicle.battery_power_W(v, a))


def consumption_Wh_per_km(cell: Cell, pack: Pack, vehicle: Vehicle) -> float:
    """Battery energy per km over one WLTC (sanity check on the vehicle model)."""
    _, v = wltc_class3b()
    p = vehicle.battery_power_W(v / 3.6, np.gradient(v / 3.6, 1.0))
    return float(p.sum() / 3600.0 / (v.sum() / 3600.0))


def _compress(c: np.ndarray, dt: float = 1.0) -> tuple[tuple[float, float], ...]:
    """Merge consecutive equal C-rates into (duration, c_rate) steps."""
    steps: list[list[float]] = []
    for x in np.round(c, 6):
        if steps and steps[-1][1] == x:
            steps[-1][0] += dt
        else:
            steps.append([dt, float(x)])
    return tuple((d, x) for d, x in steps)


def wltc_duty(
    cell: Cell,
    pack: Pack | None = None,
    vehicle: Vehicle | None = None,
    cycles: int = 3,
    soc0: float = 0.9,
    soc_min: float = 0.1,
    **kw,
) -> DutyCycle:
    """``cycles`` back-to-back WLTC Class 3b cycles, then a rest."""
    pack = pack or Pack.for_energy(cell)
    vehicle = vehicle or Vehicle()
    _, v = wltc_class3b()
    c = speed_trace_c_rate(cell, pack, vehicle, v)
    steps = _compress(np.tile(c, cycles))
    return DutyCycle(
        name=f"{cycles}x WLTC 3b ({vehicle.name}, {pack.n_series}s{pack.n_parallel}p)",
        steps=steps,
        soc0=soc0,
        soc_limits=(soc_min, 1.0),
        **kw,
    )


def motorway_c_rate(cell: Cell, pack: Pack, vehicle: Vehicle, speed_kmh: float) -> float:
    v = np.array([speed_kmh / 3.6])
    return float(cell_c_rate(cell, pack, vehicle.battery_power_W(v, np.zeros(1)))[0])


def road_trip_duty(
    cell: Cell,
    pack: Pack | None = None,
    vehicle: Vehicle | None = None,
    speed_kmh: float = 130.0,
    soc_start: float = 0.9,
    soc_arrive: float = 0.1,
    charge_c_rate: float | None = None,
    soc_charged: float = 0.8,
    **kw,
) -> DutyCycle:
    """Motorway drive from ``soc_start`` to ``soc_arrive``, then rapid charge to ``soc_charged``.

    The hardest common EV thermal case: the pack arrives hot and is charged
    straight away. Charge C-rate defaults to the cell's datasheet maximum.
    """
    pack = pack or Pack.for_energy(cell)
    vehicle = vehicle or Vehicle()
    c_drive = motorway_c_rate(cell, pack, vehicle, speed_kmh)
    c_chg = charge_c_rate if charge_c_rate is not None else (cell.max_charge_C or 1.0)
    t_drive = 3600.0 * (soc_start - soc_arrive) / c_drive
    t_chg = 3600.0 * (soc_charged - soc_arrive) / c_chg
    return DutyCycle(
        name=(
            f"{speed_kmh:g} km/h {soc_start:.0%}→{soc_arrive:.0%}, then {c_chg:.2g}C charge to {soc_charged:.0%} "
            f"({pack.n_series}s{pack.n_parallel}p)"
        ),
        steps=((round(t_drive), c_drive), (round(t_chg), -c_chg)),
        soc0=soc_start,
        soc_limits=(min(soc_arrive, soc_start) - 1e-6, max(soc_charged, soc_start) + 1e-6),
        **kw,
    )

"""Electro-thermal coupling: current profiles -> cell heat generation.

Heat generation follows Bernardi et al. (1985) in its common lumped form,
with current I positive on discharge:

    Q = I^2 R(SOC, T)  -  I T dU/dT(SOC)
        irreversible       reversible (entropic)

State of charge is coulomb-counted: dSOC/dt = -I / (3600 * capacity_Ah).
Temperature feeds back through R(SOC, T) every time step.
"""

from __future__ import annotations

import csv
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .cells import Cell

CurrentProfile = Callable[[float], float]  # t [s] -> I [A], + = discharge


def constant_current(cell: Cell, c_rate: float, mode: str = "discharge") -> CurrentProfile:
    """Constant C-rate charge or discharge."""
    if mode not in ("charge", "discharge"):
        raise ValueError("mode must be 'charge' or 'discharge'")
    sign = 1.0 if mode == "discharge" else -1.0
    current = sign * cell.current(c_rate)
    return lambda t: current


def segments(cell: Cell, steps: Sequence[tuple[float, float]], repeat: bool = False) -> CurrentProfile:
    """Piecewise-constant profile from (duration_s, c_rate) pairs.

    c_rate > 0 discharges, < 0 charges, 0 rests. With ``repeat`` the sequence
    loops (e.g. a drive cycle); otherwise current is 0 after the last step.
    """
    durations = np.array([d for d, _ in steps], dtype=float)
    if np.any(durations <= 0):
        raise ValueError("Segment durations must be positive.")
    ends = np.cumsum(durations)
    currents = np.array([cell.current(c) for _, c in steps])
    period = ends[-1]

    def profile(t: float) -> float:
        if repeat:
            t = t % period
        elif t >= period:
            return 0.0
        return float(currents[np.searchsorted(ends, t, side="right")])

    return profile


def from_csv(path: str | Path, time_col: str = "time_s", current_col: str = "current_A") -> CurrentProfile:
    """Linearly interpolated current profile from a CSV with time and current columns."""
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    t = np.array([float(r[time_col]) for r in rows])
    current = np.array([float(r[current_col]) for r in rows])
    if np.any(np.diff(t) <= 0):
        raise ValueError("Time column must be strictly increasing.")
    return lambda x: float(np.interp(x, t, current, left=current[0], right=0.0))


@dataclass
class ElectroThermalLoad:
    """Stateful :class:`btms.model.Load` driven by a current profile.

    soc_limits : current is cut (set to 0) once SOC leaves this window,
                 e.g. a charge to 80 % stops at 0.8.
    entropic   : include the reversible heat term.
    """

    cell: Cell
    profile: CurrentProfile
    soc0: float = 1.0
    soc_limits: tuple[float, float] = (0.0, 1.0)
    entropic: bool = True
    soc: float = field(init=False)
    log: dict[str, list[float]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        lo, hi = self.soc_limits
        if not (0.0 <= lo < hi <= 1.0) or not (lo <= self.soc0 <= hi):
            raise ValueError("Require 0 <= soc_min < soc_max <= 1 and soc0 inside the window.")
        self.soc = self.soc0
        self.log = {k: [] for k in ("t", "current_A", "soc", "R_ohm", "Q_irr_W", "Q_rev_W")}

    def power(self, t: float, dt: float, T_cell: float) -> float:
        current = float(self.profile(t))
        lo, hi = self.soc_limits
        # Stop at the SOC window edge; a partial final step uses only the
        # charge that fits in the window.
        dsoc = -current * dt / (3600.0 * self.cell.capacity_Ah)
        if current > 0 and self.soc + dsoc < lo:
            current *= (self.soc - lo) / -dsoc if dsoc else 0.0
        elif current < 0 and self.soc + dsoc > hi:
            current *= (hi - self.soc) / dsoc if dsoc else 0.0
        soc_mid = self.soc - 0.5 * current * dt / (3600.0 * self.cell.capacity_Ah)
        R = self.cell.resistance(soc_mid, T_cell)
        q_irr = current**2 * R
        q_rev = -current * T_cell * self.cell.dUdT(soc_mid) if self.entropic else 0.0
        self.soc = min(max(self.soc - current * dt / (3600.0 * self.cell.capacity_Ah), lo), hi)
        for k, v in zip(self.log, (t, current, self.soc, R, q_irr, q_rev)):
            self.log[k].append(v)
        return q_irr + q_rev

    def arrays(self) -> dict[str, np.ndarray]:
        return {k: np.asarray(v) for k, v in self.log.items()}


def simulate_cell(
    cell: Cell,
    profile: CurrentProfile,
    duration: float,
    h: float,
    T_env: float,
    *,
    pcm_thickness: float = 3e-3,
    case_thickness: float = 1e-3,
    soc0: float = 1.0,
    soc_limits: tuple[float, float] = (0.0, 1.0),
    entropic: bool = True,
    T_initial: float | None = None,
    base=None,
):
    """Run an electro-thermal event for one cell in its PCM sleeve and casing.

    Returns (SimulationResult, ElectroThermalLoad); the load holds the SOC,
    current, resistance and heat logs.
    """
    from .cells import params_for_cell
    from .model import simulate

    P = params_for_cell(cell, pcm_thickness, case_thickness, base=base)
    if T_initial is not None:
        P = P.with_(T_initial=T_initial)
    load = ElectroThermalLoad(cell, profile, soc0=soc0, soc_limits=soc_limits, entropic=entropic)
    res = simulate(P, duration=duration, h=h, T_env=T_env, load=load)
    return res, load


def check_limits(cell: Cell, load: ElectroThermalLoad, res, window_s: float = 30.0) -> list[str]:
    """Datasheet-limit warnings for a finished run (empty list = within limits).

    C-rates are judged on a rolling ``window_s`` mean, so short drive-cycle
    peaks are not reported as breaches of a *continuous* rating.
    """
    from .params import KELVIN

    a = load.arrays()
    warnings: list[str] = []
    current = a["current_A"]
    if current.size == 0:
        return warnings
    dt = float(np.median(np.diff(a["t"]))) if current.size > 1 else 1.0
    n = max(1, min(current.size, round(window_s / dt)))
    rolling = np.convolve(current, np.ones(n) / n, mode="valid")
    c_dis = max(rolling.max(), 0.0) / cell.capacity_Ah
    c_chg = max(-rolling.min(), 0.0) / cell.capacity_Ah
    charging = bool((current < 0).any())
    discharging = bool((current > 0).any())
    T_peak = res.T_max.max() - KELVIN
    if cell.max_discharge_C is not None and c_dis > cell.max_discharge_C + 1e-9:
        warnings.append(f"Discharge {c_dis:.2f}C exceeds the {cell.max_discharge_C:.2f}C continuous rating.")
    if cell.max_charge_C is not None and c_chg > cell.max_charge_C + 1e-9:
        warnings.append(f"Charge {c_chg:.2f}C exceeds the {cell.max_charge_C:.2f}C rating.")
    if charging and cell.T_max_charge_C is not None and T_peak > cell.T_max_charge_C:
        warnings.append(f"Peak {T_peak:.1f} degC exceeds the {cell.T_max_charge_C:.0f} degC charging limit.")
    if discharging and cell.T_max_discharge_C is not None and T_peak > cell.T_max_discharge_C:
        warnings.append(f"Peak {T_peak:.1f} degC exceeds the {cell.T_max_discharge_C:.0f} degC discharge limit.")
    return warnings

"""Transient 1D radial finite-volume thermal model: cell -> PCM -> casing.

Started as a port of ``matlab/run_scenario_1D.m``. The governing equation per
control volume is the enthalpy balance

    rho dh(T)/dt = A T + q + b

solved fully implicitly (backward Euler). PCM melting enters through h(T),
whose slope is the apparent heat capacity over the melting range. By default
each step is solved with Newton iteration on the enthalpy residual; the
original thesis scheme (Picard on apparent capacity) is available via
``SolverSettings(scheme="thesis")``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from scipy.linalg.lapack import dgtsv

from .params import KELVIN, Params

CELL, PCM_REGION, CASE = 1, 2, 3

HeatSource = Callable[[float], float]


@dataclass
class Grid:
    r: np.ndarray  # control-volume centres [m]
    region: np.ndarray  # 1 cell, 2 PCM, 3 casing
    dr: float
    volume: np.ndarray  # control-volume volumes [m^3]
    outer_area: float  # m^2


def build_grid(P: Params) -> Grid:
    g = P.geometry
    n = g.n_cells
    dr = g.r_case / n
    r = (np.arange(1, n + 1) - 0.5) * dr
    region = np.full(n, CASE, dtype=int)
    region[r <= g.r_pcm] = PCM_REGION
    region[r <= g.r_cell] = CELL
    r_w = np.maximum(r - dr / 2, 0.0)
    r_e = r + dr / 2
    volume = np.pi * (r_e**2 - r_w**2) * g.length
    outer_area = 2 * np.pi * (r[-1] + dr / 2) * g.length
    return Grid(r, region, dr, volume, outer_area)


def _region_props(grid: Grid, P: Params):
    rho = np.select(
        [grid.region == CELL, grid.region == PCM_REGION],
        [P.cell.rho, P.pcm.rho],
        P.case.rho,
    ).astype(float)
    cp = np.select(
        [grid.region == CELL, grid.region == PCM_REGION],
        [P.cell.cp, P.pcm.cp_solid],
        P.case.cp,
    ).astype(float)
    k = np.select(
        [grid.region == CELL, grid.region == PCM_REGION],
        [P.cell.k, P.pcm.k],
        P.case.k,
    ).astype(float)
    return rho, cp, k


def build_conduction(grid: Grid, P: Params):
    """Tridiagonal conduction operator A [W/(m^3 K)] as (lower, diag, upper)."""
    _, _, k = _region_props(grid, P)
    r, dr, V = grid.r, grid.dr, grid.volume
    r_face = 0.5 * (r[:-1] + r[1:])
    area = 2 * np.pi * r_face * P.geometry.length
    k_face = 2 * k[:-1] * k[1:] / (k[:-1] + k[1:])  # harmonic mean
    G = k_face * area / dr  # W/K
    n = r.size
    diag = np.zeros(n)
    diag[:-1] -= G / V[:-1]
    diag[1:] -= G / V[1:]
    upper = G / V[:-1]  # A[i, i+1]
    lower = G / V[1:]  # A[i+1, i]
    return lower, diag, upper


def boundary_conductance(grid: Grid, P: Params, h: float) -> float:
    """Outer-wall conductance [W/K]: half-cell conduction + convection in series."""
    if h < 0:
        raise ValueError("Convective coefficient cannot be negative.")
    if h == 0:
        return 0.0
    _, _, k = _region_props(grid, P)
    return grid.outer_area / (grid.dr / (2 * k[-1]) + 1.0 / h)


def apparent_cp(T: np.ndarray, P: Params) -> np.ndarray:
    """Apparent specific heat of PCM at temperature T [J/(kg K)]."""
    p = P.pcm
    return np.where(
        T <= p.T_solidus,
        p.cp_solid,
        np.where(T >= p.T_liquidus, p.cp_liquid, p.cp_mushy),
    )


def specific_enthalpy(T: np.ndarray, grid: Grid, P: Params) -> np.ndarray:
    """Specific enthalpy relative to 0 degC [J/kg], consistent with apparent_cp."""
    p = P.pcm
    Tref = KELVIN
    h = np.empty_like(T)
    reg = grid.region
    h[reg == CELL] = P.cell.cp * (T[reg == CELL] - Tref)
    h[reg == CASE] = P.case.cp * (T[reg == CASE] - Tref)
    Tp = T[reg == PCM_REGION]
    h_sol = p.cp_solid * (p.T_solidus - Tref)
    h_liq = h_sol + p.cp_mushy * p.melt_range
    h[reg == PCM_REGION] = np.where(
        Tp <= p.T_solidus,
        p.cp_solid * (Tp - Tref),
        np.where(
            Tp < p.T_liquidus,
            h_sol + p.cp_mushy * (Tp - p.T_solidus),
            h_liq + p.cp_liquid * (Tp - p.T_liquidus),
        ),
    )
    return h


def liquid_fraction(T: np.ndarray, grid: Grid, P: Params) -> float:
    """Volume-weighted PCM liquid fraction (0-1)."""
    m = grid.region == PCM_REGION
    if not m.any():
        return 0.0
    phi = np.clip((T[m] - P.pcm.T_solidus) / P.pcm.melt_range, 0.0, 1.0)
    w = grid.volume[m]
    return float(np.sum(phi * w) / np.sum(w))


@dataclass
class SimulationResult:
    t: np.ndarray  # s
    r: np.ndarray  # m
    region: np.ndarray
    volume: np.ndarray
    T: np.ndarray  # K, radial profiles, shape (n_nodes, len(t_T))
    T_max: np.ndarray  # K, hottest cell node
    T_min: np.ndarray  # K, coolest cell node
    dT_cell: np.ndarray  # K, in-cell spread
    pcm_fraction: np.ndarray
    dE_gen: np.ndarray  # J per step
    dE_boundary: np.ndarray  # J per step, + leaving
    dE_cell: np.ndarray
    dE_pcm: np.ndarray
    dE_case: np.ndarray
    dE_stored: np.ndarray
    dE_residual: np.ndarray
    iterations: np.ndarray
    h: float
    T_env: float
    converged: bool
    max_iterations: int
    heat_W: np.ndarray  # W, mean cell heat generation over each step
    load: object | None = None  # the Load used, holds its own log
    t_T: np.ndarray | None = None  # times of the stored radial profiles in T

    @property
    def unconverged_steps(self) -> int:
        """Steps where the PCM Picard iteration hit max_iterations."""
        return int(np.sum(self.iterations >= self.max_iterations))

    @property
    def E_generated(self) -> float:
        return float(self.dE_gen.sum())

    @property
    def E_rejected(self) -> float:
        return float(self.dE_boundary.sum())

    @property
    def E_stored(self) -> float:
        return float(self.dE_stored.sum())

    @property
    def E_residual(self) -> float:
        return float(self.dE_residual.sum())

    @property
    def balance_error_pct(self) -> float:
        E = self.E_generated
        return 100 * abs(self.E_residual) / abs(E) if abs(E) > 0 else 0.0


class Load(Protocol):
    """Electrical load that produces heat inside the cell region.

    ``power`` is called once per time step with the step start time, the step
    length and the current volume-averaged cell temperature [K]. It returns the
    mean heat generation over the step [W] and may advance internal state
    (state of charge, logs).
    """

    def power(self, t: float, dt: float, T_cell: float) -> float: ...


def simulate(
    P: Params,
    heat_source: HeatSource | None = None,
    duration: float = 600.0,
    h: float = 0.0,
    T_env: float | None = None,
    load: Load | None = None,
) -> SimulationResult:
    """Run one transient event.

    Give exactly one of
      heat_source : callable t [s] -> volumetric heat generation in the cell [W/m^3]
      load        : a :class:`Load` returning total cell heat [W] (electro-thermal)
    duration    : event length [s]
    h           : outer convective coefficient [W/(m^2 K)]; 0 = adiabatic
    T_env       : ambient / coolant temperature [K] (defaults to P.T_initial)
    """
    if (heat_source is None) == (load is None):
        raise ValueError("Give exactly one of heat_source or load.")
    T_env = P.T_initial if T_env is None else T_env
    grid = build_grid(P)
    rho, cp, _ = _region_props(grid, P)
    lower, diag, upper = build_conduction(grid, P)
    n = grid.r.size
    G_bc = boundary_conductance(grid, P, h)

    diag = diag.copy()
    b = np.zeros(n)
    if G_bc > 0:
        sink = G_bc / grid.volume[-1]
        diag[-1] -= sink
        b[-1] += sink * T_env

    s = P.solver
    nt = max(1, round(duration / s.dt))
    dt = duration / nt
    t = np.arange(nt + 1) * dt

    cell, pcm, case = (grid.region == CELL), (grid.region == PCM_REGION), (grid.region == CASE)
    if not cell.any():
        raise ValueError("Grid contains no battery-cell control volumes.")
    V_cell = grid.volume[cell].sum()

    T = np.full(n, P.T_initial)
    # Full radial profiles are stored every `store_every` steps (and at the
    # end); cell max/min temperatures are tracked every step.
    k_store = max(1, int(s.store_every))
    store_idx = np.unique(np.r_[np.arange(0, nt + 1, k_store), nt])
    T_hist = np.empty((n, store_idx.size))
    T_hist[:, 0] = T
    slot = np.full(nt + 1, -1)
    slot[store_idx] = np.arange(store_idx.size)
    T_max = np.empty(nt + 1)
    T_min = np.empty(nt + 1)
    T_max[0] = T_min[0] = P.T_initial
    pcm_frac = np.empty(nt + 1)
    pcm_frac[0] = liquid_fraction(T, grid, P)
    zeros = lambda: np.zeros(nt + 1)
    dE_gen, dE_bc, dE_cell, dE_pcm, dE_case, dE_st, dE_res = (zeros() for _ in range(7))
    heat_W = zeros()
    iters = np.zeros(nt + 1, dtype=int)
    all_converged = True

    rho_cp_base = rho * cp
    sub = -lower  # M[i+1, i]
    sup = -upper  # M[i, i+1]
    q = np.zeros(n)

    def solve(main_diag, rhs):
        x = dgtsv(sub, main_diag, sup, rhs, overwrite_dl=0, overwrite_d=0, overwrite_du=0, overwrite_b=0)[3]
        if not np.all(np.isfinite(x)):
            raise FloatingPointError("Non-finite temperature in linear solve.")
        return x

    # Fast specific enthalpy with precomputed masks (hot path).
    pcm_idx = np.flatnonzero(pcm)
    cp_lin = np.where(cell, P.cell.cp, P.case.cp).astype(float)
    pc = P.pcm
    h_sol = pc.cp_solid * (pc.T_solidus - KELVIN)
    h_liq = h_sol + pc.cp_mushy * pc.melt_range

    def enthalpy(T):
        h = cp_lin * (T - KELVIN)
        Tp = T[pcm_idx]
        h[pcm_idx] = np.where(
            Tp <= pc.T_solidus,
            pc.cp_solid * (Tp - KELVIN),
            np.where(
                Tp < pc.T_liquidus,
                h_sol + pc.cp_mushy * (Tp - pc.T_solidus),
                h_liq + pc.cp_liquid * (Tp - pc.T_liquidus),
            ),
        )
        return h

    def conduction_times(T):
        out = diag * T
        out[:-1] += upper * T[1:]
        out[1:] += lower * T[:-1]
        return out

    h_old = enthalpy(T)
    for step in range(nt):
        if load is not None:
            T_cell = float(np.sum(T[cell] * grid.volume[cell]) / V_cell)
            q_val = float(load.power(t[step], dt, T_cell)) / V_cell
        else:
            q_val = float(heat_source(t[step]))
        if not np.isfinite(q_val):
            raise ValueError(f"Non-finite heat generation at t={t[step]}")
        q[:] = 0.0
        q[cell] = q_val
        heat_W[step + 1] = q_val * V_cell

        T_old = T
        T_guess = T_old.copy()
        converged = False
        for it in range(1, s.max_iterations + 1):
            C = rho_cp_base.copy()
            C[pcm] = P.pcm.rho * apparent_cp(T_guess[pcm], P)
            main = C / dt - diag
            if s.scheme == "enthalpy":
                # Newton on R(T) = rho (h(T) - h_old)/dt - (A T + q + b)
                resid = rho * (enthalpy(T_guess) - h_old) / dt - (conduction_times(T_guess) + q + b)
                delta = solve(main, -resid)
                T_guess = T_guess + delta
                if np.max(np.abs(delta)) < s.tolerance:
                    converged = True
                    break
            else:
                rhs = C / dt * T_old + q + b
                T_cand = solve(main, rhs)
                change = np.max(np.abs(T_cand - T_guess))
                if change < s.tolerance:
                    T_guess = T_cand
                    converged = True
                    break
                T_guess = s.relaxation * T_cand + (1 - s.relaxation) * T_guess
        all_converged &= converged
        # On non-convergence keep going (as the MATLAB reference does); the
        # independent enthalpy balance below exposes any harm.
        iters[step + 1] = it if converged else s.max_iterations
        T = T_guess

        h_new = enthalpy(T)
        dE_gen[step + 1] = np.sum(q * grid.volume) * dt
        dE_bc[step + 1] = G_bc * (T[-1] - T_env) * dt
        dE_node = rho * grid.volume * (h_new - h_old)
        h_old = h_new
        dE_cell[step + 1] = dE_node[cell].sum()
        dE_pcm[step + 1] = dE_node[pcm].sum()
        dE_case[step + 1] = dE_node[case].sum()
        dE_st[step + 1] = dE_node.sum()
        dE_res[step + 1] = dE_gen[step + 1] - dE_bc[step + 1] - dE_st[step + 1]

        if slot[step + 1] >= 0:
            T_hist[:, slot[step + 1]] = T
        Tc = T[cell]
        T_max[step + 1] = Tc.max()
        T_min[step + 1] = Tc.min()
        pcm_frac[step + 1] = liquid_fraction(T, grid, P)

    return SimulationResult(
        t=t,
        r=grid.r,
        region=grid.region,
        volume=grid.volume,
        T=T_hist,
        T_max=T_max,
        T_min=T_min,
        dT_cell=T_max - T_min,
        pcm_fraction=pcm_frac,
        dE_gen=dE_gen,
        dE_boundary=dE_bc,
        dE_cell=dE_cell,
        dE_pcm=dE_pcm,
        dE_case=dE_case,
        dE_stored=dE_st,
        dE_residual=dE_res,
        iterations=iters,
        h=h,
        T_env=T_env,
        converged=all_converged,
        max_iterations=s.max_iterations,
        heat_W=heat_W,
        load=load,
        t_T=t[store_idx],
    )

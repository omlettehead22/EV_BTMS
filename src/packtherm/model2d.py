"""2D (radius x height) finite-volume model for bottom-plate cooling.

The 1D radial model treats the cell as uniform along its height, which suits
side cooling. With a cold plate under the cells, heat runs down the winding to
the base, so the hottest point is at the top. Up to v0.4.7 that was handled by
a distributed sink plus a quasi-steady axial estimate (an upper bound). This
module solves the axisymmetric r-z field instead:

    rho dh(T)/dt = div(k grad T) + q

* radial: the same grid, materials and PCM enthalpy as the 1D model
  (``model.build_grid``), with the cell's radial conductivity;
* axial: ``nz`` layers; the winding conducts along its layers (``k_axial``),
  the filler isotropically;
* base: each bottom node loses heat to the coolant through half a layer of
  conduction, then the roll-end resistance (cell nodes only), the thermal
  interface and the coolant film;
* top: adiabatic; outer radius: adiabatic, or the module wall for edge cells.

Backward Euler, Newton on the enthalpy residual, sparse LU each iteration.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import splu

from .model import CELL, PCM_REGION, Grid, SimulationResult, apparent_cp, build_grid, specific_enthalpy
from .params import Params


@dataclass(frozen=True)
class Axial:
    """Axial discretisation and base boundary for the 2D model."""

    nz: int = 16
    k_axial_cell: float = 25.0  # W/(m K), along the winding layers
    R_base_cell: float = 0.0  # m^2 K/W from the cell's bottom face to the coolant
    R_base_filler: float = 0.0  # m^2 K/W from the filler's bottom face to the coolant


def simulate_2d(
    P: Params,
    axial: Axial,
    duration: float,
    load,
    coolant_T: Callable[[float, np.ndarray, np.ndarray], float],
    T_env: float,
    wall: tuple[float, float] | None = None,
) -> tuple[SimulationResult, np.ndarray]:
    """Run the r-z model.

    coolant_T(t, T_nodes, G) gives the coolant temperature from the start-of-step
    node temperatures and per-node base conductances (as for 1D sinks).
    wall = (area per unit height [m], U [W/m^2K]) puts the outer radius on the
    module wall at T_env. Returns the result and the top-layer temperature of
    the hottest cell node at every step.
    """
    s = P.solver
    g1 = build_grid(P)
    nr, nz = g1.r.size, axial.nz
    L = P.geometry.length
    dz = L / nz
    n = nr * nz
    reg1 = g1.region
    reg = np.tile(reg1, nz)
    area_ann = g1.volume / L  # annulus area of each radial node
    vol = np.tile(g1.volume / nz, nz)
    grid2 = Grid(r=np.tile(g1.r, nz), region=reg, dr=g1.dr, volume=vol, outer_area=g1.outer_area / nz)

    k_r1 = np.where(reg1 == CELL, P.cell.k, P.pcm.k).astype(float)
    k_z1 = np.where(reg1 == CELL, axial.k_axial_cell, P.pcm.k).astype(float)
    rho = np.tile(np.where(reg1 == CELL, P.cell.rho, P.pcm.rho).astype(float), nz)
    cell, pcm = reg == CELL, reg == PCM_REGION

    # Conductances [W/K]
    r_face = 0.5 * (g1.r[:-1] + g1.r[1:])
    Gr = 2 * k_r1[:-1] * k_r1[1:] / (k_r1[:-1] + k_r1[1:]) * 2 * np.pi * r_face * dz / g1.dr
    Gz = k_z1 * area_ann / dz
    R_path = np.where(reg1 == CELL, axial.R_base_cell, axial.R_base_filler)
    Gb1 = area_ann / (dz / (2 * k_z1) + R_path)
    G_base = np.zeros(n)
    G_base[:nr] = Gb1
    G_wall = np.zeros(n)
    if wall is not None:
        a_per_h, U = wall
        if U > 0 and a_per_h > 0:
            G_wall[np.arange(nz) * nr + nr - 1] = a_per_h * dz / (g1.dr / (2 * k_r1[-1]) + 1.0 / U)

    rows, cols, vals = [], [], []

    def link(i, j, G):
        rows.extend([i, j, i, j])
        cols.extend([i, j, j, i])
        vals.extend([-G, -G, G, G])

    for j in range(nz):
        base = j * nr
        for i in range(nr - 1):
            link(base + i, base + i + 1, Gr[i])
        if j < nz - 1:
            for i in range(nr):
                Gzz = 2 * Gz[i] * Gz[i] / (Gz[i] + Gz[i])  # same material above and below
                link(base + i, base + nr + i, Gzz)
    K = sp.csc_matrix((vals, (rows, cols)), shape=(n, n))  # W/K, conduction only
    K = K - sp.diags(G_base + G_wall)
    A = sp.diags(1.0 / vol) @ K  # W/(m^3 K)

    dt = s.dt
    nt = int(np.ceil(duration / dt))
    t = np.arange(nt + 1) * dt
    T = np.full(n, P.T_initial)
    V_cell = vol[cell].sum()

    def enthalpy(T):
        return specific_enthalpy(T, grid2, P)

    out = {k: np.zeros(nt + 1) for k in ("T_max", "T_min", "T_top", "T_surf", "pcm", "heat", "gen", "bc", "st")}
    Q_cool, T_cool, Q_wall = np.zeros(nt + 1), np.zeros(nt + 1), np.zeros(nt + 1)
    iters = np.zeros(nt + 1, dtype=int)
    top = slice((nz - 1) * nr, n)
    out["T_max"][0] = out["T_min"][0] = out["T_top"][0] = out["T_surf"][0] = P.T_initial
    T_cool[0] = coolant_T(0.0, T, G_base)
    h_old = enthalpy(T)
    q = np.zeros(n)
    all_conv = True
    pcm_vol = vol[pcm].sum()
    C_base = np.where(cell, rho * P.cell.cp, 0.0)
    lu, lu_band = None, None

    def phase_band(T):
        Tp = T[pcm]
        return (Tp > P.pcm.T_solidus).astype(np.int8) + (Tp >= P.pcm.T_liquidus).astype(np.int8)

    for step in range(nt):
        T_cell = float(np.sum(T[cell] * vol[cell]) / V_cell)
        P_W = float(load.power(t[step], dt, T_cell))
        q[:] = 0.0
        q[cell] = P_W / V_cell
        Tc = coolant_T(t[step], T, G_base)
        T_cool[step + 1] = Tc
        b = (G_base * Tc + G_wall * T_env) / vol
        Tg = T.copy()
        conv = False
        for it in range(1, s.max_iterations + 1):
            # The apparent heat capacity is piecewise constant (solid / mushy /
            # liquid), so the Jacobian only changes when a PCM node changes
            # phase band: refactorise only then.
            band = phase_band(Tg)
            if lu is None or not np.array_equal(band, lu_band):
                C = C_base.copy()
                C[pcm] = P.pcm.rho * apparent_cp(Tg[pcm], P)
                lu = splu((sp.diags(C / dt) - A).tocsc())
                lu_band = band
            resid = rho * (enthalpy(Tg) - h_old) / dt - (A @ Tg + q + b)
            delta = lu.solve(-resid)
            Tg = Tg + delta
            if np.max(np.abs(delta)) < s.tolerance:
                conv = True
                break
        all_conv &= conv
        iters[step + 1] = it
        T = Tg
        h_new = enthalpy(T)
        Q_cool[step + 1] = float(np.sum(G_base * (T - Tc)))
        Q_wall[step + 1] = float(np.sum(G_wall * (T - T_env)))
        out["gen"][step + 1] = P_W * dt
        out["bc"][step + 1] = (Q_cool[step + 1] + Q_wall[step + 1]) * dt
        out["st"][step + 1] = float(np.sum(rho * vol * (h_new - h_old)))
        h_old = h_new
        out["heat"][step + 1] = P_W
        out["T_max"][step + 1] = T[cell].max()
        out["T_min"][step + 1] = T[cell].min()
        out["T_top"][step + 1] = T[top][reg1 == CELL].max()
        out["T_surf"][step + 1] = T[top][-1]
        if pcm.any():
            phi = np.clip((T[pcm] - P.pcm.T_solidus) / P.pcm.melt_range, 0.0, 1.0)
            out["pcm"][step + 1] = float(np.sum(phi * vol[pcm]) / pcm_vol)

    res_ = out["gen"] - out["bc"] - out["st"]
    z = np.zeros(nt + 1)
    res = SimulationResult(
        t=t,
        r=g1.r,
        region=reg1,
        volume=g1.volume,
        T=T.reshape(nz, nr).T,  # final field, radius x height
        T_max=out["T_max"],
        T_min=out["T_min"],
        dT_cell=out["T_max"] - out["T_min"],
        pcm_fraction=out["pcm"],
        dE_gen=out["gen"],
        dE_boundary=out["bc"],
        dE_cell=z,
        dE_pcm=z,
        dE_case=z,
        dE_stored=out["st"],
        dE_residual=res_,
        iterations=iters,
        h=0.0,
        T_env=T_env,
        converged=all_conv,
        max_iterations=s.max_iterations,
        heat_W=out["heat"],
        load=load,
        t_T=t[-1:],
        T_surface=out["T_surf"],
        Q_sinks={"coolant": Q_cool, "wall": Q_wall},
        T_sinks={"coolant": T_cool},
    )
    return res, out["T_top"]


__all__ = ["Axial", "simulate_2d"]

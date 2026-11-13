"""2D finite-volume models: radius x height (bottom plate), radius x angle (side ribbon).

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


def _link(rows, cols, vals, i, j, G):
    rows.extend([i, j, i, j])
    cols.extend([i, j, j, i])
    vals.extend([-G, -G, G, G])


def simulate_2d(
    P: Params,
    axial: Axial,
    duration: float,
    load,
    coolant_T: Callable[[float, np.ndarray, np.ndarray], float],
    T_env: float,
    wall: tuple[float, float] | None = None,
) -> tuple[SimulationResult, np.ndarray]:
    """Run the r-z model (bottom plate).

    coolant_T(t, T_nodes, G) gives the coolant temperature from the start-of-step
    node temperatures and per-node base conductances (as for 1D sinks).
    wall = (area per unit height [m], U [W/m^2K]) puts the outer radius on the
    module wall at T_env. Returns the result and the top-layer temperature of
    the hottest cell node at every step.
    """
    g1 = build_grid(P)
    nr, nz = g1.r.size, axial.nz
    L = P.geometry.length
    dz = L / nz
    n = nr * nz
    reg1 = g1.region
    area_ann = g1.volume / L  # annulus area of each radial node
    vol = np.tile(g1.volume / nz, nz)
    k_r1 = np.where(reg1 == CELL, P.cell.k, P.pcm.k).astype(float)
    k_z1 = np.where(reg1 == CELL, axial.k_axial_cell, P.pcm.k).astype(float)

    r_face = 0.5 * (g1.r[:-1] + g1.r[1:])
    Gr = 2 * k_r1[:-1] * k_r1[1:] / (k_r1[:-1] + k_r1[1:]) * 2 * np.pi * r_face * dz / g1.dr
    Gz = k_z1 * area_ann / dz
    R_path = np.where(reg1 == CELL, axial.R_base_cell, axial.R_base_filler)
    G_base = np.zeros(n)
    G_base[:nr] = area_ann / (dz / (2 * k_z1) + R_path)
    # The roll's base face sits half a layer below the bottom node centres: the
    # share of each node-to-coolant drop inside that half layer. The coolest
    # point of the cell is on that face, not at a node centre (v0.4.13).
    face = np.zeros(n)
    face[:nr] = (dz / (2 * k_z1)) / (dz / (2 * k_z1) + R_path)
    G_wall = np.zeros(n)
    if wall is not None:
        a_per_h, U = wall
        if U > 0 and a_per_h > 0:
            G_wall[np.arange(nz) * nr + nr - 1] = a_per_h * dz / (g1.dr / (2 * k_r1[-1]) + 1.0 / U)

    rows, cols, vals = [], [], []
    for j in range(nz):
        base = j * nr
        for i in range(nr - 1):
            _link(rows, cols, vals, base + i, base + i + 1, Gr[i])
        if j < nz - 1:
            for i in range(nr):
                _link(rows, cols, vals, base + i, base + nr + i, Gz[i])
    K = sp.csc_matrix((vals, (rows, cols)), shape=(n, n))
    top = np.arange((nz - 1) * nr, n)
    return _run(P, g1, np.tile(reg1, nz), vol, K, G_base, G_wall, coolant_T, T_env, load, duration, top, face=face)


def _run(P, g1, reg, vol, K, G_cool, G_wall, coolant_T, T_env, load, duration, watch, share=1.0, face=None):
    """Shared implicit enthalpy-Newton loop for the 2D grids.

    K: conduction conductance matrix [W/K] (Laplacian, no boundary terms);
    G_cool, G_wall: per-node conductances to the coolant and to ambient.
    watch: node indices whose hottest cell node is reported every step.
    share: the fraction of the cell the grid covers (0.5 for a half by
    symmetry). Heat, energies and sink flows are reported per whole cell.
    face: per node, the share of its drop to the coolant that lies between the
    node centre and the cooled face; the coolest cell temperature is taken on
    that face (so the in-cell spread does not depend on the layer thickness).
    """
    s = P.solver
    n = vol.size
    nr = g1.r.size
    grid2 = Grid(r=np.tile(g1.r, n // nr), region=reg, dr=g1.dr, volume=vol, outer_area=g1.outer_area)
    cell, pcm = reg == CELL, reg == PCM_REGION
    rho = np.where(cell, P.cell.rho, P.pcm.rho).astype(float)
    A = sp.diags(1.0 / vol) @ (K - sp.diags(G_cool + G_wall))  # W/(m^3 K)

    dt = s.dt
    nt = int(np.ceil(duration / dt))
    t = np.arange(nt + 1) * dt
    T = np.full(n, P.T_initial)
    V_cell = vol[cell].sum()

    def enthalpy(T):
        return specific_enthalpy(T, grid2, P)

    out = {k: np.zeros(nt + 1) for k in ("T_max", "T_min", "T_watch", "T_surf", "pcm", "heat", "gen", "bc", "st")}
    Q_cool, T_cool, Q_wall = np.zeros(nt + 1), np.zeros(nt + 1), np.zeros(nt + 1)
    iters = np.zeros(nt + 1, dtype=int)
    watch_cell = watch[cell[watch]]
    surf = watch[-1]
    for key in ("T_max", "T_min", "T_watch", "T_surf"):
        out[key][0] = P.T_initial
    T_cool[0] = coolant_T(0.0, T, G_cool / share)
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
        q[cell] = P_W * share / V_cell
        Tc = coolant_T(t[step], T, G_cool / share)
        T_cool[step + 1] = Tc
        b = (G_cool * Tc + G_wall * T_env) / vol
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
        Q_cool[step + 1] = float(np.sum(G_cool * (T - Tc))) / share
        Q_wall[step + 1] = float(np.sum(G_wall * (T - T_env))) / share
        out["gen"][step + 1] = P_W * dt
        out["bc"][step + 1] = (Q_cool[step + 1] + Q_wall[step + 1]) * dt
        out["st"][step + 1] = float(np.sum(rho * vol * (h_new - h_old))) / share
        h_old = h_new
        out["heat"][step + 1] = P_W
        out["T_max"][step + 1] = T[cell].max()
        T_lo = T[cell].min()
        if face is not None:
            cooled = cell & (face > 0)
            if cooled.any():
                T_lo = min(T_lo, float(np.min(T[cooled] - face[cooled] * (T[cooled] - Tc))))
        out["T_min"][step + 1] = T_lo
        out["T_watch"][step + 1] = T[watch_cell].max()
        out["T_surf"][step + 1] = T[surf]
        if pcm.any():
            phi = np.clip((T[pcm] - P.pcm.T_solidus) / P.pcm.melt_range, 0.0, 1.0)
            out["pcm"][step + 1] = float(np.sum(phi * vol[pcm]) / pcm_vol)

    z = np.zeros(nt + 1)
    res = SimulationResult(
        t=t,
        r=g1.r,
        region=g1.region,
        volume=g1.volume,
        T=T.reshape(-1, nr).T,  # final field, radius x (height or angle)
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
        dE_residual=out["gen"] - out["bc"] - out["st"],
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
    return res, out["T_watch"]


@dataclass(frozen=True)
class Strip:
    """Circumferential discretisation for a side ribbon bonded along a strip.

    The jelly roll is wound in a spiral, so around the circumference heat runs
    along the layers: it uses the in-plane conductivity (as along the height).
    The steel can adds a thin circumferential path. ASSUMPTIONS: can wall
    0.25 mm, k = 50 W/m K (nickel-plated low-carbon steel).
    """

    n_theta: int = 12  # angular slices over half the circumference (symmetry)
    k_inplane_cell: float = 25.0
    can_mm: float = 0.25
    k_can: float = 50.0


def simulate_rtheta(
    P: Params,
    strip: Strip,
    contact_fraction: float,
    G_contact_per_area: float,
    contact_height: float,
    duration: float,
    load,
    coolant_T: Callable[[float, np.ndarray, np.ndarray], float],
    T_env: float,
    wall: tuple[float, float] | None = None,
) -> tuple[SimulationResult, np.ndarray]:
    """Run the r-theta model (side ribbon on a strip of the can).

    Half the cell's share by symmetry, theta = 0 under the ribbon's centre. The
    ribbon cools the can surface over theta < contact_fraction * pi with
    conductance per area G_contact_per_area over contact_height of the can.
    wall = (area per unit height [m], U): edge cells, spread evenly round the
    outer boundary. Returns the result and the hottest can-surface temperature.
    """
    g1 = build_grid(P)
    nr, nt_ = g1.r.size, strip.n_theta
    L = P.geometry.length
    dth = np.pi / nt_
    n = nr * nt_
    reg1 = g1.region
    vol1 = g1.volume / (2 * nt_)  # half the circumference in n_theta slices
    vol = np.tile(vol1, nt_)
    k_r1 = np.where(reg1 == CELL, P.cell.k, P.pcm.k).astype(float)
    k_t1 = np.where(reg1 == CELL, strip.k_inplane_cell, P.pcm.k).astype(float)
    i_can = int(np.flatnonzero(reg1 == CELL)[-1])

    r_face = 0.5 * (g1.r[:-1] + g1.r[1:])
    Gr = 2 * k_r1[:-1] * k_r1[1:] / (k_r1[:-1] + k_r1[1:]) * r_face * dth * L / g1.dr
    Gt = k_t1 * g1.dr * L / (g1.r * dth)
    Gt[i_can] += strip.k_can * strip.can_mm * 1e-3 * L / (g1.r[i_can] * dth)
    r_can = g1.r[i_can] + g1.dr / 2
    edges = np.arange(nt_ + 1) * dth
    covered = np.clip(contact_fraction * np.pi - edges[:-1], 0.0, dth)  # angle of each slice in contact
    G_cool = np.zeros(n)
    G_half = 1.0 / (g1.dr / (2 * k_r1[i_can]) + 1.0 / G_contact_per_area)
    G_cool[np.arange(nt_) * nr + i_can] = G_half * r_can * covered * contact_height
    face = np.zeros(n)
    face[np.arange(nt_) * nr + i_can] = np.where(
        covered > 0, (g1.dr / (2 * k_r1[i_can])) / (g1.dr / (2 * k_r1[i_can]) + 1.0 / G_contact_per_area), 0.0
    )
    G_wall = np.zeros(n)
    if wall is not None:
        a_per_h, U = wall
        if U > 0 and a_per_h > 0:
            G_wall[np.arange(nt_) * nr + nr - 1] = a_per_h * L / (2 * nt_) / (g1.dr / (2 * k_r1[-1]) + 1.0 / U)

    rows, cols, vals = [], [], []
    for j in range(nt_):
        base = j * nr
        for i in range(nr - 1):
            _link(rows, cols, vals, base + i, base + i + 1, Gr[i])
        if j < nt_ - 1:
            for i in range(nr):
                _link(rows, cols, vals, base + i, base + nr + i, Gt[i])
    K = sp.csc_matrix((vals, (rows, cols)), shape=(n, n))
    can = np.arange(nt_) * nr + i_can
    return _run(
        P, g1, np.tile(reg1, nt_), vol, K, G_cool, G_wall, coolant_T, T_env, load, duration, can, share=0.5, face=face
    )


__all__ = ["Axial", "Strip", "simulate_2d", "simulate_rtheta"]

"""Identify the NCR18650PF electrical model from the dataset's characterisation tests.

Usage:
    python validation/identify_panasonic.py /path/to/Panasonic-18650PF-Data

Reproduces the constants in ``btms.cells.NCR18650PF_ECM`` and the OCV table
``src/btms/data/ncr18650pf_ocv.csv``:

* OCV(SOC): the 25 degC C/20 discharge plus its own I*R drop.
* Kinetics: every HPPC pulse (0.5-6C, 10 s) at 25, 10, 0, -10 and -20 degC.
  The 10 s overpotential at 20-95 % SOC is fitted to
      eta = I R0 exp(Ea_R0/R (1/T - 1/T25)) + gamma (2RT/F) asinh(I / (2 I0(T)))
  with I0(T) = I0_25 exp(-Ea_I0/R (1/T - 1/T25)).
* Low-SOC factor: the ratio of measured to fitted overpotential over all
  SOCs, fitted to 1 + a exp(-SOC/b).

The slow branch (Rd, tau_d) and the chamber h are calibrated separately on the
25 degC 1C discharge #1 by ``btms.validation.calibrate``.

Source: P. Kollmeyer, "Panasonic 18650PF Li-ion Battery Data", Mendeley Data v1
(2018), doi:10.17632/wykht8y7tg.1, CC BY 4.0.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import scipy.io as sio
from scipy.optimize import least_squares

F, R_GAS, T25 = 96485.33212, 8.314462618, 298.15
FOLDERS = ["Panasonic 18650PF Data/25degC", "10degC", "0degC", "-10degC", "-20degC"]
CAPACITY = 2.99491  # Ah, C/20 at 25 degC


def load(p: Path) -> dict[str, np.ndarray]:
    m = sio.loadmat(str(p), squeeze_me=True, struct_as_record=False)["meas"]
    return {
        k: np.atleast_1d(getattr(m, k)).astype(float) for k in ("Time", "Voltage", "Current", "Ah", "Battery_Temp_degC")
    }


def pulse_points(root: Path) -> np.ndarray:
    """(T_K, soc, I, eta_10s) for every >= 9 s HPPC pulse at every temperature."""
    pts = []
    for folder in FOLDERS:
        path = next(p for p in (root / folder).glob("*ulse*/*.mat") if "dis5" not in p.name)
        d = load(path)
        t, I, V, Ah, T = d["Time"], d["Current"], d["Voltage"], d["Ah"], d["Battery_Temp_degC"]
        on = np.abs(I) > 0.05
        e = np.flatnonzero(np.diff(on.astype(int)))
        for s, k in zip(e[::2] + 1, e[1::2] + 1):
            if t[k] - t[s] < 9:
                continue
            i10 = s + np.searchsorted(t[s:k] - t[s - 1], 10.0) - 1
            pts.append((T[s] + 273.15, 1 + Ah[s] / CAPACITY, -I[s:k].mean(), V[s - 1] - V[i10]))
    return np.array(pts)


def overpotential(p, Tk, current):
    lnR0, Ea0, lnI0, EaI, gamma = p
    R0 = np.exp(lnR0) * np.exp(Ea0 / R_GAS * (1 / Tk - 1 / T25))
    I0 = np.exp(lnI0) * np.exp(-EaI / R_GAS * (1 / Tk - 1 / T25))
    return current * R0 + gamma * 2 * R_GAS * Tk / F * np.arcsinh(current / (2 * I0))


def main(root: str) -> dict:
    pts = pulse_points(Path(root))
    Tk, soc, current, eta = pts.T
    mid = (soc > 0.2) & (soc < 0.95)
    fit = least_squares(
        lambda p: (overpotential(p, Tk[mid], current[mid]) - eta[mid]) / np.maximum(eta[mid], 0.02),
        [np.log(0.03), 20e3, np.log(2.0), 40e3, 1.0],
        bounds=([np.log(1e-3), 0, np.log(1e-3), 0, 0.1], [np.log(0.5), 1e5, np.log(100), 1.5e5, 10]),
    )
    lnR0, Ea0, lnI0, EaI, gamma = fit.x
    pred = overpotential(fit.x, Tk, current)
    ratio = eta / pred
    a, b = least_squares(
        lambda q: 1 + q[0] * np.exp(-soc / q[1]) - ratio, [1.0, 0.05], bounds=([0, 0.005], [20, 0.5])
    ).x
    out = {
        "R0_25C": np.exp(lnR0),
        "Ea_R0": Ea0,
        "I0_25C": np.exp(lnI0),
        "Ea_I0": EaI,
        "gamma": gamma,
        "soc_a": a,
        "soc_b": b,
    }
    for k, v in out.items():
        print(f"{k:>8} = {v:.4g}")
    for Tn in (25, 10, 0, -10, -20):
        sel = mid & (np.abs(Tk - 273.15 - Tn) < 2)
        err = np.abs(pred[sel] / eta[sel] - 1)
        print(f"{Tn:>4} degC: {sel.sum():2d} pulses, 10 s overpotential error median {100 * np.median(err):.1f} %")
    return out


if __name__ == "__main__":
    main(sys.argv[1])

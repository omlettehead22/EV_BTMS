# ruff: noqa: SIM115
"""Derive the LG M50 equivalent circuit from PyBaMM (DFN + ORegan2022).

Not measured data: a physics model with a parameter set measured on the LG M50T
(O'Regan et al. 2022) is run through synthetic characterisation tests, and the
same circuit as the NCR18650PF is fitted to them. Requires `pip install pybamm`.

    python validation/derive_m50_ecm.py           # writes synthetic.pkl, m50_ecm.pkl, prints constants
    python validation/derive_m50_ecm.py --check   # heat and cut-off against the DFN

Results used in packtherm.cells.LG_M50_ECM (v0.4.11).
"""

# ---- 1. synthetic characterisation ----
import pickle
import sys
import time

import numpy as np
import pybamm

pybamm.set_logging_level("ERROR")


def params(T):
    p = pybamm.ParameterValues("ORegan2022")
    p.update({"Ambient temperature [K]": T, "Initial temperature [K]": T})
    return p


out = {}
t0 = time.time()
# OCV: C/25 discharge and charge at 25 degC
p = params(298.15)
m = pybamm.lithium_ion.DFN()
sd = pybamm.Simulation(
    m, parameter_values=p, experiment=pybamm.Experiment(["Discharge at C/25 until 2.5 V"], period="60 seconds")
).solve()
Qd = sd["Discharge capacity [A.h]"].entries
Vd = sd["Voltage [V]"].entries
sc = pybamm.Simulation(
    pybamm.lithium_ion.DFN(),
    parameter_values=p,
    experiment=pybamm.Experiment(["Rest for 1 hour", "Charge at C/25 until 4.2 V"], period="60 seconds"),
).solve(initial_soc=0.0)
out["ocv"] = {"Qd": Qd, "Vd": Vd, "Qc": sc["Discharge capacity [A.h]"].entries, "Vc": sc["Voltage [V]"].entries}
C = Qd[-1]
print("C/25 capacity", C, time.time() - t0)
rates = [0.2, 0.5, 1, 2, 3]
for Tc in (25, 10, 0, -10):
    T = Tc + 273.15
    steps = []
    socs = [0.95, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.15, 0.1, 0.05]
    prev = 1.0
    for s in socs:
        dt_min = (prev - s) * 60 / (1 / 3)  # minutes at C/3 to go from prev to s
        steps += [f"Discharge at C/3 for {dt_min:.2f} minutes or until 2.5 V", "Rest for 1 hour"]
        for r in rates:
            steps += [f"Discharge at {r}C for 10 seconds or until 2.5 V", "Rest for 2 minutes"]
        prev = s
    exp = pybamm.Experiment(steps, period="1 second")
    sim = pybamm.Simulation(pybamm.lithium_ion.DFN(), parameter_values=params(T), experiment=exp)
    sol = sim.solve(initial_soc=1.0)
    out[Tc] = {
        "t": sol["Time [s]"].entries,
        "I": sol["Current [A]"].entries,
        "V": sol["Voltage [V]"].entries,
        "Q": sol["Discharge capacity [A.h]"].entries,
    }
    print(Tc, "done", len(out[Tc]["t"]), "pts", round(time.time() - t0), "s, Q end", out[Tc]["Q"][-1])
out["C"] = C
pickle.dump(out, open("synthetic.pkl", "wb"))

# ---- 2. circuit fit ----
import math
from dataclasses import replace

from scipy.optimize import least_squares

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import identify_panasonic as ip

from packtherm.ecm import ECM, ECMState

R, T25 = 8.314462618, 298.15
D = pickle.load(open("synthetic.pkl", "rb"))
CAP = 5.0
# OCV: mean of C/25 discharge and charge, on SOC = 1 - Q/5.0
o = D["ocv"]
sd = 1 - o["Qd"] / CAP
sc = sd[-1] - o["Qc"] / CAP  # charge starts from the discharged state
grid = np.linspace(max(sd.min(), sc.min()) + 0.002, min(sd.max(), sc.max()), 81)
Vd = np.interp(grid, sd[::-1], o["Vd"][::-1])
Vc = np.interp(grid, np.sort(sc), o["Vc"][np.argsort(sc)])
ocv = 0.5 * (Vd + Vc)
print("OCV range", ocv[0], ocv[-1], "soc", grid[0])
# pulses
pts = []
for Tc in (25, 10, 0, -10):
    d = D[Tc]
    t, I, V, Q = d["t"], d["I"], d["V"], d["Q"]
    on = I > 0.05
    e = np.flatnonzero(np.diff(on.astype(int))) + 1
    if on[0]:
        e = np.r_[0, e]
    for s, k in zip(e[::2], e[1::2]):
        dur = t[k - 1] - t[s - 1]
        if not (9 < dur < 11):
            continue
        i10 = s + np.searchsorted(t[s:k] - t[s - 1], 10.0) - 1
        if s == 0:
            continue
        pts.append((Tc + 273.15, 1 - Q[s - 1] / CAP, I[s:k].mean(), V[s - 1] - V[i10]))
pts = np.array(pts)
Tk, soc, cur, eta = pts.T
print(len(pts), "pulses")
mid = (soc > 0.2) & (soc < 0.95)
fit = least_squares(
    lambda p: (ip.overpotential(p, Tk[mid], cur[mid]) - eta[mid]) / np.maximum(eta[mid], 0.005),
    [np.log(0.02), 20e3, np.log(5.0), 40e3, 1.0],
    bounds=([np.log(1e-4), 0, np.log(1e-3), 0, 0.1], [np.log(0.5), 1e5, np.log(500), 1.5e5, 10]),
)
lnR0, Ea0, lnI0, EaI, gamma = fit.x
pred = ip.overpotential(fit.x, Tk, cur)
for Tn in (25, 10, 0, -10):
    sel = mid & (np.abs(Tk - 273.15 - Tn) < 1)
    print(Tn, "pulse fit median err %.1f%%" % (100 * np.median(np.abs(pred[sel] / eta[sel] - 1))))
# low-SOC factor with temperature
low = soc < 0.3


def rsoc(q):
    a25, b, Ea = q
    a = a25 * np.exp(Ea / R * (1 / Tk - 1 / T25))
    return (1 + a * np.exp(-soc / b)) * pred - eta


fq = least_squares(
    lambda q: rsoc(q) / np.maximum(eta, 0.005), [1.0, 0.05, 20e3], bounds=([0, 0.005, 0], [50, 0.5, 1e5])
)
a25, b, Easoc = fq.x
print(
    f"R0 {math.exp(lnR0):.4f} Ea_R0 {Ea0:.0f} I0 {math.exp(lnI0):.3f} Ea_I0 {EaI:.0f} gamma {gamma:.3f} | soc_a {a25:.3f} soc_b {b:.4f} Ea_soc {Easoc:.0f}"
)
base = ECM(
    ocv_soc=tuple(grid),
    ocv_V=tuple(ocv),
    R0_25C=math.exp(lnR0),
    Ea_R0=Ea0,
    I0_25C=math.exp(lnI0),
    Ea_I0=EaI,
    gamma=gamma,
    tau_ct=4.0,
    Rd_25C=0.01,
    tau_d=300.0,
    V_max=4.2,
    V_min=2.5,
    cv_cutoff_A=0.05,
    soc_a=a25,
    soc_b=b,
    Ea_soc=Easoc,
    Ea_Rd=20e3,
)


def replay(ecm, d, step=5):
    t, I, V, Q = d["t"][::step], d["I"][::step], d["V"][::step], d["Q"][::step]
    st = ECMState()
    out = np.empty_like(V)
    out[0] = V[0]
    T = d["Tk"]
    for k in range(1, len(t)):
        Vk, eta_, vd = st.step(ecm, I[k], 1 - Q[k] / CAP, T, t[k] - t[k - 1])
        st.eta_ct, st.V_d = eta_, vd
        out[k] = Vk
    return out, V


for Tc in (25, 10, 0, -10):
    D[Tc]["Tk"] = Tc + 273.15


def resid(p):
    Rd, ltau, EaRd, ltct = p
    ecm = replace(base, Rd_25C=Rd, tau_d=math.exp(ltau), Ea_Rd=EaRd, tau_ct=math.exp(ltct))
    r = []
    for Tc in (25, 10, 0, -10):
        m, V = replay(ecm, D[Tc])
        soc = 1 - D[Tc]["Q"][::5] / CAP
        r.append((m - V)[soc > 0.1])
    return np.concatenate(r)


r0 = resid([0.01, math.log(300), 20e3, math.log(4)])
fs = least_squares(
    resid,
    [0.01, math.log(300), 20e3, math.log(4)],
    bounds=([1e-4, math.log(10), 0, math.log(0.3)], [0.2, math.log(1e4), 1e5, math.log(60)]),
    diff_step=1e-3,
)
Rd, ltau, EaRd, ltct = fs.x
print(
    f"slow: Rd {Rd:.4f} tau {math.exp(ltau):.0f} Ea_Rd {EaRd:.0f} tau_ct {math.exp(ltct):.1f} | rmse {1e3 * np.sqrt(np.mean(r0**2)):.1f} -> {1e3 * np.sqrt(np.mean(fs.fun**2)):.1f} mV"
)
ecm = replace(base, Rd_25C=Rd, tau_d=math.exp(ltau), Ea_Rd=EaRd, tau_ct=math.exp(ltct))
for Tc in (25, 10, 0, -10):
    m, V = replay(ecm, D[Tc])
    soc = 1 - D[Tc]["Q"][::5] / CAP
    print(
        Tc,
        f"replay rmse (SOC>10%) {1e3 * np.sqrt(np.mean((m - V)[soc > 0.1] ** 2)):.1f} mV, all {1e3 * np.sqrt(np.mean((m - V) ** 2)):.1f} mV",
    )
pickle.dump(ecm, open("m50_ecm.pkl", "wb"))

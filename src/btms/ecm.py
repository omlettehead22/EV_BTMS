"""Equivalent-circuit electrical model with temperature-dependent kinetics.

Terminal voltage (current I > 0 on discharge):

    V = OCV(SOC) - I R0(T) - eta_ct - V_d

* R0(T): ohmic resistance, Arrhenius in temperature.
* eta_ct: charge-transfer overpotential. Its steady-state value follows a
  lumped Butler-Volmer form, eta_ss = A(T) asinh(I / (2 I0(T))) with
  A = gamma 2RT/F, so the apparent resistance falls as current rises and
  climbs steeply in the cold. It relaxes to eta_ss with time constant tau_ct.
* On discharge all three are scaled by a low-SOC factor 1 + soc_a exp(-SOC/soc_b)
  (identified from discharge pulses, so not applied while charging).
* V_d: a slow (diffusion) RC branch with resistance R_d(T) and time
  constant tau_d. R_d scales with the small-signal charge-transfer
  resistance so its temperature dependence comes from the same kinetics.

Irreversible heat is I (OCV - V), so every loss term heats the cell.
Discharge stops at V_min; charging switches from constant current to
constant voltage at V_max and ends when |I| falls below the cut-off.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

F = 96485.33212
R_GAS = 8.314462618
T_REF = 298.15


@dataclass(frozen=True)
class ECM:
    ocv_soc: tuple[float, ...]
    ocv_V: tuple[float, ...]
    R0_25C: float  # Ohm
    Ea_R0: float  # J/mol
    I0_25C: float  # A, lumped exchange current
    Ea_I0: float  # J/mol
    gamma: float  # multiplier on 2RT/F
    tau_ct: float = 2.0  # s
    Rd_25C: float = 0.0  # Ohm, slow branch
    tau_d: float = 300.0  # s
    V_max: float = 4.2
    V_min: float = 2.5
    cv_cutoff_A: float = 0.05
    # Low-SOC rise of all overpotentials: factor = 1 + soc_a exp(-SOC / soc_b).
    soc_a: float = 0.0
    soc_b: float = 0.08
    sources: tuple[str, ...] = field(default=())

    def soc_factor(self, soc: float) -> float:
        return 1.0 + self.soc_a * math.exp(-max(soc, 0.0) / self.soc_b)

    def ocv(self, soc: float) -> float:
        """OCV from the table; linear extrapolation (slope of the last 5 %) outside it."""
        s, v = self.ocv_soc, self.ocv_V
        if soc > s[-1]:
            k = min(len(s) - 1, max(1, round(0.05 / (s[-1] - s[-2]))))
            return v[-1] + (v[-1] - v[-1 - k]) / (s[-1] - s[-1 - k]) * (soc - s[-1])
        if soc < s[0]:
            k = min(len(s) - 1, max(1, round(0.05 / (s[1] - s[0]))))
            return v[0] + (v[k] - v[0]) / (s[k] - s[0]) * (soc - s[0])
        return float(np.interp(soc, s, v))

    def R0(self, T: float) -> float:
        return self.R0_25C * math.exp(self.Ea_R0 / R_GAS * (1.0 / T - 1.0 / T_REF))

    def I0(self, T: float) -> float:
        return self.I0_25C * math.exp(-self.Ea_I0 / R_GAS * (1.0 / T - 1.0 / T_REF))

    def A(self, T: float) -> float:
        return self.gamma * 2.0 * R_GAS * T / F

    def eta_ss(self, current: float, T: float) -> float:
        return self.A(T) * math.asinh(current / (2.0 * self.I0(T)))

    def R_ct_small_signal(self, T: float) -> float:
        return self.A(T) / (2.0 * self.I0(T))

    def Rd(self, T: float) -> float:
        return self.Rd_25C * self.R_ct_small_signal(T) / self.R_ct_small_signal(T_REF)


@dataclass
class ECMState:
    eta_ct: float = 0.0
    V_d: float = 0.0
    cutoff: bool = False  # discharge hit V_min
    charge_done: bool = False  # CV phase ended

    def step(self, ecm: ECM, current: float, soc: float, T: float, dt: float) -> tuple[float, float, float]:
        """Voltage after a step at ``current`` without committing: (V, eta_ct_new, V_d_new)."""
        e1 = math.exp(-dt / ecm.tau_ct)
        e2 = math.exp(-dt / ecm.tau_d)
        # The low-SOC rise was identified on discharge pulses; apply it on discharge only.
        f = ecm.soc_factor(soc) if current > 0 else 1.0
        eta = self.eta_ct * e1 + f * ecm.eta_ss(current, T) * (1.0 - e1)
        vd = self.V_d * e2 + f * ecm.Rd(T) * current * (1.0 - e2)
        V = ecm.ocv(soc) - current * f * ecm.R0(T) - eta - vd
        return V, eta, vd

    def apply(self, ecm: ECM, current: float, soc: float, T: float, dt: float) -> tuple[float, float]:
        """Enforce voltage limits, commit the step and return (current, V).

        Discharge below V_min stops the test (current 0 from then on).
        Charge above V_max switches to constant voltage: the current is
        reduced (by bisection, V is monotonic in I) to hold V_max until it
        falls below the cut-off, which ends the charge.
        """
        if current > 0 and self.cutoff:
            current = 0.0
        if current < 0 and self.charge_done:
            current = 0.0
        V, eta, vd = self.step(ecm, current, soc, T, dt)
        if current > 0 and V < ecm.V_min:
            self.cutoff = True
            current = 0.0
            V, eta, vd = self.step(ecm, 0.0, soc, T, dt)
        elif current < 0 and V > ecm.V_max:
            lo, hi = current, 0.0  # V(lo) > V_max >= V(hi) at rest
            if self.step(ecm, 0.0, soc, T, dt)[0] > ecm.V_max:
                lo = hi = 0.0
            for _ in range(50):
                mid = 0.5 * (lo + hi)
                if self.step(ecm, mid, soc, T, dt)[0] > ecm.V_max:
                    lo = mid
                else:
                    hi = mid
                if hi - lo < 1e-6:
                    break
            current = hi
            if abs(current) < ecm.cv_cutoff_A:
                self.charge_done = True
                current = 0.0
            V, eta, vd = self.step(ecm, current, soc, T, dt)
        self.eta_ct, self.V_d = eta, vd
        return current, V

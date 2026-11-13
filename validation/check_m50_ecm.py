"""Check the derived LG M50 circuit against the physics model it came from.

Runs PyBaMM's DFN (ORegan2022, lumped thermal, self-heating) on constant-current
discharges and a pulsed profile at 25, 10 and 0 degC, drives the packtherm
circuit (LG_M50_ECM) and the old lumped model (LG_M50_LUMPED) with the same
current along the DFN's temperature path, and compares irreversible heat.
Writes validation/m50_vs_dfn.csv. Requires `pip install pybamm`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pybamm

from packtherm.cells import LG_M50, LG_M50_LUMPED
from packtherm.ecm import ECMState

pybamm.set_logging_level("ERROR")
CAP = 5.0
CASES = {
    "0.5C": ["Discharge at 0.5C until 2.5 V"],
    "1C": ["Discharge at 1C until 2.5 V"],
    "1.4C": ["Discharge at 1.4C until 2.5 V"],
    "pulsed": [
        "Discharge at 1.4C for 60 seconds",
        "Rest for 30 seconds",
        "Discharge at 0.3C for 120 seconds",
        "Discharge at 1C for 90 seconds",
        "Rest for 60 seconds",
    ]
    * 12,
}


def dfn(T_C: float, steps: list[str]):
    p = pybamm.ParameterValues("ORegan2022")
    p.update({"Ambient temperature [K]": T_C + 273.15, "Initial temperature [K]": T_C + 273.15})
    model = pybamm.lithium_ion.DFN(options={"thermal": "lumped"})
    sol = pybamm.Simulation(model, parameter_values=p, experiment=pybamm.Experiment(steps, period="5 seconds")).solve(
        initial_soc=1.0
    )

    def g(k):
        return sol[k].entries

    return (
        g("Time [s]"),
        g("Current [A]"),
        g("Discharge capacity [A.h]"),
        g("Volume-averaged cell temperature [K]"),
        g("Total heating [W]") - g("Reversible heating [W]"),
    )


def main() -> pd.DataFrame:
    ecm, lumped = LG_M50.ecm, LG_M50_LUMPED
    rows = []
    for T_C in (25, 10, 0):
        for name, steps in CASES.items():
            t, I, Q, Tk, H_dfn = dfn(T_C, steps)
            st, soc, H_ecm = ECMState(), 1.0, []
            for k in range(1, t.size):
                dt = t[k] - t[k - 1]
                soc -= I[k] * dt / 3600 / CAP
                V, eta, vd = st.step(ecm, I[k], soc, Tk[k - 1], dt)
                st.eta_ct, st.V_d = eta, vd
                H_ecm.append(I[k] * (ecm.ocv(soc) - V))
            H_lump = [
                I[k] ** 2
                * lumped.R0_25C
                * np.exp(lumped.Ea_R / 8.314462618 * (1 / Tk[k - 1] - 1 / 298.15))
                * lumped.soc_factor(1 - Q[k] / CAP)
                for k in range(1, t.size)
            ]
            tt = t[1:]

            def E(h, tt=tt):
                return float(np.trapezoid(np.asarray(h), tt))

            e_dfn = E(H_dfn[1:])
            rows.append(
                {
                    "ambient_C": T_C,
                    "case": name,
                    "duration_min": t[-1] / 60,
                    "capacity_Ah": Q[-1],
                    "heat_dfn_Wh": e_dfn / 3600,
                    "ratio_circuit": E(H_ecm) / e_dfn,
                    "ratio_lumped": E(H_lump) / e_dfn,
                }
            )
            print(rows[-1])
    df = pd.DataFrame(rows)
    df.to_csv(Path(__file__).with_name("m50_vs_dfn.csv"), index=False)
    return df


if __name__ == "__main__":
    main()

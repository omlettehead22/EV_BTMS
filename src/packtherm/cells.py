"""Cell library: geometry, electrical and thermal parameters of real cells.

Every number carries a source. Where a value is an engineering assumption
rather than a measurement it is marked ``ASSUMPTION`` and is exposed as a
field so it can be overridden or swept.

Sources
-------
[ORegan2022]  K. O'Regan, F. Brosa Planella, W.D. Widanage, E. Kendrick,
              "Thermal-electrochemical parameters of a high energy lithium-ion
              cylindrical battery", Electrochimica Acta 425 (2022) 140700.
              Layer thermal properties and electrode entropic coefficients of
              the LG M50 (NMC811 / graphite-SiOx), as implemented in PyBaMM's
              ``ORegan2022`` parameter set.
[Chen2020]    C.-H. Chen et al., "Development of experimental techniques for
              parameterization of multi-scale lithium-ion battery models",
              J. Electrochem. Soc. 167 (2020) 080534. LG M50 electrode design.
[BD-M50]      batterydesign.net, "LG INR 21700 M50" (datasheet summary):
              5.0 Ah, 3.63 V, <=21.10 x 70.15 mm, 68 g, DCIR 30 +/- 6 mOhm
              (30 s, 0.5C), max charge 0.7C at 25-50 degC, max continuous
              discharge 1.5C at 5-60 degC.
[BD-MJ1]      batterydesign.net, "LG INR 18650 MJ1": NMC811 / graphite-Si,
              3.5 Ah, 46.8 g measured, DCIR 33 mOhm (summary) and 60 mOhm
              (Heenan et al., J. Electrochem. Soc. 167 (2020)), -20 to 60 degC.
[MJ1-DS]      LG Chem INR18650 MJ1 product specification: 3.635 V nominal,
              10 A max continuous discharge, approx. 18.3 x 65.1 mm.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from .ecm import ECM
from .params import KELVIN, Geometry, Material, Params

R_GAS = 8.314462618  # J/(mol K)
T_REF = 25.0 + KELVIN


# ---------------------------------------------------------------------------
# NMC811 / graphite-Si jelly-roll properties from [ORegan2022]
# ---------------------------------------------------------------------------


def nmc811_jellyroll_properties(T: float = T_REF) -> tuple[float, float, float]:
    """Stack-averaged (rho, cp, k_radial) of an NMC811/graphite-SiOx jelly roll.

    Builds one repeat unit of the wound stack (Cu foil | 2x anode | 2x
    separator | 2x cathode | Al foil) with LG M50 layer thicknesses [Chen2020]
    and wet-layer properties [ORegan2022]. Heat capacity is thickness-weighted;
    radial conductivity is the series (through-plane) combination, which is
    the relevant direction for a radial model.
    """
    rho_e, cp_e = 1280.0, 229.0  # electrolyte

    def wet(rho_dry, cp_dry, eps):
        rho = rho_dry + rho_e * eps
        return rho, (rho_dry * cp_dry + rho_e * cp_e * eps) / rho

    neg = wet(1740.0, 4.932e-4 * T**3 - 0.491 * T**2 + 169.4 * T - 1.897e4, 0.25)
    pos = wet(3270.0, -8.414e-4 * T**3 + 0.7892 * T**2 - 241.3 * T + 2.508e4, 0.335)
    sep = wet(946.0, 1.494e-3 * T**3 - 1.444 * T**2 + 475.5 * T - 5.13e4, 0.47)
    cu = (8933.0, 1.445e-6 * T**3 - 1.946e-3 * T**2 + 0.9633 * T + 236.0)
    al = (2702.0, 4.503e-6 * T**3 - 6.256e-3 * T**2 + 3.281 * T + 355.7)
    k = {
        "cu": -5.409e-7 * T**3 + 7.054e-4 * T**2 - 0.3727 * T + 463.6,
        "neg": -2.61e-4 * T**2 + 0.1726 * T - 24.49,
        "sep": 0.3344,
        "pos": 2.063e-5 * T**2 - 0.01127 * T + 2.331,
        "al": 237.0,
    }
    layers = {  # (thickness [m], (rho, cp))
        "cu": (12e-6, cu),
        "neg": (2 * 85.2e-6, neg),
        "sep": (2 * 12e-6, sep),
        "pos": (2 * 75.6e-6, pos),
        "al": (16e-6, al),
    }
    L = sum(th for th, _ in layers.values())
    rho = sum(th * p[0] for th, p in layers.values()) / L
    rho_cp = sum(th * p[0] * p[1] for th, p in layers.values()) / L
    k_radial = L / sum(th / k[name] for name, (th, _) in layers.items())
    return rho, rho_cp / rho, k_radial


def nmc811_jellyroll_k_axial(T: float = T_REF) -> float:
    """In-plane (axial) conductivity of the same repeat unit: layers in parallel [W/(m K)].

    The copper and aluminium foils dominate. This is the ideal value along the
    winding; how well the roll's ends couple to the can is a separate
    resistance (see ``packtherm.module.BottomPlate.R_end``).
    """
    k = {
        "cu": -5.409e-7 * T**3 + 7.054e-4 * T**2 - 0.3727 * T + 463.6,
        "neg": -2.61e-4 * T**2 + 0.1726 * T - 24.49,
        "sep": 0.3344,
        "pos": 2.063e-5 * T**2 - 0.01127 * T + 2.331,
        "al": 237.0,
    }
    th = {"cu": 12e-6, "neg": 2 * 85.2e-6, "sep": 2 * 12e-6, "pos": 2 * 75.6e-6, "al": 16e-6}
    return sum(th[n] * k[n] for n in th) / sum(th.values())


def nmc811_graphite_dUdT(soc: float) -> float:
    """Full-cell entropic coefficient dU/dT [V/K] versus state of charge.

    dU/dT = dU_pos/dT(y) - dU_neg/dT(x), electrode fits from [ORegan2022].
    Stoichiometry windows are derived from the LG M50 PyBaMM ``ORegan2022``
    set (100 % SOC: x = 0.976, y = 0.270; 5 Ah spans dx = 0.961, dy = 0.698).
    """
    soc = min(max(soc, 0.0), 1.0)
    x = 0.976 - 0.961 * (1.0 - soc)
    y = 0.270 + 0.698 * (1.0 - soc)
    dU_neg = (-0.1112 * x + 0.02914 + 0.3561 * math.exp(-((x - 0.08309) ** 2) / 0.004616)) / 1000.0
    dU_pos = (
        0.04006 * math.exp(-((y - 0.2828) ** 2) / 0.0009855) - 0.06656 * math.exp(-((y - 0.8032) ** 2) / 0.02179)
    ) / 1000.0
    return dU_pos - dU_neg


def default_soc_factor(soc: float) -> float:
    """ASSUMPTION: resistance multiplier vs SOC.

    Flat over the usable window, rising to ~1.6x at 0 % SOC. This mirrors the
    generic shape of HPPC resistance maps for NMC/graphite cells; replace it
    with a measured map when one is available.
    """
    return 1.0 + 0.6 * math.exp(-max(soc, 0.0) / 0.08)


# ---------------------------------------------------------------------------
# Cell definition
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Cell:
    name: str
    form_factor: str
    chemistry: str
    capacity_Ah: float
    V_nominal: float
    diameter: float  # m
    height: float  # m
    mass: float  # kg
    R0_25C: float  # Ohm, lumped DC resistance used for irreversible heat
    R0_range: tuple[float, float]  # Ohm, published spread, for sensitivity sweeps
    cp: float  # J/(kg K), jelly-roll average
    k_radial: float  # W/(m K)
    dUdT: Callable[[float], float] = field(repr=False, default=nmc811_graphite_dUdT)
    # ASSUMPTION: Arrhenius activation energy of the lumped resistance. 20 kJ/mol
    # roughly doubles R between 25 degC and 0 degC, typical of NMC/graphite DCIR.
    Ea_R: float = 20e3  # J/mol
    soc_factor: Callable[[float], float] = field(repr=False, default=default_soc_factor)
    max_charge_C: float | None = None
    max_discharge_C: float | None = None
    T_max_charge_C: float | None = None  # degC, datasheet upper limit while charging
    T_max_discharge_C: float | None = None
    sources: tuple[str, ...] = ()
    # Axial (along the winding) conductivity; defaults to the NMC811 jelly-roll value.
    k_axial: float = field(default_factory=lambda: nmc811_jellyroll_k_axial())
    # Optional equivalent-circuit model. When set, heat is I (OCV - V) from the
    # ECM (with voltage limits and CC-CV charging) instead of I^2 R0.
    ecm: ECM | None = None

    @property
    def radius(self) -> float:
        return self.diameter / 2

    @property
    def volume(self) -> float:
        return math.pi * self.radius**2 * self.height

    @property
    def density(self) -> float:
        """Bulk density from measured mass and can volume [kg/m^3]."""
        return self.mass / self.volume

    @property
    def material(self) -> Material:
        return Material(rho=self.density, cp=self.cp, k=self.k_radial)

    def resistance(self, soc: float, T: float) -> float:
        """Lumped resistance [Ohm] at state of charge and temperature [K]."""
        arrhenius = math.exp(self.Ea_R / R_GAS * (1.0 / T - 1.0 / T_REF))
        return self.R0_25C * arrhenius * self.soc_factor(soc)

    def current(self, c_rate: float) -> float:
        return c_rate * self.capacity_Ah


_RHO_JR, _CP_JR, _K_JR = nmc811_jellyroll_properties()

LG_M50 = Cell(
    name="LG INR21700 M50",
    form_factor="21700",
    chemistry="NMC811 / graphite-SiOx",
    capacity_Ah=5.0,
    V_nominal=3.63,
    diameter=21.10e-3,
    height=70.15e-3,
    mass=0.068,
    R0_25C=0.030,
    R0_range=(0.024, 0.036),
    cp=_CP_JR,
    k_radial=_K_JR,
    max_charge_C=0.7,
    max_discharge_C=1.5,
    T_max_charge_C=50.0,
    T_max_discharge_C=60.0,
    sources=("BD-M50", "ORegan2022", "Chen2020"),
)

LG_MJ1 = Cell(
    name="LG INR18650 MJ1",
    form_factor="18650",
    chemistry="NMC811 / graphite-Si",
    capacity_Ah=3.5,
    V_nominal=3.635,
    diameter=18.3e-3,
    height=65.1e-3,
    mass=0.0468,
    # Conservative choice: the measured 60 mOhm (Heenan 2020) rather than the
    # 33 mOhm summary value; both bound R0_range.
    R0_25C=0.060,
    R0_range=(0.033, 0.060),
    # Same chemistry family as the M50; jelly-roll properties reused (ASSUMPTION).
    cp=_CP_JR,
    k_radial=_K_JR,
    max_charge_C=None,
    max_discharge_C=10.0 / 3.5,
    T_max_charge_C=None,
    T_max_discharge_C=60.0,
    sources=("BD-MJ1", "MJ1-DS", "ORegan2022"),
)

CELLS: dict[str, Cell] = {"M50": LG_M50, "MJ1": LG_MJ1}


def get_cell(key: str) -> Cell:
    try:
        return CELLS[key.upper()]
    except KeyError:
        raise KeyError(f"Unknown cell '{key}'. Available: {', '.join(CELLS)}") from None


def params_for_cell(
    cell: Cell,
    pcm_thickness: float = 3e-3,
    case_thickness: float = 1e-3,
    base: Params | None = None,
    dr_target: float = 1e-4,
) -> Params:
    """Model parameters for ``cell`` wrapped in PCM and a casing.

    pcm_thickness may be 0 (no PCM). The radial mesh keeps a ~0.1 mm spacing,
    which the thesis mesh study showed is converged to < 0.001 degC.
    """
    base = base or Params()
    r_cell = cell.radius
    r_pcm = r_cell + pcm_thickness
    r_case = r_pcm + case_thickness
    n = max(3, int(np.ceil(r_case / dr_target)))
    geom = Geometry(r_cell=r_cell, r_pcm=r_pcm, r_case=r_case, length=cell.height, n_cells=n)
    return base.with_(geometry=geom, cell=cell.material)


# ---------------------------------------------------------------------------
# Panasonic NCR18650PF: identified from the Kollmeyer test dataset
# ---------------------------------------------------------------------------


def _load_ocv_table(name: str) -> tuple[tuple[float, ...], tuple[float, ...]]:
    from importlib import resources

    text = resources.files("packtherm").joinpath(f"data/{name}").read_text()
    rows = [line.split(",") for line in text.splitlines() if line and not line.startswith(("#", "soc"))]
    soc, ocv = zip(*((float(a), float(b)) for a, b in rows))
    return soc, ocv


def _zero_dUdT(soc: float) -> float:
    return 0.0


_PF_SOC, _PF_OCV = _load_ocv_table("ncr18650pf_ocv.csv")

# Electrical model identified from the dataset's own characterisation tests
# (see validation/identify_panasonic.py):
#   OCV: 25 degC C/20 discharge/charge.
#   R0, I0, Ea_I0, gamma: 10 s overpotential of every HPPC pulse at 20-95 % SOC
#       at 25, 10, 0, -10, -20 degC (median error 5-11 % per temperature).
#   soc_a, soc_b: low-SOC rise of the same pulse overpotentials (all temperatures).
#   tau_ct: median fitted pulse time constant at 25 degC.
#   Rd, tau_d: slow branch fitted to the voltage of the 25 degC 1C calibration
#       discharge (the only test used for calibration).
NCR18650PF_ECM = ECM(
    ocv_soc=_PF_SOC,
    ocv_V=_PF_OCV,
    R0_25C=0.0260,
    Ea_R0=0.0,
    I0_25C=15.61,
    Ea_I0=45.2e3,
    gamma=8.69,
    tau_ct=4.0,
    Rd_25C=0.0284,  # calibrated on the 25 degC 1C discharge #1 voltage (v0.4.10 re-fit)
    tau_d=405.0,
    V_max=4.2,
    V_min=2.5,
    cv_cutoff_A=0.05,
    soc_a=10.18,
    soc_b=0.0801,
    # v0.4.10: temperature laws from the 0.9 A discharge-and-rest steps between
    # the HPPC pulse sets at 25, 10, 0 and -10 degC (identification data, not
    # in the validation set): the low-SOC rise grows in the cold (20.7 kJ/mol)
    # and the slow branch follows its own, gentler Arrhenius law (26.8 kJ/mol)
    # instead of the charge-transfer kinetics (45 kJ/mol). Rd_25C and tau_d
    # re-calibrated on the same single test with these laws.
    Ea_Rd=26.8e3,
    Ea_soc=20.7e3,
    sources=("Kollmeyer2018",),
)

PANASONIC_NCR18650PF = Cell(
    name="Panasonic NCR18650PF",
    form_factor="18650",
    chemistry="NCA / graphite",
    capacity_Ah=2.99491,  # C/20 at 25 degC, this dataset's cell
    V_nominal=3.6,
    diameter=18.5e-3,  # with tube (datasheet max); the thermocouple sits on the tube
    height=65.3e-3,
    mass=0.047,  # datasheet: 47.0 g max without tube, 48.0 g max with tube
    R0_25C=0.046,  # 10 s DC resistance at 1-2C, mid SOC, from the HPPC data
    R0_range=(0.043, 0.052),
    # ASSUMPTION: NMC811-family jelly-roll properties reused for NCA/graphite.
    cp=_CP_JR,
    k_radial=_K_JR,
    # ASSUMPTION: entropic heat neglected (no NCA dU/dT data in this dataset).
    dUdT=_zero_dUdT,
    max_charge_C=0.5,  # datasheet standard charge 0.5C (1375 mA)
    max_discharge_C=10.0 / 2.9,  # 10 A
    T_max_charge_C=45.0,
    T_max_discharge_C=60.0,
    sources=("Kollmeyer2018", "NCR18650PF datasheet"),
    ecm=NCR18650PF_ECM,
)

CELLS["PF"] = PANASONIC_NCR18650PF

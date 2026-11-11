"""Model parameters.

Defaults mirror ``matlab/params_materials.m`` exactly so that the Python
solver reproduces the thesis results. All temperatures are in kelvin and all
quantities are SI unless a name says otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

KELVIN = 273.15


@dataclass(frozen=True)
class Material:
    """Constant-property solid."""

    rho: float  # kg/m^3
    cp: float  # J/(kg K)
    k: float  # W/(m K)


@dataclass(frozen=True)
class PCM:
    """Phase-change material modelled with an apparent heat capacity."""

    rho: float = 830.0  # kg/m^3
    cp_solid: float = 2000.0  # J/(kg K)
    cp_liquid: float = 2300.0  # J/(kg K)
    k: float = 0.2  # W/(m K)
    T_solidus: float = 29.0 + KELVIN  # K, start of melting
    T_liquidus: float = 34.0 + KELVIN  # K, end of melting
    latent_heat: float = 160e3  # J/kg

    def __post_init__(self) -> None:
        if self.T_liquidus <= self.T_solidus:
            raise ValueError("PCM liquidus must be above solidus.")

    @property
    def melt_range(self) -> float:
        return self.T_liquidus - self.T_solidus

    @property
    def cp_mushy(self) -> float:
        """Apparent heat capacity inside the melting range [J/(kg K)]."""
        return 0.5 * (self.cp_solid + self.cp_liquid) + self.latent_heat / self.melt_range


@dataclass(frozen=True)
class Geometry:
    """Radial line from cell centre through PCM to casing outer wall."""

    r_cell: float = 0.009  # m, cell outer radius (18650-type)
    r_pcm: float = 0.012  # m, PCM outer radius (3 mm layer)
    r_case: float = 0.013  # m, casing outer radius (1 mm wall)
    length: float = 0.065  # m, axial length
    n_cells: int = 130  # radial control volumes

    def __post_init__(self) -> None:
        if not (0 < self.r_cell <= self.r_pcm <= self.r_case):
            raise ValueError("Require 0 < r_cell <= r_pcm <= r_case.")
        if self.n_cells < 3:
            raise ValueError("n_cells must be >= 3.")

    @property
    def pcm_thickness(self) -> float:
        return self.r_pcm - self.r_cell

    @property
    def case_thickness(self) -> float:
        return self.r_case - self.r_pcm


# Convective coefficients [W/(m^2 K)] and assumed pack-level auxiliary power [W]
# for each cooling level, from params_materials.m.
DEFAULT_H = {
    "air": {"low": 10.0, "mid": 30.0, "high": 60.0},
    "liquid": {"low": 100.0, "mid": 300.0, "high": 600.0},
    "none": {"low": 0.0, "mid": 0.0, "high": 0.0},
}
DEFAULT_AUX_POWER = {
    "air": {"low": 10.0, "mid": 20.0, "high": 40.0},
    "liquid": {"low": 10.0, "mid": 40.0, "high": 80.0},
    "none": {"low": 0.0, "mid": 0.0, "high": 0.0},
}


@dataclass(frozen=True)
class SolverSettings:
    """Time stepping and PCM nonlinear iteration.

    scheme:
      "enthalpy" (default) - Newton iteration on the enthalpy-form residual.
          Energy is conserved to machine precision and it converges in ~2
          iterations per step, including when a node sits on the solidus or
          liquidus kink.
      "thesis" - the original MATLAB scheme: under-relaxed Picard iteration
          on the apparent heat capacity. Kept for bit-for-bit parity with the
          thesis results; a few melt-front steps can hit max_iterations.
    """

    dt: float = 0.5  # s
    tolerance: float = 1e-7  # K, max temperature update for convergence
    max_iterations: int = 30
    relaxation: float = 0.7  # thesis scheme only
    scheme: str = "enthalpy"

    def __post_init__(self) -> None:
        if self.scheme not in ("enthalpy", "thesis"):
            raise ValueError("scheme must be 'enthalpy' or 'thesis'")


@dataclass(frozen=True)
class Params:
    geometry: Geometry = field(default_factory=Geometry)
    cell: Material = field(default_factory=lambda: Material(rho=2500.0, cp=1040.0, k=0.9))
    pcm: PCM = field(default_factory=PCM)
    case: Material = field(default_factory=lambda: Material(rho=2700.0, cp=900.0, k=170.0))
    solver: SolverSettings = field(default_factory=SolverSettings)
    T_initial: float = 25.0 + KELVIN
    T_ambient_mild: float = 25.0 + KELVIN
    T_ambient_warm: float = 30.0 + KELVIN
    T_coolant: float = 25.0 + KELVIN
    t_end_drive: float = 600.0  # s
    t_end_charge: float = 3600.0  # s

    def with_(self, **changes) -> Params:
        """Return a copy with top-level fields replaced."""
        return replace(self, **changes)


def default_params() -> Params:
    return Params()

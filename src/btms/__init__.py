"""btms: battery thermal management design toolkit."""

from .cells import CELLS, LG_M50, LG_MJ1, PANASONIC_NCR18650PF, Cell, get_cell, params_for_cell
from .ecm import ECM
from .electrothermal import (
    ElectroThermalLoad,
    MeasuredHeatLoad,
    check_limits,
    constant_current,
    from_csv,
    segments,
    simulate_cell,
)
from .materials import PCM_LIBRARY, get_pcm
from .model import SimulationResult, simulate
from .params import KELVIN, PCM, Geometry, Material, Params, SolverSettings, default_params
from .scenarios import Scenario, run_scenario, thesis_scenarios

__version__ = "0.3.2"

__all__ = [
    "CELLS",
    "ECM",
    "KELVIN",
    "LG_M50",
    "LG_MJ1",
    "PANASONIC_NCR18650PF",
    "PCM",
    "PCM_LIBRARY",
    "Cell",
    "ElectroThermalLoad",
    "Geometry",
    "Material",
    "MeasuredHeatLoad",
    "Params",
    "Scenario",
    "SimulationResult",
    "SolverSettings",
    "check_limits",
    "constant_current",
    "default_params",
    "from_csv",
    "get_cell",
    "get_pcm",
    "params_for_cell",
    "run_scenario",
    "segments",
    "simulate",
    "simulate_cell",
    "thesis_scenarios",
]

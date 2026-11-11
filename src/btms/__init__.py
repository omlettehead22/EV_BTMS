"""btms: battery thermal management design toolkit."""

from .cells import CELLS, LG_M50, LG_MJ1, Cell, get_cell, params_for_cell
from .electrothermal import ElectroThermalLoad, check_limits, constant_current, from_csv, segments, simulate_cell
from .model import SimulationResult, simulate
from .params import KELVIN, PCM, Geometry, Material, Params, SolverSettings, default_params
from .scenarios import Scenario, run_scenario, thesis_scenarios

__version__ = "0.2.0"

__all__ = [
    "CELLS",
    "KELVIN",
    "LG_M50",
    "LG_MJ1",
    "PCM",
    "Cell",
    "ElectroThermalLoad",
    "Geometry",
    "Material",
    "Params",
    "Scenario",
    "SimulationResult",
    "SolverSettings",
    "check_limits",
    "constant_current",
    "default_params",
    "from_csv",
    "get_cell",
    "params_for_cell",
    "run_scenario",
    "segments",
    "simulate",
    "simulate_cell",
    "thesis_scenarios",
]

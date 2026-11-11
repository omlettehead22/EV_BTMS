"""btms: battery thermal management design toolkit."""

from .model import SimulationResult, simulate
from .params import KELVIN, PCM, Geometry, Material, Params, default_params
from .scenarios import Scenario, run_scenario, thesis_scenarios

__version__ = "0.1.0"

__all__ = [
    "KELVIN",
    "PCM",
    "Geometry",
    "Material",
    "Params",
    "Scenario",
    "SimulationResult",
    "default_params",
    "run_scenario",
    "simulate",
    "thesis_scenarios",
]

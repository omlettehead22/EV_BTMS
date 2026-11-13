"""PackTherm: battery thermal management design toolkit for cylindrical-cell EV packs."""

from .cells import (
    CELLS,
    LG_M50,
    LG_M50_LUMPED,
    LG_MJ1,
    PANASONIC_NCR18650PF,
    Cell,
    get_cell,
    params_for_cell,
    with_R0,
)
from .design import DutyCycle, Requirements
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
from .hardware import PackHardware, hardware_mass_per_cell
from .materials import PCM_LIBRARY, get_pcm
from .model import SimulationResult, Sink, simulate
from .module import (
    AirFlow,
    BottomPlate,
    Chiller,
    Coolant,
    Interface,
    Layout,
    Module,
    PlateGeometry,
    RibbonGeometry,
    SideRibbon,
    Wall,
    compare_modules,
    simulate_module,
)
from .module_design import ModuleDesign, ModuleStudy, run_module_study
from .params import KELVIN, PCM, Geometry, Material, Params, SolverSettings, default_params
from .scenarios import Scenario, run_scenario, thesis_scenarios

__version__ = "0.5.1"

__all__ = [
    "CELLS",
    "ECM",
    "KELVIN",
    "LG_M50",
    "LG_M50_LUMPED",
    "LG_MJ1",
    "PANASONIC_NCR18650PF",
    "PCM",
    "PCM_LIBRARY",
    "AirFlow",
    "BottomPlate",
    "Cell",
    "Chiller",
    "Coolant",
    "DutyCycle",
    "ElectroThermalLoad",
    "Geometry",
    "Interface",
    "Layout",
    "Material",
    "MeasuredHeatLoad",
    "Module",
    "ModuleDesign",
    "ModuleStudy",
    "PackHardware",
    "Params",
    "PlateGeometry",
    "Requirements",
    "RibbonGeometry",
    "Scenario",
    "SideRibbon",
    "SimulationResult",
    "Sink",
    "SolverSettings",
    "Wall",
    "check_limits",
    "compare_modules",
    "constant_current",
    "default_params",
    "from_csv",
    "get_cell",
    "get_pcm",
    "hardware_mass_per_cell",
    "params_for_cell",
    "run_module_study",
    "run_scenario",
    "segments",
    "simulate",
    "simulate_cell",
    "simulate_module",
    "thesis_scenarios",
    "with_R0",
]

import math
from dataclasses import replace

import numpy as np
import pytest

from packtherm.cells import LG_M50
from packtherm.electrothermal import constant_current
from packtherm.hardware import RHO_AL, PackHardware, hardware_mass_per_cell
from packtherm.materials import get_pcm
from packtherm.module import (
    AirFlow,
    BottomPlate,
    Layout,
    Module,
    PlateGeometry,
    RibbonGeometry,
    SideRibbon,
    module_mass_per_cell_kg,
    simulate_module,
)
from packtherm.params import KELVIN

CELL = LG_M50
N_CELLS = 60e3 / (CELL.capacity_Ah * CELL.V_nominal)


def test_cold_plate_by_hand():
    m = Module(Layout("hex", 2.0), None, BottomPlate())
    parts = hardware_mass_per_cell(CELL, m)
    p = CELL.diameter + 2e-3
    A = math.sqrt(3) / 2 * p * p
    assert parts["aluminium"] == pytest.approx(RHO_AL * A * (1.5 + 1.0 * 1.1) * 1e-3)
    assert parts["coolant"] == pytest.approx(1060 * A * 0.5 * 4e-3)
    assert parts["interface"] == pytest.approx(2000 * A * 0.5e-3)
    assert parts["pack_share"] == pytest.approx(3.0 / N_CELLS)
    assert parts["total"] == pytest.approx(sum(v for k, v in parts.items() if k != "total"))
    # Thicker sheets, heavier plate.
    heavy = Module(m.layout, None, BottomPlate(plate=PlateGeometry(base_mm=3.0)))
    assert hardware_mass_per_cell(CELL, heavy)["aluminium"] > parts["aluminium"]


def test_ribbon_by_hand():
    rib = SideRibbon()
    m = Module(Layout("hex", rib.min_gap_mm), None, rib)
    parts = hardware_mass_per_cell(CELL, m)
    g = rib.tube
    h = 0.75 * CELL.height
    n_ribs = math.floor(h / 2.5e-3) - 1
    a_al = 2 * (h + 2.5e-3) * 0.4e-3 + n_ribs * (2.5e-3 - 0.8e-3) * 0.35e-3
    length = (CELL.diameter + 3.5e-3) * 1.1 / 2
    assert parts["aluminium"] == pytest.approx(RHO_AL * a_al * length)
    assert parts["coolant"] == pytest.approx(1060 * (h * 2.5e-3 - a_al) * length)
    bond = 0.25 * 2 * math.pi * CELL.radius * h * 0.5e-3
    assert parts["interface"] == pytest.approx(2000 * bond)
    # The ribbon sits in the gap, so a PCM filler gets less volume.
    filled = Module(m.layout, "RT31", rib)
    plain = Module(m.layout, "RT31", BottomPlate())
    tube_vol = g.thickness_mm * 1e-3 * h * length + bond
    assert module_mass_per_cell_kg(CELL, plain) - module_mass_per_cell_kg(CELL, filled) == pytest.approx(
        get_pcm("RT31").rho * tube_vol, rel=1e-9
    )


def test_pack_level_parts():
    air = hardware_mass_per_cell(CELL, Module(Layout(), None, AirFlow()))
    assert air["aluminium"] == air["coolant"] == 0.0
    assert air["total"] == pytest.approx(4.0 / N_CELLS)
    sealed = hardware_mass_per_cell(CELL, Module(Layout(), "RT31", None))
    assert sealed["total"] == 0.0
    m = Module(Layout(), None, BottomPlate())
    plain, chilled = hardware_mass_per_cell(CELL, m), hardware_mass_per_cell(CELL, m, chilled=True)
    assert chilled["total"] - plain["total"] == pytest.approx(4.0 / N_CELLS)
    # A bigger pack spreads the same parts over more cells.
    big = hardware_mass_per_cell(CELL, m, PackHardware(pack_kWh=120.0))
    assert big["pack_share"] == pytest.approx(plain["pack_share"] / 2)


def test_liquid_hardware_in_published_range():
    """Module cooling hardware alone should sit below whole-system figures
    (0.5-5 kg/kWh including radiator, compressor and structure)."""
    kWh = CELL.capacity_Ah * CELL.V_nominal / 1e3
    for cooling in (BottomPlate(), SideRibbon()):
        gap = cooling.min_gap_mm if isinstance(cooling, SideRibbon) else 2.0
        kg_per_kWh = hardware_mass_per_cell(CELL, Module(Layout("hex", gap), None, cooling))["total"] / kWh
        assert 0.1 < kg_per_kWh < 0.5


def test_ribbon_height_sets_contact():
    """Quasi-steady at the inlet: can-surface rise over coolant = Q / G, G ~ height fraction."""
    flat = replace(CELL, Ea_R=0.0, soc_factor=lambda soc: 1.0)
    prof = constant_current(flat, 1.0)
    rises = []
    for hf in (1.0, 0.5):
        rib = SideRibbon(tube=RibbonGeometry(height_fraction=hf))
        r = simulate_module(
            flat, Module(Layout("hex", 3.5), None, rib), prof, 3000, 25.0, position="inlet", entropic=False
        )
        i = np.searchsorted(r.res.t, 2700)
        rises.append(r.res.T_surface[i] - (25.0 + KELVIN))
    assert rises[1] / rises[0] == pytest.approx(2.0, rel=0.05)


def test_geometry_checks():
    with pytest.raises(ValueError):
        RibbonGeometry(height_fraction=0.0)
    with pytest.raises(ValueError):
        RibbonGeometry(thickness_mm=0.5, wall_mm=0.4)

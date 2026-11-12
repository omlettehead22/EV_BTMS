"""Cooling hardware mass per cell, from geometry.

v0.4.1 charged cooling hardware as a flat kg per kWh. Once pump energy became
physical (milliwatts per cell), that guess decided most picks, so this module
builds the mass up from the parts instead:

* **cold plate** (``BottomPlate.plate``): base and channel sheets over the
  cell's footprint, the coolant inside, and the thermal interface (gap filler)
  under the cell;
* **side ribbon** (``SideRibbon.tube``): the cell's share of the extruded
  tube (walls and internal ribs), the coolant inside, and the bond between the
  tube and the can;
* **pack-level parts** shared by every cell (:class:`PackHardware`): the
  liquid loop (pump, manifolds, hoses), the air system (fan, plenum, ducts) or
  the chiller, divided by the number of cells in the pack.

Every dimension is a labelled default with its source or assumption, and every
one can be overridden.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .cells import Cell
from .module import AirFlow, BottomPlate, Module, SideRibbon

RHO_AL = 2700.0  # kg/m^3, 3003 / 6063 aluminium


@dataclass(frozen=True)
class PackHardware:
    """Parts shared across the pack, charged per cell.

    ASSUMPTIONS (no single public teardown gives these for a generic pack):
    * liquid loop, 3 kg: electric coolant pump, inlet/outlet manifolds, hoses
      and the coolant outside the module channels;
    * air system, 4 kg: fan, plenum and ducting;
    * chiller, 4 kg: the battery chiller heat exchanger, expansion valve and
      refrigerant lines. The compressor is shared with cabin air conditioning
      and is not charged to the battery. For scale, a complete integrated
      refrigerant module including the compressor weighs 16 kg (Hanon, BMW iX3).

    The radiator is shared with the drive unit and is not charged either.
    """

    pack_kWh: float = 60.0
    liquid_loop_kg: float = 3.0
    air_system_kg: float = 4.0
    chiller_kg: float = 4.0

    def cells(self, cell: Cell) -> float:
        return self.pack_kWh * 1e3 / (cell.capacity_Ah * cell.V_nominal)


def _plate_parts(cell: Cell, module: Module, c: BottomPlate) -> dict[str, float]:
    A = module.layout.area_per_cell(cell)  # footprint per cell, m^2
    g = c.plate
    v_al = A * (g.base_mm + g.channel_sheet_mm * g.forming_factor) * 1e-3
    v_cool = A * g.channel_coverage * g.channel_height_mm * 1e-3
    v_tim = A * c.tim.bond_line_mm * 1e-3
    return {"aluminium": RHO_AL * v_al, "coolant": c.coolant.rho * v_cool, "interface": c.tim.rho * v_tim}


def _ribbon_parts(cell: Cell, module: Module, c: SideRibbon) -> dict[str, float]:
    g = c.tube
    h = g.height_fraction * cell.height  # m
    t, w = g.thickness_mm * 1e-3, g.wall_mm * 1e-3
    n_ribs = max(0, math.floor(h / (g.rib_pitch_mm * 1e-3)) - 1)
    a_al = 2.0 * (h + t) * w + n_ribs * (t - 2.0 * w) * g.rib_mm * 1e-3  # cross-section, m^2
    a_cool = h * t - a_al
    length = module.layout.pitch(cell) * g.weave_factor / g.rows_per_ribbon  # tube length per cell, m
    bond_area = c.contact_fraction * 2.0 * math.pi * cell.radius * h
    return {
        "aluminium": RHO_AL * a_al * length,
        "coolant": c.coolant.rho * a_cool * length,
        "interface": c.tim.rho * bond_area * c.tim.bond_line_mm * 1e-3,
    }


def hardware_mass_per_cell(cell: Cell, module: Module, pack: PackHardware | None = None, chilled: bool = False) -> dict:
    """Cooling hardware per cell [kg], by part. ``total`` is the sum."""
    pack = pack or PackHardware()
    c = module.cooling
    parts = {"aluminium": 0.0, "coolant": 0.0, "interface": 0.0, "pack_share": 0.0}
    n = pack.cells(cell)
    if isinstance(c, BottomPlate):
        parts.update(_plate_parts(cell, module, c))
        parts["pack_share"] = pack.liquid_loop_kg / n
    elif isinstance(c, SideRibbon):
        parts.update(_ribbon_parts(cell, module, c))
        parts["pack_share"] = pack.liquid_loop_kg / n
    elif isinstance(c, AirFlow):
        parts["pack_share"] = pack.air_system_kg / n
    if chilled:
        parts["pack_share"] += pack.chiller_kg / n
    parts["total"] = sum(parts.values())
    return parts


__all__ = ["RHO_AL", "PackHardware", "hardware_mass_per_cell"]

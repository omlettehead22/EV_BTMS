"""Volumetric heat-generation profiles [W/m^3] inside the cell region."""

from __future__ import annotations


def qgen_drive(t: float) -> float:
    """Stepped drive-cycle heat load (~0.5-1.7 W per 18650 cell)."""
    if t < 100:
        return 3e4
    if t < 300:
        return 1.0e5
    return 6e4


def qgen_charge(t: float) -> float:
    """Constant fast-charge load, calibrated to ~94 kW/m^3 (3C, NCR18650PF)."""
    return 9.4e4


PROFILES = {"drive": qgen_drive, "charge": qgen_charge}

"""PCM library for design studies.

Each grade lists its source. Where a datasheet value is missing, the RT31
thesis value is reused and marked ASSUMPTION. The model uses one density, so
where solid and liquid densities are given their mean is taken.

Sources
-------
[thesis]     RT31 values from the MSc thesis (``matlab/params_materials.m``).
[Rolka2022]  P. Rolka et al., "Thermal properties of RT22 HC and RT28 HC phase
             change materials...", Renewable Energy 197 (2022) 462-471:
             RT28HC latent heat 244 kJ/kg (measured), main peak 27-28 degC,
             conductivity 0.12-0.33 W/mK.
[PLUSS-OM35] PLUSS savE OM35 technical data sheet: melting 35 degC, latent
             171 kJ/kg (30-40 degC), density 900 solid / 870 liquid kg/m3,
             cp 2.57 / 2.78 kJ/kgK, k 0.2 solid / 0.16 liquid W/mK.
[Yu2023]     Y. Yu et al., "A Low-Density Polyethylene-Reinforced Ternary
             Phase-Change Composite with High Thermal Conductivity for Battery
             Thermal Management", Energies 16 (2023) 3838: paraffin with
             10 wt% expanded graphite and 4 wt% LDPE reaches 172 J/g latent
             heat and 3.85 W/mK.
[RT42-DS]    Rubitherm RT42 data sheet: melting area 38-43 degC, heat storage
             capacity 174 kJ/kg, density 0.97 solid / 0.75 liquid kg/l,
             k 0.2 W/mK.
"""

from __future__ import annotations

from .params import KELVIN, PCM

PCM_LIBRARY: dict[str, PCM] = {
    # ASSUMPTION: density (paraffin mean ~825) and cp reused from RT31.
    "RT28HC": PCM(
        rho=825.0,
        cp_solid=2000.0,
        cp_liquid=2300.0,
        k=0.2,
        T_solidus=27.0 + KELVIN,
        T_liquidus=29.0 + KELVIN,
        latent_heat=244e3,
    ),
    "RT31": PCM(),  # thesis baseline: 29-34 degC, 160 kJ/kg
    # ASSUMPTION: a 4 K melting window centred on the 35 degC transition.
    "OM35": PCM(
        rho=885.0,
        cp_solid=2570.0,
        cp_liquid=2780.0,
        k=0.18,
        T_solidus=33.0 + KELVIN,
        T_liquidus=37.0 + KELVIN,
        latent_heat=171e3,
    ),
    # ASSUMPTION: cp reused from RT31.
    "RT42": PCM(
        rho=860.0,
        cp_solid=2000.0,
        cp_liquid=2300.0,
        k=0.2,
        T_solidus=38.0 + KELVIN,
        T_liquidus=43.0 + KELVIN,
        latent_heat=174e3,
    ),
}

PCM_SOURCES = {"RT28HC": "Rolka2022", "RT31": "thesis", "OM35": "PLUSS-OM35", "RT42": "RT42-DS"}

EG_CP = 710.0  # J/(kg K), graphite


def composite_pcm(base: PCM, k: float = 3.85, paraffin_mass_fraction: float = 0.86) -> PCM:
    """Paraffin / expanded-graphite composite built on a base grade.

    Defaults follow [Yu2023]: 14 wt% additives (10 % EG, 4 % LDPE) give
    k = 3.85 W/mK. Latent heat and heat capacity scale with the paraffin mass
    fraction (rule of mixtures). ASSUMPTION: density unchanged from the base
    grade and the same melting window.
    """
    if not 0 < paraffin_mass_fraction <= 1:
        raise ValueError("paraffin_mass_fraction must be in (0, 1].")
    f = paraffin_mass_fraction
    return PCM(
        rho=base.rho,
        cp_solid=f * base.cp_solid + (1 - f) * EG_CP,
        cp_liquid=f * base.cp_liquid + (1 - f) * EG_CP,
        k=k,
        T_solidus=base.T_solidus,
        T_liquidus=base.T_liquidus,
        latent_heat=f * base.latent_heat,
    )


# Composite (expanded-graphite) versions of every grade: "<grade>-EG".
for _name in list(PCM_LIBRARY):
    PCM_LIBRARY[f"{_name}-EG"] = composite_pcm(PCM_LIBRARY[_name])
    PCM_SOURCES[f"{_name}-EG"] = f"{PCM_SOURCES[_name]} + Yu2023"


def get_pcm(name: str) -> PCM:
    try:
        return PCM_LIBRARY[name]
    except KeyError:
        raise KeyError(f"Unknown PCM '{name}'. Available: {', '.join(PCM_LIBRARY)}") from None


def melt_midpoint_C(pcm: PCM) -> float:
    return 0.5 * (pcm.T_solidus + pcm.T_liquidus) - KELVIN

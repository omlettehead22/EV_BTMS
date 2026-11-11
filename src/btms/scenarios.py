"""Named thesis scenarios (port of define_scenarios.m / run_all_scenarios.m)."""

from __future__ import annotations

from dataclasses import dataclass

from .heat import PROFILES
from .model import SimulationResult, simulate
from .params import DEFAULT_AUX_POWER, DEFAULT_H, Params


@dataclass(frozen=True)
class Scenario:
    name: str
    event: str  # "drive" | "charge"
    cooling: str  # "air" | "liquid" | "none"
    level: str  # "low" | "mid" | "high"
    T_env: float  # K

    def h(self) -> float:
        return DEFAULT_H[self.cooling][self.level]

    def aux_power(self) -> float:
        return DEFAULT_AUX_POWER[self.cooling][self.level]

    def duration(self, P: Params) -> float:
        return {"drive": P.t_end_drive, "charge": P.t_end_charge}[self.event]


def thesis_scenarios(P: Params) -> list[Scenario]:
    return [
        Scenario("drive-air-mid", "drive", "air", "mid", P.T_ambient_mild),
        Scenario("drive-liquid-low", "drive", "liquid", "low", P.T_coolant),
        Scenario("charge-air-high", "charge", "air", "high", P.T_ambient_mild),
        Scenario("charge-liquid-mid", "charge", "liquid", "mid", P.T_coolant),
    ]


def run_scenario(P: Params, sc: Scenario, duration: float | None = None, heat_source=None) -> SimulationResult:
    return simulate(
        P,
        heat_source=heat_source or PROFILES[sc.event],
        duration=duration if duration is not None else sc.duration(P),
        h=sc.h(),
        T_env=sc.T_env,
    )

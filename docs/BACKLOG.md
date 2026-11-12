# Known issues and improvement backlog

A review of the model and advisor as of v0.3.1, ranked by how much each item could change a design recommendation. "Fixed" items were found in this review and resolved in v0.3.1.

## Fixed in v0.3.1
| Issue | Effect before the fix |
|---|---|
| Fan/pump energy counted only during the event, while recovery assumed the cooling kept running | Slow-recovering designs looked cheaper than they are |
| Design studies never checked the datasheet C-rate limit | A 2.5C study on a 1.5C cell gave no warning |
| Robustness check did nothing when nominal resistance was already the published maximum (MJ1) | No margin for ageing or cell spread |
| If every front design failed the robustness check, the advisor still picked a fragile one | Recommendation could fail on a high-resistance cell |
| Full temperature history stored every step | Memory grew with run length (~26 MB per 2 h run) |
| Sink temperature tied to initial temperature | A chiller could not be modelled |

## Model fidelity (largest effect on recommendations)
1. **Isolated-cell assumption.** Each cell gets a uniform h around its whole circumference, and natural convection treats it as alone in free air. In a module, neighbouring cells block most of that path, and a cold plate touches only part of each can. Natural-cooling and liquid-cooling results are both optimistic. **Fix in v0.4:** a module unit cell (square/hex packing, contact fraction to the plate, coolant temperature rise along the plate).
2. **PCM as a per-cell sleeve inside a 1 mm Al tube.** The sleeve alone adds about 19 % of cell mass, and packs are not built this way. Real PCM packs use a matrix between cells, often expanded-graphite composite with k of 3–10 W/m·K rather than 0.2. **Fix:** composite-PCM grades and module-level PCM geometry (v0.4).
3. **Lumped DC resistance.** The 30 s DCIR understates heat under sustained load, because polarisation builds up. **Fix:** a 1–2 RC equivalent circuit, **validated against the open Warwick LG M50 dataset** (CC/CV cycling at C/10–1.5C with cell-surface temperatures).
4. **Charging has no CV taper**, and capacity doesn't depend on temperature. Rapid-charge heat is slightly overstated near the end of charge, and cold-weather capacity is overstated.
5. **1D radial model only.** There are no axial gradients and no tab/base cooling. Bottom cooling of cylindrical cells is common in production packs.
6. **Fan-law anchors are the thesis estimates**, and the h^3.75 law assumes turbulent flow. Laminar cold-plate channels behave differently, where h is set by geometry more than flow. Needs a cold-plate design reference.
7. **The chiller has a fixed COP** and ignores ambient heat leaking into the chilled loop.

## Advisor and product
8. **Ageing as a third objective.** Temperature drives calendar and cycle ageing. Scoring designs on predicted capacity fade (Arrhenius ageing) would show what "hotter but lighter" costs in battery life. This is probably the highest-value product feature.
9. **Cost objective (£/pack):** PCM £/kg, cooling hardware £/kWh, chiller.
10. **Cold climate:** pre-heating energy and cold-start limits, not just cooling.
11. **Speed.** Each run takes about 0.5 s in a Python time loop. Batching all designs into one vectorised solve (or using Numba) would give an estimated 10–50× speed-up. Needed for a responsive web app.
12. **Search instead of grid.** As design variables multiply, use a multi-objective optimiser (NSGA-II / Bayesian) rather than full factorial sweeps.
13. **Uncertainty:** Monte Carlo over the assumption registry instead of a single worst case.
14. **Assumption registry exported with every result**, so a CSV carries the assumptions that produced it.

## Engineering
15. Regression tests against stored example-study outputs.
16. Publish to PyPI, add versioned docs.
17. **Licence:** still to be decided; ask at each release.

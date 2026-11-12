# Known issues and improvement backlog

A review of the model and advisor as of v0.3.1, ranked by how much each item could change a design recommendation. "Fixed" items were found in this review and resolved in v0.3.1.

## Found and fixed during the v0.3.2 validation
| Issue | Effect |
|---|---|
| OCV taken as the mean of the C/20 charge and discharge curves | about 50 mV too high near full charge, so heat was wrong at the start of every test |
| No low-SOC resistance rise | missed the end-of-discharge voltage collapse and its heat |
| Low-SOC factor (identified on discharge) also applied when charging | false heat spike at the start of a charge |
| SOC window hard-stopped charging at SOC = 1 | CC-CV charge ended before the taper; the OCV table now extrapolates and CV ends the charge |
| Calibrated slow-branch constants stored only in the validation module | the library cell lacked them; now on the cell |

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
1. ~~Isolated-cell assumption~~ **Addressed in v0.4** by `btms.module`: packed unit cell, cold-plate and ribbon contact, coolant rise. **Still open:** the design advisor (`btms design`) still uses the single-cell model (moving it is v0.4.1); cells at module edges; 2D axial-radial field (the axial gradient is a quasi-steady estimate). Original note: **Isolated-cell assumption.** Each cell gets a uniform h around its whole circumference, and natural convection treats it as alone in free air. In a module, neighbouring cells block most of that path, and a cold plate touches only part of each can. Natural-cooling and liquid-cooling results are both optimistic. **Fix in v0.4:** a module unit cell (square/hex packing, contact fraction to the plate, coolant temperature rise along the plate).
2. ~~Per-cell PCM sleeve~~ **Addressed in v0.4:** PCM and composite PCM now fill the inter-cell gaps of the module model. Composite properties follow one published formulation (Yu 2023); other EG loadings are available via `composite_pcm(k=..., paraffin_mass_fraction=...)`. Original note: **PCM as a per-cell sleeve inside a 1 mm Al tube.** The sleeve alone adds about 19 % of cell mass, and packs are not built this way. Real PCM packs use a matrix between cells, often expanded-graphite composite with k of 3–10 W/m·K rather than 0.2. **Fix:** composite-PCM grades and module-level PCM geometry (v0.4).
3. ~~Lumped DC resistance~~ **Done in v0.3.2** for the NCR18650PF: an equivalent circuit with Butler–Volmer kinetics and a slow RC branch, validated on 49 tests (docs/VALIDATION.md). **Still open:** the M50 and MJ1 have no measured data in reach (the Warwick M50 data is not reachable from the build environment), so they still use lumped DCIR.
4. ~~No CV taper~~ **Done in v0.3.2.** **Still open:** capacity does not depend on temperature (cold capacity loss near cut-off below 0 °C), deep-cold kinetics at high current (−20 °C predictive heat up to +3.4 K), and the NCA entropic coefficient (charge under-predicted by about 1.1–1.5 K).
5. **1D radial model only.** There are no axial gradients and no tab/base cooling. Bottom cooling of cylindrical cells is common in production packs.
6. **Pump power inconsistency (important for v0.4.1).** The module model computes pump power from flow (about 2 mW per cell at the reference flow) and fan power (about 170 mW per cell). The design advisor still uses the thesis anchors (liquid about 400 mW per cell), which overstate liquid-cooling energy by about 200×. Fix by moving the advisor onto `btms.module`. Also: **fan-law anchors are the thesis estimates**, and the h^3.75 law assumes turbulent flow. Laminar cold-plate channels behave differently, where h is set by geometry more than flow. Needs a cold-plate design reference.
7. **The chiller has a fixed COP** and ignores ambient heat leaking into the chilled loop.

## Module model assumptions to firm up
- Roll-end-to-can resistance (5e-4 m²K/W) dominates bottom cooling and is the least certain value. A teardown or bottom-cooling test would pin it down.
- Coolant reference flow (0.05 g/s per cell), h_ref (1500 W/m²K), Δp_ref (20 kPa), pump efficiency (0.5) and air flow/Δp are typical values, not a specific pack.
- The side ribbon is applied at the can surface with a uniform contact fraction. In reality the contact is a strip, so the can gets a circumferential gradient.

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

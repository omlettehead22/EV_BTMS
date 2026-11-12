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
1. ~~Isolated-cell assumption~~ **Addressed in v0.4** by `packtherm.module`: packed unit cell, cold-plate and ribbon contact, coolant rise. **Advisor moved onto the module model in v0.4.1.** **2D bottom plate done in v0.4.8.** Original note: **Isolated-cell assumption.** Each cell gets a uniform h around its whole circumference, and natural convection treats it as alone in free air. In a module, neighbouring cells block most of that path, and a cold plate touches only part of each can. Natural-cooling and liquid-cooling results are both optimistic. **Fix in v0.4:** a module unit cell (square/hex packing, contact fraction to the plate, coolant temperature rise along the plate).
2. ~~Per-cell PCM sleeve~~ **Addressed in v0.4:** PCM and composite PCM now fill the inter-cell gaps of the module model. Composite properties follow one published formulation (Yu 2023); other EG loadings are available via `composite_pcm(k=..., paraffin_mass_fraction=...)`. Original note: **PCM as a per-cell sleeve inside a 1 mm Al tube.** The sleeve alone adds about 19 % of cell mass, and packs are not built this way. Real PCM packs use a matrix between cells, often expanded-graphite composite with k of 3–10 W/m·K rather than 0.2. **Fix:** composite-PCM grades and module-level PCM geometry (v0.4).
3. ~~Lumped DC resistance~~ **Done in v0.3.2** for the NCR18650PF: an equivalent circuit with Butler–Volmer kinetics and a slow RC branch, validated on 49 tests (docs/VALIDATION.md). **Still open:** the M50 and MJ1 have no measured data in reach (the Warwick M50 data is not reachable from the build environment), so they still use lumped DCIR.
4. ~~No CV taper~~ **Done in v0.3.2.** **Still open:** capacity does not depend on temperature (cold capacity loss near cut-off below 0 °C), deep-cold kinetics at high current (−20 °C predictive heat up to +3.4 K), and the NCA entropic coefficient (charge under-predicted by about 1.1–1.5 K).
5. ~~1D radial model only~~ **Done in v0.4.8** for bottom plates: an axisymmetric radius × height model (`packtherm.model2d`), checked against the exact steady solution. **Still open:** tab heating and top-side (tab/busbar) cooling are not modelled; the 2D run is about 2.5× slower than the radial one.
6. ~~Pump power inconsistency~~ **Fixed in v0.4.1:** the module advisor computes pump and fan power from flow and pressure drop. **Whole loop done in v0.4.5:** pump power covers module + rest-of-loop pressure drop at a datasheet efficiency, and the radiator fan is charged. **Still open:** the radiator fan share (3 % of rejected heat) is an assumption; ram air at speed would make it smaller; chiller idle losses and the condenser fan are not modelled. Original note: **Pump power inconsistency.** The module model computes pump power from flow (about 2 mW per cell at the reference flow) and fan power (about 170 mW per cell). The design advisor still uses the thesis anchors (liquid about 400 mW per cell), which overstate liquid-cooling energy by about 200×. Fix by moving the advisor onto `packtherm.module`. Also: **fan-law anchors are the thesis estimates**, and the h^3.75 law assumes turbulent flow. Laminar cold-plate channels behave differently, where h is set by geometry more than flow. Needs a cold-plate design reference.
7. ~~Fixed chiller COP, no heat leak~~ **Done in v0.4.4:** COP falls with ambient (Carnot share), heat leaking in from a hot day is charged, and the chiller runs during the event then hands back to the radiator. **Still open:** the Carnot share (0.42) and the 9 h pack time constant are single-source assumptions; the leak heat is charged to the chiller but does not warm the cells in the thermal model; chiller idle losses are not modelled.

## Module model assumptions to firm up
- **Coolant thermal mass done in v0.4.7:** the coolant held in each cell's share of the channel (from the v0.4.3 geometry) stores heat, solved implicitly; `coolant_mass=False` restores the steady balance. It is a single lump per cell, not a transport delay along the channel, so a sharp step at the inlet arrives smeared rather than delayed.
- Roll-end-to-can resistance (5e-4 m²K/W) dominates bottom cooling and is the least certain value. A teardown or bottom-cooling test would pin it down.
- Coolant reference flow (0.05 g/s per cell), h_ref (1500 W/m²K), Δp_ref (20 kPa), pump efficiency (0.5) and air flow/Δp are typical values, not a specific pack.
- The side ribbon is applied at the can surface with a uniform contact fraction. In reality the contact is a strip, so the can gets a circumferential gradient.

- ~~Flat cooling hardware mass~~ **Done in v0.4.3:** mass from geometry with sourced dimensions. **Still open:** pack-level parts (liquid loop 3 kg, air system 4 kg, chiller 4 kg) are assumptions; cell holders and module structure are not charged to any option; the ribbon contact is still uniform around the bonded share of the can.
- **Edge cells done in v0.4.6** (`simulate_module(edge=True)`, `Wall`). **Still open:** the wall U-value (5 W/m²K) and edge share (1/3) are assumptions; with air gaps the wall is applied at the can, which slightly overstates the edge path; the chiller's heat leak (v0.4.4) and the edge-cell wall are separate estimates of the same physics.

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

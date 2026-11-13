# Known issues and improvement backlog

Open items as of v0.5.2, ranked within each group by how much they could change a design recommendation. What has been fixed, and when, is in the [resolved log](#resolved-log) at the end and in [CHANGELOG.md](../CHANGELOG.md).

## Cell model
1. **LG M50 circuit is derived, not measured.** It comes from PyBaMM's DFN with the ORegan2022 parameter set and matches that model's heat within 0.94–1.13× ([VALIDATION.md](VALIDATION.md#lg-m50-checked-against-a-physics-model-not-measured)), but no measured M50 temperatures check it. The Warwick M50 core-temperature data (Mendeley bf6fksxpp2) would; it is not reachable from this build. Its cold voltage knee arrives late (cut-off up to 0.75 Ah after the DFN at 0 °C, 1.4C).
2. **Lumped-resistance cells.** The LG MJ1 and every user-defined cell (v0.5.2) use a lumped DC resistance with assumed temperature and SOC shapes and no voltage model; `packtherm cells` shows which model each cell uses. User-defined cells are NMC or NCA only (LFP planned), and NCA has no entropic heat. Fitting a full circuit from a user's own test data is planned (v0.6).
3. **Cold drive-cycle heat is 7–10 % low** on the validated PF cell: the slow-branch temperature law, fitted at 0.3C, is slightly too gentle at drive-cycle currents (worst peak −3.5 K at −20 °C).
4. **NCA entropic heat is neglected** (no dU/dT data in the dataset; published NCA profiles disagree on the sign). The PF charge is under-predicted by 1.1–1.4 K.
5. **Core temperature is not validated**; the dataset has one surface thermocouple.

## Module model
6. **Roll-end-to-can resistance** (5e-4 m²K/W) dominates bottom-plate cooling and is the least certain value. A teardown or a bottom-cooling test would pin it down.
7. **Reference flows and pressure drops are typical values, not a specific pack:** coolant 0.05 g/s per cell, h_ref 1500 W/m²K, module Δp 20 kPa plus loop 30 kPa, pump efficiency 0.3; air 0.3 g/s, h 30 W/m²K and Δp 200 Pa at a 2 mm gap. Only the scaling away from these points is physics (since v0.4.13: laminar coolant channels, cross-flow over the cans for air). The air correlation is used below its usual pitch range (pitch/diameter 1.1 against ≥ 1.25), and the ribbon's h_ref is not tied to its port geometry.
8. **2D slices, not a 3D field.** The plate is solved in radius × height and the ribbon in radius × angle, separately. The ribbon displaces filler near the strip, but the angle model fills the full annulus.
9. **Coolant holdup is one lump per cell**, not a transport delay, so a sharp inlet step arrives smeared rather than delayed.
10. **Edge cells use an assumed wall** (U = 5 W/m²K over 1/3 of the share). With air gaps the wall is applied at the can, which slightly overstates the edge path. The chiller's heat leak and the edge wall are separate estimates of the same physics, and the leak is charged to the chiller but does not warm the cells.
11. **Not modelled:** tab heating, top-side (tab/busbar) cooling, cell holders and module structure (not charged to any option).

## Energy and hardware assumptions
12. **Chiller:** the Carnot share (0.42) and the 9 h pack time constant are single-source assumptions; idle losses and the condenser fan are not modelled.
13. **Radiator fan at 3 % of rejected heat** is an assumption; ram air at speed would make it smaller.
14. **Pack-level parts** (liquid loop 3 kg, air system 4 kg, chiller 4 kg) are assumptions.

## Advisor and product
15. **Ageing as a third objective.** Temperature drives calendar and cycle ageing. Scoring designs on predicted capacity fade would show what "hotter but lighter" costs in battery life. Probably the highest-value product feature.
16. **Cost objective (£/pack):** PCM £/kg, cooling hardware, chiller.
17. **Cold climate:** pre-heating energy and cold-start limits, not just cooling.
18. **Speed.** Fast mode (v0.5.0) runs the road-trip study in about 40 s on two cores, against about 3 minutes in normal mode. Not yet done: adaptive time steps (long steady cruise and rest periods would allow much longer steps), stopping a simulation once the cell has recovered, and compiled inner loops (Numba). A design is four cell simulations in a Python time loop, so more cores help directly.
19. **Search instead of grid** once the design variables multiply (NSGA-II or Bayesian optimisation).
20. **Uncertainty:** Monte Carlo over the assumptions instead of a single worst case.
21. **Assumption registry.** Since v0.5.1 a results JSON carries the main assumptions (reference flows and pressure drops, efficiencies, chiller, wall, pack parts, resolution). Not yet: the cell-model and material values, and the CSV on its own carries none.

## Engineering
22. **Regression tests that re-run the example studies** against their stored results (v0.5.1 checks the README against the stored results, but CI does not re-run the studies; fast mode could make that affordable).
23. Publish to PyPI, add versioned docs.
24. **Licence:** decided at v0.5.

## Resolved log

| Version | Resolved |
|---|---|
| v0.3.1 | Fan/pump energy now counted through recovery; datasheet C-rate check in studies; robustness margin when nominal R is already the maximum; no fragile pick when every front design fails the re-check; bounded memory; sink temperature independent of the start temperature (chiller possible) |
| v0.3.2 | Validation on the NCR18650PF: equivalent circuit with Butler–Volmer kinetics and a slow branch, CC-CV taper, OCV from the discharge branch, low-SOC rise (discharge only), charge past SOC 1 handled by CV |
| v0.4 | Isolated-cell assumption replaced by a packed module unit cell; PCM and composite PCM fill the gaps instead of a per-cell sleeve |
| v0.4.1 | Advisor moved onto the module model; pump and fan power from flow and pressure drop |
| v0.4.3 | Cooling hardware mass from sourced geometry instead of flat kg/kWh |
| v0.4.4 | Chiller COP falls with ambient; heat leak charged; chiller hands back to the radiator |
| v0.4.5 | Whole-loop pump power; radiator fan charged |
| v0.4.6 | Edge cells on the module wall |
| v0.4.7 | Coolant thermal mass in the channel |
| v0.4.8 | 2D radius × height bottom-plate model |
| v0.4.9 | Ribbon cools a strip of the can (radius × angle model) instead of a uniform contact |
| v0.4.10 | Cold-weather temperature laws for the low-SOC rise and slow branch (88 % of blind tests within 1 K) |
| v0.4.11 | LG M50 circuit derived from the DFN; worst-case re-check scales every loss term |
| v0.4.12 | Audit: duplicate-design crash, contradictory messages, CLI header and flags, air cooling now depends on the gap |
| v0.4.13 | Physics audit: laminar coolant and cross-flow air laws, in-cell spread on the cooled face, per-phase datasheet temperature checks, datasheet limits as currents, MJ1 charge limits, CLI input checks |
| v0.5.0 | Fast mode (about 5×); exact region volumes on every mesh; faster electrical model |
| v0.5.1 | Study files and results JSON; README numbers checked against the examples in CI |
| v0.5.2 | User-defined cylindrical cells (NMC/NCA) from datasheet values |

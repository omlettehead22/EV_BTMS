# Changelog

## 0.4.6
- **Edge cells** (`simulate_module(..., edge=True)`, `module.Wall`): a cell on the module wall exchanges heat with ambient through a third of its share (it has 4 neighbours instead of 6), at U = 5 W/m²K (assumption). `Wall(fraction=0.5)` for corner cells.
- **Advisor** (`ModuleStudy.edge_cells`, on by default): edge cells at both ends of the channel are simulated; feasibility uses the hottest of interior and edge cells, and the cell-to-cell spread is hottest minus coolest. New columns `T_peak_interior_C`, `T_peak_edge_outlet_C`, `T_peak_edge_inlet_C`, `hottest_cell`.
- **Effect (M50, 35 °C road trip):** cooled modules' edge cells run 0.1–0.8 K cooler than interior cells; a sealed module's edge cells run 8 K cooler; in chilled designs the edge cells are the hottest, by hundredths of a degree. Same picks. Studies take about 60 % longer (two more cells per design).

## 0.4.5
- **Whole-loop pump power.** `Coolant.dp_loop_ref_Pa` (30 kPa) adds the rest of the loop (hoses, manifolds, chiller, radiator) to the module channels (20 kPa); 50 kPa in total matches the 0.5–0.6 bar small electric coolant pumps are rated for at 20–25 L/min. Pump efficiency 0.5 → 0.3, from the same datasheets (Pierburg CWA50, Rheinmetall CWA 50). Pump power per cell 1.9 → 7.9 mW (about 26 W for a 60 kWh M50 pack).
- **Radiator fan energy** (`ModuleResult.radiator_fan_energy_Wh`): 3 % of the heat the coolant carries to the radiator, whenever the chiller is not running (assumption).
- **Effect:** liquid cooling costs about 0.05 % of the energy moved on the 35 °C road trip (was about 0.001 %), still about 5× less than the lightest air design. The bottom plate and the ribbon now tie on energy, so the lowest-energy pick moves to the bottom plate; the ribbon stays the balanced pick.

## 0.4.4
- **Chiller accounting** (`packtherm.module.Chiller`):
  - COP falls with ambient: a share (0.42) of the Carnot COP between an evaporator 5 K below the set-point and a condenser 15 K above ambient. About 3.0 at 35 °C with a 15 °C set-point (the old fixed value), 2.4 at 45 °C, 4.0 at 25 °C. `--cop` still fixes it.
  - Heat leaking into a chilled pack from a hot day is charged to the chiller: cell heat capacity / 9 h pack time constant × (ambient − set-point).
  - The chiller runs during the event, then the loop hands back to the radiator (`Coolant.chiller_until_s`, `--chiller-runs event|always`). Before, the chiller held the set-point forever in the simulation and its energy was cut off at an immediate "ready" time.
- **Effect:** chilled designs cost 1.2–2.1 % of the energy moved on the 35 °C road trip (was 1.1–2.0 %). Same picks.

## 0.4.3
- **Cooling hardware mass from geometry** (`packtherm.hardware`), replacing the flat kg per kWh in the module advisor:
  - cold plate: base and channel sheets over the cell's footprint, coolant in the channels, gap filler under the cell (`PlateGeometry`);
  - side ribbon: the cell's share of an extruded multi-port tube (walls and ribs), coolant inside, bond to the can (`RibbonGeometry`);
  - pack-level parts per cell: liquid loop, air system, chiller (`PackHardware`, with `--pack-kwh`, `--liquid-loop-kg`, `--air-system-kg`, `--chiller-kg`);
  - defaults sourced from supplier data (AMAG, Boyd, XD Thermal, Dow, Bostik); the rest labelled as assumptions;
  - mass breakdown columns in the design CSV (`mass_hw_aluminium_g`, `_coolant_g`, `_interface_g`, `_pack_share_g`).
- **Changed:** liquid hardware drops from 1.0 to about 0.3 kg/kWh and air from 0.5 to 0.07. M50 road trip at 35 °C: forced air +1.8 % mass (was +13 %), side ribbon +7.2 % (was +27 %). Same picks.
- **Changed:** the side ribbon covers 75 % of the can height, and its contact conductance is scaled to match (it assumed full height).
- **Changed:** the ribbon's minimum gap is the tube plus two bond lines (3.5 mm by default, was a flat 1.5 mm). The advisor and `packtherm module` widen the gap to fit, and the tube's volume is taken out of the filler.
- `Interface.rho` (gap-filler density). Heatmap rows carry the gap when it varies, so filler columns stay aligned. Pick labels sit closer to their point.

## 0.4.2
- **Renamed to PackTherm.** GitHub repo `EV_BTMS` → `PackTherm` (old links redirect), Python package `btms` → `packtherm` (`import packtherm`), command `btms` → `packtherm`. Entries below keep the old names.
- **New model picture** (`docs/figures/model_overview.svg`, drawn by `make_model_diagram.py`): the module, one cell's share solved in 1D, and the design loop. Replaces the thesis cell–PCM–casing figure in the README.
- **Fixed:** v0.4.1 never reached `main` (PR #8 merged into the v0.4 branch after it had been merged); brought across in #9.
- **Fixed:** `matlab/main_simulation.m` called `plot_additional_results.m`, which was never committed. It now calls `generate_thesis_figures.m`, the routine that replaced it.
- **Fixed:** trade-off chart pick labels could cross the front line. Labels now sit below-left of each pick, where the front's staircase never runs.

## 0.4.1
- **Design advisor on the module model** (`btms.module_design`, now the default for `btms design`):
  - design variables: topology (sealed / forced air / bottom plate / side ribbon), flow per cell, chiller inlet, gap filler, gap;
  - scored on the coolant-outlet cell; the inlet cell gives the cell-to-cell spread, with an optional limit (`--cell-to-cell-max`, fail reason `spread`);
  - fan and pump energy from flow and pressure drop, chiller energy from the heat taken by sub-ambient coolant ÷ COP;
  - mass = filler + cooling hardware; gap volume reported as `volume_overhead_pct`;
  - the v0.3 single-cell advisor stays available as `btms design --level cell`.
- **Fixed:** the advisor used the thesis pump anchor (about 400 mW per cell for liquid), about 200× the pump power computed from flow and pressure drop (1.9 mW).
- **Fixed:** forced-air h was fixed while flow changed fan power and air rise. h now follows flow (h ∝ flow^0.8); `AirFlow.with_h()` finds the flow for a target h. `btms module --h` is replaced by `--air-flow`.
- **Fixed:** chiller energy was missing from the module model (`ModuleResult.chiller_energy_Wh`).
- **Fixed:** a side ribbon could be placed in a gap too small for it; it now needs at least 1.5 mm (`SideRibbon.min_gap_mm`).
- **Changed:** the bottom-plate axial estimate uses the smaller of generated heat and heat reaching the coolant, rather than generated heat alone. Still an upper bound; bottom-plate in-cell ΔT at 1.5C drops from 9.3 K to 6.4 K.
- Front, robustness and picks are factored into `design.select_front`, shared by both advisors. Trade-off chart: n/a cells for invalid combinations, adaptive log threshold, labels kept inside the axes.

## 0.4.0
- **Module-level model** (`btms.module`, `btms module`):
  - one cell in a packed hex or square array, as an equivalent annulus with an adiabatic outer edge;
  - gap filler: air, PCM or composite PCM;
  - cooling: forced air, bottom cold plate (axial conduction, roll-end resistance, thermal interface), side ribbon (contact fraction), or none;
  - coolant and air warm along the channel, solved in balance with the absorbed heat (stable at any contact-to-flow ratio); inlet and outlet cells are both reported;
  - flow sets h, the coolant rise and pump/fan power.
- **Solver:** distributed sinks with a state-dependent sink temperature (`model.Sink`). The heat taken by each sink and its temperature are returned.
- **Composite PCM grades** (`<grade>-EG`, Yu et al. 2023): k = 3.85 W/m·K, latent heat × 0.86.
- `Cell.k_axial`: in-plane conductivity of the winding (25 W/m·K for NMC811 layers).
- **`btms cell --pcm-grade`** to choose the PCM for single runs.
- Tests: analytic bottom-plate steady state (within 3 %), coolant heat balance, adiabatic interior cell, air-flow equivalence with the bare-cell model, stability at extreme contact-to-flow ratios.

## 0.3.2
- **Validation** (`btms.validation`, `validation/`, `docs/VALIDATION.md`) against 49 tests of the Panasonic NCR18650PF (Kollmeyer 2018, CC BY 4.0) at 25 to −20 °C. Thermal mode: 0.59 K median RMSE. Fully predictive: 0.62 K. Regression gates are in `tests/test_validation.py`.
- **Equivalent-circuit electrical model** (`btms.ecm`):
  - OCV table, ohmic R0, Butler–Volmer charge-transfer overpotential with Arrhenius I₀(T), a slow diffusion RC branch, and a low-SOC factor on discharge;
  - heat = I·(OCV − V);
  - discharge stops at V_min; charging switches to CV at V_max and ends at the current cut-off.
- **New cell** `PF` (Panasonic NCR18650PF), identified from the dataset's own C/20 and HPPC tests (`validation/identify_panasonic.py`).
- `MeasuredHeatLoad` for thermal-only validation from logged current and voltage.
- `SimulationResult.T_surface`: outer-surface temperature at every step.
- Cells without an ECM (M50, MJ1) keep the lumped I²R path unchanged.

## 0.3.1
- **Passenger-EV duties** (`btms.ev`): WLTC Class 3b trace (UN GTR 15), road-load vehicle model, pack sizing, a 3× WLTC duty, and a motorway-then-rapid-charge road trip.
- **Continuous cooling:** h sweeps with fan-law power (P ∝ h^3.75), anchored to the thesis levels. The thesis levels are still available via `thesis_cooling_options()` / `--thesis-levels`.
- **Chiller:** a coolant setpoint below ambient as a design option, with chiller energy = heat removed ÷ COP.
- **PCM library** (`btms.materials`): RT28HC, RT31, OM35, RT42, with grade as a design variable alongside thickness.
- **Robustness:** worst-case resistance = published max × (1 + 20 % margin). Front designs that fail are marked fragile and the front is rebuilt without them.
- **Fixed:** fan/pump energy now covers event + recovery (it previously covered the event only).
- **Fixed:** design studies report datasheet C-rate breaches, judged on a 30 s rolling mean.
- Solver 2.6× faster (direct LAPACK tridiagonal solve, precomputed enthalpy masks). Optional `store_every` cuts memory for long runs.
- Separate initial and sink temperatures in `simulate_cell`.
- New `docs/BACKLOG.md`: known limitations and the improvement plan.

## 0.3.0
- Design advisor (`btms.design`): sweeps cooling option × PCM thickness for one cell and duty cycle.
- Feasibility checks peak temperature, in-cell ΔT and recovery (ready for the next event), with a reason recorded for each failure.
- Costs are mass overhead (PCM + sleeve + cooling hardware, % of cell mass) and fan/pump energy (% of throughput).
- Pareto front plus three picks (lightest, lowest energy, balanced). Front designs are re-checked at worst-case cell resistance.
- Trade-off chart (`btms.report.plot_tradeoff`): scatter of mass vs energy, and a grid of peak temperatures with failure reasons.
- `btms design` CLI writes a CSV and PNG. Studies run in parallel.
- Duties stop drawing current at the end of the event, so the rest period is a true rest.
- matplotlib added as a dependency.

## 0.2.0
- Electro-thermal load: Q = I²R(SOC,T) − I·T·dU/dT, coulomb-counted SOC, SOC windows.
- Cell library: LG M50 (21700) and LG MJ1 (18650) with cited parameters; jelly-roll cp and k from O'Regan 2022 layer data.
- Current profiles: constant C-rate, piecewise segments (optionally repeating), CSV import.
- Datasheet limit warnings (`check_limits`).
- Solver: Newton on the enthalpy residual is now the default (`SolverSettings.scheme="enthalpy"`). It converges on every step, about 3× faster, with machine-precision energy balance. The thesis scheme is still available and parity-tested.
- CLI subcommands: `btms thesis`, `btms cells`, `btms cell`.
- `metrics.summarise_result` works for any run, not just thesis scenarios.

## 0.1.0
- Python port of the MATLAB thesis model with bit-for-bit parity tests, README and CI.

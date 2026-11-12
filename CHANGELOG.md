# Changelog

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

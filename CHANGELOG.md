# Changelog

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

# EV_BTMS: battery thermal management design toolkit

A transient thermal model of a lithium-ion cell wrapped in a phase-change material (PCM) layer and an aluminium casing, cooled by forced air or a liquid cold plate. It started as an MSc thesis model in MATLAB and is being developed into a Python **BTMS design tool**. The tool answers questions like *"for this cell and duty cycle, do I need PCM, how much cooling, and what does it cost in fan or pump energy?"*

![Model domain](docs/figures/figure_3_1_model_domain.png)

## Status: v0.1, Python port

The thesis solver has been ported to Python (`src/btms`) and reproduces the MATLAB results to about 1e-11 on every summary metric for the four thesis scenarios. It also reproduces the mesh and time-step studies. The original MATLAB code is kept in [`matlab/`](matlab/) as the reference.

| Scenario | Peak T (°C) | In-cell ΔT (°C) | Mean PCM liquid fraction | Fan/pump energy (Wh) | Energy-balance error |
|---|---|---|---|---|---|
| drive, air, mid (h=30) | 31.67 | 1.39 | 0.02 | 3.3 | 0.013 % |
| drive, liquid, low (h=100) | 31.09 | 1.43 | 0.005 | 1.7 | 0.0007 % |
| fast charge, air, high (h=60) | 36.81 | 2.07 | 0.32 | 40 | 0.003 % |
| fast charge, liquid, mid (h=300) | 33.56 | 2.09 | 0.07 | 40 | 0.001 % |

These results already contain a design insight: with liquid cooling the PCM barely melts (about 7 % used), so it adds mass with little benefit. With weaker air cooling the PCM does real work.

## Quick start

```bash
pip install -e ".[dev]"
btms                 # run the four thesis scenarios
pytest -q            # parity + physics tests
```

```python
from btms import default_params, simulate

P = default_params()
res = simulate(P, heat_source=lambda t: 9.4e4, duration=1800, h=60.0, T_env=P.T_coolant)
print(res.T_max.max() - 273.15, res.pcm_fraction.max(), res.balance_error_pct)
```

## Model

- **Domain:** a 1D radial line from the cell centre (18650 geometry, r = 9 mm) through 3 mm of RT31-type paraffin PCM to a 1 mm Al 6061 casing.
- **Discretisation:** conservative cell-centred finite volumes in cylindrical coordinates, harmonic-mean face conductivities, and backward Euler in time.
- **PCM:** apparent heat capacity over the 29–34 °C melting range, iterated per step with under-relaxed Picard iteration.
- **Boundary:** a convective outer wall, with half-cell conduction and 1/h in series.
- **Verification:** an independent enthalpy-based energy balance (< 0.1 % error required), plus mesh (Nx 65/130/260) and time-step (1 to 0.125 s) convergence studies.

**Known limitation (fixed in v0.2):** a few time steps per run, where a node sits right on the edge of the melting range, hit the iteration cap. The original MATLAB code had the same behaviour. The energy balance stays below 0.02 %, so the results are unaffected, but an enthalpy-consistent capacity converges in about 4× fewer iterations.

## Roadmap

| Version | Scope |
|---|---|
| **v0.1** ✅ | Python port, parity tests, CI |
| v0.2 | Electro-thermal heat generation (current/C-rate × internal resistance + entropic), cell library (18650, 21700), faster enthalpy-consistent PCM solver |
| v0.3 | Design advisor: sweep cooling type, h and PCM thickness and return the lightest or lowest-energy design that meets T_max and ΔT limits |
| v0.4 | Pack level: coolant temperature rise along the cold plate, cell-to-cell spread |
| v0.5 | Web app and API |

## Repository layout

```
src/btms/        Python package (params, model, scenarios, metrics, cli)
tests/           MATLAB-parity and physics tests
matlab/          original thesis code + reference results
docs/figures/    thesis figures
```

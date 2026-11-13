# Fast and normal modes

Module studies and comparisons run in one of two numerical resolutions:

```bash
packtherm design M50 --duty roadtrip --t-env 35            # normal (default)
packtherm design M50 --duty roadtrip --t-env 35 --fast     # fast
packtherm module M50 --compare --c-rate 1.5 --fast
```

In Python: `ModuleStudy(..., mode="fast")` or `compare_modules(..., mode="fast")`. Fast mode is for exploring: sweeping many designs, or getting an answer while you wait. Normal mode is for final numbers, and every result in the README and examples uses it.

## What changes

| Setting | Normal | Fast |
|---|---|---|
| Thermal time step | 2 s | 5 s |
| Electrical step (the cell model inside a thermal step) | 2 s | 2 s while the current changes; one step while it is constant |
| Radial spacing | 0.1 mm | 0.3 mm |
| Plate layers (radius × height) | 16 | 12 |
| Ribbon slices (radius × angle, half the can) | 12 | 8 |
| Each region given its exact volume | yes | yes |

The electrical substeps keep a drive cycle's second-by-second current (and its drive–regen swings) in the heat and in the energy throughput, whatever the thermal step. Exact region volumes matter on a coarse mesh: a uniform mesh assigns each node wholly to the cell or the filler, so a 1.6 mm filler layer at 0.3 mm spacing could be up to about 10 % off in heat capacity.

## Speed and accuracy

Measured on the three example studies (LG M50, 39 designs each, interior and edge cells at inlet and outlet, worst-case re-check), run one at a time on the same 2-core machine:

| Study | Normal | Fast | Speed-up |
|---|---|---|---|
| Road trip, 35 °C | 196 s | 38 s | 5.2× |
| 1.5C discharge, 25 °C | 104 s | 19 s | 5.5× |
| 3 × WLTC, 35 °C | 139 s | 28 s | 5.0× |

Largest difference from normal mode over all 117 designs:

| Quantity | Road trip | 1.5C | WLTC |
|---|---|---|---|
| Hottest cell | 0.01 K | 0.12 K | 0.003 K |
| In-cell spread | 0.18 K | 0.13 K | 0.19 K |
| Cell-to-cell spread | 0.02 K | 0.26 K | 0.005 K |
| Recovery time | 0.9 min | 1.9 min | 0 min |
| Fan, pump and chiller energy | 0.1 % | 0.5 % | 0.5 % |
| Designs whose verdict changes | 0 | 0 | 0 |
| Picks | same | same | same |

The largest errors come from fast transients: the end of a hard discharge, when the cell heats fastest (time step), and a chiller pulling a hot pack down through its base (plate layers). A design within about 0.3 K of a temperature limit, or 0.2 K of the in-cell limit, can come out differently in the two modes. Check close calls in normal mode.

`tests/test_module_design.py::test_fast_mode_tracks_normal_mode` checks agreement on a smaller study in CI.

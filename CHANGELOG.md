# Changelog

## 0.5.3

The HTTP API, the fourth v0.5 mini update: run studies over HTTP, for programs and for the web app to come.

- **New: `packtherm.api`** (FastAPI). Install with `pip install "packtherm[api]"`, start with `packtherm serve` or the new Docker image.
  - `POST /studies` queues a study (the study-file format, as JSON) and returns its id.
  - `GET /studies/{id}` gives state, progress (designs done out of total, then the worst-case re-check), time remaining and queue position.
  - `GET /studies/{id}/results`, `/designs.csv` and `/chart.png` fetch the outputs. `DELETE` cancels a study or deletes its results.
  - Also `GET /cells`, `POST /cells/check`, `GET /schema`, `/template`, `/limits` and `/health`, with interactive docs at `/docs`.
  - Details in `docs/API.md`.
- **Same results:** a study through the API gives exactly the results `packtherm run` writes for it (test).
- **Jobs.**
  - Each study runs in its own process, so a time limit or a cancel stops it cleanly and a crash can't affect another.
  - There's no database: each job is a folder, deleted 24 hours after it finishes.
  - A restart fails unfinished studies and keeps finished ones.
- **Limits** for a public server, all settable by environment variables: designs per study (120 fast, 40 normal), simulated time (24 h), duty segments, run time (15 min), 10 studies per visitor per hour, request size (256 kB), 2 running and 20 queued. **API keys** (`PACKTHERM_API_KEYS`, `X-API-Key` header) skip the per-study limits, the time limit and the rate limit.
- **New: `GET /schema`**, the study format as data: types, defaults, choices and bounds, taken from the same rules that validate studies. The web app will build its forms from it. (`packtherm.study.schema()`; the validation rules now carry their bounds.)
- **New: progress reporting.** `run_module_study(progress=...)` and `StudySpec.run(progress=...)`.
- **New: example studies re-run in CI** (`tests/test_examples_rerun.py`). The three examples run in fast mode and must match their committed results: the same verdicts and picks, peaks and spreads within 0.3 K, recovery within 3 min, energy within 2 %. A model change that moves a result now fails CI until the examples are regenerated. About 1½ minutes.
- **CI:** a new job builds the Docker image, starts it and runs a study through the API.
- `packtherm serve`; `Dockerfile` (non-root, health check); `api` extra (FastAPI, Uvicorn).

## 0.5.2

User-defined cells, the third v0.5 mini update: describe your own cylindrical cell from its datasheet and run every study on it.

- **New: user-defined cells** (`packtherm.user_cells`).
  - A definition gives name, format (18650, 21700, 26650, 4680) or diameter and height, chemistry (NMC or NCA), capacity, nominal voltage, mass and DC resistance. Optional: datasheet maximum resistance (for the worst case), current and temperature limits, and overrides for heat capacity, conductivities and the cold resistance rise.
  - It can be written inline in a study (`cell:` as a mapping) or as its own file. A cell file works wherever a cell name does: `packtherm design my_cell.yaml`, `packtherm module my_cell.yaml`, `cell: my_cell.yaml` in a study (relative to the study; inlined so the results carry the full cell). In Python: `Cell.from_datasheet(...)` or `load_cell(path)`.
  - `packtherm cells my_cell.yaml` checks a file and shows the cell as PackTherm understands it: density, energy density, cold resistance rise, thermal properties and limits.
- **Model:** the lumped resistance model of the library MJ1, with no voltage model (no cut-off, no constant-voltage taper). NMC uses the NMC/graphite jelly-roll properties and entropic heat behind the LG M50. NCA uses the same jelly-roll properties and no entropic heat, as for the validated Panasonic NCA cell. Results are labelled "user-defined, lumped DCIR" in the cells table, the results JSON (`summary.cell_model`) and a study note.
- **Unit-slip checks.** Values no real cylindrical Li-ion cell has are errors, each naming the likely slip: mass in kg, resistance in ohms, capacity in mAh, sizes, voltage, temperature limits. Unusual values are warnings, written into the results notes.
- **Proof:** `docs/examples/user_cell_mj1.yaml`, the LG MJ1 from its datasheet values, gives byte-identical results to the library MJ1. A test checks every value the model uses and a design's full result. Conversions shift the decimal point (`65.1 mm` gives exactly `65.1e-3 m`) so this holds exactly.
- **New note:** a duty that charges a cell with no datasheet charge limit gets a study note saying the charge rate is unchecked. The road trip's rapid charge falls back to 1C without a limit, which was easy to miss.
- `Cell.model_label` and `Cell.user_defined`; the `packtherm cells` model column now comes from the cell.
- Docs: README "your own cell" section; `docs/STUDY_FILES.md` documents every cell key (enforced by a test); BACKLOG.

## 0.5.1

Study files, the second v0.5 mini update: one document describes a whole module study, so the command line, Python and (next) the API and web app run the same thing.

- **New: study files** (`packtherm.study`), format 1, in YAML or JSON.
  - A document holds the cell, normal or fast mode, ambient, duty (constant, wltc, roadtrip or segments), requirements, design space and options. Every key except `packtherm_study`, `cell` and `duty.type` is optional; defaults are those of `packtherm design`.
  - `packtherm run study.yaml [--out-dir]` writes `<stem>_results.json`, the designs CSV and the trade-off chart.
  - `packtherm template [--out]` prints a commented file with every default.
  - Python: `load_study(path)`, `StudySpec.build()` (the `ModuleStudy`), `StudySpec.run()`, `StudyRun.to_json()` and `.write()`.
- **Validation before anything runs.** Unknown keys, wrong types, out-of-range values, unknown cells or fillers, and duty keys a duty type doesn't use are all reported together, each naming its field (for example `design_space.coolant_flows_g_s[1]: must be > 0, got -0.05`). Bad YAML or JSON and missing files give a one-line CLI error.
- **New: results JSON** (format 1). It holds:
  - the study as run (with defaults), PackTherm version, time and run time;
  - a summary (designs, feasible, on the front, temperature limit), the picks and notes;
  - the main assumptions (resolution, reference flows and pressure drops, efficiencies, chiller, wall, resistance margin, pack parts);
  - every design.

  NaN and infinities are written as null, so the file is strict JSON. It will be the API's response format.
- **New: segments duties** in study files: `steps: [[duration_s, c_rate], ...]` (negative C-rate charges), for a custom duty without a CSV.
- **Changed:** `packtherm design --level module` builds a study document from its flags and runs it. The CLI and study files can't diverge, and it now also writes the results JSON. Output files are otherwise unchanged, and so are the results: the road-trip study through a study file reproduces the v0.5.0 CSV exactly.
- **New: README numbers checked in CI** (`tests/test_docs.py`): the current version against the roadmap and CHANGELOG, the road-trip picks and claims, the WLTC claims, the module comparison table and the validation figures, all against the committed example results. A model change that moves a quoted number now fails CI until the README is updated.
- Example study files for the three example studies (`docs/examples/*.yaml`), with their results JSON. Tests check that each file is exactly what its `packtherm design` command runs.
- README: study-file quick start; fast mode under "What the model covers"; study time corrected to 2–3½ minutes.
- New dependency: PyYAML (≥ 6.0).
- `packtherm.cli.parser()` returns the argument parser.
- `docs/STUDY_FILES.md`: every key of the study and results formats; a test checks that every key the format accepts is documented there. A test also checks the README's M50 heat claims against `validation/m50_vs_dfn.csv`.

## 0.5.0

Fast and normal modes, the first v0.5 mini update.

- **New: fast mode.** `packtherm design ... --fast`, `packtherm module ... --fast`, `ModuleStudy(mode="fast")` and `compare_modules(mode="fast")`.
  - Settings: 5 s thermal step, 0.3 mm radial spacing, 12 plate layers, 8 ribbon slices.
  - Speed: 5.0–5.5× quicker on the three example studies (road trip 196 s → 38 s on two cores).
  - Accuracy over all 117 designs: hottest cell within 0.12 K, in-cell spread within 0.19 K, recovery within 2 min, energy within 0.6 %. No design changes verdict and the picks are the same.
  - Details in `docs/FAST_MODE.md`. Normal mode stays the default.
- **New: electrical substeps.** `ElectroThermalLoad(max_substep=...)` runs the cell model in steps of at most that length inside a longer thermal step, and logs one averaged entry per thermal step. A drive cycle's second-by-second current is followed whatever the thermal step. It takes a single step when the current is constant across the step. The log gains `I_abs_A` (mean absolute current), and studies now use it for energy throughput, so drive and regen within one step don't cancel.
- **Changed: exact region volumes in module simulations.** A uniform radial mesh puts each node wholly in the cell or the filler, so the filler's volume (and heat capacity and latent heat) was only right to half a node. Each region now gets its exact volume (`Geometry.exact_volumes`; the module model's default). Effect in normal mode: peaks move by at most 0.09 K (sealed RT42 at 1.5C), with no verdict changes. The thesis model and its parity tests are unchanged.
- **Faster electrical model:** scalar OCV interpolation without `np.interp` (identical results), which helps both modes.
- `Resolution` and `RESOLUTIONS` (in `packtherm.module`) hold the settings for each mode.
- Examples regenerated in normal mode; README quick start, roadmap and BACKLOG updated.

## 0.4.13

A physics and minor-bug audit: every model file read against its physics, numerical convergence checked, and every CLI option tried with bad input.

- **Changed: coolant flow laws.** The module's coolant channels are laminar (Reynolds number about 3–550 for any plausible number of cells per channel; ribbon ports under 2 mm, plate channels 4 mm high). Up to v0.4.12 they used turbulent laws (h ∝ flow^0.8, Δp ∝ flow²).
  - h now depends only weakly on flow. Ribbon ports are fully developed within a few cells, so their h doesn't depend on flow. Plate channels are still developing (Lévêque): h ∝ flow^1/3. The exponent is set by `Coolant.h_flow_exponent`; the default comes from the cooling layout.
  - Pressure drop across the module channels ∝ flow (Hagen–Poiseuille); the rest of the loop (hoses, Re ≈ 4,000) stays ∝ flow².
  - Results at the 0.05 g/s reference flow are unchanged.
- **Changed: air flow laws.** The air crosses the array of cans, so it is cross-flow over a bank of cylinders (Re ≈ 1,200–5,000 on the can diameter). h ∝ v^0.6 (Žukauskas, staggered banks) and Δp ∝ v^1.8, with v ∝ flow / gap. This replaces h ∝ flow^0.8 / gap and Δp ∝ flow² / gap³ (v0.4.12). Results at 0.3 g/s and a 2 mm gap are unchanged.
- **Fixed: in-cell spread of plate designs was about 0.4 K low.** The coolest point was taken at the centre of the bottom layer, half a layer above the cooled face, so the spread depended on the grid: 5.35 / 5.75 / 5.95 K at 8 / 16 / 32 layers for the M50 at 1.5C. It is now taken on the roll's base face (and on the cooled can face for ribbons) and gives 6.14 K at every grid. The 2D model now matches the exact solution within 1 % (test tightened from 3 %).
- **Fixed: datasheet temperature warnings** compared the whole run's peak with the charging limit. A hot discharge followed by a cooler charge was reported as a charging breach. Each limit is now judged on the peak while that kind of current flows. The design studies' own limits were not affected.
- **Fixed: datasheet current limits.**
  - The Panasonic NCR18650PF's 10 A discharge and 1,375 mA charge limits were written as C-rates against the 2.9 Ah rating, but the model converts with this cell's measured 2.995 Ah, so they allowed 10.3 A and 1.50 A. They are now exact currents.
  - The LG MJ1 had no charge limits; it now has the product specification's 3.4 A and 45 °C.
- **Fixed: CLI input.**
  - Every numeric option is checked when parsed (flows, C-rates, cycles and margins > 0; SOC 0–1; ribbon contact (0, 1]). For example, `--c-rate 0` crashed and `--cycles 0` or `--r-margin -2` ran a full study.
  - Unknown cells, fillers and topologies, and invalid combinations, give a one-line error instead of a traceback.
- **Fixed, smaller:**
  - `compare_modules` measured the coolant rise from its first-step temperature rather than the inlet. That understated it whenever the coolant warmed in the first step, as chilled coolant does (4.4 K reported against 8.4 K for a 15 °C inlet at 1C).
  - "1 module designs" now reads "1 module design".
  - The PF road-trip name showed "0.459098C".
  - The forced-air error message used API wording.
  - The Coolant docstring said 13 L/min for a 4,400-cell pack; the example pack is 3,360 cells at 9.5 L/min.
  - The module advisor's docstring still described scoring on the outlet cell with an axial estimate.
  - `compare_modules` was missing from `packtherm.module.__all__`.
- **Checked, no change:**
  - Energy balance closes to 1e-11 in every layout.
  - A 2 s step is within 0.07 K of 0.5 s.
  - Ribbon angle grid converged (12 vs 24 slices: 0.01 K).
  - RT42 data-sheet values; M50 stoichiometry windows (the parameter set's initial state, a 4.2 V full charge; PyBaMM's own calculation assumes 4.4 V); chiller COP law; road-load power at 130 km/h (0.45C).
- **Effect on the examples.** M50 road trip at 35 °C: same three picks (air 39.5 °C, plate 40.4 °C, ribbon 39.2 °C); 23 of 39 designs feasible (was 24). A chilled plate at 0.05 g/s now fails on in-cell spread (5.3 K), as does a 0.05 g/s plate with RT42 at 1.5C (5.1 K).
- Docs: the README roadmap lists every version from v0.1. The README module table shows the corrected spreads (plate 6.1 K) and the flow finding (tripling the flow buys 0.8–1.0 K for 20× the pump power). BACKLOG is updated.

## 0.4.12

An audit of every documented command, message and claim, plus the documentation rebuilt around the module tool.

- **Fixed: crash on gaps below the ribbon minimum.** `packtherm design M50 ... --gaps 1.5 2 3` (the README example) failed with "Index contains duplicate entries": every gap under 3.5 mm widens to 3.5 mm for a ribbon, so the same design appeared several times. `ModuleStudy.designs()` now keeps one of each.
- **Fixed: air cooling did not depend on the gap.** Forced air now scales with the gap at fixed mass flow: h ∝ 2 mm / gap and pressure drop ∝ (2 mm / gap)³ (laminar channel, fixed Nusselt number; `AirFlow.gap_ref_mm`). A module sets the gap on its air flow. Results at the 2 mm default are unchanged.
- **Fixed: messages.**
  - A study with feasible designs that all fail the worst-case re-check said there was no feasible design; it now says "No robust design", lists each with its nominal and worst-case peak, and suggests what to change.
  - The chilled pull-down note appeared whenever a chilled bottom plate was in the sweep; it now appears only when one fails on uneven cooling.
  - `packtherm module --compare` printed the gap-widened note once per ribbon design, and its header showed the requested gap; the header now shows the gaps actually used, and the output has a `gap_mm` column.
- **Fixed: trade-off chart labels.** Pick labels could overlap each other and the legend when picks sat close together, and a long footnote ran off the edge. Picks are now numbered badges with a key under the plot, the legend sits below the axes, and the footnote wraps.
- **CLI:**
  - `packtherm design`: `--no-edge-cells` and `--wall-u`; progress line says which cells are simulated; clearer help for `--cell-to-cell-max` and `--cells-in-pack`.
  - `packtherm module --edge` runs the edge cells.
  - `packtherm cells` shows each cell's model (measured circuit, derived circuit or lumped DCIR); `R0_mOhm` renamed `DCIR_25C_mOhm`, with a note on what it is used for; capacity rounded.
- **Package:** the top-level docstring, `module.py` docstring and `pyproject.toml` description describe the module tool; project URLs added; `LG_M50_LUMPED`, `with_R0`, `PackHardware`, `hardware_mass_per_cell`, `Chiller`, `PlateGeometry`, `RibbonGeometry`, `Wall`, `compare_modules`, `ModuleDesign`, `ModuleStudy`, `run_module_study`, `DutyCycle` and `Requirements` exported.
- **Docs:**
  - README rebuilt around the module tool: design result first, then the 2D fields, then validation. Thesis-era results, figures and the version table moved to `docs/HISTORY.md` (`docs/history/`).
  - New figures: model picture with edge cells and the 2D slices; 2D temperature fields (`make_fields.py`); cold-weather validation before and after v0.4.10 (`make_validation_compare.py`); M50 circuit against the physics model (`validation/check_m50_ecm.py`, `make_m50_check.py`).
  - VALIDATION.md: 48 blind tests plus one calibration test (was "49 blind"); thermal median 0.60 K; new LG M50 section.
  - BACKLOG.md restructured into open items and a resolved log; stale items removed (pump efficiency, uniform ribbon contact, speed, licence).
  - Example studies regenerated.
- **Effect:** same picks; no result at the default 2 mm gap changes.

## 0.4.11
- **LG M50 equivalent circuit** (`cells.LG_M50_ECM`, now on `LG_M50`): derived, not measured. PyBaMM's DFN with the ORegan2022 parameter set (measured on the LG M50T, with temperature dependence) was run through synthetic HPPC tests at 25, 10, 0 and −10 °C, and the PF cell's circuit fitted to them (`validation/derive_m50_ecm.py`). OCV table `data/lgm50_oregan2022_ocv.csv`.
  - Pulse overpotential within 3.6–4.7 % (median) at every temperature; replay within 21–23 mV above 10 % SOC.
  - Irreversible heat within 0.94–1.13× of the DFN on 0.5–1.4C discharges and a pulsed profile at 0–25 °C; the lumped model it replaces was 0.92–1.42× (over-predicting pulsed loads by 24–42 %).
  - The M50 now stops at its voltage cut-off. The knee comes late in the cold (up to 0.75 Ah after the DFN at 0 °C 1.4C); the lumped model had no cut-off.
  - `LG_M50_LUMPED` (CLI key `M50-LUMPED`) keeps the previous model.
- **Fixed:** the worst-case resistance re-check only scaled the lumped R0, so for equivalent-circuit cells (the PF, now the M50) it did nothing. `cells.with_R0` now scales R0, the slow branch and the charge-transfer term together.
- **Effect:** same picks; M50 road-trip peaks 0.5–0.9 K lower.

## 0.4.10
- **Cold-weather cell model** (Panasonic NCR18650PF): two temperature laws identified from the 0.9 A discharge-and-rest steps between the HPPC pulse sets at 25, 10, 0 and −10 °C (identification data, not in the validation set; `identify_panasonic.cold_laws`):
  - the low-SOC rise grows in the cold (`ECM.Ea_soc`, 20.7 kJ/mol), so the voltage knee arrives earlier: the cold capacity loss;
  - the slow branch follows its own Arrhenius law (`ECM.Ea_Rd`, 26.8 kJ/mol) instead of the charge-transfer kinetics (45 kJ/mol), which made it about twice too large at 0 to −10 °C.
  - R_d and τ_d re-calibrated on the same single test with these laws (28.4 mΩ, 405 s).
- **Blind validation (48 tests), predictive mode:** within 1 K 79 % → 88 %; −20 °C median 1.28 → 0.73 K; cold voltage error 177/84/40 → 70/53/34 mV at −20/−10/0 °C; overall median 0.63 → 0.65 K. In the cold the model now under-predicts heat by 7–10 % (worst −3.5 K) where it used to over-predict (worst +3.4 K). Thermal mode unchanged.
- **Not changed:** NCA entropic heat. Published NCA/graphite profiles disagree on the sign over the SOC range that matters, so no curve is applied (see docs/VALIDATION.md).
- The four combinations of the two laws were compared on the blind tests before choosing; only the M50/MJ1-independent PF electrical model changes.

## 0.4.9
- **Side ribbon on a strip of the can** (`model2d.simulate_rtheta`, `model2d.Strip`): ribbons are now solved on a radius × angle grid (12 slices over half the circumference, by symmetry). The ribbon cools the can over its contact share; heat reaches it round the circumference along the spiral winding (in-plane conductivity, as along the height) and through the steel can (0.25 mm, 50 W/m·K, assumption). `simulate_module(..., n_theta=0)` keeps the radial model with the contact spread evenly.
- The 2D bottom-plate and ribbon grids share one solver core (`model2d._run`), which reports heat and sink flows per whole cell when the grid covers a symmetric part.
- **Checked:** a full wrap matches the radial model within 0.02 K; 12 and 24 slices agree within 0.05 K; quasi-steady heat into the coolant matches generation; energy balance < 1e-6 %.
- **Effect:** ribbon peaks rise 0.1–1.0 K and the in-cell spread 0.5–1.6 K (the far side of the can runs warm). All ribbon designs that passed still pass. At 1.5C the lowest-energy pick moves to the 0.05 g/s ribbon (the 0.02 g/s RT42 design no longer survives worst-case resistance). Road-trip study: about 3 minutes.

## 0.4.8
- **2D bottom-plate model** (`packtherm.model2d`): bottom plates are now solved on an axisymmetric radius × height grid (16 layers by default) with the winding's axial conductivity, the roll-end resistance, interface and coolant film at the base, an adiabatic top and, for edge cells, the module wall. Same enthalpy–Newton scheme as the radial model; the sparse factorisation is reused until a PCM node changes phase band, which makes it about 15× faster than refactorising every iteration. `simulate_module(..., nz=0)` keeps the v0.4.7 radial model with its quasi-steady axial estimate.
- **Checked** against the exact steady solution for a base-cooled cell (top and top-to-base spread within 1 % and 3 % at 8 and 16 layers), with PCM filler and with the edge wall; energy balance closes to 1e-6 %.
- **Effect:** at 1.5C the bottom-plate peaks fall 0.1–0.45 K and the in-cell spread 0.15–0.7 K (the estimate was conservative, as intended). New finding: a chiller pulling a hot-soaked pack down through its base opens top-to-bottom gradients of up to 6 K while it does so, so three chilled bottom-plate designs now fail the 5 K in-cell limit on the 35 °C road trip. Studies with bottom plates take about twice as long.

## 0.4.7
- **Coolant thermal mass:** the coolant held in each cell's share of the channel (`module.coolant_holdup_kg`, from the v0.4.3 plate and ribbon geometry, about 1 g per M50 cell) stores heat. Energy balance M·cp·dTc/dt = (ṁ·cp/frac)(T_in − Tc) + ΣG(T − Tc), solved implicitly each step, so the outlet coolant lags heat input by about M/ṁ (about 20 s at the reference flow). `simulate_module(..., coolant_mass=False)` restores the steady balance. The hardware mass model now uses the same holdup function.
- **Effect:** peaks on the long M50 duties move by under 0.1 K and recovery by about a minute; the term matters for short pulses and start-up.

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

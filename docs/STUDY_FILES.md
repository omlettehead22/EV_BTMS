# Study files

A study file describes a whole module design study in one YAML or JSON document. The command line, Python and (next) the API and web app all run the same document, so they cannot drift apart. `packtherm design --level module` builds the same document from its flags.

```bash
packtherm template --out study.yaml          # a commented file with every default
packtherm run study.yaml --out-dir results/  # results JSON, designs CSV, trade-off chart
```

```python
from packtherm.study import load_study

run = load_study("study.yaml").run()
doc = run.to_json()  # the results document
run.write("results/")  # the same three files as packtherm run
```

The smallest valid study:

```yaml
packtherm_study: 1
cell: M50
duty: {type: constant, c_rate: 1.5}
```

The examples in [`docs/examples/`](examples/) (`m50_roadtrip_35c.yaml`, `m50_discharge_1.5c_25c.yaml`, `m50_wltc3_35c.yaml`) are the studies behind the README, and each sits next to its results.

## Rules

- `packtherm_study` (the format version, currently `1`), `cell` and `duty.type` are required. Everything else is optional; defaults are those of `packtherm design`.
- Problems are reported together before anything runs, each naming its field, for example `design_space.coolant_flows_g_s[1]: must be > 0, got 0`. Rejected:
  - unknown keys and keys a duty type does not use;
  - wrong types (`true` is not a number);
  - NaN and infinity;
  - out-of-range values;
  - unknown cells and fillers.
- YAML is read with a safe loader; JSON is accepted as it is (`.json` files are parsed as JSON).
- `null` means "use the model's own value" where a key allows it (for example `requirements.T_max_C`).

## Top level

| Key | Type | Default | Meaning |
|---|---|---|---|
| `packtherm_study` | integer | required | Format version: `1` |
| `name` | text | none | Optional label, echoed in the results |
| `cell` | text or mapping | required | A library cell from `packtherm cells` (M50, M50-LUMPED, MJ1, PF, case-insensitive), a cell file (`my_cell.yaml`, relative to the study file), or a definition written inline ([below](#user-defined-cells)) |
| `mode` | `normal` / `fast` | `normal` | Numerical resolution ([FAST_MODE.md](FAST_MODE.md)) |
| `ambient_C` | number | 25 | Ambient temperature; also the coolant's radiator inlet |

## User-defined cells

A cylindrical cell described by its datasheet, inline under `cell:` or in its own file. A cell file works wherever a cell name does: `packtherm design my_cell.yaml ...`, `packtherm module my_cell.yaml ...`, and `cell: my_cell.yaml` in a study. A study's results carry the full definition. `packtherm cells my_cell.yaml` checks a file and shows the cell as PackTherm understands it, including its density, energy density, cold resistance rise and thermal properties.

```yaml
name: My 21700 cell
format: 21700
chemistry: NMC
capacity_Ah: 5.0
V_nominal: 3.6
mass_g: 69
DCIR_mOhm: 22
```

[`examples/user_cell_mj1.yaml`](examples/user_cell_mj1.yaml) is the LG MJ1 written this way; it gives exactly the library MJ1's results. [`examples/user_cell_lfp_26650.yaml`](examples/user_cell_lfp_26650.yaml) is an LFP power cell (Lithium Werks / A123 ANR26650M1-B) from its datasheet.

**Model.** The lumped resistance model, as for the library MJ1: heat from current and DC resistance, rising in the cold (Arrhenius) and at low charge, plus entropic heat. There is no voltage model, so no voltage cut-off and no constant-voltage charge taper: a charge runs at constant current to its target. Results are labelled "user-defined, lumped DCIR" and are less accurate than the validated cells.

| Key | Default | Meaning |
|---|---|---|
| `name` | required | Label |
| `format` | none | `18650` (18.4 × 65.0 mm), `21700` (21.1 × 70.1), `26650` (26.2 × 65.2) or `4680` (46.0 × 80.0); give this or both sizes |
| `diameter_mm`, `height_mm` | from `format` | Can size; override the nominal size with the measured one |
| `chemistry` | `NMC` | `NMC`: NMC/graphite jelly-roll properties and entropic heat (from the LG M50 data). `NCA`: the same jelly-roll properties, no entropic heat (published NCA profiles disagree). `LFP`: heat capacity 1100 J/kg·K, radial conductivity 0.35 W/m·K (about a third of NMC's), axial 31 W/m·K, all measured on whole cylindrical LFP cells, and graphite-dominated entropic heat; literature values, so lower confidence ([below](#lfp-cells)) |
| `capacity_Ah` | required | Rated capacity |
| `V_nominal` | required | Nominal voltage |
| `mass_g` | required | Mass, grams |
| `DCIR_mOhm` | required | **DC** resistance at 25 °C, mid charge, milliohms. Many datasheets give only the 1 kHz AC impedance, which is lower (A123's 26650 datasheet: 8 mΩ AC against 10 mΩ DC); using it under-predicts heat. If that is all you have, raise it, and say so in `source` |
| `DCIR_max_mOhm` | `DCIR_mOhm` | Datasheet maximum; the worst-case re-check uses it plus `options.r_margin` |
| `max_discharge_A`, `max_charge_A` | none | Datasheet current limits, checked against the duty. Without `max_charge_A`, charging is unchecked (a study note says so) and the road trip's rapid charge runs at 1C |
| `T_max_charge_C`, `T_max_discharge_C` | none | Datasheet temperature limits. The default peak limit is the lower of 45 °C and the charging limit (for a duty that charges) or the discharge limit |
| `cp_J_kgK`, `k_radial_W_mK`, `k_axial_W_mK` | jelly roll | Heat capacity and conductivities, if you have measured values |
| `Ea_kJ_mol` | 20 | How fast resistance rises in the cold (20 kJ/mol: about ×2.1 from 25 to 0 °C) |
| `entropic` | true | Entropic heat (NMC and LFP; NCA has none) |
| `source` | none | Where the values come from, echoed in the results |

**Checks.** Values no real cylindrical Li-ion cell has are errors, so a unit slip fails before anything runs. Each error names the likely slip:
- size outside 8–60 × 30–200 mm;
- density outside 1.5–4.0 g/cm³ (mass in kg instead of grams);
- nominal voltage outside 3.3–4.2 V for NMC and NCA, or 2.9–3.45 V for LFP (a cell around 3.2 V labelled NMC, or 3.6 V labelled LFP, is probably the wrong chemistry, and the error says so);
- energy density outside 100–1000 Wh/L (100–600 for LFP; capacity in mAh);
- resistance outside 0.5–500 mΩ (resistance in ohms);
- temperature limits outside 20–90 °C.

Unusual but possible values are warnings, shown by `packtherm cells` and written into the results notes:
- density outside 2.2–3.2 g/cm³ (LFP 1.9–2.7);
- voltage outside 3.4–3.8 V (LFP 3.1–3.35);
- more than 800 Wh/L (LFP 500);
- a current limit above 20C.

### LFP cells

- **Thermal properties** are from measurements on whole cylindrical LFP cells. Heat capacity is the mean of the cylindrical LFP entries in a 2022 meta-analysis (Steinhardt et al., *J. Power Sources* 522, 230829), leaving out two taken at full charge, which were higher. Radial conductivity is the median of those entries (range 0.15–0.51 W/m·K). Axial conductivity is from Drake et al. (*J. Power Sources* 252, 2014) on 26650 and 18650 LFP cells. Measured the same way, NMC cells have a median radial conductivity of about 1.1 W/m·K. PackTherm's calculated NMC value (1.23) sits close to it, so the LFP/NMC difference is the chemistry, not the method.
- **Entropic heat** comes from the graphite electrode, which dominates an LFP/graphite cell's entropy change. It uses the graphite fit behind the NMC profile and the graphite range of an A123 26650 LFP cell (PyBaMM `Prada2013`). It runs from −0.38 mV/K near empty to +0.06 mV/K near full. That is inside the −0.42 to +0.17 mV/K reported for LFP/graphite cells, and heat-absorbing on discharge from about 30 % charge, as measured. It understates the measured mid-charge peak, so mid-charge discharge heat is slightly overstated (the safe side for cooling design) and mid-charge charge heat slightly understated.
- **What it means for design:** radial conduction is poor, so a side ribbon or air leaves LFP cells with two to three times NMC's in-cell spread. A bottom plate draws heat along the axis, where LFP conducts well, so it does comparatively better.

## `duty`

| Key | Used by | Default | Meaning |
|---|---|---|---|
| `type` | all | required | `constant`, `wltc`, `roadtrip` or `segments` |
| `rest_h` | all | 3 | Rest simulated after the event, for recovery |
| `pack_kWh` | all | 60 | Pack size: sets the EV duties' current, and sizes pack-level cooling hardware |
| `c_rate` | constant | 1.0 | Current, in C (> 0) |
| `direction` | constant | `discharge` | `discharge` or `charge` |
| `soc0` | constant, segments | null | Starting SOC (0–1); null: the top of the SOC window for a discharge, the bottom for a charge (segments: 1) |
| `soc_min`, `soc_max` | constant, segments | 0, 1 | Current stops when SOC leaves this window (`soc_min` < `soc_max`) |
| `cycles` | wltc | 3 | WLTC Class 3b cycles back to back |
| `speed_kmh` | roadtrip | 130 | Motorway speed, driven from 90 % to 10 %, then a rapid charge to 80 % |
| `charge_c_rate` | roadtrip | null | Rapid-charge rate; null: the cell's maximum charge rate |
| `pack_V` | wltc, roadtrip | 350 | Pack voltage, for the series count |
| `steps` | segments | required | `[[duration_s, c_rate], ...]`; positive discharges, negative charges, 0 rests |
| `name` | segments | `custom segments` | Label for the duty |

## `requirements`

| Key | Default | Meaning |
|---|---|---|
| `T_max_C` | null | Peak limit for the hottest cell; null: the lower of 45 °C and the cell's datasheet limit |
| `dT_cell_max_C` | 5 | In-cell spread limit (> 0) |
| `recovery_max_min` | null | Ready again (near ambient, PCM re-frozen) within this time; null: within the rest window |
| `cell_to_cell_max_K` | null | Hottest-to-coolest cell limit; null: reported but not limited |

## `design_space`

Every combination is simulated (ribbons widen to their minimum gap; duplicates are dropped).

| Key | Default | Items |
|---|---|---|
| `topologies` | `[none, air, bottom, ribbon]` | `none` (sealed), `air` (forced air), `bottom` (cold plate), `ribbon` (side ribbon) |
| `air_flows_g_s` | `[0.15, 0.3, 0.6]` | Air per cell, > 0 |
| `coolant_flows_g_s` | `[0.02, 0.05]` | Liquid per cell, > 0 |
| `chiller_C` | `[15]` | Chiller set-points; `[]` for no chiller. Liquid designs always also run on the radiator, and set-points at or above `ambient_C` are skipped |
| `fillers` | `[none, RT31, RT42, RT31-EG]` | `none` or a grade from the PCM library (`-EG`: with expanded graphite) |
| `gaps_mm` | `[2]` | Gap between cans, ≥ 0 |
| `packing` | `hex` | `hex` or `square` |

## `options`

| Key | Default | Meaning |
|---|---|---|
| `edge_cells` | true | Also simulate cells on the module wall |
| `wall_U` | 5 | Module wall heat-transfer coefficient, W/m²K |
| `r_margin` | 0.2 | Worst-case resistance margin above the datasheet maximum, for the re-check of the picks |
| `chiller_cop` | null | Fixed chiller COP; null: from ambient (Carnot fraction) |
| `chiller_runs` | `event` | `event` (then the radiator takes over) or `always` |
| `liquid_loop_kg`, `air_system_kg`, `chiller_kg` | 3, 4, 4 | Pack-level hardware mass |

## Results document

`packtherm run` writes `<stem>_results.json` next to the designs CSV and the chart (`<stem>` is the name `packtherm design` uses). Format `packtherm_results: 1`, strict JSON (NaN and infinities become `null`):

| Key | Contents |
|---|---|
| `packtherm_results`, `packtherm_version` | Format and software version |
| `created`, `elapsed_s` | When it ran (UTC) and how long it took |
| `study` | The study as run, with every default filled in |
| `summary` | Cell, duty, mode, number of designs, feasible, on the trade-off front, the temperature limit, and the text summary |
| `picks` | `lightest`, `lowest_energy`, `balanced` (where they exist), each with every column of its design |
| `notes` | Warnings and notes from the study |
| `assumptions` | Resolution, coolant and air reference points, chiller, wall, resistance margin and pack-level parts |
| `designs` | Every design, one object per row of the designs CSV |

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
| `cell` | text | required | A cell from `packtherm cells` (M50, M50-LUMPED, MJ1, PF), case-insensitive |
| `mode` | `normal` / `fast` | `normal` | Numerical resolution ([FAST_MODE.md](FAST_MODE.md)) |
| `ambient_C` | number | 25 | Ambient temperature; also the coolant's radiator inlet |

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

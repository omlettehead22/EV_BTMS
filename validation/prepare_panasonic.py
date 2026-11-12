"""Build the processed validation set from the Panasonic NCR18650PF dataset.

Usage:
    python validation/prepare_panasonic.py /path/to/Panasonic-18650PF-Data

Source: P. Kollmeyer, "Panasonic 18650PF Li-ion Battery Data", Mendeley Data
v1 (2018), doi:10.17632/wykht8y7tg.1, licensed CC BY 4.0. The raw dataset
(~370 MB of .mat files) is not stored here; this script extracts the tests used
for validation, resamples them to 1 s bin means and writes compact gzipped CSVs
plus a manifest to validation/data/panasonic_18650pf/.

Selection
---------
* 25 degC 1C constant-current discharges: #1 calibrates the model, #2 validates.
* A 25 degC 1C CC-CV charge (after a full 1C discharge).
* Every single drive-cycle file at 25, 10, 0, -10 and -20 degC. Combined
  multi-cycle files, which also contain charges, are skipped: the README says
  they duplicate the single-cycle files.

Records that start with a long soak (cooling from the previous charge) are
trimmed to begin 60 s before the first current, by which time the cell has
equilibrated with the chamber. The starting SOC is then read from the rested
voltage through the OCV curve.

Ambient temperature: the logged chamber channel is used when it agrees with
the folder's setpoint (within 3 K). Otherwise the setpoint is used; the
channel reads a constant 0.0 in the -10 degC files and is empty in others.
"""

from __future__ import annotations

import gzip
import json
import re
import sys
from pathlib import Path

import numpy as np
import scipy.io as sio

OUT = Path(__file__).resolve().parent / "data" / "panasonic_18650pf"
FOLDERS = {
    25: "Panasonic 18650PF Data/25degC",
    10: "10degC",
    0: "0degC",
    -10: "-10degC",
    -20: "-20degC",
}
ROOT_OCV = Path(__file__).resolve().parents[1] / "src" / "packtherm" / "data" / "ncr18650pf_ocv.csv"
CAPACITY_C20 = 2.99491  # Ah, from the 25 degC C/20 test (see src/packtherm/data/ncr18650pf_ocv.csv)


def load(path: Path) -> dict[str, np.ndarray]:
    m = sio.loadmat(str(path), squeeze_me=True, struct_as_record=False)["meas"]
    keys = ("Time", "Voltage", "Current", "Ah", "Battery_Temp_degC", "Chamber_Temp_degC")
    d = {k: np.atleast_1d(getattr(m, k)).astype(float) for k in keys}
    ok = np.all([np.isfinite(v) for k, v in d.items() if k != "Chamber_Temp_degC"], axis=0)
    d = {k: v[ok] for k, v in d.items()}
    keep = np.concatenate([[True], np.diff(d["Time"]) > 0])
    return {k: v[keep] for k, v in d.items()}


def ambient(d: dict, setpoint: float) -> float:
    ch = d["Chamber_Temp_degC"]
    ch = ch[np.isfinite(ch)]
    if ch.size and abs(np.median(ch) - setpoint) < 3.0:
        return float(np.median(ch))
    return float(setpoint)


def bin_means(t: np.ndarray, y: np.ndarray, edges: np.ndarray) -> np.ndarray:
    """Exact means of the piecewise-linear signal y(t) over [edges[i], edges[i+1]]."""
    cum = np.concatenate([[0.0], np.cumsum(0.5 * (y[1:] + y[:-1]) * np.diff(t))])
    c = np.interp(edges, t, cum)
    return np.diff(c) / np.diff(edges)


def trim_soak(d: dict, lead_s: float = 60.0) -> dict:
    """Drop a pre-test soak: start ``lead_s`` before the first current if that is > 10 min in."""
    active = np.flatnonzero(np.abs(d["Current"]) > 0.05)
    if active.size and d["Time"][active[0]] - d["Time"][0] > 600.0:
        start = np.searchsorted(d["Time"], d["Time"][active[0]] - lead_s)
        d = {k: v[start:] for k, v in d.items()}
    return d


def soc_from_rest(d: dict) -> float:
    """SOC at the start from the rested voltage, if the record starts at rest (else 1.0)."""
    if abs(d["Current"][0]) > 0.05:
        return 1.0
    ocv = np.loadtxt(ROOT_OCV, delimiter=",", comments="#", skiprows=6)
    return float(np.clip(np.interp(d["Voltage"][0], ocv[:, 1], ocv[:, 0]), 0.0, 1.0))


def resample(d: dict, dt: float = 1.0) -> dict[str, np.ndarray]:
    t = d["Time"] - d["Time"][0]
    edges = np.arange(0.0, t[-1] + 1e-9, dt)
    mids = 0.5 * (edges[1:] + edges[:-1])
    return {
        "t": edges[:-1],
        "current_A": -bin_means(t, d["Current"], edges),  # dataset: discharge < 0; packtherm: discharge > 0
        "voltage_V": bin_means(t, d["Voltage"], edges),
        "T_cell_C": np.interp(mids, t, d["Battery_Temp_degC"]),
    }


def write(name: str, r: dict, meta: dict, manifest: list) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.csv.gz"
    with gzip.open(path, "wt", compresslevel=9) as f:
        f.write("t_s,current_A,voltage_V,T_cell_C\n")
        for row in zip(r["t"], r["current_A"], r["voltage_V"], r["T_cell_C"]):
            f.write(f"{row[0]:.0f},{row[1]:.4f},{row[2]:.4f},{row[3]:.2f}\n")
    manifest.append({"name": name, "file": path.name, **meta})
    print(
        f"{name:<22} {r['t'][-1] / 60:6.1f} min  ambient {meta['ambient_C']:6.2f} C  soc0 {meta['soc0']:.3f}  T0 {r['T_cell_C'][0]:6.2f}"
    )


def main(root: str) -> None:
    root = Path(root)
    manifest: list[dict] = []
    base25 = root / FOLDERS[25]
    cc = sorted((base25).glob("C20 OCV*/*"))
    for path, role, name in (
        (next(p for p in cc if "Dis1C_1" in p.name), "calibration", "25C_1C_discharge_1"),
        (next(p for p in cc if "Dis1C_2" in p.name), "validation", "25C_1C_discharge_2"),
    ):
        d = load(path)
        write(
            name,
            resample(d),
            {
                "setpoint_C": 25,
                "ambient_C": ambient(d, 25),
                "role": role,
                "kind": "cc_discharge",
                "soc0": 1.0,
                "source": path.name,
            },
            manifest,
        )

    # 1C CC-CV charge that follows the first 1C discharge (starts empty and warm).
    chg = next(p for p in cc if p.name.endswith("Charge2.mat"))
    d = load(chg)
    soc0 = 1.0 - float(d["Ah"].max() - d["Ah"].min()) / CAPACITY_C20
    write(
        "25C_1C_CCCV_charge",
        resample(d),
        {
            "setpoint_C": 25,
            "ambient_C": ambient(d, 25),
            "role": "validation",
            "kind": "cccv_charge",
            "soc0": round(max(soc0, 0.0), 4),
            "source": chg.name,
        },
        manifest,
    )

    combined = re.compile(r"(US06|HWFET|LA92|NN|UDDS)_(HWFET|UDDS|LA92|NN)")
    for setpoint, folder in FOLDERS.items():
        for path in sorted((root / folder).glob("Drive*/*.mat")):
            if combined.search(path.name):
                continue
            m = re.search(r"degC_(.+?)_Pan18650PF", path.name)
            cycle = m.group(1) if m else path.stem
            d = load(path)
            amb = ambient(d, setpoint)
            d = trim_soak(d)
            soc0 = round(soc_from_rest(d), 4)
            name = f"{setpoint}C_{cycle}".replace("-", "m")
            write(
                name,
                resample(d),
                {
                    "setpoint_C": setpoint,
                    "ambient_C": amb,
                    "role": "validation",
                    "kind": "drive_cycle",
                    "soc0": soc0,
                    "source": path.name,
                },
                manifest,
            )

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1))
    (OUT / "README.md").write_text(
        "# Panasonic NCR18650PF validation subset\n\n"
        "Processed from P. Kollmeyer, *Panasonic 18650PF Li-ion Battery Data*, Mendeley Data v1 (2018), "
        "doi:10.17632/wykht8y7tg.1, licensed **CC BY 4.0**. The tests were performed at the University of "
        "Wisconsin-Madison by Dr. Phillip Kollmeyer.\n\n"
        "Changes from the original: tests selected, non-finite and duplicate-time samples removed, resampled "
        "to exact 1 s bin means (current sign flipped so discharge is positive), battery case temperature "
        "interpolated at bin centres, ambient taken from the chamber channel only where it agrees with the "
        "setpoint. Generated by `validation/prepare_panasonic.py`.\n"
    )
    print(f"{len(manifest)} tests written to {OUT}")


if __name__ == "__main__":
    main(sys.argv[1])

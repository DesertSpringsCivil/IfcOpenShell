"""Saikei voxel benchmark harness — dense vs RLE, for the bSI Implementers Forum.

Measures the RLE occupancy/payload encoding (bonsai.tool.Voxel) against the dense
TM27 baseline across three realistic scenarios at increasing resolution, and
authors the actual IFC 4.4 sidecar (ifcopenshell.api.voxel) to report real
on-disk file sizes. Produces `Saikei_Voxel_Benchmark_Results.md` + a CSV.

Run with Blender's Python (needs the compiled ifcopenshell wrapper + numpy):

  PY="/c/Program Files/Blender Foundation/Blender5/5.0/python/bin/python.exe"
  export PYTHONPATH="$APPDATA/Blender Foundation/Blender/5.0/extensions/.local/lib/python3.11/site-packages"
  "$PY" spike_voxel/voxel_benchmark.py

Deterministic (seeded). tool.Voxel is loaded standalone (it is pure-numpy, no
bpy) so no Blender process is needed.
"""

import csv
import importlib.util
import os
import pathlib
import sys
import tempfile
import time

import numpy as np

import ifcopenshell.api.voxel as apivox

REPO = pathlib.Path(r"C:\GitHub\IfcOpenShell-saikei-dev")
REPORT_MD = REPO / "Saikei_Voxel_Benchmark_Results.md"
CSV_PATH = REPO / "spike_voxel" / "voxel_benchmark.csv"

# Load bonsai.tool.voxel standalone (pure numpy; avoids the bpy-laden package).
_spec = importlib.util.spec_from_file_location(
    "voxel_standalone", REPO / "src" / "bonsai" / "bonsai" / "tool" / "voxel.py"
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod  # dataclass annotation resolution needs this
_spec.loader.exec_module(_mod)
Voxel = _mod.Voxel

# Approx STEP serialized bytes per value token, by IfcValue kind. Dense storage
# is one token per cell; RLE storage is one token per run-pair element.
TOKEN_BYTES = {"bool": 3, "int": 2, "real": 6, "label": 8}  # '.T.,' / '0,' / '0.95,' / "'sand',"


# --------------------------------------------------------------------------- #
# Scene generators -> (label, counts, cell_size, occupancy_mask, payloads)
#   payloads: list of (name, values_1d, data_type)  where values are gathered
#   over occupied cells in X->Y->Z order (occupancy mode) or full grid (stratum).
# --------------------------------------------------------------------------- #


def gen_terrain(nx, ny, nz, cell):
    """Earthwork occupancy: soil below a gently undulating ground surface (~50% full)."""
    xs = np.arange(nx) * cell
    ys = np.arange(ny) * cell
    gx, gy = np.meshgrid(xs, ys, indexing="ij")
    depth = nz * cell
    # Surface near mid-depth with gentle multi-wavelength undulation.
    h = 0.5 * depth + 0.12 * depth * np.sin(2 * np.pi * gx / (nx * cell / 3)) \
        + 0.08 * depth * np.cos(2 * np.pi * gy / (ny * cell / 2))
    zc = (np.arange(nz) + 0.5) * cell
    mask = zc[None, None, :] < h[:, :, None]  # (nx,ny,nz) soil below surface
    return "terrain-bounded", (nx, ny, nz), cell, mask, []


def gen_geomodel(nx, ny, nz, cell):
    """Geomodel (stratum mode): all-TRUE box; horizontal strata + depth confidence."""
    mask = np.ones((nx, ny, nz), dtype=bool)
    # 5 horizontal strata by depth -> a label layer that collapses to ~5 runs.
    k = np.arange(nz)
    band = (k * 5 // nz).astype(np.int16)  # 0..4 by depth
    label_full = np.broadcast_to(band[None, None, :], (nx, ny, nz))
    label_vals = label_full.ravel(order="F")  # X->Y->Z; all occupied
    # Confidence: decreases with depth, quantized to 0.05 (banded -> compresses).
    conf = np.round(1.0 - 0.6 * (k / max(nz - 1, 1)), 2)
    conf_full = np.broadcast_to(conf[None, None, :], (nx, ny, nz))
    conf_vals = conf_full.ravel(order="F")
    return (
        "geomodel-stratum", (nx, ny, nz), cell, mask,
        [("MaterialCode", label_vals, "integer"), ("Confidence", conf_vals, "real")],
    )


def gen_noisy(nx, ny, nz, cell):
    """Contamination plume (differential sparsity): mostly-zero ppm with a blob."""
    mask = np.ones((nx, ny, nz), dtype=bool)
    cx, cy, cz = nx * 0.5, ny * 0.4, nz * 0.6
    gx, gy, gz = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij")
    r2 = ((gx - cx) / (nx * 0.12)) ** 2 + ((gy - cy) / (ny * 0.12)) ** 2 + ((gz - cz) / (nz * 0.2)) ** 2
    ppm = np.where(r2 < 1.0, np.clip(10 * (1.0 - r2), 0, 10).astype(np.int16), 0)
    ppm_vals = ppm.ravel(order="F")
    return "noisy-contamination", (nx, ny, nz), cell, mask, [("ContaminationPpm", ppm_vals, "integer")]


# --------------------------------------------------------------------------- #
# Benchmark one scene
# --------------------------------------------------------------------------- #


def bench(scene):
    label, counts, cell, mask, payloads = scene
    nx, ny, nz = counts
    cells = nx * ny * nz

    t0 = time.perf_counter()
    occ_rle = Voxel.encode_occupancy(mask)
    t_encode = time.perf_counter() - t0

    t0 = time.perf_counter()
    rebuilt = Voxel.decode_occupancy(occ_rle, nx, ny, nz)
    t_decode = time.perf_counter() - t0
    lossless = bool(np.array_equal(rebuilt, mask))

    occ_runs = len(occ_rle) // 2
    occ_ratio = cells / len(occ_rle) if occ_rle else float("inf")

    # Dense projected STEP bytes: occupancy (bool) + each payload (per kind).
    dense_bytes = cells * TOKEN_BYTES["bool"]
    rle_tokens = len(occ_rle)
    layer_stats = []
    payload_rle = []
    for name, vals, dtype in payloads:
        rle = Voxel.encode_runs(vals)
        payload_rle.append((name, rle, dtype))
        runs = len(rle) // 2
        ratio = len(vals) / len(rle) if rle else float("inf")
        layer_stats.append((name, dtype, len(vals), runs, ratio))
        dense_bytes += len(vals) * TOKEN_BYTES.get(dtype, 4)
        rle_tokens += len(rle)

    # Author the real IFC 4.4 sidecar and measure on-disk size.
    t0 = time.perf_counter()
    f = apivox.new_file()
    host, _ = apivox.create_voxel_earthwork(
        f, name=label, voxel_sizes=(cell, cell, cell), voxel_counts=counts, occupancy=occ_rle,
    )
    for name, rle, dtype in payload_rle:
        apivox.add_voxel_data(f, host, value_data=rle, data_type=dtype, name=name)
    fd, path = tempfile.mkstemp(suffix=".ifc")
    os.close(fd)
    f.write(path)
    t_write = time.perf_counter() - t0
    file_bytes = os.path.getsize(path)
    os.remove(path)

    return {
        "scenario": label,
        "dims": f"{nx}x{ny}x{nz}",
        "cells": cells,
        "occ_runs": occ_runs,
        "occ_ratio": occ_ratio,
        "layers": layer_stats,
        "dense_proj_mb": dense_bytes / 1e6,
        "rle_file_kb": file_bytes / 1e3,
        "file_vs_dense": dense_bytes / file_bytes if file_bytes else float("inf"),
        "t_encode_ms": t_encode * 1e3,
        "t_decode_ms": t_decode * 1e3,
        "t_write_ms": t_write * 1e3,
        "lossless": lossless,
    }


SCENARIOS = [
    lambda: gen_terrain(100, 100, 20, 1.0),
    lambda: gen_terrain(200, 200, 40, 0.5),
    lambda: gen_terrain(500, 500, 50, 0.5),
    lambda: gen_terrain(1000, 1000, 80, 0.5),   # 8e7 cells (~500m site @ 0.5m)
    lambda: gen_geomodel(100, 100, 50, 1.0),
    lambda: gen_geomodel(200, 200, 100, 0.5),
    lambda: gen_geomodel(400, 400, 100, 0.5),   # 1.6e7
    lambda: gen_noisy(100, 100, 50, 1.0),
    lambda: gen_noisy(200, 200, 100, 0.5),
]


def main():
    apivox.ensure_registered()
    rows = []
    for make in SCENARIOS:
        scene = make()
        print(f"  benchmarking {scene[0]} {scene[1]} ({np.prod(scene[1]):,} cells)...")
        rows.append(bench(scene))
        del scene

    _write_csv(rows)
    _write_report(rows)
    print(f"\nReport: {REPORT_MD}\nCSV:    {CSV_PATH}")


def _write_csv(rows):
    with open(CSV_PATH, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "scenario", "dims", "cells", "occ_runs", "occ_ratio",
            "dense_proj_mb", "rle_file_kb", "file_vs_dense",
            "t_encode_ms", "t_decode_ms", "t_write_ms", "lossless",
        ])
        for r in rows:
            w.writerow([
                r["scenario"], r["dims"], r["cells"], r["occ_runs"], f"{r['occ_ratio']:.1f}",
                f"{r['dense_proj_mb']:.2f}", f"{r['rle_file_kb']:.2f}", f"{r['file_vs_dense']:.0f}",
                f"{r['t_encode_ms']:.1f}", f"{r['t_decode_ms']:.1f}", f"{r['t_write_ms']:.1f}",
                r["lossless"],
            ])


def _write_report(rows):
    lines = []
    a = lines.append
    a("# Saikei Voxel Benchmark — Dense vs RLE")
    a("")
    a("Measured with `spike_voxel/voxel_benchmark.py` against `bonsai.tool.Voxel` "
      "(vectorized RLE) + `ifcopenshell.api.voxel` (real IFC 4.4 sidecar authoring). "
      "Deterministic/seeded. The dense column is **projected** STEP byte cost "
      "(one value token per cell) because the dense `Voxels: ARRAY OF IfcBoolean` "
      "form is *un-authorable* in IfcOpenShell (finding F2) — so RLE is both "
      "smaller **and** the only encoding that serializes.")
    a("")
    a("| Scenario | Grid | Cells | Occ. runs | Occ. ratio | Dense proj. | RLE file | File vs dense | Encode | Decode | Lossless |")
    a("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|:--:|")
    for r in rows:
        a("| {s} | {d} | {c:,} | {runs:,} | {orr:.0f}× | {dm:,.1f} MB | {fk:,.1f} KB | {fvd:,.0f}× | {te:.0f} ms | {td:.0f} ms | {ll} |".format(
            s=r["scenario"], d=r["dims"], c=r["cells"], runs=r["occ_runs"], orr=r["occ_ratio"],
            dm=r["dense_proj_mb"], fk=r["rle_file_kb"], fvd=r["file_vs_dense"],
            te=r["t_encode_ms"], td=r["t_decode_ms"], ll="✓" if r["lossless"] else "✗",
        ))
    a("")
    a("## Per-layer payload compression (semantic layers)")
    a("")
    a("| Scenario | Grid | Layer | Type | Values | Runs | Ratio |")
    a("|---|---|---|---|--:|--:|--:|")
    for r in rows:
        for name, dtype, nvals, runs, ratio in r["layers"]:
            a(f"| {r['scenario']} | {r['dims']} | {name} | {dtype} | {nvals:,} | {runs:,} | {ratio:,.0f}× |")
    a("")
    a("## Notes")
    a("")
    a("- **Occupancy ratio** = dense cell count ÷ RLE token count. Terrain-bounded "
      "grids compress on long uniform runs (soil below / air above), best where "
      "the surface is smooth; roughness raises run count.")
    a("- **Stratum mode**: occupancy is a trivial all-TRUE box (≈1 run); the "
      "information lives in the semantic layers. A homogeneous material/stratum "
      "layer collapses to ~one run per stratum boundary; a depth-banded scalar "
      "field compresses moderately.")
    a("- **Noisy/contamination**: differential sparsity — long clean runs plus a "
      "noisy plume region. RLE is a *per-layer* cost, not a uniform tax (spec §1.2).")
    a("- **Findings carried to the forum**: F1 `Voxels: ARRAY [1:?] OF IfcBoolean` "
      "→ parser resolves indeterminate ARRAY to UNKNOWN (use LIST); F2 list-of-"
      "boolean is un-authorable in the IfcOpenShell wrapper (dense mask can't be "
      "written) → RLE-as-integer is the only working occupancy encoding; F3 "
      "standalone defined-type value wrappers crash the registered schema → use "
      "direct attribute assignment.")
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()

# Saikei Voxel Benchmark — Dense vs RLE

Measured with `spike_voxel/voxel_benchmark.py` against `bonsai.tool.Voxel` (vectorized RLE) + `ifcopenshell.api.voxel` (real IFC 4.4 sidecar authoring). Deterministic/seeded. The dense column is **projected** STEP byte cost (one value token per cell) because the dense `Voxels: ARRAY OF IfcBoolean` form is *un-authorable* in IfcOpenShell (finding F2) — so RLE is both smaller **and** the only encoding that serializes.

| Scenario | Grid | Cells | Occ. runs | Occ. ratio | Dense proj. | RLE file | File vs dense | Encode | Decode | Lossless |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|:--:|
| terrain-bounded | 100x100x20 | 200,000 | 2,920 | 34× | 0.6 MB | 15.1 KB | 40× | 1 ms | 1 ms | ✓ |
| terrain-bounded | 200x200x40 | 1,600,000 | 11,634 | 69× | 4.8 MB | 58.6 KB | 82× | 5 ms | 8 ms | ✓ |
| terrain-bounded | 500x500x50 | 12,500,000 | 36,002 | 174× | 37.5 MB | 193.4 KB | 194× | 83 ms | 60 ms | ✓ |
| terrain-bounded | 1000x1000x80 | 80,000,000 | 115,130 | 347× | 240.0 MB | 668.2 KB | 359× | 885 ms | 410 ms | ✓ |
| geomodel-stratum | 100x100x50 | 500,000 | 1 | 250000× | 6.5 MB | 2.0 KB | 3,318× | 2 ms | 4 ms | ✓ |
| geomodel-stratum | 200x200x100 | 4,000,000 | 1 | 2000000× | 52.0 MB | 2.1 KB | 24,821× | 14 ms | 18 ms | ✓ |
| geomodel-stratum | 400x400x100 | 16,000,000 | 1 | 8000000× | 208.0 MB | 2.2 KB | 96,207× | 124 ms | 68 ms | ✓ |
| noisy-contamination | 100x100x50 | 500,000 | 1 | 250000× | 3.5 MB | 14.4 KB | 243× | 1 ms | 2 ms | ✓ |
| noisy-contamination | 200x200x100 | 4,000,000 | 1 | 2000000× | 28.0 MB | 58.8 KB | 477× | 15 ms | 19 ms | ✓ |

## Per-layer payload compression (semantic layers)

| Scenario | Grid | Layer | Type | Values | Runs | Ratio |
|---|---|---|---|--:|--:|--:|
| geomodel-stratum | 100x100x50 | MaterialCode | integer | 500,000 | 5 | 50,000× |
| geomodel-stratum | 100x100x50 | Confidence | real | 500,000 | 50 | 5,000× |
| geomodel-stratum | 200x200x100 | MaterialCode | integer | 4,000,000 | 5 | 400,000× |
| geomodel-stratum | 200x200x100 | Confidence | real | 4,000,000 | 61 | 32,787× |
| geomodel-stratum | 400x400x100 | MaterialCode | integer | 16,000,000 | 5 | 1,600,000× |
| geomodel-stratum | 400x400x100 | Confidence | real | 16,000,000 | 61 | 131,148× |
| noisy-contamination | 100x100x50 | ContaminationPpm | integer | 500,000 | 3,203 | 78× |
| noisy-contamination | 200x200x100 | ContaminationPpm | integer | 4,000,000 | 13,493 | 148× |

## Notes

- **Occupancy ratio** = dense cell count ÷ RLE token count. Terrain-bounded grids compress on long uniform runs (soil below / air above), best where the surface is smooth; roughness raises run count.
- **Stratum mode**: occupancy is a trivial all-TRUE box (≈1 run); the information lives in the semantic layers. A homogeneous material/stratum layer collapses to ~one run per stratum boundary; a depth-banded scalar field compresses moderately.
- **Noisy/contamination**: differential sparsity — long clean runs plus a noisy plume region. RLE is a *per-layer* cost, not a uniform tax (spec §1.2).
- **Findings carried to the forum**: F1 `Voxels: ARRAY [1:?] OF IfcBoolean` → parser resolves indeterminate ARRAY to UNKNOWN (use LIST); F2 list-of-boolean is un-authorable in the IfcOpenShell wrapper (dense mask can't be written) → RLE-as-integer is the only working occupancy encoding; F3 standalone defined-type value wrappers crash the registered schema → use direct attribute assignment.
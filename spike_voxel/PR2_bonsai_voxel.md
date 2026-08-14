# feat(voxel): Bonsai voxel earthwork + geomodel module

The Bonsai-side 3-layer module over `ifcopenshell.api.voxel` — a working voxel
earthwork + geomodel tool with a viewport UI. Pivots civil volumetrics from the
boundary/prismoidal method to occupancy voxels (TM27).

**Depends on** the `api.voxel` PR (and the surface / earthwork Bonsai stack):
`tool.Voxel` uses `tool.Surface.z_at`; QTO delegates to `api.earthwork`.

## Layers
- **tool.Voxel** — vectorized RLE codec + TM27 occupancy ordering (X→Y→Z, scales
  to 1e8 cells); voxelization from TINs (cell-centre test + N×N supersampling);
  cut/fill as occupancy set-ops on a shared lattice; stratum classification from
  a stack of boundary surfaces + `stratum_volume` queries; per-stratum excavation
  (cut ∩ strata → quantities by material); disposable Blender cube-mesh previews.
- **core.voxel** — orchestration (voxelize, compute/author cut-fill, geomodel,
  per-stratum), type-injected tools, math-free.
- **bim/module/voxel** — `CIVIL > Voxel Earthwork` tab: cut/fill, geomodel
  strata, single-surface occupancy, excavation-by-stratum, author IFC 4.4
  sidecar; property group + 6 operators + 4 panels.

## Correctness
- Cut/fill cross-validated against the analytic prism volume (exact on
  cell-aligned geometry; provably converges as cell size shrinks).
- Per-stratum excavation validated to sum back to the total cut.
- 108 tests (92 tool via pytest-blender + 16 core). Combined voxel suite
  (incl. `api.voxel`): 130 green.

## Notes
- Voxel grids are a **derived/analysis** representation in a separate IFC 4.4
  sidecar; the production model stays IFC4X3_ADD2 (TIN remains source of truth).
- Targets the unreleased IFC 4.4 (pinned prototype schema); see the `api.voxel`
  PR for schema details and findings F1–F3.

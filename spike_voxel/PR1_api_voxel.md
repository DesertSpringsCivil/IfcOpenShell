# feat(api.voxel): IFC 4.4 TM27 voxel authoring (prototype)

Adds `ifcopenshell.api.voxel` — a high-level API for authoring IFC 4.4 TM27 voxel
entities (`IfcVoxelGrid` + the `IfcVoxelData` family) into an analysis sidecar.
Mirrors the `api.surface` / `api.earthwork` style (file-per-function, no Blender).

## What's included
- `_schema` — registers a prototype `IFC4X4_TM27` at runtime by appending a small
  TM27 entity **delta** to a base `IFC4x3` longform `.exp` (located via
  `SAIKEI_IFC4X3_BASE_EXP` or a sibling `IFC4.x-development` checkout). The merged
  schema is **generated, not vendored** — this package carries only the ~50-line
  delta, not a copy of buildingSMART's schema.
- `add_voxel_grid_representation` — `IfcVoxelGrid` Body/Tessellation rep.
- `add_voxel_data` — the five `IfcVoxelData` subtypes + `IfcRelAssignsToProduct`.
- `create_voxel_earthwork` / `create_voxel_geomodel` — `IfcEarthworksCut/Fill` and
  `IfcGeomodel` hosts.
- `write_earthwork_quantities` — `Qto_Earthworks*BaseQuantities` (delegates to
  `api.earthwork`).
- 22 round-trip tests (`test/api/test_voxel.py`); they **skip** when no base `.exp`
  is configured.

## Why RLE-integer occupancy (findings worth flagging)
- **F1** `Voxels : ARRAY [1:?] OF IfcBoolean` resolves to UNKNOWN in IfcOpenShell's
  express parser; `LIST [1:?]` parses.
- **F2** the wrapper has no setter/getter for a list-of-boolean attribute, so the
  dense occupancy mask is **un-authorable**; a list-of-integer round-trips. We
  therefore store occupancy as RLE integer run-pairs (`[count, value, …]`,
  value 1 = occupied).
- **F3** creating a standalone defined-type value wrapper (e.g. `IfcIdentifier`
  for a Pset `NominalValue`) crashes the registered schema; we use direct
  attribute assignment.

## Status / caveats
- Targets the **unreleased** IFC 4.4 (TM27, PR #1110); schema is **pinned** and
  labelled `IFC4X4_TM27`. Files are an **analysis sidecar**, not production
  exchange — they won't validate in third-party tools.
- `register_schema` is the experimental runtime-schema path.
- **Depends on** `ifcopenshell.api.earthwork` (and the surrounding civil API
  stack). To run the tests, set `SAIKEI_IFC4X3_BASE_EXP` to an `IFC4x3_RC4`
  longform `.exp`.

Foundation for the companion Bonsai voxel-module PR.

# Saikei Voxel — 3D Tiles 2.0 / glTF Landscape (background note)

**Status:** Background/project-knowledge note from an IFC Implementers Forum
follow-up (researched 2026-06-18). NOT part of the build spec. Companion to
`Saikei_Voxel_RLE_BuildSpec.md`. Captures how the OGC 3D Tiles 2.0 / Khronos
glTF voxel track relates to the Saikei IFC TM27 + RLE plan.

---

## TL;DR

3D Tiles 2.0 voxels are **the delivery/visualization layer, not a competitor**
to IFC TM27. IFC is the authoritative semantic *source/exchange* (compact,
self-contained, RLE); 3D Tiles/glTF is the streaming *runtime* format
(dense-per-tile + octree LOD). They are complementary stages of one pipeline.
The commercial momentum is in **our exact domain (geotech subsurface)** —
bedrock.engineer and swisstopo are shipping it — and **nobody emits IFC-native
geotech voxels yet.** That gap is Saikei's positioning.

## Where the spec actually lives (the shared link is a stub)

`CesiumGS/3d-tiles` `next/2.0` is just a README. The real voxel spec is split,
and everything is **draft, in the Cesium fork, not yet ratified by Khronos**:

| Piece | Location | Role |
|---|---|---|
| `3DTILES_content_voxels` | CesiumGS/3d-tiles @ branch `voxels` | tileset-level pointer/declaration |
| `EXT_primitive_voxels` | CesiumGS/glTF @ branch `primitive-voxels` (PR #69 merged) | per-tile payload; glTF primitive mode `0x7FFFFFFF` |
| `EXT_structural_metadata` | CesiumGS/glTF | per-cell attributes (one accessor per field) |

Only `EXT_meshopt_compression` is in the upstream KhronosGroup/glTF registry. The
rest are **proposed**. "OGC Community Standard later this year (2026)" is
plausible/on-track but has **no documented adoption date**; CesiumJS 1.127 ships
a voxel *tiler* tech-preview. Cite as *draft/proposed* at the forum.

## Encoding contrast (the load-bearing point)

| | IFC TM27 + Saikei RLE | 3D Tiles 2.0 / glTF |
|---|---|---|
| Per-tile occupancy | RLE-sparse within the grid | **dense** (one value/cell incl. padding halo) |
| Cross-region sparsity | one grid (RLE collapses uniform runs) | **octree** implicit tiling + LOD streaming |
| Empty cells | not stored (run skips) | stored as `noData` sentinel |
| Compression | semantic RLE inline in STEP | buffer layer (meshopt/Draco/sparse accessors); no RLE in data model |
| Optimized for | archival / exchange / self-contained file | GPU streaming / web rendering |

RLE-vs-dense is **not a contradiction** — it is the build-spec §7.2
inline-vs-external (archival-vs-streaming) fork. Bridging IFC→3D Tiles means
expanding RLE to dense `noData` arrays, octree-tiling, and re-compressing at the
buffer layer.

## Domain/range split holds in a third standard (extends build-spec §7.1)

| Layer | "where" | "what" |
|---|---|---|
| IFC TM27 | `IfcVoxelGrid` | `IfcVoxelData` (one per attribute) |
| OGC CIS | `domainSet` | `rangeSet` / `rangeType` |
| 3D Tiles / glTF | `EXT_primitive_voxels` grid | `EXT_structural_metadata` property attributes (one accessor per field) |

TM27's one-attribute-per-layer maps 1:1 onto glTF's one-accessor-per-attribute.

## Who's shipping it (geotech)

- **bedrock.engineer** (Jules Blom, ex-Arup) — GeoTOP (Dutch national geomodel,
  NetCDF, 100×100×0.5 m cells, lithology + stratum per cell) → in-house Python →
  3D Tiles 2.0 draft voxels → CesiumJS. Converter is **closed**. Open repos
  (github.com/bedrock-engineer) are geotech *data* tooling: `bedrock-ge`
  (Apache-2.0), GEF/BRO parsers, **`ifc-georeferencer`**. Lists IFC as supported
  but the voxel pipeline has **no IFC voxel representation**.
- **swisstopo** — `swisstopo/swissgeol-viewer-suite` (BSD-3): production voxel
  layers via Cesium ion.

## Key repos

- https://github.com/CesiumGS/3d-tiles (branch `voxels`; also `specification/Metadata` Binary Table Format)
- https://github.com/CesiumGS/glTF (branch `primitive-voxels`: `EXT_primitive_voxels`, `EXT_structural_metadata`)
- https://github.com/CesiumGS/cesium (CesiumJS `VoxelPrimitive`, `Cesium3DTilesVoxelProvider`, v1.127)
- https://github.com/CesiumGS/cesium-native (C++ schema/parse classes)
- https://github.com/bedrock-engineer (geotech data tooling; voxel converter not public)
- https://github.com/swisstopo/swissgeol-viewer-suite

## Implications for the plan (deferred; not acted on)

1. Add a 3D Tiles / glTF row to build-spec §7 alignment table.
2. Add a 3D Tiles 2.0 export target alongside CIS (later phase): IFC RLE → dense
   `noData` arrays → `EXT_primitive_voxels` + `EXT_structural_metadata`, octree-tiled.
3. Forum framing: lead with the gap ("geotech voxels stream today but have no
   IFC-native source"); the glTF track is more concrete/commercial than HSML.

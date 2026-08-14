# Saikei Build Spec — RLE-Encoded Voxels as a TM27 Extension

**Status:** Design spec for implementation and forum testing. Companion to
`IFC44_Voxels_TM27_Reference.md` (schema-as-proposed) and `IFC44_Voxels_TM27_RawDocs.md`.

**Thesis.** Implement run-length-encoded (RLE) occupancy and payloads as a Saikei-side
extension of IFC 4.4 TM27 (PR #1110), because RLE is the only encoding that simultaneously:
1. reuses the PR's existing compact-list + derived-array pattern (`IfcListToExpandedArray`);
2. serializes natively in STEP/IFC with no external binary references (self-contained file);
3. maps directly onto the OGC Coverage Implementation Schema (CIS) `rangeSet` for web delivery;
4. stays semantically transparent for HSML / IEEE 2874 graph integration.

Octree compresses comparably but has no native home in CIS (a tree must be flattened to a grid
on export) and serializes poorly in STEP. VDB/Zarr is the superior technology but aligns with
IFC only as an *external referenced blob*, breaking the self-contained-file principle. RLE is the
defensible middle that wins on the constraints that actually bind: STEP-fit, pattern-reuse,
standards-alignment, transparency.

**Build-then-report goal:** ship this in Saikei, generate real serialized models, benchmark
against the dense TM27 baseline, and bring measured numbers + this rationale to the bSI
Implementers Forum ahead of the IFC 4.4 NWI (est. Aug/Sep 2026).

---

## 1. Conceptual foundation

### 1.1 Geometric vs. semantic voxels
- **Geometric voxel** = occupancy only ("is this cell full?"). One bit. Drives cut/fill.
- **Semantic voxel** = occupancy + attributes ("full, medium-dense sand, 18% moisture,
  0.7 confidence"). Same geometry; richer cell.
- TM27 expresses this exactly: `IfcVoxelGrid` carries the geometric occupancy mask; each
  attached `IfcVoxelData` carries one *homogeneous* semantic layer.

### 1.2 One attribute per layer (not one record per cell)
TM27 keeps each attribute in its own `IfcVoxelData` rather than a struct-per-cell. Reasons,
all of which the RLE design depends on:
- **Compression**: a homogeneous layer (a million sand labels) RLE-collapses to almost nothing;
  a million mixed structs do not.
- **Independence**: add/drop a layer without rewriting others.
- **Differential sparsity**: the contamination layer may be sparse (values near a spill only)
  while the material layer is dense — each layer is encoded on its own terms.
- **Consequence for this spec:** RLE is applied **per layer**. Uniform layers cost almost
  nothing; noisy layers cost more. This is a feature, not a uniform tax.

### 1.3 Two volume modes (critical modeling distinction)
- **Occupancy mode** (earthwork): cells are soil or air. Volume of soil = count(TRUE) × cell vol.
  Cut/fill = set-difference between existing-state and design-state grids. The occupancy mask
  carries the information.
- **Stratum/label mode** (geomodel): everything in the modeled box is "full"; occupancy is a
  trivial bounding box of all-TRUE. The information lives in the semantic layers. Volume of a
  *particular* stratum = count(cells where material-layer == target) × cell vol — a **semantic
  query**, not a geometric one.

Saikei MUST track which mode a grid is in. "Volume" means different things in each, and the
QTO code path differs (geometric count vs. label-filtered count).

---

## 2. Architecture in Saikei

Layered, consistent with the established Saikei principle that **IFC is the sole source of truth
and Blender objects are disposable derived caches**.

```
┌─────────────────────────────────────────────────────────────────┐
│ Saikei business-logic layer (civil semantics, QTO, mode tracking) │
│   - voxelization of TINs / solids -> occupancy + semantic layers  │
│   - volume queries (occupancy mode / stratum mode)                │
│   - cut/fill as grid set-ops                                       │
│   - RLE codec (encode on write, expand on read)                   │
└───────────────┬───────────────────────────────────┬───────────────┘
                │ writes/reads IFC                  │ regenerates
                ▼                                   ▼
┌──────────────────────────────┐     ┌──────────────────────────────┐
│ IFC layer (source of truth)  │     │ Blender cache (disposable)    │
│   IfcVoxelGrid + IfcVoxelData │     │   voxel preview mesh / volume │
│   RLE-encoded arrays          │     │   regenerated from IFC        │
└──────────────────────────────┘     └──────────────────────────────┘
                │ export
                ▼
┌──────────────────────────────────────────────────────────────────┐
│ Interop layer  (OGC CIS coverage  /  HSML cellular-space entity)  │
└──────────────────────────────────────────────────────────────────┘
```

The IfcOpenShell alignment-API split still applies elsewhere in Saikei; voxels are a parallel
representation concern living in the business-logic layer and persisted through the IFC layer.

---

## 3. The RLE encoding design

### 3.1 Why RLE fits the TM27 pattern
TM27 already separates **stored compact form** (`ValueData`, a `LIST`) from **derived dense form**
(`Values`, an `ARRAY`), reconstructed by `IfcListToExpandedArray` driven by the occupancy mask.
RLE is the same idea applied to the *occupancy mask itself*, which TM27 currently leaves dense.

The gap being closed: `IfcVoxelGrid.Voxels : ARRAY [1:?] OF IfcBoolean` is O(Nx·Ny·Nz),
uncompressed. For a 500 m site at 0.5 m that is ~2×10⁸ boolean tokens (~800 MB serialized).
RLE collapses the long uniform runs that dominate terrain-bounded and stratum models.

### 3.2 Encoding model
Encode each array (occupancy mask AND each payload's `ValueData`) as a **run list**: a sequence
of (value, count) pairs over the canonical X→Y→Z cell order.

```
Dense:   T T T T F F F F F T T          (11 cells)
RLE:     (T,4) (F,5) (T,2)              (3 runs, 6 tokens)
```

For payloads in **occupancy mode**, the payload only stores values for TRUE cells (per TM27),
so payload RLE runs over the *gathered* list, not the full grid. For **stratum mode** (mask all
TRUE), payload runs over the full grid directly.

### 3.3 Serialization strategy (two options, pick per forum guidance)

**Option A — Saikei-local convention over stock TM27 (no schema change).**
Store the RLE run list inside the existing TM27 fields by treating them as a typed pair-stream,
plus a property-set flag marking the encoding. No new entities; maximal compatibility; works
against the PR exactly as drafted. Downside: a naive TM27 reader sees pair-encoded data and must
honor the flag. Good for *immediate* prototyping and benchmarking.

**Option B — proposed schema extension (the forum ask).**
Introduce optional encoding metadata so the array semantics are explicit and standard, e.g.:
- An `Encoding` enumeration on `IfcVoxelGrid` / `IfcVoxelData`:
  `DENSE` (current behavior) | `RLE`.
- When `RLE`, the `Voxels` / `ValueData` list is interpreted as alternating
  (count, value, count, value, …) or as paired runs.
- A derived-function update so `IfcListToExpandedArray` (or a sibling
  `IfcRunLengthToExpandedArray`) reconstructs the dense `ARRAY [1:GridSize] OF OPTIONAL <T>`.

Option B is the clean long-term design and the substance of the review comment. Option A lets
Saikei generate test files *now* without waiting on schema acceptance. **Recommended path:
implement A for benchmarking, propose B with the measured results.**

### 3.4 Reference codec (Python / IfcOpenShell-adjacent)

```python
from itertools import groupby

def rle_encode(seq):
    """Dense sequence -> list of (value, count) runs."""
    return [(val, sum(1 for _ in grp)) for val, grp in groupby(seq)]

def rle_decode(runs):
    """List of (value, count) runs -> dense list."""
    out = []
    for val, count in runs:
        out.extend([val] * count)
    return out

def rle_flatten(runs):
    """Runs -> flat alternating [count, value, count, value, ...] for STEP storage."""
    flat = []
    for val, count in runs:
        flat.extend([count, val])
    return flat

def rle_unflatten(flat):
    """Flat alternating stream -> runs."""
    return [(flat[i + 1], flat[i]) for i in range(0, len(flat), 2)]

def compression_ratio(seq):
    dense = len(seq)
    runs = len(rle_encode(seq))
    return dense / (runs * 2) if runs else float("inf")
```

Occupancy mask round-trip:
```python
mask = [bool(v) for v in grid.Voxels]          # dense from a DENSE grid
runs = rle_encode(mask)                          # encode
stored = rle_flatten(runs)                        # store in IFC (Option A/B)
# ... later, on read ...
mask2 = rle_decode(rle_unflatten(stored))         # expand
assert mask == mask2
```

---

## 4. IFC entity wiring

### 4.1 Geometric grid (occupancy mode)
```
IfcEarthworksElement / host product
  └─ Representation -> IfcShapeRepresentation ('Body', 'Voxel')
        └─ Items[1] = IfcVoxelGrid
             VoxelSizeX/Y/Z, NumberOfVoxelsX/Y/Z
             Voxels  (RLE-encoded per §3 when Encoding=RLE)
```

### 4.2 Semantic layers (one IfcVoxelData per attribute)
```
IfcVoxelData subtype  (e.g. IfcLabelVoxelData for material)
  ├─ HasAssignments -> IfcRelAssignsToProduct -> host product (exactly one; TM27 WHERE rule)
  ├─ Representation  -> same IfcShapeRepresentation containing the IfcVoxelGrid
  ├─ ValueType       -> optional IfcLabel naming the value select-type
  └─ ValueData       -> RLE-encoded payload (gathered in occupancy mode; full in stratum mode)
```

TM27 WHERE rules to honor on write: exactly one `IfcRelAssignsToProduct`; exactly one
`IfcShapeRepresentation` whose single item is an `IfcVoxelGrid`; assigned product carries that
same representation; `GridSize = SIZEOF(grid.Voxels)`.

### 4.3 Layer roster for civil/geotech
| Layer | Entity | Mode | Notes |
|---|---|---|---|
| Occupancy | `IfcVoxelGrid.Voxels` | both | bounding box (all-TRUE) in stratum mode |
| Material / stratum | `IfcLabelVoxelData` | stratum | the primary geomodel field |
| Density | `IfcRealVoxelData` + Unit | both | kg/m³ |
| Moisture / scalar field | `IfcRealVoxelData` + Unit | both | % or domain unit |
| Confidence | `IfcRealVoxelData` | both | 0–1 interpolation certainty |
| Flow / displacement | `IfcVectorVoxelData` + Unit | both | per-cell vector (x,y,z) |

---

## 5. Volume query modes

### 5.1 Occupancy-mode volume + cut/fill
```python
import numpy as np

def occupancy_volume(grid, mask3d):
    vcell = grid.VoxelSizeX * grid.VoxelSizeY * grid.VoxelSizeZ
    return int(mask3d.sum()) * vcell

def cut_fill(existing_mask, design_mask, grid):
    """Both masks on the SAME lattice (origin, sizes, counts identical)."""
    vcell = grid.VoxelSizeX * grid.VoxelSizeY * grid.VoxelSizeZ
    cut  = int((existing_mask & ~design_mask).sum()) * vcell   # soil -> air
    fill = int((~existing_mask & design_mask).sum()) * vcell   # air  -> soil
    return {"cut": cut, "fill": fill, "net": fill - cut}
```
INVARIANT: cut/fill requires a shared lattice. Saikei MUST voxelize existing-ground and
design-surface into the *same* grid definition, or resample before differencing. Enforce as a
precondition check.

### 5.2 Stratum-mode volume (semantic query)
```python
def stratum_volume(grid, label_layer_values, target_label):
    """label_layer_values: dense list aligned to cells (X->Y->Z), e.g. from rle_decode."""
    vcell = grid.VoxelSizeX * grid.VoxelSizeY * grid.VoxelSizeZ
    count = sum(1 for v in label_layer_values if v == target_label)
    return count * vcell
```
This is the geomodel QTO path: "how much clay is in this model" = label-filtered cell count ×
cell volume. Distinct from occupancy volume; surface both in the Saikei QTO UI with clear naming.

---

## 6. Voxelization (TIN/solid -> occupancy grid)

Saikei already has boundary-based earthwork (TIN via `IfcTriangulatedIrregularNetwork`,
`IfcEarthworksCut`/`Fill`, `Qto_Earthworks*BaseQuantities` incl. Undisturbed vs. Loose volume).
Voxelization consumes those surfaces; it does not replace them.

Rasterization rule (baseline): for each cell, test whether the cell **centre** lies below the
surface -> TRUE (soil). Document the known bias (a partly-filled boundary cell counts as wholly
in or out). Optional precision upgrades, in priority order:
1. **Supersampling** boundary cells (N sample points, majority vote) — reduces bias, same schema.
2. **Partial-occupancy layer**: carry fraction-filled per boundary cell as an
   `IfcRealVoxelData` layer (0–1), enabling sub-cell-accurate volume without changing occupancy
   semantics. Flag this as a candidate forum discussion point (boolean mask vs. fractional).

Treat the voxel grid as a **derived/computed** representation: TIN / `IfcSectionedSolidHorizontal`
remain the parametric source of truth, consistent with the surface-vs-solid boundary already
established for superelevation. The grid is computed *from* the model for volumetrics; never the
authoritative geometry.

---

## 7. Standards-alignment rationale (the forum case)

### 7.1 The structural insight
The domain/range split appears at every layer, which is why alignment is natural rather than
forced:

| Layer | "where" | "what" |
|---|---|---|
| IFC 4.4 / TM27 | `IfcVoxelGrid` | `IfcVoxelData` (one per field) |
| OGC CIS | `domainSet` | `rangeSet` + `rangeType` (named fields/bands) |
| HSML / IEEE 2874 | cellular-space positions | typed attributes in the Universal Domain Graph |

### 7.2 OGC CIS alignment (verified against the live standard)
- **domainSet ↔ IfcVoxelGrid**: CIS regular grid = origin + per-axis spacing + extent. This is
  exactly `VoxelSize*` + `NumberOfVoxels*`. No method choice required; the standards already agree.
- **rangeSet ↔ payload**: the CIS `rangeSet` serializes as a `dataBlock` with a flat `values`
  array, and may be stored **inline** in the CIS document or **referenced externally** in a binary
  format (NetCDF/GeoTIFF/raw). That inline-vs-external choice IS the RLE-vs-VDB fork: RLE keeps
  values inline and self-contained (matching IFC's philosophy); VDB/Zarr would be the external
  blob path. A sequential `values` array is precisely what per-layer RLE expands into.
- **rangeType ↔ semantic layers**: CIS `rangeType` describes one or more **fields** (a.k.a. bands /
  channels / variables) per position. Saikei's stack of `IfcVoxelData` layers maps onto CIS as a
  multi-field coverage — the exact thing CIS was built for (e.g. multi-band imagery). Material +
  density + confidence = three rangeType fields, not three coverages.
- **Why not octree for CIS**: coverages are grid/array structures, not trees. An octree-encoded
  voxel grid must be flattened to a regular grid on CIS export, discarding the hierarchy that made
  it compact. Poor alignment.

Export target: a Saikei voxel model -> CIS-encoded coverage (domainSet from the grid, rangeSet
per layer with RLE expanded to the CIS `values` block or carried as run pairs, rangeType from the
layer roster). Deliverable over OGC API – Coverages / 3D GeoVolumes.

### 7.3 HSML / IEEE 2874 alignment
HSML is a *semantic* standard (machine-readable meaning in a graph; "cellular" is one of its
supported spatial structures). Implications:
- A purely geometric voxel is near-invisible to HSML; a **semantic** voxel is exactly what it
  wants — each layer becomes a typed property in the Universal Domain Graph, linkable to
  controlled vocabularies (a stratum label -> a geology ontology term; a confidence value ->
  provenance about the source borehole interpolation).
- HSML favors **semantically transparent, self-describing** encodings: a run-length list is
  readable; an octree is a traversal structure; a VDB blob is opaque. HSML's preference points the
  same direction as CIS — toward RLE.
- Ingestion connection: converting unstructured geotech docs/CAD into compliant HSML is the same
  shape as an ingestion pipeline parsing borehole logs and emitting labeled voxel layers. The
  semantic voxel is the bridge between Saikei's IFC authoring and an HSML-described spatial web.

(Reference correction for notes: the Spatial Web standard is **IEEE 2874**, HSML/HSTP — not 2784.)

---

## 8. Build phases

1. **Codec + occupancy (Option A).** Implement RLE encode/decode; write/read RLE occupancy in
   stock TM27 fields behind a Pset flag. Round-trip tests.
2. **Voxelization.** TIN/solid -> occupancy grid (centre test + supersampling). Enforce
   shared-lattice invariant.
3. **Occupancy QTO.** Volume + cut/fill as grid set-ops; wire into Saikei QTO UI alongside
   existing TIN-difference earthwork numbers (cross-validate the two).
4. **Semantic layers.** `IfcLabelVoxelData` material + `IfcRealVoxelData` density/confidence,
   each RLE-encoded; stratum-mode volume query.
5. **Benchmark harness.** Generate representative terrain-bounded and stratum grids; serialize
   dense vs. RLE; report byte counts + access timings. This produces the forum numbers.
6. **CIS export.** Map grid+layers -> CIS coverage (domainSet/rangeSet/rangeType); validate a
   round-trip to a CIS reader.
7. **Forum package.** Option B schema-extension proposal (Encoding enum +
   `IfcRunLengthToExpandedArray`) backed by phase-5 measurements and the §7 alignment case.

---

## 9. Open questions to resolve before/with the forum

- **Encoding enum vs. separate function**: extend `IfcListToExpandedArray` with a mode arg, or
  add a sibling `IfcRunLengthToExpandedArray`? (Schema cleanliness vs. backward signature.)
- **Run-pair ordering**: (count, value) vs. (value, count); fix one convention.
- **Boolean mask vs. fractional occupancy**: should TM27 allow a fractional layer for sub-cell
  earthwork accuracy, or keep occupancy strictly boolean and push fractions to a payload? (§6)
- **CIS rangeSet encoding conformance**: confirm exactly which CIS `rangeSet` encodings are
  blessed as conformant for inline run-style values before staking the web-delivery claim on it.
- **Georeferencing / placement**: confirm `IfcVoxelGrid` composes with `IfcLinearPlacement` for
  corridor-aligned geotech grids, and that X/Y/Z map unambiguously to placement axes.
- **TM20 overlap**: the shared `IfcComplementaryData` supertype (TM27↔TM20 merge) affects how
  observation/payload data is modeled generally; coordinate.

---

*Companion files: `IFC44_Voxels_TM27_Reference.md` (schema as proposed),
`IFC44_Voxels_TM27_RawDocs.md` (verbatim entity docs). TM27 is under public review and subject to
change before the IFC 4.4 NWI submission.*

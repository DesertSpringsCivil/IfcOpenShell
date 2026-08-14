# IFC 4.4 Voxels (TM27) — Schema Reference & Implementation Notes

**Source:** PR #1110 `[TM27] Voxels` by aothms (Thomas Krijnen), targeting `ifc4.4-main`.
Opened 2026-05-27, moved to **PUBLIC REVIEW** in the *IFC 4.4 NWI preparation* project 2026-05-28.
Labels: `4.4`, `ready-for-review`. Status as captured: open, no formal reviews logged.
Branch: `tm27`. Commit: `4fe8707`.

> Scope note from the PR author: *"Due to the introduction of `IfcComplementaryData`, this PR
> overlaps with TM20 and will likely conflict when merging."* The `IfcComplementaryData`
> supertype is shared with TM20; the merge resolution between the two is an open item.

This document captures the schema **as proposed**. It is a moving target under public review —
attributes, types, and constraints may change before the NWI submission (est. Aug/Sep 2026).

---

## 1. Concept primer

A **voxel** ("volume pixel") is a small box that tiles 3D space, the 3D analogue of a pixel.
A voxel grid is a **regular 3D array**: an origin, a per-axis cell size, and a per-axis cell
count define a stack of identical boxes filling a rectangular region. Cell `(i, j, k)` has a
fixed, computable position — coordinates are never stored per cell.

**Occupancy representation vs. boundary representation.** Everything IFC used for volumes before
TM27 is boundary-based: a TIN is a surface skin; a BRep is defined by bounding faces;
`IfcSectionedSolidHorizontal` is a swept profile. Solidness is *implied* by what lies inside the
boundary. Voxels invert this: you *enumerate* which chunks of space are full. Material is listed
cell-by-cell, not implied.

| | Boundary (TIN / BRep) | Occupancy (voxel) |
|---|---|---|
| Describes | the surface / edges | the filled volume directly |
| Point-in-solid test | geometric computation | array lookup (instant) |
| Volume | integrate / difference surfaces | count cells × cell volume |
| Heterogeneous interior | hard (nested solids) | trivial (per-cell value) |
| Precision | exact, smooth | stair-stepped at cell size |
| Storage | compact for smooth shapes | potentially huge |

**Earthwork intuition.** Boundary cut/fill = signed volume of the prism between existing-ground
and design TINs (fiddly around overhangs, vertical faces, undercuts). Voxel cut/fill = mark each
cell "soil" or "air" in before/after states; cut volume = count of cells that went soil→air ×
cell volume. Counting, not calculus. Overhangs and disconnected pockets need no special handling.

**The exponential tension.** Halving cell size multiplies cell count by 2³ = 8×. 1 m → 0.25 m is
a 64× increase. Fine resolution over a real site is hundreds of millions of cells. Hence any
serious voxel format spends its design effort on *not* storing every cell explicitly.

---

## 2. Architecture of the proposal

TM27 deliberately splits **geometry** from **payload**:

- **`IfcVoxelGrid`** — a geometric representation item (subtype of `IfcTessellatedItem`).
  Holds the grid dimensions and a boolean **occupancy mask** only. No per-cell data.
- **`IfcVoxelData`** (abstract) — a **product** (via new `IfcComplementaryData` → `IfcProduct`),
  assigned to the host product with `IfcRelAssignsToProduct` and sharing the same `IfcVoxelGrid`
  representation. Carries the per-cell payload.

Why split:
1. **One grid, many layers.** Define grid geometry once; hang multiple payloads off it
   (material labels, density, confidence) — like Photoshop layers sharing one canvas.
2. **The mask compresses the payload** (see §5).

```
IfcProduct (e.g. IfcGeomodel / earthwork element)
  ├─ Representation → IfcShapeRepresentation
  │                     └─ Items[1] = IfcVoxelGrid   (occupancy mask + dimensions)
  └─ HasAssignments ← IfcRelAssignsToProduct
                          └─ RelatedObjects: IfcVoxelData subtype(s)
                                               (payload; same IfcVoxelGrid representation)
```

---

## 3. `IfcVoxelGrid` (geometry)

Subtype of **`IfcTessellatedItem`** — sits beside `IfcTriangulatedFaceSet` etc. as a tessellated
representation. Defined in `IfcGeometricModelResource`.

| Attribute | Type | Card. | Meaning |
|---|---|---|---|
| `VoxelSizeX` | `IfcNonNegativeLengthMeasure` | 1 | Cell size, X axis |
| `VoxelSizeY` | `IfcNonNegativeLengthMeasure` | 1 | Cell size, Y axis |
| `VoxelSizeZ` | `IfcNonNegativeLengthMeasure` | 1 | Cell size, Z axis |
| `NumberOfVoxelsX` | `IfcPositiveInteger` | 1 | Cell count, X axis |
| `NumberOfVoxelsY` | `IfcPositiveInteger` | 1 | Cell count, Y axis |
| `NumberOfVoxelsZ` | `IfcPositiveInteger` | 1 | Cell count, Z axis |
| `Voxels` | `ARRAY [1:?] OF IfcBoolean` | 1 | Occupancy mask, ordered **X → Y → Z** |

Notes:
- Per-axis cell sizes ⇒ **anisotropic spacing is supported** (fine vertical / coarse horizontal
  is common in geology).
- The grid carries **no placement of its own** — origin/orientation come from the host
  `IfcProduct.ObjectPlacement`.
- The `Voxels` ordering convention (X fastest, then Y, then Z) is the indexing key the payload
  relies on.

---

## 4. `IfcVoxelData` (payload) and subtypes

### `IfcComplementaryData` (new, abstract)
Subtype of `IfcProduct`. *"A kind of product whose purpose is providing additional raw data,
such as observations, to other products… related to the main product using
`IfcRelAssignsToProduct`."* Shared with TM20 (merge-conflict source). No own attributes here.

### `IfcVoxelData` (abstract)
Subtype of `IfcComplementaryData`. Defined in `IfcProductExtension`.

| Attribute | Type | Card. | Meaning |
|---|---|---|---|
| `ValueType` | `IfcLabel` | 0..1 | Optional; names the `IfcValue` select-type used by the payload |
| `GridSize` | `IfcInteger` (**derived**) | 1 | `= SIZEOF(grid.Voxels)` — total cell count read off the assigned grid |

WHERE rules:
- **`IsAssignedToProduct`** — exactly one `IfcRelAssignsToProduct` assignment.
- **`VoxelGridRepresentation`** — must have a product-definition shape with exactly one
  `IfcShapeRepresentation` whose single item is an `IfcVoxelGrid`.
- **`SameRepresentation`** — the assigned product carries that same representation.

### Concrete subtypes
All add `ValueData` (stored `LIST [1:?]`) and a derived `Values` array (see §5).

| Entity | `ValueData` element type | `Unit`? | Use |
|---|---|---|---|
| `IfcIntegerVoxelData` | `IfcInteger` | yes (`IfcUnit`) | counts, indices, coded data |
| `IfcRealVoxelData` | `IfcReal` | yes (`IfcUnit`) | scalar fields: density, moisture, ppm, confidence |
| `IfcLabelVoxelData` | `IfcLabel` | — | material/stratum classification per cell |
| `IfcLogicalVoxelData` | `IfcLogical` | — | tri-state flags (TRUE/FALSE/UNKNOWN) per cell |
| `IfcVectorVoxelData` | `IfcVector` (`IfcGeometryResource`) | yes (`IfcUnit`) | per-cell vectors: flow, displacement, gradient |

`IfcVectorVoxelData.ValueData` ordering: *"first x, then y, lastly z."* Its `Unit` *"overrides the
default Magnitude `IfcLengthMeasure`."*

---

## 5. Sparse storage — `IfcListToExpandedArray`

The compression mechanism, and the heart of the design. Each payload stores only values for
**occupied** cells (`ValueData`, compact list), and reconstructs the full dense array on demand
(`Values`, derived). The function walks the boolean mask: each `TRUE` consumes the next list
element; each `FALSE` becomes `$` (null).

Derived expression (identical pattern across all five subtypes; type varies):

```express
Values : ARRAY [1:SELF\IfcVoxelData.GridSize] OF OPTIONAL IfcReal :=
    IfcListToExpandedArray(
        ValueData,                                              (* stored sparse list *)
        1,                                                      (* start index *)
        SELF\IfcVoxelData.GridSize,                             (* full grid cell count *)
        SELF\IfcProduct.Representation.Representations[1].Items[1]\IfcVoxelGrid.Voxels  (* mask *)
    );
```

`GridSize` is itself derived:
```express
GridSize : IfcInteger := SIZEOF(...Items[1]\IfcVoxelGrid.Voxels);
```

Gather/scatter illustration:
```
Mask (Voxels):    T   F   F   T   T   F   T
ValueData stored: [a,          b,  c,      d]      ← 4 values stored
Values derived:    a   $   $   b   c   $   d       ← 7 slots reconstructed
```
On a grid where ~95% of cells are empty, payload storage drops ~20×.

**Critical caveat (review item):** the *payload* is sparse, but the **occupancy mask is not**.
`Voxels : ARRAY [1:?] OF IfcBoolean` is one boolean per cell, dense and uncompressed —
O(Nx·Ny·Nz). For a 1000×1000×200 grid (2×10⁸ cells), the mask alone is the scalability ceiling.

---

## 6. Worked example — cut/fill volume (IfcOpenShell, conceptual)

> Conceptual / illustrative. The TM27 entities are not yet in released IfcOpenShell; treat the
> API names as placeholders and adjust to whatever the eventual build exposes. The *logic* is the
> point: occupancy set-difference + cell-count.

```python
import ifcopenshell
import numpy as np

def voxel_grid_to_mask(grid):
    """IfcVoxelGrid.Voxels (flat X->Y->Z booleans) -> 3D numpy bool array."""
    nx, ny, nz = grid.NumberOfVoxelsX, grid.NumberOfVoxelsY, grid.NumberOfVoxelsZ
    flat = np.array([bool(v) for v in grid.Voxels], dtype=bool)
    # X fastest, then Y, then Z  => reshape (nz, ny, nx) with C-order then transpose to (nx,ny,nz)
    return flat.reshape((nz, ny, nx)).transpose(2, 1, 0)

def cell_volume(grid):
    return grid.VoxelSizeX * grid.VoxelSizeY * grid.VoxelSizeZ

# Two grids on the SAME lattice (same origin, sizes, counts): existing vs. design state.
existing_mask = voxel_grid_to_mask(existing_grid)   # True = soil present
design_mask   = voxel_grid_to_mask(design_grid)     # True = soil present after grading

cut_cells  = existing_mask & ~design_mask           # soil -> air  (excavation)
fill_cells = ~existing_mask & design_mask           # air  -> soil  (embankment)

vcell = cell_volume(existing_grid)                  # assumes identical lattice
cut_volume  = int(cut_cells.sum())  * vcell
fill_volume = int(fill_cells.sum()) * vcell
net         = fill_volume - cut_volume

print(f"Cut:  {cut_volume:,.1f} m3")
print(f"Fill: {fill_volume:,.1f} m3")
print(f"Net:  {net:,.1f} m3 ({'import' if net > 0 else 'export'})")
```

Reading a payload layer (e.g. material labels) back onto occupied cells:
```python
def expand_payload(voxel_data, grid):
    """Reconstruct dense ARRAY[1:GridSize] OF OPTIONAL <T> from sparse ValueData + mask."""
    mask = [bool(v) for v in grid.Voxels]
    values = list(voxel_data.ValueData)
    out, it = [], iter(values)
    for occupied in mask:
        out.append(next(it) if occupied else None)   # None == EXPRESS '$'
    return out  # index-aligned with grid cells (X->Y->Z order)
```

---

## 7. Domain mapping (Saikei)

| Concept | Entity | Notes |
|---|---|---|
| Chopped box of space over site | `IfcVoxelGrid` | occupancy = "material present in this cube" |
| Material / stratum per cube | `IfcLabelVoxelData` | voxelized `IfcGeomodel` stratum classification |
| Scalar field per cube | `IfcRealVoxelData` + Unit | density, moisture, contamination, confidence |
| Vector field per cube | `IfcVectorVoxelData` | groundwater flow, settlement vector |
| Cut / fill | boolean set-ops between grids | count soil→air and air→soil cells × cell vol |

**Source-of-truth stance:** treat the voxel grid as a **derived/computed** representation for
analysis and exchange. Keep TIN / `IfcSectionedSolidHorizontal` definitions as the parametric
source of truth (consistent with the surface-vs-solid boundary already established for
superelevation). The grid is computed *from* the model for volumetrics; it is not hand-authored.

**Consume-vs-author:** Saikei consumes ground models; an upstream ingestion pipeline handles
unstructured geotechnical inputs (borehole logs, CAD, scans). Voxelization fits naturally as an
ingestion-side transform that emits a standard `IfcVoxelGrid` + payload, which Saikei then
consumes for QTO.

---

## 8. Public-review observations (for the IF)

1. **Dense occupancy mask.** Payload is sparse; `Voxels` is not. Consider whether the grid should
   permit a compressed occupancy encoding (RLE / octree), or whether sparsity should extend to the
   mask. This is the dominant file-size driver at infrastructure scale.
2. **No explicit grid placement.** `IfcVoxelGrid` defines sizes/counts but inherits placement only
   via the host product. Confirm clean composition with `IfcLinearPlacement` for corridor-aligned
   geotechnical models, and that X/Y/Z map unambiguously to placement axes.
3. **`VoxelSize*` is `IfcNonNegativeLengthMeasure`** — admits zero (degenerate, zero-thickness
   voxel). `IfcPositiveLengthMeasure` would be the tighter constraint.
4. **`IfcComplementaryData` / TM20 overlap.** The shared supertype is unresolved; the TM27↔TM20
   merge is where observation-data modeling gets decided. Weigh in if relevant.
5. **PredefinedType.** The new leaf `*VoxelData` entities lack `PredefinedType` (flagged by SHACL),
   though they share this with existing geotech leaves (`IfcGeomodel`, `IfcGeoslice`, `IfcBorehole`)
   — a schema-wide pattern rather than a TM27-specific defect.

---

## 9. Entity quick-reference (verbatim doc text)

- **IfcVoxelGrid** — *"A 3D solid shape representation that is compiled of a series of regular
  blocks placed inside a predefined grid."*
- **IfcVoxelData** — *"Abstract class representing voxel data values… assigned to `IfcProduct`
  using `IfcRelAssignsToProduct` and to a product representation, as `IfcVoxelGrid`, using
  `Representation`. The number of values shall correspond to the number of voxels in the grid."*
- **IfcComplementaryData** — *"A kind of product with the purpose of providing additional raw
  data, such as observations, to other products."*
- **IfcIntegerVoxelData** — *"The voxels represented by integer values."*
- **IfcRealVoxelData** — *"The voxels represented by real values."*
- **IfcLabelVoxelData** — *"The voxels represented by label values."*
- **IfcLogicalVoxelData** — *"The voxels represented by logical values."*
- **IfcVectorVoxelData** — *"The voxels represented by vector values. First x, then y and lastly z."*

---

*Compiled from the `tm27` branch (commit `4fe8707`) of `buildingSMART/IFC4.x-development`,
PR #1110. Schema is under public review and subject to change before the IFC 4.4 NWI submission.*

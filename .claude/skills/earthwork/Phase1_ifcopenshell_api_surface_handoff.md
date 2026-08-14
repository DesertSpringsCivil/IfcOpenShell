# Phase 1 hand-off — `ifcopenshell.api.surface`

**Sequencing:** B3 (all three APIs land before any Bonsai work). This doc covers Phase 1 only — the surface API. Phases 2 (`ifcopenshell.api.grading`) and 3 (`ifcopenshell.api.earthwork`) follow the same pattern.

**Branch:** `saikei-dev` on the `desertspringscivil/IfcOpenShell` fork. Rebase up to `IfcOpenShell/IfcOpenShell saikei` when Phase 1 is review-ready.

**Workflow:** Drive Claude Code in VS Code through the commit list below. Each commit is small enough to review in one sitting; the test plan keeps each one self-contained.

---

## v3.2 spec amendment needed

Before coding, fix one stale paragraph in `Saikei_Grading_Earthwork_Spec.md`:

- **§4.3 Core-to-Tool pattern** currently says: "There is no `ifcopenshell.api.surface`, no `ifcopenshell.api.grading`, no `ifcopenshell.api.earthwork`. These would need to be built and upstreamed separately, which is out of scope for this sprint."
- **Replace with:** "Per the B3 sequencing decision, the three APIs (`ifcopenshell.api.surface`, `ifcopenshell.api.grading`, `ifcopenshell.api.earthwork`) are built FIRST as Phases 1–3. Bonsai tool methods (Phase 4+) call those APIs rather than `ifc_file.create_entity()` directly. This mirrors the existing `ifcopenshell.api.alignment` pattern."
- **§11 Sprint 1 reframe:** rename "Sprint 1 — Surfaces" to "Phase 1 — `ifcopenshell.api.surface`" and update tasks to reflect the API-only scope (drop Bonsai panel/operator rows from this phase).

This is a v3.2.1 patch. Quick edit, no review cycle needed.

---

## Phase 1 scope

Build `ifcopenshell.api.surface` — a high-level Python API for authoring surface-related IFC 4.3 entities. **No Bonsai code, no Blender dependency.** Tests run pure-Python via `pytest`.

Entities the API authors:
- `IfcGeographicElement` with `PredefinedType=TERRAIN` (existing ground host)
- `IfcEarthworksFill` with `PredefinedType=SUBGRADE` (proposed ground host — needed for Phase 1 because the API has to support both kinds even if proposed-ground use cases come later)
- `IfcTriangulatedIrregularNetwork` (TIN representation)
- `IfcBoundingBox` (LOD representation)
- `IfcAnnotation` + `IfcPolyline` (breakline source geometry)
- `IfcRelContainedInSpatialStructure` (placement under `IfcSite`)
- `IfcRelDefinesByProperties` for the standard psets (`Pset_GeographicElementCommon`, `Pset_EarthworksFillCommon`)
- `IfcRelDefinesByProperties` for the Saikei custom pset (`Pset_SaikeiGradingSurface`)

**Out of scope for Phase 1:**
- Slope projection / grading objects (Phase 2)
- Cut/fill volumes (Phase 3)
- Boundary/hole/void enforcement during triangulation — the API takes pre-triangulated point/index arrays; the *caller* (Bonsai or a script) is responsible for running the constrained Delaunay. The API just persists what it's given.
- Blender visualization

---

## File tree (new files)

All paths relative to `src/ifcopenshell-python/ifcopenshell/api/surface/`:

```
surface/
├── __init__.py                          # Module docstring + public re-exports
├── create_terrain.py                    # Top-level: existing ground TIN
├── create_proposed_surface.py           # Top-level: proposed ground TIN (Phase 2 will refine)
├── add_tin_representation.py            # Lower-level: IfcTriangulatedIrregularNetwork
├── add_bounding_box_representation.py   # Lower-level: IfcBoundingBox
├── add_breakline_annotation.py          # Lower-level: IfcAnnotation polyline for breaklines
├── update_tin_representation.py         # For retriangulation / edit ops
├── apply_saikei_pset.py                 # Pset_SaikeiGradingSurface
└── _representation_context.py           # Internal: get/create the SurfaceModel + Box subcontexts
```

Plus tests at `src/ifcopenshell-python/test/api/test_surface.py` (single file with one class per function — see `test_alignment.py` for the precedent shape).

---

## Public function signatures

All functions return the created IFC entity (or `None` for in-place operations). All take `ifc_file: ifcopenshell.file` as the first arg, matching the alignment-API convention.

### `create_terrain`

```python
def create_terrain(
    file: "ifcopenshell.file",
    name: str,
    points: "numpy.ndarray | list[tuple[float, float, float]]",  # (N, 3)
    triangles: "numpy.ndarray | list[tuple[int, int, int]]",     # (M, 3), 0-based vertex indices
    triangle_flags: "numpy.ndarray | list[int] | None" = None,   # (M,), IFC Flags list values; defaults to all 0
    site: "ifcopenshell.entity_instance | None" = None,           # auto-resolves to the project's IfcSite
    triangulation_tolerance: float = 0.0,
    breakline_count: int = 0,
) -> "ifcopenshell.entity_instance":
    """Create an IfcGeographicElement[TERRAIN] hosting an IfcTriangulatedIrregularNetwork.

    The terrain is contained in IfcSite via IfcRelContainedInSpatialStructure.
    Standard Pset_GeographicElementCommon and Pset_SaikeiGradingSurface are attached.
    A bounding-box representation is added alongside the SurfaceModel TIN for LOD.

    The function does NOT triangulate — it persists pre-triangulated data. Callers
    are responsible for constrained Delaunay (Bonsai/Saikei tool layer handles that).

    Args:
        file: The IFC file to author into.
        name: Human-readable name for the terrain entity (e.g., "Existing Ground").
        points: (N, 3) array of XYZ coordinates in project coordinates.
        triangles: (M, 3) array of 0-based vertex indices. Counterclockwise from above.
        triangle_flags: Optional IFC Flags list (per-triangle integer encoding breakline membership).
        site: The IfcSite to attach to. If None, auto-resolves to the project's first IfcSite.
        triangulation_tolerance: Stored on Pset_SaikeiGradingSurface.
        breakline_count: Stored on Pset_SaikeiGradingSurface.

    Returns:
        The created IfcGeographicElement.

    Raises:
        ValueError: if site is None and no IfcSite exists in the project.
        ValueError: if points or triangles are empty.
        ValueError: if triangle indices reference points outside the points array.
    """
```

### `create_proposed_surface`

Same signature as `create_terrain`, but creates `IfcEarthworksFill[SUBGRADE]` instead of `IfcGeographicElement[TERRAIN]`. Used for proposed grading surfaces. Phase 2 (`ifcopenshell.api.grading`) will add higher-level functions like `create_grading_group` that internally call this.

### `add_tin_representation`

```python
def add_tin_representation(
    file: "ifcopenshell.file",
    product: "ifcopenshell.entity_instance",  # IfcProduct host
    points: "numpy.ndarray | list[tuple[float, float, float]]",
    triangles: "numpy.ndarray | list[tuple[int, int, int]]",
    triangle_flags: "numpy.ndarray | list[int] | None" = None,
) -> "ifcopenshell.entity_instance":
    """Attach an IfcTriangulatedIrregularNetwork to product.Representation as a SurfaceModel.

    Creates IfcCartesianPointList3D (1-based indexing handled internally),
    IfcTriangulatedIrregularNetwork with CoordList, CoordIndex (1-based), and Flags,
    wraps in IfcShapeRepresentation with RepresentationIdentifier='SurfaceModel',
    appends to the product's IfcProductDefinitionShape.Representations.

    If product has no ProductDefinitionShape, creates one. If it has one but no
    SurfaceModel rep, adds it. If it already has a SurfaceModel rep, raises ValueError
    (use update_tin_representation instead).

    Returns:
        The created IfcTriangulatedIrregularNetwork entity.
    """
```

### `add_bounding_box_representation`

```python
def add_bounding_box_representation(
    file: "ifcopenshell.file",
    product: "ifcopenshell.entity_instance",
    min_xyz: tuple[float, float, float],
    max_xyz: tuple[float, float, float],
) -> "ifcopenshell.entity_instance":
    """Attach an IfcBoundingBox representation to product.Representation as a Box.

    Creates IfcBoundingBox at the corner with appropriate dimensions, wraps in
    IfcShapeRepresentation with RepresentationIdentifier='Box',
    appends to the product's IfcProductDefinitionShape.Representations.

    Returns:
        The created IfcBoundingBox entity.
    """
```

### `add_breakline_annotation`

```python
def add_breakline_annotation(
    file: "ifcopenshell.file",
    site: "ifcopenshell.entity_instance",
    polyline: "list[tuple[float, float, float]]",
    name: str,
    kind: "Literal['standard', 'wall', 'non_destructive', 'proximity']" = "standard",
    source: str = "manual",
    grading_group_guid: str | None = None,
) -> "ifcopenshell.entity_instance":
    """Persist a breakline as a separate IfcAnnotation entity with IfcPolyline representation.

    Breaklines are stored as annotations (not as part of any TIN's representation)
    so they survive retriangulation. The TIN's per-triangle Flags list independently
    encodes which triangles touch which breaklines for query purposes.

    The annotation is contained in IfcSite via IfcRelContainedInSpatialStructure.
    A Pset_SaikeiBreaklineCommon is attached with name, kind, source, grading_group_guid.

    Returns:
        The created IfcAnnotation entity.
    """
```

### `update_tin_representation`

```python
def update_tin_representation(
    file: "ifcopenshell.file",
    product: "ifcopenshell.entity_instance",
    points: "numpy.ndarray | list[tuple[float, float, float]]",
    triangles: "numpy.ndarray | list[tuple[int, int, int]]",
    triangle_flags: "numpy.ndarray | list[int] | None" = None,
) -> "ifcopenshell.entity_instance":
    """Replace the existing SurfaceModel TIN representation on product with a new one.

    Removes the old IfcTriangulatedIrregularNetwork and IfcCartesianPointList3D
    (only if they have no other inverse references), creates new ones, swaps the
    representation pointer.

    Used by retriangulation / breakline-add / boundary-edit flows.

    Returns:
        The new IfcTriangulatedIrregularNetwork entity.

    Raises:
        ValueError: if product has no existing SurfaceModel TIN representation.
    """
```

### `apply_saikei_pset`

```python
def apply_saikei_pset(
    file: "ifcopenshell.file",
    product: "ifcopenshell.entity_instance",
    triangulation_tolerance: float = 0.0,
    breakline_count: int = 0,
    vertex_count: int | None = None,        # if None, inferred from existing TIN
    boundary_polygon_reference: str | None = None,
) -> "ifcopenshell.entity_instance":
    """Attach Pset_SaikeiGradingSurface to a surface host (terrain or proposed).

    If a Pset with this name is already attached, updates the values rather than
    creating a duplicate. Returns the (existing or new) IfcPropertySet.
    """
```

---

## Implementation notes

**Spatial containment.** Use `ifcopenshell.api.spatial.assign_container(...)` (the existing API) to put new products under `IfcSite`. Do not author `IfcRelContainedInSpatialStructure` by hand — that's the alignment-API precedent (it uses `assign_container` too).

**Pset authoring.** Use `ifcopenshell.api.pset.add_pset(...)` and `pset.edit_pset(...)` rather than direct `IfcRelDefinesByProperties` creation. Standard Bonsai-style consistency.

**Coordinate indices.** IFC's `IfcIndexedPolygonalFace`-style entities expect 1-based indices. Numpy/Python triangle arrays are 0-based. The conversion happens **inside** `add_tin_representation`; callers always pass 0-based. Add an internal `_to_one_based(triangles)` helper.

**Representation contexts.** `_representation_context.py` resolves or creates the `Body`, `SurfaceModel`, and `Box` `IfcGeometricRepresentationSubContext` instances under the project's `Model` `IfcGeometricRepresentationContext`. Cache them per file (lazy lookup pattern from alignment API).

**Numpy as soft dependency.** Functions accept `numpy.ndarray | list[...]`. Internally, convert lists to ndarrays for math; convert ndarrays to lists for IFC entity attributes (IfcOpenShell expects Python lists/tuples). Do NOT make numpy a hard import requirement of `ifcopenshell.api.surface` — guard with `try: import numpy as np`.

**Module docstring.** `__init__.py` should have the same shape as `alignment/__init__.py` — a doctring describing what the API does, what's currently supported, what's planned. Re-export each public function so callers do `ifcopenshell.api.surface.create_terrain(...)`.

**Type stubs / annotations.** Use string-quoted forward references for `ifcopenshell.entity_instance` and `numpy.ndarray` to keep import costs low.

---

## Test plan

Tests live at `src/ifcopenshell-python/test/api/test_surface.py`. Pure pytest, no Blender. Per-function class structure (precedent: `test_alignment.py`).

**Fixtures:**
- `empty_project_file` — fresh `ifcopenshell.file()` with `IfcProject`, `IfcSite`, `IfcGeometricRepresentationContext` for `Model`. Reusable across tests.
- `flat_pad_geometry` — a 100m × 100m flat surface at z=100, 9 vertices in a 3×3 grid, 8 triangles. Hand-calculable.
- `pyramid_geometry` — 4-vertex pyramid. Used to test triangle-flags round-trip.
- `cone_frustum_geometry` — 16-segment frustum, used in volume tests later (will move to `test_earthwork.py` in Phase 3).

**Test cases per function (minimum):**

1. **`create_terrain`** — happy path; site auto-resolution; ValueError on no-site; ValueError on empty points; ValueError on out-of-range triangle index; round-trip (write file to disk, reopen, assert structure).
2. **`create_proposed_surface`** — happy path; same set as terrain.
3. **`add_tin_representation`** — happy path on host with no existing reps; happy path on host with a Box rep already; ValueError on host with existing SurfaceModel rep.
4. **`add_bounding_box_representation`** — happy path; Box rep correctly identifies as RepresentationType='BoundingBox'.
5. **`add_breakline_annotation`** — happy path; pset values round-trip correctly.
6. **`update_tin_representation`** — happy path replaces in place; old TIN entity is GC'd if no other refs; ValueError when no existing TIN.
7. **`apply_saikei_pset`** — happy path creates pset; second call updates values rather than duplicating.

**Round-trip discipline:** every "creates an entity" test does `file.write("/tmp/foo.ifc")`, `file2 = ifcopenshell.open("/tmp/foo.ifc")`, asserts the structure is preserved. This catches serialization issues that in-memory checks miss.

**bSI reference validator:** add one CI test that runs the validator against a flat-pad demo file. Skip if validator binary isn't available locally; require it in CI.

---

## Suggested commit order

Each commit is independently reviewable. Stop and run tests at every step.

1. `chore(api.surface): scaffold ifcopenshell.api.surface package` — empty `__init__.py` with module docstring, package directory created. No functions yet. No tests yet. ~30 LoC.
2. `feat(api.surface): _representation_context helper` — internal helper for SurfaceModel/Box context resolution. Two unit tests. ~80 LoC.
3. `feat(api.surface): add_tin_representation` — public function + tests. ~150 LoC.
4. `feat(api.surface): add_bounding_box_representation` — public function + tests. ~80 LoC.
5. `feat(api.surface): apply_saikei_pset` — public function + tests. ~70 LoC.
6. `feat(api.surface): create_terrain` — top-level wrapper using all the above. Tests for happy path + round-trip. ~120 LoC.
7. `feat(api.surface): create_proposed_surface` — twin of create_terrain for IfcEarthworksFill. ~100 LoC.
8. `feat(api.surface): add_breakline_annotation` — public function + tests. ~120 LoC.
9. `feat(api.surface): update_tin_representation` — public function + tests. Includes the GC-old-entities logic. ~150 LoC.
10. `test(api.surface): bSI reference validator integration test` — runs the validator on a flat-pad output. ~50 LoC.
11. `docs(api.surface): module docstring + usage examples` — flesh out `__init__.py` per the alignment-API style. ~80 LoC.

Total estimate: ~1,030 LoC across 11 commits. Conservative; the alignment-API equivalent files are larger because alignments have segment math. Surface API is structurally simpler.

---

## What "done" looks like for Phase 1

- All 11 commits land on `saikei-dev`.
- Tests pass: `pytest src/ifcopenshell-python/test/api/test_surface.py -v`.
- A standalone Python script can:
  1. Open or create an IFC file.
  2. Call `ifcopenshell.api.surface.create_terrain(...)` with a flat-pad point cloud.
  3. Save the file.
  4. Reopen and verify entity structure.
  5. Run bSI validator and get a clean report.
- Demo script lives at `src/ifcopenshell-python/test/api/demo_surface.py` (not a test, not part of CI — a runnable example for stakeholders).

When that's all green, Phase 1 is shippable. Phase 2 (`ifcopenshell.api.grading`) starts on top of it.

---

## Things to flag to me as you go

If Claude Code (or you) hits any of these, ping me — they're the kinds of things that warrant a design conversation rather than an in-flight decision:

- An IFC entity attribute or relationship that doesn't have a clean Python idiom (e.g., things that need numerical tolerance defaults).
- A test fixture that requires a hand-calc number you don't have memorized — those should be in the spec but aren't yet (we deferred §6.4 known-answer cases).
- Any case where the alignment-API precedent would push you toward a different shape than what's in this hand-off.
- bSI validator failures that look like our author code is wrong rather than the validator being out of date.

Otherwise: drive it.

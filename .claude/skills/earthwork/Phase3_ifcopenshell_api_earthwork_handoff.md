# Phase 3 hand-off — `ifcopenshell.api.earthwork`

**Sequencing:** Phase 1 (`ifcopenshell.api.surface`) shipped 2026-04-28 — 11 commits, 47 tests. Phase 2 (`ifcopenshell.api.grading`) shipped 2026-04-29 — 12 commits + 1 prep refactor, 81 tests, schema-clean. Phase 3 builds on top.

**Branch:** `saikei-dev` on `desertspringscivil/IfcOpenShell`. Rebase up to `IfcOpenShell/IfcOpenShell saikei` when Phase 3 is review-ready.

**Workflow:** Eleven atomic commits, each independently reviewable. Run tests after every commit.

---

## Spec amendment needed

**None.** v3.2.3 of `Saikei_Grading_Earthwork_Spec.md` covers Phase 3 entity choices (§2.4, §3.2, §3.3). If Phase 3 surfaces issues, bump to v3.2.4 with a delta changelog at the top.

---

## Phase 3 scope

Build `ifcopenshell.api.earthwork` — a high-level Python API for authoring earthwork volume solids in IFC 4.3. **No Bonsai code, no Blender dependency, no volume math.** The actual prismoidal-volume calculation (§6.4) and cut/fill solid construction (§6.5) live in Bonsai's `tool.Earthwork` (Phase 6); the API persists what it's given.

Entities the API authors:

- :class:`IfcEarthworksCut` (the act of excavation; closed solid representation +
  optional :class:`IfcRelVoidsElement` to host terrain)
- :class:`IfcEarthworksFill` (volume-bearing fill, distinct from Phase 2's
  surface-representing fills — different `PredefinedType`s, no group membership)
- :class:`IfcPolygonalFaceSet` with `Closed=TRUE` (the canonical IFC 4.3
  lightweight closed solid; carried in a Body / Tessellation
  :class:`IfcShapeRepresentation` per spec §2.4)
- :class:`IfcRelVoidsElement` (cut → host terrain void relationship; mirrors
  the doors-void-walls pattern)
- :class:`IfcElementQuantity` for `Qto_EarthworksCutBaseQuantities` and
  `Qto_EarthworksFillBaseQuantities` (the standard Qtos QTO tools query)
- :class:`IfcRelDefinesByProperties` for `Pset_EarthworksCutCommon`,
  `Pset_EarthworksFillCommon`, and `Pset_SaikeiGradingShrinkSwell`
- :class:`IfcRelAssociatesClassification` for OmniClass Table 22 codes

Reuses from Phase 2 (no rework):

- `ifcopenshell.api.grading._shared.identity_placement` for the
  identity local-placement pattern (spec §2.8)
- `ifcopenshell.api.grading._shared.attach_earthworks_fill_common`
  for the fill-side standard-pset author
- `ifcopenshell.api.grading._shared.apply_omniclass_classification` for
  the OmniClass Table 22 idempotent author/extend
- `ifcopenshell.api.grading._shared.to_point_list` for soft-numpy point
  coercion
- `ifcopenshell.api.grading._shared.compute_bounding_box` for derived
  bounding-box LOD reps if needed

**Cross-API import policy.** Phase 3 imports from `ifcopenshell.api.grading._shared`
directly — that module is the de facto civil-engineering-shared helper home until
Phase 4+ refactors it to a more obvious location. Earthwork-specific helpers (e.g.,
`attach_earthworks_cut_common`) go in a new `ifcopenshell.api.earthwork._shared.py`.
Do not duplicate the grading helpers — that defeats the consolidation done in the
prep commit.

**Out of scope for Phase 3:**

- Volume math itself (TIN-to-TIN prismoidal, region extraction) — Phase 6
  Bonsai `tool.Earthwork`
- Cut/fill solid construction algorithm (§6.5 stages 1–4) — Phase 6
- Cut/fill color-map mesh generation — Phase 6
- DESITE-style takeoff schedule export — out of scope entirely

---

## File tree (new files)

All paths relative to `src/ifcopenshell-python/ifcopenshell/api/earthwork/`:

```
earthwork/
├── __init__.py                              # Module docstring + public re-exports
├── _shared.py                               # attach_earthworks_cut_common, predefined-type validators
├── add_volume_solid_representation.py       # Lower-level: Body/Tessellation IfcPolygonalFaceSet closed solid
├── apply_shrink_swell_pset.py               # Pset_SaikeiGradingShrinkSwell (idempotent)
├── create_earthworks_cut.py                 # Top-level: IfcEarthworksCut with solid + psets + classification
├── create_earthworks_fill.py                # Top-level: IfcEarthworksFill volume entity (distinct from grading composites)
├── void_terrain.py                          # IfcRelVoidsElement: cut voids host terrain
├── write_cut_quantities.py                  # Qto_EarthworksCutBaseQuantities (idempotent)
└── write_fill_quantities.py                 # Qto_EarthworksFillBaseQuantities (idempotent)
```

Plus tests at `src/ifcopenshell-python/test/api/test_earthwork.py` and a
runnable `src/ifcopenshell-python/test/api/demo_earthwork.py`.

---

## Public function signatures

### `add_volume_solid_representation`

```python
def add_volume_solid_representation(
    file: "ifcopenshell.file",
    product: "ifcopenshell.entity_instance",
    points: "PointArray",
    faces: "list[list[int]]",
    *,
    closed: bool = True,
) -> "ifcopenshell.entity_instance":
    """Attach an IfcPolygonalFaceSet (Closed=TRUE) Body/Tessellation representation to a product.

    Per spec §2.4 + v3.2.3 changelog, the canonical RepresentationType is
    "Tessellation", not "Brep" — `IfcPolygonalFaceSet` is a tessellated face
    set even when closed. RepresentationIdentifier="Body".

    Faces are passed as a list of vertex-index lists (variable per-face vertex
    count; the IFC schema permits arbitrary polygons, not just triangles).
    Indices are 0-based on the API surface; converted to IFC's 1-based
    convention internally.

    The product must not already carry a Body representation — re-authoring
    is an error here. (Compare update_tin_representation in Phase 1 for the
    in-place replacement pattern when needed; Phase 3 doesn't ship that for
    closed solids since recomputation typically replaces the whole entity.)

    Args:
        file: the IFC file to author into.
        product: the host product (typically IfcEarthworksCut or IfcEarthworksFill).
        points: (N, 3) array of XYZ coordinates.
        faces: list of vertex-index lists; each list is a single polygonal
            face. Faces must form a closed manifold (caller responsibility).
        closed: stored on IfcPolygonalFaceSet.Closed; defaults to True for
            volume solids.

    Returns:
        The created IfcPolygonalFaceSet entity.
    """
```

### `create_earthworks_cut`

```python
def create_earthworks_cut(
    file: "ifcopenshell.file",
    name: str,
    *,
    points: "PointArray",
    faces: "list[list[int]]",
    voids_terrain: "ifcopenshell.entity_instance | None" = None,
    predefined_type: "Literal['BASE_EXCAVATION', 'CUTTING', 'DREDGING', 'OVEREXCAVATION', 'PAVEMENTMILLING', 'STEPEXCAVATION', 'TOPSOILREMOVAL', 'TRENCH', 'USERDEFINED']" = "CUTTING",
    omniclass_code: str = "22-07 31 16",
    omniclass_title: str = "Excavation and Fill",
    site: "ifcopenshell.entity_instance | None" = None,
) -> "ifcopenshell.entity_instance":
    """Create an IfcEarthworksCut with a closed PolygonalFaceSet body.

    Spatial containment: IfcRelContainedInSpatialStructure under IfcSite.
    Standard pset: Pset_EarthworksCutCommon (Status="NEW") via the new
    attach_earthworks_cut_common helper.
    Classification: OmniClass Table 22 (default 22-07 31 16; overridable).
    Optional: IfcRelVoidsElement from this cut to a host terrain
    (typically the IfcGeographicElement[TERRAIN] from Phase 1).

    Returns:
        The created IfcEarthworksCut.
    """
```

### `create_earthworks_fill`

```python
def create_earthworks_fill(
    file: "ifcopenshell.file",
    name: str,
    *,
    points: "PointArray",
    faces: "list[list[int]]",
    predefined_type: "Literal['BACKFILL', 'COUNTERWEIGHT', 'EMBANKMENT', 'TRANSITIONSECTION', 'USERDEFINED']" = "EMBANKMENT",
    omniclass_code: str = "22-07 31 23",
    omniclass_title: str = "Fill",
    site: "ifcopenshell.entity_instance | None" = None,
) -> "ifcopenshell.entity_instance":
    """Create a volume-bearing IfcEarthworksFill — distinct from Phase 2's surface fills.

    PredefinedType excludes SLOPEFILL and SUBGRADE (those belong to Phase 2's
    grading-group composition). Phase 3 fills are EMBANKMENT, BACKFILL,
    COUNTERWEIGHT, TRANSITIONSECTION — earthwork volumes representing
    designed fill material, with closed-solid representation.

    Same wiring as create_earthworks_cut otherwise: spatial containment,
    standard pset, OmniClass classification.

    Returns:
        The created IfcEarthworksFill.
    """
```

### `void_terrain`

```python
def void_terrain(
    file: "ifcopenshell.file",
    cut: "ifcopenshell.entity_instance",
    terrain: "ifcopenshell.entity_instance",
) -> "ifcopenshell.entity_instance":
    """Author an IfcRelVoidsElement between a cut and its host terrain.

    Idempotent: if the cut already voids the terrain, returns the existing
    rel rather than duplicating. The cut's RelatingOpeningElement role
    must be a single relationship (schema cardinality), so a cut that
    already voids ANOTHER terrain raises ValueError — re-target by
    removing the existing rel first.

    Returns:
        The IfcRelVoidsElement (existing or newly created).

    Raises:
        ValueError: if cut is not IfcEarthworksCut, terrain is not
            IfcGeographicElement, or cut already voids a different element.
    """
```

### `write_cut_quantities`

```python
def write_cut_quantities(
    file: "ifcopenshell.file",
    cut: "ifcopenshell.entity_instance",
    *,
    length: float | None = None,
    width: float | None = None,
    depth: float | None = None,
    undisturbed_volume: float | None = None,
    loose_volume: float | None = None,
    weight: float | None = None,
) -> "ifcopenshell.entity_instance":
    """Write or update Qto_EarthworksCutBaseQuantities on an IfcEarthworksCut.

    **Idempotent.** When the cut already carries a
    Qto_EarthworksCutBaseQuantities, the existing IfcElementQuantity is
    updated in place — old IfcQuantity* entities are removed, new ones
    installed, and the same IfcElementQuantity entity is returned. This
    matches the pattern assign_grading_criteria established in Phase 2:
    re-running a volume calculation should not duplicate Qtos.

    Quantity types follow the standard:
      Length, Width, Depth         -> IfcQuantityLength
      UndisturbedVolume, LooseVolume -> IfcQuantityVolume
      Weight                        -> IfcQuantityWeight

    Any quantity left as None is omitted from the Qto.

    Returns:
        The IfcElementQuantity (existing or newly created).
    """
```

### `write_fill_quantities`

```python
def write_fill_quantities(
    file: "ifcopenshell.file",
    fill: "ifcopenshell.entity_instance",
    *,
    length: float | None = None,
    width: float | None = None,
    depth: float | None = None,
    compacted_volume: float | None = None,
    loose_volume: float | None = None,
) -> "ifcopenshell.entity_instance":
    """Write or update Qto_EarthworksFillBaseQuantities on an IfcEarthworksFill.

    Same idempotency contract as write_cut_quantities. Quantities:
      Length, Width, Depth          -> IfcQuantityLength
      CompactedVolume, LooseVolume  -> IfcQuantityVolume
    """
```

### `apply_shrink_swell_pset`

```python
def apply_shrink_swell_pset(
    file: "ifcopenshell.file",
    product: "ifcopenshell.entity_instance",
    *,
    shrink_factor: float = 1.0,
    swell_factor: float = 1.0,
) -> "ifcopenshell.entity_instance":
    """Attach (or update) Pset_SaikeiGradingShrinkSwell on an earthwork product.

    Per spec §3.3, this pset carries shrink and swell factors (compacted/bank
    and loose/bank ratios respectively) that the standard
    Qto_Earthworks*BaseQuantities don't cover.

    Idempotent: re-applying updates the existing pset's properties.
    Valid on IfcEarthworksFill or IfcEarthworksCut.

    Args:
        shrink_factor: ratio of compacted volume to bank volume (defaults
            to 1.0 = no shrink).
        swell_factor: ratio of loose volume to bank volume (defaults to 1.0
            = no swell).

    Returns:
        The IfcPropertySet (existing or newly created).
    """
```

---

## Implementation notes

**Cross-API helper imports.** Phase 3 modules import shared helpers from
`ifcopenshell.api.grading._shared` directly:

```python
from ifcopenshell.api.grading._shared import (
    identity_placement,
    attach_earthworks_fill_common,
    apply_omniclass_classification,
    to_point_list,
    compute_bounding_box,
)
```

That module is private to `ifcopenshell.api.grading` by underscore convention,
but the import is intentional for civil-engineering-API sharing. Don't duplicate
these helpers into `ifcopenshell.api.earthwork._shared.py`. The earthwork
private-shared module is reserved for genuinely earthwork-specific helpers like
`attach_earthworks_cut_common`.

**Idempotency pattern for Qto authoring.** When `write_cut_quantities` or
`write_fill_quantities` is called against a product that already has the
corresponding standard Qto, the existing `IfcElementQuantity` is updated in
place rather than duplicated — pattern matches `assign_grading_criteria` from
Phase 2. Drop the old `IfcQuantity*` child entities, install new ones, return
the existing `IfcElementQuantity`. Same applies to `apply_shrink_swell_pset`.

This idempotency is load-bearing for Phase 6 cascade rebuild flows: when a
volume calculation is re-run for the same (existing, proposed) surface pair,
the persisted Qto must not accumulate duplicates. The API enforces this; Bonsai
callers don't have to remember to clean up.

**RepresentationType="Tessellation".** Spec v3.2.3 corrected the closed-solid
representation type. `IfcPolygonalFaceSet` belongs to the Tessellation kernel
and uses `RepresentationType="Tessellation"` regardless of `Closed=TRUE`.
`'Brep'` is reserved for `IfcManifoldSolidBrep` / `IfcAdvancedBrep` family.

**Watertightness is the caller's responsibility.** Phase 3 persists what it's
given. Phase 6's `tool.Earthwork` runs the watertightness checks (manifold
edge count, Euler characteristic, signed-volume agreement) before calling
`add_volume_solid_representation`. The API does NOT re-validate — it would be
expensive and the caller has already done the work.

**1-based indexing.** `IfcPolygonalFaceSet.Faces[i].CoordIndex` uses 1-based
indices, matching `IfcTriangulatedIrregularNetwork.CoordIndex`. The API takes
0-based and converts internally — consistent with Phase 1 + Phase 2 contracts.

**OmniClass defaults.** Per spec §3.4:
- Bulk excavation cut: `22-07 31 00` (Earthwork)
- Structural excavation: `22-07 31 16` (Excavation and Fill)
- Topsoil stripping: `22-07 31 14` (Site Clearing)
- Embankment / general fill: `22-07 31 23` (Fill)

`create_earthworks_cut` defaults to `22-07 31 16`; `create_earthworks_fill`
defaults to `22-07 31 23`. Override via the `omniclass_code` / `omniclass_title`
kwargs when authoring a non-default cut/fill type.

**`IfcEarthworksCut` PredefinedType.** The IFC 4.3 enum is
`(BASE_EXCAVATION, CUTTING, DREDGING, OVEREXCAVATION, PAVEMENTMILLING,
STEPEXCAVATION, TOPSOILREMOVAL, TRENCH, USERDEFINED, NOTDEFINED)`. The API
default is `"CUTTING"` (general earthwork cut). Validate against the enum;
raise ValueError on unknown values. NOTDEFINED is also accepted but not
defaulted-to.

**`IfcEarthworksFill` PredefinedType for Phase 3.** SLOPEFILL and SUBGRADE
are reserved for Phase 2 grading composition. Phase 3 fills use BACKFILL,
COUNTERWEIGHT, EMBANKMENT, or TRANSITIONSECTION. The API default is
`"EMBANKMENT"`. Soft-validate the choice — accept any IFC-valid value but
emit a warning if SLOPEFILL/SUBGRADE is passed (probably a caller mix-up
between Phase 2 and Phase 3).

**Faces representation.** Use `IfcIndexedPolygonalFace` (one entity per face),
each with `CoordIndex: LIST OF IfcPositiveInteger`. The face set wraps these
in `IfcPolygonalFaceSet.Faces`. Don't use the simpler "single triangulation
list" approach — that's a different kernel.

---

## Test plan

Pure pytest at `src/ifcopenshell-python/test/api/test_earthwork.py`. Same harness
as Phase 1/2 (Blender 5.0's bundled Python 3.11 + dev fork's SWIG wrapper).
Per-function class structure.

**Fixtures:**

- `empty_project_file` — same as Phase 2's. Lift it.
- `tetrahedron_solid_geometry` — 4 vertices + 4 triangular faces forming a
  closed tetrahedron. Smallest hand-calculable closed solid; signed volume = 1/6.
- `cube_solid_geometry` — 8 vertices + 6 quad faces forming a closed unit cube;
  signed volume = 1.
- `frustum_solid_geometry` — truncated pyramid with non-trivial volume; for
  end-to-end Qto round-trip tests where the volume number matters.

**Test cases per function (minimum):**

1. **`add_volume_solid_representation`** — happy path on cube; faces with
   variable vertex count (mix of triangles and quads) round-trip; ValueError
   on out-of-range face index; ValueError when product already has Body rep;
   round-trip through disk preserves face structure.

2. **`create_earthworks_cut`** — happy path; default predefined_type=CUTTING;
   default OmniClass; spatial containment in IfcSite; pset attached;
   ValueError on invalid PredefinedType; ValueError on no-site; round-trip.

3. **`create_earthworks_fill`** — happy path; default predefined_type=EMBANKMENT;
   default OmniClass; SLOPEFILL/SUBGRADE accepted but warning emitted;
   round-trip.

4. **`void_terrain`** — happy path creates IfcRelVoidsElement; idempotent on
   second call (same cut/terrain); ValueError when re-targeting a cut that
   already voids a different terrain; ValueError on wrong types.

5. **`write_cut_quantities`** — happy path writes 6 quantities in standard
   ranges; partial write (subset of None values) omits the corresponding
   IfcQuantity*; **second call updates in place — same IfcElementQuantity
   entity, replaced child quantities, no duplicate Qto**; round-trip.

6. **`write_fill_quantities`** — same as above for the fill flavor.

7. **`apply_shrink_swell_pset`** — happy path on fill; happy path on cut;
   second call updates in place; round-trip.

8. **Cross-cutting: idempotency under repeated authoring.** Build a complete
   cut + fill + Qto + pset + shrink-swell scenario, then call
   `write_cut_quantities` / `write_fill_quantities` / `apply_shrink_swell_pset`
   five times in a row with different values — assert exactly ONE Qto and ONE
   shrink-swell pset on each product after the burst; final values match the
   last-supplied set.

9. **`ifcopenshell.validate` integration.** Build a full earthwork scenario
   (existing terrain + cut voiding it + fill on top + Qtos + shrink-swell +
   classifications), reopen, run validator, assert no warnings/errors. Same
   pattern as Phase 1/2.

10. **External bSI binary.** Opt-in via `BSI_VALIDATOR_PATH` env var. Skip
    when unset. Same shape as Phase 1/2.

**Round-trip discipline:** every "creates an entity" test does
`file.write(...)` → `file2 = ifcopenshell.open(...)` → asserts the structure
is preserved. Idempotent operations get an additional re-call after reopen
to verify the persisted state behaves the same way as the in-memory state.

---

## Suggested commit order

| # | Commit | Est. LoC | Depends on |
|---|--------|---------:|------------|
| 1 | `chore(api.earthwork): scaffold ifcopenshell.api.earthwork package` | ~30 | — |
| 2 | `feat(api.earthwork): _shared (attach_earthworks_cut_common, predefined-type validators)` | ~80 | 1 |
| 3 | `feat(api.earthwork): add_volume_solid_representation` | ~200 | 1 |
| 4 | `feat(api.earthwork): create_earthworks_cut` | ~200 | 2,3 |
| 5 | `feat(api.earthwork): create_earthworks_fill` | ~180 | 2,3 |
| 6 | `feat(api.earthwork): void_terrain` (IfcRelVoidsElement) | ~100 | 4 |
| 7 | `feat(api.earthwork): write_cut_quantities` (idempotent Qto) | ~180 | 4 |
| 8 | `feat(api.earthwork): write_fill_quantities` (idempotent Qto) | ~150 | 5 |
| 9 | `feat(api.earthwork): apply_shrink_swell_pset` (idempotent Pset) | ~100 | 4,5 |
| 10 | `test(api.earthwork): bSI reference validator integration test` | ~180 | 4–9 |
| 11 | `docs(api.earthwork): module docstring + usage examples + demo` | ~120 | all |

Total estimate: ~1,500 LoC across 11 commits. Spec §11 Phase 3 row says
~900 LoC for code; expect tests to bring the total to 1,500-1,800 (Phase 1
came in at 2,300, Phase 2 at 2,700 with tests bundled per commit).

---

## What "done" looks like for Phase 3

- All 11 commits land on `saikei-dev`.
- Tests pass:
  ```bash
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  PYTHONPATH=src/ifcopenshell-python \
  "/c/Program Files/Blender Foundation/Blender_5/5.0/python/bin/python.exe" \
  -m pytest src/ifcopenshell-python/test/api/test_earthwork.py -o "addopts="
  ```
- A standalone Python script can:
  1. Open a Phase-1+2 file with terrain, feature lines, grading group, slope
     fills, interior fill.
  2. Author an `IfcEarthworksCut` voiding the terrain.
  3. Author an `IfcEarthworksFill` (volume-bearing, distinct from the grading
     composite).
  4. Write `Qto_Earthworks*BaseQuantities` on both.
  5. Apply `Pset_SaikeiGradingShrinkSwell` to both.
  6. Save and reopen.
  7. Run `ifcopenshell.validate` and get a clean report.
- Demo script lives at `src/ifcopenshell-python/test/api/demo_earthwork.py`
  showing the full cut-and-fill scenario end-to-end.

When that's all green, all three civil-engineering APIs are shipped. Phase 4
(Bonsai surface module) can begin on top of them.

---

## Things to flag as you go

- `IfcRelVoidsElement.RelatingBuildingElement` (the cut) cardinality may
  surprise — check the schema. If a cut can void only one element at a time,
  the void_terrain idempotency story needs care.
- `IfcPolygonalFaceSet.Faces` cardinality / ordering — verify that face
  winding is preserved through file round-trip. If readers re-order faces,
  watertightness checks the caller did before authoring may need to be
  re-runnable post-load.
- `Qto_*` quantity names — the standard names (Length, Width, Depth,
  UndisturbedVolume, etc.) are case-sensitive. Cross-check against
  buildingSMART's official Qto property tables; ifcopenshell's
  `ifcopenshell.api.pset.add_qto` may accept any name without enforcing
  the standard set.
- Cross-API circular import risk — `ifcopenshell.api.earthwork` importing from
  `ifcopenshell.api.grading._shared` means earthwork can't be loaded without
  grading present. That's fine in this sequencing but worth knowing if any
  reader expects them independent.
- Site-composite aggregation hand-off — Phase 2's `create_grading_group`
  returns a per-group composite that's intended to later be aggregated under
  a site composite. Phase 3 doesn't address that wiring; it remains a Phase
  4/5 Bonsai concern. If Phase 3 finds itself needing it (e.g., for a demo
  scenario that wants both grading composites and earthwork volumes
  side-by-side), surface that and we'll add an `aggregate_group_to_site`
  helper as a Phase 3.5 follow-on rather than baking it into the API now.

Otherwise: drive it.

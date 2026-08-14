# Implementation Feasibility Critique: Saikei Grading & Earthwork Spec

**Reviewer:** saikei-tool-dev agent
**Date:** 2026-04-24
**Subject:** [Saikei_Grading_Earthwork_Spec.md](Saikei_Grading_Earthwork_Spec.md)
**Review perspective:** The engineer who will write `src/bonsai/bonsai/tool/grading.py` and `tool/surface.py` / `tool/earthwork.py`.

---

## 1. Math Feasibility

### Triangulation backend — viable but incomplete

`shapely.constrained_delaunay_triangles` (Shapely 2.1.2, confirmed present in Blender's user extensions) is real and callable. Its signature takes a `Polygon` geometry and returns a `GeometryCollection` of triangles. **The critical limitation:** it only accepts polygons as input, meaning breaklines must be embedded as interior edges of a containing polygon — they cannot be arbitrary free-floating line segments crossing a triangulation domain. The spec's `Breakline` dataclass defines breaklines as independent polylines, but CDT in Shapely works on polygon boundary edges, not on interior constraints as a separate input set. For a flat pad with a single perimeter feature line this may be workable. For interior breaklines that don't coincide with the outer boundary, the Shapely CDT will not honor them.

The production-quality approach for general breakline CDT is `triangle` (Shewchuk's library, available via the `triangle` Python package), `mapbox_earcut`, or CGAL via Python bindings. None of these are in Blender's current stack. The spec should either (a) acknowledge the Shapely CDT limitation explicitly and constrain the Sprint 1 breakline scope to perimeter/boundary breaklines only, or (b) add `triangle` as a dependency and update the setup docs accordingly.

**`scipy.spatial.Delaunay` is confirmed not present in Blender's built-in site-packages.** It is not in the user extensions either. The spec calls it out as the unconstrained TIN path. Before Sprint 1 starts, `scipy` must be added to Blender's user extensions or an alternative must be named. `numpy` alone can drive a simpler Bowyer-Watson implementation, or Shapely's `delaunay_triangles` on a `MultiPoint` geometry provides unconstrained triangulation without scipy. The `Triangulator` abstraction class the spec proposes is exactly right — but the concrete backend for the unconstrained case needs to be resolved before any code is written.

### Slope projection — viable, with one convergence gap

The §6.2 "march outward" algorithm is implementable: for each sample point on the feature line, project horizontally at the correct H:V slope until hitting the target surface. `z_at(surface, x, y)` handles interpolation at each step. This works on convex existing surfaces.

The spec does not address convergence on concave existing surfaces. If the existing surface has a bowl shape (e.g., the daylight search marches into a valley and then back up), the naive "march until we find where proposed grade crosses existing grade" produces an ambiguous answer — the slope from the feature line may intersect the existing surface twice, once at the near valley wall and once on the far side. Civil 3D picks the nearest intersection; Saikei needs to commit to the same convention. Without this the solver can skip over the correct daylight point on concave terrain.

Additionally, the "outward direction" logic for closed feature lines — "counterclockwise = outward is to the right of the direction of traversal" — is correct but inverted. **For a pad perimeter traversed counterclockwise (standard positive winding), the outward normal is to the left, not the right.** This needs to be verified before `compute_grading_object` is implemented, or every pad grading will project inward.

### Volume computation — viable but underspecified

The §6.4 TIN prismoidal algorithm is conceptually correct. The implementation requires a fast polygon intersection routine (`shapely.intersection` on triangle XY projections), Z-interpolation at sub-triangle vertices from both surfaces (calling `z_at` many times), and summation. With numpy vectorization this is performant for typical site grading (~10k triangles). The spec does not state what happens when the two surfaces have different XY extents — the "compute domain = intersection of outer boundaries" step is mentioned but there's no guidance on what constitutes the outer boundary of a surface that was built from a point cloud without an explicit `outer_boundary` polygon. If `CivilSurface.outer_boundary` is `None` (allowed by the dataclass), the domain computation is undefined. This needs a fallback: convex hull of `surface.points[:, :2]`, or explicit requirement that `outer_boundary` be non-None before volume computation.

### Cut/fill solid construction — algorithmically risky

§6.5 describes building a watertight `IfcPolygonalFaceSet` from:
1. top face (proposed TIN portion)
2. bottom face (existing TIN portion, reversed winding)
3. side faces (triangulated strips along the region boundary)

Step 3 — the side face strips — requires identifying the 3D boundary loop of the cut/fill region, projecting it onto both surfaces, and connecting the two resulting 3D boundary loops with triangles. This is a non-trivial 3D meshing problem. The boundary of a cut/fill region is where `z_existing ≈ z_proposed` (the zero-delta contour), which is itself computed by intersection. Extracting this boundary cleanly, especially when it has concave sections or multiple disconnected regions, is the hardest single algorithmic piece in Sprint 3. The spec treats it as a bullet point. **I would flag this as a multi-day implementation task that needs a concrete algorithm choice before Sprint 3 starts.**

---

## 2. IFC API Availability

**No `ifcopenshell.api.surface`, `grading`, or `earthwork` modules exist.** This is correctly acknowledged in §4.3 of the spec. However, the tools that are available cover most of the work:

| Operation | Available API |
|---|---|
| Create `IfcGroup` | `ifcopenshell.api.group.add_group` |
| Assign members to group | `ifcopenshell.api.group.assign_group` / `update_group_products` |
| Assign pset / qto | `ifcopenshell.api.pset.add_pset`, `edit_pset`, `add_qto` |
| Assign classification | `ifcopenshell.api.classification.add_classification`, `add_reference` |
| Aggregate objects | `ifcopenshell.api.aggregate.assign_object` |
| Nest objects | `ifcopenshell.api.nest.assign_object` |
| Assign spatial container | `ifcopenshell.api.spatial.assign_container` |
| Assign representation | `ifcopenshell.api.geometry.assign_representation` |
| Author pset template | `ifcopenshell.api.pset_template.add_pset_template`, `add_prop_template` |
| Void an element | `ifcopenshell.api.feature.add_feature` (wraps `IfcRelVoidsElement`) |

**What must be written via `ifc_file.create_entity()` with no API wrapper:**

- `IfcTriangulatedIrregularNetwork` — no geometry API creates this. The spec's §7.2 code is correct: call `ifc_file.create_entity("IfcTriangulatedIrregularNetwork", ...)` directly. There are zero existing uses of this entity type in the entire non-rules IfcOpenShell Python codebase; this is entirely new territory.
- `IfcGeotechnicalStratum` / `IfcGeomodel` — no API wrappers. Must be `ifc_file.create_entity()` with manual placement.
- `IfcEarthworksCut` / `IfcEarthworksFill` — no API wrappers. `ifc_file.create_entity()` with `PredefinedType`.
- `IfcPolygonalFaceSet` with `Closed=TRUE` — `ifcopenshell.api.geometry.add_mesh_representation` creates `IfcPolygonalFaceSet` but the `Closed` attribute may not be set correctly for a solid. Verify by reading `add_mesh_representation.py` before assuming this method works; the tool layer may need to call `ifc_file.create_entity("IfcPolygonalFaceSet", ..., Closed=True)` directly.
- `IfcBoundingBox` representation — `ifc_file.create_entity()` directly.
- `IfcAnnotation` with 3D polyline — `ifc_file.create_entity()` plus `ifcopenshell.api.geometry.assign_representation`.

`ifcopenshell.api.feature.add_feature` handles `IfcRelVoidsElement` for the cut-voids-stratum relationship — this is a genuine win that avoids manual relationship authoring.

**Open question on `IfcGeomodel` spatial relationship.** The IFC critique is correct: `IfcGeomodel` is a subtype of `IfcSpatialZone`, which relates to `IfcSite` via `IfcRelAggregates`. The spec's updated §2.7 hierarchy diagram (in the spec, not the older critique version) does now correctly say `IfcRelAggregates` for `IfcGeomodel → IfcGeotechnicalStratum`. I'd verify this is also correct in `tool.Surface.author_ifc_host()` before writing that method.

**One additional IFC issue the spec and the critique both miss:** `IfcEarthworksCut` is a subtype of `IfcFeatureElementSubtraction`, which itself inherits from `IfcFeatureElement`, then `IfcElement`. But `IfcFeatureElement` has no `PredefinedType` — the `PredefinedType` on `IfcEarthworksCut` is its own enum (`DREDGING`, `EXCAVATION`, `TOPSOILREMOVAL`, `USERDEFINED`, `NOTDEFINED`). The spec never names which `PredefinedType` to use. Write `EXCAVATION` for cut slopes, `TOPSOILREMOVAL` for stripping, `DREDGING` for pond excavation — this needs to be a documented convention in the tool.

---

## 3. Blender Mesh Authoring and Headless Safety

**The headless gap is real and the spec does not acknowledge it.**

Three tool methods in the spec call into Blender in ways that are not headless-safe:

`tool.Loader.create_generic_shape()` calls `tool.Project.get_project_props()`, which returns `bpy.context.scene.BIMProjectProperties`. Without an active Blender scene (`bpy.context`) this raises `AttributeError`. Additionally, `Loader.load_settings()` calls `bonsai.bim.import_ifc.IfcImportSettings.factory(bpy.context, ...)`. Both of these are called at class-level initialization. For headless use, `create_generic_shape` cannot be used without first standing up a Blender context. The spec says "tool layer is headless-callable" but `link_to_blender` and `update_blender` methods will all hit `bpy.context`.

**The sync path.** The spec prescribes calling `tool.Loader.create_generic_shape(element)` to get a Blender mesh from the authored `IfcTriangulatedIrregularNetwork`. This is the correct approach — it avoids duplicating the geometry engine — but it requires:
1. The IFC entity must be authored and attached to the IFC file before calling `create_generic_shape`.
2. `Loader.load_settings()` must have been called first to initialize `Loader.settings`.
3. A Blender scene must be active.

For headless (agent/CI) use, the surface math (`build_tin_from_points`, `retriangulate`, `z_at`, `volume_tin_to_tin`) is pure Python/numpy and can run headlessly. The IFC authoring methods (`author_ifc_host`, `author_ifc_tin_representation`) are also headless-safe since they only call `ifc_file.create_entity()`. Only the Blender visualization methods (`link_to_blender`, `update_blender`, `build_cutfill_color_mesh`) require `bpy.context`.

**Recommended isolation pattern:** split each tool class into two groups of methods:
1. IFC-only methods (headless-safe, no `bpy` imports) — everything up through writing to the IFC file.
2. Blender sync methods (`link_to_blender`, `update_blender`) — guarded by a conditional import or a `_blender_available()` check.

The core orchestration functions should not call `update_blender` unless Blender is available. The spec's core layer calls `tool.Surface.link_to_blender(surface)` and `tool.Grading.update_blender(group)` unconditionally — this blocks headless execution. The fix is to make the `link_to_blender` call conditional, or to split the core workflow into `create_surface_from_points_headless()` and `create_surface_from_points_with_visualization()`.

`VolumeResult.color_map_mesh_id: int | None` stores a Blender mesh object ID. This is a Blender scene ID, not an IFC ID. Storing it in a dataclass that is passed to `write_standard_qtos()` (a headless-safe IFC operation) couples the IFC writing path to Blender state. This field should be moved out of `VolumeResult` into a separate `VolumeVisualization` dataclass, or kept as metadata only in the Blender-specific visualization layer.

---

## 4. Data Model Shape

### `CivilSurface` — mostly sufficient with one critical gap

`outer_boundary: shapely.Polygon | None = None` — as noted in §1, allowing `None` here blocks the volume computation domain check. For any surface that will be used in earthwork volume calculations, `outer_boundary` must be required or auto-computed. The method `tool.Surface.build_tin_from_points` should always compute and set `outer_boundary` (at minimum the convex hull of the input points).

The field `kind: Literal["existing", "proposed_group", "proposed_site"]` controls which IFC host entity to create. This is correct. However, there is no `ifc_geomodel_id: int | None` field — the `author_ifc_host` method needs to know which `IfcGeomodel` to attach to when there are multiple geomodels in the file. A production site may have both survey data and geotechnical borehole data as separate geomodels. Either add `geomodel_guid: str | None` to `CivilSurface` or require the tool method to take an explicit geomodel argument. The current spec lets `author_ifc_host` find or create a geomodel implicitly — that will cause problems when two surfaces should be in different geomodels.

### `Breakline` — missing priority field

When two breaklines cross or share a vertex, the CDT must decide which edge takes precedence. Civil 3D resolves this via "breakline type" ordering (wall > standard > non_destructive). The spec's `kind` field covers the type but there's no `priority: int` field for tie-breaking. When two standard breaklines cross, which wins? This needs a rule before `retriangulate` is implemented.

There is also no `z_interpolation: Literal["linear", "no_interpolate"]` field. In Civil 3D, standard breaklines use linear Z interpolation along the breakline segment; non-destructive breaklines do not interpolate new vertices. Saikei's CDT must decide how to handle Z at the constrained edge vertices. Without this field the behavior will be inconsistent.

### `GradingCriteria` — sign convention unspecified

`cut_slope: float` and `fill_slope: float` are documented as "ratio (H:V), e.g., 2.0 means 2:1". But there is no comment on whether these are always positive or whether a negative value encodes a "reverse slope" (sloping upward away from the feature line rather than downward). In practice cut slopes are always positive H:V ratios but the sign convention for the `target_ref` field when `target_kind = "relative_elevation"` is also unspecified — a relative elevation of -2.0 means 2 feet below the feature line elevation. Document this explicitly or the first test case will be ambiguous.

### `GradingObject` — `projection_points` indexing not linked to `daylight_line`

`daylight_line: list[tuple[float, float, float]]` and `projection_points: np.ndarray` are parallel data structures but there's no documented correspondence between them. Are the daylight points a subset of `projection_points`? Are they indexed into it? When `rebuild_group_surface` merges multiple `GradingObject` instances, it needs to deduplicate shared daylight points at group boundaries. The deduplication key is missing — probably should be an `np.ndarray` of vertex indices rather than separate lists.

### `VolumeResult` — unit duplication

The dataclass carries both `cut_volume_m3` / `fill_volume_m3` and `cut_cubic_yards` / `fill_cubic_yards`. This is a unit-conversion maintenance hazard — one method writes m3, another writes CY, and they can get out of sync if a caller forgets to convert both. Prefer storing SI values only and providing a `to_cubic_yards(volume_m3)` utility function. The CY fields should be computed properties, not stored fields, or omitted and computed in the report generator.

---

## 5. Sprint Sizing Reality Check

### Sprint 1 (~2,500 LoC) — achievable but tight

The allocation of 700 LoC to `tool.Surface` for `build_tin_from_points`, `retriangulate`, `z_at`, and boundary/hole/void handling is realistic if the scipy/Shapely backend question is resolved first. The CDT breakline limitation (see §1) means "breakline support" in Sprint 1 may realistically be constrained to perimeter breaklines only, which is still useful. The IFC authoring piece (800 LoC for `saikei-ifc`) is the riskiest allocation: `IfcTriangulatedIrregularNetwork` has zero prior usage in the IfcOpenShell Python layer, meaning the implementor will discover schema validation surprises during development. Recommend allocating a day at the start of Sprint 1 specifically to author a minimal `IfcTriangulatedIrregularNetwork` by hand and validate it with the bSI reference validator before the full Sprint 1 sprint begins.

### Sprint 2 (~3,000 LoC) — high risk

The 1,000-LoC allocation to `tool.Grading` for all four projection methods plus group rebuild plus cascade edit is optimistic. The slope projection algorithm alone has non-trivial edge cases (concave surfaces, open feature lines with side selection, the outward-normal issue noted above). The cascade-edit dependency graph (which groups use this feature line → rebuild all of them) requires a traversal over the IFC model that isn't trivially fast. I'd estimate 1,400–1,600 LoC for `tool.Grading` Sprint 2 scope, putting the sprint over 3,500 total — uncomfortably close to Dion's 4,000-line PR cap. Either shrink the Sprint 2 UI scope or defer cascade-on-edit to Sprint 3.

The `FeatureLine` as `IfcAlignment` question (Open Question 1 in the spec) must be resolved before Sprint 2 begins. If Dion says no to `IfcAlignment` for feature lines, the IFC authoring strategy changes materially. This is a blocking dependency.

### Sprint 3 (~2,000 LoC) — biggest risk

The cut/fill solid construction (§6.5) is the hardest algorithm in the entire spec and is allocated 700 LoC in `tool.Earthwork`. The boundary extraction, side-face triangulation, and watertight solid assembly are each non-trivial. More realistic: 1,000–1,200 LoC. The bSI validator run is also listed here as a test step — if validation fails, the IFC authoring work may need significant rework. Sprint 3 is the sprint most likely to slip. Recommend treating the volume computation and the solid authoring as separate deliverables so that volumes (the number engineers need) can ship even if the watertight solids aren't ready.

---

## 6. Concurrency / State

The spec is entirely silent on this axis.

**Module-level class attributes.** The tool classes (`Surface`, `Grading`, `Earthwork`) use `@staticmethod` rather than `@classmethod`, so there are no class-level caches to collide on. This is the correct choice for headless-safe stateless tools.

However, if two agents both call `tool.Surface.author_ifc_host()` on the same IFC file concurrently, they will race on `ifc_file.create_entity()`. IfcOpenShell's `file` object is not thread-safe — it is a C++ object with Python bindings and no internal locking. The IFC file is the shared mutable state. The isolation pattern for concurrent agents is: each agent should work on its own IFC file (or its own copy), with a merge/synchronize step at the end rather than both writing to a single shared file. The spec should state this explicitly. For CI pipelines, this is fine — each test gets its own `ifcopenshell.open()` or `ifcopenshell.file()`. For remote agent swarms sharing one project file, this is a hard constraint.

**Blender scene state.** The `Loader.settings` class attribute (`cls.settings = ...`) is set at load time via `Loader.load_settings()`. If two operators run concurrently in Blender (unusual but possible via modal operators), they share this class attribute. This is pre-existing alignment tool behavior; grading should follow the same pattern.

---

## 7. Test Fixture Needs

The spec mentions "round-trip tests" and "bSI reference validator" but does not identify what fixtures are needed.

For the tool layer, the minimum fixture set for Sprint 1:

- A flat point cloud (`fixture_flat_grid.npy` or equivalent) — 10x10 uniform grid, known Z values — for testing `build_tin_from_points` with a predictable triangulation.
- A sloped point cloud — constant slope surface — for testing `z_at` barycentric interpolation against known analytical values.
- A breakline-constrained case — a surface with a ridge breakline — where the CDT should produce edge-aligned triangles rather than crossing the breakline. This is the primary correctness test for Sprint 1.
- A minimum IFC file with `IfcProject`, `IfcSite`, `IfcGeometricRepresentationContext`, and `IfcMapConversion` already authored — so Sprint 1 IFC authoring tests can focus on the new earthwork entities without re-testing the project setup path.

For Sprint 2 and 3:
- A grading scenario with a known analytical answer: a circular pad at elevation 100.0 ft, 3:1 slopes to a flat existing surface at 95.0 ft — the daylight circle radius should be exactly 15.0 ft (slope horizontal = 5 ft × 3.0 H:V). The volume of the resulting fill cone frustum is computable analytically. This fixture validates both the slope projection and the volume math against a known answer rather than just checking that numbers come out.

None of these fixtures are provided or referenced in the spec. The `saikei-tester` agent will need them before writing any meaningful tests.

---

## 8. Integration with Existing Alignment Tool

**No circular import problem.** `tool/surface.py` and `tool/grading.py` can both `import bonsai.tool as tool` and call `tool.Alignment.method()` for stationing queries — the same pattern `tool/alignment.py` uses for `tool.Georeference` and `tool.Loader`. The existing alignment tool is imported via the `bonsai.tool` namespace, not directly, so no cross-file circular dependency occurs.

**Headless alignment calls.** The alignment tool methods that grading will use most — `calculate_pi_geometry`, `calculate_tangent_length`, and `back_calculate_pis_from_alignment` — are pure Python math with no `bpy` dependencies. These are safe to call from headless grading code. The `create_hierarchy_for_alignment` and `create_object_for_alignment` methods do touch `bpy.data` and are not safe headlessly — grading should avoid calling these.

**The `Pset_SaikeiGradingAlignment` interface.** The spec's alignment integration approach (Store `AlignmentGuid`, `StartStation`, `EndStation` on the grading group's pset) is the right MVP strategy. For the tool layer this means: `tool.Grading.apply_alignment_pset(group, alignment_guid, start_station, end_station)` writes three properties to the group's `Pset_SaikeiGradingAlignment`. Retrieving the alignment object for stationing queries requires `ifc_file.by_guid(alignment_guid)` then `tool.Alignment.back_calculate_pis_from_alignment(alignment)`. Both are headless-safe.

**One missing method in `tool/alignment.py`.** For grading, the most useful alignment query is "give me the XY coordinates and grade at station S" — interpolating between PIs or along curve segments. The current alignment tool has `calculate_pi_geometry` (returns overall geometry) and `extract_pis_from_segments` (returns PI list) but no `point_at_station(alignment, station) -> tuple[float, float, float]` method. Sprint 2 grading work will need this, and it belongs in `tool/alignment.py`. This is worth noting as a Sprint 2 dependency on the alignment tool layer.

---

## Summary of Blocking Unknowns Before Coding

In priority order:

1. **scipy availability** — not present in Blender. Either add it to the user extensions stack or commit to Shapely's `delaunay_triangles(MultiPoint(...))` as the unconstrained backend. Unblock Sprint 1.

2. **CDT backend for interior breaklines** — `shapely.constrained_delaunay_triangles` accepts polygons, not free-floating line segments as breakline constraints. If Sprint 1 needs arbitrary interior breaklines (not just perimeter), the `triangle` package must be added. Clarify scope before any surface math is written.

3. **`IfcAlignment` as feature line** — Dion's approval needed before Sprint 2 IFC authoring begins. If denied, the feature line persistence strategy changes to `IfcAnnotation` which has different tool layer implications (`author_ifc_annotation` vs. the existing `create_object_for_alignment` machinery).

4. **`IfcPolygonalFaceSet Closed=TRUE` via geometry API** — verify whether `ifcopenshell.api.geometry.add_mesh_representation` correctly sets `Closed=TRUE` for solid representations, or whether `tool.Earthwork.author_cut_solid` must use `ifc_file.create_entity()` directly. One test at the start of Sprint 3 resolves this.

5. **Outward normal sign for closed feature lines** — counterclockwise perimeter means outward is to the left of traversal direction, not the right. Verify and fix in `compute_grading_object` before any projection math is written.

6. **`CivilSurface.outer_boundary` when `None`** — the volume domain computation is undefined. Add an auto-compute-convex-hull fallback or make this a required field for surfaces entering the earthwork path.

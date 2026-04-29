# Saikei Civil — Site Grading & Earthwork Implementation Spec

**Status:** Draft v3.2.4 — Phases 1–3 shipped, Phase 4 ready
**Target repo path:** `C:\GitHub\IfcOpenShell-saikei-dev\src\bonsai\bonsai\` (branch: `saikei-dev`)
**Scope:** Non-linear site grading (pads, parking lots, ponds, infield areas)
**Companion doc:** `Saikei_Grading_Earthwork_Research.md` (commercial tool survey — background reading)

## v3.2.4 changelog

Phase 3 (`ifcopenshell.api.earthwork`) shipped — 11 atomic commits, 67 tests, schema-clean. All three civil-engineering APIs are now in. Post-Phase-3 corrections from implementation drift and review:

1. **§2.4** — Three additions to the cut/void section:
   - **Schema-completeness note.** `IfcFeatureElementSubtraction.VoidsElements` cardinality is `[1:1]`; a cut entity is schema-incomplete until paired with a void relationship. `ifcopenshell.validate` will fail on a cut without one.
   - **Voiding is a dedicated API call**, not a kwarg on `create_earthworks_cut`. Authors call `ifcopenshell.api.earthwork.void_terrain(file, cut, terrain)` after cut creation — separation of concerns keeps the schema-completeness contract visible at the call site.
   - **`IfcEarthworksCut.PredefinedType` default is `EXCAVATION`** (general earthwork excavation). The actual IFC 4.3 enum is `BASE_EXCAVATION, CUT, DREDGING, EXCAVATION, OVEREXCAVATION, PAVEMENTMILLING, STEPEXCAVATION, TOPSOILREMOVAL, TRENCH, USERDEFINED, NOTDEFINED` — no `CUTTING` value, despite earlier handoff drafts using that name.

2. **§3.3** — `Pset_SaikeiGradingCriteria` row updated. `TargetReference` is encoded as a single `IfcLabel`, not split by `TargetKind` into separate measure types. Heterogeneous content (GUID for `kind=surface`, stringified numeric for elevation/distance variants) parses on read against the discriminator `TargetKind`.

3. **§4.3** — New paragraph **Cross-API helper sharing**: `ifcopenshell.api.grading._shared` is the de-facto civil-engineering shared helper module Phase 3 imports from directly. Earthwork does not duplicate `identity_placement`, `to_point_list`, `compute_bounding_box`, `apply_omniclass_classification`, `attach_earthworks_fill_common`, or `aggregate_under`. Earthwork-specific helpers (`attach_earthworks_cut_common`, predefined-type validators) live in `ifcopenshell.api.earthwork._shared`.

4. **§4.3** — **Multi-site footgun**: `_resolve_site(site=None)` returns the project's *first* `IfcSite`. Multi-site projects (rare but valid in IFC 4.3) must pass `site=` explicitly to every earthwork/grading API call to avoid silent attachment to the wrong site.

5. **§4.3** — Tracked-but-not-fixed: `_get_or_create_body_subcontext` duplicated between `ifcopenshell.api.surface._representation_context` and `ifcopenshell.api.earthwork.add_volume_solid_representation`. ~20 lines of isolated duplication. Cleanest long-term fix is to expose `get_body_subcontext` publicly on the surface API, or push the get-or-create logic up to `ifcopenshell.util.representation` since it isn't Saikei-specific.

6. **§11 Phase 3** — Task description updated to reflect implementation: `EXCAVATION` as default predefined type, dedicated `void_terrain` for `IfcRelVoidsElement` authoring.

Phase 1, 2, 3 implementations are unaffected — this revision catches the spec up to what shipped.

## v3.2.3 changelog

Pre-Phase-2 follow-on correction triggered by reviewing the IFC 4.3.2 basin-tessellation example (Annex E.1.3). The example shows a closed `IfcTriangulatedFaceSet` carried in `IfcShapeRepresentation` with `RepresentationType='Tessellation'`, not `'Brep'`. Saikei v3.2.2 had several locations describing closed `IfcPolygonalFaceSet` cut/fill solids with `RepresentationType='Brep'` — that string is wrong. `'Brep'` in IFC's RepresentationType vocabulary is reserved for `IfcManifoldSolidBrep` / `IfcFacetedBrep` / `IfcAdvancedBrep` (actual B-rep entities); `IfcPolygonalFaceSet` belongs to the Tessellation kernel, so closed-tessellated solids use `RepresentationType='Tessellation'` regardless of whether they happen to be closed.

1. **§2.2** — Fill solid representation now correctly described as `Body` / `Tessellation`.
2. **§2.4** — Cut and fill volume `RepresentationType` corrected to `'Tessellation'`. Kept the existing framing about `IfcPolygonalFaceSet` being "the IFC 4.3 preferred lightweight closed solid" (still accurate — that's a kernel-choice statement, not a RepresentationType claim).
3. **§6.3** — Composite fill representation language updated.
4. **§7.2** — `author_fill_solid` docstring corrected.
5. **§11 Phase 6** — `IfcEarthworksFill` task description updated.

Phase 1 implementation is unaffected — `add_tin_representation` already correctly authors with `RepresentationType='Tessellation'`. `RepresentationIdentifier='Body'` (per the basin example's pattern for closed solids) is unchanged and remains correct.

## v3.2.2 changelog

Phase 1 (`ifcopenshell.api.surface`) shipped — 11 atomic commits, 47 tests, schema-clean. Pre-Phase-2 corrections from review of the buildingSMART `IfcTriangulatedIrregularNetwork` documentation:

1. **§2.1** — Corrected the IFC `Flags` list semantic. The encoding is fixed by IFC 4.3.2: `-2` = invisible void; `-1` = invisible hole; `0` = no breaklines; `1`–`7` = 3-bit edge mask (which of the triangle's three edges are breakline edges). The previous "Saikei breakline ID N" interpretation was wrong and would corrupt round-trip with conformant readers. Rewrote the table and the Known limitation paragraph; clarified that breakline identity lives only in the separate `IfcAnnotation` polylines (§2.3).
2. **§3.1** — `Pset_GeographicElementCommon` "use for" column updated to reflect what the API authors at creation (`Status` defaulting to `"NEW"` to satisfy `HasProperties [1:?]` cardinality) plus what callers can override (`IsLandmarked`, `Reference`).
3. **§3.3** — Added `Pset_SaikeiBreaklineCommon` row (Kind, Source, GradingGroupGuid). Was used by `add_breakline_annotation` in Phase 1 but missing from this table.
4. **§4.4** — Clarified that pinned versions and bundled wheels live in `src/bonsai/pyproject.toml` and the Bonsai extension manifest, **not** in `src/ifcopenshell-python/pyproject.toml`. The IFC API in Phases 1–3 does not import scipy or shapely; those libraries are consumed only by Bonsai's `tool.Surface` math, Phase 4 onward.
5. **§5** — Clarified that `outer_boundary`, `holes`, and `voids` polygon fields on `CivilSurface` are **caller-supplied authoring inputs**. The persistence step translates them into per-triangle IFC `Flags` integers (`-1` for hole, `-2` for void). The IFC entity itself stores integers per triangle, not polygons.
6. **§6.3** — Added a paragraph on IFC's standardized cross-surface composition rules (Void retained, Hole overridden by other surfaces' visible geometry at the same XY) and how Saikei surfaces leverage them. The existing per-grading-object structural composition algorithm is retained.

## v3.2.1 changelog

Locks in the **B3 build sequencing** decision (all three `ifcopenshell.api.*` libraries land before any Bonsai work). Phase numbering supersedes Sprint numbering.

1. **§4.3** — Replaced the "no `ifcopenshell.api.surface`... out of scope" paragraph with the B3 statement: APIs are Phases 1–3, Bonsai is Phases 4–6, tool methods call the APIs (not `ifc_file.create_entity()` directly).
2. **§11** — Reframed Sprint 1/2/3 → Phase 4/5/6 (Bonsai work). Added Phase 1/2/3 tables for the API work that comes first. See companion doc `Phase1_ifcopenshell_api_surface_handoff.md` for the Phase 1 commit-by-commit plan.

## v3.2 changelog

Multi-agent review of v3.1 (see `Saikei_Grading_Earthwork_Spec_v3.1_MultiAgent_Synthesis.md`) surfaced 12 deal-breakers. v3.2 closes them:

1. **§2.2 / §2.7** — Existing ground host changed from `IfcGeotechnicalStratum` to `IfcGeographicElement[TERRAIN]`. `IfcGeomodel` umbrella dropped (Geomodel is for subsurface geotechnical interpretation, not surface grading). Spatial hierarchy simplified — earthwork entities sit directly under `IfcSite`. `IfcGroup` (grading group) is explicitly outside the spatial tree.
2. **§2.7** — Composite-fill aggregation tree clarified: only `IfcEarthworksFill → sub-IfcEarthworksFill` aggregation remains.
3. **§4.4** — Library install path documented, pinned versions, `Triangulator` interface defined.
4. **§4.6** (new) — Tool-side state registry contract.
5. **§4.7** (new) — Core function signature pattern (explicit class injection per `core/alignment.py`).
6. **§5** — `outer_boundary` default and `np.ndarray` annotation handling at the core boundary.
7. **§6.4** — `outer_boundary` None fallback rule (auto-compute convex hull).
8. **§6.5** — Cut/fill solid construction scaffold with named algorithms.
9. **§7** — Core functions rewritten with explicit class-injection signatures; tool methods accept `ifc_file`.
10. **§8.3, §8.4, §8.5** (new) — PropertyGroup / UIList schema, keymap table mirroring alignment PI editor, modal/headless operator contract.
11. **§13** — References updated.

---

## 1. Purpose and Model

Saikei Civil models site grading using the **AutoCAD Civil 3D pattern**, implemented with IFC 4.3 entities as the native persistence layer. Civil 3D's model is the most widespread in US practice and the most legible to practicing civil engineers; adopting it means minimal conceptual retraining for the target user.

This document is the implementation spec for agents. It defines the data model, the 3-layer architecture mapping, the IFC entities, the operator set, and the sprint breakdown. For background on *why* Civil 3D's model was chosen over alternatives, see the companion research doc.

### Core Civil 3D concepts Saikei adopts

| Civil 3D concept | Role | Saikei class |
|------------------|------|--------------|
| Surface (TIN) | Existing or proposed ground | `CivilSurface` |
| Breakline | Constrained edge in a surface | `Breakline` |
| Feature Line | 3D polyline with elevations — grading footprint | `FeatureLine` |
| Grading Criteria | Rule for projecting a slope from a feature line | `GradingCriteria` |
| Grading | Feature line + criteria + target → slope projection geometry | `GradingObject` |
| Grading Group | Collection of gradings composing one feature; produces one surface + volumes | `GradingGroup` |
| Cut/Fill Report | Earthwork quantities between two surfaces | `VolumeResult` |

Saikei does **not** implement the Civil 3D "site" concept for automatic topological interaction between grading objects. That behavior is fragile in Civil 3D itself, and its absence can be worked around by disciplined feature-line authoring. Grading groups are standalone.

### The Civil 3D grading workflow Saikei supports

The MVP target is this workflow, identical to Civil 3D's:

1. Load or create existing ground surface (from XYZ points, CSV, or IFC import).
2. Draw or import a feature line representing the grading footprint.
3. Assign elevations to feature line vertices — either manually, from the surface (drape), or via grade/elevation editing.
4. Create a grading group targeting the existing surface.
5. Author or select a grading criteria (e.g., "slope to surface, 3:1 fill / 2:1 cut").
6. Apply the criteria to the feature line — Saikei computes slope projection, daylight line, and the proposed surface for the grading object.
7. Add more gradings to the group as needed; the group surface composes.
8. Compute earthwork volumes between existing and proposed surface.
9. Export to IFC.

---

## 2. Mapping to IFC 4.3

Each Civil 3D concept maps to a standard IFC 4.3 entity. No schema extensions are required.

### 2.1 Surfaces — `IfcTriangulatedIrregularNetwork`

`IfcTriangulatedIrregularNetwork` (subtype of `IfcTriangulatedFaceSet`) is the canonical IFC 4.3 terrain representation. Key facts:

- `Closed` must be `FALSE` — it's an open surface, not a solid.
- One unique Z per (X, Y) — draped surfaces only. Fine for typical civil site grading; overhanging/vertical faces (retaining walls, steep cut faces) are a known limitation handled via separate wall entities (see §10, future considerations).
- Triangles counterclockwise from above (right-hand rule).
- `Flags` list: one integer **per triangle** encoding breakline membership or hole/void status.

**IFC 4.3.2 `Flags` encoding (verbatim from the standard):**

| Value | Meaning |
|---|---|
| `-2` | invisible **void** — face excluded with no fallback to other geometry (e.g., portions of a site beneath a building) |
| `-1` | invisible **hole** — face excluded but may fall back on another surface's geometry at the same XY (e.g., portions of a proposed site that conform to existing ground) |
| `0` | no breaklines |
| `1` | breakline at edge 1 |
| `2` | breakline at edge 2 |
| `3` | breakline at edges 1 and 2 |
| `4` | breakline at edge 3 |
| `5` | breakline at edges 1 and 3 |
| `6` | breakline at edges 2 and 3 |
| `7` | breakline at all three edges |

Values `1`–`7` are a **3-bit mask** indicating which of the triangle's three edges are breakline edges (bit 0 = edge 1, bit 1 = edge 2, bit 2 = edge 3). Edge `i` is between vertex `i` and vertex `(i+1) mod 3` of the triangle's `CoordIndex` triple.

**Cross-surface composition (IFC-standard).** When a downstream tool combines multiple `IfcTriangulatedIrregularNetwork` instances at the same XY locations, the standard rules apply: triangles marked Void (-2) are retained as voids regardless of other surfaces; triangles marked Hole (-1) are overridden by any other surface that has visible geometry at the same XY. Saikei leverages this for grading-group composite surfaces (§6.3) — the proposed surface marks Hole at unmodified-ground regions, and the existing surface fills through automatically.

**Breakline identity, not edges.** The Flags encoding tells you *which edges* of a triangle are breakline edges; it does **not** store *which named breakline* an edge belongs to. To recover breakline identity, query the proximity of the constrained edge to the breakline polylines authored separately as `IfcAnnotation` (see §2.3). On round-trip, edge-vs-breakline membership is preserved by edge geometry; the named-breakline lookup runs against the annotation set.

### 2.2 Host entities — existing vs. proposed surfaces

Saikei distinguishes existing from proposed ground via the **host entity type**, not via a property on a shared host:

| Surface kind | Host IFC entity | Notes |
|---|---|---|
| **Existing ground** | `IfcGeographicElement` with `PredefinedType=TERRAIN` | TIN attached as shape representation. IFC 4.3-canonical entity for natural terrain features. |
| **Proposed ground** (per grading group) | `IfcEarthworksFill` with `PredefinedType=SUBGRADE` | TIN attached as shape representation. The fill entity *also* carries the solid fill volume representation (see §2.4). |
| **Composite site proposed** (all groups merged) | `IfcEarthworksFill` with `PredefinedType=SUBGRADE` | Top-level site-proposed surface; aggregates per-group composite fills via `IfcRelAggregates`. |

The split is principled: `IfcGeographicElement` is semantically for *natural* geographic features (which existing ground is); `IfcEarthworksFill` is the IFC 4.3 Earthworks-domain entity for designed/built fill (which proposed ground is). Saikei does **not** model subsurface geology — `IfcGeomodel` and `IfcGeotechnicalStratum` belong to a different domain (geotechnical interpretation from boreholes and stratigraphy) and are not used here.

**Important: surface ≠ fill solid.** A proposed `IfcEarthworksFill` carries two distinct geometric representations:
1. **The proposed surface** (top face of the design) — `IfcTriangulatedIrregularNetwork` in a `SurfaceModel` `ShapeRepresentation`.
2. **The fill volume solid** (the dirt between proposed and existing) — `IfcPolygonalFaceSet` with `Closed=TRUE` in a `Body` / `Tessellation` `ShapeRepresentation` (`RepresentationIdentifier='Body'`, `RepresentationType='Tessellation'`).

Both are attached to the same `IfcEarthworksFill` entity in different `IfcShapeRepresentation` blocks. `IfcProductDefinitionShape.Representations` holds the list.

### 2.3 Feature lines and grading criteria — IFC persistence

These are Civil 3D-native concepts with no directly-matching IFC 4.3 entity. Saikei commits to specific persistence strategies:

**Feature lines** are persisted as `IfcAlignment` entities with a simplified representation:
- `IfcAlignment` carries a 3D `IfcPolyline` or `IfcIndexedPolyCurve` as its shape representation (IFC 4.3 explicitly lists `IfcPolyline` as a valid `IfcAlignment` representation for 3D polyline alignments from survey data).
- No `IfcAlignmentHorizontal` / `IfcAlignmentVertical` subdivision is required for feature lines — the polyline representation suffices.
- `Pset_SaikeiFeatureLineCommon` carries Saikei-specific metadata (closed/open, source origin, grading group membership).
- This reuses the existing alignment IFC infrastructure rather than inventing new entities.

**Breakline source geometry** is persisted as `IfcAnnotation` polylines separate from the derived TIN. This preserves editability — on file re-open, the breakline polylines are still present and retriangulation can be re-run. Without this, the TIN would load but the breaklines that produced it would be lost.

**Grading criteria** are persisted as **reusable `IfcPropertySetTemplate`** definitions in the project, instantiated as `IfcPropertySet` on each grading group that uses them. This matches Civil 3D's "grading criteria set" model where criteria are named and reusable across multiple groups. The template carries the parameter structure (`target_kind`, `cut_slope`, `fill_slope`, `max_distance`, etc.); instances bind to specific values.

### 2.4 Cut and fill volumes — `IfcEarthworksCut` / `IfcEarthworksFill`

**`IfcEarthworksCut`** is a subtype of `IfcFeatureElementSubtraction`. Semantically it represents the act of excavation; geometrically it is the void created. It relates to the host stratum via `IfcRelVoidsElement` (the same relationship doors use to void walls).

**Default `PredefinedType`** for cuts authored by Saikei is `EXCAVATION` (general earthwork excavation). The full IFC 4.3 `IfcEarthworksCutTypeEnum` is `BASE_EXCAVATION, CUT, DREDGING, EXCAVATION, OVEREXCAVATION, PAVEMENTMILLING, STEPEXCAVATION, TOPSOILREMOVAL, TRENCH, USERDEFINED, NOTDEFINED` — note no `CUTTING` value.

**Schema-completeness note.** `IfcFeatureElementSubtraction.VoidsElements` has cardinality `[1:1]` — every cut must void exactly one host element. `ifcopenshell.api.earthwork.create_earthworks_cut` does not author the void relationship; the dedicated `void_terrain(file, cut, terrain)` API call handles it after cut creation. A cut entity is schema-incomplete (and `ifcopenshell.validate` will flag it) until the paired `void_terrain` call lands. The contract surface is intentional: keeping voiding as a separate API call surfaces the schema constraint at the call site rather than burying it in a kwarg.

**Shape representation for cut volumes:** `IfcPolygonalFaceSet` with `Closed=TRUE` in a `ShapeRepresentation` with `RepresentationIdentifier='Body'` and `RepresentationType='Tessellation'`. `IfcPolygonalFaceSet` is the IFC 4.3 preferred lightweight closed solid — note that it's a tessellated face set, not a B-rep entity, so `'Brep'` (which in IFC's RepresentationType vocabulary is reserved for `IfcManifoldSolidBrep` and friends) is **not** the correct RepresentationType. Pattern matches `IfcOpeningElement`: the cut has its own renderable solid geometry *and* establishes a void relationship via `IfcRelVoidsElement`. These are complementary, not alternative.

**`IfcEarthworksFill`** is a subtype of `IfcEarthworksElement`, which is a subtype of `IfcBuiltElement` → `IfcElement`. (Not `IfcElementAssembly` — that is a sibling, not an ancestor.) `PredefinedType` enum covers `EMBANKMENT`, `SUBGRADE`, `SUBGRADEBED`, `SLOPEFILL`, `BACKFILL`, `COUNTERWEIGHT`, `TRANSITIONSECTION`.

**Shape representation for fill volumes:** also `IfcPolygonalFaceSet` with `Closed=TRUE`. Same `Body` / `Tessellation` representation.

**Important:** `IfcEarthworksCut` does not represent the excavated *material*. For a cut + fill scenario where excavated dirt is reused as fill, Saikei authors separate `IfcEarthworksCut` and `IfcEarthworksFill` entities with no direct IFC link between them (material tracking is a resource concept not in IFC 4.3).

### 2.5 Slope fill and interior fill as distinct entities

Within a grading group, the composite proposed surface is composed of multiple distinct regions that have **different material treatment and quantities**. Saikei authors each as a separate `IfcEarthworksFill`:

- **Slope fill** — the sloped tie from the feature line out to the daylight line. `PredefinedType=SLOPEFILL`. One per grading object.
- **Interior fill** — the floor of the pad, pond, or infield area enclosed by feature lines. `PredefinedType=SUBGRADE`. One per grading group (if `interior_fill != "none"`).
- **Group composite** — the `IfcEarthworksFill` that aggregates the per-object slope fills and interior fill via `IfcRelAggregates`. `PredefinedType=SUBGRADE`.

This is takeoff-friendly: contractors can quantify slope fill (typically borrow/waste) separately from subgrade fill (often imported structural fill or native compacted).

### 2.6 Grading groups — `IfcGroup` with `ObjectType="GradingGroup"`

A grading group is a logical collection of cuts and fills that together compose one designed feature. The IFC entity is **`IfcGroup`** with `ObjectType="GradingGroup"`, with members attached via `IfcRelAssignsToGroup`.

**Not `IfcBuiltSystem`.** The IRROADWP3 Annex I example diagrams suggest `IfcBuiltSystem[EARTHWORK]`, but `IfcBuiltSystemTypeEnum` does **not** include `EARTHWORK` as a valid value (the enum is `EROSIONPREVENTION, FENESTRATION, FOUNDATION, LOADBEARING, MOORING, OUTERSHELL, PRESTRESSING, RAILWAYLINE, RAILWAYTRACK, REINFORCING, SHADING, TRACKCIRCUIT, TRANSPORT, USERDEFINED, NOTDEFINED`). Using `IfcBuiltSystem[USERDEFINED]` with `ObjectType="Earthwork"` works schema-wise but is a semantic stretch — `IfcBuiltSystem` is defined as "built elements forming a particular structural or service part of a facility," which site grading is not.

`IfcGroup` is the parent type of `IfcSystem` (and therefore `IfcBuiltSystem`). It has no `PredefinedType` constraint, accepts arbitrary `ObjectType` strings, and will round-trip through any compliant viewer without semantic confusion. This is the simpler, honest mapping.

### 2.7 Spatial hierarchy

```
IfcProject
└── IfcSite  [IfcRelAggregates from IfcProject]
    │
    ├── IfcGeographicElement [TERRAIN]                  [IfcRelContainedInSpatialStructure from IfcSite]
    │   └── Rep: IfcTriangulatedIrregularNetwork (existing ground TIN)
    │
    ├── IfcEarthworksCut [EXCAVATION]                   [IfcRelContainedInSpatialStructure from IfcSite]
    │   ├── Rep: IfcPolygonalFaceSet Closed (cut volume solid)
    │   └── Voids IfcGeographicElement via IfcRelVoidsElement
    │
    ├── IfcEarthworksFill [SUBGRADE] (site composite)   [IfcRelContainedInSpatialStructure from IfcSite]
    │   ├── Rep 1: IfcTriangulatedIrregularNetwork (proposed TIN)
    │   ├── Rep 2: IfcPolygonalFaceSet Closed (fill volume solid)
    │   └── Aggregates per-group composite fills via IfcRelAggregates
    │
    └── IfcAlignment (feature line)                     [IfcRelContainedInSpatialStructure from IfcSite]
        └── Rep: IfcPolyline / IfcIndexedPolyCurve (3D polyline)

IfcGroup ObjectType="GradingGroup"     (separate, no spatial placement)
├── Contains IfcEarthworksCut instances via IfcRelAssignsToGroup
├── Contains IfcEarthworksFill instances (slope + interior) via IfcRelAssignsToGroup
└── Contains IfcAlignment feature lines via IfcRelAssignsToGroup
```

**Why `IfcGroup` is outside the spatial tree.** `IfcGroup` is not an `IfcProduct` and has no `ObjectPlacement`. `IfcRelContainedInSpatialStructure.RelatedElements` is typed `SET OF IfcProduct` — placing `IfcGroup` there would be a schema violation. Grading groups are discovered by querying `IfcGroup` instances with `ObjectType='GradingGroup'`, not by walking the spatial tree.

**Why `IfcGeomodel` is not used.** Per buildingSMART, `IfcGeomodel` is "Representation of the concept of a volumetric geological and geotechnical model" — i.e., a subsurface stratigraphic interpretation derived from boreholes and ground-penetrating measurement. Saikei models surface grading and earthwork only; using `IfcGeomodel` would mis-type the output as a geotechnical interpretation model. The earthwork entities are all `IfcElement` subtypes and sit directly under `IfcSite` via `IfcRelContainedInSpatialStructure` — the same pattern Bonsai uses for buildings, alignments, and other site-level elements.

**Relationship summary:**

- `IfcProject → IfcSite`: `IfcRelAggregates` (spatial structure)
- `IfcSite → IfcGeographicElement [TERRAIN]`: `IfcRelContainedInSpatialStructure`
- `IfcSite → IfcEarthworksCut`: `IfcRelContainedInSpatialStructure`
- `IfcSite → IfcEarthworksFill (site composite)`: `IfcRelContainedInSpatialStructure`
- `IfcSite → IfcAlignment (feature line)`: `IfcRelContainedInSpatialStructure`
- `IfcEarthworksFill (site composite) → IfcEarthworksFill (per-group composite)`: `IfcRelAggregates`
- `IfcEarthworksFill (per-group composite) → IfcEarthworksFill (slope / interior)`: `IfcRelAggregates`
- `IfcGeographicElement ← IfcEarthworksCut`: `IfcRelVoidsElement` (void relation)
- `IfcGroup → members`: `IfcRelAssignsToGroup`

**Aggregation tree is flat.** Every `IfcEarthworksFill` has at most one `RelatingObject` parent. Site composite is the root, per-group composites are direct children, slope/interior fills are leaves. This satisfies `IfcRelAggregates` cardinality (each `RelatedObject` has a unique `RelatingObject`).

### 2.8 Object placement

All earthwork products (`IfcGeographicElement`, `IfcEarthworksCut`, `IfcEarthworksFill`) use:
- `IfcLocalPlacement` with identity `IfcAxis2Placement3D` (origin `(0,0,0)`, axes aligned to project coordinate system).
- Absolute world positioning is handled by `IfcMapConversion` at the project level — the same pattern the existing alignment tool uses.

This is prescriptive. Implementors should not use non-identity local placements for earthwork entities; it breaks the georeferencing contract shared with alignments.

### 2.9 Bounding box representation

Every terrain surface authored by Saikei attaches an `IfcBoundingBox` representation alongside the `SurfaceModel` representation:
- `RepresentationIdentifier='Box'`, `RepresentationType='BoundingBox'`.
- Provides `IfcBoundingBox.Corner` (min x,y,z) + `XDim`, `YDim`, `ZDim`.

This enables viewer-side LOD and culling without forcing the full TIN parse for every frame. Site-scale surfaces (multi-hectare) are large enough that this matters in practice.

### 2.10 Georeferencing

**Horizontal:** `IfcMapConversion` with `SourceCRS=IfcGeometricRepresentationContext` and `TargetCRS=IfcProjectedCRS` — the established Saikei pattern.

**Vertical:** `IfcProjectedCRS.VerticalDatum` is required (not optional) for surfaces. Values: `NAVD88`, `NGVD29`, `WGS84_ELLIPSOIDAL`, or project-specific string. `IfcMapConversion.OrthogonalHeight` encodes the geoid-ellipsoid separation at the site centroid. Without these, 0.1 ft vertical errors accumulate and drainage design becomes unreliable through IFC round-trip.

This is a shared gap with the current alignment implementation; fixing it here for surfaces creates the pattern for alignments to adopt.

---

## 3. Property Sets and Quantity Sets

### 3.1 Standard IFC 4.3 Psets — use these first

| Entity | Standard Pset | Use for |
|---|---|---|
| `IfcGeographicElement` | `Pset_GeographicElementCommon` | `Status` (default `"NEW"` at creation, satisfies `HasProperties [1:?]`), `IsLandmarked`, `Reference` |
| `IfcEarthworksFill` | `Pset_EarthworksFillCommon` | `ContaminationLevel`, `FillMaterial`, `IsTopsoilStripped` |
| `IfcEarthworksCut` | `Pset_EarthworksCutCommon` | `CuttingType`, `ContaminationLevel`, `IsTopsoilStripped` |

Populate these on every relevant entity. Do not duplicate their properties in custom Psets.

Soil-mechanical properties (bearing capacity, plasticity, moisture content) are out of scope for Saikei's surface-only modeling. If a project later requires geotechnical investigation data, that's a separate concern that introduces `IfcGeotechnicalStratum` and `IfcBorehole` for subsurface — Saikei does not currently extend in that direction.

### 3.2 Standard IFC 4.3 Qtos — volumes live here

| Entity | Qto | Quantities |
|---|---|---|
| `IfcEarthworksFill` | `Qto_EarthworksFillBaseQuantities` | `Length`, `Width`, `Depth`, `CompactedVolume`, `LooseVolume` |
| `IfcEarthworksCut` | `Qto_EarthworksCutBaseQuantities` | `Length`, `Width`, `Depth`, `UndisturbedVolume`, `LooseVolume`, `Weight` |

All earthwork volumes Saikei computes go here, not in custom Psets. QTO tools (Solibri, CostX, iTWO) query these standard Qtos and will find Saikei volumes.

### 3.3 Saikei custom Psets — only for what standards don't cover

Naming follows bSI convention: `Pset_<Organization><Topic>` with no internal underscores in the topic portion.

| Pset | Attached to | Purpose |
|---|---|---|
| `Pset_SaikeiGradingSource` | `IfcGroup` (grading group) | Source metadata: criteria reference, author, timestamp, grading group version |
| `Pset_SaikeiGradingSurface` | `IfcTriangulatedIrregularNetwork` host entity | Triangulation tolerance, breakline count, vertex count, boundary polygon reference |
| `Pset_SaikeiGradingCriteria` (template) | `IfcPropertySetTemplate` | Reusable criteria definitions: `TargetKind` (`P_ENUMERATEDVALUE`, four values), `TargetReference` (`IfcLabel` — heterogeneous content: GUID for `kind=surface`, stringified numeric for elevation/distance variants; readers parse against `TargetKind`), `CutSlope` / `FillSlope` (`IfcPositiveRatioMeasure`), `MaxDistance` (`IfcPositiveLengthMeasure`, optional), `RetainingWallAtLimit` (`IfcBoolean`) |
| `Pset_SaikeiGradingShrinkSwell` | `IfcEarthworksFill`, `IfcEarthworksCut` | `ShrinkFactor`, `SwellFactor` (not in standard Qtos — only Compacted/Loose volumes are) |
| `Pset_SaikeiFeatureLineCommon` | `IfcAlignment` (feature line) | `IsClosed`, `Source`, `GradingGroupGuid`, `ElevationSource` |
| `Pset_SaikeiBreaklineCommon` | `IfcAnnotation` (breakline polyline) | `Kind` (`standard` / `wall` / `non_destructive` / `proximity`), `Source` (`manual` / `feature_line` / `corridor_extract`), `GradingGroupGuid` (optional link to parent group) |
| `Pset_SaikeiGradingAlignment` | `IfcGroup` (grading group), `IfcEarthworksFill` | `AlignmentGuid`, `StartStation`, `EndStation` — for grading adjacent to a corridor |

### 3.4 Classification

Every `IfcEarthworksCut` and `IfcEarthworksFill` authored by Saikei is classified via `IfcRelAssociatesClassification` using **OmniClass Table 22** (Work Results). Default codes:

| Element | OmniClass Code | Title |
|---|---|---|
| Bulk excavation cut | `22-07 31 00` | Earthwork |
| Structural excavation | `22-07 31 16` | Excavation and Fill |
| Embankment / general fill | `22-07 31 23` | Fill |
| Topsoil stripping | `22-07 31 14` | Site Clearing (topsoil removal) |

These map to CSI MasterFormat Division 31 codes that US civil engineers and estimators recognize. Saikei authors the classification automatically based on the `PredefinedType` of the earthwork entity. Users can override or add additional classifications (Uniclass, MasterFormat direct) via UI.

Classification matters for interop with QS/cost-estimating software that queries by classification code, not by IFC entity type.

---

## 4. Architecture

Saikei grading follows the mandatory Bonsai 3-layer architecture. Dion's clarification is strictly enforced: **Core = workflow orchestration only (no math, no `bpy`, no IFC creation); Tool = all implementations; UI = operators and panels.**

### 4.1 Module layout

```
src/bonsai/bonsai/
├── core/
│   ├── alignment.py          (existing)
│   ├── surface.py            (new — workflow orchestration for TIN surfaces)
│   ├── grading.py            (new — orchestration for feature lines / criteria / gradings)
│   └── earthwork.py          (new — orchestration for volume calcs and IFC export)
├── tool/
│   ├── alignment.py          (existing)
│   ├── surface.py            (new — TIN math, breakline CDT, IFC authoring)
│   ├── grading.py            (new — slope projection, group composition)
│   └── earthwork.py          (new — prismoidal volumes, cut/fill map)
└── bim/module/
    ├── alignment/            (existing)
    ├── surface/              (new — surface panel, operators, props)
    ├── grading/              (new — grading panel, operators, props)
    └── earthwork/            (new — earthwork panel, operators, props)
```

### 4.2 Operator prefixes

Following the established `CIVIL_OT_*` / `CIVIL_PT_*` convention:

- Surface: `CIVIL_OT_surface_*`, `CIVIL_PT_surface_*`
- Grading: `CIVIL_OT_grading_*`, `CIVIL_PT_grading_*`
- Earthwork: `CIVIL_OT_earthwork_*`, `CIVIL_PT_earthwork_*`

All operators inherit `tool.Ifc.Operator` and implement `_execute()` for automatic undo/redo.

### 4.3 Core-to-Tool pattern

**Core never invents API paths.** The existing `core/alignment.py` pattern is: core orchestrates by calling tool methods; tool methods call real `ifcopenshell.api.*` functions. Core **does not** call `tool.Ifc.run("some.fabricated.path")`.

**B3 sequencing.** The three APIs (`ifcopenshell.api.surface`, `ifcopenshell.api.grading`, `ifcopenshell.api.earthwork`) are built FIRST as Phases 1–3 in the IfcOpenShell repo (`src/ifcopenshell-python/ifcopenshell/api/<domain>/`). Bonsai tool methods (Phases 4–6) then call those APIs rather than `ifc_file.create_entity()` directly. This mirrors the existing `ifcopenshell.api.alignment` pattern Rick Brice landed and ensures the API surface is stable before Bonsai depends on it.

**Cross-API helper sharing.** `ifcopenshell.api.grading._shared` is the de-facto civil-engineering shared helper module. Phase 3 (`api.earthwork`) imports the following directly from it rather than duplicating: `_resolve_site`, `identity_placement`, `to_point_list`, `compute_bounding_box`, `apply_omniclass_classification`, `attach_earthworks_fill_common`, `aggregate_under`. Earthwork-specific helpers (`attach_earthworks_cut_common`, predefined-type validators) live in `ifcopenshell.api.earthwork._shared`. The cross-package private import is intentional and documented; it keeps Phase 3 from re-creating a parallel set of helpers and ensures the two modules stay in lock-step. If a future refactor wants to relocate the shared helpers (e.g., to `ifcopenshell.util.civil` or a public surface API), the imports are concentrated and the move is a single search-and-replace.

**Multi-site footgun.** `_resolve_site(site=None)` returns the project's *first* `IfcSite`. Multi-site projects (rare but valid in IFC 4.3 — site-aggregation hierarchies, sub-sites, or projects with both an existing-conditions site and a proposed-development site) must pass `site=` explicitly to every earthwork/grading API call to avoid silent attachment to the wrong site. The Saikei API does not currently warn when multiple sites are present; Bonsai-side callers in Phases 4–6 should check `len(file.by_type("IfcSite")) > 1` and prompt the user if so.

**Tracked-but-not-fixed: body-subcontext duplication.** `_get_or_create_body_subcontext` exists in both `ifcopenshell.api.surface._representation_context` and `ifcopenshell.api.earthwork.add_volume_solid_representation`. ~20 lines of isolated duplication. Cleanest long-term fix is to expose `get_body_subcontext` publicly on the surface API or push the get-or-create logic up to `ifcopenshell.util.representation` since it isn't Saikei-specific. Not blocking; flagged for a future v3.2.x cleanup pass.

See §11 for the phase work breakdown and §6 for the corrected core/tool code patterns.

### 4.4 Surface math backend

Saikei uses two libraries for triangulation:

- **`scipy.spatial.Delaunay`** — unconstrained Delaunay (point cloud → TIN, no breaklines). Used by the `Triangulator.unconstrained()` path.
- **`shapely.constrained_delaunay_triangles`** (Shapely 2.1+) — constrained Delaunay honoring breakline polylines and hole/void polygons. Used by the `Triangulator.constrained()` path.

**Pinned versions** (declared in `src/bonsai/pyproject.toml` under the saikei optional-dependencies group; **not** in `src/ifcopenshell-python/pyproject.toml`, since the IFC API in Phases 1–3 does not import scipy or shapely — those libraries are consumed only by Bonsai's `tool.Surface` math layer, Phase 4 onward):

- `scipy >= 1.11, < 2.0`
- `shapely >= 2.1, < 3.0`
- `numpy >= 1.24, < 3.0` (already required by Bonsai)

**Install path.** Neither `scipy` nor `shapely` ships with Blender 5.0; they install into the user-extensions Python at:

```
%APPDATA%\Blender Foundation\Blender\5.0\extensions\.local\lib\python3.11\site-packages\
```

Saikei's Blender extension manifest (`bonsai/blender_manifest.toml`) bundles wheels for both libraries via the `wheels/` directory mechanism so installation is zero-friction for end users. CI verifies the wheels are present before building the extension package.

**Triangulator abstraction.** A `Triangulator` protocol in `tool/surface.py` abstracts the backend so it can be swapped (e.g., for the `triangle` package or a compiled library if site sizes exceed ~1M triangles):

```python
from typing import Protocol
import numpy as np

class Triangulator(Protocol):
    def unconstrained(
        self,
        points: np.ndarray,                    # shape (N, 2) or (N, 3)
    ) -> np.ndarray:                           # shape (M, 3), vertex indices
        ...

    def constrained(
        self,
        points: np.ndarray,                    # shape (N, 3)
        breakline_segments: list[tuple[int, int]],
        outer_boundary: "shapely.Polygon",
        holes: list["shapely.Polygon"],
        voids: list["shapely.Polygon"],
    ) -> tuple[np.ndarray, np.ndarray]:        # (triangles (M, 3), flags (M,))
        ...
```

`tool.Surface` holds a `Triangulator` instance as a class attribute, defaulting to `_ScipyShapelyTriangulator`. Tests override it with deterministic stubs. Performance target: under 2 s on 100k vertices for the unconstrained path, under 10 s for the constrained path — measured on the Sprint 1 acceptance fixture.

### 4.5 Shared Bonsai tools reused

- `tool.Ifc` — `get()`, `link()`, `unlink()` for IFC entity access.
- `tool.Loader.create_generic_shape()` — `IfcTriangulatedIrregularNetwork` → Blender mesh via IfcOpenShell geometry engine.
- `tool.Georeference` — `enh2xyz` / `xyz2enh` for coordinate transforms. Surfaces store engineering coordinates in IFC, render near-origin in Blender for 32-bit float precision.
- `tool.Collector.assign()` — spatial hierarchy placement.
- `tool.Blender` — `validate_shader_batch_data`, `scale_font_size` for annotation.

### 4.6 Tool-side state registry

Tool classes (`tool.Surface`, `tool.Grading`, `tool.Earthwork`) maintain in-memory caches of their data primitives keyed by `(ifc_file_id, guid)`. The cache is **lazy-rehydrating** from IFC: `tool.Surface.get(ifc_file, guid)` returns the cached `CivilSurface` if present, otherwise reads the IFC entity, reconstructs the dataclass, caches it, and returns it.

```python
class Surface:
    _registry: dict[tuple[int, str], "CivilSurface"] = {}

    @classmethod
    def get(cls, ifc_file: "ifcopenshell.file", guid: str) -> "CivilSurface":
        key = (id(ifc_file), guid)
        if key not in cls._registry:
            cls._registry[key] = cls._rehydrate_from_ifc(ifc_file, guid)
        return cls._registry[key]

    @classmethod
    def invalidate(cls, ifc_file: "ifcopenshell.file", guid: str) -> None:
        cls._registry.pop((id(ifc_file), guid), None)

    @classmethod
    def clear(cls) -> None:
        cls._registry.clear()
```

**Lifecycle rules:**

- The cache is invalidated on edit operations that modify the IFC entity (e.g., `retriangulate` calls `invalidate` after committing IFC writes).
- Multi-file usage works correctly because the key includes `id(ifc_file)`.
- Headless tests call `Surface.clear()` in fixture teardown to prevent cross-test contamination.
- IFC is the source of truth; the cache is an optimization. Reopening a file rehydrates fresh.

The same pattern applies to `tool.Grading._registry` (`FeatureLine` / `GradingObject` / `GradingGroup` / `GradingCriteria`) and `tool.Earthwork._registry` (keyed by `(ifc_file_id, existing_guid, proposed_guid)` since one existing surface can pair with multiple proposed surfaces).

### 4.7 Core function signature pattern

Core functions follow the alignment-precedent of **explicit class injection** (`core/alignment.py`):

```python
# Existing precedent — core/alignment.py
def create_alignment(
    ifc_tool: "type[tool.Ifc]",
    alignment_tool: "type[tool.Alignment]",
    name: str,
    start_station: float = 0.0,
) -> "ifcopenshell.entity_instance":
    ...
```

Saikei core functions inject the same way:

```python
# core/surface.py
def create_surface_from_points(
    ifc_tool: "type[tool.Ifc]",
    surface_tool: "type[tool.Surface]",
    name: str,
    points: list[tuple[float, float, float]],   # NOT np.ndarray — keep core import-clean
    kind: str,
) -> str:
    ...
```

**Why explicit injection.** Core becomes unit-testable with mock tool classes; MCP wrappers see exactly which tool surfaces a function touches; the pattern stays consistent with the existing alignment code in the same `core/` directory.

**Type-annotation rule.** Core function signatures use only built-in types and `ifcopenshell` types. They do **not** import `numpy`, `shapely`, or `bpy` at module top. Where a signature needs to accept point arrays, the type is `list[tuple[float, float, float]]`; the tool layer converts to `np.ndarray` internally on the way in and back to native Python types on the way out. This keeps `core/` agent-callable and headless without pulling the math stack into every importer.

---

## 5. Data Model

Data primitives live in `tool/surface.py`, `tool/grading.py`, `tool/earthwork.py`. They are not Core-facing — Core only sees them via tool-class methods.

```python
# tool/surface.py

from dataclasses import dataclass, field
from typing import Literal
import numpy as np
import shapely


@dataclass
class Breakline:
    """A 3D polyline that must be honored as constrained edges in a TIN.
    Persisted to IFC as IfcAnnotation with IfcPolyline representation."""
    guid: str
    name: str
    polyline: list[tuple[float, float, float]]   # (x, y, z) per vertex
    kind: Literal["standard", "wall", "non_destructive", "proximity"]
    source: str                                    # "manual", "feature_line", "corridor_extract"
    ifc_annotation_id: int | None = None           # step id of IfcAnnotation


@dataclass
class CivilSurface:
    """An engineered or measured 3D surface — the central grading primitive."""
    guid: str
    name: str
    kind: Literal["existing", "proposed_group", "proposed_site"]
    points: np.ndarray                             # shape (N, 3), xyz coordinates
    triangles: np.ndarray                          # shape (M, 3), vertex indices into points
    triangle_flags: np.ndarray                     # shape (M,), IFC Flags list values
    breaklines: list[Breakline] = field(default_factory=list)
    outer_boundary: shapely.Polygon | None = None  # 2D, XY only. None → tool.Surface auto-computes
                                                   # the convex hull of `points` at construction
                                                   # time (see §6.4). Volume-calc domain is never
                                                   # left undefined.
    holes: list[shapely.Polygon] = field(default_factory=list)   # 2D regions where this surface is
                                                                 # absent but other surfaces may
                                                                 # show through (Flag = -1 per IFC §2.1)
    voids: list[shapely.Polygon] = field(default_factory=list)   # 2D regions permanently excluded
                                                                 # with no fallback (Flag = -2)

    # IFC linkage — depends on surface kind
    # existing:       host is IfcGeographicElement [TERRAIN]
    # proposed_group: host is IfcEarthworksFill [SUBGRADE] within a grading group
    # proposed_site:  host is IfcEarthworksFill [SUBGRADE] at the composite site level
    ifc_host_entity_id: int | None = None          # step id of host IfcProduct
    ifc_tin_representation_id: int | None = None   # step id of IfcTriangulatedIrregularNetwork
    ifc_bbox_representation_id: int | None = None  # step id of IfcBoundingBox

    metadata: dict = field(default_factory=dict)
```

**How the polygon fields map to IFC.** `outer_boundary`, `holes`, and `voids` are **authoring inputs** at the Saikei tool layer — caller-side polygon definitions used by the `Triangulator` to (a) clip the triangulation to the boundary and (b) decide which sub-triangles fall inside hole / void regions. At persistence time, `tool.Surface.author_ifc_tin_representation` walks the resulting `triangle_flags` array and translates: triangles whose centroid lies within a hole polygon get Flag `-1`; within a void polygon get Flag `-2`; otherwise the breakline-edge bit mask (1–7) or `0`. The IFC entity stores per-triangle integers; the polygons themselves are not persisted. On read-back from IFC, the polygons can be recovered (approximately) by tracing the boundaries of contiguous Flag = -1 / Flag = -2 sub-graphs of triangles.

```python
# tool/grading.py

@dataclass
class FeatureLine:
    """A 3D polyline used as a grading footprint. Civil 3D's Feature Line analog.
    Persisted to IFC as IfcAlignment with IfcPolyline/IfcIndexedPolyCurve representation."""
    guid: str
    name: str
    vertices: list[tuple[float, float, float]]
    closed: bool                                   # most site pads are closed loops
    grading_group: str | None = None               # parent grading group guid
    ifc_alignment_id: int | None = None            # step id of IfcAlignment


@dataclass
class GradingCriteria:
    """A rule for projecting a slope from a feature line. Civil 3D's Grading Criteria analog.

    Civil 3D ships four base target kinds; Saikei MVP implements all four.
    Criteria are persisted as IfcPropertySetTemplate at project scope (reusable), with
    IfcPropertySet instances bound to the template on each grading group that uses the
    criteria.
    """
    guid: str
    name: str
    target_kind: Literal["surface", "elevation", "relative_elevation", "distance"]
    target_ref: str | float                        # surface guid, abs elevation, rel elev, or distance
    cut_slope: float                               # ratio (H:V), e.g., 2.0 means 2:1
    fill_slope: float                              # ratio (H:V), e.g., 3.0 means 3:1
    max_distance: float | None = None              # daylight cap; None = unlimited
    retaining_wall_at_limit: bool = False          # insert wall if cap hit before target reached
    ifc_template_id: int | None = None             # step id of IfcPropertySetTemplate


@dataclass
class GradingObject:
    """A feature line + criteria, producing slope projection geometry.

    Civil 3D's Grading analog. Has dynamic relationship to its footprint — edits to
    the feature line trigger rebuild. The slope projection produces a slope fill
    region persisted as IfcEarthworksFill [SLOPEFILL].
    """
    guid: str
    name: str
    footprint: FeatureLine
    criteria: GradingCriteria
    target_surface_guid: str | None                # for target_kind="surface"
    daylight_line: list[tuple[float, float, float]]  # computed — 3D polyline of tie points
    projection_triangles: np.ndarray               # computed — slope face triangles (M, 3)
    projection_points: np.ndarray                  # computed — xyz coords (N, 3)
    ifc_slope_fill_id: int | None = None           # step id of IfcEarthworksFill [SLOPEFILL]


@dataclass
class GradingGroup:
    """A collection of grading objects composing one graded feature.

    Civil 3D's Grading Group analog. Produces one composite proposed surface and
    one earthwork report. Persisted to IFC as IfcGroup with ObjectType="GradingGroup".
    """
    guid: str
    name: str
    members: list[GradingObject] = field(default_factory=list)
    interior_fill: Literal["none", "flat", "interpolate_from_boundary", "from_surface"] = "interpolate_from_boundary"
    interior_fill_source_guid: str | None = None   # for interior_fill="from_surface"
    output_surface_guid: str | None = None         # computed composite proposed surface
    target_surface_guid: str | None = None         # existing ground reference

    # IFC linkage
    ifc_group_id: int | None = None                # step id of IfcGroup
    ifc_composite_fill_id: int | None = None       # step id of aggregating IfcEarthworksFill
    ifc_interior_fill_id: int | None = None        # step id of interior IfcEarthworksFill [SUBGRADE]
```

**Design note on `interior_fill`.** Civil 3D's grading groups have an ambiguous "infill" behavior that trips up new users. Saikei makes the interior fill strategy explicit — the engineer must pick one of four options when creating the group, and it's visible as a property thereafter. The interior fill is authored as a distinct `IfcEarthworksFill[SUBGRADE]` entity, separate from the slope fills, enabling independent quantity takeoff (contractors typically specify different material and compaction for pad subgrade vs. slope fill).

```python
# tool/earthwork.py

@dataclass
class VolumeResult:
    """Output of a TIN-to-TIN prismoidal volume calculation.

    Volumes are written to standard IFC Qtos:
      Qto_EarthworksCutBaseQuantities: UndisturbedVolume, LooseVolume
      Qto_EarthworksFillBaseQuantities: CompactedVolume, LooseVolume

    Shrink/swell factors are written to Pset_SaikeiGradingShrinkSwell (not standard).
    """
    existing_surface_guid: str
    proposed_surface_guid: str
    cut_volume_m3: float                           # undisturbed (bank) cubic meters
    fill_volume_m3: float                          # in-place (compacted) cubic meters
    net_volume_m3: float                           # cut - fill; positive = net excavation
    cut_cubic_yards: float
    fill_cubic_yards: float
    net_cubic_yards: float
    shrink_factor: float = 1.0                     # fill-side shrinkage (ratio compacted/bank)
    swell_factor: float = 1.0                      # cut-side swell (ratio loose/bank)
    compacted_fill_m3: float = 0.0                 # fill_volume_m3 (already compacted by definition)
    loose_cut_m3: float = 0.0                      # cut_volume_m3 * swell_factor
    per_triangle_deltas: np.ndarray | None = None  # optional, for cut/fill color map
    color_map_mesh_id: int | None = None           # Blender mesh id for overlay
```

---

## 6. Workflow Reference

### 6.1 Dataflow diagram

```
┌──────────────┐     ┌──────────────┐     ┌───────────────┐
│ Existing     │     │ Feature      │     │ Grading       │
│ Ground       │     │ Lines        │     │ Criteria      │
│ (CivilSurf)  │     │ (IfcAlign.)  │     │ (Pset tmpl)   │
└──────┬───────┘     └──────┬───────┘     └───────┬───────┘
       │                    │                     │
       │                    ▼                     │
       │            ┌──────────────┐              │
       └───────────▶│ Grading      │◀─────────────┘
                    │ Object       │
                    │ (FL+Crit)    │
                    │              │
                    │ → IfcEWFill  │
                    │   [SLOPEFILL]│
                    └──────┬───────┘
                           │ N objects per group
                           ▼
                    ┌──────────────┐
                    │ Grading      │
                    │ Group        │◀── Interior fill strategy
                    │              │        │
                    │ → IfcGroup   │        ▼
                    │   ObjectType │    IfcEWFill
                    │   ="Grading  │    [SUBGRADE]
                    │   Group"     │    (interior)
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐     ┌──────────────┐
                    │ Composite    │     │ Existing     │
                    │ Proposed     │     │ Surface      │
                    │ Surface      │     │              │
                    │ (IfcEWFill   │     │ (IfcGeotech  │
                    │  composite)  │     │  Stratum)    │
                    └──────┬───────┘     └──────┬───────┘
                           │                    │
                           └─────────┬──────────┘
                                     ▼
                            ┌──────────────────┐
                            │ Earthwork        │
                            │ Volumes (TIN-TIN)│
                            └────────┬─────────┘
                                     ▼
                            ┌──────────────────┐
                            │ Qto sets written:│
                            │ - Qto_EWCut...   │
                            │ - Qto_EWFill...  │
                            │ Cut/Fill solids  │
                            │ as IfcPolygonal  │
                            │ FaceSet Closed   │
                            └──────────────────┘
```

### 6.2 Slope projection algorithm (criteria-to-surface)

This is the central grading computation. It runs once when a `GradingObject` is added to a group, and re-runs whenever the feature line is edited.

```
For each segment between consecutive vertices of the feature line:
    For each sample point along the segment (spaced by configured interval):
        1. Get footprint point P₀ = (x, y, z) at the sample position on feature line.
        2. Query target surface Z at (x, y) → z_target.
        3. If z_target > z₀: this is a cut (feature line below ground).
           Use cut_slope; project outward horizontally-outward + upward.
        4. If z_target < z₀: this is a fill (feature line above ground).
           Use fill_slope; project outward horizontally-outward + downward.
        5. March outward at the chosen slope until one of:
             a. Intersection with target surface (daylight point P_tie).
             b. max_distance reached — insert retaining wall if configured,
                otherwise terminate slope at that distance.
        6. Record P_tie as a point on the daylight line.
    Triangulate the ribbon between the feature line segment and its corresponding
    daylight segment — two triangles per sample step, respecting the outward
    normal convention.
```

**Outward direction:** for closed feature lines (pad perimeters), outward is "away from the interior" — determined by polygon orientation (counterclockwise = outward is to the right of the direction of traversal). For open feature lines, the user specifies which side the projection goes on (matches Civil 3D's "Apply to Side" prompt).

### 6.3 Grading group composition

When a group has multiple grading objects, its composite proposed surface is built from:

1. All feature line vertices (at their authored elevations).
2. All daylight line vertices (at their computed elevations).
3. All projection ribbon triangles (one set per grading object → `IfcEarthworksFill[SLOPEFILL]`).
4. Interior fill triangles, per the `interior_fill` strategy → `IfcEarthworksFill[SUBGRADE]`:
   - `none` — no interior, surface has a hole. No interior fill entity authored.
   - `flat` — interior is a flat surface at the average feature line elevation.
   - `interpolate_from_boundary` — Delaunay triangulation using feature line vertices only.
   - `from_surface` — use another named surface for the interior (useful for pit-bottom or pre-designed pad-bottom cases).

The composite is authored as an `IfcEarthworksFill[SUBGRADE]` entity that aggregates the slope fills and interior fill via `IfcRelAggregates`. It carries both the proposed TIN (as `SurfaceModel` representation) and the composite fill solid (as a `Body` / `Tessellation` representation per §2.4).

**Cross-surface composition uses the IFC `Flags` semantic.** Where a grading group's proposed surface is meant to "fall through" to existing ground (e.g., the area between adjacent grading groups, or the no-grading region of a partial-site project), the composite proposed TIN's covering triangles in that XY region are authored with `Flag = -1` (Hole). Per IFC 4.3.2 §8.8.3.48, downstream readers combine surfaces by retaining Voids (-2) and overriding Holes (-1) wherever another surface has visible geometry at the same XY. This means Saikei does not need a custom merge algorithm: author the per-surface Flags correctly and the standardized rules handle composition. Use `Flag = -2` (Void) only for regions that must remain empty regardless of any other surface — e.g., under a building footprint, where the existing-ground TIN should also be excluded.

### 6.4 TIN-to-TIN prismoidal volumes

Civil 3D's most accurate volume method (its `Volumes Dashboard → Composite Volumes`). The implementation:

```
Input: surface_existing, surface_proposed (both CivilSurface)
Output: cut_volume, fill_volume

1. Resolve outer boundaries (fallback rule):
     For each surface s ∈ {existing, proposed}:
       if s.outer_boundary is None:
         s.outer_boundary = shapely.MultiPoint(s.points[:, :2]).convex_hull
   The volume domain is never undefined; an unconstrained TIN defaults to its
   convex hull.

2. Compute domain = outer_boundary(existing) ∩ outer_boundary(proposed)
   minus holes/voids from either.

3. For each pair of triangles (t_e ∈ existing, t_p ∈ proposed) whose XY projections
   overlap within the domain (broad phase: shapely.STRtree on existing triangles,
   query by proposed triangle bounds — turns O(N²) into O(N log N) on typical sites):
     a. intersection_polygon = t_e.xy ∩ t_p.xy ∩ domain
     b. Triangulate intersection_polygon → sub-triangles.
     c. For each sub-triangle s:
          z_e_avg = mean of existing surface Z at s's three vertices (interpolated)
          z_p_avg = mean of proposed surface Z at s's three vertices (interpolated)
          delta_z = z_e_avg - z_p_avg
          volume = area(s) * delta_z          # signed
          if delta_z > 0: cut_volume += volume
          else:           fill_volume += (-volume)

4. Return cut_volume, fill_volume (both positive magnitudes).
```

Grid-based alternatives are faster but lose fidelity on narrow features — MVP uses TIN prismoidal only.

### 6.5 Cut/fill solid construction

After volume calculation, Saikei constructs closed `IfcPolygonalFaceSet` solids for the cut and fill volumes. The algorithm has four named stages; full pseudocode is a Sprint 3 prep deliverable, but the named building blocks below are stable.

**Stage 1 — Region extraction (zero-delta contour).** Reuse the per-sub-triangle `delta_z` from §6.4 step 3c. A contiguous cut region is a maximal connected set of sub-triangles where `delta_z > 0`; a contiguous fill region is the same with `delta_z < 0`. Region boundaries are the polylines where `delta_z = 0` (where existing and proposed surfaces cross). Algorithm:

- Walk the §6.4 sub-triangle output, tagging each by sign of `delta_z`.
- Build adjacency graph on sub-triangles sharing an edge with the same sign.
- Each connected component is one region. Region boundary = ordered list of edges shared with opposite-sign components or with the domain boundary.
- Reference algorithm: same connected-components walk used in marching-squares for contour extraction; shapely's `unary_union` on per-sign sub-triangle sets gives the region polygons directly for the simple case, with manifold edges recovered from the union ring.

**Stage 2 — Top and bottom face clipping.** For each region, the top face is the portion of the proposed TIN above the region, and the bottom is the portion of the existing TIN below it. Triangles that straddle the region boundary must be clipped, not whole-included. Algorithm:

- Top face: `shapely.intersection(proposed_triangle.xy, region_polygon)` for every proposed triangle that intersects the region's bounding box (broad phase via STRtree). Re-triangulate each non-trivial intersection polygon. Lift Z back via the proposed TIN's `z_at(x, y)`.
- Bottom face: same but with the existing TIN, and triangles emitted with reversed winding.
- Reference algorithm: Sutherland-Hodgman polygon clipping is the textbook fallback if shapely's GEOS-backed intersection misbehaves on a degenerate triangle. Both produce equivalent results in the non-degenerate cases.

**Stage 3 — Side-face strips between two non-coincident 3D loops.** The region boundary projects to two distinct 3D polylines — one on the top face (proposed TIN), one on the bottom (existing TIN). Side faces are triangulated strips between them:

- Walk the top and bottom boundary loops in lockstep, by shared (x, y) projection (vertices match 1:1 since both come from the same 2D `region_polygon`).
- For each consecutive pair `(top[i], top[i+1], bottom[i], bottom[i+1])`, emit two triangles: `(top[i], top[i+1], bottom[i+1])` and `(top[i], bottom[i+1], bottom[i])`. Outward winding (opposite to top, same direction as bottom) keeps the solid's outward normals consistent.

**Stage 4 — Watertightness check.** Before emitting the `IfcPolygonalFaceSet`:

- Verify every edge is shared by exactly two faces (manifold edge count).
- Verify Euler characteristic: `V - E + F = 2` for a single connected solid (more for multi-region unions, equal to `2 * num_regions`).
- Verify signed volume of the BRep agrees with the §6.4 prismoidal volume to within `1e-3` (relative). If it doesn't, the construction is rejected and an error is raised — better to fail loudly than ship a leaky solid.

Once all four stages pass, assemble all triangles into a single `IfcPolygonalFaceSet` per region with `Closed=TRUE` and emit. Cut regions mirror the construction with existing as "top" and proposed as "bottom."

The result is a watertight closed BRep solid that round-trips through any IFC viewer supporting `IfcPolygonalFaceSet`. Full pseudocode (with handling for degenerate cases — collinear region boundaries, regions touching the domain edge, sub-triangles smaller than the coordinate ε) is a v3.3 prep deliverable scheduled before Sprint 3 begins.

---

## 7. Core and Tool API

### 7.1 Core — orchestration only

Core does not invent IFC API paths. It delegates all IFC work to tool methods. Per §4.7, every function injects its tool dependencies explicitly.

```python
# core/surface.py
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .. import tool


def create_surface_from_points(
    ifc_tool: "type[tool.Ifc]",
    surface_tool: "type[tool.Surface]",
    name: str,
    points: list[tuple[float, float, float]],
    kind: str,
) -> str:
    """Create a CivilSurface from a point cloud. Returns surface guid."""
    ifc_file = ifc_tool.get()
    surface = surface_tool.build_tin_from_points(ifc_file, name, points, kind)
    surface_tool.author_ifc_host(ifc_file, surface)              # IfcGeographicElement[TERRAIN] or IfcEarthworksFill
    surface_tool.author_ifc_tin_representation(ifc_file, surface)
    surface_tool.author_ifc_bounding_box(ifc_file, surface)
    surface_tool.apply_standard_psets(ifc_file, surface)
    surface_tool.apply_classification(ifc_file, surface)
    surface_tool.link_to_blender(surface)
    return surface.guid


def add_breakline_to_surface(
    ifc_tool: "type[tool.Ifc]",
    surface_tool: "type[tool.Surface]",
    surface_guid: str,
    breakline,                                                   # tool.Surface.Breakline
) -> None:
    """Add a breakline to a surface, persist as IfcAnnotation, and retriangulate."""
    ifc_file = ifc_tool.get()
    surface = surface_tool.get(ifc_file, surface_guid)
    surface_tool.add_breakline(surface, breakline)
    surface_tool.author_ifc_annotation(ifc_file, breakline)      # IfcAnnotation + IfcPolyline
    surface_tool.retriangulate(surface)
    surface_tool.update_ifc_tin_representation(ifc_file, surface)
    surface_tool.update_blender(surface)


def set_surface_boundary(
    ifc_tool: "type[tool.Ifc]",
    surface_tool: "type[tool.Surface]",
    surface_guid: str,
    polygon_2d: list[tuple[float, float]],
    kind: str,
) -> None:
    """Set outer boundary, add a hole, or add a void."""
    ifc_file = ifc_tool.get()
    surface = surface_tool.get(ifc_file, surface_guid)
    surface_tool.set_boundary(surface, polygon_2d, kind)
    surface_tool.retriangulate(surface)
    surface_tool.update_ifc_tin_representation(ifc_file, surface)
    surface_tool.update_blender(surface)


# core/grading.py

def create_grading_group(
    ifc_tool: "type[tool.Ifc]",
    surface_tool: "type[tool.Surface]",
    grading_tool: "type[tool.Grading]",
    name: str,
    target_surface_guid: str,
    interior_fill: str = "interpolate_from_boundary",
) -> str:
    """Create an empty grading group targeting an existing surface."""
    ifc_file = ifc_tool.get()
    target = surface_tool.get(ifc_file, target_surface_guid)
    group = grading_tool.create_group(name, target, interior_fill)
    grading_tool.author_ifc_group(ifc_file, group)               # IfcGroup ObjectType="GradingGroup"
    grading_tool.author_ifc_composite_fill(ifc_file, group)      # IfcEarthworksFill [SUBGRADE] (composite)
    grading_tool.apply_source_pset(ifc_file, group)              # Pset_SaikeiGradingSource
    return group.guid


def create_grading_criteria(
    ifc_tool: "type[tool.Ifc]",
    grading_tool: "type[tool.Grading]",
    name: str,
    target_kind: str,
    cut_slope: float,
    fill_slope: float,
    max_distance: float | None = None,
) -> str:
    """Author a reusable grading criteria as an IfcPropertySetTemplate."""
    ifc_file = ifc_tool.get()
    criteria = grading_tool.build_criteria(name, target_kind, cut_slope, fill_slope, max_distance)
    grading_tool.author_ifc_criteria_template(ifc_file, criteria)
    return criteria.guid


def add_grading_object(
    ifc_tool: "type[tool.Ifc]",
    surface_tool: "type[tool.Surface]",
    grading_tool: "type[tool.Grading]",
    group_guid: str,
    feature_line_guid: str,
    criteria_guid: str,
) -> str:
    """Apply a criteria to a feature line within a group."""
    ifc_file = ifc_tool.get()
    group = grading_tool.get_group(ifc_file, group_guid)
    feature_line = grading_tool.get_feature_line(ifc_file, feature_line_guid)
    criteria = grading_tool.get_criteria(ifc_file, criteria_guid)
    target = surface_tool.get(ifc_file, group.target_surface_guid)

    grading_object = grading_tool.compute_grading_object(feature_line, criteria, target)
    grading_tool.author_ifc_slope_fill(ifc_file, grading_object) # IfcEarthworksFill [SLOPEFILL]
    grading_tool.add_to_group(ifc_file, group, grading_object)
    grading_tool.rebuild_group_surface(group)
    grading_tool.update_blender(group)
    return grading_object.guid


def edit_feature_line_elevations(
    ifc_tool: "type[tool.Ifc]",
    grading_tool: "type[tool.Grading]",
    feature_line_guid: str,
    edits: list[tuple[int, float]],
) -> None:
    """Edit feature line vertex elevations; cascade rebuild to all parent groups."""
    ifc_file = ifc_tool.get()
    feature_line = grading_tool.get_feature_line(ifc_file, feature_line_guid)
    grading_tool.apply_elevation_edits(feature_line, edits)
    grading_tool.update_ifc_alignment_representation(ifc_file, feature_line)

    # Dynamic rebuild — find all grading objects using this feature line
    affected_groups = grading_tool.find_groups_using_feature_line(ifc_file, feature_line_guid)
    for group in affected_groups:
        grading_tool.rebuild_group_surface(group)
        grading_tool.update_blender(group)


# core/earthwork.py

def compute_earthwork_volumes(
    ifc_tool: "type[tool.Ifc]",
    surface_tool: "type[tool.Surface]",
    earthwork_tool: "type[tool.Earthwork]",
    existing_guid: str,
    proposed_guid: str,
    shrink_factor: float = 1.0,
    swell_factor: float = 1.0,
) -> "tool.Earthwork.VolumeResult":
    """Compute cut and fill volumes between two surfaces."""
    ifc_file = ifc_tool.get()
    existing = surface_tool.get(ifc_file, existing_guid)
    proposed = surface_tool.get(ifc_file, proposed_guid)
    result = earthwork_tool.volume_tin_to_tin(existing, proposed, shrink_factor, swell_factor)
    earthwork_tool.author_cut_solid(ifc_file, result)            # IfcEarthworksCut + IfcPolygonalFaceSet
    earthwork_tool.author_fill_solid(ifc_file, result)           # IfcEarthworksFill + IfcPolygonalFaceSet
    earthwork_tool.write_standard_qtos(ifc_file, result)         # Qto_EarthworksCut/FillBaseQuantities
    earthwork_tool.write_shrink_swell_pset(ifc_file, result)     # Pset_SaikeiGradingShrinkSwell
    earthwork_tool.apply_classification(ifc_file, result)        # OmniClass Table 22
    return result


def generate_cutfill_map(
    ifc_tool: "type[tool.Ifc]",
    surface_tool: "type[tool.Surface]",
    earthwork_tool: "type[tool.Earthwork]",
    existing_guid: str,
    proposed_guid: str,
) -> int:
    """Generate a false-color overlay mesh showing cut (red) and fill (blue)."""
    ifc_file = ifc_tool.get()
    existing = surface_tool.get(ifc_file, existing_guid)
    proposed = surface_tool.get(ifc_file, proposed_guid)
    mesh_id = earthwork_tool.build_cutfill_color_mesh(existing, proposed)
    return mesh_id
```

**Operator call site pattern.** Bonsai operators call core with explicit tool-class arguments, matching the alignment precedent (`bim/module/alignment/operator.py`):

```python
# bim/module/grading/operator.py
class CIVIL_OT_create_grading_group(Operator, tool.Ifc.Operator):
    def _execute(self, context):
        guid = core.create_grading_group(
            tool.Ifc, tool.Surface, tool.Grading,
            name=self.name,
            target_surface_guid=self.target_surface_guid,
            interior_fill=self.interior_fill,
        )
        ...
```

### 7.2 Tool — implementations

Tool methods author IFC entities directly via `ifc_file.create_entity()`. Examples:

```python
# tool/surface.py

class Surface:
    @staticmethod
    def build_tin_from_points(name: str, points: np.ndarray, kind: str) -> CivilSurface: ...

    @staticmethod
    def retriangulate(surface: CivilSurface) -> None:
        """Rebuild the TIN using constrained Delaunay. Honors breaklines, holes, voids.
        Updates surface.triangles and surface.triangle_flags in place."""

    @staticmethod
    def z_at(surface: CivilSurface, x: float, y: float) -> float | None:
        """Interpolated Z at (x, y), or None if outside. Point-in-triangle +
        barycentric interpolation."""

    @staticmethod
    def author_ifc_host(ifc_file: "ifcopenshell.file", surface: CivilSurface) -> None:
        """Create the appropriate IFC host entity based on surface.kind.

        existing       → IfcGeographicElement [TERRAIN] under IfcSite via IfcRelContainedInSpatialStructure
        proposed_group → IfcEarthworksFill [SUBGRADE] within a grading group (aggregated under the per-group composite)
        proposed_site  → IfcEarthworksFill [SUBGRADE] under IfcSite via IfcRelContainedInSpatialStructure (the site composite root)

        All use IfcLocalPlacement with identity IfcAxis2Placement3D."""
        # ... create host entity with identity placement ...
        # ... attach to IfcSite via IfcRelContainedInSpatialStructure ...
        # ... stash step id in surface.ifc_host_entity_id ...

    @staticmethod
    def author_ifc_tin_representation(surface: CivilSurface) -> None:
        """Author the IfcTriangulatedIrregularNetwork and attach as a SurfaceModel
        representation on the host entity."""
        ifc_file = tool.Ifc.get()
        coord_list = ifc_file.create_entity(
            "IfcCartesianPointList3D",
            CoordList=[tuple(p) for p in surface.points],
        )
        tin = ifc_file.create_entity(
            "IfcTriangulatedIrregularNetwork",
            Coordinates=coord_list,
            CoordIndex=[tuple(t + 1) for t in surface.triangles],  # 1-based
            Flags=surface.triangle_flags.tolist(),
            Closed=False,
        )
        # Wrap in IfcShapeRepresentation with RepresentationIdentifier='SurfaceModel'
        # Attach to host entity's IfcProductDefinitionShape.Representations
        surface.ifc_tin_representation_id = tin.id()

    @staticmethod
    def author_ifc_bounding_box(surface: CivilSurface) -> None:
        """Author an IfcBoundingBox representation for LOD/culling."""
        ...

    @staticmethod
    def author_ifc_annotation(breakline: Breakline) -> None:
        """Persist a breakline as IfcAnnotation with IfcPolyline representation.
        Separate from the derived TIN — enables retriangulation on re-open."""
        ...

    @staticmethod
    def apply_standard_psets(ifc_file: "ifcopenshell.file", surface: CivilSurface) -> None:
        """Attach Pset_GeographicElementCommon (for existing) or
        Pset_EarthworksFillCommon (for proposed) via IfcRelDefinesByProperties.
        Also apply Pset_SaikeiGradingSurface for Saikei-specific metadata."""
        ...

    @staticmethod
    def apply_classification(surface: CivilSurface) -> None:
        """Attach OmniClass Table 22 classification via IfcRelAssociatesClassification."""
        ...


# tool/grading.py

class Grading:
    @staticmethod
    def compute_grading_object(feature_line: FeatureLine,
                                criteria: GradingCriteria,
                                target_surface: CivilSurface | None) -> GradingObject:
        """Dispatch by criteria.target_kind to the four projection implementations."""

    @staticmethod
    def author_ifc_group(ifc_file: "ifcopenshell.file", group: GradingGroup) -> None:
        """Create IfcGroup with ObjectType='GradingGroup'. NOT placed in the spatial
        tree — IfcGroup is not an IfcProduct. Members are attached via
        IfcRelAssignsToGroup; discovery is by ObjectType query."""

    @staticmethod
    def author_ifc_composite_fill(group: GradingGroup) -> None:
        """Create the composite IfcEarthworksFill [SUBGRADE] that will aggregate
        per-object slope fills and the interior fill."""

    @staticmethod
    def author_ifc_slope_fill(grading_object: GradingObject) -> None:
        """Create IfcEarthworksFill [SLOPEFILL] for the slope projection region.
        Attach as member of the group via IfcRelAggregates to the composite fill."""

    @staticmethod
    def author_ifc_criteria_template(criteria: GradingCriteria) -> None:
        """Create IfcPropertySetTemplate at project scope for reusable criteria.
        Instances of this template (IfcPropertySet) are attached to each group that
        uses the criteria."""

    @staticmethod
    def rebuild_group_surface(group: GradingGroup) -> CivilSurface:
        """Compose all gradings + interior fill into a single proposed CivilSurface.
        Author the interior fill as IfcEarthworksFill [SUBGRADE] if interior_fill != 'none'."""


# tool/earthwork.py

class Earthwork:
    @staticmethod
    def volume_tin_to_tin(existing: CivilSurface, proposed: CivilSurface,
                           shrink_factor: float = 1.0,
                           swell_factor: float = 1.0) -> VolumeResult:
        """True TIN-to-TIN prismoidal volume. See §6.4."""

    @staticmethod
    def author_cut_solid(ifc_file: "ifcopenshell.file", result: VolumeResult) -> None:
        """Author IfcEarthworksCut with IfcPolygonalFaceSet Closed=TRUE.
        Establish IfcRelVoidsElement relationship to the host IfcGeographicElement."""

    @staticmethod
    def author_fill_solid(result: VolumeResult) -> None:
        """Author IfcEarthworksFill with IfcPolygonalFaceSet Closed=TRUE in a
        Body/Tessellation ShapeRepresentation alongside the proposed TIN SurfaceModel
        representation."""

    @staticmethod
    def write_standard_qtos(result: VolumeResult) -> None:
        """Write volumes to Qto_EarthworksCutBaseQuantities and
        Qto_EarthworksFillBaseQuantities. This is where QTO tools find them."""

    @staticmethod
    def build_cutfill_color_mesh(existing: CivilSurface, proposed: CivilSurface) -> int:
        """Generate a Blender mesh overlay with per-vertex colors driven by Z delta."""
```

---

## 8. UI Layer

### 8.1 Panels

- `CIVIL_PT_surface_panel` — surface list, create/edit, visualization toggles (triangles, contours, slope vectors, elevation banding).
- `CIVIL_PT_grading_panel` — grading groups list; per-group shows members, target surface, interior fill strategy, cut/fill totals.
- `CIVIL_PT_earthwork_panel` — earthwork volume calculation, cut/fill color map controls, shrink/swell factor inputs.

### 8.2 Operators (MVP set)

Each operator is annotated `[H]` (headless: data-driven, callable from `bpy.ops.civil.X("EXEC_DEFAULT", **kwargs)`), `[M]` (modal: viewport interaction or popup dialog via `invoke()`), or both. See §8.5 for the modal/headless contract.

**Surface:**
- `CIVIL_OT_surface_create_from_points` `[H]` — import XYZ, CSV, or IFC TIN file; build surface.
- `CIVIL_OT_surface_add_breakline` `[M+H]` — modal: pick a 3D polyline in viewport. Headless: accept a `polyline` payload directly.
- `CIVIL_OT_surface_set_boundary` `[M+H]` — modal: pick a 2D polygon. Headless: accept a `polygon` payload and `kind` enum (`outer` / `hole` / `void`).
- `CIVIL_OT_surface_retriangulate` `[H]` — force rebuild; rarely needed manually.
- `CIVIL_OT_surface_export_ifc` `[M+H]` — modal: file dialog. Headless: accept `filepath`. Writes `IfcTriangulatedIrregularNetwork` + bbox + breakline annotations.

**Grading:**
- `CIVIL_OT_feature_line_create` `[M+H]` — modal: draw a new feature line in viewport (mirrors the alignment PI picker pattern). Headless: convert a mesh edge loop or accept a `vertices` payload. Authors `IfcAlignment`.
- `CIVIL_OT_feature_line_drape` `[H]` — assign vertex elevations from a surface (data-driven; surface guid as input).
- `CIVIL_OT_feature_line_edit_elevations` `[M+H]` — modal: G-key vertex-grab edit (mirrors alignment PI G-key edit mode). Headless: accept an `edits: list[(vertex_index, new_z)]` payload.
- `CIVIL_OT_grading_create_group` `[M+H]` — modal: popup dialog for name + target surface + interior fill. Headless: accept all fields as kwargs.
- `CIVIL_OT_grading_create_criteria` `[M+H]` — modal: popup. Headless: kwargs. Authors `IfcPropertySetTemplate`.
- `CIVIL_OT_grading_add_object` `[M+H]` — modal: popup with group / feature-line / criteria pickers. Headless: kwargs.
- `CIVIL_OT_grading_rebuild_group` `[H]` — force-rebuild group surface; auto-rebuild handles most cases.

**Earthwork:**
- `CIVIL_OT_earthwork_compute_volumes` `[M+H]` — modal: popup with existing/proposed surface pickers and shrink/swell inputs. Headless: kwargs. Writes standard Qtos.
- `CIVIL_OT_earthwork_cutfill_map` `[H]` — generate cut/fill color overlay mesh from existing/proposed guids.
- `CIVIL_OT_earthwork_export_ifc` `[M+H]` — modal: file dialog. Headless: `filepath`. Writes `IfcEarthworksCut` / `IfcEarthworksFill` solids (`IfcPolygonalFaceSet` Closed) with classification and Qtos.

### 8.3 PropertyGroups & UILists

Panel state lives in `bpy.types.PropertyGroup` subclasses on `Scene`. Schema:

```python
# bim/module/surface/prop.py
class CivilSurfaceProperties(bpy.types.PropertyGroup):
    surfaces: bpy.props.CollectionProperty(type=CivilSurfaceItem)
    active_surface_index: bpy.props.IntProperty(default=0)
    show_triangles: bpy.props.BoolProperty(default=True)
    show_contours: bpy.props.BoolProperty(default=False)
    show_slope_vectors: bpy.props.BoolProperty(default=False)
    show_elevation_banding: bpy.props.BoolProperty(default=False)
    contour_interval: bpy.props.FloatProperty(default=1.0, min=0.01)
    pending_breakline_kind: bpy.props.EnumProperty(
        items=[("standard", "Standard", ""), ("wall", "Wall", ""),
               ("non_destructive", "Non-destructive", ""), ("proximity", "Proximity", "")])
    pending_boundary_kind: bpy.props.EnumProperty(
        items=[("outer", "Outer", ""), ("hole", "Hole", ""), ("void", "Void", "")])

class CivilSurfaceItem(bpy.types.PropertyGroup):
    guid: bpy.props.StringProperty()
    name: bpy.props.StringProperty()
    kind: bpy.props.EnumProperty(items=[("existing", "Existing", ""),
                                          ("proposed_group", "Proposed (Group)", ""),
                                          ("proposed_site", "Proposed (Site)", "")])
    is_active: bpy.props.BoolProperty(default=False)

# bim/module/grading/prop.py
class CivilGradingProperties(bpy.types.PropertyGroup):
    groups: bpy.props.CollectionProperty(type=CivilGradingGroupItem)
    active_group_index: bpy.props.IntProperty(default=0)
    criteria: bpy.props.CollectionProperty(type=CivilGradingCriteriaItem)
    active_criteria_index: bpy.props.IntProperty(default=0)
    feature_line_edit_mode: bpy.props.BoolProperty(default=False)  # for G-key modal

class CivilGradingGroupItem(bpy.types.PropertyGroup):
    guid: bpy.props.StringProperty()
    name: bpy.props.StringProperty()
    target_surface_guid: bpy.props.StringProperty()
    interior_fill: bpy.props.EnumProperty(
        items=[("none", "None", ""), ("flat", "Flat", ""),
               ("interpolate_from_boundary", "Interpolate", ""),
               ("from_surface", "From Surface", "")])
    cut_volume_m3: bpy.props.FloatProperty()
    fill_volume_m3: bpy.props.FloatProperty()

class CivilGradingCriteriaItem(bpy.types.PropertyGroup):
    guid: bpy.props.StringProperty()
    name: bpy.props.StringProperty()
    target_kind: bpy.props.EnumProperty(
        items=[("surface", "Surface", ""), ("elevation", "Elevation", ""),
               ("relative_elevation", "Relative Elevation", ""), ("distance", "Distance", "")])
    cut_slope: bpy.props.FloatProperty(default=2.0)
    fill_slope: bpy.props.FloatProperty(default=3.0)
    max_distance: bpy.props.FloatProperty(default=0.0)  # 0 = unlimited

# bim/module/earthwork/prop.py
class CivilEarthworkProperties(bpy.types.PropertyGroup):
    existing_surface_guid: bpy.props.StringProperty()
    proposed_surface_guid: bpy.props.StringProperty()
    shrink_factor: bpy.props.FloatProperty(default=1.0, min=0.5, max=1.5)
    swell_factor: bpy.props.FloatProperty(default=1.0, min=0.8, max=1.5)
    last_cut_m3: bpy.props.FloatProperty()
    last_fill_m3: bpy.props.FloatProperty()
    last_net_m3: bpy.props.FloatProperty()
```

UIList classes (one per CollectionProperty that needs an interactive list):

- `CIVIL_UL_surfaces` — list of `CivilSurfaceItem`. Columns: name, kind icon, active toggle.
- `CIVIL_UL_grading_groups` — list of `CivilGradingGroupItem`. Columns: name, target surface name (resolved from guid), cut/fill totals.
- `CIVIL_UL_grading_members` — per-group list of grading-object members. Columns: feature line name, criteria name, status icon.
- `CIVIL_UL_grading_criteria` — list of `CivilGradingCriteriaItem`. Columns: name, target_kind, slopes (`cut_slope`:`fill_slope` formatted as `2:1 / 3:1`).

PropertyGroups are registered to `bpy.types.Scene`:

```python
bpy.types.Scene.CivilSurfaceProperties = bpy.props.PointerProperty(type=CivilSurfaceProperties)
bpy.types.Scene.CivilGradingProperties = bpy.props.PointerProperty(type=CivilGradingProperties)
bpy.types.Scene.CivilEarthworkProperties = bpy.props.PointerProperty(type=CivilEarthworkProperties)
```

Operators read state via `context.scene.CivilSurfaceProperties.active_surface_index`, etc.

### 8.4 Keymaps

Saikei mirrors the alignment T-panel toolbar's modal-edit precedent for vertex-elevation editing. Keymaps are registered in the `civil` keymap (created at module load):

| Key | Active in | Operator | Behavior |
|---|---|---|---|
| `G` | Feature Line Edit Mode (`CivilGradingProperties.feature_line_edit_mode == True`) | `civil.feature_line_edit_elevations` (modal) | Grab/drag vertex Z. Mouse Y → delta-Z; numeric input typed during modal sets exact Z. Confirm with `LMB` or `Enter`; cancel with `RMB` or `Esc`. Mirrors alignment PI G-key edit. |
| `Tab` | Surface panel | `civil.surface_toggle_edit_mode` | Enter/exit feature-line edit mode. Sets `feature_line_edit_mode` flag. |
| `Esc` | Any modal pick (breakline / boundary / feature-line draw) | (operator's modal handler) | Cancel the pick; revert any partial state. |
| `Enter` / `LMB` | Any modal pick | (operator's modal handler) | Confirm pick; pass the picked geometry to the headless data path. |

`bpy.utils.register_keymap` registration is per-window-manager and is added/removed in `register()` / `unregister()` in `bim/module/grading/__init__.py`. Tests verify keymap registration via `wm.keyconfigs.user.keymaps['civil'].keymap_items`.

### 8.5 Modal vs headless operator contract

Every operator with `[M+H]` annotation in §8.2 implements both an `invoke()` (modal entry) and an `_execute()` (headless execution). Calling conventions:

```python
# Headless / agent / scripted call — always EXEC_DEFAULT:
bpy.ops.civil.surface_add_breakline(
    "EXEC_DEFAULT",
    surface_guid="01ABC...",
    polyline=[(0, 0, 100), (10, 0, 101), (10, 10, 102)],
    kind="standard",
)

# Modal / interactive call — INVOKE_DEFAULT triggers invoke():
bpy.ops.civil.surface_add_breakline("INVOKE_DEFAULT")
```

`invoke()` collects user input (viewport pick, popup dialog), populates the operator's properties, and then calls `self._execute(context)` — same code path as the headless call. This guarantees that whatever the modal path captures, an agent can reproduce by calling `EXEC_DEFAULT` with the same kwargs.

**Error reporting boundary:**

- Tool methods raise typed exceptions: `SaikeiGradingError` (base), `SaikeiSurfaceError`, `SaikeiTriangulationError`, `SaikeiVolumeError`, etc., defined in `bonsai/civil_errors.py`.
- Core orchestration may wrap or re-raise but does **not** call `self.report()`.
- Operators catch `SaikeiGradingError` in `_execute()` and convert to `self.report({"ERROR"}, str(e))` then return `{"CANCELLED"}`. Unhandled exceptions propagate to Blender's default crash handler (intentional — they indicate bugs, not user errors).

Headless callers receive the raw exception; they get the structured error type, not a Blender report string. This makes the same operators usable from CI tests, MCP-driven agents, and `bpy.ops` scripts.

---

## 9. MVP Scope — Sprint 1

Keeping PRs ≤4,000 lines (Dion's constraint), **Sprint 1 is "Terrain Modeler" only**. Grading and earthwork follow in Sprints 2 and 3.

**In scope for Sprint 1:**
- `CivilSurface` data model and `tool.Surface` implementation
- TIN construction from point cloud (unconstrained Delaunay via SciPy)
- TIN construction with breaklines (CDT via Shapely 2.1+)
- Outer boundary + holes + voids
- `IfcTriangulatedIrregularNetwork` authoring + `IfcBoundingBox` + `IfcAnnotation` breaklines
- Host entity authoring: `IfcGeographicElement[TERRAIN]` for existing surfaces
- Spatial containment under `IfcSite` via `IfcRelContainedInSpatialStructure`
- `IfcMapConversion` + `IfcProjectedCRS.VerticalDatum` wiring
- Standard psets applied: `Pset_GeographicElementCommon`
- Custom psets: `Pset_SaikeiGradingSurface`
- OmniClass Table 22 classification
- Basic Blender visualization (mesh with vertex colors for elevation banding)
- Surface panel + create-from-points + add-breakline + set-boundary operators
- Round-trip tests (write → read → compare) through `ifcopenshell`
- Validation test using bSI reference validator (see §11)

**Deferred to Sprint 2:**
- Feature lines data model + UI + `IfcAlignment` authoring with polyline representation
- Grading criteria as `IfcPropertySetTemplate`
- Grading objects (the four projection methods) + `IfcEarthworksFill[SLOPEFILL]` authoring
- Grading groups + `IfcGroup` authoring + composite surfaces + interior fill as `IfcEarthworksFill[SUBGRADE]`
- `Pset_SaikeiGradingAlignment` for linking grading groups to corridor alignments
- Cascade-on-edit behavior (Civil 3D's dynamic grading)

**Deferred to Sprint 3:**
- Earthwork volumes (TIN-to-TIN prismoidal)
- Cut/fill color map overlay
- `IfcEarthworksCut` authoring with `IfcPolygonalFaceSet` Closed solid and `IfcRelVoidsElement`
- `IfcEarthworksFill` closed solid (`Body` / `Tessellation`) alongside proposed TIN
- Standard Qto authoring: `Qto_EarthworksCutBaseQuantities`, `Qto_EarthworksFillBaseQuantities`
- Shrink/swell factors in `Pset_SaikeiGradingShrinkSwell`

**Deferred beyond MVP:**
- LandXML import/export
- Retaining walls at daylight cap (requires `IfcWall` integration — non-TIN geometry)
- Mass haul diagrams
- Full `IfcLinearPlacement` integration with corridor alignments (Pset-based in MVP)

---

## 10. Known Limitations (acknowledged, not bugs)

**Overhanging and vertical surfaces.** `IfcTriangulatedIrregularNetwork` requires one unique Z per (X, Y). Retaining walls, steep cut faces, and certain pond cross-sections have vertical or overhanging faces that cannot be represented. For MVP these are out of scope; when first encountered in practice, they will be handled via `IfcWall` entities (retaining walls) placed at the daylight line, separate from the TIN.

**Breakline edge identity in `Flags` list.** IFC's per-triangle flag cannot preserve per-edge breakline identity when a triangle straddles a breakline. Round-trip preserves triangle membership (is this triangle adjacent to breakline N?) but not which specific edge is on the breakline. Full breakline source geometry is persisted separately as `IfcAnnotation` polylines so this isn't a data-loss issue — just a query-efficiency one.

**Material flow between cut and fill.** IFC 4.3 does not model excavated material as a resource, so the relationship between a cut at one station and a fill at another (where the dirt moved) cannot be expressed in the schema. Mass haul optimization is a future module that will use Saikei-native property extensions until IFC provides the concept.

**Third-party viewer support for IFC 4.3 civil entities.** `IfcTriangulatedIrregularNetwork`, `IfcEarthworksCut`, `IfcEarthworksFill`, and `IfcGeographicElement[TERRAIN]` have partial-to-absent support in building-focused viewers (BIMvision, Solibri, Navisworks as of mid-2025). Interoperability for Saikei output is primarily with IFC 4.3 civil tools — OpenRoads, DESITE, bSI reference validator, Revit with latest Roads/Rail extensions.

---

## 11. Agent Work Breakdown

**Phasing under B3.** Phases 1–3 land the `ifcopenshell.api.*` libraries (pure Python, headless, no Blender). Phases 4–6 build the Bonsai modules on top. The naming below replaces the previous "Sprint 1/2/3" labels — the Bonsai work tables that used to be Sprint 1/2/3 are now Phase 4/5/6.

### Phase 1 — `ifcopenshell.api.surface` (target: ~1,030 LoC)

| Agent | Task | Est. LoC |
|-------|------|----------|
| `saikei-ifc` | Author `IfcGeographicElement[TERRAIN]` + `IfcEarthworksFill[SUBGRADE]` (host) + `IfcTriangulatedIrregularNetwork` + `IfcBoundingBox` + `IfcAnnotation` (breakline) helpers; `_representation_context` resolver; spatial containment via existing `ifcopenshell.api.spatial`; standard psets + `Pset_SaikeiGradingSurface`. See `Phase1_ifcopenshell_api_surface_handoff.md` for the commit-by-commit plan. | 800 |
| `saikei-tester` | Pure-Python pytest suite for each public function; round-trip tests; bSI validator integration | 150 |
| `docs` | Module docstring in `__init__.py`; usage examples; demo script (flat pad → IFC) | 80 |

### Phase 2 — `ifcopenshell.api.grading` (target: ~1,200 LoC)

| Agent | Task | Est. LoC |
|-------|------|----------|
| `saikei-ifc` | `IfcAlignment` (feature line as 3D polyline) — pending Dion sign-off per §12; `IfcPropertySetTemplate` for criteria; `IfcGroup ObjectType="GradingGroup"` + `IfcRelAssignsToGroup`; `IfcEarthworksFill[SLOPEFILL/SUBGRADE]` authoring with the §2.7 composite-fill aggregation tree; `Pset_SaikeiFeatureLineCommon`, `Pset_SaikeiGradingCriteria`, `Pset_SaikeiGradingAlignment` | 1000 |
| `saikei-tester` | Round-trip tests for grading-group composition; criteria template/instance binding; feature-line-as-IfcAlignment round-trip | 150 |
| `docs` | API docs; scripted demo (flat pad + 3:1 fill criteria → grading object → IFC) | 50 |

### Phase 3 — `ifcopenshell.api.earthwork` (target: ~900 LoC)

| Agent | Task | Est. LoC |
|-------|------|----------|
| `saikei-ifc` | `IfcEarthworksCut` (default `PredefinedType=EXCAVATION`) + `IfcEarthworksFill` (default `EMBANKMENT`; `SLOPEFILL`/`SUBGRADE` reserved for Phase 2) solid authoring (`IfcPolygonalFaceSet` Closed, `Body`/`Tessellation`); dedicated `void_terrain` API call for `IfcRelVoidsElement` to host `IfcGeographicElement` (separate from `create_earthworks_cut` so the `VoidsElements [1:1]` schema-completeness contract is visible at the call site); standard Qto authoring (`Qto_EarthworksCutBaseQuantities`, `Qto_EarthworksFillBaseQuantities`) — **idempotent** in-place update on re-author; `Pset_SaikeiGradingShrinkSwell` — **idempotent**. The actual prismoidal volume math (§6.4) and cut/fill solid construction (§6.5) live in Bonsai's `tool.Earthwork` (Phase 6); the API persists what it's given. See `Phase3_ifcopenshell_api_earthwork_handoff.md` for the commit-by-commit plan. | 700 |
| `saikei-tester` | Round-trip tests; volume Qto write/read; bSI validator on cut/fill solids | 150 |
| `docs` | API docs; scripted demo (full pad → cut/fill report → IFC) | 50 |

### Phase 4 — Bonsai surface module (target: ~2,500 LoC) [was Sprint 1]

| Agent | Task | Est. LoC |
|-------|------|----------|
| `saikei-architect` | Finalize `CivilSurface` + `Breakline` data models, triangulator abstraction, IFC host selection logic | 400 |
| `saikei-ifc` | Wire `tool.Surface` to call `ifcopenshell.api.surface` (built in Phase 1); apply OmniClass classification; round-trip tests through Bonsai. Most of the heavy IFC authoring lives in the API now — this row is integration glue. | 300 |
| `tool-dev` | `tool.Surface` impl — `build_tin_from_points`, `retriangulate` with CDT, `z_at`, boundary/hole/void handling | 700 |
| `blender-ui` | Surface panel, operators for create-from-points, add-breakline, set-boundary | 400 |
| `saikei-tester` | Test TIN build, CDT with breaklines, IFC round-trip, bSI reference validator run | 200 |
| `docs` | Surface module README, CLAUDE.md update | 100 |

### Phase 5 — Bonsai grading module (target: ~3,000 LoC) [was Sprint 2]

| Agent | Task | Est. LoC |
|-------|------|----------|
| `saikei-architect` | Finalize `FeatureLine`, `GradingCriteria`, `GradingObject`, `GradingGroup` data models; alignment-linkage pset design | 400 |
| `saikei-ifc` | `IfcAlignment` authoring for feature lines, `IfcPropertySetTemplate` for criteria, `IfcGroup` + `IfcEarthworksFill[SLOPEFILL/SUBGRADE]` authoring, `Pset_SaikeiGradingAlignment` | 600 |
| `tool-dev` | `tool.Grading` impl — all four projection methods, group rebuild, cascade edit | 1000 |
| `blender-ui` | Feature line authoring, grading panel, criteria dialog, add-object operator | 700 |
| `saikei-tester` | Test pad grading, pond-like grading, group composition, cascade edit, round-trip | 200 |
| `docs` | Grading module README + tutorial (flat pad to existing ground) | 100 |

### Phase 6 — Bonsai earthwork module (target: ~2,000 LoC) [was Sprint 3]

| Agent | Task | Est. LoC |
|-------|------|----------|
| `saikei-architect` | `VolumeResult` schema, earthwork report structure, cut/fill solid construction algorithm | 200 |
| `saikei-ifc` | `IfcEarthworksCut` + `IfcEarthworksFill` solid authoring (`IfcPolygonalFaceSet` Closed), `IfcRelVoidsElement`, standard Qto authoring, `Pset_SaikeiGradingShrinkSwell` | 500 |
| `tool-dev` | `tool.Earthwork` impl — TIN-to-TIN prismoidal, cut/fill region extraction, closed-solid construction, color map | 700 |
| `blender-ui` | Earthwork panel, compute-volumes operator, cut/fill map operator | 400 |
| `saikei-tester` | Test volumes against hand-calc values; IFC round-trip through DESITE or bSI reference validator | 150 |
| `docs` | Earthwork README + workflow example (full pad → cut/fill report → IFC export) | 50 |

---

## 12. Open Questions — Remaining

Most previous open questions have been resolved by this spec revision. Remaining items for Dion / Rick:

1. **`IfcAlignment` as feature line representation — upstream acceptance.** Using `IfcAlignment` for 3D grading feature lines is schema-valid (the spec explicitly lists `IfcPolyline` as a valid alignment representation), but it's a semantic stretch — alignments are typically "transportation routes." Confirm with Dion that this reuse is acceptable before Sprint 2 commits to it. Alternative: `IfcAnnotation` with 3D polyline representation, less sophisticated but unambiguous.

2. **Module prefix collisions.** `CIVIL_OT_surface_*` — check against any existing Bonsai site module that might overlap semantically.

3. **Georeferencing precision on large surfaces.** Alignments are linear and stay close to the alignment envelope; surfaces span the whole site. Verify `tool.Georeference` ENH↔XYZ behavior is accurate out to a several-km site extent without precision drift. A small test harness in Sprint 1 answers this.

4. **Vertical datum — ecosystem behavior.** We're prescribing `IfcProjectedCRS.VerticalDatum` + `IfcMapConversion.OrthogonalHeight` for vertical round-trip. Worth a survey of what Bonsai alignment currently does and whether fixing it for surfaces warrants a coordinated fix for alignments too.

5. **Retaining wall placeholder.** Spec defers retaining walls beyond MVP. Confirm this aligns with Dion's upstream priorities — if a highway project comes through before we implement walls, the grading module will need a fallback.

---

## 13. References

- buildingSMART IFC 4.3.2 — [IfcTriangulatedIrregularNetwork](https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/lexical/IfcTriangulatedIrregularNetwork.htm)
- buildingSMART IFC 4.3.2 — [IfcGeographicElement](https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/lexical/IfcGeographicElement.htm)
- buildingSMART IFC 4.3.2 — [IfcEarthworksCut](https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/lexical/IfcEarthworksCut.htm)
- buildingSMART IFC 4.3.2 — [IfcEarthworksFill](https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/lexical/IfcEarthworksFill.htm)
- buildingSMART IFC 4.3.2 — [IfcPolygonalFaceSet](https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/lexical/IfcPolygonalFaceSet.htm)
- buildingSMART IFC 4.3.2 — [IfcGroup](https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/lexical/IfcGroup.htm)
- buildingSMART IFC 4.3.2 — [Qto_EarthworksFillBaseQuantities, Qto_EarthworksCutBaseQuantities]
- IRROADWP3 Conceptual Model Report Annex I — Earthworks instance diagrams (project knowledge)
- OmniClass Construction Classification System — [Table 22 Work Results](https://www.csiresources.org/standards/omniclass)
- Autodesk Civil 3D Help — Creating Gradings, Grading Objects reference
- Shapely 2.1 — [constrained_delaunay_triangles](https://shapely.readthedocs.io/en/stable/reference/shapely.constrained_delaunay_triangles.html)
- SciPy — [scipy.spatial.Delaunay](https://docs.scipy.org/doc/scipy/reference/generated/scipy.spatial.Delaunay.html)
- Prior Saikei research — `Corridor_Generation_Deep_Research.md`, `IFC_Roadway_Templates_Assemblies_Reference.md`, `saikei-project-summary.md`
- Companion research — `Saikei_Grading_Earthwork_Research.md` (commercial tool comparative analysis)
- v3.1 multi-agent review pack — `Saikei_Grading_Earthwork_Spec_v3.1_MultiAgent_Synthesis.md`

---

*End of implementation spec. Phases 1–3 shipped; Phase 4 (Bonsai surface module) ready to start.*

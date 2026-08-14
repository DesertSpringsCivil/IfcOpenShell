# Surfaces, Grading & Earthworks in IFC 4.3 — Saikei Civil Implementation Context

> **Purpose**: Reference document for Claude Code while building DTM/surface, grading, and earthwork tools in Saikei Civil (Bonsai-based).
> **Scope**: IFC 4.3 ADD2 (ISO 16739-1:2024) entities, relationships, and architectural principles.
> **Audience**: Claude Code instances assisting with Saikei Civil development.

---

## Quick Reference: Entity Map

### Surface Geometry (the "what")

| Entity | Purpose | Notes |
|---|---|---|
| `IfcTriangulatedIrregularNetwork` | TIN data structure | Subclass of `IfcTriangulatedFaceSet`. The triangulation IS the surface in IFC. |
| `IfcTriangulatedFaceSet` | General tessellated surface | Use when not strictly a TIN (e.g., regular meshes). |
| `IfcBSplineSurface` | NURBS surface | For smooth analytical surfaces; rarely used for terrain. |
| `IfcShellBasedSurfaceModel` | Shell-based surface | Alternative surface representation. |

### Surface as Spatial Element (the "where it sits")

| Entity | Purpose | Notes |
|---|---|---|
| `IfcGeographicElement` | Wraps surface geometry as a product | Use `PredefinedType = TERRAIN`. Default container is `IfcSite`. |
| `IfcGeographicElementType` | Type definition for geographic elements | Optional; for shared properties across instances. |
| `IfcSite` | Spatial container | Treat as pure container, NOT as terrain holder (deprecated pattern). |

### Earthworks (the "what's it for")

| Entity | Inheritance | Purpose |
|---|---|---|
| `IfcEarthworksElement` (abstract) | `IfcBuiltElement` | Supertype for placed earthworks. |
| `IfcEarthworksFill` | `IfcEarthworksElement` | Material PLACED — embankments, structural fill, capping, topsoil. Has volumetric body. |
| `IfcReinforcedSoil` | `IfcEarthworksElement` | Mechanically/chemically stabilized soil. |
| `IfcEarthworksCut` | `IfcFeatureElementSubtraction` | The resulting VOID from excavation. NOT a built element. |

**Critical distinction**: `IfcEarthworksCut` is a feature subtraction (void), not a placed element. The excavated material itself is NOT modeled as the Cut.

### Geotechnics (subsurface)

| Entity | Purpose |
|---|---|
| `IfcGeotechnicalElement` (abstract) | Supertype for geotechnical entities. |
| `IfcGeotechnicalAssembly` | Container for related geotechnical elements + methodology/uncertainty info. |
| `IfcGeotechnicalStratum` | Discrete homogeneous geological feature. |
| `IfcSolidStratum` / `IfcVoidStratum` / `IfcWaterStratum` | Predefined stratum types. |
| `IfcGeomodel` | Volumetric geological/geotechnical model. |
| `IfcGeoslice` | 2D slice through subsurface model. |
| `IfcBorehole` | Physical borehole or interpretation carrier. |

---

## Schema-Critical Details

### `IfcTriangulatedIrregularNetwork` Internals

Inherits from `IfcTriangulatedFaceSet`:
- **Coordinates**: `IfcCartesianPointList3D` — list of unique 3D points
- **CoordIndex**: `LIST OF LIST OF INTEGER` — triangle vertex indices (1-based, 3 indices per face)
- **PnIndex**: optional point index list
- **Normals**: optional explicit normals
- **Closed**: optional boolean

Adds (TIN-specific):
- **Flags**: `LIST OF INTEGER` — one integer per face encoding breakline edges + visibility:

| Flag | Meaning |
|---|---|
| `0` | No break lines |
| `1` | Break line at edge 1 |
| `2` | Break line at edge 2 |
| `3` | Break lines at edges 1 and 2 |
| `4` | Break line at edge 3 |
| `5` | Break lines at edges 1 and 3 |
| `6` | Break lines at edges 2 and 3 |
| `7` | Break lines at all edges |
| `-1` | Invisible "hole" (missing data — may be filled by merging) |
| `-2` | Invisible "void" (intentional exclusion, e.g., building footprint) |

### `IfcEarthworksCutTypeEnum` Values

```
BASE_EXCAVATION    -- General cut to construction depth
BASEMENT_EXCAVATION -- For basements, abutments, below-ground structures
CUTTING            -- Generic cut (when more specific type unknown)
DREDGING           -- Underwater excavation
OVEREXCAVATION     -- Beyond required depth (e.g., to replace unsuitable material)
PAVEMENT_MILLING   -- Removal of expired pavement material
STEP_EXCAVATION    -- Stepped excavation when widening road slope
TOPSOIL_REMOVAL    -- Stripping organic topsoil (often reused as fill)
TRENCH             -- Excavation where length >> depth/width (foundations, utilities)
USERDEFINED
NOTDEFINED
```

### `IfcEarthworksFillTypeEnum` Values

Common values include `BACKFILL`, `COUNTERWEIGHT`, `EMBANKMENT`, `SLOPEFILL`, `SUBGRADEBED`, `TRANSITIONLAYER`, plus USERDEFINED/NOTDEFINED. Verify against current schema for project-specific needs.

### `IfcGeographicElementTypeEnum` Values

```
TERRAIN
SOIL_BORING_POINT
VEGETATION
USERDEFINED
NOTDEFINED
```

### Quantity Sets

**`Qto_EarthworksCutBaseQuantities`** (occurrence-driven):
- `Length`, `Width`, `Depth` — bounding dimensions
- `UndisturbedVolume` — in-situ volume (no swell)
- `LooseVolume` — bulked/swelled volume after excavation
- `Weight`

**`Qto_EarthworksFillBaseQuantities`**: parallel structure for placed fill.

The undisturbed/loose volume distinction handles bulking/swell factor natively — implement Saikei's earthwork calculations to populate both.

---

## Required Relationships

### Voiding Pattern (Cut → Voided Element)

```
IfcGeographicElement (terrain)
    ↓ IfcRelVoidsElement (RelatingBuildingElement)
IfcEarthworksCut
    ↓ IfcRelFillsElement (optional, RelatingOpeningElement)
IfcEarthworksFill | IfcFooting | IfcPipeSegment | etc.
```

- The voided element can be: `IfcGeotechnicalElement` subtype, `IfcEarthworksFill`, `IfcGeographicElement` (terrain).
- **CRITICAL**: There is no automatic CSG operation on import. Saikei MUST compute and write the cut body geometry explicitly — do NOT expect downstream tools to compute "existing TIN minus proposed TIN."

### Spatial Containment

```
IfcProject
    ↓ IfcRelAggregates
IfcSite
    ↓ IfcRelContainedInSpatialStructure
IfcGeographicElement (terrain) | IfcEarthworksCut | IfcEarthworksFill
```

`IfcEarthworksCut` may alternatively be contained relative to its voided element rather than spatially.

### Multiple Surfaces per Project

Use `IfcShapeAspect` to distinguish surface variants on a single element, OR use separate `IfcGeographicElement` instances classified via `IfcRelAssociatesClassification`. Common surface pairs:
- Existing ground / Proposed finish
- Top-of-subgrade / Bottom-of-pavement
- Phase 1 / Phase 2 / Final

**Always classify or aspect-tag surfaces.** Never rely on entity type + name alone.

### Shape Representation Conventions

For terrain TIN body:
- `RepresentationIdentifier` = `'Body'`
- `RepresentationType` = `'Tessellation'` (preferred for TIN) or `'SurfaceModel'`

For 2D footprint:
- `RepresentationIdentifier` = `'FootPrint'`
- `RepresentationType` = `'GeometricCurveSet'` or `'GeometricSet'`

---

## Architectural Principles for Saikei

### 1. IFC is the source of truth — but NOT the authoring format

The TIN in IFC is triangulation-final. Civil engineers expect to edit points, breaklines, and boundaries with the surface rebuilding on demand.

**Saikei must keep definition objects in its business layer**:
- Point groups (survey points, design points)
- Breakline polylines (with classification: hard/soft/wall/etc.)
- Boundary polygons (outer, inner/holes, hide regions)
- Contour data sources
- Raw imports (LandXML, CSV, LiDAR, etc.)

Run triangulation (Delaunay or constrained Delaunay for breaklines) inside Saikei. Write the resulting TIN into IFC with appropriate face flags. On read, either:
- Treat the IFC TIN as locked geometry, OR
- Attempt to reconstruct definition objects from breakline flags + property sets.

### 2. Procedural vs. Declarative Split (same as alignments/corridors)

| Layer | Responsibility |
|---|---|
| **Saikei Business Logic** | Definition objects, triangulation algorithms, grading rules, daylight projections |
| **IfcOpenShell API** | IFC entity creation, relationship management, schema compliance |
| **Bonsai/Blender** | Visualization, regenerable mesh caches, UI for civil engineering workflows |
| **IFC File** | Single source of truth — declarative result at a moment in time |

### 3. Blender Meshes are Disposable Caches

- The Blender mesh displaying the TIN is a regenerable cache.
- Direct mesh edits in Blender for surface elements should either be disallowed OR trigger sync back to IFC via the alignment/IfcOpenShell API.
- User-facing handles are the definition objects (point groups, breaklines, boundaries), NOT the displayed mesh.

### 4. Coordinate System Strategy

Surveys often have far-from-origin coordinates that destroy float precision in tessellation.

**Required setup**:
- Use proper `IfcMapConversion` for georeferencing (NOT deprecated `IfcSite.RefLatitude/RefLongitude`).
- Engineering coordinates stay local; map conversion handles geodetic transformation.
- TIN point coordinates should be in the local engineering frame.
- Reference: 2017 bSI Infra Overall Architecture Guidelines for the canonical pattern.

### 5. Voiding Semantics — Match IFC, Don't Fake

When the user grades a building pad into existing ground, the correct model is:

```
existing_ground (IfcGeographicElement)
    ↓ voided by IfcRelVoidsElement
excavation (IfcEarthworksCut, body = computed cut volume)
    ↓ optionally filled by IfcRelFillsElement
foundation_or_fill (IfcFooting, IfcEarthworksFill, etc.)
```

**Compute cut/fill bodies as solids in Saikei** and write them explicitly. Pre-compute and attach `Qto_EarthworksCut/FillBaseQuantities` rather than relying on downstream geometry processors.

### 6. Boolean Operations Are NOT Standardized for Surfaces

Per official `IfcEarthworksCut` docs:
> "...no CSG operation is expected to be performed on import for this template."

Implication: surface-to-surface differencing for cut/fill volumes must happen in Saikei. The IFC file carries the result, not the operation.

### 7. Hole/Boundary Handling

Breakline-and-visibility flags are baked into the triangulation. If a user moves a building footprint punched as a hole:
- Saikei keeps the hole as a polygon definition object.
- Re-triangulate when the polygon moves.
- Re-emit the TIN with updated face flags.

Don't try to edit the IFC TIN's flags directly to "move" a hole.

### 8. Naming, Classification, and Aspects

Always provide:
- A meaningful `Name` attribute (e.g., "EX_Ground_2024-Q3", "PR_FinishGrade_Phase1")
- An `IfcClassificationReference` (project classification, agency standard, or internal Saikei taxonomy)
- An `IfcShapeAspect` if multiple representations exist on one element

Never rely on entity type + name alone for surface identification.

---

## Known Gaps in IFC 4.3 (Saikei Must Bridge)

### Missing: First-Class "Design Grading" Entity

There is NO `IfcGradingObject` analogous to Civil 3D's grading group. IFC captures the **result** of grading (finished surface, fill volume, cut void) — not the design intent (slope from feature line at 3:1 until daylight on existing).

**Saikei's options**:
1. Capture grading inputs (footprint, slope criteria, target surface ref) as `IfcPropertySet`s on the resulting `IfcEarthworksFill`/proposed surface — design intent becomes round-trippable.
2. Treat the grading object as a Saikei-layer construct that PRODUCES IFC-compliant TINs and earthworks elements.
3. Push for IDS / property template standardization so other tools can read design intent even if they can't recompute it.

### Missing: Parametric Surface Relationships

No schema-level support for "this proposed surface depends on this corridor + this existing surface + these grading rules." Saikei is effectively defining convention here. Engage the bSI Implementers Forum.

### Missing: Surface-to-Surface Boolean Operations

See Principle #6. Compute in Saikei, write the result.

### Fuzzy: Subgrade/Pavement Layer Boundaries

The boundary between `IfcEarthworksFill` (subgrade), `IfcCourse` (pavement layers), and `IfcPavement` (finished pavement) is unclear in practice. Coordinate with corridor/road-domain implementation. Watch bSI Implementers Forum discussions.

---

## Implementation Checklist for Each Tool

### Surface Creation Tool
- [ ] Definition objects (points, breaklines, boundaries) live in Saikei business layer
- [ ] Triangulation runs inside Saikei (constrained Delaunay if breaklines present)
- [ ] TIN written via IfcOpenShell as `IfcTriangulatedIrregularNetwork`
- [ ] Face flags correctly encode breaklines and holes
- [ ] Wrapped in `IfcGeographicElement` with `PredefinedType = TERRAIN`
- [ ] Contained in `IfcSite` via `IfcRelContainedInSpatialStructure`
- [ ] `IfcMapConversion` properly configured for georeferencing
- [ ] `IfcShapeAspect` or classification applied for surface identity
- [ ] Blender mesh generated as disposable cache from IFC TIN data

### Surface Edit Tool
- [ ] Edits flow to definition objects FIRST
- [ ] Triangulation regenerated from definition objects
- [ ] IFC TIN entity replaced (not edited piecewise — flags depend on triangulation)
- [ ] Blender mesh cache regenerated from updated IFC

### Grading Tool
- [ ] Grading rules stored as Saikei business objects
- [ ] Output: proposed surface (TIN) + cut/fill volumes
- [ ] Design intent captured in property sets on resulting elements
- [ ] Cut/fill bodies computed as solids, written explicitly
- [ ] Quantity sets pre-computed and attached

### Cut/Fill Tool
- [ ] `IfcEarthworksCut` created with explicit body geometry
- [ ] `IfcRelVoidsElement` linking cut to voided element (terrain or stratum)
- [ ] `IfcRelFillsElement` if cut is filled by foundation/fill/pipe
- [ ] `IfcEarthworksFill` with explicit body for placed fill
- [ ] `Qto_EarthworksCut/FillBaseQuantities` populated (Undisturbed + Loose volumes)
- [ ] `IfcEarthworksCutTypeEnum` / `IfcEarthworksFillTypeEnum` set appropriately
- [ ] Earthworks elements contained in appropriate spatial structure

---

## Existing Bonsai/IfcOpenShell Work to Build On

There is already a Bonsai flow for creating `IfcEarthworksCut`/`IfcEarthworksFill` with auto-generated `Qto_EarthworksCut/FillBaseQuantities` from resulting body geometry (recently added). **Study this implementation before designing Saikei's tools** — avoid duplicating work and align with existing community patterns.

Reference: OSArch community discussion on automatic QTO for `IfcEarthworksCut`/`IfcEarthworksFill`.

Limitations of current Bonsai approach (worth improving in Saikei):
- Boolean difference for cut volume requires manual vertex adjustment in some workflows
- Void position doesn't auto-update when base object moves
- No "Operations" recompute equivalent to Window Tool's pattern

---

## Open Questions for bSI Implementers Forum

1. Convention for parametric surface dependency tracking (corridor + existing → proposed)
2. Subgrade/pavement layer entity boundaries (`IfcEarthworksFill` vs `IfcCourse` vs `IfcPavement`)
3. Standardization of grading design intent in property sets / IDS
4. Future direction on surface-to-surface CSG operations (per `IfcEarthworksCut` doc note)

---

## Key References

- **IFC 4.3 ADD2 Specification**: https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/
- **`IfcEarthworksCut`**: https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/lexical/IfcEarthworksCut.htm
- **`IfcEarthworksFill`**: https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/lexical/IfcEarthworksFill.htm
- **`IfcGeographicElement`**: https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/lexical/IfcGeographicElement.htm
- **`IfcGeotechnicalAssembly`**: https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/lexical/IfcGeotechnicalAssembly.htm
- **Earthworks Cuttings Concept**: https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/concepts/Object_Composition/Element_Voiding/Earthworks_Cuttings/content.html
- **bSI Infra Overall Architecture Guidelines (2017)**: https://buildingsmart.org/wp-content/uploads/2017/07/08_bSI_OverallArchitecure_Guidelines_final.pdf
- **OSArch IfcEarthworksCut/Fill QTO discussion**: https://community.osarch.org/discussion/2888/ifcearthworkscut-fill-now-with-automatic-qto

---

*Document version: 1.0 — generated for Saikei Civil grading/earthwork tool development*

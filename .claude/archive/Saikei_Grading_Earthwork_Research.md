# Saikei Civil — Site Grading & Earthwork Specification

**Status:** Draft v1.0 — Ready for agent work
**Date:** April 24, 2026
**Author:** Desert Springs Civil Engineering PLLC
**Scope:** Non-linear site grading (pads, parking lots, ponds, infield areas)
**Target repo path:** `C:\GitHub\ifcopenshell\src\bonsai\bonsai\` (branch: `saikei-dev`)

---

## 1. Executive Summary

This document specifies the grading and earthwork capabilities for Saikei Civil. The scope covers **non-linear site grading** — the work of moving dirt to create flat pads, sloped parking lots, retention ponds, building footprints, and other area features that are not driven by a single centerline alignment. Corridor/linear earthwork (already partially covered in `Corridor_Generation_Deep_Research.md`) is a separate, adjacent problem; this document touches corridors only where workflows intersect.

The specification rests on a review of four dominant commercial tools — AutoCAD Civil 3D, Bentley OpenSite Designer, Trimble Business Center, and Carlson Civil — and reconciles their approaches with the IFC 4.3 schema. The recommended architecture adopts **Civil 3D's feature-line-plus-criteria model** as the user-facing mental model, backed by **constrained Delaunay triangulation with breakline support** for surface math, and maps cleanly to **`IfcTriangulatedIrregularNetwork`**, **`IfcEarthworksFill`**, and **`IfcEarthworksCut`** for IFC persistence.

Key design decisions up front:

1. **First-class Surface entity.** Everything grading-related is ultimately a surface operation. We model `CivilSurface` as the central object, with TIN representation, breakline support, and boundary/hole handling.
2. **Feature-line-driven grading, not object-blob grading.** Users define grading footprints as feature lines with elevations, apply criteria (slope to surface, slope to elevation, slope to distance), and the engine resolves the 3D geometry. This matches Civil 3D, OpenSite, and Carlson's mental models — and critically, it's what Treasure Valley engineers already know.
3. **Grading groups aggregate volumes.** Individual grading objects are composed into groups that produce a single design surface and a single earthwork report.
4. **IFC export via `IfcTriangulatedIrregularNetwork` + earthworks entities.** The existing ground, proposed ground, cut volume, and fill volume each serialize to standard IFC 4.3 constructs — no custom extensions needed.
5. **Python-native math via `scipy.spatial.Delaunay` + `shapely.constrained_delaunay_triangles`.** No external CAD kernels, no C++ bindings beyond what's already in the Bonsai stack.

---

## 2. Research Summary — Commercial Tools

### 2.1 AutoCAD Civil 3D

Civil 3D is the dominant site-grading tool in the US and the yardstick most engineers (including Idaho-based firms) measure against. Its grading stack has three layered concepts:

**Feature Line.** A 3D polyline with explicit elevations at each vertex and grade/elevation editing tools — Civil 3D's own documentation describes it as "similar to 3D polylines and store both horizontal and elevation location data." Feature lines can come from AutoCAD polylines (with elevation assigned from a surface, or manually), from corridor feature lines, or drawn from scratch. They serve as the "footprint" for a grading object.

**Grading Criteria.** A rule that tells the engine how to project a slope from a feature line. Civil 3D ships four base criteria: slope/grade to distance, slope/grade to elevation, slope/grade to relative elevation, and slope/grade to surface. A criteria can specify different cut and fill slopes. Critically, criteria are stored in a *grading criteria set* that's scoped to the current drawing — they don't carry forward between projects unless exported.

**Grading Object.** The result of applying a criteria to a feature line. It consists of the feature line (baseline) plus slope projection lines out to a target (surface, distance, or elevation) and a dynamically computed "daylight" line — the feature line where the projection intersects the target. Grading objects are dynamic: editing the baseline feature line triggers a recalculation of every point along the projection.

**Grading Group.** A collection of grading objects that model one composed feature (a pond, a building pad, a parking lot). The group can automatically generate a surface from its members and calculate cut/fill volumes. Groups must exist within a *site*, which provides the topological context for interaction — grading objects within the same site automatically resolve conflicts at their intersections. Setting the site to `<none>` (siteless) prevents interaction.

**Workflow (typical site pad):**
1. Draw a polyline around the pad perimeter.
2. Convert polyline to feature line; assign elevation from existing surface or manually.
3. Create a grading group (in a site).
4. Apply grading criteria (e.g., "Slope to Surface, 3:1 fill / 2:1 cut") to the feature line, with the existing ground as target.
5. Civil 3D computes the daylight line and adds the resulting surface to the grading group's output surface.
6. Create a volumes surface comparing existing ground to grading group surface.

**Strengths:**
- Mental model is tangible — engineers draw the thing they want, apply rules, get geometry.
- Dynamic editing is extremely powerful; changing one vertex elevation cascades through the entire grading.
- Composable: complex sites are assembled from many feature lines and grading groups.

**Weaknesses:**
- Brittle when feature lines cross or approach each other (site interaction resolution is fragile).
- Grading criteria don't cross drawings well.
- No built-in optimization — engineer picks elevations, iterates manually.

### 2.2 Bentley OpenSite Designer

OpenSite is the successor to PowerCivil, GEOPAK Site, InRoads Site, and MXSite — Bentley consolidated all legacy site tools into one product. The philosophy is fundamentally different from Civil 3D: rule-based parametric layout plus optimization.

**Civil Cells.** Intelligent, reusable design features that encapsulate the geometry, rules, and relationships needed to build a specific graded feature — intersections, curb ramps, parking islands, roundabouts. A civil cell can be placed, then dynamically adjusts to its context (touching roadway, terrain, reference elements). When the reference geometry changes, the civil cell regenerates. This is substantially more sophisticated than Civil 3D's grading groups.

**Linear Templates.** A cross-section template applied along any linear feature (not just an alignment). Used to model curb-and-gutter around a parking lot perimeter, sidewalks, ditches — situations where the "alignment" is the edge of a feature rather than a road centerline.

**Grading Solver.** An optimization engine that iterates through thousands of design variants within engineer-defined constraints to find a grading solution that balances cut and fill, minimizes cost, or meets other objectives. This is the feature that distinguishes OpenSite from everything else on the market. The solver uses "design criteria" to parameterize what's adjustable — pad elevations, slope ratios, transition points — and runs combinatoric searches.

**Terrain Model.** OpenSite's surface object supports the expected feature types: boundaries, holes, voids, breaklines, inferred breaklines, and random points. Terrain is first-class — it can be displayed with re-symbolization for triangles, contours, slope vectors, color-coded slopes, elevation banding, and aspect, with no secondary analysis required.

**Workflow (parking lot with building pad):**
1. Import existing terrain from LiDAR or survey.
2. Use parametric layout tools to place building pad and parking layout with design rules (stall width, drive aisle widths).
3. Place civil cells for curb ramps, islands, intersections with adjacent roads.
4. Apply linear templates to parking lot edge (curb and gutter, sidewalks).
5. Run grading solver with constraints (max slope, min slope for drainage, elevation tolerance at building pad).
6. Solver produces graded surface and cut/fill report.

**Strengths:**
- Most sophisticated grading automation on the market.
- Civil cells encapsulate institutional design knowledge.
- Optimization runs thousands of alternatives in minutes.
- Strong terrain model with native feature-type awareness.

**Weaknesses:**
- Steep learning curve (user forum exchanges show engineers struggling for months with the parametric model).
- Tightly coupled to MicroStation environment.
- Civil cells require significant setup to author; out-of-box library is limited.
- Solver can produce "correct but weird" grading that engineers then have to manually fix.

### 2.3 Trimble Business Center (TBC)

TBC is different in philosophy from the first two tools. It's primarily a **contractor-side** tool — built for converting 2D engineered plans into 3D models for machine control, takeoff, and staking. It does have design capabilities, but they're oriented around constructible models rather than design iteration.

**Surface Pair Approach.** TBC's fundamental unit of earthwork is a comparison between two surfaces: existing and proposed. Volumes are calculated as the volumetric difference between TINs, typically with prismoidal methods. This matches how contractors think — they're bidding dirt movement, not designing grade.

**Site Improvements.** TBC has a library of site improvement types — heavy-duty asphalt, standard-duty asphalt, concrete slab, building pad, topsoil — each with material properties (depth, density, shrink/swell). These categorize regions of a proposed surface for detailed takeoff (how much asphalt, how much base, how much topsoil stripping).

**Takeoff from PDFs.** TBC's signature capability: import an engineered PDF plan set, georeference it, trace elevations from contours and spot elevations, and build a 3D model contractors can send to machines. This is the "Construction" edition and is heavily used in US earthwork bidding.

**Corridor Design.** TBC does have alignment-based corridor design with templates — same general pattern as Civil 3D or OpenRoads (alignment + vertical + typical section + stations). It's less sophisticated than the Autodesk/Bentley offerings but adequate for contractor use.

**Mass Haul.** TBC computes mass haul diagrams for corridors and can optimize earth movement with dozer vs. truck/shovel ranges (this is the "Cut/Fill Movement" capability).

**Strengths:**
- Unbeatable for converting 2D plans to 3D contractor models.
- Excellent volume calculation accuracy (true TIN-to-TIN prismoidal).
- Site improvements model directly supports takeoff workflows.
- Strong machine control export (Trimble SCS/WorksManager).

**Weaknesses:**
- Not a design-first tool; grading design capabilities are basic.
- No grading criteria / feature-line model like Civil 3D.
- No optimization like OpenSite.

### 2.4 Carlson Civil

Carlson is popular with contractors and smaller civil firms, particularly in the western US. It runs on IntelliCAD or AutoCAD and mirrors some of Civil 3D's concepts but with different primitives.

**Design Pad Template.** Carlson's core grading primitive. Given a perimeter polyline (the "top of pad") and a target surface, the command prompts for fill outslope ratio, cut outslope ratio, and pad elevation, then computes the graded pad surface and slope ties. It can process multiple pads in one command and output a combined earthworks report.

**Slope Templates (.TPL files).** For complex slopes, Carlson supports template files that define cross-sections with cut/fill slopes, ditches, curbs, and edges of road. Templates can be applied to pad perimeters (treating the perimeter as a centerline) to produce more detailed grading than simple outslopes.

**Surface Files.** Carlson supports both grid surfaces (`.GRD` — regular mesh) and triangulation surfaces (`.TIN` or `.FLT`). Volumes commands are split accordingly: `Two Surface Volumes` operates on grids (faster but resolution-limited), while `Volumes by Triangulation` uses true TIN-to-TIN prismoidal calculations. Carlson notes that grid volumes can miss narrow features (e.g., a 5-foot ditch) if grid resolution is coarser than the feature.

**Design Bench Pond.** A specialized pad-like command for retention ponds that computes pond storage alongside earthwork, outputting a stage-storage curve (`.CAP` file) for hydrograph routing.

**SiteNET, LotNET, RoadNET.** Sub-modules for sub-grade takeoff, subdivision layout, and road networks respectively. SiteNET is specifically aimed at contractor takeoff — layer-based surface generation from PDF/CAD imports with earthwork calc.

**Workflow (building pad):**
1. Draw perimeter polyline at desired elevation (flat pad) or with varying elevations (sloped pad).
2. Run `Design Pad Template`.
3. Specify cut/fill outslope ratios, pad elevation, and target surface (existing ground).
4. Carlson draws 3D polylines for slope ties and reports earthwork volumes.
5. Optionally write output as a triangulation file or grid and combine with other pads for a total site surface.

**Strengths:**
- Simple, fast — engineers can grade a pad in 30 seconds.
- Multiple pads in a single command with combined reporting.
- Strong pond design (stage-storage, biofiltration options).
- TIN-based volumes are accurate.

**Weaknesses:**
- Not dynamic — pads are "baked" on creation; edit requires rerunning.
- No grading groups concept; no automatic site interaction resolution.
- TPL template system is file-based and dated.
- Mental model assumes one command per feature rather than a composed design.

### 2.5 Comparative Matrix

| Concept | Civil 3D | OpenSite | TBC | Carlson |
|---------|----------|----------|-----|---------|
| Footprint primitive | Feature line (3D polyline with elevations) | Civil cell / linear feature | Linestring / polyline | Perimeter polyline |
| Slope rule primitive | Grading criteria (criteria set) | Design criteria + civil cell rules | Offset / slope tools | Outslope ratio + TPL template |
| Composition | Grading group within site | Civil cells referencing each other | Surface pairs | Individual pad commands |
| Dynamic? | Yes — recalculates on edit | Yes — rule-based regeneration | No — surfaces are baked | No — rerun command |
| Optimization | No | **Yes — Grading Solver** | No | No |
| Volume method | TIN-to-TIN prismoidal | TIN-to-TIN prismoidal | TIN-to-TIN prismoidal | Grid or TIN (user choice) |
| Surface support | Full (breaklines, holes, boundaries) | Full (incl. inferred breaklines) | Full | Full |
| Contractor orientation | Some (QTO add-ons) | Moderate (via SITEOPS) | **Strong** | Strong (SiteNET) |
| Learning curve | Moderate | Steep | Moderate | Shallow |

---

## 3. IFC 4.3 Schema Mapping

### 3.1 Terrain and Designed Surfaces

IFC 4.3 provides **`IfcTriangulatedIrregularNetwork`** as the canonical representation for terrain-type surfaces. It is a subtype of `IfcTriangulatedFaceSet` with a `Flags` list that carries one integer per triangle indicating breakline ownership, hole, or void status. Key properties per the buildingSMART specification:

- `IfcTriangulatedIrregularNetwork.Closed` must be `FALSE` (it represents an open surface, not a solid).
- One unique Z per (X, Y) — so it represents "draped" surfaces, not overhangs. This matches standard civil engineering surface modeling.
- Triangles must be counterclockwise when viewed from above (right-hand rule).
- Flag conventions (per buildingSMART):
  - Positive integer encodes edge-owning breakline ID (useful for preserving which edges are breaklines through round-trip).
  - Negative values indicate hole or void.
  - `Void` triangles are excluded with no fallback.
  - `Hole` triangles are excluded but may fall back on another surface's geometry (useful for layered sites).

**Implication for Saikei:** We can represent existing ground, proposed ground (per grading group), and the final composite proposed site all as `IfcTriangulatedIrregularNetwork`. The `Flags` mechanism lets us preserve breakline identity through IFC round-tripping, which matters for surveyors downstream who want to know which edges came from, e.g., a top-of-curb line.

### 3.2 Earthworks Entities

Two core entities handle the "volume of dirt" side of the model:

**`IfcEarthworksCut`** — a subtype of `IfcFeatureElementSubtraction`. Semantically it represents the work of excavation; geometrically it represents the void created. Per buildingSMART: "The material excavated... is not modelled as Cut." Cuts are related to their host (typically an `IfcGeotechnicalStratum` representing the existing ground or an `IfcEarthworksFill`) via `IfcRelVoidsElement` — the same relationship used for doors voiding walls. An `IfcEarthworksCut` can optionally be filled by another element via `IfcRelFillsElement`.

**`IfcEarthworksFill`** — a subtype of `IfcEarthworksElement`, which is itself a subtype of `IfcElementAssembly`. Represents bulk earthwork building subgrade or raising ground level. Has a `PredefinedType` enum covering `EMBANKMENT`, `SUBGRADE`, `SUBGRADEBED`, `SLOPEFILL`, and others. Can contain sub-fills (a fill is both an object and a collection).

**`IfcGeotechnicalStratum`** — represents a geological stratum (existing ground layer, soil horizon). Used as the parent element that cuts void and fills sit atop.

**`IfcGeomodel`** — an abstract grouping container for a site's geotechnical/earthworks description, typically contained in `IfcSite` via `IfcRelContainedInSpatialStructure`.

### 3.3 Recommended IFC Structure for a Graded Site

```
IfcProject
└── IfcSite
    ├── IfcGeomodel
    │   ├── IfcGeotechnicalStratum (existing ground — TIN representation)
    │   ├── IfcEarthworksCut [PredefinedType=EXCAVATION] (cut volume — solid)
    │   │   └── voids the stratum via IfcRelVoidsElement
    │   └── IfcEarthworksFill [PredefinedType=EMBANKMENT] (fill volume — solid)
    │
    └── IfcBuiltSystem [PredefinedType=EARTHWORK]
        └── (groups all fills and cuts for the site via IfcRelAssignsToGroup)
```

The existing ground, designed ground, cut volume, and fill volume each have independent geometric representations. This enables:
- Viewers to show existing-only, proposed-only, or both.
- Quantity takeoff tools to query cut and fill volumes directly.
- Machine-control tools to read the proposed surface (existing ± cut/fill applied to stratum).

### 3.4 Grading-specific Property Sets

We define Saikei property sets on the earthworks entities for design information that doesn't have a native home in IFC 4.3:

- `Pset_SaikeiGrading_Source`: source grading group name, criteria applied, timestamp.
- `Pset_SaikeiGrading_Volumes`: cut volume (m³), fill volume (m³), net volume, shrink factor, swell factor, compacted volume.
- `Pset_SaikeiGrading_Surface`: triangulation tolerance, breakline count, vertex count, boundary polygon reference.

Property sets serialize as `IfcPropertySet` attached via `IfcRelDefinesByProperties`, which is the standard Bonsai pattern and requires no schema extension.

---

## 4. Surface Mathematics

### 4.1 TIN Construction — Constrained Delaunay

Every modern civil tool uses **constrained Delaunay triangulation (CDT)** for surface construction. "Constrained" means specified edges (breaklines) are forced into the triangulation regardless of the Delaunay criterion. Breaklines matter because without them a Delaunay algorithm will pick whichever diagonal satisfies the circumcircle test, which can route a triangle edge across a feature that should have constrained the interpolation — e.g., a triangle crossing the top of a curb, producing a sloped face where there should be a vertical break.

**Library choices for Saikei:**

- **Shapely 2.1+** — provides `shapely.constrained_delaunay_triangles()` which takes a polygon (optionally with holes and interior edges) and returns a constrained triangulation. This is the primary tool for breakline-honoring TINs.
- **SciPy** — `scipy.spatial.Delaunay` provides unconstrained Delaunay backed by Qhull. Fast, robust, but does not honor breaklines. Good fallback for "just triangulate this point cloud."
- **Triangle** (Shewchuk) via `triangle` Python binding — if CDT performance becomes an issue. Not required for MVP.

**Saikei implementation choice:** Shapely 2.1+ for CDT, SciPy for unconstrained cases, with the interface abstracted behind a `Triangulator` class in `tool/surface.py` so the backend can swap if needed.

### 4.2 Breaklines

A breakline is a linear feature where grade must break — the triangulation is not free to interpolate smoothly across it. In civil surface modeling, breaklines come from:

- Top of curb, flowline of gutter
- Edge of pavement
- Top and toe of slope
- Ridge and valley lines
- Ditch centerlines
- Retaining wall top and bottom

Breaklines carry elevation data at every vertex (they're 3D polylines). In CDT, the breakline edges become constrained edges in the triangulation, and the algorithm subdivides the breakline at triangle intersection points if necessary.

**Saikei data model for breaklines:**

```python
@dataclass
class Breakline:
    """A 3D polyline that must be honored as constrained edges in a TIN."""
    guid: str
    name: str
    polyline: list[tuple[float, float, float]]  # (x, y, z)
    kind: Literal["standard", "wall", "non_destructive", "proximity"]
    source: str  # "manual", "feature_line_xyz", "corridor_extract"
```

- `standard`: normal breakline with elevation enforced.
- `wall`: two adjacent polylines at different elevations (top and bottom of a wall).
- `non_destructive`: breakline added to triangulation but not the vertices (interpolates Z from the surface rather than using the breakline's own Z).
- `proximity`: planar-only breakline — the triangulation is constrained but Z is interpolated.

### 4.3 Surface Boundaries and Holes

A `CivilSurface` has three boundary categories:

- **Outer boundary** (exactly one): the overall extent of the surface. Points outside are not part of the surface.
- **Holes** (zero or more): regions excluded from the surface but that may fall back on another surface (corresponds to IFC `Flags` = `Hole`).
- **Voids** (zero or more): regions excluded with no fallback (corresponds to IFC `Flags` = `Void`).

Boundaries are 2D polygons (elevations are ignored — only the XY footprint matters for boundary logic). The CDT is computed within the outer boundary minus holes minus voids, then triangles are flagged appropriately for IFC export.

### 4.4 Volume Calculation — Prismoidal TIN-to-TIN

Given two `CivilSurface` objects (existing and proposed), earthwork volume is computed by:

1. Compute the union of their outer boundaries (the area over which a comparison is defined).
2. Within that region, for every pair of overlapping triangles (one from each surface), compute the **prismoidal volume** between them.
3. Classify the prism as cut (existing above proposed) or fill (proposed above existing).
4. Sum cuts and fills separately.

**Prismoidal volume formula** for a prism between two triangles with the same XY footprint:
V = (A / 3) × (z_exist_avg - z_prop_avg)

where `A` is the triangle area and each `z_avg` is the mean of its three vertex elevations. If the sign is positive, it's a cut (net excavation); if negative, it's a fill (net placement).

**Overlap handling:** When triangles from the two surfaces don't share the same footprint (the usual case), the implementation computes the intersection polygon of each triangle pair, triangulates the intersection, and sums the prismoidal contributions per sub-triangle. This is the TIN-to-TIN prismoidal method that Civil 3D, OpenSite, and Carlson all use for their most accurate volume calculation.

**Saikei implementation:** A `volume_tin_to_tin(surface_a, surface_b) -> VolumeResult` function in `tool/earthwork.py` with `VolumeResult` carrying cut, fill, net, cut color map, and per-triangle detail.

### 4.5 Cut/Fill Visualization

Commercial tools render a cut/fill color map over the site — red-to-orange for cuts (existing above proposed, excavation), blue-to-cyan for fills (proposed above existing, placement), white at the balance line. Saikei should produce this as a **false-color overlay mesh** in Blender using per-face vertex colors. The implementation generates a copy of the proposed surface mesh with vertex colors driven by the per-vertex cut/fill delta, renderable under a shader that maps the delta to a red-white-blue gradient.

---

## 5. Saikei Grading Architecture

This section lays out the modules, classes, and data flow for Saikei's grading implementation. It follows the mandatory Bonsai 3-layer architecture (Core / Tool / UI) and sits alongside the existing Alignment module at `src/bonsai/bonsai/`.

### 5.1 Module Layout

```
src/bonsai/bonsai/
├── core/
│   ├── alignment.py          (existing)
│   ├── surface.py            (new)
│   ├── grading.py            (new)
│   └── earthwork.py          (new)
├── tool/
│   ├── alignment.py          (existing)
│   ├── surface.py            (new)
│   ├── grading.py            (new)
│   └── earthwork.py          (new)
└── bim/module/
    ├── alignment/            (existing)
    ├── surface/              (new)
    ├── grading/              (new)
    └── earthwork/            (new)
```

**Layer boundaries (strictly enforced, per Dion's clarification):**

- **Core** — workflow orchestration only. Receives tool classes via dependency injection. No `bpy`, no math, no IFC entity creation.
- **Tool** — all implementations. Math, Blender operations, IFC authoring via `ifcopenshell.api`.
- **UI** — operators (inherit `tool.Ifc.Operator`, implement `_execute()`), panels, props, decorators.

### 5.2 Operator Prefixes

Following the established `CIVIL_OT_*` / `CIVIL_PT_*` convention:

- Surface operators: `CIVIL_OT_surface_*` (e.g., `CIVIL_OT_surface_create_tin`, `CIVIL_OT_surface_add_breakline`).
- Grading operators: `CIVIL_OT_grading_*` (e.g., `CIVIL_OT_grading_create_pad`, `CIVIL_OT_grading_apply_criteria`).
- Earthwork operators: `CIVIL_OT_earthwork_*` (e.g., `CIVIL_OT_earthwork_compute_volumes`, `CIVIL_OT_earthwork_cutfill_map`).

### 5.3 Data Model Overview

```python
# tool/surface.py — data primitives (not Core-facing)

@dataclass
class CivilSurface:
    """An engineered or measured 3D surface."""
    guid: str
    name: str
    kind: Literal["existing", "proposed", "composite"]
    points: np.ndarray                        # shape (N, 3), xyz coordinates
    triangles: np.ndarray                     # shape (M, 3), vertex indices
    triangle_flags: np.ndarray                # shape (M,), IFC Flags list
    breaklines: list[Breakline]
    outer_boundary: shapely.Polygon
    holes: list[shapely.Polygon]
    voids: list[shapely.Polygon]
    ifc_entity: IfcTriangulatedIrregularNetwork | None
    metadata: dict


@dataclass
class FeatureLine:
    """A 3D polyline used as a grading footprint."""
    guid: str
    name: str
    vertices: list[tuple[float, float, float]]   # (x, y, z)
    closed: bool
    grading_group: str | None                     # parent grading group guid


@dataclass
class GradingCriteria:
    """A rule for projecting a slope from a feature line."""
    guid: str
    name: str
    target_kind: Literal["surface", "elevation", "relative_elevation", "distance"]
    target_ref: str | float                       # surface guid, elevation, or distance
    cut_slope: float                              # ratio (H:V), e.g., 2.0 means 2:1
    fill_slope: float                             # ratio (H:V)
    max_distance: float | None                    # daylight cap
    retaining_wall_at_limit: bool                 # auto-insert wall if slope exceeds cap


@dataclass
class GradingObject:
    """A feature line plus a criteria, producing slope projection geometry."""
    guid: str
    name: str
    footprint: FeatureLine
    criteria: GradingCriteria
    target_surface: CivilSurface | None
    daylight_line: list[tuple[float, float, float]]   # computed, 3D polyline
    projection_faces: list[list[int]]                 # computed, triangle indices


@dataclass
class GradingGroup:
    """A collection of grading objects producing a single composite surface."""
    guid: str
    name: str
    members: list[GradingObject]
    interior_fill: Literal["none", "flat", "interpolate_from_boundary", "from_surface"]
    interior_fill_source: CivilSurface | None
    output_surface: CivilSurface                       # computed composite
    target_surface: CivilSurface                       # existing ground reference
```

### 5.4 Workflow Diagram

```
┌──────────────┐     ┌──────────────┐     ┌───────────────┐
│ Existing     │     │ Feature      │     │ Grading       │
│ Ground       │     │ Lines        │     │ Criteria      │
│ (CivilSurf)  │     │              │     │               │
└──────┬───────┘     └──────┬───────┘     └───────┬───────┘
       │                    │                     │
       │                    ▼                     │
       │            ┌──────────────┐              │
       └───────────▶│ Grading      │◀─────────────┘
                    │ Object       │
                    │ (per FL+Crit)│
                    └──────┬───────┘
                           │ N objects
                           ▼
                    ┌──────────────┐
                    │ Grading      │
                    │ Group        │◀── Interior fill strategy
                    │              │
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐     ┌──────────────┐
                    │ Proposed     │     │ Existing     │
                    │ Surface      │     │ Surface      │
                    └──────┬───────┘     └──────┬───────┘
                           │                    │
                           └─────────┬──────────┘
                                     ▼
                            ┌──────────────────┐
                            │ Earthwork        │
                            │ Volumes          │
                            │ (Cut + Fill)     │
                            └──────────────────┘
                                     │
                                     ▼
                            ┌──────────────────┐
                            │ IFC Export       │
                            │ - TIN surfaces   │
                            │ - EarthworksCut  │
                            │ - EarthworksFill │
                            └──────────────────┘
```

### 5.5 Core API (the thin orchestration layer)

Core functions receive tool classes via dependency injection and call only into them. They contain the workflow logic — "do A, then B, then C if condition" — but none of the math or IFC authoring.

```python
# core/surface.py

def create_surface_from_points(tool, name: str, points: np.ndarray, kind: str) -> str:
    """Create a new CivilSurface from a point cloud. Returns surface guid."""
    surface = tool.Surface.build_tin_from_points(name, points, kind)
    tool.Ifc.run("surface.add_triangulated_surface", surface=surface)
    tool.Surface.link_to_blender(surface)
    return surface.guid


def add_breakline_to_surface(tool, surface_guid: str, breakline: Breakline) -> None:
    """Add a breakline to an existing surface and retriangulate."""
    surface = tool.Surface.get(surface_guid)
    tool.Surface.add_breakline(surface, breakline)
    tool.Surface.retriangulate(surface)
    tool.Surface.update_ifc(surface)
    tool.Surface.update_blender(surface)


# core/grading.py

def create_grading_group(tool, name: str, target_surface_guid: str) -> str:
    """Create a new empty grading group targeting an existing surface."""
    target = tool.Surface.get(target_surface_guid)
    group = tool.Grading.create_group(name, target)
    tool.Ifc.run("grading.add_group", group=group)
    return group.guid


def add_grading_object(
    tool,
    group_guid: str,
    feature_line_guid: str,
    criteria_guid: str,
) -> str:
    """Add a grading object (feature line + criteria) to a grading group."""
    group = tool.Grading.get_group(group_guid)
    feature_line = tool.Grading.get_feature_line(feature_line_guid)
    criteria = tool.Grading.get_criteria(criteria_guid)

    grading_object = tool.Grading.compute_grading_object(
        feature_line, criteria, group.target_surface
    )
    tool.Grading.add_to_group(group, grading_object)
    tool.Grading.rebuild_group_surface(group)
    tool.Grading.update_blender(group)
    return grading_object.guid


# core/earthwork.py

def compute_earthwork_volumes(
    tool, existing_surface_guid: str, proposed_surface_guid: str
) -> dict:
    """Compute cut and fill volumes between two surfaces."""
    existing = tool.Surface.get(existing_surface_guid)
    proposed = tool.Surface.get(proposed_surface_guid)
    result = tool.Earthwork.volume_tin_to_tin(existing, proposed)
    tool.Ifc.run("earthwork.add_cut_fill_solids", result=result)
    return {
        "cut_cy": result.cut_cubic_yards,
        "fill_cy": result.fill_cubic_yards,
        "net_cy": result.net_cubic_yards,
    }
```

### 5.6 Tool Layer (the real work)

Tool implementations are where math and IFC authoring live. They're pure Python classes with static-ish methods that operate on data primitives.

```python
# tool/surface.py

class Surface:
    @staticmethod
    def build_tin_from_points(name: str, points: np.ndarray, kind: str) -> CivilSurface:
        """Build a TIN via Delaunay triangulation."""
        from scipy.spatial import Delaunay
        xy = points[:, :2]
        tri = Delaunay(xy)
        surface = CivilSurface(
            guid=str(uuid.uuid4()),
            name=name,
            kind=kind,
            points=points,
            triangles=tri.simplices,
            triangle_flags=np.zeros(len(tri.simplices), dtype=int),
            breaklines=[],
            outer_boundary=Surface._compute_hull(xy),
            holes=[],
            voids=[],
            ifc_entity=None,
            metadata={},
        )
        return surface

    @staticmethod
    def retriangulate(surface: CivilSurface) -> None:
        """Rebuild the TIN honoring breaklines, holes, and voids (CDT)."""
        import shapely
        # Compose the domain polygon with holes
        domain = surface.outer_boundary
        for hole in surface.holes + surface.voids:
            domain = domain.difference(hole)

        # Add breakline segments as interior constraints
        constrained_geom = shapely.union_all(
            [domain] + [shapely.LineString(bl.polyline) for bl in surface.breaklines]
        )
        tri_collection = shapely.constrained_delaunay_triangles(constrained_geom)
        # ... convert back to surface.triangles with Z interpolation ...
        # Set triangle_flags based on breakline ownership, hole/void membership

    @staticmethod
    def z_at(surface: CivilSurface, x: float, y: float) -> float | None:
        """Return the interpolated Z at (x, y), or None if outside the surface."""
        # Point-in-triangle test + barycentric interpolation
        ...

    @staticmethod
    def update_ifc(surface: CivilSurface) -> None:
        """Serialize to IfcTriangulatedIrregularNetwork."""
        import ifcopenshell.api
        # ifcopenshell.api has no dedicated TIN API yet — authored directly
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
        # Wrap in IfcShapeRepresentation and attach to an IfcGeographicElement
        # or IfcGeotechnicalStratum depending on surface.kind
        surface.ifc_entity = tin


# tool/grading.py

class Grading:
    @staticmethod
    def compute_grading_object(
        feature_line: FeatureLine,
        criteria: GradingCriteria,
        target_surface: CivilSurface | None,
    ) -> GradingObject:
        """Project a slope from the feature line to the target, producing geometry."""
        if criteria.target_kind == "surface":
            return Grading._project_to_surface(feature_line, criteria, target_surface)
        elif criteria.target_kind == "elevation":
            return Grading._project_to_elevation(feature_line, criteria, float(criteria.target_ref))
        elif criteria.target_kind == "relative_elevation":
            return Grading._project_to_relative_elevation(feature_line, criteria, float(criteria.target_ref))
        elif criteria.target_kind == "distance":
            return Grading._project_to_distance(feature_line, criteria, float(criteria.target_ref))
        raise ValueError(f"Unknown criteria target_kind: {criteria.target_kind}")

    @staticmethod
    def _project_to_surface(feature_line, criteria, target_surface) -> GradingObject:
        """
        For each vertex in the feature line, march outward at the cut or fill slope
        (selected by comparing feature line Z to target surface Z at footprint)
        until hitting the surface. The resulting intersection points form the
        daylight line. Triangulate between the feature line and daylight line
        to produce projection faces.
        """
        ...

    @staticmethod
    def rebuild_group_surface(group: GradingGroup) -> CivilSurface:
        """
        Compose all grading objects in the group plus the interior fill strategy
        into a single proposed CivilSurface for the group.
        """
        ...


# tool/earthwork.py

class Earthwork:
    @staticmethod
    def volume_tin_to_tin(surface_a: CivilSurface, surface_b: CivilSurface) -> VolumeResult:
        """True TIN-to-TIN prismoidal volume calculation."""
        # For each pair of overlapping triangles:
        #   1. Compute intersection polygon in XY
        #   2. Triangulate the intersection
        #   3. For each sub-triangle, compute prismoidal volume using average Z deltas
        #   4. Classify as cut or fill based on sign
        ...
```

### 5.7 UI Layer Outline

**Panels:**

- `CIVIL_PT_surface_panel` — surface list, create/edit, visualization toggles (triangles, contours, slope vectors).
- `CIVIL_PT_grading_panel` — grading groups list; per-group shows member grading objects, cut/fill totals.
- `CIVIL_PT_earthwork_panel` — earthwork volume calculations, mass haul (future), cut/fill color map controls.

**Operators (minimum viable set for MVP):**

- `CIVIL_OT_surface_create_from_points` — import XYZ, CSV, or LandXML point set, build TIN.
- `CIVIL_OT_surface_add_breakline` — pick 3D polyline in viewport, convert to breakline.
- `CIVIL_OT_surface_set_boundary` — pick 2D polygon as outer/hole/void.
- `CIVIL_OT_feature_line_create` — draw or convert mesh edge loop to feature line with elevations.
- `CIVIL_OT_feature_line_assign_elevations_from_surface` — drape onto surface.
- `CIVIL_OT_grading_create_group` — create new grading group, target surface.
- `CIVIL_OT_grading_create_criteria` — author a new grading criteria (target kind, slopes).
- `CIVIL_OT_grading_add_object` — apply criteria to feature line within group.
- `CIVIL_OT_grading_rebuild_group` — recompute group surface after edits.
- `CIVIL_OT_earthwork_compute_volumes` — pair two surfaces, compute and report cut/fill.
- `CIVIL_OT_earthwork_cutfill_map` — generate false-color overlay mesh.

### 5.8 Shared Bonsai Tools to Reuse

Saikei grading leverages existing Bonsai tool classes rather than duplicating behavior:

- `tool.Ifc` — for `run()`, `get()`, `link()`, `unlink()` on all IFC entities.
- `tool.Loader.create_generic_shape()` — for converting `IfcTriangulatedIrregularNetwork` to a Blender mesh via the IfcOpenShell geometry engine.
- `tool.Georeference` — for XYZ ↔ ENH coordinate transforms; all surfaces are stored in engineering coordinates but rendered near origin for 32-bit float precision.
- `tool.Collector.assign()` — for placing surfaces in IFC spatial hierarchy (`IfcGeomodel`).
- `tool.Blender` — `validate_shader_batch_data`, `scale_font_size` for surface annotation.

---

## 6. MVP Scope — What Ships in the First PR

Keeping PRs under 4,000 lines (Dion's constraint), MVP scope is:

**In scope (MVP):**
- `CivilSurface` data model and `tool.Surface` implementation.
- TIN construction from point cloud (unconstrained Delaunay via SciPy).
- TIN construction with breaklines (CDT via Shapely 2.1+).
- Outer boundary + holes + voids.
- `IfcTriangulatedIrregularNetwork` authoring and round-trip.
- Basic Blender visualization (mesh with vertex colors for elevation banding).
- Surface panel UI with create-from-points, add-breakline, set-boundary.

**Deferred (next PRs):**
- Feature lines data model + UI (depends on Surface being solid).
- Grading criteria authoring + UI.
- Grading objects (project-to-surface, project-to-elevation).
- Grading groups and composite surfaces.
- Earthwork volumes (TIN-to-TIN prismoidal).
- Cut/fill color map overlay.
- LandXML import/export.
- Optimization (OpenSite-style grading solver) — research only, not MVP.

The MVP is roughly a "terrain modeler" sprint. Grading itself (feature lines + criteria + objects) is the second sprint, and earthwork volumes are the third. This phasing matches how commercial tools were originally built (Carlson, Civil 3D, and OpenSite all shipped terrain before grading).

---

## 7. Agent Work Breakdown

Distribution across the six specialized Claude Code agents. Each task targets one agent's specialty and sizes the work to fit a single PR turn.

### 7.1 Sprint 1 — Surfaces (target: ~2,500 lines)

| Agent | Task | Est. LoC |
|-------|------|----------|
| `saikei-architect` | Finalize `CivilSurface` data model, triangulator abstraction, IFC property sets | 400 |
| `saikei-ifc` | `IfcTriangulatedIrregularNetwork` author/read + `IfcGeotechnicalStratum` wrapper + round-trip test | 600 |
| `tool-dev` | `tool.Surface` impl — `build_tin_from_points`, `retriangulate` with CDT, `z_at`, `volume_tin_to_tin` stub | 700 |
| `blender-ui` | Surface panel, operators for create-from-points, add-breakline, set-boundary | 500 |
| `saikei-tester` | Test TIN build, CDT with breaklines, IFC round-trip | 200 |
| `docs` | Surface module README, CLAUDE.md update for surface layer | 100 |

### 7.2 Sprint 2 — Grading (target: ~3,000 lines)

| Agent | Task | Est. LoC |
|-------|------|----------|
| `saikei-architect` | Finalize `FeatureLine`, `GradingCriteria`, `GradingObject`, `GradingGroup` data models | 400 |
| `saikei-ifc` | Property sets for grading; link grading groups to `IfcBuiltSystem` | 300 |
| `tool-dev` | `tool.Grading` impl — criteria project-to-surface, project-to-elevation, group rebuild | 1000 |
| `blender-ui` | Feature line authoring, grading panel, criteria dialog, add-object operator | 900 |
| `saikei-tester` | Test pad grading, pond grading, group composition | 300 |
| `docs` | Grading module README + example tutorial (flat pad to existing ground) | 100 |

### 7.3 Sprint 3 — Earthwork (target: ~2,000 lines)

| Agent | Task | Est. LoC |
|-------|------|----------|
| `saikei-architect` | Finalize `VolumeResult`, earthwork report schema | 200 |
| `saikei-ifc` | `IfcEarthworksCut`, `IfcEarthworksFill` authoring; `IfcRelVoidsElement` wiring | 500 |
| `tool-dev` | `tool.Earthwork` impl — TIN-to-TIN prismoidal, cut/fill classification, color map | 700 |
| `blender-ui` | Earthwork panel, compute-volumes operator, cut/fill map operator | 400 |
| `saikei-tester` | Test volumes against known hand-calc values; validate IFC export in BIMvision | 150 |
| `docs` | Earthwork README + example workflow (full pad → cut/fill report) | 50 |

---

## 8. Deliberate Design Choices

A list of the non-obvious decisions and the reasoning, so future-me, Dion, or any agent has the rationale without having to reread the research.

**1. Adopt Civil 3D's feature-line-plus-criteria model over OpenSite's civil cells for Saikei's primary grading interface.**
Civil cells are more powerful but they require significant template authoring up front, which is a non-starter for an open-source tool with no initial template library. The feature-line approach is more primitive, which matches what a small-to-midsize civil engineering practice actually does. Civil cells are a plausible Phase 3 feature layered on top of feature lines.

**2. No grading solver in MVP.**
OpenSite's optimization engine is unmatched, but reimplementing it is a multi-month project that takes focus off the more critical problem (basic grading doesn't exist at all yet in any open-source BIM tool). A solver in a later sprint is a plausible research track; it's not in scope here.

**3. TIN-to-TIN prismoidal volumes over grid volumes.**
Grid volumes are faster but resolution-limited and lose fidelity on narrow features (Carlson documents the 5-foot-ditch problem). TIN prismoidal is the method used by all the premium tools for final-grade calculations, and the implementation cost isn't meaningfully higher once the triangle intersection code is written. Grid volumes can be a future backend option if performance demands it.

**4. `IfcTriangulatedIrregularNetwork` over `IfcGeometricCurveSet`.**
Both are valid IFC representations for terrain (the `IfcTerrain` tool documents three options: face set, triangulated face set, curve set). TIN is the richest — it preserves triangulation topology and breakline flags. Curve set loses topology. Given that Saikei's math model IS a TIN internally, serializing to TIN is a one-to-one mapping; any other format is a lossy downgrade.

**5. Shapely over a C++ triangle library.**
Shapely 2.1+ added `constrained_delaunay_triangles`, which covers the CDT case. This avoids pulling in a compiled dependency (Triangle / CGAL / pyggmsh) that complicates the Bonsai build. If performance becomes an issue on very large surfaces (>1M triangles), we can add an alternate backend later without changing the `Triangulator` interface.

**6. Store surfaces in IFC engineering coordinates, render near origin.**
This matches the Saikei georeferencing approach already established for alignments — `IfcMapConversion` provides the ENH ↔ XYZ transform, Blender viewport works at near-origin to stay within 32-bit float precision. Surfaces potentially span kilometers of extent, so this pattern is even more important for grading than for alignments.

**7. Grading groups map to `IfcBuiltSystem` with `PredefinedType=EARTHWORK`.**
This is the buildingSMART-suggested mechanism for grouping earthwork entities (per the IRROADWP3 Annex I examples — see the Earthworks instance diagram). `IfcRelAssignsToGroup` aggregates cuts and fills; the `IfcGeomodel` serves as the spatial/geotechnical container.

**8. Breakline flag encoding in the `Flags` list.**
Per the buildingSMART spec, the `Flags` list is one integer per triangle. We encode: `0` = regular triangle, `positive N` = triangle edge owned by breakline with ID N (breakline ID maps to a Saikei-maintained breakline dictionary), `-1` = `Hole`, `-2` = `Void`. This preserves round-trip fidelity — a Saikei surface exported to IFC and reimported still knows which edges are breaklines.

**9. No LandXML import in MVP.**
LandXML is the de facto surface interchange format, but its schema is large and legacy. We stub the interface but leave the implementation for Sprint 4. XYZ, CSV, and IFC import are enough for MVP. For the initial Treasure Valley subconsulting work, surveyors can export CSV or IFC and Saikei reads both.

**10. Interior fill strategy is explicit, not implicit.**
Civil 3D's grading groups have an ambiguous "infill" behavior that confuses new users. Saikei's `GradingGroup` requires an explicit `interior_fill` choice: `none` (leave interior open), `flat` (the pad is flat at the feature line elevation), `interpolate_from_boundary` (Delaunay with only the feature line as input), or `from_surface` (use another surface for the interior — the Carlson pit-bottom case). This makes the behavior inspectable and prevents surprise.

---

## 9. Open Questions (flagged for Dion / Rick discussion)

Before Sprint 1 kicks off, these items want upstream review:

1. **Grading module naming.** `CIVIL_OT_grading_*` is the natural fit with existing `CIVIL_OT_*` prefixes, but Bonsai's site module already uses `BIM_OT_*` for some spatial ops. Confirm no collision.

2. **`IfcEarthworksCut` geometric representation.** The spec says it's a void, not a solid — it voids a stratum. But for visualization we need *something* to render. Do we author a solid representation (as a shape) on the cut entity while semantically using `IfcRelVoidsElement` for the void relationship? Looking at the BIM Corner IFC 4.3 case study suggests yes, but confirming with Rick's alignment API patterns.

3. **Integration with Rick's `ifcopenshell.api.alignment`.** Linear earthwork (road embankments, cut slopes from corridors) shares data with alignments. Should corridor-driven earthwork use the existing alignment infrastructure, or does it need a parallel earthwork API? The existing `Corridor_Generation_Deep_Research.md` leans toward an extension of the alignment API; this grading spec stays non-linear to avoid that question for MVP.

4. **Georeferencing for lunar sites (LSIC context).** The Moon 2000 CRS (ESRI:104903) is set up for alignments. For surfaces in lunar coordinates, same pattern should work, but the 1,737,400 m radius vs. Earth's 6,378,137 m means projected coordinate precision behaves slightly differently. Worth validating on a test surface before pitching LSIC work.

5. **Vertical datum handling.** Sites in Treasure Valley are NAVD88; LSIC work is mean radius. IFC has `IfcProjectedCRS` but vertical datum is often inferred from the 3D CRS. Want to confirm our `IfcMapConversion` usage survives vertical datum round-trip.

---

## 10. References

- buildingSMART IFC 4.3.2 — [IfcTriangulatedIrregularNetwork](https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/lexical/IfcTriangulatedIrregularNetwork.htm)
- buildingSMART IFC 4.3.2 — [IfcEarthworksCut](https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/lexical/IfcEarthworksCut.htm)
- buildingSMART IFC 4.3.2 — [IfcEarthworksFill](https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/lexical/IfcEarthworksFill.htm)
- buildingSMART IFC 4.3.2 — [Earthworks Cuttings concept](https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/concepts/Object_Composition/Element_Voiding/Earthworks_Cuttings/content.html)
- IRROADWP3 Conceptual Model Report Annex I — Earthworks instance diagrams (project knowledge)
- Autodesk Civil 3D Help — Tutorial: Creating Gradings, Grading Objects reference
- Bentley OpenSite Designer product documentation
- Trimble Business Center help — Understanding Corridors and Corridor Surfaces; Site Takeoff workflow
- Carlson Civil 2022 manual — Design Pad Template, Design Bench Pond, Volumes by Triangulation
- Shapely 2.1 — [constrained_delaunay_triangles](https://shapely.readthedocs.io/en/stable/reference/shapely.constrained_delaunay_triangles.html)
- SciPy — [scipy.spatial.Delaunay](https://docs.scipy.org/doc/scipy/reference/generated/scipy.spatial.Delaunay.html)
- Prior Saikei research — `Corridor_Generation_Deep_Research.md`, `IFC_Roadway_Templates_Assemblies_Reference.md`, `saikei-project-summary.md`

---

*End of specification. Ready for agent work on Sprint 1 (Surfaces).*

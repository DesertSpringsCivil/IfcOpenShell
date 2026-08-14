# Saikei Civil — Complete Feature Outline
## Native IFC Roadway Modeling & Design for Bonsai BIM

**Date:** March 22, 2026
**Author:** Michael [Last Name], PE — Desert Springs Civil Engineering PLLC
**Purpose:** Comprehensive feature outline for GSoC 2026 proposal and long-term project roadmap
**Note:** All line estimates in this document refer to production code only. Test code scope (~155 tests) is tracked separately in the Testing Strategy section.
**Repository:** IfcOpenShell/IfcOpenShell, branch: `saikei`, path: `src/bonsai/bonsai/`

---

## Project Vision

Saikei Civil adds full, native IFC roadway modeling and design capability to Bonsai/IfcOpenShell. It covers everything a professional roadway modeling suite requires: horizontal and vertical alignment creation and editing, cross-section definition, corridor modeling, parametric control of cross slopes and widths, superelevation, and grading with daylight-to-existing-ground capability. All features produce standards-compliant IFC 4.3 output, follow Bonsai's three-layer architecture (Core/Tool/UI), and target workflows familiar to Civil 3D and OpenRoads users.

**Why IFC-native?** Unlike proprietary civil design tools that store project data in closed formats, Saikei writes directly to IFC 4.3 — the open buildingSMART standard for infrastructure. The IFC file *is* the project database: when a user places a PI or PVI, it immediately creates `IfcAlignmentSegment` entities. This means every design decision is interoperable from the moment it is made — no export step, no format conversion, no data loss. For small civil engineering firms priced out of proprietary software, this is the path to full BIM participation.

**Built on the IfcOpenShell alignment API.** The `ifcopenshell.api.alignment` module is an already-merged upstream contribution that provides the canonical IfcOpenShell implementation for creating alignment entities from PI/PVI data. It handles segment creation, layout nesting, geometric representations, and zero-length terminators. Saikei builds its design workflows on top of this API rather than creating IFC entities from scratch.

---

## Scope Classification

- **CORE** — Firm GSoC deliverables (Sections 1–4)
- **STRETCH** — Prioritized stretch goals attempted if core is completed ahead of schedule (Sections 5–11)

---

## CORE SCOPE

### Section 1: Horizontal Alignment (Mostly Complete)

**Status:** ~90% complete. Remaining items are enhancements, not blockers.

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| 1.1 | PI method creation (LINE + CIRCULARARC) | ✅ Done | Uses `ifcopenshell.api.alignment` |
| 1.2 | Segment visualization via geometry engine | ✅ Done | `tool.Loader.create_generic_shape()` |
| 1.3 | PI picker with rubber band | ✅ Done | Inherits Bonsai PolylineOperator |
| 1.4 | PI edit mode (G key) | ✅ Done | GPU decorator for tangent lines |
| 1.5 | Georeferencing / false origin | ✅ Done | `tool.Georeference.enh2xyz()/xyz2enh()` |
| 1.6 | CSV import | ✅ Done | |
| 1.7 | Stationing referents | ✅ Done | |
| 1.8 | Add Element dialog integration | ✅ Done | Representation templates registered |
| 1.9 | Transition spirals (clothoids) | ❌ Not started | Needed for highway-speed design; alignment API lists as future work |
| 1.10 | Station equations | ❌ Not started | Needed for project stationing resets at construction joints |
| 1.11 | LandXML import/export | ❌ Not started | Interoperability with existing Civil 3D/OpenRoads projects |

**GSoC scope for Section 1:** Items 1.9–1.11 are desirable but not blocking. Spirals (1.9) would be addressed if time permits; station equations (1.10) and LandXML (1.11) are deferred to stretch goals.

---

### Section 2: Vertical Alignment

**Status:** Not yet implemented. Feature spec drafted. The upstream alignment API (`layout_vertical_alignment_by_pi_method`) is merged and available.

#### 2.1 PVI Method Creation
- PVI (Point of Vertical Intersection) input: station, elevation, vertical curve length
- Segment types: `CONSTANTGRADIENT` (grade lines) and `PARABOLICARC` (vertical curves)
- Creates `IfcAlignmentVertical` nested under `IfcAlignment` via `IfcRelNests`
- Key IFC relationships: `IfcRelNests` (vertical layout under alignment), zero-length terminal segment required at end of layout
- Uses `ifcopenshell.api.alignment.layout_vertical_alignment_by_pi_method()`
- Mirrors horizontal PI method workflow for consistency

#### 2.2 Profile View Visualization
- 2D overlay at bottom of Blender 3D viewport (station vs. elevation coordinate system)
- GPU-accelerated rendering (shader-based, no mesh overhead)
- Grid with station/elevation labels
- Terrain profile display (existing ground sampled from Blender mesh along alignment) — requires terrain designation and profile extraction (Sections 8.1–8.2, moved to core scope)
- Alignment grade line display with PVI markers
- Interactive: click to place PVIs, drag to edit, G key to move

#### 2.3 Vertical Curve Editing
- Real-time curve preview during PVI placement
- Grade percentage display between PVIs
- K-value calculation and display for vertical curves
- Minimum curve length validation against design speed

#### 2.4 3D Alignment Combination
- Combine horizontal + vertical into 3D alignment curve
- `IfcGradientCurve` representation (Axis/Curve3D, combined horizontal + vertical geometry)
- 3D curve visualization in Blender viewport
- This 3D curve becomes the directrix for corridor generation

#### Architecture
- **Core** (`core/alignment.py`): Business logic — PVI data model, grade validation, K-value validation against design speed thresholds. No math formulas, no IFC creation, no `bpy`.
- **Tool** (`tool/alignment.py`): All implementation — parabolic arc math, K-value computation, grade calculations, alignment API calls, coordinate transforms, Blender mesh operations.
- **UI** (`bim/module/alignment/`): Operators (`CIVIL_OT_add_pvi`, `CIVIL_OT_edit_pvi`, etc.), panels, props, decorators, profile view overlay.

**Estimated scope:** 2,000–3,500 lines

---

### Section 3: Cross-Section Profiles

**Status:** Not yet implemented. Deep research complete (see Corridor_Generation_Deep_Research.md and IFC_Roadway_Templates_Assemblies_Reference.md).

#### 3.1 Component-Based Assembly System
- Assembly = ordered collection of components (like Civil 3D Assembly or OpenRoads Template)
- Components attach left-to-right from centerline outward
- Each component: list of 2D points (offset, elevation relative to attachment point) with links between points
- Component types:
  - **Lane** — traveled way surface with width, cross slope, pavement depth
  - **Shoulder** — paved or gravel shoulder with width and slope
  - **Curb** — vertical or mountable curb geometry (curb height, gutter width)
  - **Ditch** — trapezoidal or V-ditch (bottom width, side slopes, depth)
  - **Slope** — open-ended component extending to existing ground (cut/fill slopes, max offset) — *basic version in core; full daylight in stretch*
  - **Custom** — user-defined point geometry for non-standard sections

#### 3.2 Tag-Based Point Identification
- Every point in a cross-section has a tag for tracking across stations
- Standard tag mapping to industry point codes:

| Tag | Description | Civil 3D Equivalent |
|-----|-------------|-------------------|
| CL | Centerline | Crown |
| ETW_L / ETW_R | Edge of traveled way | ETW |
| EPS_L / EPS_R | Edge of pavement | EPS |
| BC_L / BC_R | Back of curb | Back |
| FL_L / FL_R | Flowline / gutter | Flowline |
| HG_L / HG_R | Hinge point (shoulder break) | Hinge |
| DL_L / DL_R | Daylight point | Daylight |

- Tags list has N+1 entries for N segments (tags identify break *points*, not segments). Enforced by `CorrespondingTags` WHERE rule on `IfcOpenCrossProfileDef`.
- Tags enable `IfcSectionedSolidHorizontal` interpolation between stations (geometry engine interpolates between profile points with matching tags)
- Tags maintain consistency when profiles vary (widening, superelevation)

#### 3.3 IFC Representation (Dual-Path)
- **Path A — IFC compliance:** Create `IfcOpenCrossProfileDef` entities with `Widths`, `Slopes`, and `Tags` attributes. Set `HorizontalWidths=True` as standard for road cross-sections (widths measured horizontally, not along slope). Slopes are stored as dimensionless ratios (rise/run) in IFC, not percentages — UI displays percentages with conversion at the Tool layer boundary. These are stored in the IFC file for standards compliance and interoperability.
- **Path B — Blender visualization:** Self-compute break point geometry from component parameters to generate Blender meshes. Required because the IfcOpenShell geometry engine cannot currently render `IfcOpenCrossProfileDef` (upstream Issue #7338 work will eventually close this gap).
- Both paths stay in sync: Core decides when sync is needed and which path triggered the change; Tool executes each path independently (IFC entity write and Blender mesh generation).
- **Constraint:** Cannot mix `IfcOpenCrossProfileDef` and `IfcArbitraryClosedProfileDef` in the same `IfcSectionedSolidHorizontal` (`SectionsSameType` WHERE rule). All profiles in a corridor solid must use the same entity type.
- **Deserialization:** Read `IfcOpenCrossProfileDef` from IFC back into editable component list (analogous to `extract_pis_from_segments()` for alignments). Required for file reopen and round-trip editing.

#### 3.4 Assembly Editor UI
- UIList-based panel (`CIVIL_UL_assembly_components`) for adding/removing/reordering components. Reorder via up/down arrow operators (Blender UIList has no native drag-and-drop).
- Per-component parameter editing (width, slope, depth, etc.)
- Cross-section editor operates in a separate 2D window (e.g., Image Editor area), not as a 3D viewport overlay. This simplifies the coordinate system to pure 2D offset/elevation space.
- Visual cross-section preview rendered to `bpy.data.images` pixel buffer, displayed via `layout.template_image()` in the panel.
- Component library panel with standard assemblies

#### 3.5 Component Library
- Pre-built AASHTO-based templates:
  - Rural two-lane road (12' lanes, 6' shoulders, 3:1 fill slopes)
  - Urban arterial with curb and gutter
  - Interstate section (12' lanes, 10' outside shoulder, 4' inside shoulder)
  - Simple gravel road
- Users can save custom assemblies as reusable library entries

#### 3.6 Multi-Layer Pavement Definition
- Surface course, base course, subbase as separate layers within lane/shoulder components
- Each layer: thickness, material assignment
- IFC material association via `IfcMaterialProfileSet`
- Enables pavement quantity takeoff by material type

#### Architecture
- **Core** (`core/cross_section.py`): Assembly/component data model, tag management, constraint validation, dual-path sync orchestration
- **Tool** (`tool/cross_section.py`): `IfcOpenCrossProfileDef` creation and deserialization, break point geometry computation, Blender mesh generation, material assignment
- **UI** (`bim/module/cross_section/`): Assembly editor operators/panels, component library, visual preview. Panels integrate into Bonsai Properties editor CIVIL tab as `BIM_PT_tab_cross_section`, sibling to existing `BIM_PT_tab_horizontal_alignment`.
- Key IFC relationships: `IfcRelDeclares` (reusable profile definitions at project level), `IfcRelAssociatesMaterial` (pavement material associations)

**Estimated scope:** 2,000–2,500 lines

---

### Section 4: Corridor Modeling

**Status:** Not yet implemented. Architecture validated against Civil 3D and OpenRoads patterns.

#### 4.0 Key Prerequisite: `evaluate_alignment_at_station()`
- Returns 3D position, tangent vector, and normal frame at any station along the combined horizontal+vertical alignment
- This is the most critical new Tool function — Sections 3–7 all depend on it for cross-section placement, corridor mesh, terrain sampling, and daylight calculations
- Belongs in `tool/alignment.py`; called by Core orchestration functions

#### 4.1 Corridor Creation
- Corridor = alignment (directrix) + assembly + station range
- Created via Bonsai Add Element dialog or dedicated operator
- IFC representation: `IfcRoad` with `IfcFacilityPart` children (ROADSEGMENT, ROADSIDE)

#### 4.2 Station Management
- Adaptive station density calculation:

| Location | Default Interval | Rationale |
|----------|-----------------|-----------|
| Tangent sections | 10m | Sufficient for straight segments |
| Horizontal curves | 5m | Smooth curve representation |
| Spiral transitions | 5m | Capture varying curvature |
| Vertical curves | At PVI + quarter points | Capture sag/crest shape |
| Geometry points | Always included | PC, PT, PVC, PVT, etc. |
| Superelevation critical | Always included | Transition points (future) |

- Users can override interval and add manual stations

#### 4.3 Cross-Section Placement
- At each station: evaluate assembly, compute break points, create profile
- Profile orientation from `IfcAxis2PlacementLinear` (normal to alignment tangent)
- Store as `IfcOpenCrossProfileDef` with consistent tag structure (cannot mix with `IfcArbitraryClosedProfileDef` per `SectionsSameType` rule)

#### 4.4 3D Solid Generation
- `IfcSectionedSolidHorizontal` entity:
  - `Directrix`: 3D alignment curve (from Section 2.4)
  - `CrossSections`: Profile list at each station
  - `CrossSectionPositions`: `IfcAxis2PlacementLinear` at each station
- Tag-based interpolation between stations for smooth transitions
- All profiles must have consistent `ProfileType` and tag structure

#### 4.5 Blender 3D Mesh Preview
- Generate Blender mesh from corridor solid for viewport visualization
- Use dual-path approach: attempt geometry engine rendering; fall back to self-computed mesh
- Mesh updates on corridor rebuild (alignment edit, profile edit, assembly edit)

#### 4.6 Region System
- Different assemblies over different station ranges within one corridor
- **Tag structure must be held constant across the entire corridor.** Region transitions (lane drops, median changes) use zero-width segments to maintain consistent tag count rather than changing the number of segments. This is required by the `IfcSectionedSolidHorizontal` tag-based interpolation scheme (buildingSMART informal proposition: consecutive profiles must have same point/edge count).
- Smooth transitions between regions interpolated over user-specified length using zero-width tapers
- Enables lane drops, median changes, section type changes along route

#### 4.7 Corridor Rebuild
- Parametric update when any input changes:
  - Alignment geometry edited → rebuild
  - Vertical profile edited → rebuild
  - Assembly modified → rebuild
  - Station interval changed → rebuild
- **Core scope: full corridor rebuild on any input change.** Incremental rebuild (only regenerate affected stations) is a future optimization.
- Corridor rebuild is an **explicit operator** (`CIVIL_OT_rebuild_corridor`) invoked by the user, with a dirty-flag indicator (`corridor_is_dirty`) when inputs have changed. NOT a Blender depsgraph handler — depsgraph handlers are unsuitable: too slow for IFC operations, no undo support, fire on irrelevant scene events.
- Use `wm.progress_begin/update/end` for rebuild progress feedback in the Blender header.

#### Architecture
- **Core** (`core/corridor.py`): Corridor/region data model, station management logic, rebuild orchestration, tag consistency validation
- **Tool** (`tool/corridor.py`): `IfcSectionedSolidHorizontal` creation, mesh generation (loft between station profiles), `IfcRoad`/`IfcFacilityPart` spatial structure, `evaluate_alignment_at_station()` (in `tool/alignment.py`)
- **UI** (`bim/module/corridor/`): Corridor creation operators, station control panels, rebuild trigger operator with dirty-flag notification. Panels integrate into Bonsai Properties editor CIVIL tab as `BIM_PT_tab_corridor`, sibling to existing alignment tabs.
- Key IFC relationships: `IfcRelContainedInSpatialStructure` (corridor elements in road), `IfcRelAggregates` (facility parts under road), `IfcRelPositions` (referents along alignment)

**Estimated scope:** 2,000–3,000 lines

---

## STRETCH GOALS (Priority Order)

### Stretch 1 — Section 5: Parametric Controls

**Prerequisite for:** Superelevation (Stretch 2)
**Priority:** First stretch goal

#### 5.1 Cross-Slope Control
- Set normal crown slope per component (e.g., 2% for pavement)
- Override slope at specific stations or station ranges
- Foundation for superelevation rotation

#### 5.2 Width Control
- Vary component width over station ranges (lane widening for turn lanes, tapers)
- Linear interpolation between start and end values
- Updates tag positions accordingly

#### 5.3 Point Constraints (Single-Station Overrides)
- Override any component parameter at a specific station
- Example: set shoulder width to 4.2m at station 300 for bus pullout

#### 5.4 Range Constraints (Interpolated Transitions)
- Smoothly interpolate parameter changes between two stations
- Example: widen lane from 3.6m to 4.2m over stations 200–300
- Linear interpolation; cubic/spline interpolation as future enhancement

#### 5.5 Target System
- **Surface targets:** Component endpoint extends to intersect a target surface (existing ground) — foundation for daylight grading
- **Alignment targets:** Component width controlled by offset alignment or feature line
- **Elevation targets:** Component point elevation tied to a profile

**Estimated scope:** 800–1,200 lines

---

### Stretch 2 — Section 6: Superelevation

**Prerequisite:** Parametric controls (Stretch 1)
**Priority:** Second stretch goal

#### 6.1 Superelevation Schedule
- Define superelevation events along alignment (station, rate, side, transition type)
- IFC representation: `IfcReferent` with `PredefinedType=SUPERELEVATIONEVENT` (positioned along alignment via `IfcRelPositions`)
- Property set: `Pset_Superelevation` (SuperElevation, Side, Transition)

#### 6.2 Transition Calculation
- Tangent runout (normal crown → zero cross slope)
- Superelevation runoff (zero cross slope → full superelevation)
- Linear transition distribution (standard AASHTO method)

#### 6.3 Design Tables
- AASHTO emax tables by design speed and curve radius
- Auto-calculate superelevation rate from horizontal curve geometry
- User override capability

#### 6.4 Cross-Section Rotation
- At each corridor station, rotate cross-section based on superelevation schedule
- Rotation about centerline (or specified rotation axis)
- Affects profile geometry in `IfcSectionedSolidHorizontal`
- Uses `IfcDerivedProfileDef` with rotation transformation, or explicit rotated coordinates

**Estimated scope:** 1,000–1,500 lines

---

### Stretch 3 — Section 7: Grading & Earthwork

**Prerequisite:** Basic corridor (Core Section 4) + parametric targets (Stretch 1, Section 5.5)
**Priority:** Third stretch goal

#### 7.1 End Conditions (Daylight to Existing Ground)
- Slope component extends from last pavement/shoulder point toward existing ground
- At each station: raycast from slope start point at specified slope ratio until intersecting terrain mesh
- Separate cut slope and fill slope ratios (e.g., 2:1 cut, 3:1 fill)
- Automatic cut/fill determination: if design surface > existing ground → fill; if below → cut
- Terrain intersection uses Blender's `BVHTree` raycasting against a user-designated existing ground mesh

#### 7.2 Daylight Controls
- Maximum daylight offset (safety limit to prevent infinite slopes in flat terrain)
- Minimum daylight offset
- Rounding at top of cut / toe of fill (optional)

#### 7.3 Benching
- Stepped cut slopes for tall embankments (e.g., bench every 6m of height)
- Bench width parameter
- Back slope between benches

#### 7.4 IFC Earthwork Entities
- `IfcEarthworksCut` (PredefinedType: CUT — the semantically correct type for road cut slopes; EXCAVATION is for foundation work)
- `IfcEarthworksFill` (PredefinedTypes: SUBGRADE, EMBANKMENT, SLOPEFILL, SUBGRADEBED)
- Contained within `IfcRoad` spatial structure
- Material associations for different fill types

#### 7.5 Earthwork Quantities
- Average end area method for cut/fill volume calculation between stations
- Cut volume, fill volume, net volume per station range
- Cumulative volume reporting

#### 7.6 Mass Haul Diagram
- Cumulative cut/fill plotted against station
- Identifies balance points, haul distances, borrow/waste locations
- 2D visualization (similar to profile view overlay)

**Estimated scope:** 1,500–2,500 lines

---

### Stretch 4 — Section 8: Terrain / Existing Ground Support

> **Note:** Sections 8.1 and 8.2 have been moved to **core scope** (see Section 2.2 dependency). The profile view overlay requires terrain display to be a useful engineering tool. Sections 8.3–8.4 remain stretch goals.

#### 8.1 Terrain Designation — CORE SCOPE
- Operator to designate any Blender mesh as "existing ground" for the project
- Store reference in IFC (linked to `IfcGeomodel` or `IfcSite` geometry)

#### 8.2 Terrain Profile Extraction — CORE SCOPE
- Sample terrain mesh elevations along alignment centerline for profile view display
- Uses alignment stationing to generate station/elevation pairs
- Displayed as filled polygon in profile view overlay

#### 8.3 Terrain Sampling at Cross-Section Stations
- At each corridor station, sample terrain at multiple offsets from centerline
- Provides existing ground profile for:
  - Daylight calculations (Section 7.1)
  - Cross-section view overlay (Section 9.2)
  - Cut/fill determination (Section 7.1)

#### 8.4 IFC Representation
- `IfcGeomodel` for geological/terrain models
- `IfcTriangulatedFaceSet` for mesh geometry
- Linked to `IfcSite` in spatial structure

**Estimated scope:** 500–800 lines

---

### Stretch 5 — Section 9: Visualization & Annotation

#### 9.1 Profile View Enhancements
- Grade percentage labels between PVIs
- K-value indicators on vertical curves
- Sight distance visualization (future)
- Design speed notation

#### 9.2 Cross-Section View
- View any station's cross-section in a 2D overlay
- Show design cross-section with component labels
- Overlay existing ground profile at that station
- Show cut/fill regions (colored shading)
- Navigate between stations (next/previous)

#### 9.3 Plan View Annotation
- Stationing tick marks along alignment in 3D viewport
- Curve data labels (radius, length, PI station)
- Alignment name/description labels

#### 9.4 Offset Labels
- Cross-section offset and elevation annotations
- Slope annotations (% or ratio)
- Component width labels

**Estimated scope:** 1,000–1,500 lines

---

### Stretch 6 — Section 10: Import / Export / Interoperability

#### 10.1 LandXML Import
- Import horizontal and vertical alignments from LandXML files
- Map to `IfcAlignment` entities via `ifcopenshell.api.alignment`
- Enables migration from Civil 3D/OpenRoads projects

#### 10.2 LandXML Export
- Export alignments and profiles to LandXML format
- Enables sharing with Civil 3D/OpenRoads users

#### 10.3 buildingSMART IFC Validation
- Automated validation of generated IFC files against buildingSMART checker
- Report validation errors/warnings in Bonsai UI

**Estimated scope:** 800–1,200 lines

---

### Stretch 7 — Section 11: Design Validation

#### 11.1 Stopping Sight Distance
- Horizontal sight distance (line of sight around curves)
- Vertical sight distance (over crest curves, through sag curves)
- Check against AASHTO tables by design speed

#### 11.2 Geometric Design Checks
- Minimum curve radius by design speed
- Maximum gradient check
- K-value validation for crest and sag curves
- Minimum tangent length between reverse curves

#### 11.3 Cross-Slope Validation
- Maximum superelevation rate check
- Cross-slope range validation (min/max by surface type)
- Rollover rate check at pavement edges

**Estimated scope:** 800–1,200 lines

---

## Total Estimated Scope

| Section | Category | Est. Lines | Status |
|---------|----------|-----------|--------|
| 1. Horizontal Alignment | Core | ~500 remaining | ~90% complete |
| 2. Vertical Alignment | Core | 2,000–3,500 | Not started |
| 3. Cross-Section Profiles | Core | 2,000–2,500 | Not started |
| 4. Corridor Modeling | Core | 2,000–3,000 | Not started |
| 8.1–8.2 Terrain (Profile Support) | Core | 300–500 | Not started |
| **Core Total** | | **6,800–10,000** | |
| 5. Parametric Controls | Stretch 1 | 800–1,200 | |
| 6. Superelevation | Stretch 2 | 1,000–1,500 | |
| 7. Grading & Earthwork | Stretch 3 | 1,500–2,500 | |
| 8.3–8.4 Terrain (Advanced) | Stretch 4 | 200–400 | |
| 9. Visualization | Stretch 5 | 1,000–1,500 | |
| 10. Import/Export | Stretch 6 | 800–1,200 | |
| 11. Design Validation | Stretch 7 | 800–1,200 | |
| **Stretch Total** | | **6,100–9,500** | |
| **Grand Total** | | **12,900–19,500** | |

*Line estimates are production code only. Test code (~155 tests across Core/Tool/Operator layers) is tracked separately in the Testing Strategy section below.*

---

## Development Methodology

- **Architecture:** All code follows Bonsai's three-layer pattern (Core/Tool/UI) with `tool.Ifc.Operator` inheritance
- **IFC Backend:** `ifcopenshell.api.alignment` for alignment entities; direct `ifcopenshell` calls for cross-sections and corridor solids
- **Formatting:** Black + ruff, per Bonsai conventions
- **Tooling:** Claude Code for accelerated feature development within test-driven workflows; Git with interactive rebase for clean PR history
- **PR Discipline:** Squash commits into focused PRs ≤4,000 lines for upstream review by Dion Moult
- **Validation:** buildingSMART International IFC validation checker for all generated files

### Testing Strategy

**155 planned tests** across Core Sections 2–4:

| Category | Section 2 | Section 3 | Section 4 | Total |
|----------|-----------|-----------|-----------|-------|
| Core tests (pure Python, no Blender) | 18 | 16 | 16 | **50** |
| Tool tests (Blender headless) | 12 | 10 | 8 | **30** |
| Operator tests (Blender headless) | 8 | 8 | 12 | **28** |
| Validation tests (buildingSMART checker) | 3 | 2 | 2 | **7** |
| Edge case tests | 10 | 10 | 10 | **30** |
| Regression tests (corridor rebuild) | — | — | 10 | **10** |
| **Subtotal** | **51** | **46** | **58** | **155** |

**Test file structure** (following existing Bonsai conventions):
- `test/core/test_alignment.py` — existing (34 tests, horizontal + vertical)
- `test/core/test_cross_section.py` — new (Section 3)
- `test/core/test_corridor.py` — new (Section 4)
- `test/tool/test_alignment.py` — existing (135 tests + vertical additions)
- `test/tool/test_cross_section.py` — new (Section 3)
- `test/tool/test_corridor.py` — new (Section 4)
- `test/bim/module/alignment/test_alignment_operators.py` — existing (39 tests)
- `test/bim/module/cross_section/` — new (Section 3 operators)
- `test/bim/module/corridor/` — new (Section 4 operators + rebuild regression)

**Execution strategy:** Write all 50 core tests first (run in seconds, fast iteration). Then tool tests. Then operator/regression tests. Reusable fixtures build progressively: `ifc_empty` → `ifc_with_horizontal_alignment` → `ifc_with_vertical_alignment` → `ifc_with_assembly` → `ifc_with_corridor`. Estimated total suite runtime: ~5 minutes with Blender headless.

---

## IFC Entity Summary

| Feature Area | Primary IFC Entities |
|-------------|---------------------|
| Horizontal Alignment | `IfcAlignment`, `IfcAlignmentHorizontal`, `IfcAlignmentSegment` (LINE, CIRCULARARC, CLOTHOID) |
| Vertical Alignment | `IfcAlignmentVertical`, `IfcAlignmentSegment` (CONSTANTGRADIENT, PARABOLICARC) |
| 3D Alignment | `IfcGradientCurve` (combined horizontal + vertical, Axis/Curve3D representation) |
| Cross-Sections | `IfcOpenCrossProfileDef` (Widths, Slopes, Tags), `IfcArbitraryClosedProfileDef` |
| Corridor Solid | `IfcSectionedSolidHorizontal` (Directrix, CrossSections, CrossSectionPositions) |
| Road Spatial Structure | `IfcRoad`, `IfcFacilityPart` (ROADSEGMENT, ROADSIDE, TRAFFICLANE) |
| Pavement | `IfcPavement`, `IfcCourse`, `IfcMaterialProfileSet` |
| Earthwork | `IfcEarthworksCut` (CUT), `IfcEarthworksFill` (SUBGRADE, EMBANKMENT, SLOPEFILL, SUBGRADEBED) |
| Superelevation | `IfcReferent` (SUPERELEVATIONEVENT, WIDTHEVENT), `Pset_Superelevation` |
| IFC Relationships | `IfcRelNests`, `IfcRelContainedInSpatialStructure`, `IfcRelAggregates`, `IfcRelPositions`, `IfcRelDeclares`, `IfcRelAssociatesMaterial` |
| Terrain | `IfcGeomodel`, `IfcTriangulatedFaceSet` |
| Georeferencing | `IfcProjectedCRS`, `IfcMapConversion` (existing) |
| Stationing | `IfcReferent` (STATION) (existing) |

---

---

## Glossary

### Civil Engineering Terms
- **PI (Point of Intersection)** — the point where two tangent lines meet in a horizontal alignment; the input method for defining horizontal curves
- **PVI (Point of Vertical Intersection)** — the point where two grade lines meet in a vertical profile; the input method for defining vertical curves
- **PC / PT (Point of Curvature / Point of Tangency)** — the start and end of a horizontal circular curve
- **PVC / PVT (Point of Vertical Curvature / Point of Vertical Tangency)** — the start and end of a parabolic vertical curve
- **K-value** — the ratio of vertical curve length to the absolute algebraic grade difference (K = L / |g2 − g1|); a measure of curve sharpness used in sight distance calculations
- **Superelevation** — the banking of a roadway cross-section through a horizontal curve to counteract centrifugal force
- **Normal crown** — the standard cross-slope configuration of a road on tangent (straight) sections, typically two-way drainage at 2%
- **Tangent runout** — the transition length from normal crown to a flat (zero cross-slope) section; the first stage of superelevation transition
- **Superelevation runoff** — the transition length from flat to full superelevation; the second stage
- **emax** — the maximum superelevation rate permitted by design standard for a given design speed
- **Corridor** — a 3D model of a road or infrastructure feature generated by sweeping a cross-section assembly along an alignment
- **Assembly** — an ordered collection of cross-section components (lanes, shoulders, curbs, ditches, slopes) defining the transverse geometry of a road at a given station
- **Component** — a single element of an assembly defined by 2D geometry relative to its attachment point
- **Daylight point** — the point where a cut or fill slope intersects the existing ground surface
- **End condition** — the outermost component of an assembly (typically a slope) that extends to meet existing ground
- **Directrix** — the 3D alignment curve (horizontal + vertical) that defines the centerline path along which a corridor cross-section is swept
- **Rollover** — the algebraic difference in cross-slope between two adjacent pavement lanes; a driver comfort and drainage check
- **Average end area method** — a formula for computing earthwork volume between two stations by averaging their cross-sectional areas and multiplying by the distance
- **Balance point (mass haul)** — a station location where cumulative cut volume equals cumulative fill volume
- **Benching** — stepped cut slopes for tall embankments, consisting of alternating back slopes and horizontal catch benches

### IFC / BIM Terms
- **IFC 4.3** — the current buildingSMART Industry Foundation Classes standard; the first version with full infrastructure (road, railway, bridge) support
- **`IfcRelNests`** — IFC relationship entity for parent-child containment (e.g., nesting `IfcAlignmentVertical` inside `IfcAlignment`)
- **`IfcGradientCurve`** — IFC geometric curve combining horizontal and vertical alignment into a 3D directrix (Axis/Curve3D representation)
- **`IfcSectionedSolidHorizontal`** — IFC geometric entity representing a 3D solid defined by a directrix curve and a series of cross-section profiles at stations along it
- **`IfcOpenCrossProfileDef`** — IFC profile entity defining an open cross-section by lists of widths, slopes, and tag labels; the primary IFC representation for road cross-sections
- **`IfcAxis2PlacementLinear`** — IFC 4.3 placement entity that positions an object relative to a point on a linear element (used to orient cross-sections normal to the alignment)
- **`IfcFacilityPart`** — IFC spatial element representing a subdivision of a facility (e.g., ROADSEGMENT, ROADSIDE, TRAFFICLANE)
- **`IfcReferent`** — IFC entity for positioning events along an alignment (STATION, SUPERELEVATIONEVENT, WIDTHEVENT)
- **`Pset_*`** — IFC Property Set; a named collection of properties attached to an IFC object. Standard Psets are defined by buildingSMART; custom Psets are project-defined.
- **buildingSMART** — the international organization that develops and maintains the IFC standard

### Bonsai Architecture Terms
- **Core layer** — Bonsai's business logic layer; contains only orchestration, validation, and data model logic; no math, no IFC creation, no Blender API calls
- **Tool layer** — Bonsai's implementation layer; contains all math, IFC operations, Blender mesh operations, and coordinate transforms
- **UI layer** — Bonsai's presentation layer; contains Blender operators, panels, property groups, and viewport decorators
- **`tool.Ifc.Operator`** — Bonsai base class for operators that modify the IFC model; provides undo/redo wrapping and IFC file access; uses `_execute()` not `execute()`
- **GPU decorator** — a Blender mechanism for drawing lines, shapes, and text directly in the 3D viewport using the GPU shader API, without creating Blender mesh objects
- **PolylineOperator** — a Bonsai base class providing click-to-place point input with rubber-band preview and snapping behavior

### Terminology Disambiguation
- **"Vertical profile"** — the alignment elevation curve (station vs. elevation). Used in Section 2.
- **"Cross-section profile"** — the `IfcOpenCrossProfileDef` entity defining transverse road geometry. Used in Sections 3–4.
- **"Material profile"** — `IfcMaterialProfileSet` for pavement layer materials. Used in Section 3.6.
- **"Assembly"** — always refers to the ordered collection of cross-section components. Never "template."

---

## Diagrams (To Be Added)

1. **Corridor generation concept** — alignment + vertical profile + assembly → 3D solid (isometric sketch showing three inputs combining)
2. **Three-layer architecture** — Core / Tool / UI boxes with data flow arrows and forbidden dependencies labeled
3. **IFC entity relationship diagram** — `IfcAlignment` → `IfcRoad` hierarchy showing `IfcRelNests`, `IfcRelContainedInSpatialStructure`, and `IfcRelAggregates` connections
4. **Cross-section anatomy** — labeled component illustration showing tag positions (CL, ETW, EPS, BC, FL, HG, DL) on a typical two-lane road section
5. **User workflow diagram** — linear flow: create horizontal alignment → define vertical profile → build assembly → generate corridor → run earthwork → export IFC

---

*This outline serves as both the GSoC 2026 proposal foundation and the long-term Saikei Civil development roadmap.*

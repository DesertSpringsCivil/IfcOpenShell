# Civil 3D — Horizontal Alignment Function Map

> A "command tree" / feature map of Autodesk Civil 3D's horizontal-alignment
> workflow, captured to inform the Saikei Civil (Bonsai) alignment UX.
> Structure mirrors Civil 3D's ribbon → dialog → toolbar → editor flow.
> Compiled May 2026. Sources listed at the bottom.

---

## 0. Entry Points (where the user starts)

```
Home tab → Create Design panel → Alignment ▾ (dropdown)
   ├─ Alignment Creation Tools…        ← draw a new alignment by layout
   ├─ Create Alignment from Objects    ← convert existing CAD geometry
   ├─ Create Best Fit Alignment        ← regress from points/entities
   ├─ Create Alignment from Corridor   ← extract from a built corridor
   ├─ Create Offset Alignment          ← parallel offset of a parent
   └─ Create Widening                  ← localized offset widening
```
Alternatives: right-click an existing alignment → **Geometry Editor**
(re-opens the layout toolbar); or Toolspace **Prospector** → Alignments
(manage, copy, delete, reference).

---

## 1. Alignment Creation Tools  (draw a NEW alignment by layout)

### 1.1 Step 1 — "Create Alignment – Layout" dialog
- **General tab**
  - Name (with optional name template / counter)
  - Type: **Centerline · Offset · Curb Return · Rail · Miscellaneous**
  - Description
  - Starting Station
  - Site assignment (Siteless is typical for road centerlines)
  - Alignment Style (visual)
  - Alignment Label Set (station/geometry labeling)
- **Design Criteria tab**
  - Starting Design Speed
  - Use criteria-based design (on/off)
  - Use Design Criteria File (.xml — AASHTO etc.; min radius vs. speed)
  - Use Design Check Set (custom pass/fail rules)

### 1.2 Step 2 — Alignment Layout Tools toolbar
Once the dialog is accepted, the floating **Alignment Layout Tools**
toolbar opens (titled with the active alignment name). It is the heart of
"by layout" creation. Commands below, grouped by flyout.

```
ALIGNMENT LAYOUT TOOLS TOOLBAR
│
├─ ▾ Tangent-Tangent (PI-method, "draw the centerline")
│     ├─ Tangent-Tangent (No Curves)        ← straight PIs only
│     └─ Tangent-Tangent (With Curves)      ← auto-insert curves at PIs
│                                              (uses Curve & Spiral Settings)
│
├─ ▾ Fixed Lines  (geometry pinned to coordinates; not constrained to neighbors)
│     ├─ Fixed Line (Two Points)
│     ├─ Fixed Line (From Curve End, Through Point)
│     └─ Fixed Line – Best Fit (from points/entities/screen picks)
│
├─ ▾ Floating Lines  (depend on ONE neighbor; maintain tangency to it)
│     ├─ Floating Line (From Curve, Through Point)
│     └─ Floating Line (From Curve End, Length)
│
├─ ▾ Free Lines  (depend on TWO neighbors)
│     └─ Free Line (Between Two Curves)
│
├─ ▾ Fixed Curves  (pinned; no tangency enforced)
│     ├─ Fixed Curve (Three Points)
│     ├─ Fixed Curve (Two Points & Direction at Start)
│     ├─ Fixed Curve (Two Points & Radius)
│     ├─ Fixed Curve (Center Point & Radius)
│     ├─ Fixed Curve (From Entity End, Through Point)
│     └─ Fixed Curve – Best Fit
│
├─ ▾ Floating Curves  (tangent to one neighbor; "free end" floats)
│     ├─ Floating Curve (From Entity, Radius, Through Point)
│     ├─ Floating Curve (From Entity, Through Point)
│     ├─ Floating Curve (From Entity End, Radius, Length)
│     └─ Floating Curve – Best Fit
│
├─ ▾ Free Curves  (fillet between two neighbors; tangent to both)
│     ├─ Free Curve Fillet (Between Two Entities, Radius)
│     ├─ Free Curve Fillet (Between Two Entities, Through Point)
│     ├─ Free Compound Curve (Between Two Entities)
│     ├─ Free Reverse Curve (Between Two Entities)
│     └─ Free Curve – Best Fit
│
├─ ▾ Fixed Spirals
│     └─ Fixed Spiral (From Curve, Length / Radius)
│
├─ ▾ Floating Spirals
│     ├─ Floating Spiral (From Curve, Length / Radius)
│     └─ Floating Spiral (From Curve, Radius, Through Point)
│
├─ ▾ Free Spiral Groups  (transition packages between two entities)
│     ├─ Free Spiral-Curve-Spiral (Between Two Entities)   ← the workhorse
│     ├─ Free Spiral-Line-Spiral
│     ├─ Free Spiral-Spiral (compound, between two curves)
│     ├─ Free Reverse Spiral-Spiral
│     ├─ Free Spiral-Spiral-Curve-Spiral-Spiral
│     └─ Free Compound Spiral-Spiral
│
├─ ── Conversion ──
│     └─ Convert AutoCAD Line and Arc  (pull dumb CAD entities into layout)
│
├─ ── PI Editing ──
│     ├─ Insert PI
│     ├─ Delete PI
│     └─ Break-Apart PI at Location
│
├─ ── Sub-entity Editing ──
│     ├─ Pick / Select Sub-entity
│     ├─ Delete Sub-entity
│     └─ Reverse Sub-entity Direction
│
├─ ── Editors / Settings ──
│     ├─ Sub-entity Editor          (parameters of the picked component)
│     ├─ Alignment Grid View        (tabular list of all sub-entities)
│     ├─ Curve & Spiral Settings    (defaults for Tangent-Tangent w/ Curves)
│     └─ Undo / Redo
```

**The fixed / floating / free mental model** (worth emulating — it is
Civil 3D's defining concept and maps cleanly to constraint solving):
- **Fixed** — geometry fully defined by its own coordinates; ignores neighbors.
- **Floating** — defined partly by ONE adjacent entity; stays tangent to it.
- **Free** — defined entirely by TWO adjacent entities it sits between
  (a fillet); moves when either neighbor moves.

---

## 2. Create Alignment from Objects  (convert existing CAD geometry)

```
Create Alignment from Objects
   ├─ 1. Select line / arc / polyline (or chain) on screen
   ├─ 2. Confirm/flip alignment direction (arrow prompt)
   └─ 3. "Create Alignment from Objects" dialog
         ├─ General tab     (Name, Type, Site, Style, Label Set — as §1.1)
         ├─ Design Criteria tab  (speed, criteria file, check set)
         └─ Conversion options:
               ├─ Add curves between tangents (radius)
               ├─ Erase existing entities (consume source geometry)
               └─ (polyline arcs become alignment curves)
```
Caveat surfaced in the docs: CAD primitives are "dumb" — no tangency
rules — so objects-derived alignments are less robust than layout-built
ones (gaps cause stationing/targeting issues). Layout is preferred.

---

## 3. Create Best Fit Alignment  (regression)

```
Create Best Fit Alignment
   └─ Input source:
         ├─ From COGO Points
         ├─ From AutoCAD Points
         ├─ From Entities (lines/arcs/polylines)
         └─ By Clicking On Screen
   → Regression panorama: tune tangent/curve fit, see deviation,
     then output an alignment.
```

---

## 4. Create Alignment from Corridor

```
Create from Corridor
   └─ Pick a corridor feature line / link → bake to an alignment
      (e.g., extract an edge-of-pavement as its own alignment).
```

---

## 5. Create Offset Alignment  (parametric child of a parent)

```
Create Offset Alignment
   ├─ Select parent (centerline) alignment
   ├─ Dialog:
   │     ├─ Number of offsets, Left / Right
   │     ├─ Incremental offset distance(s)
   │     └─ Name template, Style, Criteria
   └─ Result: dynamically linked offset that updates with the parent.
        └─ Add Widening to this offset (see §6)
```

---

## 6. Create Widening  (localized offset variation)

```
Create Widening   (operates on an offset alignment)
   ├─ Select offset alignment + region (station range)
   ├─ Widening parameters:
   │     ├─ Widening length / offset added
   │     └─ Transition type: Linear · Curve · Spiral-Line-Spiral · etc.
   └─ Used for turn lanes, bus bays, parking flares.
```

---

## 7. Editing an Existing Alignment  (post-creation)

```
Select alignment → Alignment contextual ribbon tab
   ├─ Geometry Editor              → re-opens Layout Tools toolbar (§1.2)
   ├─ Alignment Grid View          → tabular sub-entity editor
   ├─ Alignment Properties
   │     ├─ Station Control         (set/override starting station)
   │     ├─ Station Equations       (gaps/overlaps in stationing)
   │     ├─ Design Criteria         (design speeds by station, criteria file)
   │     ├─ Masking                 (hide station ranges)
   │     └─ Point of Intersection   (PI table)
   ├─ Superelevation
   │     ├─ Calculate / Edit Superelevation  (uses design speed + criteria)
   │     └─ Superelevation Tabular Editor (Panorama)
   ├─ Add Labels                    (station/geometry/tag label sets)
   ├─ Reverse Direction
   ├─ Offset / Widening (as above)
   └─ Grip editing in plan          (drag PIs, edit radii via grips)
```

---

## 8. Cross-cutting Settings & Outputs (context for the meeting)

- **Design Criteria File (.xml)** — speed→min-radius/superelevation tables
  (AASHTO, agency standards). Drives pass/fail and superelevation.
- **Design Check Set** — user-authored geometric rules (e.g., min tangent
  length) that flag violations live.
- **Styles & Label Sets** — visual + annotation; separate from geometry.
- **Stationing** — starting station, station equations, station labels.
- **Downstream consumers** — Profiles, Corridors, Sample Lines/Sections,
  Offset/Widening, Superelevation all reference the alignment.

---

## 9. Distilled "MVP path" for Saikei (my read)

What Civil 3D users actually reach for 90% of the time, in priority order:
1. **Alignment Creation Tools → Tangent-Tangent (With Curves)** — the PI
   method. (Saikei already does this:
   `layout_horizontal_alignment_by_pi_method`.)
2. **Create from Objects** — convert a polyline/line chain. (Maps to your
   "Create from object" branch + CSV import.)
3. **Fixed/Floating/Free constraint model** — the differentiator if you
   want true parametric editing later (spiral-curve-spiral transitions).
4. **Grid View / Sub-entity editor** — tabular radius/length editing.
   (Saikei has PI edit mode (G key); a grid view is the natural next step.)
5. **Offset Alignment** — parametric children. Deferrable.
6. **Superelevation / Design Criteria** — rail/road-specific; later phase.

Items 4–6 are where IFC 4.3's `IfcAlignment` ⊃ `IfcAlignmentHorizontal`
⊃ segments (LINE / CIRCULARARC / CLOTHOID) line up almost 1:1 with the
fixed/floating/free + spiral vocabulary — worth raising with Dion.

---

## 10. Gap Table — Civil 3D command → Saikei status

Status key: ✅ Done · 🟡 Partial · ⬜ Not started · ➖ N/A (no Bonsai equivalent yet)
Saikei evidence cited from `bim/module/alignment/operator.py` and `tool/alignment.py`.

### Creation entry points
| Civil 3D command | Saikei status | Saikei equivalent / notes |
|---|---|---|
| Alignment Creation Tools (by layout) | ✅ | `CIVIL_OT_create_alignment_by_pis` / `_by_pi`; `tool.layout_by_pi_method` |
| Tangent-Tangent (With Curves) — PI method | ✅ | core path; radii applied per PI via `layout_horizontal_alignment_by_pi_method` |
| Tangent-Tangent (No Curves) | 🟡 | achievable via PI method with zero/omitted radii; not a distinct command |
| Create Alignment from Objects (CAD geom) | 🟡 | CSV import only (`CIVIL_OT_import_alignment_csv`); no "convert selected Blender curve/polyline" yet |
| Create Best Fit Alignment | ⬜ | no regression-from-points tool |
| Create Alignment from Corridor | ➖ | no corridor feature in Bonsai |
| Create Offset Alignment | ⬜ | parametric offset child not implemented |
| Create Widening | ⬜ | depends on offset alignments |

### Layout toolbar — geometry primitives
| Civil 3D command | Saikei status | Notes |
|---|---|---|
| Fixed / Floating / Free **lines** | ⬜ | only PI-method tangents; no constraint-based sub-entities |
| Fixed / Floating / Free **curves** (incl. compound, reverse) | 🟡 | circular curves only, inserted at PIs; not independently constrained |
| **Spirals** (fixed/floating/free, S-C-S groups) | ⬜ | IFC 4.3 supports CLOTHOID; Saikei layout does circular arcs only |
| Best-Fit sub-entities (line/curve) | ⬜ | — |
| Convert AutoCAD Line/Arc into layout | 🟡 | CSV path is the only ingest; no live entity conversion |

### PI & sub-entity editing
| Civil 3D command | Saikei status | Notes |
|---|---|---|
| Insert PI | ✅ | `CIVIL_OT_add_pi` |
| Delete PI | ✅ | `CIVIL_OT_remove_pi` |
| Pick PI from screen | ✅ | `CIVIL_OT_pick_pi_from_viewport` (modal PolylineOperator) |
| Grip-edit PIs in plan | ✅ | `CIVIL_OT_enter_pi_edit_mode` (G key) |
| Recalculate / clear PIs | ✅ | `CIVIL_OT_recalculate_pis`, `_clear_pis` |
| Pick / Delete / Reverse **sub-entity** | ⬜ | no component-level selection model |
| Sub-entity parameter editor | 🟡 | PI radii editable; no per-segment parameter panel |
| Alignment **Grid View** (tabular) | ⬜ | natural next step after PI edit mode |

### Stationing, properties, analysis
| Civil 3D command | Saikei status | Notes |
|---|---|---|
| Starting Station / Station Control | ✅ | `create_alignment(start_station=…)`; `CIVIL_OT_add_stationing_referent` |
| Station labels / referents | 🟡 | referent placement exists; full label sets not built out |
| Segment naming | ✅ | `CIVIL_OT_name_segments` |
| Station Equations | ⬜ | — |
| Reverse Direction | ⬜ | — |
| Design Criteria File (speed→radius, AASHTO) | ⬜ | — |
| Design Check Set (pass/fail rules) | ⬜ | — |
| Superelevation (calc + tabular editor) | ⬜ | road/rail-specific; later phase |
| Masking | ⬜ | — |

### Adjacent axes (context, not horizontal)
| Civil 3D command | Saikei status | Notes |
|---|---|---|
| Vertical alignment (profile / PVIs) | 🟡 **in progress** | `CIVIL_OT_add_pvi`, `_add_vertical_to_alignment`, `_enter_pvi_edit_mode`; `tool.layout_vertical_by_pvi_method` present |
| Styles & Label Sets (visual/annotation) | 🟡 | segment visualization + decorators exist; no user-facing style/label-set system |
| Profiles / Corridors / Sections | ⬜ | out of current scope |

### Scorecard (horizontal only)
- ✅ Done: **9** — PI-method creation, PI add/remove/pick/grip-edit/recalc/clear, start station, segment naming.
- 🟡 Partial: **7** — tangent-only, from-objects (CSV), curves-at-PI, convert-entity, sub-entity params, station labels, styles.
- ⬜ Not started: **15** — best-fit, offset, widening, constraint-based lines/curves, spirals, sub-entity model, grid view, station equations, reverse, design criteria, design checks, superelevation, masking.

**One-line takeaway for Dion:** Saikei has the *PI-method spine* of Civil 3D's
alignment workflow solid (create + interactively edit by PI), plus vertical now
underway. The biggest deltas are (1) **spirals/clothoids** — supported by IFC
4.3 but not yet authored, and (2) the **fixed/floating/free constraint model +
grid view**, which is what turns "draw a centerline" into "parametrically edit
geometry." Those two are the highest-leverage next targets.

---

## Sources
- [Creating Alignments (Autodesk Help)](https://help.autodesk.com/view/CIV3D/2024/ENU/?guid=GUID-9913484D-A0D8-4B2C-A62D-536E73DF368E)
- [Alignment Layout Tools (Autodesk Help)](https://help.autodesk.com/view/CIV3D/2024/ENU/?guid=GUID-1481F228-A59C-427A-A4B0-B83CA74A401E)
- [To Create an Alignment Using the Alignment Layout Tools](https://help.autodesk.com/view/CIV3D/2024/ENU/?guid=GUID-3C25BCF3-3693-4CA2-84E6-0D980974B763)
- [To Create an Alignment From Graphic Entities](https://help.autodesk.com/view/CIV3D/2024/ENU/?guid=GUID-7D245A7F-0D27-4051-B4E6-B465123CEF29)
- [To Create an Alignment by Best Fit](https://help.autodesk.com/view/CIV3D/2024/ENU/?guid=GUID-EF036075-36E4-4E17-A2EB-D33D7876071E)
- [Civil 3D Alignment by Layout — Creation Tools (InfraTech Civil)](https://www.infratechcivil.com/pages/civil-3d-alignment-by-layout-alignment-creation-tools)
- [Civil 3D Alignment from Objects (InfraTech Civil)](https://www.infratechcivil.com/pages/civil-3d-alignment-from-objects)
- [Alignment lines and curves (WisDOT C3D KB)](https://c3dkb.dot.wi.gov/Content/c3d/ali/ali-lin-crv.htm)
- [Offset alignments and widenings (WisDOT C3D KB)](https://c3dkb.dot.wi.gov/Content/c3d/ali/ali-offst-widen.htm)
- [Create Alignment from Objects Dialog Box (Autodesk KB)](https://knowledge.autodesk.com/support/civil-3d/learn-explore/caas/CloudHelp/cloudhelp/2021/ENU/Civil3D-UserGuide/files/GUID-76AC46F4-CA7E-406D-B624-C6CDEE904A76-htm.html)
- [Design Criteria Tab — Create Alignment Layout (Autodesk KB)](https://knowledge.autodesk.com/support/civil-3d/learn-explore/caas/CloudHelp/cloudhelp/2015/ENU/Civil3D-UserGuide/files/GUID-083DB674-89B7-40F0-8927-77363FBAD51B-htm.html)
- [Exploring Grid View for Alignments in Geometry Editor (VDCI)](https://vdci.edu/learn/civil-3d/exploring-grid-view-for-alignments-in-geometry-editor)
- [Civil 3D Superelevation Part 1: the Alignment (IMAGINiT)](https://resources.imaginit.com/civil-solutions-blog/civil3d-superelevation-part-1)

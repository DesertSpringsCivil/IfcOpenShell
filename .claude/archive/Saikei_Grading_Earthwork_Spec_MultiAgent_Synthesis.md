# Multi-Agent Review Synthesis: Saikei Grading & Earthwork Spec

**Date:** 2026-04-24
**Subject:** [Saikei_Grading_Earthwork_Spec.md](Saikei_Grading_Earthwork_Spec.md) (v2)
**Reviewers:** All six Saikei agents
**Source reviews:**
- [Architect](Saikei_Grading_Earthwork_Spec_Architect_Review.md)
- [IFC v2](Saikei_Grading_Earthwork_Spec_IFC_v2_Review.md)
- [Tool-dev](Saikei_Grading_Earthwork_Spec_ToolDev_Review.md)
- [Blender UI](Saikei_Grading_Earthwork_Spec_BlenderUI_Review.md)
- [Tester](Saikei_Grading_Earthwork_Spec_Tester_Review.md)
- [Docs](Saikei_Grading_Earthwork_Spec_Docs_Review.md)

The headless / agent-driven usage axis was the dominant lens across all six reviews. Three agents independently surfaced the same root cause.

---

## Cross-cutting themes (raised by 3+ agents)

### 1. Core unconditionally calls Blender

Architect, tool-dev, and UI agents all flagged this: every `core.*` function in §7.1 calls `tool.X.update_blender(...)` / `link_to_blender(...)` without a guard. A headless script hits `bpy.data.objects.new(...)` and crashes.

**Fix:** add a `viewport_sync: bool = True` parameter on every core function and gate the Blender-touching call on it. Architect's recommendation to add a formal **§12 "Headless operation" section** consolidates this.

### 2. Compute-path code reads from scene properties

Architect and UI agents: scene props must hold UI state only (active index, edit-mode flags). Any tool/core code that reads `context.scene.CivilSurfaceProperties.active_surface_guid` breaks headless. The rule should be stated explicitly.

### 3. Modal operators lack scripted equivalents

UI agent flagged 5 operators bundled as single entries that each need a split (modal UI path + headless-data path):
- `surface_create_from_points`
- `surface_add_breakline`
- `surface_set_boundary`
- `feature_line_create`
- `feature_line_edit_elevations`

---

## The one new bug introduced in v2

**IFC agent — schema violation in §2.7:** v2 correctly moved `IfcGeomodel` to use `IfcRelContainedInSpatialStructure` (that was the right call for an `IfcElement` subtype — prior v1 critique was actually wrong on this point) — **but** the same section places `IfcGroup` (the grading group) under `IfcSite` via the same relationship.

`IfcGroup` is not an `IfcProduct` and has no `ObjectPlacement`; `IfcRelContainedInSpatialStructure.RelatedElements` is typed `SET OF IfcProduct`. A validator will reject it.

**Fix:** drop the spatial containment for `IfcGroup` entirely (groups don't live in the spatial hierarchy — they're discovered by querying `IfcGroup` with `ObjectType='GradingGroup'`).

---

## Blockers to resolve before Sprint 1 code lands

| # | Issue | Owner/agent | Impact |
|---|---|---|---|
| 1 | `scipy.spatial.Delaunay` is **not present** in Blender's user-extensions site-packages. Must add scipy or switch unconstrained backend to `shapely.delaunay_triangles(MultiPoint(...))` | tool-dev | Blocks surface math |
| 2 | **Shapely CDT limitation**: accepts polygons only, not free-floating interior breaklines. Either scope Sprint 1 to perimeter breaklines or add the `triangle` package | tool-dev | Blocks breaklines |
| 3 | **`IfcGroup` + `IfcRelContainedInSpatialStructure` schema bug** (above) | ifc | Blocks IFC authoring |
| 4 | **§12 Headless section** with `viewport_sync` flag pattern; commit to `core` being the public MCP-exposable surface | architect | Architecture |
| 5 | **Dataclasses to `bonsai/civil_types.py`** to avoid core→tool eager import pulling numpy/shapely (and later bpy) | architect | Import hygiene |
| 6 | **Surface cache lifecycle** (§5.5 — "how does `tool.Surface.get(guid)` work?") — spec is silent, default will be a module-level dict that breaks test isolation | architect | State mgmt |
| 7 | **`IfcAlignment` for feature lines** — Dion's approval needed before Sprint 2 IFC authoring; if denied, fallback is `IfcAnnotation` with different pset plan | ifc, tool-dev | Sprint 2 blocker |
| 8 | **Numerical tolerance table** + **fixture sources** + **known-answer test cases** (cone frustum, prismatic embankment, 2:1 slope-projection) | tester | Test determinism |
| 9 | **`RepresentationIdentifier` on dual-rep `IfcEarthworksFill`** — must be `'SurfaceModel'` for TIN, `'Body'` for solid; spec doesn't prescribe, default `'Body'` for both will make viewers pick one | ifc | Interop |
| 10 | **`outer_boundary: None` default** on `CivilSurface` breaks volume domain; either require it or auto-compute convex hull | tool-dev | Volume calc |

---

## Missing sections the spec should grow

- **§8.3 Decorators** — grading overlays (breaklines, daylight lines, feature-line highlights, slope arrows) are the richest GPU overlay needs in Saikei, and the spec mentions zero. (ui)
- **§12 Headless operation** — viewport-sync flag, public API seam, MCP surface. (architect)
- **§13 Error propagation contract** — named `SaikeiGradingError` hierarchy; operators convert to `self.report()`, core/tool never call `report()`. (ui)
- **§14 Round-trip testing** — every IFC entity gets a write→read→assert test; public round-trip demo IFC file for bSI validator as a Sprint 3 deliverable. (tester, docs)
- **Headless `.py` examples + `api_manifest.json`** — the agent-consumable surface the docs plan doesn't currently commit to. (docs)

---

## Good news

- v2 **fixed 9 of 10** prior IFC-critique items fully.
- Layer boundaries are clean at the macro level — §7.1 core is textbook orchestration, §7.2 tool holds all implementation.
- **~85% of the tool surface is pure-Python testable** without launching Blender. Tester estimates 305 total tests across the three sprints, with only ~55 of those needing Blender-headless (mesh sync + operators).
- Classification (OmniClass 22), standard Qto sets, and the inheritance correction all landed correctly in v2.

---

## Recommended sequencing

1. **Today:** Fix the `IfcGroup` schema bug (5 minutes — drop the relationship), commit the `viewport_sync` pattern to the spec, decide on scipy vs Shapely-only for triangulation backend.
2. **Before Sprint 1 code:** Author §12 (Headless), §5.5 (Surface lifecycle), §8.3 (Decorators), the tolerance table, the fixture commitments, and `civil_types.py` placement.
3. **Before Sprint 2 code:** Resolve the `IfcAlignment`-for-feature-lines question with Dion. Have the `IfcAnnotation` fallback pset designed in case of decline.
4. **Before Sprint 3 code:** Have the cut/fill solid construction algorithm chosen (boundary extraction + side-face triangulation) — it's the single hardest piece of math in the spec and is currently a one-bullet placeholder.

---

## Per-agent top-3 issues (deep links)

| Agent | Top issue | #2 | #3 |
|---|---|---|---|
| Architect | Core unconditionally calls Blender (§2 of review) | No §12 Headless section / MCP seam (§6) | Surface cache lifecycle silent (§7) |
| IFC v2 | `IfcGroup` schema violation (B-1) | `RepresentationIdentifier` on dual-rep `IfcEarthworksFill` (B-3) | Tool methods call `tool.Ifc.get()` instead of accepting `ifc_file` (C-1) |
| Tool-dev | scipy not present in Blender (§1) | Shapely CDT can't handle interior breaklines (§1) | Cut/fill solid construction algorithmically risky, underspec'd (§1) |
| Blender UI | 5 operators need modal/headless splits (§1) | No GPU decorator spec (§5) | No error propagation contract (§10) |
| Tester | Numerical tolerances entirely absent (§3) | Known-answer test cases missing (§4) | Determinism / triangulation tie-breaking not addressed (§7) |
| Docs | Single-persona — no UI walkthrough plan (§1) | No `api_manifest.json` / agent-facing surface (§8) | No round-trip demo IFC artifact commitment (§4) |

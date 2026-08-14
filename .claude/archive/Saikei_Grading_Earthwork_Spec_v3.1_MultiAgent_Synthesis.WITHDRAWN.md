# Multi-Agent Re-Review Synthesis: Saikei Grading & Earthwork Spec v3.1

**Date:** 2026-04-28
**Subject:** [Saikei_Grading_Earthwork_Spec.md](Saikei_Grading_Earthwork_Spec.md) (v3.1)
**Reviewers:** All six Saikei agents, parallel re-review
**Comparison baseline:** [v2 multi-agent synthesis](Saikei_Grading_Earthwork_Spec_MultiAgent_Synthesis.md)

## Headline

**5 NO GO, 1 GO WITH CAVEATS.** v3.1 absorbed almost none of the v2 synthesis's "before Sprint 1 code lands" blockers. The IFC layer has progressed (B-3 representation identifiers partly resolved, classifications and Qto sets clean from v2), but the architecture, tool-math, UI, test, and docs lanes are essentially unchanged. The bump from v2 to v3.1 looks more like a rebrand than a revision.

## Verdict by reviewer

| Reviewer | Verdict | One-line summary |
|---|---|---|
| Architect | NO GO | All three prior blockers unfixed: §12 Headless missing, §5.5 surface lifecycle silent, dataclasses still imported into core via numpy/shapely |
| IFC | GO WITH CAVEATS | B-1 schema violation (IfcGroup spatial containment) carried forward verbatim; B-3 representation identifiers partial; **new bug**: composite-fill aggregation cardinality ambiguous in §2.7 vs §6.3 |
| Tool-dev | NO GO | scipy still named as backend but not present in Blender 5.0 site-packages; Shapely CDT polygon-only limitation unaddressed; cut/fill solid §6.5 still 4 placeholder bullets |
| Blender UI | NO GO | All five bundled operators still bundled; no §8.3 Decorators; no PropertyGroup/UIList schema; no error propagation contract; no keymap parallel for feature-line elevation editing |
| Tester | NO GO | No tolerance table; no known-answer cases (cone frustum / prismatic embankment / 2:1 slope-projection); no determinism rules; tester LoC budget unrealistic vs ~305 projected tests |
| Docs | NO GO | Single-persona doc plan unchanged; no `api_manifest.json`; no public round-trip demo IFC artifact; no `docs/grading/` directory |

## Top deal-breakers (consolidated, ordered by impact)

### Schema & correctness (must fix — bSI validator will reject)
1. **§2.7 — `IfcGroup` placed under `IfcSite` via `IfcRelContainedInSpatialStructure`.** `IfcGroup` is not an `IfcProduct`. Drop the relationship; groups are discovered by `ObjectType='GradingGroup'` query. Same fix as v2 review B-1.
2. **§2.7 vs §6.3 — composite `IfcEarthworksFill` has two ambiguous aggregation parents.** §2.7 line 174 shows `IfcGeomodel` aggregating composite; §6.3 says `IfcGroup` aggregates composite via `IfcRelAggregates`. `IfcEarthworksFill` can be `RelatedObject` of at most one `IfcRelAggregates`. Pick one and write it. (NEW in v3.1.)
3. **§5 — `GradingGroup.ifc_composite_fill_id` has no IFC relationship binding it to the `IfcGroup`.** Either author `IfcRelAssignsToGroup` or remove the field; spec is silent.

### Architecture (must fix — locks in headless/MCP feasibility)
4. **No §12 Headless / MCP-surface section.** Every core function in §7.1 calls `tool.X.update_blender(...)` unconditionally. Add `viewport_sync: bool = True` to every core signature; commit to core-as-public-API.
5. **No §5.5 Surface lifecycle.** `tool.Surface.get(guid)` is called everywhere with no resolution semantics. Default will be a module-level dict that breaks test isolation and headless multi-file usage. Commit to IFC-backed cache keyed by `(ifc_file_id, guid)`.
6. **Dataclasses inside `tool/*.py` modules with numpy/shapely top-level imports.** Move to `bonsai/civil_types.py` (no `bpy`, no numpy at module top). Otherwise `core` eagerly imports the world.
7. **Core function signatures take a single `tool` arg.** Inconsistent with `core/alignment.py:47` precedent (explicit class injection). Cementing the wrong shape in Sprint 1 is expensive to undo.

### Tool / math (must fix — Sprint 1 won't run)
8. **scipy.spatial.Delaunay is the named backend but not present in Blender 5.0 user-extensions site-packages.** Replace with `shapely.delaunay_triangles(MultiPoint(...))` for unconstrained, and pull `triangle==20230923` for constrained Delaunay with interior breaklines.
9. **Shapely `constrained_delaunay_triangles` cannot accept free-floating interior breakline polylines.** Either scope Sprint 1 to perimeter-only breaklines and document the limitation, or bring `triangle` into the user-extensions environment.
10. **§6.5 cut/fill solid construction is four placeholder bullets.** Boundary extraction at zero-delta contour, side-face strip triangulation between non-coincident 3D loops, disconnected/concave region handling — all unspecified. This is the Sprint 3 schedule risk.
11. **`outer_boundary: shapely.Polygon | None = None` default** breaks the volume-calc domain at §6.4. Either require it or auto-compute convex hull.
12. **Library version pinning silent in `pyproject.toml`.** Spec mentions "Shapely 2.1+" but pins nothing; `delaunay_triangles` exists in 2.0, `constrained_delaunay_triangles` requires 2.1+.

### UI (must fix — operator-layer scope undefined)
13. **Five operators still bundled (modal + headless not split):** `surface_create_from_points`, `surface_add_breakline`, `surface_set_boundary`, `feature_line_create`, `feature_line_edit_elevations`.
14. **No §8.3 GPU Decorators section.** Grading is the richest GPU overlay surface in Saikei (breaklines, daylight lines, slope arrows, cut/fill bands, elevation banding). Spec is silent on porting the alignment decorator pattern.
15. **No §8.4 PropertyGroup/UIList schema** despite CLAUDE.md mandating `Civil*Properties` and `CIVIL_UL_*` prefixes.
16. **No §8.6 Error propagation contract** (named `SaikeiGradingError` hierarchy; rule that `core/tool` never call `self.report()`).
17. **No keymap / G-key parallel for feature-line vertex elevation editing**, despite the alignment PI editor being the cited UX precedent.

### Test (must fix — tests will be flaky)
18. **No tolerance table.** Coordinate ε, area ε, volume ε, `z_at` ε, watertight-closure ε for §6.5 BRep — all absent.
19. **No known-answer cases.** Spec says "Test volumes against hand-calc values" without naming the cases or expected numbers. Need cone frustum, prismatic embankment, 2:1 slope-projection minimum.
20. **No determinism rules.** No input lexicographic sort, no `np.random.seed(42)` policy, no Shapely/GEOS version pin, no triangle winding/row-order canonicalization.
21. **§11 tester LoC budget (200/200/150) is unrealistic** for ~305 projected tests including round-trip and known-answer cases.

### Docs (must fix — grant-artifact gaps)
22. **No `api_manifest.json`** for agent-facing surface discoverability.
23. **No public round-trip demo IFC artifact** committed (`docs/examples/round_trip_demo.ifc` validated against bSI). This is the highest-leverage NLnet/bSI grant artifact.
24. **Single-persona doc plan.** Interactive engineer / headless agent / module developer surfaces all need named deliverables.

## Recommended path

The synthesis above is a v3.2 spec-revision punch list. Most items are localized 5–30-line spec edits, not redesigns. Recommended sequencing:

1. **Today (~2 hours of spec edits):** Fix items 1–3 (IFC schema), 4–6 (architecture sections), 8 (triangulation backend), 12 (version pins). These are line-level edits that unblock the next step.
2. **Tomorrow:** Add §8.3 Decorators, §8.4 PropertyGroups, §8.5 Modal/headless splits, §8.6 Error contract; tolerance table; known-answer cases; doc deliverables. ~50 lines of new spec content.
3. **Then re-run this same six-agent panel** against v3.2 to confirm GO before any code lands.

The IFC reviewer's "GO WITH CAVEATS" verdict is the closest to the line — that's because the v2→v3.1 work happened mostly in the IFC lane. The other five lanes need the same care before Sprint 1 starts.

## Sprint 2 still needs

- Dion Moult's blessing on `IfcAlignment` for feature lines (synthesis blocker #7). The IFC reviewer reads it as defensible-but-fragile semantic stretch — schema-legal today, ecosystem-acceptance risk tomorrow. Pset_SaikeiFeatureLineCommon-discriminated approach is clean. Have the `IfcAnnotation` fallback designed.

## Per-agent deep-link table

| Agent | Top issue | #2 | #3 |
|---|---|---|---|
| Architect | Core unconditionally calls Blender | No §12 Headless / MCP seam | Surface cache lifecycle silent |
| IFC v3.1 | `IfcGroup` schema violation (B-1, unchanged) | Composite-fill aggregation cardinality (NEW) | `Body` representation identifier still implicit |
| Tool-dev | scipy not in Blender environment | Shapely CDT polygon-only | §6.5 cut/fill solid still placeholder |
| Blender UI | 5 operators still bundled | No §8.3 Decorators | No error propagation contract |
| Tester | Tolerance table absent | Known-answer cases missing | Determinism rules absent |
| Docs | No `api_manifest.json` | No round-trip demo IFC artifact | Single-persona doc plan |

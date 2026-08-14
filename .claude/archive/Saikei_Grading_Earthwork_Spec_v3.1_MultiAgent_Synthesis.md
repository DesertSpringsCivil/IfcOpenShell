# Multi-Agent Re-Review Synthesis: Saikei Grading & Earthwork Spec v3.1 (verified)

**Date:** 2026-04-28 (replaces the WITHDRAWN earlier synthesis)
**Subject:** [Saikei_Grading_Earthwork_Spec.md](Saikei_Grading_Earthwork_Spec.md) (v3.1, 1048 lines)
**Reviewers:** Six Saikei agents, parallel re-review with strict citation discipline
**Verification:** Sample of cited claims read against source by lead synthesist before inclusion

## What changed from the WITHDRAWN synthesis

The earlier pass was rejected by the spec author for asserting absences without grounding — agents searched for v2-era keywords and reported "NOT FIXED" by literal absence, even when the concern was addressed under different wording. This pass requires every claim to carry a line number + verbatim quote, and the synthesist verified a sample before including. v3.1 is in materially better shape than the WITHDRAWN synthesis suggested, but several real deal-breakers remain.

## Verdict by reviewer

| Reviewer | Verdict | Headline |
|---|---|---|
| Architect | GO WITH CAVEATS | Layer separation, IFC delegation, tool authoring strategy all sound. Three concrete signature/state issues need resolution before Sprint 1. |
| IFC | GO WITH CAVEATS | Schema fundamentals well-cited and correct. Two localized schema bugs remain: `IfcGroup` containment, composite-fill aggregation tree. Sprint 1 doesn't exercise either. |
| Tool-dev | NO GO (Sprint 3) / GO WITH CAVEATS (Sprint 1) | §6.5 cut/fill solid is a sketch, not implementable; library install path missing; `outer_boundary` fallback unspecified |
| Blender UI | GO WITH CAVEATS | Sprint 1 UI is simple enough to start; Sprint 2 needs a PropertyGroup/UIList/keymap addendum before the grading panel can be coded |
| Tester | NO GO | Tolerance table, known-answer cases, determinism rules absent — tests will be flaky or incomplete |
| Docs | GO WITH CAVEATS | §7 Core API is itself a documented agent surface; §11 commits to per-sprint READMEs and validator runs. Soft gaps: no published sample IFC, Sprint 1 has no walkthrough |

## Verified deal-breakers (must fix before coding)

Each item below has a line number and verbatim quote. Quotes shortened with `…` where helpful.

### Schema correctness (IFC layer)

1. **`IfcGroup` placement under `IfcSite` via `IfcRelContainedInSpatialStructure`.** Lines 158–159 and 169:
   > `└── IfcGroup ObjectType="GradingGroup"  [IfcRelContainedInSpatialStructure / from IfcSite]`
   > `IfcSite → IfcGroup (grading group): IfcRelContainedInSpatialStructure`

   `IfcGroup` is not an `IfcProduct`. `IfcRelContainedInSpatialStructure.RelatedElements` is typed `SET OF IfcProduct`. A bSI reference validator will reject this. v3.1 explicitly justifies the `IfcGeomodel` use of this relationship at lines 138–143 (Geomodel is an `IfcElement`) — but applies the same relationship to `IfcGroup` without that justification holding. Fix: drop the spatial-containment relation for `IfcGroup`; groups are discovered by `IfcRelAssignsToGroup` query.

2. **Composite-fill aggregation tree ambiguity.** Lines 76, 152–156, 172, 173:
   > Line 76: `Composite site proposed | IfcEarthworksFill [SUBGRADE] | aggregates contained group fills via IfcRelAggregates`
   > Lines 152–156: `IfcEarthworksFill [SUBGRADE] (composite site proposed) [IfcRelAggregates from IfcGeomodel] / └── Aggregates per-group fills via IfcRelAggregates`
   > Line 172: `IfcGeomodel → IfcEarthworksFill: IfcRelAggregates`
   > Line 173: `IfcEarthworksFill → sub-IfcEarthworksFill (group composite → slope + interior): IfcRelAggregates`

   The §2.7 hierarchy block reads as a clean tree (Geomodel → site composite → group composites → slope+interior). But the relationship summary at line 172 is unqualified ("IfcGeomodel → IfcEarthworksFill: IfcRelAggregates") and could be read as Geomodel directly aggregating *all* fills — which would put group composites under two parents. Fix: either annotate line 172 as "(site composite only)" or drop it and rely on line 173. Localized 1-line edit.

### Architecture (Core/Tool layer)

3. **Core function signatures take a single `tool` param vs. alignment precedent's explicit class injection.** Line 627:
   > `def create_surface_from_points(tool, name: str, points: np.ndarray, kind: str) -> str:`

   `core/alignment.py:47` precedent uses `(ifc_tool, alignment_tool, ...)`. The recently-staged operator at `bim/module/alignment/operator.py` calls `core.create_alignment(tool.Ifc, tool.Alignment, ...)`. v3.1's pattern is inconsistent. Operators in `bim/module/grading/` will end up calling `core.create_surface_from_points(tool, ...)` while sibling alignment operators use the explicit pattern — confusing. Fix: change v3.1 signatures to explicit class injection.

4. **State registry contract.** Lines 641, 651, 663, 685, 718, 732 all call `tool.X.get(guid)` without specifying the registry. Sample, line 641:
   > `surface = tool.Surface.get(surface_guid)`

   Spec is silent on where the cache lives, how it's seeded from IFC on file open, and how it survives multi-file or headless usage. Default implementation will be a module-level dict that breaks test isolation. Fix: ~one paragraph naming the resolution policy (e.g. "Tool-side cache keyed by `(ifc_file_id, guid)`, lazily rehydrated from IFC on miss"). User flagged this as a legitimate concern.

5. **`np.ndarray` in core function signatures.** Line 627 (same as #3) forces `import numpy` into core unless guarded. v3.1 doesn't specify `from __future__ import annotations` or `if TYPE_CHECKING:`. Either guard with the alignment-precedent pattern, or change to `list[tuple[float, float, float]]` at the core boundary.

### Tool / math layer

6. **`outer_boundary: None` default leaves volume domain undefined.** Line 350:
   > `outer_boundary: shapely.Polygon | None = None  # 2D, XY only`

   Line 579 then computes:
   > `Compute domain = outer_boundary(existing) ∩ outer_boundary(proposed) minus holes/voids from either.`

   Undefined behavior when either is `None`. Fix: pick a fallback (convex hull of points is a reasonable default) and write it in §6.4 or §5. User flagged this as legitimate.

7. **Library version pinning + install path missing.** Lines 300–303:
   > `**scipy.spatial.Delaunay** — unconstrained Delaunay triangulation`
   > `**shapely.constrained_delaunay_triangles** (Shapely 2.1+) — constrained Delaunay`

   Tool-dev verified neither scipy nor shapely is currently installed in `%APPDATA%\Blender Foundation\Blender\5.0\extensions\.local\lib\python3.11\site-packages\`. v3.1 doesn't specify exact versions, install location, or whether wheels go in the extension manifest's `wheels/` directory or via `pip --target`. Sprint 1 cannot start until this is committed. User flagged version pinning as legitimate.

8. **§6.5 cut/fill solid construction is a sketch, not an implementable spec.** Lines 597–614 (12-line pseudocode block). What's missing:
   - Region extraction (how are contiguous cut/fill regions identified from the §6.4 prismoidal algorithm output?)
   - Triangle clipping at region boundaries (currently uses whole-triangle XY-overlap test)
   - Side-face strip triangulation between two non-coincident 3D loops
   - Watertightness verification (Euler characteristic, edge-pair counts, signed-volume agreement)

   Sprint 3 will block on this. User flagged §6.5 algorithm depth as legitimate.

9. **`Triangulator` interface promised but undefined.** Lines 302–303:
   > `The backend is abstracted behind a Triangulator class in tool/surface.py so it can be swapped if performance needs dictate`

   No class signature, no method protocol, no ABC defined anywhere in §5 or §7. Without a written interface, Sprint 1 will inline shapely calls and the abstraction won't materialize.

### UI layer

10. **No `bpy.types.PropertyGroup` schema.** §5 defines `@dataclass` types in tool layer (lines 322–469), but no `Civil*Properties` PropertyGroup is committed for the panel state (active surface index, viz toggles, current criteria reference, interior-fill enum binding, shrink/swell inputs). Sprint 2 grading panel cannot be coded without this — alignment's `prop.py` is non-trivial and grading is more complex. User flagged "property group schema detail" as legitimate.

11. **No keymap table; G-key vertex-elevation modal not committed.** Line 904:
    > `CIVIL_OT_feature_line_edit_elevations — vertex-by-vertex elevation edit dialog.`

    "Dialog" implies a popup; the alignment PI editor uses Blender's G-key modal transform (proven UX). v3.1 never says "keymap," "G key," "modal," or names a precedent. User flagged keymap table as legitimate.

12. **Modal vs. headless ambiguity on 4 specific operators.** Lines 896, 897, 902, 904:
    > `CIVIL_OT_surface_add_breakline — pick a 3D polyline in viewport, convert to breakline.`
    > `CIVIL_OT_surface_set_boundary — pick a 2D polygon as outer boundary, hole, or void.`
    > `CIVIL_OT_feature_line_create — draw a new feature line or convert mesh edge loop.`
    > `CIVIL_OT_feature_line_edit_elevations — vertex-by-vertex elevation edit dialog.`

    Each conflates a modal (viewport pick / draw) and a headless (convert / dialog) path. Either split or document `invoke()`-branched single-operator pattern.

## Items where new reviewer findings disagree with your prior spot-check

You spot-checked items #1, #4, #6, #7, #8, #9, #14, #16, #18, #19, #20, #22, #23, #24 from the WITHDRAWN synthesis as "factually wrong; addressed in v3.1." The new reviewers — citing line numbers and quotes — agree with you on most of these (the API surface is in §7, decorators are addressed via different vocabulary, doc deliverables are committed in §11). They disagree on a few, with evidence:

- **#1 (IfcGroup schema violation).** New IFC reviewer cites line 158 verbatim. Verified by me — the violation is present in v3.1. Either the spec text doesn't match what you intended, or there's a schema interpretation we're missing. Worth a closer look.
- **#7 (single `tool` arg signatures).** New architect cites line 627 verbatim. Verified — the pattern differs from `core/alignment.py:47`. Whether this is a deal-breaker depends on whether you're OK with two patterns coexisting in `core/`.
- **#8 (scipy not in Blender).** Tool-dev verified by file system check — neither scipy nor shapely is present in the user-extensions site-packages. The spec names them but doesn't pin or document install. Sprint 1 can't run as-is.
- **#18, #19, #20 (tolerance table, known-answer cases, determinism rules).** Tester finds zero coverage. Cited evidence: line 232 mentions a runtime triangulation tolerance Pset field (not a test ε); line 1006 commits to "hand-calc values" without naming any specific shape (frustum, prism, etc.); no seed/ordering/version-pin policy anywhere. If you read v3.1's "Test volumes against hand-calc values" as sufficient commitment, that's a defensible position — just want to flag the gap.

**My read:** items #1, #7, #8 look like real bugs in v3.1 that warrant fixing (they have explicit cited evidence). Items #18–20 are a judgment call about how much test rigor the spec needs to specify (vs. leaving it to test fixtures). Worth your input.

## Items the prior synthesis flagged that v3.1 actually does address

Confirmed by the new reviewers with cited evidence:
- **API surface discoverability:** §7 (lines 618–736) is a complete callable surface with type-annotated signatures and docstrings — itself an `api_manifest.json` analog.
- **Doc deliverables per persona:** §11 has explicit `docs` rows per sprint (lines 985, 996, 1007) including a Sprint 2 tutorial.
- **Round-trip validation:** §9 line 935–936 commits to round-trip tests + bSI reference validator runs; §11 references DESITE for Sprint 3.
- **Decorator coverage:** addressed via different vocabulary — line 311 references `tool.Blender.validate_shader_batch_data`; line 888 lists viz toggles; line 731 / 879 commit to mesh-overlay strategy for cut/fill maps.
- **Operator inventory:** §8.2 (lines 894–913) lists 15 operators across surface/grading/earthwork.
- **Architecture (Core never invents API paths):** §4.3 lines 290–296 explicit and correct.

## Recommended sequencing (revised)

1. **Today (~30 minutes of spec edits):** Fix items 1, 2, 7 (the localized one-line schema fixes), pin library versions and document install path for item 7, write the §6.4 fallback for item 6.
2. **Today/tomorrow (~1–2 hours):** Add a §5.5 surface-lifecycle paragraph (item 4), change core signatures to explicit class injection (item 3) and either guard or simplify the np.ndarray annotation (item 5).
3. **Before Sprint 2 commits (~1–2 hours):** Add a §8.x with PropertyGroup/UIList schema and a keymap subsection mirroring alignment's PI editor (items 10, 11, 12). Sprint 1 panel is simple enough to start without this.
4. **Before Sprint 3 commits (~half day):** Expand §6.5 with real region-extraction + clipping algorithm (item 8), define `Triangulator` interface (item 9). Optional but valuable: tolerance table + named known-answer cases.

Sprint 1 is plausibly startable after step 1 + step 2. The bigger UI/test gaps are Sprint 2 / Sprint 3 concerns.

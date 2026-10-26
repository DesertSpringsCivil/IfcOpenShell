# buildingSMART IFC4.x-development — Alignment Activity Review

**Date:** August 15, 2026
**Scope:** Issues, PRs, commits, and branch activity in [buildingSMART/IFC4.x-development](https://github.com/buildingSMART/IFC4.x-development) related to alignments, linear placement, and linear referencing — reviewed for consistency with Saikei Civil development (IFC 4.3 today, IFC 4.4 next), followed by a code review of the `saikei-dev` fork (`C:\GitHub\IfcOpenShell-saikei-dev`, branch `saikei-dev-0.9.0`) against those findings.

**Bottom line:** No hard conflicts. The Saikei code is on the correct side of every recently settled upstream decision (Axis defaults, OffsetVertical semantics, zero-length segments, cant construction, no horizontal-layout reuse), and its offset-alignment code already anticipates rules still being drafted. One real conformance bug (reserved `Pset_` prefix on 5 custom psets), one sync gap (Aug 12–13 upstream API commits), and two watch items (cant-twist default Axis; 4.4's Axis-only representation rule) — details in Part 2.

---

## Part 1 — State of upstream alignment development

### 1.1 How the repo is organized right now

The repo is the single hub for IFC 4.3.x maintenance and IFC 4.4 development. What matters for tracking:

- **`ifc4.3-main`** is the default development branch for IFC 4.3 documentation/schema maintenance. **`ifc4.4-main`** is where IFC 4.4 is being built. A separate **`master`** branch still receives some doc merges destined for the published 4.3 docs site (PR #971 landed there, for example) — so a change being "merged" doesn't always mean it's on `ifc4.3-main` yet, and vice versa.
- Work is coordinated through the **"IFC4x-IF | 4.4 update" project**, run in two-week sprints through the Implementers Forum. Key labels: `before-NWI` / `after-NWI` (relative to the ISO New Work Item submission for the next cycle), `4.3-4.4` (merge to 4.3 then cherry-pick to 4.4), `4.4` (4.4-only), `IF` (to be checked with the Implementers Forum), `( ! )` (hot).
- **`TM*` branches** are numbered Technical Maintenance topics feeding 4.4 (TM11 = Alignment Representation; TM17/19/21–25 = tunnel & geoscience; TM26 = attach external data; TM27 = voxels).
- Key people on alignment topics: **Rick Brice (`RickBrice`)** — by far the most active; **Scott Lecher (`civilx64`)** — repo collaborator, reviewer/merger on most alignment PRs; plus Thomas Krijnen (`aothms`, IfcOpenShell), Sergej Muhic (`SergejMuhic`, original infra-projects author), Ilya Sokolov (`I-Sokolov`), `pjanck`, `michelangelo-acca` (ACCA/usBIM), and Evandro Alfieri (`evandroAlfieri`, bSI) coordinating.
- Rick Brice's **[IFC-Alignment-Geometry-Implementation-Guide](https://github.com/RickBrice/IFC-Alignment-Geometry-Implementation-Guide)** is the de-facto implementer reference and is cited inside upstream issues. (The numbered chapter docs in the Saikei project — `1_Introduction` … `9_Precision_and_Tolerance` — mirror this guide; note the guide has since grown, e.g. a chapter on sectioned surfaces/solids, and chapters have been renumbered.)

### 1.2 Recently settled decisions (these are now "the answer")

**a) `IfcAxis2PlacementLinear` default directions — PR #1118 (civilx64), merged Aug 4, 2026, labeled `4.3-4.4`.**
The merged doc text now reads:

> **Axis**: The exact direction of the local Z Axis. When the Axis is omitted, its direction defaults to the normal vector to the basis curve that lies within the vertical plane with the RefDirection and has positive Z coordinate. For *IfcSegmentedReferenceCurve* the Axis direction also includes the 'twist' resulting from a deviating elevation relative to the associated *IfcGradientCurve*.
>
> **RefDirection**: … If RefDirection is omitted, the direction is taken from the curve tangent at *Location*.

In other words: the default Axis is **not** global (0,0,1) — it is the curve normal (tangent-perpendicular, generally up), and on a canted `IfcSegmentedReferenceCurve` it **includes the cant twist**. This resolves long-standing issues #732 and #846 and IF #125.

**b) `IfcPointByDistanceExpression` offset semantics — consensus reached in issue #1151 (Rick Brice, Jul–Aug 2026, 17 comments).**
This is the single most important thread for any implementer. Rick consolidated all linear-placement discussions and, after initially proposing a "global Z" reading of `OffsetVertical`, reversed his position based on the IFC Alignment 1.1 conceptual model (Liebich et al. 2017) and the Jaud et al. 2021 linear placement paper. The recorded consensus (Rick's summary, concurred by Scott Lecher):

1. `DistanceAlong` is measured **along the projection of the 3D curve onto the global XY plane** (classic 2.5D "distance along" in plan view).
2. Default `IfcAxis2PlacementLinear.Axis` = **normal to the 3D curve, generally up** (per #1118).
3. Default `IfcAxis2PlacementLinear.RefDirection` = **tangent to the 3D curve**.
4. `OffsetLateral` / `OffsetVertical` / `OffsetLongitudinal` are measured in the **local frame of the basis curve at DistanceAlong** — i.e. `OffsetVertical` is perpendicular to the tangent (the "local up", rotating with grade), **not global Z** — and these offsets are **independent of** `Axis`/`RefDirection` on the owning placement. (Item 4 to be finalized in a follow-up PR; items 1–3 are considered agreed.)

Practical corollary confirmed in the thread: **IfcOpenShell/Bonsai, usBIM and the bSI Validation Service treat OffsetVertical as local-Z and this is conformant.** An entity needing a truly vertical (plumb) orientation should set `Axis = (0,0,1)` explicitly; a truly-vertical *offset* is achieved by referencing the horizontal `IfcCompositeCurve` as basis (offset from it by elevation) rather than by reinterpreting OffsetVertical.

**c) `IfcOffsetCurveByDistances` basis curve — PR #971 (Rick Brice), merged Jun 17, 2026.**
`IfcAlignment`'s representation list now allows `IfcOffsetCurveByDistances` to reference an **`IfcCompositeCurve`** (2D), not just `IfcGradientCurve` / another offset curve. (Note: merged to the `master` docs branch.)

**d) TM11 "Alignment Representation" — PR #1113 (aothms), 4.4-only, in progress but drafted.**
Adds a formal WHERE rule + function `IfcAlignmentRepresentation` on `IfcAlignment`:

> Only IfcShapeRepresentation.RepresentationIdentifier='Axis' and RepresentationType='Curve2D' or 'Curve3D' are allowed. If both 'Curve2D' and 'Curve3D' are defined, then the horizontal alignment 2D curve shall be the basis of the 3D curve.

**e) Horizontal-layout reuse between alignments is dead.** PR #981 ("Alignment Layout – Reusing Horizontal Layout") was abandoned, and PR #1156 (Rick Brice, active — updated Aug 14, 2026) now **removes the reference to the non-existent concept template "Alignment Geometry – Reusing Horizontal Layout"** from `IfcAlignment` docs. Two alignments sharing one horizontal layout is not a supported pattern; each alignment owns its representation.

**f) Zero-length segments stay mandatory in 4.3 — #727, #970.**
Rick's guidance (accepted for 4.3): the zero-length final segment defines the end of each layout (business logic **and** geometry); `IfcGradientCurve.EndPoint` / `IfcSegmentedReferenceCurve.EndPoint` are **informational only** — if present they must match the zero-length segment. (`EndPoint` is an `IfcPlacement`, so it also carries end tangent/normal.) PR #970 (clarifying wording) was abandoned in favor of resolving via the 4.4 track.

### 1.3 In-flight clarifications to watch

- **PR #1148 — `IfcPointByDistanceExpression` doc rewrite (Rick Brice, 26 comments, active).** Removes the invalid references to `IfcProduct.Placement` / `IfcCurveSegment.StartPlacement` as offset defaults; adds figures; states DistanceAlong is along the horizontal projection. Open debates inside the PR:
  - Scott Lecher proposes constraining/documenting `BasisCurve` to the supported alignment representations (`IfcCompositeCurve`, `IfcGradientCurve`, `IfcSegmentedReferenceCurve`, possibly `IfcPolyline`/`IfcIndexedPolyCurve`); Rick would limit to the three composite-curve types.
  - Sergej Muhic pushes back that parametrization follows the `BaseCurve` chain (and that offsets must also work on true 3D geometry, e.g. tunnels) — i.e. **the "DistanceAlong on a 3D basis curve" question is not 100% closed** even though the 2.5D reading has the momentum and matches practice.
- **#733 — `IfcOffsetCurveByDistances` rules (Rick Brice).** Proposed: basis restricted to `IfcCompositeCurve`+subtypes; all `OffsetValues` must share the basis curve; offsets constrained to the basis curve's domain (no negative DistanceAlong, none beyond length); first/last offsets implicitly extend; and a formal proposition **`NoLongitudinalOffsets`** (OffsetLongitudinal must not be used in offset curves).
- **#1143 (I-Sokolov)** — offset direction wording; folded into the #1151/#1148 effort.
- **#1133 (Sergej Muhic) — Product Relative Positioning vs. Product Linear Placement.** Clarifies intent: `IfcRelPositions`/Referents = the **semantic** linear-referencing layer (ISO 19148 — works without any representation); `IfcLinearPlacement` = the **geometric** placement layer. I-Sokolov argues `IfcRelPositions` is redundant. Unresolved; may become a discussion.
- **#1005 — `IfcPositioningElement` documentation errors** (open, `iso-Te`, linked PR pending).
- **PR #1162 — `IfcSectionedSurface` documentation update** (Rick Brice, opened Aug 3, 2026) and the related note that cross-sections are **not** automatically vertical: `CrossSectionPositions` needs explicit `Axis=(0,0,1)` if a vertical section plane is intended; otherwise the section plane rotates with grade/cant.
- **PR #1145 — note on `IfcCompositeCurve` segments** (don't mix `IfcCompositeCurveSegment` and `IfcCurveSegment` expectations).
- **PR #967 — update of concept template "Alignment Geometry — Horizontal, Vertical and Cant"** (TinaTyf, `after-NWI`).
- **#1011 (I-Sokolov, `after-NWI`)** — `IfcCurveMeasureSelect`: using `IfcParameterValue` for segment measures is problematic; expect a future tightening toward `IfcLengthMeasure` (`IfcCurveSegment` informal proposition already requires length measures for segments).
- **#608** — `IfcPolynomialCurve` lacks a clear definition (unit-of-measure problem for coefficients — also called out in the Saikei project's `3_Vertical.md`).
- **#1165** — `IfcCardinalPointReference` worked example (minor, new Aug 2026).

### 1.4 IFC 4.4 signals relevant to alignments

- **#727 is on the IFC4.4 milestone**: options discussed are deprecating `EndPoint`, or (Rick's preferred sketch) a new **`IfcHorizontalCurve`** subtype of `IfcCompositeCurve` with mandatory `EndPoint` on H/V/C curves and **dropping the zero-length-segment requirement** in geometry. Nothing decided; 4.3 files keep zero-length segments.
- **#728**: `IfcSegmentedReferenceCurve` as a subtype of `IfcGradientCurve` — Rick argues **no** (same attributes, different meanings; Liskov violation). Open.
- **#985**: new 4.4 concept template **"Alignment Geometry — Approximate"** (`IfcPolyline` / `IfcIndexedPolyCurve` / `IfcOffsetCurveByDistances` representations, explicitly no layout and no zero-length-segment language). Next step is a PR against `ifc4.4-main`.
- `ifc4.4-main` itself so far is mostly **platform work** (UML-based serialization as source of truth, SHACL validation CI, docs tooling) plus tunnel/geoscience/voxel domain content. The alignment entity docs on 4.4 are still nearly identical to 4.3 — alignment schema changes for 4.4 will come through the TM/IF issue pipeline above, so tracking that project board is the right early-warning system.

---

## Part 2 — Saikei Civil consistency check (code review of `saikei-dev`)

**What was reviewed:** `C:\GitHub\IfcOpenShell-saikei-dev`, branch `saikei-dev-0.9.0` — a fork of IfcOpenShell (origin `DesertSpringsCivil/IfcOpenShell`, upstream remote configured). Saikei's alignment work lives in three layers: (1) extensions to `ifcopenshell.api.alignment` (67 modules — cant layout, PI-method solver, CSV import, offset alignments, station↔distance conversion with station equations, multi-vertical support), (2) a new Bonsai Blender layer (`bonsai/bim/module/alignment`, `tool/alignment.py` ≈5,000 lines / 140 methods, `core/alignment.py`), and (3) modified `ifcgeom` C++ mappings. Compared file-by-file against upstream IfcOpenShell master (cloned Aug 15) and against the upstream schema decisions in Part 1.

### 2.1 The good news: no conflicts with settled decisions

The codebase is on the right side of every recently settled upstream question I checked:

1. **`IfcAxis2PlacementLinear` defaults (PR #1118 / #1151 items 2–3): conformant.** Saikei's `ifcgeom/mapping/IfcAxis2PlacementLinear.cpp` is functionally identical to upstream's — when Axis/RefDirection are omitted, RefDirection comes from the curve tangent (via the PBDE placement matrix) and Axis is computed as the tangent-perpendicular "generally up" normal, exactly the merged #1118 semantics. No "default Z-up" anywhere in code. (The stale "default Z-up" statement lives only in the project doc `Corridor_Generation_Deep_Research.md` — fix the doc, not the code.)
2. **`OffsetVertical` local-frame reading (#1151 item 4): conformant.** Saikei never reinterprets PBDE offsets; authoring code writes offsets only where appropriate and geometry evaluation delegates to the IfcOpenShell mapping — the same implementation the #1151 thread confirmed as conformant.
3. **Zero-length segments + `EndPoint` (#727): conformant, exemplary.** `add_zero_length_segment` / `has_zero_length_segment` / `_update_zero_length_segment_placement` maintain the mandatory terminal zero-length segment in both semantic and geometric layers, and `update_end_point()` keeps `IfcGradientCurve.EndPoint` / `IfcSegmentedReferenceCurve.EndPoint` synchronized with the zero-length segment's placement — precisely Rick Brice's recommended validation discipline.
4. **Cant (CT 4.1.7.1.1.3): conformant.** `add_cant_layout` requires an existing vertical layout, builds `IfcSegmentedReferenceCurve` with the `IfcGradientCurve` as BaseCurve, repoints the Axis/Curve3D representation, and maintains zero-length segment + EndPoint. It correctly declines to support cant via the (non-existent) reuse concept template.
5. **Offset alignments (#733 / #971): ahead of the curve.** `create_as_offset_curve` + `_build_offset_points` write `OffsetLateral` only, never `OffsetLongitudinal` (matching the proposed `NoLongitudinalOffsets` rule), clamp offset points to the basis curve's domain `[0, extent]` with explicit endpoints (safe under any resolution of the domain question), and pick Curve2D/Curve3D by basis-curve dimension with `RepresentationIdentifier='Axis'`.
6. **Multiple verticals via aggregated child alignments (CT 4.1.4.4.1.2): correct pattern.** The multi-vertical selector uses semantic child alignments — the pattern upstream is actively strengthening — not the representation-level "Reusing Horizontal Layout" that was abandoned (#981) and is being scrubbed from the docs (#1156).
7. **Stationing (CT / ISO 19148): solid.** Referents carry `Pset_Stationing` with `Station`/`IncomingStation`; `distance_along_from_station` and `station_from_distance_along` handle station-equation gaps and overlaps in both directions with documented conventions. `WIDTHEVENT`/`SUPERELEVATIONEVENT` used for event referents are valid `IfcReferentTypeEnum` values in 4.3.

### 2.2 Conflicts and gaps found

1. **🔴 Reserved `Pset_` prefix violation (real conformance bug, easy fix).** Five Saikei-defined property sets use the reserved prefix: `Pset_SaikeiAlignment`, `Pset_SaikeiCant`, `Pset_SaikeiDesignCriteria`, `Pset_SaikeiEvent`, `Pset_SaikeiOffset`. IFC 4.3's `IfcPropertySet` documentation is explicit: *"Property sets that are not declared as part of the IFC specification shall have a Name value not including the 'Pset_' prefix."* The bSI Validation Service checks this. Rename to e.g. `SaikeiCivil_Alignment`, `SaikeiCivil_Offset`, … before files start circulating.
2. **🟠 ~1 sync behind Rick Brice's upstream API work.** The fork's `api/alignment` tracks upstream master remarkably closely (last sync ≈ Aug 8–11), but misses the Aug 12–13 commits: the `"<alignment name> <station>"` referent-naming convention (`307836049`), and — directly relevant to Saikei's own multi-vertical feature — `update_key_point_referents` gaining ancestor-nest support so a child alignment's key points can be named after and nested to the top-level parent in the reusing-horizontal scenario (`1af5cc9bb`). Saikei's copy still raises TypeError in that case. Recommend a sync pass; upstream `api/alignment` is where Rick Brice develops the reference implementation, so staying current there *is* the compliance strategy.
3. **🟠 Cant twist in the default Axis.** Merged #1118 says the default Axis on an `IfcSegmentedReferenceCurve` *"also includes the 'twist'"* from cant. Neither Saikei's mapping nor upstream master implements that yet (the no-Axis case recomputes the normal from the tangent and global up, discarding roll); upstream PR [IfcOpenShell#8451](https://github.com/IfcOpenShell/IfcOpenShell/pull/8451) ("keep cant twist in IfcSectionedSurface via IfcAxis2PlacementLinear") is the fix in flight. Watch and adopt — it matters for placing objects and sweeping sections on canted track.
4. **🟡 FootPrint representations vs. the 4.4 TM11 rule.** Saikei (matching upstream and the current 4.3 concept templates) writes `FootPrint`/Curve2D + `Axis`/Curve3D when a vertical exists. TM11's drafted 4.4 WHERE rule allows **only** `Axis` representations (`Curve2D` or `Curve3D`) on `IfcAlignment`. If that lands as written, the 2D horizontal becomes `Axis`/Curve2D in 4.4 — flag `create_segment_representations` and the tool-layer code that renames FootPrint for a schema-versioned switch.
5. **🟡 Stale reference docs in the project** (not code): `Corridor_Generation_Deep_Research.md` says Axis "default Z-up" (wrong per #1118); `IFC_Roadway_Templates_Assemblies_Reference.md` samples use `IfcDistanceExpression`, which doesn't exist in IFC 4.3 (replaced by `IfcPointByDistanceExpression` at RC2); the numbered guide chapters (`1_…`–`9_…`) are an older snapshot of Rick Brice's implementation guide — e.g. `7_LinearPlacement.md` still treats the Axis default as an open question. Worth a refresh pass so future agent/design work isn't anchored on outdated semantics.

### 2.3 Opportunities

- **Contribute implementation experience to the open threads.** Saikei now has one of the few real *authoring* implementations of offset alignments, stationing referents with station equations, and cant. Issues #733 (offset-curve rules), #1148 (PBDE docs), and #985 (approximate-alignment CT — civilx64 explicitly invited a draft PR against `ifc4.4-main`) are all looking for exactly this input. This is also the natural venue given the project's TM27 voxel forum engagement already underway.
- **Add the #733 validations to the offset API** while they're still proposals: assert all `OffsetValues` share one `BasisCurve`, and constrain the basis type to `IfcCompositeCurve`/`IfcGradientCurve`(/`IfcSegmentedReferenceCurve`) — cheap now, and it makes Saikei files valid under the likely future rule.
- **Track #727 for IFC 4.4.** If 4.4 drops zero-length geometry segments (or adds `IfcHorizontalCurve`), Saikei's clean isolation of the zero-length logic in three helper modules makes that a contained change — good position, just keep the helpers as the single choke point.
- **Watch #1151 item 4 / PR #1148 to closure** — the offsets-local-frame consensus is agreed-in-thread but not yet merged text; when the PR lands, mirror any final wording in Saikei docstrings that describe PBDE offsets.
- **Event referents' future home:** the `IfcReferentTypeEnum` doc notes width/superelevation events are proposed to be contained in the road spatial structure (Lane/carriageway). Saikei currently nests them under the alignment in a dedicated nest — fine as an extension today, but when corridor generation consumes them, consider the spatial-structure containment to match the documented intent.

---

## Sources

- Issues: [#1151](https://github.com/buildingSMART/IFC4.x-development/issues/1151), [#727](https://github.com/buildingSMART/IFC4.x-development/issues/727), [#728](https://github.com/buildingSMART/IFC4.x-development/issues/728), [#733](https://github.com/buildingSMART/IFC4.x-development/issues/733), [#1143](https://github.com/buildingSMART/IFC4.x-development/issues/1143), [#985](https://github.com/buildingSMART/IFC4.x-development/issues/985), [#1133](https://github.com/buildingSMART/IFC4.x-development/issues/1133), [#1005](https://github.com/buildingSMART/IFC4.x-development/issues/1005), [#732](https://github.com/buildingSMART/IFC4.x-development/issues/732), [#846](https://github.com/buildingSMART/IFC4.x-development/issues/846), [#608](https://github.com/buildingSMART/IFC4.x-development/issues/608), [#1011](https://github.com/buildingSMART/IFC4.x-development/issues/1011), [#1165](https://github.com/buildingSMART/IFC4.x-development/issues/1165)
- PRs: [#1118](https://github.com/buildingSMART/IFC4.x-development/pull/1118), [#1148](https://github.com/buildingSMART/IFC4.x-development/pull/1148), [#1156](https://github.com/buildingSMART/IFC4.x-development/pull/1156), [#1162](https://github.com/buildingSMART/IFC4.x-development/pull/1162), [#1145](https://github.com/buildingSMART/IFC4.x-development/pull/1145), [#1113](https://github.com/buildingSMART/IFC4.x-development/pull/1113), [#971](https://github.com/buildingSMART/IFC4.x-development/pull/971), [#970](https://github.com/buildingSMART/IFC4.x-development/pull/970), [#981](https://github.com/buildingSMART/IFC4.x-development/pull/981), [#984](https://github.com/buildingSMART/IFC4.x-development/pull/984), [#967](https://github.com/buildingSMART/IFC4.x-development/pull/967)
- Git history of `ifc4.3-main`, `ifc4.4-main`, `master`, and `tm11` branches (cloned Aug 15, 2026)
- [Rick Brice's IFC-Alignment-Geometry-Implementation-Guide](https://github.com/RickBrice/IFC-Alignment-Geometry-Implementation-Guide)
- [Scott Lecher (civilx64) on GitHub](https://github.com/civilx64)

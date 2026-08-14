## ***Agent 1: saikei-architect — Complete**

***Key findings from the architect:**

1. ***Scope underestimated by ~40-50% — realistic total is 6,500-9,500 lines vs. stated 4,500-6,500. Corridor (Section 4) is the most dangerously underestimated.**

2. ***Critical dependency gap — terrain sampling (Stretch 4) is needed by the profile view (Core Section 2.2). Recommends moving Section 8.1-8.2 into core scope.**

3. ***Architecture violations flagged — K-value computation described as Core but is math (belongs in Tool). Profile view GPU rendering → UI only.**

4. ***Corridor rebuild needs transactional design — half-completed rebuilds could corrupt IFC state.**


## ***Agent 2: saikei-ifc — Complete**

***Key findings from the IFC specialist:**

1. ***Wrong entity names — `IfcAlignmentGradient` doesn't exist; correct entity is `IfcGradientCurve`. `IfcAnnotation(SUPERELEVATIONEVENT)` is wrong; correct entity is `IfcReferent(SUPERELEVATIONEVENT)`.**

2. ***IfcOpenCrossProfileDef gotchas — `Tags` list must be N+1 entries for N segments (tags = points, not segments). `Slopes` are stored as angles, not percentages. `HorizontalWidths=True` should be standard. Cannot mix with `IfcArbitraryClosedProfileDef` in same solid (`SectionsSameType` rule).**

3. ***Region transitions — tag structure must be held constant across entire corridor using zero-width segments for lane drops; cannot just change tag count mid-corridor. \[Verified\]**

4. ***Missing relationships — `IfcRelContainedInSpatialStructure` for all corridor elements, `IfcRelPositions` for referents, `IfcRelDeclares` for reusable profiles.**

5. ***Top validation failure risks — `CorrespondingTags` length mismatch, `SectionsSameType` violation from mixed profiles, missing zero-length terminal segments on vertical layouts.**


## ***Agent 3: saikei-tool-dev — Complete**

***Key findings from the tool developer:**

1. ***Rick's API mapping is clean — our existing wrapper already calls `layout\_vertical\_alignment\_by\_pi\_method` correctly. Edge cases identified: single PVI must be guarded (minimum 2), compound curves (overlapping BVC/EVC) need a UI warning.**

2. ***Critical missing function — `evaluate\_alignment\_at\_station()` doesn't exist yet and is the most load-bearing gap. Everything in Sections 3-7 needs it to get 3D position + tangent frame at a station.**

3. ***IfcOpenCrossProfileDef slopes — stored as dimensionless ratios in IFC, but UI will use percent. Must document conversion.**

4. ***Corridor mesh algorithm — loft between station profiles with quad faces. Varying vertex counts at region boundaries should use the "gap approach" (separate mesh per region) for core scope; defer taper transitions.**

5. ***Performance is fine — 400 stations × 10 break points = 4,000 vertices, trivial for Blender. The only risk is 400 separate C++ geometry engine calls; a pure-Python evaluator would be faster.**

6. ***Coordinate system gap — profile view pan/zoom state needs a `PropertyGroup` home (not specified). **

7. ***Proposed function signatures — detailed signatures for `tool/alignment.py` additions, new `tool/cross\_section.py`, and new `tool/corridor.py`.**

8. ***IFC-to-component deserialization — need a method to read `IfcOpenCrossProfileDef` back into an editable component list (analogous to `extract\_pis\_from\_segments()`)**

9. ***Write-back path design — confirm-on-exit vs. live-update-on-change must be decided before UI is built (affects undo stack depth).**

10. ***Blender window type constraint — custom `SpaceType` isn't available in Python add-ons. Practical options are `NODE\_EDITOR` area, `SpaceImageEditor` as canvas, or similar. This choice constrains the draw handler API the tool layer must target.**

11. ***New PropertyGroup — `CivilCrossSectionViewProperties` on `bpy.types.Scene` for view state (current station, zoom, offset range, terrain toggle)**



## ***Agent 4: saikei-blender-ui — Complete**

***Key findings from the Blender UI specialist:**

1. ***Profile view overlay — `POST\_PIXEL` draw handler is correct. The hard problem is mouse event partitioning between profile region and 3D viewport; needs explicit pixel-rect hit testing in the modal operator. Grid batches must be cached, not rebuilt per draw call.**

2. ***Assembly editor — UIList is the right pattern. No native drag-and-drop reorder; use up/down arrow operators instead. Cross-section preview can't draw inside an N-panel directly; use `bpy.data.images` pixel buffer + `layout.template\_image()`.**

3. ***Corridor rebuild — Must be an explicit operator with dirty flag, NOT a depsgraph handler (too slow, no undo support, fires on irrelevant events). Use `wm.progress\_\*` for feedback during generation.**

4. ***Current structure — all Saikei panels are already children of `BIM\_PT\_tab\_horizontal\_alignment` inside the `CIVIL` tab in Properties. This is the correct integration pattern. One note: The profile view toggle ("Show Profile View") is awkward in the Properties editor — user has to navigate away from their viewport to toggle it. Consider a viewport header button for that specific control instead. **

5. ***Blender 5.0 — No breaking changes for our patterns. `bgl` already removed (we don't use it). `blf.size()` is 2-argument form (we already use it correctly). Property registration ordering is stricter — register child PropertyGroups before parents.**

6. ***UX friction points — alignment selection context for corridors, profile view toggle (not auto-show), station input as decimal-only (no "STA 1+42.5" format), and corridor rebuild needs progress bar feedback.**



## ***Agent 5: saikei-tester — Complete**

***Key findings from the tester:**

1. ***Zero test strategy in the outline — flagged as a critical gap for GSoC-scale work.**

2. ***155 tests proposed across 3 core sections:**

| Category | Section 2 | Section 3 | Section 4 | Total |
| :-: | :-: | :-: | :-: | :-: |
| Core Tests | 18 | 16 | 16 | **50** |
| Tool Tests | 12 | 10 | 8 | **30** |
| Operator Tests | 8 | 8 | 12 | **28** |
| Validation Tests | 3 | 2 | 2 | **7** |
| Edge Cases | 10 | 10 | 10 | **30** |
| Regression Tests | — | — | 10 | **10** |
| **Subtotal** | **51** | **46** | **58** | **155** |

3. ***Test file structure — new files for `test/core/test\_cross\_section.py`, `test/core/test\_corridor.py`, `test/tool/test\_cross\_section.py`, `test/tool/test\_corridor.py`, plus operator tests.**

4. ***Key recommendations — write all 50 core tests first (run in seconds), build reusable fixture library (ifc\_empty → ifc\_with\_corridor progressive fixtures), automate buildingSMART validation in CI, and don't skip edge cases (30 edge case tests are where real bugs hide).**

5. ***Total test suite runtime: ~5 minutes with Blender headless.**

  
***Agent 6: saikei-docs — Complete**

***Key findings from the docs agent:**

1. ***Extensive jargon without definitions — PI, K-value, superelevation, daylight, emax, rollover rate, normal crown, and many more civil engineering terms used without explanation. IFC entities (`IfcRelNests`, `IfcAxis2PlacementLinear`, etc.) and Bonsai patterns (`tool.Ifc.Operator`, GPU decorator, PolylineOperator) also assumed known.**

2. ***Glossary is essential — drafted a comprehensive glossary with ~35 terms across three categories: Civil Engineering, IFC/BIM, and Bonsai Architecture.**

3. ***Missing context — the "why" of IFC-native design is never stated, Rick Brice is referenced without introduction, the dual-path problem lacks context, and the corridor rebuild dependency chain is implied but not explicit.**

4. ***5 diagrams recommended (priority order):**

   - ***Corridor generation concept (alignment + profile + assembly → 3D solid)**

   - ***Three-layer architecture (Core/Tool/UI with forbidden items)**

   - ***IFC entity relationship diagram**

   - ***Cross-section anatomy with labeled tags**

   - ***User workflow diagram**

5. ***Terminology inconsistencies — "assembly" vs "template" used interchangeably, "profile" is overloaded (3 different meanings), "directrix" / "3D alignment curve" / "IfcAlignmentGradient" all refer to the same concept. Line count estimates don't clarify whether tests are included.**

6. ***Documentation deliverables — 3 user tutorials (vertical alignment, cross-section assembly, corridor generation), a consolidated developer architecture guide, API reference for new Tool functions, an IFC compliance report, and a migration guide for Civil 3D/OpenRoads users.**


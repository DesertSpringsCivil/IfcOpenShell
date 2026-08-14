# Agent Review Prompts for Saikei Civil Feature Outline

**Purpose:** Have each agent review the feature outline from their specialized perspective before finalizing the GSoC 2026 application.

**Setup:** The outline file should be accessible in the repo. Adjust the path below to match your local setup.

**File to review:** `Saikei_Civil_Feature_Outline.md`

---

## 1. saikei-architect (Opus)

```
Review the file Saikei_Civil_Feature_Outline.md as the project architect. This is the feature outline for our GSoC 2026 proposal and long-term roadmap. I need your critical assessment on:

1. SCOPE FEASIBILITY: The core scope (Sections 1-4) targets 4,500-6,500 lines at 16-20 hours/week over 22 weeks. Given our experience shipping the horizontal alignment module, is this realistic? Are there hidden complexity traps in any section?

2. DEPENDENCY ORDERING: The stretch goals are ordered as Parametric Controls → Superelevation → Grading. Do you see any dependency gaps? Are there features in the core scope that secretly depend on stretch goal features to be useful?

3. ARCHITECTURE BOUNDARIES: Each section defines Core/Tool/UI responsibilities. Flag any places where the boundary descriptions are ambiguous or where you'd expect implementation to violate the stated separation. Pay special attention to:
   - Profile view visualization (Section 2.2) — does GPU rendering logic belong in Core or Tool?
   - Dual-path cross-section approach (Section 3.3) — who orchestrates keeping both paths in sync?
   - Corridor rebuild (Section 4.7) — where does the rebuild trigger logic live?

4. MILESTONE SEQUENCING: If we build Sections 2, 3, and 4 in order, does each milestone produce independently shippable, testable code? Or are there features that only become useful when combined?

5. MISSING PIECES: What's NOT in this outline that should be? Think about: error handling, edge cases, Bonsai integration points we haven't mentioned, IFC relationships that need explicit management.

Be direct and critical. I'd rather find problems now than during implementation.
```

---

## 2. saikei-ifc (Sonnet)

```
Review the file Saikei_Civil_Feature_Outline.md focusing exclusively on IFC 4.3 compliance and entity usage. This is our GSoC feature outline. I need you to audit:

1. IFC ENTITY CORRECTNESS: Review the "IFC Entity Summary" table and each section's IFC references. Are we using the right entities? Specifically:
   - Is IfcAlignmentGradient the correct representation for combined horizontal + vertical? Or should it be a different representation context?
   - Is IfcSectionedSolidHorizontal the right choice for corridor solids, or should we also consider IfcSectionedSurface for certain use cases?
   - Are the IfcEarthworksCut/IfcEarthworksFill PredefinedTypes correct per the IFC 4.3 schema?
   - Is IfcAnnotation with PredefinedType=SUPERELEVATIONEVENT a real IFC 4.3 predefined type, or are we inventing that?

2. MISSING RELATIONSHIPS: The outline mentions entities but rarely specifies the IFC relationships connecting them. For each core section, list the IfcRel* relationships that will be needed:
   - IfcRelNests (alignment → layout → segments)
   - IfcRelAggregates (road → facility parts)
   - IfcRelContainedInSpatialStructure
   - IfcRelAssociatesMaterial (pavement materials)
   - Any others we're missing

3. IfcOpenCrossProfileDef DETAILS: Section 3.3 describes a dual-path approach because the geometry engine can't render IfcOpenCrossProfileDef. Review our proposed usage:
   - Are the Widths, Slopes, and Tags attributes correctly described?
   - Is HorizontalWidths a boolean we need to handle?
   - What's the relationship between IfcOpenCrossProfileDef and IfcArbitraryClosedProfileDef — can we use them interchangeably in IfcSectionedSolidHorizontal, or does the WHERE rule (SectionsSameType) prevent mixing?

4. IfcSectionedSolidHorizontal CONSTRAINTS: Section 4.4 describes the corridor solid. Review against the EXPRESS schema:
   - ConsistentProfileTypes WHERE rule — what does this mean in practice for our varying cross-sections?
   - NoLongitudinalOffsets — does this constrain how we place cross-section positions?
   - What happens at region transitions where the profile tag structure might change?

5. VALIDATION CONCERNS: What are the most likely buildingSMART validation failures we'll encounter? What should we test for early?

Reference the IFC 4.3 specification and Rick Brice's alignment API where relevant. Cite specific entity definitions or WHERE rules.
```

---

## 3. tool-dev (Sonnet)

```
Review the file Saikei_Civil_Feature_Outline.md focusing on Tool layer implementation feasibility. This is our GSoC feature outline. I need your assessment on:

1. RICK'S API INTEGRATION: Section 2 relies heavily on layout_vertical_alignment_by_pi_method(). Review:
   - What parameters does this function actually accept? Do our PVI inputs (station, elevation, curve length) map correctly to its expected arguments?
   - Does it handle the IfcAlignmentVertical nesting automatically, or do we need to manage that?
   - Are there edge cases (single PVI, two PVIs with no curve, very short curves) we should plan for?

2. GEOMETRY COMPUTATION: Several features require us to compute geometry ourselves:
   - Parabolic arc math for vertical curves (Section 2.1) — is this straightforward, or are there numerical stability concerns?
   - Break point geometry from IfcOpenCrossProfileDef parameters (Section 3.3, Path B) — how do we compute 2D point positions from Widths + Slopes + HorizontalWidths?
   - BVHTree raycasting for terrain sampling (Section 7.1 stretch goal) — at civil engineering scale (km-long corridors), will this perform adequately? Any precision concerns?

3. COORDINATE SYSTEMS: Multiple coordinate systems are in play:
   - IFC local coordinates (alignment definition)
   - Blender viewport coordinates (visualization)
   - Georeferenced map coordinates (real-world)
   - Profile view coordinates (station vs. elevation)
   - Cross-section coordinates (offset vs. elevation from centerline)
   Flag any coordinate transform chains that seem error-prone or underspecified.

4. MESH GENERATION: Sections 3 and 4 require generating Blender meshes from computed geometry:
   - For cross-section preview (Section 3.4) — what's the simplest approach? BMesh? Direct mesh data?
   - For corridor 3D mesh (Section 4.5) — generating a mesh from swept cross-sections is non-trivial. What's the algorithm? Loft between station profiles? How do we handle varying vertex counts between stations if tags change at region boundaries?

5. PERFORMANCE: Section 4.7 describes corridor rebuild on any input change. For a 2km corridor at 5m spacing, that's 400 stations × however many profile points. Is regenerating the entire IfcSectionedSolidHorizontal + Blender mesh feasible in interactive time? What should we cache?

6. TOOL FUNCTIONS NEEDED: What new functions would tool/alignment.py, tool/cross_section.py, and tool/corridor.py need? List the key function signatures you'd expect.

Be specific about implementation approaches. If you see a section that says "compute X" without enough detail on HOW, flag it.
```

---

## 4. blender-ui (Sonnet)

```
Review the file Saikei_Civil_Feature_Outline.md focusing on Blender UI/UX implementation. This is our GSoC feature outline. I need your assessment on:

1. PROFILE VIEW OVERLAY (Section 2.2): The outline describes a 2D profile view at the bottom of the 3D viewport. Review:
   - Is a SpaceView3D draw handler the right approach for this? Or should we use a separate editor type / region?
   - How does this interact with Blender's existing timeline/playback area? Does it replace it or overlay on top?
   - For interactive PVI placement: how do we handle mouse events that need to go to the profile view vs. the 3D viewport? Is there a clean way to partition the viewport?
   - GPU rendering with gpu module (shader batches) — are there Blender 5.0 API changes we need to account for?

2. ASSEMBLY EDITOR (Section 3.4): The outline describes a panel for building cross-section assemblies. Review:
   - What's the best Blender UI pattern for this? UIList for components? Node editor? Custom PropertyGroup with dynamic properties?
   - How do we display a visual cross-section preview? Options: separate image preview, gpu overlay in 3D view, or a mini 2D canvas in the N-panel?
   - Component reordering — does Blender's UIList support drag-and-drop reorder natively?

3. OPERATOR CONVENTIONS: The outline specifies CIVIL_OT_* and CIVIL_PT_* prefixes. Review:
   - Are there new operator categories needed beyond alignment? (e.g., CIVIL_OT_add_component, CIVIL_OT_create_corridor)
   - Which operators need to be modal (interactive editing) vs. simple execute?
   - The corridor rebuild (Section 4.7) — should this be an explicit operator the user triggers, or automatic via depsgraph handler?

4. PANEL LAYOUT: We'll need panels for:
   - Vertical alignment editing (PVI table, similar to existing PI table)
   - Cross-section assembly editor
   - Corridor properties and station control
   - How should these be organized? All under one N-panel tab? Multiple tabs? Integrated into existing Bonsai panels?

5. BLENDER 5.0 COMPATIBILITY: Are there any Blender 5.0+ API changes that affect:
   - Draw handlers / gpu module usage
   - Property registration
   - Operator modal patterns
   - Extension packaging (we're part of Bonsai, not standalone)

6. UX WORKFLOW: Think about the end-to-end user experience:
   - Create horizontal alignment (existing) → create vertical profile → define cross-section → generate corridor
   - Where are the friction points? Where would a Civil 3D user get confused?
   - What feedback does the user need at each step (progress bars for corridor generation, error messages for invalid geometry, etc.)?

Focus on practical Blender implementation patterns. If the outline describes something that's awkward or impossible in Blender's UI framework, flag it with alternatives.
```

---

## 5. saikei-tester (Haiku)

```
Review the file Saikei_Civil_Feature_Outline.md focusing on test strategy. This is our GSoC feature outline. The outline currently has almost NO detail on testing. I need you to:

1. IDENTIFY TESTABLE UNITS: For each core section (2, 3, 4), list the specific functions/behaviors that need tests. Categorize each as:
   - Core test (pure Python, no Blender, no IFC file needed)
   - Tool test (needs IfcOpenShell and/or Blender headless)
   - Integration test (needs full Bonsai environment)

2. CORE TEST OPPORTUNITIES: What business logic in the Core layer can be tested without any dependencies?
   - PVI data model validation (Section 2)
   - Grade calculations between PVIs
   - K-value computation
   - Assembly/component data model (Section 3)
   - Tag consistency validation
   - Station management calculations (Section 4)

3. TOOL TEST REQUIREMENTS: What Tool layer functions need IFC file fixtures?
   - Vertical alignment creation via Rick's API — what does a test fixture look like?
   - IfcOpenCrossProfileDef creation — what should we validate in the output?
   - IfcSectionedSolidHorizontal generation — how do we verify correctness?
   - Geometry engine rendering — can we test that a shape is produced without visual inspection?

4. IFC VALIDATION TESTS: Should we have automated tests that run the buildingSMART validation checker on generated IFC files? What specific validation rules are most likely to fail?

5. EDGE CASES: List edge cases for each core section that should have explicit test coverage:
   - Section 2: Single PVI (no curve), two PVIs (single grade line), zero-length vertical curve, very steep grades
   - Section 3: Single-component assembly, empty assembly, component with zero width, asymmetric left/right sections
   - Section 4: Single-station corridor, corridor shorter than one interval, corridor with region transition at a station

6. REGRESSION TESTS: Given that corridor rebuild (Section 4.7) regenerates geometry on any change, what regression tests would catch the most bugs? Think about: edit alignment → verify corridor updates, edit assembly → verify cross-sections update, etc.

7. PROPOSED TEST FILE STRUCTURE: Where should test files live? Suggest a directory layout and naming convention consistent with the existing Bonsai test patterns.

Output a concrete test plan organized by section, with estimated test count per category.
```

---

## 6. docs (Haiku)

```
Review the file Saikei_Civil_Feature_Outline.md focusing on documentation and clarity for future contributors. This is our GSoC feature outline that doubles as a long-term roadmap. I need you to assess:

1. AUDIENCE CLARITY: This document serves two audiences — GSoC evaluators (who may not know IFC or civil engineering) and future Saikei developers (who may not know Bonsai architecture). Flag places where:
   - Civil engineering jargon is used without definition (PVI, PI, K-value, superelevation, daylight, etc.)
   - IFC terminology is assumed (IfcRelNests, IfcOpenCrossProfileDef, etc.)
   - Bonsai-specific patterns are referenced without explanation (three-layer architecture, tool.Ifc.Operator, etc.)

2. GLOSSARY NEED: Should this document include a glossary? If so, draft a list of terms that need definitions.

3. MISSING CONTEXT: Where would a new contributor reading this outline get lost? What background knowledge is assumed but never stated?

4. DIAGRAM OPPORTUNITIES: The guidelines say "create diagrams, show prototypes, create mock-up visuals." What diagrams would strengthen this outline?
   - Architecture diagram (Core/Tool/UI layers with data flow)
   - Workflow diagram (user journey from alignment → corridor)
   - IFC entity relationship diagram (how all the entities connect)
   - Cross-section anatomy diagram (labeled component illustration)
   - Corridor generation concept diagram (alignment + profiles → 3D solid)

5. INTERNAL CONSISTENCY: Check for:
   - Section numbering consistency
   - Feature references that point to the wrong section
   - Terminology used inconsistently (e.g., "assembly" vs "template", "profile" vs "cross-section")
   - Estimated scope numbers that don't add up

6. DOCUMENTATION DELIVERABLES: The GSoC acceptance requirements mention documentation as a deliverable. What docs should we commit to producing?
   - User-facing: how to create a vertical alignment, how to build a cross-section, how to generate a corridor
   - Developer-facing: architecture guide for future contributors, API reference for new Tool functions
   - Any other docs?

Be specific about what's unclear. Quote the sentence or section that confused you and suggest a rewrite.
```

---

## Running the Reviews

**Recommended order:**
1. `saikei-architect` first — catches structural issues before detail reviews
2. `saikei-ifc` and `tool-dev` in parallel — they review different aspects
3. `blender-ui` — depends on architecture decisions being solid
4. `saikei-tester` — needs the feature design to be stable
5. `docs` — final polish pass

**After reviews:** Collect findings, update the outline, then use the refined outline to build the final GSoC application with personal narrative voice.

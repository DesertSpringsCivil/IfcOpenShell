# v2 IFC Critique: Saikei Grading & Earthwork Spec

**Reviewer:** saikei-ifc agent
**Date:** 2026-04-24
**Subject:** [Saikei_Grading_Earthwork_Spec.md](Saikei_Grading_Earthwork_Spec.md) (v2, post-IFC-critique revision)
**Prior review:** [Saikei_Grading_Earthwork_Spec_IFC_Critique.md](Saikei_Grading_Earthwork_Spec_IFC_Critique.md) (v1)

---

## Schema confirmations from IfcOpenShell source

**IfcGeomodel inheritance confirmed:** `IfcGeomodel → IfcGeotechnicalAssembly → IfcGeotechnicalElement → IfcElement → IfcProduct`. It is an `IfcProduct`, not an `IfcSpatialElement`. The spec's claim in Section 2.7 that `IfcGeomodel` is an `IfcElement` is correct.

**IfcGroup confirmed:** `IfcGroup → IfcObject → IfcObjectDefinition → IfcRoot`. It is NOT an `IfcProduct`. It has no `ObjectPlacement`, no `Representation`. The spec places it under `IfcSite` via `IfcRelContainedInSpatialStructure` — that relationship's `RelatedElements` domain is `SET OF IfcProduct` (or more precisely, subtypes of `IfcSpatialElement` for some usages). Since `IfcGroup` is not an `IfcProduct`, `IfcRelContainedInSpatialStructure` is schema-invalid for it.

---

## Part (a): v1-Issue-by-v1-Issue Verdict Table

| # | v1 Issue | Verdict | Notes |
|---|----------|---------|-------|
| 1 | Proposed design surface incorrectly assigned to `IfcGeographicElement` | **Fixed** | v2 §2.2 correctly uses `IfcEarthworksFill[SUBGRADE]` for proposed surfaces, with rationale. The `IfcGeographicElement` reference is gone. |
| 2 | `IfcGeomodel` related to `IfcSite` via wrong relationship type | **Partially fixed — new error introduced** | v2 §2.7 correctly notes `IfcGeomodel` is an `IfcElement` (verified via schema: the chain is `IfcGeomodel → IfcGeotechnicalAssembly → IfcGeotechnicalElement → IfcElement`). It then concludes `IfcRelContainedInSpatialStructure` is the right relationship. This is consistent with how `IfcAlignment` sits under `IfcSite`. However, v2 also places `IfcGroup` (the grading group) under `IfcSite` via `IfcRelContainedInSpatialStructure` — and `IfcGroup` is NOT an `IfcProduct` (confirmed: `IfcGroup → IfcObject → IfcObjectDefinition → IfcRoot`, no `IfcProduct` in chain). `IfcRelContainedInSpatialStructure.RelatedElements` is typed `SET [1:?] OF IfcProduct`. Placing an `IfcGroup` in that set violates the schema. See Part (b) for the full new issue. |
| 3 | Solid representation type for earthwork volumes unspecified | **Fixed** | v2 §2.4 explicitly commits to `IfcPolygonalFaceSet` with `Closed=TRUE` in a `Brep` `ShapeRepresentation`. The "open question" is resolved. |
| 4 | Volumes in custom psets instead of standard `Qto_*` sets | **Fixed** | v2 §3.2 explicitly maps volumes to `Qto_EarthworksFillBaseQuantities` and `Qto_EarthworksCutBaseQuantities`. Shrink/swell factors correctly remain in custom `Pset_SaikeiGradingShrinkSwell`. |
| 5 | No classification section | **Fixed** | v2 §3.4 adds OmniClass Table 22 classification with specific codes per entity type, `IfcRelAssociatesClassification` usage, and auto-assignment by `PredefinedType`. |
| 6 | Incorrect `IfcEarthworksFill` inheritance (`IfcElementAssembly`) | **Fixed** | v2 §2.4 explicitly states `IfcEarthworksFill` inherits from `IfcEarthworksElement → IfcBuiltElement → IfcElement`, with a parenthetical clarifying that `IfcElementAssembly` is a sibling, not an ancestor. |
| 7 | `tool.Ifc.run()` calls with phantom API paths (`grading.*`, `surface.*`, `earthwork.*`) | **Fixed** | v2 §4.3 explicitly states "Core never invents API paths" and "There is no `ifcopenshell.api.surface`, no `ifcopenshell.api.grading`, no `ifcopenshell.api.earthwork`." Core code in §7.1 now calls named tool methods (`tool.Surface.author_ifc_host(surface)`, etc.) rather than `tool.Ifc.run()` with fabricated paths. Verified: upstream `ifcopenshell/api/` contains `alignment`, `spatial`, `aggregate`, `group`, `pset`, `system` etc. — no `surface`, `grading`, or `earthwork` modules exist. The fix is correct and the pattern is clean. |
| 8 | No persistence strategy for feature lines and grading criteria | **Fixed** | v2 §2.3 commits to `IfcAlignment` with `IfcPolyline` representation for feature lines, and `IfcPropertySetTemplate` for reusable grading criteria. Both strategies are defensible. (The `IfcAlignment`-as-feature-line stretch is acknowledged as an open question in §12.) |
| 9 | `Flags` per-triangle limitation overstated as per-edge fidelity | **Fixed** | v2 §2.1 explicitly documents the limitation: "Round-trip preserves per-triangle breakline membership, not per-edge identity." §10 acknowledges it as a known limitation. Breakline source geometry preserved separately as `IfcAnnotation` polylines. |
| 10 | No `IfcObjectPlacement` strategy or `IfcBoundingBox` requirement | **Fixed** | v2 §2.8 prescribes `IfcLocalPlacement` with identity `IfcAxis2Placement3D` for all earthwork products. §2.9 adds the `IfcBoundingBox` with `RepresentationIdentifier='Box'` requirement and explains the LOD rationale. |

**Summary:** 9 of 10 items are fully or substantially fixed. Item 2 is partially fixed but introduced a new schema error (the `IfcGroup` placement problem).

---

## Part (b): New IFC Issues Introduced in v2

### Issue B-1 (Schema violation): `IfcGroup` cannot participate in `IfcRelContainedInSpatialStructure`

Section 2.7 places the grading group (`IfcGroup`) under `IfcSite` via `IfcRelContainedInSpatialStructure`. The schema definition of `IfcRelContainedInSpatialStructure.RelatedElements` is `SET [1:?] OF IfcProduct` (with an `IfcSpatialElement` exclusion constraint). `IfcGroup` inherits from `IfcObject → IfcObjectDefinition → IfcRoot` — it is not an `IfcProduct` and has no `ObjectPlacement` or `Representation`. This relationship is schema-invalid for `IfcGroup`. A validator will reject it.

**The fix:** `IfcGroup` does not need spatial containment — it is a logical grouping entity. It does not live "in" the spatial hierarchy at all. To make a grading group findable from an `IfcSite`, use `IfcRelAssignsToGroup` in reverse (the site's elements are the members) — but more practically, no spatial link is needed. Clients find grading groups by querying `IfcGroup` with `ObjectType='GradingGroup'`. If the author wants a navigable link from the site, use `IfcRelAssociates` or store the `IfcGroup` GUID as a property on the site. Removing the `IfcRelContainedInSpatialStructure` for `IfcGroup` entirely is the correct spec fix.

### Issue B-2 (Schema ambiguity): `IfcRelAggregates` from `IfcGeomodel` to `IfcEarthworksCut` and `IfcEarthworksFill`

Section 2.7 shows `IfcGeomodel → IfcGeotechnicalStratum`, `IfcGeomodel → IfcEarthworksCut`, and `IfcGeomodel → IfcEarthworksFill` all via `IfcRelAggregates`. The concern is domain compatibility: `IfcRelAggregates.RelatingObject` must be an `IfcObjectDefinition`, and `RelatedObjects` must be `SET [1:?] OF IfcObjectDefinition`. `IfcGeomodel`, `IfcEarthworksCut`, and `IfcEarthworksFill` are all `IfcElement` subtypes and thus `IfcObjectDefinition` subtypes — the relationship is schema-valid.

However, the semantic question is whether earthwork solids (cut and fill volumes) logically decompose `IfcGeomodel`. `IfcGeomodel`'s definition is "a model of geotechnical conditions." An `IfcEarthworksCut` representing a designed excavation is arguably not part of a geotechnical model — it's a designed intervention on top of the geotechnical model. The buildingSMART example diagrams place earthwork elements under the spatial structure (`IfcSite`), not under `IfcGeomodel`. The spec should at minimum cite its authority for putting `IfcEarthworksCut` and `IfcEarthworksFill` under `IfcGeomodel` rather than directly under `IfcSite` or within the grading group's logical scope. This is a judgment call that should be documented, not assumed.

### Issue B-3 (Representation conflict): Two representations on one `IfcEarthworksFill` entity require distinct subcontexts

Section 2.2 and §2.4 state that the proposed `IfcEarthworksFill` carries two representations: a `SurfaceModel` `IfcTriangulatedIrregularNetwork` (the proposed surface TIN) and a `Brep` `IfcPolygonalFaceSet` Closed (the fill volume solid). Both attach to `IfcProductDefinitionShape.Representations` as separate `IfcShapeRepresentation` entries.

**The problem:** most IFC viewers apply a rendering decision based on the first `Body`-identified representation they find. The `Brep` solid will almost certainly be labeled with `RepresentationIdentifier='Body'` while the TIN surface should use `RepresentationIdentifier='SurfaceModel'`. As long as those identifiers are correctly differentiated, viewers can select which to display. The spec does not explicitly state what `RepresentationIdentifier` to assign to each. If the tool-dev agent defaults both to `'Body'` (a common shortcut), viewers will pick one and ignore the other. The spec needs to explicitly prescribe: the TIN surface uses `RepresentationIdentifier='SurfaceModel'` and the fill solid uses `RepresentationIdentifier='Body'`.

### Issue B-4 (Semantic stretch unresolved): `IfcAlignment` for feature lines

Section 2.3 commits to `IfcAlignment` entities for feature lines. `IfcAlignment` is defined as "a linear positioning element that defines a reference curve for the positioning of other elements along it, typically representing a designed route." A grading feature line is not a transportation route. The spec acknowledges this in §12 Open Question 1 but marks it as a question for Dion rather than making a spec decision.

This is fine for now — it is correctly flagged — but the spec should name the fallback decision that will govern Sprint 2 if Dion says no. If `IfcAlignment` is rejected, the fallback (`IfcAnnotation` with 3D `IfcPolyline`) needs to be designed with the same pset and IFC-linkage attention the current `IfcAlignment` approach gets. Sprint 2 should not begin before this question is answered.

### Issue B-5 (Missing required attribute): `IfcTriangulatedIrregularNetwork.Closed` is not a directly settable attribute in IFC4x3 ADD2

Section 7.2's `author_ifc_tin_representation` code passes `Closed=False` directly to `ifc_file.create_entity("IfcTriangulatedIrregularNetwork", ...)`. `IfcTriangulatedIrregularNetwork` is a subtype of `IfcTriangulatedFaceSet`, which is a subtype of `IfcTessellatedFaceSet`. The `Closed` attribute belongs to `IfcTessellatedFaceSet` and is inherited — setting it in `create_entity` should work via positional or keyword argument as long as the inheritance chain is respected by the SWIG wrapper. This is a minor implementation risk rather than a spec error, but the tool-dev agent should verify that `ifc_file.create_entity("IfcTriangulatedIrregularNetwork", Closed=False, ...)` correctly sets the `Closed` attribute and does not silently fail. A round-trip test that reads back `tin.Closed` and asserts it is `False` should be in Sprint 1's test suite.

---

## Part (c): Headless / Agent-Driven IFC Concerns

V2 is substantially cleaner than v1 on this front, but three concerns remain.

### C-1 (Critical): Core functions receive `tool` via dependency injection but Surface/Grading tool classes call `tool.Ifc.get()` internally

The Core API in §7.1 correctly uses dependency injection (`def create_surface_from_points(tool, name, points, kind)`). However, the Tool method stubs in §7.2 contain expressions like `ifc_file = tool.Ifc.get()` inside static methods that receive no arguments. There is no `tool` in scope for a static method — `tool` here must be the module `bonsai.tool`, which is a Blender-coupled import. In headless Python, `bonsai.tool` is importable only if the Blender extension site-packages symlink is present and `bpy` is either stubbed or not imported. The spec's code pattern for tool methods effectively requires Bonsai's runtime `tool.Ifc.get()` to work, which ties IFC authoring to the Bonsai runtime.

For the spec to be headless-callable, tool methods that author IFC entities must accept the `ifc_file` as an argument (passed from Core, which gets it from `tool.Ifc.get()` at the orchestration level), rather than calling `tool.Ifc.get()` inside each tool method. The existing `tool/alignment.py` pattern is inconsistent on this — some methods take `ifc_file` as a parameter, others call `tool.Ifc.get()` internally. The spec should make a decision here: for headless scenarios, `ifc_file` is threaded as a parameter, not pulled from Bonsai's global state.

### C-2 (Moderate): `author_ifc_group` attaches to `IfcSite` via `IfcRelContainedInSpatialStructure`

As noted in B-1, `IfcGroup` cannot use `IfcRelContainedInSpatialStructure`. The tool method implementing `author_ifc_group` will presumably call `ifcopenshell.api.spatial.assign_container()` or `ifcopenshell.api.aggregate.assign_object()`. For `IfcGroup`, neither call is appropriate — the group has no spatial position. In a headless script, calling `ifcopenshell.api.spatial.assign_container(ifc_file, product=grading_group, relating_structure=site)` with an `IfcGroup` will either raise a type error or silently produce an invalid file. The spec must remove the spatial-placement requirement for `IfcGroup` entirely, which also removes the Blender-state dependency for "which site is active."

### C-3 (Low, but systematic): Classification via `IfcRelAssociatesClassification` requires a classification source entity

Section 3.4 prescribes OmniClass Table 22 classification. To attach a classification reference, the IFC file must contain an `IfcClassification` entity representing the OmniClass Table 22 system. In a headless script, this entity must be created once per file and referenced by all `IfcRelAssociatesClassification` instances. The spec does not describe this setup step. In a Blender UI context a user might pre-configure the classification source; in headless execution the tool method `apply_classification` must handle "find or create the `IfcClassification` for OmniClass Table 22" as its first action. The spec should make this explicit in the tool method signature or as a file-initialization step.

---

## Part (d): Remaining Open Questions

### D-1 (Must resolve before Sprint 2): `IfcAlignment` as feature line — upstream acceptance

Already flagged as §12 OQ-1. Sprint 2 cannot begin without this answer. If Dion declines, the fallback `IfcAnnotation` approach needs its own spec pass — pset structure, round-trip behavior, query pattern from headless scripts — before Sprint 2 implementation starts.

### D-2 (Must resolve before Sprint 1 — schema correctness): `IfcGeomodel` spatial containment vs. aggregation

Section 2.7 places `IfcGeomodel` under `IfcSite` via `IfcRelContainedInSpatialStructure`, citing the BIM Corner case study and the `IfcAlignment` precedent (which also uses `IfcRelContainedInSpatialStructure`). The v1 critique said this was wrong (must be `IfcRelAggregates`); v2 argues the other direction, citing that `IfcGeomodel` is an `IfcElement`, not an `IfcSpatialElement`, so `IfcRelContainedInSpatialStructure` is appropriate. This deserves one more look: the `IfcRelContainedInSpatialStructure` domain specifies `RelatedElements: SET [1:?] OF IfcProduct` with the constraint that the relating structure is an `IfcSpatialElement`. `IfcGeomodel` as an `IfcElement` (confirmed via schema query: `IfcGeomodel → IfcGeotechnicalAssembly → IfcGeotechnicalElement → IfcElement → IfcProduct`) is technically a valid `RelatedElement`. The BIM Corner citation supports this reading. The v1 critique was wrong on this point — v2's correction is schema-valid. This is not an open question; v2 is right here.

### D-3 (Sprint 3 risk): `IfcRelVoidsElement` and the host of `IfcEarthworksCut`

V2 §2.4 states `IfcEarthworksCut` voids `IfcGeotechnicalStratum` via `IfcRelVoidsElement`. The schema requires `IfcRelVoidsElement.RelatingBuildingElement` to be a subtype of `IfcElement`. `IfcGeotechnicalStratum → IfcGeotechnicalElement → IfcElement`: valid. But the spec in §6.5 describes cut solid construction in purely geometric terms (existing-TIN top face, proposed-TIN bottom face, side faces) without describing how the computed cut region maps to the `IfcRelVoidsElement` void. In IFC, `IfcRelVoidsElement` is a one-to-one relationship between one `IfcFeatureElementSubtraction` and one host element. If there are multiple distinct cut regions across a site (which is typical), each requires its own `IfcEarthworksCut` instance and its own `IfcRelVoidsElement`. The spec doesn't address the multi-region case. If a site has 12 disconnected cut regions, does the implementation create 12 `IfcEarthworksCut` entities? Or one? This needs an answer in the Sprint 3 task brief before the earthwork IFC agent starts.

### D-4 (Sprint 1 validation): `IfcProjectedCRS.VerticalDatum` attribute availability

Section 2.10 prescribes populating `IfcProjectedCRS.VerticalDatum`. `IfcProjectedCRS` in IFC 4.3 does have a `VerticalDatum` attribute, but it may not be present in all ifcopenshell wrappers for every schema version. The Sprint 1 tester should verify that `ifc_file.create_entity("IfcProjectedCRS", ..., VerticalDatum="NAVD88")` round-trips correctly before this is considered a solved spec point. If the attribute is absent in the active schema version (e.g., a pre-ADD2 schema), a fallback strategy is needed.

### D-5 (Design debt): Composite `IfcEarthworksFill` aggregation creates representation duplication

Section 2.5 describes a three-level `IfcEarthworksFill` hierarchy: slope fill entities + interior fill entity, aggregated into a group composite fill entity, which may itself aggregate into a site composite fill entity. The group composite in §6.3 is described as carrying both the proposed TIN and the composite fill solid. This means the proposed surface TIN appears as a representation on the group composite fill entity, while the individual slope fill entities each carry their own geometry. A viewer parsing this file will encounter the same geometric region represented multiple times (once on each slope fill, and once again on the composite). The spec does not address whether the slope fill entities carry their own geometric representations (which they should, for per-entity QTO) or whether they are geometry-free members of the composite. If they carry geometry, the composite's TIN will overlap them. This is a sprint-blocking design decision that the architect agent needs to resolve before the tool-dev agent writes `rebuild_group_surface`.

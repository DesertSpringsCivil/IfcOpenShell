# UI-Layer Critique: Saikei Grading & Earthwork Spec

**Reviewer:** saikei-blender-ui agent
**Date:** 2026-04-24
**Subject:** [Saikei_Grading_Earthwork_Spec.md](Saikei_Grading_Earthwork_Spec.md)
**Review axes:** Operators, panels, decorators, modals, property groups, keymaps — with headless / agent-driven usage as the critical lens.

Organized by the 10 axes requested. The spec is well-structured at the IFC and tool layers; most of the problems are concentrated in the UI layer, specifically around the headless axis.

---

## 1. Operator Inventory — Headless Equivalents

The spec names 13 operators in §8.2. The analysis below adds the implied operators the spec omits, assesses each against the headless axis, and flags splits that are needed.

### Surface operators

**`CIVIL_OT_surface_create_from_points`**
The spec says "import XYZ, CSV, or IFC TIN." Three different input sources in one operator is a smell — it forces a file-picker dialog path (ImportHelper) that an agent cannot drive. The spec should split this into:
- `CIVIL_OT_surface_create_from_csv` — file-picker operator (interactive only, fine)
- `CIVIL_OT_surface_create_from_xyz_array` — takes a numpy array or a list of (x, y, z) tuples via operator properties; no dialog; this is the headless entry point
- `CIVIL_OT_surface_create_from_ifc_tin` — reads an existing `IfcTriangulatedIrregularNetwork` step ID; no dialog

The underlying tool-layer call is `tool.Surface.build_tin_from_points(name, points, kind)` plus `tool.Surface.author_ifc_host(surface)` etc. An agent bypasses all three operators and calls those tool methods directly through `core.surface.create_surface_from_points(tool, name, points, kind)`. That core path exists per §7.1 — good. The split is about making the operator signatures unambiguous, not about adding a new compute path.

**`CIVIL_OT_surface_add_breakline`**
Described as "pick a 3D polyline in viewport." This is unambiguously modal — it requires the user to click on a Blender object in the viewport to identify the polyline. Red flag for headless. Required split:
- Keep the modal operator for interactive picking
- Add `CIVIL_OT_surface_add_breakline_by_guid` (or by IFC step ID) — takes the `IfcAnnotation` step ID or the Blender object name as an operator string property; calls `core.surface.add_breakline_to_surface(tool, surface_guid, breakline)` directly; no viewport interaction

Headless equivalent: `core.surface.add_breakline_to_surface(tool, surface_guid, breakline)` where `breakline` is a `Breakline` dataclass constructed in script. This is the path agents use.

**`CIVIL_OT_surface_set_boundary`**
Same pattern as above — "pick a 2D polygon." Requires modal or viewport-selection behavior for interactive use. Required split:
- Modal operator for interactive use
- `CIVIL_OT_surface_set_boundary_from_points` — accepts a coordinate list as a JSON string or Blender text-block reference; no modal; agents call `core.surface.set_surface_boundary(tool, surface_guid, polygon, kind)` directly

**`CIVIL_OT_surface_retriangulate`**
Pure data operation on an existing surface. No dialog, no viewport. Already a clean single-call wrapper around `core.surface.add_breakline_to_surface` / retriangulate path. An agent can call `tool.Surface.retriangulate(surface)` directly. No split needed, but the operator should accept the surface GUID as an operator property (not read from scene selection) so an agent could invoke it via `bpy.ops.civil.surface_retriangulate(surface_guid="...")` without a UI selection.

**`CIVIL_OT_surface_export_ifc`**
This is a pure data operation — it writes to IFC. Already headless-safe via `tool.Surface.author_ifc_tin_representation(surface)` etc. The operator just gates it behind the UI. No split needed; agents call the tool methods directly.

### Grading operators

**`CIVIL_OT_feature_line_create`**
"Draw a new feature line or convert mesh edge loop." The "draw" path is modal — same class of problem as PI picking. The "convert edge loop" path can be headless if it takes a Blender object name. Required split:
- `CIVIL_OT_feature_line_draw` — modal operator, interactive only (same pattern as `CIVIL_OT_pick_pi_from_viewport`)
- `CIVIL_OT_feature_line_from_object` — takes a Blender object name; extracts vertices; calls `tool.Grading.build_feature_line_from_vertices(...)`; headless-safe

Headless equivalent: construct `FeatureLine` dataclass directly, call `tool.Grading.author_ifc_group(...)` chain from core. The spec's `core.grading.create_grading_group` signature already accepts a `feature_line_guid` — that guid must come from somewhere. Agents construct the `FeatureLine` in script, call a tool method to author its `IfcAlignment`, and get back a GUID. That path needs to be explicitly documented on the tool layer, not buried inside the operator.

**`CIVIL_OT_feature_line_drape`**
Assign vertex elevations from a surface. Pure computation. Headless-safe if it takes surface and feature-line GUIDs as operator properties. No modal needed. The operator should not read from viewport selection.

**`CIVIL_OT_feature_line_edit_elevations`**
"Vertex-by-vertex elevation edit dialog." The word "dialog" implies a popup or panel interaction. This is interactive-only as described. Required split:
- Keep the dialog version for interactive use
- Add `CIVIL_OT_feature_line_set_elevations` — takes a JSON-serializable dict of `{vertex_index: elevation}` as an operator string property; calls `core.grading.edit_feature_line_elevations(tool, feature_line_guid, edits)`. This is the headless path. Agents construct the edits dict and call this directly, or skip the operator entirely and call `core.grading.edit_feature_line_elevations` directly.

**`CIVIL_OT_grading_create_group`**
"Prompts for name, target surface, interior fill." A dialog is implied. This is an interactive operator that collects multiple inputs from the user. The spec needs a non-modal version: `CIVIL_OT_grading_create_group` should accept `name`, `target_surface_guid`, and `interior_fill` as operator properties with defaults — standard Blender `invoke` dialog (via `wm.invoke_props_dialog`) for interactive use, but the same operator invoked with `EXEC_DEFAULT` and all properties set works headlessly. This pattern is common in Bonsai and does not require a split, but the spec needs to state explicitly that all three properties have defaults and that `EXEC_DEFAULT` is the headless invocation path.

**`CIVIL_OT_grading_create_criteria`**
Same pattern: name, target_kind, cut_slope, fill_slope, max_distance. These are all scalar/enum properties — no viewport interaction. One operator with `invoke_props_dialog` for interactive use; fully headless via `EXEC_DEFAULT` with all properties set. No split needed, but document the `EXEC_DEFAULT` path.

**`CIVIL_OT_grading_add_object`**
Applies criteria to feature line within a group. Takes three GUIDs. Pure data operation. Headless-safe with operator properties. No modal. Already described correctly.

**`CIVIL_OT_grading_rebuild_group`**
Pure computation. Headless-safe via operator property (group_guid). No modal.

### Earthwork operators

**`CIVIL_OT_earthwork_compute_volumes`**
"Pair two surfaces, compute and display cut/fill." The "pair two surfaces" step is ambiguous — does it use viewport selection or operator properties? It must be operator properties (existing_surface_guid, proposed_surface_guid, shrink_factor, swell_factor) for the headless path. If the spec intends a "click surface A, click surface B" interactive selection, that needs a modal picker that then passes GUIDs to the computation operator. The computation must be separated from the selection.

**`CIVIL_OT_earthwork_cutfill_map`**
Generates a Blender color-mesh overlay. This is inherently display-side — it produces a Blender mesh object. In headless mode there is no display, so this operator should be a no-op when `bpy.app.background` is True. The underlying `tool.Earthwork.build_cutfill_color_mesh(existing, proposed)` should still return the color data (per-triangle deltas on `VolumeResult.per_triangle_deltas`) even in background mode. The Blender mesh creation path is wrapped in a `not bpy.app.background` guard.

**`CIVIL_OT_earthwork_export_ifc`**
Pure data operation. Headless-safe.

### Implied operators the spec omits

The spec is silent on operators for several necessary interactions:

- `CIVIL_OT_surface_select` — set the active surface (for subsequent panel operations). Alignment has an equivalent via `active_alignment_id`. Surfaces need a parallel `active_surface_guid` on `CivilSurfaceProperties` and an operator to set it.
- `CIVIL_OT_surface_rename` — trivial but needed for panel completeness.
- `CIVIL_OT_surface_delete` — remove surface from IFC and Blender. Spec does not mention deletion.
- `CIVIL_OT_grading_remove_object` — remove a grading object from a group (the spec has add but not remove).
- `CIVIL_OT_grading_delete_group` — remove a grading group.
- `CIVIL_OT_grading_criteria_delete` — remove a reusable criteria template.
- `CIVIL_OT_feature_line_delete` — remove a feature line.
- `CIVIL_OT_surface_add_points` — add individual points to an existing surface (the spec covers initial creation but not incremental update).

All of these are single-call tool-layer wrappers with no modal concerns.

---

## 2. Modal Operators — Scripted Equivalents

Three implicit modals in the spec:

**Feature line drawing** (`CIVIL_OT_feature_line_draw`): will inherit `PolylineOperator` exactly as PI picking does. The headless equivalent is constructing `FeatureLine.vertices` directly in script and calling `tool.Grading.author_ifc_alignment_for_feature_line(feature_line)`. The spec must document that `tool.Grading` exposes this as a standalone method (not locked inside the operator), and that `core.grading` calls it so both paths reach the same IFC-authoring code.

**Breakline picking** (`CIVIL_OT_surface_add_breakline`): described as picking a 3D polyline in the viewport. Headless equivalent: pass breakline vertices as a Python list to `core.surface.add_breakline_to_surface`. Must be a documented tool-layer entry point.

**Surface boundary picking** (`CIVIL_OT_surface_set_boundary`): same as breakline picking. Headless equivalent: pass boundary polygon vertices to `core.surface.set_surface_boundary`.

**Feature line elevation editing** (`CIVIL_OT_feature_line_edit_elevations`): if this becomes a G-key grab mode (analogous to PI edit mode), it is a full modal operator. The spec hints at this with "vertex-by-vertex elevation edit dialog" but doesn't commit to a modal. Given the PI edit mode precedent, a grading G-key mode is likely in Sprint 2. If it goes modal, the headless equivalent is `core.grading.edit_feature_line_elevations(tool, feature_line_guid, edits)` where `edits` is a list of `(vertex_index, new_z)` tuples. This must be callable without a running Blender modal loop.

The pattern to follow is the one the spec itself describes in §7.1: every core function takes a pure-Python data argument. The modal operator is just a UI shell that collects that data interactively and hands it to the same core call. The spec should state this contract explicitly for every grading modal, the same way it documents `core.grading.edit_feature_line_elevations(tool, feature_line_guid, edits)`.

---

## 3. Property Groups — Naming Conventions

The spec correctly uses `CIVIL_OT_*` / `CIVIL_PT_*` operator and panel prefixes throughout §4.2. One violation: the spec uses bare Python class names `CivilSurface`, `FeatureLine`, `GradingCriteria`, `GradingObject`, `GradingGroup`, `VolumeResult` in §5. These are **tool-layer dataclasses**, not `bpy.types.PropertyGroup` subclasses, so the `Civil*Properties` naming convention does not apply to them — the dataclasses are fine as-is. However, the Blender scene-level property groups that will be needed (equivalent to `CivilAlignmentProperties`) are not named anywhere in the spec. They will need names. Proposed:

- `CivilSurfaceProperties` — scene-level, holds `active_surface_guid`, surface list display cache, visualization toggles
- `CivilGradingProperties` — scene-level, holds `active_group_guid`, `active_feature_line_guid`, `is_feature_line_edit_mode`, `feature_line_edit_alignment_id`
- `CivilEarthworkProperties` — scene-level, holds shrink/swell factor inputs, active volume result reference

No violations in the operator/panel naming the spec proposes. The missing piece is defining and naming these property groups.

---

## 4. Panels / UILists

### Naming
Panel names `CIVIL_PT_surface_panel`, `CIVIL_PT_grading_panel`, `CIVIL_PT_earthwork_panel` follow the convention. No naming violations.

UILists are not named in the spec. They will be needed:
- `CIVIL_UL_surfaces` — surface list in `CIVIL_PT_surface_panel`
- `CIVIL_UL_grading_groups` — group list in `CIVIL_PT_grading_panel`
- `CIVIL_UL_grading_objects` — per-group grading objects sub-list
- `CIVIL_UL_grading_criteria` — criteria list in `CIVIL_PT_grading_panel`

### Scene props vs. IFC query

This is the most important panel-architecture issue in the spec, and it is not addressed. The alignment module uses `CollectionProperty` on `bpy.types.Scene` (the `pis` collection, `display_rows` collection) to cache PI data. This is fast for interactive use but is a known headless liability: scene properties disappear when there is no Blender session, and they can become stale if the IFC file is modified outside the operator path.

For grading, the surface list and group list panels should be driven by **fresh IFC queries** (via `tool.Ifc.get().by_type("IfcGeotechnicalStratum")`, etc.) through a `data.py` caching layer — the same pattern as `bonsai/bim/module/alignment/data.py`. The scene-level properties (`CivilSurfaceProperties`) hold only the UI state (active index, edit mode flags, toggle states) — not the data list itself. The UIList's `draw_item` then reads from IFC via the data cache rather than from a `CollectionProperty`. This is critical for headless: a script that never enters a panel still has access to the same IFC-queried data. The spec should mandate this pattern explicitly for all three new panels.

---

## 5. Decorators (GPU Overlay)

The spec does not mention GPU decorators anywhere. This is a significant gap given that grading has richer overlay needs than alignment.

**Overlay candidates** in the grading workflow:
- Breaklines drawn on the TIN surface (colored edges, distinct from triangulation edges)
- Daylight lines computed from slope projection (the tie-to-grade result)
- Feature lines shown as 3D colored polylines distinct from ordinary mesh objects
- Cut/fill color bands on the TIN (the color mesh from `CIVIL_OT_earthwork_cutfill_map` is a Blender mesh object, but an overlay version would be more performant at interactive frame rates)
- Slope arrows or gradient annotation

The spec should add a `decorator.py` for each new module (`surface/decorator.py`, `grading/decorator.py`) following the `PIEditDecorator` pattern:
- `POST_VIEW` handler for 3D geometry (breaklines, daylight lines, feature line highlights)
- `POST_PIXEL` handler for HUD text (elevation labels, cut/fill totals at the cursor)
- GPU batch data via `gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")` for 3D lines
- `tool.Blender.validate_shader_batch_data()` before every GPU draw call (prevents crashes on stale batches)
- `tool.Blender.scale_font_size()` in POST_PIXEL handlers for DPI awareness

**Headless isolation** is already satisfied by the alignment decorator pattern: `__init__.py` registers the decorator with `if not bpy.app.background:` (see alignment `__init__.py` line 71-74). The same guard should wrap all GPU decorator registration in grading. The compute path (slope projection, TIN build) never touches the decorator — it runs whether or not Blender is rendering.

The spec should add a `§8.3 Decorators` section listing these overlays explicitly.

---

## 6. Add Element Dialog Integration

The spec is completely silent on Add Element dialog integration. Alignment integrates via representation templates that appear when `IfcAlignment` is selected in Bonsai's Add Element dialog. The grading module needs equivalent entry points.

Recommended additions:

- `IfcGeotechnicalStratum` — appears in the Add Element dialog when an `IfcGeomodel` or `IfcSite` is the active container; triggers `CIVIL_OT_surface_create_from_csv` or `CIVIL_OT_surface_create_from_xyz_array`
- `IfcEarthworksFill` — Add Element entry that creates a proposed surface shell (the IFC entity only, geometry filled in by grading group operations)
- `IfcEarthworksCut` — similarly
- `IfcGroup` with `ObjectType="GradingGroup"` — Add Element entry that triggers `CIVIL_OT_grading_create_group`

Without these hookups, grading entities can only be created through the new panels. Any user who follows the standard Bonsai Add Element workflow will not discover grading tools. More critically for agents: Bonsai's standard element-creation scripting path goes through the Add Element dialog's registered templates. If grading does not register there, agents using the standard Bonsai automation pattern will not find it.

---

## 7. T-Panel Toolbar Integration

The spec is silent on toolbar integration. Given the alignment precedent in `workspace.py`, the spec should either:

**Option A (shared):** Add grading/surface/earthwork operations to the existing `AlignmentTool` workspace under a "Site Grading" section in `_draw_sidebar`. This works for Sprint 1 when grading is tightly coupled to alignments (grading adjacent to a corridor). The `AlignmentTool.bl_label` would need to become "Civil" or "Saikei" to reflect broader scope.

**Option B (separate):** A new `CivilGradingWorkTool` class in a `bim/module/surface/workspace.py` (or shared `bim/module/civil/workspace.py`). This registers as a separate tool in the T-panel. The `bl_idname` would be `bim.grading_tool`. Cleaner separation, allows grading-specific keymaps without polluting alignment's keymap.

Option B is the right call for Sprint 2 when feature-line drawing (a modal tool) is introduced — modal tools in Blender need their own `WorkSpaceTool` with their own keymap definition. Alignment already has this: `AlignmentTool` with `bl_keymap = tool.Blender.get_default_selection_keypmap()`. Feature line drawing would override the left-click action in that keymap, and doing so inside the existing `AlignmentTool` would conflict with alignment PI picking.

The spec should prescribe Option B with `CivilGradingWorkTool` in `bim/module/surface/workspace.py`, separate from `AlignmentTool`.

---

## 8. Keymap Conflicts

The spec does not discuss keymaps at all. This is a problem for Sprint 2 and Sprint 3.

**Existing alignment keymaps:**
- G key: PI move in `CIVIL_OT_enter_pi_edit_mode` and PVI move in `CIVIL_OT_enter_pvi_edit_mode`
- Enter: confirm edit
- Escape: cancel edit

**Grading needs similar affordances for feature line elevation editing.** If grading's modal G-key elevation editing is active at the same time as alignment's PI edit mode, there is no direct conflict (they are separate operator loops). But if both tools are accessible from the same `WorkSpaceTool`, activating the G key in one context must not trigger the other tool's handler.

**Specific risks:**
- G (standard Blender grab) — alignment already overrides this in PI edit mode. If grading introduces a separate elevation-grab mode within the same workspace tool, both listen to G and the order of handler registration determines which fires first. Requires either separate workspace tools (Option B above, which resolves this) or explicit priority management via `PASS_THROUGH`.
- E (extrude in Blender mesh edit mode) — if grading borrows E for "edit elevation" in object mode, check against Bonsai's existing E bindings.
- B and Z — often used for selection box / zoom in Blender; grading should avoid these for any new binding.

The spec should add a keymap table for Sprint 2 modals, confirm they do not collide with alignment's existing G/Enter/Escape handlers, and specify that grading modals live inside `CivilGradingWorkTool`'s keymap context so they are inactive when the alignment tool is selected.

---

## 9. Property Caching Across Scenes

The spec does not address multi-scene behavior. The alignment module stores properties on `bpy.types.Scene` via `bpy.types.Scene.CivilAlignmentProperties = bpy.props.PointerProperty(...)`. This is per-scene.

**Impact on headless agents:** A headless script creates a single Blender session and loads one IFC file. The IFC file is not scene-scoped — it exists in `IfcStore`. The per-scene property (`CivilSurfaceProperties` etc.) would hold only UI state (active index, edit mode flags), which is acceptable since headless agents do not need UI state at all.

**The real risk** is if any core or tool code reads scene properties to find the active surface or active group. The pattern to forbid is: `context.scene.CivilSurfaceProperties.active_surface_guid` appearing in tool or core code. Tool and core code should take explicit GUIDs/IDs as function arguments, not read them from scene properties. Scene properties are the UI's way of passing selection to operators; they must not leak into the compute path.

The spec does not state this contract. It should add a note mirroring the alignment architecture: "Scene-level properties carry only UI state. All compute and IFC operations take explicit GUIDs or IFC step IDs as arguments."

For the multi-scene case (draft + published), grading properties living per-scene means the user must re-select the active surface in each scene. This is consistent with how alignment works (`active_alignment_id` is per-scene). An agent targeting a specific surface always passes the GUID explicitly, so multi-scene is irrelevant on the headless path.

---

## 10. Error Surfacing

The spec does not prescribe error propagation. This needs to be explicit because the interactive path and the headless path diverge here.

**What the spec should add:**

Tool-layer methods should raise named exceptions from a module-level exception hierarchy:
- `SaikeiGradingError` (base)
- `SaikeiSurfaceError(SaikeiGradingError)` — non-manifold TIN, no points inside boundary, etc.
- `SaikeiTriangulationError(SaikeiSurfaceError)` — CDT failure (degenerate input to Shapely/SciPy)
- `SaikeiDaylightError(SaikeiGradingError)` — slope projection cannot find daylight (max_distance exceeded, no intersection with target surface)
- `SaikeiVolumeError(SaikeiGradingError)` — prismoidal volume degenerate (zero-area overlap domain, non-overlapping surfaces)

**Interactive path (operator `_execute`):**
```python
try:
    result = core.grading.add_grading_object(tool, ...)
except SaikeiDaylightError as e:
    self.report({"ERROR"}, str(e))
    return {"CANCELLED"}
```
The operator `report({"ERROR"}, ...)` surfaces the error to the user via Blender's info/status bar.

**Headless path (agent script):**
The agent calls `core.grading.add_grading_object(tool, ...)` directly. `SaikeiDaylightError` propagates as a plain Python exception. The agent's `try/except` catches it. No `self.report()` is in the path.

**The key rule** the spec must state: core and tool code **never** calls `self.report()` (which requires an operator instance). Error messages are only strings on raised exceptions. The operator is the only place that converts a raised exception into a Blender `report()`. This is already the implicit pattern in the alignment module (`_invoke` catches `ValueError` and calls `self.report({"ERROR"}, str(e))`), but the grading spec should make it explicit and extend it with the named exception hierarchy.

---

## Summary of Named Issues and Recommended Additions

| # | Issue | Severity | Recommendation |
|---|-------|----------|----------------|
| 1a | `CIVIL_OT_surface_create_from_points` bundles three input sources | High — blocks headless | Split into `_from_csv`, `_from_xyz_array`, `_from_ifc_tin` |
| 1b | `CIVIL_OT_surface_add_breakline` is viewport-pick only | High | Add `_by_guid` headless variant; document tool-layer entry point |
| 1c | `CIVIL_OT_surface_set_boundary` is viewport-pick only | High | Add `_from_points` headless variant |
| 1d | `CIVIL_OT_feature_line_create` bundles draw + convert | High | Split into `_draw` (modal) and `_from_object` (headless) |
| 1e | `CIVIL_OT_feature_line_edit_elevations` is dialog-only | High | Add `_set_elevations` headless variant via operator properties |
| 1f | `CIVIL_OT_grading_create_group/criteria` imply dialogs | Medium | Document `EXEC_DEFAULT` invocation path explicitly |
| 1g | 8 obvious CRUD operators are missing entirely | Medium | Add the omitted delete/rename/add-point operators |
| 2 | Modal operators lack documented headless equivalents | High | Add "Headless path" note to each modal in spec §8.2 |
| 3 | Scene-level PropertyGroup names not defined | Medium | Add `CivilSurfaceProperties`, `CivilGradingProperties`, `CivilEarthworkProperties` |
| 4 | UIList names not defined | Low | Add `CIVIL_UL_surfaces`, `_grading_groups`, `_grading_objects`, `_grading_criteria` |
| 4b | Spec does not address IFC-query vs. scene-cache data sourcing | High | Mandate `data.py` caching layer; scene props = UI state only |
| 5 | No GPU decorator spec | Medium | Add §8.3 Decorators with breakline/daylight-line/HUD overlays; guard with `not bpy.app.background` |
| 6 | No Add Element dialog integration | Medium | Register `IfcGeotechnicalStratum`, `IfcGroup(GradingGroup)` in Bonsai's element templates |
| 7 | No T-panel toolbar spec | Medium | Prescribe `CivilGradingWorkTool` (Option B) to avoid keymap collision with `AlignmentTool` |
| 8 | No keymap table | Medium | Add keymap table for Sprint 2 modals; confirm G/Enter/Escape do not collide with alignment |
| 9 | No scene-property-vs.-IFC-query contract | High | Add rule: compute/IFC code never reads scene props; takes explicit GUIDs |
| 10 | No error propagation contract | High | Add named exception hierarchy; operators convert exceptions to `report()`; core/tool never call `report()` |

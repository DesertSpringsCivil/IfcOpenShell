# Saikei Civil — UI Implementation Spec (v2)

**Status:** Draft v2 — supersedes `Surface_Grading_UI_Spec.md` (v1)
**Target:** `saikei-dev` branch
**Layer:** Bonsai UI on top of completed `ifcopenshell.api.{surface,grading,earthwork}` and `bonsai.{core,tool}.{surface,grading,earthwork}`
**Companion docs:** `Saikei_Grading_Earthwork_Spec.md` (architectural), `SURFACES_GRADING_EARTHWORKS.md` (Phase 5 audit reference)

---

## §1 Purpose and Shipped State

v1 of this spec was authored before Phases 4–6 landed. It assumed greenfield. ~70% of v1's "to-build" inventory is shipped. v2 reframes around what exists today, what needs polish, and what genuinely remains.

The Phase 4–6 modules followed Bonsai conventions: panels live in the **Properties Editor → Scene → Bonsai tab carousel**, parented to Bonsai-owned `BIM_PT_tab_*` containers. Module files use the Bonsai-canonical names: `__init__.py`, `data.py`, `decorator.py`, `operator.py`, `prop.py`, `ui.py` (NOT `panel.py`). Operators inherit `(bpy.types.Operator, tool.Ifc.Operator)` and override `_execute()`. PropertyGroups are `Civil*Properties`.

### §1.1 Shipped inventory — `bim/module/surface/`

| Class | Kind | File | Line | Status |
|---|---|---|---|---|
| `CIVIL_OT_surface_create_from_points` | Operator | `surface/operator.py` | 59 | KEEP. File-picker `invoke()` already shipped (`surface/operator.py:158-164`); §5.1 work is the column-mapping kwargs + UI. |
| `CIVIL_OT_surface_retriangulate` | Operator | `surface/operator.py` | 167 | KEEP. |
| `CIVIL_OT_surface_set_boundary` | Operator | `surface/operator.py` | 217 | KEEP. Modal viewport-pick variant in §6.1. |
| `CIVIL_OT_surface_add_breakline` | Operator | `surface/operator.py` | 299 | KEEP. Modal viewport-pick variant in §6.1. |
| `CIVIL_PT_surface_creation` | Panel | `surface/ui.py` | 37 | KEEP. |
| `CIVIL_PT_surface_list` | Panel | `surface/ui.py` | 73 | KEEP. |
| `CIVIL_PT_surface_active` | Panel | `surface/ui.py` | 116 | KEEP. |
| `CIVIL_PT_surface_display` | Panel | `surface/ui.py` | 177 | KEEP. |
| `CivilSurfaceListItem` | PropertyGroup | `surface/prop.py` | 93 | KEEP. |
| `CIVIL_UL_surfaces` | UIList | `surface/prop.py` | 121 | KEEP. |
| `CivilSurfaceProperties` | PropertyGroup | `surface/prop.py` | 155 | EXTEND. Add `csv_column_map`, statistics-cache slots (§5.1). |
| `SurfaceData` | Data cache | `surface/data.py` | 34 | KEEP. |
| `SurfaceDecorator` | GPU decorator | `surface/decorator.py` | 45 | KEEP. EXTEND in §7 with slope-shading mode. |

All sub-panels are parented `bl_parent_id = "BIM_PT_tab_surface_modeler"` (cited at `surface/ui.py:45,81,124,187`).

**Missing from surface module:** rename/delete operators, viewport-pick modals for boundary and breakline, statistics sub-panel, CSV column-remap UI, slope/contour decorators (Phase 7c), water-drop / catchment / LandXML (Phase 7d).

### §1.2 Shipped inventory — `bim/module/grading/`

| Class | Kind | File | Line | Status |
|---|---|---|---|---|
| `CIVIL_OT_feature_line_create` | Operator | `grading/operator.py` | 55 | KEEP. |
| `CIVIL_OT_feature_line_drape` | Operator | `grading/operator.py` | 154 | KEEP. |
| `CIVIL_OT_feature_line_edit_elevations` | Operator | `grading/operator.py` | 232 | KEEP. Modal "G-key elevation" variant in §6.2. |
| `CIVIL_OT_grading_create_criteria` | Operator | `grading/operator.py` | 368 | KEEP. |
| `CIVIL_OT_grading_create_group` | Operator | `grading/operator.py` | 464 | KEEP. |
| `CIVIL_OT_grading_add_object` | Operator | `grading/operator.py` | 563 | KEEP. |
| `CIVIL_OT_grading_rebuild_group` | Operator | `grading/operator.py` | 635 | KEEP. |
| `CIVIL_PT_grading_feature_lines` | Panel | `grading/ui.py` | 37 | KEEP. |
| `CIVIL_PT_grading_criteria` | Panel | `grading/ui.py` | 111 | KEEP. |
| `CIVIL_PT_grading_groups` | Panel | `grading/ui.py` | 176 | KEEP. |
| `CIVIL_PT_grading_active_group` | Panel | `grading/ui.py` | 235 | KEEP. |
| `CIVIL_PT_grading_display` | Panel | `grading/ui.py` | 293 | KEEP. |
| `CivilGradingGroupItem` | PropertyGroup | `grading/prop.py` | 91 | KEEP. |
| `CivilGradingCriteriaItem` | PropertyGroup | `grading/prop.py` | 118 | KEEP. |
| `CivilGradingMemberItem` | PropertyGroup | `grading/prop.py` | 140 | KEEP. |
| `CivilGradingFeatureLineItem` | PropertyGroup | `grading/prop.py` | 151 | KEEP. |
| `CIVIL_UL_grading_groups` | UIList | `grading/prop.py` | 167 | KEEP. |
| `CIVIL_UL_grading_criteria` | UIList | `grading/prop.py` | 191 | KEEP. |
| `CIVIL_UL_grading_feature_lines` | UIList | `grading/prop.py` | 223 | KEEP. |
| `CIVIL_UL_grading_members` | UIList | `grading/prop.py` | 248 | KEEP. |
| `CivilGradingProperties` | PropertyGroup | `grading/prop.py` | 277 | KEEP. |
| `GradingData` | Data cache | `grading/data.py` | 35 | KEEP. |
| `GradingDecorator` | GPU decorator | `grading/decorator.py` | 55 | KEEP. EXTEND with stepped-offset preview in §6.2. |

All sub-panels parented `bl_parent_id = "BIM_PT_tab_grading"`.

**Missing from grading module:** feature-line delete, grading-object remove, criteria delete, viewport-modal feature-line draw, G-key elevation modal, stepped-offset operator + tool method, fillet operator + tool method, transition / high-low-point operators (Phase 7d).

### §1.3 Shipped inventory — `bim/module/earthwork/`

| Class | Kind | File | Line | Status |
|---|---|---|---|---|
| `CIVIL_OT_compute_earthwork_volumes` | Operator | `earthwork/operator.py` | 37 | KEEP. |
| `CIVIL_PT_earthwork_inputs` | Panel | `earthwork/ui.py` | 35 | KEEP. EXTEND with surface-dropdowns (§5.3). |
| `CIVIL_PT_earthwork_compute` | Panel | `earthwork/ui.py` | 78 | KEEP. |
| `CivilEarthworkProperties` | PropertyGroup | `earthwork/prop.py` | 71 | KEEP. EXTEND with last-run report fields if not already complete. |

Both sub-panels parented `bl_parent_id = "BIM_PT_tab_earthwork"`.

**Missing from earthwork module:** report-clear operator + results-delete operator (split per §11 vocabulary; see §5.3), surface dropdown-affordance on `CIVIL_PT_earthwork_inputs`, `EarthworkDecorator` (cut/fill color map), volume-label-at-point modal, volume-report export (Phase 7d).

### §1.4 Shipped inventory — `bim/module/alignment/`

`workspace.py` (cited `alignment/workspace.py:25-86`) is the canonical reference for §6's WorkSpaceTool work. The alignment module is the only Saikei module that ships a `WorkSpaceTool` today. Phases 4–6 deliberately deferred T-bar tools.

### §1.5 Core / Tool layer line counts (for sizing reviews)

| Module | Core | Tool |
|---|---|---|
| Surface | `core/surface.py` 312 | `tool/surface.py` 1549 |
| Grading | `core/grading.py` 493 | `tool/grading.py` 2028 |
| Earthwork | `core/earthwork.py` 190 | `tool/earthwork.py` 889 |

### §1.6 IFC API surface (canonical helper names — reference)

The `ifcopenshell.api.{surface,grading,earthwork}` modules ship with the helpers listed below — names verified against each module's `__init__.py` `__all__` block (May 2026). Spec sections below — and any operator implementations — must use these exact names. v1's spec used several stale or invented names. v2's earlier draft of this section also fabricated names (`add_breakline`, `set_outer_boundary`, `add_hole_boundary`, `add_void_boundary`, `retriangulate`, `add_bounding_box`, `set_z`, `compute_volume`, `apply_classification`, `edit_feature_line_elevations`, `assign_to_group`). **Verify every helper name against `__all__` before referencing it in implementation work.**

**`ifcopenshell.api.surface`** (7 helpers)

- `create_terrain` — top-level: author `IfcGeographicElement[PredefinedType=TERRAIN]` hosting a TIN. Attaches Body (Tessellation, `IfcTriangulatedIrregularNetwork`) + Box reps, `Pset_GeographicElementCommon` (`Status="NEW"`), `Pset_SaikeiGradingSurface`, OmniClass `22-07 31 13` Site Preparation (overridable). Spatially contained in `IfcSite`.
- `create_proposed_surface` — top-level: author `IfcEarthworksFill[PredefinedType=SUBGRADE]` hosting a TIN. Same Body+Box reps, `Pset_EarthworksFillCommon` (`Status="NEW"`), `Pset_SaikeiGradingSurface`, OmniClass `22-07 31 23` Fill (overridable). Spatially contained in `IfcSite`. **Authors `IfcEarthworksFill`, NOT `IfcGeographicElement` — see §4 for the Add Element implication.**
- `add_tin_representation` — lower-level Body Tessellation rep + `IfcTriangulatedIrregularNetwork` author; called by both `create_*` helpers.
- `add_bounding_box_representation` — lower-level Box rep author.
- `apply_saikei_pset` — `Pset_SaikeiGradingSurface` author (TriangulationTolerance, BreaklineCount, VertexCount, BoundaryPolygonReference).
- `add_breakline_annotation` — author a separate `IfcAnnotation` with `IfcPolyline` carrying `Pset_SaikeiBreaklineCommon` (Kind, Source, …); breaklines survive retriangulation by being top-level entities, not surface properties.
- `update_tin_representation` — in-place TIN replacement (retriangulation, breakline-add, boundary-edit). Old TIN entities garbage-collected when no references remain.

**`ifcopenshell.api.grading`** (8 helpers + 1 dataclass)

- `create_feature_line` — author `IfcAlignment` 3D `IfcIndexedPolyCurve` under the Axis subcontext, contained in `IfcSite`, with `Pset_SaikeiFeatureLineCommon` (IsClosed, Source, …).
- `create_grading_criteria_template` — author project-singleton `IfcPropertySetTemplate` for `Pset_SaikeiGradingCriteria` (six `IfcSimplePropertyTemplate` children incl. `IfcPropertyEnumeration` for TargetKind). Idempotent.
- `create_grading_group` — author entity pair: `IfcGroup[ObjectType="GradingGroup"]` + per-group composite `IfcEarthworksFill[SUBGRADE]`. Returns a `GradingGroupAuthoring` named tuple. Attaches `Pset_SaikeiGradingSource` (criteria reference, author, timestamp, target surface, interior-fill strategy) + OmniClass `22-07 31 23`.
- `assign_grading_criteria` — bind the criteria template to a group with concrete values via `IfcRelDefinesByTemplate`; authors a `Pset_SaikeiGradingCriteria` instance. Idempotent on re-assign.
- `add_slope_fill_to_group` — author `IfcEarthworksFill[PredefinedType=SLOPEFILL]` with Body TIN + Box reps, `Pset_EarthworksFillCommon`, OmniClass `22-07 31 23`; aggregates into the group's composite via `IfcRelAggregates`; assigns into `IfcGroup` via `IfcRelAssignsToGroup`.
- `add_interior_fill_to_group` — author `IfcEarthworksFill[PredefinedType=SUBGRADE]` (one per group, when `interior_fill != "none"`) with Body TIN + Box reps and OmniClass `22-07 31 16` Excavation and Fill (distinct from slope fills).
- `link_alignment_to_group` — attach `Pset_SaikeiGradingAlignment` (corridor linkage); valid on either `IfcGroup` or `IfcEarthworksFill`.
- `add_member_to_group` — lower-level `IfcRelAssignsToGroup` building block (used internally and for ad-hoc membership wiring).
- `GradingGroupAuthoring` — named tuple returned by `create_grading_group` (`group: IfcGroup`, `composite_fill: IfcEarthworksFill`).

**`ifcopenshell.api.earthwork`** (8 helpers — verified, was correct in earlier draft)

- `add_volume_solid_representation` — lower-level: author `IfcPolygonalFaceSet` (Closed=TRUE) Body / Tessellation rep; called by both `create_earthworks_*`.
- `create_earthworks_cut` — top-level: author `IfcEarthworksCut` with closed PolygonalFaceSet body, `Pset_EarthworksCutCommon` (`Status="NEW"`), OmniClass `22-07 31 16` (overridable). Identity placement, contained in `IfcSite`.
- `create_earthworks_fill` — top-level: author volume-bearing `IfcEarthworksFill` (PredefinedType in `BACKFILL`/`COUNTERWEIGHT`/`EMBANKMENT`(default)/`SUBGRADEBED`/`TRANSITIONSECTION`; Phase 2's `SLOPEFILL`/`SUBGRADE` are reserved for grading composition and emit `UserWarning`). `Pset_EarthworksFillCommon`, OmniClass `22-07 31 23`.
- `void_terrain` — author `IfcRelVoidsElement` cut→terrain. Idempotent for the same (cut, terrain) pair; retargeting raises `ValueError` (1:1 cardinality).
- `link_fill_to_cut` — author `IfcRelFillsElement` cut→fill. Mirror of `void_terrain` for the cut→fill half of the voiding chain. Phase 5 audit fix.
- `write_cut_quantities` — idempotent `Qto_EarthworksCutBaseQuantities` author (Length / Width / Depth, UndisturbedVolume / LooseVolume, Weight). Caller is responsible for `LooseVolume = UndisturbedVolume × SwellFactor` (computed by `tool.Earthwork.VolumeResult.loose_cut_m3`).
- `write_fill_quantities` — idempotent `Qto_EarthworksFillBaseQuantities` author (Length / Width / Depth, CompactedVolume / LooseVolume; no Weight, per buildingSMART standard). Caller is responsible for `LooseVolume = CompactedVolume / ShrinkFactor`.
- `apply_shrink_swell_pset` — idempotent `Pset_SaikeiGradingShrinkSwell` (ShrinkFactor / SwellFactor) author.

**Saikei-specific psets authored by these helpers** (reference list — do not author by hand):

| Pset | Authoring helper | Attached to |
|---|---|---|
| `Pset_SaikeiGradingSurface` | `apply_saikei_pset` (called by `create_terrain` / `create_proposed_surface`) | `IfcGeographicElement[TERRAIN]` / `IfcEarthworksFill[SUBGRADE]` surfaces |
| `Pset_SaikeiBreaklineCommon` | `add_breakline_annotation` | `IfcAnnotation` |
| `Pset_SaikeiFeatureLineCommon` | `create_feature_line` | `IfcAlignment` (feature-line variant) |
| `Pset_SaikeiGradingSource` | `create_grading_group` | `IfcGroup[GradingGroup]` |
| `Pset_SaikeiGradingCriteria` | `assign_grading_criteria` (bound via template) | `IfcGroup[GradingGroup]` |
| `Pset_SaikeiGradingAlignment` | `link_alignment_to_group` | `IfcGroup[GradingGroup]` or `IfcEarthworksFill` |
| `Pset_SaikeiGradingShrinkSwell` | `apply_shrink_swell_pset` | `IfcEarthworksCut` / `IfcEarthworksFill` |

`bonsai.core.earthwork.compute_earthwork_volumes` is the orchestration entry point. **Do not reference `compute_cut_fill_volumes`** — that name was in v1 and does not exist in shipped code.

These layers are out of scope for this spec except where Phase 7 introduces new tool methods (called out per phase).

---

## §2 Architectural Decisions (binding)

### §2.1 Property panels live in the Bonsai tab carousel

All property-style panels — lists, edit forms, settings, computed-result readouts — register in the **Properties Editor → Scene → Bonsai tab carousel**, parented to a Bonsai-owned `BIM_PT_tab_*` container. Required panel header:

```python
class CIVIL_PT_<purpose>(Panel):
    bl_label = "<human-readable>"
    bl_idname = "CIVIL_PT_<purpose>"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_<surface_modeler|grading|earthwork>"
    bl_options = {"DEFAULT_CLOSED"}  # optional
```

This is the pattern shipped in Phase 4–6 (citations in §1). All Phase 7 panel work extends or adds siblings to this set. **Do not relocate panels to the 3D-viewport N-panel and do not register top-level `BIM_PT_tab_*` panels from Saikei modules** — those parent panels are owned by `bonsai.bim.ui` and changing ownership breaks Bonsai's tab discovery.

The `should_show_panel` poll uses Bonsai's `tool.Blender.should_show_panel(context, "CIVIL", cls.bl_idname)` filter so the user's tab toggles continue to work uniformly.

### §2.2 Modal/viewport interactions live in `WorkSpaceTool`

Modal operators that need T-bar discoverability, gizmos, or modal-mode keymaps register through `bpy.types.WorkSpaceTool` per module:

- `surface_tool` — T-bar entry; activates breakline-pick, set-boundary, raise/lower modals.
- `grading_tool` — T-bar entry; activates feature-line-draw, G-key elevation, stepped-offset, fillet modals.
- `earthwork_tool` — T-bar entry; activates cut/fill probe / volume-label-at-point modal.

Each WorkSpaceTool subclass copies the `alignment/workspace.py:25-86` pattern: `bl_space_type = "VIEW_3D"`, `bl_context_mode = "OBJECT"`, `bl_idname = "bim.<module>_tool"` (matching alignment's `bim.alignment_tool`), an icon, a `bl_keymap` from `tool.Blender.get_default_selection_keypmap()`, and a `draw_settings()` method that renders compact controls in the tool header and expanded controls in the sidebar (matches alignment's `_draw_header` / `_draw_sidebar` split). Registration happens in the module `__init__.py` via `bpy.utils.register_tool(...)`.

WorkSpaceTool registrations are additive: they appear in the T-bar of the 3D viewport without displacing Blender's built-ins. The user's "T-bar mental model" is satisfied by these, not by panel relocation.

### §2.3 Out-of-scope placements

- **3D-viewport `Panel` subclasses (N-panel "CIVIL" tab):** out of scope. Phases 4–6 set the precedent against this and v2 maintains it.
- **`bl_space_type="VIEW_3D"` `Panel` subclasses anywhere:** not used; only WorkSpaceTool is permitted in viewport space.
- **Top-level Bonsai tabs owned by Saikei modules:** out of scope. Saikei sub-panels are children of `BIM_PT_tab_*` containers owned by `bonsai.bim.ui`.

### §2.4 Operator dispatch layering (no change)

Operators call `core.<module>.<fn>(tool.Ifc, tool.<Module>, ...)`. Core orchestrates; Tool implements. v1's §2.7 hierarchy is correct and shipped; v2 does not relitigate.

### §2.5 Decorator data-source rule (corrected from v1)

UILists draw from `data.py` caches that materialize from IFC plus the tool registry. Decorators (GPU overlays) read directly from the tool layer when geometry needs to track the IFC entity in real time, since `data.py` caches are intentionally coarse and refresh on a different cadence. This matches shipped `SurfaceDecorator` and `GradingDecorator` behavior.

---

## §3 Conventions

### §3.1 File layout (per module)

```
src/bonsai/bonsai/bim/module/{surface,grading,earthwork}/
├── __init__.py     # register/unregister
├── data.py         # IFC-backed cache; UIList feeds from this
├── decorator.py    # GPU overlay
├── operator.py     # CIVIL_OT_* operators
├── prop.py         # PropertyGroups + UILists + scene registration
├── ui.py           # CIVIL_PT_* panels
└── workspace.py    # WorkSpaceTool (Phase 7b — new file in surface/grading/earthwork)
```

The filename is `ui.py`, not `panel.py`. Phase 4–6 ships this; v1's "panel.py" wording was wrong.

### §3.2 Naming

| Type | Prefix | Example |
|---|---|---|
| Operator | `CIVIL_OT_<verb>_<object>` | `CIVIL_OT_surface_add_breakline` |
| Panel | `CIVIL_PT_<noun>` | `CIVIL_PT_surface_active` |
| UIList | `CIVIL_UL_<plural>` | `CIVIL_UL_grading_groups` |
| PropertyGroup | `Civil<Module>Properties` | `CivilSurfaceProperties` |
| WorkSpaceTool | `<module>_tool` (`bl_idname="bim.<module>_tool"`) | `surface_tool` |
| WorkSpaceTool class | `<Module>CivilTool` | `SurfaceCivilTool` |

**WorkSpaceTool `bl_idname` convention:** `bim.<module>_tool` matches shipped alignment (`alignment/workspace.py:28` → `bim.alignment_tool`). Earlier drafts of this spec used `bim.<module>_civil_tool`; that was inconsistent with alignment. The `_civil` lives in the **class name** (`SurfaceCivilTool`) for grep-friendliness and to disambiguate from any future Bonsai-core surface tool, but stays out of `bl_idname` to match the shipped pattern.

Never `BIM_*`, `BC_*`, or `SAIKEI_*`.

### §3.3 Operator base

```python
class CIVIL_OT_example(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "civil.example"
    bl_options = {"REGISTER", "UNDO"}

    def _execute(self, context):
        result = core.surface.do_thing(tool.Ifc, tool.Surface, ...)
        return {"FINISHED"}
```

Two parents: `bpy.types.Operator` and `tool.Ifc.Operator`. Override `_execute(context)`, never `execute(context)` — Bonsai's wrapper handles undo and IFC transaction state. Phase 4–6 shipped operators all match this; reaffirmed against `surface/operator.py:59`, `grading/operator.py:55`, `earthwork/operator.py:37`.

**CANCELLED footgun for test authors.** `tool.Ifc.Operator.execute` is decorated `@final` and **always returns `{"FINISHED"}`** regardless of what `_execute` returns. The inner `{"CANCELLED"}` is dropped at the wrapper boundary (cited at `bim/module/surface/operator.py:34-47` docstring; original mechanism in `tool/ifc.py:execute`). What headless callers actually observe when `_execute` returns `{"CANCELLED"}` after a `self.report({"ERROR"}, ...)`:

1. The `ERROR`-level report is pushed onto the Window Manager's reports list.
2. Blender re-raises that report as a Python `RuntimeError` from the `bpy.ops` boundary call.

**Tests must use `pytest.raises(RuntimeError)` to assert cancellation** — never `assert result == {"CANCELLED"}` (the `{"CANCELLED"}` set never reaches the caller). Tests that need a richer behavior assertion should also check "no IFC entity was authored" as a positive postcondition, not the operator return value.

**Cancellations must always be paired with `self.report({"ERROR"}, ...)` for tests to detect them via `pytest.raises(RuntimeError)`. A bare `return {'CANCELLED'}` with no error report is silently swallowed** — the `@final` wrapper still returns `{"FINISHED"}`, no `ERROR` report is pushed onto the WM, and Blender raises nothing at the `bpy.ops` boundary. The cancel becomes invisible to both interactive users and tests.

### §3.4 Scene-properties-vs-compute-path rule

PropertyGroups attached to `bpy.types.Scene` carry only UI state: active item indices, edit-mode flags, viewport toggles, transient form-input scratch values. **Core and tool code never read scene properties.** Operators capture scene-prop values, then pass them as explicit arguments to `core.<module>.*`. This rule held in alignment, surface, grading, and earthwork; it stays.

### §3.5 Modal vs `EXEC_DEFAULT` operators

Every modal operator must have a headless sibling (or a single operator with both `invoke()` and `execute()` paths) so tests, Cowork, and agents can drive it without a viewport. The convention: properties on the operator carry all modal-captured values; `invoke()` populates them from viewport interaction; `execute()`/`_execute()` runs from those properties unchanged. Where an `invoke` and `execute` path can't share one operator class cleanly, ship a `_from_data` sibling.

**`_from_data` sibling — same class, not a separate operator.** The `_from_data` suffix in this spec refers to a property-driven entry path on the **same operator class**, not a distinct second class. Concretely: the modal `invoke()` populates the operator's properties from viewport interaction (mouse picks, drags, modal modal-keymap entries); `EXEC_DEFAULT` callers populate the same properties from kwargs; `_execute()` is the shared body driven entirely by those properties. Tests drive the headless path with `bpy.ops.civil.<op>("EXEC_DEFAULT", **props)` and never enter `invoke()`. This matches the shipped `CIVIL_OT_feature_line_create` pattern (`grading/operator.py:55`) — one class, `invoke()` opens a file selector and stores the path on `self.csv_filepath`, `_execute()` reads `self.csv_filepath` regardless of how it got there. Use that operator as the canonical reference for new modals.

### §3.6 Decorator registration

Decorators install their handler on `register()` and remove it on `unregister()`. They read from the tool layer (per §2.5). Decorators do not import core. `SurfaceDecorator` and `GradingDecorator` (cited in §1) are reference implementations.

### §3.7 Data cache (`data.py`)

Each module has a singleton class (`SurfaceData`, `GradingData`, ...) with `is_loaded`, `data: dict`, `load()` and `purge()` classmethods. UIList items rebuild from this. Cache invalidation hooks fire on `save_post`, `load_post`, and after operators that change IFC. Ship Phase 7 features the same way.

### §3.8 Test layout

Per `.claude/CLAUDE.md` (Phase 4/5/6 module note), tool + operator tests for surface / grading / earthwork live in:

- `test/tool/test_surface.py`
- `test/tool/test_grading.py`
- `test/tool/test_earthwork.py`

The `test/bim/module/{surface,grading,earthwork}/` directories are blocked by an env-level `pytest-bdd` / `parse-type` issue in `test/bim/conftest.py`. Phase 7 tests stay in `test/tool/` for the same reason. **Forward-compat note:** when the upstream conftest issue is fixed, operator tests should migrate to `test/bim/module/{module}/test_<module>_operators.py` (matches alignment's layout cited in CLAUDE.md). Tool-pure-math tests stay in `test/tool/`. Keep test class names module-scoped so the move is mechanical.

### §3.9 Headless demo scripts

Tier-level demo scripts (e.g. `tier1_demo.py`) call `ifcopenshell.api.<module>.*` directly — **not** `bonsai.core.<module>.*`. The reason: `bonsai.core.*` dispatches to `bonsai.tool.*`, which imports `bpy`. A "headless" demo that pulls in `bpy` fails outside Blender's interpreter. Use the IFC-API surface for the headless path; use Bonsai for the in-Blender flow.

---

## §4 Add Element Hooks

Bonsai's "Add Element" dialog dispatches to module-defined operators based on IFC class + predicate. v1's hook list contained classes that don't make sense ergonomically (bare `IfcEarthworksFill`, `IfcEarthworksCut` — these are derived outputs, not user inputs) or that aren't part of Saikei's authoring surface (`IfcGeotechnicalStratum` — not in shipped Phase 1–6 scope). Per the IFC agent's findings, the corrected set:

| IFC class / predicate | Operator | Notes |
|---|---|---|
| `IfcGeographicElement[PredefinedType=TERRAIN]` | `civil.surface_create_from_points` | Parallel Add Civil Element menu invokes the operator's existing file-picker `invoke()` (`surface/operator.py:158-164`). |
| `IfcGroup[ObjectType="GradingGroup"]` | `civil.grading_create_group` | The grading-group container, not its members. |
| `IfcAlignment` (feature-line variant) | `civil.feature_line_create` | Disambiguate via `tool.Grading.is_feature_line_alignment(alignment)` (cited `tool/grading.py:1268`). Saikei feature lines and standard horizontal alignments share `IfcAlignment`; the `Pset_SaikeiFeatureLine` marker distinguishes them. |

**Excluded from Add Element (deliberate):**

- **`IfcEarthworksFill[SUBGRADE]` (proposed surfaces):** `ifcopenshell.api.surface.create_proposed_surface` authors `IfcEarthworksFill[PredefinedType=SUBGRADE]` (verified at `surface/create_proposed_surface.py:111-115`), **not** `IfcGeographicElement` as v1 of this spec assumed. The same predefined-type / class pair is also produced by `ifcopenshell.api.grading.add_interior_fill_to_group` for in-group interior fills (verified in §1.6). An Add Element hook keyed on `IfcEarthworksFill[SUBGRADE]` therefore cannot disambiguate "user wants a top-level proposed surface" from "user wants an interior fill belonging to a specific grading group" without inspecting the parent context, which Add Element does not pass through. **Decision: proposed surfaces are created exclusively via the surface module's `CIVIL_PT_surface_creation` panel (`+ Create Proposed Surface` button), bypassing Add Element.** Interior fills stay owned by the grading-group panel's flow (`CIVIL_OT_grading_add_object` and friends). This is the safer and clearer choice; a SUBGRADE-disambiguation predicate would be fragile and surprising.
- **`IfcEarthworksFill[volume-bearing]` and `IfcEarthworksCut`:** outputs of `CIVIL_OT_compute_earthwork_volumes`. Not user-authored entry points.
- **`IfcGeotechnicalStratum`:** not in Phase 1–6 scope. Re-evaluate when stratum modeling lands.
- **`IfcGradingObject` (member of a group):** users add via the grading-group panel's `+` button (`CIVIL_OT_grading_add_object`), not via Add Element. Reachable through the workflow already.

The Add Element hooks are wired in each module's `__init__.py` register() block. None are wired today — this is Phase 7a work.

**Implementation note — strategy is (c), parallel menu, by default.** Bonsai's Add Element dispatch lives in `bim/module/root/operator.py` and keys exclusively on `ifc_class` + `ifc_predefined_type`. It does **not** support Pset-based predicates today. Saikei feature lines disambiguate from standard transportation alignments via `Pset_SaikeiFeatureLineCommon` — there is no `PredefinedType` difference between the two. Therefore the (`ifc_class`, `ifc_predefined_type`) tuple alone cannot route an `IfcAlignment` Add Element invocation to either `civil.feature_line_create` or the existing transportation-alignment path; some out-of-band signal is required.

The default plan for Phase 7a is **(c) parallel "Add Civil Element" menu** in the Properties → Bonsai tab carousel that bypasses root's dispatch entirely. The menu lists `Terrain`, `Grading Group`, and `Feature Line` and dispatches each entry to the correct `civil.*` operator with no class+predicate ambiguity. This avoids touching Bonsai-owned root module code, ships behind Saikei's existing panel surface, and keeps the user's discovery path adjacent to the rest of the civil module.

Options (a) extending root's dispatch with a Saikei-aware branch and (b) a `bpy.app.handlers`-style post-add callback are both **deferred to future work, contingent on root-module changes shipping upstream.** If Bonsai later adds Pset-based predicates or a module-pluggable hook registry to the root operator, Saikei can revisit. Until then, do not patch `bim/module/root/`.

The §4 hook table above remains canonical for the operator-target mapping — only the dispatch mechanism changes from "wire into root" to "ship a parallel menu."

---

## §5 Phase 7a — Polish & Housekeeping

**Goal:** close the gaps in the shipped Phase 4–6 modules and ship the demo. No new modal interactions; no new analyses. This is the "stop tripping over rough edges" tier.

**Acceptance gate:** end-to-end pad-grading flow runs cleanly in interactive Blender and via `tier1_demo.py` (headless), with rename/delete operators reachable from each panel.

### §5.1 Surface module

**New operators (in `surface/operator.py`):**

| Operator | Purpose |
|---|---|
| `CIVIL_OT_surface_rename` | Rename selected surface (active UIList row); EXEC + dialog form. |
| `CIVIL_OT_surface_delete` | Delete selected surface; confirms; removes IFC entity, unlinks Blender object. |
| `CIVIL_OT_surface_select` | Select the Blender object backing the active UIList row (for camera-frame). |

**`CIVIL_OT_surface_create_from_points` extension:**

The file-picker `invoke()` path is **already shipped** at `surface/operator.py:158-164` using `context.window_manager.fileselect_add(self); return {"RUNNING_MODAL"}` (the canonical Blender file-selector idiom — `bpy.ops.wm.url_open` is for URLs in a browser, not files, and is not used here). Do not re-do this work. The Phase 7a extension is the column-mapping path: `invoke()` already opens the file dialog; what's missing is the column-remap kwargs in the tool method and the UI affordances that drive them.

**Tool method extension** (existing function, add kwargs — do **not** introduce a new function):

The shipped signature is `tool.Surface.load_points_from_csv(filepath: str) -> np.ndarray` (`tool/surface.py:676`, declared `@staticmethod`). Extend in-place; **keep the `@staticmethod` decorator** — do not silently convert to `@classmethod`:

```python
@staticmethod
def load_points_from_csv(
    filepath: str,
    columns: tuple[int, int, int] = (0, 1, 2),
    skip_header_rows: int = 0,
) -> np.ndarray:
    ...
```

Defaults preserve current behavior (column order `x,y,z`; no skip). The existing call sites and the shipped 155-tool-test surface stay green untouched. CSV-column-remap UI lives on `CIVIL_PT_surface_creation` as a collapsible "Column Mapping" sub-section that reads/writes `props.csv_column_map` (new `IntVectorProperty(size=3)` plus `skip_header_rows: IntProperty`); the operator threads both kwargs through into `tool.Surface.load_points_from_csv(self.csv_filepath, columns=tuple(props.csv_column_map), skip_header_rows=props.skip_header_rows)`. Return type stays `np.ndarray` to avoid forcing the caller to convert.

**New panel:**

| Panel | Purpose |
|---|---|
| `CIVIL_PT_surface_statistics` | Read-only TIN stats: triangle count, area, min/max/mean elevation, node count, breakline count, boundary closed/open. Pulls from `SurfaceData`; new keys cached on `SurfaceData.load()`. |

Parented to `BIM_PT_tab_surface_modeler`.

**Add Civil Element menu entry:** `Terrain` → `civil.surface_create_from_points` (the operator's existing file-picker `invoke()` runs; no new dispatch wiring required). Per §4, Saikei ships a parallel menu rather than patching root's Add Element dispatch.

### §5.2 Grading module

**New operators (in `grading/operator.py`):**

| Operator | Purpose |
|---|---|
| `CIVIL_OT_feature_line_delete` | Delete selected feature line; unregisters from `tool.Grading.iter_registered`, removes IFC, unlinks Blender curve. |
| `CIVIL_OT_grading_remove_object` | Remove selected grading-object from the active group (dual of `CIVIL_OT_grading_add_object`). |
| `CIVIL_OT_grading_delete_criteria` | Delete a criteria template; refuses if any grading object references it (raise `BlockedByDependentError`; the operator's `_execute()` catches and translates to `self.report({"ERROR"}, str(exc))` + `return {"CANCELLED"}` per §3.3). |

**New exception class.** `BlockedByDependentError` does not exist today. Define it in `tool/grading.py` alongside the existing `SaikeiGradingError` / `SaikeiSlopeProjectionError` hierarchy (cited `tool/grading.py:109,119`):

```python
class BlockedByDependentError(SaikeiGradingError):
    """Raised when an operation is refused because another entity
    depends on its target (e.g., deleting a criteria template that
    is still referenced by a grading object). The operator layer
    catches this, reports it via self.report({"ERROR"}, ...), and
    returns {"CANCELLED"} per §3.3."""
```

Tool methods raise it; operators catch alongside the existing `SaikeiGradingError` in their `except` blocks.

**Add Civil Element menu entries:** `Feature Line` → `civil.feature_line_create`; `Grading Group` → `civil.grading_create_group`. Per §4, the parallel menu sidesteps the root-module ambiguity that `Pset_SaikeiFeatureLineCommon`-only disambiguation would have created (root's Add Element keys on `ifc_class` + `ifc_predefined_type` only).

### §5.3 Earthwork module

**New operators (in `earthwork/operator.py`):**

| Operator | Purpose |
|---|---|
| `CIVIL_OT_earthwork_clear_report` | **Clear** per §11 vocabulary: zeros `last_cut_m3` / `last_fill_m3` / `last_run_*` fields on `CivilEarthworkProperties`. **No IFC change** — UI-state reset only. |
| `CIVIL_OT_earthwork_delete_results` | **Delete** per §11 vocabulary: removes `IfcEarthworksCut` + `IfcEarthworksFill` entities authored on prior runs (and their `IfcRelVoidsElement` / `IfcRelFillsElement` chains); unlinks Blender objects. **Destructive — IFC change.** Confirms via `bl_options = {"REGISTER", "UNDO", "INTERNAL"}` + a `bpy.ops.ui.confirm` prompt before authoring. |

The earlier draft's single `CIVIL_OT_earthwork_clear_results` conflated both semantics, which §11's "Clear vs. Delete" distinction explicitly forbids.

**`CIVIL_PT_earthwork_inputs` extension:**

The shipped `existing_surface_guid` and `proposed_surface_guid` are `StringProperty`s on `CivilEarthworkProperties` (per `earthwork/prop.py:79-91`); the operator reads from the scene props per §3.4. **Keep them as `StringProperty`s — do not change the type.** Add a UI dropdown affordance over the canonical `StringProperty`: a panel-side `EnumProperty` (or `prop_search` against a UIList) whose `update` callback writes the resolved GUID back into the existing `StringProperty`. This is a pure UI affordance; the operator's read path is unchanged.

New tool methods (UI-side enumeration; do not change the operator contract):

- `tool.Surface.iter_surfaces() -> Iterator[tuple[str, int]]` — yields `(name, ifc_id)` for terrain-typed `CivilSurface`s only.
- `tool.Surface.iter_proposed_surfaces() -> Iterator[tuple[str, int]]` — yields `(name, ifc_id)` for proposed-typed surfaces (including grading-group composites).

The dropdown `enum_items` callback resolves these to `(identifier, name, description)` tuples per Blender API; on `update` it sets `props.existing_surface_guid` / `props.proposed_surface_guid` from the IFC entity's `GlobalId`.

**Decorator (new file `earthwork/decorator.py`):**

`EarthworkDecorator` — colors cut and fill solids in the viewport (red ramp for cut depth, blue ramp for fill depth). **Data source: `CivilEarthworkProperties.last_cut_m3` / `last_fill_m3` / related `last_run_*` cached fields** (already shipped per `earthwork/prop.py:147+` and CLAUDE.md). The decorator reads from scene props for display state — this is the documented exception to §2.5's "decorators read tool, not scene" rule, since these are UI-cached compute results, not source-of-truth geometry. The geometry the decorator overlays comes from the `IfcEarthworksCut` / `IfcEarthworksFill` entities themselves (via `tool.Ifc.get_object()`); only the magnitude-to-color mapping reads the scene-cached totals. Toggle on `CivilEarthworkProperties.show_cut_fill_overlay: BoolProperty`. Matches `SurfaceDecorator` / `GradingDecorator` registration pattern otherwise.

### §5.4 Tier 1 demo (`tier1_demo.py`)

A headless Python script that exercises the end-to-end flow without Blender, using **only `ifcopenshell.api.*` calls** (per §3.9). All names below are verified against the §1.6 canonical list.

```python
# Section A — bootstrap
1. ifc = ifcopenshell.file(schema="IFC4X3_ADD2")
   ifcopenshell.api.unit.add_si_unit(...) + assign_unit(...)
   project = ifc.create_entity("IfcProject", ...)
   site = ifc.create_entity("IfcSite", ...) + IfcRelAggregates project→site
   # georef omitted; production projects use ifcopenshell.api.georeference.add_georeferencing
   # For Tier 1 the demo authors in the local engineering frame only —
   # this is the documented contract. Do NOT ship a hand-authored
   # IfcMapConversion stub in the demo; an incomplete georef record is
   # worse than none, and the API helper above is the canonical path
   # for production callers.

# Section B — terrain
2. eg_points = _load_csv("docs/grading/examples/tier1_terrain.csv")
   eg_triangles = _delaunay_xy(eg_points)        # small inline helper, ~15 lines
   terrain = ifcopenshell.api.surface.create_terrain(
       ifc, name="Existing Ground",
       points=eg_points, triangles=eg_triangles,
   )
   ifcopenshell.api.surface.add_breakline_annotation(
       ifc, site=site, polyline=[...], name="Centerline", kind="standard",
   )

# Section C — grading
3. feature_line = ifcopenshell.api.grading.create_feature_line(
       ifc, name="Pad perimeter",
       vertices=[(20,20,100),(30,20,100),(30,30,100),(20,30,100)],
       closed=True,
   )
4. template = ifcopenshell.api.grading.create_grading_criteria_template(ifc)
5. grading = ifcopenshell.api.grading.create_grading_group(
       ifc, name="Pad Grading",
       target_surface=terrain, interior_fill="flat",
   )
6. ifcopenshell.api.grading.assign_grading_criteria(
       ifc, grading.group, template,
       target_kind="surface", target_reference=terrain.GlobalId,
       cut_slope=2.0, fill_slope=3.0,
   )
7. # Slope ribbon + interior fill: hand-author the triangulation here
   #   (Bonsai's tool.Grading does this in production; the demo computes
   #   a closed-form 4-triangle ribbon for the rectangular pad).
   slope_pts, slope_tris = _build_pad_slope_ribbon(...)   # inline ~25 lines
   ifcopenshell.api.grading.add_slope_fill_to_group(
       ifc, grading.group, grading.composite_fill,
       name="Pad slope", points=slope_pts, triangles=slope_tris,
       feature_line=feature_line,
   )
   interior_pts, interior_tris = _triangulate_pad_interior(...)  # inline ~10 lines
   ifcopenshell.api.grading.add_interior_fill_to_group(
       ifc, grading.group, grading.composite_fill,
       points=interior_pts, triangles=interior_tris,
   )

# Section D — earthwork
8. # Prismoidal volume math: inline helper (~40 lines) — see note below.
   cut_volume, fill_volume, cut_solid, fill_solid = _compute_volumes_headless(
       eg_points, eg_triangles,         # existing
       slope_pts + interior_pts,        # proposed
       slope_tris + interior_tris,
   )
9. cut = ifcopenshell.api.earthwork.create_earthworks_cut(
       ifc, name="Pad excavation",
       points=cut_solid.points, faces=cut_solid.faces,
       predefined_type="EXCAVATION",
   )
   ifcopenshell.api.earthwork.void_terrain(ifc, cut, terrain)
   # Derive Length/Width/Depth from the cut solid's vertex AABB.
   # tool.Earthwork.ClosedSolid carries .points: np.ndarray (N,3) and
   # .faces; no bbox attributes today, so compute inline.
   _mins = cut_solid.points.min(axis=0)
   _maxs = cut_solid.points.max(axis=0)
   _length, _width, _depth = (_maxs - _mins).tolist()
   ifcopenshell.api.earthwork.write_cut_quantities(
       ifc, cut,
       length=_length, width=_width, depth=_depth,
       undisturbed_volume=cut_volume,
       loose_volume=cut_volume * 1.25,            # SwellFactor
   )
10. fill = ifcopenshell.api.earthwork.create_earthworks_fill(
        ifc, name="Pad fill",
        points=fill_solid.points, faces=fill_solid.faces,
        predefined_type="EMBANKMENT",
    )
    ifcopenshell.api.earthwork.link_fill_to_cut(ifc, cut, fill)
    _fmins = fill_solid.points.min(axis=0)
    _fmaxs = fill_solid.points.max(axis=0)
    _flength, _fwidth, _fdepth = (_fmaxs - _fmins).tolist()
    ifcopenshell.api.earthwork.write_fill_quantities(
        ifc, fill,
        length=_flength, width=_fwidth, depth=_fdepth,
        compacted_volume=fill_volume,
        loose_volume=fill_volume / 0.92,           # ShrinkFactor
    )
11. ifcopenshell.api.earthwork.apply_shrink_swell_pset(
        ifc, cut, shrink_factor=0.92, swell_factor=1.25,
    )
    ifcopenshell.api.earthwork.apply_shrink_swell_pset(
        ifc, fill, shrink_factor=0.92, swell_factor=1.25,
    )

# Section E — write
12. ifc.write("docs/grading/examples/tier1_demo.ifc")
```

**Inline `_compute_volumes_headless` — acknowledgment.** This duplicates ~40 lines of TIN-to-TIN prismoidal math that already lives in `bonsai.tool.earthwork`. Two reasons we accept the duplication for Tier 1:

1. **§3.9 rule** says headless demos call `ifcopenshell.api.*` directly, not `bonsai.core.*` or `bonsai.tool.*`. Even though `tool/earthwork.py` does not actually import `bpy` (verified May 2026 — no `import bpy` line; the docstring's mention is aspirational), importing `bonsai.tool.earthwork` still triggers `bonsai/__init__.py` which conditionally imports bpy when present. A truly stand-alone tier-1 script must not bring `bonsai` into the import graph.
2. **Documentation value.** The demo doubles as a worked example of the IFC API for non-Bonsai consumers (e.g., a vanilla Python script using IfcOpenShell). Inlining the volume math makes the script self-explanatory; readers see the math, not a `tool.Earthwork.compute(...)` opaque call.

The alternative — extracting the prismoidal math from `tool.Earthwork` into a bpy-free helper module like `bonsai.utils.earthwork_math` (or `ifcopenshell.util.earthwork`) — is **not** required for Tier 1, but is a reasonable Phase 7c+ refactor that would let the demo `import` the math instead of inlining it. Tracked as a non-blocking follow-up; do not gate Tier 1 on it.

Companion CSV fixture at `docs/grading/examples/tier1_terrain.csv`. **Reference IFC committed at `docs/grading/examples/tier1_demo.ifc`** — checked into version control. Regenerate `tier1_demo.ifc` whenever any `ifcopenshell.api.{surface,grading,earthwork}` helper changes its output schema or argument signature. Run `python src/bonsai/scripts/tier1_demo.py docs/grading/examples/tier1_demo.ifc` to refresh; the regenerated file is committed in the same PR as the API change.

`tier1_demo.py` lives at `src/bonsai/scripts/tier1_demo.py` (alongside other Bonsai scripts) and is wrapped as `test/integration/test_tier1_demo.py` for CI. The integration test:

- Imports the module and runs `main()` to a temp file.
- Diffs the temp output against `docs/grading/examples/tier1_demo.ifc` using **structural equivalence**, not byte equality (IFC `GlobalId`s and timestamps drift on each run). Specifically: assert entity counts per `IfcEntity` class fall within expected ranges, and run schema validation via `ifcopenshell.validate` (no schema errors). A small whitelist of allowed deltas (e.g., header timestamp) is acceptable; treat unexpected entity-count drift as a test failure that flags an API change for review.
- Re-running `tier1_demo.py` and committing the regenerated `tier1_demo.ifc` is part of the same PR that introduced the API change.

### §5.5 Phase 7a deliverables checklist

- [ ] Surface: 3 new operators, 1 new tool method, 1 new panel, CSV column-remap UI.
- [ ] Grading: 3 new operators.
- [ ] Define `BlockedByDependentError` in `tool/grading.py` (subclass of `SaikeiGradingError`, per §5.2).
- [ ] Earthwork: 2 new operators (`_clear_report` + `_delete_results`, split per §11), 2 new tool methods, dropdown-affordance over the existing `StringProperty` inputs, `EarthworkDecorator`.
- [ ] Add Civil Element parallel menu wired in the surface / grading / earthwork module `__init__.py` files (per §4 — root-module dispatch is deferred).
- [ ] `tier1_demo.py` + CSV fixture + reference IFC + integration test.
- [ ] Create `docs/grading/examples/` directory; commit `tier1_terrain.csv` (sample fixture, ~30 points) alongside the reference IFC.
- [ ] All tests green via the canonical commands in CLAUDE.md.
- [ ] Manual sign-off (one-time, end of phase) per §10.

---

## §6 Phase 7b — WorkSpaceTool & Modals

**Goal:** the T-bar mental model. Each module gets a WorkSpaceTool entry; modal/viewport-pick interactions hang off those tools.

**Acceptance gate:** each module's WorkSpaceTool appears in the 3D-viewport T-bar; activating it enables the keymap for that module's modal operators; each modal operator has a `_from_data` headless sibling driven by a unit test.

**Gizmo note:** the alignment WorkSpaceTool (`alignment/workspace.py`) ships with `bl_widget = None` — no gizmo group wired. Phase 7b matches that posture: keymap-driven modals only, no gizmos. Adding gizmos requires a separate `bpy.types.GizmoGroup` subclass per tool plus `bl_widget = "<gizmo_group_idname>"` — this is deferred to a future phase, not part of 7b's acceptance.

Reference for all three: `bim/module/alignment/workspace.py:25-86` (`AlignmentTool`).

### §6.1 Surface — `surface_tool`

**File:** `bim/module/surface/workspace.py` (new).

```python
class SurfaceCivilTool(WorkSpaceTool):
    bl_space_type = "VIEW_3D"
    bl_context_mode = "OBJECT"
    bl_idname = "bim.surface_tool"   # matches alignment's bim.alignment_tool naming
    bl_label = "Surface"
    bl_description = "Place breaklines, set boundaries, and raise or lower surfaces."
    bl_icon = "MESH_GRID"
    bl_widget = None
    bl_keymap = tool.Blender.get_default_selection_keypmap()
    # draw_settings() splits header (compact) and sidebar (expanded), per alignment.
```

**Modal operators activated by this tool:**

| Operator | Modal behavior |
|---|---|
| `CIVIL_OT_surface_pick_breakline` | Polyline-pick: click to add vertex, Enter to commit, Esc to cancel. On commit, calls a shared `_apply()` that authors the breakline. Also exposes `_from_data` sibling that takes a `polyline_object_name: StringProperty` for headless use. |
| `CIVIL_OT_surface_pick_boundary` | Closed-polygon-pick variant; same `invoke()` / `_from_data` split. |
| `CIVIL_OT_surface_raise_lower` | Mouse-Y-drag raises/lowers selected surface uniformly. Numeric entry overrides drag. Headless `_from_data` takes `surface_guid: StringProperty` (identifier — required so the headless path knows which surface to mutate without a viewport selection) and `delta_z: FloatProperty`. The modal `invoke()` resolves the active surface from `CivilSurfaceProperties.active_surface_index` and stores the GUID into `self.surface_guid`. |

`CIVIL_OT_surface_pick_breakline` and `CIVIL_OT_surface_pick_boundary` are the modal counterparts to the existing `CIVIL_OT_surface_add_breakline` / `CIVIL_OT_surface_set_boundary` (§1.1, KEEP). The non-modal versions stay (they accept curve-object names; called by Add Element and tests). The new modal versions live alongside.

**New tool method:**

`tool.Surface.simplify(surface_id: int, tolerance: float) -> int` — TIN simplification via vertex-reduction (e.g., edge-collapse decimation guided by a quadric-error metric, or an equivalent `meshlib.simplify`-style pass). **Algorithm choice deferred to implementation;** the signature is the contract. Returns the count of vertices removed. Note: Douglas-Peucker is **not** appropriate here — DP is a polyline algorithm that operates on ordered chains of points, whereas a TIN is a 2D-connected mesh whose simplification must preserve triangle adjacency and cap vertical error against the original surface. The earlier draft naming DP was wrong; do not pin DP in implementation. Exposed in §7 (slope analysis + simplify can share a panel) but lives in tool to be ready for the modal which previews simplification interactively.

### §6.2 Grading — `grading_tool`

**File:** `bim/module/grading/workspace.py` (new).

```python
class GradingCivilTool(WorkSpaceTool):
    bl_idname = "bim.grading_tool"
    bl_label = "Grading"
    bl_description = "Draw feature lines and apply slope criteria to design grading."
    bl_icon = "OUTLINER_OB_CURVE"
    # (other fields per alignment template)
```

**Modal operators activated by this tool:**

| Operator | Modal behavior |
|---|---|
| `CIVIL_OT_feature_line_draw_modal` | Click-to-place vertices; Enter commits; Tab toggles 2D-vs-3D pick. On commit, calls into the existing `core.grading.create_feature_line` with the captured polyline. `_from_data` sibling takes vertex-list string. |
| `CIVIL_OT_feature_line_grab_elevation` | G-key during edit-mode-equivalent: drag selected vertex up/down; numeric entry; Enter commits; mutates `feature_line.vertices`, then calls `tool.Grading.update_feature_line_vertices(ifc_file, feature_line)` and `tool.Grading.update_blender_curve(ifc_file, feature_line)` to persist the edit. `_from_data` takes `feature_line_guid: StringProperty` (identifier — required so headless callers can target a specific FL without a viewport selection), `vertex_index: IntProperty`, and `delta_z: FloatProperty`. **Note:** this dispatches directly into `tool.Grading`, matching the shipped pattern at `grading/operator.py:345-352` (the existing `CIVIL_OT_feature_line_edit_elevations` headless operator). `core.grading` does **not** ship an `edit_feature_line_elevations` orchestration function and Phase 7b does not introduce one — the mutation is a pure curve-vertex update with no validation logic that would justify a core hop. If a future phase adds cross-feature-line constraint validation (e.g., enforcing minimum slope between adjacent FLs), a `core.grading.edit_feature_line_elevations` function should be introduced then and both operators migrated to it together. |
| `CIVIL_OT_grading_stepped_offset_modal` | Pick reference feature line; numeric entry for offset distance + step elevation delta; preview via `GradingDecorator` extension; commit creates a new feature line. `_from_data` takes `source_fl_id: IntProperty`, `offset: FloatProperty`, `step_dz: FloatProperty`. |
| `CIVIL_OT_grading_fillet_modal` | Click-pick two adjacent feature-line segments; drag radius; commit replaces sharp corner with arc. `_from_data` takes `fl_id`, `vertex_index`, `radius`. |

**New tool methods:**

- `tool.Grading.compute_stepped_offset(fl_id: int, offset: float, step_dz: float) -> list[tuple[float,float,float]]` — returns the offset polyline vertices.
- `tool.Grading.insert_fillet(fl_id: int, vertex_index: int, radius: float) -> None` — replaces vertex with arc samples; updates IFC + Blender curve.

Both of these are pure tool-layer (math + IFC + Blender object update). Core gets thin orchestrators that validate and dispatch.

### §6.3 Earthwork — `earthwork_tool`

**File:** `bim/module/earthwork/workspace.py` (new).

```python
class EarthworkCivilTool(WorkSpaceTool):
    bl_idname = "bim.earthwork_tool"
    bl_label = "Earthwork"
    bl_description = "Probe cut and fill volumes interactively at any point."
    bl_icon = "MOD_VOLUME_DISPLACE"
    # (other fields per alignment template)
```

**Modal operator activated by this tool:**

| Operator | Modal behavior |
|---|---|
| `CIVIL_OT_earthwork_volume_probe` | Mouse hover: shows cut/fill depth at cursor position over the cut/fill solids. Click commits a label. Floating overlay rendered by `EarthworkDecorator` (§5.3). `_from_data` takes `xyz: FloatVectorProperty(size=3)` and adds a label entity. |

### §6.4 Phase 7b deliverables checklist

- [ ] 3 `workspace.py` files (surface, grading, earthwork).
- [ ] 7 new modal operators with `_from_data` siblings.
- [ ] 3 new tool methods (`Surface.simplify`, `Grading.compute_stepped_offset`, `Grading.insert_fillet`).
- [ ] Each modal has a smoke test (registers, instantiates) plus a `_from_data` headless test.
- [ ] WorkSpaceTool registration smoke test per module (asserts `bpy.utils.register_tool()` succeeded; does not exercise activation).
- [ ] `docs/grading/keymaps.md` published — one section per WorkSpaceTool listing every keymap binding (key, modifier, operator, modal mode if applicable). User-facing reference, not developer notes. Civil 3D users will look here first.
- [ ] All Tier 1 demo / Phase 7a tests still green (no regressions).
- [ ] Manual sign-off per §10.

---

## §7 Phase 7c — Analysis & Labels

**Goal:** read-only analysis surfaces over existing data — contours, slope shading, station/elevation labels, panorama-style summary report.

**Acceptance gate:** contour and slope analyses produce visually correct output on the Tier 1 demo IFC; labels persist across save/load; panorama report exports to PDF or HTML.

### §7.1 Surface module additions

**New operators:**

| Operator | Purpose |
|---|---|
| `CIVIL_OT_surface_extract_contours` | Generates contour polylines at a fixed interval; authors as `IfcAnnotation` with `Pset_SaikeiContour` (interval, base elevation). **Phase 7c prereq** — `Pset_SaikeiContour` does not exist today; author it via a new `ifcopenshell.api.surface.add_contour_annotation` helper. The helper's spec lives in a follow-up IFC-API spec; do **not** hand-author the Pset in operator code. The Saikei rule (every Saikei pset is authored by an `ifcopenshell.api.*` helper, never inline in Bonsai) applies here just as it does to `Pset_SaikeiBreaklineCommon` (cited §1.6). |
| `CIVIL_OT_surface_label_elevation_at_point` | Click-pick; samples Z; authors a labeled `IfcAnnotation`. |

**New panel:** `CIVIL_PT_surface_analysis` with controls for contour interval, slope-shading enable, contour color.

**Decorator extension:** `SurfaceDecorator` gains a slope-shading mode (per-triangle fill colored by gradient magnitude) and a contour-overlay mode (cached polylines).

**New tool method:**

`tool.Surface.extract_contours(surface_id: int, interval: float, base: float = 0.0) -> list[list[tuple[float,float,float]]]` — marching-triangles algorithm; returns one polyline per contour level.

### §7.2 Grading module additions

**New operators:**

| Operator | Purpose |
|---|---|
| `CIVIL_OT_feature_line_label_stations` | Place station labels along the FL at fixed interval. |
| `CIVIL_OT_grading_panorama_report` | Aggregate all groups + criteria + computed daylight stats; export to PDF or HTML. |

### §7.3 Earthwork module additions

**New operators:**

| Operator | Purpose |
|---|---|
| `CIVIL_OT_earthwork_label_total_volumes` | Renders the cut/fill totals as a viewport-anchored text annotation. |
| `CIVIL_OT_earthwork_panorama_report` | Volume-by-region breakdown (if regions are supported) plus shrink/swell factor table; export. |

### §7.4 Phase 7c deliverables checklist

- [ ] 6 new operators, 1 new panel, 1 new tool method, decorator extensions.
- [ ] `Pset_SaikeiContour` authored via a new `ifcopenshell.api.surface.add_contour_annotation` helper (prereq from §7.1).
- [ ] Doc artifact: `docs/grading/analysis.md` — explains contour intervals, slope-band conventions, panorama-report column meanings. User-facing reference for civil engineers reading the analysis output.
- [ ] Manual sign-off per §10.

---

## §8 Phase 7d — Hydrology & Exchange

**Goal:** drainage analysis (water drop, catchment) and external-format export. Lower MVP priority; high value for specific workflows.

**Acceptance gate:** hydrology results match Civil 3D within tolerance on a shared test surface; LandXML export round-trips a surface to and from a third-party tool with the documented loss boundary.

### §8.1 Surface module additions

| Operator | Purpose |
|---|---|
| `CIVIL_OT_surface_water_drop` | Click a point; draws steepest-descent path until ponding or boundary. |
| `CIVIL_OT_surface_catchment_area` | Click a low point; draws polygon of contributing area. |
| `CIVIL_OT_surface_export_landxml` | LandXML 1.2 export of the surface (TIN, breaklines, boundary). |

### §8.2 Grading module additions

| Operator | Purpose |
|---|---|
| `CIVIL_OT_feature_line_insert_high_low_point` | Auto-insert local extrema. |
| `CIVIL_OT_grading_create_transition` | Smooth slope-criterion transition between two adjacent gradings. |

### §8.3 Earthwork module additions

| Operator | Purpose |
|---|---|
| `CIVIL_OT_earthwork_export_volume_report_csv` | CSV / Excel volume report. |

### §8.4 LandXML round-trip — known loss

Per the IFC agent's review, LandXML 1.2 does **not** carry:

- Saikei grading hierarchy (`IfcGroup[GradingGroup]` membership, criteria-to-object linkages).
- IFC classifications (OmniClass, Uniclass) applied via Phase 5 audit.
- `Pset_Saikei*` metadata (shrink/swell factors, boundary-polygon references, criteria templates).
- **IFC `GlobalId` identity** — round-tripping LandXML → IFC mints fresh GUIDs; cross-file references break.
- **`IfcRelAssignsToProduct` breakline-to-surface bindings** — LandXML breaklines are siblings of the surface, not properties of it; the parent-link metadata is dropped.

LandXML round-trip preserves: TIN points + triangulation, breaklines, boundary polygon, basic surface name. Document this loss boundary explicitly in the `CIVIL_OT_surface_export_landxml` operator's docstring and in any companion user docs. **Do not advertise LandXML as a lossless interchange format for Saikei projects.**

### §8.5 Phase 7d deliverables checklist

- [ ] 6 new operators (3 surface, 2 grading, 1 earthwork).
- [ ] LandXML loss boundary documented in operator docstring + user docs.
- [ ] Doc artifact: `docs/grading/landxml.md` — documents the loss boundary from §8.4 in user-facing prose; warns LandXML 1.2 is a TIN-only interchange format and must not be advertised as lossless for Saikei projects.
- [ ] Manual sign-off per §10.

---

## §9 Out of Scope

These are not part of the UI buildout. If a user asks "where's X," the answer is "not in scope" and a referral to `Civil3D_Tool_Inventory.md` §18.

- Sites (topological auto-resolution between feature lines) — not implemented at any layer.
- Parcels / lot subdivision — separate domain.
- Pipe networks (storm, sanitary, pressure) — separate Saikei module.
- Subassemblies / corridors — separate Saikei work track.
- Survey database — separate domain.
- Drawing production / sheets / plot styles — separate Saikei track.
- Vertical alignment beyond the existing PI-method scaffolding — covered by the `vertical-alignment` skill, not this spec.
- Cross-section profiles — covered by the `cross-section-profiles` skill, not this spec.

---

## §10 Implementation & Test Discipline

### §10.1 Order

Within each phase, ship modules in surface → grading → earthwork order. Across phases, complete Phase 7a fully before starting 7b; 7b before 7c; 7c before 7d.

### §10.2 Per-phase manual verification

**Verification is per-phase, not per-commit.** The tester's review on v1 flagged that requiring manual sign-off on every commit is unworkable; v2 collapses to one sign-off per phase. The phase exit checklist (one of §5.5 / §6.4 / §7.4 / §8.5) is the gate. Sign-off captures:

- Operators reachable via menu / panel / Add Element (where applicable).
- Modal operators behave in interactive Blender (one screenshot per modal acceptable).
- Panel layouts render without overflow at 1080p and 4K.
- Decorators draw correctly with the Tier 1 demo IFC loaded.

### §10.3 Test discipline

- **Operator tests** invoke `bpy.ops.civil.<operator>(EXEC_DEFAULT, **props)`; assert IFC entity outcomes. Use `pytest.raises(RuntimeError)` to assert cancellation paths (see §3.3 — `{"CANCELLED"}` from `_execute()` surfaces as `RuntimeError` at the `bpy.ops` boundary). **Cancellation tests must also assert "no IFC entities created"** via a postcondition query (e.g., `assert not ifc_file.by_type("IfcEarthworksCut")`) to catch a refactor that partially-authors entities before reporting an error.
- **Modal smoke tests** register the operator and instantiate it; do not exercise the modal loop. The `_from_data` property-driven path on the same operator class carries the unit-test load (see §3.5).
- **`_from_data` unit tests** invoke the same operator class with `EXEC_DEFAULT` + properties pre-set; verify it produces the same IFC outcome the modal would on commit.
- **WorkSpaceTool registration smoke tests** (Phase 7b) call `bpy.utils.register_tool(<Tool>)` and assert the tool appears in `context.workspace.tools`. Catches headless-mode registration silently failing. **Headless context note:** `bpy.context.workspace` is `None` in a fresh headless session; the test must first create a workspace with `bpy.data.workspaces.new("Test")` and activate it via `bpy.context.window.workspace = ws` before calling `register_tool`. A shared fixture in `test/tool/conftest.py` (or per-module conftest) avoids re-implementing the setup.
- **Decorator tests** (one per decorator, including `SurfaceDecorator`, `GradingDecorator`, the new `EarthworkDecorator`, and Phase 7c extensions) call the decorator's `register()` / `install()`, then trigger a `draw()` callback against a fixture IFC file; assert no exceptions, then call `unregister()` / `uninstall()` and assert the GPU draw handler is removed from `bpy.types.SpaceView3D.draw_handler_remove`'s registry. Catches handler leaks that silently break subsequent tests.
- **Panel tests** register the panel, build a fake context, call `draw()`; assert no exceptions.
- **Data class tests** load against fixture IFC files; assert dict structure.
- **Tier 1 demo** wrapped as `test/integration/test_tier1_demo.py`; runs headlessly via the IFC API. Asserts schema-validity (`ifcopenshell.validate`) on **both** the freshly-generated IFC and the committed reference IFC at `docs/grading/examples/tier1_demo.ifc`; asserts entity-count ranges (not exact equality — IFC GUIDs change between runs).
- All UI tests run via `pytest --blender-executable "<path>"` per CLAUDE.md (note: space-separated, never `=`-joined; the `=`-joined form breaks pytest-blender's flag-stripping).

**Phase 7 operator-test layout (concrete):** Phase 7 follows the same `NewIfc4X3` base-class pattern Phases 4–6 use — operator tests live in `test/tool/test_{surface,grading,earthwork}.py` alongside the pure-math tool tests, gated by the per-test-class `NewIfc4X3` fixture. Migrate to `test/bim/module/{surface,grading,earthwork}/test_*.py` only when the upstream pytest-bdd / parse-type blocker in `test/bim/conftest.py` is resolved (see CLAUDE.md "Phase 4 / 5 / 6 module note").

**Test marker for fast iteration:** decorate every new Phase 7 test with `@pytest.mark.civil`. `pytest -m civil` runs the Phase-7-only subset for fast developer iteration; `pytest -m "civil and not blender"` runs the bpy-free subset (tier-1 demo wrapper, pure-math tool tests). **CI gate always runs the full suite** — `pytest -m civil` is for developer iteration only and intentionally does not include the 577 Phase 4–6 tests. Do not retro-mark Phase 4–6 tests; treat the marker as a Phase-7+ scope filter.

### §10.4 Commit hygiene

- One operator + its tests per commit, where feasible.
- Tool-method additions get their own commit before the operators that consume them.
- Workspace.py registrations land in the same commit as their first modal operator (registration must be useful at land time).

---

## §11 Vocabulary & Tooltips

Civil 3D users have a fixed mental vocabulary. Saikei must hit those terms verbatim in user-facing UI text. The IFC class names (`IfcAlignment`, `IfcGeographicElement`, `IfcEarthworksFill`, `IfcGroup`, etc.) **never appear in user-facing UI strings.** They appear in tooltips only when explaining storage, not when naming actions.

Canonical map (use these phrases as-is):

| Civil 3D term | Saikei UI term | One-line tooltip phrase |
|---|---|---|
| Feature Line | Feature Line | "A 3D polyline that defines a grading edge or design boundary." |
| Grading Object | Grading Object | "A slope-projected surface from a feature line to a target (elevation, distance, or surface)." |
| Grading Group | Grading Group | "A collection of grading objects sharing a feature line and producing one combined surface." |
| Criteria | Criteria | "A reusable slope rule (e.g., 3:1 cut, 4:1 fill) applied to one or more grading objects." |
| Drape | Drape | "Project a feature line vertically onto a target surface, sampling elevations." |
| Quick Elevation Edit | Quick Elevation Edit | "G-key style modal for raising or lowering a feature-line vertex by a typed delta." |
| Stepped Offset | Stepped Offset | "Create a parallel feature line offset horizontally and stepped vertically." |
| Interior Fill | Interior Fill | "How the inside of a closed grading group is filled — flat, interpolated, or sampled from a surface." |
| Daylight Line | Daylight Line | "The line where a grading-object slope meets the target surface." |
| Breakline | Breakline | "A linear feature that constrains the TIN — surface triangles will not cross it." |
| Boundary | Boundary | "The outer or inner polygon defining the limits of a surface." |
| Cut | Cut | "Volume of existing terrain to be excavated below proposed surface." |
| Fill | Fill | "Volume of material to be placed above existing terrain to reach proposed surface." |
| Surface Contours | Contour | "Lines connecting points of equal elevation across a surface." |
| Shrink Factor | Shrink Factor | "Compacted-to-bank volume ratio (placed fill is denser than as-excavated material)." |
| Swell Factor | Swell Factor | "Loose-to-bank volume ratio (excavated material expands when removed from in-situ state)." |
| Volume Reports | Volume Report | "Tabular summary of cut and fill quantities across one or more surface pairs." |
| Panorama Window | (not used) | Civil 3D's tabular UI surface; Saikei renders the equivalent inside a panel sub-section, not a separate window. |

**Action-verb semantics (use deliberately — translators rely on the distinction):**

- **Delete** — destroy the IFC entity and any Blender object linked to it. Irreversible without undo.
- **Remove** — break a relationship (e.g., remove a grading object from a group, remove a member from a UIList) without destroying the entity itself. The entity remains for use elsewhere.
- **Clear** — reset transient UI/scene-property state (e.g., clear last-run earthwork report). No IFC change.

Operator `bl_label` and `bl_description` strings must match these semantics. "Delete Surface" destroys the IfcGeographicElement; "Remove from Group" only breaks the assignment; "Clear Results" only zeros the report fields.

**Rules:**

1. Operator `bl_label` strings use the Saikei UI term column verbatim — "Add Feature Line," not "Add IfcAlignment Feature-Line Variant."
2. Operator descriptions and tooltips lift the one-line phrase verbatim from this table. Variation creates inconsistency; consistency beats prose.
3. IFC class names are permitted in Python docstrings, comments, and developer-facing API docs. They are not permitted in `bl_label`, `bl_description`, panel labels, error popups, or any text the user reads in Blender. **Mechanically enforceable check:** any cold-review pass should `grep -E '(bl_label|bl_description)\s*=\s*"[^"]*Ifc' src/bonsai/bonsai/bim/module/{surface,grading,earthwork}/` and assert zero matches.
4. Tooltip strings are plain ASCII — no em-dashes, en-dashes, or other non-ASCII punctuation. Blender's tooltip renderer has historically had issues with non-ASCII; use a hyphen + spaces or a period instead.
5. **WorkSpaceTool `bl_description` exemption:** the three T-bar tools (`SurfaceCivilTool`, `GradingCivilTool`, `EarthworkCivilTool`) describe a *tool mode* containing many operators, not a single action — their `bl_description` is an action-statement of what the tool does as a whole, drawn from the verbs in the vocabulary table but not pinned to a single row. Operator-level `bl_label` / `bl_description` strings remain bound by Rule 2.
6. Where the Civil 3D term has no clean Saikei equivalent (e.g., "Site"), do not invent one — refer to §9 (out of scope) and surface no UI for that term.
7. **Surface-dropdown `EnumProperty` description field** (used in the `(identifier, name, description)` triple): populate with `f"{triangle_count} triangles, Z={z_min:.1f}–{z_max:.1f}m"` so hover-tooltips on each dropdown row show useful identification, not blank text.

The docs agent enforces this in cold-review passes; new vocabulary additions land here before they land in operator strings. Vocabulary table is canonical and lives at this file path; if Saikei publishes a "Moving from Civil 3D" guide later, it sources its terminology from this table — the table does not move.

---

## §12 References

### Shipped Phase 4–6 code (all citations live)

- `src/bonsai/bonsai/bim/module/alignment/workspace.py:25-86` — `AlignmentTool` (canonical WorkSpaceTool reference).
- `src/bonsai/bonsai/bim/module/surface/operator.py:59,167,217,299` — surface operators.
- `src/bonsai/bonsai/bim/module/surface/ui.py:37,73,116,177` — surface panels.
- `src/bonsai/bonsai/bim/module/surface/prop.py:93,121,155` — surface props + UIList.
- `src/bonsai/bonsai/bim/module/surface/decorator.py:45` — `SurfaceDecorator`.
- `src/bonsai/bonsai/bim/module/surface/data.py:34` — `SurfaceData`.
- `src/bonsai/bonsai/bim/module/grading/operator.py:55,154,232,368,464,563,635` — grading operators.
- `src/bonsai/bonsai/bim/module/grading/ui.py:37,111,176,235,293` — grading panels.
- `src/bonsai/bonsai/bim/module/grading/prop.py:91,118,140,151,167,191,223,248,277` — grading props + UILists.
- `src/bonsai/bonsai/bim/module/grading/decorator.py:55` — `GradingDecorator`.
- `src/bonsai/bonsai/bim/module/grading/data.py:35` — `GradingData`.
- `src/bonsai/bonsai/bim/module/earthwork/operator.py:37` — earthwork operator.
- `src/bonsai/bonsai/bim/module/earthwork/ui.py:35,78` — earthwork panels.
- `src/bonsai/bonsai/bim/module/earthwork/prop.py:71` — `CivilEarthworkProperties`.
- `src/bonsai/bonsai/tool/grading.py:1268` — `Grading.is_feature_line_alignment` (Add Element disambiguator).
- `src/bonsai/bonsai/tool/grading.py:1285` — `Grading.iter_registered`.
- `src/bonsai/bonsai/tool/grading.py:1539,1578` — `create_blender_curve` / `update_blender_curve`.

### Companion docs

- `Saikei_Grading_Earthwork_Spec.md` — architectural spec.
- `SURFACES_GRADING_EARTHWORKS.md` — Phase 5 audit reference.
- `.claude/CLAUDE.md` — project instructions, test commands, current state.
- `Civil3D_Tool_Inventory.md` — parity reference (§18 out-of-scope, §19 build sequencing, §20 ribbon-to-panel mapping).
- Bonsai contributing docs: https://docs.bonsaibim.org
- Blender Python API: https://docs.blender.org/api/current/

---

*End of v2 spec. Begin with §5 (Phase 7a) and proceed sequentially through §6, §7, §8.*

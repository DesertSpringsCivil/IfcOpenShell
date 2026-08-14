# Saikei Civil — UI Implementation Spec

**Status:** Draft v1 — Implementation guide for Claude Code
**Target:** `saikei-dev` branch
**Layer:** Bonsai UI on top of completed `ifcopenshell.api.{surface,grading,earthwork}` and `bonsai.{core,tool}.{surface,grading,earthwork}`
**Companion docs:** `Saikei_Grading_Earthwork_Spec.md` (architectural spec), `Civil3D_Tool_Inventory.md` (parity reference)

---

## 1. Purpose and Scope

This document specifies the Blender UI for Saikei Civil's site grading capabilities. The API, Core, and Tool layers are complete; this spec covers only the `bonsai/bim/module/{surface,grading,earthwork}/` deliverables — operators, panels, property groups, UILists, decorators, workspace tools, and Add Element hooks.

The spec is organized into **four tiers** matching the build sequence in `Civil3D_Tool_Inventory.md` §19. Each tier is independently shippable: at the end of Tier 1, Saikei has a demonstrable flat-pad-to-cut/fill workflow in Blender. Tiers 2–4 layer on tools Civil 3D users expect to find.

Claude Code should ship one tier at a time, with all tests passing and a manual-verification checklist completed before moving to the next.

### 1.1 What's already done

The API/Core/Tool layers ship with these tested capabilities (consult the Phase 1–3 commit history for exact signatures):

- `ifcopenshell.api.surface.*` — `add_surface`, `add_breakline`, `set_boundary`, `retriangulate`, `add_bounding_box`, `set_z`, `compute_volume`, `apply_classification`
- `ifcopenshell.api.grading.*` — `add_feature_line`, `edit_feature_line_elevations`, `add_criteria_template`, `instantiate_criteria`, `add_grading_group`, `add_grading_object`, `add_interior_fill`, `rebuild_group_surface`, `assign_to_group`
- `ifcopenshell.api.earthwork.*` — `compute_cut_fill_volumes`, `add_cut`, `add_fill`, `add_quantities`, `apply_classification`
- `bonsai.core.{surface,grading,earthwork}` — orchestration calling the API
- `bonsai.tool.{surface,grading,earthwork}` — Blender mesh sync, decorator helpers, IFC-to-Blender object mapping

The UI layer's job is to expose these to interactive Blender users.

### 1.2 What this spec deliberately leaves to Claude Code's judgment

The spec prescribes:
- File layout, class names, operator IDs, property group structure
- Which operators must be modal vs `EXEC_DEFAULT`-callable
- Panel composition and UIList behavior
- Acceptance criteria per tier
- The Bonsai conventions to follow

The spec does **not** prescribe:
- Exact pixel-perfect panel layouts (use Blender layout primitives sensibly)
- Icon choices (use Bonsai's existing icon vocabulary; ask the user if anything is genuinely ambiguous)
- Tooltip wording (write helpful tooltips in plain English — but they don't need pre-approval)
- The internal implementation of standard patterns (UIList scaffolding, modal operator state machines) — these follow standard Blender patterns; cite which pattern you're following

When in doubt about a UX detail, **match the existing `bonsai/bim/module/alignment/` module's conventions**. Saikei UI should feel consistent with Bonsai's existing alignment work, not invent its own dialect.

---

## 2. Common Conventions (apply to all modules)

### 2.1 File layout per module

```
src/bonsai/bonsai/bim/module/{surface,grading,earthwork}/
├── __init__.py              # bl_info, register/unregister entry points
├── data.py                  # IFC-backed data cache (UIList draws from this)
├── decorator.py             # GPU overlay drawing (Tier 2+ for some modules)
├── operator.py              # All CIVIL_OT_* operator classes
├── panel.py                 # CIVIL_PT_* panels and CIVIL_UL_* UILists
├── prop.py                  # PropertyGroup classes + scene-level registration
└── workspace.py             # WorkSpaceTool (grading module only; Tier 2)
```

Mirror `bonsai/bim/module/alignment/` exactly for file naming. If a file isn't needed in a tier, omit it; create when the tier introduces the relevant feature.

### 2.2 Naming conventions

- **Operators:** `CIVIL_OT_<module>_<verb>_<object>` (e.g., `CIVIL_OT_surface_create_from_csv`)
- **Panels:** `CIVIL_PT_<module>_<purpose>` (e.g., `CIVIL_PT_surface_main`, `CIVIL_PT_surface_properties`)
- **UILists:** `CIVIL_UL_<module>_<plural_noun>` (e.g., `CIVIL_UL_surfaces`, `CIVIL_UL_grading_groups`)
- **PropertyGroups:** `Civil<Module>Properties` (e.g., `CivilSurfaceProperties`)
- **Workspace tools:** `<purpose>_civil_tool` (e.g., `grading_civil_tool`)

### 2.3 The scene-properties-vs-compute-path rule

PropertyGroups attached to `bpy.types.Scene` carry **only UI state**:
- Active item indices for UILists
- Edit-mode flags (e.g., "feature line elevation edit active")
- Viewport visualization toggles (e.g., "show breaklines", "show daylight lines")
- Form-input scratch values for dialogs (e.g., the elevation field of a Set-Elevation operator before the user clicks OK)

Core and tool code **never** read scene properties. Operators read scene properties to capture user intent, then pass the values explicitly as arguments to `bonsai.core.*` functions. This rule already holds in `bonsai/bim/module/alignment/` — match that pattern.

### 2.4 Operator base class

All operators inherit `tool.Ifc.Operator` and implement `_execute(context)`. This wraps the operation in an IFC transaction for automatic undo/redo. Do not override `execute()` — override `_execute()` only.

```python
import bonsai.tool as tool

class CIVIL_OT_surface_example(tool.Ifc.Operator):
    bl_idname = "civil.surface_example"
    bl_label = "Example Operator"
    bl_options = {"REGISTER", "UNDO"}

    name: bpy.props.StringProperty(name="Name")

    def _execute(self, context):
        # Read scene props, dispatch to bonsai.core.surface.*
        bonsai.core.surface.do_thing(
            tool.Ifc, tool.Surface, name=self.name
        )
```

### 2.5 Modal vs `EXEC_DEFAULT` operators

Operators that have a viewport-pick or modal-edit interaction must also be invokable from Python with all properties pre-set, so headless tests and Cowork/agent calls work. The pattern: use `invoke()` for the modal path; `execute()` (which calls `_execute()`) for the headless path. Operators that use viewport modals should also expose a `_by_guid` or `_from_data` sibling operator if the modal version cannot accept all inputs as properties.

Example (from Tier 1, breakline):
- `CIVIL_OT_surface_add_breakline_modal` — `invoke()` enters polyline-pick modal; on confirm, calls a shared `_apply()` method
- `CIVIL_OT_surface_add_breakline_from_polyline` — takes a `polyline_object_name` property pointing to an existing Blender curve/mesh; calls the same `_apply()` method

### 2.6 Error handling contract

`bonsai.core.*` and `bonsai.tool.*` raise the named exception hierarchy from `ifcopenshell.api.surface` (`SaikeiGradingError` and subclasses). Operators catch these in `_execute()` and convert:

```python
def _execute(self, context):
    try:
        bonsai.core.surface.do_thing(tool.Ifc, tool.Surface, name=self.name)
    except SaikeiGradingError as e:
        self.report({"ERROR"}, str(e))
        return {"CANCELLED"}
```

UI code never invents new exception types. If the API needs a new exception class, add it to `ifcopenshell.api.surface.exceptions` first.

### 2.7 UIList data backing

UILists draw from a **fresh IFC query through `data.py`**, not from a `CollectionProperty` on the scene. Match `bonsai/bim/module/alignment/data.py` — it provides a class with classmethods that return cached query results, and an `is_loaded` flag the panel uses to detect when refresh is needed.

`data.py` skeleton:

```python
class SurfacesData:
    data = {}
    is_loaded = False

    @classmethod
    def load(cls):
        cls.data = {
            "surfaces": cls.get_surfaces(),
            "active_surface": cls.get_active_surface(),
        }
        cls.is_loaded = True

    @classmethod
    def get_surfaces(cls):
        # Query IFC for IfcGeotechnicalStratum + IfcEarthworksFill instances
        # tagged as Saikei surfaces; return [{"guid": ..., "name": ..., "kind": ...}, ...]
        ...
```

The panel's `draw()` calls `SurfacesData.load()` if `not is_loaded`, then iterates `SurfacesData.data["surfaces"]`.

Invalidation: any operator that creates/edits/deletes surfaces sets `SurfacesData.is_loaded = False` at the end of `_execute()`. This is the same pattern alignment uses.

### 2.8 Add Element dialog hooks

Bonsai's "Add Element" dialog (the dropdown for creating new IFC entities) is extended via `bonsai/bim/module/root/`. Saikei registers entity-class hooks so users picking these entity classes from the dialog get routed to Saikei's create operators:

| IFC entity class | Hooks to operator |
|---|---|
| `IfcGeotechnicalStratum` | `CIVIL_OT_surface_create_from_csv` (Tier 1) |
| `IfcEarthworksFill` | `CIVIL_OT_grading_create_group` (Tier 1) |
| `IfcEarthworksCut` | `CIVIL_OT_earthwork_compute_volumes` (Tier 1) |
| `IfcGroup` with `ObjectType="GradingGroup"` | `CIVIL_OT_grading_create_group` (Tier 1) |
| `IfcAlignment` (when used as feature line) | `CIVIL_OT_feature_line_create` (Tier 1; needs distinguishing logic) |

`IfcAlignment` distinguishing: feature lines vs. transportation alignments share the IFC class. Saikei's feature lines carry `Pset_SaikeiFeatureLineCommon`. The Add Element hook should ask "Create as feature line or transportation alignment?" when `IfcAlignment` is selected, or use a separate dialog entry like "Feature Line (Saikei Civil)" if Bonsai's Add Element supports custom entry labels.

### 2.9 Decorator pattern

Decorators are GPU overlays drawn via `gpu` and `gpu_extras.batch.batch_for_shader`. They register draw handlers via `bpy.types.SpaceView3D.draw_handler_add(callback, (), 'WINDOW', 'POST_VIEW')` and store the handle on the decorator class for cleanup on unregister.

Decorators read from `data.py` (not directly from IFC) and re-derive geometry only when `is_loaded` flips. They never modify IFC or Blender data — they are purely visualization.

Match `bonsai/bim/module/alignment/decorator.py` for the registration pattern.

### 2.10 Decorator registration is conditional

GPU draw handlers crash Blender if registered in background mode. Wrap registration:

```python
def register():
    # ... operator and panel registration ...
    if not bpy.app.background:
        SurfaceDecorator.install()

def unregister():
    if not bpy.app.background:
        SurfaceDecorator.uninstall()
    # ... operator and panel unregistration ...
```

### 2.11 Common testing approach

UI module tests use pytest-blender. Three test classes per module:

1. **Operator tests** — invoke each operator with property values pre-set (`EXEC_DEFAULT` path); assert the IFC file has the expected entities. Modal paths are not unit-tested at this layer; manual verification covers them.
2. **Panel tests** — register the panel, build a fake context, call `draw()`; assert no exceptions. This catches UIList wiring bugs.
3. **Data class tests** — call `load()` against an IFC file fixture; assert the dict structure matches expectations.

Each tier has a test file: `test/bim/module/{module}/test_tier1.py`, `test_tier2.py`, etc.

---

## 3. Tier 1 — Minimum Viable Grading Workflow

**Goal:** A user opens Blender, opens an IFC file, loads existing ground from CSV, draws a feature line representing a building pad, applies a slope criteria, computes cut/fill volumes, and exports IFC. End-to-end, in Blender, matching the headless agent script in the architectural spec.

**Acceptance criteria:**
- A new Blender user can complete the flat-pad demo workflow in under 10 minutes from a cold start (excluding install).
- The same workflow runs headless via `EXEC_DEFAULT` operator calls, suitable for Cowork/agent scripting.
- All operators have `bl_options = {"REGISTER", "UNDO"}` and undo correctly.
- A `tier1_demo.py` script in `docs/grading/examples/` runs the workflow end-to-end without Blender (using the API directly), demonstrating the IFC layer is independently usable.

### 3.1 Surface module — Tier 1

**File deliverables:**
- `bonsai/bim/module/surface/__init__.py`
- `bonsai/bim/module/surface/data.py`
- `bonsai/bim/module/surface/operator.py`
- `bonsai/bim/module/surface/panel.py`
- `bonsai/bim/module/surface/prop.py`

**`prop.py` — `CivilSurfaceProperties`:**

```python
class CivilSurfaceProperties(PropertyGroup):
    active_surface_index: IntProperty(name="Active Surface Index", default=0)
    is_editing: BoolProperty(default=False)

    # Form-input scratch values for the create-from-CSV operator
    csv_filepath: StringProperty(name="CSV Path", subtype="FILE_PATH")
    csv_xyz_columns: StringProperty(
        name="XYZ Columns",
        description="Comma-separated 1-indexed column numbers for X,Y,Z (e.g., '2,3,4')",
        default="1,2,3",
    )
    new_surface_name: StringProperty(name="Surface Name", default="Existing Ground")
    new_surface_kind: EnumProperty(
        name="Kind",
        items=[
            ("existing", "Existing Ground", "Survey or as-built ground"),
            ("proposed_group", "Proposed (Group)", "Proposed surface for one grading group"),
            ("proposed_site", "Proposed (Site Composite)", "Composite proposed for whole site"),
        ],
        default="existing",
    )

    # Visualization toggles (decorator settings; Tier 2 uses these)
    show_triangulation: BoolProperty(name="Show Triangulation", default=False)
    show_breaklines: BoolProperty(name="Show Breaklines", default=True)
    show_boundary: BoolProperty(name="Show Boundary", default=True)
    elevation_banding_enabled: BoolProperty(name="Elevation Banding", default=False)
```

Register on `bpy.types.Scene` as `BIMSurfaceProperties` (matching Bonsai's convention of prefixing scene-attached groups with `BIM`).

**`data.py` — `SurfacesData`:**

Provides:
- `get_surfaces()` — returns `[{"guid": str, "name": str, "kind": str, "ifc_id": int, "vertex_count": int, "triangle_count": int, "z_min": float, "z_max": float}, ...]`
- `get_active_surface()` — returns the dict for the active index, or `None`
- `get_surface_statistics(guid)` — returns extended stats (used by the properties panel)

Invalidation: Tier 1 operators set `is_loaded = False` after any create/edit/delete.

**Operators:**

| Operator | bl_idname | What it does |
|---|---|---|
| `CIVIL_OT_surface_create_from_csv` | `civil.surface_create_from_csv` | File picker (interactive) + `EXEC_DEFAULT` path. Reads CSV using `csv_xyz_columns` mapping. Calls `bonsai.core.surface.create_surface_from_points`. |
| `CIVIL_OT_surface_create_from_xyz_array` | `civil.surface_create_from_xyz_array` | Headless-only operator. Takes a `xyz_csv_string` property (CSV-encoded points). Used by tests and agent scripts. |
| `CIVIL_OT_surface_select` | `civil.surface_select` | Sets `active_surface_index`; selects the corresponding Blender mesh in viewport. |
| `CIVIL_OT_surface_rename` | `civil.surface_rename` | Renames surface (IFC `.Name`). |
| `CIVIL_OT_surface_delete` | `civil.surface_delete` | Removes surface entity and its representations. |
| `CIVIL_OT_surface_export_ifc` | `civil.surface_export_ifc` | Wraps the global IFC export, ensuring surfaces serialize correctly. (May be a no-op delegating to existing Bonsai save.) |

**Panels:**

`CIVIL_PT_surface_main` — placed in Properties → Scene → BIM → Civil Engineering → Surfaces (or wherever `bonsai/bim/module/alignment/panel.py` places its top-level panel; mirror that location).

```
[ + Create from CSV    ]   [ Refresh ]
┌──────────────────────────────────┐
│ CIVIL_UL_surfaces                │
│  ▸ Existing Ground       [Stratum]│
│  ▸ Proposed Pad          [Fill]  │
└──────────────────────────────────┘
[ Select ]  [ Rename ]  [ Delete ]
[ ⌄ Statistics ]
   Vertices: 1,247
   Triangles: 2,489
   Z range: 100.2 — 145.8 m
```

Statistics is a sub-row that draws when an active surface is selected. Pulls from `SurfacesData.get_surface_statistics(active_guid)`.

**UIList:** `CIVIL_UL_surfaces` — single column showing name and kind tag; standard Blender icon for terrain/mesh.

**Manual verification checklist for Tier 1 surface:**
- Open Blender with Saikei loaded; create a new IFC project.
- Click "Create from CSV", select a sample CSV; surface appears in UIList and in viewport.
- Surface mesh is visible with correct Z (not flat).
- Statistics panel shows accurate vertex/triangle counts.
- Rename works; UIList updates.
- Delete works; mesh disappears from viewport.
- Save and reopen the IFC file; surface still loads correctly.

### 3.2 Grading module — Tier 1

**File deliverables:**
- `bonsai/bim/module/grading/__init__.py`
- `bonsai/bim/module/grading/data.py`
- `bonsai/bim/module/grading/operator.py`
- `bonsai/bim/module/grading/panel.py`
- `bonsai/bim/module/grading/prop.py`

**`prop.py` — `CivilGradingProperties`:**

```python
class CivilGradingProperties(PropertyGroup):
    active_group_index: IntProperty(default=0)
    active_feature_line_index: IntProperty(default=0)
    active_criteria_index: IntProperty(default=0)
    active_grading_object_index: IntProperty(default=0)

    # Feature line creation
    new_feature_line_name: StringProperty(name="Name", default="Pad Perimeter")
    new_feature_line_closed: BoolProperty(name="Closed", default=True)

    # Grading group creation
    new_group_name: StringProperty(name="Name", default="Building Pad")
    new_group_target_surface: StringProperty(name="Target Surface GUID")
    new_group_interior_fill: EnumProperty(
        name="Interior Fill",
        items=[
            ("none", "None (open)", ""),
            ("flat", "Flat", "Flat surface at average FL elevation"),
            ("interpolate_from_boundary", "Interpolate from FL", "Delaunay using FL vertices"),
            ("from_surface", "From Surface", "Use another surface for interior"),
        ],
        default="interpolate_from_boundary",
    )
    new_group_interior_fill_source: StringProperty(name="Interior Source GUID")

    # Criteria authoring
    new_criteria_name: StringProperty(name="Name", default="3:1 Fill / 2:1 Cut")
    new_criteria_target_kind: EnumProperty(
        name="Target",
        items=[
            ("surface", "Surface", "Project to target surface"),
            ("elevation", "Elevation", "Project to absolute elevation"),
            ("relative_elevation", "Relative Elevation", "Project to elev offset from FL"),
            ("distance", "Distance", "Project for fixed distance"),
        ],
        default="surface",
    )
    new_criteria_target_value: FloatProperty(name="Target Value", default=0.0)
    new_criteria_cut_slope: FloatProperty(name="Cut H:V", default=2.0, min=0.1)
    new_criteria_fill_slope: FloatProperty(name="Fill H:V", default=3.0, min=0.1)
    new_criteria_max_distance: FloatProperty(name="Max Distance (0=unlim)", default=0.0)

    # Grading object creation
    new_grading_feature_line: StringProperty(name="Feature Line GUID")
    new_grading_criteria: StringProperty(name="Criteria GUID")
    new_grading_sample_interval: FloatProperty(name="Sample Interval (m)", default=1.0)
```

**`data.py` — `GradingData`:**

Provides:
- `get_feature_lines()` — `IfcAlignment` instances with `Pset_SaikeiFeatureLineCommon`
- `get_grading_groups()` — `IfcGroup` instances with `ObjectType="GradingGroup"`
- `get_criteria_templates()` — `IfcPropertySetTemplate` instances tagged as Saikei criteria
- `get_grading_objects(group_guid)` — `IfcEarthworksFill[SLOPEFILL]` instances assigned to the named group
- `get_active_*` accessors

**Operators (Tier 1):**

| Operator | bl_idname | What it does |
|---|---|---|
| `CIVIL_OT_feature_line_draw_modal` | `civil.feature_line_draw_modal` | Modal polyline draw. Click to add vertex; right-click/Esc to confirm. Each vertex prompts elevation in command-line / 3D cursor. Uses the same modal scaffolding as `bonsai/bim/module/alignment` PI editor. |
| `CIVIL_OT_feature_line_create_from_data` | `civil.feature_line_create_from_data` | Headless path. Takes `vertices_csv` property (semicolon-separated `x,y,z` triples) and `closed` flag. Calls `bonsai.core.grading.create_feature_line`. |
| `CIVIL_OT_feature_line_drape` | `civil.feature_line_drape` | Pick a target surface; sets each FL vertex's Z to surface Z at (x,y). Optional "insert intermediate grade-break points" toggle (Civil 3D parity). |
| `CIVIL_OT_feature_line_delete` | `civil.feature_line_delete` | |
| `CIVIL_OT_grading_create_group` | `civil.grading_create_group` | `invoke_props_dialog` for interactive (gathers all props from `CivilGradingProperties` scratch fields). `EXEC_DEFAULT` path uses props directly. |
| `CIVIL_OT_grading_create_criteria` | `civil.grading_create_criteria` | `invoke_props_dialog` + `EXEC_DEFAULT` path. |
| `CIVIL_OT_grading_add_object` | `civil.grading_add_object` | Combines a feature line + criteria → calls `bonsai.core.grading.add_grading_object`. Auto-rebuilds group surface afterward. |
| `CIVIL_OT_grading_remove_object` | `civil.grading_remove_object` | Removes a grading object from a group; rebuilds group surface. |
| `CIVIL_OT_grading_rebuild_group` | `civil.grading_rebuild_group` | Force-rebuild (auto-rebuild handles most cases). |
| `CIVIL_OT_grading_delete_group` | `civil.grading_delete_group` | |
| `CIVIL_OT_criteria_delete` | `civil.criteria_delete` | |

**Panels:**

`CIVIL_PT_grading_main` — top-level panel.

```
─── Feature Lines ─────────────────────
[+ Draw]  [+ From Data]  [Refresh]
┌──────────────────────────────────┐
│ CIVIL_UL_feature_lines           │
│  ▸ Pad Perimeter      [closed]   │
│  ▸ Drive Centerline   [open]     │
└──────────────────────────────────┘
[Drape]  [Delete]

─── Criteria ──────────────────────────
[+ New Criteria]
┌──────────────────────────────────┐
│ CIVIL_UL_criteria                │
│  ▸ 3:1 Fill / 2:1 Cut [surface]  │
└──────────────────────────────────┘
[Delete]

─── Grading Groups ────────────────────
[+ New Group]
┌──────────────────────────────────┐
│ CIVIL_UL_grading_groups          │
│  ▸ Building Pad                  │
└──────────────────────────────────┘

When group active: ─────────────────────
[+ Add Grading Object]  [Rebuild]
┌──────────────────────────────────┐
│ CIVIL_UL_grading_objects         │
│  ▸ Pad Slopes (3:1)              │
│  ▸ Interior Fill                 │
└──────────────────────────────────┘
[Remove]
```

**Manual verification checklist for Tier 1 grading:**
- Draw a 4-vertex closed feature line at z=100.
- Drape onto existing ground; observe varying Z values per vertex (sanity check).
- Create a 3:1 fill criteria.
- Create a grading group targeting existing ground, interior fill = "flat".
- Add grading object: select feature line + criteria. Group surface (proposed) appears as a Blender mesh with slope ribbon visible.
- Modify a feature line elevation directly in panel input; group surface rebuilds.
- Save and reopen IFC; full grading hierarchy persists.

### 3.3 Earthwork module — Tier 1

**File deliverables:**
- `bonsai/bim/module/earthwork/__init__.py`
- `bonsai/bim/module/earthwork/data.py`
- `bonsai/bim/module/earthwork/operator.py`
- `bonsai/bim/module/earthwork/panel.py`
- `bonsai/bim/module/earthwork/prop.py`

**`prop.py` — `CivilEarthworkProperties`:**

```python
class CivilEarthworkProperties(PropertyGroup):
    existing_surface_guid: StringProperty(name="Existing Surface GUID")
    proposed_surface_guid: StringProperty(name="Proposed Surface GUID")
    shrink_factor: FloatProperty(name="Shrink Factor", default=1.0, min=0.1, max=2.0)
    swell_factor: FloatProperty(name="Swell Factor", default=1.0, min=0.1, max=2.0)
    
    # Last-computed result cache for display (UI-only; not source of truth)
    last_cut_volume_m3: FloatProperty(default=0.0)
    last_fill_volume_m3: FloatProperty(default=0.0)
    last_net_volume_m3: FloatProperty(default=0.0)

    # Cut/fill color map decorator toggle
    show_cutfill_map: BoolProperty(name="Show Cut/Fill Map", default=False)
```

**`data.py` — `EarthworkData`:**

Provides:
- `get_volume_results()` — list of `IfcEarthworksCut` and `IfcEarthworksFill` instances with their `Qto_*` quantities
- `get_active_pair()` — returns the existing/proposed surfaces currently being analyzed

**Operators (Tier 1):**

| Operator | bl_idname | What it does |
|---|---|---|
| `CIVIL_OT_earthwork_compute_volumes` | `civil.earthwork_compute_volumes` | Pair two surfaces, calls `bonsai.core.earthwork.compute_earthwork_volumes`. Authors `IfcEarthworksCut` / `IfcEarthworksFill` entities and their Qtos. Updates `last_*_volume_m3` for display. |
| `CIVIL_OT_earthwork_export_ifc` | `civil.earthwork_export_ifc` | Wraps export. (May be a no-op delegating to global save.) |
| `CIVIL_OT_earthwork_clear_results` | `civil.earthwork_clear_results` | Removes computed cut/fill entities (for redo with different params). |

**Panels:**

`CIVIL_PT_earthwork_main`:

```
─── Volume Calculation ──────────────────
Existing Surface: [dropdown of surfaces]
Proposed Surface: [dropdown of surfaces]

Shrink Factor:  [   1.00 ]
Swell Factor:   [   1.00 ]

[ Compute Volumes ]

─── Last Result ────────────────────────
Cut:    1,234.5 m³  (1,613.4 cy)
Fill:     987.2 m³  (1,290.6 cy)
Net:    +247.3 m³  (excavation)

─── Cut/Fill Map ───────────────────────
[ ] Show on viewport
```

**Manual verification checklist for Tier 1 earthwork:**
- With existing ground and proposed pad surface from §3.2, run Compute Volumes.
- Cut and fill values display non-zero, plausible numbers.
- IFC inspector (or external IFC viewer) shows `IfcEarthworksCut` and `IfcEarthworksFill` entities with `Qto_*` quantities populated.
- Export IFC; reload in another tool (BlenderBIM, Solibri, IfcTester); volumes survive round-trip.

### 3.4 Tier 1 demo script

A `docs/grading/examples/tier1_demo.py` script demonstrates the complete Tier 1 workflow headlessly:

```python
# Loads CSV, builds existing ground, creates feature line, applies criteria,
# creates grading group, computes volumes, writes IFC. No bpy import.
# Used as both documentation and integration test.
```

The Tier 1 success criterion is: this script runs end-to-end with no errors, produces a valid IFC file, and the same IFC file opens correctly in Blender with all entities visible in the panels.

---

## 4. Tier 2 — Civil 3D-Familiar Editing Tools

**Goal:** A user familiar with Civil 3D can edit a surface or feature line using the tools they expect to find. Adds modal interactions, the workspace tool, and basic decorators.

**Acceptance criteria:**
- All Tier 1 features still work.
- The grading workspace tool registers and provides keymap shortcuts (G-key elevation edit on feature lines mirrors Civil 3D's Quick Elevation Edit).
- Decorators draw correctly without crashing in background mode.
- Modal operators have clear status-bar prompts and ESC cancel.

### 4.1 Surface module — Tier 2 additions

**Operators:**

| Operator | What it does |
|---|---|
| `CIVIL_OT_surface_add_breakline_modal` | Modal: pick a curve/edge in viewport, convert to breakline. |
| `CIVIL_OT_surface_add_breakline_from_polyline` | Headless: take `polyline_object_name`, convert. |
| `CIVIL_OT_surface_set_boundary_modal` | Modal: pick a closed polyline; choose Outer/Hole/Void. |
| `CIVIL_OT_surface_set_boundary_from_polygon` | Headless: take `polygon_csv` and `boundary_kind`. |
| `CIVIL_OT_surface_raise_lower` | Add constant Z offset to all surface points. |
| `CIVIL_OT_surface_delete_line` | Click a triangle edge; remove it (with edge history per Civil 3D). |
| `CIVIL_OT_surface_simplify` | Apply Douglas-Peucker simplification with tolerance input. |

**Decorator (`surface/decorator.py`):**

`SurfaceDecorator` draws:
- Triangulation edges when `show_triangulation` is True (thin gray lines per triangle edge)
- Breakline edges when `show_breaklines` is True (colored polylines from the source `IfcAnnotation` polylines, not the derived TIN)
- Boundary polygons when `show_boundary` is True (outer = solid, hole = dashed, void = dotted)
- Elevation banding when `elevation_banding_enabled` (vertex-color-driven mesh shader; replaces the wireframe display)

Reads from `SurfacesData`. Re-derives geometry on `is_loaded` flip.

### 4.2 Grading module — Tier 2 additions

**Workspace tool (`grading/workspace.py`):**

`grading_civil_tool` — registered to `bpy.types.WorkSpaceTool`. When active:
- G-key with a feature line vertex hovered → enters elevation-edit modal (Quick Elevation Edit equivalent)
- I-key with a feature line selected → enters Insert PI / Insert Elevation Point sub-modal (per Civil 3D Insert PI vs Insert Elevation Point distinction)
- D-key with a feature line selected → drape onto active target surface

Workspace tool keymap is documented in a `keymaps.md` companion file. Match `bonsai/bim/module/alignment/workspace.py` for the registration pattern.

**Operators:**

| Operator | What it does |
|---|---|
| `CIVIL_OT_feature_line_quick_elevation_modal` | The G-key modal. Numpad/keyboard input changes vertex Z; shows live mesh update. |
| `CIVIL_OT_feature_line_set_grade_between_points` | Pick two PIs; specify grade (%) or slope (H:V); recompute intermediate elevations. |
| `CIVIL_OT_feature_line_insert_pi` | Insert horizontal PI at a clicked point on the FL (interpolates Z). |
| `CIVIL_OT_feature_line_insert_elevation_point` | Insert vertical elevation point only (no horizontal change). |
| `CIVIL_OT_feature_line_delete_pi` | Delete PI at clicked point. |
| `CIVIL_OT_feature_line_raise_lower` | Constant Z offset to all vertices, or selection. |
| `CIVIL_OT_feature_line_flatten` | Set all FL elevations to a single value. |
| `CIVIL_OT_feature_line_stepped_offset` | Offset horizontally + vertically (Civil 3D Stepped Offset parity). Critical for curb/wall workflows. |
| `CIVIL_OT_feature_line_fillet` | Insert tangent arc at FL corner; radius input. |

**Decorator (`grading/decorator.py`):**

`GradingDecorator` draws:
- Feature line highlight (selected FL gets emphasized color/width)
- Daylight line for active grading object (different color from FL)
- Slope arrows along the slope ribbon (Civil 3D parity, optional toggle)
- PI markers (square at PI, circle at elevation point, diamond at start/end — match Civil 3D conventions)

### 4.3 Earthwork module — Tier 2 additions

**Operators:**

| Operator | What it does |
|---|---|
| `CIVIL_OT_earthwork_cutfill_map` | Generate cut/fill color overlay. Builds a Blender mesh from per-vertex Z deltas; assigns per-vertex colors via a color ramp (red=cut, white=balance, blue=fill). |
| `CIVIL_OT_earthwork_volume_label` | Place a text label at a clicked point showing the local cut/fill value. |

**Decorator (`earthwork/decorator.py`):**

`EarthworkDecorator` draws:
- Cut/fill color map mesh overlay when `show_cutfill_map` is True
- Per-region cut/fill volume labels (auto-placed at region centroids; toggle in panel)

### 4.4 Manual verification checklist for Tier 2

- Workspace tool activates; G-key modal works on a feature line vertex with live mesh update.
- Stepped Offset produces a parallel feature line at correct H/V offset.
- Add Breakline modal: pick a curve, breakline appears in surface UIList; surface retriangulates with the new constraint.
- Set Boundary modal: pick a polygon, surface gets clipped/punched.
- Cut/Fill color map shows red/blue gradient over the proposed surface; matches the volume calculation totals.
- All decorators toggle on/off without flicker; no errors in background mode.

---

## 5. Tier 3 — Quality of Life and Analysis

**Goal:** Engineers can produce labeled deliverables. Annotation, slope arrows, contour displays, volume reports.

**Acceptance criteria:**
- Plot-quality output: a labeled surface plan with spot elevations, contours, and a volume report table.
- Analysis decorators (slope, watersheds, user-defined contours) are toggleable per-surface.

### 5.1 Surface module — Tier 3 additions

**Operators:**

| Operator | What it does |
|---|---|
| `CIVIL_OT_surface_paste` | Composite one surface onto another. Civil 3D parity. |
| `CIVIL_OT_surface_extract_contours` | Generate contour polylines as Blender curves (export to mesh or external). |
| `CIVIL_OT_surface_extract_boundary` | Extract the surface boundary as a polyline. |
| `CIVIL_OT_surface_validate_breaklines` | Run the crossing-breaklines report; surface or list-of-issues output. |

**Decorator additions:**
- Slope analysis (per-triangle color by slope range, settable bands)
- Slope arrows (per-triangle direction arrows colored by magnitude)
- User-defined contours (specific elevations highlighted)
- Contour line decorator (continuous contour rendering at specified interval, with major/minor distinction)

**Panel additions:**
- Analysis sub-panel for configuring elevation/slope/slope-arrow ranges, contour intervals, and color ramps

### 5.2 Grading module — Tier 3 additions

**Operators:**

| Operator | What it does |
|---|---|
| `CIVIL_OT_feature_line_label_elevations` | Drop spot elevation labels at every PI / elevation point. |
| `CIVIL_OT_feature_line_label_grades` | Drop grade labels on each FL segment. |
| `CIVIL_OT_grading_label_slopes` | Drop slope labels on each grading object's projection. |
| `CIVIL_OT_grading_edit_criteria_in_place` | Modify an existing criteria's parameters; auto-rebuild affected groups. |

### 5.3 Earthwork module — Tier 3 additions

**Operators:**

| Operator | What it does |
|---|---|
| `CIVIL_OT_earthwork_volume_report_panorama` | Open a panel showing tabular volume report (multi-pair, with subtotals). Civil 3D Volumes Dashboard parity. |
| `CIVIL_OT_earthwork_label_volume_at_point` | Click a point; label local cut/fill depth there. |

### 5.4 Manual verification checklist for Tier 3

- Generate a labeled plan view: surface with contours, spot elevations on feature line, slope labels on grading object, volume label.
- Change a criteria's slope ratio; affected gradings auto-rebuild and re-label.
- Volume Report panel shows multiple existing/proposed pairs with totals.

---

## 6. Tier 4 — Advanced and Adjacent

**Goal:** Hydrology and exchange-format support. Less critical for MVP but high-value for specific workflows.

**Acceptance criteria:**
- Water drop and catchment area produce correct hydrology results that match Civil 3D output for the same input (within tolerance).
- LandXML export round-trips a surface to Civil 3D or alternative tools with no data loss.

### 6.1 Surface module — Tier 4 additions

**Operators:**

| Operator | What it does |
|---|---|
| `CIVIL_OT_surface_water_drop` | Click a point; draw the steepest-descent path. Useful for drainage assessment. |
| `CIVIL_OT_surface_catchment_area` | Click a low point; draw the polygon of contributing area. |
| `CIVIL_OT_surface_export_landxml` | Write LandXML 1.2 (with full breakline/boundary metadata). |

### 6.2 Grading module — Tier 4 additions

**Operators:**

| Operator | What it does |
|---|---|
| `CIVIL_OT_feature_line_insert_high_low_point` | Auto-insert local high or low elevation point. |
| `CIVIL_OT_grading_create_transition` | Smoothly transition slope criteria between two adjacent gradings. |
| `CIVIL_OT_feature_line_profile_view` | Open a 2D profile view of the FL (Tier 4 if profile views become a feature; otherwise this slips). |

### 6.3 Earthwork module — Tier 4 additions

**Operators:**

| Operator | What it does |
|---|---|
| `CIVIL_OT_earthwork_export_volume_report` | Export volume report as Excel or CSV. |

---

## 7. Out of Scope (Documented Non-Features)

These are explicitly not part of the UI buildout. If a user asks "where's X," the answer is "not in scope" and a referral to the Civil 3D inventory's §18 (Concepts that exist in Civil 3D but not Saikei).

- Sites (topological auto-resolution between feature lines) — not implemented at any layer
- Parcels / lot subdivision — separate domain
- Pipe networks (storm, sanitary, pressure) — separate Saikei module
- Subassemblies / corridors — separate Saikei work
- Survey database — separate domain
- Drawing production / sheets / plot styles — separate Saikei track

---

## 8. Implementation Order and Test Discipline

**Order:**
1. Surface module Tier 1 → tests pass → manual verification → commit
2. Grading module Tier 1 → tests pass → manual verification → commit
3. Earthwork module Tier 1 → tests pass → manual verification → commit
4. Demo script `tier1_demo.py` runs cleanly headlessly → commit
5. Repeat for Tier 2 modules (surface → grading → earthwork)
6. Repeat for Tier 3, then Tier 4

**Per-tier discipline:**
- Each tier must ship with all tests passing.
- Each tier must include the manual verification checklist completed (document results in commit message or PR).
- Decorators are added in the tier where they first appear, never re-implemented.
- Tier N+1 must not break Tier N functionality.

**Test discipline:**
- Operator tests use `bpy.ops.civil.<operator>(EXEC_DEFAULT, **props)` invocation; assert IFC entity outcomes.
- Modal operators have only a smoke test (operator class registers); modal interaction is manually verified.
- Panel tests register the panel, build a fake context with a loaded IFC, call `draw()`; assert no exceptions.
- Data class tests load against fixture IFC files; assert dict structure.
- All UI tests run with `pytest --blender-executable=...`.

---

## 9. References and Conventions Source

- `bonsai/bim/module/alignment/` — primary pattern reference for all Saikei UI modules. When uncertain, look there first.
- Architectural spec: `Saikei_Grading_Earthwork_Spec.md`
- Tool inventory: `Civil3D_Tool_Inventory.md` (especially §19 build sequencing and §20 ribbon-to-panel mapping)
- Bonsai contributing docs: https://docs.bonsaibim.org
- Blender Python API: https://docs.blender.org/api/current/

---

*End of UI implementation spec. Begin with §3 Tier 1 Surface module and proceed in the order specified in §8.*

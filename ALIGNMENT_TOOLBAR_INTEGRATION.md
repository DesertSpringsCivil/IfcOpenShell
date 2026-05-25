# Integration Task: Add Alignment Tool to Bonsai T-Panel Toolbar

## Goal

Add an `AlignmentTool` workspace tool to Bonsai's T-panel (left sidebar toolbar in the 3D Viewport). This gives users quick access to the Saikei Civil alignment operators (horizontal, vertical, stationing) directly from the toolbar, matching the pattern used by Bonsai's existing tools (WallTool, SlabTool, SpatialTool, etc.).

## Branch

Work on the `saikei` branch of IfcOpenShell.

## Where It Goes

The alignment module lives at:
```
src/bonsai/bonsai/bim/module/alignment/
```

Add a new `workspace.py` file there, and update `__init__.py` for registration.

## AlignmentTool Class

Create `src/bonsai/bonsai/bim/module/alignment/workspace.py`:

```python
import bpy
from bpy.types import WorkSpaceTool


class AlignmentTool(WorkSpaceTool):
    bl_space_type = "VIEW_3D"
    bl_context_mode = "OBJECT"
    bl_idname = "bim.alignment_tool"
    bl_label = "Alignment"
    bl_description = (
        "Civil alignment tools — create and edit horizontal/vertical "
        "alignments using PI/PVI method"
    )
    bl_icon = "CURVE_DATA"
    bl_widget = None
    bl_keymap = ()

    def draw_settings(
        context: bpy.types.Context,
        layout: bpy.types.UILayout,
        workspace_tool: bpy.types.WorkSpaceTool,
    ) -> None:
        """Draw the tool's UI when active."""
        if context.region.type == "TOOL_HEADER":
            _draw_header(layout)
        else:
            _draw_sidebar(layout)


def _draw_header(layout):
    """Compact icon-only layout for the tool header bar."""
    row = layout.row(align=True)
    row.operator("civil.create_alignment_by_pi", text="", icon="CURVE_DATA")
    row.operator("civil.import_alignment_csv", text="", icon="IMPORT")
    row.separator()
    row.operator("civil.enter_pi_edit_mode", text="", icon="EDITMODE_HLT")
    row.operator("civil.add_pi", text="", icon="ADD")
    row.operator("civil.remove_pi", text="", icon="REMOVE")
    row.operator("civil.pick_pi_from_viewport", text="", icon="EYEDROPPER")
    row.separator()
    row.operator("civil.recalculate_pis", text="", icon="FILE_REFRESH")


def _draw_sidebar(layout):
    """Expanded layout for the sidebar / N-panel."""
    # ── Horizontal Alignment ──
    col = layout.column(align=True)
    col.label(text="Horizontal Alignment", icon="CURVE_DATA")
    col.operator("civil.create_alignment_by_pi", icon="CURVE_DATA")
    col.operator("civil.import_alignment_csv", icon="IMPORT")
    col.separator()
    col.operator("civil.enter_pi_edit_mode", icon="EDITMODE_HLT")
    row = col.row(align=True)
    row.operator("civil.add_pi", icon="ADD")
    row.operator("civil.remove_pi", icon="REMOVE")
    col.operator("civil.pick_pi_from_viewport", icon="EYEDROPPER")
    row = col.row(align=True)
    row.operator("civil.recalculate_pis", text="Recalculate", icon="FILE_REFRESH")
    row.operator("civil.clear_pis", text="Clear", icon="TRASH")
    col.separator()
    col.operator("civil.add_stationing_referent", icon="EMPTY_AXIS")
    col.operator("civil.name_segments", icon="FONT_DATA")

    layout.separator()

    # ── Vertical Alignment ──
    col = layout.column(align=True)
    col.label(text="Vertical Alignment", icon="GRAPH")
    col.operator("civil.add_vertical_to_alignment", icon="GRAPH")
    col.operator("civil.enter_pvi_edit_mode", icon="EDITMODE_HLT")
    row = col.row(align=True)
    row.operator("civil.add_pvi", icon="ADD")
    row.operator("civil.remove_pvi", icon="REMOVE")
    row = col.row(align=True)
    row.operator("civil.recalculate_pvis", text="Recalculate", icon="FILE_REFRESH")
    row.operator("civil.clear_pvis", text="Clear", icon="TRASH")
```

## Registration

Update `src/bonsai/bonsai/bim/module/alignment/__init__.py` to register the tool.

Follow the same pattern as other Bonsai modules (e.g., `model/__init__.py`, `spatial/__init__.py`):

```python
from . import workspace

def register():
    # ... existing registration code ...
    if not bpy.app.background:
        bpy.utils.register_tool(
            workspace.AlignmentTool,
            separator=True,
            group=False,
        )

def unregister():
    # ... existing unregistration code ...
    if not bpy.app.background:
        bpy.utils.unregister_tool(workspace.AlignmentTool)
```

## Notes

- **bl_idname**: Use `"bim.alignment_tool"` (not `"saikei.alignment_tool"`) since this lives inside Bonsai
- **No runtime detection needed**: Since this is part of Bonsai itself, the civil.* operators are guaranteed to exist when the alignment module is loaded
- **No custom keybindings**: `bl_keymap = ()` for now; can be added later with a hotkey operator pattern like `CadHotkey`
- **Icon**: Uses Blender's built-in `CURVE_DATA` icon. Can be replaced with a custom PNG icon later following Bonsai's icon loading pattern in `model/workspace.py`
- **Positioning**: The tool should appear after Bonsai's existing tools in the T-panel. If you want specific placement, use the `after={"bim.spatial_tool"}` parameter in `register_tool()`

## Existing Operators Referenced

All 16 operators from `src/bonsai/bonsai/bim/module/alignment/operator.py`:

| Operator | Section |
|----------|---------|
| `civil.create_alignment_by_pi` | Horizontal |
| `civil.import_alignment_csv` | Horizontal |
| `civil.enter_pi_edit_mode` | Horizontal |
| `civil.add_pi` | Horizontal |
| `civil.remove_pi` | Horizontal |
| `civil.pick_pi_from_viewport` | Horizontal |
| `civil.recalculate_pis` | Horizontal |
| `civil.clear_pis` | Horizontal |
| `civil.add_stationing_referent` | Horizontal |
| `civil.name_segments` | Horizontal |
| `civil.add_vertical_to_alignment` | Vertical |
| `civil.enter_pvi_edit_mode` | Vertical |
| `civil.add_pvi` | Vertical |
| `civil.remove_pvi` | Vertical |
| `civil.recalculate_pvis` | Vertical |
| `civil.clear_pvis` | Vertical |

## Tested & Working

This exact UI layout was prototyped and tested in Blender 5.0.1 via the bonsai-saikei-view addon. The draw_settings layout shown above is confirmed working.
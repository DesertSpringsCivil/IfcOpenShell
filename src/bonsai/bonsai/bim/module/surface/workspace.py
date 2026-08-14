# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2026 Michael Yoder <myoder@desertspringscivil.com>
#
# This file is part of Bonsai.
#
# Bonsai is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Bonsai is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Bonsai.  If not, see <http://www.gnu.org/licenses/>.

"""WorkSpaceTool registration for the Saikei surface module.

Adds ``SurfaceCivilTool`` to the 3D-viewport T-bar following the pattern
established by :class:`bonsai.bim.module.alignment.workspace.AlignmentTool`
(``alignment/workspace.py:25-86``).

``bl_idname = "bim.surface_tool"`` matches the alignment precedent
(``bim.alignment_tool``) — the ``_civil`` part lives in the class name
(:class:`SurfaceCivilTool`) for grep-friendliness, not in the idname.

``bl_keymap = tool.Blender.get_default_selection_keypmap()`` replicates the
alignment tool's exact call (typo in the method name is canonical; do not
correct it).
"""

import os

import bpy
from bpy.types import WorkSpaceTool

import bonsai.tool as tool


class SurfaceCivilTool(WorkSpaceTool):
    bl_space_type = "VIEW_3D"
    bl_context_mode = "OBJECT"
    bl_idname = "bim.surface_tool"
    bl_label = "Surface"
    bl_description = (
        "Place breaklines, set boundaries, and raise or lower surfaces."
    )
    bl_icon = os.path.join(os.path.dirname(__file__), "ops.authoring.surface")
    bl_widget = None
    bl_keymap = tool.Blender.get_default_selection_keypmap()

    def draw_settings(
        context: bpy.types.Context,
        layout: bpy.types.UILayout,
        workspace_tool: bpy.types.WorkSpaceTool,
    ) -> None:
        if context.region.type == "TOOL_HEADER":
            _draw_header(layout)
        else:
            _draw_sidebar(layout)


def _draw_header(layout: bpy.types.UILayout) -> None:
    """Compact icon-only layout for the tool header bar."""
    row = layout.row(align=True)
    row.operator("civil.surface_pick_breakline", text="", icon="IPO_CONSTANT")
    row.operator("civil.surface_pick_boundary", text="", icon="MESH_CIRCLE")
    row.separator()
    row.operator("civil.surface_raise_lower", text="", icon="TRIA_UP")


def _draw_sidebar(layout: bpy.types.UILayout) -> None:
    """Expanded layout for the sidebar / N-panel."""
    col = layout.column(align=True)
    col.label(text="Surface Editing", icon="MESH_GRID")
    col.operator("civil.surface_pick_breakline", icon="IPO_CONSTANT")
    col.operator("civil.surface_pick_boundary", icon="MESH_CIRCLE")
    col.separator()
    col.operator("civil.surface_raise_lower", icon="TRIA_UP")
    col.separator()
    col.operator("civil.surface_retriangulate", icon="FILE_REFRESH")

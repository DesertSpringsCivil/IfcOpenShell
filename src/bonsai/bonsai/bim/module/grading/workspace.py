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

"""WorkSpaceTool registration for the Saikei grading module.

Adds :class:`GradingCivilTool` to the 3D-viewport T-bar following the
pattern established by
:class:`bonsai.bim.module.alignment.workspace.AlignmentTool`
(``alignment/workspace.py:25-86``) and the freshly-shipped
:class:`bonsai.bim.module.surface.workspace.SurfaceCivilTool`.

``bl_idname = "bim.grading_tool"`` matches the alignment/surface naming
convention (``bim.alignment_tool`` / ``bim.surface_tool``) — the
``_civil`` part lives in the class name (:class:`GradingCivilTool`) for
grep-friendliness, not in the idname.

``bl_keymap = tool.Blender.get_default_selection_keypmap()`` replicates
the alignment tool's exact call (the typo in the method name is
canonical; do not correct it).
"""

import os

import bpy
from bpy.types import WorkSpaceTool

import bonsai.tool as tool


class GradingCivilTool(WorkSpaceTool):
    bl_space_type = "VIEW_3D"
    bl_context_mode = "OBJECT"
    bl_idname = "bim.grading_tool"
    bl_label = "Grading"
    bl_description = (
        "Draw feature lines and apply slope criteria to design grading."
    )
    bl_icon = os.path.join(os.path.dirname(__file__), "ops.authoring.grading")
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
    row.operator("civil.feature_line_draw_modal", text="", icon="GREASEPENCIL")
    row.operator("civil.feature_line_grab_elevation", text="", icon="TRIA_UP")
    row.separator()
    row.operator("civil.grading_stepped_offset_modal", text="", icon="MOD_OFFSET")
    row.operator("civil.grading_fillet_modal", text="", icon="SPHERECURVE")


def _draw_sidebar(layout: bpy.types.UILayout) -> None:
    """Expanded layout for the sidebar / N-panel."""
    col = layout.column(align=True)
    col.label(text="Feature Lines", icon="OUTLINER_OB_CURVE")
    col.operator("civil.feature_line_draw_modal", icon="GREASEPENCIL")
    col.operator("civil.feature_line_grab_elevation", icon="TRIA_UP")
    col.separator()
    col.label(text="Editing", icon="MOD_OFFSET")
    col.operator("civil.grading_stepped_offset_modal", icon="MOD_OFFSET")
    col.operator("civil.grading_fillet_modal", icon="SPHERECURVE")

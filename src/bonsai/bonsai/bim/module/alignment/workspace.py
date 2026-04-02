# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2020, 2021 Dion Moult <dion@thinkmoult.com>, 2026 Michael Yoder <myoder@desertspringscivil.com>
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

import bpy
from bpy.types import WorkSpaceTool

import bonsai.tool as tool


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


def _draw_header(layout):
    """Compact icon-only layout for the tool header bar."""
    row = layout.row(align=True)
    row.operator("civil.import_alignment_csv", text="", icon="IMPORT")
    row.operator("civil.pick_pi_from_viewport", text="", icon="EYEDROPPER")
    row.separator()
    row.operator("civil.recalculate_pis", text="", icon="FILE_REFRESH")


def _draw_sidebar(layout):
    """Expanded layout for the sidebar / N-panel."""
    # -- Horizontal Alignment --
    col = layout.column(align=True)
    col.label(text="Horizontal Alignment", icon="CURVE_DATA")
    op = col.operator("bim.add_element", text="Add Alignment", icon="ADD")
    op.ifc_product = "IfcAlignment"
    op.ifc_class = "IfcAlignment"
    col.operator("civil.import_alignment_csv", icon="IMPORT")
    col.separator()
    col.operator("civil.pick_pi_from_viewport", icon="EYEDROPPER")
    row = col.row(align=True)
    row.operator("civil.recalculate_pis", text="Visualize", icon="FILE_REFRESH")
    row.operator("civil.clear_pis", text="Clear", icon="TRASH")
    col.separator()
    col.operator("civil.add_stationing_referent", icon="EMPTY_AXIS")
    col.operator("civil.name_segments", icon="FONT_DATA")

    layout.separator()

    # -- Vertical Alignment --
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

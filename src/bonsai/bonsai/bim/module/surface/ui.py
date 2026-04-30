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

"""UI panels for the Saikei surface module.

All panels live in the Properties sidebar under the CIVIL tab,
nested under :class:`BIM_PT_tab_surface_modeler` (defined in
:mod:`bonsai.bim.ui`).
"""

import bonsai.tool as tool
from bpy.types import Panel

from .data import SurfaceData


def _is_ifc4x3() -> bool:
    """The surface module's IFC schema target is IFC4X3 (per spec §2)."""
    return tool.Ifc.get_schema() == "IFC4X3"


class CIVIL_PT_surface_creation(Panel):
    """Sub-panel: build a new surface from an XYZ point cloud."""

    bl_label = "Create Surface"
    bl_idname = "CIVIL_PT_surface_creation"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_surface_modeler"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return (
            tool.Blender.should_show_panel(context, "CIVIL", cls.bl_idname)
            and _is_ifc4x3()
        )

    def draw(self, context):
        layout = self.layout
        props = context.scene.CivilSurfaceProperties

        box = layout.box()
        box.label(text="New Surface:", icon="ADD")
        box.prop(props, "new_surface_name")
        box.prop(props, "new_surface_kind")
        box.prop(props, "triangulation_tolerance")

        col = layout.column(align=True)
        col.operator(
            "civil.surface_create_from_points",
            icon="IMPORT",
            text="Load XYZ Points...",
        )


class CIVIL_PT_surface_list(Panel):
    """Sub-panel: list of authored surfaces in the active IFC file."""

    bl_label = "Surfaces"
    bl_idname = "CIVIL_PT_surface_list"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_surface_modeler"

    @classmethod
    def poll(cls, context):
        return (
            tool.Blender.should_show_panel(context, "CIVIL", cls.bl_idname)
            and _is_ifc4x3()
        )

    def draw(self, context):
        layout = self.layout
        props = context.scene.CivilSurfaceProperties

        if not SurfaceData.is_loaded:
            SurfaceData.load()

        layout.label(
            text=f"{SurfaceData.data.get('surface_count', 0)} surfaces in file",
            icon="INFO",
        )

        # The UIList drives active_surface_index; the row-selection callback
        # (commit 14.1+) writes back to active_surface_id / _guid.
        layout.template_list(
            "CIVIL_UL_surfaces",
            "",
            props,
            "surfaces",
            props,
            "active_surface_index",
            rows=4,
        )


class CIVIL_PT_surface_active(Panel):
    """Sub-panel: details and edit operators for the active surface."""

    bl_label = "Active Surface"
    bl_idname = "CIVIL_PT_surface_active"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_surface_modeler"

    @classmethod
    def poll(cls, context):
        if not _is_ifc4x3():
            return False
        if not tool.Blender.should_show_panel(context, "CIVIL", cls.bl_idname):
            return False
        return bool(context.scene.CivilSurfaceProperties.active_surface_guid)

    def draw(self, context):
        layout = self.layout
        props = context.scene.CivilSurfaceProperties

        if not SurfaceData.is_loaded:
            SurfaceData.load()

        summary = SurfaceData.active_surface_summary(
            tool.Ifc.get(), props.active_surface_guid
        )

        box = layout.box()
        col = box.column(align=True)
        col.label(text=f"Name: {summary['name']}")
        col.label(text=f"Kind: {summary['kind']}")
        col.label(
            text=f"Vertices: {summary['vertex_count']} | "
            f"Triangles: {summary['triangle_count']}"
        )
        col.label(text=f"Breaklines: {summary['breakline_count']}")
        col.label(
            text=f"Boundary: {'set' if summary['has_boundary'] else 'convex hull'}"
        )

        # Edit operators
        col = layout.column(align=True)
        col.operator(
            "civil.surface_add_breakline",
            icon="IPO_BACK",
            text="Add Breakline...",
        )
        col.operator(
            "civil.surface_set_boundary",
            icon="MESH_PLANE",
            text="Set Boundary...",
        )
        col.operator(
            "civil.surface_retriangulate",
            icon="FILE_REFRESH",
            text="Retriangulate",
        )


class CIVIL_PT_surface_display(Panel):
    """Sub-panel: GPU decorator toggles. The decorator class itself lands
    in commit 15; this panel ships its UI now so the toggles persist
    across the development cycle."""

    bl_label = "Display"
    bl_idname = "CIVIL_PT_surface_display"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_surface_modeler"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return (
            tool.Blender.should_show_panel(context, "CIVIL", cls.bl_idname)
            and _is_ifc4x3()
        )

    def draw(self, context):
        layout = self.layout
        props = context.scene.CivilSurfaceProperties

        col = layout.column(align=True)
        col.prop(props, "show_triangles")
        col.prop(props, "show_elevation_banding")

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
from bpy.types import Menu, Panel

from .data import SurfaceData


def _is_ifc4x3() -> bool:
    """The surface module's IFC schema target is IFC4X3 (per spec §2)."""
    return tool.Ifc.get_schema() == "IFC4X3"


class CIVIL_MT_add_element(Menu):
    """Pop-up menu for adding top-level civil elements.

    Provides a single access point for authoring terrain surfaces, feature
    lines, grading groups, grading criteria, and triggering earthwork-volume
    computation — bypassing Bonsai's root Add Element dispatch, which does not
    support Pset-based predicates needed to disambiguate Saikei entities.

    Invoked via ``layout.menu("CIVIL_MT_add_element")`` in any CIVIL panel.
    Each entry calls the corresponding ``civil.*`` operator directly; operators
    that require a file (terrain, feature line) open Blender's file selector
    via their own ``invoke()`` path.

    Per spec §4 (strategy (c), parallel menu) and §3.2 (``CIVIL_MT_*`` prefix).
    """

    bl_idname = "CIVIL_MT_add_element"
    bl_label = "Add Civil Element"

    def draw(self, context):
        layout = self.layout

        layout.label(text="Surfaces", icon="MESH_GRID")
        layout.operator(
            "civil.surface_create_from_points",
            text="Terrain (existing)",
            icon="IMPORT",
        )

        layout.separator()

        layout.label(text="Grading", icon="CURVE_PATH")
        layout.operator(
            "civil.feature_line_create",
            text="Feature Line",
            icon="OUTLINER_OB_CURVE",
        )
        layout.operator(
            "civil.grading_create_group",
            text="Grading Group",
            icon="OUTLINER_COLLECTION",
        )
        layout.operator(
            "civil.grading_create_criteria",
            text="Grading Criteria",
            icon="PROPERTIES",
        )

        layout.separator()

        layout.label(text="Earthwork", icon="SCULPTMODE_HLT")
        layout.operator(
            "civil.compute_earthwork_volumes",
            text="Compute Earthwork Volumes",
            icon="MOD_BOOLEAN",
        )


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

        # CSV column-remap section — always visible so the user can configure
        # before opening the file picker. Only two fields; they take minimal
        # space and are needed before the file dialog is invoked.
        col_map_box = layout.box()
        col_map_box.label(text="Column Mapping (optional):", icon="SPREADSHEET")
        row = col_map_box.row(align=True)
        row.prop(props, "csv_column_map", text="X/Y/Z Columns")
        col_map_box.prop(props, "csv_skip_header_rows")

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

        # Quick-add menu: terrain, feature line, grading group, criteria,
        # earthwork volumes — all civil authoring entry points in one popup.
        layout.menu("CIVIL_MT_add_element", text="Add Civil Element", icon="ADD")
        layout.separator()

        if not SurfaceData.is_loaded:
            SurfaceData.load()

        layout.label(
            text=f"{SurfaceData.data.get('surface_count', 0)} surfaces in file",
            icon="INFO",
        )

        # The UIList drives active_surface_index; the prop's update= callback
        # writes back to active_surface_id / _guid (see prop.py
        # _on_active_surface_index_change).
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

        # Management operators
        col = layout.column(align=True)
        col.label(text="Manage:", icon="TOOL_SETTINGS")
        rename_op = col.operator(
            "civil.surface_rename",
            icon="OUTLINER_DATA_FONT",
            text="Rename...",
        )
        rename_op.surface_guid = props.active_surface_guid
        col.operator(
            "civil.surface_select",
            icon="RESTRICT_SELECT_OFF",
            text="Select Object",
        )
        col.operator(
            "civil.surface_delete",
            icon="TRASH",
            text="Delete Surface",
        )


class CIVIL_PT_surface_statistics(Panel):
    """Sub-panel: read-only TIN statistics for the active surface.

    Polls the active surface GUID; hides itself when no surface is selected.
    All data is read from the :class:`SurfaceData` cache (which the
    in-memory :class:`CivilSurface` dataclass backs) so this panel adds zero
    IFC I/O cost per redraw.
    """

    bl_label = "Surface Statistics"
    bl_idname = "CIVIL_PT_surface_statistics"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_surface_modeler"
    bl_options = {"DEFAULT_CLOSED"}

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

        stats = SurfaceData.get_active_surface_statistics(
            tool.Ifc.get(), props.active_surface_guid
        )

        box = layout.box()
        col = box.column(align=True)
        col.label(text=f"Name: {stats['name']}")
        col.label(text=f"Vertices: {stats['vertex_count']}")
        col.label(text=f"Triangles: {stats['triangle_count']}")
        col.label(text=f"Breaklines: {stats['breakline_count']}")
        col.separator()
        col.label(text=f"Z min: {stats['z_min']:.3f}  Z max: {stats['z_max']:.3f}")
        col.label(
            text=f"Footprint: {stats['bb_width']:.2f} x {stats['bb_depth']:.2f}"
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

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

"""UI panels for the Saikei voxel earthwork module (CIVIL > Voxel Earthwork)."""

import bonsai.tool as tool
from bpy.types import Panel


def _show(context, idname):
    return tool.Blender.should_show_panel(context, "CIVIL", idname) and tool.Ifc.get()


def _draw_resolution(layout, props):
    col = layout.column(align=True)
    col.prop(props, "cell_size")
    col.prop(props, "supersample")
    col.prop(props, "use_z_range")
    if props.use_z_range:
        row = col.row(align=True)
        row.prop(props, "z_min")
        row.prop(props, "z_max")


class CIVIL_PT_voxel_cut_fill(Panel):
    """Cut/fill voxelization between two surfaces — the earthwork volumes."""

    bl_label = "Cut / Fill"
    bl_idname = "CIVIL_PT_voxel_cut_fill"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_voxel_earthwork"

    @classmethod
    def poll(cls, context):
        return _show(context, cls.bl_idname)

    def draw(self, context):
        layout = self.layout
        props = context.scene.CivilVoxelProperties

        col = layout.column(align=True)
        col.prop(props, "existing_surface")
        col.prop(props, "design_surface")
        _draw_resolution(layout, props)

        row = layout.row(align=True)
        row.operator("civil.voxel_preview_cut_fill", icon="MESH_GRID", text="Preview Cut / Fill")
        row.operator("civil.voxel_clear_preview", icon="TRASH", text="")

        if props.has_result:
            box = layout.box()
            box.label(text="Volumes (m³):", icon="SNAP_VOLUME")
            grid = box.grid_flow(columns=2, align=True)
            grid.label(text="Cut:")
            grid.label(text=f"{props.cut_volume:,.1f}")
            grid.label(text="Fill:")
            grid.label(text=f"{props.fill_volume:,.1f}")
            grid.label(text="Net:")
            net = props.net_volume
            grid.label(text=f"{net:,.1f}  ({'import' if net > 0 else 'export'})")

        # Excavation split by native stratum (cut ∩ geology).
        layout.operator(
            "civil.voxel_cut_by_stratum", icon="OUTLINER_OB_VOLUME", text="Excavation by Stratum"
        )
        if len(props.cut_strata):
            box = layout.box()
            box.label(text="Excavation by stratum (m³):", icon="SNAP_VOLUME")
            for item in props.cut_strata:
                row = box.row()
                row.label(text=item.name)
                row.label(text=f"{item.volume:,.1f}")


class CIVIL_PT_voxel_single(Panel):
    """Occupancy preview of a single surface (soil below it)."""

    bl_label = "Single Surface Occupancy"
    bl_idname = "CIVIL_PT_voxel_single"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_voxel_earthwork"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _show(context, cls.bl_idname)

    def draw(self, context):
        layout = self.layout
        props = context.scene.CivilVoxelProperties
        layout.prop(props, "single_surface")
        layout.operator("civil.voxel_preview_surface", icon="MESH_GRID", text="Preview Occupancy")


class CIVIL_PT_voxel_geomodel(Panel):
    """Geomodel strata: classify surfaces into stratum voxels + per-stratum volumes."""

    bl_label = "Geomodel / Strata"
    bl_idname = "CIVIL_PT_voxel_geomodel"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_voxel_earthwork"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _show(context, cls.bl_idname)

    def draw(self, context):
        layout = self.layout
        props = context.scene.CivilVoxelProperties

        layout.label(text="All surfaces, ordered by elevation → strata", icon="OUTLINER_OB_VOLUME")
        _draw_resolution(layout, props)

        row = layout.row(align=True)
        row.operator("civil.voxel_preview_geomodel", icon="MESH_GRID", text="Preview Strata")
        row.operator("civil.voxel_clear_preview", icon="TRASH", text="")

        if len(props.strata):
            box = layout.box()
            box.label(text="Stratum volumes (m³):", icon="SNAP_VOLUME")
            for item in props.strata:
                srow = box.row()
                srow.label(text=item.name)
                srow.label(text=f"{item.volume:,.1f}")

        layout.operator("civil.voxel_author_geomodel", icon="EXPORT", text="Author Geomodel Sidecar")


class CIVIL_PT_voxel_sidecar(Panel):
    """Author the IFC 4.4 voxel sidecar to disk."""

    bl_label = "IFC 4.4 Sidecar"
    bl_idname = "CIVIL_PT_voxel_sidecar"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_voxel_earthwork"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _show(context, cls.bl_idname)

    def draw(self, context):
        layout = self.layout
        props = context.scene.CivilVoxelProperties
        layout.prop(props, "swell_factor")
        layout.prop(props, "sidecar_filepath")
        layout.operator("civil.voxel_author_sidecar", icon="EXPORT", text="Author Voxel Sidecar")

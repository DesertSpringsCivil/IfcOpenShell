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

"""UI panels for the Saikei earthwork module.

All panels live in the Properties sidebar under the CIVIL tab,
nested under :class:`BIM_PT_tab_earthwork` (defined in
:mod:`bonsai.bim.ui`).
"""

import bonsai.tool as tool
from bpy.types import Panel


def _is_ifc4x3() -> bool:
    """The earthwork module's IFC schema target is IFC4X3."""
    return tool.Ifc.get_schema() == "IFC4X3"


class CIVIL_PT_earthwork_inputs(Panel):
    """Sub-panel: pick the surfaces, configure shrink/swell + naming."""

    bl_label = "Inputs"
    bl_idname = "CIVIL_PT_earthwork_inputs"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_earthwork"

    @classmethod
    def poll(cls, context):
        return (
            tool.Blender.should_show_panel(context, "CIVIL", cls.bl_idname)
            and _is_ifc4x3()
        )

    def draw(self, context):
        layout = self.layout
        props = context.scene.CivilEarthworkProperties

        box = layout.box()
        box.label(text="Surfaces:", icon="SURFACE_DATA")
        box.prop(props, "existing_surface_guid")
        box.prop(props, "proposed_surface_guid")

        box = layout.box()
        box.label(text="Shrink/Swell:", icon="MOD_SOLIDIFY")
        row = box.row(align=True)
        row.prop(props, "shrink_factor")
        row.prop(props, "swell_factor")

        box = layout.box()
        box.label(text="IFC Names:", icon="SORTALPHA")
        box.prop(props, "cut_name")
        box.prop(props, "fill_name")

        box = layout.box()
        box.label(text="Predefined Types:", icon="OUTLINER_OB_POINTCLOUD")
        box.prop(props, "cut_predefined_type")
        box.prop(props, "fill_predefined_type")


class CIVIL_PT_earthwork_compute(Panel):
    """Sub-panel: the compute button + last-run summary."""

    bl_label = "Compute"
    bl_idname = "CIVIL_PT_earthwork_compute"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_earthwork"

    @classmethod
    def poll(cls, context):
        return (
            tool.Blender.should_show_panel(context, "CIVIL", cls.bl_idname)
            and _is_ifc4x3()
        )

    def draw(self, context):
        layout = self.layout
        props = context.scene.CivilEarthworkProperties

        col = layout.column(align=True)
        col.enabled = bool(
            props.existing_surface_guid and props.proposed_surface_guid
        )
        op = col.operator(
            "civil.compute_earthwork_volumes",
            icon="META_CUBE",
            text="Compute Volumes",
        )
        op.existing_surface_guid = props.existing_surface_guid
        op.proposed_surface_guid = props.proposed_surface_guid
        op.shrink_factor = props.shrink_factor
        op.swell_factor = props.swell_factor
        op.cut_name = props.cut_name
        op.fill_name = props.fill_name
        op.cut_predefined_type = props.cut_predefined_type
        op.fill_predefined_type = props.fill_predefined_type

        if not props.last_run_existing_guid:
            return

        box = layout.box()
        box.label(text="Last Run:", icon="INFO")
        col = box.column(align=True)
        col.label(text=f"Cut: {props.last_cut_m3:.1f} m³")
        col.label(text=f"Fill: {props.last_fill_m3:.1f} m³")
        col.label(text=f"Net: {props.last_net_m3:+.1f} m³")
        col.label(text=f"Loose Cut: {props.last_loose_cut_m3:.1f} m³")

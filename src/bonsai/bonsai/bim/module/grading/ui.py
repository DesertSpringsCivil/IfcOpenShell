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

"""UI panels for the Saikei grading module.

All panels live in the Properties sidebar under the CIVIL tab,
nested under :class:`BIM_PT_tab_grading` (defined in
:mod:`bonsai.bim.ui`).
"""

import bonsai.tool as tool
from bpy.types import Panel

from .data import GradingData


def _is_ifc4x3() -> bool:
    """The grading module's IFC schema target is IFC4X3 (per spec §2)."""
    return tool.Ifc.get_schema() == "IFC4X3"


class CIVIL_PT_grading_feature_lines(Panel):
    """Sub-panel: author and edit feature lines."""

    bl_label = "Feature Lines"
    bl_idname = "CIVIL_PT_grading_feature_lines"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_grading"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return (
            tool.Blender.should_show_panel(context, "CIVIL", cls.bl_idname)
            and _is_ifc4x3()
        )

    def draw(self, context):
        layout = self.layout
        props = context.scene.CivilGradingProperties

        if not GradingData.is_loaded:
            GradingData.load()

        layout.label(
            text=(
                f"{GradingData.data.get('feature_line_count', 0)} "
                f"feature lines in file"
            ),
            icon="INFO",
        )
        layout.template_list(
            "CIVIL_UL_grading_feature_lines",
            "",
            props,
            "feature_lines",
            props,
            "active_feature_line_index",
            rows=3,
        )

        box = layout.box()
        box.label(text="New Feature Line:", icon="ADD")
        box.prop(props, "new_feature_line_name")
        box.prop(props, "new_feature_line_closed")

        col = layout.column(align=True)
        col.operator(
            "civil.feature_line_create",
            icon="IMPORT",
            text="Create from XYZ File...",
        )

        layout.separator()

        layout.label(text="Edit Active Feature Line:", icon="GREASEPENCIL")
        col = layout.column(align=True)
        col.enabled = bool(props.active_feature_line_guid)
        op_drape = col.operator(
            "civil.feature_line_drape",
            icon="MOD_SHRINKWRAP",
            text="Drape to Surface...",
        )
        op_drape.feature_line_guid = props.active_feature_line_guid
        # surface_guid is filled by the operator's invoke() popup.
        op_edit = col.operator(
            "civil.feature_line_edit_elevations",
            icon="DRIVER_TRANSFORM",
            text="Edit Elevations...",
        )
        op_edit.feature_line_guid = props.active_feature_line_guid


class CIVIL_PT_grading_criteria(Panel):
    """Sub-panel: list and create reusable grading criteria."""

    bl_label = "Criteria"
    bl_idname = "CIVIL_PT_grading_criteria"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_grading"

    @classmethod
    def poll(cls, context):
        return (
            tool.Blender.should_show_panel(context, "CIVIL", cls.bl_idname)
            and _is_ifc4x3()
        )

    def draw(self, context):
        layout = self.layout
        props = context.scene.CivilGradingProperties

        if not GradingData.is_loaded:
            GradingData.load()

        layout.label(
            text=f"{GradingData.data.get('criteria_count', 0)} criteria in file",
            icon="INFO",
        )

        layout.template_list(
            "CIVIL_UL_grading_criteria",
            "",
            props,
            "criteria",
            props,
            "active_criteria_index",
            rows=3,
        )

        box = layout.box()
        box.label(text="New Criteria:", icon="ADD")
        box.prop(props, "new_criteria_name")
        box.prop(props, "new_criteria_target_kind")
        box.prop(props, "new_criteria_target_ref")
        row = box.row(align=True)
        row.prop(props, "new_criteria_cut_slope")
        row.prop(props, "new_criteria_fill_slope")
        box.prop(props, "new_criteria_max_distance")
        box.prop(props, "new_criteria_retaining_wall")

        col = layout.column(align=True)
        op = col.operator(
            "civil.grading_create_criteria",
            icon="ADD",
            text="Create Criteria",
        )
        op.name = props.new_criteria_name
        op.target_kind = props.new_criteria_target_kind
        op.target_ref = props.new_criteria_target_ref
        op.cut_slope = props.new_criteria_cut_slope
        op.fill_slope = props.new_criteria_fill_slope
        op.max_distance = props.new_criteria_max_distance
        op.retaining_wall_at_limit = props.new_criteria_retaining_wall


class CIVIL_PT_grading_groups(Panel):
    """Sub-panel: list and create grading groups."""

    bl_label = "Grading Groups"
    bl_idname = "CIVIL_PT_grading_groups"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_grading"

    @classmethod
    def poll(cls, context):
        return (
            tool.Blender.should_show_panel(context, "CIVIL", cls.bl_idname)
            and _is_ifc4x3()
        )

    def draw(self, context):
        layout = self.layout
        props = context.scene.CivilGradingProperties

        if not GradingData.is_loaded:
            GradingData.load()

        layout.label(
            text=f"{GradingData.data.get('group_count', 0)} groups in file",
            icon="INFO",
        )

        layout.template_list(
            "CIVIL_UL_grading_groups",
            "",
            props,
            "groups",
            props,
            "active_group_index",
            rows=4,
        )

        box = layout.box()
        box.label(text="New Group:", icon="ADD")
        box.prop(props, "new_group_name")
        box.prop(props, "new_group_target_surface_guid")
        box.prop(props, "new_group_interior_fill")
        if props.new_group_interior_fill == "from_surface":
            box.prop(props, "new_group_interior_fill_source_guid")

        col = layout.column(align=True)
        op = col.operator(
            "civil.grading_create_group",
            icon="ADD",
            text="Create Group",
        )
        op.name = props.new_group_name
        op.target_surface_guid = props.new_group_target_surface_guid
        op.interior_fill = props.new_group_interior_fill
        op.interior_fill_source_guid = props.new_group_interior_fill_source_guid


class CIVIL_PT_grading_active_group(Panel):
    """Sub-panel: details and edit operators for the active grading group."""

    bl_label = "Active Group"
    bl_idname = "CIVIL_PT_grading_active_group"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_grading"

    @classmethod
    def poll(cls, context):
        if not _is_ifc4x3():
            return False
        if not tool.Blender.should_show_panel(context, "CIVIL", cls.bl_idname):
            return False
        return bool(context.scene.CivilGradingProperties.active_group_guid)

    def draw(self, context):
        layout = self.layout
        props = context.scene.CivilGradingProperties

        if 0 <= props.active_group_index < len(props.groups):
            active = props.groups[props.active_group_index]
            box = layout.box()
            col = box.column(align=True)
            col.label(text=f"Name: {active.name}")
            col.label(text=f"Interior Fill: {active.interior_fill}")
            col.label(
                text=f"Cut: {active.cut_volume_m3:g} m³ | "
                f"Fill: {active.fill_volume_m3:g} m³"
            )

        layout.label(text="Members:", icon="OUTLINER_COLLECTION")
        layout.template_list(
            "CIVIL_UL_grading_members",
            "",
            props,
            "active_group_members",
            props,
            "active_member_index",
            rows=4,
        )

        col = layout.column(align=True)
        col.operator(
            "civil.grading_add_object",
            icon="ADD",
            text="Add Grading Object...",
        )
        op = col.operator(
            "civil.grading_rebuild_group",
            icon="FILE_REFRESH",
            text="Rebuild Group",
        )
        op.group_guid = props.active_group_guid


class CIVIL_PT_grading_display(Panel):
    """Sub-panel: GPU decorator toggles."""

    bl_label = "Display"
    bl_idname = "CIVIL_PT_grading_display"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_grading"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return (
            tool.Blender.should_show_panel(context, "CIVIL", cls.bl_idname)
            and _is_ifc4x3()
        )

    def draw(self, context):
        layout = self.layout
        props = context.scene.CivilGradingProperties

        col = layout.column(align=True)
        col.prop(props, "show_feature_lines")
        col.prop(props, "show_daylight_lines")

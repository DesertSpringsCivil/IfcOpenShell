# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2025, 2026 Michael Yoder <myoder@desertspringscivil.com>
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


"""UI panels for the alignment module

All panels appear in the Properties sidebar under the CIVIL tab,
nested under BIM_PT_tab_horizontal_alignment.
"""

import bpy
import bonsai.tool as tool
from bpy.types import Panel, UIList


def is_ifc4x3():
    """Check if the current IFC file is IFC4X3 schema"""
    return tool.Ifc.get_schema() == "IFC4X3"


# =============================================================================
# UILists
# =============================================================================


class CIVIL_UL_alignment_pis(UIList):
    """UIList for displaying interleaved points and segments (Civil 3D style)

    Row types:
    - POINT rows: End (endpoint), Mid (interior PI without curve)
    - SEGMENT rows: Tan (tangent line), Curve (circular arc)

    When a Mid point has radius > 0, it becomes a Curve segment row.
    """

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)

            if item.row_type == "POINT":
                # Point row: No., Type, X, Y, Length, Radius
                row.label(text="")  # No segment number for points

                # Type with point/dot icon
                # "End" = endpoint (POB/POE), "Mid" = interior PI point
                row.label(text=item.display_type, icon="DOT")

                # X, Y coordinates - get actual PI for editing
                pi = data.pis[item.pi_index] if item.pi_index < len(data.pis) else None
                if pi:
                    sub = row.row(align=True)
                    sub.prop(pi, "e", text="")
                    sub.prop(pi, "n", text="")
                else:
                    row.label(text=f"{float(item.e):.2f}")
                    row.label(text=f"{float(item.n):.2f}")

                # Length column - empty for point rows
                row.label(text="")

                # Radius column - editable for Mid points (where curves can be added)
                if item.display_type == "Mid" and pi:
                    row.prop(pi, "radius", text="")
                else:
                    row.label(text="")

            elif item.row_type == "SEGMENT":
                if item.display_type == "Curve":
                    # Curve segment row: No., Type (arc icon), X, Y, Arc Length, Radius
                    row.label(text=f"{item.segment_number}")
                    row.label(text="Curve", icon="SPHERECURVE")

                    # Show PI coordinates on curve row
                    row.label(text=f"{float(item.e):.2f}")
                    row.label(text=f"{float(item.n):.2f}")

                    # Arc length
                    row.label(text=f"{item.arc_length:.2f}")

                    # Radius - editable so user can modify or delete curve (set to 0)
                    pi = data.pis[item.pi_index] if item.pi_index < len(data.pis) else None
                    if pi:
                        row.prop(pi, "radius", text="")
                    else:
                        row.label(text=f"{item.radius:.2f}")
                else:
                    # Tangent segment row: No., Type (line icon), -, -, Length, -
                    row.label(text=f"{item.segment_number}")
                    row.label(text="Tan", icon="IPO_LINEAR")

                    # No X, Y for tangent segments
                    row.label(text="")
                    row.label(text="")

                    # Length
                    row.label(text=f"{item.length:.2f}")

                    # No radius for tangent segments
                    row.label(text="-")

        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(text="", icon="DECORATE")


class CIVIL_UL_vertical_pvis(UIList):
    """UIList for displaying interleaved PVI points and grade segments (Civil 3D style)

    Row types:
    - POINT rows: End (endpoint BOM/EOM), PVI (interior PVI with optional curve)
    - SEGMENT rows: Grade (tangent grade run between curves/endpoints)
    """

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)

            if item.row_type == "POINT":
                row.label(text="")  # No segment number for point rows

                row.label(text=item.display_type, icon="DOT")

                # Station and elevation — get actual PVI for editing
                pvi = data.vertical_pvis[item.pvi_index] if item.pvi_index < len(data.vertical_pvis) else None
                if pvi:
                    sub = row.row(align=True)
                    sub.prop(pvi, "station", text="")
                    sub.prop(pvi, "elevation", text="")
                else:
                    row.label(text=f"{item.station:.2f}")
                    row.label(text=f"{item.elevation:.3f}")

                # Curve length — editable for interior PVIs
                if item.display_type == "PVI" and pvi:
                    row.prop(pvi, "curve_length", text="")
                elif item.curve_length > 0:
                    row.label(text=f"L={item.curve_length:.1f}")
                else:
                    row.label(text="")

                # K value — display only; ERROR icon flags an advisory
                # AASHTO stopping-sight-distance deficiency (spec 2.4).
                if item.k_value > 0 and item.k_deficient:
                    sub = row.row(align=True)
                    sub.alert = True
                    sub.label(
                        text=f"K={item.k_value:.1f} < {item.k_required:.0f}",
                        icon="ERROR",
                    )
                elif item.k_value > 0:
                    row.label(text=f"K={item.k_value:.1f}")
                else:
                    row.label(text="")

            elif item.row_type == "SEGMENT":
                # Grade segment row
                row.label(text="")
                row.label(text="Grade", icon="IPO_LINEAR")
                row.label(text="")  # No station for segment rows
                row.label(text="")  # No elevation for segment rows
                row.label(text=f"{item.grade_pct:+.3f}%")
                row.label(text=f"{item.length:.2f}")

        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(text="", icon="DECORATE")


# =============================================================================
# Creation Sub-Panel
# =============================================================================


class CIVIL_PT_alignment_creation(Panel):
    """Sub-panel for alignment creation tools"""

    bl_label = "Creation"
    bl_idname = "CIVIL_PT_alignment_creation"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_horizontal_alignment"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return tool.Blender.should_show_panel(context, "CIVIL", cls.bl_idname) and is_ifc4x3()

    def draw(self, context):
        layout = self.layout
        props = context.scene.CivilAlignmentProperties

        # New alignment properties
        box = layout.box()
        box.label(text="New Alignment:", icon="ADD")
        box.prop(props, "new_alignment_name")
        box.prop(props, "start_station")

        # Creation operators
        col = layout.column(align=True)
        col.operator("civil.create_alignment_by_pi", icon="CURVE_DATA")

        if props.active_alignment_id != 0:
            layout.separator()
            layout.operator("civil.delete_alignment", icon="TRASH")


# =============================================================================
# PI Editor Sub-Panel
# =============================================================================


class CIVIL_PT_pi_editor(Panel):
    """Sub-panel for PI point table editor (Civil 3D style grid view)"""

    bl_label = "PI Editor"
    bl_idname = "CIVIL_PT_pi_editor"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_horizontal_alignment"
    bl_options = set()  # Open by default

    @classmethod
    def poll(cls, context):
        return tool.Blender.should_show_panel(context, "CIVIL", cls.bl_idname) and is_ifc4x3()

    def draw(self, context):
        layout = self.layout
        props = context.scene.CivilAlignmentProperties

        # PI Edit Mode indicator
        if props.is_pi_edit_mode:
            box = layout.box()
            box.alert = True
            box.label(text="PI Edit Mode Active", icon="EDITMODE_HLT")
            col = box.column(align=True)
            col.label(text="Move PIs with G key")
            col.label(text="Press Enter to apply")
            col.label(text="Press Escape to cancel")
            layout.separator()
            return  # Don't show normal UI while in edit mode

        # Edit existing alignment button
        if props.active_alignment_id != 0:
            box = layout.box()
            box.label(text="Edit Alignment:", icon="EDITMODE_HLT")
            box.operator("civil.enter_pi_edit_mode", icon="PIVOT_CURSOR", text="Edit PIs (G key)")
            layout.separator()

        # Header row with column labels
        header = layout.row(align=True)
        header.label(text="No.")
        header.label(text="Type")
        header.label(text="E")
        header.label(text="N")
        header.label(text="Length")
        header.label(text="Radius")

        # Combined point/segment list (interleaved view)
        row = layout.row()
        row.template_list(
            "CIVIL_UL_alignment_pis",
            "",
            props,
            "display_rows",
            props,
            "active_display_row_index",
            rows=8,
        )

        # Side buttons for list management
        col = row.column(align=True)
        col.operator("civil.add_pi", icon="ADD", text="")
        col.operator("civil.remove_pi", icon="REMOVE", text="")
        col.separator()
        col.operator("civil.pick_pi_from_viewport", icon="EYEDROPPER", text="")

        # Bottom actions
        layout.separator()
        row = layout.row(align=True)
        row.operator("civil.recalculate_pis", icon="FILE_REFRESH", text="Recalculate")
        row.operator("civil.clear_pis", icon="TRASH", text="Clear All")


# =============================================================================
# Stationing Sub-Panel
# =============================================================================


class CIVIL_PT_vertical_creation(Panel):
    """Sub-panel for vertical alignment creation"""

    bl_label = "Vertical Alignment"
    bl_idname = "CIVIL_PT_vertical_creation"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_horizontal_alignment"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return tool.Blender.should_show_panel(context, "CIVIL", cls.bl_idname) and is_ifc4x3()

    def draw(self, context):
        layout = self.layout
        props = context.scene.CivilAlignmentProperties

        # Show Add Vertical Layout button when no vertical exists
        if props.active_alignment_id != 0:
            box = layout.box()
            box.label(text="Setup:", icon="ADD")
            box.operator("civil.add_vertical_to_alignment", icon="CURVE_PATH")

            has_vertical = False
            ifc_file = tool.Ifc.get()
            if ifc_file is not None:
                try:
                    alignment = ifc_file.by_id(props.active_alignment_id)
                    has_vertical = tool.Alignment.get_vertical_layout(alignment) is not None
                except RuntimeError:
                    pass
            if has_vertical:
                box.operator("civil.delete_vertical_layout", icon="TRASH")
            layout.separator()

            # 3D combined-alignment centerline (D3)
            box = layout.box()
            box.label(text="3D Combination:", icon="MOD_CURVE")
            box.operator("civil.visualize_3d_alignment", icon="OUTLINER_OB_CURVE")
            layout.separator()


class CIVIL_PT_pvi_editor(Panel):
    """Sub-panel for PVI point table editor (Civil 3D style grid view)"""

    bl_label = "PVI Editor"
    bl_idname = "CIVIL_PT_pvi_editor"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_horizontal_alignment"
    bl_options = set()  # Open by default

    @classmethod
    def poll(cls, context):
        return tool.Blender.should_show_panel(context, "CIVIL", cls.bl_idname) and is_ifc4x3()

    def draw(self, context):
        layout = self.layout
        props = context.scene.CivilAlignmentProperties

        # PVI Edit Mode indicator
        if props.is_pvi_edit_mode:
            box = layout.box()
            box.alert = True
            box.label(text="PVI Edit Mode Active", icon="EDITMODE_HLT")
            col = box.column(align=True)
            col.label(text="Move PVIs with G key")
            col.label(text="Press Enter to apply")
            col.label(text="Press Escape to cancel")
            layout.separator()
            return  # Don't show normal UI while in edit mode

        # Edit existing alignment button
        if props.active_alignment_id != 0:
            box = layout.box()
            box.label(text="Edit Vertical Alignment:", icon="EDITMODE_HLT")
            box.operator("civil.enter_pvi_edit_mode", icon="PIVOT_CURSOR", text="Edit PVIs (G key)")
            layout.separator()

        # Advisory design-speed check (spec 2.4): flags short vertical curves
        # in the table below; 0 disables.
        layout.prop(props, "design_speed")

        # Header row with column labels
        header = layout.row(align=True)
        header.label(text="No.")
        header.label(text="Type")
        header.label(text="Station")
        header.label(text="Elevation")
        header.label(text="Curve L")
        header.label(text="K")

        # Combined PVI/grade list (interleaved view)
        row = layout.row()
        row.template_list(
            "CIVIL_UL_vertical_pvis",
            "",
            props,
            "vertical_display_rows",
            props,
            "active_vertical_display_row_index",
            rows=8,
        )

        # Side buttons for list management
        col = row.column(align=True)
        col.operator("civil.add_pvi", icon="ADD", text="")
        col.operator("civil.remove_pvi", icon="REMOVE", text="")

        # Bottom actions
        layout.separator()
        row = layout.row(align=True)
        row.operator("civil.recalculate_pvis", icon="FILE_REFRESH", text="Recalculate")
        row.operator("civil.clear_pvis", icon="TRASH", text="Clear All")


class CIVIL_PT_profile_view(Panel):
    """Sub-panel for the 2D profile view (station vs elevation) — D2"""

    bl_label = "Profile View"
    bl_idname = "CIVIL_PT_profile_view"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_horizontal_alignment"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return tool.Blender.should_show_panel(context, "CIVIL", cls.bl_idname) and is_ifc4x3()

    def draw(self, context):
        from . import decorator as alignment_decorator

        layout = self.layout
        props = context.scene.CivilAlignmentProperties

        if props.active_alignment_id == 0:
            layout.label(text="Select an alignment", icon="INFO")
            return

        col = layout.column()
        col.prop(props, "profile_terrain", text="Terrain")
        col.prop(props, "profile_view_interval", text="Interval")
        col.prop(props, "profile_view_height", text="Height (px)")
        col.prop(props, "profile_exaggeration", text="Vert. Exaggeration")

        layout.separator()

        is_shown = alignment_decorator.ProfileViewDecorator.is_installed
        row = layout.row(align=True)
        row.operator(
            "civil.toggle_profile_view",
            icon="HIDE_ON" if is_shown else "HIDE_OFF",
            text="Hide Profile View" if is_shown else "Show Profile View",
            depress=is_shown,
        )
        if is_shown:
            row.operator("civil.refresh_profile_view", icon="FILE_REFRESH", text="")
            layout.operator("civil.edit_pvi_in_profile", icon="PIVOT_CURSOR", text="Edit PVIs (drag in view)")


class CIVIL_PT_alignment_stationing(Panel):
    """Sub-panel for stationing and referents"""

    bl_label = "Stationing"
    bl_idname = "CIVIL_PT_alignment_stationing"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_horizontal_alignment"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return tool.Blender.should_show_panel(context, "CIVIL", cls.bl_idname) and is_ifc4x3()

    def draw(self, context):
        layout = self.layout
        props = context.scene.CivilAlignmentProperties

        # Station display options
        box = layout.box()
        box.label(text="Display:", icon="HIDE_OFF")
        box.prop(props, "show_station_labels")
        box.prop(props, "station_interval")

        layout.separator()

        # Stationing operators
        col = layout.column(align=True)
        col.operator("civil.add_stationing_referent", icon="EMPTY_AXIS")
        col.operator("civil.name_segments", icon="FONT_DATA")

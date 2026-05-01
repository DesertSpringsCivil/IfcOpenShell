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

"""Property groups for the Saikei grading module.

Per spec §8.3 + Phase 5 handoff, the UI exposes:

- A list of authored grading groups in the active IFC project (UIList
  row = :class:`CivilGradingGroupItem`).
- A list of reusable criteria (UIList row = :class:`CivilGradingCriteriaItem`).
- A per-group member list (UIList row = :class:`CivilGradingMemberItem`)
  that's repopulated when the user selects a group.
- Inputs for the operators that author feature lines / criteria /
  groups / grading objects.
- The currently-active group/criteria for editing.
- ``feature_line_edit_mode`` flag — drives the spec §8.4 G-key
  conflict resolution policy (G-key is only active in this mode;
  surface module's modal pickers respect the flag).

The data layer (commit 15) keeps the three collection properties in
sync with the IFC tree on every refresh, mirroring the surface
module's :class:`SurfaceData._sync_uilist_from_ifc` pattern.
"""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import PropertyGroup, UIList


# ---------------------------------------------------------------------------
# Collection-element types
# ---------------------------------------------------------------------------


class CivilGradingGroupItem(PropertyGroup):
    """A single row in the grading-groups list."""

    name: StringProperty(name="Name", default="")
    guid: StringProperty(name="GlobalId", default="")
    ifc_id: IntProperty(name="IFC Step ID", default=0)
    target_surface_guid: StringProperty(
        name="Target Surface",
        description="GUID of the existing-ground surface this group's "
        "slopes project to",
        default="",
    )
    interior_fill: StringProperty(
        name="Interior Fill",
        description="Per spec §6.3: none / flat / interpolate_from_boundary "
        "/ from_surface",
        default="interpolate_from_boundary",
    )
    cut_volume_m3: FloatProperty(
        name="Cut Volume (m³)",
        description="Computed by Phase 6 earthwork module; 0 until "
        "volume calculation runs",
        default=0.0,
    )
    fill_volume_m3: FloatProperty(name="Fill Volume (m³)", default=0.0)


class CivilGradingCriteriaItem(PropertyGroup):
    """A single row in the criteria list."""

    name: StringProperty(name="Name", default="")
    guid: StringProperty(name="GlobalId", default="")
    target_kind: StringProperty(
        name="Target Kind",
        description="One of surface / elevation / relative_elevation / distance",
        default="surface",
    )
    cut_slope: FloatProperty(
        name="Cut Slope (H:V)",
        description="Cut-side slope ratio. 2.0 = 2:1 (2 horizontal to 1 vertical)",
        default=2.0,
    )
    fill_slope: FloatProperty(
        name="Fill Slope (H:V)",
        description="Fill-side slope ratio",
        default=3.0,
    )


class CivilGradingMemberItem(PropertyGroup):
    """A single row in the per-group member list. Repopulated by the
    data layer when the user selects a different group."""

    feature_line_guid: StringProperty(default="")
    feature_line_name: StringProperty(default="")
    criteria_guid: StringProperty(default="")
    criteria_name: StringProperty(default="")
    slope_fill_id: IntProperty(default=0)


# ---------------------------------------------------------------------------
# UILists
# ---------------------------------------------------------------------------


class CIVIL_UL_grading_groups(UIList):
    """UIList for :attr:`CivilGradingProperties.groups`."""

    def draw_item(
        self,
        context,
        layout,
        data,
        item,
        icon,
        active_data,
        active_propname,
        index,
    ):
        kind_icon = "MESH_PLANE"
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)
            row.label(text="", icon=kind_icon)
            row.prop(item, "name", text="", emboss=False)
        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(text=item.name, icon=kind_icon)


class CIVIL_UL_grading_criteria(UIList):
    """UIList for :attr:`CivilGradingProperties.criteria`."""

    _TARGET_KIND_LABELS = {
        "surface": "→Sfc",
        "elevation": "→Z",
        "relative_elevation": "ΔZ",
        "distance": "→D",
    }

    def draw_item(
        self,
        context,
        layout,
        data,
        item,
        icon,
        active_data,
        active_propname,
        index,
    ):
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)
            row.label(text="", icon="CON_TRACKTO")
            row.prop(item, "name", text="", emboss=False)
            label = self._TARGET_KIND_LABELS.get(item.target_kind, "?")
            row.label(text=f"{label} {item.cut_slope:g}:1/{item.fill_slope:g}:1")
        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(text=item.name)


class CIVIL_UL_grading_members(UIList):
    """UIList for :attr:`CivilGradingProperties.active_group_members`."""

    def draw_item(
        self,
        context,
        layout,
        data,
        item,
        icon,
        active_data,
        active_propname,
        index,
    ):
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)
            row.label(text="", icon="IPO_BACK")
            row.label(text=item.feature_line_name or "(unnamed)")
            row.label(text=f"@ {item.criteria_name}")
        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(text=item.feature_line_name)


# ---------------------------------------------------------------------------
# Top-level scene PropertyGroup
# ---------------------------------------------------------------------------


class CivilGradingProperties(PropertyGroup):
    """Top-level Saikei grading module state. Attached to
    ``bpy.types.Scene`` via :func:`bonsai.bim.module.grading.register`."""

    # ----------------------------------------------------------------------
    # Group list
    # ----------------------------------------------------------------------

    groups: CollectionProperty(type=CivilGradingGroupItem)
    active_group_index: IntProperty(
        name="Active Group Index",
        description="Index into :attr:`groups` of the highlighted UIList row",
        default=0,
    )
    active_group_guid: StringProperty(
        name="Active Group GUID",
        description="GlobalId of the currently active grading group",
        default="",
    )
    active_group_id: IntProperty(
        name="Active Group IFC ID",
        description="Step id of the currently active IfcGroup[GradingGroup]",
        default=0,
    )

    active_group_members: CollectionProperty(type=CivilGradingMemberItem)
    active_member_index: IntProperty(name="Active Member Index", default=0)

    # ----------------------------------------------------------------------
    # Criteria list
    # ----------------------------------------------------------------------

    criteria: CollectionProperty(type=CivilGradingCriteriaItem)
    active_criteria_index: IntProperty(name="Active Criteria Index", default=0)
    active_criteria_guid: StringProperty(default="")

    # ----------------------------------------------------------------------
    # Feature-line edit mode (spec §8.4 G-key partition)
    # ----------------------------------------------------------------------

    feature_line_edit_mode: BoolProperty(
        name="Feature Line Edit Mode",
        description="When True, the G-key activates the feature-line "
        "elevation-edit modal. Spec §8.4 G-key conflict resolution: "
        "only one Saikei modal claims G at a time, partitioned by "
        "edit-mode flags.",
        default=False,
    )

    # ----------------------------------------------------------------------
    # New-feature-line operator inputs
    # ----------------------------------------------------------------------

    new_feature_line_name: StringProperty(
        name="Name", default="Pad Perimeter"
    )
    new_feature_line_csv_filepath: StringProperty(
        name="CSV Filepath",
        description="Path to a CSV / whitespace-separated XYZ vertex file",
        subtype="FILE_PATH",
        default="",
    )
    new_feature_line_closed: BoolProperty(
        name="Closed Loop",
        description="True for closed loops (pad perimeters), False for "
        "open lines (e.g., ditch centerlines)",
        default=True,
    )

    # ----------------------------------------------------------------------
    # New-criteria operator inputs
    # ----------------------------------------------------------------------

    new_criteria_name: StringProperty(name="Name", default="3:1 fill / 2:1 cut")
    new_criteria_target_kind: EnumProperty(
        name="Target Kind",
        items=[
            ("surface", "Surface", "Project until intersecting a target surface"),
            ("elevation", "Elevation", "Project until reaching an absolute Z"),
            (
                "relative_elevation",
                "Relative Elevation",
                "Project until reaching a Z delta from the feature line",
            ),
            ("distance", "Distance", "Project to a fixed horizontal offset"),
        ],
        default="surface",
    )
    new_criteria_target_ref: StringProperty(
        name="Target Reference",
        description="For surface: GUID of target. For numeric kinds: float "
        "value as string.",
        default="",
    )
    new_criteria_cut_slope: FloatProperty(
        name="Cut Slope (H:V)", default=2.0, min=0.01
    )
    new_criteria_fill_slope: FloatProperty(
        name="Fill Slope (H:V)", default=3.0, min=0.01
    )
    new_criteria_max_distance: FloatProperty(
        name="Max Distance",
        description="Daylight cap; 0 = unlimited",
        default=0.0,
        min=0.0,
    )
    new_criteria_retaining_wall: BoolProperty(
        name="Retaining Wall at Limit",
        description="When True, terminate at max_distance with a vertical "
        "wall rather than raising on cap-exceeded",
        default=False,
    )

    # ----------------------------------------------------------------------
    # New-group operator inputs
    # ----------------------------------------------------------------------

    new_group_name: StringProperty(name="Name", default="Grading Group 1")
    new_group_target_surface_guid: StringProperty(
        name="Target Surface GUID",
        description="GUID of the existing-ground surface; populate from "
        "the surface module's UIList selection",
        default="",
    )
    new_group_interior_fill: EnumProperty(
        name="Interior Fill",
        items=[
            ("none", "None", "No interior fill — surface has a hole"),
            ("flat", "Flat", "Interior at the average feature-line elevation"),
            (
                "interpolate_from_boundary",
                "Interpolate from Boundary",
                "Delaunay over feature-line vertices (Civil 3D default)",
            ),
            (
                "from_surface",
                "From Surface",
                "Drape feature-line ring onto a source surface",
            ),
        ],
        default="interpolate_from_boundary",
    )
    new_group_interior_fill_source_guid: StringProperty(
        name="Interior Fill Source GUID",
        description="Required when interior_fill == 'from_surface'",
        default="",
    )

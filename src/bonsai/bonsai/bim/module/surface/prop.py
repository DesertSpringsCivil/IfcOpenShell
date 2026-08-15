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

"""Property groups for the Saikei surface module.

Per spec §8 + Phase 4 handoff, the UI exposes:

- A list of authored surfaces in the active IFC project (UIList row =
  :class:`CivilSurfaceListItem`).
- Inputs for the "create surface from points" operator (name, kind, tolerance).
- The currently-active surface for editing.
- Display toggles for the GPU decorator (triangle wireframe, elevation banding).

The decorator install/uninstall ``update=`` callbacks are wired up in
commit 15 alongside the :class:`SurfaceDecorator` itself; at this commit
the booleans are inert and the ``classes`` tuple in
:mod:`bonsai.bim.module.surface` registers the property groups against
``bpy.types.Scene``.
"""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    IntVectorProperty,
    StringProperty,
)
from bpy.types import PropertyGroup, UIList


def _on_active_surface_index_change(
    self, context: bpy.types.Context
) -> None:
    """Sync :attr:`active_surface_id` and :attr:`active_surface_guid` from
    the highlighted UIList row.

    Without this, clicking a row in :class:`CIVIL_UL_surfaces` only changes
    the visually-highlighted row — the operator-targeting fields stay
    pointed at whichever surface was last *created*, which makes editing
    any earlier surface impossible through the panel. With this callback,
    the active GUID always matches the selected list row.

    Empty / out-of-range indices clear the active state so downstream
    polls (``CIVIL_PT_surface_active.poll``) hide the active panel rather
    than running against stale references.
    """
    if 0 <= self.active_surface_index < len(self.surfaces):
        item = self.surfaces[self.active_surface_index]
        self.active_surface_id = item.ifc_id
        self.active_surface_guid = item.guid
    else:
        self.active_surface_id = 0
        self.active_surface_guid = ""


def _on_decorator_toggle_change(self, context: bpy.types.Context) -> None:
    """Install / uninstall :class:`SurfaceDecorator` based on the two
    decorator-toggle booleans.

    Lazy-imports the decorator module to avoid the circular import that
    would otherwise hit (decorator imports tool which imports the bim
    module's prop). The handler runs when ``show_triangles`` or
    ``show_elevation_banding`` flips — installed once with both False
    means "uninstall completely"; either True means "install if not
    already installed".
    """
    from . import decorator as surface_decorator

    if self.show_triangles or self.show_elevation_banding:
        if not surface_decorator.SurfaceDecorator.is_installed:
            surface_decorator.SurfaceDecorator.install(context)
    else:
        surface_decorator.SurfaceDecorator.uninstall()


class CivilSurfaceListItem(PropertyGroup):
    """A single row in the surface list. Points the UI at one authored
    surface entity in the IFC file."""

    name: StringProperty(
        name="Name",
        description="Surface name (matches IfcGeographicElement.Name or "
        "IfcEarthworksFill.Name)",
        default="",
    )
    guid: StringProperty(
        name="GlobalId",
        description="IFC GlobalId of the host entity",
        default="",
    )
    ifc_id: IntProperty(
        name="IFC Step ID",
        description="Step id of the host entity (IfcGeographicElement or "
        "IfcEarthworksFill)",
        default=0,
    )
    kind: StringProperty(
        name="Kind",
        description="One of existing / proposed_group / proposed_site",
        default="existing",
    )


class CIVIL_UL_surfaces(UIList):
    """UIList for :attr:`CivilSurfaceProperties.surfaces`.

    Renders one row per surface with a kind-appropriate icon. The
    panel (commit 14) draws this list above the active-surface details.
    """

    _KIND_ICON = {
        "existing": "WORLD",
        "proposed_group": "MESH_PLANE",
        "proposed_site": "OUTLINER_OB_SURFACE",
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
        kind_icon = self._KIND_ICON.get(item.kind, "MESH_DATA")
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)
            row.label(text="", icon=kind_icon)
            row.prop(item, "name", text="", emboss=False)
        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(text=item.name, icon=kind_icon)


class CivilSurfaceProperties(PropertyGroup):
    """Top-level Saikei surface module state. Attached to ``bpy.types.Scene``
    via :func:`bonsai.bim.module.surface.register`."""

    # ----------------------------------------------------------------------
    # New-surface creation inputs (consumed by CIVIL_OT_surface_create_from_points)
    # ----------------------------------------------------------------------

    new_surface_name: StringProperty(
        name="Name",
        description="Name for the new surface entity",
        default="Existing Ground",
    )

    new_surface_kind: EnumProperty(
        name="Kind",
        description="Surface kind drives the IFC host entity per spec §2.2",
        items=[
            (
                "existing",
                "Existing Ground",
                "IfcGeographicElement[TERRAIN] — natural terrain",
            ),
            (
                "proposed_group",
                "Proposed (Group)",
                "IfcEarthworksFill[SUBGRADE] within a grading group",
            ),
            (
                "proposed_site",
                "Proposed (Site)",
                "IfcEarthworksFill[SUBGRADE] at the composite site root",
            ),
        ],
        default="existing",
    )

    triangulation_tolerance: FloatProperty(
        name="Triangulation Tolerance",
        description="Maximum point-to-surface distance below which a point "
        "may be omitted from the TIN (stored on SaikeiCivil_GradingSurface)",
        default=0.0,
        min=0.0,
        max=1.0,
        precision=4,
    )

    # ----------------------------------------------------------------------
    # Active-surface state (set by the panel's UIList selection callback)
    # ----------------------------------------------------------------------

    active_surface_id: IntProperty(
        name="Active Surface IFC ID",
        description="Step id of the currently active surface host entity, or "
        "0 if no surface is selected",
        default=0,
    )

    active_surface_guid: StringProperty(
        name="Active Surface GUID",
        description="GlobalId of the currently active surface, or empty if "
        "no surface is selected",
        default="",
    )

    # ----------------------------------------------------------------------
    # Surface-list collection (the UIList drives this)
    # ----------------------------------------------------------------------

    surfaces: CollectionProperty(type=CivilSurfaceListItem)

    active_surface_index: IntProperty(
        name="Active Surface Index",
        description="Index into :attr:`surfaces` of the highlighted UIList row. "
        "Selecting a different row updates :attr:`active_surface_id` and "
        ":attr:`active_surface_guid` via the update callback so subsequent "
        "edit operators target the correct surface",
        default=0,
        update=_on_active_surface_index_change,
    )

    # ----------------------------------------------------------------------
    # CSV column-remap inputs (consumed by CIVIL_OT_surface_create_from_points)
    # ----------------------------------------------------------------------

    csv_column_map: IntVectorProperty(
        name="Column Map (X, Y, Z)",
        description=(
            "1-indexed column numbers for X, Y, and Z in the CSV file. "
            "Default (1, 2, 3) reads the first three columns as X, Y, Z. "
            "Change when your file has a different column order (e.g. Z first "
            "would be (3, 2, 1) for Z, Y, X)"
        ),
        size=3,
        default=(1, 2, 3),
        min=1,
        soft_max=20,
    )

    csv_skip_header_rows: IntProperty(
        name="Skip Header Rows",
        description="Number of leading rows to skip before reading point data "
        "(e.g., 1 if your CSV has a header row with column labels)",
        default=0,
        min=0,
        soft_max=10,
    )

    # ----------------------------------------------------------------------
    # GPU decorator toggles (the ``update=`` hooks land in commit 15
    # alongside the SurfaceDecorator class)
    # ----------------------------------------------------------------------

    show_triangles: BoolProperty(
        name="Show Triangles",
        description="Render the TIN triangle wireframe via the surface decorator",
        default=False,
        update=_on_decorator_toggle_change,
    )

    show_elevation_banding: BoolProperty(
        name="Show Elevation Banding",
        description="Render the TIN with per-vertex elevation colors via the "
        "surface decorator",
        default=False,
        update=_on_decorator_toggle_change,
    )

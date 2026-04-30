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

"""Operators for the Saikei surface module.

Each operator follows the Bonsai standard pattern:

- Inherits ``tool.Ifc.Operator`` so undo/redo, IFC mutation tracking, and
  validation hooks run automatically.
- Implements ``_execute(self, context)`` (not ``execute()``) — Bonsai wraps
  the underscore form with the IFC operator boilerplate.
- Operators that author IFC catch typed tool exceptions
  (:class:`SaikeiSurfaceError`, :class:`SaikeiTriangulationError`) and
  convert them to ``self.report({"ERROR"}, ...)`` + ``CANCELLED`` per the
  spec §8.5 modal/headless contract. Headless callers via
  ``bpy.ops.civil.surface_<X>("EXEC_DEFAULT", ...)`` receive the same
  cancelled/finished result codes (with ``self.report`` writing to
  ``bpy.context.window_manager.reports``).
"""

import bpy
from bpy.props import FloatProperty, StringProperty
from bpy.types import Operator

import bonsai.core.surface as core_surface
import bonsai.tool as tool
import bonsai.tool.surface as tool_surface


class CIVIL_OT_surface_create_from_points(Operator, tool.Ifc.Operator):
    """Build a TIN from a CSV / XYZ point cloud and persist as IFC.

    Inputs come from two places:

    - :class:`CivilSurfaceProperties` (scene-level): ``new_surface_name``,
      ``new_surface_kind``, ``triangulation_tolerance``.
    - The operator's own ``csv_filepath`` property — populated by Blender's
      file selector when invoked from the panel button, or set explicitly
      by headless callers.

    Headless usage::

        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath="/path/to/points.csv"
        )

    The created surface is linked to a Blender mesh via
    :meth:`tool.Surface.create_blender_mesh` so the user sees the TIN in
    the viewport immediately after creation.
    """

    bl_idname = "civil.surface_create_from_points"
    bl_label = "Create Surface from Points"
    bl_description = (
        "Build a TIN from a CSV or whitespace-separated XYZ file and persist "
        "as IfcGeographicElement[TERRAIN] (existing) or "
        "IfcEarthworksFill[SUBGRADE] (proposed)"
    )
    bl_options = {"REGISTER", "UNDO"}

    csv_filepath: StringProperty(
        name="CSV / XYZ Filepath",
        description="Path to a comma- or whitespace-separated XYZ point file",
        subtype="FILE_PATH",
    )
    filter_glob: StringProperty(
        default="*.csv;*.txt;*.xyz",
        options={"HIDDEN"},
    )

    def _execute(self, context):
        props = context.scene.CivilSurfaceProperties
        try:
            points = tool.Surface.load_points_from_csv(self.csv_filepath)
        except tool_surface.SaikeiSurfaceError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        try:
            surface = core_surface.create_surface_from_points(
                tool.Ifc,
                tool.Surface,
                name=props.new_surface_name,
                points=points,
                kind=props.new_surface_kind,
                triangulation_tolerance=props.triangulation_tolerance,
            )
        except (ValueError, tool_surface.SaikeiSurfaceError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        # Create the Blender mesh + collection-assigned object so the user
        # sees the TIN in the viewport.
        try:
            tool.Surface.create_blender_mesh(tool.Ifc.get(), surface)
        except tool_surface.SaikeiSurfaceError as exc:
            # The IFC entity exists; only the Blender mirror failed. Report
            # but don't cancel — the IFC write succeeded.
            self.report(
                {"WARNING"},
                f"surface authored to IFC but Blender mesh creation failed: {exc}",
            )

        # Append the new surface to the panel's UIList.
        list_item = props.surfaces.add()
        list_item.name = surface.name
        list_item.guid = surface.guid
        list_item.ifc_id = surface.ifc_host_entity_id or 0
        list_item.kind = surface.kind
        props.active_surface_index = len(props.surfaces) - 1
        props.active_surface_id = list_item.ifc_id
        props.active_surface_guid = list_item.guid

        self.report(
            {"INFO"},
            f"Created surface {surface.name!r} ({len(points)} pts → "
            f"{len(surface.triangles)} triangles)",
        )
        return {"FINISHED"}

    def invoke(self, context, event):
        # If the user already populated csv_filepath (e.g., via a property
        # bound on the panel), skip the file dialog and execute directly.
        if self.csv_filepath:
            return self.execute(context)
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

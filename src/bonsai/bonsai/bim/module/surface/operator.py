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
  convert them to ``self.report({"ERROR"}, ...)`` + ``return {"CANCELLED"}``
  inside ``_execute``.

.. note::

    **Bonsai's `tool.Ifc.Operator.execute` always returns
    ``{"FINISHED"}``** regardless of what ``_execute`` returns — the
    inner CANCELLED is dropped at the wrapper boundary (see
    ``tool/ifc.py:execute``, decorated ``@final``). What the headless
    caller actually sees is:

    1. An ``ERROR``-level report on the Window Manager's reports list.
    2. Blender re-raises that report as a Python ``RuntimeError`` from
       the ``bpy.ops`` boundary call. Headless tests use
       ``pytest.raises(RuntimeError)`` to detect cancellation.

    Callers that need a clean status code should also assert "no IFC
    entity was authored" as a behavior check rather than relying on
    the return set.
"""

import bpy
import ifcopenshell.guid
import shapely
from bpy.props import EnumProperty, StringProperty
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


class CIVIL_OT_surface_retriangulate(Operator, tool.Ifc.Operator):
    """Force-rebuild the active surface's TIN.

    Headless-only ([H] per spec §8.6) — exposed in the panel as a small
    "rebuild" button for cases where authoring polygons were edited
    out-of-band. Most edit flows (set_boundary, add_breakline) already
    retriangulate automatically.

    Headless usage::

        bpy.ops.civil.surface_retriangulate("EXEC_DEFAULT")
    """

    bl_idname = "civil.surface_retriangulate"
    bl_label = "Retriangulate Active Surface"
    bl_description = (
        "Force a constrained-Delaunay rebuild of the active surface's TIN. "
        "Rarely needed manually — boundary / breakline edits already retriangulate"
    )
    bl_options = {"REGISTER", "UNDO"}

    def _execute(self, context):
        props = context.scene.CivilSurfaceProperties
        if not props.active_surface_guid:
            self.report(
                {"ERROR"},
                "No active surface — select one in the panel UIList first",
            )
            return {"CANCELLED"}

        try:
            surface = core_surface.retriangulate_surface(
                tool.Ifc, tool.Surface, surface_guid=props.active_surface_guid
            )
        except (ValueError, tool_surface.SaikeiSurfaceError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        try:
            tool.Surface.update_blender_mesh(tool.Ifc.get(), surface)
        except tool_surface.SaikeiSurfaceError as exc:
            self.report({"WARNING"}, f"Blender mesh refresh failed: {exc}")

        self.report(
            {"INFO"},
            f"Retriangulated {surface.name} → {len(surface.triangles)} triangles",
        )
        return {"FINISHED"}


class CIVIL_OT_surface_set_boundary(Operator, tool.Ifc.Operator):
    """Replace the active surface's outer-boundary polygon.

    Modal entry per spec §8.5: ``invoke()`` opens a file selector for a
    polygon-ring CSV/XYZ file (≥ 3 rows of x,y,z; Z is ignored — the
    polygon is XY only). The interactive viewport-pick polygon flow is a
    Phase 4.1+ refinement.

    The CSV may be open (last point ≠ first point) — :class:`shapely.Polygon`
    closes the ring automatically.

    Headless usage::

        bpy.ops.civil.surface_set_boundary(
            "EXEC_DEFAULT", csv_filepath="/path/to/ring.csv"
        )
    """

    bl_idname = "civil.surface_set_boundary"
    bl_label = "Set Outer Boundary"
    bl_description = (
        "Replace the active surface's outer-boundary polygon and "
        "retriangulate. Polygon ring loaded from a CSV / XYZ file."
    )
    bl_options = {"REGISTER", "UNDO"}

    csv_filepath: StringProperty(
        name="Boundary CSV / XYZ",
        description="Path to a CSV / whitespace-separated XYZ file describing "
        "the polygon ring (≥ 3 rows of x,y,z; Z is ignored)",
        subtype="FILE_PATH",
    )
    filter_glob: StringProperty(
        default="*.csv;*.txt;*.xyz",
        options={"HIDDEN"},
    )

    def _execute(self, context):
        props = context.scene.CivilSurfaceProperties
        if not props.active_surface_guid:
            self.report(
                {"ERROR"},
                "No active surface — select one in the panel UIList first",
            )
            return {"CANCELLED"}

        try:
            ring_points = tool.Surface.load_points_from_csv(self.csv_filepath)
        except tool_surface.SaikeiSurfaceError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        if ring_points.shape[0] < 3:
            self.report(
                {"ERROR"},
                f"boundary polygon needs ≥ 3 vertices; got {ring_points.shape[0]}",
            )
            return {"CANCELLED"}

        try:
            polygon = shapely.Polygon(
                [(float(p[0]), float(p[1])) for p in ring_points]
            )
        except (ValueError, shapely.errors.GEOSException) as exc:
            self.report({"ERROR"}, f"could not build polygon from ring: {exc}")
            return {"CANCELLED"}

        if not polygon.is_valid:
            self.report(
                {"ERROR"},
                f"polygon is not topologically valid: "
                f"{shapely.is_valid_reason(polygon)}",
            )
            return {"CANCELLED"}

        try:
            surface = core_surface.set_outer_boundary(
                tool.Ifc,
                tool.Surface,
                surface_guid=props.active_surface_guid,
                boundary_polygon=polygon,
            )
        except (ValueError, tool_surface.SaikeiSurfaceError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        try:
            tool.Surface.update_blender_mesh(tool.Ifc.get(), surface)
        except tool_surface.SaikeiSurfaceError as exc:
            self.report({"WARNING"}, f"Blender mesh refresh failed: {exc}")

        self.report(
            {"INFO"},
            f"Set boundary on {surface.name} → {len(surface.triangles)} triangles",
        )
        return {"FINISHED"}

    def invoke(self, context, event):
        if self.csv_filepath:
            return self.execute(context)
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class CIVIL_OT_surface_add_breakline(Operator, tool.Ifc.Operator):
    """Add a breakline to the active surface and retriangulate.

    Modal entry per spec §8.5: ``invoke()`` opens a file selector for a
    polyline CSV/XYZ file (same format as ``CIVIL_OT_surface_create_from_points``
    — three columns of XYZ floats, one row per polyline vertex). The
    interactive viewport-pick modal flow (click points to define the
    polyline) is a Phase 4.1+ refinement; for now the file-dialog path
    covers both UI invocation and headless callers.

    Headless usage::

        bpy.ops.civil.surface_add_breakline(
            "EXEC_DEFAULT",
            csv_filepath="/path/to/polyline.csv",
            kind="standard",
            breakline_name="ridge",
        )

    Reads :attr:`CivilSurfaceProperties.active_surface_guid` to identify
    the host surface.
    """

    bl_idname = "civil.surface_add_breakline"
    bl_label = "Add Breakline to Surface"
    bl_description = (
        "Append a breakline polyline to the active surface, persist as "
        "IfcAnnotation, and retriangulate the TIN to honor the new edge. "
        "Phase 4 limitation: the polyline must fully cross the outer "
        "boundary — internal-only ridges (start and end inside the surface) "
        "are silently dropped by the constrained Delaunay backend"
    )
    bl_options = {"REGISTER", "UNDO"}

    csv_filepath: StringProperty(
        name="Polyline CSV / XYZ",
        description="Path to a CSV / whitespace-separated XYZ file describing "
        "an ordered polyline (≥ 2 rows of x,y,z)",
        subtype="FILE_PATH",
    )
    filter_glob: StringProperty(
        default="*.csv;*.txt;*.xyz",
        options={"HIDDEN"},
    )
    kind: EnumProperty(
        name="Kind",
        description="Breakline kind per spec §2.3",
        items=[
            ("standard", "Standard", "Edges added to the TIN at each segment"),
            ("wall", "Wall", "Edges added; downstream may render a vertical face"),
            (
                "non_destructive",
                "Non-Destructive",
                "Edges added without splitting existing triangles",
            ),
            (
                "proximity",
                "Proximity",
                "Triangles flagged near this polyline; no edges forced",
            ),
        ],
        default="standard",
    )
    breakline_name: StringProperty(
        name="Name",
        description="Human-readable label for the IfcAnnotation",
        default="Breakline",
    )
    source: StringProperty(
        name="Source",
        description="Free-form provenance label (manual, feature_line, etc.)",
        default="manual",
    )

    def _execute(self, context):
        props = context.scene.CivilSurfaceProperties
        if not props.active_surface_guid:
            self.report(
                {"ERROR"},
                "No active surface — select a surface in the panel UIList first",
            )
            return {"CANCELLED"}

        try:
            polyline_points = tool.Surface.load_points_from_csv(self.csv_filepath)
        except tool_surface.SaikeiSurfaceError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        if polyline_points.shape[0] < 2:
            self.report(
                {"ERROR"},
                f"breakline polyline must have ≥ 2 points; got {polyline_points.shape[0]}",
            )
            return {"CANCELLED"}

        breakline = tool_surface.Breakline(
            guid=ifcopenshell.guid.new(),
            name=self.breakline_name,
            polyline=[
                (float(p[0]), float(p[1]), float(p[2])) for p in polyline_points
            ],
            kind=self.kind,
            source=self.source,
        )

        try:
            surface = core_surface.add_breakline_to_surface(
                tool.Ifc,
                tool.Surface,
                surface_guid=props.active_surface_guid,
                breakline=breakline,
            )
        except (ValueError, tool_surface.SaikeiSurfaceError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        # Refresh the Blender mesh so the user sees the rebuilt TIN with the
        # new breakline edges.
        try:
            tool.Surface.update_blender_mesh(tool.Ifc.get(), surface)
        except tool_surface.SaikeiSurfaceError as exc:
            self.report(
                {"WARNING"},
                f"breakline added to IFC but Blender mesh refresh failed: {exc}",
            )

        self.report(
            {"INFO"},
            f"Added breakline {breakline.name!r} ({len(breakline.polyline)} pts) "
            f"to {surface.name}",
        )
        return {"FINISHED"}

    def invoke(self, context, event):
        if self.csv_filepath:
            return self.execute(context)
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

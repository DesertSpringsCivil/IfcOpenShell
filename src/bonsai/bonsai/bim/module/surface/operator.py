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

import json

import bpy
from bpy.props import EnumProperty, FloatProperty, StringProperty
from bpy.types import Operator

import bonsai.core.surface as core_surface
import bonsai.tool as tool
import bonsai.tool.surface as tool_surface
from bonsai.bim.module.surface.data import SurfaceData


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
        "as a terrain surface (existing) or proposed surface"
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
        # csv_column_map is 1-indexed (user-friendly); tool layer is 0-indexed.
        columns: tuple[int, int, int] = tuple(  # type: ignore[assignment]
            int(c) - 1 for c in props.csv_column_map
        )
        try:
            points = tool.Surface.load_points_from_csv(
                self.csv_filepath,
                columns=columns,
                skip_header_rows=int(props.csv_skip_header_rows),
            )
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

        # The UIList rebuilds itself via SurfaceData._sync_uilist_from_ifc
        # which Bonsai's refresh_ui_data hook fires after every IFC
        # mutation (this operator inherits tool.Ifc.Operator → triggers
        # the refresh). We only set the active selection here so the
        # user sees the new surface highlighted — the row itself will
        # appear via the refresh.
        SurfaceData.is_loaded = False
        SurfaceData.load()
        # SurfaceData.load preserves the previously-selected GUID if it's
        # still in the list. Override to make the freshly-created surface
        # the active selection.
        for index, item in enumerate(props.surfaces):
            if item.guid == surface.guid:
                props.active_surface_index = index
                break

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
        "the polygon ring (>= 3 rows of x,y,z; Z is ignored)",
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
            polygon = tool.Surface.build_boundary_polygon_from_ring(ring_points)
        except tool_surface.SaikeiSurfaceError as exc:
            self.report({"ERROR"}, str(exc))
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
        "Append a breakline polyline to the active surface, persist as a "
        "breakline annotation, and retriangulate the TIN to honor the new edge. "
        "Phase 4 limitation: the polyline must fully cross the outer "
        "boundary - internal-only ridges (start and end inside the surface) "
        "are silently dropped by the constrained Delaunay backend"
    )
    bl_options = {"REGISTER", "UNDO"}

    csv_filepath: StringProperty(
        name="Polyline CSV / XYZ",
        description="Path to a CSV / whitespace-separated XYZ file describing "
        "an ordered polyline (>= 2 rows of x,y,z)",
        subtype="FILE_PATH",
    )
    filter_glob: StringProperty(
        default="*.csv;*.txt;*.xyz",
        options={"HIDDEN"},
    )
    kind: EnumProperty(
        name="Kind",
        description="Breakline kind (standard, wall, non_destructive, proximity)",
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
        description="Breakline name (used as the entity Name in the IFC file)",
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

        # core_surface.add_breakline_to_surface enforces the ≥ 2-point rule
        # (business validation belongs in core, not the UI layer).
        # Breakline.guid defaults via ifcopenshell.guid.new() — no need to
        # mint one in the UI layer.
        breakline = tool_surface.Breakline(
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


class CIVIL_OT_surface_rename(Operator, tool.Ifc.Operator):
    """Rename the active surface in the UIList.

    Reads the target surface from :attr:`surface_guid` (defaults to
    :attr:`CivilSurfaceProperties.active_surface_guid` when not supplied by
    the caller) and writes ``new_name`` to the IFC entity's ``Name``
    attribute.

    Headless usage::

        bpy.ops.civil.surface_rename(
            "EXEC_DEFAULT", surface_guid="<guid>", new_name="Road Centerline DG"
        )
    """

    bl_idname = "civil.surface_rename"
    bl_label = "Rename Surface"
    bl_description = "Rename the active surface."
    bl_options = {"REGISTER", "UNDO"}

    surface_guid: StringProperty(
        name="Surface GUID",
        description="GlobalId of the surface to rename. Defaults to the "
        "active UIList selection when empty",
        default="",
    )
    new_name: StringProperty(
        name="New Name",
        description="New human-readable name for the surface",
        default="",
    )

    def _execute(self, context):
        props = context.scene.CivilSurfaceProperties
        target_guid = self.surface_guid or props.active_surface_guid
        if not target_guid:
            self.report(
                {"ERROR"},
                "No active surface — select one in the UIList or supply surface_guid",
            )
            return {"CANCELLED"}
        if not self.new_name or not self.new_name.strip():
            self.report({"ERROR"}, "new_name cannot be empty")
            return {"CANCELLED"}

        try:
            tool.Surface.rename(target_guid, self.new_name.strip())
        except tool_surface.SaikeiSurfaceError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        SurfaceData.is_loaded = False
        self.report({"INFO"}, f"Renamed surface to {self.new_name.strip()!r}")
        return {"FINISHED"}


class CIVIL_OT_surface_delete(Operator, tool.Ifc.Operator):
    """Delete the active surface.

    Destroys the IFC host entity, its representation tree, all scoped
    breakline :class:`IfcAnnotation` siblings, and the linked Blender mesh
    object. Irreversible; Blender undo captures the pre-delete state.

    Headless usage::

        bpy.ops.civil.surface_delete("EXEC_DEFAULT", surface_guid="<guid>")
    """

    bl_idname = "civil.surface_delete"
    bl_label = "Delete Surface"
    bl_description = "Permanently delete the active surface and its breaklines."
    bl_options = {"REGISTER", "UNDO"}

    surface_guid: StringProperty(
        name="Surface GUID",
        description="GlobalId of the surface to delete. Defaults to the "
        "active UIList selection when empty",
        default="",
    )

    def _execute(self, context):
        props = context.scene.CivilSurfaceProperties
        target_guid = self.surface_guid or props.active_surface_guid
        if not target_guid:
            self.report(
                {"ERROR"},
                "No active surface — select one in the UIList or supply surface_guid",
            )
            return {"CANCELLED"}

        try:
            core_surface.delete_surface(tool.Ifc, tool.Surface, target_guid)
        except (ValueError, tool_surface.SaikeiSurfaceError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        # Clear active selection if it pointed at the deleted surface.
        if props.active_surface_guid == target_guid:
            props.active_surface_guid = ""
            props.active_surface_id = 0

        SurfaceData.is_loaded = False
        SurfaceData.load()
        self.report({"INFO"}, f"Deleted surface {target_guid!r}")
        return {"FINISHED"}


class CIVIL_OT_surface_select(Operator):
    """Select the Blender mesh object backing the active UIList row.

    Pure UI operator — makes no IFC changes. Sets the viewport selection
    to the linked Blender mesh object so the user can camera-frame
    (:kbd:`Numpad .`) or inspect the surface in the 3D viewport.

    Also syncs :attr:`CivilSurfaceProperties.active_surface_index` to the
    UIList row that matches ``surface_guid``, so the panel list and the
    viewport selection stay in agreement.

    Headless usage::

        bpy.ops.civil.surface_select("EXEC_DEFAULT", surface_guid="<guid>")
    """

    bl_idname = "civil.surface_select"
    bl_label = "Select Surface"
    bl_description = "Select the active surface in the viewport."
    bl_options = {"REGISTER", "UNDO"}

    surface_guid: StringProperty(
        name="Surface GUID",
        description="GlobalId of the surface to select. Defaults to the "
        "active UIList selection when empty",
        default="",
    )

    def execute(self, context):
        props = context.scene.CivilSurfaceProperties
        target_guid = self.surface_guid or props.active_surface_guid
        if not target_guid:
            self.report(
                {"ERROR"},
                "No active surface — select one in the UIList or supply surface_guid",
            )
            return {"CANCELLED"}

        ifc_file = tool.Ifc.get()
        if ifc_file is None:
            self.report({"ERROR"}, "No IFC file loaded")
            return {"CANCELLED"}

        host = tool.Surface.get_host_entity(ifc_file, target_guid)
        if host is None:
            self.report(
                {"ERROR"},
                f"No IFC entity with GlobalId {target_guid!r} in this file",
            )
            return {"CANCELLED"}

        obj = tool.Ifc.get_object(host)
        if obj is None:
            self.report(
                {"WARNING"},
                "Surface has no linked Blender object — cannot select",
            )
            return {"CANCELLED"}

        # Deselect all, then select the surface object.
        for scene_obj in context.scene.objects:
            scene_obj.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj

        # Sync UIList index to the matching row.
        for index, item in enumerate(props.surfaces):
            if item.guid == target_guid:
                props.active_surface_index = index
                break

        return {"FINISHED"}


class CIVIL_OT_surface_pick_breakline(Operator, tool.Ifc.Operator):
    """Add a breakline to the active surface by interactively picking vertices.

    Modal entry (``invoke``): click to add polyline vertices; Enter commits;
    Esc cancels. On commit the captured vertex list is written to
    ``polyline_object_name`` and ``_execute`` authors the breakline IFC entity.

    Headless / ``_from_data`` path: the same class invoked with
    ``EXEC_DEFAULT``; set ``polyline_object_name`` to an existing
    ``bpy.data.curves`` object whose spline vertices define the polyline.

    Headless usage::

        bpy.ops.civil.surface_pick_breakline(
            "EXEC_DEFAULT",
            polyline_object_name="MyPolylineCurve",
            surface_guid="<guid>",
        )
    """

    bl_idname = "civil.surface_pick_breakline"
    bl_label = "Pick Breakline"
    bl_description = (
        "Click to place polyline vertices on the surface; Enter commits the "
        "breakline to IFC; Esc cancels."
    )
    bl_options = {"REGISTER", "UNDO"}

    vertices_json: StringProperty(
        name="Vertices JSON",
        description="JSON-encoded list of [[x,y,z], ...] vertices set by the "
        "modal on commit. Empty when the headless polyline_object_name path is "
        "used instead.",
        default="",
        options={"SKIP_SAVE"},
    )
    polyline_object_name: StringProperty(
        name="Polyline Object Name",
        description="Name of a Blender curve object whose points define the "
        "breakline polyline. Used for the headless EXEC_DEFAULT path when "
        "the caller already has a curve object. The modal path uses "
        "vertices_json instead (no orphan curve created on cancel).",
        default="",
    )
    surface_guid: StringProperty(
        name="Surface GUID",
        description="GlobalId of the target surface. Defaults to the active "
        "UIList selection when empty.",
        default="",
    )
    breakline_name: StringProperty(
        name="Breakline Name",
        description="Human-readable name for the authored IFC breakline entity.",
        default="Breakline",
    )
    kind: EnumProperty(
        name="Kind",
        description="Breakline kind (standard, wall, non_destructive, proximity)",
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

    # --- Modal state (not operator properties — not serialised) ---------------
    _vertices: list  # accumulated click vertices

    def invoke(self, context, event):
        self._vertices = []
        context.window_manager.modal_handler_add(self)
        self.report({"INFO"}, "Click to add vertices; Enter to commit; Esc to cancel")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            # Ray-cast against the scene to find 3D position.
            region = context.region
            rv3d = context.region_data
            coord = (event.mouse_region_x, event.mouse_region_y)
            from bpy_extras import view3d_utils

            view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
            ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
            # Default Z = 0 plane for simplicity (Phase 7b scope).
            if view_vector.z != 0:
                t = -ray_origin.z / view_vector.z
                hit = ray_origin + t * view_vector
            else:
                hit = ray_origin
            self._vertices.append((float(hit.x), float(hit.y), float(hit.z)))
            context.area.tag_redraw()
            return {"RUNNING_MODAL"}

        elif event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            if len(self._vertices) < 2:
                self.report({"ERROR"}, "Need at least 2 vertices for a breakline")
                return {"CANCELLED"}
            # Stash vertices as JSON — no bpy.data mutation in modal().
            # _execute() builds the polyline directly from this JSON blob.
            self.vertices_json = json.dumps(self._vertices)
            return self.execute(context)

        elif event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self.report({"INFO"}, "Breakline pick cancelled")
            return {"CANCELLED"}

        return {"PASS_THROUGH"}

    def _execute(self, context):
        props = context.scene.CivilSurfaceProperties
        target_guid = self.surface_guid or props.active_surface_guid
        if not target_guid:
            self.report(
                {"ERROR"},
                "No active surface — select one in the UIList or supply surface_guid",
            )
            return {"CANCELLED"}

        # Resolve the polyline from either the JSON blob (modal path) or the
        # curve-object name (headless EXEC_DEFAULT path).
        if self.vertices_json:
            try:
                raw_verts = json.loads(self.vertices_json)
                polyline = [(float(v[0]), float(v[1]), float(v[2])) for v in raw_verts]
            except (ValueError, KeyError, TypeError) as exc:
                self.report({"ERROR"}, f"Invalid vertices_json: {exc}")
                return {"CANCELLED"}
        elif self.polyline_object_name:
            curve_obj = bpy.data.objects.get(self.polyline_object_name)
            if curve_obj is None or curve_obj.data is None:
                self.report(
                    {"ERROR"},
                    f"No curve object named {self.polyline_object_name!r}",
                )
                return {"CANCELLED"}

            curve_data = curve_obj.data
            if not hasattr(curve_data, "splines") or len(curve_data.splines) == 0:
                self.report({"ERROR"}, f"Curve {self.polyline_object_name!r} has no splines")
                return {"CANCELLED"}

            spline = curve_data.splines[0]
            if hasattr(spline, "points"):
                polyline = [
                    (float(p.co[0]), float(p.co[1]), float(p.co[2]))
                    for p in spline.points
                ]
            elif hasattr(spline, "bezier_points"):
                polyline = [
                    (float(p.co[0]), float(p.co[1]), float(p.co[2]))
                    for p in spline.bezier_points
                ]
            else:
                self.report({"ERROR"}, f"Could not extract points from curve {self.polyline_object_name!r}")
                return {"CANCELLED"}
        else:
            self.report({"ERROR"}, "Either vertices_json or polyline_object_name is required")
            return {"CANCELLED"}

        if len(polyline) < 2:
            self.report({"ERROR"}, "Breakline needs at least 2 vertices")
            return {"CANCELLED"}

        breakline = tool_surface.Breakline(
            name=self.breakline_name,
            polyline=polyline,
            kind=self.kind,
            source="manual",
        )

        try:
            surface = core_surface.add_breakline_to_surface(
                tool.Ifc,
                tool.Surface,
                surface_guid=target_guid,
                breakline=breakline,
            )
        except (ValueError, tool_surface.SaikeiSurfaceError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        try:
            tool.Surface.update_blender_mesh(tool.Ifc.get(), surface)
        except tool_surface.SaikeiSurfaceError as exc:
            self.report(
                {"WARNING"},
                f"breakline added to IFC but Blender mesh refresh failed: {exc}",
            )

        self.report(
            {"INFO"},
            f"Added breakline {breakline.name!r} ({len(breakline.polyline)} pts)",
        )
        return {"FINISHED"}


class CIVIL_OT_surface_pick_boundary(Operator, tool.Ifc.Operator):
    """Set the outer boundary of the active surface by interactively clicking.

    Modal entry (``invoke``): click to add polygon vertices; Enter commits the
    closed polygon; Esc cancels. On commit the captured vertex list is written
    to ``polyline_object_name`` and ``_execute`` sets the boundary in IFC.

    Headless / ``_from_data`` path: the same class invoked with
    ``EXEC_DEFAULT``; set ``polyline_object_name`` to an existing
    ``bpy.data.curves`` object whose first spline's vertices (>= 3) define
    the boundary ring.

    Headless usage::

        bpy.ops.civil.surface_pick_boundary(
            "EXEC_DEFAULT",
            polyline_object_name="MyBoundaryCurve",
            surface_guid="<guid>",
        )
    """

    bl_idname = "civil.surface_pick_boundary"
    bl_label = "Pick Boundary"
    bl_description = (
        "Click to place polygon vertices defining the outer boundary; Enter "
        "commits the closed polygon to IFC; Esc cancels."
    )
    bl_options = {"REGISTER", "UNDO"}

    vertices_json: StringProperty(
        name="Vertices JSON",
        description="JSON-encoded list of [[x,y,z], ...] vertices set by the "
        "modal on commit. Empty when the headless polyline_object_name path is "
        "used instead.",
        default="",
        options={"SKIP_SAVE"},
    )
    polyline_object_name: StringProperty(
        name="Boundary Object Name",
        description="Name of a Blender curve object whose spline vertices "
        "define the boundary ring (>= 3 points). Used for the headless "
        "EXEC_DEFAULT path when the caller already has a curve object. The "
        "modal path uses vertices_json instead (no orphan curve on cancel).",
        default="",
    )
    surface_guid: StringProperty(
        name="Surface GUID",
        description="GlobalId of the target surface. Defaults to the active "
        "UIList selection when empty.",
        default="",
    )

    # --- Modal state ----------------------------------------------------------
    _vertices: list

    def invoke(self, context, event):
        self._vertices = []
        context.window_manager.modal_handler_add(self)
        self.report({"INFO"}, "Click to add vertices; Enter to commit polygon; Esc to cancel")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            region = context.region
            rv3d = context.region_data
            coord = (event.mouse_region_x, event.mouse_region_y)
            from bpy_extras import view3d_utils

            view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
            ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
            if view_vector.z != 0:
                t = -ray_origin.z / view_vector.z
                hit = ray_origin + t * view_vector
            else:
                hit = ray_origin
            self._vertices.append((float(hit.x), float(hit.y), float(hit.z)))
            context.area.tag_redraw()
            return {"RUNNING_MODAL"}

        elif event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            if len(self._vertices) < 3:
                self.report({"ERROR"}, "Need at least 3 vertices for a boundary polygon")
                return {"CANCELLED"}
            # Stash vertices as JSON — no bpy.data mutation in modal().
            # _execute() builds the ring directly from this JSON blob.
            self.vertices_json = json.dumps(self._vertices)
            return self.execute(context)

        elif event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self.report({"INFO"}, "Boundary pick cancelled")
            return {"CANCELLED"}

        return {"PASS_THROUGH"}

    def _execute(self, context):
        props = context.scene.CivilSurfaceProperties
        target_guid = self.surface_guid or props.active_surface_guid
        if not target_guid:
            self.report(
                {"ERROR"},
                "No active surface — select one in the UIList or supply surface_guid",
            )
            return {"CANCELLED"}

        import numpy as np

        # Resolve the ring from either the JSON blob (modal path) or the
        # curve-object name (headless EXEC_DEFAULT path).
        if self.vertices_json:
            try:
                raw_verts = json.loads(self.vertices_json)
                ring_points_raw = [(float(v[0]), float(v[1]), float(v[2])) for v in raw_verts]
            except (ValueError, KeyError, TypeError) as exc:
                self.report({"ERROR"}, f"Invalid vertices_json: {exc}")
                return {"CANCELLED"}
        elif self.polyline_object_name:
            curve_obj = bpy.data.objects.get(self.polyline_object_name)
            if curve_obj is None or curve_obj.data is None:
                self.report(
                    {"ERROR"},
                    f"No curve object named {self.polyline_object_name!r}",
                )
                return {"CANCELLED"}

            curve_data = curve_obj.data
            if not hasattr(curve_data, "splines") or len(curve_data.splines) == 0:
                self.report({"ERROR"}, f"Curve {self.polyline_object_name!r} has no splines")
                return {"CANCELLED"}

            spline = curve_data.splines[0]
            if hasattr(spline, "points"):
                ring_points_raw = [
                    (float(p.co[0]), float(p.co[1]), float(p.co[2]))
                    for p in spline.points
                ]
            elif hasattr(spline, "bezier_points"):
                ring_points_raw = [
                    (float(p.co[0]), float(p.co[1]), float(p.co[2]))
                    for p in spline.bezier_points
                ]
            else:
                self.report({"ERROR"}, f"Could not extract points from curve {self.polyline_object_name!r}")
                return {"CANCELLED"}
        else:
            self.report({"ERROR"}, "Either vertices_json or polyline_object_name is required")
            return {"CANCELLED"}

        if len(ring_points_raw) < 3:
            self.report({"ERROR"}, "Boundary ring needs at least 3 vertices")
            return {"CANCELLED"}

        ring_points = np.array(ring_points_raw, dtype=float)

        try:
            polygon = tool.Surface.build_boundary_polygon_from_ring(ring_points)
        except tool_surface.SaikeiSurfaceError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        try:
            surface = core_surface.set_outer_boundary(
                tool.Ifc,
                tool.Surface,
                surface_guid=target_guid,
                boundary_polygon=polygon,
            )
        except (ValueError, tool_surface.SaikeiSurfaceError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        try:
            tool.Surface.update_blender_mesh(tool.Ifc.get(), surface)
        except tool_surface.SaikeiSurfaceError as exc:
            self.report(
                {"WARNING"},
                f"boundary set in IFC but Blender mesh refresh failed: {exc}",
            )

        self.report(
            {"INFO"},
            f"Set boundary on {surface.name} ({len(ring_points_raw)} vertices)",
        )
        return {"FINISHED"}


class CIVIL_OT_surface_raise_lower(Operator, tool.Ifc.Operator):
    """Uniformly raise or lower the active surface by dragging the mouse.

    Modal entry (``invoke``): drag vertically to raise (up) or lower (down);
    numeric entry overrides the drag delta; Enter commits; Esc cancels. On
    commit, all TIN vertices are translated by ``delta_z`` and the IFC
    representation is updated.

    Headless / ``_from_data`` path: the same class invoked with
    ``EXEC_DEFAULT``; set ``surface_guid`` and ``delta_z`` explicitly.

    Headless usage::

        bpy.ops.civil.surface_raise_lower(
            "EXEC_DEFAULT", surface_guid="<guid>", delta_z=5.0
        )
    """

    bl_idname = "civil.surface_raise_lower"
    bl_label = "Raise or Lower Surface"
    bl_description = (
        "Drag the mouse up or down to raise or lower the active surface "
        "uniformly. Numeric entry overrides the drag delta."
    )
    bl_options = {"REGISTER", "UNDO"}

    surface_guid: StringProperty(
        name="Surface GUID",
        description="GlobalId of the surface to translate. Defaults to the "
        "active UIList selection when empty.",
        default="",
    )
    delta_z: FloatProperty(
        name="Delta Z",
        description="Vertical offset in project units (positive = raise, "
        "negative = lower). Set by the modal drag; set directly for the "
        "headless EXEC_DEFAULT path.",
        default=0.0,
        unit="LENGTH",
    )

    # --- Modal state ----------------------------------------------------------
    _initial_mouse_y: int
    _drag_scale: float
    _numeric_buffer: str

    def invoke(self, context, event):
        props = context.scene.CivilSurfaceProperties
        # Resolve surface_guid from props when not supplied by the caller.
        if not self.surface_guid:
            self.surface_guid = props.active_surface_guid
        if not self.surface_guid:
            self.report(
                {"ERROR"},
                "No active surface — select one in the UIList first",
            )
            return {"CANCELLED"}

        self._initial_mouse_y = event.mouse_y
        self._drag_scale = 0.01  # 1 unit per 100 px by default
        self._numeric_buffer = ""

        context.window_manager.modal_handler_add(self)
        self.report({"INFO"}, "Drag to raise/lower; Enter to commit; Esc to cancel")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"NUMPAD_0", "NUMPAD_1", "NUMPAD_2", "NUMPAD_3",
                           "NUMPAD_4", "NUMPAD_5", "NUMPAD_6", "NUMPAD_7",
                           "NUMPAD_8", "NUMPAD_9", "ZERO", "ONE", "TWO",
                           "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT",
                           "NINE", "PERIOD", "MINUS"} and event.value == "PRESS":
            # Numeric override: accumulate digit presses into a buffer.
            char_map = {
                "NUMPAD_0": "0", "NUMPAD_1": "1", "NUMPAD_2": "2",
                "NUMPAD_3": "3", "NUMPAD_4": "4", "NUMPAD_5": "5",
                "NUMPAD_6": "6", "NUMPAD_7": "7", "NUMPAD_8": "8",
                "NUMPAD_9": "9", "ZERO": "0", "ONE": "1", "TWO": "2",
                "THREE": "3", "FOUR": "4", "FIVE": "5", "SIX": "6",
                "SEVEN": "7", "EIGHT": "8", "NINE": "9",
                "PERIOD": ".", "MINUS": "-",
            }
            self._numeric_buffer += char_map.get(event.type, "")
            return {"RUNNING_MODAL"}

        elif event.type == "MOUSEMOVE":
            if not self._numeric_buffer:
                delta_px = event.mouse_y - self._initial_mouse_y
                self.delta_z = delta_px * self._drag_scale
            context.area.tag_redraw()
            return {"RUNNING_MODAL"}

        elif event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            if self._numeric_buffer:
                try:
                    self.delta_z = float(self._numeric_buffer)
                except ValueError:
                    self.report({"ERROR"}, f"Invalid numeric input: {self._numeric_buffer!r}")
                    return {"CANCELLED"}
            return self.execute(context)

        elif event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self.report({"INFO"}, "Raise/lower cancelled")
            return {"CANCELLED"}

        return {"PASS_THROUGH"}

    def _execute(self, context):
        props = context.scene.CivilSurfaceProperties
        target_guid = self.surface_guid or props.active_surface_guid
        if not target_guid:
            self.report(
                {"ERROR"},
                "No active surface — select one in the UIList or supply surface_guid",
            )
            return {"CANCELLED"}

        if self.delta_z == 0.0:
            self.report({"INFO"}, "delta_z is 0 — no change")
            return {"FINISHED"}

        try:
            core_surface.translate_surface_z(
                tool.Ifc,
                tool.Surface,
                surface_guid=target_guid,
                delta_z=self.delta_z,
            )
        except (ValueError, tool_surface.SaikeiSurfaceError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        # Refresh Blender mesh so the viewport reflects the Z shift.
        ifc_file = tool.Ifc.get()
        if ifc_file is not None:
            try:
                surface = tool.Surface.get(ifc_file, target_guid)
                tool.Surface.update_blender_mesh(ifc_file, surface)
            except tool_surface.SaikeiSurfaceError as exc:
                self.report(
                    {"WARNING"},
                    f"Surface translated in IFC but Blender mesh refresh failed: {exc}",
                )

        self.report({"INFO"}, f"Surface translated by {self.delta_z:+.3f} m")
        return {"FINISHED"}

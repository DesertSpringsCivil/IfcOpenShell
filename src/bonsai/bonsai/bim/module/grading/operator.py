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

"""Operators for the Saikei grading module.

Same Bonsai operator pattern as the surface module: every operator
inherits :class:`tool.Ifc.Operator` so undo/redo, IFC mutation tracking,
and validation hooks run automatically. Implements ``_execute`` (not
``execute``) — Bonsai wraps the underscore form with the IFC operator
boilerplate.

.. note::

    Bonsai's ``tool.Ifc.Operator.execute`` always returns
    ``{"FINISHED"}`` regardless of what ``_execute`` returns. The inner
    CANCELLED is dropped at the wrapper boundary. What the headless
    caller actually sees is:

    1. An ``ERROR``-level report on the Window Manager's reports list.
    2. Blender re-raises that report as a Python ``RuntimeError`` from
       the ``bpy.ops`` boundary. Headless tests use
       ``pytest.raises(RuntimeError)`` to detect cancellation.

    Operators that ``self.report({"ERROR"}, ...)`` should also assert
    "no IFC entity was authored" as a behavior check rather than
    relying on the return set.
"""

import json

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
from bpy.types import Operator

import bonsai.core.grading as core_grading
import bonsai.tool as tool
import bonsai.tool.grading as tool_grading


class CIVIL_OT_feature_line_create(Operator, tool.Ifc.Operator):
    """Create a feature line from a CSV / XYZ vertex file.

    Modal entry per spec §8.5: ``invoke()`` opens a file selector for
    a CSV / whitespace-separated XYZ file (same format as
    ``CIVIL_OT_surface_create_from_points`` from Phase 4). The
    interactive viewport-pick modal flow (draw vertices on the canvas)
    is deferred to Phase 5.1 — file-dialog covers MVP authoring and
    headless callers.

    Inputs from :class:`CivilGradingProperties` (scene-level):
    ``new_feature_line_name``, ``new_feature_line_closed``.

    Headless usage::

        bpy.ops.civil.feature_line_create(
            "EXEC_DEFAULT",
            csv_filepath="/path/to/perimeter.csv",
            closed=True,
        )

    On success, appends the new feature line to the panel UIList and
    creates a Blender curve object so the user sees it in the viewport.
    """

    bl_idname = "civil.feature_line_create"
    bl_label = "Create Feature Line from CSV"
    bl_description = (
        "Author an IfcAlignment feature line from a CSV / whitespace-"
        "separated XYZ vertex file. Used as the footprint for grading "
        "objects within a grading group."
    )
    bl_options = {"REGISTER", "UNDO"}

    csv_filepath: StringProperty(
        name="CSV / XYZ Filepath",
        description="Path to a CSV / whitespace-separated XYZ vertex file (≥ 2 rows)",
        subtype="FILE_PATH",
    )
    filter_glob: StringProperty(
        default="*.csv;*.txt;*.xyz",
        options={"HIDDEN"},
    )
    closed: BoolProperty(
        name="Closed Loop",
        description="True for closed loops (pad perimeters), False for "
        "open lines (e.g., ditch centerlines). Defaults to the panel's "
        "new_feature_line_closed when not supplied.",
        default=True,
    )

    def _execute(self, context):
        props = context.scene.CivilGradingProperties
        try:
            vertices = tool.Surface.load_points_from_csv(self.csv_filepath)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        try:
            feature_line = core_grading.create_feature_line(
                tool.Ifc,
                tool.Grading,
                name=props.new_feature_line_name,
                vertices=vertices,
                closed=bool(self.closed),
            )
        except (ValueError, tool_grading.SaikeiGradingError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        # Create the Blender curve object so the user sees the feature
        # line in the viewport.
        try:
            tool.Grading.create_blender_curve(tool.Ifc.get(), feature_line)
        except tool_grading.SaikeiGradingError as exc:
            self.report(
                {"WARNING"},
                f"feature line authored to IFC but Blender curve creation "
                f"failed: {exc}",
            )

        self.report(
            {"INFO"},
            f"Created feature line {feature_line.name!r} "
            f"({len(feature_line.vertices)} vertices)",
        )
        return {"FINISHED"}

    def invoke(self, context, event):
        if not self.csv_filepath:
            # Default closed-loop flag from the panel's pending state.
            props = context.scene.CivilGradingProperties
            self.closed = bool(props.new_feature_line_closed)
            context.window_manager.fileselect_add(self)
            return {"RUNNING_MODAL"}
        return self.execute(context)


class CIVIL_OT_feature_line_drape(Operator, tool.Ifc.Operator):
    """Drape a feature line's vertices onto a target surface.

    Headless-only ([H] per spec §8.2 — surface picker would be a
    panel popup, not a viewport-pick modal). Replaces each vertex's Z
    with ``surface.z_at(x, y)`` and persists the new polyline back to
    the IFC alignment via :meth:`tool.Grading.update_feature_line_vertices`.

    Headless usage::

        bpy.ops.civil.feature_line_drape(
            "EXEC_DEFAULT",
            feature_line_guid="...",
            surface_guid="...",
        )

    UI flow: the panel pre-populates ``feature_line_guid`` from the
    active feature line and ``surface_guid`` from the surface module's
    active surface; the user clicks "Drape to Surface" and the
    operator runs headless.
    """

    bl_idname = "civil.feature_line_drape"
    bl_label = "Drape Feature Line to Surface"
    bl_description = (
        "Replace each feature-line vertex's Z with the elevation read "
        "from a target surface at that XY position. Vertices outside "
        "the target surface raise an error."
    )
    bl_options = {"REGISTER", "UNDO"}

    feature_line_guid: StringProperty(
        name="Feature Line GUID",
        description="GlobalId of the feature line to drape",
    )
    surface_guid: StringProperty(
        name="Surface GUID",
        description="GlobalId of the source CivilSurface (existing ground)",
    )

    def _execute(self, context):
        if not self.feature_line_guid or not self.surface_guid:
            self.report(
                {"ERROR"},
                "Both feature_line_guid and surface_guid are required",
            )
            return {"CANCELLED"}

        try:
            feature_line = core_grading.drape_feature_line(
                tool.Ifc,
                tool.Surface,
                tool.Grading,
                feature_line_guid=self.feature_line_guid,
                surface_guid=self.surface_guid,
            )
        except (ValueError, tool_grading.SaikeiGradingError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        # Update the Blender curve to reflect new Z values.
        try:
            ifc_file = tool.Ifc.get()
            obj = tool.Ifc.get_object(
                ifc_file.by_id(feature_line.ifc_alignment_id)
            )
            if obj is not None and obj.data is not None:
                spline = obj.data.splines[0]
                for i, (x, y, z) in enumerate(feature_line.vertices):
                    if i < len(spline.points):
                        spline.points[i].co = (
                            float(x),
                            float(y),
                            float(z),
                            1.0,
                        )
        except Exception as exc:
            self.report(
                {"WARNING"},
                f"feature line draped in IFC but Blender curve refresh "
                f"failed: {exc}",
            )

        self.report(
            {"INFO"},
            f"Draped {feature_line.name!r} to surface "
            f"({len(feature_line.vertices)} vertices)",
        )
        return {"FINISHED"}


class CIVIL_OT_feature_line_edit_elevations(Operator, tool.Ifc.Operator):
    """Apply per-vertex Z edits to a feature line.

    Phase 5 MVP ships the headless contract; the G-key viewport-grab
    modal flow (mirror of the alignment PI edit mode at
    ``tool/alignment.py``) is deferred to Phase 5.1 — a faithful G-key
    modal needs ~300 lines of event-dispatch code that's better
    landed alongside its sibling viewport pickers (feature-line draw,
    boundary draw) in one cohesive Phase 5.1 commit.

    The headless contract per spec §8.2: accept a JSON-encoded payload
    of ``[(vertex_index, new_z), ...]`` pairs; apply each in order to
    the feature line; persist via
    :meth:`tool.Grading.update_feature_line_vertices`. UI panel
    (commit 15) provides a popup dialog that builds the JSON payload
    from a UIList of editable vertex rows.

    Headless usage::

        bpy.ops.civil.feature_line_edit_elevations(
            "EXEC_DEFAULT",
            feature_line_guid="...",
            edits_json='[[0, 99.5], [2, 100.5]]',
        )
    """

    bl_idname = "civil.feature_line_edit_elevations"
    bl_label = "Edit Feature-Line Elevations"
    bl_description = (
        "Apply per-vertex Z edits to a feature line. Phase 5 MVP "
        "headless contract: pass a JSON-encoded list of "
        "[vertex_index, new_z] pairs. The G-key viewport-grab modal "
        "flow lands in Phase 5.1."
    )
    bl_options = {"REGISTER", "UNDO"}

    feature_line_guid: StringProperty(
        name="Feature Line GUID",
        description="GlobalId of the feature line to edit",
    )
    edits_json: StringProperty(
        name="Edits (JSON)",
        description="JSON-encoded list of [vertex_index, new_z] pairs, "
        "e.g. '[[0, 99.5], [2, 100.0]]'. Empty defaults to '[]' (no-op).",
        default="[]",
    )

    def _execute(self, context):
        if not self.feature_line_guid:
            self.report(
                {"ERROR"}, "feature_line_guid is required"
            )
            return {"CANCELLED"}

        try:
            edits = json.loads(self.edits_json)
        except json.JSONDecodeError as exc:
            self.report(
                {"ERROR"},
                f"could not parse edits_json: {exc}",
            )
            return {"CANCELLED"}

        if not isinstance(edits, list):
            self.report(
                {"ERROR"},
                f"edits_json must decode to a list of [index, z] pairs; "
                f"got {type(edits).__name__}",
            )
            return {"CANCELLED"}

        ifc_file = tool.Ifc.get()
        try:
            feature_line = tool.Grading.get_feature_line(
                ifc_file, self.feature_line_guid
            )
        except tool_grading.SaikeiGradingError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        # Validate every edit before mutating, so a bad edit at index 5
        # of 10 doesn't leave indices 0–4 mutated and 5–9 untouched.
        n_vertices = len(feature_line.vertices)
        for entry in edits:
            if (
                not isinstance(entry, (list, tuple))
                or len(entry) != 2
                or not isinstance(entry[0], int)
            ):
                self.report(
                    {"ERROR"},
                    f"each edit must be [vertex_index, new_z]; got {entry!r}",
                )
                return {"CANCELLED"}
            vertex_index = int(entry[0])
            if not (0 <= vertex_index < n_vertices):
                self.report(
                    {"ERROR"},
                    f"vertex_index {vertex_index} out of range "
                    f"[0, {n_vertices})",
                )
                return {"CANCELLED"}

        # All edits validated — apply them.
        new_vertices = list(feature_line.vertices)
        for entry in edits:
            vertex_index = int(entry[0])
            new_z = float(entry[1])
            x, y, _ = new_vertices[vertex_index]
            new_vertices[vertex_index] = (x, y, new_z)
        feature_line.vertices = new_vertices

        try:
            tool.Grading.update_feature_line_vertices(ifc_file, feature_line)
        except tool_grading.SaikeiGradingError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        # Refresh the Blender curve so the viewport reflects the edits.
        try:
            obj = tool.Ifc.get_object(
                ifc_file.by_id(feature_line.ifc_alignment_id)
            )
            if obj is not None and obj.data is not None and obj.data.splines:
                spline = obj.data.splines[0]
                for i, (x, y, z) in enumerate(feature_line.vertices):
                    if i < len(spline.points):
                        spline.points[i].co = (
                            float(x),
                            float(y),
                            float(z),
                            1.0,
                        )
        except Exception as exc:
            self.report(
                {"WARNING"},
                f"feature line edited in IFC but Blender curve refresh "
                f"failed: {exc}",
            )

        self.report(
            {"INFO"},
            f"Applied {len(edits)} elevation edit(s) to "
            f"{feature_line.name!r}",
        )
        return {"FINISHED"}


class CIVIL_OT_grading_create_criteria(Operator, tool.Ifc.Operator):
    """Author a reusable grading criteria.

    Inputs default to :class:`CivilGradingProperties` panel state
    (``new_criteria_name``, ``new_criteria_target_kind``, etc.); the
    operator's own properties override per-call. Modal flow is the
    panel popup itself — clicking the "Create Criteria" panel button
    runs the operator with the panel's values.

    Headless usage::

        bpy.ops.civil.grading_create_criteria(
            "EXEC_DEFAULT",
            name="3:1 fill / 2:1 cut",
            target_kind="surface",
            target_ref="<surface-guid>",
            cut_slope=2.0,
            fill_slope=3.0,
        )
    """

    bl_idname = "civil.grading_create_criteria"
    bl_label = "Create Grading Criteria"
    bl_description = (
        "Author a reusable grading-slope criteria as an "
        "IfcPropertySetTemplate. Civil 3D's Grading Criteria analog: "
        "binds to grading groups via assign_criteria when used."
    )
    bl_options = {"REGISTER", "UNDO"}

    name: StringProperty(name="Name", default="")
    target_kind: EnumProperty(
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
    target_ref: StringProperty(
        name="Target Reference",
        description="For surface kind: GUID of target. For numeric kinds: "
        "float value as string.",
        default="",
    )
    cut_slope: FloatProperty(name="Cut Slope (H:V)", default=2.0, min=0.01)
    fill_slope: FloatProperty(name="Fill Slope (H:V)", default=3.0, min=0.01)
    max_distance: FloatProperty(
        name="Max Distance",
        description="Daylight cap; 0 = unlimited",
        default=0.0,
        min=0.0,
    )
    retaining_wall_at_limit: BoolProperty(
        name="Retaining Wall at Limit", default=False
    )

    def _execute(self, context):
        props = context.scene.CivilGradingProperties
        # Fall back to panel state when the operator wasn't given an
        # explicit name / target_ref (the panel's "Create" button path).
        name = self.name or props.new_criteria_name
        target_ref = self.target_ref or props.new_criteria_target_ref

        try:
            criteria = core_grading.create_grading_criteria(
                tool.Ifc,
                tool.Grading,
                name=name,
                target_kind=self.target_kind,
                target_ref=target_ref,
                cut_slope=self.cut_slope,
                fill_slope=self.fill_slope,
                max_distance=(
                    self.max_distance if self.max_distance > 0.0 else None
                ),
                retaining_wall_at_limit=self.retaining_wall_at_limit,
            )
        except (ValueError, tool_grading.SaikeiGradingError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            f"Created criteria {criteria.name!r} "
            f"({criteria.cut_slope:g}:1 cut / {criteria.fill_slope:g}:1 fill)",
        )
        return {"FINISHED"}


class CIVIL_OT_grading_create_group(Operator, tool.Ifc.Operator):
    """Author an empty grading group.

    Inputs default to :class:`CivilGradingProperties` panel state
    (``new_group_name``, ``new_group_target_surface_guid``,
    ``new_group_interior_fill``, ``new_group_interior_fill_source_guid``);
    the operator's own properties override per-call.

    Headless usage::

        bpy.ops.civil.grading_create_group(
            "EXEC_DEFAULT",
            name="North Pad",
            target_surface_guid="<terrain-guid>",
            interior_fill="flat",
        )
    """

    bl_idname = "civil.grading_create_group"
    bl_label = "Create Grading Group"
    bl_description = (
        "Author an empty grading group as IfcGroup[GradingGroup] with a "
        "per-group composite IfcEarthworksFill[SUBGRADE]. Add grading "
        "objects via the Add Object operator."
    )
    bl_options = {"REGISTER", "UNDO"}

    name: StringProperty(name="Name", default="")
    target_surface_guid: StringProperty(
        name="Target Surface GUID",
        description="GlobalId of the existing-ground surface; populates "
        "from the surface module's active surface when blank",
        default="",
    )
    interior_fill: EnumProperty(
        name="Interior Fill",
        items=[
            ("none", "None", "No interior fill"),
            ("flat", "Flat", "Interior at average feature-line elevation"),
            (
                "interpolate_from_boundary",
                "Interpolate from Boundary",
                "Delaunay over feature-line vertices",
            ),
            ("from_surface", "From Surface", "Drape from a source surface"),
        ],
        default="interpolate_from_boundary",
    )
    interior_fill_source_guid: StringProperty(
        name="Interior Fill Source GUID",
        description="Required when interior_fill='from_surface'",
        default="",
    )

    def _execute(self, context):
        props = context.scene.CivilGradingProperties
        # Fall back to panel state for any blank operator parameters.
        name = self.name or props.new_group_name
        target_surface_guid = (
            self.target_surface_guid or props.new_group_target_surface_guid
        )
        interior_fill_source_guid = (
            self.interior_fill_source_guid
            or props.new_group_interior_fill_source_guid
        )

        try:
            group = core_grading.create_grading_group(
                tool.Ifc,
                tool.Surface,
                tool.Grading,
                name=name,
                target_surface_guid=target_surface_guid or None,
                interior_fill=self.interior_fill,
                interior_fill_source_guid=interior_fill_source_guid or None,
            )
        except (ValueError, tool_grading.SaikeiGradingError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        # Create a Blender Empty as the group's parent placeholder so
        # the user has something selectable in the outliner.
        try:
            tool.Grading.create_blender_empty_for_group(tool.Ifc.get(), group)
        except tool_grading.SaikeiGradingError as exc:
            self.report(
                {"WARNING"},
                f"group authored to IFC but Blender Empty creation "
                f"failed: {exc}",
            )

        self.report(
            {"INFO"},
            f"Created grading group {group.name!r} "
            f"(interior_fill={group.interior_fill})",
        )
        return {"FINISHED"}


class CIVIL_OT_grading_add_object(Operator, tool.Ifc.Operator):
    """Apply a criteria to a feature line within a group, computing the
    slope projection and authoring the resulting slope fill.

    The headless three-GUID payload is the cleanest API surface: the
    panel popup (commit 15) lets the user pick group / feature-line /
    criteria from UILists and clicks "Add Object," which runs the
    operator with the picked GUIDs.

    Headless usage::

        bpy.ops.civil.grading_add_object(
            "EXEC_DEFAULT",
            group_guid="...",
            feature_line_guid="...",
            criteria_guid="...",
        )

    Side effect: appends the new :class:`GradingObject` to the group's
    members. The composite surface isn't rebuilt automatically — call
    :class:`CIVIL_OT_grading_rebuild_group` after adding all the
    objects you want, so the rebuild fires once per editing session
    rather than per-add.
    """

    bl_idname = "civil.grading_add_object"
    bl_label = "Add Grading Object"
    bl_description = (
        "Apply a criteria to a feature line within a grading group. "
        "Authors the slope-fill ribbon as IfcEarthworksFill[SLOPEFILL] "
        "aggregated under the group's composite. Run "
        "Rebuild Group after adding objects to refresh the composite "
        "proposed surface."
    )
    bl_options = {"REGISTER", "UNDO"}

    group_guid: StringProperty(name="Group GUID")
    feature_line_guid: StringProperty(name="Feature Line GUID")
    criteria_guid: StringProperty(name="Criteria GUID")

    def _execute(self, context):
        if not (
            self.group_guid and self.feature_line_guid and self.criteria_guid
        ):
            self.report(
                {"ERROR"},
                "group_guid, feature_line_guid, and criteria_guid are "
                "all required",
            )
            return {"CANCELLED"}

        try:
            grading_object = core_grading.add_grading_object(
                tool.Ifc,
                tool.Surface,
                tool.Grading,
                group_guid=self.group_guid,
                feature_line_guid=self.feature_line_guid,
                criteria_guid=self.criteria_guid,
            )
        except (ValueError, tool_grading.SaikeiGradingError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            f"Added grading object {grading_object.name!r} "
            f"({len(grading_object.daylight_line)} daylight points)",
        )
        return {"FINISHED"}


class CIVIL_OT_grading_rebuild_group(Operator, tool.Ifc.Operator):
    """Force-rebuild a grading group's composite proposed surface.

    Per spec §8.2 [H] — headless-only. Most rebuild needs are handled
    automatically by ``add_grading_object`` (Phase 5.1 will add
    cascade rebuild on feature-line edit per the v3.2.5 amendments
    queue item 4); this operator is the explicit "force a fresh
    rebuild" hatch for power users and the panel.

    Sequencing: core.rebuild_group (assembles slope-fill members +
    interior-fill geometry → updates the composite TIN +
    BoundingBox) → refresh the Blender mesh on the composite.

    Headless usage::

        bpy.ops.civil.grading_rebuild_group(
            "EXEC_DEFAULT", group_guid="..."
        )
    """

    bl_idname = "civil.grading_rebuild_group"
    bl_label = "Rebuild Grading Group"
    bl_description = (
        "Force a rebuild of the group's composite proposed surface. "
        "Reassembles slope-fill members + interior fill + writes the "
        "result to the composite IfcEarthworksFill's TIN representation."
    )
    bl_options = {"REGISTER", "UNDO"}

    group_guid: StringProperty(name="Group GUID")

    def _execute(self, context):
        if not self.group_guid:
            self.report({"ERROR"}, "group_guid is required")
            return {"CANCELLED"}

        try:
            composite_surface = core_grading.rebuild_group(
                tool.Ifc,
                tool.Surface,
                tool.Grading,
                group_guid=self.group_guid,
            )
        except (ValueError, tool_grading.SaikeiGradingError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        # Refresh / create the composite's Blender mesh so the user
        # sees the rebuilt TIN.
        try:
            tool.Surface.update_blender_mesh(tool.Ifc.get(), composite_surface)
        except tool_grading.SaikeiGradingError:
            # Composite hasn't been linked to a Blender mesh yet on
            # first rebuild — call create_blender_mesh instead.
            try:
                tool.Surface.create_blender_mesh(
                    tool.Ifc.get(), composite_surface
                )
            except Exception as exc:
                self.report(
                    {"WARNING"},
                    f"composite TIN rebuilt in IFC but Blender mesh "
                    f"refresh failed: {exc}",
                )

        self.report(
            {"INFO"},
            f"Rebuilt {composite_surface.name!r} → "
            f"{len(composite_surface.triangles)} triangles",
        )
        return {"FINISHED"}

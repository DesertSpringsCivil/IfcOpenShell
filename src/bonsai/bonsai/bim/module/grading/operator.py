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
from bpy.props import BoolProperty, FloatProperty, IntProperty, StringProperty
from bpy.props import EnumProperty
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
        "Create a feature line from a CSV / whitespace-separated XYZ "
        "vertex file. Used as the footprint for grading objects within "
        "a grading group."
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
            tool.Grading.update_blender_curve(tool.Ifc.get(), feature_line)
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


class CIVIL_OT_feature_line_from_daylight(Operator, tool.Ifc.Operator):
    """Promote a grading object's daylight line to a feature line.

    Headless-only ([H] per spec §8.2 — the source is picked from the
    group's member UIList, not the viewport).

    :meth:`tool.Grading.compute_grading_object` already solves the
    tie-out points where each slope ray meets the target surface, but
    that polyline was previously reachable only as GPU-decorator draw
    data. This operator persists it as a real
    :class:`IfcAlignment`-backed feature line so it can be draped,
    offset, filleted, re-graded from (benched/terraced slopes), or used
    as a boundary for surface clipping and terrain masking.

    Headless usage::

        bpy.ops.civil.feature_line_from_daylight(
            "EXEC_DEFAULT",
            grading_object_guid="...",
            name="pad tie-in",          # optional
        )

    UI flow: the panel pre-populates ``grading_object_guid`` from the
    active grading object; the user clicks "Feature Line from Daylight".
    """

    bl_idname = "civil.feature_line_from_daylight"
    bl_label = "Feature Line from Daylight"
    bl_description = (
        "Create a feature line from a grading object's computed "
        "daylight (tie-in) line, so it can be draped, offset, "
        "re-graded from, or used as a clipping boundary"
    )
    bl_options = {"REGISTER", "UNDO"}

    grading_object_guid: StringProperty(
        name="Grading Object GUID",
        description="GlobalId of the grading object whose daylight line to promote",
    )
    name: StringProperty(
        name="Name",
        description=(
            "Label for the new feature line. Defaults to "
            "'<grading-object-name> daylight'"
        ),
        default="",
    )

    def _execute(self, context):
        if not self.grading_object_guid:
            self.report({"ERROR"}, "grading_object_guid is required")
            return {"CANCELLED"}

        try:
            feature_line = core_grading.create_feature_line_from_daylight(
                tool.Ifc,
                tool.Grading,
                grading_object_guid=self.grading_object_guid,
                name=self.name,
            )
        except (ValueError, tool_grading.SaikeiGradingError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        # Mirror to Blender so the new tie-in is visible immediately.
        try:
            tool.Grading.create_blender_curve(tool.Ifc.get(), feature_line)
        except Exception as exc:
            self.report(
                {"WARNING"},
                f"feature line authored to IFC but Blender curve "
                f"creation failed: {exc}",
            )

        self.report(
            {"INFO"},
            f"Created feature line {feature_line.name!r} from daylight "
            f"({len(feature_line.vertices)} vertices, "
            f"{'closed' if feature_line.closed else 'open'})",
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
            tool.Grading.update_blender_curve(ifc_file, feature_line)
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
        "Author a reusable grading-slope criteria as a slope-rule "
        "template. Civil 3D's Grading Criteria analog: binds to "
        "grading groups via assign_criteria when used."
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
        "Author an empty grading group with a per-group composite "
        "proposed surface. Add grading objects via the Add Object "
        "operator."
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
        "Authors the slope-fill grading object aggregated under the "
        "group's composite. Run Rebuild Group after adding objects to "
        "refresh the composite proposed surface."
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
        "result to the group's composite proposed surface TIN."
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


class CIVIL_OT_feature_line_delete(Operator, tool.Ifc.Operator):
    """Delete the active feature line.

    Removes the IFC entity, its property set, and any linked Blender
    curve object. Blocked if the feature line is currently assigned to
    a grading group as its source FL -- remove all grading objects from
    that group first.

    Headless usage::

        bpy.ops.civil.feature_line_delete(
            "EXEC_DEFAULT",
            feature_line_guid="...",
        )
    """

    bl_idname = "civil.feature_line_delete"
    bl_label = "Delete Feature Line"
    bl_description = (
        "A 3D polyline that defines a grading edge or design boundary. "
        "Deletes the selected feature line from the IFC file and removes "
        "its Blender curve. Blocked if assigned to a grading group."
    )
    bl_options = {"REGISTER", "UNDO"}

    feature_line_guid: StringProperty(
        name="Feature Line GUID",
        description="GlobalId of the feature line to delete",
        default="",
    )

    def _execute(self, context):
        guid = self.feature_line_guid
        if not guid:
            props = context.scene.CivilGradingProperties
            guid = props.active_feature_line_guid
        if not guid:
            self.report({"ERROR"}, "feature_line_guid is required")
            return {"CANCELLED"}

        try:
            core_grading.delete_feature_line(
                tool.Ifc,
                tool.Grading,
                feature_line_guid=guid,
            )
        except (
            tool_grading.BlockedByDependentError,
            tool_grading.SaikeiGradingError,
            ValueError,
        ) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        from .data import GradingData

        GradingData.is_loaded = False
        self.report({"INFO"}, "Feature line deleted")
        return {"FINISHED"}


class CIVIL_OT_grading_remove_object(Operator, tool.Ifc.Operator):
    """Remove the active grading object from its parent grading group.

    Per vocabulary: Remove breaks the group membership without
    destroying the entity. The grading object (slope-projected surface)
    remains in the IFC file. The group composite surface is rebuilt
    automatically after the removal.

    Headless usage::

        bpy.ops.civil.grading_remove_object(
            "EXEC_DEFAULT",
            object_guid="...",
            group_guid="...",
        )
    """

    bl_idname = "civil.grading_remove_object"
    bl_label = "Remove Grading Object"
    bl_description = (
        "A slope-projected surface from a feature line to a target "
        "(elevation, distance, or surface). Removes the selected grading "
        "object from its group without deleting the entity."
    )
    bl_options = {"REGISTER", "UNDO"}

    object_guid: StringProperty(
        name="Grading Object GUID",
        description="GlobalId of the grading object to remove",
        default="",
    )
    group_guid: StringProperty(
        name="Group GUID",
        description="GlobalId of the parent grading group",
        default="",
    )

    def _execute(self, context):
        if not self.object_guid or not self.group_guid:
            self.report(
                {"ERROR"}, "object_guid and group_guid are both required"
            )
            return {"CANCELLED"}

        try:
            core_grading.remove_grading_object_from_group(
                tool.Ifc,
                tool.Grading,
                tool.Surface,
                object_guid=self.object_guid,
                group_guid=self.group_guid,
            )
        except (tool_grading.SaikeiGradingError, ValueError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        from .data import GradingData

        GradingData.is_loaded = False
        self.report({"INFO"}, "Grading object removed from group")
        return {"FINISHED"}


class CIVIL_OT_grading_delete_criteria(Operator, tool.Ifc.Operator):
    """Delete a grading criteria template.

    Blocked if any grading object currently references this criteria --
    remove those grading objects from their groups first, then delete
    the criteria.

    Headless usage::

        bpy.ops.civil.grading_delete_criteria(
            "EXEC_DEFAULT",
            criteria_guid="...",
        )
    """

    bl_idname = "civil.grading_delete_criteria"
    bl_label = "Delete Criteria"
    bl_description = (
        "A reusable slope rule (e.g., 3:1 cut, 4:1 fill) applied to one "
        "or more grading objects. Deletes the selected criteria template. "
        "Blocked if any grading object still references it."
    )
    bl_options = {"REGISTER", "UNDO"}

    criteria_guid: StringProperty(
        name="Criteria GUID",
        description="GlobalId of the criteria template to delete",
        default="",
    )

    def _execute(self, context):
        guid = self.criteria_guid
        if not guid:
            props = context.scene.CivilGradingProperties
            guid = props.active_criteria_guid
        if not guid:
            self.report({"ERROR"}, "criteria_guid is required")
            return {"CANCELLED"}

        try:
            core_grading.delete_criteria(
                tool.Ifc,
                tool.Grading,
                criteria_guid=guid,
            )
        except (
            tool_grading.BlockedByDependentError,
            tool_grading.SaikeiGradingError,
            ValueError,
        ) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        from .data import GradingData

        GradingData.is_loaded = False
        self.report({"INFO"}, "Criteria deleted")
        return {"FINISHED"}


class CIVIL_OT_feature_line_draw_modal(Operator, tool.Ifc.Operator):
    """Draw a new feature line by clicking vertices in the 3D viewport.

    Modal entry (``invoke``): click to place vertices; Enter commits; Esc
    cancels. On commit the captured vertex list is JSON-encoded into
    ``vertices_json`` and ``_execute`` authors the feature line.

    Headless / ``_from_data`` path: invoke with ``EXEC_DEFAULT`` and set
    ``vertices_json`` directly.

    Headless usage::

        bpy.ops.civil.feature_line_draw_modal(
            "EXEC_DEFAULT",
            vertices_json='[[0,0,0],[10,0,0],[10,10,0]]',
            feature_line_name="Pad Perimeter",
            closed=True,
        )
    """

    bl_idname = "civil.feature_line_draw_modal"
    bl_label = "Draw Feature Line"
    bl_description = (
        "Click to place vertices in the viewport; Enter commits the "
        "feature line to IFC; Esc cancels."
    )
    bl_options = {"REGISTER", "UNDO"}

    vertices_json: StringProperty(
        name="Vertices JSON",
        description="JSON-encoded [[x,y,z], ...] vertex list set by the modal "
        "on commit. Supply directly for the headless EXEC_DEFAULT path.",
        default="",
        options={"SKIP_SAVE"},
    )
    feature_line_name: StringProperty(
        name="Feature Line Name",
        description="Human-readable name for the new feature line.",
        default="Feature Line",
    )
    closed: BoolProperty(
        name="Closed Loop",
        description="True for closed loops (e.g., pad perimeters); "
        "False for open lines (e.g., ditch centerlines).",
        default=False,
    )

    # --- Modal state (not serialised) -----------------------------------------
    _vertices: list

    def invoke(self, context, event):
        self._vertices = []
        context.window_manager.modal_handler_add(self)
        self.report({"INFO"}, "Click to place vertices; Enter commits; Esc cancels")
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
            if len(self._vertices) < 2:
                self.report({"ERROR"}, "Need at least 2 vertices for a feature line")
                return {"CANCELLED"}
            self.vertices_json = json.dumps(self._vertices)
            return self.execute(context)

        elif event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self.report({"INFO"}, "Feature line draw cancelled")
            return {"CANCELLED"}

        return {"PASS_THROUGH"}

    def _execute(self, context):
        if not self.vertices_json:
            self.report({"ERROR"}, "vertices_json is required")
            return {"CANCELLED"}

        try:
            raw_verts = json.loads(self.vertices_json)
            vertices = [
                (float(v[0]), float(v[1]), float(v[2])) for v in raw_verts
            ]
        except (ValueError, KeyError, TypeError) as exc:
            self.report({"ERROR"}, f"Invalid vertices_json: {exc}")
            return {"CANCELLED"}

        if len(vertices) < 2:
            self.report({"ERROR"}, "A feature line requires at least 2 vertices")
            return {"CANCELLED"}

        try:
            feature_line = core_grading.create_feature_line(
                tool.Ifc,
                tool.Grading,
                name=self.feature_line_name,
                vertices=vertices,
                closed=bool(self.closed),
            )
        except (ValueError, tool_grading.SaikeiGradingError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        try:
            tool.Grading.create_blender_curve(tool.Ifc.get(), feature_line)
        except tool_grading.SaikeiGradingError as exc:
            self.report(
                {"WARNING"},
                f"Feature line authored to IFC but Blender curve creation "
                f"failed: {exc}",
            )

        from .data import GradingData

        GradingData.is_loaded = False
        self.report(
            {"INFO"},
            f"Created feature line {feature_line.name!r} "
            f"({len(feature_line.vertices)} vertices)",
        )
        return {"FINISHED"}


class CIVIL_OT_feature_line_grab_elevation(Operator, tool.Ifc.Operator):
    """Interactively drag a single feature-line vertex up or down.

    Modal entry: drag mouse Y to adjust vertex Z; numeric typing overrides
    drag; Enter commits; Esc cancels.

    Headless / ``_from_data`` path: invoke with ``EXEC_DEFAULT`` and set
    ``feature_line_guid``, ``vertex_index``, and ``delta_z``.

    Headless usage::

        bpy.ops.civil.feature_line_grab_elevation(
            "EXEC_DEFAULT",
            feature_line_guid="...",
            vertex_index=0,
            delta_z=5.0,
        )

    Per spec §6.2 footnote: this dispatches directly to
    :meth:`tool.Grading.update_feature_line_vertices`, matching the
    pattern at ``grading/operator.py`` for the existing headless
    :class:`CIVIL_OT_feature_line_edit_elevations`. No core hop is
    introduced because the mutation is a pure curve-vertex update.
    """

    bl_idname = "civil.feature_line_grab_elevation"
    bl_label = "Quick Elevation Edit"
    bl_description = (
        "G-key style modal for raising or lowering a feature-line vertex "
        "by a typed delta."
    )
    bl_options = {"REGISTER", "UNDO"}

    feature_line_guid: StringProperty(
        name="Feature Line GUID",
        description="GlobalId of the feature line to edit.",
    )
    vertex_index: IntProperty(
        name="Vertex Index",
        description="Zero-based index of the vertex to move.",
        default=0,
        min=0,
    )
    delta_z: FloatProperty(
        name="Delta Z",
        description="Z offset applied to the selected vertex (positive = up).",
        default=0.0,
    )

    # --- Modal state (not serialised) -----------------------------------------
    _feature_line: object
    _original_z: float
    _start_mouse_y: int
    _numeric_entry: str

    def invoke(self, context, event):
        if not self.feature_line_guid:
            props = context.scene.CivilGradingProperties
            self.feature_line_guid = props.active_feature_line_guid
        if not self.feature_line_guid:
            self.report({"ERROR"}, "feature_line_guid is required")
            return {"CANCELLED"}

        ifc_file = tool.Ifc.get()
        if ifc_file is None:
            self.report({"ERROR"}, "No IFC file loaded")
            return {"CANCELLED"}

        try:
            self._feature_line = tool.Grading.get_feature_line(
                ifc_file, self.feature_line_guid
            )
        except tool_grading.SaikeiGradingError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        n = len(self._feature_line.vertices)
        if not (0 <= self.vertex_index < n):
            self.report(
                {"ERROR"},
                f"vertex_index {self.vertex_index} out of range [0, {n})",
            )
            return {"CANCELLED"}

        self._original_z = self._feature_line.vertices[self.vertex_index][2]
        self._start_mouse_y = event.mouse_y
        self._numeric_entry = ""
        context.window_manager.modal_handler_add(self)
        self.report(
            {"INFO"},
            "Drag mouse to adjust elevation; Enter commits; Esc cancels",
        )
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            if self._numeric_entry:
                try:
                    self.delta_z = float(self._numeric_entry)
                except ValueError:
                    self.report(
                        {"ERROR"},
                        f"Invalid numeric input: {self._numeric_entry!r}",
                    )
                    return {"CANCELLED"}
            return self.execute(context)

        elif event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self.report({"INFO"}, "Elevation grab cancelled")
            return {"CANCELLED"}

        elif event.type in {
            "ZERO", "ONE", "TWO", "THREE", "FOUR",
            "FIVE", "SIX", "SEVEN", "EIGHT", "NINE",
            "NUMPAD_0", "NUMPAD_1", "NUMPAD_2", "NUMPAD_3", "NUMPAD_4",
            "NUMPAD_5", "NUMPAD_6", "NUMPAD_7", "NUMPAD_8", "NUMPAD_9",
            "PERIOD", "NUMPAD_PERIOD", "MINUS",
        } and event.value == "PRESS":
            key_map = {
                "ZERO": "0", "ONE": "1", "TWO": "2", "THREE": "3",
                "FOUR": "4", "FIVE": "5", "SIX": "6", "SEVEN": "7",
                "EIGHT": "8", "NINE": "9",
                "NUMPAD_0": "0", "NUMPAD_1": "1", "NUMPAD_2": "2",
                "NUMPAD_3": "3", "NUMPAD_4": "4", "NUMPAD_5": "5",
                "NUMPAD_6": "6", "NUMPAD_7": "7", "NUMPAD_8": "8",
                "NUMPAD_9": "9",
                "PERIOD": ".", "NUMPAD_PERIOD": ".",
                "MINUS": "-",
            }
            self._numeric_entry += key_map.get(event.type, "")
            return {"RUNNING_MODAL"}

        elif event.type == "BACK_SPACE" and event.value == "PRESS":
            self._numeric_entry = self._numeric_entry[:-1]
            return {"RUNNING_MODAL"}

        elif event.type == "MOUSEMOVE":
            # Drag: 1 pixel ≈ 0.01 m.
            if not self._numeric_entry:
                self.delta_z = (event.mouse_y - self._start_mouse_y) * 0.01
            context.area.tag_redraw()
            return {"RUNNING_MODAL"}

        return {"PASS_THROUGH"}

    def _execute(self, context):
        if not self.feature_line_guid:
            self.report({"ERROR"}, "feature_line_guid is required")
            return {"CANCELLED"}

        ifc_file = tool.Ifc.get()
        if ifc_file is None:
            self.report({"ERROR"}, "No IFC file loaded")
            return {"CANCELLED"}

        try:
            feature_line = tool.Grading.get_feature_line(
                ifc_file, self.feature_line_guid
            )
        except tool_grading.SaikeiGradingError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        n = len(feature_line.vertices)
        if not (0 <= self.vertex_index < n):
            self.report(
                {"ERROR"},
                f"vertex_index {self.vertex_index} out of range [0, {n})",
            )
            return {"CANCELLED"}

        new_verts = list(feature_line.vertices)
        x, y, z = new_verts[self.vertex_index]
        new_verts[self.vertex_index] = (x, y, z + self.delta_z)
        feature_line.vertices = new_verts

        try:
            tool.Grading.update_feature_line_vertices(ifc_file, feature_line)
        except tool_grading.SaikeiGradingError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        try:
            tool.Grading.update_blender_curve(ifc_file, feature_line)
        except Exception as exc:
            self.report(
                {"WARNING"},
                f"Vertex updated in IFC but Blender curve refresh failed: {exc}",
            )

        from .data import GradingData

        GradingData.is_loaded = False
        self.report(
            {"INFO"},
            f"Vertex {self.vertex_index} of {feature_line.name!r} "
            f"moved by dZ={self.delta_z:.3f}",
        )
        return {"FINISHED"}


class CIVIL_OT_grading_stepped_offset_modal(Operator, tool.Ifc.Operator):
    """Create a parallel stepped-offset copy of a feature line.

    Modal entry: pick the source feature line by clicking its curve
    object; type or drag for offset distance; type elevation step;
    Enter commits; Esc cancels.

    Headless / ``_from_data`` path: invoke with ``EXEC_DEFAULT`` and set
    ``source_fl_id``, ``offset``, ``step_dz``, and ``new_name``.

    Headless usage::

        bpy.ops.civil.grading_stepped_offset_modal(
            "EXEC_DEFAULT",
            source_fl_id=5,
            offset=3.0,
            step_dz=0.1,
            new_name="Offset FL",
        )
    """

    bl_idname = "civil.grading_stepped_offset_modal"
    bl_label = "Stepped Offset Feature Line"
    bl_description = (
        "Create a parallel stepped-offset copy of a feature line. "
        "Each vertex is shifted perpendicular to the local direction "
        "and incremented in elevation."
    )
    bl_options = {"REGISTER", "UNDO"}

    source_fl_id: IntProperty(
        name="Source Feature Line ID",
        description="IFC step id of the source feature line alignment.",
        default=0,
    )
    offset: FloatProperty(
        name="Offset Distance",
        description="Perpendicular offset in project units (positive = left).",
        default=1.0,
    )
    step_dz: FloatProperty(
        name="Elevation Step",
        description="Z increment applied cumulatively along the polyline "
        "(positive = uphill, negative = downhill).",
        default=0.0,
    )
    new_name: StringProperty(
        name="New Feature Line Name",
        description="Name for the resulting offset feature line.",
        default="Offset FL",
    )

    # --- Modal state (not serialised) -----------------------------------------
    _start_mouse_x: int
    _numeric_entry: str

    def invoke(self, context, event):
        """Enter modal or fast-execute when source is already set.

        User must select the source feature line in the viewport BEFORE
        activating the modal; the first left-click in the modal resolves
        ``source_fl_id`` from the currently active object.

        Future polish: in-modal raycast pick via
        ``mathutils.geometry.intersect_line_plane`` against Z=0.
        """
        if self.source_fl_id > 0:
            # If already set (e.g. panel button) skip the pick step.
            return self.execute(context)
        self._start_mouse_x = event.mouse_x
        self._numeric_entry = ""
        context.window_manager.modal_handler_add(self)
        self.report(
            {"INFO"},
            "Select a feature-line curve object first; Enter commits offset",
        )
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            if self._numeric_entry:
                try:
                    self.offset = float(self._numeric_entry)
                except ValueError:
                    self.report(
                        {"ERROR"},
                        f"Invalid numeric input: {self._numeric_entry!r}",
                    )
                    return {"CANCELLED"}
            if self.source_fl_id <= 0:
                self.report({"ERROR"}, "No source feature line selected")
                return {"CANCELLED"}
            return self.execute(context)

        elif event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self.report({"INFO"}, "Stepped offset cancelled")
            return {"CANCELLED"}

        elif event.type == "LEFTMOUSE" and event.value == "PRESS":
            # Resolve the source feature line from the active object.
            # Phase 7b scope: user selects the feature-line curve in the
            # viewport before activating the modal.  The active object is
            # the simplest reliable pick without a full raycast.
            obj = context.active_object
            if obj is not None:
                entity = tool.Ifc.get_entity(obj)
                if entity is not None and entity.is_a("IfcAlignment"):
                    if tool.Grading.is_feature_line_alignment(entity):
                        self.source_fl_id = entity.id()
                        self.report(
                            {"INFO"},
                            f"Source FL: {entity.Name!r} — now type or "
                            "drag offset; Enter commits",
                        )
                        self._start_mouse_x = event.mouse_x
                        return {"RUNNING_MODAL"}
            return {"RUNNING_MODAL"}

        elif event.type in {
            "ZERO", "ONE", "TWO", "THREE", "FOUR",
            "FIVE", "SIX", "SEVEN", "EIGHT", "NINE",
            "NUMPAD_0", "NUMPAD_1", "NUMPAD_2", "NUMPAD_3", "NUMPAD_4",
            "NUMPAD_5", "NUMPAD_6", "NUMPAD_7", "NUMPAD_8", "NUMPAD_9",
            "PERIOD", "NUMPAD_PERIOD", "MINUS",
        } and event.value == "PRESS":
            key_map = {
                "ZERO": "0", "ONE": "1", "TWO": "2", "THREE": "3",
                "FOUR": "4", "FIVE": "5", "SIX": "6", "SEVEN": "7",
                "EIGHT": "8", "NINE": "9",
                "NUMPAD_0": "0", "NUMPAD_1": "1", "NUMPAD_2": "2",
                "NUMPAD_3": "3", "NUMPAD_4": "4", "NUMPAD_5": "5",
                "NUMPAD_6": "6", "NUMPAD_7": "7", "NUMPAD_8": "8",
                "NUMPAD_9": "9",
                "PERIOD": ".", "NUMPAD_PERIOD": ".",
                "MINUS": "-",
            }
            self._numeric_entry += key_map.get(event.type, "")
            return {"RUNNING_MODAL"}

        elif event.type == "BACK_SPACE" and event.value == "PRESS":
            self._numeric_entry = self._numeric_entry[:-1]
            return {"RUNNING_MODAL"}

        elif event.type == "MOUSEMOVE":
            if not self._numeric_entry and self.source_fl_id > 0:
                self.offset = (event.mouse_x - self._start_mouse_x) * 0.02
            context.area.tag_redraw()
            return {"RUNNING_MODAL"}

        return {"PASS_THROUGH"}

    def _execute(self, context):
        if self.source_fl_id <= 0:
            self.report({"ERROR"}, "source_fl_id is required")
            return {"CANCELLED"}

        ifc_file = tool.Ifc.get()
        if ifc_file is None:
            self.report({"ERROR"}, "No IFC file loaded")
            return {"CANCELLED"}

        try:
            offset_verts = core_grading.compute_stepped_offset(
                tool.Ifc,
                tool.Grading,
                fl_guid=ifc_file.by_id(self.source_fl_id).GlobalId,
                offset=self.offset,
                step_dz=self.step_dz,
            )
        except (ValueError, tool_grading.SaikeiGradingError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        try:
            feature_line = core_grading.create_feature_line(
                tool.Ifc,
                tool.Grading,
                name=self.new_name,
                vertices=offset_verts,
                closed=False,
            )
        except (ValueError, tool_grading.SaikeiGradingError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        try:
            tool.Grading.create_blender_curve(ifc_file, feature_line)
        except tool_grading.SaikeiGradingError as exc:
            self.report(
                {"WARNING"},
                f"Offset FL authored to IFC but Blender curve failed: {exc}",
            )

        from .data import GradingData

        GradingData.is_loaded = False
        self.report(
            {"INFO"},
            f"Created offset feature line {feature_line.name!r} "
            f"({len(feature_line.vertices)} vertices)",
        )
        return {"FINISHED"}


class CIVIL_OT_grading_fillet_modal(Operator, tool.Ifc.Operator):
    """Replace a sharp corner in a feature line with a circular arc.

    Modal entry: click to pick a feature line, click a vertex to mark it,
    drag outward for radius, Enter commits; Esc cancels.

    Headless / ``_from_data`` path: invoke with ``EXEC_DEFAULT`` and set
    ``fl_guid``, ``vertex_index``, and ``radius``.

    Headless usage::

        bpy.ops.civil.grading_fillet_modal(
            "EXEC_DEFAULT",
            fl_guid="...",
            vertex_index=1,
            radius=2.0,
        )
    """

    bl_idname = "civil.grading_fillet_modal"
    bl_label = "Fillet Feature Line Corner"
    bl_description = (
        "Replace a sharp corner in a feature line with a smooth circular "
        "arc. Pick the feature line, click a vertex, drag for radius."
    )
    bl_options = {"REGISTER", "UNDO"}

    fl_guid: StringProperty(
        name="Feature Line GUID",
        description="GlobalId of the feature line to fillet.",
        default="",
    )
    vertex_index: IntProperty(
        name="Vertex Index",
        description="Zero-based index of the corner vertex to fillet.",
        default=1,
        min=1,
    )
    radius: FloatProperty(
        name="Radius",
        description="Fillet radius in project units. Must be smaller than "
        "half the length of each adjacent segment.",
        default=1.0,
        min=1e-4,
    )

    # --- Modal state (not serialised) -----------------------------------------
    _start_mouse_x: int
    _numeric_entry: str

    def invoke(self, context, event):
        """Enter modal or fast-execute when fl_guid is already set.

        User must select the source feature line in the viewport BEFORE
        activating the modal; the first left-click in the modal resolves
        ``fl_guid`` from the currently active object.  The ``vertex_index``
        must be set numerically before drag-radius begins.

        Future polish: in-modal raycast pick and click-to-pick vertex.
        """
        if self.fl_guid:
            return self.execute(context)
        self._start_mouse_x = event.mouse_x
        self._numeric_entry = ""
        context.window_manager.modal_handler_add(self)
        self.report(
            {"INFO"},
            "Select a feature-line curve first; set vertex_index; drag for radius",
        )
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            if self._numeric_entry:
                try:
                    self.radius = float(self._numeric_entry)
                except ValueError:
                    self.report(
                        {"ERROR"},
                        f"Invalid numeric input: {self._numeric_entry!r}",
                    )
                    return {"CANCELLED"}
            if not self.fl_guid:
                self.report({"ERROR"}, "No feature line selected")
                return {"CANCELLED"}
            return self.execute(context)

        elif event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self.report({"INFO"}, "Fillet cancelled")
            return {"CANCELLED"}

        elif event.type == "LEFTMOUSE" and event.value == "PRESS":
            # Resolve the feature line from the active object.
            # Phase 7b scope: user selects the feature-line curve in the
            # viewport before activating the modal.
            obj = context.active_object
            if obj is not None:
                entity = tool.Ifc.get_entity(obj)
                if entity is not None and entity.is_a("IfcAlignment"):
                    if tool.Grading.is_feature_line_alignment(entity):
                        self.fl_guid = entity.GlobalId
                        self.report(
                            {"INFO"},
                            f"Selected FL: {entity.Name!r} — "
                            "now type or drag radius; Enter commits",
                        )
                        self._start_mouse_x = event.mouse_x
                        return {"RUNNING_MODAL"}
            return {"RUNNING_MODAL"}

        elif event.type in {
            "ZERO", "ONE", "TWO", "THREE", "FOUR",
            "FIVE", "SIX", "SEVEN", "EIGHT", "NINE",
            "NUMPAD_0", "NUMPAD_1", "NUMPAD_2", "NUMPAD_3", "NUMPAD_4",
            "NUMPAD_5", "NUMPAD_6", "NUMPAD_7", "NUMPAD_8", "NUMPAD_9",
            "PERIOD", "NUMPAD_PERIOD",
        } and event.value == "PRESS":
            key_map = {
                "ZERO": "0", "ONE": "1", "TWO": "2", "THREE": "3",
                "FOUR": "4", "FIVE": "5", "SIX": "6", "SEVEN": "7",
                "EIGHT": "8", "NINE": "9",
                "NUMPAD_0": "0", "NUMPAD_1": "1", "NUMPAD_2": "2",
                "NUMPAD_3": "3", "NUMPAD_4": "4", "NUMPAD_5": "5",
                "NUMPAD_6": "6", "NUMPAD_7": "7", "NUMPAD_8": "8",
                "NUMPAD_9": "9",
                "PERIOD": ".", "NUMPAD_PERIOD": ".",
            }
            self._numeric_entry += key_map.get(event.type, "")
            return {"RUNNING_MODAL"}

        elif event.type == "BACK_SPACE" and event.value == "PRESS":
            self._numeric_entry = self._numeric_entry[:-1]
            return {"RUNNING_MODAL"}

        elif event.type == "MOUSEMOVE":
            if not self._numeric_entry and self.fl_guid:
                drag = (event.mouse_x - self._start_mouse_x) * 0.02
                self.radius = max(1e-4, drag)
            context.area.tag_redraw()
            return {"RUNNING_MODAL"}

        return {"PASS_THROUGH"}

    def _execute(self, context):
        if not self.fl_guid:
            self.report({"ERROR"}, "fl_guid is required")
            return {"CANCELLED"}

        if self.radius <= 0.0:
            self.report({"ERROR"}, f"radius must be positive; got {self.radius}")
            return {"CANCELLED"}

        try:
            core_grading.insert_fillet(
                tool.Ifc,
                tool.Grading,
                fl_guid=self.fl_guid,
                vertex_index=self.vertex_index,
                radius=self.radius,
            )
        except (ValueError, tool_grading.SaikeiGradingError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        from .data import GradingData

        GradingData.is_loaded = False
        self.report(
            {"INFO"},
            f"Inserted fillet at vertex {self.vertex_index} "
            f"(radius={self.radius:.3f})",
        )
        return {"FINISHED"}

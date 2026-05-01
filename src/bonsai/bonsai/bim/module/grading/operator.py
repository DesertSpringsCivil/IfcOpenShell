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

import bpy
from bpy.props import BoolProperty, StringProperty
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

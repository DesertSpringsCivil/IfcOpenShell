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

"""Operators for the Saikei earthwork module.

Same Bonsai operator pattern as Phase 4 (surface) and Phase 5
(grading): every operator inherits :class:`tool.Ifc.Operator` so
undo/redo, IFC mutation tracking, and validation hooks run
automatically. Implements ``_execute`` (not ``execute``) — Bonsai
wraps the underscore form with the IFC operator boilerplate.
"""

import bpy
from bpy.props import EnumProperty, FloatProperty, FloatVectorProperty, StringProperty
from bpy.types import Operator

import bonsai.core.earthwork as core_earthwork
import bonsai.tool as tool
import bonsai.tool.earthwork as tool_earthwork


class CIVIL_OT_compute_earthwork_volumes(Operator, tool.Ifc.Operator):
    """Compute cut and fill volumes between two surfaces and persist
    the result to IFC.

    Inputs default to :class:`CivilEarthworkProperties` panel state
    (``existing_surface_guid``, ``proposed_surface_guid``,
    ``shrink_factor``, ``swell_factor``, etc.); the operator's own
    properties override per-call.

    Headless usage::

        bpy.ops.civil.compute_earthwork_volumes(
            "EXEC_DEFAULT",
            existing_surface_guid="<terrain-guid>",
            proposed_surface_guid="<proposed-guid>",
            shrink_factor=0.92,
            swell_factor=1.25,
        )

    Side effects:

    - Authors :class:`IfcEarthworksCut` and/or :class:`IfcEarthworksFill`
      with closed PolygonalFaceSet body geometry.
    - Authors :class:`IfcRelVoidsElement` (cut → terrain) and
      :class:`IfcRelFillsElement` (fill → cut) when both cut and
      fill exist.
    - Authors ``Qto_EarthworksCut/FillBaseQuantities`` with
      ``UndisturbedVolume`` / ``LooseVolume`` (cut) and
      ``CompactedVolume`` / ``LooseVolume`` (fill) — ``LooseVolume``
      is computed as ``UndisturbedVolume × swell_factor``, closing
      the audit gap.
    - Authors ``SaikeiCivil_GradingShrinkSwell`` with the shrink/swell
      factors.
    - Stamps ``last_cut_m3`` / ``last_fill_m3`` / ``last_net_m3`` /
      ``last_loose_cut_m3`` on :class:`CivilEarthworkProperties` so
      the panel shows the result after the operator finishes.
    """

    bl_idname = "civil.compute_earthwork_volumes"
    bl_label = "Compute Earthwork Volumes"
    bl_description = (
        "Compute cut and fill volumes between two surfaces and write "
        "the result to IFC. Authors cut and fill entities with closed "
        "solid bodies, quantity takeoffs, and shrink/swell properties."
    )
    bl_options = {"REGISTER", "UNDO"}

    existing_surface_guid: StringProperty(
        name="Existing Surface GUID",
        description="GlobalId of the existing-ground CivilSurface",
        default="",
    )
    proposed_surface_guid: StringProperty(
        name="Proposed Surface GUID",
        description="GlobalId of the proposed-ground CivilSurface",
        default="",
    )
    # Sentinel default 0.0 means "fall back to panel state in
    # _execute". The valid ranges for both factors exclude 0.0
    # (shrink ∈ [0.5, 1.5], swell ∈ [1.0, 1.5]) so 0.0 unambiguously
    # signals "not explicitly supplied".
    shrink_factor: FloatProperty(
        name="Shrink Factor",
        default=0.0,
        min=0.0,
        max=1.5,
    )
    swell_factor: FloatProperty(
        name="Swell Factor",
        default=0.0,
        min=0.0,
        max=1.5,
    )
    cut_name: StringProperty(name="Cut Name", default="")
    fill_name: StringProperty(name="Fill Name", default="")
    cut_predefined_type: StringProperty(
        name="Cut Predefined Type",
        default="EXCAVATION",
    )
    fill_predefined_type: StringProperty(
        name="Fill Predefined Type",
        default="BACKFILL",
    )

    def _execute(self, context):
        props = context.scene.CivilEarthworkProperties
        # Fall back to panel state when the operator wasn't given
        # explicit GUIDs.
        existing_guid = (
            self.existing_surface_guid or props.existing_surface_guid
        )
        proposed_guid = (
            self.proposed_surface_guid or props.proposed_surface_guid
        )
        if not existing_guid or not proposed_guid:
            self.report(
                {"ERROR"},
                "Both existing_surface_guid and proposed_surface_guid "
                "are required",
            )
            return {"CANCELLED"}

        cut_name = self.cut_name or props.cut_name
        fill_name = self.fill_name or props.fill_name
        cut_predefined_type = (
            self.cut_predefined_type or props.cut_predefined_type
        )
        fill_predefined_type = (
            self.fill_predefined_type or props.fill_predefined_type
        )
        # Sentinel default 0.0 means "fall back to panel state".
        shrink_factor = (
            self.shrink_factor if self.shrink_factor > 0 else props.shrink_factor
        )
        swell_factor = (
            self.swell_factor if self.swell_factor > 0 else props.swell_factor
        )

        try:
            result = core_earthwork.compute_earthwork_volumes(
                tool.Ifc,
                tool.Surface,
                tool.Earthwork,
                existing_surface_guid=existing_guid,
                proposed_surface_guid=proposed_guid,
                shrink_factor=shrink_factor,
                swell_factor=swell_factor,
                cut_name=cut_name,
                fill_name=fill_name,
                cut_predefined_type=cut_predefined_type,
                fill_predefined_type=fill_predefined_type,
            )
        except (ValueError, tool_earthwork.SaikeiEarthworkError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        # Cache the report on the PropertyGroup so the panel shows
        # a persistent summary without recomputing.
        props.last_cut_m3 = float(result.undisturbed_cut_m3)
        props.last_fill_m3 = float(result.compacted_fill_m3)
        props.last_net_m3 = float(result.net_volume_m3)
        props.last_loose_cut_m3 = float(result.loose_cut_m3)
        props.last_run_existing_guid = existing_guid
        props.last_run_proposed_guid = proposed_guid

        # Stamp IFC entity GUIDs so the delete-results operator can
        # locate and remove the authored entities without a file scan.
        ifc_file = tool.Ifc.get()
        if result.ifc_cut_id is not None and ifc_file is not None:
            cut_entity = ifc_file.by_id(result.ifc_cut_id)
            props.last_run_cut_guid = cut_entity.GlobalId
        else:
            props.last_run_cut_guid = ""
        if result.ifc_fill_id is not None and ifc_file is not None:
            fill_entity = ifc_file.by_id(result.ifc_fill_id)
            props.last_run_fill_guid = fill_entity.GlobalId
        else:
            props.last_run_fill_guid = ""

        self.report(
            {"INFO"},
            f"Earthwork: cut={result.undisturbed_cut_m3:.1f} m³ "
            f"({result.cut_cubic_yards:.1f} cu yd) | "
            f"fill={result.compacted_fill_m3:.1f} m³ "
            f"({result.fill_cubic_yards:.1f} cu yd) | "
            f"net={result.net_volume_m3:+.1f} m³",
        )
        return {"FINISHED"}


class CIVIL_OT_earthwork_clear_report(Operator):
    """Reset the last-run report fields on CivilEarthworkProperties.

    Clears the cached cut / fill / net / loose-cut volumes and the
    last-run surface GUIDs so the panel shows no stale report.  Does
    NOT modify the IFC file — this is a UI-state reset only.  Use
    ``CIVIL_OT_earthwork_delete_results`` to remove the authored IFC
    entities as well.

    Headless usage::

        bpy.ops.civil.earthwork_clear_report("EXEC_DEFAULT")
    """

    bl_idname = "civil.earthwork_clear_report"
    bl_label = "Clear Results"
    bl_description = (
        "Clear the last computed earthwork report. Zeros the cached "
        "cut, fill, and net volumes in the panel. No IFC change - use "
        "Delete Results to remove authored volume entities."
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.CivilEarthworkProperties
        props.last_cut_m3 = 0.0
        props.last_fill_m3 = 0.0
        props.last_net_m3 = 0.0
        props.last_loose_cut_m3 = 0.0
        props.last_run_existing_guid = ""
        props.last_run_proposed_guid = ""
        props.last_run_cut_guid = ""
        props.last_run_fill_guid = ""
        self.report({"INFO"}, "Earthwork report cleared.")
        return {"FINISHED"}


class CIVIL_OT_earthwork_delete_results(Operator, tool.Ifc.Operator):
    """Delete the cut and fill volume entities from the last run.

    Removes the :class:`IfcEarthworksCut` and
    :class:`IfcEarthworksFill` entities authored by the most recent
    ``Compute Volumes`` run (identified by
    ``CivilEarthworkProperties.last_run_cut_guid`` /
    ``last_run_fill_guid``), together with their voiding /
    filling relationship chains and quantity sets.  Also clears the
    last-run report fields.

    This operator requires a prior ``Compute Volumes`` run in the
    current session.  If no run GUID is cached the operator cancels
    with an error.

    Headless usage::

        bpy.ops.civil.earthwork_delete_results("EXEC_DEFAULT")
    """

    bl_idname = "civil.earthwork_delete_results"
    bl_label = "Delete Results"
    bl_description = (
        "Delete the cut and fill volume entities authored on the last "
        "Compute Volumes run. Removes IFC entities, quantity sets, and "
        "voiding relationships. Clears the report panel. Irreversible "
        "without undo."
    )
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    def _execute(self, context):
        props = context.scene.CivilEarthworkProperties
        cut_guid = props.last_run_cut_guid
        fill_guid = props.last_run_fill_guid

        if not cut_guid and not fill_guid:
            self.report(
                {"WARNING"},
                "No prior earthwork run found. Run 'Compute Volumes' first.",
            )
            return {"CANCELLED"}

        try:
            core_earthwork.delete_earthwork_results(
                tool.Ifc,
                tool.Earthwork,
                cut_guid=cut_guid,
                fill_guid=fill_guid,
            )
        except (ValueError, tool_earthwork.SaikeiEarthworkError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        # Clear cached report after successful deletion.
        props.last_cut_m3 = 0.0
        props.last_fill_m3 = 0.0
        props.last_net_m3 = 0.0
        props.last_loose_cut_m3 = 0.0
        props.last_run_existing_guid = ""
        props.last_run_proposed_guid = ""
        props.last_run_cut_guid = ""
        props.last_run_fill_guid = ""

        self.report({"INFO"}, "Earthwork volume results deleted.")
        return {"FINISHED"}


class CIVIL_OT_earthwork_volume_probe(Operator, tool.Ifc.Operator):
    """Hover or click to probe cut and fill volumes at any point.

    Modal entry (``invoke``): move the mouse to preview the cut/fill
    depth under the cursor via a status-bar info message; left-click
    commits a :class:`IfcAnnotation` volume label at that position;
    Esc cancels without authoring.

    Headless / ``_from_data`` path: invoke with ``EXEC_DEFAULT`` and
    supply ``xyz`` directly.  The operator reads the last-run surface
    GUIDs from :class:`CivilEarthworkProperties` and computes depths
    from the cached surfaces::

        bpy.ops.civil.earthwork_volume_probe(
            "EXEC_DEFAULT",
            xyz=(500.0, 300.0, 0.0),
            label_text="Station 1+250",
        )

    Guard: if ``CivilEarthworkProperties.last_run_existing_guid`` or
    ``last_run_proposed_guid`` is empty (no prior ``Compute Volumes``
    run in the current session), ``invoke`` / ``_execute`` cancels
    immediately with a ``WARNING`` report.
    """

    bl_idname = "civil.earthwork_volume_probe"
    bl_label = "Probe Volume"
    bl_description = (
        "Click to place a cut/fill volume label at any point. "
        "Requires a prior Compute Volumes run to identify the surfaces."
    )
    bl_options = {"REGISTER", "UNDO"}

    xyz: FloatVectorProperty(
        name="Probe Position",
        description="World-space XYZ position of the probe point",
        size=3,
        default=(0.0, 0.0, 0.0),
    )
    label_text: StringProperty(
        name="Label Text",
        description="Optional free-text override for the annotation name",
        default="",
    )

    # --- Modal state (not operator properties — not serialised) ----------
    _existing_guid: str
    _proposed_guid: str

    def invoke(self, context, event):
        props = context.scene.CivilEarthworkProperties
        existing_guid = props.last_run_existing_guid
        proposed_guid = props.last_run_proposed_guid

        if not existing_guid or not proposed_guid:
            self.report(
                {"WARNING"},
                "No prior Compute Volumes run found. "
                "Run 'Compute Volumes' first to identify surfaces.",
            )
            return {"CANCELLED"}

        self._existing_guid = existing_guid
        self._proposed_guid = proposed_guid

        context.window_manager.modal_handler_add(self)
        self.report(
            {"INFO"},
            "Move mouse to preview cut/fill depth; "
            "left-click to place label; Esc to cancel",
        )
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "MOUSEMOVE":
            # Ray-cast mouse onto Z=0 plane — same pattern as surface modal.
            region = context.region
            rv3d = context.region_data
            if region is None or rv3d is None:
                return {"PASS_THROUGH"}
            from bpy_extras import view3d_utils

            coord = (event.mouse_region_x, event.mouse_region_y)
            view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
            ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
            if view_vector.z != 0:
                t = -ray_origin.z / view_vector.z
                hit = ray_origin + t * view_vector
            else:
                hit = ray_origin
            # Stash the current probe position on the operator property
            # (no IFC work here — modal must stay side-effect free).
            self.xyz = (float(hit.x), float(hit.y), float(hit.z))
            context.area.tag_redraw()
            return {"PASS_THROUGH"}

        elif event.type == "LEFTMOUSE" and event.value == "PRESS":
            # Commit: dispatch IFC authoring via _execute.
            return self.execute(context)

        elif event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self.report({"INFO"}, "Volume probe cancelled")
            return {"CANCELLED"}

        return {"PASS_THROUGH"}

    def _execute(self, context):
        props = context.scene.CivilEarthworkProperties

        # Accept either modal-set self.xyz or headless-supplied property.
        probe_xyz = tuple(self.xyz)

        existing_guid = (
            getattr(self, "_existing_guid", None)
            or props.last_run_existing_guid
        )
        proposed_guid = (
            getattr(self, "_proposed_guid", None)
            or props.last_run_proposed_guid
        )

        if not existing_guid or not proposed_guid:
            self.report(
                {"WARNING"},
                "No prior Compute Volumes run found. "
                "Run 'Compute Volumes' first to identify surfaces.",
            )
            return {"CANCELLED"}

        try:
            core_earthwork.author_volume_label_at_surfaces(
                tool.Ifc,
                tool.Earthwork,
                tool.Surface,
                existing_surface_guid=existing_guid,
                proposed_surface_guid=proposed_guid,
                xyz=probe_xyz,
                label_text=self.label_text,
            )
        except (ValueError, tool_earthwork.SaikeiEarthworkError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        # Invalidate data cache if it exists (optional module, Phase 7b+).
        try:
            from .data import EarthworkData  # noqa: PLC0415

            EarthworkData.is_loaded = False
        except ImportError:
            pass

        self.report(
            {"INFO"},
            f"Volume label placed at "
            f"({probe_xyz[0]:.2f}, {probe_xyz[1]:.2f}, {probe_xyz[2]:.2f})",
        )
        return {"FINISHED"}

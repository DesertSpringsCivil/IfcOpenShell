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
from bpy.props import EnumProperty, FloatProperty, StringProperty
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
    - Authors ``Pset_SaikeiGradingShrinkSwell`` with the shrink/swell
      factors.
    - Stamps ``last_cut_m3`` / ``last_fill_m3`` / ``last_net_m3`` /
      ``last_loose_cut_m3`` on :class:`CivilEarthworkProperties` so
      the panel shows the result after the operator finishes.
    """

    bl_idname = "civil.compute_earthwork_volumes"
    bl_label = "Compute Earthwork Volumes"
    bl_description = (
        "Compute cut/fill volumes between two surfaces (TIN-to-TIN "
        "prismoidal). Authors IfcEarthworksCut/Fill entities with "
        "Qto and shrink/swell pset. Spec §6.4 + §6.5."
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
    shrink_factor: FloatProperty(
        name="Shrink Factor",
        default=1.0,
        min=0.5,
        max=1.5,
    )
    swell_factor: FloatProperty(
        name="Swell Factor",
        default=1.0,
        min=0.8,
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

        try:
            result = core_earthwork.compute_earthwork_volumes(
                tool.Ifc,
                tool.Surface,
                tool.Earthwork,
                existing_surface_guid=existing_guid,
                proposed_surface_guid=proposed_guid,
                shrink_factor=self.shrink_factor,
                swell_factor=self.swell_factor,
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

        self.report(
            {"INFO"},
            f"Earthwork: cut={result.undisturbed_cut_m3:.1f} m³ "
            f"({result.cut_cubic_yards:.1f} cu yd) | "
            f"fill={result.compacted_fill_m3:.1f} m³ "
            f"({result.fill_cubic_yards:.1f} cu yd) | "
            f"net={result.net_volume_m3:+.1f} m³",
        )
        return {"FINISHED"}

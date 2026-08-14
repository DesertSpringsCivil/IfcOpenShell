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

"""Operators for the Saikei voxel earthwork module.

These build *disposable* Blender previews and write the IFC 4.4 sidecar; none
mutate the loaded production IFC, so they are plain operators (no
``tool.Ifc.Operator`` transaction wrapping).
"""

import bpy
from bpy.types import Operator

import bonsai.core.voxel as core
import bonsai.tool as tool


def _z_range(props):
    return (props.z_min, props.z_max) if props.use_z_range else (None, None)


def _all_surface_guids(ifc_file):
    """All authored surfaces (existing terrains + proposed fills) by GlobalId."""
    guids = []
    for terrain in ifc_file.by_type("IfcGeographicElement"):
        if terrain.PredefinedType == "TERRAIN":
            guids.append(terrain.GlobalId)
    for fill in ifc_file.by_type("IfcEarthworksFill"):
        if fill.PredefinedType == "SUBGRADE":
            guids.append(fill.GlobalId)
    return guids


class CIVIL_OT_voxel_preview_cut_fill(Operator):
    bl_idname = "civil.voxel_preview_cut_fill"
    bl_label = "Preview Cut / Fill Voxels"
    bl_description = "Voxelize existing vs design surfaces and show cut (red) / fill (blue) volumes"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.CivilVoxelProperties
        if not props.existing_surface or not props.design_surface:
            self.report({"ERROR"}, "Pick both an existing and a design surface")
            return {"CANCELLED"}
        if props.existing_surface == props.design_surface:
            self.report({"ERROR"}, "Existing and design surfaces must differ")
            return {"CANCELLED"}
        z_min, z_max = _z_range(props)
        try:
            result = core.preview_cut_fill(
                tool.Ifc, tool.Surface, tool.Voxel,
                existing_guid=props.existing_surface, design_guid=props.design_surface,
                cell_size=props.cell_size, z_min=z_min, z_max=z_max, supersample=props.supersample,
            )
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        props.cut_volume = result["cut"]
        props.fill_volume = result["fill"]
        props.net_volume = result["net"]
        props.has_result = True
        self.report(
            {"INFO"},
            f"Cut {result['cut']:.1f} | Fill {result['fill']:.1f} | Net {result['net']:.1f} m³",
        )
        return {"FINISHED"}


class CIVIL_OT_voxel_cut_by_stratum(Operator):
    bl_idname = "civil.voxel_cut_by_stratum"
    bl_label = "Excavation by Stratum"
    bl_description = (
        "Split the excavation (cut) between existing and design by native "
        "stratum, and color the cut region by material"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.CivilVoxelProperties
        if not props.existing_surface or not props.design_surface:
            self.report({"ERROR"}, "Pick both an existing and a design surface")
            return {"CANCELLED"}
        ifc_file = tool.Ifc.get()
        # Stratum boundaries = all surfaces except the design (excavation target);
        # the existing ground is the topmost boundary.
        stratum_guids = [g for g in _all_surface_guids(ifc_file) if g != props.design_surface]
        if len(stratum_guids) < 2:
            self.report({"ERROR"}, "Need >= 2 stratum boundary surfaces (existing + deeper)")
            return {"CANCELLED"}
        z_min, z_max = _z_range(props)
        try:
            result = core.preview_cut_fill_by_stratum(
                tool.Ifc, tool.Surface, tool.Voxel,
                existing_guid=props.existing_surface, design_guid=props.design_surface,
                stratum_guids=stratum_guids, cell_size=props.cell_size,
                z_min=z_min, z_max=z_max, supersample=props.supersample,
            )
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        totals = result["totals"]
        props.cut_volume = totals["cut"]
        props.fill_volume = totals["fill"]
        props.net_volume = totals["net"]
        props.has_result = True
        _populate_strata_table_into(props.cut_strata, result["cut_by_stratum"], result["legend"])
        self.report({"INFO"}, f"Excavation split across {len(result['cut_by_stratum'])} strata")
        return {"FINISHED"}


class CIVIL_OT_voxel_preview_surface(Operator):
    bl_idname = "civil.voxel_preview_surface"
    bl_label = "Preview Surface Occupancy"
    bl_description = "Voxelize a single surface and show the soil occupancy (green)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.CivilVoxelProperties
        if not props.single_surface:
            self.report({"ERROR"}, "Pick a surface to voxelize")
            return {"CANCELLED"}
        z_min, z_max = _z_range(props)
        try:
            result = core.preview_surface_occupancy(
                tool.Ifc, tool.Surface, tool.Voxel,
                surface_guid=props.single_surface, cell_size=props.cell_size,
                z_min=z_min, z_max=z_max, supersample=props.supersample,
            )
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        props.has_result = False
        self.report({"INFO"}, f"Soil volume {result['volume']:.1f} m³")
        return {"FINISHED"}


class CIVIL_OT_voxel_clear_preview(Operator):
    bl_idname = "civil.voxel_clear_preview"
    bl_label = "Clear Voxel Preview"
    bl_description = "Remove the Saikei voxel preview objects"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        removed = core.clear_preview(tool.Voxel)
        context.scene.CivilVoxelProperties.has_result = False
        self.report({"INFO"}, f"Removed {removed} voxel preview object(s)")
        return {"FINISHED"}


class CIVIL_OT_voxel_author_sidecar(Operator):
    bl_idname = "civil.voxel_author_sidecar"
    bl_label = "Author Voxel Sidecar (.ifc)"
    bl_description = "Generate the IFC 4.4 voxel earthwork sidecar and write it to disk"
    bl_options = {"REGISTER"}

    def execute(self, context):
        props = context.scene.CivilVoxelProperties
        if not props.existing_surface or not props.design_surface:
            self.report({"ERROR"}, "Pick both an existing and a design surface")
            return {"CANCELLED"}
        if props.existing_surface == props.design_surface:
            self.report({"ERROR"}, "Existing and design surfaces must differ")
            return {"CANCELLED"}
        z_min, z_max = _z_range(props)
        try:
            sidecar, result = core.author_cut_fill_sidecar(
                tool.Ifc, tool.Surface, tool.Voxel,
                existing_guid=props.existing_surface, design_guid=props.design_surface,
                cell_size=props.cell_size, z_min=z_min, z_max=z_max,
                supersample=props.supersample, swell_factor=props.swell_factor,
            )
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        path = bpy.path.abspath(props.sidecar_filepath)
        sidecar.write(path)
        self.report({"INFO"}, f"Wrote {sidecar.schema} sidecar → {path}")
        return {"FINISHED"}


def _populate_strata_table_into(collection, volumes, legend):
    collection.clear()
    for code in sorted(volumes):
        item = collection.add()
        item.name = legend.get(code, f"stratum {code}")
        item.volume = volumes[code]


def _populate_strata_table(props, volumes, legend):
    _populate_strata_table_into(props.strata, volumes, legend)


class CIVIL_OT_voxel_preview_geomodel(Operator):
    bl_idname = "civil.voxel_preview_geomodel"
    bl_label = "Preview Geomodel Strata"
    bl_description = (
        "Classify all authored surfaces (ordered by elevation) into stratum "
        "voxels and show per-stratum volumes"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.CivilVoxelProperties
        ifc_file = tool.Ifc.get()
        guids = _all_surface_guids(ifc_file) if ifc_file else []
        if len(guids) < 2:
            self.report({"ERROR"}, "Need at least 2 surfaces (stratum boundaries)")
            return {"CANCELLED"}
        z_min, z_max = _z_range(props)
        try:
            result = core.preview_geomodel(
                tool.Ifc, tool.Surface, tool.Voxel,
                surface_guids=guids, cell_size=props.cell_size,
                z_min=z_min, z_max=z_max, supersample=props.supersample,
            )
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        _populate_strata_table(props, result["volumes"], result["legend"])
        self.report({"INFO"}, f"{len(result['volumes'])} strata classified")
        return {"FINISHED"}


class CIVIL_OT_voxel_author_geomodel(Operator):
    bl_idname = "civil.voxel_author_geomodel"
    bl_label = "Author Geomodel Sidecar (.ifc)"
    bl_description = "Generate the IFC 4.4 IfcGeomodel voxel sidecar and write it to disk"
    bl_options = {"REGISTER"}

    def execute(self, context):
        props = context.scene.CivilVoxelProperties
        ifc_file = tool.Ifc.get()
        guids = _all_surface_guids(ifc_file) if ifc_file else []
        if len(guids) < 2:
            self.report({"ERROR"}, "Need at least 2 surfaces (stratum boundaries)")
            return {"CANCELLED"}
        z_min, z_max = _z_range(props)
        try:
            sidecar, volumes, legend = core.author_geomodel_sidecar(
                tool.Ifc, tool.Surface, tool.Voxel,
                surface_guids=guids, cell_size=props.cell_size,
                z_min=z_min, z_max=z_max, supersample=props.supersample,
            )
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        _populate_strata_table(props, volumes, legend)
        path = bpy.path.abspath(props.sidecar_filepath)
        sidecar.write(path)
        self.report({"INFO"}, f"Wrote {sidecar.schema} geomodel → {path}")
        return {"FINISHED"}

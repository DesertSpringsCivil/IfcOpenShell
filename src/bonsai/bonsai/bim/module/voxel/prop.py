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

"""Property group for the Saikei voxel earthwork module.

Exposes the inputs the voxel operators consume — existing/design surface
pickers (dynamic enums over the surfaces authored in the active IFC file),
lattice resolution, optional Z range, supersampling, and shrink/swell — plus
read-only fields the panel shows after a preview (cut / fill / net volumes).
"""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

import bonsai.tool as tool

# Module-level ref to the last-built enum item tuples — Blender requires the
# items() callback's returned strings to outlive the call (else garbage chars).
_surface_enum_cache: list = []


def _surface_enum_items(self, context):
    """Dynamic enum of authored surfaces (terrains + proposed fills) by GlobalId."""
    global _surface_enum_cache
    items = []
    ifc_file = tool.Ifc.get()
    if ifc_file is not None:
        for terrain in ifc_file.by_type("IfcGeographicElement"):
            if terrain.PredefinedType == "TERRAIN":
                items.append((terrain.GlobalId, terrain.Name or "(terrain)", "Existing terrain"))
        for fill in ifc_file.by_type("IfcEarthworksFill"):
            if fill.PredefinedType == "SUBGRADE":
                items.append((fill.GlobalId, fill.Name or "(proposed)", "Proposed surface"))
    if not items:
        items = [("", "(no surfaces)", "Author surfaces in the Terrain / Surface tab first")]
    _surface_enum_cache = items
    return _surface_enum_cache


class CivilVoxelStratumItem(PropertyGroup):
    """One row of the geomodel stratum-volume readout."""

    name: StringProperty(name="Stratum", default="")
    volume: FloatProperty(name="Volume", default=0.0)


class CivilVoxelProperties(PropertyGroup):
    """Saikei voxel earthwork module state (attached to ``bpy.types.Scene``)."""

    existing_surface: EnumProperty(
        name="Existing",
        description="Existing-ground surface (the before state)",
        items=_surface_enum_items,
    )
    design_surface: EnumProperty(
        name="Design",
        description="Design/proposed surface (the after state)",
        items=_surface_enum_items,
    )
    single_surface: EnumProperty(
        name="Surface",
        description="Surface to voxelize for an occupancy preview",
        items=_surface_enum_items,
    )

    cell_size: FloatProperty(
        name="Cell Size",
        description="Voxel edge length (project units). Smaller = finer + more cells",
        default=1.0,
        min=0.01,
        soft_max=10.0,
        precision=3,
    )
    supersample: IntProperty(
        name="Supersample",
        description="N×N XY subsamples per cell (majority vote) for sub-cell "
        "boundary accuracy. 1 = centre test",
        default=1,
        min=1,
        max=5,
    )
    use_z_range: BoolProperty(
        name="Override Z Range",
        description="Set an explicit vertical extent instead of the surfaces' own",
        default=False,
    )
    z_min: FloatProperty(name="Z Min", description="Lattice base elevation", default=0.0)
    z_max: FloatProperty(name="Z Max", description="Lattice top elevation", default=10.0)

    swell_factor: FloatProperty(
        name="Swell Factor",
        description="Bulking factor for the loose (hauled) volume: loose = bank × swell",
        default=1.25,
        min=0.1,
        soft_max=2.0,
        precision=3,
    )

    sidecar_filepath: StringProperty(
        name="Sidecar Path",
        description="Where to write the IFC 4.4 voxel sidecar file",
        default="//voxel_earthwork.ifc",
        subtype="FILE_PATH",
    )

    # ---- Read-only results (set by the preview operators) ----
    has_result: BoolProperty(name="Has Result", default=False)
    cut_volume: FloatProperty(name="Cut", default=0.0)
    fill_volume: FloatProperty(name="Fill", default=0.0)
    net_volume: FloatProperty(name="Net", default=0.0)

    # ---- Geomodel stratum-volume readout (set by the geomodel preview) ----
    strata: CollectionProperty(type=CivilVoxelStratumItem)

    # ---- Excavation-by-stratum readout (set by the cut-by-stratum preview) ----
    cut_strata: CollectionProperty(type=CivilVoxelStratumItem)

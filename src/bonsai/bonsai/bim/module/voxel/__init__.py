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

"""Saikei voxel earthwork module — Bonsai-side UI.

Phase 6 of the Saikei grading/earthwork sprint (voxel pivot). Wraps the voxel
math (:mod:`bonsai.tool.voxel`), cut/fill orchestration (:mod:`bonsai.core.voxel`),
and IFC 4.4 authoring (:mod:`ifcopenshell.api.voxel`) in a viewport UI:

- :mod:`prop` — :class:`CivilVoxelProperties` (surface pickers + lattice params +
  result fields), attached to ``bpy.types.Scene``.
- :mod:`operator` — preview cut/fill, preview single-surface occupancy, clear
  preview, author IFC 4.4 sidecar.
- :mod:`ui` — sub-panels under :class:`BIM_PT_tab_voxel_earthwork`
  (CIVIL > Voxel Earthwork).

Previews are disposable Blender cube meshes (cut = red, fill = blue, occupancy =
green) regenerated from the grid + masks; the IFC sidecar is the source of truth.
"""

import bpy

from . import operator, prop, ui

classes: tuple[type, ...] = (
    prop.CivilVoxelStratumItem,
    prop.CivilVoxelProperties,
    operator.CIVIL_OT_voxel_preview_cut_fill,
    operator.CIVIL_OT_voxel_cut_by_stratum,
    operator.CIVIL_OT_voxel_preview_surface,
    operator.CIVIL_OT_voxel_clear_preview,
    operator.CIVIL_OT_voxel_author_sidecar,
    operator.CIVIL_OT_voxel_preview_geomodel,
    operator.CIVIL_OT_voxel_author_geomodel,
    ui.CIVIL_PT_voxel_cut_fill,
    ui.CIVIL_PT_voxel_geomodel,
    ui.CIVIL_PT_voxel_single,
    ui.CIVIL_PT_voxel_sidecar,
)


def register() -> None:
    """Attach :class:`CivilVoxelProperties` to ``bpy.types.Scene``."""
    bpy.types.Scene.CivilVoxelProperties = bpy.props.PointerProperty(
        type=prop.CivilVoxelProperties
    )


def unregister() -> None:
    del bpy.types.Scene.CivilVoxelProperties

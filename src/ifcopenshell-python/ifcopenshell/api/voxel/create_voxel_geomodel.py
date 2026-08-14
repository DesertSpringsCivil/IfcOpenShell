# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2026 Michael Yoder <myoder@desertspringscivil.com>
#
# This file is part of IfcOpenShell.
#
# IfcOpenShell is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# IfcOpenShell is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with IfcOpenShell.  If not, see <http://www.gnu.org/licenses/>.

"""Top-level: create a voxel-bearing IfcGeomodel (stratum mode) in a sidecar."""

from __future__ import annotations

from typing import Optional, Sequence

import ifcopenshell
import ifcopenshell.guid

from .add_voxel_grid import add_voxel_grid_representation
from .create_voxel_earthwork import _contain_in_site

#: Description tokens recording cross-file source surfaces + the stratum legend.
SOURCE_PREFIX = "voxelized-from:"
LEGEND_PREFIX = "strata:"


def create_voxel_geomodel(
    file: ifcopenshell.file,
    *,
    name: str,
    voxel_sizes: Sequence[float],
    voxel_counts: Sequence[int],
    occupancy: Sequence[int],
    source_surface_guids: Optional[Sequence[str]] = None,
    legend: Optional[dict] = None,
) -> ifcopenshell.entity_instance:
    """Create an :class:`IfcGeomodel` carrying a voxel occupancy grid.

    The geotech counterpart of :func:`create_voxel_earthwork`: a single
    ``IfcGeomodel`` host (no ``PredefinedType`` — geotech leaves lack one) with
    an :class:`IfcVoxelGrid` body. Stratum classification is added afterward as
    an ``IfcIntegerVoxelData`` layer (:func:`add_voxel_data`).

    The code→material ``legend`` and the production source-surface GlobalIds are
    recorded on ``Description`` (``"voxelized-from:… | strata:1=Clay;2=Sand"``)
    via direct attribute assignment — Pset value-wrappers crash the runtime-
    registered prototype schema (finding F3).

    :param occupancy: RLE integer run-pair stream (occupied = code > 0 cells).
    :param legend: ``{code: material_name}`` (codes are 1-based stratum indices).
    :returns: the created :class:`IfcGeomodel`.
    """
    host = file.create_entity("IfcGeomodel", GlobalId=ifcopenshell.guid.new(), Name=name)
    _contain_in_site(file, host)
    add_voxel_grid_representation(
        file, host, voxel_sizes=voxel_sizes, voxel_counts=voxel_counts, occupancy=occupancy
    )

    parts = []
    if source_surface_guids:
        parts.append(SOURCE_PREFIX + ",".join(source_surface_guids))
    if legend:
        parts.append(LEGEND_PREFIX + ";".join(f"{code}={material}" for code, material in legend.items()))
    if parts:
        host.Description = " | ".join(parts)
    return host

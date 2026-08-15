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

"""Top-level: create a voxel-bearing earthwork element in a sidecar file."""

from __future__ import annotations

from typing import Optional, Sequence

import ifcopenshell
import ifcopenshell.guid

from .add_voxel_grid import add_voxel_grid_representation

#: Allowed host classes for a voxel earthwork volume.
_HOST_CLASSES = ("IfcEarthworksCut", "IfcEarthworksFill")

#: Description prefix recording the production-model source surface (cross-file link).
SOURCE_PREFIX = "voxelized-from:"


def _contain_in_site(file: ifcopenshell.file, product: ifcopenshell.entity_instance) -> None:
    """Contain ``product`` in the first IfcSite via IfcRelContainedInSpatialStructure (if any)."""
    sites = file.by_type("IfcSite")
    if not sites:
        return
    file.create_entity(
        "IfcRelContainedInSpatialStructure",
        GlobalId=ifcopenshell.guid.new(),
        RelatedElements=[product],
        RelatingStructure=sites[0],
    )


def _attach_source_reference(
    product: ifcopenshell.entity_instance, source_surface_guid: str
) -> None:
    """Record the production surface GlobalId on ``product.Description`` for
    cross-file linkage (``"voxelized-from:<guid>"``).

    The sidecar is IFC 4.4; the production model is IFC4X3_ADD2. This GlobalId is
    the cross-file pointer back to the production ``IfcGeographicElement`` /
    ``IfcEarthworksFill`` surface the grid was voxelized from.

    NOTE: this uses a direct attribute assignment rather than a Pset, because the
    runtime-registered prototype schema crashes (access violation) when creating
    a standalone defined-type value wrapper (e.g. ``IfcIdentifier``) for a
    property ``NominalValue``. Direct attribute writes (auto-wrapped) are safe.
    Promote to a proper ``SaikeiCivil_VoxelSource`` once authoring against a
    real built IFC 4.4 schema.
    """
    product.Description = f"{SOURCE_PREFIX}{source_surface_guid}"


def create_voxel_earthwork(
    file: ifcopenshell.file,
    *,
    name: str,
    voxel_sizes: Sequence[float],
    voxel_counts: Sequence[int],
    occupancy: Sequence[int],
    host_class: str = "IfcEarthworksCut",
    predefined_type: str = "EXCAVATION",
    source_surface_guid: Optional[str] = None,
) -> tuple[ifcopenshell.entity_instance, ifcopenshell.entity_instance]:
    """Create an earthwork host carrying an :class:`IfcVoxelGrid` occupancy body.

    The single top-level call for the common case: mint an
    ``IfcEarthworksCut`` / ``IfcEarthworksFill``, contain it in the sidecar's
    site, attach the RLE occupancy grid, and (optionally) record the production
    surface it derives from. Semantic layers are added afterward with
    :func:`add_voxel_data`.

    :param occupancy: RLE integer run-pair stream (see
        :func:`add_voxel_grid_representation`).
    :param host_class: ``IfcEarthworksCut`` (excavation) or ``IfcEarthworksFill``
        (embankment).
    :param predefined_type: the host's ``PredefinedType`` (e.g. ``EXCAVATION``
        for a cut, ``EMBANKMENT`` for a fill).
    :param source_surface_guid: optional production-model surface GlobalId,
        recorded on ``host.Description`` (``"voxelized-from:<guid>"``) for
        cross-file linkage.
    :returns: ``(host, grid)``.
    :raises ValueError: on an unknown ``host_class`` (grid validation is
        delegated to :func:`add_voxel_grid_representation`).
    """
    if host_class not in _HOST_CLASSES:
        raise ValueError(f"host_class must be one of {_HOST_CLASSES}, got {host_class!r}")

    host = file.create_entity(
        host_class,
        GlobalId=ifcopenshell.guid.new(),
        Name=name,
        PredefinedType=predefined_type,
    )
    _contain_in_site(file, host)
    grid = add_voxel_grid_representation(
        file,
        host,
        voxel_sizes=voxel_sizes,
        voxel_counts=voxel_counts,
        occupancy=occupancy,
    )
    if source_surface_guid is not None:
        _attach_source_reference(host, source_surface_guid)
    return host, grid

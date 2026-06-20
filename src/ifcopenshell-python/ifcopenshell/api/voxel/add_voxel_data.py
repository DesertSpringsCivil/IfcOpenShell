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

"""Author an IfcVoxelData payload layer assigned to a voxel-grid host product."""

from __future__ import annotations

from typing import Optional, Sequence

import ifcopenshell
import ifcopenshell.guid

#: Maps a payload ``data_type`` to its concrete ``IfcVoxelData`` subtype.
VOXEL_DATA_SUBTYPES = {
    "integer": "IfcIntegerVoxelData",
    "real": "IfcRealVoxelData",
    "label": "IfcLabelVoxelData",
    "logical": "IfcLogicalVoxelData",
    "vector": "IfcVectorVoxelData",
}

#: Subtypes that carry an optional ``Unit``.
_UNIT_BEARING = {"integer", "real", "vector"}


def _grid_representation(product: ifcopenshell.entity_instance) -> ifcopenshell.entity_instance:
    """Return the host's IfcShapeRepresentation whose single item is an IfcVoxelGrid."""
    shape = product.Representation
    if shape is None or not shape.is_a("IfcProductDefinitionShape"):
        raise ValueError(
            f"host {product.is_a()} #{product.id()} has no IfcProductDefinitionShape; "
            "author the voxel grid (add_voxel_grid_representation) first"
        )
    for rep in shape.Representations or []:
        items = rep.Items or []
        if rep.is_a("IfcShapeRepresentation") and len(items) == 1 and items[0].is_a("IfcVoxelGrid"):
            return rep
    raise ValueError(
        f"host {product.is_a()} #{product.id()} has no IfcVoxelGrid representation; "
        "author the voxel grid first"
    )


def add_voxel_data(
    file: ifcopenshell.file,
    product: ifcopenshell.entity_instance,
    *,
    value_data: Sequence,
    data_type: str,
    value_type: Optional[str] = None,
    unit: Optional[ifcopenshell.entity_instance] = None,
    name: Optional[str] = None,
) -> ifcopenshell.entity_instance:
    """Author one :class:`IfcVoxelData` semantic layer on a voxel-grid host.

    One attribute per layer (TM27 design): material, density, confidence, etc.
    each get their own ``IfcVoxelData`` sharing the host's single
    ``IfcVoxelGrid`` representation. The layer is assigned to ``product`` via
    ``IfcRelAssignsToProduct`` (TM27 ``IsAssignedToProduct`` rule) and carries
    the same product-definition shape (``SameRepresentation`` rule) — both
    honored here by construction (the runtime-registered schema does not execute
    WHERE rules).

    ``value_data`` is *persisted as given*: in occupancy mode it is the gathered
    values over occupied cells, RLE-encoded as the caller sees fit; the caller
    owns the encoding (this layer does not RLE-encode).

    :param value_data: the ``ValueData`` list (element type must match
        ``data_type`` — int / float / str / logical / vector components).
    :param data_type: one of ``integer`` / ``real`` / ``label`` / ``logical`` /
        ``vector`` (selects the ``IfcVoxelData`` subtype).
    :param value_type: optional ``ValueType`` label naming the ``IfcValue``
        select-type used.
    :param unit: optional ``IfcUnit`` (only for ``integer`` / ``real`` /
        ``vector``; ignored otherwise with a :class:`ValueError` if misused).
    :param name: optional human-readable layer name.
    :returns: the created ``IfcVoxelData`` subtype instance.
    :raises ValueError: on an unknown ``data_type``, a unit on a non-unit-bearing
        type, or a host without a voxel-grid representation.
    """
    if data_type not in VOXEL_DATA_SUBTYPES:
        raise ValueError(
            f"data_type must be one of {sorted(VOXEL_DATA_SUBTYPES)}, got {data_type!r}"
        )
    if unit is not None and data_type not in _UNIT_BEARING:
        raise ValueError(f"{data_type!r} voxel data does not carry a Unit")

    # Ensure the grid representation exists; share the host's product shape.
    _grid_representation(product)

    attributes = {
        "GlobalId": ifcopenshell.guid.new(),
        "Name": name,
        "Representation": product.Representation,
        "ValueData": list(value_data),
    }
    if value_type is not None:
        attributes["ValueType"] = value_type
    if data_type in _UNIT_BEARING and unit is not None:
        attributes["Unit"] = unit

    voxel_data = file.create_entity(VOXEL_DATA_SUBTYPES[data_type], **attributes)
    file.create_entity(
        "IfcRelAssignsToProduct",
        GlobalId=ifcopenshell.guid.new(),
        RelatedObjects=[voxel_data],
        RelatingProduct=product,
    )
    return voxel_data

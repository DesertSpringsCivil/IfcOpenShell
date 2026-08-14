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

"""Author an IfcVoxelGrid Body/Tessellation representation on a product."""

from __future__ import annotations

from typing import Optional, Sequence

import ifcopenshell

from ._schema import get_model_context


def get_or_create_product_definition_shape(
    file: ifcopenshell.file, product: ifcopenshell.entity_instance
) -> ifcopenshell.entity_instance:
    """Return the product's IfcProductDefinitionShape, creating one if absent."""
    shape = product.Representation
    if shape is not None and shape.is_a("IfcProductDefinitionShape"):
        return shape
    shape = file.create_entity("IfcProductDefinitionShape", Representations=[])
    product.Representation = shape
    return shape


def add_voxel_grid_representation(
    file: ifcopenshell.file,
    product: ifcopenshell.entity_instance,
    *,
    voxel_sizes: Sequence[float],
    voxel_counts: Sequence[int],
    occupancy: Sequence[int],
    context: Optional[ifcopenshell.entity_instance] = None,
) -> ifcopenshell.entity_instance:
    """Attach an :class:`IfcVoxelGrid` ``Body`` / ``Tessellation`` representation to ``product``.

    The grid's ``Voxels`` is the Saikei RLE integer run-pair occupancy stream
    (``[count, value, count, value, …]``; value ``1`` = occupied), as produced
    by :meth:`bonsai.tool.Voxel.encode_occupancy`. This function *persists what
    it is given* — it does not RLE-encode or validate occupancy semantics; the
    caller owns the encoding (mirrors how ``ifcopenshell.api.earthwork`` persists
    pre-built solids).

    Per TM27 the grid carries no placement of its own; origin/orientation come
    from ``product.ObjectPlacement``. The lattice's min-corner origin
    (:attr:`bonsai.tool.voxel.GridDef.origin`) maps to that placement and is not
    stored on the grid.

    :param voxel_sizes: ``(sx, sy, sz)`` cell sizes (``VoxelSize{X,Y,Z}``); all > 0.
    :param voxel_counts: ``(nx, ny, nz)`` cell counts (``NumberOfVoxels{X,Y,Z}``); all >= 1.
    :param occupancy: flat RLE integer stream for ``Voxels``; even length (whole
        ``(count, value)`` runs).
    :param context: the ``IfcGeometricRepresentationContext`` to author into;
        defaults to the file's ``Model`` context.
    :returns: the created :class:`IfcVoxelGrid`.
    :raises ValueError: if sizes/counts are out of range, the occupancy stream
        has odd length, or the product already has a Body representation.
    """
    sizes = [float(s) for s in voxel_sizes]
    counts = [int(c) for c in voxel_counts]
    voxels = [int(v) for v in occupancy]
    if len(sizes) != 3 or len(counts) != 3:
        raise ValueError("voxel_sizes and voxel_counts must each have 3 components")
    if any(s <= 0 for s in sizes):
        raise ValueError(f"voxel sizes must be > 0, got {sizes}")
    if any(c < 1 for c in counts):
        raise ValueError(f"voxel counts must be >= 1, got {counts}")
    if len(voxels) % 2 != 0:
        raise ValueError(
            f"occupancy must be an RLE (count, value) stream of even length; got {len(voxels)}"
        )

    ctx = context or get_model_context(file)
    shape = get_or_create_product_definition_shape(file, product)
    for existing in shape.Representations or []:
        if existing.is_a("IfcShapeRepresentation") and existing.RepresentationIdentifier == "Body":
            raise ValueError(
                f"product {product.is_a()} #{product.id()} already has a Body "
                "representation; remove it before authoring a voxel grid"
            )

    grid = file.create_entity(
        "IfcVoxelGrid",
        VoxelSizeX=sizes[0],
        VoxelSizeY=sizes[1],
        VoxelSizeZ=sizes[2],
        NumberOfVoxelsX=counts[0],
        NumberOfVoxelsY=counts[1],
        NumberOfVoxelsZ=counts[2],
        Voxels=voxels,
    )
    representation = file.create_entity(
        "IfcShapeRepresentation",
        ContextOfItems=ctx,
        RepresentationIdentifier="Body",
        RepresentationType="Tessellation",
        Items=[grid],
    )
    shape.Representations = list(shape.Representations or []) + [representation]
    return grid

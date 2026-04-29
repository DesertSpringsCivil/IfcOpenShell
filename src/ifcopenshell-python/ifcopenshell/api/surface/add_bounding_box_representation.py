# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2026 Desert Springs Civil Engineering PLLC
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

"""Author an IfcBoundingBox LOD representation under a host product."""

from __future__ import annotations

import ifcopenshell

from ._representation_context import get_box_subcontext
from .add_tin_representation import _get_or_create_product_definition_shape


def add_bounding_box_representation(
    file: ifcopenshell.file,
    product: ifcopenshell.entity_instance,
    min_xyz: tuple[float, float, float],
    max_xyz: tuple[float, float, float],
) -> ifcopenshell.entity_instance:
    """Attach an IfcBoundingBox representation to ``product.Representation`` as a Box LOD.

    Creates an :class:`IfcBoundingBox` anchored at ``min_xyz`` with positive
    dimensions ``max_xyz - min_xyz``, wraps it in an
    :class:`IfcShapeRepresentation` with ``RepresentationIdentifier='Box'`` and
    ``RepresentationType='BoundingBox'``, and appends the shape representation
    to the product's :class:`IfcProductDefinitionShape`.

    :param file: the IFC file to author into
    :param product: any :class:`IfcProduct` host
    :param min_xyz: the (x, y, z) corner closer to the origin
    :param max_xyz: the (x, y, z) corner farther from the origin; must be strictly
        greater than ``min_xyz`` in every axis (IFC requires positive dimensions)
    :returns: the created :class:`IfcBoundingBox` entity
    :raises ValueError: if any axis of ``max_xyz`` is not strictly greater than
        ``min_xyz``, or if the product already has a Box representation
    """
    x_dim = float(max_xyz[0]) - float(min_xyz[0])
    y_dim = float(max_xyz[1]) - float(min_xyz[1])
    z_dim = float(max_xyz[2]) - float(min_xyz[2])
    if x_dim <= 0 or y_dim <= 0 or z_dim <= 0:
        raise ValueError(
            f"max_xyz must be strictly greater than min_xyz on every axis "
            f"(got dims x={x_dim}, y={y_dim}, z={z_dim})"
        )

    shape = _get_or_create_product_definition_shape(file, product)
    for existing in shape.Representations:
        if existing.is_a("IfcShapeRepresentation") and existing.RepresentationIdentifier == "Box":
            raise ValueError(
                f"product {product.is_a()} #{product.id()} already has a Box representation"
            )

    corner = file.create_entity(
        "IfcCartesianPoint",
        Coordinates=(float(min_xyz[0]), float(min_xyz[1]), float(min_xyz[2])),
    )
    box = file.create_entity(
        "IfcBoundingBox",
        Corner=corner,
        XDim=x_dim,
        YDim=y_dim,
        ZDim=z_dim,
    )
    representation = file.create_entity(
        "IfcShapeRepresentation",
        ContextOfItems=get_box_subcontext(file),
        RepresentationIdentifier="Box",
        RepresentationType="BoundingBox",
        Items=[box],
    )
    shape.Representations = list(shape.Representations) + [representation]
    return box

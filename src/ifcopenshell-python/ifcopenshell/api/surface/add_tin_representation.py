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

"""Author an IfcTriangulatedIrregularNetwork representation under a host product."""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence, Union

import ifcopenshell

from ._representation_context import get_surface_model_subcontext

if TYPE_CHECKING:
    import numpy as np

    PointArray = Union[np.ndarray, Sequence[Sequence[float]]]
    TriangleArray = Union[np.ndarray, Sequence[Sequence[int]]]
    FlagArray = Union[np.ndarray, Sequence[int], None]


def _to_point_list(points: "PointArray") -> list[tuple[float, float, float]]:
    """Coerce a (N, 3) numpy array or list of triples to a list of float tuples."""
    return [(float(p[0]), float(p[1]), float(p[2])) for p in points]


def _to_one_based_triangles(triangles: "TriangleArray", point_count: int) -> list[tuple[int, int, int]]:
    """Coerce 0-based (M, 3) triangle indices to 1-based int tuples; validate range."""
    out: list[tuple[int, int, int]] = []
    for triangle in triangles:
        a, b, c = int(triangle[0]), int(triangle[1]), int(triangle[2])
        if a < 0 or b < 0 or c < 0 or a >= point_count or b >= point_count or c >= point_count:
            raise ValueError(
                f"Triangle vertex index out of range for points array of length {point_count}: "
                f"({a}, {b}, {c})"
            )
        out.append((a + 1, b + 1, c + 1))
    return out


def _to_flag_list(triangle_flags: "FlagArray", triangle_count: int) -> list[int]:
    """Coerce per-triangle flags to a list of ints; default to zeros if None."""
    if triangle_flags is None:
        return [0] * triangle_count
    flags = [int(f) for f in triangle_flags]
    if len(flags) != triangle_count:
        raise ValueError(
            f"triangle_flags length {len(flags)} does not match triangle count {triangle_count}"
        )
    return flags


def _get_or_create_product_definition_shape(
    file: ifcopenshell.file, product: ifcopenshell.entity_instance
) -> ifcopenshell.entity_instance:
    """Return the product's IfcProductDefinitionShape, creating one if absent."""
    shape = product.Representation
    if shape is not None and shape.is_a("IfcProductDefinitionShape"):
        return shape
    shape = file.create_entity("IfcProductDefinitionShape", Representations=[])
    product.Representation = shape
    return shape


def add_tin_representation(
    file: ifcopenshell.file,
    product: ifcopenshell.entity_instance,
    points: "PointArray",
    triangles: "TriangleArray",
    triangle_flags: "FlagArray" = None,
) -> ifcopenshell.entity_instance:
    """Attach an IfcTriangulatedIrregularNetwork to ``product.Representation`` as a SurfaceModel.

    Creates an :class:`IfcCartesianPointList3D`, an
    :class:`IfcTriangulatedIrregularNetwork` with 1-based ``CoordIndex`` and a
    per-triangle ``Flags`` list, wraps them in an :class:`IfcShapeRepresentation`
    with ``RepresentationIdentifier='SurfaceModel'`` and
    ``RepresentationType='Tessellation'``, and appends the shape representation
    to the product's :class:`IfcProductDefinitionShape`.

    If the product has no ``ProductDefinitionShape``, one is created. If a
    ``SurfaceModel`` representation is already present, ``ValueError`` is
    raised — use :func:`update_tin_representation` to replace it.

    :param file: the IFC file to author into
    :param product: any :class:`IfcProduct` host (typically an IfcGeographicElement
        or IfcEarthworksFill)
    :param points: ``(N, 3)`` array of XYZ coordinates in project coordinates
    :param triangles: ``(M, 3)`` array of 0-based vertex indices, counterclockwise
        from above
    :param triangle_flags: optional ``(M,)`` array of IFC ``Flags`` integers; defaults
        to all zeros
    :returns: the created :class:`IfcTriangulatedIrregularNetwork` entity
    :raises ValueError: if ``points`` or ``triangles`` are empty, if any triangle index
        is out of range, or if the product already has a SurfaceModel representation
    """
    point_list = _to_point_list(points)
    if not point_list:
        raise ValueError("points must not be empty")
    triangle_list = _to_one_based_triangles(triangles, len(point_list))
    if not triangle_list:
        raise ValueError("triangles must not be empty")
    flag_list = _to_flag_list(triangle_flags, len(triangle_list))

    shape = _get_or_create_product_definition_shape(file, product)
    for existing in shape.Representations:
        if existing.is_a("IfcShapeRepresentation") and existing.RepresentationIdentifier == "SurfaceModel":
            raise ValueError(
                f"product {product.is_a()} #{product.id()} already has a SurfaceModel "
                "representation; use update_tin_representation instead"
            )

    coord_list = file.create_entity("IfcCartesianPointList3D", CoordList=point_list)
    tin = file.create_entity(
        "IfcTriangulatedIrregularNetwork",
        Coordinates=coord_list,
        Closed=False,
        CoordIndex=triangle_list,
        Flags=flag_list,
    )
    representation = file.create_entity(
        "IfcShapeRepresentation",
        ContextOfItems=get_surface_model_subcontext(file),
        RepresentationIdentifier="SurfaceModel",
        RepresentationType="Tessellation",
        Items=[tin],
    )
    shape.Representations = list(shape.Representations) + [representation]
    return tin

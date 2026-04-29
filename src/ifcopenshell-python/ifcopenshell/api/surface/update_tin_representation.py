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

"""Replace the existing SurfaceModel TIN on a host product with a new one."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import ifcopenshell

from .add_tin_representation import (
    _to_flag_list,
    _to_one_based_triangles,
    _to_point_list,
)

if TYPE_CHECKING:
    from .add_tin_representation import FlagArray, PointArray, TriangleArray


def _find_surface_model_rep(
    product: ifcopenshell.entity_instance,
) -> Optional[ifcopenshell.entity_instance]:
    """Return the host's IfcShapeRepresentation with RepresentationIdentifier='SurfaceModel', or None."""
    representation = product.Representation
    if representation is None:
        return None
    for shape_rep in representation.Representations or []:
        if (
            shape_rep.is_a("IfcShapeRepresentation")
            and shape_rep.RepresentationIdentifier == "SurfaceModel"
        ):
            return shape_rep
    return None


def _gc_if_orphaned(file: ifcopenshell.file, entity: ifcopenshell.entity_instance) -> bool:
    """Remove ``entity`` from ``file`` iff no other entity still references it. Returns True if removed."""
    if any(file.get_inverse(entity)):
        return False
    file.remove(entity)
    return True


def update_tin_representation(
    file: ifcopenshell.file,
    product: ifcopenshell.entity_instance,
    points: "PointArray",
    triangles: "TriangleArray",
    triangle_flags: "FlagArray" = None,
) -> ifcopenshell.entity_instance:
    """Replace the existing SurfaceModel TIN on ``product`` with a freshly built one.

    Used by retriangulation, breakline-add, and boundary-edit flows. The
    function looks up the host's existing ``SurfaceModel`` representation,
    creates a new :class:`IfcCartesianPointList3D` and
    :class:`IfcTriangulatedIrregularNetwork` from the supplied data, swaps the
    representation's ``Items`` to point at the new TIN, and then removes the
    old TIN and its CoordList — but only if they have no other inverse
    references in the file (i.e., nothing else was sharing them).

    The :class:`IfcShapeRepresentation` itself is preserved, so any other
    references to it (e.g., from the host's :class:`IfcProductDefinitionShape`)
    remain valid.

    :param file: the IFC file to author into
    :param product: the host product whose SurfaceModel rep is being updated
    :param points: ``(N, 3)`` array of XYZ coordinates in project coordinates
    :param triangles: ``(M, 3)`` 0-based vertex indices, counterclockwise from above
    :param triangle_flags: optional per-triangle IFC ``Flags`` integers; defaults
        to all zeros
    :returns: the newly created :class:`IfcTriangulatedIrregularNetwork`
    :raises ValueError: if ``points`` or ``triangles`` are empty, if any triangle
        index is out of range, or if the product has no existing SurfaceModel rep
    """
    point_list = _to_point_list(points)
    if not point_list:
        raise ValueError("points must not be empty")
    triangle_list = _to_one_based_triangles(triangles, len(point_list))
    if not triangle_list:
        raise ValueError("triangles must not be empty")
    flag_list = _to_flag_list(triangle_flags, len(triangle_list))

    shape_rep = _find_surface_model_rep(product)
    if shape_rep is None:
        raise ValueError(
            f"product {product.is_a()} #{product.id()} has no SurfaceModel "
            "representation; use add_tin_representation to create one"
        )

    old_tins = [item for item in shape_rep.Items or [] if item.is_a("IfcTriangulatedIrregularNetwork")]
    other_items = [item for item in shape_rep.Items or [] if not item.is_a("IfcTriangulatedIrregularNetwork")]

    new_coord_list = file.create_entity("IfcCartesianPointList3D", CoordList=point_list)
    new_tin = file.create_entity(
        "IfcTriangulatedIrregularNetwork",
        Coordinates=new_coord_list,
        Closed=False,
        CoordIndex=triangle_list,
        Flags=flag_list,
    )
    shape_rep.Items = other_items + [new_tin]

    for old_tin in old_tins:
        old_coord_list = old_tin.Coordinates
        if _gc_if_orphaned(file, old_tin):
            _gc_if_orphaned(file, old_coord_list)

    return new_tin

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

"""Author an IfcPolygonalFaceSet (Closed=TRUE) Body/Tessellation solid representation."""

from __future__ import annotations

from typing import Sequence

import ifcopenshell
import ifcopenshell.api.context
import ifcopenshell.util.representation
from ifcopenshell.api.grading._shared import to_point_list


def _get_or_create_body_subcontext(
    file: ifcopenshell.file,
) -> ifcopenshell.entity_instance:
    """Return Model/Body/MODEL_VIEW subcontext, creating both it and parent Model if absent.

    Mirrors the pattern in ``ifcopenshell.api.surface._representation_context``
    but inlined here to avoid extending the cross-package private-import web.
    """
    sub = ifcopenshell.util.representation.get_context(file, "Model", "Body", "MODEL_VIEW")
    if sub is not None:
        return sub
    parent = ifcopenshell.util.representation.get_context(file, "Model")
    if parent is None:
        parent = ifcopenshell.api.context.add_context(file, context_type="Model")
    return ifcopenshell.api.context.add_context(
        file,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=parent,
    )


def _to_one_based_face_indices(
    faces: Sequence[Sequence[int]], point_count: int
) -> list[list[int]]:
    """Coerce 0-based face vertex-index lists to 1-based; validate range and arity."""
    out: list[list[int]] = []
    for face_index, face in enumerate(faces):
        face_list = list(face)
        if len(face_list) < 3:
            raise ValueError(
                f"face {face_index} has {len(face_list)} vertices; "
                "IfcIndexedPolygonalFace requires at least 3"
            )
        coerced: list[int] = []
        for vertex_index in face_list:
            v = int(vertex_index)
            if v < 0 or v >= point_count:
                raise ValueError(
                    f"face {face_index} references vertex index {v} outside the "
                    f"points array of length {point_count}"
                )
            coerced.append(v + 1)
        out.append(coerced)
    return out


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


def add_volume_solid_representation(
    file: ifcopenshell.file,
    product: ifcopenshell.entity_instance,
    points: Sequence[Sequence[float]],
    faces: Sequence[Sequence[int]],
    *,
    closed: bool = True,
) -> ifcopenshell.entity_instance:
    """Attach an :class:`IfcPolygonalFaceSet` Body/Tessellation representation to ``product``.

    Per spec §2.4 + v3.2.3 changelog, the canonical ``RepresentationType`` is
    ``"Tessellation"`` — :class:`IfcPolygonalFaceSet` is a tessellated face
    set even when ``Closed=TRUE``. ``RepresentationIdentifier="Body"``.

    Faces are passed as a sequence of vertex-index lists (variable per-face
    vertex count; the IFC schema admits arbitrary polygons of degree 3+, not
    just triangles). Indices are 0-based on the API surface; converted to
    IFC's 1-based convention internally.

    The product must not already carry a Body representation — re-authoring
    is rejected with :class:`ValueError`. Phase 6 cascade-rebuild flows that
    need to replace a closed solid in place should remove the existing Body
    rep and call this again.

    The function does **not** verify watertightness, manifold topology, or
    signed-volume agreement (spec §6.5 stages 1–4). Those checks live in
    Bonsai's ``tool.Earthwork`` and run before the API is called.

    :param file: the IFC file to author into
    :param product: the host :class:`IfcProduct` (typically
        :class:`IfcEarthworksCut` or :class:`IfcEarthworksFill`)
    :param points: ``(N, 3)`` array of XYZ coordinates
    :param faces: list of vertex-index lists; each list is one polygonal face
        (3+ vertices, counterclockwise from outside per IFC right-hand rule)
    :param closed: stored on :class:`IfcPolygonalFaceSet.Closed`; defaults to
        ``True`` for volume solids
    :returns: the created :class:`IfcPolygonalFaceSet`
    :raises ValueError: if ``points`` or ``faces`` are empty, any face has
        fewer than 3 vertices, any face references an out-of-range vertex
        index, or the product already has a Body representation
    """
    point_list = to_point_list(points)
    if not point_list:
        raise ValueError("points must not be empty")
    if not faces:
        raise ValueError("faces must not be empty")
    one_based_faces = _to_one_based_face_indices(faces, len(point_list))

    shape = _get_or_create_product_definition_shape(file, product)
    for existing in shape.Representations:
        if (
            existing.is_a("IfcShapeRepresentation")
            and existing.RepresentationIdentifier == "Body"
        ):
            raise ValueError(
                f"product {product.is_a()} #{product.id()} already has a Body "
                "representation; remove it first to author a new closed solid"
            )

    coord_list = file.create_entity("IfcCartesianPointList3D", CoordList=point_list)
    face_entities = [
        file.create_entity("IfcIndexedPolygonalFace", CoordIndex=face)
        for face in one_based_faces
    ]
    face_set = file.create_entity(
        "IfcPolygonalFaceSet",
        Coordinates=coord_list,
        Closed=bool(closed),
        Faces=face_entities,
    )
    representation = file.create_entity(
        "IfcShapeRepresentation",
        ContextOfItems=_get_or_create_body_subcontext(file),
        RepresentationIdentifier="Body",
        RepresentationType="Tessellation",
        Items=[face_set],
    )
    shape.Representations = list(shape.Representations) + [representation]
    return face_set

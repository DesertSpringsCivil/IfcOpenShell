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

"""Persist a breakline as a separate IfcAnnotation entity with IfcPolyline geometry."""

from __future__ import annotations

from typing import Optional, Sequence

import ifcopenshell
import ifcopenshell.api.pset
import ifcopenshell.api.spatial
import ifcopenshell.guid

from ._representation_context import get_annotation_subcontext

PSET_NAME = "Pset_SaikeiBreaklineCommon"
ALLOWED_KINDS = frozenset({"standard", "wall", "non_destructive", "proximity"})


def add_breakline_annotation(
    file: ifcopenshell.file,
    site: ifcopenshell.entity_instance,
    polyline: Sequence[Sequence[float]],
    name: str,
    kind: str = "standard",
    source: str = "manual",
    grading_group_guid: Optional[str] = None,
) -> ifcopenshell.entity_instance:
    """Persist a breakline as a separate :class:`IfcAnnotation` entity.

    Breaklines are stored as annotations rather than as part of any TIN's
    representation so they survive retriangulation. The TIN's per-triangle
    ``Flags`` list (authored via :func:`add_tin_representation`) independently
    encodes which triangles touch which breaklines for query purposes.

    The annotation is contained in :class:`IfcSite` via
    :func:`ifcopenshell.api.spatial.assign_container`. It uses
    ``PredefinedType=USERDEFINED`` with ``ObjectType="BREAKLINE"`` since the
    standard ``IfcAnnotationTypeEnum`` has no first-class breakline value. A
    ``Pset_SaikeiBreaklineCommon`` is attached carrying ``Kind``, ``Source``,
    and (when provided) ``GradingGroupGuid``.

    :param file: the IFC file to author into
    :param site: the :class:`IfcSite` to contain the annotation
    :param polyline: an ordered sequence of ``(x, y, z)`` points; at least two
        are required to form a polyline
    :param name: human-readable name (stored on ``IfcAnnotation.Name``)
    :param kind: one of ``"standard"``, ``"wall"``, ``"non_destructive"``,
        ``"proximity"``
    :param source: free-form provenance label (default ``"manual"``)
    :param grading_group_guid: optional GUID of the grading group whose
        retriangulation this breakline participates in
    :returns: the created :class:`IfcAnnotation`
    :raises ValueError: if ``polyline`` has fewer than two points or ``kind``
        is not one of the allowed values
    """
    points = [(float(p[0]), float(p[1]), float(p[2])) for p in polyline]
    if len(points) < 2:
        raise ValueError("polyline must have at least two points")
    if kind not in ALLOWED_KINDS:
        raise ValueError(
            f"kind must be one of {sorted(ALLOWED_KINDS)}, got {kind!r}"
        )

    annotation = file.create_entity(
        "IfcAnnotation",
        GlobalId=ifcopenshell.guid.new(),
        Name=name,
        ObjectType="BREAKLINE",
        PredefinedType="USERDEFINED",
    )
    ifcopenshell.api.spatial.assign_container(
        file, products=[annotation], relating_structure=site
    )

    cartesian_points = [
        file.create_entity("IfcCartesianPoint", Coordinates=p) for p in points
    ]
    polyline_entity = file.create_entity("IfcPolyline", Points=cartesian_points)
    representation = file.create_entity(
        "IfcShapeRepresentation",
        ContextOfItems=get_annotation_subcontext(file),
        RepresentationIdentifier="Annotation",
        RepresentationType="Curve3D",
        Items=[polyline_entity],
    )
    annotation.Representation = file.create_entity(
        "IfcProductDefinitionShape", Representations=[representation]
    )

    properties: dict[str, object] = {"Kind": kind, "Source": source}
    if grading_group_guid is not None:
        properties["GradingGroupGuid"] = grading_group_guid
    pset = ifcopenshell.api.pset.add_pset(file, product=annotation, name=PSET_NAME)
    ifcopenshell.api.pset.edit_pset(file, pset=pset, properties=properties)

    return annotation

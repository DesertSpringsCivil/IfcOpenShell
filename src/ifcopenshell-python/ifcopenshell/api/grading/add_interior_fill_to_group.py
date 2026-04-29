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

"""Author an IfcEarthworksFill[SUBGRADE] interior fill under a grading group."""

from __future__ import annotations

from typing import TYPE_CHECKING

import ifcopenshell
import ifcopenshell.api.surface
import ifcopenshell.guid

from ._shared import (
    aggregate_under,
    apply_omniclass_classification,
    attach_earthworks_fill_common,
    compute_bounding_box,
    identity_placement,
    to_point_list,
)
from .add_member_to_group import add_member_to_group

if TYPE_CHECKING:
    from ifcopenshell.api.surface.add_tin_representation import (
        FlagArray,
        PointArray,
        TriangleArray,
    )

INTERIOR_FILL_OMNICLASS_CODE = "22-07 31 16"
INTERIOR_FILL_OMNICLASS_TITLE = "Excavation and Fill"


def _existing_interior_fill_under(
    composite_fill: ifcopenshell.entity_instance,
) -> ifcopenshell.entity_instance | None:
    """Return the SUBGRADE child of composite_fill, or None if none exists yet."""
    for rel in composite_fill.IsDecomposedBy or []:
        if not rel.is_a("IfcRelAggregates"):
            continue
        for child in rel.RelatedObjects:
            if child.is_a("IfcEarthworksFill") and child.PredefinedType == "SUBGRADE":
                return child
    return None


def add_interior_fill_to_group(
    file: ifcopenshell.file,
    group: ifcopenshell.entity_instance,
    composite_fill: ifcopenshell.entity_instance,
    *,
    name: str,
    points: "PointArray",
    triangles: "TriangleArray",
    triangle_flags: "FlagArray" = None,
) -> ifcopenshell.entity_instance:
    """Author an :class:`IfcEarthworksFill` with ``PredefinedType=SUBGRADE`` under a grading group.

    The interior fill is the floor of the pad / pond / infield area enclosed
    by the grading group's feature lines — the geometric realisation of the
    group's chosen ``interior_fill`` strategy (``flat`` /
    ``interpolate_from_boundary`` / ``from_surface``). One per group;
    callers using ``interior_fill="none"`` should not call this function.

    The shape mirrors :func:`add_slope_fill_to_group`, but with
    ``PredefinedType=SUBGRADE`` and the OmniClass Table 22 code
    ``22-07 31 16`` (Excavation and Fill, the standard takeoff code for
    pad subgrade). A second interior fill on the same group raises
    ``ValueError`` — re-grading the interior should update the existing
    fill via Phase 5 rebuild flows, not duplicate it.

    Wiring (identical to slope fill):

    - SurfaceModel TIN representation (via Phase 1
      :func:`ifcopenshell.api.surface.add_tin_representation`)
    - Box LOD representation (via
      :func:`ifcopenshell.api.surface.add_bounding_box_representation`)
    - Standard ``Pset_EarthworksFillCommon`` (``Status="NEW"``)
    - OmniClass Table 22 classification
    - :class:`IfcRelAssignsToGroup` membership
    - :class:`IfcRelAggregates` decomposition under ``composite_fill``

    :param file: the IFC file to author into
    :param group: the :class:`IfcGroup` (with ``ObjectType="GradingGroup"``)
    :param composite_fill: the per-group composite :class:`IfcEarthworksFill`
        returned alongside ``group`` from :func:`create_grading_group`
    :param name: human-readable name
    :param points: ``(N, 3)`` array of XYZ coordinates
    :param triangles: ``(M, 3)`` 0-based vertex indices, counterclockwise from above
    :param triangle_flags: optional per-triangle IFC ``Flags`` integers
    :returns: the created :class:`IfcEarthworksFill`
    :raises ValueError: if ``group`` is not an ``IfcGroup``, ``composite_fill``
        is not an ``IfcEarthworksFill``, ``points`` is empty, or the group
        already has an interior fill
    """
    if not group.is_a("IfcGroup"):
        raise ValueError(f"group must be an IfcGroup, got {group.is_a()} #{group.id()}")
    if not composite_fill.is_a("IfcEarthworksFill"):
        raise ValueError(
            f"composite_fill must be an IfcEarthworksFill, got "
            f"{composite_fill.is_a()} #{composite_fill.id()}"
        )

    existing = _existing_interior_fill_under(composite_fill)
    if existing is not None:
        raise ValueError(
            f"composite_fill #{composite_fill.id()} already has an interior fill "
            f"({existing.is_a()} #{existing.id()}); only one is permitted per group"
        )

    point_list = to_point_list(points)
    if not point_list:
        raise ValueError("points must not be empty")

    interior_fill = file.create_entity(
        "IfcEarthworksFill",
        GlobalId=ifcopenshell.guid.new(),
        Name=name,
        PredefinedType="SUBGRADE",
        ObjectPlacement=identity_placement(file),
    )

    ifcopenshell.api.surface.add_tin_representation(
        file, interior_fill, point_list, triangles, triangle_flags=triangle_flags
    )
    min_xyz, max_xyz = compute_bounding_box(point_list)
    ifcopenshell.api.surface.add_bounding_box_representation(
        file, interior_fill, min_xyz=min_xyz, max_xyz=max_xyz
    )

    attach_earthworks_fill_common(file, interior_fill)
    apply_omniclass_classification(
        file,
        interior_fill,
        INTERIOR_FILL_OMNICLASS_CODE,
        INTERIOR_FILL_OMNICLASS_TITLE,
    )

    add_member_to_group(file, group, interior_fill)
    aggregate_under(file, composite_fill, interior_fill)

    return interior_fill

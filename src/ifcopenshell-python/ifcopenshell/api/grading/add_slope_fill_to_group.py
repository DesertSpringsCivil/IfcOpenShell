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

"""Author an IfcEarthworksFill[SLOPEFILL] under a grading group."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

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

SLOPE_FILL_OMNICLASS_CODE = "22-07 31 23"
SLOPE_FILL_OMNICLASS_TITLE = "Fill"


def add_slope_fill_to_group(
    file: ifcopenshell.file,
    group: ifcopenshell.entity_instance,
    composite_fill: ifcopenshell.entity_instance,
    *,
    name: str,
    points: "PointArray",
    triangles: "TriangleArray",
    triangle_flags: "FlagArray" = None,
    feature_line: Optional[ifcopenshell.entity_instance] = None,
) -> ifcopenshell.entity_instance:
    """Author an :class:`IfcEarthworksFill` with ``PredefinedType=SLOPEFILL`` under a grading group.

    The slope fill is the ribbon of triangles between a feature line and its
    daylight line — the geometric output of the slope projection algorithm.
    Bonsai's ``tool.Grading`` (Phase 5) computes the points and triangles;
    this function persists them.

    The fill is wired into the grading group two ways:

    1. **Group membership** via :class:`IfcRelAssignsToGroup` — appended to
       the existing rel that ``create_grading_group`` set up, alongside the
       composite_fill. Use :func:`add_member_to_group` for this.
    2. **Aggregation** under ``composite_fill`` via
       :class:`IfcRelAggregates` — establishes the per-group composite as
       this slope fill's parent in the decomposition tree.

    Both ``group`` and ``composite_fill`` are passed as explicit arguments
    rather than discovered via inverse-walk on the group, which keeps the
    contract robust against future site-composite-aggregation changes that
    would alter ``composite_fill.Decomposes``. The expected caller pattern:

    .. code:: python

        result = ifcopenshell.api.grading.create_grading_group(file, "Pad A", ...)
        slope = ifcopenshell.api.grading.add_slope_fill_to_group(
            file, result.group, result.composite_fill,
            name="North slope", points=..., triangles=...,
        )

    Representations and psets attached:

    - SurfaceModel :class:`IfcTriangulatedIrregularNetwork` (via
      :func:`ifcopenshell.api.surface.add_tin_representation`)
    - Box :class:`IfcBoundingBox` (via
      :func:`ifcopenshell.api.surface.add_bounding_box_representation`),
      derived from the point cloud's axis-aligned extents
    - Standard ``Pset_EarthworksFillCommon`` (``Status="NEW"``)
    - OmniClass Table 22 classification (``22-07 31 23`` Fill)

    :param file: the IFC file to author into
    :param group: the :class:`IfcGroup` (with ``ObjectType="GradingGroup"``)
        the slope fill is a member of
    :param composite_fill: the per-group composite
        :class:`IfcEarthworksFill` returned alongside ``group`` from
        :func:`create_grading_group`
    :param name: human-readable name for the slope fill
    :param points: ``(N, 3)`` array of XYZ coordinates
    :param triangles: ``(M, 3)`` 0-based vertex indices, counterclockwise from above
    :param triangle_flags: optional per-triangle IFC ``Flags`` integers
    :param feature_line: optional :class:`IfcAlignment` whose criteria
        produced this slope fill; when supplied, the feature line is also
        attached to the group as a member, establishing the traceability
        link from projection back to source
    :returns: the created :class:`IfcEarthworksFill`
    :raises ValueError: if ``group`` is not an ``IfcGroup``,
        ``composite_fill`` is not an ``IfcEarthworksFill``, or ``points`` /
        ``triangles`` are empty (the surface API enforces the latter)
    """
    if not group.is_a("IfcGroup"):
        raise ValueError(f"group must be an IfcGroup, got {group.is_a()} #{group.id()}")
    if not composite_fill.is_a("IfcEarthworksFill"):
        raise ValueError(
            f"composite_fill must be an IfcEarthworksFill, got "
            f"{composite_fill.is_a()} #{composite_fill.id()}"
        )

    point_list = to_point_list(points)
    if not point_list:
        raise ValueError("points must not be empty")

    slope_fill = file.create_entity(
        "IfcEarthworksFill",
        GlobalId=ifcopenshell.guid.new(),
        Name=name,
        PredefinedType="SLOPEFILL",
        ObjectPlacement=identity_placement(file),
    )

    ifcopenshell.api.surface.add_tin_representation(
        file, slope_fill, point_list, triangles, triangle_flags=triangle_flags
    )
    min_xyz, max_xyz = compute_bounding_box(point_list)
    ifcopenshell.api.surface.add_bounding_box_representation(
        file, slope_fill, min_xyz=min_xyz, max_xyz=max_xyz
    )

    attach_earthworks_fill_common(file, slope_fill)
    apply_omniclass_classification(
        file, slope_fill, SLOPE_FILL_OMNICLASS_CODE, SLOPE_FILL_OMNICLASS_TITLE
    )

    add_member_to_group(file, group, slope_fill)
    aggregate_under(file, composite_fill, slope_fill)

    if feature_line is not None:
        add_member_to_group(file, group, feature_line)

    return slope_fill

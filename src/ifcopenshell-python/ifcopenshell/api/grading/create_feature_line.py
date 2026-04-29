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

"""Author an IfcAlignment carrying a 3D polyline — the Saikei feature line."""

from __future__ import annotations

from typing import Optional, Sequence

import ifcopenshell
import ifcopenshell.api.alignment
import ifcopenshell.api.pset
import ifcopenshell.api.spatial
import ifcopenshell.guid

from ._shared import _resolve_site

PSET_NAME = "Pset_SaikeiFeatureLineCommon"
ALLOWED_SOURCES = frozenset({"manual", "drape", "corridor_extract", "csv_import"})


def create_feature_line(
    file: ifcopenshell.file,
    name: str,
    vertices: Sequence[Sequence[float]],
    *,
    closed: bool = False,
    source: str = "manual",
    elevation_source: str = "manual",
    grading_group_guid: Optional[str] = None,
    site: Optional[ifcopenshell.entity_instance] = None,
) -> ifcopenshell.entity_instance:
    """Create an :class:`IfcAlignment` whose representation is a 3D :class:`IfcIndexedPolyCurve`.

    Feature lines are Civil 3D's grading-footprint primitive: a 3D polyline
    with elevations at each vertex. Saikei persists them as ``IfcAlignment``
    to reuse the alignment infrastructure (segments, stationing, picker UI)
    and because IFC 4.3 explicitly lists ``IfcPolyline`` /
    ``IfcIndexedPolyCurve`` as a valid alignment representation. Per-vertex
    elevations are encoded directly in the polyline coordinates, so no
    ``IfcAlignmentVertical`` is created.

    The alignment is contained in :class:`IfcSite` via
    :func:`ifcopenshell.api.spatial.assign_container` — feature lines are
    site-scoped grading objects, distinct from transportation alignments
    which IFC 4.1.4.1.1 aggregates under :class:`IfcProject`. The
    ``Pset_SaikeiFeatureLineCommon`` carries ``IsClosed``, ``Source``,
    ``ElevationSource``, and the optional ``GradingGroupGuid``.

    :param file: the IFC file to author into
    :param name: human-readable name for the feature line
    :param vertices: an ordered sequence of ``(x, y, z)`` points; at least
        two are required
    :param closed: whether the polyline forms a closed loop. When ``True``,
        the first vertex is repeated as the polyline's terminating point so
        the geometry round-trips through any consumer
    :param source: free-form provenance label; one of ``manual``, ``drape``,
        ``corridor_extract``, ``csv_import``
    :param elevation_source: how vertex elevations were obtained (e.g.,
        ``"drape"`` if interpolated from an existing surface)
    :param grading_group_guid: optional GUID of the grading group this
        feature line is a member of
    :param site: the :class:`IfcSite` to attach to; if ``None``, the
        project's first ``IfcSite`` is used
    :returns: the created :class:`IfcAlignment`
    :raises ValueError: if ``vertices`` has fewer than two points, ``source``
        is not one of the allowed values, or ``site`` is ``None`` and no
        :class:`IfcSite` exists in the project
    """
    points = [(float(v[0]), float(v[1]), float(v[2])) for v in vertices]
    if len(points) < 2:
        raise ValueError("vertices must have at least two points")
    if source not in ALLOWED_SOURCES:
        raise ValueError(
            f"source must be one of {sorted(ALLOWED_SOURCES)}, got {source!r}"
        )
    target_site = _resolve_site(file, site)

    polyline_points = list(points)
    if closed and points[0] != points[-1]:
        polyline_points.append(points[0])

    alignment = file.create_entity(
        "IfcAlignment",
        GlobalId=ifcopenshell.guid.new(),
        Name=name,
    )
    alignment.ObjectPlacement = file.create_entity(
        "IfcLocalPlacement",
        RelativePlacement=file.create_entity(
            "IfcAxis2Placement3D",
            Location=file.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0)),
        ),
    )

    coord_list = file.create_entity("IfcCartesianPointList3D", CoordList=polyline_points)
    curve = file.create_entity("IfcIndexedPolyCurve", Points=coord_list, SelfIntersect=False)
    representation = file.create_entity(
        "IfcShapeRepresentation",
        ContextOfItems=ifcopenshell.api.alignment.get_axis_subcontext(file),
        RepresentationIdentifier="Axis",
        RepresentationType="Curve3D",
        Items=[curve],
    )
    alignment.Representation = file.create_entity(
        "IfcProductDefinitionShape", Representations=[representation]
    )

    ifcopenshell.api.spatial.assign_container(
        file, products=[alignment], relating_structure=target_site
    )

    properties: dict[str, object] = {
        "IsClosed": bool(closed),
        "Source": source,
        "ElevationSource": elevation_source,
    }
    if grading_group_guid is not None:
        properties["GradingGroupGuid"] = grading_group_guid
    pset = ifcopenshell.api.pset.add_pset(file, product=alignment, name=PSET_NAME)
    ifcopenshell.api.pset.edit_pset(file, pset=pset, properties=properties)

    return alignment

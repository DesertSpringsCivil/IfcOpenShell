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

"""Attach the Saikei-specific property set ``Pset_SaikeiGradingSurface``."""

from __future__ import annotations

from typing import Optional

import ifcopenshell
import ifcopenshell.api.pset

PSET_NAME = "Pset_SaikeiGradingSurface"


def _find_existing_pset(
    product: ifcopenshell.entity_instance, pset_name: str
) -> Optional[ifcopenshell.entity_instance]:
    """Return the IfcPropertySet of ``pset_name`` directly attached to product, or None."""
    for rel in product.IsDefinedBy or []:
        if not rel.is_a("IfcRelDefinesByProperties"):
            continue
        pset = rel.RelatingPropertyDefinition
        if pset is not None and pset.is_a("IfcPropertySet") and pset.Name == pset_name:
            return pset
    return None


def _infer_vertex_count_from_tin(product: ifcopenshell.entity_instance) -> Optional[int]:
    """Return the number of points on the host's SurfaceModel TIN, or None if absent."""
    representation = product.Representation
    if representation is None:
        return None
    for shape_rep in representation.Representations or []:
        if not shape_rep.is_a("IfcShapeRepresentation"):
            continue
        if shape_rep.RepresentationIdentifier != "SurfaceModel":
            continue
        for item in shape_rep.Items or []:
            if item.is_a("IfcTriangulatedIrregularNetwork"):
                return len(item.Coordinates.CoordList)
    return None


def apply_saikei_pset(
    file: ifcopenshell.file,
    product: ifcopenshell.entity_instance,
    triangulation_tolerance: float = 0.0,
    breakline_count: int = 0,
    vertex_count: Optional[int] = None,
    boundary_polygon_reference: Optional[str] = None,
) -> ifcopenshell.entity_instance:
    """Attach (or update) ``Pset_SaikeiGradingSurface`` on a surface host.

    The pset records Saikei-specific triangulation metadata that the IFC 4.3
    standard psets do not cover:

    - ``TriangulationTolerance``: the snap distance used during constrained
      Delaunay (project-units length, default 0)
    - ``BreaklineCount``: the number of distinct breaklines that contributed
      to the triangulation (defaults to 0; the API never overwrites this with
      a stale value — pass it explicitly when retriangulating)
    - ``VertexCount``: the number of TIN points; if ``None``, inferred from
      the host's existing SurfaceModel representation
    - ``BoundaryPolygonReference``: GUID-like reference to the outer boundary
      polygon used during triangulation (or None if the boundary was the
      convex hull of the points)

    If the pset is already attached, its values are updated in place rather
    than duplicating it. Returns the (existing or new) :class:`IfcPropertySet`.

    :param file: the IFC file to author into
    :param product: any :class:`IfcProduct` host (typically an IfcGeographicElement
        or IfcEarthworksFill)
    :param triangulation_tolerance: stored as ``TriangulationTolerance``
    :param breakline_count: stored as ``BreaklineCount``
    :param vertex_count: stored as ``VertexCount``; inferred from the SurfaceModel
        TIN when ``None``
    :param boundary_polygon_reference: stored as ``BoundaryPolygonReference``;
        omitted from the pset when ``None``
    :returns: the :class:`IfcPropertySet` carrying the Saikei properties
    """
    resolved_vertex_count = (
        vertex_count if vertex_count is not None else _infer_vertex_count_from_tin(product)
    )

    properties: dict[str, object] = {
        "TriangulationTolerance": float(triangulation_tolerance),
        "BreaklineCount": int(breakline_count),
    }
    if resolved_vertex_count is not None:
        properties["VertexCount"] = int(resolved_vertex_count)
    if boundary_polygon_reference is not None:
        properties["BoundaryPolygonReference"] = str(boundary_polygon_reference)

    pset = _find_existing_pset(product, PSET_NAME)
    if pset is None:
        pset = ifcopenshell.api.pset.add_pset(file, product=product, name=PSET_NAME)
    ifcopenshell.api.pset.edit_pset(file, pset=pset, properties=properties)
    return pset

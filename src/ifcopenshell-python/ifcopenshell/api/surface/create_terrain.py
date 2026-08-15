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

"""Top-level: create an IfcGeographicElement[TERRAIN] hosting a TIN, with all psets."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import ifcopenshell
import ifcopenshell.api.pset
import ifcopenshell.api.spatial
import ifcopenshell.guid

from ..grading._shared import apply_omniclass_classification
from .add_bounding_box_representation import add_bounding_box_representation
from .add_tin_representation import (
    _to_point_list,
    add_tin_representation,
)
from .apply_saikei_pset import apply_saikei_pset


# OmniClass Table 22 — 22-07 31 13 Site Preparation. Used as the default
# classification for an existing-ground TIN; distinguishes terrains from
# proposed surfaces (which default to 22-07 31 23 Fill, like slope fills)
# so consumers can tell them apart by classification, not just entity
# type + name (per the surfaces/grading/earthworks doc Principle #8).
TERRAIN_OMNICLASS_CODE = "22-07 31 13"
TERRAIN_OMNICLASS_TITLE = "Site Preparation"

if TYPE_CHECKING:
    from .add_tin_representation import FlagArray, PointArray, TriangleArray


def _resolve_site(
    file: ifcopenshell.file, site: Optional[ifcopenshell.entity_instance]
) -> ifcopenshell.entity_instance:
    if site is not None:
        return site
    sites = file.by_type("IfcSite")
    if not sites:
        raise ValueError(
            "no IfcSite present in project; pass site= explicitly or add an IfcSite first"
        )
    return sites[0]


def _bounding_box_corners(
    point_list: list[tuple[float, float, float]],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Return ``(min_xyz, max_xyz)`` from a list of (x, y, z) points."""
    xs = [p[0] for p in point_list]
    ys = [p[1] for p in point_list]
    zs = [p[2] for p in point_list]
    min_xyz = (min(xs), min(ys), min(zs))
    max_xyz = (max(xs), max(ys), max(zs))
    # IfcBoundingBox requires positive dims; nudge any zero axis (degenerate flat
    # surface oriented along an axis) so authoring succeeds.
    epsilon = 1e-6
    max_xyz = (
        max_xyz[0] if max_xyz[0] > min_xyz[0] else min_xyz[0] + epsilon,
        max_xyz[1] if max_xyz[1] > min_xyz[1] else min_xyz[1] + epsilon,
        max_xyz[2] if max_xyz[2] > min_xyz[2] else min_xyz[2] + epsilon,
    )
    return min_xyz, max_xyz


def _attach_geographic_element_common(
    file: ifcopenshell.file, product: ifcopenshell.entity_instance
) -> ifcopenshell.entity_instance:
    """Attach Pset_GeographicElementCommon with Status="NEW" so the pset is schema-valid."""
    pset = ifcopenshell.api.pset.add_pset(file, product=product, name="Pset_GeographicElementCommon")
    ifcopenshell.api.pset.edit_pset(file, pset=pset, properties={"Status": "NEW"})
    return pset


def create_terrain(
    file: ifcopenshell.file,
    name: str,
    points: "PointArray",
    triangles: "TriangleArray",
    triangle_flags: "FlagArray" = None,
    site: Optional[ifcopenshell.entity_instance] = None,
    triangulation_tolerance: float = 0.0,
    breakline_count: int = 0,
    omniclass_code: str = TERRAIN_OMNICLASS_CODE,
    omniclass_title: str = TERRAIN_OMNICLASS_TITLE,
) -> ifcopenshell.entity_instance:
    """Create an :class:`IfcGeographicElement` with ``PredefinedType=TERRAIN`` hosting a TIN.

    The new element is contained in :class:`IfcSite` via
    :func:`ifcopenshell.api.spatial.assign_container`. A
    :class:`IfcTriangulatedIrregularNetwork` Body representation is
    attached, alongside an :class:`IfcBoundingBox` LOD representation derived
    from the point cloud's axis-aligned extents. The standard
    ``Pset_GeographicElementCommon`` (``Status="NEW"``) and the Saikei
    ``SaikeiCivil_GradingSurface`` (with ``triangulation_tolerance``,
    ``breakline_count``, and inferred ``VertexCount``) are attached.
    An OmniClass Table 22 ``IfcClassificationReference`` is associated
    via :class:`IfcRelAssociatesClassification` so consumers can
    distinguish existing-vs-proposed surfaces beyond the entity-type
    + name pair (per the surfaces/grading/earthworks doc Principle #8).

    The function does **not** triangulate — it persists pre-triangulated data.
    Callers are responsible for the constrained Delaunay step (Bonsai's
    ``tool.Surface`` covers that).

    Coordinate system: TIN points are in the project's local engineering
    frame. Geodetic positioning is the caller's responsibility via
    :class:`IfcMapConversion` (Bonsai's ``tool.Georeference`` covers
    this); ``IfcSite.RefLatitude``/``RefLongitude`` is deprecated for
    new authoring.

    :param file: the IFC file to author into
    :param name: human-readable name for the terrain (e.g., ``"Existing Ground"``)
    :param points: ``(N, 3)`` array of XYZ coordinates in project coordinates
    :param triangles: ``(M, 3)`` 0-based vertex indices, counterclockwise from above
    :param triangle_flags: optional per-triangle IFC ``Flags`` integers; defaults
        to all zeros
    :param site: the :class:`IfcSite` to attach to; if ``None``, the project's
        first ``IfcSite`` is used
    :param triangulation_tolerance: stored on ``SaikeiCivil_GradingSurface``
    :param breakline_count: stored on ``SaikeiCivil_GradingSurface``
    :param omniclass_code: OmniClass Table 22 code. Default ``22-07 31 13``
        (Site Preparation). Override for project-specific or agency
        classifications (e.g., ``22-07 31 14`` Site Clearing).
    :param omniclass_title: human-readable title paired with ``omniclass_code``.
    :returns: the created :class:`IfcGeographicElement`
    :raises ValueError: if ``points`` or ``triangles`` are empty, if any triangle
        index is out of range, or if ``site`` is ``None`` and no IfcSite exists
    """
    target_site = _resolve_site(file, site)
    point_list = _to_point_list(points)
    if not point_list:
        raise ValueError("points must not be empty")

    terrain = file.create_entity(
        "IfcGeographicElement",
        GlobalId=ifcopenshell.guid.new(),
        Name=name,
        PredefinedType="TERRAIN",
    )
    ifcopenshell.api.spatial.assign_container(
        file, products=[terrain], relating_structure=target_site
    )
    add_tin_representation(file, terrain, point_list, triangles, triangle_flags=triangle_flags)
    min_xyz, max_xyz = _bounding_box_corners(point_list)
    add_bounding_box_representation(file, terrain, min_xyz=min_xyz, max_xyz=max_xyz)
    _attach_geographic_element_common(file, terrain)
    apply_saikei_pset(
        file,
        terrain,
        triangulation_tolerance=triangulation_tolerance,
        breakline_count=breakline_count,
    )
    apply_omniclass_classification(file, terrain, omniclass_code, omniclass_title)
    return terrain

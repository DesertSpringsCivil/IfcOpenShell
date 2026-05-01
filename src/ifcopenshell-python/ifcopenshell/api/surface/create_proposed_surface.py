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

"""Top-level: create an IfcEarthworksFill[SUBGRADE] hosting a TIN, with all psets."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import ifcopenshell
import ifcopenshell.api.pset
import ifcopenshell.api.spatial
import ifcopenshell.guid

from ..grading._shared import apply_omniclass_classification
from .add_bounding_box_representation import add_bounding_box_representation
from .add_tin_representation import _to_point_list, add_tin_representation
from .apply_saikei_pset import apply_saikei_pset
from .create_terrain import _bounding_box_corners, _resolve_site


# OmniClass Table 22 — 22-07 31 23 Fill. Used as the default
# classification for a proposed-ground TIN; matches the OmniClass code
# used for slope fills and group-composite fills, distinguishing
# proposed surfaces from existing terrain (which defaults to
# 22-07 31 13 Site Preparation) per the surfaces/grading/earthworks
# doc Principle #8.
PROPOSED_SURFACE_OMNICLASS_CODE = "22-07 31 23"
PROPOSED_SURFACE_OMNICLASS_TITLE = "Fill"

if TYPE_CHECKING:
    from .add_tin_representation import FlagArray, PointArray, TriangleArray


def _attach_earthworks_fill_common(
    file: ifcopenshell.file, product: ifcopenshell.entity_instance
) -> ifcopenshell.entity_instance:
    """Attach Pset_EarthworksFillCommon with Status="NEW" so the pset is schema-valid."""
    pset = ifcopenshell.api.pset.add_pset(file, product=product, name="Pset_EarthworksFillCommon")
    ifcopenshell.api.pset.edit_pset(file, pset=pset, properties={"Status": "NEW"})
    return pset


def create_proposed_surface(
    file: ifcopenshell.file,
    name: str,
    points: "PointArray",
    triangles: "TriangleArray",
    triangle_flags: "FlagArray" = None,
    site: Optional[ifcopenshell.entity_instance] = None,
    triangulation_tolerance: float = 0.0,
    breakline_count: int = 0,
    omniclass_code: str = PROPOSED_SURFACE_OMNICLASS_CODE,
    omniclass_title: str = PROPOSED_SURFACE_OMNICLASS_TITLE,
) -> ifcopenshell.entity_instance:
    """Create an :class:`IfcEarthworksFill` with ``PredefinedType=SUBGRADE`` hosting a TIN.

    Companion to :func:`create_terrain`. Same triangulation contract — the
    function persists pre-triangulated data; callers handle the constrained
    Delaunay step. The new element is contained in :class:`IfcSite` via
    :func:`ifcopenshell.api.spatial.assign_container`. A Body TIN
    representation, a Box LOD representation, the standard
    ``Pset_EarthworksFillCommon`` (``Status="NEW"``), the Saikei
    ``Pset_SaikeiGradingSurface``, and an OmniClass Table 22
    ``IfcClassificationReference`` are attached.

    :func:`ifcopenshell.api.grading.create_grading_group` (Phase 2) will call
    this for the proposed-ground TIN of every grading group it authors.

    Coordinate system: TIN points are in the project's local engineering
    frame. Geodetic positioning is the caller's responsibility via
    :class:`IfcMapConversion` (Bonsai's ``tool.Georeference`` covers this).

    :param file: the IFC file to author into
    :param name: human-readable name for the proposed surface
    :param points: ``(N, 3)`` array of XYZ coordinates in project coordinates
    :param triangles: ``(M, 3)`` 0-based vertex indices, counterclockwise from above
    :param triangle_flags: optional per-triangle IFC ``Flags`` integers; defaults
        to all zeros
    :param site: the :class:`IfcSite` to attach to; if ``None``, the project's
        first ``IfcSite`` is used
    :param triangulation_tolerance: stored on ``Pset_SaikeiGradingSurface``
    :param breakline_count: stored on ``Pset_SaikeiGradingSurface``
    :param omniclass_code: OmniClass Table 22 code. Default ``22-07 31 23``
        (Fill). Override for project-specific or agency classifications.
    :param omniclass_title: human-readable title paired with ``omniclass_code``.
    :returns: the created :class:`IfcEarthworksFill`
    :raises ValueError: if ``points`` or ``triangles`` are empty, if any triangle
        index is out of range, or if ``site`` is ``None`` and no IfcSite exists
    """
    target_site = _resolve_site(file, site)
    point_list = _to_point_list(points)
    if not point_list:
        raise ValueError("points must not be empty")

    proposed = file.create_entity(
        "IfcEarthworksFill",
        GlobalId=ifcopenshell.guid.new(),
        Name=name,
        PredefinedType="SUBGRADE",
    )
    ifcopenshell.api.spatial.assign_container(
        file, products=[proposed], relating_structure=target_site
    )
    add_tin_representation(file, proposed, point_list, triangles, triangle_flags=triangle_flags)
    min_xyz, max_xyz = _bounding_box_corners(point_list)
    add_bounding_box_representation(file, proposed, min_xyz=min_xyz, max_xyz=max_xyz)
    _attach_earthworks_fill_common(file, proposed)
    apply_saikei_pset(
        file,
        proposed,
        triangulation_tolerance=triangulation_tolerance,
        breakline_count=breakline_count,
    )
    apply_omniclass_classification(file, proposed, omniclass_code, omniclass_title)
    return proposed

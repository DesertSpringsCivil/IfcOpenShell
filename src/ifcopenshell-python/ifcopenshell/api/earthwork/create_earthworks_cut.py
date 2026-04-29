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

"""Top-level: create an IfcEarthworksCut with a closed-solid body representation."""

from __future__ import annotations

from typing import Optional, Sequence

import ifcopenshell
import ifcopenshell.api.spatial
import ifcopenshell.guid
from ifcopenshell.api.grading._shared import (
    _resolve_site,
    apply_omniclass_classification,
    identity_placement,
)

from ._shared import attach_earthworks_cut_common, validate_cut_predefined_type
from .add_volume_solid_representation import add_volume_solid_representation


def create_earthworks_cut(
    file: ifcopenshell.file,
    name: str,
    *,
    points: Sequence[Sequence[float]],
    faces: Sequence[Sequence[int]],
    predefined_type: str = "EXCAVATION",
    omniclass_code: str = "22-07 31 16",
    omniclass_title: str = "Excavation and Fill",
    site: Optional[ifcopenshell.entity_instance] = None,
) -> ifcopenshell.entity_instance:
    """Create an :class:`IfcEarthworksCut` with a closed PolygonalFaceSet body.

    Authors:

    - :class:`IfcEarthworksCut` with the supplied ``predefined_type`` (must
      be a valid ``IfcEarthworksCutTypeEnum`` value; defaults to
      ``"EXCAVATION"`` — general earthwork excavation)
    - Identity :class:`IfcLocalPlacement` (per spec §2.8 — absolute world
      positioning is handled by ``IfcMapConversion`` at the project level)
    - :class:`IfcRelContainedInSpatialStructure` attaching the cut to the
      site
    - :class:`IfcPolygonalFaceSet` closed body (via
      :func:`add_volume_solid_representation`) — RepresentationIdentifier
      ``"Body"``, RepresentationType ``"Tessellation"``
    - ``Pset_EarthworksCutCommon`` with ``Status="NEW"``
    - OmniClass Table 22 classification

    To void a host terrain (the typical "this cut excavates that terrain"
    relationship), call :func:`void_terrain` separately after the cut is
    authored. See spec §2.4 for the cut/void semantics.

    **Schema-completeness note.** The cut authored by this function is
    schema-incomplete until :func:`void_terrain` is called — IFC 4.3 mandates
    :class:`IfcFeatureElementSubtraction.VoidsElements` cardinality ``[1:1]``,
    so every cut must void exactly one host element. Always pair
    :func:`create_earthworks_cut` with a :func:`void_terrain` call before
    saving or running ``ifcopenshell.validate`` on the file; a partial file
    between the two calls will fail validation with a missing-VoidsElements
    error.

    :param file: the IFC file to author into
    :param name: human-readable name
    :param points: ``(N, 3)`` array of XYZ coordinates for the closed solid
    :param faces: list of vertex-index lists; each face must have at least
        3 vertices (triangles, quads, higher n-gons all valid)
    :param predefined_type: one of the IFC 4.3 ``IfcEarthworksCutTypeEnum``
        values: ``BASE_EXCAVATION``, ``CUT``, ``DREDGING``, ``EXCAVATION``,
        ``OVEREXCAVATION``, ``PAVEMENTMILLING``, ``STEPEXCAVATION``,
        ``TOPSOILREMOVAL``, ``TRENCH``, ``USERDEFINED``, ``NOTDEFINED``
    :param omniclass_code: OmniClass Table 22 code. Default ``22-07 31 16``
        (Excavation and Fill — the umbrella code for earth-moving). Override
        with a more specific code (e.g., ``22-07 31 26`` Trench Excavation,
        ``22-07 31 53`` Rock Removal, ``22-07 31 14`` Site Clearing for
        topsoil stripping) when the project warrants it.
    :param omniclass_title: human-readable title paired with the code; the
        default matches the default code. Pair updates with ``omniclass_code``
        so the :class:`IfcClassificationReference` shows the right title.
    :param site: the :class:`IfcSite` to spatially contain the cut in; if
        ``None``, the project's first ``IfcSite`` is used
    :returns: the created :class:`IfcEarthworksCut`
    :raises ValueError: if ``predefined_type`` is not a valid enum value,
        if ``points`` or ``faces`` are malformed, or if ``site`` is ``None``
        and no IfcSite exists in the project
    """
    validate_cut_predefined_type(predefined_type)
    target_site = _resolve_site(file, site)

    cut = file.create_entity(
        "IfcEarthworksCut",
        GlobalId=ifcopenshell.guid.new(),
        Name=name,
        PredefinedType=predefined_type,
        ObjectPlacement=identity_placement(file),
    )
    ifcopenshell.api.spatial.assign_container(
        file, products=[cut], relating_structure=target_site
    )
    add_volume_solid_representation(file, cut, points, faces)
    attach_earthworks_cut_common(file, cut)
    apply_omniclass_classification(file, cut, omniclass_code, omniclass_title)
    return cut

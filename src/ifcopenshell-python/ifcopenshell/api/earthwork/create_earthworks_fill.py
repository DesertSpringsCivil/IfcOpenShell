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

"""Top-level: create a volume-bearing IfcEarthworksFill — distinct from Phase 2 surface fills."""

from __future__ import annotations

from typing import Optional, Sequence

import ifcopenshell
import ifcopenshell.api.spatial
import ifcopenshell.guid
from ifcopenshell.api.grading._shared import (
    _resolve_site,
    apply_omniclass_classification,
    attach_earthworks_fill_common,
    identity_placement,
)

from ._shared import validate_fill_predefined_type
from .add_volume_solid_representation import add_volume_solid_representation


def create_earthworks_fill(
    file: ifcopenshell.file,
    name: str,
    *,
    points: Sequence[Sequence[float]],
    faces: Sequence[Sequence[int]],
    predefined_type: str = "EMBANKMENT",
    omniclass_code: str = "22-07 31 23",
    omniclass_title: str = "Fill",
    site: Optional[ifcopenshell.entity_instance] = None,
) -> ifcopenshell.entity_instance:
    """Create a volume-bearing :class:`IfcEarthworksFill` with a closed PolygonalFaceSet body.

    Distinct from Phase 2 surface fills authored by
    :mod:`ifcopenshell.api.grading`: those use ``PredefinedType=SLOPEFILL``
    or ``SUBGRADE`` and carry Body TIN representations. Phase 3
    fills are volume-bearing — closed solid bodies representing actual
    earthwork material with computable volumes — and use the
    ``BACKFILL`` / ``COUNTERWEIGHT`` / ``EMBANKMENT`` / ``SUBGRADEBED`` /
    ``TRANSITIONSECTION`` family of PredefinedType values.

    Passing ``SLOPEFILL`` or ``SUBGRADE`` is allowed (they're still valid
    IFC values) but emits a :class:`UserWarning` — almost always a caller
    mix-up between the two APIs.

    Authors:

    - :class:`IfcEarthworksFill` with the supplied ``predefined_type``
    - Identity :class:`IfcLocalPlacement` (per spec §2.8)
    - :class:`IfcRelContainedInSpatialStructure` attaching the fill to the site
    - :class:`IfcPolygonalFaceSet` closed body (via
      :func:`add_volume_solid_representation`) — RepresentationIdentifier
      ``"Body"``, RepresentationType ``"Tessellation"``
    - ``Pset_EarthworksFillCommon`` with ``Status="NEW"``
    - OmniClass Table 22 classification

    :param file: the IFC file to author into
    :param name: human-readable name
    :param points: ``(N, 3)`` array of XYZ coordinates for the closed solid
    :param faces: list of vertex-index lists; each face must have at least
        3 vertices
    :param predefined_type: one of the IFC 4.3 ``IfcEarthworksFillTypeEnum``
        values. Recommended for Phase 3: ``BACKFILL``, ``COUNTERWEIGHT``,
        ``EMBANKMENT`` (default), ``SUBGRADEBED``, ``TRANSITIONSECTION``,
        ``USERDEFINED``, ``NOTDEFINED``. Passing ``SLOPEFILL`` or
        ``SUBGRADE`` produces a UserWarning since those are reserved by
        ``ifcopenshell.api.grading``.
    :param omniclass_code: OmniClass Table 22 code. Default ``22-07 31 23``
        (Fill — the umbrella code for placed earth material). Override
        with a more specific code (e.g., ``22-07 31 23 13`` Embankment,
        ``22-07 31 23 16`` Backfill, ``22-07 31 16`` Excavation and Fill
        when the fill comes from on-site cut/fill matching) when the
        project warrants it.
    :param omniclass_title: human-readable title paired with the code; the
        default matches the default code. Pair updates with ``omniclass_code``
        so the :class:`IfcClassificationReference` shows the right title.
    :param site: the :class:`IfcSite` to spatially contain the fill in; if
        ``None``, the project's first ``IfcSite`` is used
    :returns: the created :class:`IfcEarthworksFill`
    :raises ValueError: if ``predefined_type`` is not in the IFC enum, if
        ``points`` or ``faces`` are malformed, or if ``site`` is ``None``
        and no IfcSite exists in the project
    """
    validate_fill_predefined_type(predefined_type)
    target_site = _resolve_site(file, site)

    fill = file.create_entity(
        "IfcEarthworksFill",
        GlobalId=ifcopenshell.guid.new(),
        Name=name,
        PredefinedType=predefined_type,
        ObjectPlacement=identity_placement(file),
    )
    ifcopenshell.api.spatial.assign_container(
        file, products=[fill], relating_structure=target_site
    )
    add_volume_solid_representation(file, fill, points, faces)
    attach_earthworks_fill_common(file, fill)
    apply_omniclass_classification(file, fill, omniclass_code, omniclass_title)
    return fill

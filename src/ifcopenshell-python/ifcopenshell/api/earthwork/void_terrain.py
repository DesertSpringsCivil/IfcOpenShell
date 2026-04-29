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

"""Author IfcRelVoidsElement: an earthwork cut subtracts geometry from a host terrain."""

from __future__ import annotations

import ifcopenshell
import ifcopenshell.guid


def void_terrain(
    file: ifcopenshell.file,
    cut: ifcopenshell.entity_instance,
    terrain: ifcopenshell.entity_instance,
) -> ifcopenshell.entity_instance:
    """Author an :class:`IfcRelVoidsElement` between a cut and its host terrain.

    Establishes the "this cut excavates that terrain" relationship per spec
    §2.4 — the same pattern :class:`IfcOpeningElement` uses to void
    :class:`IfcWall` etc. The cut is the ``RelatedOpeningElement`` (the
    subtraction); the terrain is the ``RelatingBuildingElement`` (the host
    being voided).

    **Cardinality.** :class:`IfcFeatureElementSubtraction` (the supertype of
    :class:`IfcEarthworksCut`) has the schema-level inverse
    ``VoidsElements [1:1]`` — each cut voids exactly one element. This
    function enforces that:

    - If ``cut`` already voids ``terrain``, the existing rel is returned
      (idempotent).
    - If ``cut`` already voids a *different* element, :class:`ValueError`
      is raised — the caller must remove the existing rel first to retarget.

    A single terrain can be voided by many cuts; only the cut side is
    cardinality-restricted.

    :param file: the IFC file to author into
    :param cut: an :class:`IfcEarthworksCut` (or any
        :class:`IfcFeatureElementSubtraction` subtype)
    :param terrain: an :class:`IfcGeographicElement` (typically
        ``PredefinedType=TERRAIN``) or other :class:`IfcElement` host
    :returns: the :class:`IfcRelVoidsElement` (existing or newly created)
    :raises ValueError: if ``cut`` is not a feature-element-subtraction,
        ``terrain`` is not an element, or ``cut`` already voids a different
        host element
    """
    if not cut.is_a("IfcFeatureElementSubtraction"):
        raise ValueError(
            f"cut must be an IfcFeatureElementSubtraction (e.g., IfcEarthworksCut), "
            f"got {cut.is_a()} #{cut.id()}"
        )
    if not terrain.is_a("IfcElement"):
        raise ValueError(
            f"terrain must be an IfcElement (e.g., IfcGeographicElement), got "
            f"{terrain.is_a()} #{terrain.id()}"
        )

    existing_rels = list(cut.VoidsElements or [])
    for rel in existing_rels:
        # IFC 4.3 schema: IfcRelVoidsElement.RelatingBuildingElement is
        # required, so host is guaranteed non-None on a well-formed file.
        # If a malformed file ever has None here, the AttributeError below
        # is more diagnostic than a silent fallthrough.
        host = rel.RelatingBuildingElement
        if host.id() == terrain.id():
            return rel
        raise ValueError(
            f"cut {cut.is_a()} #{cut.id()} already voids "
            f"{host.is_a()} #{host.id()}; remove the existing IfcRelVoidsElement "
            "before retargeting to a different host"
        )

    return file.create_entity(
        "IfcRelVoidsElement",
        GlobalId=ifcopenshell.guid.new(),
        RelatingBuildingElement=terrain,
        RelatedOpeningElement=cut,
    )

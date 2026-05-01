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

"""Author IfcRelFillsElement: a fill (or footing/pipe/etc.) fills an earthwork cut."""

from __future__ import annotations

import ifcopenshell
import ifcopenshell.guid


def link_fill_to_cut(
    file: ifcopenshell.file,
    cut: ifcopenshell.entity_instance,
    fill: ifcopenshell.entity_instance,
) -> ifcopenshell.entity_instance:
    """Author an :class:`IfcRelFillsElement` between an earthwork cut and a fill.

    Establishes the "this fill occupies that cut" relationship per the
    IFC 4.3 voiding pattern (Earthworks Cuttings concept) — the same
    rel that links a window into a wall opening, repurposed for the
    civil case where an earthwork cut is filled by an
    :class:`IfcEarthworksFill`, an :class:`IfcFooting`, an
    :class:`IfcPipeSegment`, etc. The cut is the
    ``RelatingOpeningElement``; the fill is the
    ``RelatedBuildingElement``.

    Companion to :func:`void_terrain` (which authors the
    cut→terrain :class:`IfcRelVoidsElement` half of the chain). Together
    they let Saikei express the canonical earthworks model:

    - terrain (IfcGeographicElement[TERRAIN])
    - voided by IfcRelVoidsElement
    - cut (IfcEarthworksCut, body = computed cut volume)
    - filled by IfcRelFillsElement
    - fill (IfcEarthworksFill / IfcFooting / IfcPipeSegment / etc.)

    **Cardinality.** The IFC 4.3 schema's
    :class:`IfcElement.FillsVoids` inverse is [0:?] (an element can fill
    multiple openings), but practical view definitions restrict it to
    one. This function follows the convention: if ``fill`` already
    fills a different cut, :class:`ValueError` is raised. Callers must
    remove the existing rel before retargeting. From the cut side,
    :class:`IfcOpeningElement.HasFillings` is unrestricted — a single
    cut can host multiple fills (e.g., subgrade + bedding + structural
    fill in the same trench).

    Idempotent: if the rel already exists with the same
    ``(cut, fill)`` pair, the existing rel is returned.

    :param file: the IFC file to author into
    :param cut: an :class:`IfcEarthworksCut` (or any
        :class:`IfcFeatureElementSubtraction` subtype). The IFC 4.3
        schema accepts these in ``RelatingOpeningElement`` even though
        the field is typed :class:`IfcOpeningElement` — the parser
        permits the broader feature-subtraction supertype.
    :param fill: an :class:`IfcElement` that fills the cut, typically an
        :class:`IfcEarthworksFill` but anything that occupies the void
        is valid (footing, pipe segment, etc.)
    :returns: the :class:`IfcRelFillsElement` (existing or newly created)
    :raises ValueError: if ``cut`` is not a feature-element-subtraction,
        ``fill`` is not an element, or ``fill`` already fills a
        different cut
    """
    if not cut.is_a("IfcFeatureElementSubtraction"):
        raise ValueError(
            f"cut must be an IfcFeatureElementSubtraction (e.g., "
            f"IfcEarthworksCut), got {cut.is_a()} #{cut.id()}"
        )
    if not fill.is_a("IfcElement"):
        raise ValueError(
            f"fill must be an IfcElement (e.g., IfcEarthworksFill), got "
            f"{fill.is_a()} #{fill.id()}"
        )

    existing_rels = list(fill.FillsVoids or [])
    for rel in existing_rels:
        opening = rel.RelatingOpeningElement
        if opening.id() == cut.id():
            return rel
        raise ValueError(
            f"fill {fill.is_a()} #{fill.id()} already fills "
            f"{opening.is_a()} #{opening.id()}; remove the existing "
            "IfcRelFillsElement before retargeting to a different cut"
        )

    return file.create_entity(
        "IfcRelFillsElement",
        GlobalId=ifcopenshell.guid.new(),
        RelatingOpeningElement=cut,
        RelatedBuildingElement=fill,
    )

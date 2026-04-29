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

"""Attach Pset_SaikeiGradingAlignment to a grading group or fill, recording corridor linkage."""

from __future__ import annotations

from typing import Optional

import ifcopenshell
import ifcopenshell.api.pset

PSET_NAME = "Pset_SaikeiGradingAlignment"


def link_alignment_to_group(
    file: ifcopenshell.file,
    group_or_fill: ifcopenshell.entity_instance,
    alignment: ifcopenshell.entity_instance,
    *,
    start_station: Optional[float] = None,
    end_station: Optional[float] = None,
) -> ifcopenshell.entity_instance:
    """Record a corridor linkage on a grading group or earthworks fill.

    Used when grading is being authored alongside a corridor — the
    ``AlignmentGuid``, ``StartStation``, and ``EndStation`` give cost-
    estimating tools the station range over which the grading applies. Per
    spec §3.3, ``Pset_SaikeiGradingAlignment`` may be attached to either
    :class:`IfcGroup` (the grading group) or :class:`IfcEarthworksFill` (a
    specific fill within the group); both are accepted here.

    If the pset is already attached to the supplied entity, its values are
    updated in place rather than duplicating — re-linking is an "update
    station range" operation.

    :param file: the IFC file to author into
    :param group_or_fill: the entity to attach the pset to; must be an
        :class:`IfcGroup` or :class:`IfcEarthworksFill`
    :param alignment: the :class:`IfcAlignment` whose stationing the grading
        is referenced against
    :param start_station: optional start of the station range (length-measure
        units)
    :param end_station: optional end of the station range (length-measure
        units); if both are supplied, must be greater than ``start_station``
    :returns: the :class:`IfcPropertySet` (existing or newly created)
    :raises ValueError: if ``group_or_fill`` is neither an ``IfcGroup`` nor
        an ``IfcEarthworksFill``, ``alignment`` is not an ``IfcAlignment``,
        or ``end_station <= start_station`` when both are supplied
    """
    if not (group_or_fill.is_a("IfcGroup") or group_or_fill.is_a("IfcEarthworksFill")):
        raise ValueError(
            f"group_or_fill must be IfcGroup or IfcEarthworksFill, got "
            f"{group_or_fill.is_a()} #{group_or_fill.id()}"
        )
    if not alignment.is_a("IfcAlignment"):
        raise ValueError(
            f"alignment must be an IfcAlignment, got {alignment.is_a()} #{alignment.id()}"
        )
    if (
        start_station is not None
        and end_station is not None
        and end_station <= start_station
    ):
        raise ValueError(
            f"end_station ({end_station}) must be greater than start_station ({start_station})"
        )

    properties: dict[str, object] = {"AlignmentGuid": alignment.GlobalId}
    if start_station is not None:
        properties["StartStation"] = float(start_station)
    if end_station is not None:
        properties["EndStation"] = float(end_station)

    existing_pset = None
    for rel in group_or_fill.IsDefinedBy or []:
        if not rel.is_a("IfcRelDefinesByProperties"):
            continue
        candidate = rel.RelatingPropertyDefinition
        if (
            candidate is not None
            and candidate.is_a("IfcPropertySet")
            and candidate.Name == PSET_NAME
        ):
            existing_pset = candidate
            break

    if existing_pset is None:
        existing_pset = ifcopenshell.api.pset.add_pset(
            file, product=group_or_fill, name=PSET_NAME
        )
    ifcopenshell.api.pset.edit_pset(file, pset=existing_pset, properties=properties)
    return existing_pset

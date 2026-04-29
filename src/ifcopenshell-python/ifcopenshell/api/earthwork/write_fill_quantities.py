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

"""Write or update Qto_EarthworksFillBaseQuantities on an IfcEarthworksFill."""

from __future__ import annotations

from typing import Optional

import ifcopenshell
import ifcopenshell.guid

from .write_cut_quantities import _find_existing_qto

QTO_NAME = "Qto_EarthworksFillBaseQuantities"


def _build_quantities(
    file: ifcopenshell.file,
    *,
    length: Optional[float],
    width: Optional[float],
    depth: Optional[float],
    compacted_volume: Optional[float],
    loose_volume: Optional[float],
) -> list[ifcopenshell.entity_instance]:
    """Build the list of IfcQuantity* entities for the fill Qto, omitting None-valued ones."""
    quantities: list[ifcopenshell.entity_instance] = []
    if length is not None:
        quantities.append(
            file.create_entity("IfcQuantityLength", Name="Length", LengthValue=float(length))
        )
    if width is not None:
        quantities.append(
            file.create_entity("IfcQuantityLength", Name="Width", LengthValue=float(width))
        )
    if depth is not None:
        quantities.append(
            file.create_entity("IfcQuantityLength", Name="Depth", LengthValue=float(depth))
        )
    if compacted_volume is not None:
        quantities.append(
            file.create_entity(
                "IfcQuantityVolume",
                Name="CompactedVolume",
                VolumeValue=float(compacted_volume),
            )
        )
    if loose_volume is not None:
        quantities.append(
            file.create_entity(
                "IfcQuantityVolume",
                Name="LooseVolume",
                VolumeValue=float(loose_volume),
            )
        )
    return quantities


def write_fill_quantities(
    file: ifcopenshell.file,
    fill: ifcopenshell.entity_instance,
    *,
    length: Optional[float] = None,
    width: Optional[float] = None,
    depth: Optional[float] = None,
    compacted_volume: Optional[float] = None,
    loose_volume: Optional[float] = None,
) -> ifcopenshell.entity_instance:
    """Write or update ``Qto_EarthworksFillBaseQuantities`` on an :class:`IfcEarthworksFill`.

    Quantities follow the buildingSMART standard:

    +-----------------------+----------------------+
    | Quantity              | Type                 |
    +=======================+======================+
    | Length, Width, Depth  | IfcQuantityLength    |
    +-----------------------+----------------------+
    | CompactedVolume,      | IfcQuantityVolume    |
    | LooseVolume           |                      |
    +-----------------------+----------------------+

    Note the asymmetry with the cut Qto: cuts have ``UndisturbedVolume`` /
    ``LooseVolume`` (bank vs. swelled), fills have ``CompactedVolume`` /
    ``LooseVolume`` (placed vs. delivered). No ``Weight`` field on the fill
    Qto — the buildingSMART standard doesn't include it.

    Any ``None`` argument is omitted from the Qto entirely. At least one
    quantity must be supplied (IfcElementQuantity's ``Quantities``
    cardinality is ``[1:?]``).

    **Idempotent.** Same contract as :func:`write_cut_quantities`: when the
    fill already carries ``Qto_EarthworksFillBaseQuantities``, the existing
    :class:`IfcElementQuantity` is updated in place — old IfcQuantity*
    children are removed, new ones built, and the same
    :class:`IfcElementQuantity` entity is returned. Re-running a volume
    calculation does not duplicate Qtos.

    Accepts either a Phase 3 volume-bearing fill (``EMBANKMENT``,
    ``BACKFILL``, etc) or a Phase 2 surface fill (``SLOPEFILL``,
    ``SUBGRADE``) — there's no PredefinedType filter here, since some
    Phase 2 fills (the per-group composite, the interior fill) genuinely
    do carry computed volumes once Phase 6 runs.

    :param file: the IFC file to author into
    :param fill: the :class:`IfcEarthworksFill` to attach the Qto to
    :param length: stored as ``Length`` (IfcQuantityLength)
    :param width: stored as ``Width`` (IfcQuantityLength)
    :param depth: stored as ``Depth`` (IfcQuantityLength)
    :param compacted_volume: stored as ``CompactedVolume`` — the placed,
        compacted volume of fill material
    :param loose_volume: stored as ``LooseVolume`` — the volume as
        delivered, before compaction
    :returns: the :class:`IfcElementQuantity` (existing or newly created)
    :raises ValueError: if ``fill`` is not an :class:`IfcEarthworksFill` or
        all quantity arguments are ``None``
    """
    if not fill.is_a("IfcEarthworksFill"):
        raise ValueError(
            f"fill must be an IfcEarthworksFill, got {fill.is_a()} #{fill.id()}"
        )

    quantities = _build_quantities(
        file,
        length=length,
        width=width,
        depth=depth,
        compacted_volume=compacted_volume,
        loose_volume=loose_volume,
    )
    if not quantities:
        raise ValueError(
            "at least one quantity must be supplied; IfcElementQuantity.Quantities "
            "cardinality is [1:?]"
        )

    existing_qto, _existing_rel = _find_existing_qto(fill, QTO_NAME)
    if existing_qto is not None:
        for old_quantity in existing_qto.Quantities or []:
            file.remove(old_quantity)
        existing_qto.Quantities = quantities
        return existing_qto

    qto = file.create_entity(
        "IfcElementQuantity",
        GlobalId=ifcopenshell.guid.new(),
        Name=QTO_NAME,
        Quantities=quantities,
    )
    file.create_entity(
        "IfcRelDefinesByProperties",
        GlobalId=ifcopenshell.guid.new(),
        RelatedObjects=[fill],
        RelatingPropertyDefinition=qto,
    )
    return qto

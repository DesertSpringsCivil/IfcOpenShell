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

"""Write or update Qto_EarthworksCutBaseQuantities on an IfcEarthworksCut."""

from __future__ import annotations

from typing import Optional

import ifcopenshell
import ifcopenshell.guid

QTO_NAME = "Qto_EarthworksCutBaseQuantities"


def _find_existing_qto(
    cut: ifcopenshell.entity_instance, qto_name: str
) -> tuple[
    Optional[ifcopenshell.entity_instance], Optional[ifcopenshell.entity_instance]
]:
    """Return (qto, defining_rel) tuple, or (None, None) if no Qto with this name attached."""
    for rel in cut.IsDefinedBy or []:
        if not rel.is_a("IfcRelDefinesByProperties"):
            continue
        candidate = rel.RelatingPropertyDefinition
        if (
            candidate is not None
            and candidate.is_a("IfcElementQuantity")
            and candidate.Name == qto_name
        ):
            return candidate, rel
    return None, None


def _build_quantities(
    file: ifcopenshell.file,
    *,
    length: Optional[float],
    width: Optional[float],
    depth: Optional[float],
    undisturbed_volume: Optional[float],
    loose_volume: Optional[float],
    weight: Optional[float],
) -> list[ifcopenshell.entity_instance]:
    """Build the list of IfcQuantity* entities for the cut Qto, omitting None-valued ones."""
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
    if undisturbed_volume is not None:
        quantities.append(
            file.create_entity(
                "IfcQuantityVolume",
                Name="UndisturbedVolume",
                VolumeValue=float(undisturbed_volume),
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
    if weight is not None:
        quantities.append(
            file.create_entity(
                "IfcQuantityWeight", Name="Weight", WeightValue=float(weight)
            )
        )
    return quantities


def write_cut_quantities(
    file: ifcopenshell.file,
    cut: ifcopenshell.entity_instance,
    *,
    length: Optional[float] = None,
    width: Optional[float] = None,
    depth: Optional[float] = None,
    undisturbed_volume: Optional[float] = None,
    loose_volume: Optional[float] = None,
    weight: Optional[float] = None,
) -> ifcopenshell.entity_instance:
    """Write or update ``Qto_EarthworksCutBaseQuantities`` on an :class:`IfcEarthworksCut`.

    Quantities follow the buildingSMART standard:

    +-----------------------+----------------------+
    | Quantity              | Type                 |
    +=======================+======================+
    | Length, Width, Depth  | IfcQuantityLength    |
    +-----------------------+----------------------+
    | UndisturbedVolume,    | IfcQuantityVolume    |
    | LooseVolume           |                      |
    +-----------------------+----------------------+
    | Weight                | IfcQuantityWeight    |
    +-----------------------+----------------------+

    Any ``None`` argument is omitted from the Qto entirely. At least one
    quantity must be supplied (IfcElementQuantity's ``Quantities`` cardinality
    is ``[1:?]``).

    **Idempotent.** When ``cut`` already carries a
    ``Qto_EarthworksCutBaseQuantities``, the existing
    :class:`IfcElementQuantity` is updated in place — old IfcQuantity*
    children are removed, new ones built, and the same
    :class:`IfcElementQuantity` entity is returned. Pattern matches
    ``ifcopenshell.api.grading.assign_grading_criteria``: re-running a
    volume calculation does not duplicate Qtos.

    :param file: the IFC file to author into
    :param cut: the :class:`IfcEarthworksCut` to attach the Qto to
    :param length: stored as ``Length`` (IfcQuantityLength)
    :param width: stored as ``Width`` (IfcQuantityLength)
    :param depth: stored as ``Depth`` (IfcQuantityLength)
    :param undisturbed_volume: stored as ``UndisturbedVolume`` — the bank
        / in-place volume of soil before excavation
    :param loose_volume: stored as ``LooseVolume`` — the volume after
        excavation, including swell
    :param weight: stored as ``Weight`` — total mass of excavated material
    :returns: the :class:`IfcElementQuantity` (existing or newly created)
    :raises ValueError: if ``cut`` is not an :class:`IfcEarthworksCut` or
        all quantity arguments are ``None``
    """
    if not cut.is_a("IfcEarthworksCut"):
        raise ValueError(
            f"cut must be an IfcEarthworksCut, got {cut.is_a()} #{cut.id()}"
        )

    quantities = _build_quantities(
        file,
        length=length,
        width=width,
        depth=depth,
        undisturbed_volume=undisturbed_volume,
        loose_volume=loose_volume,
        weight=weight,
    )
    if not quantities:
        raise ValueError(
            "at least one quantity must be supplied; IfcElementQuantity.Quantities "
            "cardinality is [1:?]"
        )

    existing_qto, _existing_rel = _find_existing_qto(cut, QTO_NAME)
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
        RelatedObjects=[cut],
        RelatingPropertyDefinition=qto,
    )
    return qto

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

"""Attach products to an IfcGroup via IfcRelAssignsToGroup."""

from __future__ import annotations

import ifcopenshell
import ifcopenshell.guid


def add_member_to_group(
    file: ifcopenshell.file,
    group: ifcopenshell.entity_instance,
    *products: ifcopenshell.entity_instance,
) -> ifcopenshell.entity_instance:
    """Attach one or more :class:`IfcObjectDefinition` entities to an :class:`IfcGroup`.

    Lower-level building block. If the group already has an
    :class:`IfcRelAssignsToGroup`, products are appended to its ``RelatedObjects``
    (de-duplicated). Otherwise a new rel is created.

    The IFC schema permits any ``IfcObjectDefinition`` as a group member, not
    just ``IfcProduct`` — ``IfcGroup`` and ``IfcTypeObject`` are also valid.
    This function permits all three.

    :param file: the IFC file to author into
    :param group: the :class:`IfcGroup` to add to
    :param products: one or more entities to add to the group
    :returns: the :class:`IfcRelAssignsToGroup` (existing or newly created)
    :raises ValueError: if ``group`` is not an :class:`IfcGroup`, if no products
        are supplied, or if any product is not an :class:`IfcObjectDefinition`
    """
    if not group.is_a("IfcGroup"):
        raise ValueError(
            f"group must be an IfcGroup, got {group.is_a()} #{group.id()}"
        )
    if not products:
        raise ValueError("at least one product must be supplied")
    for product in products:
        if not product.is_a("IfcObjectDefinition"):
            raise ValueError(
                f"product {product.is_a()} #{product.id()} is not an IfcObjectDefinition"
            )

    existing_rel = None
    for rel in group.IsGroupedBy or []:
        if rel.is_a("IfcRelAssignsToGroup") and rel.RelatingGroup.id() == group.id():
            existing_rel = rel
            break

    if existing_rel is None:
        return file.create_entity(
            "IfcRelAssignsToGroup",
            GlobalId=ifcopenshell.guid.new(),
            RelatedObjects=list(products),
            RelatingGroup=group,
        )

    existing_ids = {p.id() for p in existing_rel.RelatedObjects}
    additions = [p for p in products if p.id() not in existing_ids]
    if additions:
        existing_rel.RelatedObjects = list(existing_rel.RelatedObjects) + additions
    return existing_rel

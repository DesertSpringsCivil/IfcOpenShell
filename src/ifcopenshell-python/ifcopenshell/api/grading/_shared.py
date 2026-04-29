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

"""Internal helpers shared across the grading API.

Currently provides:

- ``_resolve_site`` — auto-resolve an IfcSite when callers leave the ``site``
  arg as None. Raises ValueError if no IfcSite exists in the project.
- ``apply_omniclass_classification`` — author OmniClass Table 22
  classification on a product. Idempotent: the IfcClassification and
  IfcClassificationReference are reused across calls in the same file.
"""

from __future__ import annotations

from typing import Optional

import ifcopenshell
import ifcopenshell.guid

OMNICLASS_TABLE_22_NAME = "OmniClass Table 22"
OMNICLASS_TABLE_22_SOURCE = "Construction Specifications Institute"


def _resolve_site(
    file: ifcopenshell.file, site: Optional[ifcopenshell.entity_instance]
) -> ifcopenshell.entity_instance:
    """Return ``site`` if supplied, else the project's first IfcSite. Raises if neither."""
    if site is not None:
        return site
    sites = file.by_type("IfcSite")
    if not sites:
        raise ValueError(
            "no IfcSite present in project; pass site= explicitly or add an IfcSite first"
        )
    return sites[0]


def _get_or_create_omniclass_table_22(file: ifcopenshell.file) -> ifcopenshell.entity_instance:
    """Return the file's IfcClassification for OmniClass Table 22, creating it if absent."""
    for classification in file.by_type("IfcClassification"):
        if classification.Name == OMNICLASS_TABLE_22_NAME:
            return classification
    return file.create_entity(
        "IfcClassification",
        Source=OMNICLASS_TABLE_22_SOURCE,
        Name=OMNICLASS_TABLE_22_NAME,
        Description="OmniClass Construction Classification System — Table 22 (Work Results)",
    )


def _get_or_create_classification_reference(
    file: ifcopenshell.file, code: str, title: str
) -> ifcopenshell.entity_instance:
    """Return the IfcClassificationReference for ``code`` under OmniClass Table 22, creating it if absent."""
    classification = _get_or_create_omniclass_table_22(file)
    for reference in file.by_type("IfcClassificationReference"):
        if (
            reference.Identification == code
            and reference.ReferencedSource is not None
            and reference.ReferencedSource.id() == classification.id()
        ):
            return reference
    return file.create_entity(
        "IfcClassificationReference",
        Identification=code,
        Name=title,
        ReferencedSource=classification,
    )


def apply_omniclass_classification(
    file: ifcopenshell.file,
    product: ifcopenshell.entity_instance,
    code: str,
    title: str,
) -> ifcopenshell.entity_instance:
    """Associate ``product`` with the OmniClass Table 22 reference for ``code``.

    Idempotent across products: an existing IfcRelAssociatesClassification
    against the matching IfcClassificationReference is extended with the
    new product (de-duplicated). A new rel is created when none exists.

    :returns: the IfcRelAssociatesClassification (existing or newly created).
    """
    reference = _get_or_create_classification_reference(file, code, title)
    for rel in file.by_type("IfcRelAssociatesClassification"):
        if rel.RelatingClassification.id() != reference.id():
            continue
        if product in rel.RelatedObjects:
            return rel
        rel.RelatedObjects = list(rel.RelatedObjects) + [product]
        return rel
    return file.create_entity(
        "IfcRelAssociatesClassification",
        GlobalId=ifcopenshell.guid.new(),
        RelatedObjects=[product],
        RelatingClassification=reference,
    )

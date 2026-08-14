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

"""Internal helpers shared across the grading API.

Provides:

- :func:`_resolve_site` — auto-resolve an IfcSite when callers leave the
  ``site`` arg as None. Raises ValueError if no IfcSite exists.
- :func:`identity_placement` — build an IfcLocalPlacement at the project
  origin. Used by every IfcEarthworksFill / IfcEarthworksCut authored by
  the API.
- :func:`attach_earthworks_fill_common` — author Pset_EarthworksFillCommon
  with ``Status="NEW"`` so the pset is schema-valid (HasProperties [1:?]).
- :func:`to_point_list` — coerce a numpy array or list-of-tuples to a
  list of ``(x, y, z)`` float tuples.
- :func:`compute_bounding_box` — derive ``(min_xyz, max_xyz)`` from a
  point cloud, nudging zero-length axes upward to satisfy
  IfcPositiveLengthMeasure.
- :func:`aggregate_under` — idempotent IfcRelAggregates author/extend.
- :func:`apply_omniclass_classification` — idempotent OmniClass Table 22
  classification author/extend.
"""

from __future__ import annotations

from typing import Optional, Sequence

import ifcopenshell
import ifcopenshell.api.pset
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


def identity_placement(file: ifcopenshell.file) -> ifcopenshell.entity_instance:
    """Build an :class:`IfcLocalPlacement` at the project origin (0, 0, 0).

    Earthwork products use identity placement per spec §2.8 — absolute world
    positioning is handled by :class:`IfcMapConversion` at the project level,
    not by per-product local transforms. Every :class:`IfcEarthworksFill`,
    :class:`IfcEarthworksCut`, and :class:`IfcGeographicElement` authored by
    the Saikei APIs uses a fresh identity placement.
    """
    return file.create_entity(
        "IfcLocalPlacement",
        RelativePlacement=file.create_entity(
            "IfcAxis2Placement3D",
            Location=file.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0)),
        ),
    )


def attach_earthworks_fill_common(
    file: ifcopenshell.file, fill: ifcopenshell.entity_instance
) -> ifcopenshell.entity_instance:
    """Attach ``Pset_EarthworksFillCommon`` with ``Status="NEW"`` to ``fill``.

    The minimum-property write is intentional: IFC's
    ``IfcPropertySet.HasProperties`` cardinality is ``[1:?]``, so an empty
    pset is schema-invalid. ``Status="NEW"`` is the lightest legal default;
    callers can override or extend via ``ifcopenshell.api.pset.edit_pset``.

    :returns: the created :class:`IfcPropertySet`.
    """
    pset = ifcopenshell.api.pset.add_pset(file, product=fill, name="Pset_EarthworksFillCommon")
    ifcopenshell.api.pset.edit_pset(file, pset=pset, properties={"Status": "NEW"})
    return pset


def to_point_list(
    points: Sequence[Sequence[float]],
) -> list[tuple[float, float, float]]:
    """Coerce a ``(N, 3)`` numpy array or sequence of triples to a list of float tuples.

    Numpy is a soft dependency: this helper accepts either array-like input
    and emits the plain-Python form IFC entity authoring expects.
    """
    return [(float(p[0]), float(p[1]), float(p[2])) for p in points]


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


def aggregate_under(
    file: ifcopenshell.file,
    parent: ifcopenshell.entity_instance,
    child: ifcopenshell.entity_instance,
) -> ifcopenshell.entity_instance:
    """Make ``child`` an aggregation child of ``parent`` via :class:`IfcRelAggregates`.

    Idempotent: if ``parent`` already has an :class:`IfcRelAggregates` with
    ``RelatingObject == parent``, ``child`` is appended (de-duplicated)
    rather than creating a new rel. Returns the rel (existing or newly
    created).
    """
    for rel in parent.IsDecomposedBy or []:
        if rel.is_a("IfcRelAggregates") and rel.RelatingObject.id() == parent.id():
            if child.id() not in {c.id() for c in rel.RelatedObjects}:
                rel.RelatedObjects = list(rel.RelatedObjects) + [child]
            return rel
    return file.create_entity(
        "IfcRelAggregates",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=parent,
        RelatedObjects=[child],
    )


def compute_bounding_box(
    points: list[tuple[float, float, float]],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Return ``(min_xyz, max_xyz)`` for ``points``, nudging zero-length axes upward.

    IFC's :class:`IfcBoundingBox` requires :class:`IfcPositiveLengthMeasure`
    for ``XDim``/``YDim``/``ZDim``, so any axis where ``max == min`` is
    bumped by a small epsilon.
    """
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    min_xyz = (min(xs), min(ys), min(zs))
    max_xyz = (max(xs), max(ys), max(zs))
    epsilon = 1e-6
    max_xyz = (
        max_xyz[0] if max_xyz[0] > min_xyz[0] else min_xyz[0] + epsilon,
        max_xyz[1] if max_xyz[1] > min_xyz[1] else min_xyz[1] + epsilon,
        max_xyz[2] if max_xyz[2] > min_xyz[2] else min_xyz[2] + epsilon,
    )
    return min_xyz, max_xyz


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

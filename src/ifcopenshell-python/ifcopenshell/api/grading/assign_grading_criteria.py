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

"""Bind a grading-criteria template to a group as a concrete IfcPropertySet."""

from __future__ import annotations

from typing import Optional

import ifcopenshell
import ifcopenshell.guid

from .create_grading_criteria_template import (
    ENUMERATION_VALUES,
    PSET_TEMPLATE_NAME,
)

ALLOWED_TARGET_KINDS = frozenset(ENUMERATION_VALUES)


def _find_existing_pset(
    group: ifcopenshell.entity_instance,
) -> Optional[ifcopenshell.entity_instance]:
    """Return the IfcPropertySet of name ``Pset_SaikeiGradingCriteria`` attached to group, or None."""
    for rel in group.IsDefinedBy or []:
        if not rel.is_a("IfcRelDefinesByProperties"):
            continue
        pset = rel.RelatingPropertyDefinition
        if (
            pset is not None
            and pset.is_a("IfcPropertySet")
            and pset.Name == PSET_TEMPLATE_NAME
        ):
            return pset
    return None


def _resolve_target_kind_enumeration(
    criteria_template: ifcopenshell.entity_instance,
) -> ifcopenshell.entity_instance:
    """Pull the IfcPropertyEnumeration off the template's TargetKind child."""
    for property_template in criteria_template.HasPropertyTemplates or []:
        if property_template.Name == "TargetKind":
            enumeration = property_template.Enumerators
            if enumeration is None:
                raise ValueError(
                    "criteria template's TargetKind property template has no Enumerators set"
                )
            return enumeration
    raise ValueError("criteria template is missing the TargetKind property template")


def _build_property_entities(
    file: ifcopenshell.file,
    *,
    target_kind: str,
    target_reference: Optional[str],
    cut_slope: float,
    fill_slope: float,
    max_distance: Optional[float],
    retaining_wall_at_limit: bool,
    target_kind_enumeration: ifcopenshell.entity_instance,
) -> list[ifcopenshell.entity_instance]:
    """Build the IfcSimpleProperty entities that go into the pset's HasProperties."""
    properties: list[ifcopenshell.entity_instance] = []

    properties.append(
        file.create_entity(
            "IfcPropertyEnumeratedValue",
            Name="TargetKind",
            EnumerationValues=[file.create_entity("IfcLabel", target_kind)],
            EnumerationReference=target_kind_enumeration,
        )
    )
    if target_reference is not None:
        properties.append(
            file.create_entity(
                "IfcPropertySingleValue",
                Name="TargetReference",
                NominalValue=file.create_entity("IfcLabel", target_reference),
            )
        )
    properties.append(
        file.create_entity(
            "IfcPropertySingleValue",
            Name="CutSlope",
            NominalValue=file.create_entity("IfcPositiveRatioMeasure", float(cut_slope)),
        )
    )
    properties.append(
        file.create_entity(
            "IfcPropertySingleValue",
            Name="FillSlope",
            NominalValue=file.create_entity("IfcPositiveRatioMeasure", float(fill_slope)),
        )
    )
    if max_distance is not None:
        properties.append(
            file.create_entity(
                "IfcPropertySingleValue",
                Name="MaxDistance",
                NominalValue=file.create_entity(
                    "IfcPositiveLengthMeasure", float(max_distance)
                ),
            )
        )
    properties.append(
        file.create_entity(
            "IfcPropertySingleValue",
            Name="RetainingWallAtLimit",
            NominalValue=file.create_entity("IfcBoolean", bool(retaining_wall_at_limit)),
        )
    )
    return properties


def _link_pset_to_template(
    file: ifcopenshell.file,
    pset: ifcopenshell.entity_instance,
    template: ifcopenshell.entity_instance,
) -> ifcopenshell.entity_instance:
    """Author or extend the IfcRelDefinesByTemplate that ties this pset to its template."""
    for rel in file.by_type("IfcRelDefinesByTemplate"):
        if rel.RelatingTemplate.id() == template.id():
            if pset not in rel.RelatedPropertySets:
                rel.RelatedPropertySets = list(rel.RelatedPropertySets) + [pset]
            return rel
    return file.create_entity(
        "IfcRelDefinesByTemplate",
        GlobalId=ifcopenshell.guid.new(),
        RelatedPropertySets=[pset],
        RelatingTemplate=template,
    )


def assign_grading_criteria(
    file: ifcopenshell.file,
    group: ifcopenshell.entity_instance,
    criteria_template: ifcopenshell.entity_instance,
    *,
    target_kind: str,
    cut_slope: float,
    fill_slope: float,
    target_reference: Optional[str] = None,
    max_distance: Optional[float] = None,
    retaining_wall_at_limit: bool = False,
    name: Optional[str] = None,
) -> ifcopenshell.entity_instance:
    """Bind a :class:`IfcPropertySetTemplate` to a grading group with concrete values.

    Authors an :class:`IfcPropertySet` whose ``Name`` matches the template
    (``Pset_SaikeiGradingCriteria`` by default), wires it to the template
    via :class:`IfcRelDefinesByTemplate`, and attaches it to the group via
    :class:`IfcRelDefinesByProperties`. Re-assigning to the same group
    updates the existing pset's values in place rather than creating a
    duplicate.

    The six properties match the template structure authored by
    :func:`create_grading_criteria_template`:

    - ``TargetKind`` — :class:`IfcPropertyEnumeratedValue` with
      ``EnumerationReference`` pointing at the template's
      ``SaikeiGradingTargetKind`` enumeration. The supplied ``target_kind``
      must be one of the four enumerated values.
    - ``TargetReference`` — :class:`IfcPropertySingleValue` (``IfcLabel``).
      Heterogeneous content depending on ``target_kind``: for ``surface``
      it is the GUID of the target :class:`IfcGeographicElement`; for
      ``elevation`` and ``relative_elevation`` it is a stringified numeric
      elevation; for ``distance`` it is a stringified numeric distance.
      Callers stringify; readers parse based on ``TargetKind``. Omitted from
      the pset entirely when ``None``.
    - ``CutSlope``, ``FillSlope`` — :class:`IfcPositiveRatioMeasure` (H:V).
      Must be strictly positive (schema constraint).
    - ``MaxDistance`` — :class:`IfcPositiveLengthMeasure`. Optional;
      omitted entirely when ``None``.
    - ``RetainingWallAtLimit`` — :class:`IfcBoolean`.

    :param file: the IFC file to author into
    :param group: the :class:`IfcGroup` to bind the criteria to (any
        ``IfcGroup`` is accepted; the function does not enforce
        ``ObjectType="GradingGroup"``)
    :param criteria_template: the :class:`IfcPropertySetTemplate` produced
        by :func:`create_grading_criteria_template`
    :param target_kind: one of ``surface``, ``elevation``,
        ``relative_elevation``, ``distance``
    :param cut_slope: cut slope ratio (H:V); must be > 0
    :param fill_slope: fill slope ratio (H:V); must be > 0
    :param target_reference: optional reference value paired with
        ``target_kind``; see above for encoding
    :param max_distance: optional daylight cap; must be > 0 if supplied
    :param retaining_wall_at_limit: whether to insert a retaining wall
        when ``max_distance`` is reached before daylighting
    :param name: optional override for ``IfcPropertySet.Name``; defaults to
        the template's name (``Pset_SaikeiGradingCriteria``)
    :returns: the :class:`IfcPropertySet` carrying the values (existing or
        newly created)
    :raises ValueError: if ``group`` is not an :class:`IfcGroup`, if
        ``criteria_template`` is not the ``Pset_SaikeiGradingCriteria``
        template, if ``target_kind`` is not one of the allowed values, or
        if ``cut_slope``/``fill_slope``/``max_distance`` violate their
        positivity constraints
    """
    if not group.is_a("IfcGroup"):
        raise ValueError(f"group must be an IfcGroup, got {group.is_a()} #{group.id()}")
    if (
        not criteria_template.is_a("IfcPropertySetTemplate")
        or criteria_template.Name != PSET_TEMPLATE_NAME
    ):
        raise ValueError(
            f"criteria_template must be a {PSET_TEMPLATE_NAME} IfcPropertySetTemplate "
            f"(got {criteria_template.is_a()} Name={criteria_template.Name!r})"
        )
    if target_kind not in ALLOWED_TARGET_KINDS:
        raise ValueError(
            f"target_kind must be one of {sorted(ALLOWED_TARGET_KINDS)}, got {target_kind!r}"
        )
    if cut_slope <= 0:
        raise ValueError(f"cut_slope must be > 0 (IfcPositiveRatioMeasure), got {cut_slope}")
    if fill_slope <= 0:
        raise ValueError(f"fill_slope must be > 0 (IfcPositiveRatioMeasure), got {fill_slope}")
    if max_distance is not None and max_distance <= 0:
        raise ValueError(
            f"max_distance must be > 0 (IfcPositiveLengthMeasure), got {max_distance}"
        )

    target_kind_enumeration = _resolve_target_kind_enumeration(criteria_template)
    pset_name = name if name is not None else PSET_TEMPLATE_NAME
    properties = _build_property_entities(
        file,
        target_kind=target_kind,
        target_reference=target_reference,
        cut_slope=cut_slope,
        fill_slope=fill_slope,
        max_distance=max_distance,
        retaining_wall_at_limit=retaining_wall_at_limit,
        target_kind_enumeration=target_kind_enumeration,
    )

    existing_pset = _find_existing_pset(group)
    if existing_pset is not None:
        # Update in place: drop the previous property entities, install new ones.
        for old_prop in existing_pset.HasProperties or []:
            file.remove(old_prop)
        existing_pset.HasProperties = properties
        existing_pset.Name = pset_name
        _link_pset_to_template(file, existing_pset, criteria_template)
        return existing_pset

    pset = file.create_entity(
        "IfcPropertySet",
        GlobalId=ifcopenshell.guid.new(),
        Name=pset_name,
        HasProperties=properties,
    )
    file.create_entity(
        "IfcRelDefinesByProperties",
        GlobalId=ifcopenshell.guid.new(),
        RelatedObjects=[group],
        RelatingPropertyDefinition=pset,
    )
    _link_pset_to_template(file, pset, criteria_template)
    return pset

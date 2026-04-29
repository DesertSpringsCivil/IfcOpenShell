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

"""Author the project-scope IfcPropertySetTemplate for Saikei grading criteria.

The template defines the parameter shape of ``Pset_SaikeiGradingCriteria``.
Instances of the pset (with concrete values) are authored against grading
groups by :func:`assign_grading_criteria`.

This is a singleton template: every file has at most one
``Pset_SaikeiGradingCriteria`` template. The function is idempotent — calling
it twice returns the same template entity.
"""

from __future__ import annotations

from typing import Optional

import ifcopenshell
import ifcopenshell.guid

PSET_TEMPLATE_NAME = "Pset_SaikeiGradingCriteria"
ENUMERATION_NAME = "SaikeiGradingTargetKind"
ENUMERATION_VALUES: tuple[str, ...] = (
    "surface",
    "elevation",
    "relative_elevation",
    "distance",
)


def _get_or_create_target_kind_enumeration(
    file: ifcopenshell.file,
) -> ifcopenshell.entity_instance:
    """Return the SaikeiGradingTargetKind enumeration, creating it if absent."""
    for enumeration in file.by_type("IfcPropertyEnumeration"):
        if enumeration.Name == ENUMERATION_NAME:
            return enumeration
    return file.create_entity(
        "IfcPropertyEnumeration",
        Name=ENUMERATION_NAME,
        EnumerationValues=[file.create_entity("IfcLabel", v) for v in ENUMERATION_VALUES],
    )


def _create_simple_property_template(
    file: ifcopenshell.file,
    *,
    name: str,
    description: str,
    template_type: str,
    primary_measure_type: Optional[str] = None,
    enumerators: Optional[ifcopenshell.entity_instance] = None,
) -> ifcopenshell.entity_instance:
    """Build one IfcSimplePropertyTemplate entry."""
    return file.create_entity(
        "IfcSimplePropertyTemplate",
        GlobalId=ifcopenshell.guid.new(),
        Name=name,
        Description=description,
        TemplateType=template_type,
        PrimaryMeasureType=primary_measure_type,
        Enumerators=enumerators,
        AccessState="READWRITE",
    )


def _find_existing_template(
    file: ifcopenshell.file,
) -> Optional[ifcopenshell.entity_instance]:
    for template in file.by_type("IfcPropertySetTemplate"):
        if template.Name == PSET_TEMPLATE_NAME:
            return template
    return None


def create_grading_criteria_template(
    file: ifcopenshell.file,
) -> ifcopenshell.entity_instance:
    """Create or return the project's :class:`IfcPropertySetTemplate` for grading criteria.

    The template defines the structure of ``Pset_SaikeiGradingCriteria``:

    - ``TargetKind`` — enumerated label, one of ``surface``, ``elevation``,
      ``relative_elevation``, ``distance``. Backed by an
      :class:`IfcPropertyEnumeration` named ``SaikeiGradingTargetKind`` so
      consumers can discover the allowed values from the template alone.
    - ``TargetReference`` — free-form label. For ``TargetKind=surface``
      this is the target surface's GUID; for the elevation / distance
      variants it is the numeric value stringified. Single-property type
      simplifies template authoring and instance-side parsing.
    - ``CutSlope`` — positive ratio measure (H:V form).
    - ``FillSlope`` — positive ratio measure (H:V form).
    - ``MaxDistance`` — positive length measure, optional.
    - ``RetainingWallAtLimit`` — boolean.

    The template's ``ApplicableEntity`` is ``IfcGroup`` — instances of this
    pset attach to grading groups. ``TemplateType`` is
    ``PSET_OCCURRENCEDRIVEN`` (each occurrence carries its own values, no
    type inheritance).

    The function is idempotent: a second call on the same file returns the
    existing template entity unchanged.

    :param file: the IFC file to author into
    :returns: the :class:`IfcPropertySetTemplate` for ``Pset_SaikeiGradingCriteria``
    """
    existing = _find_existing_template(file)
    if existing is not None:
        return existing

    target_kind_enum = _get_or_create_target_kind_enumeration(file)

    target_kind_template = _create_simple_property_template(
        file,
        name="TargetKind",
        description="Kind of grading target: surface, elevation, relative_elevation, or distance.",
        template_type="P_ENUMERATEDVALUE",
        enumerators=target_kind_enum,
    )
    target_reference_template = _create_simple_property_template(
        file,
        name="TargetReference",
        description=(
            "Reference value paired with TargetKind: GUID of the target IfcGeographicElement "
            "for kind=surface; numeric (stringified) for the elevation / distance variants."
        ),
        template_type="P_SINGLEVALUE",
        primary_measure_type="IfcLabel",
    )
    cut_slope_template = _create_simple_property_template(
        file,
        name="CutSlope",
        description="Cut slope ratio (H:V); typical values 1.5–3.0.",
        template_type="P_SINGLEVALUE",
        primary_measure_type="IfcPositiveRatioMeasure",
    )
    fill_slope_template = _create_simple_property_template(
        file,
        name="FillSlope",
        description="Fill slope ratio (H:V); typical values 2.0–4.0.",
        template_type="P_SINGLEVALUE",
        primary_measure_type="IfcPositiveRatioMeasure",
    )
    max_distance_template = _create_simple_property_template(
        file,
        name="MaxDistance",
        description=(
            "Daylight cap — maximum horizontal projection distance before the slope is "
            "terminated (or a retaining wall inserted if RetainingWallAtLimit is true). "
            "Omit the property entirely for unlimited."
        ),
        template_type="P_SINGLEVALUE",
        primary_measure_type="IfcPositiveLengthMeasure",
    )
    retaining_wall_template = _create_simple_property_template(
        file,
        name="RetainingWallAtLimit",
        description="Whether to insert a retaining wall when MaxDistance is reached before daylighting.",
        template_type="P_SINGLEVALUE",
        primary_measure_type="IfcBoolean",
    )

    return file.create_entity(
        "IfcPropertySetTemplate",
        GlobalId=ifcopenshell.guid.new(),
        Name=PSET_TEMPLATE_NAME,
        Description=(
            "Saikei grading criteria — slope projection rules. Instances attach to "
            "IfcGroup ObjectType='GradingGroup' via IfcRelDefinesByProperties + "
            "IfcRelDefinesByTemplate."
        ),
        TemplateType="PSET_OCCURRENCEDRIVEN",
        ApplicableEntity="IfcGroup",
        HasPropertyTemplates=[
            target_kind_template,
            target_reference_template,
            cut_slope_template,
            fill_slope_template,
            max_distance_template,
            retaining_wall_template,
        ],
    )

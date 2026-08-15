# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2025 Thomas Krijnen <thomas@aecgeeks.com>
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

from collections.abc import Sequence

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.alignment
import ifcopenshell.util.alignment
from ifcopenshell import entity_instance
from ifcopenshell.api.alignment._create_offset_curve_representation import (
    _create_offset_curve_representation,
)


def create_as_offset_curve(
    file: ifcopenshell.file,
    name: str,
    offsets: Sequence[entity_instance],
    start_station: float = 0.0,
) -> entity_instance:
    """
    Creates a new IfcAlignment with an IfcOffsetCurveByDistances representation.

    The IfcAlignment is aggreated to IfcProject

    :param file:
    :param name: name assigned to IfcAlignment.Name
    :param offsets: offsets from the basis curve that defines the offset curve, expected to be IfcPointByDistanceExpression.
        All offsets must reference the same BasisCurve, and that basis must be
        an IfcCompositeCurve (which includes IfcGradientCurve and
        IfcSegmentedReferenceCurve) — the rules proposed in buildingSMART
        IFC4.x-development #733, adopted early so authored files stay valid
        under the likely future constraints.
    :param start_station: station value at the start of the alignment
    :return: Returns an IfcAlignment
    """
    if not offsets:
        raise ValueError("At least one offset point is required")

    # Proposed WHERE rules from bSI IFC4.x-development #733, validated at
    # authoring time: one shared basis curve, restricted to the composite
    # alignment curve types.
    basis_curves = {offset.BasisCurve for offset in offsets}
    if len(basis_curves) != 1:
        raise ValueError("All offsets must reference the same BasisCurve (bSI IFC4.x-development #733)")
    basis_curve = next(iter(basis_curves))
    if basis_curve is None or not basis_curve.is_a("IfcCompositeCurve"):
        found = basis_curve.is_a() if basis_curve is not None else "None"
        raise ValueError(
            "BasisCurve must be an IfcCompositeCurve, IfcGradientCurve, or "
            f"IfcSegmentedReferenceCurve, got {found} (bSI IFC4.x-development #733)"
        )

    alignment = file.createIfcAlignment(
        GlobalId=ifcopenshell.guid.new(),
        Name=name,
    )

    _create_offset_curve_representation(file, alignment, offsets)

    # establish the alignment's stationing scheme, same as create() does for
    # start_station — including the "<alignment name> <station>" naming
    # convention introduced upstream (307836049)
    referent_name = f"{name} {ifcopenshell.util.alignment.station_as_string(file, start_station)}"
    ifcopenshell.api.alignment.add_stationing_referent(file, referent_name, alignment, 0.0, start_station)

    # IFC 4.1.4.1.1 Alignment Aggregation To Project
    project = file.by_type("IfcProject")[0]
    if project:
        ifcopenshell.api.aggregate.assign_object(file, products=[alignment], relating_object=project)

    return alignment

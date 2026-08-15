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

import ifcopenshell
import ifcopenshell.api.alignment
import ifcopenshell.api.unit
import ifcopenshell.util.element


def test_create_as_offset_curve_honors_start_station_with_a_stationing_referent():
    # create_as_offset_curve() accepted start_station but silently dropped it -- unlike every
    # other create path (create(), create_by_pi_method()), it never established the alignment's
    # stationing referent.
    file = ifcopenshell.file(schema="IFC4X3")
    project = file.createIfcProject(GlobalId=ifcopenshell.guid.new(), Name="Test")
    length = ifcopenshell.api.unit.add_si_unit(file, unit_type="LENGTHUNIT")
    ifcopenshell.api.unit.assign_unit(file, units=[length])

    # the basis alignment only needs a real (if empty) Axis representation for
    # IfcPointByDistanceExpression.BasisCurve to reference -- no real segments needed.
    basis_alignment = ifcopenshell.api.alignment.create(file, "Basis", include_geometry=True)
    basis_curve = ifcopenshell.api.alignment.get_curve(basis_alignment)
    assert basis_curve.is_a("IfcCompositeCurve")

    offsets = [
        file.createIfcPointByDistanceExpression(
            DistanceAlong=file.createIfcLengthMeasure(0.0), OffsetLateral=10.0, BasisCurve=basis_curve
        ),
    ]

    offset_alignment = ifcopenshell.api.alignment.create_as_offset_curve(file, "Offset", offsets, start_station=1000.0)

    curve = ifcopenshell.api.alignment.get_curve(offset_alignment)
    assert curve.is_a("IfcOffsetCurveByDistances")

    # the referent must be created even though IfcOffsetCurveByDistances isn't a curve type that
    # add_stationing_referent() can build a linear placement on top of -- it falls back to a plain
    # IfcLocalPlacement, same as when there's no representation at all.
    referent_nest = ifcopenshell.api.alignment.get_stationing_nest(file, offset_alignment)
    assert referent_nest is not None
    assert len(referent_nest.RelatedObjects) == 1

    referent = referent_nest.RelatedObjects[0]
    assert referent.is_a("IfcReferent")
    assert referent.PredefinedType == "STATION"
    assert referent.ObjectPlacement is not None
    assert referent.ObjectPlacement.is_a("IfcLocalPlacement")
    assert ifcopenshell.util.element.get_pset(referent, name="Pset_Stationing", prop="Station") == 1000.0


def test_create_as_offset_curve_default_start_station_is_zero():
    file = ifcopenshell.file(schema="IFC4X3")
    project = file.createIfcProject(GlobalId=ifcopenshell.guid.new(), Name="Test")
    length = ifcopenshell.api.unit.add_si_unit(file, unit_type="LENGTHUNIT")
    ifcopenshell.api.unit.assign_unit(file, units=[length])

    basis_alignment = ifcopenshell.api.alignment.create(file, "Basis", include_geometry=True)
    basis_curve = ifcopenshell.api.alignment.get_curve(basis_alignment)

    offsets = [
        file.createIfcPointByDistanceExpression(
            DistanceAlong=file.createIfcLengthMeasure(0.0), OffsetLateral=10.0, BasisCurve=basis_curve
        ),
    ]

    offset_alignment = ifcopenshell.api.alignment.create_as_offset_curve(file, "Offset", offsets)

    referent_nest = ifcopenshell.api.alignment.get_stationing_nest(file, offset_alignment)
    assert referent_nest is not None
    referent = referent_nest.RelatedObjects[0]
    assert ifcopenshell.util.element.get_pset(referent, name="Pset_Stationing", prop="Station") == 0.0


def _make_file_with_basis():
    file = ifcopenshell.file(schema="IFC4X3")
    file.createIfcProject(GlobalId=ifcopenshell.guid.new(), Name="Test")
    length = ifcopenshell.api.unit.add_si_unit(file, unit_type="LENGTHUNIT")
    ifcopenshell.api.unit.assign_unit(file, units=[length])
    basis_alignment = ifcopenshell.api.alignment.create(file, "Basis", include_geometry=True)
    return file, ifcopenshell.api.alignment.get_curve(basis_alignment)


def test_create_as_offset_curve_referent_name_includes_alignment_name():
    # "<alignment name> <station>" convention, matching create() and
    # create_as_polyline() after upstream 307836049.
    file, basis_curve = _make_file_with_basis()
    offsets = [
        file.createIfcPointByDistanceExpression(
            DistanceAlong=file.createIfcLengthMeasure(0.0), OffsetLateral=10.0, BasisCurve=basis_curve
        ),
    ]
    offset_alignment = ifcopenshell.api.alignment.create_as_offset_curve(file, "Offset", offsets, start_station=1000.0)
    referent = ifcopenshell.api.alignment.get_stationing_nest(file, offset_alignment).RelatedObjects[0]
    assert referent.Name == "Offset 1+000.000"


def test_create_as_offset_curve_refuses_mixed_basis_curves():
    # Proposed rule from bSI IFC4.x-development #733: all offsets must share
    # one BasisCurve.
    file, basis_curve = _make_file_with_basis()
    other_alignment = ifcopenshell.api.alignment.create(file, "Other", include_geometry=True)
    other_curve = ifcopenshell.api.alignment.get_curve(other_alignment)
    offsets = [
        file.createIfcPointByDistanceExpression(
            DistanceAlong=file.createIfcLengthMeasure(0.0), OffsetLateral=10.0, BasisCurve=basis_curve
        ),
        file.createIfcPointByDistanceExpression(
            DistanceAlong=file.createIfcLengthMeasure(100.0), OffsetLateral=10.0, BasisCurve=other_curve
        ),
    ]
    try:
        ifcopenshell.api.alignment.create_as_offset_curve(file, "Offset", offsets)
        raise AssertionError("expected ValueError for mixed basis curves")
    except ValueError as e:
        assert "#733" in str(e)


def test_create_as_offset_curve_refuses_non_composite_basis():
    # Proposed rule from bSI IFC4.x-development #733: basis restricted to the
    # composite alignment curve types.
    file, _ = _make_file_with_basis()
    polyline = file.createIfcPolyline(
        Points=[file.createIfcCartesianPoint((0.0, 0.0)), file.createIfcCartesianPoint((100.0, 0.0))]
    )
    offsets = [
        file.createIfcPointByDistanceExpression(
            DistanceAlong=file.createIfcLengthMeasure(0.0), OffsetLateral=10.0, BasisCurve=polyline
        ),
    ]
    try:
        ifcopenshell.api.alignment.create_as_offset_curve(file, "Offset", offsets)
        raise AssertionError("expected ValueError for non-composite basis")
    except ValueError as e:
        assert "IfcCompositeCurve" in str(e)


def test_create_as_offset_curve_refuses_empty_offsets():
    file, _ = _make_file_with_basis()
    try:
        ifcopenshell.api.alignment.create_as_offset_curve(file, "Offset", [])
        raise AssertionError("expected ValueError for empty offsets")
    except ValueError:
        pass


test_create_as_offset_curve_honors_start_station_with_a_stationing_referent()
test_create_as_offset_curve_default_start_station_is_zero()
test_create_as_offset_curve_referent_name_includes_alignment_name()
test_create_as_offset_curve_refuses_mixed_basis_curves()
test_create_as_offset_curve_refuses_non_composite_basis()
test_create_as_offset_curve_refuses_empty_offsets()

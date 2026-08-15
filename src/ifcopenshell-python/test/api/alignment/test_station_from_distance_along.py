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

from typing import Optional

import pytest

import ifcopenshell.api.alignment
import ifcopenshell.api.context
import ifcopenshell.api.pset
import ifcopenshell.api.unit
import ifcopenshell.guid

try:
    ifcopenshell.file(schema="IFC4X3")
    IFC4X3_AVAILABLE = True
except RuntimeError:
    IFC4X3_AVAILABLE = False


def _setup_file() -> ifcopenshell.file:
    file = ifcopenshell.file(schema="IFC4X3")
    project = file.createIfcProject(GlobalId=ifcopenshell.guid.new(), Name="Test")
    length = ifcopenshell.api.unit.add_si_unit(file, unit_type="LENGTHUNIT")
    ifcopenshell.api.unit.assign_unit(file, units=[length])
    ifcopenshell.api.context.add_context(file, context_type="Model")
    return file


def _add_semantic_stationing_referent(
    file: ifcopenshell.file,
    alignment: ifcopenshell.entity_instance,
    name: str,
    distance_along: float,
    station: float,
    incoming_station: Optional[float] = None,
) -> ifcopenshell.entity_instance:
    """
    Test-only stand-in for ifcopenshell.api.alignment.add_stationing_referent.

    Builds the same IfcReferent / IfcLinearPlacement / Pset_Stationing structure that
    add_stationing_referent builds, and nests it into the alignment's stationing nest the same
    way, but skips the update_fallback_position() call. That call resolves the referent's
    IfcLinearPlacement to a CartesianPosition via ifcopenshell.util.placement.get_local_placement,
    which in turn invokes the geometry engine (ifcopenshell.geom.create_shape) once the
    alignment's composite curve already carries real segments - unavailable in this test
    environment ("No geometry mapping registered for ifc4x3_add2").

    Skipping it is safe for these tests: distance_along_from_station and
    station_from_distance_along only ever read DistanceAlong off the placement and the
    Pset_Stationing properties. Neither reads CartesianPosition.
    """
    curve = ifcopenshell.api.alignment.get_basis_curve(alignment)
    object_placement = file.createIfcLinearPlacement(
        RelativePlacement=file.createIfcAxis2PlacementLinear(
            Location=file.createIfcPointByDistanceExpression(
                DistanceAlong=file.createIfcLengthMeasure(distance_along),
                OffsetLateral=None,
                OffsetVertical=None,
                OffsetLongitudinal=None,
                BasisCurve=curve,
            )
        ),
    )

    referent = file.createIfcReferent(
        GlobalId=ifcopenshell.guid.new(),
        OwnerHistory=None,
        Name=name,
        Description=None,
        ObjectType=None,
        ObjectPlacement=object_placement,
        Representation=None,
        PredefinedType="STATION",
    )

    properties = {"Station": station}
    if incoming_station is not None:
        properties["IncomingStation"] = incoming_station

    pset_stationing = ifcopenshell.api.pset.add_pset(file, product=referent, name="Pset_Stationing")
    ifcopenshell.api.pset.edit_pset(file, pset=pset_stationing, properties=properties)

    nest = ifcopenshell.api.alignment.get_stationing_nest(file, alignment)
    if nest is None:
        nest = file.createIfcRelNests(
            GlobalId=ifcopenshell.guid.new(), RelatingObject=alignment, RelatedObjects=(referent,)
        )
    else:
        nest.RelatedObjects += (referent,)

    return referent


@pytest.mark.skipif(not IFC4X3_AVAILABLE, reason="IFC4X3 not available")
def test_station_from_distance_along_with_no_stationing():
    # a bare alignment with no stationing referents at all - not even the implicit start-station
    # referent that ifcopenshell.api.alignment.create() would add. distance along is the station.
    file = _setup_file()
    alignment = file.createIfcAlignment(GlobalId=ifcopenshell.guid.new(), Name="A0")

    assert ifcopenshell.api.alignment.get_stationing_nest(file, alignment) is None
    assert ifcopenshell.api.alignment.station_from_distance_along(file, alignment, 250.0) == pytest.approx(250.0)
    assert ifcopenshell.api.alignment.station_from_distance_along(file, alignment, 0.0) == pytest.approx(0.0)


@pytest.mark.skipif(not IFC4X3_AVAILABLE, reason="IFC4X3 not available")
def test_station_from_distance_along_basic():
    # single start-station referent, no equations - exact inverse of distance_along_from_station's
    # own basic test (same start_station and distance/station pairing).
    file = _setup_file()
    alignment = ifcopenshell.api.alignment.create(file, "TestAlignment", start_station=10000.0)

    station_from_distance_along = ifcopenshell.api.alignment.station_from_distance_along
    distance_along_from_station = ifcopenshell.api.alignment.distance_along_from_station

    assert station_from_distance_along(file, alignment, 3883.96) == pytest.approx(13883.96)
    assert station_from_distance_along(file, alignment, 7525.36) == pytest.approx(17525.36)

    # round trip through the forward function
    for distance_along in (3883.96, 7525.36):
        station = station_from_distance_along(file, alignment, distance_along)
        assert distance_along_from_station(file, alignment, station) == pytest.approx(distance_along)

    # distance_along before the start referent's DistanceAlong (0.0) extrapolates backward
    assert station_from_distance_along(file, alignment, -100.0) == pytest.approx(9900.0)


@pytest.mark.skipif(not IFC4X3_AVAILABLE, reason="IFC4X3 not available")
def test_station_from_distance_along_with_station_equations():
    # Same station-equation values as the worked example reproduced in
    # test_distance_along_from_station.py's test_distance_along_from_station_with_station_equations
    # (IFC Alignment Geometry Implementation Guide, chapter 9.2.6): a gap equation (P3: incoming
    # 14+00.00, outgoing 17+00.00) and an overlap equation (P4: incoming 19+00.00, outgoing
    # 18+50.00). Built via create() + _add_semantic_stationing_referent instead of
    # create_by_pi_method() + add_stationing_referent(), since this environment's geometry engine
    # can't map ifc4x3_add2 shapes - see _add_semantic_stationing_referent's docstring. Only the
    # DistanceAlong bookkeeping matters here, not real curve shape.
    file = _setup_file()
    alignment = ifcopenshell.api.alignment.create(file, "TestAlignment", start_station=1000.0)

    _add_semantic_stationing_referent(
        file, alignment, "P3", distance_along=400.0, station=1700.0, incoming_station=1400.0
    )
    _add_semantic_stationing_referent(
        file, alignment, "P4", distance_along=600.0, station=1850.0, incoming_station=1900.0
    )

    station_from_distance_along = ifcopenshell.api.alignment.station_from_distance_along
    distance_along_from_station = ifcopenshell.api.alignment.distance_along_from_station

    # mirror image of distance_along_from_station's assertions on the same fixture
    assert station_from_distance_along(file, alignment, 300.0) == pytest.approx(1300.0)  # between P2 and P3
    assert station_from_distance_along(file, alignment, 500.0) == pytest.approx(1800.0)  # between P3 and P4
    assert station_from_distance_along(file, alignment, 675.0) == pytest.approx(1925.0)  # between P4 and P5
    assert station_from_distance_along(file, alignment, 625.0) == pytest.approx(1875.0)  # overlap zone, outgoing side

    # Round trip through distance_along_from_station, on both the gap side (300.0, 500.0) and the
    # overlap side (625.0, which lands in the range re-used by P4's overlap equation). Unlike
    # distance_along_from_station (which can return None for a station inside a gap, e.g. 1500.0),
    # station_from_distance_along is total: every distance along the alignment is a single
    # physical point with exactly one station, so there is no analogous "gap" case on this side.
    for distance_along in (300.0, 500.0, 675.0, 625.0):
        station = station_from_distance_along(file, alignment, distance_along)
        assert distance_along_from_station(file, alignment, station) == pytest.approx(distance_along)


test_station_from_distance_along_with_no_stationing()
test_station_from_distance_along_basic()
test_station_from_distance_along_with_station_equations()

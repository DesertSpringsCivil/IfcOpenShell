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
import ifcopenshell.util.element
from ifcopenshell import entity_instance


def _distance_along_of_referent(referent: entity_instance) -> float:
    placement = referent.ObjectPlacement
    if placement.is_a("IfcLinearPlacement"):
        return placement.RelativePlacement.Location.DistanceAlong.wrappedValue
    # IfcLocalPlacement fallback (e.g. semantic-only alignment, or the placement could not yet
    # be expressed relative to a basis curve) carries no DistanceAlong; it is only ever used for
    # the starting referent, at distance 0.0.
    return 0.0


def station_from_distance_along(file: ifcopenshell.file, alignment: entity_instance, distance_along: float) -> float:
    """
    Given a distance along the horizontal alignment, returns the station.

    This is the exact inverse of distance_along_from_station.

    If the alignment does not have stationing defined with an IfcReferent, the start of the
    alignment is assumed to be at station 0.0. That is, the distance along is the station.

    Station equations (where Pset_Stationing.IncomingStation is set on a referent) are taken into
    account. For each STATION referent nested to the alignment, DistanceAlong (D) and the outgoing
    station (S, i.e. Pset_Stationing.Station) are read off, sorted by DistanceAlong. The governing
    referent for the requested distance along is the last one whose DistanceAlong is less than or
    equal to it, and the station is computed as S + (distance_along - D) for that referent.

    Unlike distance_along_from_station, this function is total: every distance along the alignment
    corresponds to exactly one physical location, and therefore exactly one station, regardless of
    any station equations. Station equations only ever introduce gaps or overlaps in station space
    (some stations mapping to zero, or to two, distances along); distance along is never ambiguous.
    So, where distance_along_from_station can return None for a station that falls inside a gap,
    station_from_distance_along never returns None.

    Note that for a distance along that falls within the range re-used by a backward (overlap)
    station equation, the station returned here is still whichever value the forward equation
    arithmetic produces for that particular distance along - it does not attempt to disambiguate
    against the pre-equation occurrence of the same station value, because there is nothing to
    disambiguate: the distance along, unlike the station, is already unique.

    :param file:
    :param alignment: the alignment
    :param distance_along: distance along the horizontal alignment
    :return: station value

    Example:

    .. code:: python

        alignment = model.by_type("IfcAlignment")[0] # alignment with start station 1+00.00
        station = ifcopenshell.api.alignment.station_from_distance_along(model, alignment=alignment, distance_along=100.0)
        print(station) # 200.00
    """

    stationing_nest = ifcopenshell.api.alignment.get_stationing_nest(file, alignment)
    if stationing_nest is None:
        start_station = ifcopenshell.api.alignment.get_alignment_start_station(file, alignment)
        return distance_along + start_station

    stations = [
        (
            _distance_along_of_referent(referent),
            ifcopenshell.util.element.get_pset(referent, name="Pset_Stationing", prop="Station"),
        )
        for referent in stationing_nest.RelatedObjects
    ]
    stations.sort(key=lambda entry: entry[0])

    index = None
    for i, (referent_distance_along, outgoing_station) in enumerate(stations):
        if referent_distance_along <= distance_along:
            index = i

    if index is None:
        # distance_along precedes the first referent's DistanceAlong; extrapolate backward from it
        referent_distance_along, outgoing_station = stations[0]
        return outgoing_station + (distance_along - referent_distance_along)

    referent_distance_along, outgoing_station = stations[index]
    return outgoing_station + (distance_along - referent_distance_along)

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

# This file was generated with the assistance of an AI coding tool.

"""
Pure-solver tests for compound (PCC) and reverse (PRC) curves in the PI method solver: a
join_next=True element joins the curve at that PI directly to the curve at the next PI, at a
shared tangency point, with no intermediate tangent run.

These tests need no geometry engine: solve_horizontal_alignment_by_pi_method is pure Python/numpy.
"""

import math
import re

import pytest

import ifcopenshell.api.alignment


def _build_pcc_prc_hpoints(
    r1: float,
    delta1_deg: float,
    r2: float,
    delta2_deg: float,
    back_tangent_length: float = 1000.0,
    forward_tangent_length: float = 800.0,
) -> tuple[list[tuple[float, float]], float, float, float]:
    """
    Builds a POB/PI1/PI2/POE layout where the curve at PI1 (radius r1, deflection delta1_deg) and
    the curve at PI2 (radius r2, deflection delta2_deg) close exactly at a direct PI1-PI2 join,
    with no intermediate tangent run.

    Derivation: a plain circular curve's tangent length is T = R * tan(delta / 2), and PI-to-PC
    equals PI-to-PT for a curve with no spiral transitions. Placing PI1 and PI2 exactly T1 + T2
    apart, along the PI1 -> PI2 bearing implied by delta1, makes the two curves' tangent claims
    exactly consume the shared leg with nothing left over -- precisely the closure condition
    join_next enforces (T_out(1) + T_in(2) == |PI1 PI2|).

    :param r1: radius of the curve at PI1 (the join_next curve)
    :param delta1_deg: deflection angle at PI1, in degrees (positive = left turn)
    :param r2: radius of the curve at PI2 (the joined-into curve)
    :param delta2_deg: deflection angle at PI2, in degrees (positive = left turn)
    :param back_tangent_length: distance from POB to PI1
    :param forward_tangent_length: distance from PI2 to POE
    :return: (hpoints, T1, T2, pi_to_pi_distance)
    """
    delta1 = math.radians(delta1_deg)
    delta2 = math.radians(delta2_deg)
    t1 = abs(r1 * math.tan(delta1 / 2.0))
    t2 = abs(r2 * math.tan(delta2 / 2.0))
    pi_to_pi_distance = t1 + t2

    # back tangent (POB -> PI1) runs along the +X axis
    pob = (0.0, 0.0)
    pi1 = (back_tangent_length, 0.0)

    # PI1 -> PI2 bearing is delta1 off the back tangent bearing (0.0)
    bearing_1_to_2 = delta1
    pi2 = (
        pi1[0] + pi_to_pi_distance * math.cos(bearing_1_to_2),
        pi1[1] + pi_to_pi_distance * math.sin(bearing_1_to_2),
    )

    # PI2 -> POE bearing is delta2 off the PI1 -> PI2 bearing
    bearing_2_to_poe = bearing_1_to_2 + delta2
    poe = (
        pi2[0] + forward_tangent_length * math.cos(bearing_2_to_poe),
        pi2[1] + forward_tangent_length * math.sin(bearing_2_to_poe),
    )

    return [pob, pi1, pi2, poe], t1, t2, pi_to_pi_distance


def _assert_chain_continuous(segments) -> None:
    """Position and direction continuity between every consecutive pair of segments, < 1e-9."""
    for segment, next_segment in zip(segments[:-1], segments[1:]):
        end_x, end_y, end_direction = ifcopenshell.api.alignment.compute_horizontal_segment_end(segment)
        assert end_x == pytest.approx(next_segment.start_point[0], abs=1.0e-9)
        assert end_y == pytest.approx(next_segment.start_point[1], abs=1.0e-9)
        gap = math.atan2(
            math.sin(end_direction - next_segment.start_direction),
            math.cos(end_direction - next_segment.start_direction),
        )
        assert gap == pytest.approx(0.0, abs=1.0e-9)


def test_pcc_golden_case():
    """
    PCC (point of compound curvature): two same-direction circular curves, R1=600 then R2=300,
    joined directly at PI1-PI2 with no intermediate tangent run.

    Hand derivation (see also _build_pcc_prc_hpoints):
        delta1 = 60 deg, delta2 = 40 deg -- both left turns, same sign, so a compound curve.
        T1 = R1 * tan(delta1 / 2) = 600 * tan(30 deg) = 346.4101615137755
        T2 = R2 * tan(delta2 / 2) = 300 * tan(20 deg) = 109.19107027934464
        PI1-PI2 is constructed to be exactly T1 + T2 = 455.60123179312017 apart, so the curves'
        tangent claims close the leg exactly and no LINE segment separates the two arcs.
        Lc1 = R1 * delta1(rad) = 600 * 1.0471975511965976 = 628.3185307179587
        Lc2 = R2 * delta2(rad) = 300 * 0.6981317007977318 = 209.43951023931952
    """
    r1, delta1_deg = 600.0, 60.0
    r2, delta2_deg = 300.0, 40.0
    hpoints, t1, t2, pi_to_pi_distance = _build_pcc_prc_hpoints(r1, delta1_deg, r2, delta2_deg)

    # sanity-check the hand-derived literals quoted in the docstring above
    assert t1 == pytest.approx(346.4101615137755)
    assert t2 == pytest.approx(109.19107027934464)
    assert pi_to_pi_distance == pytest.approx(455.60123179312017)

    radii = [{"radius": r1, "join_next": True}, {"radius": r2}]
    segments = ifcopenshell.api.alignment.solve_horizontal_alignment_by_pi_method(hpoints, radii)

    assert [s.predefined_type for s in segments] == ["LINE", "CIRCULARARC", "CIRCULARARC", "LINE"]
    line_in, arc1, arc2, line_out = segments

    # both curves turn the same direction (left, positive radius) -- PCC, not PRC
    assert arc1.start_radius_of_curvature == pytest.approx(r1)
    assert arc1.end_radius_of_curvature == pytest.approx(r1)
    assert arc2.start_radius_of_curvature == pytest.approx(r2)
    assert arc2.end_radius_of_curvature == pytest.approx(r2)
    assert math.copysign(1.0, arc1.start_radius_of_curvature) == math.copysign(1.0, arc2.start_radius_of_curvature)

    # arc lengths follow from each curve's own deflection
    assert arc1.segment_length == pytest.approx(r1 * math.radians(delta1_deg))
    assert arc2.segment_length == pytest.approx(r2 * math.radians(delta2_deg))
    assert arc1.segment_length == pytest.approx(628.3185307179587)
    assert arc2.segment_length == pytest.approx(209.43951023931952)

    # tangent runs bracket the compound curve; no LINE segment sits between the two arcs
    assert line_in.predefined_type == "LINE"
    assert line_out.predefined_type == "LINE"

    # junction (and full chain) continuity, position + direction, < 1e-9
    _assert_chain_continuous(segments)


def test_prc_case():
    """
    PRC (point of reverse curvature): the curve at PI1 turns left (positive), the curve at PI2
    turns right (negative), joined directly at PI1-PI2 with no intermediate tangent run.

    delta1 = +60 deg, delta2 = -40 deg. T = R * tan(delta / 2) only depends on |delta|, so T1 and
    T2 are unchanged from the PCC case above; the sign of delta2 only flips the curvature sign.
    """
    r1, delta1_deg = 600.0, 60.0
    r2, delta2_deg = 300.0, -40.0
    hpoints, t1, t2, pi_to_pi_distance = _build_pcc_prc_hpoints(r1, delta1_deg, r2, delta2_deg)

    radii = [{"radius": r1, "join_next": True}, {"radius": r2}]
    segments = ifcopenshell.api.alignment.solve_horizontal_alignment_by_pi_method(hpoints, radii)

    assert [s.predefined_type for s in segments] == ["LINE", "CIRCULARARC", "CIRCULARARC", "LINE"]
    _, arc1, arc2, _ = segments

    # curvature signs flip at the junction: PI1 turns left (+), PI2 turns right (-)
    assert arc1.start_radius_of_curvature == pytest.approx(r1)
    assert arc1.end_radius_of_curvature == pytest.approx(r1)
    assert arc2.start_radius_of_curvature == pytest.approx(-r2)
    assert arc2.end_radius_of_curvature == pytest.approx(-r2)
    assert math.copysign(1.0, arc1.start_radius_of_curvature) != math.copysign(1.0, arc2.start_radius_of_curvature)

    # arc lengths still follow from each curve's own (unsigned) deflection
    assert arc1.segment_length == pytest.approx(r1 * math.radians(delta1_deg))
    assert arc2.segment_length == pytest.approx(r2 * math.radians(abs(delta2_deg)))

    # position and direction remain continuous across the reverse curve junction; only curvature
    # is discontinuous there, which is correct and expected for a PRC
    _assert_chain_continuous(segments)


def test_join_next_refusal_on_tangent_overshoot():
    """
    Perturbing PI2 5% closer to PI1 (holding the PI2 -> POE bearing fixed) shrinks the shared leg
    below T1 + T2: the two curves' tangent claims can no longer close on the leg, and the solver
    must refuse with an explanation -- stating the excess and the PIs involved -- rather than
    silently letting the curves overlap.
    """
    r1, delta1_deg = 600.0, 60.0
    r2, delta2_deg = 300.0, 40.0
    hpoints, t1, t2, pi_to_pi_distance = _build_pcc_prc_hpoints(r1, delta1_deg, r2, delta2_deg)
    pob, pi1, pi2, poe = hpoints

    bearing_1_to_2 = math.radians(delta1_deg)
    bearing_2_to_poe = bearing_1_to_2 + math.radians(delta2_deg)
    forward_tangent_length = math.hypot(poe[0] - pi2[0], poe[1] - pi2[1])

    shrunk_leg = pi_to_pi_distance * 0.95  # 5% short of T1 + T2 -> tangent runs overshoot the leg
    perturbed_pi2 = (
        pi1[0] + shrunk_leg * math.cos(bearing_1_to_2),
        pi1[1] + shrunk_leg * math.sin(bearing_1_to_2),
    )
    perturbed_poe = (
        perturbed_pi2[0] + forward_tangent_length * math.cos(bearing_2_to_poe),
        perturbed_pi2[1] + forward_tangent_length * math.sin(bearing_2_to_poe),
    )
    perturbed_hpoints = [pob, pi1, perturbed_pi2, perturbed_poe]

    radii = [{"radius": r1, "join_next": True}, {"radius": r2}]

    expected_excess = pi_to_pi_distance - shrunk_leg  # == 0.05 * pi_to_pi_distance
    assert expected_excess == pytest.approx(0.05 * pi_to_pi_distance)

    with pytest.raises(ValueError) as exc_info:
        ifcopenshell.api.alignment.solve_horizontal_alignment_by_pi_method(perturbed_hpoints, radii)

    message = str(exc_info.value)
    assert "PI 1-2" in message  # the PIs involved
    assert "exceed" in message  # tangent runs overshoot, not fall short

    match = re.search(r"PI-to-PI distance by ([0-9.eE+-]+)", message)
    assert match is not None, message
    reported_excess = float(match.group(1))
    assert reported_excess == pytest.approx(expected_excess, rel=1.0e-5)


def test_join_next_rejects_last_pi():
    """join_next on the last PI curve has no next curve to join to; refused with an explanation."""
    hpoints = [(0.0, 0.0), (1000.0, 0.0), (2000.0, 1000.0)]
    radii = [{"radius": 500.0, "join_next": True}]
    with pytest.raises(ValueError, match="join_next"):
        ifcopenshell.api.alignment.solve_horizontal_alignment_by_pi_method(hpoints, radii)


def test_join_next_rejects_spiral_on_joined_side():
    """
    Spiral transitions are not supported on the joined side of a compound/reverse curve junction
    (a documented v1 limitation): the joining curve's exit spiral and the joined-into curve's
    entry spiral must both be 0.0.
    """
    r1, delta1_deg = 600.0, 60.0
    r2, delta2_deg = 300.0, 40.0
    hpoints, _, _, _ = _build_pcc_prc_hpoints(r1, delta1_deg, r2, delta2_deg)

    # exit spiral on the joining curve (PI1) is rejected
    with pytest.raises(ValueError, match="join_next"):
        ifcopenshell.api.alignment.solve_horizontal_alignment_by_pi_method(
            hpoints, [{"radius": r1, "lout": 50.0, "join_next": True}, {"radius": r2}]
        )

    # entry spiral on the joined-into curve (PI2) is rejected
    with pytest.raises(ValueError, match="join_next"):
        ifcopenshell.api.alignment.solve_horizontal_alignment_by_pi_method(
            hpoints, [{"radius": r1, "join_next": True}, {"radius": r2, "lin": 50.0}]
        )


def test_dict_form_without_join_next_matches_tuple_form():
    """The new dict form is a drop-in alternative to the (R, Lin, Lout) tuple when join_next is unused."""
    hpoints = [(500.0, 2500.0), (3340.0, 660.0), (4340.0, 5000.0), (8480.0, 2010.0)]

    segments_tuple = ifcopenshell.api.alignment.solve_horizontal_alignment_by_pi_method(
        hpoints, [(1000.0, 150.0, 120.0), (1250.0, 0.0, 0.0)]
    )
    segments_dict = ifcopenshell.api.alignment.solve_horizontal_alignment_by_pi_method(
        hpoints, [{"radius": 1000.0, "lin": 150.0, "lout": 120.0}, {"radius": 1250.0}]
    )
    assert segments_tuple == segments_dict


def test_malformed_dict_radii_element_raises():
    hpoints = [(0.0, 0.0), (1000.0, 0.0), (2000.0, 1000.0)]
    with pytest.raises(ValueError):  # missing required 'radius' key
        ifcopenshell.api.alignment.solve_horizontal_alignment_by_pi_method(hpoints, [{"lin": 50.0}])
    with pytest.raises(ValueError):  # unrecognized key
        ifcopenshell.api.alignment.solve_horizontal_alignment_by_pi_method(hpoints, [{"radius": 500.0, "bogus": 1.0}])

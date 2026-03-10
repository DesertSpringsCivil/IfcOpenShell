# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2026 Michael Yoder <myoder@desertspringscivil.com>
#
# This file is part of Bonsai.
#
# Bonsai is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Bonsai is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Bonsai.  If not, see <http://www.gnu.org/licenses/>.

import math
import pytest
import bpy
import ifcopenshell
import bonsai.tool as tool
from bonsai.tool.alignment import Alignment as subject, PVIGeometryResult
from test.bim.bootstrap import NewFile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TOLERANCE = 1e-9


def assert_close(actual: float, expected: float, tol: float = TOLERANCE) -> None:
    assert abs(actual - expected) < tol, f"Expected {expected}, got {actual} (diff={abs(actual-expected):.2e})"


class _FakeDesignParams:
    """Minimal stand-in for an IfcAlignmentHorizontalSegment or similar."""

    def __init__(self, ifc_class: str, segment_length: float = 0.0, horizontal_length: float = 0.0):
        self._ifc_class = ifc_class
        self.SegmentLength = segment_length
        self.HorizontalLength = horizontal_length

    def is_a(self, ifc_class: str) -> bool:
        return self._ifc_class == ifc_class


class _FakeSegment:
    """Minimal stand-in for an IfcAlignmentSegment."""

    def __init__(self, design_params=None):
        self.DesignParameters = design_params


# ---------------------------------------------------------------------------
# calculate_pi_geometry
# ---------------------------------------------------------------------------


class TestCalculatePiGeometry(NewFile):
    def test_returns_empty_result_for_empty_pi_list(self):
        result = subject.calculate_pi_geometry([])
        assert result.stations == []
        assert result.total_length == 0.0

    def test_returns_single_point_result_for_one_pi(self):
        result = subject.calculate_pi_geometry([(50.0, 100.0)])
        assert len(result.stations) == 1
        assert result.total_length == 0.0

    def test_calculates_length_between_two_points(self):
        result = subject.calculate_pi_geometry([(0.0, 0.0), (100.0, 0.0)])
        assert_close(result.total_length, 100.0)
        assert_close(result.lengths[0], 100.0)

    def test_calculates_due_east_direction(self):
        result = subject.calculate_pi_geometry([(0.0, 0.0), (100.0, 0.0)])
        assert_close(result.directions[0], 0.0)

    def test_calculates_due_north_direction(self):
        result = subject.calculate_pi_geometry([(0.0, 0.0), (0.0, 100.0)])
        assert_close(result.directions[0], math.pi / 2)

    def test_calculates_diagonal_length(self):
        result = subject.calculate_pi_geometry([(0.0, 0.0), (3.0, 4.0)])
        assert_close(result.total_length, 5.0)

    def test_calculates_stations_for_three_pis(self):
        pis = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)]
        result = subject.calculate_pi_geometry(pis)
        assert_close(result.stations[0], 0.0)
        assert_close(result.stations[1], 100.0)
        assert_close(result.stations[2], 200.0)
        assert_close(result.total_length, 200.0)

    def test_applies_start_station_offset(self):
        pis = [(0.0, 0.0), (100.0, 0.0)]
        result = subject.calculate_pi_geometry(pis, start_station=1000.0)
        assert_close(result.stations[0], 1000.0)
        assert_close(result.stations[1], 1100.0)
        assert_close(result.total_length, 100.0)

    def test_last_pi_has_zero_length_and_direction(self):
        result = subject.calculate_pi_geometry([(0.0, 0.0), (100.0, 0.0)])
        assert_close(result.lengths[-1], 0.0)
        assert_close(result.directions[-1], 0.0)


# ---------------------------------------------------------------------------
# calculate_tangent_length   T = R * tan(Δ/2)
# ---------------------------------------------------------------------------


class TestCalculateTangentLength(NewFile):
    def test_returns_zero_for_zero_radius(self):
        assert_close(subject.calculate_tangent_length(0.0, math.pi / 2), 0.0)

    def test_returns_zero_for_zero_deflection(self):
        assert_close(subject.calculate_tangent_length(300.0, 0.0), 0.0)

    def test_calculates_tangent_for_30_degree_deflection(self):
        deflection = math.radians(30)
        expected = 300.0 * math.tan(deflection / 2)
        assert_close(subject.calculate_tangent_length(300.0, deflection), expected)

    def test_calculates_tangent_for_90_degree_deflection(self):
        deflection = math.pi / 2
        expected = 100.0 * math.tan(math.pi / 4)  # R * tan(45°) = R
        assert_close(subject.calculate_tangent_length(100.0, deflection), expected)


# ---------------------------------------------------------------------------
# calculate_arc_length   L = R * Δ
# ---------------------------------------------------------------------------


class TestCalculateArcLength(NewFile):
    def test_calculates_arc_for_90_degree_curve(self):
        expected = 100.0 * math.pi / 2
        assert_close(subject.calculate_arc_length(100.0, math.pi / 2), expected)

    def test_calculates_arc_for_full_circle(self):
        expected = 50.0 * 2 * math.pi
        assert_close(subject.calculate_arc_length(50.0, 2 * math.pi), expected)

    def test_zero_radius_yields_zero_length(self):
        assert_close(subject.calculate_arc_length(0.0, math.pi / 2), 0.0)

    def test_zero_deflection_yields_zero_length(self):
        assert_close(subject.calculate_arc_length(100.0, 0.0), 0.0)


# ---------------------------------------------------------------------------
# deflection_angle_from_points
# ---------------------------------------------------------------------------


class TestDeflectionAngleFromPoints(NewFile):
    def test_returns_zero_for_straight_alignment(self):
        angle = subject.deflection_angle_from_points((0.0, 0.0), (100.0, 0.0), (200.0, 0.0))
        assert_close(angle, 0.0)

    def test_positive_for_90_degree_left_turn(self):
        """Turning left (CCW) is a positive deflection."""
        angle = subject.deflection_angle_from_points((0.0, 0.0), (100.0, 0.0), (100.0, 100.0))
        assert_close(angle, math.pi / 2)

    def test_negative_for_90_degree_right_turn(self):
        """Turning right (CW) is a negative deflection."""
        angle = subject.deflection_angle_from_points((0.0, 0.0), (100.0, 0.0), (100.0, -100.0))
        assert_close(angle, -math.pi / 2)

    def test_returns_pi_for_u_turn(self):
        """180-degree turn."""
        angle = subject.deflection_angle_from_points((0.0, 0.0), (100.0, 0.0), (0.0, 0.0))
        assert_close(abs(angle), math.pi)

    def test_normalises_angle_into_minus_pi_to_pi_range(self):
        """Result must always be in (-π, π]."""
        angle = subject.deflection_angle_from_points((0.0, 0.0), (100.0, 0.0), (50.0, -50.0))
        assert -math.pi < angle <= math.pi


# ---------------------------------------------------------------------------
# arc_length_at_pi
# ---------------------------------------------------------------------------


class TestArcLengthAtPi(NewFile):
    def test_returns_zero_for_zero_radius(self):
        arc = subject.arc_length_at_pi((0.0, 0.0), (100.0, 0.0), (100.0, 100.0), radius=0.0)
        assert_close(arc, 0.0)

    def test_returns_zero_for_negative_radius(self):
        arc = subject.arc_length_at_pi((0.0, 0.0), (100.0, 0.0), (100.0, 100.0), radius=-100.0)
        assert_close(arc, 0.0)

    def test_calculates_arc_for_90_degree_left_turn(self):
        expected = 100.0 * math.pi / 2
        arc = subject.arc_length_at_pi((0.0, 0.0), (100.0, 0.0), (100.0, 100.0), radius=100.0)
        assert_close(arc, expected)

    def test_calculates_arc_for_90_degree_right_turn(self):
        """Sign of deflection should not affect arc length."""
        expected = 100.0 * math.pi / 2
        arc = subject.arc_length_at_pi((0.0, 0.0), (100.0, 0.0), (100.0, -100.0), radius=100.0)
        assert_close(arc, expected)


# ---------------------------------------------------------------------------
# tangent_length_at_pi
# ---------------------------------------------------------------------------


class TestTangentLengthAtPi(NewFile):
    def test_returns_zero_for_zero_radius(self):
        t = subject.tangent_length_at_pi((0.0, 0.0), (100.0, 0.0), (100.0, 100.0), radius=0.0)
        assert_close(t, 0.0)

    def test_returns_zero_for_negative_radius(self):
        t = subject.tangent_length_at_pi((0.0, 0.0), (100.0, 0.0), (100.0, 100.0), radius=-100.0)
        assert_close(t, 0.0)

    def test_calculates_tangent_for_90_degree_left_turn(self):
        expected = 100.0 * math.tan(math.pi / 4)  # R * tan(45°)
        t = subject.tangent_length_at_pi((0.0, 0.0), (100.0, 0.0), (100.0, 100.0), radius=100.0)
        assert_close(t, expected)

    def test_matches_calculate_tangent_length_for_same_geometry(self):
        """tangent_length_at_pi must agree with calculate_tangent_length."""
        deflection = abs(subject.deflection_angle_from_points((0.0, 0.0), (100.0, 0.0), (100.0, 100.0)))
        expected = subject.calculate_tangent_length(300.0, deflection)
        actual = subject.tangent_length_at_pi((0.0, 0.0), (100.0, 0.0), (100.0, 100.0), radius=300.0)
        assert_close(actual, expected)


# ---------------------------------------------------------------------------
# tangent_segment_length
# ---------------------------------------------------------------------------


class TestTangentSegmentLength(NewFile):
    def test_returns_full_distance_with_no_tangents(self):
        length = subject.tangent_segment_length((0.0, 0.0), (100.0, 0.0))
        assert_close(length, 100.0)

    def test_subtracts_start_tangent(self):
        length = subject.tangent_segment_length((0.0, 0.0), (100.0, 0.0), start_tangent=20.0)
        assert_close(length, 80.0)

    def test_subtracts_end_tangent(self):
        length = subject.tangent_segment_length((0.0, 0.0), (100.0, 0.0), end_tangent=30.0)
        assert_close(length, 70.0)

    def test_subtracts_both_tangents(self):
        length = subject.tangent_segment_length((0.0, 0.0), (100.0, 0.0), start_tangent=20.0, end_tangent=30.0)
        assert_close(length, 50.0)

    def test_clamps_to_zero_when_tangents_exceed_full_distance(self):
        length = subject.tangent_segment_length((0.0, 0.0), (100.0, 0.0), start_tangent=70.0, end_tangent=70.0)
        assert_close(length, 0.0)

    def test_works_on_diagonal_leg(self):
        """3-4-5 triangle: full_length=5, minus tangents=2 → 3."""
        length = subject.tangent_segment_length((0.0, 0.0), (3.0, 4.0), start_tangent=1.0, end_tangent=1.0)
        assert_close(length, 3.0)


# ---------------------------------------------------------------------------
# is_zero_length_segment
# ---------------------------------------------------------------------------


class TestIsZeroLengthSegment(NewFile):
    def test_returns_false_when_segment_has_no_design_parameters(self):
        seg = _FakeSegment(design_params=None)
        assert subject.is_zero_length_segment(seg) is False

    def test_returns_true_for_horizontal_segment_with_zero_length(self):
        dp = _FakeDesignParams("IfcAlignmentHorizontalSegment", segment_length=0.0)
        seg = _FakeSegment(dp)
        assert subject.is_zero_length_segment(seg) is True

    def test_returns_false_for_horizontal_segment_with_nonzero_length(self):
        dp = _FakeDesignParams("IfcAlignmentHorizontalSegment", segment_length=100.0)
        seg = _FakeSegment(dp)
        assert subject.is_zero_length_segment(seg) is False

    def test_returns_true_for_vertical_segment_with_zero_horizontal_length(self):
        dp = _FakeDesignParams("IfcAlignmentVerticalSegment", horizontal_length=0.0)
        seg = _FakeSegment(dp)
        assert subject.is_zero_length_segment(seg) is True

    def test_returns_false_for_vertical_segment_with_nonzero_horizontal_length(self):
        dp = _FakeDesignParams("IfcAlignmentVerticalSegment", horizontal_length=50.0)
        seg = _FakeSegment(dp)
        assert subject.is_zero_length_segment(seg) is False

    def test_returns_true_for_cant_segment_with_zero_horizontal_length(self):
        dp = _FakeDesignParams("IfcAlignmentCantSegment", horizontal_length=0.0)
        seg = _FakeSegment(dp)
        assert subject.is_zero_length_segment(seg) is True

    def test_returns_false_for_unknown_segment_type(self):
        dp = _FakeDesignParams("IfcUnknownSegmentType", segment_length=0.0)
        seg = _FakeSegment(dp)
        assert subject.is_zero_length_segment(seg) is False

    def test_uses_near_zero_tolerance(self):
        """Lengths below 1e-6 should be considered zero."""
        dp = _FakeDesignParams("IfcAlignmentHorizontalSegment", segment_length=1e-7)
        seg = _FakeSegment(dp)
        assert subject.is_zero_length_segment(seg) is True


# ---------------------------------------------------------------------------
# layout_has_real_segments
# ---------------------------------------------------------------------------


class _FakeAlignmentSegment:
    """Stand-in for IfcAlignmentSegment: is_a() returns True for IfcAlignmentSegment."""

    def __init__(self, design_params=None):
        self.DesignParameters = design_params

    def is_a(self, ifc_class: str) -> bool:
        return ifc_class == "IfcAlignmentSegment"


class _FakeRelNests:
    def __init__(self, related_objects):
        self.RelatedObjects = related_objects


class _FakeLayout:
    def __init__(self, rels=None):
        self.IsNestedBy = rels or []


class TestLayoutHasRealSegments(NewFile):
    def test_returns_false_for_layout_with_no_nested_relationships(self):
        layout = _FakeLayout(rels=[])
        assert subject.layout_has_real_segments(layout) is False

    def test_returns_false_for_layout_with_empty_related_objects(self):
        layout = _FakeLayout(rels=[_FakeRelNests(related_objects=[])])
        assert subject.layout_has_real_segments(layout) is False

    def test_returns_false_when_only_segment_is_zero_length_terminator(self):
        dp = _FakeDesignParams("IfcAlignmentHorizontalSegment", segment_length=0.0)
        terminator = _FakeAlignmentSegment(dp)
        layout = _FakeLayout(rels=[_FakeRelNests([terminator])])
        assert subject.layout_has_real_segments(layout) is False

    def test_returns_true_when_one_real_segment_exists(self):
        dp = _FakeDesignParams("IfcAlignmentHorizontalSegment", segment_length=100.0)
        real_seg = _FakeAlignmentSegment(dp)
        layout = _FakeLayout(rels=[_FakeRelNests([real_seg])])
        assert subject.layout_has_real_segments(layout) is True

    def test_returns_true_when_real_segment_follows_terminator(self):
        dp_zero = _FakeDesignParams("IfcAlignmentHorizontalSegment", segment_length=0.0)
        dp_real = _FakeDesignParams("IfcAlignmentHorizontalSegment", segment_length=50.0)
        layout = _FakeLayout(rels=[_FakeRelNests([_FakeAlignmentSegment(dp_zero), _FakeAlignmentSegment(dp_real)])])
        assert subject.layout_has_real_segments(layout) is True

    def test_ignores_non_alignment_segment_objects(self):
        """Non-IfcAlignmentSegment objects in RelatedObjects should be ignored."""

        class _FakeOtherObject:
            def is_a(self, ifc_class):
                return False

        layout = _FakeLayout(rels=[_FakeRelNests([_FakeOtherObject()])])
        assert subject.layout_has_real_segments(layout) is False


# ---------------------------------------------------------------------------
# safe_layout_horizontal_by_pi_method
# ---------------------------------------------------------------------------


class TestSafeLayoutHorizontalByPiMethod(NewFile):
    def test_raises_when_layout_has_no_parent_alignment(self):
        """An orphan layout (no parent IfcAlignment) must raise ValueError."""
        ifc = ifcopenshell.file(schema="IFC4X3_ADD2")
        tool.Ifc.set(ifc)
        orphan_layout = ifc.createIfcAlignmentHorizontal()
        with pytest.raises(ValueError, match="no parent IfcAlignment"):
            subject.safe_layout_horizontal_by_pi_method(
                ifc, orphan_layout, hpoints=[(0.0, 0.0), (100.0, 0.0)], radii=[]
            )

    def test_succeeds_when_layout_has_parent_alignment(self):
        """A layout properly nested under an IfcAlignment should not raise."""
        import ifcopenshell.api.root
        import ifcopenshell.api.alignment

        ifc = ifcopenshell.file(schema="IFC4X3_ADD2")
        tool.Ifc.set(ifc)
        # Create a minimal alignment hierarchy
        project = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcProject")
        alignment = ifc.createIfcAlignment()
        layout = ifc.createIfcAlignmentHorizontal()
        ifc.createIfcRelNests(RelatingObject=alignment, RelatedObjects=[layout])
        result = subject.safe_layout_horizontal_by_pi_method(
            ifc, layout, hpoints=[(0.0, 0.0), (100.0, 0.0)], radii=[]
        )
        assert result is True


# ===========================================================================
# Vertical Alignment Geometry Tests
# ===========================================================================


# ---------------------------------------------------------------------------
# calculate_grade
# ---------------------------------------------------------------------------


class TestCalculateGrade(NewFile):
    def test_returns_zero_for_zero_horizontal_distance(self):
        assert_close(subject.calculate_grade(0.0, 10.0, 0.0), 0.0)

    def test_returns_zero_for_negative_horizontal_distance(self):
        assert_close(subject.calculate_grade(0.0, 10.0, -100.0), 0.0)

    def test_calculates_positive_uphill_grade(self):
        """2% uphill: rise=2, run=100 → g=0.02."""
        assert_close(subject.calculate_grade(100.0, 102.0, 100.0), 0.02)

    def test_calculates_negative_downhill_grade(self):
        """3% downhill: drop=3, run=100 → g=-0.03."""
        assert_close(subject.calculate_grade(103.0, 100.0, 100.0), -0.03)

    def test_returns_zero_for_flat_grade(self):
        assert_close(subject.calculate_grade(50.0, 50.0, 200.0), 0.0)

    def test_grade_is_independent_of_absolute_elevation(self):
        """Same rise and run at different elevations → same grade."""
        g1 = subject.calculate_grade(0.0, 5.0, 100.0)
        g2 = subject.calculate_grade(1000.0, 1005.0, 100.0)
        assert_close(g1, g2)


# ---------------------------------------------------------------------------
# calculate_k_value
# ---------------------------------------------------------------------------


class TestCalculateKValue(NewFile):
    def test_returns_zero_for_zero_grade_change(self):
        assert_close(subject.calculate_k_value(200.0, 0.0), 0.0)

    def test_returns_zero_for_zero_curve_length(self):
        assert_close(subject.calculate_k_value(0.0, 0.04), 0.0)

    def test_calculates_k_for_positive_grade_change(self):
        """L=200, Δg=0.04 → K=5000 (sag curve)."""
        assert_close(subject.calculate_k_value(200.0, 0.04), 5000.0)

    def test_calculates_k_for_negative_grade_change(self):
        """K uses |Δg|, so sign of grade change does not matter."""
        assert_close(subject.calculate_k_value(200.0, -0.04), 5000.0)

    def test_k_increases_with_longer_curve(self):
        k_short = subject.calculate_k_value(100.0, 0.04)
        k_long = subject.calculate_k_value(400.0, 0.04)
        assert k_long > k_short


# ---------------------------------------------------------------------------
# calculate_vertical_curve_length_from_k
# ---------------------------------------------------------------------------


class TestCalculateVerticalCurveLengthFromK(NewFile):
    def test_calculates_length_from_k_and_grade_change(self):
        """K=5000, Δg=0.04 → L=200."""
        assert_close(subject.calculate_vertical_curve_length_from_k(5000.0, 0.04), 200.0)

    def test_uses_absolute_value_of_grade_change(self):
        """Negative Δg gives same length as positive."""
        l_pos = subject.calculate_vertical_curve_length_from_k(5000.0, 0.04)
        l_neg = subject.calculate_vertical_curve_length_from_k(5000.0, -0.04)
        assert_close(l_pos, l_neg)

    def test_returns_zero_for_zero_grade_change(self):
        assert_close(subject.calculate_vertical_curve_length_from_k(5000.0, 0.0), 0.0)

    def test_round_trips_with_calculate_k_value(self):
        """L → K → L should recover the original length."""
        original_length = 300.0
        grade_change = 0.06
        k = subject.calculate_k_value(original_length, grade_change)
        recovered_length = subject.calculate_vertical_curve_length_from_k(k, grade_change)
        assert_close(recovered_length, original_length)


# ---------------------------------------------------------------------------
# calculate_elevation_on_parabola
# ---------------------------------------------------------------------------


class TestCalculateElevationOnParabola(NewFile):
    def test_elevation_at_bvc_equals_start_elevation(self):
        """At x=0 (BVC), elevation must equal start_elevation."""
        elev = subject.calculate_elevation_on_parabola(
            start_elevation=100.0,
            start_gradient=0.02,
            end_gradient=-0.02,
            curve_length=200.0,
            distance_from_bvc=0.0,
        )
        assert_close(elev, 100.0)

    def test_elevation_at_evc_matches_tangent_grades(self):
        """At x=L (EVC), elevation = start_elev + g1*L + (g2-g1)/(2L)*L²
        which simplifies to start_elev + (g1+g2)/2 * L."""
        g1, g2, L = 0.02, -0.02, 200.0
        start_elev = 100.0
        expected = start_elev + (g1 + g2) / 2.0 * L
        elev = subject.calculate_elevation_on_parabola(start_elev, g1, g2, L, L)
        assert_close(elev, expected)

    def test_elevation_is_parabolic_midpoint(self):
        """At x=L/2 the elevation follows the quadratic formula."""
        g1, g2, L = 0.03, -0.01, 200.0
        start_elev = 50.0
        x = L / 2.0
        expected = start_elev + g1 * x + (g2 - g1) / (2.0 * L) * x**2
        assert_close(subject.calculate_elevation_on_parabola(start_elev, g1, g2, L, x), expected)

    def test_falls_back_to_linear_for_zero_curve_length(self):
        """Zero curve length → straight tangent grade."""
        elev = subject.calculate_elevation_on_parabola(
            start_elevation=100.0, start_gradient=0.05,
            end_gradient=-0.05, curve_length=0.0, distance_from_bvc=50.0,
        )
        assert_close(elev, 102.5)  # 100 + 0.05 * 50

    def test_crest_curve_elevation_at_high_point(self):
        """On a crest curve the high point is where g1*x + (g2-g1)/(2L)*x² is maximised."""
        g1, g2, L = 0.04, -0.02, 300.0
        start_elev = 200.0
        # x_hl = g1 * L / (g1 - g2) = 0.04 * 300 / 0.06 = 200
        x_hl = g1 * L / (g1 - g2)
        elev_hl = subject.calculate_elevation_on_parabola(start_elev, g1, g2, L, x_hl)
        # Elevation just before and after should both be lower
        elev_before = subject.calculate_elevation_on_parabola(start_elev, g1, g2, L, x_hl - 1.0)
        elev_after = subject.calculate_elevation_on_parabola(start_elev, g1, g2, L, x_hl + 1.0)
        assert elev_hl >= elev_before
        assert elev_hl >= elev_after


# ---------------------------------------------------------------------------
# calculate_high_low_point_distance
# ---------------------------------------------------------------------------


class TestCalculateHighLowPointDistance(NewFile):
    def test_returns_none_for_constant_gradient(self):
        """No high/low point when g1 == g2 (constant slope)."""
        result = subject.calculate_high_low_point_distance(0.02, 0.02, 200.0)
        assert result is None

    def test_returns_none_when_high_low_point_is_outside_curve(self):
        """When both grades are positive (sag/crest entirely outside curve)."""
        # g1=0.01, g2=0.03 → Δg positive, x_hl = g1*L/(g1-g2) negative → outside
        result = subject.calculate_high_low_point_distance(0.01, 0.03, 200.0)
        assert result is None

    def test_finds_high_point_on_crest_curve(self):
        """g1 > 0, g2 < 0 → crest curve, high point inside."""
        g1, g2, L = 0.04, -0.02, 300.0
        expected = g1 * L / (g1 - g2)  # 0.04*300 / 0.06 = 200
        result = subject.calculate_high_low_point_distance(g1, g2, L)
        assert result is not None
        assert_close(result, expected)

    def test_finds_low_point_on_sag_curve(self):
        """g1 < 0, g2 > 0 → sag curve, low point inside."""
        g1, g2, L = -0.03, 0.01, 200.0
        expected = g1 * L / (g1 - g2)  # -0.03*200 / (-0.04) = 150
        result = subject.calculate_high_low_point_distance(g1, g2, L)
        assert result is not None
        assert_close(result, expected)

    def test_high_low_point_is_strictly_inside_curve(self):
        """Returned distance must be 0 < x < L."""
        g1, g2, L = 0.05, -0.03, 400.0
        result = subject.calculate_high_low_point_distance(g1, g2, L)
        assert result is not None
        assert 0 < result < L


# ---------------------------------------------------------------------------
# calculate_bvc_evc_stations
# ---------------------------------------------------------------------------


class TestCalculateBvcEvcStations(NewFile):
    def test_bvc_is_half_length_before_pvi(self):
        bvc, _ = subject.calculate_bvc_evc_stations(pvi_station=1000.0, curve_length=200.0)
        assert_close(bvc, 900.0)

    def test_evc_is_half_length_after_pvi(self):
        _, evc = subject.calculate_bvc_evc_stations(pvi_station=1000.0, curve_length=200.0)
        assert_close(evc, 1100.0)

    def test_zero_length_curve_places_bvc_and_evc_at_pvi(self):
        bvc, evc = subject.calculate_bvc_evc_stations(pvi_station=500.0, curve_length=0.0)
        assert_close(bvc, 500.0)
        assert_close(evc, 500.0)

    def test_curve_length_equals_evc_minus_bvc(self):
        L = 300.0
        bvc, evc = subject.calculate_bvc_evc_stations(pvi_station=2000.0, curve_length=L)
        assert_close(evc - bvc, L)

    def test_pvi_is_midpoint_of_bvc_and_evc(self):
        pvi = 1500.0
        bvc, evc = subject.calculate_bvc_evc_stations(pvi_station=pvi, curve_length=100.0)
        assert_close((bvc + evc) / 2.0, pvi)


# ---------------------------------------------------------------------------
# calculate_pvi_geometry
# ---------------------------------------------------------------------------


class TestCalculatePviGeometry(NewFile):
    def test_returns_empty_result_for_no_pvis(self):
        result = subject.calculate_pvi_geometry([])
        assert result.stations == []
        assert result.total_length == 0.0

    def test_returns_single_pvi_result(self):
        result = subject.calculate_pvi_geometry([(100.0, 50.0)])
        assert result.stations == [100.0]
        assert result.elevations == [50.0]
        assert result.grades == []
        assert result.k_values == []
        assert result.total_length == 0.0

    def test_calculates_grade_between_two_pvis(self):
        """2% uphill from station 0 to 100."""
        result = subject.calculate_pvi_geometry([(0.0, 100.0), (100.0, 102.0)])
        assert len(result.grades) == 1
        assert_close(result.grades[0], 0.02)
        assert_close(result.total_length, 100.0)

    def test_calculates_two_grades_for_three_pvis(self):
        pvis = [(0.0, 100.0), (100.0, 102.0), (300.0, 98.0)]
        result = subject.calculate_pvi_geometry(pvis)
        assert len(result.grades) == 2
        assert_close(result.grades[0], 0.02)   # +2% uphill
        assert_close(result.grades[1], -0.02)  # -2% downhill

    def test_calculates_bvc_evc_for_interior_pvi(self):
        """Single interior PVI at station 100, curve length 50 → BVC=75, EVC=125."""
        pvis = [(0.0, 100.0), (100.0, 102.0), (300.0, 98.0)]
        result = subject.calculate_pvi_geometry(pvis, curve_lengths=[50.0])
        assert len(result.bvc_stations) == 1
        assert_close(result.bvc_stations[0], 75.0)
        assert_close(result.evc_stations[0], 125.0)

    def test_k_value_is_zero_for_zero_curve_length(self):
        pvis = [(0.0, 100.0), (100.0, 102.0), (300.0, 98.0)]
        result = subject.calculate_pvi_geometry(pvis, curve_lengths=[0.0])
        assert_close(result.k_values[0], 0.0)

    def test_k_value_matches_expected_for_known_curve(self):
        """g1=+2%, g2=-2%, Δg=0.04, L=200 → K=5000."""
        pvis = [(0.0, 100.0), (1000.0, 120.0), (2000.0, 100.0)]
        result = subject.calculate_pvi_geometry(pvis, curve_lengths=[200.0])
        # grades: [0.02, -0.02], Δg = -0.04, K = 200/0.04 = 5000
        assert_close(result.k_values[0], 5000.0)

    def test_defaults_curve_lengths_to_zero_when_not_provided(self):
        pvis = [(0.0, 100.0), (500.0, 110.0), (1000.0, 100.0)]
        result = subject.calculate_pvi_geometry(pvis)
        assert_close(result.k_values[0], 0.0)
        assert_close(result.bvc_stations[0], result.stations[1])
        assert_close(result.evc_stations[0], result.stations[1])

    def test_total_length_equals_last_minus_first_station(self):
        pvis = [(100.0, 50.0), (400.0, 56.0), (700.0, 50.0)]
        result = subject.calculate_pvi_geometry(pvis)
        assert_close(result.total_length, 600.0)

    def test_two_interior_pvis_produce_two_k_values(self):
        pvis = [
            (0.0, 100.0),
            (200.0, 104.0),   # interior 1: g_in=+2%, g_out varies
            (600.0, 100.0),   # interior 2
            (1000.0, 92.0),
        ]
        result = subject.calculate_pvi_geometry(pvis, curve_lengths=[100.0, 150.0])
        assert len(result.k_values) == 2
        assert len(result.bvc_stations) == 2
        assert len(result.evc_stations) == 2

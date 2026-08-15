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
import ifcopenshell.api.alignment as align_api
import bonsai.tool as tool
from bonsai.tool.alignment import Alignment as subject, PVIGeometryResult, AlignmentPoint, ProfileViewTransform
from test.bim.bootstrap import NewFile, NewIfc4X3


def _geometry_mapping_available() -> bool:
    """True when the modular geometry-mapping plugins are present.

    v0.9.0 evaluates segment endpoints through the geometry engine, which
    loads per-schema ifcopenshell_geometry_mapping_* plugins at runtime. The
    win64 v0.9.0alpha0 builds ship without them (IfcOpenShell#9301), so
    geometry-dependent tests skip locally and run in CI where builds are
    complete.
    """
    import pathlib

    package_root = pathlib.Path(ifcopenshell.__file__).parent
    return any(f.name.startswith("ifcopenshell_geometry_mapping_") for f in package_root.iterdir())


requires_geometry_engine = pytest.mark.skipif(
    not _geometry_mapping_available(),
    reason="geometry mapping plugins unavailable (IfcOpenShell#9301); covered in CI",
)


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


@requires_geometry_engine
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
        result = subject.safe_layout_horizontal_by_pi_method(ifc, layout, hpoints=[(0.0, 0.0), (100.0, 0.0)], radii=[])
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
        """L=200, Δg=0.04 (4%) → K=50 per civil convention (length/percent)."""
        assert_close(subject.calculate_k_value(200.0, 0.04), 50.0)

    def test_calculates_k_for_negative_grade_change(self):
        """K uses |Δg|, so sign of grade change does not matter."""
        assert_close(subject.calculate_k_value(200.0, -0.04), 50.0)

    def test_k_increases_with_longer_curve(self):
        k_short = subject.calculate_k_value(100.0, 0.04)
        k_long = subject.calculate_k_value(400.0, 0.04)
        assert k_long > k_short


# ---------------------------------------------------------------------------
# calculate_vertical_curve_length_from_k
# ---------------------------------------------------------------------------


class TestCalculateVerticalCurveLengthFromK(NewFile):
    def test_calculates_length_from_k_and_grade_change(self):
        """K=50 (per percent), Δg=0.04 (4%) → L=200."""
        assert_close(subject.calculate_vertical_curve_length_from_k(50.0, 0.04), 200.0)

    def test_uses_absolute_value_of_grade_change(self):
        """Negative Δg gives same length as positive."""
        l_pos = subject.calculate_vertical_curve_length_from_k(50.0, 0.04)
        l_neg = subject.calculate_vertical_curve_length_from_k(50.0, -0.04)
        assert_close(l_pos, l_neg)

    def test_returns_zero_for_zero_grade_change(self):
        assert_close(subject.calculate_vertical_curve_length_from_k(50.0, 0.0), 0.0)

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
            start_elevation=100.0,
            start_gradient=0.05,
            end_gradient=-0.05,
            curve_length=0.0,
            distance_from_bvc=50.0,
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
        assert_close(result.grades[0], 0.02)  # +2% uphill
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
        """g1=+2%, g2=-2%, A=4%, L=200 → K=50 (length per percent)."""
        pvis = [(0.0, 100.0), (1000.0, 120.0), (2000.0, 100.0)]
        result = subject.calculate_pvi_geometry(pvis, curve_lengths=[200.0])
        # grades: [0.02, -0.02], A = 4%, K = 200/4 = 50
        assert_close(result.k_values[0], 50.0)

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
            (200.0, 104.0),  # interior 1: g_in=+2%, g_out varies
            (600.0, 100.0),  # interior 2
            (1000.0, 92.0),
        ]
        result = subject.calculate_pvi_geometry(pvis, curve_lengths=[100.0, 150.0])
        assert len(result.k_values) == 2
        assert len(result.bvc_stations) == 2
        assert len(result.evc_stations) == 2


# ---------------------------------------------------------------------------
# is_crest_curve / is_sag_curve
# ---------------------------------------------------------------------------


class TestIsCrestCurve(NewFile):
    def test_returns_true_when_grade_decreases(self):
        """g1=+3%, g2=-2% → crest curve."""
        assert subject.is_crest_curve(0.03, -0.02) is True

    def test_returns_false_when_grade_increases(self):
        """g1=-2%, g2=+3% → sag, not crest."""
        assert subject.is_crest_curve(-0.02, 0.03) is False

    def test_returns_false_for_constant_grade(self):
        """No grade change → neither crest nor sag."""
        assert subject.is_crest_curve(0.02, 0.02) is False

    def test_returns_true_when_both_positive_but_decreasing(self):
        """g1=+4%, g2=+1% → crest (still decreasing)."""
        assert subject.is_crest_curve(0.04, 0.01) is True


class TestIsSagCurve(NewFile):
    def test_returns_true_when_grade_increases(self):
        """g1=-2%, g2=+3% → sag curve."""
        assert subject.is_sag_curve(-0.02, 0.03) is True

    def test_returns_false_when_grade_decreases(self):
        """g1=+3%, g2=-2% → crest, not sag."""
        assert subject.is_sag_curve(0.03, -0.02) is False

    def test_returns_false_for_constant_grade(self):
        """No grade change → neither crest nor sag."""
        assert subject.is_sag_curve(-0.01, -0.01) is False

    def test_crest_and_sag_are_mutually_exclusive(self):
        """For any non-constant grade, exactly one of is_crest or is_sag is True."""
        g1, g2 = 0.03, -0.02
        assert subject.is_crest_curve(g1, g2) != subject.is_sag_curve(g1, g2)


# ---------------------------------------------------------------------------
# back_calculate_pvis_from_vertical  (IFC integration — uses real ifcopenshell)
# ---------------------------------------------------------------------------


@requires_geometry_engine
class TestBackCalculatePvisFromVertical(NewFile):
    def _build_alignment_with_vertical(self, vpoints, lengths):
        """Helper: create IfcAlignment + vertical layout via Rick's API.

        Uses align_api.create() to build a complete alignment with proper
        horizontal geometric representation (Axis/Curve2D). This is required
        so that add_vertical_layout() can find a valid BaseCurve for the
        IfcGradientCurve it creates.
        """
        import ifcopenshell.api.root
        import ifcopenshell.api.unit
        import ifcopenshell.api.alignment as align_api

        ifc = ifcopenshell.file(schema="IFC4X3_ADD2")
        tool.Ifc.set(ifc)
        ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcProject")
        # assign_unit is required so align_api.create() can call station_as_string
        ifcopenshell.api.unit.assign_unit(ifc)
        # create() sets up IfcAlignment + IfcAlignmentHorizontal + Axis/Curve2D representation
        alignment = align_api.create(ifc, name="Test Alignment", include_vertical=False)
        h_layout = align_api.get_horizontal_layout(alignment)
        # Simple tangent spanning the full station range (non-collinear to avoid div-by-zero)
        align_api.layout_horizontal_alignment_by_pi_method(
            ifc, h_layout, hpoints=[(0.0, 0.0), (vpoints[-1][0], 200.0)], radii=[]
        )
        v_layout = align_api.add_vertical_layout(ifc, alignment)
        align_api.layout_vertical_alignment_by_pi_method(ifc, v_layout, vpoints, lengths)
        return alignment

    def test_raises_when_alignment_has_no_vertical_layout(self):
        import ifcopenshell.api.root

        ifc = ifcopenshell.file(schema="IFC4X3_ADD2")
        tool.Ifc.set(ifc)
        ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcProject")
        alignment = ifc.createIfcAlignment()
        with pytest.raises(ValueError, match="no vertical layout"):
            subject.back_calculate_pvis_from_vertical(alignment)

    def test_round_trips_two_pvis_with_no_curve(self):
        """Simple grade line: 2 PVIs, no vertical curve."""
        vpoints = [(0.0, 100.0), (500.0, 110.0)]
        lengths = []
        alignment = self._build_alignment_with_vertical(vpoints, lengths)
        pvis = subject.back_calculate_pvis_from_vertical(alignment)
        assert len(pvis) == 2
        assert_close(pvis[0]["station"], 0.0)
        assert_close(pvis[0]["elevation"], 100.0)
        assert_close(pvis[-1]["station"], 500.0)
        assert_close(pvis[-1]["elevation"], 110.0)

    def test_round_trips_three_pvis_with_one_curve(self):
        """Crest curve: 3 PVIs, 1 vertical curve."""
        vpoints = [(0.0, 100.0), (500.0, 110.0), (1000.0, 100.0)]
        lengths = [100.0]
        alignment = self._build_alignment_with_vertical(vpoints, lengths)
        pvis = subject.back_calculate_pvis_from_vertical(alignment)
        assert len(pvis) == 3
        # Interior PVI should be recovered near station 500
        assert_close(pvis[1]["station"], 500.0, tol=1e-3)
        assert_close(pvis[1]["curve_length"], 100.0, tol=1e-3)

    def test_recovered_interior_pvi_elevation_is_tangent_intersection(self):
        """PVI elevation = BVC + g1 * (L/2) — the tangent intersection."""
        vpoints = [(0.0, 100.0), (500.0, 110.0), (1000.0, 100.0)]
        lengths = [100.0]
        alignment = self._build_alignment_with_vertical(vpoints, lengths)
        pvis = subject.back_calculate_pvis_from_vertical(alignment)
        # Back-calculated elevation should match the original PVI
        assert_close(pvis[1]["elevation"], 110.0, tol=1e-3)

    def test_endpoint_curve_lengths_are_zero(self):
        """Endpoints never have a vertical curve."""
        vpoints = [(0.0, 100.0), (500.0, 110.0), (1000.0, 100.0)]
        lengths = [100.0]
        alignment = self._build_alignment_with_vertical(vpoints, lengths)
        pvis = subject.back_calculate_pvis_from_vertical(alignment)
        assert_close(pvis[0]["curve_length"], 0.0)
        assert_close(pvis[-1]["curve_length"], 0.0)


# ===========================================================================
# Blender-Dependent Tool Tests (require full Bonsai IFC4X3 project)
# ===========================================================================
# These tests exercise methods that create or query Blender objects.
# They use NewIfc4X3 which sets up a clean Blender scene with a Bonsai-managed
# IFC4X3 project (IfcProject + geometric contexts + IfcStore integration).


def _create_alignment_with_pis(name="Test Alignment", hpoints=None, radii=None):
    """Helper: create an IfcAlignment, add PI segments, return (alignment, h_layout).

    Uses align_api.create() to build the full alignment hierarchy (IfcAlignment
    + IfcAlignmentHorizontal + zero-length terminator + geometry + project
    aggregation), then lays out horizontal segments via PI method.
    """
    if hpoints is None:
        hpoints = [(0.0, 0.0), (500.0, 0.0), (1000.0, 200.0)]
    if radii is None:
        radii = [300.0]

    ifc_file = tool.Ifc.get()
    alignment = align_api.create(ifc_file, name=name)
    h_layout = align_api.get_horizontal_layout(alignment)

    # Add real segments via PI method
    align_api.layout_horizontal_alignment_by_pi_method(ifc_file, h_layout, hpoints, radii)

    return alignment, h_layout


# ---------------------------------------------------------------------------
# get_horizontal_layout / get_vertical_layout (IFC queries, no bpy needed)
# ---------------------------------------------------------------------------


class TestGetHorizontalLayout(NewIfc4X3):
    """Tests for Alignment.get_horizontal_layout()."""

    def test_returns_horizontal_layout_from_alignment(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="HL Test")
        h_layout = subject.get_horizontal_layout(alignment)
        assert h_layout is not None
        assert h_layout.is_a("IfcAlignmentHorizontal")

    def test_returns_none_for_alignment_without_horizontal(self):
        ifc_file = tool.Ifc.get()
        # Create a bare alignment without the helper (no nesting)
        alignment = ifc_file.createIfcAlignment(GlobalId=ifcopenshell.guid.new(), Name="Bare")
        h_layout = subject.get_horizontal_layout(alignment)
        assert h_layout is None


class TestGetVerticalLayout(NewIfc4X3):
    """Tests for Alignment.get_vertical_layout()."""

    def test_returns_none_when_no_vertical_layout_exists(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="NoVert")
        v_layout = subject.get_vertical_layout(alignment)
        assert v_layout is None

    def test_returns_vertical_layout_when_present(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="WithVert", include_vertical=True)
        v_layout = subject.get_vertical_layout(alignment)
        assert v_layout is not None
        assert v_layout.is_a("IfcAlignmentVertical")


# ---------------------------------------------------------------------------
# layout_by_pi_method (IFC + tool.Ifc integration)
# ---------------------------------------------------------------------------


@requires_geometry_engine
class TestLayoutByPiMethod(NewIfc4X3):
    """Tests for Alignment.layout_by_pi_method() — IFC segment creation."""

    def test_creates_ifc_segments_for_straight_alignment(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="Straight")
        h_layout = subject.get_horizontal_layout(alignment)

        subject.layout_by_pi_method(h_layout, [(0.0, 0.0), (1000.0, 0.0)], [])

        segments = align_api.get_layout_segments(h_layout)
        real_segments = [s for s in segments if not subject.is_zero_length_segment(s)]
        assert len(real_segments) >= 1  # At least one tangent

    def test_creates_arc_segment_for_curve(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="Curve")
        h_layout = subject.get_horizontal_layout(alignment)

        subject.layout_by_pi_method(h_layout, [(0.0, 0.0), (500.0, 0.0), (1000.0, 200.0)], [300.0])

        segments = align_api.get_layout_segments(h_layout)
        real_segments = [s for s in segments if not subject.is_zero_length_segment(s)]
        segment_types = [s.DesignParameters.PredefinedType for s in real_segments if s.DesignParameters]
        assert "LINE" in segment_types
        assert "CIRCULARARC" in segment_types


# ---------------------------------------------------------------------------
# back_calculate_pis_from_alignment (IFC + unit conversion)
# ---------------------------------------------------------------------------


@requires_geometry_engine
class TestBackCalculatePisFromAlignment(NewIfc4X3):
    """Tests for Alignment.back_calculate_pis_from_alignment() — PI recovery."""

    def test_recovers_endpoints_from_straight_alignment(self):
        alignment, _ = _create_alignment_with_pis(hpoints=[(0.0, 0.0), (1000.0, 0.0)], radii=[])
        pis = subject.back_calculate_pis_from_alignment(alignment)
        assert len(pis) >= 2
        assert pis[0]["pi_type"] == "ENDPOINT"
        assert pis[-1]["pi_type"] == "ENDPOINT"
        assert_close(pis[0]["e"], 0.0, tol=0.01)
        assert_close(pis[0]["n"], 0.0, tol=0.01)
        assert_close(pis[-1]["e"], 1000.0, tol=0.01)
        assert_close(pis[-1]["n"], 0.0, tol=0.01)

    def test_recovers_curve_pi_with_radius(self):
        alignment, _ = _create_alignment_with_pis(hpoints=[(0.0, 0.0), (500.0, 0.0), (1000.0, 200.0)], radii=[300.0])
        pis = subject.back_calculate_pis_from_alignment(alignment)
        # Should have 3 PIs: start endpoint, curve PI, end endpoint
        assert len(pis) == 3
        curve_pis = [p for p in pis if p["pi_type"] == "CURVE"]
        assert len(curve_pis) == 1
        assert_close(curve_pis[0]["e"], 500.0, tol=1.0)
        assert_close(curve_pis[0]["n"], 0.0, tol=1.0)
        assert curve_pis[0]["radius"] > 0

    def test_raises_for_alignment_without_horizontal_layout(self):
        ifc_file = tool.Ifc.get()
        alignment = ifc_file.createIfcAlignment(GlobalId=ifcopenshell.guid.new(), Name="Bare")
        with pytest.raises(ValueError, match="no horizontal layout"):
            subject.back_calculate_pis_from_alignment(alignment)

    def test_raises_for_alignment_with_only_terminator(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="EmptyLayout")
        # align_api.create() produces a horizontal layout with only a zero-length terminator
        with pytest.raises(ValueError, match="no real segments"):
            subject.back_calculate_pis_from_alignment(alignment)

    def test_roundtrip_preserves_pi_positions(self):
        """Create alignment from PIs, back-calculate, verify positions match."""
        original_hpoints = [(0.0, 0.0), (500.0, 0.0), (1000.0, 200.0)]
        original_radii = [300.0]
        alignment, _ = _create_alignment_with_pis(hpoints=original_hpoints, radii=original_radii)

        recovered_pis = subject.back_calculate_pis_from_alignment(alignment)
        assert len(recovered_pis) == len(original_hpoints)

        for original, recovered in zip(original_hpoints, recovered_pis):
            assert_close(recovered["e"], original[0], tol=1.0)
            assert_close(recovered["n"], original[1], tol=1.0)


# ---------------------------------------------------------------------------
# Blender Object Creation Methods
# ---------------------------------------------------------------------------


class TestCreateObjectForAlignment(NewIfc4X3):
    """Tests for Alignment.create_object_for_alignment()."""

    def test_creates_empty_object_for_alignment(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="ObjTest")
        obj = subject.create_object_for_alignment(alignment)
        assert obj is not None
        assert obj.type == "EMPTY"
        assert "IfcAlignment" in obj.name

    def test_links_blender_object_to_ifc_entity(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="LinkTest")
        obj = subject.create_object_for_alignment(alignment)
        # Verify bidirectional IFC link
        assert tool.Ifc.get_object(alignment) == obj
        assert tool.Ifc.get_entity(obj) == alignment

    def test_returns_existing_object_if_already_linked(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="DupTest")
        obj1 = subject.create_object_for_alignment(alignment)
        obj2 = subject.create_object_for_alignment(alignment)
        assert obj1 == obj2  # Same object returned, not a duplicate


class TestCreateObjectForLayout(NewIfc4X3):
    """Tests for Alignment.create_object_for_layout()."""

    def test_creates_empty_object_for_horizontal_layout(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="LayoutObj")
        h_layout = align_api.get_horizontal_layout(alignment)
        alignment_obj = subject.create_object_for_alignment(alignment)
        layout_obj = subject.create_object_for_layout(h_layout, alignment_obj)
        assert layout_obj is not None
        assert layout_obj.type == "EMPTY"
        assert "IfcAlignmentHorizontal" in layout_obj.name

    def test_layout_object_is_parented_to_alignment_object(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="ParentTest")
        h_layout = align_api.get_horizontal_layout(alignment)
        alignment_obj = subject.create_object_for_alignment(alignment)
        layout_obj = subject.create_object_for_layout(h_layout, alignment_obj)
        assert layout_obj.parent == alignment_obj


class TestCreateHierarchyForAlignment(NewIfc4X3):
    """Tests for Alignment.create_hierarchy_for_alignment() — full hierarchy creation."""

    def test_creates_alignment_and_layout_objects(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="Hierarchy")
        root_obj = subject.create_hierarchy_for_alignment(alignment)
        assert root_obj is not None
        assert tool.Ifc.get_entity(root_obj) == alignment
        # Should have at least one child (the horizontal layout object)
        child_objects = [o for o in bpy.data.objects if o.parent == root_obj]
        assert len(child_objects) >= 1
        # One of the children should be linked to the horizontal layout
        h_layout = align_api.get_horizontal_layout(alignment)
        layout_obj = tool.Ifc.get_object(h_layout)
        assert layout_obj is not None
        assert layout_obj.parent == root_obj

    def test_creates_vertical_layout_object_when_present(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="WithVert", include_vertical=True)
        root_obj = subject.create_hierarchy_for_alignment(alignment)
        v_layout = align_api.get_vertical_layout(alignment)
        assert v_layout is not None
        v_layout_obj = tool.Ifc.get_object(v_layout)
        assert v_layout_obj is not None
        assert v_layout_obj.parent == root_obj


# ---------------------------------------------------------------------------
# get_active_alignment
# ---------------------------------------------------------------------------


class TestGetActiveAlignment(NewIfc4X3):
    """Tests for Alignment.get_active_alignment() — scene context queries."""

    def test_returns_none_when_no_object_is_active(self):
        bpy.context.view_layer.objects.active = None
        result = subject.get_active_alignment()
        assert result is None

    def test_returns_none_when_active_object_is_not_alignment(self):
        # Active object is some random cube, not an IFC alignment
        bpy.ops.mesh.primitive_cube_add()
        assert subject.get_active_alignment() is None

    def test_returns_alignment_when_active_object_is_linked(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="Active")
        obj = subject.create_object_for_alignment(alignment)
        bpy.context.view_layer.objects.active = obj
        result = subject.get_active_alignment()
        assert result is not None
        assert result.id() == alignment.id()


# ---------------------------------------------------------------------------
# PI Edit Empties
# ---------------------------------------------------------------------------


@requires_geometry_engine
class TestCreatePiEditEmpties(NewIfc4X3):
    """Tests for Alignment.create_pi_edit_empties()."""

    def test_creates_empties_at_pi_positions(self):
        alignment, _ = _create_alignment_with_pis(hpoints=[(0.0, 0.0), (500.0, 0.0), (1000.0, 200.0)], radii=[300.0])
        alignment_obj = subject.create_hierarchy_for_alignment(alignment)
        bpy.context.view_layer.objects.active = alignment_obj

        pis = subject.back_calculate_pis_from_alignment(alignment)
        empties = subject.create_pi_edit_empties(alignment, pis)

        assert len(empties) == len(pis)
        for empty in empties:
            assert empty.type == "EMPTY"
            assert empty.get("civil_is_pi_empty") is True
            assert empty.get("civil_alignment_id") == alignment.id()

    def test_empties_are_parented_to_alignment_object(self):
        alignment, _ = _create_alignment_with_pis(hpoints=[(0.0, 0.0), (500.0, 0.0)], radii=[])
        alignment_obj = subject.create_hierarchy_for_alignment(alignment)
        pis = subject.back_calculate_pis_from_alignment(alignment)
        empties = subject.create_pi_edit_empties(alignment, pis)
        for empty in empties:
            assert empty.parent == alignment_obj

    def test_empties_have_sequential_pi_indices(self):
        alignment, _ = _create_alignment_with_pis(hpoints=[(0.0, 0.0), (500.0, 0.0), (1000.0, 200.0)], radii=[300.0])
        alignment_obj = subject.create_hierarchy_for_alignment(alignment)
        pis = subject.back_calculate_pis_from_alignment(alignment)
        empties = subject.create_pi_edit_empties(alignment, pis)
        indices = [e.get("civil_pi_index") for e in empties]
        assert indices == list(range(len(pis)))


@requires_geometry_engine
class TestGetPiEditEmpties(NewIfc4X3):
    """Tests for Alignment.get_pi_edit_empties()."""

    def test_finds_empties_for_given_alignment_id(self):
        alignment, _ = _create_alignment_with_pis(hpoints=[(0.0, 0.0), (500.0, 0.0)], radii=[])
        alignment_obj = subject.create_hierarchy_for_alignment(alignment)
        pis = subject.back_calculate_pis_from_alignment(alignment)
        subject.create_pi_edit_empties(alignment, pis)

        found = subject.get_pi_edit_empties(alignment.id())
        assert len(found) == len(pis)

    def test_returns_empty_list_when_no_empties_exist(self):
        found = subject.get_pi_edit_empties(99999)
        assert found == []

    def test_returns_sorted_by_pi_index(self):
        alignment, _ = _create_alignment_with_pis(hpoints=[(0.0, 0.0), (500.0, 0.0), (1000.0, 200.0)], radii=[300.0])
        alignment_obj = subject.create_hierarchy_for_alignment(alignment)
        pis = subject.back_calculate_pis_from_alignment(alignment)
        subject.create_pi_edit_empties(alignment, pis)

        found = subject.get_pi_edit_empties(alignment.id())
        indices = [e.get("civil_pi_index") for e in found]
        assert indices == sorted(indices)


@requires_geometry_engine
class TestRemovePiEditEmpties(NewIfc4X3):
    """Tests for Alignment.remove_pi_edit_empties()."""

    def test_removes_all_empties_for_alignment(self):
        alignment, _ = _create_alignment_with_pis(hpoints=[(0.0, 0.0), (500.0, 0.0), (1000.0, 200.0)], radii=[300.0])
        alignment_obj = subject.create_hierarchy_for_alignment(alignment)
        pis = subject.back_calculate_pis_from_alignment(alignment)
        subject.create_pi_edit_empties(alignment, pis)

        removed = subject.remove_pi_edit_empties(alignment.id())
        assert removed == len(pis)
        assert subject.get_pi_edit_empties(alignment.id()) == []

    def test_returns_zero_when_no_empties_exist(self):
        removed = subject.remove_pi_edit_empties(99999)
        assert removed == 0


@requires_geometry_engine
class TestCollectPisFromEmpties(NewIfc4X3):
    """Tests for Alignment.collect_pis_from_empties() — reading positions back."""

    def test_roundtrip_positions_through_empties(self):
        """Create empties from PIs, collect back, verify positions match."""
        alignment, _ = _create_alignment_with_pis(hpoints=[(0.0, 0.0), (500.0, 0.0), (1000.0, 200.0)], radii=[300.0])
        alignment_obj = subject.create_hierarchy_for_alignment(alignment)

        pis = subject.back_calculate_pis_from_alignment(alignment)
        subject.create_pi_edit_empties(alignment, pis)

        # Force Blender to update transforms (empties are parented)
        bpy.context.view_layer.update()

        hpoints_back, radii_back = subject.collect_pis_from_empties(alignment.id())
        assert len(hpoints_back) == len(pis)

        # Positions should round-trip: empties created from pis, collected back
        for pi, (back_e, back_n) in zip(pis, hpoints_back):
            assert_close(back_e, pi["e"], tol=2.0)  # Generous tolerance for georef
            assert_close(back_n, pi["n"], tol=2.0)

    def test_collects_radii_for_interior_pis_only(self):
        alignment, _ = _create_alignment_with_pis(hpoints=[(0.0, 0.0), (500.0, 0.0), (1000.0, 200.0)], radii=[300.0])
        alignment_obj = subject.create_hierarchy_for_alignment(alignment)
        pis = subject.back_calculate_pis_from_alignment(alignment)
        subject.create_pi_edit_empties(alignment, pis)

        _, radii_back = subject.collect_pis_from_empties(alignment.id())
        # Radii should have one entry (for the interior PI)
        assert len(radii_back) == 1
        assert radii_back[0] > 0

    def test_returns_empty_when_fewer_than_two_empties(self):
        hpoints, radii = subject.collect_pis_from_empties(99999)
        assert hpoints == []
        assert radii == []


# ---------------------------------------------------------------------------
# Remove alignment hierarchy
# ---------------------------------------------------------------------------


class TestRemoveAlignmentHierarchy(NewIfc4X3):
    """Tests for Alignment.remove_alignment_hierarchy() — cleanup."""

    def test_removes_all_blender_objects_for_alignment(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="RemoveMe")
        root_obj = subject.create_hierarchy_for_alignment(alignment)
        assert root_obj is not None

        # Count objects before removal (excluding default camera/light)
        alignment_objects_before = [o for o in bpy.data.objects if tool.Ifc.get_entity(o)]
        assert len(alignment_objects_before) > 0

        removed = subject.remove_alignment_hierarchy(alignment)
        assert removed > 0

        # The alignment object should be gone
        assert tool.Ifc.get_object(alignment) is None


# ---------------------------------------------------------------------------
# IFC Roundtrip (save + reload)
# ---------------------------------------------------------------------------


@requires_geometry_engine
class TestIfcSaveReloadRoundtrip(NewIfc4X3):
    """Tests verifying alignment data survives IFC file save/reload."""

    def test_alignment_entities_survive_roundtrip(self):
        import tempfile
        import os

        alignment, _ = _create_alignment_with_pis(hpoints=[(0.0, 0.0), (500.0, 0.0), (1000.0, 200.0)], radii=[300.0])

        ifc_file = tool.Ifc.get()
        alignment_count_before = len(ifc_file.by_type("IfcAlignment"))
        segment_count_before = len(ifc_file.by_type("IfcAlignmentSegment"))

        tmp = tempfile.NamedTemporaryFile(suffix=".ifc", delete=False)
        tmp.close()
        try:
            ifc_file.write(tmp.name)
            reloaded = ifcopenshell.open(tmp.name)

            assert len(reloaded.by_type("IfcAlignment")) == alignment_count_before
            assert len(reloaded.by_type("IfcAlignmentSegment")) == segment_count_before
            assert len(reloaded.by_type("IfcAlignmentHorizontal")) >= 1

            # Verify segment types survived
            segments = reloaded.by_type("IfcAlignmentSegment")
            predefined_types = set()
            for seg in segments:
                dp = seg.DesignParameters
                if dp and hasattr(dp, "PredefinedType") and dp.PredefinedType:
                    predefined_types.add(dp.PredefinedType)
            assert "LINE" in predefined_types
            assert "CIRCULARARC" in predefined_types
        finally:
            os.unlink(tmp.name)


# ---------------------------------------------------------------------------
# evaluate_alignment_at_station  (D3 keystone — 3D combination)
# ---------------------------------------------------------------------------


@requires_geometry_engine
class TestEvaluateAlignmentAtStation(NewFile):
    """Tests for Alignment.evaluate_alignment_at_station().

    Built on a straight-east horizontal so XY positions are predictable
    (station -> x, y == 0), with a symmetric crest vertical curve. The model
    units are millimetres (default assign_unit), so these also exercise the
    SI<->model unit conversion in the evaluation path.
    """

    def _build(self, vpoints, lengths, hpoints=None):
        import ifcopenshell.api.root
        import ifcopenshell.api.unit

        ifc = ifcopenshell.file(schema="IFC4X3_ADD2")
        tool.Ifc.set(ifc)
        ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcProject")
        ifcopenshell.api.unit.assign_unit(ifc)
        alignment = align_api.create(ifc, name="Eval", include_vertical=False)
        h_layout = align_api.get_horizontal_layout(alignment)
        if hpoints is None:
            # Straight east tangent spanning the full station range.
            hpoints = [(0.0, 0.0), (vpoints[-1][0], 0.0)]
        align_api.layout_horizontal_alignment_by_pi_method(ifc, h_layout, hpoints=hpoints, radii=[])
        if vpoints is not None:
            v_layout = align_api.add_vertical_layout(ifc, alignment)
            align_api.layout_vertical_alignment_by_pi_method(ifc, v_layout, vpoints, lengths)
        return alignment

    # Crest curve: +2% in, -2% out, 100-unit parabola at the middle PVI.
    CREST = ([(0.0, 100.0), (500.0, 110.0), (1000.0, 100.0)], [100.0])

    def test_returns_alignment_point(self):
        alignment = self._build(*self.CREST)
        result = subject.evaluate_alignment_at_station(alignment, 250.0)
        assert isinstance(result, AlignmentPoint)
        assert_close(result.station, 250.0)

    def test_position_on_entry_grade_tangent(self):
        """Before the curve (BVC at 450): straight +2% grade from elev 100."""
        alignment = self._build(*self.CREST)
        result = subject.evaluate_alignment_at_station(alignment, 250.0)
        assert_close(result.position[0], 250.0, tol=0.1)  # x == station (straight east)
        assert_close(result.position[1], 0.0, tol=0.1)  # y == 0
        assert_close(result.position[2], 105.0, tol=0.1)  # 100 + 0.02*250
        assert_close(result.grade, 0.02, tol=1e-3)

    def test_position_at_start(self):
        alignment = self._build(*self.CREST)
        result = subject.evaluate_alignment_at_station(alignment, 0.0)
        assert_close(result.position[0], 0.0, tol=0.1)
        assert_close(result.position[2], 100.0, tol=0.1)  # start elevation
        assert_close(result.grade, 0.02, tol=1e-3)

    def test_position_at_crest_apex(self):
        """At the PVI station the symmetric crest apex sits L/8 below the PVI:
        elev = 109.5 (BVC 109 at sta 450, +0.02*50 - 0.5)."""
        alignment = self._build(*self.CREST)
        result = subject.evaluate_alignment_at_station(alignment, 500.0)
        assert_close(result.position[2], 109.5, tol=0.1)
        assert_close(result.grade, 0.0, tol=1e-3)  # grade is zero at the apex

    def test_position_at_end_on_exit_grade(self):
        alignment = self._build(*self.CREST)
        result = subject.evaluate_alignment_at_station(alignment, 1000.0)
        assert_close(result.position[0], 1000.0, tol=0.1)
        assert_close(result.position[2], 100.0, tol=0.1)
        assert_close(result.grade, -0.02, tol=1e-3)

    def test_frame_is_orthonormal(self):
        alignment = self._build(*self.CREST)
        result = subject.evaluate_alignment_at_station(alignment, 250.0)

        def dot(a, b):
            return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

        for vec in (result.tangent, result.normal, result.up):
            assert_close(math.sqrt(dot(vec, vec)), 1.0, tol=1e-6)  # unit length
        assert_close(dot(result.tangent, result.normal), 0.0, tol=1e-6)
        assert_close(dot(result.tangent, result.up), 0.0, tol=1e-6)
        assert_close(dot(result.normal, result.up), 0.0, tol=1e-6)
        # Travel is mostly +x (straight east), up is mostly +z.
        assert result.tangent[0] > 0.99
        assert result.up[2] > 0.9

    def test_returns_none_beyond_end(self):
        """The engine extrapolates past the end; we must reject it."""
        alignment = self._build(*self.CREST)
        assert subject.evaluate_alignment_at_station(alignment, 1500.0) is None

    def test_returns_none_before_start(self):
        alignment = self._build(*self.CREST)
        assert subject.evaluate_alignment_at_station(alignment, -10.0) is None

    def test_horizontal_only_alignment_has_zero_elevation(self):
        """With no vertical layout the curve is a composite curve; Z == 0."""
        alignment = self._build(vpoints=None, lengths=None, hpoints=[(0.0, 0.0), (500.0, 0.0)])
        result = subject.evaluate_alignment_at_station(alignment, 250.0)
        assert result is not None
        assert_close(result.position[0], 250.0, tol=0.1)
        assert_close(result.position[2], 0.0, tol=0.1)
        assert_close(result.grade, 0.0, tol=1e-3)


@requires_geometry_engine
class TestGetAlignmentLength(NewFile):
    """Tests for Alignment.get_alignment_length()."""

    def test_sums_horizontal_segment_lengths(self):
        import ifcopenshell.api.root
        import ifcopenshell.api.unit

        ifc = ifcopenshell.file(schema="IFC4X3_ADD2")
        tool.Ifc.set(ifc)
        ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcProject")
        ifcopenshell.api.unit.assign_unit(ifc)
        alignment = align_api.create(ifc, name="Len", include_vertical=False)
        h_layout = align_api.get_horizontal_layout(alignment)
        align_api.layout_horizontal_alignment_by_pi_method(ifc, h_layout, hpoints=[(0.0, 0.0), (1000.0, 0.0)], radii=[])
        assert_close(subject.get_alignment_length(alignment), 1000.0, tol=1e-6)

    def test_returns_none_without_horizontal_layout(self):
        import ifcopenshell.api.root

        ifc = ifcopenshell.file(schema="IFC4X3_ADD2")
        tool.Ifc.set(ifc)
        ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcProject")
        bare = ifc.createIfcAlignment()
        assert subject.get_alignment_length(bare) is None


# ---------------------------------------------------------------------------
# create_3d_alignment_object  (D3 — draped 3D centerline visualization)
# ---------------------------------------------------------------------------


@requires_geometry_engine
class TestCreate3DAlignmentObject(NewIfc4X3):
    """Tests for Alignment.create_3d_alignment_object()."""

    def _build_with_vertical(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="C3D", include_vertical=False)
        h = align_api.get_horizontal_layout(alignment)
        align_api.layout_horizontal_alignment_by_pi_method(ifc_file, h, hpoints=[(0.0, 0.0), (1000.0, 0.0)], radii=[])
        v = align_api.add_vertical_layout(ifc_file, alignment)
        align_api.layout_vertical_alignment_by_pi_method(
            ifc_file, v, [(0.0, 100.0), (500.0, 110.0), (1000.0, 100.0)], [100.0]
        )
        subject.create_hierarchy_for_alignment(alignment)
        return alignment

    def test_creates_mesh_object_with_draped_elevation(self):
        alignment = self._build_with_vertical()
        obj = subject.create_3d_alignment_object(alignment, distance_interval=50.0)
        assert obj is not None
        assert obj.type == "MESH"
        assert len(obj.data.vertices) >= 2
        zs = [v.co.z for v in obj.data.vertices]
        # The vertical curve drapes the centerline: Z must vary, not be flat.
        assert (max(zs) - min(zs)) > 1.0

    def test_is_idempotent(self):
        alignment = self._build_with_vertical()
        subject.create_3d_alignment_object(alignment, distance_interval=50.0)
        obj2 = subject.create_3d_alignment_object(alignment, distance_interval=50.0)
        assert obj2 is not None
        centerlines = [o for o in bpy.data.objects if o.get(subject.CENTERLINE_3D_TAG) == alignment.id()]
        assert len(centerlines) == 1  # rebuilt, not duplicated
        assert centerlines[0] == obj2  # the survivor is the freshly-built object

    def test_remove_3d_alignment_object(self):
        alignment = self._build_with_vertical()
        subject.create_3d_alignment_object(alignment, distance_interval=50.0)
        removed = subject.remove_3d_alignment_object(alignment)
        assert removed == 1
        centerlines = [o for o in bpy.data.objects if o.get(subject.CENTERLINE_3D_TAG) == alignment.id()]
        assert centerlines == []


# ---------------------------------------------------------------------------
# buildingSMART validation  (D1 verification criterion for vertical output)
# ---------------------------------------------------------------------------


@requires_geometry_engine
class TestAlignmentVerticalBSIIntegration(NewIfc4X3):
    """Round-trips a horizontal+vertical alignment through
    ``ifcopenshell.validate`` to assert the IfcAlignmentVertical /
    IfcGradientCurve output is schema-clean — the D1 deliverable's
    "passes buildingSMART validation" criterion.
    """

    @staticmethod
    def _validate_clean(ifc_path):
        import logging
        import ifcopenshell.validate

        reopened = ifcopenshell.open(str(ifc_path))
        records: list = []

        class _CollectingHandler(logging.Handler):
            def emit(self, record):
                records.append(record)

        logger = logging.Logger("vertical-bsi-validate")
        logger.addHandler(_CollectingHandler(level=logging.DEBUG))
        ifcopenshell.validate.validate(reopened, logger)

        errors = [r.getMessage() for r in records if r.levelno >= logging.WARNING]
        assert errors == [], f"ifcopenshell.validate() reported: {errors}"
        return reopened

    def test_vertical_alignment_passes_validation_with_expected_entities(self, tmp_path):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="BSIVert", include_vertical=False)
        h = align_api.get_horizontal_layout(alignment)
        align_api.layout_horizontal_alignment_by_pi_method(
            ifc_file, h, hpoints=[(0.0, 0.0), (500.0, 0.0), (1000.0, 200.0)], radii=[300.0]
        )
        v = align_api.add_vertical_layout(ifc_file, alignment)
        align_api.layout_vertical_alignment_by_pi_method(
            ifc_file, v, [(0.0, 100.0), (500.0, 110.0), (1000.0, 100.0)], [100.0]
        )

        # Combining horizontal + vertical yields an IfcGradientCurve.
        assert align_api.get_curve(alignment).is_a() == "IfcGradientCurve"

        ifc_path = tmp_path / "vertical_bsi.ifc"
        ifc_file.write(str(ifc_path))
        reopened = self._validate_clean(ifc_path)

        # D1: IfcAlignmentVertical with CONSTANTGRADIENT + PARABOLICARC segments.
        assert len(reopened.by_type("IfcAlignmentVertical")) >= 1
        vertical_segments = [
            s
            for s in reopened.by_type("IfcAlignmentSegment")
            if s.DesignParameters and s.DesignParameters.is_a("IfcAlignmentVerticalSegment")
        ]
        vertical_types = {s.DesignParameters.PredefinedType for s in vertical_segments}
        assert "CONSTANTGRADIENT" in vertical_types
        assert "PARABOLICARC" in vertical_types
        # The 3D combined representation survives the round-trip.
        assert len(reopened.by_type("IfcGradientCurve")) >= 1


# ---------------------------------------------------------------------------
# ProfileViewTransform  (D2 — screen <-> profile-data coordinate mapping)
# ---------------------------------------------------------------------------


class TestProfileViewTransform(NewFile):
    @staticmethod
    def _transform():
        return ProfileViewTransform(
            station_min=0.0,
            station_max=100.0,
            elevation_min=10.0,
            elevation_max=20.0,
            rect_x=50.0,
            rect_y=30.0,
            rect_width=200.0,
            rect_height=100.0,
        )

    def test_data_to_screen_at_origin(self):
        px, py = self._transform().data_to_screen(0.0, 10.0)
        assert_close(px, 50.0, tol=1e-6)
        assert_close(py, 30.0, tol=1e-6)

    def test_data_to_screen_at_far_corner(self):
        px, py = self._transform().data_to_screen(100.0, 20.0)
        assert_close(px, 250.0, tol=1e-6)
        assert_close(py, 130.0, tol=1e-6)

    def test_data_to_screen_at_midpoint(self):
        px, py = self._transform().data_to_screen(50.0, 15.0)
        assert_close(px, 150.0, tol=1e-6)
        assert_close(py, 80.0, tol=1e-6)

    def test_screen_to_data_round_trips(self):
        transform = self._transform()
        px, py = transform.data_to_screen(37.0, 14.5)
        station, elevation = transform.screen_to_data(px, py)
        assert_close(station, 37.0, tol=1e-6)
        assert_close(elevation, 14.5, tol=1e-6)

    def test_zero_span_does_not_divide_by_zero(self):
        transform = ProfileViewTransform(5.0, 5.0, 5.0, 5.0, 0.0, 0.0, 100.0, 100.0)
        px, py = transform.data_to_screen(5.0, 5.0)  # must not raise
        station, elevation = transform.screen_to_data(px, py)
        assert isinstance(station, float) and isinstance(elevation, float)


class TestBuildProfileViewTransform(NewFile):
    def test_returns_none_for_no_data(self):
        assert subject.build_profile_view_transform([], [], 0.0, 0.0, 100.0, 100.0) is None

    def test_bounds_cover_design_and_terrain_with_padding(self):
        design = [(0.0, 100.0), (100.0, 110.0)]
        terrain = [(0.0, 95.0), (100.0, 108.0)]
        transform = subject.build_profile_view_transform(design, terrain, 10.0, 20.0, 300.0, 150.0)
        assert_close(transform.station_min, 0.0)
        assert_close(transform.station_max, 100.0)
        # Elevation bounds are padded beyond the raw [95, 110] data range.
        assert transform.elevation_min < 95.0
        assert transform.elevation_max > 110.0
        assert (transform.rect_x, transform.rect_y) == (10.0, 20.0)
        assert (transform.rect_width, transform.rect_height) == (300.0, 150.0)

    def test_exaggeration_locks_vertical_scale_to_horizontal(self):
        design = [(0.0, 100.0), (1000.0, 110.0)]
        transform = subject.build_profile_view_transform(design, [], 0.0, 0.0, 500.0, 200.0, vertical_exaggeration=10.0)
        # Horizontal scale: 500 px / 1000 units = 0.5 px/unit; ×10 exaggeration
        # gives 5 px/unit vertically → 200 px shows 40 units, centered on 105.
        assert_close(transform.elevation_min, 85.0)
        assert_close(transform.elevation_max, 125.0)

    def test_zero_exaggeration_keeps_auto_fit_with_padding(self):
        design = [(0.0, 100.0), (1000.0, 110.0)]
        transform = subject.build_profile_view_transform(design, [], 0.0, 0.0, 500.0, 200.0, vertical_exaggeration=0.0)
        # Auto-fit pads the raw [100, 110] range by 10% of the span each side.
        assert_close(transform.elevation_min, 99.0)
        assert_close(transform.elevation_max, 111.0)


# ---------------------------------------------------------------------------
# sample_design_profile / sample_terrain_profile  (D2 profile sampling)
# ---------------------------------------------------------------------------


@requires_geometry_engine
class TestSampleDesignProfile(NewFile):
    def _build(self, vpoints, lengths):
        import ifcopenshell.api.root
        import ifcopenshell.api.unit

        ifc = ifcopenshell.file(schema="IFC4X3_ADD2")
        tool.Ifc.set(ifc)
        ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcProject")
        ifcopenshell.api.unit.assign_unit(ifc)
        alignment = align_api.create(ifc, name="Profile", include_vertical=False)
        h_layout = align_api.get_horizontal_layout(alignment)
        align_api.layout_horizontal_alignment_by_pi_method(
            ifc, h_layout, hpoints=[(0.0, 0.0), (vpoints[-1][0], 0.0)], radii=[]
        )
        v_layout = align_api.add_vertical_layout(ifc, alignment)
        align_api.layout_vertical_alignment_by_pi_method(ifc, v_layout, vpoints, lengths)
        return alignment

    def test_endpoints_match_design(self):
        alignment = self._build([(0.0, 100.0), (500.0, 110.0), (1000.0, 100.0)], [100.0])
        points = subject.sample_design_profile(alignment, interval=100.0)
        assert len(points) >= 2
        assert_close(points[0][0], 0.0, tol=0.5)
        assert_close(points[0][1], 100.0, tol=0.5)
        assert_close(points[-1][0], 1000.0, tol=0.5)
        assert_close(points[-1][1], 100.0, tol=0.5)

    def test_profile_follows_parabola_apex_below_pvi(self):
        """The crest apex (~109.5) is below the PVI tangent intersection (110),
        proving the parabola — not the straight tangents — is being sampled."""
        alignment = self._build([(0.0, 100.0), (500.0, 110.0), (1000.0, 100.0)], [100.0])
        points = subject.sample_design_profile(alignment, interval=50.0)
        max_elevation = max(elevation for _, elevation in points)
        assert 109.0 <= max_elevation < 110.0

    def test_returns_empty_without_horizontal(self):
        import ifcopenshell.api.root

        ifc = ifcopenshell.file(schema="IFC4X3_ADD2")
        tool.Ifc.set(ifc)
        ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcProject")
        bare = ifc.createIfcAlignment()
        assert subject.sample_design_profile(bare, interval=100.0) == []


@requires_geometry_engine
class TestSampleTerrainProfile(NewFile):
    def _build_horizontal(self, length=1000.0):
        import ifcopenshell.api.root
        import ifcopenshell.api.unit

        ifc = ifcopenshell.file(schema="IFC4X3_ADD2")
        tool.Ifc.set(ifc)
        ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcProject")
        ifcopenshell.api.unit.assign_unit(ifc)
        alignment = align_api.create(ifc, name="TerrainAlign", include_vertical=False)
        h_layout = align_api.get_horizontal_layout(alignment)
        align_api.layout_horizontal_alignment_by_pi_method(ifc, h_layout, hpoints=[(0.0, 0.0), (length, 0.0)], radii=[])
        return alignment

    @staticmethod
    def _make_flat_terrain(z, size):
        """Flat terrain quad in Blender world metres at height ``z``."""
        mesh = bpy.data.meshes.new("Terrain")
        verts = [(-size, -size, z), (size, -size, z), (size, size, z), (-size, size, z)]
        mesh.from_pydata(verts, [], [(0, 1, 2, 3)])
        mesh.update()
        obj = bpy.data.objects.new("Terrain", mesh)
        bpy.context.collection.objects.link(obj)
        return obj

    def test_flat_terrain_returns_constant_elevation(self):
        # The model is millimetres (unit_scale=0.001) and the 1000-unit alignment
        # spans 0..1 m in Blender world. A flat terrain at z=0.05 m therefore
        # reports a ground elevation of 0.05 / 0.001 = 50 project units.
        alignment = self._build_horizontal(1000.0)
        terrain = self._make_flat_terrain(z=0.05, size=5.0)
        points = subject.sample_terrain_profile(alignment, terrain, interval=100.0)
        assert len(points) >= 2
        for _station, ground in points:
            assert_close(ground, 50.0, tol=0.5)

    def test_returns_empty_for_no_terrain(self):
        alignment = self._build_horizontal(1000.0)
        assert subject.sample_terrain_profile(alignment, None, interval=100.0) == []

    def test_get_alignment_start_station_is_zero(self):
        alignment = self._build_horizontal(1000.0)
        assert_close(subject.get_alignment_start_station(alignment), 0.0, tol=1e-6)


# ---------------------------------------------------------------------------
# Registration smoke test  (D2 + D3 operators / panel / props)
# ---------------------------------------------------------------------------


class TestProfileAndD3Registration(NewFile):
    """The pytest-bdd conftest issue blocks the operator-test directory, so
    this verifies the new D2/D3 operators, panel, and properties registered
    cleanly with the Bonsai addon (the failure mode operator tests would catch)."""

    def test_operators_registered(self):
        for name in (
            "CIVIL_OT_visualize_3d_alignment",
            "CIVIL_OT_toggle_profile_view",
            "CIVIL_OT_refresh_profile_view",
            "CIVIL_OT_edit_pvi_in_profile",
        ):
            assert hasattr(bpy.types, name), f"{name} is not registered"

    def test_panel_registered(self):
        assert hasattr(bpy.types, "CIVIL_PT_profile_view")

    def test_profile_view_properties_registered(self):
        props = bpy.context.scene.CivilAlignmentProperties
        assert hasattr(props, "profile_terrain")
        assert hasattr(props, "show_profile_view")
        assert hasattr(props, "profile_view_interval")
        assert hasattr(props, "profile_view_height")
        assert hasattr(props, "profile_exaggeration")


# ---------------------------------------------------------------------------
# clear_layout_segments  (re-implemented after upstream removed the API helper)
# ---------------------------------------------------------------------------


@requires_geometry_engine
class TestClearLayoutSegments(NewFile):
    """The alignment API exposes no segment-clearing helper and its layout
    functions only append, so editing relies on tool.Alignment.clear_layout_segments.
    These verify it removes real segments (both halves) without orphans and
    keeps the zero-length terminator, for horizontal and vertical layouts."""

    @staticmethod
    def _new_ifc():
        import ifcopenshell.api.root
        import ifcopenshell.api.unit

        ifc = ifcopenshell.file(schema="IFC4X3_ADD2")
        tool.Ifc.set(ifc)
        ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcProject")
        ifcopenshell.api.unit.assign_unit(ifc)
        return ifc

    def test_clear_horizontal_keeps_only_terminator(self):
        ifc = self._new_ifc()
        alignment = align_api.create(ifc, name="Clr", include_vertical=False)
        h = align_api.get_horizontal_layout(alignment)
        align_api.layout_horizontal_alignment_by_pi_method(
            ifc, h, hpoints=[(0.0, 0.0), (500.0, 0.0), (1000.0, 200.0)], radii=[300.0]
        )
        assert subject.layout_has_real_segments(h) is True
        subject.clear_layout_segments(h)
        assert subject.layout_has_real_segments(h) is False
        assert len(align_api.get_layout_segments(h)) == 1  # terminator only

    def test_relayout_after_clear_has_no_doubling_or_orphans(self):
        ifc = self._new_ifc()
        alignment = align_api.create(ifc, name="Clr2", include_vertical=False)
        h = align_api.get_horizontal_layout(alignment)
        align_api.layout_horizontal_alignment_by_pi_method(
            ifc, h, hpoints=[(0.0, 0.0), (500.0, 0.0), (1000.0, 200.0)], radii=[300.0]
        )
        subject.clear_layout_segments(h)
        align_api.layout_horizontal_alignment_by_pi_method(ifc, h, hpoints=[(0.0, 0.0), (1000.0, 0.0)], radii=[])
        nested = align_api.get_layout_segments(h)
        real = [s for s in nested if not subject.is_zero_length_segment(s)]
        assert len(real) == 1  # exactly one LINE — no leftover from the first layout
        # No orphaned semantic segments left in the file.
        assert len(ifc.by_type("IfcAlignmentSegment")) == len(nested)

    def test_clear_vertical_keeps_only_terminator(self):
        ifc = self._new_ifc()
        alignment = align_api.create(ifc, name="ClrV", include_vertical=False)
        h = align_api.get_horizontal_layout(alignment)
        align_api.layout_horizontal_alignment_by_pi_method(ifc, h, hpoints=[(0.0, 0.0), (1000.0, 0.0)], radii=[])
        v = align_api.add_vertical_layout(ifc, alignment)
        align_api.layout_vertical_alignment_by_pi_method(
            ifc, v, [(0.0, 100.0), (500.0, 110.0), (1000.0, 100.0)], [100.0]
        )
        assert subject.layout_has_real_segments(v) is True
        subject.clear_layout_segments(v)
        assert subject.layout_has_real_segments(v) is False


@requires_geometry_engine
class TestSetLayoutSegmentsSelectable(NewIfc4X3):
    """PI edit mode disables segment-curve selection so clicks hit the PI
    empties; set_layout_segments_selectable toggles hide_select accordingly."""

    def test_toggles_segment_hide_select(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="Sel", include_vertical=False)
        h = align_api.get_horizontal_layout(alignment)
        align_api.layout_horizontal_alignment_by_pi_method(
            ifc_file, h, hpoints=[(0.0, 0.0), (500.0, 0.0), (1000.0, 200.0)], radii=[300.0]
        )
        subject.create_hierarchy_for_alignment(alignment)
        segment_objects = [o for o in bpy.data.objects if "IfcAlignmentSegment" in o.name]
        assert len(segment_objects) >= 1

        subject.set_layout_segments_selectable(h, False)
        assert all(o.hide_select for o in segment_objects)

        subject.set_layout_segments_selectable(h, True)
        assert all(not o.hide_select for o in segment_objects)


class TestFormatStation(NewFile):
    """tool.Alignment.format_station — project-unit-driven stationing notation."""

    def _make_file(self, length):
        import ifcopenshell.api.root
        import ifcopenshell.api.unit

        ifc = ifcopenshell.file(schema="IFC4X3_ADD2")
        tool.Ifc.set(ifc)
        ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcProject")
        ifcopenshell.api.unit.assign_unit(ifc, length=length)
        return ifc

    def test_metric_metre_project_uses_three_digit_groups(self):
        self._make_file(length={"is_metric": True, "raw": "METERS"})
        assert subject.format_station(10050.0) == "10+050.000"

    def test_imperial_foot_project_uses_two_digit_groups(self):
        self._make_file(length={"is_metric": False, "raw": "FEET"})
        assert subject.format_station(10050.0) == "100+50.00"

    def test_zero_station_metric(self):
        self._make_file(length={"is_metric": True, "raw": "METERS"})
        assert subject.format_station(0.0) == "0+000.000"

    def test_negative_station_keeps_sign(self):
        self._make_file(length={"is_metric": True, "raw": "METERS"})
        assert subject.format_station(-50.0) == "-0+050.000"

    def test_without_project_falls_back_to_plain_number(self):
        assert subject.format_station(1234.5) == "1234.50"


class TestRequiredKForDesignSpeed(NewFile):
    """AASHTO stopping-sight-distance K lookup (spec 2.4, advisory only)."""

    def _make_file(self, length):
        import ifcopenshell.api.root
        import ifcopenshell.api.unit

        ifc = ifcopenshell.file(schema="IFC4X3_ADD2")
        tool.Ifc.set(ifc)
        ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcProject")
        ifcopenshell.api.unit.assign_unit(ifc, length=length)
        return ifc

    def test_zero_speed_disables_checking(self):
        self._make_file(length={"is_metric": True, "raw": "METERS"})
        assert subject.required_k_for_design_speed(0.0, is_crest=True) is None

    def test_metric_exact_row(self):
        self._make_file(length={"is_metric": True, "raw": "METERS"})
        assert subject.required_k_for_design_speed(100.0, is_crest=True) == pytest.approx(52.0)
        assert subject.required_k_for_design_speed(100.0, is_crest=False) == pytest.approx(45.0)

    def test_metric_rounds_up_to_next_tabulated_speed(self):
        self._make_file(length={"is_metric": True, "raw": "METERS"})
        # 55 km/h is not tabulated; the 60 km/h row governs (conservative).
        assert subject.required_k_for_design_speed(55.0, is_crest=True) == pytest.approx(11.0)

    def test_imperial_project_uses_mph_table(self):
        self._make_file(length={"is_metric": False, "raw": "FEET"})
        assert subject.required_k_for_design_speed(60.0, is_crest=True) == pytest.approx(151.0)
        assert subject.required_k_for_design_speed(60.0, is_crest=False) == pytest.approx(136.0)

    def test_speed_above_table_returns_none(self):
        self._make_file(length={"is_metric": True, "raw": "METERS"})
        assert subject.required_k_for_design_speed(200.0, is_crest=True) is None


class TestDesignCriteriaPset(NewFile):
    """Design speed persistence on the alignment (Pset_SaikeiDesignCriteria)."""

    def _make_alignment(self):
        import ifcopenshell.api.root
        import ifcopenshell.api.unit

        ifc = ifcopenshell.file(schema="IFC4X3_ADD2")
        tool.Ifc.set(ifc)
        ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcProject")
        ifcopenshell.api.unit.assign_unit(ifc)
        return ifc.createIfcAlignment(GlobalId=ifcopenshell.guid.new(), Name="A1")

    def test_round_trips_design_speed(self):
        alignment = self._make_alignment()
        subject.set_design_criteria(alignment, 60.0)
        assert subject.get_design_criteria(alignment) == pytest.approx(60.0)

    def test_set_twice_updates_in_place(self):
        alignment = self._make_alignment()
        subject.set_design_criteria(alignment, 60.0)
        subject.set_design_criteria(alignment, 45.0)
        assert subject.get_design_criteria(alignment) == pytest.approx(45.0)
        ifc = tool.Ifc.get()
        assert len([p for p in ifc.by_type("IfcPropertySet") if p.Name == "Pset_SaikeiDesignCriteria"]) == 1

    def test_returns_none_when_never_set(self):
        alignment = self._make_alignment()
        assert subject.get_design_criteria(alignment) is None


# ===========================================================================
# PI Edit Mode — In-Mode Editing (spec 1.3) — pure math, no Blender objects
# ===========================================================================
# compute_curve_tangent_length / project_point_onto_segment_2d /
# line_intersection_2d / find_tangent_insertion_point /
# validate_curve_fit_geometry / slide_tangent all take plain (x, y) tuples,
# so they are unit-testable independent of Blender objects or the IFC file.


class TestComputeCurveTangentLength(NewFile):
    """Tests for Alignment.compute_curve_tangent_length()."""

    def test_returns_zero_when_radius_is_zero(self):
        t = subject.compute_curve_tangent_length((-100.0, 0.0), (0.0, 0.0), (0.0, 100.0), 0.0)
        assert t == 0.0

    def test_returns_zero_when_prev_missing(self):
        t = subject.compute_curve_tangent_length(None, (0.0, 0.0), (0.0, 100.0), 50.0)
        assert t == 0.0

    def test_returns_zero_when_next_missing(self):
        t = subject.compute_curve_tangent_length((-100.0, 0.0), (0.0, 0.0), None, 50.0)
        assert t == 0.0

    def test_right_angle_turn_gives_tangent_length_equal_to_radius(self):
        # A 90-degree deflection: T = R * tan(45deg) = R.
        t = subject.compute_curve_tangent_length((-100.0, 0.0), (0.0, 0.0), (0.0, 100.0), 50.0)
        assert_close(t, 50.0, tol=1e-6)

    def test_straight_through_pi_gives_zero_tangent_length(self):
        # Collinear PI: no deflection, so even a "curved" PI claims nothing.
        t = subject.compute_curve_tangent_length((-100.0, 0.0), (0.0, 0.0), (100.0, 0.0), 50.0)
        assert_close(t, 0.0, tol=1e-6)


class TestProjectPointOntoSegment2D(NewFile):
    """Tests for Alignment.project_point_onto_segment_2d()."""

    def test_projects_onto_middle_of_segment(self):
        t, closest, perpendicular = subject.project_point_onto_segment_2d((50.0, 10.0), (0.0, 0.0), (100.0, 0.0))
        assert_close(t, 0.5, tol=1e-9)
        assert closest == pytest.approx((50.0, 0.0))
        assert_close(perpendicular, 10.0, tol=1e-9)

    def test_clamps_before_segment_start(self):
        t, closest, perpendicular = subject.project_point_onto_segment_2d((-50.0, 0.0), (0.0, 0.0), (100.0, 0.0))
        assert t == 0.0
        assert closest == pytest.approx((0.0, 0.0))

    def test_clamps_after_segment_end(self):
        t, closest, perpendicular = subject.project_point_onto_segment_2d((150.0, 0.0), (0.0, 0.0), (100.0, 0.0))
        assert t == 1.0
        assert closest == pytest.approx((100.0, 0.0))

    def test_degenerate_segment_returns_start_point(self):
        t, closest, perpendicular = subject.project_point_onto_segment_2d((3.0, 4.0), (0.0, 0.0), (0.0, 0.0))
        assert t == 0.0
        assert closest == (0.0, 0.0)
        assert_close(perpendicular, 5.0, tol=1e-9)


class TestLineIntersection2D(NewFile):
    """Tests for Alignment.line_intersection_2d()."""

    def test_intersecting_lines(self):
        point = subject.line_intersection_2d((0.0, 0.0), (1.0, 0.0), (5.0, -5.0), (0.0, 1.0))
        assert point == pytest.approx((5.0, 0.0))

    def test_parallel_lines_return_none(self):
        point = subject.line_intersection_2d((0.0, 0.0), (1.0, 0.0), (0.0, 5.0), (2.0, 0.0))
        assert point is None


class TestFindTangentInsertionPoint(NewFile):
    """Tests for Alignment.find_tangent_insertion_point() — spec 1.3 'I' key."""

    def test_refuses_when_fewer_than_two_points(self):
        result = subject.find_tangent_insertion_point([(0.0, 0.0)], [0.0], (0.0, 0.0))
        assert result["ok"] is False

    def test_point_projects_onto_correct_segment(self):
        points = [(0.0, 0.0), (100.0, 0.0), (200.0, 0.0)]
        radii = [0.0, 0.0, 0.0]
        result = subject.find_tangent_insertion_point(points, radii, (150.0, 5.0))
        assert result["ok"] is True
        assert result["segment_index"] == 1
        assert result["point"] == pytest.approx((150.0, 0.0))

    def test_allows_insertion_just_outside_curve_extent(self):
        # PI 1 is a 90-degree bend with R=50 -> T=50 claimed on both sides.
        points = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)]
        radii = [0.0, 50.0, 0.0]
        result = subject.find_tangent_insertion_point(points, radii, (20.0, 0.0))
        assert result["ok"] is True
        assert result["segment_index"] == 0

    def test_refuses_insertion_inside_curve_extent_on_incoming_tangent(self):
        points = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)]
        radii = [0.0, 50.0, 0.0]
        # (80, 0) is 80 units along segment 0 (length 100); T=50 blocks
        # anything past x=50.
        result = subject.find_tangent_insertion_point(points, radii, (80.0, 0.0))
        assert result["ok"] is False
        assert "tangent extents" in result["reason"]

    def test_refuses_insertion_inside_curve_extent_on_outgoing_tangent(self):
        points = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)]
        radii = [0.0, 50.0, 0.0]
        # (100, 20) is 20 units along segment 1; T=50 blocks anything before y=50.
        result = subject.find_tangent_insertion_point(points, radii, (100.0, 20.0))
        assert result["ok"] is False
        assert "tangent extents" in result["reason"]


class TestValidateCurveFitGeometry(NewFile):
    """Tests for Alignment.validate_curve_fit_geometry() — spec 1.3 'C' key."""

    def test_fits_with_ample_tangent_length(self):
        points = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)]
        radii = [0.0, 0.0, 0.0]
        ok, reason = subject.validate_curve_fit_geometry(points, radii, 1, 50.0)
        assert ok is True
        assert reason is None

    def test_refuses_radius_not_positive(self):
        points = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)]
        radii = [0.0, 0.0, 0.0]
        ok, reason = subject.validate_curve_fit_geometry(points, radii, 1, 0.0)
        assert ok is False
        assert "greater than zero" in reason

    def test_refuses_endpoint_index(self):
        points = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)]
        radii = [0.0, 0.0, 0.0]
        ok, reason = subject.validate_curve_fit_geometry(points, radii, 0, 50.0)
        assert ok is False
        assert "interior" in reason.lower()

    def test_refuses_when_too_large_for_available_tangent(self):
        points = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)]
        radii = [0.0, 0.0, 0.0]
        ok, reason = subject.validate_curve_fit_geometry(points, radii, 1, 200.0)
        assert ok is False
        assert "too large" in reason

    def test_refuses_accounting_for_neighbor_curve_claim(self):
        # U-shape: p0=(0,0) p1=(100,0) p2=(100,100) p3=(0,100). PI 1 already
        # has a 60-radius curve, which claims 60 of the shared 100-length
        # tangent between PI 1 and PI 2 (index under test).
        points = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
        radii = [0.0, 60.0, 0.0, 0.0]

        # 50 alone would fit a 100-length tangent, but 50 + 60 (neighbor's
        # claim) > 100, so it must be refused.
        ok, reason = subject.validate_curve_fit_geometry(points, radii, 2, 50.0)
        assert ok is False
        assert "too large" in reason

        # 30 + 60 = 90 <= 100, so it fits.
        ok2, reason2 = subject.validate_curve_fit_geometry(points, radii, 2, 30.0)
        assert ok2 is True
        assert reason2 is None


class TestSlideTangent(NewFile):
    """Tests for Alignment.slide_tangent() — spec 1.3 'T' key (bearing-constant slide)."""

    def test_mid_tangent_slide_keeps_bearing_and_applies_only_perpendicular_offset(self):
        p_prev = (-100.0, 50.0)
        p_a = (0.0, 0.0)
        p_b = (100.0, 0.0)
        p_next = (200.0, 50.0)
        # x-component of delta is parallel to the tangent and must be discarded.
        delta = (5.0, 10.0)

        new_a, new_b = subject.slide_tangent(p_prev, p_a, p_b, p_next, delta)

        assert new_a == pytest.approx((-20.0, 10.0))
        assert new_b == pytest.approx((120.0, 10.0))
        # Bearing (direction vector) of the slid tangent is unchanged.
        direction = (new_b[0] - new_a[0], new_b[1] - new_a[1])
        assert direction == pytest.approx((140.0, 0.0))
        # Perpendicular offset equals the perpendicular component of delta.
        assert new_a[1] == pytest.approx(10.0)
        assert new_b[1] == pytest.approx(10.0)

    def test_end_tangent_case_missing_prev_translates_endpoint_directly(self):
        p_a = (0.0, 0.0)
        p_b = (100.0, 0.0)
        p_next = (200.0, 50.0)
        delta = (0.0, 10.0)

        new_a, new_b = subject.slide_tangent(None, p_a, p_b, p_next, delta)

        assert new_a == pytest.approx((0.0, 10.0))
        assert new_b == pytest.approx((120.0, 10.0))

    def test_end_tangent_case_missing_next_translates_endpoint_directly(self):
        p_prev = (-100.0, 50.0)
        p_a = (0.0, 0.0)
        p_b = (100.0, 0.0)
        delta = (0.0, 10.0)

        new_a, new_b = subject.slide_tangent(p_prev, p_a, p_b, None, delta)

        assert new_a == pytest.approx((-20.0, 10.0))
        assert new_b == pytest.approx((100.0, 10.0))

    def test_degenerate_zero_length_tangent_returns_unchanged(self):
        p = (5.0, 5.0)
        new_a, new_b = subject.slide_tangent((0.0, 0.0), p, p, (10.0, 10.0), (3.0, 4.0))
        assert new_a == p
        assert new_b == p


# ===========================================================================
# PI Edit Mode — In-Mode Editing (spec 1.3) — Blender-dependent
# ===========================================================================
# These build PI edit empties directly from a hand-crafted ``pis`` list
# (bypassing back_calculate_pis_from_alignment, which needs the geometry
# engine to read segment endpoints) so they run without requires_geometry_engine.


def _pi(e, n, radius=0.0, pi_type="TANGENT"):
    return {"e": e, "n": n, "radius": radius, "pi_type": pi_type}


def _create_bare_alignment_with_pi_empties(pis, name="Test Alignment"):
    """Create an IfcAlignment (align_api.create — no geometry engine) and PI
    edit empties from a hand-built ``pis`` list. Returns (alignment, empties)."""
    ifc_file = tool.Ifc.get()
    alignment = align_api.create(ifc_file, name=name)
    subject.create_hierarchy_for_alignment(alignment)
    empties = subject.create_pi_edit_empties(alignment, pis)
    return alignment, empties


class TestInsertPiOnTangent(NewIfc4X3):
    """Tests for Alignment.insert_pi_on_tangent() — spec 1.3 'I' key."""

    def test_inserts_on_nearest_segment_and_renumbers(self):
        pis = [_pi(0.0, 0.0, pi_type="ENDPOINT"), _pi(500.0, 0.0), _pi(500.0, 500.0, pi_type="ENDPOINT")]
        alignment, empties = _create_bare_alignment_with_pi_empties(pis)

        new_empty, reason = subject.insert_pi_on_tangent(alignment.id(), (250.0, 0.0))

        assert reason is None
        assert new_empty is not None
        assert new_empty.get("civil_pi_index") == 1

        all_empties = subject.get_pi_edit_empties(alignment.id())
        assert len(all_empties) == 4
        assert [e.get("civil_pi_index") for e in all_empties] == [0, 1, 2, 3]
        # The old index-1 PI (500, 0) is now renumbered to index 2.
        assert all_empties[2].location.x == pytest.approx(500.0, abs=2.0)

    def test_returns_none_with_reason_when_fewer_than_two_pis(self):
        new_empty, reason = subject.insert_pi_on_tangent(999999, (0.0, 0.0))
        assert new_empty is None
        assert reason is not None and "at least 2" in reason.lower()

    def test_refuses_when_inside_curve_extent(self):
        pis = [
            _pi(0.0, 0.0, pi_type="ENDPOINT"),
            _pi(100.0, 0.0, radius=50.0, pi_type="CURVE"),
            _pi(100.0, 100.0, pi_type="ENDPOINT"),
        ]
        alignment, empties = _create_bare_alignment_with_pi_empties(pis)

        # 80 units along the first tangent (length 100); T=50 blocks past x=50.
        new_empty, reason = subject.insert_pi_on_tangent(alignment.id(), (80.0, 0.0))
        assert new_empty is None
        assert reason is not None


class TestDeletePiEditEmptyToolMethod(NewIfc4X3):
    """Tests for Alignment.delete_pi_edit_empty() — spec 1.3 'X' key primitive."""

    def test_deletes_and_renumbers_remaining_empties(self):
        pis = [
            _pi(0.0, 0.0, pi_type="ENDPOINT"),
            _pi(100.0, 0.0),
            _pi(200.0, 0.0),
            _pi(300.0, 0.0, pi_type="ENDPOINT"),
        ]
        alignment, empties = _create_bare_alignment_with_pi_empties(pis)

        removed = subject.delete_pi_edit_empty(alignment.id(), 1)
        assert removed is True

        remaining = subject.get_pi_edit_empties(alignment.id())
        assert len(remaining) == 3
        assert [e.get("civil_pi_index") for e in remaining] == [0, 1, 2]

    def test_returns_false_for_out_of_range_index(self):
        pis = [_pi(0.0, 0.0, pi_type="ENDPOINT"), _pi(100.0, 0.0, pi_type="ENDPOINT")]
        alignment, empties = _create_bare_alignment_with_pi_empties(pis)
        assert subject.delete_pi_edit_empty(alignment.id(), 5) is False


class TestSetAndClearPiRadius(NewIfc4X3):
    """Tests for Alignment.set_pi_radius() / clear_pi_radius()."""

    def test_set_pi_radius_marks_curve_type(self):
        pis = [_pi(0.0, 0.0, pi_type="ENDPOINT"), _pi(100.0, 0.0), _pi(200.0, 0.0, pi_type="ENDPOINT")]
        alignment, empties = _create_bare_alignment_with_pi_empties(pis)

        subject.set_pi_radius(empties, 1, 50.0)

        assert empties[1].get("civil_pi_radius") == pytest.approx(50.0)
        assert empties[1].get("civil_pi_type") == "CURVE"

    def test_clear_pi_radius_resets_to_tangent(self):
        pis = [
            _pi(0.0, 0.0, pi_type="ENDPOINT"),
            _pi(100.0, 0.0, radius=50.0, pi_type="CURVE"),
            _pi(200.0, 0.0, pi_type="ENDPOINT"),
        ]
        alignment, empties = _create_bare_alignment_with_pi_empties(pis)

        subject.clear_pi_radius(alignment.id(), 1)

        refreshed = subject.get_pi_edit_empties(alignment.id())
        assert refreshed[1].get("civil_pi_radius") == 0.0
        assert refreshed[1].get("civil_pi_type") == "TANGENT"


class TestValidateCurveFitEmpties(NewIfc4X3):
    """Sanity check that the empties-facing wrapper matches validate_curve_fit_geometry."""

    def test_matches_pure_geometry_result(self):
        pis = [_pi(0.0, 0.0, pi_type="ENDPOINT"), _pi(100.0, 0.0), _pi(100.0, 100.0, pi_type="ENDPOINT")]
        alignment, empties = _create_bare_alignment_with_pi_empties(pis)

        ok, reason = subject.validate_curve_fit(empties, 1, 50.0)
        assert ok is True

        ok2, reason2 = subject.validate_curve_fit(empties, 1, 500.0)
        assert ok2 is False


# ===========================================================================
# Alignment / Vertical Deletion (spec 1.4, 2.6)
# ===========================================================================


class TestRemoveAlignmentEntity(NewIfc4X3):
    """Tests for Alignment.remove_alignment_entity()."""

    def test_removes_the_ifc_alignment_entity(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="DeleteMe")
        alignment_id = alignment.id()

        subject.remove_alignment_entity(alignment)

        with pytest.raises(RuntimeError):
            ifc_file.by_id(alignment_id)


# ===========================================================================
# Cant — Pure Math (spec 3.2, 3.4) — no bpy/IFC dependency
# ===========================================================================
# All of these are plain math on floats; NewFile is used only because the
# module under test (bonsai.tool.alignment) imports bpy at module scope, same
# as every other pure-math test class in this file (see
# TestCalculateVerticalCurveLengthFromK etc. above).


class TestCantEquilibrium(NewFile):
    """Tests for Alignment.cant_equilibrium() — E_eq = gauge * v^2 / (g * radius)."""

    def test_metric_hand_computed_value(self):
        # Standard gauge 1.435 m, V=100 km/h, R=1000 m.
        # v = 100/3.6 = 27.777... m/s
        # E = 1.435 * 27.777...^2 / (9.80665 * 1000)
        gauge, speed, radius = 1.435, 100.0, 1000.0
        v_mps = speed / 3.6
        expected = gauge * v_mps**2 / (subject.GRAVITY_MPS2 * radius)
        result = subject.cant_equilibrium(speed, radius, gauge, is_imperial=False)
        assert_close(result, expected, tol=1e-9)
        # Sanity: known order of magnitude for this classic example (~113 mm).
        assert_close(result, 0.11292, tol=5e-4)

    def test_imperial_hand_computed_value(self):
        # gauge/radius are ALWAYS metres internally (Blender LENGTH-property
        # convention) regardless of is_imperial; only speed's unit convention
        # changes (mph here). 1 mph = 0.44704 m/s exactly.
        gauge, speed, radius = 1.4351, 60.0, 500.0
        v_mps = speed * 0.44704
        expected = gauge * v_mps**2 / (subject.GRAVITY_MPS2 * radius)
        result = subject.cant_equilibrium(speed, radius, gauge, is_imperial=True)
        assert_close(result, expected, tol=1e-9)

    def test_metric_and_imperial_speed_conventions_differ_for_same_number(self):
        # The same numeric speed means a different (slower) physical speed
        # under is_imperial=True (mph) vs False (km/h) since 1 mph > 1 km/h,
        # so the imperial call should give a LARGER equilibrium cant for
        # otherwise-identical inputs.
        metric_result = subject.cant_equilibrium(60.0, 500.0, 1.435, is_imperial=False)
        imperial_result = subject.cant_equilibrium(60.0, 500.0, 1.435, is_imperial=True)
        assert imperial_result > metric_result

    def test_zero_for_non_positive_radius(self):
        assert subject.cant_equilibrium(100.0, 0.0, 1.435) == 0.0
        assert subject.cant_equilibrium(100.0, -50.0, 1.435) == 0.0

    def test_zero_for_non_positive_speed(self):
        assert subject.cant_equilibrium(0.0, 1000.0, 1.435) == 0.0

    def test_zero_for_non_positive_gauge(self):
        assert subject.cant_equilibrium(100.0, 1000.0, 0.0) == 0.0

    def test_larger_radius_gives_smaller_equilibrium_cant(self):
        tight = subject.cant_equilibrium(100.0, 500.0, 1.435)
        wide = subject.cant_equilibrium(100.0, 2000.0, 1.435)
        assert tight > wide


class TestCantGradient(NewFile):
    """Tests for Alignment.cant_gradient()."""

    def test_metric_returns_mm_per_m(self):
        # 0.1 m of cant change over 100 m -> 1 mm/m.
        result = subject.cant_gradient(0.1, 100.0, is_imperial=False)
        assert_close(result, 1.0)

    def test_imperial_returns_in_per_ft(self):
        # Same underlying ratio (0.1/100 = 0.001), scaled by 12 (in/ft) instead
        # of 1000 (mm/m) -- NOT simply "12x the metric number".
        result = subject.cant_gradient(0.1, 100.0, is_imperial=True)
        assert_close(result, 0.012)

    def test_zero_for_non_positive_length(self):
        assert subject.cant_gradient(0.1, 0.0) == 0.0
        assert subject.cant_gradient(0.1, -10.0) == 0.0

    def test_negative_delta_gives_negative_gradient(self):
        result = subject.cant_gradient(-0.1, 100.0)
        assert result < 0.0


class TestTwist(NewFile):
    """Tests for Alignment.twist()."""

    def test_per_length_matches_cant_gradient(self):
        per_length, _ = subject.twist(0.1, 100.0, speed=None, is_imperial=False)
        assert_close(per_length, subject.cant_gradient(0.1, 100.0, is_imperial=False))

    def test_per_time_is_zero_without_speed(self):
        _, per_time = subject.twist(0.1, 100.0, speed=None)
        assert per_time == 0.0
        _, per_time_zero_speed = subject.twist(0.1, 100.0, speed=0.0)
        assert per_time_zero_speed == 0.0

    def test_per_time_hand_computed_metric(self):
        # 100 mm of cant change over 100 m, traversed at 36 km/h = 10 m/s.
        # time = 100 / 10 = 10 s; twist = 100 mm / 10 s = 10 mm/s.
        _, per_time = subject.twist(0.1, 100.0, speed=36.0, is_imperial=False)
        assert_close(per_time, 10.0, tol=1e-6)

    def test_per_time_scales_with_speed(self):
        _, slow = subject.twist(0.1, 100.0, speed=36.0)
        _, fast = subject.twist(0.1, 100.0, speed=72.0)
        assert fast > slow


class TestCantRampFunctions(NewFile):
    """Tests for the normalized ramp functions f(xi) dispatched by
    ``_ramp_for_transition_type`` — every ramp must satisfy f(0)=0, f(1)=1,
    and be monotonically non-decreasing (spec 3.4)."""

    RAMPS = {
        "LINEARTRANSITION": subject._ramp_linear,
        "BLOSSCURVE": subject._ramp_bloss,
        "COSINECURVE": subject._ramp_cosine,
        "SINECURVE": subject._ramp_sine,
        "HELMERTCURVE": subject._ramp_helmert,
    }

    def test_endpoints_are_zero_and_one_for_every_ramp(self):
        for name, ramp in self.RAMPS.items():
            assert_close(ramp(0.0), 0.0, tol=1e-9), name
            assert_close(ramp(1.0), 1.0, tol=1e-9), name

    def test_symmetric_ramps_hit_half_at_midpoint(self):
        # Linear, Bloss, Cosine, Sine, and Helmert are all point-symmetric
        # about (0.5, 0.5) by construction.
        for name, ramp in self.RAMPS.items():
            assert_close(ramp(0.5), 0.5, tol=1e-9), name

    def test_ramps_are_monotonically_non_decreasing(self):
        samples = [i / 100.0 for i in range(101)]
        for name, ramp in self.RAMPS.items():
            values = [ramp(xi) for xi in samples]
            for a, b in zip(values, values[1:]):
                assert b >= a - 1e-9, f"{name} is not monotonic: {a} -> {b}"

    def test_bloss_and_cosine_have_zero_end_slopes(self):
        # Finite-difference slope near each end should be ~0 for these two
        # (unlike linear, which has a constant nonzero slope everywhere).
        eps = 1e-4
        for ramp in (subject._ramp_bloss, subject._ramp_cosine, subject._ramp_sine, subject._ramp_helmert):
            start_slope = (ramp(eps) - ramp(0.0)) / eps
            end_slope = (ramp(1.0) - ramp(1.0 - eps)) / eps
            assert abs(start_slope) < 0.01
            assert abs(end_slope) < 0.01

    def test_linear_has_constant_nonzero_slope(self):
        assert_close(subject._ramp_linear(0.25), 0.25)
        assert_close(subject._ramp_linear(0.75), 0.75)

    def test_dispatch_by_transition_type_name(self):
        assert subject._ramp_for_transition_type("LINEARTRANSITION", 0.5) == subject._ramp_linear(0.5)
        assert subject._ramp_for_transition_type("HELMERTCURVE", 0.5) == subject._ramp_helmert(0.5)
        assert subject._ramp_for_transition_type("BLOSSCURVE", 0.5) == subject._ramp_bloss(0.5)
        assert subject._ramp_for_transition_type("COSINECURVE", 0.5) == subject._ramp_cosine(0.5)
        assert subject._ramp_for_transition_type("SINECURVE", 0.5) == subject._ramp_sine(0.5)

    def test_viennese_bend_approximates_with_bloss(self):
        for xi in (0.0, 0.25, 0.5, 0.75, 1.0):
            assert subject._ramp_for_transition_type("VIENNESEBEND", xi) == subject._ramp_bloss(xi)

    def test_constant_cant_ramp_is_zero(self):
        assert subject._ramp_for_transition_type("CONSTANTCANT", 0.5) == 0.0

    def test_dispatch_clamps_xi_outside_zero_one(self):
        assert subject._ramp_for_transition_type("LINEARTRANSITION", -0.5) == 0.0
        assert subject._ramp_for_transition_type("LINEARTRANSITION", 1.5) == 1.0


class TestSampleCantProfile(NewFile):
    """Tests for Alignment.sample_cant_profile() — spec 3.4, display-only."""

    def _linear_points(self):
        return [
            {"station": 0.0, "cant_left": 0.0, "cant_right": 0.0, "transition_type": "LINEARTRANSITION"},
            {"station": 100.0, "cant_left": 0.0, "cant_right": 0.10, "transition_type": "LINEARTRANSITION"},
        ]

    def test_linear_ramp_midpoint_is_half(self):
        samples = subject.sample_cant_profile(self._linear_points(), [50.0])
        station, left, right = samples[0]
        assert_close(station, 50.0)
        assert_close(left, 0.0)
        assert_close(right, 0.05)

    def test_endpoints_match_table_values_exactly(self):
        samples = subject.sample_cant_profile(self._linear_points(), [0.0, 100.0])
        assert_close(samples[0][2], 0.0)
        assert_close(samples[1][2], 0.10)

    def test_clamps_stations_outside_range(self):
        samples = subject.sample_cant_profile(self._linear_points(), [-50.0, 500.0])
        assert_close(samples[0][2], 0.0)  # clamped to first point
        assert_close(samples[1][2], 0.10)  # clamped to last point

    def test_fewer_than_two_points_returns_zero_cant(self):
        samples = subject.sample_cant_profile([], [0.0, 50.0])
        assert samples == [(0.0, 0.0, 0.0), (50.0, 0.0, 0.0)]

    def test_bloss_midpoint_matches_ramp_half(self):
        points = [
            {"station": 0.0, "cant_left": 0.0, "cant_right": 0.0, "transition_type": "BLOSSCURVE"},
            {"station": 100.0, "cant_left": 0.0, "cant_right": 0.16, "transition_type": "BLOSSCURVE"},
        ]
        samples = subject.sample_cant_profile(points, [50.0])
        assert_close(samples[0][2], 0.08, tol=1e-6)

    def test_constant_cant_holds_start_value_flat_ignoring_next_point(self):
        # Mirrors _map_constant_cant, which never reads End* -- the sampled
        # profile should stay flat at the start value across the whole
        # segment even when the next point differs.
        points = [
            {"station": 0.0, "cant_left": 0.0, "cant_right": 0.05, "transition_type": "CONSTANTCANT"},
            {"station": 100.0, "cant_left": 0.0, "cant_right": 0.15, "transition_type": "CONSTANTCANT"},
        ]
        samples = subject.sample_cant_profile(points, [0.0, 25.0, 50.0, 75.0])
        for station, left, right in samples:
            assert_close(right, 0.05, tol=1e-9)

    def test_multi_segment_walks_correct_segment(self):
        points = [
            {"station": 0.0, "cant_left": 0.0, "cant_right": 0.0, "transition_type": "LINEARTRANSITION"},
            {"station": 100.0, "cant_left": 0.0, "cant_right": 0.10, "transition_type": "LINEARTRANSITION"},
            {"station": 200.0, "cant_left": 0.0, "cant_right": 0.0, "transition_type": "LINEARTRANSITION"},
        ]
        samples = subject.sample_cant_profile(points, [150.0])
        # Halfway through the second (descending) segment: 0.10 -> 0.0, so 0.05.
        assert_close(samples[0][2], 0.05, tol=1e-9)


class TestEN13803DefaultLimits(NewFile):
    """Sanity checks for the transcribed EN 13803-1:2017 defaults."""

    def test_all_five_limits_present_and_positive(self):
        limits = subject.EN13803_DEFAULT_LIMITS
        for key in ("max_applied_cant", "max_deficiency", "max_excess", "max_cant_gradient", "max_twist"):
            assert key in limits
            assert limits[key] > 0.0

    def test_length_limits_are_metres_matching_published_mm_figures(self):
        limits = subject.EN13803_DEFAULT_LIMITS
        assert_close(limits["max_applied_cant"], 0.160)
        assert_close(limits["max_deficiency"], 0.153)
        assert_close(limits["max_excess"], 0.110)

    def test_rate_limits_are_dimensionless_ratios_matching_published_mm_per_m(self):
        limits = subject.EN13803_DEFAULT_LIMITS
        assert_close(limits["max_cant_gradient"], 0.00225)
        assert_close(limits["max_twist"], 0.003)


# ===========================================================================
# Cant — Semantic IFC Tests (no geometry engine)
# ===========================================================================
# These build fixtures either via align_api.create(include_vertical=True,
# include_cant=True) (bare layouts -- only the mandatory zero-length
# terminators, confirmed to NOT touch the geometry engine) or by nesting
# IfcAlignmentSegment entities directly (bypassing
# create_layout_segment/_add_segment_to_layout, whose _get_segment_endpoint
# call DOES require ifcopenshell_wrapper.map_shape -- see
# TestWriteCantSegments below for the one path that genuinely needs it).


def _bare_alignment_with_h_v_cant(name="Cant Fixture", rail_head_distance=1.5):
    """align_api.create() with horizontal + vertical + cant, all bare
    (zero-length-terminator only, no real segments) -- empirically confirmed
    to work without the geometry engine (unlike layout_*_by_pi_method)."""
    ifc_file = tool.Ifc.get()
    return align_api.create(
        ifc_file, name=name, include_vertical=True, include_cant=True, rail_head_distance=rail_head_distance
    )


def _nest_semantic_horizontal_segments(alignment, design_params_list):
    """Directly nest real IfcAlignmentSegments onto the horizontal layout via
    their DesignParameters, bypassing create_layout_segment (geometry-engine
    dependent). Semantic-only fixture, mirrored by
    _nest_semantic_cant_segments below for the cant layout."""
    import ifcopenshell.guid

    ifc_file = tool.Ifc.get()
    h_layout = align_api.get_horizontal_layout(alignment)
    rel = h_layout.IsNestedBy[0]
    terminator = rel.RelatedObjects[-1]
    segments = []
    for dp in design_params_list:
        segment = ifc_file.createIfcAlignmentSegment(GlobalId=ifcopenshell.guid.new(), DesignParameters=dp)
        segments.append(segment)
    rel.RelatedObjects = tuple(segments) + (terminator,)
    return segments


def _line_dp(ifc_file, start_xy, start_direction, length):
    return ifc_file.createIfcAlignmentHorizontalSegment(
        StartPoint=ifc_file.createIfcCartesianPoint(start_xy),
        StartDirection=start_direction,
        StartRadiusOfCurvature=None,
        EndRadiusOfCurvature=None,
        SegmentLength=length,
        PredefinedType="LINE",
    )


def _arc_dp(ifc_file, start_xy, start_direction, radius, length):
    return ifc_file.createIfcAlignmentHorizontalSegment(
        StartPoint=ifc_file.createIfcCartesianPoint(start_xy),
        StartDirection=start_direction,
        StartRadiusOfCurvature=radius,
        EndRadiusOfCurvature=radius,
        SegmentLength=length,
        PredefinedType="CIRCULARARC",
    )


def _nest_semantic_cant_segments(alignment, design_params_list):
    """Directly nest real IfcAlignmentSegments onto the cant layout via their
    DesignParameters, bypassing create_layout_segment (geometry-engine
    dependent — see TestWriteCantSegments for why write_cant_segments itself
    cannot avoid it)."""
    import ifcopenshell.guid

    ifc_file = tool.Ifc.get()
    cant_layout = align_api.get_cant_layout(alignment)
    rel = cant_layout.IsNestedBy[0]
    terminator = rel.RelatedObjects[-1]
    segments = []
    for dp in design_params_list:
        segment = ifc_file.createIfcAlignmentSegment(GlobalId=ifcopenshell.guid.new(), DesignParameters=dp)
        segments.append(segment)
    rel.RelatedObjects = tuple(segments) + (terminator,)
    return segments


def _cant_dp(ifc_file, start, length, start_left, end_left, start_right, end_right, transition_type):
    return ifc_file.createIfcAlignmentCantSegment(
        StartDistAlong=start,
        HorizontalLength=length,
        StartCantLeft=start_left,
        EndCantLeft=end_left,
        StartCantRight=start_right,
        EndCantRight=end_right,
        PredefinedType=transition_type,
    )


class TestGetAddRemoveCantLayout(NewIfc4X3):
    """Tests for get_cant_layout / add_cant_layout / remove_cant_layout —
    all confirmed to work without the geometry engine on bare layouts."""

    def test_get_cant_layout_returns_none_when_absent(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="NoCant", include_vertical=True)
        assert subject.get_cant_layout(alignment) is None

    def test_add_cant_layout_creates_and_get_finds_it(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="AddCant", include_vertical=True)
        cant_layout = subject.add_cant_layout(alignment, rail_head_distance=1.75)
        assert cant_layout is not None
        assert cant_layout.is_a("IfcAlignmentCant")
        assert_close(cant_layout.RailHeadDistance, 1.75)
        assert subject.get_cant_layout(alignment) == cant_layout

    def test_remove_cant_layout_reverts_representation(self):
        import ifcopenshell.util.representation

        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="RemoveCant", include_vertical=True)
        subject.add_cant_layout(alignment, rail_head_distance=1.5)
        assert subject.get_cant_layout(alignment) is not None

        subject.remove_cant_layout(alignment)

        assert subject.get_cant_layout(alignment) is None
        assert len(ifc_file.by_type("IfcAlignmentCant")) == 0
        assert len(ifc_file.by_type("IfcSegmentedReferenceCurve")) == 0

        representations = list(ifcopenshell.util.representation.get_representations_iter(alignment))
        identifiers = [(r.RepresentationIdentifier, r.RepresentationType) for r in representations]
        assert ("Axis", "Curve3D") in identifiers
        # The gradient curve (vertical's representation) must survive.
        axis_curve3d = next(
            r for r in representations if (r.RepresentationIdentifier, r.RepresentationType) == ("Axis", "Curve3D")
        )
        assert axis_curve3d.Items[0].is_a("IfcGradientCurve")

    def test_remove_cant_layout_noop_when_absent(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="NothingToRemove", include_vertical=True)
        subject.remove_cant_layout(alignment)  # should not raise
        assert subject.get_cant_layout(alignment) is None


class TestGetHorizontalExtentSemantic(NewIfc4X3):
    """Tests for Alignment.get_horizontal_extent_semantic()."""

    def test_returns_zero_for_bare_layout(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="Bare")
        assert subject.get_horizontal_extent_semantic(alignment) == 0.0

    def test_sums_semantic_segment_lengths(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="Summed")
        _nest_semantic_horizontal_segments(
            alignment,
            [
                _line_dp(ifc_file, (0.0, 0.0), 0.0, 100.0),
                _arc_dp(ifc_file, (100.0, 0.0), 0.0, 200.0, 157.08),
            ],
        )
        assert_close(subject.get_horizontal_extent_semantic(alignment), 257.08, tol=1e-6)


class TestRadiusAtStation(NewIfc4X3):
    """Tests for Alignment.radius_at_station() on a semantically-built
    line-arc-line layout (bypasses create_layout_segment; see module note)."""

    def _line_arc_line_alignment(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="LineArcLine")
        _nest_semantic_horizontal_segments(
            alignment,
            [
                _line_dp(ifc_file, (0.0, 0.0), 0.0, 100.0),
                _arc_dp(ifc_file, (100.0, 0.0), 0.0, 200.0, 157.08),
                _line_dp(ifc_file, (150.0, 150.0), 1.5708, 100.0),
            ],
        )
        return alignment

    def test_zero_within_first_line_segment(self):
        alignment = self._line_arc_line_alignment()
        assert subject.radius_at_station(alignment, 50.0) == 0.0

    def test_constant_radius_within_arc_segment(self):
        alignment = self._line_arc_line_alignment()
        assert_close(subject.radius_at_station(alignment, 150.0), 200.0)
        assert_close(subject.radius_at_station(alignment, 105.0), 200.0)

    def test_zero_within_second_line_segment(self):
        alignment = self._line_arc_line_alignment()
        assert subject.radius_at_station(alignment, 300.0) == 0.0

    def test_zero_outside_alignment_domain(self):
        alignment = self._line_arc_line_alignment()
        assert subject.radius_at_station(alignment, -10.0) == 0.0
        assert subject.radius_at_station(alignment, 9999.0) == 0.0

    def test_zero_when_no_horizontal_layout(self):
        ifc_file = tool.Ifc.get()
        alignment = ifc_file.createIfcAlignment(GlobalId=ifcopenshell.guid.new())
        assert subject.radius_at_station(alignment, 0.0) == 0.0

    def test_interpolates_curvature_linearly_across_a_spiral(self):
        # A CLOTHOID transitioning from a straight (radius None/0) into a
        # 100 m-radius arc over 50 m: curvature should be exactly half way
        # between 0 and 1/100 at the segment's midpoint.
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="Spiral")
        spiral_dp = ifc_file.createIfcAlignmentHorizontalSegment(
            StartPoint=ifc_file.createIfcCartesianPoint((0.0, 0.0)),
            StartDirection=0.0,
            StartRadiusOfCurvature=None,
            EndRadiusOfCurvature=100.0,
            SegmentLength=50.0,
            PredefinedType="CLOTHOID",
        )
        _nest_semantic_horizontal_segments(alignment, [spiral_dp])
        radius_at_mid = subject.radius_at_station(alignment, 25.0)
        expected_curvature = 0.5 * (1.0 / 100.0)
        assert_close(1.0 / radius_at_mid, expected_curvature, tol=1e-6)


class TestCantRotationReferencePset(NewIfc4X3):
    """Tests for set/get_cant_rotation_reference() — spec 3.3."""

    def test_get_returns_none_when_never_set(self):
        alignment = _bare_alignment_with_h_v_cant()
        cant_layout = subject.get_cant_layout(alignment)
        assert subject.get_cant_rotation_reference(cant_layout) is None

    def test_round_trips_through_pset(self):
        alignment = _bare_alignment_with_h_v_cant()
        cant_layout = subject.get_cant_layout(alignment)
        subject.set_cant_rotation_reference(cant_layout, "HIGH_RAIL")
        assert subject.get_cant_rotation_reference(cant_layout) == "HIGH_RAIL"

    def test_overwrites_previous_value(self):
        alignment = _bare_alignment_with_h_v_cant()
        cant_layout = subject.get_cant_layout(alignment)
        subject.set_cant_rotation_reference(cant_layout, "LOW_RAIL")
        subject.set_cant_rotation_reference(cant_layout, "CENTERLINE")
        assert subject.get_cant_rotation_reference(cant_layout) == "CENTERLINE"


class TestBackCalculateCantPointsFromLayout(NewIfc4X3):
    """Tests for Alignment.back_calculate_cant_points_from_layout() — pure
    semantic read of IfcAlignmentCantSegment design parameters."""

    def test_empty_when_no_cant_layout(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="NoCant", include_vertical=True)
        assert subject.back_calculate_cant_points_from_layout(alignment) == []

    def test_empty_when_cant_layout_has_no_real_segments(self):
        alignment = _bare_alignment_with_h_v_cant()
        assert subject.back_calculate_cant_points_from_layout(alignment) == []

    def test_round_trips_two_point_table(self):
        ifc_file = tool.Ifc.get()
        alignment = _bare_alignment_with_h_v_cant()
        _nest_semantic_cant_segments(
            alignment,
            [_cant_dp(ifc_file, 0.0, 100.0, 0.0, 0.0, 0.0, 0.15, "LINEARTRANSITION")],
        )
        points = subject.back_calculate_cant_points_from_layout(alignment)
        assert len(points) == 2
        assert_close(points[0]["station"], 0.0)
        assert_close(points[0]["cant_right"], 0.0)
        assert points[0]["transition_type"] == "LINEARTRANSITION"
        assert_close(points[1]["station"], 100.0)
        assert_close(points[1]["cant_right"], 0.15)

    def test_round_trips_three_point_table(self):
        ifc_file = tool.Ifc.get()
        alignment = _bare_alignment_with_h_v_cant()
        _nest_semantic_cant_segments(
            alignment,
            [
                _cant_dp(ifc_file, 0.0, 100.0, 0.0, 0.0, 0.0, 0.15, "LINEARTRANSITION"),
                _cant_dp(ifc_file, 100.0, 50.0, 0.0, 0.0, 0.15, 0.15, "CONSTANTCANT"),
            ],
        )
        points = subject.back_calculate_cant_points_from_layout(alignment)
        assert len(points) == 3
        assert_close(points[2]["station"], 150.0)
        assert_close(points[2]["cant_right"], 0.15)


def _cant_point(station, cant_left, cant_right, transition_type="LINEARTRANSITION", design_speed=0.0):
    return {
        "station": station,
        "cant_left": cant_left,
        "cant_right": cant_right,
        "transition_type": transition_type,
        "design_speed": design_speed,
    }


class TestComputeCantChecks(NewIfc4X3):
    """Tests for Alignment.compute_cant_checks() — spec 3.2."""

    def _alignment_with_arc(self, radius=1000.0):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="ChecksFixture")
        _nest_semantic_horizontal_segments(
            alignment,
            [_arc_dp(ifc_file, (0.0, 0.0), 0.0, radius, 500.0)],
        )
        return alignment

    def test_out_of_range_index_returns_zero_result_no_violations(self):
        alignment = self._alignment_with_arc()
        points = [_cant_point(0.0, 0.0, 0.10)]
        result = subject.compute_cant_checks(points, 0, alignment, 1.435, subject.EN13803_DEFAULT_LIMITS, 100.0)
        assert result["violations"] == []
        assert result["equilibrium"] == 0.0

    def test_applied_cant_is_right_minus_left(self):
        alignment = self._alignment_with_arc()
        points = [_cant_point(0.0, 0.02, 0.12), _cant_point(100.0, 0.02, 0.12)]
        result = subject.compute_cant_checks(points, 0, alignment, 1.435, subject.EN13803_DEFAULT_LIMITS, 0.0)
        assert_close(result["applied"], 0.10)

    def test_point_level_design_speed_overrides_alignment_default(self):
        alignment = self._alignment_with_arc(radius=1000.0)
        points = [
            _cant_point(0.0, 0.0, 0.0, design_speed=100.0),
            _cant_point(100.0, 0.0, 0.0),
        ]
        result = subject.compute_cant_checks(points, 0, alignment, 1.435, subject.EN13803_DEFAULT_LIMITS, 30.0)
        expected_eq = subject.cant_equilibrium(100.0, 1000.0, 1.435, False)
        assert_close(result["equilibrium"], expected_eq, tol=1e-6)

    def test_zero_applied_cant_is_all_deficiency(self):
        alignment = self._alignment_with_arc(radius=1000.0)
        points = [_cant_point(0.0, 0.0, 0.0), _cant_point(100.0, 0.0, 0.0)]
        result = subject.compute_cant_checks(points, 0, alignment, 1.435, subject.EN13803_DEFAULT_LIMITS, 100.0)
        assert result["deficiency"] > 0.0
        assert result["excess"] == 0.0
        assert_close(result["deficiency"], result["equilibrium"], tol=1e-9)

    def test_overcant_produces_excess_not_deficiency(self):
        # A very tight-radius curve at low speed with a large applied cant.
        alignment = self._alignment_with_arc(radius=1000.0)
        points = [_cant_point(0.0, 0.0, 0.15), _cant_point(100.0, 0.0, 0.15)]
        result = subject.compute_cant_checks(points, 0, alignment, 1.435, subject.EN13803_DEFAULT_LIMITS, 20.0)
        assert result["excess"] > 0.0
        assert result["deficiency"] == 0.0

    def test_gradient_and_twist_reflect_change_between_points(self):
        alignment = self._alignment_with_arc()
        points = [_cant_point(0.0, 0.0, 0.0), _cant_point(100.0, 0.0, 0.10)]
        result = subject.compute_cant_checks(points, 0, alignment, 1.435, subject.EN13803_DEFAULT_LIMITS, 0.0)
        assert_close(result["gradient"], 1.0, tol=1e-6)  # 0.10 m / 100 m = 1 mm/m

    def test_max_applied_cant_violation_is_flagged(self):
        alignment = self._alignment_with_arc()
        points = [_cant_point(0.0, 0.0, 0.20), _cant_point(100.0, 0.0, 0.20)]
        result = subject.compute_cant_checks(points, 0, alignment, 1.435, subject.EN13803_DEFAULT_LIMITS, 0.0)
        assert "max_applied_cant" in result["violations"]

    def test_max_deficiency_violation_is_flagged_at_high_speed(self):
        alignment = self._alignment_with_arc(radius=300.0)
        points = [_cant_point(0.0, 0.0, 0.0), _cant_point(100.0, 0.0, 0.0)]
        result = subject.compute_cant_checks(points, 0, alignment, 1.435, subject.EN13803_DEFAULT_LIMITS, 160.0)
        assert "max_deficiency" in result["violations"]

    def test_max_gradient_violation_is_flagged_for_a_steep_transition(self):
        alignment = self._alignment_with_arc()
        points = [_cant_point(0.0, 0.0, 0.0), _cant_point(10.0, 0.0, 0.15)]
        result = subject.compute_cant_checks(points, 0, alignment, 1.435, subject.EN13803_DEFAULT_LIMITS, 0.0)
        assert "max_cant_gradient" in result["violations"]
        assert "max_twist" in result["violations"]

    def test_compliant_segment_has_no_violations(self):
        alignment = self._alignment_with_arc(radius=2000.0)
        points = [_cant_point(0.0, 0.0, 0.05), _cant_point(500.0, 0.0, 0.05)]
        result = subject.compute_cant_checks(points, 0, alignment, 1.435, subject.EN13803_DEFAULT_LIMITS, 0.0)
        assert result["violations"] == []

    def test_missing_limit_key_is_never_flagged(self):
        alignment = self._alignment_with_arc()
        points = [_cant_point(0.0, 0.0, 0.30), _cant_point(100.0, 0.0, 0.30)]
        result = subject.compute_cant_checks(points, 0, alignment, 1.435, {}, 0.0)
        assert result["violations"] == []


# ===========================================================================
# Cant — Geometry-Dependent (write path)
# ===========================================================================
# write_cant_segments() calls ifcopenshell.api.alignment.create_layout_segment,
# which (via _add_segment_to_layout -> _get_segment_endpoint) unconditionally
# calls ifcopenshell_wrapper.map_shape to reposition the mandatory zero-length
# terminator after the new segment -- EVEN for a semantic-only write with no
# geometric representation on the layout. This was confirmed empirically:
# every write_cant_segments call fails locally with "No geometry mapping
# registered for ifc4x3_add2" (IfcOpenShell#9301) until the win64 packaging
# gap is closed. Reading cant points back out (back_calculate_cant_points_
# from_layout, tested above) is pure semantic and does NOT need the engine --
# only the WRITE path does.


@requires_geometry_engine
class TestWriteCantSegments(NewIfc4X3):
    """Tests for Alignment.write_cant_segments() — spec 3.2 semantic round-trip."""

    def test_raises_when_no_cant_layout(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="NoCant", include_vertical=True)
        points = [
            {"station": 0.0, "cant_left": 0.0, "cant_right": 0.0, "transition_type": "LINEARTRANSITION"},
            {"station": 100.0, "cant_left": 0.0, "cant_right": 0.10, "transition_type": "LINEARTRANSITION"},
        ]
        with pytest.raises(ValueError, match="no cant layout"):
            subject.write_cant_segments(alignment, points)

    def test_writes_two_point_table_as_one_segment(self):
        alignment = _bare_alignment_with_h_v_cant()
        points = [
            {"station": 0.0, "cant_left": 0.0, "cant_right": 0.0, "transition_type": "LINEARTRANSITION"},
            {"station": 100.0, "cant_left": 0.0, "cant_right": 0.10, "transition_type": "LINEARTRANSITION"},
        ]
        subject.write_cant_segments(alignment, points)

        cant_layout = subject.get_cant_layout(alignment)
        segments = align_api.get_layout_segments(cant_layout)
        real_segments = [s for s in segments if not subject.is_zero_length_segment(s)]
        assert len(real_segments) == 1
        dp = real_segments[0].DesignParameters
        assert_close(dp.StartDistAlong, 0.0)
        assert_close(dp.HorizontalLength, 100.0)
        assert_close(dp.StartCantRight, 0.0)
        assert_close(dp.EndCantRight, 0.10)
        assert dp.PredefinedType == "LINEARTRANSITION"

    def test_writes_three_point_table_as_two_segments_with_correct_types(self):
        alignment = _bare_alignment_with_h_v_cant()
        points = [
            {"station": 0.0, "cant_left": 0.0, "cant_right": 0.0, "transition_type": "LINEARTRANSITION"},
            {"station": 100.0, "cant_left": 0.0, "cant_right": 0.15, "transition_type": "CONSTANTCANT"},
            {"station": 200.0, "cant_left": 0.0, "cant_right": 0.15, "transition_type": "LINEARTRANSITION"},
        ]
        subject.write_cant_segments(alignment, points)

        cant_layout = subject.get_cant_layout(alignment)
        segments = align_api.get_layout_segments(cant_layout)
        real_segments = [s for s in segments if not subject.is_zero_length_segment(s)]
        assert len(real_segments) == 2
        assert real_segments[0].DesignParameters.PredefinedType == "LINEARTRANSITION"
        assert real_segments[1].DesignParameters.PredefinedType == "CONSTANTCANT"
        assert_close(real_segments[1].DesignParameters.StartDistAlong, 100.0)
        assert_close(real_segments[1].DesignParameters.HorizontalLength, 100.0)

    def test_clears_previous_segments_before_rewriting(self):
        alignment = _bare_alignment_with_h_v_cant()
        first_points = [
            {"station": 0.0, "cant_left": 0.0, "cant_right": 0.0, "transition_type": "LINEARTRANSITION"},
            {"station": 100.0, "cant_left": 0.0, "cant_right": 0.10, "transition_type": "LINEARTRANSITION"},
            {"station": 200.0, "cant_left": 0.0, "cant_right": 0.0, "transition_type": "LINEARTRANSITION"},
        ]
        subject.write_cant_segments(alignment, first_points)

        second_points = [
            {"station": 0.0, "cant_left": 0.0, "cant_right": 0.0, "transition_type": "LINEARTRANSITION"},
            {"station": 50.0, "cant_left": 0.0, "cant_right": 0.05, "transition_type": "LINEARTRANSITION"},
        ]
        subject.write_cant_segments(alignment, second_points)

        cant_layout = subject.get_cant_layout(alignment)
        segments = align_api.get_layout_segments(cant_layout)
        real_segments = [s for s in segments if not subject.is_zero_length_segment(s)]
        assert len(real_segments) == 1
        assert_close(real_segments[0].DesignParameters.HorizontalLength, 50.0)


class TestRemoveVerticalLayout(NewIfc4X3):
    """Tests for Alignment.remove_vertical_layout() — spec 2.6."""

    def test_noop_when_no_vertical_layout(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="NoVertical")

        subject.remove_vertical_layout(alignment)  # should not raise

        assert align_api.get_vertical_layout(alignment) is None

    def test_removes_vertical_layout_and_reverts_representation(self):
        import ifcopenshell.util.representation

        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="WithVertical")
        subject.add_vertical_layout(alignment)
        assert align_api.get_vertical_layout(alignment) is not None

        subject.remove_vertical_layout(alignment)

        assert align_api.get_vertical_layout(alignment) is None
        assert len(ifc_file.by_type("IfcAlignmentVertical")) == 0

        representations = list(ifcopenshell.util.representation.get_representations_iter(alignment))
        identifiers = [(r.RepresentationIdentifier, r.RepresentationType) for r in representations]
        assert ("Axis", "Curve2D") in identifiers
        assert ("Axis", "Curve3D") not in identifiers
        assert ("FootPrint", "Curve2D") not in identifiers


# ---------------------------------------------------------------------------
# Stationing Referents (spec Section 4)
# ---------------------------------------------------------------------------


class TestGetReferents(NewIfc4X3):
    """Tests for Alignment.get_referents() — spec 4.2."""

    def test_returns_the_default_start_station_referent(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="Test", start_station=100.0, include_vertical=False)

        referents = subject.get_referents(alignment)

        assert len(referents) == 1
        entry = referents[0]
        assert entry["predefined_type"] == "STATION"
        assert_close(entry["station"], 100.0)
        assert entry["is_equation"] is False
        assert entry["incoming_station"] is None

    def test_includes_a_manually_nested_position_referent_and_sorts_by_station(self):
        import ifcopenshell.api.pset
        import ifcopenshell.guid

        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="Test", start_station=0.0, include_vertical=False)

        # A manually-nested POSITION referent (e.g. representing a bridge
        # pier or other feature located along the alignment) at a LATER
        # station than the default start referent -- proves get_referents
        # walks every IfcRelNests under the alignment, not just the
        # stationing one, and sorts the combined result by station.
        position_referent = ifc_file.createIfcReferent(
            GlobalId=ifcopenshell.guid.new(), Name="Pier 1", PredefinedType="POSITION"
        )
        pset = ifcopenshell.api.pset.add_pset(ifc_file, product=position_referent, name="Pset_Stationing")
        ifcopenshell.api.pset.edit_pset(ifc_file, pset=pset, properties={"Station": 250.0})
        ifc_file.createIfcRelNests(
            GlobalId=ifcopenshell.guid.new(), RelatingObject=alignment, RelatedObjects=(position_referent,)
        )

        referents = subject.get_referents(alignment)

        assert len(referents) == 2
        assert [r["predefined_type"] for r in referents] == ["STATION", "POSITION"]
        assert_close(referents[0]["station"], 0.0)
        assert_close(referents[1]["station"], 250.0)
        assert referents[1]["name"] == "Pier 1"
        assert referents[1]["id"] == position_referent.id()

    def test_returns_empty_list_for_alignment_with_no_referents(self):
        import ifcopenshell.api.root

        ifc_file = tool.Ifc.get()
        alignment = ifcopenshell.api.root.create_entity(ifc_file, ifc_class="IfcAlignment", name="Bare")
        assert subject.get_referents(alignment) == []


class TestAddEventReferent(NewIfc4X3):
    """Tests for Alignment.add_event_referent() — spec 4.4.

    Unlike TestAddStationEquationReferent below, this is NOT gated behind
    @requires_geometry_engine: add_event_referent deliberately skips
    align_api.update_fallback_position (see its comment in
    tool.Alignment.add_event_referent) so it stays fully semantic, even
    though it otherwise mirrors add_stationing_referent's placement
    construction.
    """

    def test_creates_superelevation_event_referent(self):
        import ifcopenshell.util.element

        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="Test", include_vertical=False)

        referent = subject.add_event_referent(alignment, "SUPERELEVATIONEVENT", 250.0)

        assert referent.is_a("IfcReferent")
        assert referent.PredefinedType == "SUPERELEVATIONEVENT"
        pset = ifcopenshell.util.element.get_pset(referent, "Pset_Stationing", should_inherit=False)
        assert_close(pset["Station"], 250.0)

    def test_records_optional_value_in_saikei_event_pset(self):
        import ifcopenshell.util.element

        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="Test", include_vertical=False)

        referent = subject.add_event_referent(alignment, "WIDTHEVENT", 300.0, name="Widen", value=3.6)

        assert referent.Name == "Widen"
        pset = ifcopenshell.util.element.get_pset(referent, "Pset_SaikeiEvent", should_inherit=False)
        assert_close(pset["Value"], 3.6)

    def test_omits_saikei_event_pset_when_no_value_given(self):
        import ifcopenshell.util.element

        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="Test", include_vertical=False)

        referent = subject.add_event_referent(alignment, "SUPERELEVATIONEVENT", 250.0)

        pset = ifcopenshell.util.element.get_pset(referent, "Pset_SaikeiEvent", should_inherit=False)
        assert pset is None

    def test_nests_events_separately_from_the_stationing_nest_and_reuses_it(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="Test", include_vertical=False)

        first = subject.add_event_referent(alignment, "SUPERELEVATIONEVENT", 250.0)

        stationing_nest = align_api.get_stationing_nest(ifc_file, alignment)
        assert first not in stationing_nest.RelatedObjects

        second = subject.add_event_referent(alignment, "WIDTHEVENT", 400.0)

        events_nests = [rel for rel in alignment.IsNestedBy if first in rel.RelatedObjects]
        # The same events nest is reused across calls -- not a fresh
        # IfcRelNests every time (mirrors commit_layout_change's key-point
        # nest tracking).
        assert len(events_nests) == 1
        assert second in events_nests[0].RelatedObjects


@requires_geometry_engine
class TestAddStationEquationReferent(NewIfc4X3):
    """Tests for Alignment.add_station_equation_referent() — spec 4.3.

    Gated: this is a thin wrapper over align_api.add_stationing_referent,
    which needs the geometry engine for the same update_fallback_position
    reason as TestAddEventReferent above.
    """

    def test_writes_incoming_station_and_returns_station_referent(self):
        import ifcopenshell.util.element

        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="Test", start_station=0.0, include_vertical=False)

        referent = subject.add_station_equation_referent(
            alignment, distance_along=100.0, back_station=100.0, ahead_station=300.0
        )

        assert referent.PredefinedType == "STATION"
        pset = ifcopenshell.util.element.get_pset(referent, "Pset_Stationing", should_inherit=False)
        assert_close(pset["Station"], 300.0)
        assert_close(pset["IncomingStation"], 100.0)

    def test_downstream_station_conversion_respects_the_equation(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="Test", start_station=0.0, include_vertical=False)

        subject.add_station_equation_referent(alignment, distance_along=100.0, back_station=100.0, ahead_station=300.0)

        # distance_along 100 now reads as station 300 -- a 200-unit gap
        # equation was just introduced at that point -- proving every
        # downstream reader keyed off distance_along_from_station /
        # station_from_distance_along automatically respects it.
        result = align_api.station_from_distance_along(ifc_file, alignment, 100.0)
        assert_close(result, 300.0)

    def test_supports_an_overlap_equation(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="Test", start_station=0.0, include_vertical=False)

        # An overlap equation: ahead_station < back_station.
        subject.add_station_equation_referent(alignment, distance_along=300.0, back_station=300.0, ahead_station=100.0)

        result = align_api.station_from_distance_along(ifc_file, alignment, 300.0)
        assert_close(result, 100.0)


class TestGetStationTicks(NewIfc4X3):
    """Tests for Alignment.get_station_ticks() — spec 4.1."""

    def test_returns_empty_list_when_no_real_segments(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="Empty", include_vertical=False)
        assert subject.get_station_ticks(alignment, 100.0) == []

    def test_returns_empty_list_when_evaluation_is_unavailable(self, monkeypatch):
        """Degrades to [] when evaluate_alignment_at_station can't resolve
        any station -- e.g. no geometry engine (IfcOpenShell#9301).
        Monkeypatched so this is deterministic regardless of local engine
        availability (get_station_ticks itself does nothing engine-specific
        -- it just consumes evaluate_alignment_at_station's contract)."""
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="NoEval", include_vertical=False)
        monkeypatch.setattr(subject, "get_alignment_length", classmethod(lambda cls, a: 300.0))
        monkeypatch.setattr(subject, "evaluate_alignment_at_station", classmethod(lambda cls, a, s: None))

        assert subject.get_station_ticks(alignment, 100.0) == []

    @requires_geometry_engine
    def test_returns_ticks_with_positions_directions_and_stations(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="WithEngine", start_station=0.0, include_vertical=False)
        h_layout = align_api.get_horizontal_layout(alignment)
        align_api.layout_horizontal_alignment_by_pi_method(
            ifc_file, h_layout, hpoints=[(0.0, 0.0), (200.0, 0.0)], radii=[]
        )

        ticks = subject.get_station_ticks(alignment, 50.0)

        assert len(ticks) >= 3  # stations 0, 50, 100, 150, 200
        position, direction, station = ticks[0]
        assert len(position) == 3
        assert len(direction) == 3
        assert isinstance(station, float)
        assert_close(ticks[0][2], 0.0)


class TestCommitLayoutChange(NewIfc4X3):
    """Tests for Alignment.commit_layout_change() — spec 4.2."""

    def test_returns_zero_for_alignment_with_no_real_segments(self):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="Empty", include_vertical=False)

        # A segment-less horizontal layout's update_key_point_referents call
        # returns an empty nest without ever touching the geometry engine
        # (no segments to iterate) -- this exercises the whole funnel
        # deterministically, regardless of local engine availability.
        count = subject.commit_layout_change(alignment)

        assert count == 0

    def test_swallows_geometry_mapping_runtime_error(self, monkeypatch):
        """A "No geometry mapping registered" RuntimeError from any one
        layout's update_key_point_referents call must not fail the commit
        as a whole (IfcOpenShell#9301) -- spec 4.2's narrow-catch
        requirement."""
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="Test", include_vertical=False)

        def _raise(*args, **kwargs):
            raise RuntimeError("No geometry mapping registered for IfcAlignmentHorizontal")

        monkeypatch.setattr(align_api, "update_key_point_referents", _raise)

        count = subject.commit_layout_change(alignment)  # must not raise

        assert count == 0

    def test_reraises_unrelated_runtime_errors(self, monkeypatch):
        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name="Test", include_vertical=False)

        def _raise(*args, **kwargs):
            raise RuntimeError("some unrelated failure")

        monkeypatch.setattr(align_api, "update_key_point_referents", _raise)

        with pytest.raises(RuntimeError, match="some unrelated failure"):
            subject.commit_layout_change(alignment)

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
            (200.0, 104.0),   # interior 1: g_in=+2%, g_out varies
            (600.0, 100.0),   # interior 2
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
        alignment = ifc_file.createIfcAlignment(
            GlobalId=ifcopenshell.guid.new(), Name="Bare"
        )
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

        subject.layout_by_pi_method(
            h_layout, [(0.0, 0.0), (500.0, 0.0), (1000.0, 200.0)], [300.0]
        )

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
        alignment, _ = _create_alignment_with_pis(
            hpoints=[(0.0, 0.0), (1000.0, 0.0)], radii=[]
        )
        pis = subject.back_calculate_pis_from_alignment(alignment)
        assert len(pis) >= 2
        assert pis[0]["pi_type"] == "ENDPOINT"
        assert pis[-1]["pi_type"] == "ENDPOINT"
        assert_close(pis[0]["e"], 0.0, tol=0.01)
        assert_close(pis[0]["n"], 0.0, tol=0.01)
        assert_close(pis[-1]["e"], 1000.0, tol=0.01)
        assert_close(pis[-1]["n"], 0.0, tol=0.01)

    def test_recovers_curve_pi_with_radius(self):
        alignment, _ = _create_alignment_with_pis(
            hpoints=[(0.0, 0.0), (500.0, 0.0), (1000.0, 200.0)], radii=[300.0]
        )
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
        alignment = ifc_file.createIfcAlignment(
            GlobalId=ifcopenshell.guid.new(), Name="Bare"
        )
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
        alignment, _ = _create_alignment_with_pis(
            hpoints=original_hpoints, radii=original_radii
        )

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
        alignment, _ = _create_alignment_with_pis(
            hpoints=[(0.0, 0.0), (500.0, 0.0), (1000.0, 200.0)], radii=[300.0]
        )
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
        alignment, _ = _create_alignment_with_pis(
            hpoints=[(0.0, 0.0), (500.0, 0.0)], radii=[]
        )
        alignment_obj = subject.create_hierarchy_for_alignment(alignment)
        pis = subject.back_calculate_pis_from_alignment(alignment)
        empties = subject.create_pi_edit_empties(alignment, pis)
        for empty in empties:
            assert empty.parent == alignment_obj

    def test_empties_have_sequential_pi_indices(self):
        alignment, _ = _create_alignment_with_pis(
            hpoints=[(0.0, 0.0), (500.0, 0.0), (1000.0, 200.0)], radii=[300.0]
        )
        alignment_obj = subject.create_hierarchy_for_alignment(alignment)
        pis = subject.back_calculate_pis_from_alignment(alignment)
        empties = subject.create_pi_edit_empties(alignment, pis)
        indices = [e.get("civil_pi_index") for e in empties]
        assert indices == list(range(len(pis)))


@requires_geometry_engine
class TestGetPiEditEmpties(NewIfc4X3):
    """Tests for Alignment.get_pi_edit_empties()."""

    def test_finds_empties_for_given_alignment_id(self):
        alignment, _ = _create_alignment_with_pis(
            hpoints=[(0.0, 0.0), (500.0, 0.0)], radii=[]
        )
        alignment_obj = subject.create_hierarchy_for_alignment(alignment)
        pis = subject.back_calculate_pis_from_alignment(alignment)
        subject.create_pi_edit_empties(alignment, pis)

        found = subject.get_pi_edit_empties(alignment.id())
        assert len(found) == len(pis)

    def test_returns_empty_list_when_no_empties_exist(self):
        found = subject.get_pi_edit_empties(99999)
        assert found == []

    def test_returns_sorted_by_pi_index(self):
        alignment, _ = _create_alignment_with_pis(
            hpoints=[(0.0, 0.0), (500.0, 0.0), (1000.0, 200.0)], radii=[300.0]
        )
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
        alignment, _ = _create_alignment_with_pis(
            hpoints=[(0.0, 0.0), (500.0, 0.0), (1000.0, 200.0)], radii=[300.0]
        )
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
        alignment, _ = _create_alignment_with_pis(
            hpoints=[(0.0, 0.0), (500.0, 0.0), (1000.0, 200.0)], radii=[300.0]
        )
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
        alignment, _ = _create_alignment_with_pis(
            hpoints=[(0.0, 0.0), (500.0, 0.0), (1000.0, 200.0)], radii=[300.0]
        )
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
        alignment_objects_before = [
            o for o in bpy.data.objects if tool.Ifc.get_entity(o)
        ]
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

        alignment, _ = _create_alignment_with_pis(
            hpoints=[(0.0, 0.0), (500.0, 0.0), (1000.0, 200.0)], radii=[300.0]
        )

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
        align_api.layout_horizontal_alignment_by_pi_method(
            ifc, h_layout, hpoints=[(0.0, 0.0), (1000.0, 0.0)], radii=[]
        )
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
        align_api.layout_horizontal_alignment_by_pi_method(
            ifc_file, h, hpoints=[(0.0, 0.0), (1000.0, 0.0)], radii=[]
        )
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
        transform = subject.build_profile_view_transform(
            design, [], 0.0, 0.0, 500.0, 200.0, vertical_exaggeration=10.0
        )
        # Horizontal scale: 500 px / 1000 units = 0.5 px/unit; ×10 exaggeration
        # gives 5 px/unit vertically → 200 px shows 40 units, centered on 105.
        assert_close(transform.elevation_min, 85.0)
        assert_close(transform.elevation_max, 125.0)

    def test_zero_exaggeration_keeps_auto_fit_with_padding(self):
        design = [(0.0, 100.0), (1000.0, 110.0)]
        transform = subject.build_profile_view_transform(
            design, [], 0.0, 0.0, 500.0, 200.0, vertical_exaggeration=0.0
        )
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
        align_api.layout_horizontal_alignment_by_pi_method(
            ifc, h_layout, hpoints=[(0.0, 0.0), (length, 0.0)], radii=[]
        )
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
        align_api.layout_horizontal_alignment_by_pi_method(
            ifc, h, hpoints=[(0.0, 0.0), (1000.0, 0.0)], radii=[]
        )
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

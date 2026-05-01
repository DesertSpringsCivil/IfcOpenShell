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

"""Tests for ``bonsai.tool.grading``.

Run via the canonical Phase 4/5 invocation (PowerShell, from src/bonsai)::

    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
    python -m pytest test/tool/test_grading.py `
      -o "addopts=" `
      -p pytest-blender `
      -v `
      --blender-executable "C:\\Program Files\\Blender Foundation\\Blender_5\\blender.exe"
"""

import bpy
import ifcopenshell
import ifcopenshell.api.unit
import ifcopenshell.guid
import numpy as np
import pytest

import bonsai.tool as tool
import bonsai.tool.grading as tool_grading
import bonsai.tool.surface as tool_surface
from test.bim.bootstrap import NewIfc4X3


@pytest.fixture(autouse=True)
def _reset_grading_registry():
    """Wipe :attr:`Grading._registry` between every test (per spec §4.6).
    Mirrors the surface module's autouse teardown."""
    yield
    tool_grading.Grading.clear()


def _make_ifc_file_with_site() -> ifcopenshell.file:
    """Build a minimal IFC4X3 file with project + site for IFC-authoring
    tests. Mirrors the helper in test_surface.py."""
    ifc_file = ifcopenshell.file(schema="IFC4X3_ADD2")
    project = ifc_file.create_entity(
        "IfcProject", GlobalId=ifcopenshell.guid.new(), Name="Test Project"
    )
    length = ifcopenshell.api.unit.add_si_unit(ifc_file, unit_type="LENGTHUNIT")
    ifcopenshell.api.unit.assign_unit(ifc_file, units=[length])
    site = ifc_file.create_entity(
        "IfcSite", GlobalId=ifcopenshell.guid.new(), Name="Test Site"
    )
    ifc_file.create_entity(
        "IfcRelAggregates",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=project,
        RelatedObjects=[site],
    )
    return ifc_file


# ---------------------------------------------------------------------------
# FeatureLine
# ---------------------------------------------------------------------------


class TestFeatureLine:
    """Tests for :class:`bonsai.tool.grading.FeatureLine`."""

    def test_minimum_construction(self) -> None:
        """No required arguments — every field has a default."""
        feature_line = tool_grading.FeatureLine()
        assert isinstance(feature_line.guid, str)
        assert len(feature_line.guid) == 22  # IFC GlobalId compressed length
        assert feature_line.name == ""
        assert feature_line.vertices == []
        assert feature_line.closed is False
        assert feature_line.grading_group is None
        assert feature_line.ifc_alignment_id is None

    def test_explicit_construction(self) -> None:
        feature_line = tool_grading.FeatureLine(
            guid="0123456789ABCDEFGHIJKL",
            name="Pad perimeter",
            vertices=[(0.0, 0.0, 100.0), (10.0, 0.0, 100.0), (10.0, 10.0, 100.0)],
            closed=True,
            grading_group="parent-group-guid",
            ifc_alignment_id=42,
        )
        assert feature_line.name == "Pad perimeter"
        assert feature_line.closed is True
        assert feature_line.grading_group == "parent-group-guid"
        assert feature_line.ifc_alignment_id == 42

    def test_default_guid_is_unique_per_instance(self) -> None:
        """Default factory mints a fresh GUID for each construction so two
        feature lines aren't accidentally aliased."""
        a = tool_grading.FeatureLine()
        b = tool_grading.FeatureLine()
        assert a.guid != b.guid

    def test_vertices_default_factory_is_independent(self) -> None:
        """``field(default_factory=list)`` (not ``=[]``) means each
        instance gets its own list — append on one doesn't leak."""
        a = tool_grading.FeatureLine()
        b = tool_grading.FeatureLine()
        a.vertices.append((1.0, 2.0, 3.0))
        assert b.vertices == []


# ---------------------------------------------------------------------------
# GradingCriteria
# ---------------------------------------------------------------------------


class TestGradingCriteria:
    """Tests for :class:`bonsai.tool.grading.GradingCriteria`."""

    def test_minimum_construction(self) -> None:
        criteria = tool_grading.GradingCriteria()
        assert isinstance(criteria.guid, str)
        assert criteria.name == ""
        assert criteria.target_kind == "surface"
        assert criteria.target_ref == ""
        assert criteria.cut_slope == pytest.approx(2.0)
        assert criteria.fill_slope == pytest.approx(3.0)
        assert criteria.max_distance is None
        assert criteria.retaining_wall_at_limit is False
        assert criteria.ifc_template_id is None

    @pytest.mark.parametrize(
        "kind",
        ["surface", "elevation", "relative_elevation", "distance"],
    )
    def test_each_target_kind_value_accepted(self, kind: str) -> None:
        criteria = tool_grading.GradingCriteria(target_kind=kind)  # type: ignore[arg-type]
        assert criteria.target_kind == kind

    def test_target_ref_accepts_string_for_surface_target(self) -> None:
        """Surface kind: target_ref is a GUID string."""
        criteria = tool_grading.GradingCriteria(
            target_kind="surface",
            target_ref="surface-guid-22-chars-AB",
        )
        assert isinstance(criteria.target_ref, str)

    def test_target_ref_accepts_float_for_elevation_target(self) -> None:
        """Elevation kind: target_ref is an absolute Z value."""
        criteria = tool_grading.GradingCriteria(
            target_kind="elevation",
            target_ref=125.5,
        )
        assert criteria.target_ref == pytest.approx(125.5)

    def test_max_distance_with_retaining_wall(self) -> None:
        """A criteria can specify a daylight cap and request a wall at
        the cap rather than raising on max-iter."""
        criteria = tool_grading.GradingCriteria(
            max_distance=10.0,
            retaining_wall_at_limit=True,
        )
        assert criteria.max_distance == pytest.approx(10.0)
        assert criteria.retaining_wall_at_limit is True


# ---------------------------------------------------------------------------
# GradingObject
# ---------------------------------------------------------------------------


class TestGradingObject:
    """Tests for :class:`bonsai.tool.grading.GradingObject`."""

    def test_minimum_construction(self) -> None:
        grading_object = tool_grading.GradingObject()
        assert isinstance(grading_object.guid, str)
        assert grading_object.name == ""
        assert grading_object.footprint is None
        assert grading_object.criteria is None
        assert grading_object.target_surface_guid is None
        assert grading_object.daylight_line == []
        assert grading_object.projection_points.shape == (0, 3)
        assert grading_object.projection_triangles.shape == (0, 3)
        assert grading_object.ifc_slope_fill_id is None

    def test_projection_arrays_are_numpy_with_correct_dtypes(self) -> None:
        grading_object = tool_grading.GradingObject()
        assert isinstance(grading_object.projection_points, np.ndarray)
        assert grading_object.projection_points.dtype == np.float64
        assert isinstance(grading_object.projection_triangles, np.ndarray)
        # int dtype family — width depends on platform.
        assert np.issubdtype(grading_object.projection_triangles.dtype, np.integer)

    def test_default_arrays_are_independent_per_instance(self) -> None:
        """``field(default_factory=lambda: np.zeros(...))`` means each
        instance gets its own array — mutating one doesn't leak to the
        next."""
        a = tool_grading.GradingObject()
        b = tool_grading.GradingObject()
        a_id = id(a.projection_points)
        b_id = id(b.projection_points)
        assert a_id != b_id

    def test_full_construction_with_inputs_and_outputs(self) -> None:
        feature_line = tool_grading.FeatureLine(name="bound")
        criteria = tool_grading.GradingCriteria(name="3:1")
        grading_object = tool_grading.GradingObject(
            name="bound @ 3:1",
            footprint=feature_line,
            criteria=criteria,
            target_surface_guid="terrain-guid",
            daylight_line=[(5.0, 0.0, 99.0), (5.0, 10.0, 99.0)],
            projection_points=np.array(
                [(0.0, 0.0, 100.0), (5.0, 0.0, 99.0)]
            ),
            projection_triangles=np.array([(0, 1, 0)]),
            ifc_slope_fill_id=99,
        )
        assert grading_object.footprint is feature_line
        assert grading_object.criteria is criteria
        assert len(grading_object.daylight_line) == 2
        assert grading_object.projection_points.shape == (2, 3)
        assert grading_object.ifc_slope_fill_id == 99


# ---------------------------------------------------------------------------
# GradingGroup
# ---------------------------------------------------------------------------


class TestGradingGroup:
    """Tests for :class:`bonsai.tool.grading.GradingGroup`."""

    def test_minimum_construction(self) -> None:
        group = tool_grading.GradingGroup()
        assert isinstance(group.guid, str)
        assert group.name == ""
        assert group.members == []
        assert group.interior_fill == "interpolate_from_boundary"
        assert group.interior_fill_source_guid is None
        assert group.target_surface_guid is None
        assert group.output_surface_guid is None
        assert group.ifc_group_id is None
        assert group.ifc_composite_fill_id is None
        assert group.ifc_interior_fill_id is None
        assert group.metadata == {}

    @pytest.mark.parametrize(
        "strategy",
        ["none", "flat", "interpolate_from_boundary", "from_surface"],
    )
    def test_each_interior_fill_strategy_accepted(self, strategy: str) -> None:
        group = tool_grading.GradingGroup(interior_fill=strategy)  # type: ignore[arg-type]
        assert group.interior_fill == strategy

    def test_members_default_factory_is_independent(self) -> None:
        a = tool_grading.GradingGroup()
        b = tool_grading.GradingGroup()
        a.members.append(tool_grading.GradingObject())
        assert b.members == []

    def test_metadata_default_factory_is_independent(self) -> None:
        """Mirrors the ``CivilSurface.metadata`` invariant — each group
        gets its own scratchpad dict."""
        a = tool_grading.GradingGroup()
        b = tool_grading.GradingGroup()
        a.metadata["test_key"] = "test_value"
        assert b.metadata == {}

    def test_full_construction_with_ifc_ids(self) -> None:
        member = tool_grading.GradingObject(name="m1")
        group = tool_grading.GradingGroup(
            name="North Pad",
            members=[member],
            interior_fill="from_surface",
            interior_fill_source_guid="pit-bottom-guid",
            target_surface_guid="terrain-guid",
            output_surface_guid="composite-guid",
            ifc_group_id=10,
            ifc_composite_fill_id=11,
            ifc_interior_fill_id=12,
        )
        assert group.members[0] is member
        assert group.interior_fill_source_guid == "pit-bottom-guid"
        assert group.ifc_group_id == 10
        assert group.ifc_composite_fill_id == 11
        assert group.ifc_interior_fill_id == 12


# ---------------------------------------------------------------------------
# Typed exceptions
# ---------------------------------------------------------------------------


class TestExceptions:
    """Tests for :class:`SaikeiGradingError` and
    :class:`SaikeiSlopeProjectionError`."""

    def test_grading_error_is_exception(self) -> None:
        with pytest.raises(tool_grading.SaikeiGradingError, match="boom"):
            raise tool_grading.SaikeiGradingError("boom")

    def test_slope_projection_error_subclasses_grading_error(self) -> None:
        """:class:`SaikeiSlopeProjectionError` must be catchable as
        :class:`SaikeiGradingError` so operator error-handling can
        catch the parent type once."""
        assert issubclass(
            tool_grading.SaikeiSlopeProjectionError,
            tool_grading.SaikeiGradingError,
        )

    def test_slope_projection_error_carries_message(self) -> None:
        with pytest.raises(
            tool_grading.SaikeiSlopeProjectionError,
            match="max-iter",
        ):
            raise tool_grading.SaikeiSlopeProjectionError(
                "marching loop hit max-iter"
            )


# ---------------------------------------------------------------------------
# Slope projection — unit tests
# ---------------------------------------------------------------------------


def _flat_existing_surface_at_z(z: float, extent: float = 100.0) -> tool_surface.CivilSurface:
    """Helper: build a flat ``CivilSurface`` at the given Z, large enough
    that the test slope-projection samples don't walk off the edge."""
    half = extent / 2.0
    points = np.array(
        [
            (-half, -half, z),
            (half, -half, z),
            (half, half, z),
            (-half, half, z),
        ]
    )
    return tool_surface.Surface.build_tin_from_points(
        f"flat-z={z}", points
    )


class TestSlopeProjectionDistance:
    """Tests for ``criteria.target_kind == "distance"`` — closed-form
    projection at fixed horizontal offset."""

    def test_distance_projection_offsets_by_horizontal_amount(self) -> None:
        feature_line = tool_grading.FeatureLine(
            vertices=[(0.0, 0.0, 100.0), (10.0, 0.0, 100.0)],
            closed=False,
        )
        criteria = tool_grading.GradingCriteria(
            target_kind="distance",
            target_ref=5.0,
            fill_slope=3.0,
        )
        result = tool_grading.Grading.compute_grading_object(
            feature_line, criteria, side="right"
        )
        # Outward at side="right" of a +X-direction segment is -Y.
        # 5m at fill_slope 3:1 → drops 5/3 ≈ 1.667 m.
        for tie_x, tie_y, tie_z in result.daylight_line:
            assert tie_y == pytest.approx(-5.0)
            assert tie_z == pytest.approx(100.0 - 5.0 / 3.0)


class TestSlopeProjectionElevation:
    """Tests for ``criteria.target_kind == "elevation"`` — closed-form
    projection to an absolute Z."""

    def test_elevation_fill_drops_to_target(self) -> None:
        """Feature line at z=100, target z=99, fill_slope=3 → projection
        runs 3m horizontal and 1m vertical to reach z=99."""
        feature_line = tool_grading.FeatureLine(
            vertices=[(0.0, 0.0, 100.0), (10.0, 0.0, 100.0)],
            closed=False,
        )
        criteria = tool_grading.GradingCriteria(
            target_kind="elevation",
            target_ref=99.0,
            fill_slope=3.0,
        )
        result = tool_grading.Grading.compute_grading_object(
            feature_line, criteria, side="right"
        )
        for tie_x, tie_y, tie_z in result.daylight_line:
            # Outward = -Y, fill drops 1m at 3:1 → Y=-3, Z=99.
            assert tie_y == pytest.approx(-3.0)
            assert tie_z == pytest.approx(99.0)

    def test_elevation_cut_rises_to_target(self) -> None:
        """Feature line at z=99, target z=100, cut_slope=2 → 2m horizontal
        and 1m vertical to reach z=100."""
        feature_line = tool_grading.FeatureLine(
            vertices=[(0.0, 0.0, 99.0), (10.0, 0.0, 99.0)],
            closed=False,
        )
        criteria = tool_grading.GradingCriteria(
            target_kind="elevation",
            target_ref=100.0,
            cut_slope=2.0,
        )
        result = tool_grading.Grading.compute_grading_object(
            feature_line, criteria, side="right"
        )
        for tie_x, tie_y, tie_z in result.daylight_line:
            assert tie_y == pytest.approx(-2.0)
            assert tie_z == pytest.approx(100.0)

    def test_elevation_at_grade_returns_footprint(self) -> None:
        """When footprint Z == target Z, daylight is the footprint itself
        (no projection needed)."""
        feature_line = tool_grading.FeatureLine(
            vertices=[(0.0, 0.0, 100.0), (10.0, 0.0, 100.0)],
            closed=False,
        )
        criteria = tool_grading.GradingCriteria(
            target_kind="elevation",
            target_ref=100.0,
        )
        result = tool_grading.Grading.compute_grading_object(
            feature_line, criteria, side="right"
        )
        for footprint, tie in zip(result.daylight_line, result.daylight_line):
            assert footprint == tie  # at-grade

    def test_elevation_max_distance_raises_without_wall(self) -> None:
        """Cap exceeded with no retaining-wall fallback raises."""
        feature_line = tool_grading.FeatureLine(
            vertices=[(0.0, 0.0, 100.0), (10.0, 0.0, 100.0)],
            closed=False,
        )
        # 5m drop at 3:1 needs 15m horizontal; cap at 5m.
        criteria = tool_grading.GradingCriteria(
            target_kind="elevation",
            target_ref=95.0,
            fill_slope=3.0,
            max_distance=5.0,
            retaining_wall_at_limit=False,
        )
        with pytest.raises(
            tool_grading.SaikeiSlopeProjectionError, match="max_distance"
        ):
            tool_grading.Grading.compute_grading_object(
                feature_line, criteria, side="right"
            )

    def test_elevation_max_distance_with_retaining_wall(self) -> None:
        """Cap exceeded with retaining_wall_at_limit=True returns the
        cap-XY at target_z (vertical-wall close)."""
        feature_line = tool_grading.FeatureLine(
            vertices=[(0.0, 0.0, 100.0), (10.0, 0.0, 100.0)],
            closed=False,
        )
        criteria = tool_grading.GradingCriteria(
            target_kind="elevation",
            target_ref=95.0,
            fill_slope=3.0,
            max_distance=5.0,
            retaining_wall_at_limit=True,
        )
        result = tool_grading.Grading.compute_grading_object(
            feature_line, criteria, side="right"
        )
        for tie_x, tie_y, tie_z in result.daylight_line:
            assert tie_y == pytest.approx(-5.0)  # cap horizontal offset
            assert tie_z == pytest.approx(95.0)  # at target


class TestSlopeProjectionRelativeElevation:
    """Tests for ``criteria.target_kind == "relative_elevation"`` — same
    as elevation but the target is relative to the footprint Z."""

    def test_relative_elevation_drop(self) -> None:
        feature_line = tool_grading.FeatureLine(
            vertices=[(0.0, 0.0, 100.0), (10.0, 0.0, 100.0)],
            closed=False,
        )
        # delta_z = -1: drop 1m relative to footprint.
        criteria = tool_grading.GradingCriteria(
            target_kind="relative_elevation",
            target_ref=-1.0,
            fill_slope=3.0,
        )
        result = tool_grading.Grading.compute_grading_object(
            feature_line, criteria, side="right"
        )
        for tie_x, tie_y, tie_z in result.daylight_line:
            assert tie_z == pytest.approx(99.0)
            assert tie_y == pytest.approx(-3.0)


class TestSlopeProjectionSurface:
    """Tests for ``criteria.target_kind == "surface"`` — marching-loop
    projection against a target :class:`CivilSurface`."""

    def test_fill_to_flat_existing_below_feature_line(self) -> None:
        """Feature line at z=100, flat existing at z=99, 3:1 fill →
        daylight at horizontal offset 3m, z=99."""
        existing = _flat_existing_surface_at_z(99.0)
        feature_line = tool_grading.FeatureLine(
            vertices=[(0.0, 0.0, 100.0), (10.0, 0.0, 100.0)],
            closed=False,
        )
        criteria = tool_grading.GradingCriteria(
            target_kind="surface",
            target_ref=existing.guid,
            fill_slope=3.0,
        )
        result = tool_grading.Grading.compute_grading_object(
            feature_line,
            criteria,
            target_surface=existing,
            side="right",
        )
        # Tolerance loosened to march_step granularity (0.5m) since the
        # marching loop bisects to ~daylight_epsilon precision but the
        # crossing might land on a boundary between iterations.
        for tie_x, tie_y, tie_z in result.daylight_line:
            assert tie_y == pytest.approx(-3.0, abs=0.5)
            assert tie_z == pytest.approx(99.0, abs=0.05)

    def test_cut_to_flat_existing_above_feature_line(self) -> None:
        """Feature line at z=99, flat existing at z=100, 2:1 cut →
        daylight at horizontal offset 2m, z=100."""
        existing = _flat_existing_surface_at_z(100.0)
        feature_line = tool_grading.FeatureLine(
            vertices=[(0.0, 0.0, 99.0), (10.0, 0.0, 99.0)],
            closed=False,
        )
        criteria = tool_grading.GradingCriteria(
            target_kind="surface",
            target_ref=existing.guid,
            cut_slope=2.0,
        )
        result = tool_grading.Grading.compute_grading_object(
            feature_line,
            criteria,
            target_surface=existing,
            side="right",
        )
        for tie_x, tie_y, tie_z in result.daylight_line:
            assert tie_y == pytest.approx(-2.0, abs=0.5)
            assert tie_z == pytest.approx(100.0, abs=0.05)

    def test_at_grade_footprint_returns_footprint_xyz(self) -> None:
        existing = _flat_existing_surface_at_z(100.0)
        feature_line = tool_grading.FeatureLine(
            vertices=[(0.0, 0.0, 100.0), (10.0, 0.0, 100.0)],
            closed=False,
        )
        criteria = tool_grading.GradingCriteria(
            target_kind="surface", target_ref=existing.guid
        )
        result = tool_grading.Grading.compute_grading_object(
            feature_line,
            criteria,
            target_surface=existing,
            side="right",
        )
        # Daylight is the footprint sample itself.
        for sample in result.daylight_line:
            assert sample[2] == pytest.approx(100.0)

    def test_missing_target_surface_raises(self) -> None:
        feature_line = tool_grading.FeatureLine(
            vertices=[(0.0, 0.0, 100.0), (10.0, 0.0, 100.0)],
            closed=False,
        )
        criteria = tool_grading.GradingCriteria(
            target_kind="surface", target_ref="some-guid"
        )
        with pytest.raises(
            tool_grading.SaikeiGradingError, match="requires a target_surface"
        ):
            tool_grading.Grading.compute_grading_object(
                feature_line, criteria, side="right"
            )


class TestOutwardDirection:
    """Tests for outward-direction computation (CCW closed loop, CW closed
    loop, open with explicit side)."""

    def test_ccw_closed_polygon_outward_is_right_of_traversal(self) -> None:
        # Square traversed CCW: (0,0) → (10,0) → (10,10) → (0,10).
        # First edge is +X direction; outward (right) = -Y.
        feature_line = tool_grading.FeatureLine(
            vertices=[
                (0.0, 0.0, 100.0),
                (10.0, 0.0, 100.0),
                (10.0, 10.0, 100.0),
                (0.0, 10.0, 100.0),
            ],
            closed=True,
        )
        outward = tool_grading.Grading._compute_outward_per_segment(
            feature_line, side="auto"
        )
        # Bottom edge (0,0)→(10,0): outward = (0, -1).
        assert outward[0] == pytest.approx((0.0, -1.0))
        # Right edge (10,0)→(10,10): outward = (1, 0).
        assert outward[1] == pytest.approx((1.0, 0.0))

    def test_open_feature_line_with_explicit_side(self) -> None:
        feature_line = tool_grading.FeatureLine(
            vertices=[(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)],
            closed=False,
        )
        outward_right = tool_grading.Grading._compute_outward_per_segment(
            feature_line, side="right"
        )
        assert outward_right[0] == pytest.approx((0.0, -1.0))
        outward_left = tool_grading.Grading._compute_outward_per_segment(
            feature_line, side="left"
        )
        assert outward_left[0] == pytest.approx((0.0, 1.0))

    def test_zero_length_segment_skipped_in_sampling(self) -> None:
        """Consecutive duplicate vertices produce a zero-length segment;
        the sampler must skip it rather than emit a sample with zero
        outward direction."""
        feature_line = tool_grading.FeatureLine(
            vertices=[
                (0.0, 0.0, 100.0),
                (5.0, 0.0, 100.0),
                (5.0, 0.0, 100.0),  # duplicate
                (10.0, 0.0, 100.0),
            ],
            closed=False,
        )
        outward = tool_grading.Grading._compute_outward_per_segment(
            feature_line, side="right"
        )
        # 3 segments total; the middle one is zero-length and emits
        # (0.0, 0.0).
        assert len(outward) == 3
        assert outward[1] == pytest.approx((0.0, 0.0))
        # Sampling should skip the zero-length segment without crashing.
        sample_points, sample_outward = (
            tool_grading.Grading._sample_along_feature_line(
                feature_line, outward, sample_step=1.0
            )
        )
        # Samples on the 0–5 segment (5 + 1) + samples on the 5–10
        # segment (5, plus end vertex on the open last segment).
        assert len(sample_points) > 0
        # No sample carries the zero outward.
        for o in sample_outward:
            assert o != (0.0, 0.0)

    def test_self_intersecting_ring_raises(self) -> None:
        """Bowtie-shaped closed feature line: shapely.Polygon is_valid
        is False; outward computation must reject upfront rather than
        silently producing wrong directions."""
        feature_line = tool_grading.FeatureLine(
            vertices=[
                (0.0, 0.0, 100.0),
                (10.0, 10.0, 100.0),
                (10.0, 0.0, 100.0),
                (0.0, 10.0, 100.0),
            ],
            closed=True,
        )
        with pytest.raises(
            tool_grading.SaikeiGradingError,
            match="not topologically valid",
        ):
            tool_grading.Grading._compute_outward_per_segment(
                feature_line, side="auto"
            )

    def test_open_feature_line_auto_side_raises(self) -> None:
        feature_line = tool_grading.FeatureLine(
            vertices=[(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)],
            closed=False,
        )
        with pytest.raises(
            tool_grading.SaikeiGradingError, match="explicit side"
        ):
            tool_grading.Grading._compute_outward_per_segment(
                feature_line, side="auto"
            )


class TestRibbonTriangulation:
    """Tests for :meth:`Grading._triangulate_ribbon`."""

    def test_two_triangles_per_sample_pair(self) -> None:
        footprint = [(0.0, 0.0, 100.0), (1.0, 0.0, 100.0), (2.0, 0.0, 100.0)]
        daylight = [(0.0, -3.0, 99.0), (1.0, -3.0, 99.0), (2.0, -3.0, 99.0)]
        points, triangles = tool_grading.Grading._triangulate_ribbon(
            footprint, daylight
        )
        # 3 footprint + 3 daylight = 6 points; 2 triangles per consecutive
        # pair × 2 pairs = 4 triangles.
        assert points.shape == (6, 3)
        assert triangles.shape == (4, 3)

    def test_empty_input_returns_empty_arrays(self) -> None:
        points, triangles = tool_grading.Grading._triangulate_ribbon([], [])
        assert points.shape == (0, 3)
        assert triangles.shape == (0, 3)

    def test_mismatched_lengths_returns_empty_arrays(self) -> None:
        points, triangles = tool_grading.Grading._triangulate_ribbon(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
            [(0.0, -1.0, 0.0)],  # only 1 daylight for 2 footprint
        )
        assert points.shape == (0, 3)
        assert triangles.shape == (0, 3)

    def test_closed_ribbon_emits_wraparound_strip(self) -> None:
        """For closed feature lines, the ribbon must wrap from the last
        sample back to sample 0 — otherwise the closing strip is
        missing and the proposed surface has a gap.
        """
        footprint = [
            (0.0, 0.0, 100.0),
            (1.0, 0.0, 100.0),
            (1.0, 1.0, 100.0),
            (0.0, 1.0, 100.0),
        ]
        daylight = [
            (-1.0, -1.0, 99.0),
            (2.0, -1.0, 99.0),
            (2.0, 2.0, 99.0),
            (-1.0, 2.0, 99.0),
        ]
        # Open ribbon: 3 strips × 2 triangles = 6.
        _, open_triangles = tool_grading.Grading._triangulate_ribbon(
            footprint, daylight, closed=False
        )
        assert open_triangles.shape == (6, 3)
        # Closed ribbon: 4 strips × 2 triangles = 8.
        _, closed_triangles = tool_grading.Grading._triangulate_ribbon(
            footprint, daylight, closed=True
        )
        assert closed_triangles.shape == (8, 3)


class TestCompositeSurfaceGuid:
    """Pin: composite_surface.guid in rebuild_group_surface MUST match
    the IFC composite fill's GlobalId so tool.Surface.get can resolve
    it. Phase 6 volume math depends on this lookup working."""

    def test_composite_surface_guid_matches_ifc_composite_fill(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        group = tool_grading.GradingGroup(
            name="guid-pin", interior_fill="none"
        )
        tool_grading.Grading.author_group(ifc_file, group)
        feature_line = tool_grading.FeatureLine(
            vertices=[(0.0, 0.0, 100.0), (10.0, 0.0, 100.0)],
            closed=False,
        )
        criteria = tool_grading.GradingCriteria(
            target_kind="distance", target_ref=3.0
        )
        member = tool_grading.Grading.compute_grading_object(
            feature_line, criteria, side="right"
        )
        tool_grading.Grading.author_slope_fill(ifc_file, group, member)
        group.members.append(member)

        composite_surface = tool_grading.Grading.rebuild_group_surface(
            ifc_file, group
        )
        composite_fill_entity = ifc_file.by_id(group.ifc_composite_fill_id)
        # The dataclass GUID must match the IFC entity's GlobalId.
        assert composite_surface.guid == composite_fill_entity.GlobalId
        # And group.output_surface_guid points at the same GUID.
        assert group.output_surface_guid == composite_fill_entity.GlobalId


class TestComputeGradingObjectIntegration:
    """End-to-end tests for :meth:`Grading.compute_grading_object`."""

    def test_returns_grading_object_with_populated_outputs(self) -> None:
        feature_line = tool_grading.FeatureLine(
            vertices=[(0.0, 0.0, 100.0), (10.0, 0.0, 100.0)],
            closed=False,
        )
        criteria = tool_grading.GradingCriteria(
            target_kind="distance", target_ref=3.0
        )
        result = tool_grading.Grading.compute_grading_object(
            feature_line, criteria, side="right", name="test"
        )
        assert isinstance(result, tool_grading.GradingObject)
        assert result.name == "test"
        assert result.footprint is feature_line
        assert result.criteria is criteria
        assert len(result.daylight_line) > 0
        assert result.projection_points.shape[0] > 0
        assert result.projection_triangles.shape[0] > 0
        assert result.projection_triangles.shape[1] == 3

    def test_too_short_feature_line_raises(self) -> None:
        feature_line = tool_grading.FeatureLine(
            vertices=[(0.0, 0.0, 0.0)], closed=False
        )
        criteria = tool_grading.GradingCriteria(target_kind="distance", target_ref=1.0)
        with pytest.raises(
            tool_grading.SaikeiGradingError, match="≥ 2 vertices"
        ):
            tool_grading.Grading.compute_grading_object(
                feature_line, criteria, side="right"
            )

    def test_unknown_target_kind_raises(self) -> None:
        feature_line = tool_grading.FeatureLine(
            vertices=[(0.0, 0.0, 100.0), (10.0, 0.0, 100.0)],
            closed=False,
        )
        # Bypass the dataclass Literal check by constructing then mutating.
        criteria = tool_grading.GradingCriteria(target_kind="distance", target_ref=1.0)
        criteria.target_kind = "bogus"  # type: ignore[assignment]
        with pytest.raises(
            tool_grading.SaikeiGradingError, match="unknown target_kind"
        ):
            tool_grading.Grading.compute_grading_object(
                feature_line, criteria, side="right"
            )


# ---------------------------------------------------------------------------
# IFC authoring wrappers
# ---------------------------------------------------------------------------


class TestAuthorFeatureLine:
    """Tests for :meth:`Grading.author_feature_line`."""

    def test_creates_alignment(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        feature_line = tool_grading.FeatureLine(
            name="Pad perimeter",
            vertices=[
                (0.0, 0.0, 100.0),
                (10.0, 0.0, 100.0),
                (10.0, 10.0, 100.0),
                (0.0, 10.0, 100.0),
            ],
            closed=True,
        )
        alignment = tool_grading.Grading.author_feature_line(ifc_file, feature_line)
        assert alignment.is_a("IfcAlignment")
        assert alignment.Name == "Pad perimeter"

    def test_global_id_matches_dataclass_guid(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        feature_line = tool_grading.FeatureLine(
            name="bound",
            vertices=[(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)],
        )
        alignment = tool_grading.Grading.author_feature_line(ifc_file, feature_line)
        assert alignment.GlobalId == feature_line.guid

    def test_stamps_step_id(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        feature_line = tool_grading.FeatureLine(
            vertices=[(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)]
        )
        alignment = tool_grading.Grading.author_feature_line(ifc_file, feature_line)
        assert feature_line.ifc_alignment_id == alignment.id()

    def test_too_short_raises(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        feature_line = tool_grading.FeatureLine(vertices=[(0.0, 0.0, 0.0)])
        with pytest.raises(tool_grading.SaikeiGradingError, match="≥ 2 vertices"):
            tool_grading.Grading.author_feature_line(ifc_file, feature_line)


class TestAuthorCriteriaTemplate:
    """Tests for :meth:`Grading.author_criteria_template`."""

    def test_creates_property_set_template(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        criteria = tool_grading.GradingCriteria(name="3:1 fill / 2:1 cut")
        template = tool_grading.Grading.author_criteria_template(ifc_file, criteria)
        assert template.is_a("IfcPropertySetTemplate")

    def test_idempotent_on_repeat_call(self) -> None:
        """Phase 2 API treats the template as singleton-by-shape — two
        calls return the same entity."""
        ifc_file = _make_ifc_file_with_site()
        criteria_a = tool_grading.GradingCriteria()
        criteria_b = tool_grading.GradingCriteria()
        template_a = tool_grading.Grading.author_criteria_template(ifc_file, criteria_a)
        template_b = tool_grading.Grading.author_criteria_template(ifc_file, criteria_b)
        assert template_a.id() == template_b.id()

    def test_stamps_template_id_on_criteria(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        criteria = tool_grading.GradingCriteria()
        template = tool_grading.Grading.author_criteria_template(ifc_file, criteria)
        assert criteria.ifc_template_id == template.id()


class TestAuthorGroup:
    """Tests for :meth:`Grading.author_group`."""

    def test_creates_group_and_composite_fill(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        group = tool_grading.GradingGroup(name="North Pad")
        ifc_group = tool_grading.Grading.author_group(ifc_file, group)
        assert ifc_group.is_a("IfcGroup")
        assert ifc_group.ObjectType == "GradingGroup"
        assert ifc_group.Name == "North Pad"

        # Composite fill exists and is referenced by the group.
        composite = ifc_file.by_id(group.ifc_composite_fill_id)
        assert composite.is_a("IfcEarthworksFill")
        assert composite.PredefinedType == "SUBGRADE"

    def test_global_id_matches_dataclass_guid(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        group = tool_grading.GradingGroup(name="GuidTest")
        ifc_group = tool_grading.Grading.author_group(ifc_file, group)
        assert ifc_group.GlobalId == group.guid

    def test_stamps_step_ids(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        group = tool_grading.GradingGroup()
        ifc_group = tool_grading.Grading.author_group(ifc_file, group)
        assert group.ifc_group_id == ifc_group.id()
        assert group.ifc_composite_fill_id is not None

    def test_interior_fill_strategy_passes_through(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        group = tool_grading.GradingGroup(interior_fill="flat")
        tool_grading.Grading.author_group(ifc_file, group)
        # Pset_SaikeiGradingSource on the group records InteriorFillStrategy.
        ifc_group = ifc_file.by_id(group.ifc_group_id)
        psets = []
        for rel in ifc_file.by_type("IfcRelDefinesByProperties"):
            if ifc_group in (rel.RelatedObjects or []):
                psets.append(rel.RelatingPropertyDefinition)
        source_pset = next(
            (p for p in psets if p.Name == "Pset_SaikeiGradingSource"), None
        )
        assert source_pset is not None
        strategy = next(
            (
                p.NominalValue.wrappedValue
                for p in source_pset.HasProperties
                if p.Name == "InteriorFillStrategy"
            ),
            None,
        )
        assert strategy == "flat"


class TestAssignCriteria:
    """Tests for :meth:`Grading.assign_criteria`."""

    def test_binds_criteria_to_group(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        group = tool_grading.GradingGroup()
        tool_grading.Grading.author_group(ifc_file, group)

        criteria = tool_grading.GradingCriteria(
            name="3:1 fill",
            target_kind="surface",
            target_ref="some-target-guid",
            cut_slope=2.0,
            fill_slope=3.0,
        )
        pset = tool_grading.Grading.assign_criteria(ifc_file, group, criteria)
        assert pset.is_a("IfcPropertySet")

        # Pset is bound to the group via IfcRelDefinesByProperties.
        ifc_group = ifc_file.by_id(group.ifc_group_id)
        bound_psets = []
        for rel in ifc_file.by_type("IfcRelDefinesByProperties"):
            if ifc_group in (rel.RelatedObjects or []):
                bound_psets.append(rel.RelatingPropertyDefinition)
        assert pset in bound_psets

    def test_no_group_raises(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        group = tool_grading.GradingGroup()  # no ifc_group_id
        criteria = tool_grading.GradingCriteria()
        with pytest.raises(
            tool_grading.SaikeiGradingError, match="no IFC entity"
        ):
            tool_grading.Grading.assign_criteria(ifc_file, group, criteria)

    def test_auto_authors_template_when_missing(self) -> None:
        """assign_criteria should auto-author the template if it hasn't
        been authored yet."""
        ifc_file = _make_ifc_file_with_site()
        group = tool_grading.GradingGroup()
        tool_grading.Grading.author_group(ifc_file, group)
        criteria = tool_grading.GradingCriteria()
        # criteria.ifc_template_id is None at this point
        assert criteria.ifc_template_id is None
        tool_grading.Grading.assign_criteria(ifc_file, group, criteria)
        # Template was auto-authored.
        assert criteria.ifc_template_id is not None


class TestAuthorSlopeFill:
    """Tests for :meth:`Grading.author_slope_fill`."""

    @staticmethod
    def _make_grading_object_with_geometry() -> tool_grading.GradingObject:
        feature_line = tool_grading.FeatureLine(
            vertices=[(0.0, 0.0, 100.0), (10.0, 0.0, 100.0)],
            closed=False,
        )
        criteria = tool_grading.GradingCriteria(
            target_kind="distance", target_ref=3.0
        )
        return tool_grading.Grading.compute_grading_object(
            feature_line, criteria, side="right"
        )

    def test_creates_slopefill(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        group = tool_grading.GradingGroup()
        tool_grading.Grading.author_group(ifc_file, group)

        grading_object = self._make_grading_object_with_geometry()
        slope_fill = tool_grading.Grading.author_slope_fill(
            ifc_file, group, grading_object
        )
        assert slope_fill.is_a("IfcEarthworksFill")
        assert slope_fill.PredefinedType == "SLOPEFILL"

    def test_global_id_matches_grading_object_guid(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        group = tool_grading.GradingGroup()
        tool_grading.Grading.author_group(ifc_file, group)
        grading_object = self._make_grading_object_with_geometry()
        slope_fill = tool_grading.Grading.author_slope_fill(
            ifc_file, group, grading_object
        )
        assert slope_fill.GlobalId == grading_object.guid
        assert grading_object.ifc_slope_fill_id == slope_fill.id()

    def test_no_group_raises(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        group = tool_grading.GradingGroup()  # no ifc ids
        grading_object = self._make_grading_object_with_geometry()
        with pytest.raises(
            tool_grading.SaikeiGradingError, match="no IFC entities"
        ):
            tool_grading.Grading.author_slope_fill(ifc_file, group, grading_object)

    def test_empty_geometry_raises(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        group = tool_grading.GradingGroup()
        tool_grading.Grading.author_group(ifc_file, group)
        empty_grading = tool_grading.GradingObject()  # empty arrays
        with pytest.raises(
            tool_grading.SaikeiGradingError, match="empty projection_points"
        ):
            tool_grading.Grading.author_slope_fill(ifc_file, group, empty_grading)


class TestAuthorInteriorFill:
    """Tests for :meth:`Grading.author_interior_fill`."""

    def test_creates_subgrade_fill(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        group = tool_grading.GradingGroup(interior_fill="flat")
        tool_grading.Grading.author_group(ifc_file, group)
        points = np.array(
            [
                (0.0, 0.0, 99.0),
                (10.0, 0.0, 99.0),
                (10.0, 10.0, 99.0),
                (0.0, 10.0, 99.0),
            ]
        )
        triangles = np.array([(0, 1, 2), (0, 2, 3)])
        interior = tool_grading.Grading.author_interior_fill(
            ifc_file, group, points, triangles
        )
        assert interior.is_a("IfcEarthworksFill")
        assert interior.PredefinedType == "SUBGRADE"
        assert group.ifc_interior_fill_id == interior.id()

    def test_none_strategy_raises(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        group = tool_grading.GradingGroup(interior_fill="none")
        tool_grading.Grading.author_group(ifc_file, group)
        points = np.array([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)])
        triangles = np.array([(0, 1, 2)])
        with pytest.raises(
            tool_grading.SaikeiGradingError,
            match="interior_fill is 'none'",
        ):
            tool_grading.Grading.author_interior_fill(
                ifc_file, group, points, triangles
            )

    def test_no_group_raises(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        group = tool_grading.GradingGroup()  # no ifc ids
        points = np.array([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)])
        triangles = np.array([(0, 1, 2)])
        with pytest.raises(
            tool_grading.SaikeiGradingError, match="no IFC entities"
        ):
            tool_grading.Grading.author_interior_fill(
                ifc_file, group, points, triangles
            )


# ---------------------------------------------------------------------------
# Registry — lazy-rehydrating cache (spec §4.6)
# ---------------------------------------------------------------------------


class TestRegistryFeatureLine:
    """Tests for :class:`Grading._registry` + :meth:`get_feature_line`."""

    def test_register_then_get_returns_same_instance(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        feature_line = tool_grading.FeatureLine(
            name="bound",
            vertices=[(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)],
        )
        tool_grading.Grading.author_feature_line(ifc_file, feature_line)
        tool_grading.Grading.register(ifc_file, feature_line)
        cached = tool_grading.Grading.get_feature_line(ifc_file, feature_line.guid)
        assert cached is feature_line

    def test_get_rehydrates_on_cache_miss(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        feature_line = tool_grading.FeatureLine(
            name="re-bound",
            vertices=[
                (0.0, 0.0, 100.0),
                (10.0, 0.0, 100.5),
                (10.0, 10.0, 101.0),
            ],
            closed=True,
        )
        tool_grading.Grading.author_feature_line(ifc_file, feature_line)
        # Wipe the cache; next get() rehydrates from IFC.
        tool_grading.Grading.clear()
        rehydrated = tool_grading.Grading.get_feature_line(
            ifc_file, feature_line.guid
        )
        assert rehydrated is not feature_line
        assert rehydrated.guid == feature_line.guid
        assert rehydrated.name == "re-bound"
        assert rehydrated.closed is True
        assert len(rehydrated.vertices) == 3
        # Z values round-trip exactly through IfcCartesianPointList3D.
        assert rehydrated.vertices[0][2] == pytest.approx(100.0)
        assert rehydrated.vertices[2][2] == pytest.approx(101.0)

    def test_get_unknown_guid_raises(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        with pytest.raises(
            tool_grading.SaikeiGradingError, match="no IfcAlignment"
        ):
            tool_grading.Grading.get_feature_line(
                ifc_file, ifcopenshell.guid.new()
            )


class TestRegistryGroup:
    """Tests for :meth:`Grading.get_group`."""

    def test_register_then_get_returns_same_instance(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        group = tool_grading.GradingGroup(name="cached", interior_fill="flat")
        tool_grading.Grading.author_group(ifc_file, group)
        tool_grading.Grading.register(ifc_file, group)
        cached = tool_grading.Grading.get_group(ifc_file, group.guid)
        assert cached is group

    def test_get_rehydrates_on_cache_miss(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        group = tool_grading.GradingGroup(
            name="Test Group", interior_fill="flat"
        )
        tool_grading.Grading.author_group(ifc_file, group)
        tool_grading.Grading.clear()
        rehydrated = tool_grading.Grading.get_group(ifc_file, group.guid)
        assert rehydrated is not group
        assert rehydrated.name == "Test Group"
        assert rehydrated.interior_fill == "flat"
        # Composite-fill step id recovered from IfcRelAssignsToGroup.
        assert rehydrated.ifc_composite_fill_id == group.ifc_composite_fill_id
        # Members start empty; member rehydration is commit 6 territory.
        assert rehydrated.members == []

    def test_get_unknown_guid_raises(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        with pytest.raises(
            tool_grading.SaikeiGradingError,
            match="no IfcGroup\\[GradingGroup\\]",
        ):
            tool_grading.Grading.get_group(ifc_file, ifcopenshell.guid.new())


class TestRegistryLifecycle:
    """Tests for :meth:`Grading.invalidate` and :meth:`clear`."""

    def test_invalidate_drops_specific_entry(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        feature_line = tool_grading.FeatureLine(
            vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
        )
        tool_grading.Grading.author_feature_line(ifc_file, feature_line)
        tool_grading.Grading.register(ifc_file, feature_line)
        assert (id(ifc_file), feature_line.guid) in tool_grading.Grading._registry
        tool_grading.Grading.invalidate(ifc_file, feature_line.guid)
        assert (
            id(ifc_file),
            feature_line.guid,
        ) not in tool_grading.Grading._registry

    def test_clear_wipes_registry(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        feature_line = tool_grading.FeatureLine(
            vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
        )
        tool_grading.Grading.author_feature_line(ifc_file, feature_line)
        tool_grading.Grading.register(ifc_file, feature_line)
        assert tool_grading.Grading._registry  # non-empty
        tool_grading.Grading.clear()
        assert not tool_grading.Grading._registry

    def test_multi_file_registry_keyed_by_id(self) -> None:
        """Same GUID in two files → two separate cache entries."""
        ifc_a = _make_ifc_file_with_site()
        ifc_b = _make_ifc_file_with_site()
        guid = ifcopenshell.guid.new()
        feature_line_a = tool_grading.FeatureLine(
            guid=guid, vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
        )
        feature_line_b = tool_grading.FeatureLine(
            guid=guid, vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
        )
        tool_grading.Grading.author_feature_line(ifc_a, feature_line_a)
        tool_grading.Grading.author_feature_line(ifc_b, feature_line_b)
        tool_grading.Grading.register(ifc_a, feature_line_a)
        tool_grading.Grading.register(ifc_b, feature_line_b)
        assert tool_grading.Grading.get_feature_line(ifc_a, guid) is feature_line_a
        assert tool_grading.Grading.get_feature_line(ifc_b, guid) is feature_line_b


# ---------------------------------------------------------------------------
# Blender object linkage
# ---------------------------------------------------------------------------


class TestBlenderCurve(NewIfc4X3):
    """Tests for :meth:`Grading.create_blender_curve` — feature lines as
    Blender curve objects. Inherits NewIfc4X3 so each test starts with
    a Bonsai-bootstrapped project (Collector.assign needs the
    collection hierarchy).
    """

    def test_creates_curve_object(self) -> None:
        ifc_file = tool.Ifc.get()
        feature_line = tool_grading.FeatureLine(
            name="curve-test",
            vertices=[(0.0, 0.0, 100.0), (10.0, 0.0, 100.0), (10.0, 10.0, 100.0)],
        )
        tool_grading.Grading.author_feature_line(ifc_file, feature_line)
        obj = tool_grading.Grading.create_blender_curve(ifc_file, feature_line)
        assert obj is not None
        assert obj.type == "CURVE"
        assert obj.data is not None

    def test_links_to_ifc_alignment(self) -> None:
        ifc_file = tool.Ifc.get()
        feature_line = tool_grading.FeatureLine(
            name="link-test",
            vertices=[(0.0, 0.0, 0.0), (5.0, 0.0, 0.0)],
        )
        tool_grading.Grading.author_feature_line(ifc_file, feature_line)
        obj = tool_grading.Grading.create_blender_curve(ifc_file, feature_line)
        alignment = ifc_file.by_id(feature_line.ifc_alignment_id)
        assert tool.Ifc.get_object(alignment) is obj
        assert tool.Ifc.get_entity(obj) == alignment

    def test_idempotent_on_repeat_call(self) -> None:
        ifc_file = tool.Ifc.get()
        feature_line = tool_grading.FeatureLine(
            vertices=[(0.0, 0.0, 0.0), (5.0, 0.0, 0.0)]
        )
        tool_grading.Grading.author_feature_line(ifc_file, feature_line)
        a = tool_grading.Grading.create_blender_curve(ifc_file, feature_line)
        b = tool_grading.Grading.create_blender_curve(ifc_file, feature_line)
        assert a is b

    def test_no_ifc_alignment_raises(self) -> None:
        ifc_file = tool.Ifc.get()
        feature_line = tool_grading.FeatureLine(
            vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
        )
        with pytest.raises(
            tool_grading.SaikeiGradingError, match="no IFC alignment"
        ):
            tool_grading.Grading.create_blender_curve(ifc_file, feature_line)

    def test_closed_feature_line_yields_cyclic_spline(self) -> None:
        ifc_file = tool.Ifc.get()
        feature_line = tool_grading.FeatureLine(
            vertices=[
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (1.0, 1.0, 0.0),
                (0.0, 1.0, 0.0),
            ],
            closed=True,
        )
        tool_grading.Grading.author_feature_line(ifc_file, feature_line)
        obj = tool_grading.Grading.create_blender_curve(ifc_file, feature_line)
        assert obj.data.splines[0].use_cyclic_u is True


class TestBlenderGroupEmpty(NewIfc4X3):
    """Tests for :meth:`Grading.create_blender_empty_for_group`."""

    def test_creates_empty_object(self) -> None:
        ifc_file = tool.Ifc.get()
        group = tool_grading.GradingGroup(name="empty-test")
        tool_grading.Grading.author_group(ifc_file, group)
        obj = tool_grading.Grading.create_blender_empty_for_group(ifc_file, group)
        assert obj is not None
        assert obj.type == "EMPTY"
        assert obj.data is None

    def test_links_to_ifc_group(self) -> None:
        ifc_file = tool.Ifc.get()
        group = tool_grading.GradingGroup(name="g")
        tool_grading.Grading.author_group(ifc_file, group)
        obj = tool_grading.Grading.create_blender_empty_for_group(ifc_file, group)
        ifc_group = ifc_file.by_id(group.ifc_group_id)
        assert tool.Ifc.get_object(ifc_group) is obj

    def test_idempotent_on_repeat_call(self) -> None:
        ifc_file = tool.Ifc.get()
        group = tool_grading.GradingGroup()
        tool_grading.Grading.author_group(ifc_file, group)
        a = tool_grading.Grading.create_blender_empty_for_group(ifc_file, group)
        b = tool_grading.Grading.create_blender_empty_for_group(ifc_file, group)
        assert a is b

    def test_no_ifc_group_raises(self) -> None:
        ifc_file = tool.Ifc.get()
        group = tool_grading.GradingGroup()
        with pytest.raises(
            tool_grading.SaikeiGradingError, match="no IFC entity"
        ):
            tool_grading.Grading.create_blender_empty_for_group(ifc_file, group)


# ---------------------------------------------------------------------------
# Group composite surface — rebuild_group_surface (spec §6.3 skeleton)
# ---------------------------------------------------------------------------


class TestRebuildGroupSurface:
    """Tests for :meth:`Grading.rebuild_group_surface` — the merge
    skeleton. Interior-fill strategies land in commit 7."""

    @staticmethod
    def _populate_group_with_one_grading_object(
        ifc_file,
    ) -> tuple[tool_grading.GradingGroup, tool_grading.GradingObject]:
        """Helper: create a group with a single SLOPEFILL member ready
        for rebuild."""
        group = tool_grading.GradingGroup(
            name="rebuild-test", interior_fill="none"
        )
        tool_grading.Grading.author_group(ifc_file, group)

        feature_line = tool_grading.FeatureLine(
            vertices=[(0.0, 0.0, 100.0), (10.0, 0.0, 100.0)],
            closed=False,
        )
        criteria = tool_grading.GradingCriteria(
            target_kind="distance", target_ref=3.0, fill_slope=3.0
        )
        grading_object = tool_grading.Grading.compute_grading_object(
            feature_line, criteria, side="right", name="member-1"
        )
        tool_grading.Grading.author_slope_fill(
            ifc_file, group, grading_object
        )
        group.members.append(grading_object)
        return group, grading_object

    def test_rebuild_with_one_member_produces_composite_surface(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        group, member = self._populate_group_with_one_grading_object(ifc_file)
        composite = tool_grading.Grading.rebuild_group_surface(ifc_file, group)
        assert composite is not None
        assert composite.kind == "proposed_group"
        assert composite.points.shape[0] == member.projection_points.shape[0]
        assert composite.triangles.shape[0] == member.projection_triangles.shape[0]

    def test_rebuild_stamps_output_surface_guid(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        group, _ = self._populate_group_with_one_grading_object(ifc_file)
        composite = tool_grading.Grading.rebuild_group_surface(ifc_file, group)
        assert group.output_surface_guid == composite.guid

    def test_rebuild_updates_existing_composite_fill_tin(self) -> None:
        """rebuild_group_surface should NOT author a new composite fill
        — it updates the in-place TIN representation of the composite
        already created by author_group."""
        ifc_file = _make_ifc_file_with_site()
        group, _ = self._populate_group_with_one_grading_object(ifc_file)
        before_count = len(ifc_file.by_type("IfcEarthworksFill"))
        tool_grading.Grading.rebuild_group_surface(ifc_file, group)
        # No new IfcEarthworksFill — only the slope fill (1) and the
        # composite (1) authored earlier.
        assert (
            len(ifc_file.by_type("IfcEarthworksFill"))
            == before_count
        )

    def test_rebuild_with_two_members_concatenates_geometry(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        group = tool_grading.GradingGroup(interior_fill="none")
        tool_grading.Grading.author_group(ifc_file, group)
        # Two non-overlapping segments → two grading objects → two
        # ribbons that concatenate into one composite.
        for offset_x, offset_y in [(0.0, 0.0), (0.0, 30.0)]:
            feature_line = tool_grading.FeatureLine(
                vertices=[
                    (offset_x, offset_y, 100.0),
                    (offset_x + 10.0, offset_y, 100.0),
                ],
                closed=False,
            )
            criteria = tool_grading.GradingCriteria(
                target_kind="distance", target_ref=3.0
            )
            grading_object = tool_grading.Grading.compute_grading_object(
                feature_line, criteria, side="right"
            )
            tool_grading.Grading.author_slope_fill(
                ifc_file, group, grading_object
            )
            group.members.append(grading_object)

        composite = tool_grading.Grading.rebuild_group_surface(ifc_file, group)
        # Each member contributes some points; merged is the sum (no
        # vertex deduplication in the skeleton — that's a future
        # optimization).
        expected_point_count = sum(
            m.projection_points.shape[0] for m in group.members
        )
        assert composite.points.shape[0] == expected_point_count

    def test_rebuild_no_group_raises(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        group = tool_grading.GradingGroup()  # no ifc ids
        with pytest.raises(
            tool_grading.SaikeiGradingError, match="no IFC entities"
        ):
            tool_grading.Grading.rebuild_group_surface(ifc_file, group)

    def test_rebuild_no_members_raises(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        group = tool_grading.GradingGroup(interior_fill="none")
        tool_grading.Grading.author_group(ifc_file, group)
        # No members appended.
        with pytest.raises(
            tool_grading.SaikeiGradingError, match="no members"
        ):
            tool_grading.Grading.rebuild_group_surface(ifc_file, group)



class TestMergeMemberGeometry:
    """Direct tests for :meth:`Grading._merge_member_geometry`."""

    def test_empty_members_returns_empty_arrays(self) -> None:
        points, triangles = tool_grading.Grading._merge_member_geometry([])
        assert points.shape == (0, 3)
        assert triangles.shape == (0, 3)

    def test_single_member_returns_its_arrays(self) -> None:
        member = tool_grading.GradingObject(
            projection_points=np.array([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]),
            projection_triangles=np.array([(0, 1, 2)]),
        )
        points, triangles = tool_grading.Grading._merge_member_geometry([member])
        assert points.shape == (3, 3)
        assert triangles.shape == (1, 3)
        assert tuple(triangles[0]) == (0, 1, 2)

    def test_multi_member_offsets_triangle_indices(self) -> None:
        """Member-2's triangle index 0 must become member-1's
        len(points) in the merged array."""
        member1 = tool_grading.GradingObject(
            projection_points=np.array([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]),
            projection_triangles=np.array([(0, 1, 2)]),
        )
        member2 = tool_grading.GradingObject(
            projection_points=np.array([(10.0, 0.0, 0.0), (11.0, 0.0, 0.0), (10.0, 1.0, 0.0)]),
            projection_triangles=np.array([(0, 1, 2)]),
        )
        points, triangles = tool_grading.Grading._merge_member_geometry(
            [member1, member2]
        )
        assert points.shape == (6, 3)
        assert triangles.shape == (2, 3)
        assert tuple(triangles[0]) == (0, 1, 2)
        # Member-2's triangle indices offset by 3 (member-1's point count).
        assert tuple(triangles[1]) == (3, 4, 5)

    def test_empty_member_skipped(self) -> None:
        empty_member = tool_grading.GradingObject()  # default empty arrays
        normal_member = tool_grading.GradingObject(
            projection_points=np.array([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]),
            projection_triangles=np.array([(0, 1, 2)]),
        )
        points, triangles = tool_grading.Grading._merge_member_geometry(
            [empty_member, normal_member]
        )
        assert points.shape == (3, 3)
        # No offset since empty member contributed 0 points.
        assert tuple(triangles[0]) == (0, 1, 2)


# ---------------------------------------------------------------------------
# Interior-fill strategies (spec §6.3)
# ---------------------------------------------------------------------------


class TestInteriorFillFlat:
    """Tests for :meth:`Grading._interior_fill_flat` — pad bottom at
    average feature-line Z."""

    def test_square_pad_at_average_z(self) -> None:
        feature_line = tool_grading.FeatureLine(
            vertices=[
                (0.0, 0.0, 100.0),
                (10.0, 0.0, 100.0),
                (10.0, 10.0, 100.0),
                (0.0, 10.0, 100.0),
            ],
            closed=True,
        )
        points, triangles = tool_grading.Grading._interior_fill_flat(feature_line)
        # 4 vertices, 2 triangles for a square.
        assert points.shape == (4, 3)
        assert triangles.shape == (2, 3)
        # All Z's equal the average (100.0 in this constant-Z case).
        for p in points:
            assert p[2] == pytest.approx(100.0)

    def test_average_z_used_for_varied_feature_line(self) -> None:
        feature_line = tool_grading.FeatureLine(
            vertices=[
                (0.0, 0.0, 100.0),
                (10.0, 0.0, 102.0),
                (10.0, 10.0, 104.0),
                (0.0, 10.0, 106.0),
            ],
            closed=True,
        )
        points, _ = tool_grading.Grading._interior_fill_flat(feature_line)
        # Average = (100+102+104+106)/4 = 103
        for p in points:
            assert p[2] == pytest.approx(103.0)


class TestInteriorFillInterpolateFromBoundary:
    """Tests for :meth:`Grading._interior_fill_interpolate_from_boundary` —
    Delaunay over feature-line vertices, Z values preserved."""

    def test_preserves_boundary_z(self) -> None:
        feature_line = tool_grading.FeatureLine(
            vertices=[
                (0.0, 0.0, 100.0),
                (10.0, 0.0, 102.0),
                (10.0, 10.0, 104.0),
                (0.0, 10.0, 106.0),
            ],
            closed=True,
        )
        points, triangles = (
            tool_grading.Grading._interior_fill_interpolate_from_boundary(
                feature_line
            )
        )
        assert points.shape == (4, 3)
        assert triangles.shape == (2, 3)
        # Each point's Z matches the feature-line input.
        expected = {(0.0, 0.0, 100.0), (10.0, 0.0, 102.0),
                    (10.0, 10.0, 104.0), (0.0, 10.0, 106.0)}
        actual = {tuple(p) for p in points}
        assert actual == expected


class TestInteriorFillFromSurface:
    """Tests for :meth:`Grading._interior_fill_from_surface` — drape
    feature-line ring on a source surface."""

    def test_drapes_to_flat_source(self) -> None:
        # Source surface is a flat existing ground at z=98.
        source_points = np.array(
            [(-50.0, -50.0, 98.0), (50.0, -50.0, 98.0),
             (50.0, 50.0, 98.0), (-50.0, 50.0, 98.0)]
        )
        source = tool_surface.Surface.build_tin_from_points("source", source_points)
        feature_line = tool_grading.FeatureLine(
            vertices=[
                (0.0, 0.0, 100.0),  # original Z's get overwritten
                (10.0, 0.0, 100.0),
                (10.0, 10.0, 100.0),
                (0.0, 10.0, 100.0),
            ],
            closed=True,
        )
        points, triangles = (
            tool_grading.Grading._interior_fill_from_surface(feature_line, source)
        )
        assert points.shape == (4, 3)
        assert triangles.shape == (2, 3)
        # All Z's draped to source z=98.
        for p in points:
            assert p[2] == pytest.approx(98.0)

    def test_vertex_outside_source_raises(self) -> None:
        # Tiny source surface; feature line far outside.
        source_points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        )
        source = tool_surface.Surface.build_tin_from_points("tiny", source_points)
        feature_line = tool_grading.FeatureLine(
            vertices=[
                (100.0, 100.0, 0.0),
                (110.0, 100.0, 0.0),
                (110.0, 110.0, 0.0),
                (100.0, 110.0, 0.0),
            ],
            closed=True,
        )
        with pytest.raises(
            tool_grading.SaikeiGradingError,
            match="falls outside",
        ):
            tool_grading.Grading._interior_fill_from_surface(feature_line, source)


class TestComputeInteriorFillDispatcher:
    """Tests for :meth:`Grading._compute_interior_fill` validation."""

    @staticmethod
    def _make_group_with_open_member() -> tool_grading.GradingGroup:
        feature_line = tool_grading.FeatureLine(
            vertices=[(0.0, 0.0, 100.0), (10.0, 0.0, 100.0)],
            closed=False,
        )
        criteria = tool_grading.GradingCriteria(target_kind="distance", target_ref=3.0)
        member = tool_grading.GradingObject(
            footprint=feature_line,
            criteria=criteria,
            projection_points=np.zeros((0, 3)),
            projection_triangles=np.zeros((0, 3), dtype=int),
        )
        group = tool_grading.GradingGroup(interior_fill="flat", members=[member])
        return group

    def test_open_feature_line_raises(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        group = self._make_group_with_open_member()
        with pytest.raises(
            tool_grading.SaikeiGradingError, match="closed loop"
        ):
            tool_grading.Grading._compute_interior_fill(ifc_file, group)

    def test_multi_member_raises(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        group = tool_grading.GradingGroup(
            interior_fill="flat",
            members=[tool_grading.GradingObject(), tool_grading.GradingObject()],
        )
        # SaikeiGradingError (not NotImplementedError) so operators catch
        # it via the documented operator/headless contract — same
        # exception type as other validation failures.
        with pytest.raises(
            tool_grading.SaikeiGradingError, match="single-member"
        ):
            tool_grading.Grading._compute_interior_fill(ifc_file, group)

    def test_from_surface_without_source_guid_raises(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        feature_line = tool_grading.FeatureLine(
            vertices=[
                (0.0, 0.0, 100.0),
                (10.0, 0.0, 100.0),
                (10.0, 10.0, 100.0),
                (0.0, 10.0, 100.0),
            ],
            closed=True,
        )
        member = tool_grading.GradingObject(footprint=feature_line)
        group = tool_grading.GradingGroup(
            interior_fill="from_surface",
            interior_fill_source_guid=None,  # missing!
            members=[member],
        )
        with pytest.raises(
            tool_grading.SaikeiGradingError,
            match="interior_fill_source_guid",
        ):
            tool_grading.Grading._compute_interior_fill(ifc_file, group)


class TestRebuildGroupSurfaceWithInteriorFill:
    """End-to-end tests for rebuild_group_surface with non-none interior
    fill. The pre-commit-7 NotImplementedError path is replaced with
    real interior-fill geometry."""

    @staticmethod
    def _populate_closed_pad_group(
        ifc_file, interior_fill: str, source_surface=None
    ) -> tool_grading.GradingGroup:
        """Build a group with a closed-pad feature line and one slope-fill
        member, ready for rebuild."""
        # Pre-author the source surface (if any) to populate the registry.
        source_arg = None
        if source_surface is not None:
            tool_surface.Surface.author_ifc_host(ifc_file, source_surface)
            tool_surface.Surface.register(ifc_file, source_surface)
            source_arg = ifc_file.by_id(source_surface.ifc_host_entity_id)

        group = tool_grading.GradingGroup(
            name="pad",
            interior_fill=interior_fill,  # type: ignore[arg-type]
            interior_fill_source_guid=(
                source_surface.guid if source_surface is not None else None
            ),
        )
        tool_grading.Grading.author_group(
            ifc_file, group, interior_fill_source=source_arg
        )

        feature_line = tool_grading.FeatureLine(
            name="pad-perimeter",
            vertices=[
                (0.0, 0.0, 100.0),
                (10.0, 0.0, 100.0),
                (10.0, 10.0, 100.0),
                (0.0, 10.0, 100.0),
            ],
            closed=True,
        )
        criteria = tool_grading.GradingCriteria(
            target_kind="distance", target_ref=3.0, fill_slope=3.0
        )
        # Compute one slope-fill ribbon (around the perimeter, outward).
        grading_object = tool_grading.Grading.compute_grading_object(
            feature_line, criteria, side="auto"
        )
        tool_grading.Grading.author_slope_fill(ifc_file, group, grading_object)
        group.members.append(grading_object)
        return group

    def test_flat_strategy_produces_interior_geometry(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        group = self._populate_closed_pad_group(ifc_file, interior_fill="flat")
        composite = tool_grading.Grading.rebuild_group_surface(ifc_file, group)
        # Composite has slope-fill triangles + interior triangles.
        assert composite.triangles.shape[0] > 0
        # Interior fill was authored as IfcEarthworksFill[SUBGRADE].
        assert group.ifc_interior_fill_id is not None
        interior = ifc_file.by_id(group.ifc_interior_fill_id)
        assert interior.is_a("IfcEarthworksFill")
        assert interior.PredefinedType == "SUBGRADE"

    def test_interpolate_strategy_produces_interior_geometry(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        group = self._populate_closed_pad_group(
            ifc_file, interior_fill="interpolate_from_boundary"
        )
        composite = tool_grading.Grading.rebuild_group_surface(ifc_file, group)
        assert composite.triangles.shape[0] > 0
        assert group.ifc_interior_fill_id is not None

    def test_from_surface_strategy_drapes_interior(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        # Source surface at z=98 (1 m below pad).
        source_points = np.array(
            [(-50.0, -50.0, 98.0), (50.0, -50.0, 98.0),
             (50.0, 50.0, 98.0), (-50.0, 50.0, 98.0)]
        )
        source = tool_surface.Surface.build_tin_from_points(
            "source", source_points
        )
        group = self._populate_closed_pad_group(
            ifc_file, interior_fill="from_surface", source_surface=source
        )
        composite = tool_grading.Grading.rebuild_group_surface(ifc_file, group)
        assert composite.triangles.shape[0] > 0
        assert group.ifc_interior_fill_id is not None

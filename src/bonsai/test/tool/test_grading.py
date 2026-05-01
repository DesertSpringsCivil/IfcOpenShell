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

import numpy as np
import pytest

import bonsai.tool.grading as tool_grading


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

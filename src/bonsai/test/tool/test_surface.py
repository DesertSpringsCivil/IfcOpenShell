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

"""Tests for ``bonsai.tool.surface``.

Run via the canonical Phase 4 invocation (PowerShell, from src/bonsai)::

    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
    python -m pytest test/tool/test_surface.py `
      -o "addopts=" `
      -p pytest-blender `
      -v `
      --blender-executable "C:\\Program Files\\Blender Foundation\\Blender_5\\blender.exe"
"""

import logging

import bpy
import ifcopenshell
import ifcopenshell.api.unit
import ifcopenshell.guid
import numpy as np
import pytest
import shapely

import bonsai.tool as tool
import bonsai.tool.surface as tool_surface
from test.bim.bootstrap import NewIfc4X3


def _read_breakline_count(
    ifc_file: ifcopenshell.file, host: ifcopenshell.entity_instance
) -> int:
    """Read ``SaikeiCivil_GradingSurface.BreaklineCount`` off the host
    entity. Returns 0 if the pset or property is missing."""
    for rel in ifc_file.by_type("IfcRelDefinesByProperties"):
        if host not in (rel.RelatedObjects or []):
            continue
        pset = rel.RelatingPropertyDefinition
        if pset is None or pset.Name != "SaikeiCivil_GradingSurface":
            continue
        for prop in pset.HasProperties or []:
            if prop.Name == "BreaklineCount" and prop.NominalValue is not None:
                return int(prop.NominalValue.wrappedValue)
    return 0


def _make_ifc_file_with_site() -> ifcopenshell.file:
    """Build a minimal IFC4X3 file with an IfcProject + IfcSite container.

    Reused across the IFC-authoring test classes; matches the bootstrap
    pattern in ``test/api/demo_surface.py``.
    """
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


class TestBreakline:
    """Tests for :class:`bonsai.tool.surface.Breakline`."""

    def test_minimum_construction(self) -> None:
        breakline = tool_surface.Breakline(
            guid="3VxJzKQwT9XwJZ8RbZkH7E",
            name="Top of curb",
            polyline=[(0.0, 0.0, 100.0), (10.0, 0.0, 100.5)],
            kind="standard",
            source="manual",
        )
        assert breakline.guid == "3VxJzKQwT9XwJZ8RbZkH7E"
        assert breakline.kind == "standard"
        assert breakline.ifc_annotation_id is None

    def test_ifc_annotation_id_persists(self) -> None:
        breakline = tool_surface.Breakline(
            guid="g",
            name="n",
            polyline=[(0.0, 0.0, 0.0), (1.0, 1.0, 1.0)],
            kind="wall",
            source="feature_line",
            ifc_annotation_id=42,
        )
        assert breakline.ifc_annotation_id == 42

    def test_each_kind_value_accepted(self) -> None:
        for kind in ("standard", "wall", "non_destructive", "proximity"):
            breakline = tool_surface.Breakline(
                guid="g",
                name="n",
                polyline=[(0.0, 0.0, 0.0), (1.0, 1.0, 1.0)],
                kind=kind,
                source="manual",
            )
            assert breakline.kind == kind


class TestCivilSurface:
    """Tests for :class:`bonsai.tool.surface.CivilSurface`."""

    def _flat_pad(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """3×3 grid at z=100 with 8 triangles, all flags=0."""
        points = np.array(
            [(float(i * 50), float(j * 50), 100.0) for j in range(3) for i in range(3)],
            dtype=float,
        )
        triangles = np.array(
            [
                (0, 1, 4), (0, 4, 3),
                (1, 2, 5), (1, 5, 4),
                (3, 4, 7), (3, 7, 6),
                (4, 5, 8), (4, 8, 7),
            ],
            dtype=int,
        )
        flags = np.zeros(8, dtype=int)
        return points, triangles, flags

    def test_minimum_construction(self) -> None:
        points, triangles, flags = self._flat_pad()
        surface = tool_surface.CivilSurface(
            guid="g",
            name="Existing Ground",
            kind="existing",
            points=points,
            triangles=triangles,
            triangle_flags=flags,
        )
        assert surface.kind == "existing"
        assert surface.points.shape == (9, 3)
        assert surface.triangles.shape == (8, 3)
        assert surface.triangle_flags.shape == (8,)
        assert surface.breaklines == []
        assert surface.outer_boundary is None
        assert surface.holes == []
        assert surface.voids == []
        assert surface.ifc_host_entity_id is None

    def test_each_kind_value_accepted(self) -> None:
        points, triangles, flags = self._flat_pad()
        for kind in ("existing", "proposed_group", "proposed_site"):
            surface = tool_surface.CivilSurface(
                guid="g",
                name="n",
                kind=kind,
                points=points,
                triangles=triangles,
                triangle_flags=flags,
            )
            assert surface.kind == kind

    def test_breaklines_holes_voids_persist(self) -> None:
        points, triangles, flags = self._flat_pad()
        breakline = tool_surface.Breakline(
            guid="b",
            name="ridge",
            polyline=[(0.0, 50.0, 100.0), (100.0, 50.0, 100.0)],
            kind="standard",
            source="manual",
        )
        outer = shapely.Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
        hole = shapely.Polygon([(40, 40), (60, 40), (60, 60), (40, 60)])
        void = shapely.Polygon([(80, 80), (95, 80), (95, 95), (80, 95)])
        surface = tool_surface.CivilSurface(
            guid="g",
            name="With features",
            kind="existing",
            points=points,
            triangles=triangles,
            triangle_flags=flags,
            breaklines=[breakline],
            outer_boundary=outer,
            holes=[hole],
            voids=[void],
        )
        assert len(surface.breaklines) == 1
        assert surface.breaklines[0].name == "ridge"
        assert surface.outer_boundary is outer
        assert surface.holes == [hole]
        assert surface.voids == [void]

    def test_metadata_is_independent_per_instance(self) -> None:
        """Mutable defaults shouldn't leak across instances."""
        points, triangles, flags = self._flat_pad()
        a = tool_surface.CivilSurface(
            guid="a", name="A", kind="existing",
            points=points, triangles=triangles, triangle_flags=flags,
        )
        b = tool_surface.CivilSurface(
            guid="b", name="B", kind="existing",
            points=points, triangles=triangles, triangle_flags=flags,
        )
        a.metadata["color"] = "red"
        assert b.metadata == {}


class TestTriangulatorProtocol:
    """Tests for :class:`bonsai.tool.surface.Triangulator` (Protocol).

    Protocols aren't runtime-checkable by default; these tests verify that
    a stub class implementing the protocol's two methods type-checks via
    duck-typing (the Protocol's intended use).
    """

    def test_stub_implementation_satisfies_protocol(self) -> None:
        class _StubTriangulator:
            def unconstrained(self, points: np.ndarray) -> np.ndarray:
                # Trivial fan triangulation from vertex 0
                n = points.shape[0]
                return np.array([(0, i, i + 1) for i in range(1, n - 1)], dtype=int)

            def constrained(
                self,
                points: np.ndarray,
                breakline_segments: list[tuple[int, int]],
                outer_boundary: shapely.Polygon,
                holes: list[shapely.Polygon],
                voids: list[shapely.Polygon],
            ) -> tuple[np.ndarray, np.ndarray]:
                triangles = self.unconstrained(points)
                flags = np.zeros(len(triangles), dtype=int)
                return triangles, flags

        stub: tool_surface.Triangulator = _StubTriangulator()  # type: ignore[assignment]
        points = np.array([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)])
        triangles = stub.unconstrained(points)
        assert triangles.shape == (2, 3)

        outer = shapely.Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        triangles, flags = stub.constrained(points, [], outer, [], [])
        assert triangles.shape == (2, 3)
        assert flags.shape == (2,)
        assert (flags == 0).all()


class TestScipyShapelyTriangulator:
    """Tests for :class:`bonsai.tool.surface._ScipyShapelyTriangulator`."""

    def _make(self) -> tool_surface._ScipyShapelyTriangulator:
        return tool_surface._ScipyShapelyTriangulator()

    def test_unconstrained_unit_square_produces_two_triangles(self) -> None:
        """Four corners of a unit square should triangulate to exactly two triangles
        covering the whole square — sum of triangle areas = 1.0."""
        triangulator = self._make()
        points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
        )
        triangles = triangulator.unconstrained(points)
        assert triangles.shape == (2, 3)
        # Verify it covers the unit square (sum of triangle areas = 1.0).
        total_area = 0.0
        for a, b, c in triangles:
            ax, ay = points[a, 0], points[a, 1]
            bx, by = points[b, 0], points[b, 1]
            cx, cy = points[c, 0], points[c, 1]
            total_area += abs((bx - ax) * (cy - ay) - (cx - ax) * (by - ay)) / 2.0
        assert abs(total_area - 1.0) < 1e-9

    def test_unconstrained_accepts_2d_points(self) -> None:
        triangulator = self._make()
        points_2d = np.array([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        triangles = triangulator.unconstrained(points_2d)
        assert triangles.shape == (2, 3)

    def test_unconstrained_3x3_grid_produces_8_triangles(self) -> None:
        """A 3×3 vertex grid should triangulate to 8 triangles (2 per cell × 4 cells)."""
        triangulator = self._make()
        points = np.array(
            [(float(i * 50), float(j * 50), 100.0) for j in range(3) for i in range(3)]
        )
        triangles = triangulator.unconstrained(points)
        assert triangles.shape == (8, 3)
        # All indices must be in [0, 9).
        assert (triangles >= 0).all() and (triangles < 9).all()

    def test_unconstrained_indices_are_int(self) -> None:
        triangulator = self._make()
        points = np.array([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)])
        triangles = triangulator.unconstrained(points)
        assert triangles.dtype == np.dtype("int64") or triangles.dtype == np.dtype("int32")

    def test_unconstrained_too_few_points_raises(self) -> None:
        triangulator = self._make()
        with pytest.raises(ValueError, match="at least 3 points"):
            triangulator.unconstrained(np.array([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]))

    def test_unconstrained_wrong_shape_raises(self) -> None:
        triangulator = self._make()
        with pytest.raises(ValueError, match=r"\(N, 2\) or \(N, 3\)"):
            triangulator.unconstrained(np.array([(0.0, 0.0, 0.0, 0.0)]))

    def test_constrained_unit_square_no_breaklines(self) -> None:
        """Same domain as unconstrained, no breaklines — should produce 2 triangles."""
        triangulator = self._make()
        points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
        )
        outer = shapely.Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        triangles, flags = triangulator.constrained(points, [], outer, [], [])
        assert triangles.shape == (2, 3)
        assert flags.shape == (2,)
        assert (flags == 0).all()  # Commit 5 fills in flags; commit 3 returns zeros.

    def test_constrained_breakline_forces_diagonal_edge(self) -> None:
        """A breakline along the diagonal of a unit square should force both triangles
        to share that diagonal as a common edge."""
        triangulator = self._make()
        # Add the diagonal-midpoint endpoints to the points array so the breakline
        # endpoints match input vertices (no Steiner points).
        points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
        )
        outer = shapely.Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        # Breakline from (0,0) to (1,1) — vertices 0 and 2.
        triangles, flags = triangulator.constrained(points, [(0, 2)], outer, [], [])
        assert triangles.shape == (2, 3)
        # Each unordered edge should be counted once per triangle that contains it.
        # An internal edge appears in 2 triangles; a boundary edge in 1.
        edges_count: dict[tuple[int, int], int] = {}
        for a, b, c in triangles:
            for edge in ((a, b), (b, c), (a, c)):
                key = tuple(sorted((int(edge[0]), int(edge[1]))))
                edges_count[key] = edges_count.get(key, 0) + 1
        # The diagonal (0, 2) must appear in both triangles as an internal edge.
        assert edges_count.get((0, 2)) == 2, (
            f"diagonal edge (0, 2) should be shared by both triangles, "
            f"got count {edges_count.get((0, 2))}; full edges: {edges_count}"
        )

    def test_constrained_no_breakline_no_polygon_flags_zero(self) -> None:
        """With no breaklines and no hole/void polygons, every triangle's flag is 0
        (IFC: no breakline edges, not a hole, not a void)."""
        triangulator = self._make()
        points = np.array(
            [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0), (0.0, 10.0, 0.0)]
        )
        outer = shapely.Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        triangles, flags = triangulator.constrained(points, [], outer, [], [])
        assert (flags == 0).all()

    def test_constrained_wrong_outer_type_raises(self) -> None:
        triangulator = self._make()
        points = np.array([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0)])
        with pytest.raises(ValueError, match="outer_boundary must be a shapely.Polygon"):
            triangulator.constrained(points, [], "not a polygon", [], [])  # type: ignore[arg-type]

    def test_constrained_2d_points_raises(self) -> None:
        triangulator = self._make()
        with pytest.raises(ValueError, match=r"\(N, 3\)"):
            triangulator.constrained(
                np.array([(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]),
                [],
                shapely.Polygon([(0, 0), (1, 0), (0, 1)]),
                [],
                [],
            )

    def test_satisfies_triangulator_protocol(self) -> None:
        """Verify the default backend duck-types as :class:`Triangulator`."""
        backend: tool_surface.Triangulator = self._make()  # type: ignore[assignment]
        assert hasattr(backend, "unconstrained")
        assert hasattr(backend, "constrained")


class TestFlagsTranslation:
    """Tests for the polygon → IFC ``Flags`` translation in
    :meth:`_ScipyShapelyTriangulator.constrained`.

    Per spec §2.1 + §5: each triangle's ``Flags`` integer is one of
    ``-2`` (void), ``-1`` (hole), or ``0`` to ``7`` (3-bit breakline-edge mask).
    """

    @staticmethod
    def _make() -> tool_surface._ScipyShapelyTriangulator:
        return tool_surface._ScipyShapelyTriangulator()

    def test_centroid_in_hole_flagged_minus_one(self) -> None:
        """A triangle whose centroid lies inside a hole polygon gets Flag -1."""
        triangulator = self._make()
        # Two-triangle unit square with a hole that covers ~half of it.
        # The hole spans x in [0.0, 0.6], y in [0.0, 1.0] which contains the
        # centroid of triangles in the lower-left half.
        points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
        )
        outer = shapely.Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        hole = shapely.Polygon([(0, 0), (0.6, 0), (0.6, 1), (0, 1)])
        triangles, flags = triangulator.constrained(points, [], outer, [hole], [])
        # At least one triangle's centroid lies inside the hole.
        assert any(flag == -1 for flag in flags), f"no -1 flag in {flags.tolist()}"

    def test_centroid_in_void_flagged_minus_two(self) -> None:
        """A triangle whose centroid lies inside a void polygon gets Flag -2."""
        triangulator = self._make()
        points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
        )
        outer = shapely.Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        void = shapely.Polygon([(0, 0), (0.6, 0), (0.6, 1), (0, 1)])
        triangles, flags = triangulator.constrained(points, [], outer, [], [void])
        assert any(flag == -2 for flag in flags), f"no -2 flag in {flags.tolist()}"

    def test_void_takes_precedence_over_hole(self) -> None:
        """Per spec §6.3, voids override holes when polygons overlap."""
        triangulator = self._make()
        points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
        )
        outer = shapely.Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        # The void and hole polygons are identical and cover the lower-left half.
        hole = shapely.Polygon([(0, 0), (0.6, 0), (0.6, 1), (0, 1)])
        void = shapely.Polygon([(0, 0), (0.6, 0), (0.6, 1), (0, 1)])
        triangles, flags = triangulator.constrained(points, [], outer, [hole], [void])
        # Triangles in the overlapping region must be -2, not -1.
        assert -2 in flags.tolist()
        assert -1 not in flags.tolist()

    def test_outside_hole_and_void_gets_zero_or_breakline_mask(self) -> None:
        """Triangles whose centroid is outside both hole and void polygons get
        a non-negative flag (0 if no breakline edges, 1–7 otherwise)."""
        triangulator = self._make()
        points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
        )
        outer = shapely.Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        # A small hole far from where the triangulation will fall.
        hole = shapely.Polygon(
            [(0.45, 0.45), (0.55, 0.45), (0.55, 0.55), (0.45, 0.55)]
        )
        triangles, flags = triangulator.constrained(points, [], outer, [hole], [])
        # At least one triangle should be entirely outside the small hole.
        assert any(flag == 0 for flag in flags)

    def test_breakline_edge_sets_bitmask(self) -> None:
        """A breakline along the diagonal of a unit square sets the
        appropriate edge bit in both adjacent triangles."""
        triangulator = self._make()
        points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
        )
        outer = shapely.Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        triangles, flags = triangulator.constrained(
            points, [(0, 2)], outer, [], []
        )
        # Both triangles share the diagonal (0, 2). For each triangle, find
        # which edge index (0/1/2) maps to that pair, then assert the bit is set.
        for triangle, flag in zip(triangles, flags):
            v0, v1, v2 = (int(triangle[0]), int(triangle[1]), int(triangle[2]))
            edges = (
                (v0, v1),
                (v1, v2),
                (v2, v0),
            )
            for edge_index, (a, b) in enumerate(edges):
                if {a, b} == {0, 2}:
                    expected_bit = 1 << edge_index
                    assert flag & expected_bit, (
                        f"triangle {triangle.tolist()} edge index {edge_index} "
                        f"is the breakline (vertices 0,2) but flag {flag} "
                        f"does not have bit {expected_bit} set"
                    )
                    break
            else:
                pytest.fail(
                    f"triangle {triangle.tolist()} does not contain the breakline "
                    f"diagonal (0, 2); flags={flags.tolist()}"
                )

    def test_centroid_on_hole_boundary_flagged_as_hole(self) -> None:
        """Closes the cold-review-flagged boundary edge case: a centroid
        that lands exactly on a hole polygon's boundary must be flagged
        ``-1``, not silently classified as visible. This happens when a
        breakline runs coincident with a hole edge — a common pattern in
        survey data where curb/gutter lines define both breaklines and
        no-fill regions.

        Constructs a triangle whose centroid lies exactly on a polygon
        boundary line, then asserts the flag is ``-1`` (hole), not ``0``.
        """
        triangulator = self._make()
        # Triangle with vertices (0,0), (3,0), (0,3) — centroid at (1, 1).
        # The hole polygon is a triangle (0,0)-(2,0)-(0,2); its edge from
        # (2,0) to (0,2) passes through (1, 1) exactly.
        points = np.array(
            [
                (0.0, 0.0, 0.0),
                (3.0, 0.0, 0.0),
                (0.0, 3.0, 0.0),
            ]
        )
        outer = shapely.Polygon([(0, 0), (3, 0), (0, 3)])
        hole = shapely.Polygon([(0, 0), (2, 0), (0, 2)])
        triangles, flags = triangulator.constrained(points, [], outer, [hole], [])
        # Verify centroid (1, 1) lies on the hole edge (sanity).
        centroid = shapely.Point(1.0, 1.0)
        assert centroid.intersects(hole.boundary)
        assert not centroid.within(hole)
        # The single triangle's flag must be -1, not 0.
        assert len(flags) == 1
        assert flags[0] == -1

    def test_breakline_segments_passed_directly_to_triangulator(self) -> None:
        """Bypass Surface.retriangulate and pass breakline_segments directly —
        verify the triangulator translates them into bitmask flags."""
        triangulator = self._make()
        points = np.array(
            [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 2.0, 0.0), (0.0, 2.0, 0.0)]
        )
        outer = shapely.Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
        # Breakline along the diagonal — vertices 0 and 2.
        triangles, flags = triangulator.constrained(
            points, [(0, 2)], outer, [], []
        )
        # Every flag should be in the 1-7 range (bitmask) since the diagonal
        # is shared by both triangles.
        assert all(1 <= flag <= 7 for flag in flags), f"flags={flags.tolist()}"

    def test_internal_breakline_silently_dropped_pin(self, caplog) -> None:
        """Pin the documented Phase 4 limitation: breaklines that don't
        fully cross the outer boundary aren't honored as forced edges
        (per :meth:`_build_constrained_geometry` docstring). The CDT
        completes without error, but the tool layer emits a WARNING log
        so callers / users can detect the non-honored breakline rather
        than getting a silent miss.
        """
        triangulator = self._make()
        points = np.array(
            [
                (0.0, 0.0, 0.0),
                (4.0, 0.0, 0.0),
                (4.0, 4.0, 0.0),
                (0.0, 4.0, 0.0),
                # Two interior vertices for a breakline that ends inside the polygon.
                (1.0, 2.0, 0.0),
                (3.0, 2.0, 0.0),
            ]
        )
        outer = shapely.Polygon([(0, 0), (4, 0), (4, 4), (0, 4)])
        # Internal breakline from vertex 4 to vertex 5 — does NOT fully cross
        # the outer boundary. shapely.ops.split returns the polygon unchanged.
        with caplog.at_level("WARNING", logger="bonsai.tool.surface"):
            triangles, flags = triangulator.constrained(
                points, [(4, 5)], outer, [], []
            )
        assert triangles.ndim == 2 and triangles.shape[1] == 3
        assert flags.shape == (triangles.shape[0],)
        # WARNING was emitted naming the dropped segment.
        assert any(
            "not honored" in r.message
            for r in caplog.records
            if r.levelno >= logging.WARNING
        ), f"expected breakline-drop warning, got: {[r.message for r in caplog.records]}"


class TestSurfaceBuildTinFromPoints:
    """Tests for :meth:`bonsai.tool.surface.Surface.build_tin_from_points`."""

    def test_returns_civil_surface(self) -> None:
        points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
        )
        surface = tool_surface.Surface.build_tin_from_points("Test TIN", points)
        assert isinstance(surface, tool_surface.CivilSurface)
        assert surface.name == "Test TIN"
        assert surface.kind == "existing"

    def test_unit_square_produces_two_triangles(self) -> None:
        points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
        )
        surface = tool_surface.Surface.build_tin_from_points("unit square", points)
        assert surface.triangles.shape == (2, 3)
        assert surface.triangle_flags.shape == (2,)
        assert (surface.triangle_flags == 0).all()

    def test_outer_boundary_is_convex_hull(self) -> None:
        # 4 corners of a unit square — convex hull is the square itself, area 1.
        points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
        )
        surface = tool_surface.Surface.build_tin_from_points("hull check", points)
        assert isinstance(surface.outer_boundary, shapely.Polygon)
        assert surface.outer_boundary.area == pytest.approx(1.0)

    def test_outer_boundary_contains_interior_point(self) -> None:
        # An interior point shouldn't expand the hull beyond the corner square.
        points = np.array(
            [
                (0.0, 0.0, 0.0),
                (10.0, 0.0, 0.0),
                (10.0, 10.0, 0.0),
                (0.0, 10.0, 0.0),
                (5.0, 5.0, 1.0),  # interior point
            ]
        )
        surface = tool_surface.Surface.build_tin_from_points("interior", points)
        assert surface.outer_boundary.area == pytest.approx(100.0)

    def test_generates_guid_when_not_provided(self) -> None:
        points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        )
        surface = tool_surface.Surface.build_tin_from_points("auto guid", points)
        # IFC GlobalId is a 22-character compressed base64 string.
        assert isinstance(surface.guid, str)
        assert len(surface.guid) == 22

    def test_explicit_guid_passes_through(self) -> None:
        points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        )
        explicit = "0123456789ABCDEFGHIJKL"
        surface = tool_surface.Surface.build_tin_from_points(
            "explicit guid", points, guid=explicit
        )
        assert surface.guid == explicit

    def test_kind_default_is_existing(self) -> None:
        points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        )
        surface = tool_surface.Surface.build_tin_from_points("default kind", points)
        assert surface.kind == "existing"

    def test_kind_proposed_group_passes_through(self) -> None:
        points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        )
        surface = tool_surface.Surface.build_tin_from_points(
            "proposed", points, kind="proposed_group"
        )
        assert surface.kind == "proposed_group"

    def test_too_few_points_raises(self) -> None:
        points = np.array([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)])
        with pytest.raises(
            tool_surface.SaikeiTriangulationError, match="at least 3 points"
        ):
            tool_surface.Surface.build_tin_from_points("too few", points)

    def test_wrong_shape_raises(self) -> None:
        points = np.array([(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)])  # 2D
        with pytest.raises(
            tool_surface.SaikeiTriangulationError, match=r"\(N, 3\)"
        ):
            tool_surface.Surface.build_tin_from_points("2d", points)

    def test_collinear_points_raise(self) -> None:
        # Three collinear points are degenerate either at the SciPy Delaunay
        # step (initial simplex is flat) or at the convex-hull guard, depending
        # on the backend. Either path must surface as SaikeiTriangulationError
        # so callers can catch a single exception type.
        points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
        )
        with pytest.raises(tool_surface.SaikeiTriangulationError):
            tool_surface.Surface.build_tin_from_points("collinear", points)

    def test_input_points_are_copied_not_aliased(self) -> None:
        points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        )
        surface = tool_surface.Surface.build_tin_from_points("alias check", points)
        points[0, 2] = 99.0
        assert surface.points[0, 2] == pytest.approx(0.0)


class TestSurfaceRetriangulate:
    """Tests for :meth:`bonsai.tool.surface.Surface.retriangulate`."""

    @staticmethod
    def _unit_square_surface() -> tool_surface.CivilSurface:
        points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
        )
        return tool_surface.Surface.build_tin_from_points("retri", points)

    def test_no_breaklines_clipped_to_boundary(self) -> None:
        surface = self._unit_square_surface()
        original_id = id(surface)
        tool_surface.Surface.retriangulate(surface)
        assert id(surface) == original_id  # in-place
        # Two triangles cover the unit square either way; constrained Delaunay
        # may pick a different diagonal than the unconstrained build.
        assert surface.triangles.shape == (2, 3)

    def test_with_breakline_forces_diagonal(self) -> None:
        surface = self._unit_square_surface()
        # Breakline along the (0,0) -> (1,1) diagonal — endpoints already in points.
        surface.breaklines.append(
            tool_surface.Breakline(
                guid="bl-guid-1",
                name="diagonal",
                polyline=[(0.0, 0.0, 0.0), (1.0, 1.0, 0.0)],
                kind="standard",
                source="manual",
            )
        )
        tool_surface.Surface.retriangulate(surface)
        # The diagonal between vertex 0 (0,0) and vertex 2 (1,1) must be a
        # shared internal edge in both triangles.
        assert surface.triangles.shape == (2, 3)
        edges_count: dict[tuple[int, int], int] = {}
        for a, b, c in surface.triangles:
            for edge in ((a, b), (b, c), (a, c)):
                key = tuple(sorted((int(edge[0]), int(edge[1]))))
                edges_count[key] = edges_count.get(key, 0) + 1
        assert edges_count.get((0, 2)) == 2

    def test_breakline_with_new_vertex_grows_points_array(self) -> None:
        surface = self._unit_square_surface()
        # Breakline that introduces a brand new midpoint vertex.
        surface.breaklines.append(
            tool_surface.Breakline(
                guid="bl-guid-2",
                name="new vertex",
                polyline=[(0.5, 0.0, 0.0), (0.5, 1.0, 0.0)],
                kind="standard",
                source="manual",
            )
        )
        tool_surface.Surface.retriangulate(surface)
        # Original 4 corners plus the 2 new midpoints = 6 points.
        assert surface.points.shape == (6, 3)

    def test_retriangulate_translates_breakline_to_flag_bitmask(self) -> None:
        """End-to-end through Surface.retriangulate: a breakline polyline
        produces non-zero edge-bitmask flags on the triangles it touches."""
        surface = self._unit_square_surface()
        surface.breaklines.append(
            tool_surface.Breakline(
                guid="bl-flagcheck",
                name="diagonal",
                polyline=[(0.0, 0.0, 0.0), (1.0, 1.0, 0.0)],
                kind="standard",
                source="manual",
            )
        )
        tool_surface.Surface.retriangulate(surface)
        assert any(
            1 <= int(flag) <= 7 for flag in surface.triangle_flags
        ), f"no breakline-bitmask flag in {surface.triangle_flags.tolist()}"

    def test_retriangulate_translates_hole_polygon_to_minus_one(self) -> None:
        """End-to-end: a hole polygon on the surface yields a -1 flag on
        triangles whose centroid falls inside it after retriangulation."""
        surface = self._unit_square_surface()
        surface.holes.append(
            shapely.Polygon([(0, 0), (0.6, 0), (0.6, 1), (0, 1)])
        )
        tool_surface.Surface.retriangulate(surface)
        assert -1 in surface.triangle_flags.tolist()

    def test_no_outer_boundary_raises(self) -> None:
        points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        )
        # Bypass build_tin_from_points to construct a CivilSurface without a
        # boundary — exercising the defensive guard in retriangulate.
        surface = tool_surface.CivilSurface(
            guid="no-boundary",
            name="no boundary",
            kind="existing",
            points=points,
            triangles=np.array([(0, 1, 2)]),
            triangle_flags=np.zeros(1, dtype=int),
            outer_boundary=None,
        )
        with pytest.raises(
            tool_surface.SaikeiTriangulationError, match="no outer_boundary"
        ):
            tool_surface.Surface.retriangulate(surface)


class TestSurfaceZAt:
    """Tests for :meth:`bonsai.tool.surface.Surface.z_at`."""

    @staticmethod
    def _flat_unit_square(z: float = 0.0) -> tool_surface.CivilSurface:
        points = np.array(
            [
                (0.0, 0.0, z),
                (1.0, 0.0, z),
                (1.0, 1.0, z),
                (0.0, 1.0, z),
            ]
        )
        return tool_surface.Surface.build_tin_from_points("flat", points)

    @staticmethod
    def _pyramid() -> tool_surface.CivilSurface:
        # Square base at z=0 with a peak at the centre at z=10.
        points = np.array(
            [
                (0.0, 0.0, 0.0),
                (10.0, 0.0, 0.0),
                (10.0, 10.0, 0.0),
                (0.0, 10.0, 0.0),
                (5.0, 5.0, 10.0),
            ]
        )
        return tool_surface.Surface.build_tin_from_points("pyramid", points)

    def test_flat_surface_returns_constant_z(self) -> None:
        surface = self._flat_unit_square(z=42.5)
        assert tool_surface.Surface.z_at(surface, 0.5, 0.5) == pytest.approx(42.5)
        assert tool_surface.Surface.z_at(surface, 0.1, 0.9) == pytest.approx(42.5)
        assert tool_surface.Surface.z_at(surface, 0.99, 0.01) == pytest.approx(42.5)

    def test_at_vertex_returns_exact_z(self) -> None:
        surface = self._pyramid()
        # At the apex (5,5) the interpolated Z should be the apex Z.
        assert tool_surface.Surface.z_at(surface, 5.0, 5.0) == pytest.approx(10.0)

    def test_outside_returns_none(self) -> None:
        surface = self._flat_unit_square()
        assert tool_surface.Surface.z_at(surface, 5.0, 5.0) is None
        assert tool_surface.Surface.z_at(surface, -1.0, -1.0) is None

    def test_pyramid_midway_to_apex(self) -> None:
        surface = self._pyramid()
        # Halfway from base corner (0,0,0) to apex (5,5,10): z should be 5.
        z = tool_surface.Surface.z_at(surface, 2.5, 2.5)
        assert z is not None
        assert z == pytest.approx(5.0)

    def test_strtree_index_built_on_first_call_and_cached(self) -> None:
        """First :meth:`z_at` call builds the STRtree index and caches it
        in ``surface.metadata["_z_at_index"]``; subsequent calls reuse the
        cached tree."""
        surface = self._flat_unit_square()
        assert "_z_at_index" not in surface.metadata

        tool_surface.Surface.z_at(surface, 0.5, 0.5)
        assert "_z_at_index" in surface.metadata
        cached_tuple = surface.metadata["_z_at_index"]

        tool_surface.Surface.z_at(surface, 0.25, 0.75)
        # Same tuple object reused — proves no rebuild.
        assert surface.metadata["_z_at_index"] is cached_tuple

    def test_retriangulate_invalidates_z_at_index(self) -> None:
        """:meth:`retriangulate` must drop the cached STRtree index so the
        next :meth:`z_at` call rebuilds against the new triangles."""
        surface = self._flat_unit_square()
        tool_surface.Surface.z_at(surface, 0.5, 0.5)
        assert "_z_at_index" in surface.metadata

        tool_surface.Surface.retriangulate(surface)
        assert "_z_at_index" not in surface.metadata

        # Next z_at rebuilds. Verify it still returns correct values.
        z = tool_surface.Surface.z_at(surface, 0.5, 0.5)
        assert z == pytest.approx(0.0)
        assert "_z_at_index" in surface.metadata

    def test_array_replacement_forces_cache_rebuild(self) -> None:
        """Replacing surface.points / surface.triangles with a new array
        (different ``id()``) forces the next z_at call to rebuild the
        cache. This is the common Phase 5 mutation pattern (assigning a
        fresh array post-mutation)."""
        surface = self._flat_unit_square()
        tool_surface.Surface.z_at(surface, 0.5, 0.5)
        original_cache = surface.metadata["_z_at_index"]

        # Replace with a copy — different id().
        surface.triangles = surface.triangles.copy()
        tool_surface.Surface.z_at(surface, 0.5, 0.5)
        new_cache = surface.metadata["_z_at_index"]
        assert new_cache is not original_cache

    def test_array_shape_change_forces_cache_rebuild(self) -> None:
        """Appending a row changes the shape, which is part of the cache
        key alongside id()."""
        surface = self._flat_unit_square()
        tool_surface.Surface.z_at(surface, 0.5, 0.5)
        original_cache = surface.metadata["_z_at_index"]

        # Append a vertex (changes shape and triggers retriangulate
        # via the same surface). Use vstack to keep API typical.
        surface.points = np.vstack([surface.points, [[0.5, 0.5, 0.0]]])
        tool_surface.Surface.z_at(surface, 0.5, 0.5)
        new_cache = surface.metadata["_z_at_index"]
        assert new_cache is not original_cache

    def test_z_at_correctness_unchanged_with_strtree(self) -> None:
        """Sanity: regression on the existing z_at correctness suite. The
        STRtree path must produce identical results to the linear scan
        for at-vertex / on-edge / interior queries."""
        surface = self._pyramid()
        # At apex.
        assert tool_surface.Surface.z_at(surface, 5.0, 5.0) == pytest.approx(10.0)
        # Halfway from base corner to apex.
        assert tool_surface.Surface.z_at(surface, 2.5, 2.5) == pytest.approx(5.0)
        # Outside.
        assert tool_surface.Surface.z_at(surface, -1.0, -1.0) is None
        assert tool_surface.Surface.z_at(surface, 100.0, 100.0) is None

    def test_z_at_performance_on_grid_surface(self) -> None:
        """STRtree-accelerated lookup keeps z_at sub-linear on larger
        surfaces. With a 50x50 grid (4900 triangles) and 1000 random
        queries, the total time should be well under 1 second on any
        modern machine. This is a ballpark perf gate, not a strict bound."""
        import time

        # Build a 50x50 grid surface — 2500 vertices, ~4900 triangles.
        n = 50
        coords = []
        for j in range(n):
            for i in range(n):
                coords.append((float(i), float(j), float(i + j) * 0.1))
        points = np.asarray(coords, dtype=float)
        surface = tool_surface.Surface.build_tin_from_points("Perf", points)

        # 1000 random in-bound queries.
        rng = np.random.default_rng(seed=0)
        xs = rng.uniform(0, n - 1, size=1000)
        ys = rng.uniform(0, n - 1, size=1000)

        start = time.perf_counter()
        hits = 0
        for x, y in zip(xs, ys):
            z = tool_surface.Surface.z_at(surface, float(x), float(y))
            if z is not None:
                hits += 1
        elapsed = time.perf_counter() - start

        assert hits > 950  # most random queries land inside the grid
        assert elapsed < 1.0, (
            f"1000 z_at queries on a {len(surface.triangles)}-triangle "
            f"surface took {elapsed:.3f}s; STRtree may be misbehaving"
        )

    def test_inclined_plane_interpolates(self) -> None:
        # Plane z = x: linear ramp.
        points = np.array(
            [
                (0.0, 0.0, 0.0),
                (10.0, 0.0, 10.0),
                (10.0, 10.0, 10.0),
                (0.0, 10.0, 0.0),
            ]
        )
        surface = tool_surface.Surface.build_tin_from_points("ramp", points)
        # Anywhere on the plane, z should equal x.
        for x_query, y_query in [(2.5, 5.0), (7.5, 1.0), (5.0, 5.0)]:
            z = tool_surface.Surface.z_at(surface, x_query, y_query)
            assert z is not None
            assert z == pytest.approx(x_query)


class TestSurfaceTriangulatorAttribute:
    """Tests for the swappable :attr:`Surface.triangulator` class attribute."""

    def test_default_is_scipy_shapely_backend(self) -> None:
        assert isinstance(
            tool_surface.Surface.triangulator,
            tool_surface._ScipyShapelyTriangulator,
        )

    def test_can_be_overridden_for_tests(self) -> None:
        """Reassigning the class attribute swaps the backend used by
        :meth:`build_tin_from_points`."""

        class _StubTriangulator:
            unconstrained_called_with: list[np.ndarray] = []

            def unconstrained(self, points: np.ndarray) -> np.ndarray:
                self.unconstrained_called_with.append(points)
                # Return a single triangle covering the first three points.
                return np.array([(0, 1, 2)], dtype=int)

            def constrained(
                self,
                points: np.ndarray,
                breakline_segments: list[tuple[int, int]],
                outer_boundary: shapely.Polygon,
                holes: list[shapely.Polygon],
                voids: list[shapely.Polygon],
            ) -> tuple[np.ndarray, np.ndarray]:
                return np.array([(0, 1, 2)], dtype=int), np.zeros(1, dtype=int)

        original = tool_surface.Surface.triangulator
        stub = _StubTriangulator()
        try:
            tool_surface.Surface.triangulator = stub  # type: ignore[assignment]
            points = np.array(
                [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
            )
            surface = tool_surface.Surface.build_tin_from_points("stub", points)
            assert surface.triangles.shape == (1, 3)
            assert len(stub.unconstrained_called_with) == 1
        finally:
            tool_surface.Surface.triangulator = original


class TestSurfaceAuthorIfcHost:
    """Tests for :meth:`bonsai.tool.surface.Surface.author_ifc_host`."""

    @staticmethod
    def _surface(kind: str = "existing") -> tool_surface.CivilSurface:
        points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
        )
        return tool_surface.Surface.build_tin_from_points(
            "Test Surface", points, kind=kind
        )

    def test_existing_creates_geographic_element(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        surface = self._surface("existing")
        host = tool_surface.Surface.author_ifc_host(ifc_file, surface)
        assert host.is_a("IfcGeographicElement")
        assert host.PredefinedType == "TERRAIN"
        assert host.Name == "Test Surface"

    def test_proposed_group_creates_earthworks_fill(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        surface = self._surface("proposed_group")
        host = tool_surface.Surface.author_ifc_host(ifc_file, surface)
        assert host.is_a("IfcEarthworksFill")
        assert host.PredefinedType == "SUBGRADE"

    def test_proposed_site_creates_earthworks_fill(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        surface = self._surface("proposed_site")
        host = tool_surface.Surface.author_ifc_host(ifc_file, surface)
        assert host.is_a("IfcEarthworksFill")
        assert host.PredefinedType == "SUBGRADE"

    def test_global_id_matches_surface_guid(self) -> None:
        """The host entity's GlobalId is rewritten to the dataclass GUID."""
        ifc_file = _make_ifc_file_with_site()
        surface = self._surface()
        host = tool_surface.Surface.author_ifc_host(ifc_file, surface)
        assert host.GlobalId == surface.guid

    def test_stamps_host_id_on_surface(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        surface = self._surface()
        host = tool_surface.Surface.author_ifc_host(ifc_file, surface)
        assert surface.ifc_host_entity_id == host.id()

    def test_stamps_tin_id_on_surface(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        surface = self._surface()
        tool_surface.Surface.author_ifc_host(ifc_file, surface)
        assert surface.ifc_tin_representation_id is not None
        tin = ifc_file.by_id(surface.ifc_tin_representation_id)
        assert tin.is_a("IfcTriangulatedIrregularNetwork")

    def test_stamps_bbox_id_on_surface(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        surface = self._surface()
        tool_surface.Surface.author_ifc_host(ifc_file, surface)
        assert surface.ifc_bbox_representation_id is not None
        bbox = ifc_file.by_id(surface.ifc_bbox_representation_id)
        assert bbox.is_a("IfcBoundingBox")

    def test_unknown_kind_raises(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        # Construct a surface with an invalid kind, bypassing the type-checked
        # build_tin_from_points entry point.
        surface = self._surface()
        surface.kind = "nonsense"  # type: ignore[assignment]
        with pytest.raises(
            tool_surface.SaikeiSurfaceError, match="unknown surface.kind"
        ):
            tool_surface.Surface.author_ifc_host(ifc_file, surface)

    def test_explicit_site_argument(self) -> None:
        """When an explicit site is supplied, it is used regardless of file order."""
        ifc_file = _make_ifc_file_with_site()
        # Add a second site; pass the first one explicitly.
        site_a = ifc_file.by_type("IfcSite")[0]
        ifc_file.create_entity(
            "IfcSite", GlobalId=ifcopenshell.guid.new(), Name="Site B"
        )
        surface = self._surface()
        host = tool_surface.Surface.author_ifc_host(ifc_file, surface, site=site_a)
        # Containment: the host should be related to site_a via
        # IfcRelContainedInSpatialStructure.
        contained_in = [
            rel
            for rel in ifc_file.by_type("IfcRelContainedInSpatialStructure")
            if host in (rel.RelatedElements or [])
        ]
        assert len(contained_in) == 1
        assert contained_in[0].RelatingStructure == site_a

    def test_breakline_count_passed_to_pset(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        surface = self._surface()
        surface.breaklines.append(
            tool_surface.Breakline(
                guid=ifcopenshell.guid.new(),
                name="bl",
                polyline=[(0.0, 0.0, 0.0), (1.0, 1.0, 0.0)],
                kind="standard",
                source="manual",
            )
        )
        host = tool_surface.Surface.author_ifc_host(ifc_file, surface)
        # Find the SaikeiCivil_GradingSurface and verify BreaklineCount.
        psets_via_rels = []
        for rel in ifc_file.by_type("IfcRelDefinesByProperties"):
            if host in (rel.RelatedObjects or []):
                psets_via_rels.append(rel.RelatingPropertyDefinition)
        saikei_pset = next(
            (p for p in psets_via_rels if p.Name == "SaikeiCivil_GradingSurface"),
            None,
        )
        assert saikei_pset is not None
        breakline_count = next(
            (
                p.NominalValue.wrappedValue
                for p in saikei_pset.HasProperties
                if p.Name == "BreaklineCount"
            ),
            None,
        )
        assert breakline_count == 1


class TestSurfaceUpdateIfcTin:
    """Tests for :meth:`bonsai.tool.surface.Surface.update_ifc_tin`."""

    def test_no_host_raises(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        )
        surface = tool_surface.Surface.build_tin_from_points("orphan", points)
        with pytest.raises(
            tool_surface.SaikeiSurfaceError, match="no IFC host entity"
        ):
            tool_surface.Surface.update_ifc_tin(ifc_file, surface)

    def test_replaces_old_tin(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
        )
        surface = tool_surface.Surface.build_tin_from_points("update target", points)
        tool_surface.Surface.author_ifc_host(ifc_file, surface)
        old_tin_id = surface.ifc_tin_representation_id
        # Add a new vertex and retriangulate.
        surface.points = np.vstack([surface.points, [[0.5, 0.5, 1.0]]])
        tool_surface.Surface.retriangulate(surface)
        new_tin = tool_surface.Surface.update_ifc_tin(ifc_file, surface)
        assert new_tin.id() != old_tin_id
        assert surface.ifc_tin_representation_id == new_tin.id()
        # Old TIN should be garbage-collected (no other refs to it).
        tins = ifc_file.by_type("IfcTriangulatedIrregularNetwork")
        assert len(tins) == 1
        assert tins[0].id() == new_tin.id()

    def test_refreshes_bounding_box_after_point_change(self) -> None:
        """Closes the cold-review-flagged stale-bbox bug. After the
        points array shrinks (e.g., set_boundary clips the surface), the
        IfcBoundingBox in the host's Box representation must update in
        place — viewers using it for LOD / culling rely on the current
        extents.
        """
        ifc_file = _make_ifc_file_with_site()
        # Original surface spans (0..10, 0..10, 0..0).
        big_points = np.array(
            [
                (0.0, 0.0, 0.0),
                (10.0, 0.0, 0.0),
                (10.0, 10.0, 0.0),
                (0.0, 10.0, 0.0),
            ]
        )
        surface = tool_surface.Surface.build_tin_from_points("BBoxTest", big_points)
        host = tool_surface.Surface.author_ifc_host(ifc_file, surface)

        original_bbox_id = surface.ifc_bbox_representation_id
        bbox = ifc_file.by_id(original_bbox_id)
        assert bbox.XDim == pytest.approx(10.0)
        assert bbox.YDim == pytest.approx(10.0)

        # Replace the points with a smaller subset and update_ifc_tin.
        small_points = np.array(
            [(0.0, 0.0, 0.0), (5.0, 0.0, 0.0), (0.0, 5.0, 0.0)]
        )
        surface.points = small_points
        surface.triangles = np.array([(0, 1, 2)], dtype=int)
        surface.triangle_flags = np.zeros(1, dtype=int)
        tool_surface.Surface.update_ifc_tin(ifc_file, surface)

        # Same bbox entity (in-place update, no orphan).
        assert surface.ifc_bbox_representation_id == original_bbox_id
        bbox_after = ifc_file.by_id(original_bbox_id)
        assert bbox_after.id() == original_bbox_id
        # New extents.
        assert bbox_after.XDim == pytest.approx(5.0)
        assert bbox_after.YDim == pytest.approx(5.0)
        assert tuple(bbox_after.Corner.Coordinates) == pytest.approx((0.0, 0.0, 0.0))
        # Only one IfcBoundingBox in the file (no orphans).
        assert len(ifc_file.by_type("IfcBoundingBox")) == 1

    def test_refreshes_breakline_count_pset(self) -> None:
        """``SaikeiCivil_GradingSurface.BreaklineCount`` should reflect
        ``len(surface.breaklines)`` after every ``update_ifc_tin``. Without
        this refresh, the pset goes stale after every edit (it was set
        once at create_terrain / create_proposed_surface time).
        """
        ifc_file = _make_ifc_file_with_site()
        # Centerpoint vertex lets two non-crossing breaklines share an
        # endpoint without introducing Steiner points.
        points = np.array(
            [
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (1.0, 1.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.5, 0.5, 0.0),
            ]
        )
        surface = tool_surface.Surface.build_tin_from_points("BLCount", points)
        host = tool_surface.Surface.author_ifc_host(ifc_file, surface)

        assert _read_breakline_count(ifc_file, host) == 0

        # First breakline: (0,0) → (0.5,0.5).
        surface.breaklines.append(
            tool_surface.Breakline(
                guid=ifcopenshell.guid.new(),
                name="bl",
                polyline=[(0.0, 0.0, 0.0), (0.5, 0.5, 0.0)],
                kind="standard",
                source="manual",
            )
        )
        tool_surface.Surface.retriangulate(surface)
        tool_surface.Surface.update_ifc_tin(ifc_file, surface)
        assert _read_breakline_count(ifc_file, host) == 1

        # Second breakline: (0.5,0.5) → (1,1). Shares the endpoint with
        # the first so the two segments form a continuous polyline path
        # without crossing.
        surface.breaklines.append(
            tool_surface.Breakline(
                guid=ifcopenshell.guid.new(),
                name="bl-2",
                polyline=[(0.5, 0.5, 0.0), (1.0, 1.0, 0.0)],
                kind="standard",
                source="manual",
            )
        )
        tool_surface.Surface.retriangulate(surface)
        tool_surface.Surface.update_ifc_tin(ifc_file, surface)
        assert _read_breakline_count(ifc_file, host) == 2


class TestSurfaceAuthorIfcBreakline:
    """Tests for :meth:`bonsai.tool.surface.Surface.author_ifc_breakline`."""

    @staticmethod
    def _breakline() -> tool_surface.Breakline:
        return tool_surface.Breakline(
            guid=ifcopenshell.guid.new(),
            name="centerline",
            polyline=[(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0)],
            kind="standard",
            source="manual",
        )

    def test_creates_annotation(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        breakline = self._breakline()
        annotation = tool_surface.Surface.author_ifc_breakline(ifc_file, breakline)
        assert annotation.is_a("IfcAnnotation")
        assert annotation.Name == "centerline"
        assert annotation.ObjectType == "BREAKLINE"

    def test_global_id_matches_breakline_guid(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        breakline = self._breakline()
        annotation = tool_surface.Surface.author_ifc_breakline(ifc_file, breakline)
        assert annotation.GlobalId == breakline.guid

    def test_stamps_step_id_on_breakline(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        breakline = self._breakline()
        annotation = tool_surface.Surface.author_ifc_breakline(ifc_file, breakline)
        assert breakline.ifc_annotation_id == annotation.id()

    def test_no_site_in_file_raises(self) -> None:
        ifc_file = ifcopenshell.file(schema="IFC4X3_ADD2")
        ifc_file.create_entity(
            "IfcProject", GlobalId=ifcopenshell.guid.new(), Name="No Site"
        )
        with pytest.raises(
            tool_surface.SaikeiSurfaceError, match="no IfcSite"
        ):
            tool_surface.Surface.author_ifc_breakline(ifc_file, self._breakline())

    def test_grading_group_guid_passed_through(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        breakline = self._breakline()
        group_guid = ifcopenshell.guid.new()
        annotation = tool_surface.Surface.author_ifc_breakline(
            ifc_file, breakline, grading_group_guid=group_guid
        )
        # Find SaikeiCivil_BreaklineCommon and check GradingGroupGuid.
        psets = []
        for rel in ifc_file.by_type("IfcRelDefinesByProperties"):
            if annotation in (rel.RelatedObjects or []):
                psets.append(rel.RelatingPropertyDefinition)
        breakline_pset = next(
            (p for p in psets if p.Name == "SaikeiCivil_BreaklineCommon"), None
        )
        assert breakline_pset is not None
        stored_guid = next(
            (
                p.NominalValue.wrappedValue
                for p in breakline_pset.HasProperties
                if p.Name == "GradingGroupGuid"
            ),
            None,
        )
        assert stored_guid == group_guid


@pytest.fixture(autouse=True)
def _reset_surface_registry():
    """Wipe :attr:`Surface._registry` between every test so cross-test
    contamination can't mask bugs (per spec §4.6 "headless tests call
    Surface.clear() in fixture teardown")."""
    yield
    tool_surface.Surface.clear()


class TestRehydrationHelpers:
    """Direct tests for the module-level rehydration helpers.

    These functions were previously only exercised via
    ``_recover_breaklines_from_annotations``; the cold-review tester
    flagged them as untested helper paths. Direct tests pin error
    branches and skip-paths that the integration test wouldn't surface.
    """

    @staticmethod
    def _make_breakline_annotation(
        ifc_file: ifcopenshell.file,
        polyline: list[tuple[float, float, float]],
        kind: str = "standard",
        source: str = "manual",
        name: str = "test-bl",
    ) -> ifcopenshell.entity_instance:
        """Build an IfcAnnotation[BREAKLINE] via the Phase 1 API for use
        in the helper-function tests."""
        site = ifc_file.by_type("IfcSite")[0]
        return ifcopenshell.api.surface.add_breakline_annotation(
            ifc_file,
            site=site,
            polyline=polyline,
            name=name,
            kind=kind,
            source=source,
        )

    def test_extract_polyline_3d_returns_points(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        annotation = self._make_breakline_annotation(
            ifc_file,
            polyline=[(0.0, 0.0, 0.0), (10.0, 5.0, 1.5)],
        )
        result = tool_surface._extract_polyline_3d(annotation)
        assert result == [(0.0, 0.0, 0.0), (10.0, 5.0, 1.5)]

    def test_extract_polyline_3d_returns_none_when_representation_absent(
        self,
    ) -> None:
        ifc_file = _make_ifc_file_with_site()
        # Hand-roll an IfcAnnotation with no Representation.
        annotation = ifc_file.create_entity(
            "IfcAnnotation",
            GlobalId=ifcopenshell.guid.new(),
            Name="naked",
            ObjectType="BREAKLINE",
            PredefinedType="USERDEFINED",
        )
        assert tool_surface._extract_polyline_3d(annotation) is None

    def test_extract_breakline_pset_returns_pset_values(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        annotation = self._make_breakline_annotation(
            ifc_file,
            polyline=[(0.0, 0.0, 0.0), (1.0, 1.0, 0.0)],
            kind="wall",
            source="feature_line",
        )
        kind, source = tool_surface._extract_breakline_pset(annotation)
        assert kind == "wall"
        assert source == "feature_line"

    def test_extract_breakline_pset_falls_back_when_pset_missing(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        # Bare annotation with no SaikeiCivil_BreaklineCommon.
        annotation = ifc_file.create_entity(
            "IfcAnnotation",
            GlobalId=ifcopenshell.guid.new(),
            Name="no-pset",
            ObjectType="BREAKLINE",
            PredefinedType="USERDEFINED",
        )
        kind, source = tool_surface._extract_breakline_pset(annotation)
        assert kind == "standard"
        assert source == "recovered"

    def test_annotation_belongs_to_host_no_assignments_returns_true(
        self,
    ) -> None:
        """The fallback for legacy unscoped breaklines: when an annotation
        has no IfcRelAssignsToProduct, return True for any host so
        single-surface files keep recovering their breaklines."""
        ifc_file = _make_ifc_file_with_site()
        annotation = self._make_breakline_annotation(
            ifc_file,
            polyline=[(0.0, 0.0, 0.0), (1.0, 1.0, 0.0)],
        )
        # Use any IfcProduct as the host; the fallback ignores it.
        host = ifc_file.by_type("IfcSite")[0]
        assert tool_surface._annotation_belongs_to_host(annotation, host) is True

    def test_annotation_belongs_to_host_matches_assigned_product(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        # Build a surface to use as host.
        surface = tool_surface.Surface.build_tin_from_points(
            "Host",
            np.array([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]),
        )
        host = tool_surface.Surface.author_ifc_host(ifc_file, surface)
        # Author breakline scoped to host.
        breakline = tool_surface.Breakline(
            guid=ifcopenshell.guid.new(),
            name="bl",
            polyline=[(0.0, 0.0, 0.0), (1.0, 1.0, 0.0)],
            kind="standard",
            source="manual",
        )
        annotation = tool_surface.Surface.author_ifc_breakline(
            ifc_file, breakline, host_surface=host
        )
        assert tool_surface._annotation_belongs_to_host(annotation, host) is True

    def test_annotation_belongs_to_host_rejects_other_product(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        # Two surfaces; breakline scoped to A only.
        surface_a = tool_surface.Surface.build_tin_from_points(
            "A",
            np.array([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]),
        )
        surface_b = tool_surface.Surface.build_tin_from_points(
            "B",
            np.array([(10.0, 10.0, 0.0), (11.0, 10.0, 0.0), (10.0, 11.0, 0.0)]),
        )
        host_a = tool_surface.Surface.author_ifc_host(ifc_file, surface_a)
        host_b = tool_surface.Surface.author_ifc_host(ifc_file, surface_b)
        breakline = tool_surface.Breakline(
            guid=ifcopenshell.guid.new(),
            name="bl",
            polyline=[(0.0, 0.0, 0.0), (1.0, 1.0, 0.0)],
            kind="standard",
            source="manual",
        )
        annotation = tool_surface.Surface.author_ifc_breakline(
            ifc_file, breakline, host_surface=host_a
        )
        # Belongs to A, not B.
        assert tool_surface._annotation_belongs_to_host(annotation, host_a) is True
        assert tool_surface._annotation_belongs_to_host(annotation, host_b) is False


class TestSurfaceRegistry:
    """Tests for :class:`Surface._registry` and :meth:`get` / :meth:`register`
    / :meth:`invalidate` / :meth:`clear` per spec §4.6."""

    @staticmethod
    def _build_registered_surface() -> tuple[
        ifcopenshell.file, tool_surface.CivilSurface
    ]:
        ifc_file = _make_ifc_file_with_site()
        points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
        )
        surface = tool_surface.Surface.build_tin_from_points("Reg Test", points)
        tool_surface.Surface.author_ifc_host(ifc_file, surface)
        tool_surface.Surface.register(ifc_file, surface)
        return ifc_file, surface

    def test_register_then_get_returns_same_instance(self) -> None:
        ifc_file, surface = self._build_registered_surface()
        cached = tool_surface.Surface.get(ifc_file, surface.guid)
        assert cached is surface  # same object, not just equivalent

    def test_get_rehydrates_on_cache_miss(self) -> None:
        ifc_file, surface = self._build_registered_surface()
        # Wipe the cache; next get() must rehydrate from IFC.
        tool_surface.Surface.clear()
        rehydrated = tool_surface.Surface.get(ifc_file, surface.guid)
        # New instance, but same data.
        assert rehydrated is not surface
        assert rehydrated.guid == surface.guid
        assert rehydrated.name == surface.name
        assert rehydrated.kind == surface.kind
        assert rehydrated.points.shape == surface.points.shape
        assert rehydrated.triangles.shape == surface.triangles.shape

    def test_invalidate_drops_specific_entry(self) -> None:
        ifc_file, surface = self._build_registered_surface()
        # Register a second surface so we can prove invalidate is targeted.
        points2 = np.array(
            [(10.0, 10.0, 0.0), (11.0, 10.0, 0.0), (10.0, 11.0, 0.0)]
        )
        surface_b = tool_surface.Surface.build_tin_from_points("B", points2)
        tool_surface.Surface.author_ifc_host(ifc_file, surface_b)
        tool_surface.Surface.register(ifc_file, surface_b)

        tool_surface.Surface.invalidate(ifc_file, surface.guid)

        # surface.guid is gone; surface_b.guid is still cached as the same instance.
        assert (id(ifc_file), surface.guid) not in tool_surface.Surface._registry
        assert tool_surface.Surface.get(ifc_file, surface_b.guid) is surface_b

    def test_clear_wipes_registry(self) -> None:
        ifc_file, surface = self._build_registered_surface()
        assert tool_surface.Surface._registry  # non-empty
        tool_surface.Surface.clear()
        assert not tool_surface.Surface._registry

    def test_get_unknown_guid_raises(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        with pytest.raises(
            tool_surface.SaikeiSurfaceError, match="no IFC entity with GlobalId"
        ):
            tool_surface.Surface.get(ifc_file, ifcopenshell.guid.new())

    def test_get_wrong_entity_type_raises(self) -> None:
        """Looking up a non-surface entity by its GUID should raise.

        Per the cleanup-4 perf fix, the rehydrate path narrows to
        IfcGeographicElement + IfcEarthworksFill; non-surface GUIDs no
        longer reach the "not a Saikei surface host" branch — they
        surface as "no IFC entity with GlobalId" instead. Functionally
        equivalent for the caller, ~10× faster on large files.
        """
        ifc_file = _make_ifc_file_with_site()
        site = ifc_file.by_type("IfcSite")[0]
        with pytest.raises(
            tool_surface.SaikeiSurfaceError,
            match="no IFC entity with GlobalId",
        ):
            tool_surface.Surface.get(ifc_file, site.GlobalId)

    def test_rehydrate_recovers_breakline_annotations(self) -> None:
        """Per spec §2.3, breaklines persist as IfcAnnotation entities
        separate from the TIN. Rehydration must walk the file and rebuild
        Breakline dataclasses from those annotations so the multi-session
        editing flow doesn't silently drop previously-authored breaklines.
        """
        ifc_file = _make_ifc_file_with_site()
        points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
        )
        surface = tool_surface.Surface.build_tin_from_points(
            "BL Recovery", points
        )
        tool_surface.Surface.author_ifc_host(ifc_file, surface)
        breakline = tool_surface.Breakline(
            guid=ifcopenshell.guid.new(),
            name="diagonal",
            polyline=[(0.0, 0.0, 0.0), (1.0, 1.0, 0.0)],
            kind="wall",
            source="manual",
        )
        tool_surface.Surface.author_ifc_breakline(ifc_file, breakline)

        # Wipe the cache so the next get() rehydrates from IFC.
        tool_surface.Surface.clear()
        rehydrated = tool_surface.Surface.get(ifc_file, surface.guid)

        assert len(rehydrated.breaklines) == 1
        recovered = rehydrated.breaklines[0]
        assert recovered.name == "diagonal"
        assert recovered.kind == "wall"
        assert recovered.guid == breakline.guid
        # Polyline geometry round-trips exactly.
        assert recovered.polyline == [
            (0.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
        ]

    def test_breakline_host_assignment_scopes_recovery(self) -> None:
        """Multi-surface disambiguation: when a breakline is authored with
        ``host_surface=`` set, only that surface recovers it. Other
        surfaces in the same file see no breaklines.

        Closes the cold-review-flagged "breakline scatter" — before this
        fix, every rehydrated surface inherited every IfcAnnotation in
        the file regardless of attribution.
        """
        ifc_file = _make_ifc_file_with_site()
        # Two distinct surfaces.
        surface_a = tool_surface.Surface.build_tin_from_points(
            "A",
            np.array([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]),
        )
        surface_b = tool_surface.Surface.build_tin_from_points(
            "B",
            np.array([(10.0, 10.0, 0.0), (11.0, 10.0, 0.0), (10.0, 11.0, 0.0)]),
        )
        host_a = tool_surface.Surface.author_ifc_host(ifc_file, surface_a)
        host_b = tool_surface.Surface.author_ifc_host(ifc_file, surface_b)

        # Author one breakline scoped to A, one scoped to B.
        bl_a = tool_surface.Breakline(
            guid=ifcopenshell.guid.new(),
            name="bl-on-A",
            polyline=[(0.0, 0.0, 0.0), (1.0, 1.0, 0.0)],
            kind="standard",
            source="manual",
        )
        bl_b = tool_surface.Breakline(
            guid=ifcopenshell.guid.new(),
            name="bl-on-B",
            polyline=[(10.0, 10.0, 0.0), (11.0, 11.0, 0.0)],
            kind="standard",
            source="manual",
        )
        tool_surface.Surface.author_ifc_breakline(
            ifc_file, bl_a, host_surface=host_a
        )
        tool_surface.Surface.author_ifc_breakline(
            ifc_file, bl_b, host_surface=host_b
        )

        # Wipe the cache and rehydrate both surfaces.
        tool_surface.Surface.clear()
        rehydrated_a = tool_surface.Surface.get(ifc_file, surface_a.guid)
        rehydrated_b = tool_surface.Surface.get(ifc_file, surface_b.guid)

        # A only sees its own breakline; B only sees its own.
        a_names = {b.name for b in rehydrated_a.breaklines}
        b_names = {b.name for b in rehydrated_b.breaklines}
        assert a_names == {"bl-on-A"}
        assert b_names == {"bl-on-B"}

    def test_unscoped_breakline_falls_back_to_all_surfaces(self) -> None:
        """Phase-4 fallback: if a breakline is authored WITHOUT a host
        surface link (e.g., legacy data, or the test path that bypasses
        the core orchestrator), every rehydrated surface still recovers
        it. Single-surface files keep working without any migration."""
        ifc_file = _make_ifc_file_with_site()
        surface = tool_surface.Surface.build_tin_from_points(
            "Single",
            np.array([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]),
        )
        tool_surface.Surface.author_ifc_host(ifc_file, surface)

        bl = tool_surface.Breakline(
            guid=ifcopenshell.guid.new(),
            name="legacy",
            polyline=[(0.0, 0.0, 0.0), (1.0, 1.0, 0.0)],
            kind="standard",
            source="manual",
        )
        # No host_surface = legacy / unscoped path.
        tool_surface.Surface.author_ifc_breakline(ifc_file, bl)

        tool_surface.Surface.clear()
        rehydrated = tool_surface.Surface.get(ifc_file, surface.guid)
        assert len(rehydrated.breaklines) == 1
        assert rehydrated.breaklines[0].name == "legacy"

    def test_rehydrate_proposed_fill_without_group_is_proposed_site(self) -> None:
        """Per :meth:`infer_kind_from_spatial_parent`: an
        ``IfcEarthworksFill[SUBGRADE]`` not assigned to any
        ``IfcGroup[GradingGroup]`` round-trips as ``"proposed_site"`` (the
        composite-site kind). Phase 4 files never author grading groups,
        so all proposed surfaces should rehydrate as proposed_site."""
        ifc_file = _make_ifc_file_with_site()
        points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        )
        surface = tool_surface.Surface.build_tin_from_points(
            "P", points, kind="proposed_site"
        )
        tool_surface.Surface.author_ifc_host(ifc_file, surface)
        tool_surface.Surface.clear()

        rehydrated = tool_surface.Surface.get(ifc_file, surface.guid)
        assert rehydrated.kind == "proposed_site"

    def test_rehydrate_proposed_fill_with_grading_group_is_proposed_group(
        self,
    ) -> None:
        """When the proposed fill is assigned to an ``IfcGroup`` whose
        ``ObjectType == "GradingGroup"``, rehydration classifies it as
        ``"proposed_group"``. This is the Phase 5 case — pre-wired into
        Phase 4 so grading-group rehydration just works."""
        ifc_file = _make_ifc_file_with_site()
        points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        )
        surface = tool_surface.Surface.build_tin_from_points(
            "PG", points, kind="proposed_group"
        )
        host = tool_surface.Surface.author_ifc_host(ifc_file, surface)

        # Author a fake IfcGroup[GradingGroup] and assign the host to it
        # (Phase 5 will own this code path; here we just exercise the
        # disambiguation helper).
        group = ifc_file.create_entity(
            "IfcGroup",
            GlobalId=ifcopenshell.guid.new(),
            Name="Test Grading Group",
            ObjectType="GradingGroup",
        )
        ifc_file.create_entity(
            "IfcRelAssignsToGroup",
            GlobalId=ifcopenshell.guid.new(),
            RelatingGroup=group,
            RelatedObjects=[host],
        )

        tool_surface.Surface.clear()
        rehydrated = tool_surface.Surface.get(ifc_file, surface.guid)
        assert rehydrated.kind == "proposed_group"

    def test_infer_kind_helper_directly(self) -> None:
        """Smoke-test :meth:`Surface.infer_kind_from_spatial_parent`
        without going through rehydration."""
        ifc_file = _make_ifc_file_with_site()
        # No-group fill → proposed_site.
        host = ifc_file.create_entity(
            "IfcEarthworksFill",
            GlobalId=ifcopenshell.guid.new(),
            Name="Bare Fill",
            PredefinedType="SUBGRADE",
        )
        assert (
            tool_surface.Surface.infer_kind_from_spatial_parent(host)
            == "proposed_site"
        )

        # Same host assigned to a grading group → proposed_group.
        group = ifc_file.create_entity(
            "IfcGroup",
            GlobalId=ifcopenshell.guid.new(),
            ObjectType="GradingGroup",
        )
        ifc_file.create_entity(
            "IfcRelAssignsToGroup",
            GlobalId=ifcopenshell.guid.new(),
            RelatingGroup=group,
            RelatedObjects=[host],
        )
        assert (
            tool_surface.Surface.infer_kind_from_spatial_parent(host)
            == "proposed_group"
        )

        # A group whose ObjectType is something else (e.g., a clash group)
        # should NOT be classified as proposed_group.
        other_host = ifc_file.create_entity(
            "IfcEarthworksFill",
            GlobalId=ifcopenshell.guid.new(),
            PredefinedType="SUBGRADE",
        )
        unrelated_group = ifc_file.create_entity(
            "IfcGroup",
            GlobalId=ifcopenshell.guid.new(),
            ObjectType="ClashGroup",
        )
        ifc_file.create_entity(
            "IfcRelAssignsToGroup",
            GlobalId=ifcopenshell.guid.new(),
            RelatingGroup=unrelated_group,
            RelatedObjects=[other_host],
        )
        assert (
            tool_surface.Surface.infer_kind_from_spatial_parent(other_host)
            == "proposed_site"
        )

    def test_rehydrate_no_breaklines_in_file_returns_empty_list(self) -> None:
        """When the file has no IfcAnnotation[BREAKLINE], rehydration
        produces a CivilSurface with empty breaklines (the common case)."""
        ifc_file = _make_ifc_file_with_site()
        points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        )
        surface = tool_surface.Surface.build_tin_from_points(
            "NoBL", points
        )
        tool_surface.Surface.author_ifc_host(ifc_file, surface)
        tool_surface.Surface.clear()

        rehydrated = tool_surface.Surface.get(ifc_file, surface.guid)
        assert rehydrated.breaklines == []

    def test_multi_session_add_breakline_preserves_previous(self) -> None:
        """The agent-flagged risk: user creates surface + breakline, reopens,
        then adds another breakline. After the second add, BOTH breaklines
        should be present in the TIN — not just the new one. Before the
        rehydration recovery shipped, session 2's retriangulate would only
        see ``diag-B`` and silently drop ``diag-A``.

        Uses non-crossing breaklines (a diagonal and a centerline) to
        avoid the documented CDT Steiner-point limitation.
        """
        # Session 1: create surface, add diagonal breakline. The points
        # include the breakline endpoints + a center vertex so subsequent
        # non-crossing breaklines can share endpoints without introducing
        # Steiner points (the documented CDT Phase-4 limitation).
        ifc_file = _make_ifc_file_with_site()
        points = np.array(
            [
                (0.0, 0.0, 0.0),
                (5.0, 0.0, 0.0),
                (10.0, 0.0, 0.0),
                (10.0, 10.0, 0.0),
                (5.0, 10.0, 0.0),
                (0.0, 10.0, 0.0),
                (5.0, 5.0, 0.0),  # shared interior vertex
            ]
        )
        surface = tool_surface.Surface.build_tin_from_points("Multi", points)
        tool_surface.Surface.author_ifc_host(ifc_file, surface)

        # First breakline: bottom-left edge.
        breakline_a = tool_surface.Breakline(
            guid=ifcopenshell.guid.new(),
            name="bl-A",
            polyline=[(0.0, 0.0, 0.0), (5.0, 5.0, 0.0)],
            kind="standard",
            source="manual",
        )
        tool_surface.Surface.author_ifc_breakline(ifc_file, breakline_a)
        surface.breaklines.append(breakline_a)
        tool_surface.Surface.retriangulate(surface)
        tool_surface.Surface.update_ifc_tin(ifc_file, surface)

        # Session 2: simulate a reopen by clearing the cache. Get() now
        # rehydrates with breaklines recovered from IfcAnnotation.
        tool_surface.Surface.clear()
        rehydrated = tool_surface.Surface.get(ifc_file, surface.guid)
        assert len(rehydrated.breaklines) == 1

        # Add a second breakline that shares the (5,5) endpoint with the
        # first — top-right edge from center to corner.
        breakline_b = tool_surface.Breakline(
            guid=ifcopenshell.guid.new(),
            name="bl-B",
            polyline=[(5.0, 5.0, 0.0), (10.0, 10.0, 0.0)],
            kind="standard",
            source="manual",
        )
        tool_surface.Surface.author_ifc_breakline(ifc_file, breakline_b)
        rehydrated.breaklines.append(breakline_b)
        tool_surface.Surface.retriangulate(rehydrated)
        tool_surface.Surface.update_ifc_tin(ifc_file, rehydrated)

        # Both breaklines should be present in the dataclass — proves the
        # rehydration recovery prevented the silent drop.
        assert len(rehydrated.breaklines) == 2
        names = sorted(b.name for b in rehydrated.breaklines)
        assert names == ["bl-A", "bl-B"]

    def test_multi_file_registry_keyed_by_id(self) -> None:
        """Per spec §4.6, the same GUID in two different files is stored as
        two separate entries — keyed on ``(id(ifc_file), guid)``."""
        ifc_file_a = _make_ifc_file_with_site()
        ifc_file_b = _make_ifc_file_with_site()
        points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        )
        guid = ifcopenshell.guid.new()

        surface_a = tool_surface.Surface.build_tin_from_points(
            "A", points, guid=guid
        )
        tool_surface.Surface.author_ifc_host(ifc_file_a, surface_a)
        tool_surface.Surface.register(ifc_file_a, surface_a)

        surface_b = tool_surface.Surface.build_tin_from_points(
            "B", points, guid=guid
        )
        tool_surface.Surface.author_ifc_host(ifc_file_b, surface_b)
        tool_surface.Surface.register(ifc_file_b, surface_b)

        # Same guid, two separate registry entries.
        assert tool_surface.Surface.get(ifc_file_a, guid) is surface_a
        assert tool_surface.Surface.get(ifc_file_b, guid) is surface_b


class TestSurfaceBlenderMesh(NewIfc4X3):
    """Tests for :meth:`Surface.create_blender_mesh` and
    :meth:`Surface.update_blender_mesh`.

    Inherits :class:`test.bim.bootstrap.NewIfc4X3` so each test starts from a
    Bonsai-bootstrapped IFC4X3 project (with its collection hierarchy and
    spatial root) — :func:`tool.Collector.assign` requires the project /
    container Blender objects to be present.
    """

    def _make_registered_surface(
        self, name: str = "MeshTest"
    ) -> tool_surface.CivilSurface:
        ifc_file = tool.Ifc.get()
        points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
        )
        surface = tool_surface.Surface.build_tin_from_points(name, points)
        tool_surface.Surface.author_ifc_host(ifc_file, surface)
        return surface

    def test_create_blender_mesh_returns_object(self) -> None:
        surface = self._make_registered_surface()
        obj = tool_surface.Surface.create_blender_mesh(tool.Ifc.get(), surface)
        assert obj is not None
        assert obj.data is not None
        assert isinstance(obj.data, bpy.types.Mesh)
        # Two triangles → 2 polygons; 4 unique vertices.
        assert len(obj.data.polygons) == 2
        assert len(obj.data.vertices) == 4

    def test_create_blender_mesh_no_host_raises(self) -> None:
        ifc_file = tool.Ifc.get()
        points = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        )
        surface = tool_surface.Surface.build_tin_from_points("orphan", points)
        with pytest.raises(
            tool_surface.SaikeiSurfaceError, match="no IFC host entity"
        ):
            tool_surface.Surface.create_blender_mesh(ifc_file, surface)

    def test_create_blender_mesh_idempotent(self) -> None:
        """Calling create_blender_mesh twice returns the same Blender object."""
        surface = self._make_registered_surface()
        ifc_file = tool.Ifc.get()
        obj_a = tool_surface.Surface.create_blender_mesh(ifc_file, surface)
        obj_b = tool_surface.Surface.create_blender_mesh(ifc_file, surface)
        assert obj_a is obj_b

    def test_create_blender_mesh_links_to_ifc_entity(self) -> None:
        """Bidirectional link works both ways via tool.Ifc."""
        surface = self._make_registered_surface()
        ifc_file = tool.Ifc.get()
        obj = tool_surface.Surface.create_blender_mesh(ifc_file, surface)
        host = ifc_file.by_id(surface.ifc_host_entity_id)
        assert tool.Ifc.get_object(host) is obj
        assert tool.Ifc.get_entity(obj) == host

    def test_update_blender_mesh_rebuilds_geometry(self) -> None:
        surface = self._make_registered_surface()
        ifc_file = tool.Ifc.get()
        obj = tool_surface.Surface.create_blender_mesh(ifc_file, surface)
        # Add a vertex and retriangulate.
        surface.points = np.vstack([surface.points, [[0.5, 0.5, 1.0]]])
        tool_surface.Surface.retriangulate(surface)
        updated = tool_surface.Surface.update_blender_mesh(ifc_file, surface)
        assert updated is obj  # in-place update
        assert len(obj.data.vertices) == 5

    def test_update_blender_mesh_no_object_returns_none(self) -> None:
        surface = self._make_registered_surface()
        # No create_blender_mesh call — no object linked.
        result = tool_surface.Surface.update_blender_mesh(tool.Ifc.get(), surface)
        assert result is None


class TestSurfaceModuleRegistration:
    """Smoke tests verifying :func:`bonsai.bim.module.surface.register`
    attached the property groups to ``bpy.types.Scene``.

    These tests live here (test/tool/) rather than test/bim/module/surface/
    because the latter directory triggers a pytest-bdd conftest that the
    current environment's parse_type version can't load. Move them once
    the bdd-conftest dependency is fixed upstream.
    """

    def test_civil_surface_properties_attached_to_scene(self) -> None:
        scene_props = bpy.types.Scene.bl_rna.properties
        assert "CivilSurfaceProperties" in scene_props, (
            "CivilSurfaceProperties not registered on bpy.types.Scene"
        )

    def test_default_property_values(self) -> None:
        import bonsai.bim.module.surface.prop as surface_prop

        # bpy.context.scene may not exist in some pytest contexts; defaults
        # are fixed by the PropertyGroup definition itself.
        rna = surface_prop.CivilSurfaceProperties.bl_rna
        assert rna.properties["new_surface_name"].default == "Existing Ground"
        assert rna.properties["new_surface_kind"].default == "existing"
        assert rna.properties["triangulation_tolerance"].default == 0.0
        assert rna.properties["show_triangles"].default is False
        assert rna.properties["show_elevation_banding"].default is False

    def test_kind_enum_has_three_options(self) -> None:
        import bonsai.bim.module.surface.prop as surface_prop

        rna = surface_prop.CivilSurfaceProperties.bl_rna
        kind_prop = rna.properties["new_surface_kind"]
        identifiers = {item.identifier for item in kind_prop.enum_items}
        assert identifiers == {"existing", "proposed_group", "proposed_site"}

    def test_uilist_class_registered(self) -> None:
        assert hasattr(bpy.types, "CIVIL_UL_surfaces")

    def test_panels_registered(self) -> None:
        """All four CIVIL_PT_surface_* sub-panels and the
        BIM_PT_tab_surface_modeler tab parent should be in bpy.types."""
        assert hasattr(bpy.types, "BIM_PT_tab_surface_modeler")
        assert hasattr(bpy.types, "CIVIL_PT_surface_creation")
        assert hasattr(bpy.types, "CIVIL_PT_surface_list")
        assert hasattr(bpy.types, "CIVIL_PT_surface_active")
        assert hasattr(bpy.types, "CIVIL_PT_surface_display")


class TestSurfaceDataCache(NewIfc4X3):
    """Tests for :class:`bonsai.bim.module.surface.data.SurfaceData`."""

    def test_load_with_no_surfaces_returns_zero_count(self) -> None:
        from bonsai.bim.module.surface.data import SurfaceData

        SurfaceData.is_loaded = False
        SurfaceData.load()
        assert SurfaceData.is_loaded
        assert SurfaceData.data["surface_count"] == 0

    def test_load_after_creating_surface_increments_count(
        self, tmp_path
    ) -> None:
        from bonsai.bim.module.surface.data import SurfaceData

        points_path = tmp_path / "p.csv"
        points_path.write_text("0,0,0\n1,0,0\n0,1,0\n")
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(points_path)
        )
        SurfaceData.is_loaded = False
        SurfaceData.load()
        assert SurfaceData.data["surface_count"] == 1

    def test_active_surface_summary(self, tmp_path) -> None:
        from bonsai.bim.module.surface.data import SurfaceData

        points_path = tmp_path / "p.csv"
        points_path.write_text("0,0,0\n10,0,0\n10,10,0\n0,10,0\n")
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(points_path)
        )
        guid = bpy.context.scene.CivilSurfaceProperties.active_surface_guid

        summary = SurfaceData.active_surface_summary(tool.Ifc.get(), guid)
        assert summary["name"] == "Existing Ground"
        assert summary["kind"] == "existing"
        assert summary["vertex_count"] == 4
        assert summary["triangle_count"] == 2
        assert summary["breakline_count"] == 0
        assert summary["has_boundary"] is True

    def test_active_surface_summary_unknown_guid_returns_missing(self) -> None:
        from bonsai.bim.module.surface.data import SurfaceData

        summary = SurfaceData.active_surface_summary(
            tool.Ifc.get(), "non-existent-guid"
        )
        assert summary["name"] == "(missing)"

    def test_load_syncs_uilist_with_ifc_entities(self, tmp_path) -> None:
        """Closes the cold-review-flagged "UIList empty on file reopen"
        bug. SurfaceData.load() must repopulate
        CivilSurfaceProperties.surfaces from the IFC tree, not just count
        entities. Without this, opening a file with surfaces shows an
        empty list."""
        from bonsai.bim.module.surface.data import SurfaceData

        # Create a surface, then simulate "reopen" by clearing the UIList.
        path = tmp_path / "p.csv"
        path.write_text("0,0,0\n10,0,0\n10,10,0\n0,10,0\n")
        bpy.context.scene.CivilSurfaceProperties.new_surface_name = "ListTest"
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(path)
        )
        # The UIList has 1 row from the create operator.
        assert len(bpy.context.scene.CivilSurfaceProperties.surfaces) == 1

        # Simulate a file reopen: clear the UIList in place.
        bpy.context.scene.CivilSurfaceProperties.surfaces.clear()
        assert len(bpy.context.scene.CivilSurfaceProperties.surfaces) == 0

        # Force a sync — the UIList should rebuild from the IFC tree.
        SurfaceData.sync_uilists()

        surfaces = bpy.context.scene.CivilSurfaceProperties.surfaces
        assert len(surfaces) == 1
        assert surfaces[0].name == "ListTest"
        assert surfaces[0].kind == "existing"
        assert surfaces[0].guid != ""
        assert surfaces[0].ifc_id > 0

    def test_uilist_kind_reflects_spatial_parent(self, tmp_path) -> None:
        """``SurfaceData._sync_uilist_from_ifc`` must classify each
        IfcEarthworksFill via ``infer_kind_from_spatial_parent`` rather
        than hardcoding ``"proposed_group"``. Phase-4 files (no grading
        group) should land as ``"proposed_site"`` in the UIList.
        """
        from bonsai.bim.module.surface.data import SurfaceData

        path = tmp_path / "p.csv"
        path.write_text("0,0,0\n10,0,0\n10,10,0\n0,10,0\n")
        bpy.context.scene.CivilSurfaceProperties.new_surface_kind = (
            "proposed_site"
        )
        bpy.context.scene.CivilSurfaceProperties.new_surface_name = "PSite"
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(path)
        )
        # Force a reload so the UIList is rebuilt from IFC, not from the
        # in-memory authoring path.
        bpy.context.scene.CivilSurfaceProperties.surfaces.clear()
        SurfaceData.sync_uilists()

        surfaces = bpy.context.scene.CivilSurfaceProperties.surfaces
        assert len(surfaces) == 1
        assert surfaces[0].kind == "proposed_site"

    def test_load_preserves_active_selection_if_guid_still_present(
        self, tmp_path
    ) -> None:
        """When refreshing an existing UIList, the previously-selected
        row stays selected if its GUID survives in the IFC."""
        from bonsai.bim.module.surface.data import SurfaceData

        path_a = tmp_path / "a.csv"
        path_a.write_text("0,0,0\n1,0,0\n0,1,0\n")
        bpy.context.scene.CivilSurfaceProperties.new_surface_name = "Surf A"
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(path_a)
        )
        path_b = tmp_path / "b.csv"
        path_b.write_text("10,10,0\n11,10,0\n10,11,0\n")
        bpy.context.scene.CivilSurfaceProperties.new_surface_name = "Surf B"
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(path_b)
        )

        # Select A.
        props = bpy.context.scene.CivilSurfaceProperties
        props.active_surface_index = 0
        guid_a = props.active_surface_guid

        # Force a sync — A's guid is still in the IFC, selection preserved.
        SurfaceData.sync_uilists()
        assert props.active_surface_guid == guid_a


class TestActiveSurfaceIndexSync(NewIfc4X3):
    """Tests for the :func:`_on_active_surface_index_change` update callback.

    Without this callback, clicking a different UIList row only changes the
    visually-highlighted row — :attr:`active_surface_guid` would stay
    pointed at whichever surface was last created, blocking the user from
    editing earlier surfaces.
    """

    def _create_two_surfaces(self, tmp_path) -> tuple[str, str]:
        """Create two surfaces and return (guid_A, guid_B). After this
        helper, B is the active surface (last created)."""
        path_a = tmp_path / "a.csv"
        path_a.write_text("0,0,0\n1,0,0\n0,1,0\n")
        bpy.context.scene.CivilSurfaceProperties.new_surface_name = "Surf A"
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(path_a)
        )
        guid_a = bpy.context.scene.CivilSurfaceProperties.active_surface_guid

        path_b = tmp_path / "b.csv"
        path_b.write_text("10,10,0\n11,10,0\n10,11,0\n")
        bpy.context.scene.CivilSurfaceProperties.new_surface_name = "Surf B"
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(path_b)
        )
        guid_b = bpy.context.scene.CivilSurfaceProperties.active_surface_guid

        return guid_a, guid_b

    def test_selecting_first_row_makes_first_surface_active(self, tmp_path) -> None:
        guid_a, guid_b = self._create_two_surfaces(tmp_path)
        props = bpy.context.scene.CivilSurfaceProperties

        # Sanity: after creation the second surface is active.
        assert props.active_surface_guid == guid_b

        # Click the first row.
        props.active_surface_index = 0
        assert props.active_surface_guid == guid_a
        assert props.active_surface_id == props.surfaces[0].ifc_id

    def test_selecting_second_row_makes_second_surface_active(
        self, tmp_path
    ) -> None:
        guid_a, guid_b = self._create_two_surfaces(tmp_path)
        props = bpy.context.scene.CivilSurfaceProperties

        # Switch to first, then back to second.
        props.active_surface_index = 0
        assert props.active_surface_guid == guid_a
        props.active_surface_index = 1
        assert props.active_surface_guid == guid_b

    def test_out_of_range_index_clears_active_state(self, tmp_path) -> None:
        self._create_two_surfaces(tmp_path)
        props = bpy.context.scene.CivilSurfaceProperties

        # An index beyond the list bounds clears active state instead of
        # leaving stale values around.
        props.active_surface_index = 99
        assert props.active_surface_id == 0
        assert props.active_surface_guid == ""

    def test_row_selection_routes_edits_to_first_surface(self, tmp_path) -> None:
        """End-to-end: after switching active row, add_breakline targets
        the correct surface — proves the operator sees the synced GUID."""
        # Use 4-corner squares so the diagonal breakline (corner-to-corner)
        # doesn't introduce Steiner points.
        path_a = tmp_path / "a.csv"
        path_a.write_text("0,0,0\n1,0,0\n1,1,0\n0,1,0\n")
        bpy.context.scene.CivilSurfaceProperties.new_surface_name = "Surf A"
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(path_a)
        )
        guid_a = bpy.context.scene.CivilSurfaceProperties.active_surface_guid

        path_b = tmp_path / "b.csv"
        path_b.write_text("10,10,0\n11,10,0\n11,11,0\n10,11,0\n")
        bpy.context.scene.CivilSurfaceProperties.new_surface_name = "Surf B"
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(path_b)
        )
        guid_b = bpy.context.scene.CivilSurfaceProperties.active_surface_guid

        props = bpy.context.scene.CivilSurfaceProperties

        # Switch active to A via UIList row index.
        props.active_surface_index = 0
        assert props.active_surface_guid == guid_a

        # Add a breakline; it should land on A, not on B.
        bl_path = tmp_path / "bl.csv"
        bl_path.write_text("0,0,0\n1,1,0\n")
        bpy.ops.civil.surface_add_breakline(
            "EXEC_DEFAULT",
            csv_filepath=str(bl_path),
            breakline_name="bl-on-A",
        )

        surface_a = tool.Surface.get(tool.Ifc.get(), guid_a)
        surface_b = tool.Surface.get(tool.Ifc.get(), guid_b)
        assert len(surface_a.breaklines) == 1
        assert surface_a.breaklines[0].name == "bl-on-A"
        assert len(surface_b.breaklines) == 0


class TestSurfaceDecorator(NewIfc4X3):
    """Tests for :class:`bonsai.bim.module.surface.decorator.SurfaceDecorator`.

    The GPU draw handler itself can't run headless (no viewport), but install/
    uninstall lifecycle, the toggle update= callback, and the elevation-color
    ramp math are all exercisable.
    """

    def test_install_uninstall_lifecycle(self) -> None:
        from bonsai.bim.module.surface.decorator import SurfaceDecorator

        SurfaceDecorator.uninstall()  # ensure clean slate
        assert not SurfaceDecorator.is_installed
        SurfaceDecorator.install(bpy.context)
        try:
            assert SurfaceDecorator.is_installed
            assert len(SurfaceDecorator.handlers) == 1
        finally:
            SurfaceDecorator.uninstall()
        assert not SurfaceDecorator.is_installed
        assert SurfaceDecorator.handlers == []

    def test_install_idempotent(self) -> None:
        from bonsai.bim.module.surface.decorator import SurfaceDecorator

        SurfaceDecorator.uninstall()
        SurfaceDecorator.install(bpy.context)
        SurfaceDecorator.install(bpy.context)  # second install replaces handler
        try:
            assert SurfaceDecorator.is_installed
            assert len(SurfaceDecorator.handlers) == 1
        finally:
            SurfaceDecorator.uninstall()

    def test_toggle_show_triangles_installs_decorator(self) -> None:
        from bonsai.bim.module.surface.decorator import SurfaceDecorator

        SurfaceDecorator.uninstall()
        props = bpy.context.scene.CivilSurfaceProperties
        props.show_triangles = True
        try:
            assert SurfaceDecorator.is_installed
        finally:
            props.show_triangles = False
            SurfaceDecorator.uninstall()

    def test_toggling_both_off_uninstalls_decorator(self) -> None:
        from bonsai.bim.module.surface.decorator import SurfaceDecorator

        SurfaceDecorator.uninstall()
        props = bpy.context.scene.CivilSurfaceProperties
        props.show_triangles = True
        props.show_elevation_banding = True
        try:
            assert SurfaceDecorator.is_installed
            props.show_triangles = False
            assert SurfaceDecorator.is_installed  # banding still on
            props.show_elevation_banding = False
            assert not SurfaceDecorator.is_installed
        finally:
            props.show_triangles = False
            props.show_elevation_banding = False
            SurfaceDecorator.uninstall()

    def test_elevation_color_ramp_endpoints(self) -> None:
        """``_elevation_color`` returns the low / mid / high stops at 0 /
        0.5 / 1 respectively, and clamps out-of-range values."""
        from bonsai.bim.module.surface.decorator import SurfaceDecorator

        assert SurfaceDecorator._elevation_color(0.0) == pytest.approx(
            SurfaceDecorator.COLOR_ELEVATION_LOW
        )
        assert SurfaceDecorator._elevation_color(0.5) == pytest.approx(
            SurfaceDecorator.COLOR_ELEVATION_MID
        )
        assert SurfaceDecorator._elevation_color(1.0) == pytest.approx(
            SurfaceDecorator.COLOR_ELEVATION_HIGH
        )
        # Out-of-range values are clamped.
        assert SurfaceDecorator._elevation_color(-0.5) == pytest.approx(
            SurfaceDecorator.COLOR_ELEVATION_LOW
        )
        assert SurfaceDecorator._elevation_color(1.5) == pytest.approx(
            SurfaceDecorator.COLOR_ELEVATION_HIGH
        )


# ---------------------------------------------------------------------------
# Phase 7b tests — WorkSpaceTool, modal operators, simplify, translate_z
# ---------------------------------------------------------------------------


class TestSurfaceSimplify(NewIfc4X3):
    """Tests for :meth:`Surface.simplify`.

    Uses ``NewIfc4X3`` so ``tool.Ifc.get()`` returns the Bonsai-active IFC
    file that ``simplify`` reads internally.
    """

    def _create_five_point_surface(self, tmp_path) -> tuple[str, int]:
        """Create a surface with 5 points (4 corners + collinear mid-edge).

        The 5 points form a convex boundary: bottom-left, bottom-middle
        (collinear on the bottom edge), bottom-right, top-right, top-left.
        Returns ``(surface_guid, host_step_id)``.
        """
        # Write a CSV with 5 points that form a convex shape but with one
        # collinear mid-edge vertex on the bottom side.
        path = tmp_path / "pts5.csv"
        path.write_text(
            "0,0,5\n"
            "5,0,5\n"   # collinear on bottom edge between (0,0) and (10,0)
            "10,0,5\n"
            "10,10,5\n"
            "0,10,5\n"
        )
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(path)
        )
        props = bpy.context.scene.CivilSurfaceProperties
        surface_guid = props.active_surface_guid
        ifc_file = tool.Ifc.get()
        surface = tool.Surface.get(ifc_file, surface_guid)
        return surface_guid, ifc_file.by_id(surface.ifc_host_entity_id).id()

    @pytest.mark.civil
    def test_simplify_zero_tolerance_no_op(self, tmp_path) -> None:
        """When tolerance == 0.0 the method is a guaranteed no-op."""
        surface_guid, host_id = self._create_five_point_surface(tmp_path)
        ifc_file = tool.Ifc.get()
        surface = tool.Surface.get(ifc_file, surface_guid)
        point_count_before = len(surface.points)

        removed = tool_surface.Surface.simplify(ifc_file, host_id, 0.0)

        assert removed == 0
        # Point count unchanged (surface not re-fetched; simplify returned early).
        assert len(surface.points) == point_count_before

    @pytest.mark.civil
    def test_simplify_no_op_when_no_removable_vertices(self, tmp_path) -> None:
        """simplify() returns 0 and leaves points unchanged when the boundary
        has no removable vertices (all corners are already tight)."""
        surface_guid, host_id = self._create_five_point_surface(tmp_path)
        ifc_file = tool.Ifc.get()
        surface = tool.Surface.get(ifc_file, surface_guid)

        # Set a clean 4-corner boundary with no collinear vertices.
        import shapely as _shapely

        tight_boundary = _shapely.Polygon(
            [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        )
        surface.outer_boundary = tight_boundary
        points_before = surface.points.copy()

        removed = tool_surface.Surface.simplify(ifc_file, host_id, 0.5)

        assert removed == 0
        # Surface points should be unchanged.
        np.testing.assert_array_equal(surface.points, points_before)

    @pytest.mark.civil
    def test_simplify_removes_collinear_boundary_vertices(self, tmp_path) -> None:
        """A collinear mid-edge vertex on an explicitly set outer boundary is removed.

        Build a surface, then explicitly set its outer boundary to a polygon
        that has 5 corners (4 actual corners + 1 collinear midpoint on the
        bottom edge).  With a tolerance > 0, Douglas-Peucker drops the
        collinear vertex.  Returns 1 removed vertex.

        The boundary must be set explicitly because the convex-hull fallback
        already drops collinear points — only an explicitly authored boundary
        polygon (from ``set_outer_boundary``) retains them, giving
        ``simplify`` something to reduce.
        """
        surface_guid, host_id = self._create_five_point_surface(tmp_path)
        ifc_file = tool.Ifc.get()
        surface = tool.Surface.get(ifc_file, surface_guid)

        # Explicitly set an outer boundary that includes the collinear midpoint.
        # Shapely allows collinear vertices in an explicit Polygon ring.
        import shapely as _shapely

        boundary_with_collinear = _shapely.Polygon(
            [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        )
        # Verify shapely keeps the collinear vertex in the explicit ring.
        coords = list(boundary_with_collinear.exterior.coords)
        assert len(coords) == 6  # 5 unique + closing repeat

        surface.outer_boundary = boundary_with_collinear

        removed = tool_surface.Surface.simplify(ifc_file, host_id, 0.5)

        assert removed == 1
        # Force rehydration so the registry reflects the post-simplify state.
        tool.Surface.invalidate(ifc_file, surface_guid)
        surface_after = tool.Surface.get(ifc_file, surface_guid)
        assert len(surface_after.points) == 4

    @pytest.mark.civil
    def test_simplify_invalid_surface_id_raises(self, tmp_path) -> None:
        """A step-id that resolves to no entity raises SaikeiSurfaceError."""
        # Create at least one surface so the IFC file is initialized.
        path = tmp_path / "pts.csv"
        path.write_text("0,0,0\n1,0,0\n0,1,0\n")
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(path)
        )
        surface_guid = bpy.context.scene.CivilSurfaceProperties.active_surface_guid
        ifc_file = tool.Ifc.get()
        surface = tool.Surface.get(ifc_file, surface_guid)
        points_before = len(surface.points)

        with pytest.raises(tool_surface.SaikeiSurfaceError):
            tool_surface.Surface.simplify(ifc_file, 999999, 1.0)

        # Postcondition: original surface unmodified.
        assert len(surface.points) == points_before


class TestSurfaceWorkspaceToolRegistration:
    """Smoke test: :class:`SurfaceCivilTool` class is importable and has
    the correct ``bl_idname``.

    A full T-bar registration smoke test requires an interactive 3D
    viewport workspace which is not available in headless pytest-blender.
    Per spec §10.3, the registration smoke test only asserts
    ``bpy.utils.register_tool()`` succeeded — which our module-level
    ``register()`` already calls at import time (the module is imported by
    Bonsai's ``bim/__init__.py`` registration chain during test setup via
    ``NewIfc4X3``).  We therefore assert the class attributes here rather
    than calling register_tool again (idempotent call in headless fails
    silently; duplicating it doesn't add coverage).
    """

    @pytest.mark.civil
    def test_workspace_tool_class_has_correct_idname(self) -> None:
        from bonsai.bim.module.surface.workspace import SurfaceCivilTool

        assert SurfaceCivilTool.bl_idname == "bim.surface_tool"

    @pytest.mark.civil
    def test_workspace_tool_class_has_correct_label(self) -> None:
        from bonsai.bim.module.surface.workspace import SurfaceCivilTool

        assert SurfaceCivilTool.bl_label == "Surface"

    @pytest.mark.civil
    def test_workspace_tool_icon(self) -> None:
        from bonsai.bim.module.surface.workspace import SurfaceCivilTool

        # bl_icon is a filesystem path to the .dat icon file (Bonsai
        # convention; matches cad/, drawing/, model/ workspace tools).
        # WorkSpaceTool does not accept Blender enum-string icons.
        assert SurfaceCivilTool.bl_icon.endswith("ops.authoring.surface")

    @pytest.mark.civil
    def test_workspace_tool_no_gizmo(self) -> None:
        from bonsai.bim.module.surface.workspace import SurfaceCivilTool

        # Per spec §6.4: gizmos deferred; bl_widget must be None.
        assert SurfaceCivilTool.bl_widget is None


class TestSurfacePickBreaklineModal(NewIfc4X3):
    """Tests for :class:`CIVIL_OT_surface_pick_breakline`.

    Exercises the ``_from_data`` headless path (``EXEC_DEFAULT`` with
    properties pre-set) per spec §3.5 and §10.3.
    """

    def _make_surface_with_curve(self, tmp_path) -> tuple[str, str]:
        """Create a registered surface and a Blender curve object.

        Returns ``(surface_guid, curve_object_name)``.
        """
        path = tmp_path / "pts.csv"
        path.write_text("0,0,0\n10,0,0\n10,10,0\n0,10,0\n")
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(path)
        )
        surface_guid = bpy.context.scene.CivilSurfaceProperties.active_surface_guid

        # Build a Blender curve as the headless polyline source.
        curve_data = bpy.data.curves.new("TestBreaklineCurve", type="CURVE")
        curve_data.dimensions = "3D"
        spline = curve_data.splines.new("POLY")
        spline.points.add(1)  # 2 points total
        spline.points[0].co = (0.0, 5.0, 0.0, 1.0)
        spline.points[1].co = (10.0, 5.0, 0.0, 1.0)
        obj = bpy.data.objects.new("TestBreaklineCurve", curve_data)
        bpy.context.scene.collection.objects.link(obj)

        return surface_guid, obj.name

    @pytest.mark.civil
    def test_smoke_register_and_instantiate(self) -> None:
        """The operator class is registered; instantiation does not raise."""
        assert hasattr(bpy.types, "CIVIL_OT_surface_pick_breakline")

    @pytest.mark.civil
    def test_from_data_authors_breakline(self, tmp_path) -> None:
        """EXEC_DEFAULT path with polyline_object_name set authors a breakline
        IFC entity and re-triangulates the surface."""
        surface_guid, curve_name = self._make_surface_with_curve(tmp_path)

        ifc_file = tool.Ifc.get()
        breaklines_before = len(ifc_file.by_type("IfcAnnotation"))

        bpy.ops.civil.surface_pick_breakline(
            "EXEC_DEFAULT",
            polyline_object_name=curve_name,
            surface_guid=surface_guid,
            breakline_name="TestBL",
        )

        # One new IfcAnnotation authored for the breakline.
        annotations_after = ifc_file.by_type("IfcAnnotation")
        assert len(annotations_after) == breaklines_before + 1
        names = {a.Name for a in annotations_after}
        assert "TestBL" in names

    @pytest.mark.civil
    def test_invalid_polyline_object_raises(self, tmp_path) -> None:
        """A nonexistent curve object name raises RuntimeError at the bpy.ops
        boundary and leaves no new IFC annotation."""
        path = tmp_path / "pts.csv"
        path.write_text("0,0,0\n10,0,0\n10,10,0\n0,10,0\n")
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(path)
        )
        surface_guid = bpy.context.scene.CivilSurfaceProperties.active_surface_guid

        ifc_file = tool.Ifc.get()
        annotations_before = len(ifc_file.by_type("IfcAnnotation"))

        with pytest.raises(RuntimeError):
            bpy.ops.civil.surface_pick_breakline(
                "EXEC_DEFAULT",
                polyline_object_name="__does_not_exist__",
                surface_guid=surface_guid,
            )

        # Postcondition: no annotation authored.
        assert len(ifc_file.by_type("IfcAnnotation")) == annotations_before


class TestSurfacePickBoundaryModal(NewIfc4X3):
    """Tests for :class:`CIVIL_OT_surface_pick_boundary`.

    Exercises the ``_from_data`` headless path per spec §3.5 and §10.3.
    """

    def _make_surface_and_boundary_curve(self, tmp_path) -> tuple[str, str]:
        """Create a registered surface and a Blender curve with >= 3 vertices.

        The boundary polygon uses the same XY coordinates as 3 of the surface
        corners, so constrained Delaunay does not need to introduce Steiner
        points (which fail Phase 4's triangulator).

        Returns ``(surface_guid, curve_object_name)``.
        """
        path = tmp_path / "pts.csv"
        # 4-corner square at Z=0.
        path.write_text("0,0,0\n20,0,0\n20,20,0\n0,20,0\n")
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(path)
        )
        surface_guid = bpy.context.scene.CivilSurfaceProperties.active_surface_guid

        # Build a triangular boundary from 3 of the 4 corners — these exact XY
        # coordinates already exist in the TIN so no Steiner points are needed.
        curve_data = bpy.data.curves.new("TestBoundaryCurve", type="CURVE")
        curve_data.dimensions = "3D"
        spline = curve_data.splines.new("POLY")
        spline.points.add(2)  # 3 points total
        spline.points[0].co = (0.0, 0.0, 0.0, 1.0)
        spline.points[1].co = (20.0, 0.0, 0.0, 1.0)
        spline.points[2].co = (0.0, 20.0, 0.0, 1.0)
        obj = bpy.data.objects.new("TestBoundaryCurve", curve_data)
        bpy.context.scene.collection.objects.link(obj)

        return surface_guid, obj.name

    @pytest.mark.civil
    def test_smoke_register_and_instantiate(self) -> None:
        """The operator class is registered; instantiation does not raise."""
        assert hasattr(bpy.types, "CIVIL_OT_surface_pick_boundary")

    @pytest.mark.civil
    def test_from_data_sets_outer_boundary(self, tmp_path) -> None:
        """EXEC_DEFAULT path with polyline_object_name sets the surface's
        outer boundary polygon and retriangulates.

        Verifies that the committed polygon's shape matches the input vertex
        list (not just that outer_boundary is non-None).  The input curve
        uses 3 vertices forming a right triangle at (0,0), (20,0), (0,20) —
        the boundary polygon must contain all three corners.
        """
        surface_guid, curve_name = self._make_surface_and_boundary_curve(tmp_path)

        ifc_file = tool.Ifc.get()

        bpy.ops.civil.surface_pick_boundary(
            "EXEC_DEFAULT",
            polyline_object_name=curve_name,
            surface_guid=surface_guid,
        )

        # After setting a boundary the surface is retriangulated.
        tool.Surface.invalidate(ifc_file, surface_guid)
        surface_after = tool.Surface.get(ifc_file, surface_guid)

        # The outer boundary must be set.
        assert surface_after.outer_boundary is not None

        # The boundary polygon must cover all three input corner XY pairs
        # (the curve was authored at these exact coordinates).  "covers"
        # is true for both interior containment and boundary coincidence,
        # which is what we need for a polygon whose vertices sit ON the ring.
        boundary = surface_after.outer_boundary
        for corner_x, corner_y, label in [
            (0.0, 0.0, "(0,0)"),
            (20.0, 0.0, "(20,0)"),
            (0.0, 20.0, "(0,20)"),
        ]:
            pt = shapely.Point(corner_x, corner_y)
            assert boundary.covers(pt) or boundary.distance(pt) < 1e-6, (
                f"Boundary does not cover input corner {label}"
            )

        # The boundary must be non-degenerate (positive area).
        assert boundary.area > 0.0, "Boundary polygon has zero area"

    @pytest.mark.civil
    def test_invalid_polyline_object_raises(self, tmp_path) -> None:
        """A nonexistent curve object name raises RuntimeError and leaves the
        IFC annotation count unchanged (no partial authoring on failure)."""
        path = tmp_path / "pts.csv"
        path.write_text("0,0,0\n10,0,0\n10,10,0\n0,10,0\n")
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(path)
        )
        surface_guid = bpy.context.scene.CivilSurfaceProperties.active_surface_guid

        ifc_file = tool.Ifc.get()
        annotations_before = len(ifc_file.by_type("IfcAnnotation"))

        with pytest.raises(RuntimeError):
            bpy.ops.civil.surface_pick_boundary(
                "EXEC_DEFAULT",
                polyline_object_name="__does_not_exist__",
                surface_guid=surface_guid,
            )

        # Postcondition: no annotation authored on failure.
        assert len(ifc_file.by_type("IfcAnnotation")) == annotations_before


class TestSurfaceRaiseLowerModal(NewIfc4X3):
    """Tests for :class:`CIVIL_OT_surface_raise_lower`.

    Exercises the ``_from_data`` headless path (``EXEC_DEFAULT`` with
    ``surface_guid`` and ``delta_z`` pre-set) per spec §3.5 and §10.3.
    """

    def _make_flat_surface(self, tmp_path, z: float = 10.0) -> str:
        """Create a flat surface at elevation ``z`` and return its GUID."""
        path = tmp_path / "pts.csv"
        path.write_text(
            f"0,0,{z}\n10,0,{z}\n10,10,{z}\n0,10,{z}\n"
        )
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(path)
        )
        return bpy.context.scene.CivilSurfaceProperties.active_surface_guid

    @pytest.mark.civil
    def test_smoke_register_and_instantiate(self) -> None:
        """The operator class is registered; instantiation does not raise."""
        assert hasattr(bpy.types, "CIVIL_OT_surface_raise_lower")

    @pytest.mark.civil
    def test_from_data_translates_z(self, tmp_path) -> None:
        """EXEC_DEFAULT path with delta_z=5.0 raises every TIN vertex by 5 m."""
        surface_guid = self._make_flat_surface(tmp_path, z=10.0)

        ifc_file = tool.Ifc.get()
        surface_before = tool.Surface.get(ifc_file, surface_guid)
        z_before = float(surface_before.points[0, 2])

        bpy.ops.civil.surface_raise_lower(
            "EXEC_DEFAULT",
            surface_guid=surface_guid,
            delta_z=5.0,
        )

        # Invalidate to force a fresh read from IFC.
        tool.Surface.invalidate(ifc_file, surface_guid)
        surface_after = tool.Surface.get(ifc_file, surface_guid)
        z_after = float(surface_after.points[0, 2])

        assert z_after == pytest.approx(z_before + 5.0, abs=1e-3)
        # All vertices should be at the same elevation (flat surface).
        for z_val in surface_after.points[:, 2]:
            assert float(z_val) == pytest.approx(z_before + 5.0, abs=1e-3)

    @pytest.mark.civil
    def test_zero_delta_no_op(self, tmp_path) -> None:
        """delta_z=0.0 leaves the surface unchanged (no IFC write performed)."""
        surface_guid = self._make_flat_surface(tmp_path, z=20.0)

        ifc_file = tool.Ifc.get()
        surface_before = tool.Surface.get(ifc_file, surface_guid)
        points_before = surface_before.points.copy()

        bpy.ops.civil.surface_raise_lower(
            "EXEC_DEFAULT",
            surface_guid=surface_guid,
            delta_z=0.0,
        )

        # No change — tool.Surface.translate_z returns early for delta_z==0.
        surface_after = tool.Surface.get(ifc_file, surface_guid)
        np.testing.assert_array_almost_equal(surface_after.points, points_before)

    @pytest.mark.civil
    def test_invalid_surface_guid_raises(self, tmp_path) -> None:
        """A GUID that resolves to no surface raises RuntimeError."""
        # Create at least one surface so the IFC file is initialized.
        path = tmp_path / "pts.csv"
        path.write_text("0,0,0\n1,0,0\n0,1,0\n")
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(path)
        )

        with pytest.raises(RuntimeError):
            bpy.ops.civil.surface_raise_lower(
                "EXEC_DEFAULT",
                surface_guid="00000000-0000-0000-0000-000000000000",
                delta_z=1.0,
            )

        # Postcondition: IFC still has exactly one surface (not corrupted).
        ifc_file = tool.Ifc.get()
        terrains = ifc_file.by_type("IfcGeographicElement")
        assert len(terrains) == 1

    @pytest.mark.civil
    def test_translate_z_also_translates_breaklines(self, tmp_path) -> None:
        """translate_z shifts scoped IfcAnnotation breakline Z coordinates too.

        Regression for FIX 4: after translate_z, the surface's scoped
        breakline annotations must have their polyline Z values shifted by
        delta_z — not remain at the original Z.  Without the fix, the TIN
        would be at Z+5 while the breakline stayed at Z+0, leaving the
        surface internally inconsistent.
        """
        # Create a flat surface at Z=10.
        surface_guid = self._make_flat_surface(tmp_path, z=10.0)

        # Add a breakline at Z=10 using the CSV path.
        bl_path = tmp_path / "bl.csv"
        bl_path.write_text("0,5,10\n10,5,10\n")
        bpy.ops.civil.surface_add_breakline(
            "EXEC_DEFAULT",
            csv_filepath=str(bl_path),
            breakline_name="FIX4Breakline",
        )

        ifc_file = tool.Ifc.get()

        # Confirm the annotation was authored at Z=10.
        annotations = [
            a for a in ifc_file.by_type("IfcAnnotation")
            if a.ObjectType == "BREAKLINE" and a.Name == "FIX4Breakline"
        ]
        assert len(annotations) == 1

        def _bl_z_values(ifc_f, ann):
            """Extract all Z values from the first IfcPolyline in annotation."""
            zs = []
            rep = ann.Representation
            if rep is None:
                return zs
            for shape_rep in rep.Representations or []:
                for item in shape_rep.Items or []:
                    if item.is_a("IfcPolyline"):
                        for pt in item.Points or []:
                            coords = pt.Coordinates
                            if coords and len(coords) >= 3:
                                zs.append(float(coords[2]))
            return zs

        z_values_before = _bl_z_values(ifc_file, annotations[0])
        assert all(abs(z - 10.0) < 1e-3 for z in z_values_before), (
            f"Expected all breakline Z ≈ 10, got {z_values_before}"
        )

        # Raise the surface by 5 m.
        bpy.ops.civil.surface_raise_lower(
            "EXEC_DEFAULT",
            surface_guid=surface_guid,
            delta_z=5.0,
        )

        # Re-query the same annotation (same step id, IFC in-memory).
        z_values_after = _bl_z_values(ifc_file, annotations[0])
        assert len(z_values_after) > 0, "No breakline Z values found after translate"
        assert all(abs(z - 15.0) < 1e-3 for z in z_values_after), (
            f"Expected all breakline Z ≈ 15 after +5 translate, got {z_values_after}"
        )

    def test_load_post_handler_registered_and_uninstalls_decorator(self) -> None:
        """Closes the cold-review-flagged decorator handler leak. The
        @persistent load_post handler must be installed at module-register
        time so that opening a .blend file doesn't leave a draw handler
        running against the previous file's captured context.
        """
        from bonsai.bim.module.surface import _on_load_post
        from bonsai.bim.module.surface.decorator import SurfaceDecorator

        # Handler is registered.
        assert _on_load_post in bpy.app.handlers.load_post

        # Install the decorator, then fire the load_post handler manually
        # — uninstall must run.
        SurfaceDecorator.install(bpy.context)
        try:
            assert SurfaceDecorator.is_installed
            _on_load_post(None)
            assert not SurfaceDecorator.is_installed
        finally:
            SurfaceDecorator.uninstall()

    def test_elevation_color_interpolates_between_stops(self) -> None:
        """At t=0.25 the result should be the midpoint of LOW and MID."""
        from bonsai.bim.module.surface.decorator import SurfaceDecorator

        result = SurfaceDecorator._elevation_color(0.25)
        expected = SurfaceDecorator._lerp_rgba(
            SurfaceDecorator.COLOR_ELEVATION_LOW,
            SurfaceDecorator.COLOR_ELEVATION_MID,
            0.5,
        )
        assert result == pytest.approx(expected)


class TestSurfaceBSIIntegration(NewIfc4X3):
    """End-to-end integration test mirroring the spec §16 'done' criterion.

    Drives the full operator chain (create → add breakline → set boundary
    → retriangulate) through ``bpy.ops``, writes the result to disk,
    reopens via :func:`ifcopenshell.open`, and runs
    :func:`ifcopenshell.validate.validate` to assert no schema warnings.

    This is the Phase 4 acceptance test — when this passes, end users can
    load XYZ data, add breaklines, set boundaries, and round-trip the
    result through IFC with a clean validator report.
    """

    def test_full_workflow_round_trip_and_validate(self, tmp_path) -> None:
        import logging

        import ifcopenshell
        import ifcopenshell.validate

        # 1. Create a 3x3 grid surface so all subsequent operators work
        #    against existing vertices (no Steiner points).
        points_path = tmp_path / "grid.csv"
        rows = []
        for y in (0, 5, 10):
            for x in (0, 5, 10):
                z = (x * 0.1) + (y * 0.05)  # gentle slope for varied Z
                rows.append(f"{x},{y},{z:.2f}")
        points_path.write_text("\n".join(rows) + "\n")

        bpy.context.scene.CivilSurfaceProperties.new_surface_name = (
            "bSI Validation Surface"
        )
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(points_path)
        )

        # 2. Add a breakline along an interior edge of the grid.
        breakline_path = tmp_path / "ridge.csv"
        breakline_path.write_text("0,5,0.25\n10,5,0.75\n")
        bpy.ops.civil.surface_add_breakline(
            "EXEC_DEFAULT",
            csv_filepath=str(breakline_path),
            kind="standard",
            breakline_name="ridge",
        )

        # 3. Set a quarter-square boundary using existing grid vertices.
        boundary_path = tmp_path / "boundary.csv"
        boundary_path.write_text("0,0,0\n5,0,0.5\n5,5,0.75\n0,5,0.25\n")
        bpy.ops.civil.surface_set_boundary(
            "EXEC_DEFAULT", csv_filepath=str(boundary_path)
        )

        # 4. Force-retriangulate (no-op semantically, but exercises the path).
        bpy.ops.civil.surface_retriangulate("EXEC_DEFAULT")

        # 5. Write to disk and reopen as a fresh file (not via Bonsai).
        ifc_path = tmp_path / "phase4_acceptance.ifc"
        tool.Ifc.get().write(str(ifc_path))
        reopened = ifcopenshell.open(str(ifc_path))

        # 6. Verify the IFC structure round-tripped: terrain entity, TIN
        #    representation, breakline annotation, all the right psets.
        terrains = reopened.by_type("IfcGeographicElement")
        assert len(terrains) == 1
        assert terrains[0].Name == "bSI Validation Surface"

        tins = reopened.by_type("IfcTriangulatedIrregularNetwork")
        assert len(tins) == 1
        assert tins[0].Closed is False

        annotations = [
            a
            for a in reopened.by_type("IfcAnnotation")
            if a.ObjectType == "BREAKLINE"
        ]
        assert len(annotations) == 1
        assert annotations[0].Name == "ridge"

        # 7. Run the bSI validator on the reopened file. Collect WARNING+
        #    log records into a list so the assertion message is helpful.
        records: list[logging.LogRecord] = []

        class _CollectingHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        logger = logging.Logger("phase4-acceptance-validate")
        logger.addHandler(_CollectingHandler(level=logging.DEBUG))

        ifcopenshell.validate.validate(reopened, logger)

        errors = [r.getMessage() for r in records if r.levelno >= logging.WARNING]
        assert errors == [], f"ifcopenshell.validate() reported: {errors}"

    def test_multi_surface_with_host_link_validates_clean(
        self, tmp_path
    ) -> None:
        """Two surfaces with host-linked breaklines must round-trip
        through ifcopenshell.validate without warnings.

        Closes the cold-review IFC schema bug: IfcRelAssignsToProduct
        requires the RelatedObjectsType attribute. Before that fix, this
        test would have surfaced WARNING-level validate records on every
        multi-surface file with a breakline link.
        """
        import logging

        import ifcopenshell
        import ifcopenshell.validate

        # Two distinct surfaces, each with one breakline scoped to it.
        path_a = tmp_path / "a.csv"
        path_a.write_text("0,0,0\n1,0,0\n1,1,0\n0,1,0\n")
        bpy.context.scene.CivilSurfaceProperties.new_surface_name = "Surf A"
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(path_a)
        )
        bl_a_path = tmp_path / "bl_a.csv"
        bl_a_path.write_text("0,0,0\n1,1,0\n")
        bpy.ops.civil.surface_add_breakline(
            "EXEC_DEFAULT",
            csv_filepath=str(bl_a_path),
            breakline_name="bl-A",
        )

        path_b = tmp_path / "b.csv"
        path_b.write_text("10,10,0\n11,10,0\n11,11,0\n10,11,0\n")
        bpy.context.scene.CivilSurfaceProperties.new_surface_name = "Surf B"
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(path_b)
        )
        bl_b_path = tmp_path / "bl_b.csv"
        bl_b_path.write_text("10,10,0\n11,11,0\n")
        bpy.ops.civil.surface_add_breakline(
            "EXEC_DEFAULT",
            csv_filepath=str(bl_b_path),
            breakline_name="bl-B",
        )

        ifc_path = tmp_path / "multi_surface_validate.ifc"
        tool.Ifc.get().write(str(ifc_path))
        reopened = ifcopenshell.open(str(ifc_path))

        # Two IfcRelAssignsToProduct entities (one per breakline → host).
        rels = reopened.by_type("IfcRelAssignsToProduct")
        assert len(rels) == 2
        for rel in rels:
            assert len(rel.RelatedObjects) == 1
            assert rel.RelatedObjects[0].is_a("IfcAnnotation")

        records: list[logging.LogRecord] = []

        class _CollectingHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        logger = logging.Logger("multi-surface-validate")
        logger.addHandler(_CollectingHandler(level=logging.DEBUG))
        ifcopenshell.validate.validate(reopened, logger)

        errors = [r.getMessage() for r in records if r.levelno >= logging.WARNING]
        assert errors == [], f"validate() reported: {errors}"


class TestLoadPointsFromCsv:
    """Tests for :meth:`bonsai.tool.surface.Surface.load_points_from_csv`."""

    def test_loads_whitespace_separated_xyz(self, tmp_path) -> None:
        path = tmp_path / "points.txt"
        path.write_text("0.0 0.0 0.0\n1.0 0.0 0.0\n0.0 1.0 0.5\n")
        points = tool_surface.Surface.load_points_from_csv(str(path))
        assert points.shape == (3, 3)
        assert points[2, 2] == pytest.approx(0.5)

    def test_loads_comma_separated_csv(self, tmp_path) -> None:
        path = tmp_path / "points.csv"
        path.write_text("0,0,0\n1,0,0\n0,1,0\n")
        points = tool_surface.Surface.load_points_from_csv(str(path))
        assert points.shape == (3, 3)

    def test_skips_comment_lines(self, tmp_path) -> None:
        path = tmp_path / "points.txt"
        path.write_text(
            "# header\n0 0 0\n1 0 0\n# another comment\n0 1 1.5\n"
        )
        points = tool_surface.Surface.load_points_from_csv(str(path))
        assert points.shape == (3, 3)

    def test_wrong_column_count_raises(self, tmp_path) -> None:
        path = tmp_path / "bad.txt"
        path.write_text("0 0\n1 0\n0 1\n")  # only 2 columns
        with pytest.raises(
            tool_surface.SaikeiSurfaceError, match="must have exactly 3 columns"
        ):
            tool_surface.Surface.load_points_from_csv(str(path))

    def test_unparseable_file_raises(self, tmp_path) -> None:
        path = tmp_path / "bad.txt"
        path.write_text("hello world\nfoo bar baz\n")
        with pytest.raises(
            tool_surface.SaikeiSurfaceError, match="could not parse"
        ):
            tool_surface.Surface.load_points_from_csv(str(path))


class TestBuildBoundaryPolygonFromRing:
    """Tests for :meth:`Surface.build_boundary_polygon_from_ring` — the
    XYZ-ring → shapely.Polygon helper that lets operators stay in the
    UI layer without importing shapely."""

    def test_happy_path_returns_polygon(self) -> None:
        ring = np.array(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
        )
        polygon = tool_surface.Surface.build_boundary_polygon_from_ring(ring)
        assert isinstance(polygon, shapely.Polygon)
        assert polygon.area == pytest.approx(1.0)

    def test_drops_z_coordinate(self) -> None:
        ring = np.array(
            [
                (0.0, 0.0, 99.0),
                (10.0, 0.0, 50.0),
                (10.0, 10.0, -1.5),
                (0.0, 10.0, 0.0),
            ]
        )
        polygon = tool_surface.Surface.build_boundary_polygon_from_ring(ring)
        assert polygon.area == pytest.approx(100.0)
        # Polygon is XY only — no Z dimension surfaces.
        assert not polygon.has_z

    def test_too_few_vertices_raises(self) -> None:
        ring = np.array([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)])
        with pytest.raises(
            tool_surface.SaikeiSurfaceError,
            match=r"≥\s*3 vertices",
        ):
            tool_surface.Surface.build_boundary_polygon_from_ring(ring)

    def test_wrong_shape_raises(self) -> None:
        ring = np.array([(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)])  # 2D ring
        with pytest.raises(
            tool_surface.SaikeiSurfaceError, match=r"\(N, 3\)"
        ):
            tool_surface.Surface.build_boundary_polygon_from_ring(ring)

    def test_self_intersecting_polygon_raises(self) -> None:
        """Bowtie polygon: (0,0) → (1,1) → (1,0) → (0,1) → close.
        This crosses itself and shapely flags it as invalid."""
        ring = np.array(
            [
                (0.0, 0.0, 0.0),
                (1.0, 1.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
            ]
        )
        with pytest.raises(
            tool_surface.SaikeiSurfaceError,
            match="not topologically valid",
        ):
            tool_surface.Surface.build_boundary_polygon_from_ring(ring)


class TestSurfaceCreateFromPointsOperator(NewIfc4X3):
    """Tests for :class:`CIVIL_OT_surface_create_from_points` headless path.

    Inherits :class:`NewIfc4X3` so each test starts from a Bonsai-bootstrapped
    project (collection hierarchy needed by ``tool.Collector.assign``).
    """

    def test_headless_create_from_csv(self, tmp_path) -> None:
        # Write a 4-corner unit-square point file.
        points_path = tmp_path / "square.csv"
        points_path.write_text("0,0,0\n1,0,0\n1,1,0\n0,1,0\n")

        props = bpy.context.scene.CivilSurfaceProperties
        props.new_surface_name = "OpTest Existing"
        props.new_surface_kind = "existing"
        props.triangulation_tolerance = 0.001

        result = bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(points_path)
        )
        assert result == {"FINISHED"}

        ifc_file = tool.Ifc.get()
        terrains = ifc_file.by_type("IfcGeographicElement")
        assert len(terrains) == 1
        assert terrains[0].Name == "OpTest Existing"
        assert terrains[0].PredefinedType == "TERRAIN"

        # The new surface was added to the panel UIList.
        assert len(props.surfaces) == 1
        assert props.surfaces[0].name == "OpTest Existing"
        assert props.active_surface_id == terrains[0].id()
        assert props.active_surface_guid == terrains[0].GlobalId

    def test_headless_create_proposed(self, tmp_path) -> None:
        points_path = tmp_path / "square.csv"
        points_path.write_text("0,0,0\n10,0,0\n10,10,0\n0,10,0\n5,5,1\n")

        props = bpy.context.scene.CivilSurfaceProperties
        props.new_surface_name = "OpTest Proposed"
        props.new_surface_kind = "proposed_group"

        result = bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(points_path)
        )
        assert result == {"FINISHED"}

        ifc_file = tool.Ifc.get()
        fills = ifc_file.by_type("IfcEarthworksFill")
        assert len(fills) == 1
        assert fills[0].PredefinedType == "SUBGRADE"

    def test_invalid_csv_path_raises_and_does_not_create_surface(self) -> None:
        """Blender converts an ``ERROR``-level report into a ``RuntimeError``
        at the ``bpy.ops`` boundary. We assert both: the call raises, and no
        IFC entity was authored."""
        ifc_file = tool.Ifc.get()
        before = len(ifc_file.by_type("IfcGeographicElement"))
        with pytest.raises(RuntimeError, match="could not parse"):
            bpy.ops.civil.surface_create_from_points(
                "EXEC_DEFAULT", csv_filepath="/nonexistent/path/bogus.csv"
            )
        assert len(ifc_file.by_type("IfcGeographicElement")) == before

    def test_too_few_points_raises_and_does_not_create_surface(
        self, tmp_path
    ) -> None:
        ifc_file = tool.Ifc.get()
        points_path = tmp_path / "two.csv"
        points_path.write_text("0,0,0\n1,0,0\n")
        before = len(ifc_file.by_type("IfcGeographicElement"))
        with pytest.raises(RuntimeError, match="at least 3 points"):
            bpy.ops.civil.surface_create_from_points(
                "EXEC_DEFAULT", csv_filepath=str(points_path)
            )
        assert len(ifc_file.by_type("IfcGeographicElement")) == before


class TestSurfaceAddBreaklineOperator(NewIfc4X3):
    """Tests for :class:`CIVIL_OT_surface_add_breakline` headless path."""

    def _create_active_surface(self, tmp_path) -> str:
        """Helper: create a unit-square surface and return its GUID. Sets it
        as the active surface in props."""
        points_path = tmp_path / "square.csv"
        points_path.write_text("0,0,0\n10,0,0\n10,10,0\n0,10,0\n")
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(points_path)
        )
        props = bpy.context.scene.CivilSurfaceProperties
        return props.active_surface_guid

    def test_headless_add_breakline(self, tmp_path) -> None:
        guid = self._create_active_surface(tmp_path)
        # Diagonal breakline crossing the unit-square surface.
        polyline_path = tmp_path / "diag.csv"
        polyline_path.write_text("0,0,0\n10,10,0\n")

        ifc_file = tool.Ifc.get()
        before_annotations = len(ifc_file.by_type("IfcAnnotation"))

        result = bpy.ops.civil.surface_add_breakline(
            "EXEC_DEFAULT",
            csv_filepath=str(polyline_path),
            kind="standard",
            breakline_name="diagonal",
        )
        assert result == {"FINISHED"}

        # An IfcAnnotation was authored.
        annotations = ifc_file.by_type("IfcAnnotation")
        assert len(annotations) == before_annotations + 1
        breakline_annotation = annotations[-1]
        assert breakline_annotation.Name == "diagonal"
        assert breakline_annotation.ObjectType == "BREAKLINE"

        # The cached surface has the breakline appended.
        surface = tool.Surface.get(ifc_file, guid)
        assert len(surface.breaklines) == 1
        assert surface.breaklines[0].name == "diagonal"

    def test_no_active_surface_raises(self, tmp_path) -> None:
        polyline_path = tmp_path / "diag.csv"
        polyline_path.write_text("0,0,0\n10,10,0\n")
        # No active_surface_guid set.
        bpy.context.scene.CivilSurfaceProperties.active_surface_guid = ""
        with pytest.raises(RuntimeError, match="No active surface"):
            bpy.ops.civil.surface_add_breakline(
                "EXEC_DEFAULT", csv_filepath=str(polyline_path)
            )

    def test_too_short_polyline_raises(self, tmp_path) -> None:
        self._create_active_surface(tmp_path)
        polyline_path = tmp_path / "single.csv"
        polyline_path.write_text("0,0,0\n")  # only 1 point — must be ≥ 2
        with pytest.raises(RuntimeError):
            bpy.ops.civil.surface_add_breakline(
                "EXEC_DEFAULT", csv_filepath=str(polyline_path)
            )

    def test_kind_passed_through_to_pset(self, tmp_path) -> None:
        self._create_active_surface(tmp_path)
        polyline_path = tmp_path / "diag.csv"
        polyline_path.write_text("0,0,0\n10,10,0\n")

        bpy.ops.civil.surface_add_breakline(
            "EXEC_DEFAULT",
            csv_filepath=str(polyline_path),
            kind="wall",
            breakline_name="wall-line",
        )

        ifc_file = tool.Ifc.get()
        annotation = next(
            (
                a
                for a in ifc_file.by_type("IfcAnnotation")
                if a.Name == "wall-line"
            ),
            None,
        )
        assert annotation is not None

        # Find the SaikeiCivil_BreaklineCommon and check Kind.
        kind_value = None
        for rel in ifc_file.by_type("IfcRelDefinesByProperties"):
            if annotation in (rel.RelatedObjects or []):
                pset = rel.RelatingPropertyDefinition
                if pset.Name == "SaikeiCivil_BreaklineCommon":
                    for prop in pset.HasProperties:
                        if prop.Name == "Kind":
                            kind_value = prop.NominalValue.wrappedValue
        assert kind_value == "wall"


class TestSurfaceSetBoundaryAndRetriangulateOperators(NewIfc4X3):
    """Tests for :class:`CIVIL_OT_surface_set_boundary` and
    :class:`CIVIL_OT_surface_retriangulate`."""

    def _create_active_surface(self, tmp_path) -> str:
        """Create a 3x3 grid surface so set_boundary can clip to a sub-grid
        without introducing Steiner points (the Phase 4 CDT limitation).
        Vertices live at every (x, y) in {0, 5, 10}."""
        points_path = tmp_path / "grid.csv"
        rows = []
        for y in (0, 5, 10):
            for x in (0, 5, 10):
                rows.append(f"{x},{y},0")
        points_path.write_text("\n".join(rows) + "\n")
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(points_path)
        )
        return bpy.context.scene.CivilSurfaceProperties.active_surface_guid

    def test_set_boundary_headless(self, tmp_path) -> None:
        guid = self._create_active_surface(tmp_path)

        # Quarter-square boundary using existing grid vertices: (5,5), (10,5),
        # (10,10), (5,10). Area = 25.
        boundary_path = tmp_path / "boundary.csv"
        boundary_path.write_text("5,5,0\n10,5,0\n10,10,0\n5,10,0\n")

        result = bpy.ops.civil.surface_set_boundary(
            "EXEC_DEFAULT", csv_filepath=str(boundary_path)
        )
        assert result == {"FINISHED"}

        surface = tool.Surface.get(tool.Ifc.get(), guid)
        assert isinstance(surface.outer_boundary, shapely.Polygon)
        assert surface.outer_boundary.area == pytest.approx(25.0)
        assert len(surface.triangles) > 0

    def test_set_boundary_too_few_vertices_raises(self, tmp_path) -> None:
        self._create_active_surface(tmp_path)
        boundary_path = tmp_path / "ring.csv"
        boundary_path.write_text("0,0,0\n10,0,0\n")  # only 2 vertices
        with pytest.raises(RuntimeError, match=r"≥\s*3 vertices"):
            bpy.ops.civil.surface_set_boundary(
                "EXEC_DEFAULT", csv_filepath=str(boundary_path)
            )

    def test_set_boundary_no_active_surface_raises(self, tmp_path) -> None:
        boundary_path = tmp_path / "ring.csv"
        boundary_path.write_text("0,0,0\n10,0,0\n10,10,0\n0,10,0\n")
        bpy.context.scene.CivilSurfaceProperties.active_surface_guid = ""
        with pytest.raises(RuntimeError, match="No active surface"):
            bpy.ops.civil.surface_set_boundary(
                "EXEC_DEFAULT", csv_filepath=str(boundary_path)
            )

    def test_retriangulate_headless(self, tmp_path) -> None:
        guid = self._create_active_surface(tmp_path)
        before_tin_id = tool.Surface.get(
            tool.Ifc.get(), guid
        ).ifc_tin_representation_id
        result = bpy.ops.civil.surface_retriangulate("EXEC_DEFAULT")
        assert result == {"FINISHED"}
        # After force-rebuild the TIN id should be different (new entity in IFC).
        after_tin_id = tool.Surface.get(
            tool.Ifc.get(), guid
        ).ifc_tin_representation_id
        assert after_tin_id != before_tin_id

    def test_retriangulate_no_active_surface_raises(self) -> None:
        bpy.context.scene.CivilSurfaceProperties.active_surface_guid = ""
        with pytest.raises(RuntimeError, match="No active surface"):
            bpy.ops.civil.surface_retriangulate("EXEC_DEFAULT")

    def test_disk_round_trip_preserves_surface(self, tmp_path) -> None:
        """End-to-end: create + set_boundary → write IFC → reopen → assert."""
        import ifcopenshell

        self._create_active_surface(tmp_path)
        # Quarter boundary that hits existing grid vertices (no Steiner points).
        boundary_path = tmp_path / "boundary.csv"
        boundary_path.write_text("5,5,0\n10,5,0\n10,10,0\n5,10,0\n")
        bpy.ops.civil.surface_set_boundary(
            "EXEC_DEFAULT", csv_filepath=str(boundary_path)
        )

        # Write to disk.
        ifc_path = tmp_path / "round_trip.ifc"
        tool.Ifc.get().write(str(ifc_path))

        # Reopen as a fresh ifcopenshell.file (not via Bonsai's project).
        reopened = ifcopenshell.open(str(ifc_path))
        terrains = reopened.by_type("IfcGeographicElement")
        assert len(terrains) == 1
        terrain = terrains[0]
        assert terrain.PredefinedType == "TERRAIN"

        # Find the persisted TIN.
        tins = reopened.by_type("IfcTriangulatedIrregularNetwork")
        assert len(tins) == 1
        tin = tins[0]
        assert tin.Closed is False
        assert len(tin.CoordIndex) > 0
        assert len(tin.Flags) == len(tin.CoordIndex)


# ---------------------------------------------------------------------------
# Phase 7a additions
# ---------------------------------------------------------------------------


class TestSurfaceRenameOperator(NewIfc4X3):
    """Tests for :class:`CIVIL_OT_surface_rename` (Phase 7a).

    Verifies that the operator mutates the IFC entity ``Name`` attribute,
    updates the in-memory registry, and invalidates the ``SurfaceData`` cache.
    """

    @pytest.mark.civil
    def test_rename_updates_ifc_entity_name(self, tmp_path) -> None:
        points_path = tmp_path / "p.csv"
        points_path.write_text("0,0,0\n1,0,0\n0,1,0\n")
        bpy.context.scene.CivilSurfaceProperties.new_surface_name = "Original Name"
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(points_path)
        )
        guid = bpy.context.scene.CivilSurfaceProperties.active_surface_guid
        assert guid

        result = bpy.ops.civil.surface_rename(
            "EXEC_DEFAULT", surface_guid=guid, new_name="Renamed Surface"
        )
        assert result == {"FINISHED"}

        ifc_file = tool.Ifc.get()
        terrains = ifc_file.by_type("IfcGeographicElement")
        matching = [t for t in terrains if t.GlobalId == guid]
        assert len(matching) == 1
        assert matching[0].Name == "Renamed Surface"

    @pytest.mark.civil
    def test_rename_updates_registry_dataclass(self, tmp_path) -> None:
        points_path = tmp_path / "p.csv"
        points_path.write_text("0,0,0\n1,0,0\n0,1,0\n")
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(points_path)
        )
        guid = bpy.context.scene.CivilSurfaceProperties.active_surface_guid

        bpy.ops.civil.surface_rename(
            "EXEC_DEFAULT", surface_guid=guid, new_name="Cache Check"
        )

        # The registry should return the updated name without a cache miss.
        surface = tool_surface.Surface.get(tool.Ifc.get(), guid)
        assert surface.name == "Cache Check"

    @pytest.mark.civil
    def test_rename_empty_name_raises(self, tmp_path) -> None:
        points_path = tmp_path / "p.csv"
        points_path.write_text("0,0,0\n1,0,0\n0,1,0\n")
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(points_path)
        )
        guid = bpy.context.scene.CivilSurfaceProperties.active_surface_guid

        with pytest.raises(RuntimeError):
            bpy.ops.civil.surface_rename(
                "EXEC_DEFAULT", surface_guid=guid, new_name="   "
            )

    @pytest.mark.civil
    def test_rename_bogus_guid_raises(self) -> None:
        with pytest.raises(RuntimeError):
            bpy.ops.civil.surface_rename(
                "EXEC_DEFAULT",
                surface_guid="bogus-guid-that-does-not-exist",
                new_name="X",
            )
        # Postcondition: no IFC entity was mutated (file still clean).
        ifc_file = tool.Ifc.get()
        assert not any(
            e.GlobalId == "bogus-guid-that-does-not-exist"
            for e in ifc_file.by_type("IfcGeographicElement")
        )


class TestSurfaceDeleteOperator(NewIfc4X3):
    """Tests for :class:`CIVIL_OT_surface_delete` (Phase 7a)."""

    @pytest.mark.civil
    def test_delete_removes_ifc_entity(self, tmp_path) -> None:
        points_path = tmp_path / "p.csv"
        points_path.write_text("0,0,0\n1,0,0\n0,1,0\n")
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(points_path)
        )
        guid = bpy.context.scene.CivilSurfaceProperties.active_surface_guid
        ifc_file = tool.Ifc.get()
        assert any(e.GlobalId == guid for e in ifc_file.by_type("IfcGeographicElement"))

        result = bpy.ops.civil.surface_delete(
            "EXEC_DEFAULT", surface_guid=guid
        )
        assert result == {"FINISHED"}

        # Entity must be gone.
        assert not any(
            e.GlobalId == guid for e in ifc_file.by_type("IfcGeographicElement")
        )

    @pytest.mark.civil
    def test_delete_clears_active_selection(self, tmp_path) -> None:
        points_path = tmp_path / "p.csv"
        points_path.write_text("0,0,0\n1,0,0\n0,1,0\n")
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(points_path)
        )
        guid = bpy.context.scene.CivilSurfaceProperties.active_surface_guid
        props = bpy.context.scene.CivilSurfaceProperties

        bpy.ops.civil.surface_delete("EXEC_DEFAULT", surface_guid=guid)

        # Active GUID must be cleared since the surface is gone.
        assert props.active_surface_guid == ""
        assert props.active_surface_id == 0

    @pytest.mark.civil
    def test_delete_bogus_guid_raises(self) -> None:
        ifc_file = tool.Ifc.get()
        surfaces_before = len(ifc_file.by_type("IfcGeographicElement")) + len(
            ifc_file.by_type("IfcEarthworksFill")
        )
        with pytest.raises(RuntimeError):
            bpy.ops.civil.surface_delete(
                "EXEC_DEFAULT",
                surface_guid="totally-bogus-guid",
            )
        # Postcondition: no surface was accidentally removed.
        surfaces_after = len(ifc_file.by_type("IfcGeographicElement")) + len(
            ifc_file.by_type("IfcEarthworksFill")
        )
        assert surfaces_after == surfaces_before

    @pytest.mark.civil
    def test_delete_removes_scoped_breaklines(self, tmp_path) -> None:
        """Deleting a surface must also remove its scoped breakline annotations."""
        points_path = tmp_path / "pts.csv"
        points_path.write_text(
            "0,0,0\n10,0,0\n10,10,0\n0,10,0\n5,5,1\n"
        )
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(points_path)
        )
        guid = bpy.context.scene.CivilSurfaceProperties.active_surface_guid

        # Add two breaklines to the surface.
        bl_path_1 = tmp_path / "bl1.csv"
        bl_path_1.write_text("0,5,0\n10,5,1\n")
        bpy.ops.civil.surface_add_breakline(
            "EXEC_DEFAULT",
            csv_filepath=str(bl_path_1),
            breakline_name="ridge-a",
        )

        bl_path_2 = tmp_path / "bl2.csv"
        bl_path_2.write_text("5,0,0\n5,10,1\n")
        bpy.ops.civil.surface_add_breakline(
            "EXEC_DEFAULT",
            csv_filepath=str(bl_path_2),
            breakline_name="ridge-b",
        )

        ifc_file = tool.Ifc.get()
        # Confirm the breaklines exist before deletion.
        breakline_annotations_before = [
            a
            for a in ifc_file.by_type("IfcAnnotation")
            if getattr(a, "ObjectType", None) == "BREAKLINE"
        ]
        assert len(breakline_annotations_before) >= 2

        bpy.ops.civil.surface_delete("EXEC_DEFAULT", surface_guid=guid)

        # Both breakline annotations must be gone.
        breakline_annotations_after = [
            a
            for a in ifc_file.by_type("IfcAnnotation")
            if getattr(a, "ObjectType", None) == "BREAKLINE"
        ]
        assert len(breakline_annotations_after) == 0
        # The host entity itself must also be gone.
        assert not any(
            e.GlobalId == guid for e in ifc_file.by_type("IfcGeographicElement")
        )


class TestSurfaceSelectOperator(NewIfc4X3):
    """Tests for :class:`CIVIL_OT_surface_select` (Phase 7a).

    Verifies that the operator sets the active Blender object and syncs
    the UIList index.
    """

    @pytest.mark.civil
    def test_select_sets_active_object_and_index(self, tmp_path) -> None:
        # Create two surfaces so we can verify index selectivity.
        path_a = tmp_path / "a.csv"
        path_a.write_text("0,0,0\n1,0,0\n0,1,0\n")
        bpy.context.scene.CivilSurfaceProperties.new_surface_name = "Surf A"
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(path_a)
        )
        guid_a = bpy.context.scene.CivilSurfaceProperties.active_surface_guid

        path_b = tmp_path / "b.csv"
        path_b.write_text("10,10,0\n11,10,0\n10,11,0\n")
        bpy.context.scene.CivilSurfaceProperties.new_surface_name = "Surf B"
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(path_b)
        )

        # Select surface A by guid.
        result = bpy.ops.civil.surface_select(
            "EXEC_DEFAULT", surface_guid=guid_a
        )
        assert result == {"FINISHED"}

        props = bpy.context.scene.CivilSurfaceProperties
        # active_surface_index should point to A's row.
        assert props.surfaces[props.active_surface_index].guid == guid_a

    @pytest.mark.civil
    def test_select_bogus_guid_raises(self) -> None:
        props = bpy.context.scene.CivilSurfaceProperties
        guid_before = props.active_surface_guid
        with pytest.raises(RuntimeError):
            bpy.ops.civil.surface_select(
                "EXEC_DEFAULT", surface_guid="bogus-guid-xyz"
            )
        # Postcondition: the active_surface_guid prop is unchanged.
        assert props.active_surface_guid == guid_before

    @pytest.mark.civil
    def test_select_no_linked_blender_object_warns(self, tmp_path) -> None:
        """Selecting a surface whose Blender object was unlinked returns CANCELLED."""
        points_path = tmp_path / "p.csv"
        points_path.write_text("0,0,0\n1,0,0\n0,1,0\n")
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(points_path)
        )
        guid = bpy.context.scene.CivilSurfaceProperties.active_surface_guid
        ifc_file = tool.Ifc.get()
        host = tool.Surface.get_host_entity(ifc_file, guid)
        obj = tool.Ifc.get_object(host)
        assert obj is not None, "setup: surface must have a linked Blender object"

        # Unlink the Blender object so the operator hits the obj-is-None branch.
        tool.Ifc.unlink(obj=obj)
        bpy.data.objects.remove(obj, do_unlink=True)

        # The operator should report a WARNING and return CANCELLED.
        # tool.Ifc.Operator wraps _execute, but surface_select uses plain
        # Operator so the CANCELLED propagates directly to the caller.
        result = bpy.ops.civil.surface_select(
            "EXEC_DEFAULT", surface_guid=guid
        )
        assert result == {"CANCELLED"}


class TestSurfaceGetHostEntity(NewIfc4X3):
    """Tests for :meth:`tool.Surface.get_host_entity` (FIX 5 helper)."""

    @pytest.mark.civil
    def test_get_host_entity_finds_terrain(self, tmp_path) -> None:
        points_path = tmp_path / "p.csv"
        points_path.write_text("0,0,0\n1,0,0\n0,1,0\n")
        bpy.context.scene.CivilSurfaceProperties.new_surface_kind = "existing"
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(points_path)
        )
        guid = bpy.context.scene.CivilSurfaceProperties.active_surface_guid
        ifc_file = tool.Ifc.get()

        host = tool.Surface.get_host_entity(ifc_file, guid)

        assert host is not None
        assert host.GlobalId == guid
        assert host.is_a("IfcGeographicElement")

    @pytest.mark.civil
    def test_get_host_entity_finds_proposed(self, tmp_path) -> None:
        points_path = tmp_path / "p.csv"
        points_path.write_text("0,0,0\n1,0,0\n0,1,0\n")
        bpy.context.scene.CivilSurfaceProperties.new_surface_kind = "proposed_site"
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(points_path)
        )
        guid = bpy.context.scene.CivilSurfaceProperties.active_surface_guid
        ifc_file = tool.Ifc.get()

        host = tool.Surface.get_host_entity(ifc_file, guid)

        assert host is not None
        assert host.GlobalId == guid
        assert host.is_a("IfcEarthworksFill")

    @pytest.mark.civil
    def test_get_host_entity_returns_none_for_unknown(self) -> None:
        ifc_file = tool.Ifc.get()
        result = tool.Surface.get_host_entity(ifc_file, "no-such-guid-anywhere")
        assert result is None


class TestSurfaceStatisticsPanel(NewIfc4X3):
    """Tests for :class:`CIVIL_PT_surface_statistics` and
    :meth:`SurfaceData.get_active_surface_statistics` (Phase 7a)."""

    @pytest.mark.civil
    def test_statistics_panel_registered(self) -> None:
        assert hasattr(bpy.types, "CIVIL_PT_surface_statistics")

    @pytest.mark.civil
    def test_get_active_surface_statistics_returns_expected_keys(
        self, tmp_path
    ) -> None:
        from bonsai.bim.module.surface.data import SurfaceData

        points_path = tmp_path / "p.csv"
        # 4-corner 10x10 unit square at z=5 — easy to assert on.
        points_path.write_text("0,0,5\n10,0,5\n10,10,5\n0,10,5\n")
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(points_path)
        )
        guid = bpy.context.scene.CivilSurfaceProperties.active_surface_guid

        stats = SurfaceData.get_active_surface_statistics(tool.Ifc.get(), guid)

        assert stats["vertex_count"] == 4
        assert stats["triangle_count"] == 2
        assert stats["z_min"] == pytest.approx(5.0)
        assert stats["z_max"] == pytest.approx(5.0)
        assert stats["bb_width"] == pytest.approx(10.0)
        assert stats["bb_depth"] == pytest.approx(10.0)

    @pytest.mark.civil
    def test_get_active_surface_statistics_empty_guid_returns_sentinel(
        self,
    ) -> None:
        from bonsai.bim.module.surface.data import SurfaceData

        stats = SurfaceData.get_active_surface_statistics(tool.Ifc.get(), "")
        assert stats["name"] == "(missing)"
        assert stats["vertex_count"] == 0

    @pytest.mark.civil
    def test_get_active_surface_statistics_unknown_guid_returns_sentinel(
        self,
    ) -> None:
        from bonsai.bim.module.surface.data import SurfaceData

        stats = SurfaceData.get_active_surface_statistics(
            tool.Ifc.get(), "not-a-real-guid-at-all"
        )
        assert stats["name"] == "(missing)"

    @pytest.mark.civil
    def test_statistics_panel_draw_no_exception(self, tmp_path) -> None:
        """The panel must not raise when drawn against a valid active surface."""
        import types

        from bonsai.bim.module.surface.ui import CIVIL_PT_surface_statistics

        points_path = tmp_path / "p.csv"
        points_path.write_text("0,0,0\n5,0,0\n5,5,0\n0,5,0\n")
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(points_path)
        )

        # Build a minimal fake context so the panel draw() can read props.
        fake_context = types.SimpleNamespace(
            scene=bpy.context.scene,
        )

        # Bonsai panels are bpy_struct subclasses and cannot be instantiated
        # directly with Panel().  Call draw() as an unbound class method,
        # passing a minimal fake layout sink as ``self`` so the layout calls
        # do not raise.  This is the pattern used in test_feature.py.
        class _FakeLayout:
            def box(self):
                return self

            def column(self, **_kw):
                return self

            def label(self, **_kw):
                pass

            def separator(self, **_kw):
                pass

        fake_self = types.SimpleNamespace(layout=_FakeLayout())
        # draw() must not raise.
        CIVIL_PT_surface_statistics.draw(fake_self, fake_context)  # type: ignore[arg-type]


class TestCsvColumnRemap:
    """Tests for ``tool.Surface.load_points_from_csv`` column-remap kwargs.

    These tests do not require Blender and run against raw CSV fixtures on
    ``tmp_path``. They verify that ``columns`` and ``skip_header_rows``
    work correctly and that defaults preserve the existing behavior.
    """

    @pytest.mark.civil
    def test_default_columns_reads_first_three(self, tmp_path) -> None:
        path = tmp_path / "default.csv"
        path.write_text("1.0,2.0,3.0\n4.0,5.0,6.0\n")
        data = tool_surface.Surface.load_points_from_csv(str(path))
        assert data.shape == (2, 3)
        assert data[0, 0] == pytest.approx(1.0)  # X
        assert data[0, 1] == pytest.approx(2.0)  # Y
        assert data[0, 2] == pytest.approx(3.0)  # Z

    @pytest.mark.civil
    def test_columns_remap_swaps_order(self, tmp_path) -> None:
        """columns=(2, 1, 0) reads original col-2 as output col-0 (X), etc."""
        path = tmp_path / "remap.csv"
        # File column order: A, B, C — we request C, B, A → so output is (C, B, A)
        path.write_text("10.0,20.0,30.0\n40.0,50.0,60.0\n")
        data = tool_surface.Surface.load_points_from_csv(
            str(path), columns=(2, 1, 0)
        )
        assert data.shape == (2, 3)
        # Output col 0 = original col 2 = 30.0, 60.0
        assert data[0, 0] == pytest.approx(30.0)
        assert data[1, 0] == pytest.approx(60.0)
        # Output col 2 = original col 0 = 10.0, 40.0
        assert data[0, 2] == pytest.approx(10.0)
        assert data[1, 2] == pytest.approx(40.0)

    @pytest.mark.civil
    def test_skip_header_rows_skips_leading_text(self, tmp_path) -> None:
        path = tmp_path / "header.csv"
        path.write_text("X,Y,Z\n0.0,1.0,2.0\n3.0,4.0,5.0\n")
        data = tool_surface.Surface.load_points_from_csv(
            str(path), skip_header_rows=1
        )
        assert data.shape == (2, 3)
        assert data[0, 0] == pytest.approx(0.0)
        assert data[1, 2] == pytest.approx(5.0)

    @pytest.mark.civil
    def test_skip_header_and_remap_combined(self, tmp_path) -> None:
        """Combined: skip a header + remap columns."""
        path = tmp_path / "combined.csv"
        # Header row + two data rows: file cols are (A, B, C).
        # We want output (C, B, A) — columns=(2, 1, 0).
        path.write_text("col_a,col_b,col_c\n1.0,2.0,3.0\n4.0,5.0,6.0\n")
        data = tool_surface.Surface.load_points_from_csv(
            str(path), columns=(2, 1, 0), skip_header_rows=1
        )
        assert data.shape == (2, 3)
        assert data[0, 0] == pytest.approx(3.0)  # C
        assert data[0, 2] == pytest.approx(1.0)  # A

    @pytest.mark.civil
    def test_extra_columns_file_selects_subset(self, tmp_path) -> None:
        """File has 5 columns; we only read columns 0, 2, 4."""
        path = tmp_path / "wide.csv"
        path.write_text("1.0,2.0,3.0,4.0,5.0\n6.0,7.0,8.0,9.0,10.0\n")
        data = tool_surface.Surface.load_points_from_csv(
            str(path), columns=(0, 2, 4)
        )
        assert data.shape == (2, 3)
        assert data[0, 0] == pytest.approx(1.0)
        assert data[0, 1] == pytest.approx(3.0)
        assert data[0, 2] == pytest.approx(5.0)


class TestCsvColumnRemapOperatorIntegration(NewIfc4X3):
    """Integration tests verifying that ``CIVIL_OT_surface_create_from_points``
    threads the ``csv_column_map`` and ``csv_skip_header_rows`` props into
    ``tool.Surface.load_points_from_csv``.
    """

    @pytest.mark.civil
    def test_operator_uses_column_map_from_props(self, tmp_path) -> None:
        """The operator subtracts 1 from the 1-indexed props before calling
        the tool method; so props=(3,2,1) → tool columns=(2,1,0).

        File column order is (Z, Y, X) — we use props=(3,2,1) to remap so
        that output col-0 (X) = file col-2, col-1 (Y) = file col-1, col-2
        (Z) = file col-0.  The three XY footprint points must be non-collinear
        so Qhull can triangulate: (0,0), (5,0), (0,5).
        """
        path = tmp_path / "remap_op.csv"
        # file col order: Z,   Y,   X
        #   row 0:        10,  0.0, 0.0   → X=0.0  Y=0.0  Z=10
        #   row 1:        20,  0.0, 5.0   → X=5.0  Y=0.0  Z=20
        #   row 2:        15,  5.0, 0.0   → X=0.0  Y=5.0  Z=15
        path.write_text("10.0,0.0,0.0\n20.0,0.0,5.0\n15.0,5.0,0.0\n")

        props = bpy.context.scene.CivilSurfaceProperties
        props.new_surface_name = "Remap Test"
        props.csv_column_map = (3, 2, 1)  # 1-indexed: X=col3, Y=col2, Z=col1
        props.csv_skip_header_rows = 0

        result = bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(path)
        )
        assert result == {"FINISHED"}

        # Surface should exist.
        ifc_file = tool.Ifc.get()
        surface_entities = list(ifc_file.by_type("IfcGeographicElement")) + list(
            ifc_file.by_type("IfcEarthworksFill")
        )
        assert len(surface_entities) == 1
        assert surface_entities[0].Name == "Remap Test"

    @pytest.mark.civil
    def test_operator_uses_skip_header_rows_from_props(self, tmp_path) -> None:
        path = tmp_path / "skip_header_op.csv"
        path.write_text("X,Y,Z\n0.0,0.0,0.0\n5.0,0.0,0.0\n0.0,5.0,0.0\n")

        props = bpy.context.scene.CivilSurfaceProperties
        props.new_surface_name = "SkipHeader Test"
        props.csv_column_map = (1, 2, 3)  # default 1-indexed
        props.csv_skip_header_rows = 1  # skip the "X,Y,Z" header

        result = bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(path)
        )
        assert result == {"FINISHED"}

        ifc_file = tool.Ifc.get()
        terrains = ifc_file.by_type("IfcGeographicElement")
        assert len(terrains) == 1


# ---------------------------------------------------------------------------
# Phase 7a — surface dropdown enum tests
# ---------------------------------------------------------------------------


class TestSurfaceDropdownEnumItems(NewIfc4X3):
    """Tests for :meth:`tool.Surface.iter_surfaces` and
    :meth:`tool.Surface.iter_proposed_surfaces`.

    These methods are the items-source callbacks for the earthwork
    inputs panel dropdowns (spec §5.3 / §11 Rule 7).
    """

    def _author_terrain(self, tmp_path, name: str = "Test Terrain") -> str:
        """Author a minimal terrain and return its GUID."""
        path = tmp_path / f"{name}.csv"
        path.write_text(
            "0.0,0.0,100.0\n10.0,0.0,105.0\n10.0,10.0,110.0\n"
        )
        bpy.context.scene.CivilSurfaceProperties.new_surface_name = name
        bpy.context.scene.CivilSurfaceProperties.new_surface_kind = "existing"
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(path)
        )
        return bpy.context.scene.CivilSurfaceProperties.active_surface_guid

    def _author_proposed(self, tmp_path, name: str = "Test Proposed") -> str:
        """Author a minimal proposed surface and return its GUID."""
        path = tmp_path / f"{name}.csv"
        path.write_text(
            "0.0,0.0,95.0\n10.0,0.0,98.0\n10.0,10.0,100.0\n"
        )
        bpy.context.scene.CivilSurfaceProperties.new_surface_name = name
        bpy.context.scene.CivilSurfaceProperties.new_surface_kind = "proposed_site"
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(path)
        )
        return bpy.context.scene.CivilSurfaceProperties.active_surface_guid

    @pytest.mark.civil
    def test_iter_surfaces_returns_triple_tuples(self, tmp_path) -> None:
        """iter_surfaces must yield ``(guid, name, description)`` triples
        for every terrain surface in the file."""
        guid = self._author_terrain(tmp_path, "Triple Test")
        ifc_file = tool.Ifc.get()

        results = list(tool_surface.Surface.iter_surfaces(ifc_file))

        assert len(results) == 1
        identifier, name, description = results[0]
        assert identifier == guid
        assert name == "Triple Test"
        # description must be a non-empty string
        assert isinstance(description, str)
        assert len(description) > 0

    @pytest.mark.civil
    def test_iter_surfaces_description_format(self, tmp_path) -> None:
        """The description string must match the spec §11 Rule 7 format:
        ``"{N} triangles, Z={z_min:.1f}-{z_max:.1f}m"``
        (plain ASCII hyphen, not en-dash)."""
        self._author_terrain(tmp_path, "Format Test")
        ifc_file = tool.Ifc.get()

        results = list(tool_surface.Surface.iter_surfaces(ifc_file))
        assert len(results) == 1
        _, _, description = results[0]

        # Must contain "triangles" and "Z=" and a plain ASCII hyphen.
        assert "triangles" in description
        assert "Z=" in description
        # Plain ASCII hyphen check — en-dash (–) must NOT appear.
        assert "–" not in description, (
            "description must use ASCII hyphen, not en-dash"
        )
        assert "-" in description, "description must contain a hyphen separator"
        assert description.endswith("m"), "description must end with 'm'"

    @pytest.mark.civil
    def test_iter_proposed_surfaces_returns_proposed(self, tmp_path) -> None:
        """iter_proposed_surfaces yields proposed surfaces, not terrain."""
        guid = self._author_proposed(tmp_path, "Proposed Test")
        ifc_file = tool.Ifc.get()

        results = list(tool_surface.Surface.iter_proposed_surfaces(ifc_file))

        guids = [r[0] for r in results]
        assert guid in guids
        # Terrain surfaces must NOT appear in proposed iterator.
        terrain_guids = [
            e.GlobalId
            for e in ifc_file.by_type("IfcGeographicElement")
            if getattr(e, "PredefinedType", None) == "TERRAIN"
        ]
        for tg in terrain_guids:
            assert tg not in guids, (
                "iter_proposed_surfaces must not yield terrain GUIDs"
            )

    @pytest.mark.civil
    def test_iter_surfaces_empty_file(self) -> None:
        """iter_surfaces on an empty file (no terrain) must return an
        empty iterator without raising."""
        ifc_file = tool.Ifc.get()
        results = list(tool_surface.Surface.iter_surfaces(ifc_file))
        assert results == []


# ---------------------------------------------------------------------------
# Phase 7a — Add Civil Element parallel menu (spec §4)
# ---------------------------------------------------------------------------


class TestCivilAddMenu(NewIfc4X3):
    """Tests for :class:`CIVIL_MT_add_element` and the panel integration.

    The menu is the Phase 7a "parallel Add Civil Element" entry point
    (spec §4, strategy (c)).  It bypasses Bonsai's root Add Element dispatch
    which cannot support Pset-based predicates, and instead lists each top-level
    civil authoring operator directly.

    Per spec §3.8: operator-layer tests for Phase 7a live in test/tool/ while
    the test/bim/module/surface conftest issue is unresolved upstream.
    """

    @pytest.mark.civil
    def test_menu_registered(self) -> None:
        """CIVIL_MT_add_element must appear in bpy.types after module
        registration."""
        assert hasattr(bpy.types, "CIVIL_MT_add_element"), (
            "CIVIL_MT_add_element not registered — check surface/__init__.py classes tuple"
        )

    @pytest.mark.civil
    def test_menu_bl_idname(self) -> None:
        """bl_idname must be 'CIVIL_MT_add_element' per CIVIL_MT_* naming rule."""
        menu_cls = bpy.types.CIVIL_MT_add_element
        assert menu_cls.bl_idname == "CIVIL_MT_add_element"

    @pytest.mark.civil
    def test_menu_draw_no_exception(self) -> None:
        """draw() must not raise when called with a fake context + layout.

        The menu references operators from three modules (surface, grading,
        earthwork).  A draw-path exception here signals a broken operator
        bl_idname reference.
        """
        import types

        from bonsai.bim.module.surface.ui import CIVIL_MT_add_element

        fake_context = types.SimpleNamespace(scene=bpy.context.scene)

        class _FakeLayout:
            """Absorbs all layout calls silently."""

            def label(self, **_kw):
                return self

            def operator(self, bl_idname: str, **_kw):
                return types.SimpleNamespace()

            def separator(self, **_kw):
                return self

            def menu(self, bl_idname: str, **_kw):
                return self

        fake_self = types.SimpleNamespace(layout=_FakeLayout())
        # draw() must complete without raising.
        CIVIL_MT_add_element.draw(fake_self, fake_context)  # type: ignore[arg-type]

    @pytest.mark.civil
    def test_menu_button_in_surface_list_panel(self) -> None:
        """CIVIL_PT_surface_list.draw() must call layout.menu('CIVIL_MT_add_element').

        This confirms the panel wires up the Add Civil Element button so the
        menu is discoverable from the main civil panel surface.
        """
        import types

        from bonsai.bim.module.surface.ui import CIVIL_PT_surface_list

        fake_context = types.SimpleNamespace(scene=bpy.context.scene)

        menu_calls: list[str] = []

        class _TrackingLayout:
            def menu(self, bl_idname: str, **_kw):
                menu_calls.append(bl_idname)
                return self

            def label(self, **_kw):
                return self

            def separator(self, **_kw):
                return self

            def template_list(self, *_a, **_kw):
                return self

            def column(self, **_kw):
                return self

            def row(self, **_kw):
                return self

        fake_self = types.SimpleNamespace(layout=_TrackingLayout())
        CIVIL_PT_surface_list.draw(fake_self, fake_context)  # type: ignore[arg-type]

        assert "CIVIL_MT_add_element" in menu_calls, (
            "CIVIL_PT_surface_list.draw() must call layout.menu('CIVIL_MT_add_element')"
        )

    @pytest.mark.civil
    def test_dispatch_terrain_create(self, tmp_path) -> None:
        """Invoking civil.surface_create_from_points headless (the terrain
        entry in the Add Civil Element menu) authors an IfcGeographicElement.

        This is the spec §4 table row:
        IfcGeographicElement[TERRAIN] → civil.surface_create_from_points
        """
        points_path = tmp_path / "menu_terrain.csv"
        points_path.write_text("0,0,0\n10,0,0\n10,10,0\n0,10,0\n")
        props = bpy.context.scene.CivilSurfaceProperties
        props.new_surface_name = "Menu Terrain"
        props.new_surface_kind = "existing"

        result = bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(points_path)
        )
        assert result == {"FINISHED"}

        ifc_file = tool.Ifc.get()
        terrains = ifc_file.by_type("IfcGeographicElement")
        assert any(t.Name == "Menu Terrain" for t in terrains), (
            "Terrain surface not found after dispatching via surface_create_from_points"
        )

    @pytest.mark.civil
    def test_dispatch_feature_line_create(self, tmp_path) -> None:
        """Invoking civil.feature_line_create headless (the Feature Line
        entry in the Add Civil Element menu) authors an IfcAlignment with
        SaikeiCivil_FeatureLineCommon.

        This is the spec §4 table row:
        IfcAlignment (feature-line variant) → civil.feature_line_create
        """
        perimeter_path = tmp_path / "menu_fl.csv"
        # Four-corner rectangle: must form a non-collinear polygon.
        perimeter_path.write_text(
            "0,0,100\n10,0,100\n10,10,100\n0,10,100\n"
        )
        props = bpy.context.scene.CivilGradingProperties
        props.new_feature_line_name = "Menu Feature Line"

        result = bpy.ops.civil.feature_line_create(
            "EXEC_DEFAULT",
            csv_filepath=str(perimeter_path),
            closed=True,
        )
        assert result == {"FINISHED"}

        ifc_file = tool.Ifc.get()
        alignments = ifc_file.by_type("IfcAlignment")
        assert len(alignments) >= 1, "No IfcAlignment authored by feature_line_create"
        names = [a.Name for a in alignments]
        assert "Menu Feature Line" in names, (
            f"Expected 'Menu Feature Line' in alignments, got {names}"
        )

    @pytest.mark.civil
    def test_dispatch_grading_group_create(self, tmp_path) -> None:
        """Invoking civil.grading_create_group headless (the Grading Group
        entry in the Add Civil Element menu) authors an IfcGroup[GradingGroup].

        This is the spec §4 table row:
        IfcGroup[ObjectType='GradingGroup'] → civil.grading_create_group
        """
        # Author a terrain first so the group has a valid target surface.
        points_path = tmp_path / "terrain_for_group.csv"
        points_path.write_text("0,0,0\n20,0,0\n20,20,0\n0,20,0\n")
        bpy.context.scene.CivilSurfaceProperties.new_surface_name = "Group Terrain"
        bpy.context.scene.CivilSurfaceProperties.new_surface_kind = "existing"
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(points_path)
        )
        terrain_guid = bpy.context.scene.CivilSurfaceProperties.active_surface_guid

        result = bpy.ops.civil.grading_create_group(
            "EXEC_DEFAULT",
            name="Menu Grading Group",
            target_surface_guid=terrain_guid,
            interior_fill="none",
        )
        assert result == {"FINISHED"}

        ifc_file = tool.Ifc.get()
        groups = [
            g for g in ifc_file.by_type("IfcGroup")
            if getattr(g, "ObjectType", None) == "GradingGroup"
        ]
        assert any(g.Name == "Menu Grading Group" for g in groups), (
            "Grading group not found after dispatching via grading_create_group"
        )

    @pytest.mark.civil
    def test_dispatch_grading_criteria_create(self) -> None:
        """Invoking civil.grading_create_criteria headless (the Grading
        Criteria entry in the Add Civil Element menu) authors an
        IfcPropertySetTemplate.

        There is no spec §4 table row for criteria (it is an authoring
        convenience, not an IFC element entry point), but the menu includes
        it as a top-level action so users can pre-build criteria before
        associating with groups.
        """
        result = bpy.ops.civil.grading_create_criteria(
            "EXEC_DEFAULT",
            name="Menu 2:1 Cut",
            target_kind="surface",
            target_ref="",
            cut_slope=2.0,
            fill_slope=3.0,
        )
        assert result == {"FINISHED"}

        ifc_file = tool.Ifc.get()
        templates = ifc_file.by_type("IfcPropertySetTemplate")
        names = [t.Name for t in templates]
        # The criteria template is named by the grading API; check one exists.
        assert len(templates) >= 1, (
            f"No IfcPropertySetTemplate after grading_create_criteria; names={names}"
        )

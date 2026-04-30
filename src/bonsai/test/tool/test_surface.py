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

import ifcopenshell
import ifcopenshell.api.unit
import ifcopenshell.guid
import numpy as np
import pytest
import shapely

import bonsai.tool.surface as tool_surface


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
        # Find the Pset_SaikeiGradingSurface and verify BreaklineCount.
        psets_via_rels = []
        for rel in ifc_file.by_type("IfcRelDefinesByProperties"):
            if host in (rel.RelatedObjects or []):
                psets_via_rels.append(rel.RelatingPropertyDefinition)
        saikei_pset = next(
            (p for p in psets_via_rels if p.Name == "Pset_SaikeiGradingSurface"),
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
        # Find Pset_SaikeiBreaklineCommon and check GradingGroupGuid.
        psets = []
        for rel in ifc_file.by_type("IfcRelDefinesByProperties"):
            if annotation in (rel.RelatedObjects or []):
                psets.append(rel.RelatingPropertyDefinition)
        breakline_pset = next(
            (p for p in psets if p.Name == "Pset_SaikeiBreaklineCommon"), None
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

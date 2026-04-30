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

import numpy as np
import shapely

import bonsai.tool.surface as tool_surface


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

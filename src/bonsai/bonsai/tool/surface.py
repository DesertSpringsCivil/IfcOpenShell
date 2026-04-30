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

"""Saikei surface tool layer — TIN math, IFC authoring, and Blender linkage.

Phase 4 of the Saikei grading/earthwork sprint. This module owns:

- Data primitives :class:`Breakline` and :class:`CivilSurface` per spec §5.
- The :class:`Triangulator` protocol per spec §4.4 — a swappable backend
  for unconstrained / constrained Delaunay so tests can override with
  deterministic stubs.

Subsequent commits add the default :class:`_ScipyShapelyTriangulator`
backend and the :class:`Surface` tool class with ``build_tin_from_points``,
``retriangulate``, ``z_at``, and IFC authoring wrappers around
``ifcopenshell.api.surface``.

The tool layer is the only Saikei layer that imports ``numpy``, ``shapely``,
or ``bpy``. Core stays import-clean (only built-ins + ``ifcopenshell``);
UI calls into core which calls into tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional, Protocol

import numpy as np
import scipy.spatial
import shapely


@dataclass
class Breakline:
    """A 3D polyline that must be honored as constrained edges in a TIN.

    Persisted to IFC as :class:`IfcAnnotation` with :class:`IfcPolyline`
    representation (per :func:`ifcopenshell.api.surface.add_breakline_annotation`),
    separate from the derived TIN so retriangulation on file re-open is
    possible.
    """

    guid: str
    """Stable identifier for cross-session reference; matches the IFC GlobalId."""

    name: str
    """Human-readable label."""

    polyline: list[tuple[float, float, float]]
    """Ordered ``(x, y, z)`` vertex sequence; at least two points required."""

    kind: Literal["standard", "wall", "non_destructive", "proximity"]
    """Breakline category. Drives triangulation behavior:

    - ``standard``: edges added to the TIN at this polyline's segments.
    - ``wall``: edges added; downstream code may render a vertical face.
    - ``non_destructive``: edges added but original triangles are preserved
      where possible (no mid-edge splits).
    - ``proximity``: triangles are flagged near this polyline but no
      edges are forced through it (informational only).
    """

    source: str
    """Free-form provenance label: ``manual``, ``feature_line``,
    ``corridor_extract``, etc."""

    ifc_annotation_id: Optional[int] = None
    """Step id of the persisted :class:`IfcAnnotation`, or ``None`` if the
    breakline has not been authored to IFC yet."""


@dataclass
class CivilSurface:
    """An engineered or measured 3D surface — the central grading primitive.

    Per spec §5, the polygon fields (``outer_boundary``, ``holes``, ``voids``)
    are caller-supplied authoring inputs used by the :class:`Triangulator` to
    clip the triangulation and decide which sub-triangles fall inside which
    region. At IFC persistence time, those polygons are translated into
    per-triangle ``triangle_flags`` integers (Hole=-1, Void=-2, breakline
    edge bitmask 0–7); the IFC entity stores integers per triangle, **not**
    polygons. On read-back from IFC, the polygons can be approximately
    recovered by tracing contiguous-flag sub-graphs of triangles.
    """

    guid: str
    """Stable identifier; matches the IFC GlobalId of the host entity."""

    name: str
    """Human-readable label."""

    kind: Literal["existing", "proposed_group", "proposed_site"]
    """IFC host entity selection driver:

    - ``existing``: host is :class:`IfcGeographicElement[TERRAIN]`
      (existing-ground TIN authored via
      :func:`ifcopenshell.api.surface.create_terrain`).
    - ``proposed_group``: host is :class:`IfcEarthworksFill[SUBGRADE]`
      within a grading group (per-group composite, authored via
      :func:`ifcopenshell.api.surface.create_proposed_surface`).
    - ``proposed_site``: host is :class:`IfcEarthworksFill[SUBGRADE]` at
      the composite site level (the deferred Phase 4/5 site-composite
      aggregation root).
    """

    points: np.ndarray
    """``(N, 3)`` float array of XYZ coordinates in project coordinates."""

    triangles: np.ndarray
    """``(M, 3)`` int array of vertex indices into ``points``,
    counterclockwise from above per IFC right-hand rule."""

    triangle_flags: np.ndarray
    """``(M,)`` int array of IFC ``Flags`` values per triangle:

    - ``-2`` invisible void (excluded with no fallback)
    - ``-1`` invisible hole (excluded but may fall back to other surfaces)
    - ``0`` no breakline edges
    - ``1``–``7`` breakline-edge bitmask (bit 0 = edge 1, bit 1 = edge 2,
      bit 2 = edge 3 of the triangle's CoordIndex triple)
    """

    breaklines: list[Breakline] = field(default_factory=list)
    """Constrained edges. Authored polylines that the triangulator must
    honor. Persisted to IFC as separate :class:`IfcAnnotation` entities."""

    outer_boundary: Optional[shapely.Polygon] = None
    """2D (XY-only) clipping polygon. ``None`` means
    :class:`Triangulator` auto-computes the convex hull of ``points`` at
    construction time (per spec §6.4); the volume-calculation domain is
    never left undefined."""

    holes: list[shapely.Polygon] = field(default_factory=list)
    """2D regions where this surface is absent but other surfaces may
    show through. Translated to ``triangle_flags`` value ``-1`` at
    persistence time per IFC §2.1."""

    voids: list[shapely.Polygon] = field(default_factory=list)
    """2D regions permanently excluded with no fallback. Translated to
    ``triangle_flags`` value ``-2`` at persistence time."""

    ifc_host_entity_id: Optional[int] = None
    """Step id of the host :class:`IfcProduct`
    (:class:`IfcGeographicElement` or :class:`IfcEarthworksFill`),
    or ``None`` if the surface has not been authored to IFC yet."""

    ifc_tin_representation_id: Optional[int] = None
    """Step id of the :class:`IfcTriangulatedIrregularNetwork`
    representation item, or ``None``."""

    ifc_bbox_representation_id: Optional[int] = None
    """Step id of the :class:`IfcBoundingBox` LOD representation item,
    or ``None``."""

    metadata: dict = field(default_factory=dict)
    """Free-form per-surface metadata. Not persisted to IFC; useful for
    UI-side state (last-edited timestamp, display color, etc.)."""


class Triangulator(Protocol):
    """Swappable Delaunay backend per spec §4.4.

    The default backend is :class:`_ScipyShapelyTriangulator` (added in a
    subsequent commit) — SciPy for unconstrained, Shapely 2.1+ for
    constrained. Tests override the class attribute on
    :class:`Surface` with deterministic stubs (predictable triangle order)
    to make hand-checked assertions stable.

    Performance target on the default backend: under 2 s on 100k vertices
    for the unconstrained path, under 10 s for the constrained path.
    """

    def unconstrained(self, points: np.ndarray) -> np.ndarray:
        """Plain Delaunay triangulation of a point cloud.

        :param points: ``(N, 2)`` or ``(N, 3)`` array of vertex coordinates;
            triangulation is in XY only — Z is ignored.
        :returns: ``(M, 3)`` array of triangle vertex indices, counterclockwise.
        """
        ...

    def constrained(
        self,
        points: np.ndarray,
        breakline_segments: list[tuple[int, int]],
        outer_boundary: shapely.Polygon,
        holes: list[shapely.Polygon],
        voids: list[shapely.Polygon],
    ) -> tuple[np.ndarray, np.ndarray]:
        """Constrained Delaunay honoring breaklines + boundary + holes + voids.

        :param points: ``(N, 3)`` array of vertex coordinates.
        :param breakline_segments: list of ``(start_index, end_index)`` pairs
            referencing rows in ``points``; the triangulation must include
            edges between every such pair.
        :param outer_boundary: 2D polygon clipping the triangulation; triangles
            whose centroid falls outside are dropped.
        :param holes: 2D polygons inside which triangles are flagged with
            value ``-1`` (excluded with fallback) per IFC §2.1.
        :param voids: 2D polygons inside which triangles are flagged with
            value ``-2`` (excluded with no fallback).
        :returns: ``(triangles, flags)`` tuple where ``triangles`` is
            ``(M, 3)`` indices and ``flags`` is ``(M,)`` IFC Flags values
            (-2, -1, or 0–7 breakline-edge bitmask).
        """
        ...


class _ScipyShapelyTriangulator:
    """Default :class:`Triangulator` backend per spec §4.4.

    - ``unconstrained()`` uses :func:`scipy.spatial.Delaunay` (Qhull).
    - ``constrained()`` uses :func:`shapely.constrained_delaunay_triangles`
      on the outer boundary unioned with breakline line strings — shapely
      respects polygon edges, so the unioned input forces breakline
      segments into the triangulation as edges.

    Output triangle indices are reverse-mapped from shapely's coordinate-
    space output to the input ``points`` array via a rounded-coordinate
    lookup. The lookup tolerance is :data:`COORDINATE_PRECISION` decimal
    places (default 6 ≈ micrometre precision in metric project units).

    Returned ``flags`` are zeros at this layer; commit 5 implements the
    centroid-in-polygon hole/void translation and the breakline-edge
    bitmask.

    Pinned dependency versions per spec §4.4: ``scipy >= 1.11, < 2.0`` and
    ``shapely >= 2.1, < 3.0``.
    """

    COORDINATE_PRECISION = 6
    """Decimal places used when rounding XY coordinates for the
    triangle-vertex → input-point-index lookup. Six decimals ≈
    1 micrometre in metric project units, well below typical civil-
    engineering survey accuracy. Increase only if a test fixture uses
    sub-micrometre vertex spacing."""

    def unconstrained(self, points: np.ndarray) -> np.ndarray:
        if points.ndim != 2 or points.shape[1] not in (2, 3):
            raise ValueError(
                f"points must be (N, 2) or (N, 3), got shape {points.shape}"
            )
        if points.shape[0] < 3:
            raise ValueError(
                f"unconstrained Delaunay requires at least 3 points, got {points.shape[0]}"
            )
        xy = points[:, :2] if points.shape[1] == 3 else points
        delaunay = scipy.spatial.Delaunay(xy)
        return delaunay.simplices.astype(int).copy()

    def constrained(
        self,
        points: np.ndarray,
        breakline_segments: list[tuple[int, int]],
        outer_boundary: shapely.Polygon,
        holes: list[shapely.Polygon],
        voids: list[shapely.Polygon],
    ) -> tuple[np.ndarray, np.ndarray]:
        if points.ndim != 2 or points.shape[1] != 3:
            raise ValueError(
                f"points must be (N, 3), got shape {points.shape}"
            )
        if not isinstance(outer_boundary, shapely.Polygon):
            raise ValueError(
                f"outer_boundary must be a shapely.Polygon, got {type(outer_boundary).__name__}"
            )

        coord_to_index = self._build_coord_index(points)
        constrained_geom = self._build_constrained_geometry(
            points, breakline_segments, outer_boundary
        )
        triangle_geoms = shapely.constrained_delaunay_triangles(constrained_geom)
        triangles = self._extract_triangle_indices(triangle_geoms, coord_to_index)
        # Flags are zeros at this layer; commit 5 fills in hole/void/breakline-bitmask.
        flags = np.zeros(len(triangles), dtype=int)
        return triangles, flags

    @classmethod
    def _build_coord_index(
        cls, points: np.ndarray
    ) -> dict[tuple[float, float], int]:
        """Return a ``(rounded_x, rounded_y) -> point_index`` dict.

        Used to reverse-map shapely's output triangle coordinates back to
        indices in the original ``points`` array. Rounding tolerance is
        :attr:`COORDINATE_PRECISION` decimals.
        """
        precision = cls.COORDINATE_PRECISION
        return {
            (round(float(x), precision), round(float(y), precision)): i
            for i, (x, y, *_) in enumerate(points)
        }

    @staticmethod
    def _build_constrained_geometry(
        points: np.ndarray,
        breakline_segments: list[tuple[int, int]],
        outer_boundary: shapely.Polygon,
    ) -> shapely.geometry.base.BaseGeometry:
        """Split the outer boundary along breakline segments to force breakline
        edges into the constrained Delaunay triangulation.

        Shapely's :func:`constrained_delaunay_triangles` respects polygon edges
        but ignores interior line strings, so a naive
        :func:`shapely.unary_union` of polygon + breakline doesn't enforce the
        breakline as a triangulation edge. Splitting the polygon along the
        breakline produces sub-polygons whose shared edge IS the breakline,
        which the CDT then preserves.

        Limitation: breaklines that don't fully cross the (sub-)polygon are
        silently ignored — :func:`shapely.ops.split` returns the polygon
        unchanged in that case. Internal breaklines (Civil 3D's "ridge that
        ends inside the surface" case) need a proper CDT library to enforce.
        Phase 4 MVP fixtures use breaklines that fully cross; later phases
        may upgrade this backend.

        With no breaklines, returns the outer boundary unchanged.
        """
        if not breakline_segments:
            return outer_boundary
        polygons: list[shapely.Polygon] = [outer_boundary]
        for a, b in breakline_segments:
            line = shapely.LineString(
                [
                    (float(points[a, 0]), float(points[a, 1])),
                    (float(points[b, 0]), float(points[b, 1])),
                ]
            )
            new_polygons: list[shapely.Polygon] = []
            for poly in polygons:
                split_result = shapely.ops.split(poly, line)
                if hasattr(split_result, "geoms"):
                    new_polygons.extend(
                        g for g in split_result.geoms if isinstance(g, shapely.Polygon)
                    )
                elif isinstance(split_result, shapely.Polygon):
                    new_polygons.append(split_result)
            polygons = new_polygons or polygons
        return shapely.MultiPolygon(polygons) if len(polygons) > 1 else polygons[0]

    @classmethod
    def _extract_triangle_indices(
        cls,
        triangle_geoms: shapely.GeometryCollection,
        coord_to_index: dict[tuple[float, float], int],
    ) -> np.ndarray:
        """Convert shapely's GeometryCollection-of-polygons output to an
        ``(M, 3)`` index array referencing the original points.

        Raises :class:`ValueError` if a triangle vertex cannot be matched —
        which happens when shapely introduces a Steiner point (e.g., where
        a breakline segment crosses the outer boundary). Future commits may
        relax this by adding new points to a returned augmented array; the
        Phase 4 MVP fixtures don't require Steiner points.
        """
        precision = cls.COORDINATE_PRECISION
        indices: list[tuple[int, int, int]] = []
        geoms = (
            triangle_geoms.geoms
            if hasattr(triangle_geoms, "geoms")
            else [triangle_geoms]
        )
        for triangle in geoms:
            if not isinstance(triangle, shapely.Polygon):
                continue
            coords = list(triangle.exterior.coords)
            # First three coords are the triangle vertices; the fourth closes the ring.
            triangle_indices: list[int] = []
            for x, y in coords[:3]:
                key = (round(float(x), precision), round(float(y), precision))
                if key not in coord_to_index:
                    raise ValueError(
                        f"triangle vertex {key} not found in input points; "
                        "shapely may have introduced a Steiner point — supply "
                        "breakline endpoints that match input vertices exactly"
                    )
                triangle_indices.append(coord_to_index[key])
            indices.append(tuple(triangle_indices))  # type: ignore[arg-type]
        return np.array(indices, dtype=int)

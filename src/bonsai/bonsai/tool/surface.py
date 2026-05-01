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
- The default :class:`_ScipyShapelyTriangulator` backend.
- The :class:`Surface` tool class with ``build_tin_from_points``,
  ``retriangulate``, and ``z_at``. IFC authoring wrappers and the
  ``_registry`` cache land in subsequent commits.

The tool layer is the only Saikei layer that imports ``numpy``, ``shapely``,
or ``bpy``. Core stays import-clean (only built-ins + ``ifcopenshell``);
UI calls into core which calls into tool.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Optional, Protocol

import bpy
import ifcopenshell.api.surface
import ifcopenshell.guid
import numpy as np
import scipy.spatial
import shapely

import bonsai.tool as tool

if TYPE_CHECKING:
    import ifcopenshell


_logger = logging.getLogger("bonsai.tool.surface")


@dataclass
class Breakline:
    """A 3D polyline that must be honored as constrained edges in a TIN.

    Persisted to IFC as :class:`IfcAnnotation` with :class:`IfcPolyline`
    representation (per :func:`ifcopenshell.api.surface.add_breakline_annotation`),
    separate from the derived TIN so retriangulation on file re-open is
    possible.
    """

    guid: str = field(default_factory=ifcopenshell.guid.new)
    """Stable identifier for cross-session reference; matches the IFC GlobalId.
    Defaults to a fresh ``ifcopenshell.guid.new()`` when not supplied — keeps
    GUID minting in the data layer, not in operators."""

    name: str = ""
    """Human-readable label."""

    polyline: list[tuple[float, float, float]] = field(default_factory=list)
    """Ordered ``(x, y, z)`` vertex sequence; at least two points required
    when used by :meth:`Surface.retriangulate`."""

    kind: Literal["standard", "wall", "non_destructive", "proximity"] = "standard"
    """Breakline category. Drives triangulation behavior:

    - ``standard``: edges added to the TIN at this polyline's segments.
    - ``wall``: edges added; downstream code may render a vertical face.
    - ``non_destructive``: edges added but original triangles are preserved
      where possible (no mid-edge splits) — note: Phase 4 implementation
      treats this identically to ``standard``; the kind is round-tripped
      through IFC for forward compatibility.
    - ``proximity``: triangles are flagged near this polyline but no
      edges are forced through it (informational only).
    """

    source: str = "manual"
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

    Returned ``flags`` follow IFC 4.3.2 §8.8.3.48 per-triangle Flags
    semantics (per spec §2.1, §5): ``-2`` for triangles whose centroid is
    inside a void polygon, ``-1`` for hole, otherwise a 3-bit bitmask of
    which triangle edges are breakline edges.

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
        flags = self._compute_flags(
            points, triangles, breakline_segments, holes, voids
        )
        return triangles, flags

    @staticmethod
    def _compute_flags(
        points: np.ndarray,
        triangles: np.ndarray,
        breakline_segments: list[tuple[int, int]],
        holes: list[shapely.Polygon],
        voids: list[shapely.Polygon],
    ) -> np.ndarray:
        """Translate caller-supplied polygons + breakline segments into the
        per-triangle IFC ``Flags`` integer (per spec §2.1, §5).

        Per spec §6.3 (cross-surface composition), voids take precedence over
        holes — a triangle whose centroid lies in both a void and a hole is
        flagged ``-2``. Triangles outside all hole/void polygons get the 3-bit
        breakline-edge bitmask (``0`` to ``7``).

        Edge ``i`` (in IFC's 1-based convention) is between vertex ``i`` and
        vertex ``(i+1) mod 3`` of the triangle's CoordIndex triple. Bit
        position 0 of the mask corresponds to IFC edge 1, bit 1 to edge 2,
        bit 2 to edge 3.
        """
        breakline_set: set[frozenset[int]] = {
            frozenset((int(a), int(b))) for a, b in breakline_segments
        }
        flags = np.zeros(len(triangles), dtype=int)

        for triangle_index, triangle in enumerate(triangles):
            v0, v1, v2 = triangle
            centroid_x = (
                points[v0, 0] + points[v1, 0] + points[v2, 0]
            ) / 3.0
            centroid_y = (
                points[v0, 1] + points[v1, 1] + points[v2, 1]
            ) / 3.0
            centroid = shapely.Point(float(centroid_x), float(centroid_y))

            # Voids take precedence over holes per spec §6.3.
            # ``intersects`` (rather than ``within``) handles the
            # boundary case: a triangle whose centroid lands exactly on
            # a hole/void edge (common when a breakline is coincident
            # with a hole boundary) gets the correct flag instead of
            # silently classifying as "visible" via ``within``'s
            # strict-interior semantics.
            if any(centroid.intersects(void) for void in voids):
                flags[triangle_index] = -2
                continue
            if any(centroid.intersects(hole) for hole in holes):
                flags[triangle_index] = -1
                continue

            # Breakline-edge bitmask — IFC edge i is (vertex i, vertex (i+1) mod 3).
            bitmask = 0
            edges = (
                (int(v0), int(v1)),
                (int(v1), int(v2)),
                (int(v2), int(v0)),
            )
            for edge_index, (start_vertex, end_vertex) in enumerate(edges):
                if frozenset((start_vertex, end_vertex)) in breakline_set:
                    bitmask |= 1 << edge_index
            flags[triangle_index] = bitmask

        return flags

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

        **Interaction with `_compute_flags`.** When a breakline is silently
        dropped here, :meth:`_compute_flags` still receives the original
        ``breakline_segments`` list. If the unconstrained Delaunay output
        happens to contain an edge geometrically equal to ``(a, b)``, that
        edge's flag bit is set — which is *correct* per IFC §2.1 (the bit
        encodes "this edge is at a breakline," not "the triangulator forced
        this edge"). If Delaunay chose a different diagonal, no flag bit is
        set and the breakline is recoverable only via the separate
        ``IfcAnnotation`` polyline. Callers that need a guarantee the
        bitmask reflects forced edges must validate the breakline crosses
        the boundary before calling.

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
            polygon_count_before = len(polygons)
            for poly in polygons:
                split_result = shapely.ops.split(poly, line)
                if hasattr(split_result, "geoms"):
                    new_polygons.extend(
                        g for g in split_result.geoms if isinstance(g, shapely.Polygon)
                    )
                elif isinstance(split_result, shapely.Polygon):
                    new_polygons.append(split_result)
            # Detect the silent-drop case: split produced no new sub-polygons
            # (either because the breakline doesn't fully cross any polygon,
            # or because it's tangential to a sub-polygon boundary). Log a
            # warning so callers / users can spot non-honored breaklines
            # rather than getting a TIN that silently ignores their input.
            if len(new_polygons) <= polygon_count_before:
                _logger.warning(
                    "Breakline segment (%d, %d) was not honored by the "
                    "constrained Delaunay backend — polyline may not fully "
                    "cross the outer boundary, or may be tangent to an "
                    "existing sub-polygon edge. The annotation persists in "
                    "IFC but the resulting TIN does not contain the forced "
                    "edge.",
                    a,
                    b,
                )
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
                        "shapely introduced a Steiner point. This usually "
                        "means a breakline crosses the outer boundary at a "
                        "non-vertex point, OR two breaklines intersect "
                        "interior to the surface. Phase 4 fix: add the "
                        "intersection coordinates to surface.points before "
                        "retriangulation, or restrict breaklines to share "
                        "existing surface vertices"
                    )
                triangle_indices.append(coord_to_index[key])
            indices.append(tuple(triangle_indices))  # type: ignore[arg-type]
        return np.array(indices, dtype=int)


class SaikeiSurfaceError(Exception):
    """Base exception for the Saikei surface tool layer.

    Operators catch this and the more specific subclasses below to convert
    tool-layer failures into ``self.report({"ERROR"}, ...)`` + ``CANCELLED``
    in interactive mode (per handoff §"Modal vs headless operator contract").
    Headless callers receive the raw exception.
    """


class SaikeiTriangulationError(SaikeiSurfaceError):
    """Raised when triangulation fails (degenerate input, missing Steiner
    point, or :class:`Triangulator` backend error)."""


def _extract_polyline_3d(
    annotation: "ifcopenshell.entity_instance",
) -> Optional[list[tuple[float, float, float]]]:
    """Pull the ordered ``(x, y, z)`` polyline points from an
    :class:`IfcAnnotation` whose representation is an :class:`IfcPolyline`.

    Returns ``None`` if the annotation has no representation, no polyline
    item, or fewer than two points. Callers (currently only
    :meth:`Surface._recover_breaklines_from_annotations`) treat ``None``
    as "skip this annotation."
    """
    representation = annotation.Representation
    if representation is None:
        return None
    for shape_rep in representation.Representations or []:
        for item in shape_rep.Items or []:
            if not item.is_a("IfcPolyline"):
                continue
            points: list[tuple[float, float, float]] = []
            for pt in item.Points or []:
                coords = pt.Coordinates or ()
                if len(coords) >= 3:
                    points.append(
                        (float(coords[0]), float(coords[1]), float(coords[2]))
                    )
                elif len(coords) == 2:
                    points.append(
                        (float(coords[0]), float(coords[1]), 0.0)
                    )
            if len(points) >= 2:
                return points
    return None


def _annotation_belongs_to_host(
    annotation: "ifcopenshell.entity_instance",
    host: "ifcopenshell.entity_instance",
) -> bool:
    """Return True if ``annotation`` is assigned to ``host`` via at least
    one :class:`IfcRelAssignsToProduct`, OR if it has no host assignments
    at all (the no-attribution fallback used by single-surface files).

    Returns False only when the annotation is explicitly assigned to a
    *different* host product — that's the case the multi-surface
    disambiguation must filter out.
    """
    has_assignments = getattr(annotation, "HasAssignments", None) or []
    host_assignments = [
        rel
        for rel in has_assignments
        if rel.is_a("IfcRelAssignsToProduct")
    ]
    if not host_assignments:
        # No host link at all — fall back to "global to all surfaces."
        return True
    return any(
        rel.RelatingProduct == host for rel in host_assignments
    )


def _extract_breakline_pset(
    annotation: "ifcopenshell.entity_instance",
) -> tuple[str, str]:
    """Return ``(kind, source)`` from ``Pset_SaikeiBreaklineCommon`` on the
    annotation, defaulting to ``"standard"`` / ``"recovered"`` if the pset
    or properties are missing.

    The ``"recovered"`` source label distinguishes annotations that were
    rehydrated from disk (no in-memory provenance) from annotations
    authored directly via :meth:`Surface.author_ifc_breakline` (which
    preserves the user-supplied source).
    """
    kind = "standard"
    source = "recovered"
    for rel in getattr(annotation, "IsDefinedBy", None) or []:
        if not rel.is_a("IfcRelDefinesByProperties"):
            continue
        pset = rel.RelatingPropertyDefinition
        if pset is None or pset.Name != "Pset_SaikeiBreaklineCommon":
            continue
        for prop in pset.HasProperties or []:
            if prop.Name == "Kind" and prop.NominalValue is not None:
                kind = prop.NominalValue.wrappedValue or kind
            elif prop.Name == "Source" and prop.NominalValue is not None:
                source = prop.NominalValue.wrappedValue or source
    return kind, source


class Surface:
    """Tool-layer entry point for surface math, IFC authoring, and Blender
    linkage. Per spec §7.2 each method is a static or class method called
    from :mod:`bonsai.core.surface` orchestration.

    The default :attr:`triangulator` is :class:`_ScipyShapelyTriangulator`.
    Tests override this class attribute with deterministic stubs (predictable
    triangle order) so hand-checked assertions stay stable; remember to
    reset to the default in fixture teardown.
    """

    triangulator: Triangulator = _ScipyShapelyTriangulator()
    """Swappable Delaunay backend per spec §4.4. Tests reassign this to a
    stub before exercising :meth:`build_tin_from_points` /
    :meth:`retriangulate`, then restore the default in teardown."""

    @staticmethod
    def build_boundary_polygon_from_ring(
        ring_points: np.ndarray,
    ) -> shapely.Polygon:
        """Build a 2D :class:`shapely.Polygon` from an XYZ ring.

        Inputs come from CSV ring files (open or closed); Z is dropped
        before polygon construction. Validates topologically before
        returning so callers don't have to.

        :param ring_points: ``(N, 3)`` XYZ array; ``N >= 3``.
        :returns: a topologically-valid :class:`shapely.Polygon`.
        :raises SaikeiSurfaceError: if the ring has fewer than 3 vertices,
            cannot be assembled into a polygon, or is not topologically
            valid (self-intersecting, etc.).
        """
        if not isinstance(ring_points, np.ndarray):
            ring_points = np.asarray(ring_points, dtype=float)
        if ring_points.ndim != 2 or ring_points.shape[1] != 3:
            raise SaikeiSurfaceError(
                f"boundary ring must be (N, 3); got shape {ring_points.shape}"
            )
        if ring_points.shape[0] < 3:
            raise SaikeiSurfaceError(
                f"boundary polygon needs ≥ 3 vertices; got {ring_points.shape[0]}"
            )

        try:
            polygon = shapely.Polygon(
                [(float(p[0]), float(p[1])) for p in ring_points]
            )
        except (ValueError, shapely.errors.GEOSException) as exc:
            raise SaikeiSurfaceError(
                f"could not build polygon from ring: {exc}"
            ) from exc

        if not polygon.is_valid:
            raise SaikeiSurfaceError(
                f"polygon is not topologically valid: "
                f"{shapely.is_valid_reason(polygon)}"
            )
        return polygon

    @staticmethod
    def load_points_from_csv(filepath: str) -> np.ndarray:
        """Load an ``(N, 3)`` XYZ point cloud from a CSV file.

        Accepts comma- or whitespace-separated rows of three floats. Skips
        blank lines and lines beginning with ``#``. Per Phase 4 MVP, the
        tool layer owns CSV parsing because :func:`numpy.loadtxt` is
        math-adjacent — the UI operator delegates here rather than parsing
        inline.

        :param filepath: absolute path to a ``.csv`` (or ``.txt``,
            ``.xyz``) file.
        :returns: ``(N, 3)`` float numpy array of XYZ coordinates.
        :raises SaikeiSurfaceError: if the file cannot be parsed as
            ``(N, 3)`` floats.
        """
        try:
            data = np.loadtxt(
                filepath,
                comments="#",
                delimiter=None,  # any whitespace
                ndmin=2,
            )
        except Exception:
            # Retry with comma delimiter for CSV exports that aren't
            # whitespace-separable.
            try:
                data = np.loadtxt(
                    filepath, comments="#", delimiter=",", ndmin=2
                )
            except Exception as exc:
                raise SaikeiSurfaceError(
                    f"could not parse {filepath!r} as a CSV/whitespace point "
                    f"cloud: {exc}"
                ) from exc

        if data.ndim != 2 or data.shape[1] != 3:
            raise SaikeiSurfaceError(
                f"point file {filepath!r} must have exactly 3 columns "
                f"(x, y, z); got shape {data.shape}"
            )
        return data.astype(float, copy=False)

    _registry: dict[tuple[int, str], "CivilSurface"] = {}
    """Per spec §4.6: lazy-rehydrating cache keyed by ``(id(ifc_file), guid)``.
    IFC is the source of truth; this cache avoids re-reading the IFC entity on
    every :meth:`get` call. Multi-file safety comes from ``id(ifc_file)`` in
    the key. Headless tests call :meth:`clear` in teardown."""

    @classmethod
    def register(
        cls, ifc_file: "ifcopenshell.file", surface: CivilSurface
    ) -> None:
        """Add ``surface`` to the registry under ``(id(ifc_file), surface.guid)``.

        Called by core orchestration after :meth:`author_ifc_host` so the
        in-memory dataclass is reused on subsequent :meth:`get` calls without
        a round-trip through :meth:`_rehydrate_from_ifc`.
        """
        cls._registry[(id(ifc_file), surface.guid)] = surface

    @classmethod
    def get(
        cls, ifc_file: "ifcopenshell.file", guid: str
    ) -> CivilSurface:
        """Return the cached :class:`CivilSurface` for ``guid``, rehydrating
        from IFC on cache miss.

        :raises SaikeiSurfaceError: if ``guid`` doesn't resolve to an entity in
            ``ifc_file``, or the entity isn't one of the supported host types
            (``IfcGeographicElement[TERRAIN]``, ``IfcEarthworksFill[SUBGRADE]``).
        """
        key = (id(ifc_file), guid)
        if key not in cls._registry:
            cls._registry[key] = cls._rehydrate_from_ifc(ifc_file, guid)
        return cls._registry[key]

    @classmethod
    def invalidate(
        cls, ifc_file: "ifcopenshell.file", guid: str
    ) -> None:
        """Drop the cache entry for ``guid`` so the next :meth:`get` rehydrates
        from IFC. Called by edit operations after committing IFC writes."""
        cls._registry.pop((id(ifc_file), guid), None)

    @classmethod
    def clear(cls) -> None:
        """Wipe the entire registry. Headless test teardown calls this to
        prevent cross-test contamination."""
        cls._registry.clear()

    @classmethod
    def _rehydrate_from_ifc(
        cls, ifc_file: "ifcopenshell.file", guid: str
    ) -> CivilSurface:
        """Reconstruct a :class:`CivilSurface` from the IFC entity identified
        by ``guid``.

        Reads the host's Body :class:`IfcTriangulatedIrregularNetwork`
        for ``points`` (from ``Coordinates.CoordList``), ``triangles`` (from
        ``CoordIndex`` minus 1 to convert IFC's 1-based to 0-based), and
        ``triangle_flags``. The ``outer_boundary`` defaults to the convex hull
        of the points (per spec §6.4) since IFC stores per-triangle flags, not
        the authoring polygons. ``holes`` and ``voids`` start empty — recovery
        from the per-triangle flag mask is a Phase 4.1+ refinement.

        ``breaklines`` are recovered from every :class:`IfcAnnotation` with
        ``ObjectType="BREAKLINE"`` in the file (per spec §2.3 — breaklines
        live on the site, not on individual surfaces, so all annotations are
        re-attached on rehydration). For multi-surface files, this means
        every rehydrated surface "sees" every breakline; multi-surface
        attribution is heuristic until Phase 5 introduces explicit
        surface↔breakline links via ``IfcRelAssociates`` or a similar
        relationship.

        .. note::

            **proposed_group / proposed_site disambiguation on read-back.**
            Both kinds host as ``IfcEarthworksFill[SUBGRADE]`` with identical
            entity structure (per spec §2.2). To disambiguate on rehydration,
            this method calls :meth:`infer_kind_from_spatial_parent` which
            checks for an ``IfcRelAssignsToGroup`` relationship whose
            ``RelatingGroup.ObjectType == "GradingGroup"``. Phase 4 files (no
            grading groups exist yet) always read back as
            ``"proposed_site"``; once Phase 5 authors grading groups, the
            same helper classifies pre-existing fills correctly.
        """
        # Targeted lookup — only the two entity types Saikei surfaces ever
        # host as. Avoids the full-file scan of by_type("IfcRoot") which
        # would walk every IfcAlignment, IfcAnnotation, etc. on every
        # rehydration cache miss.
        host = next(
            (
                e
                for e in (
                    *ifc_file.by_type("IfcGeographicElement"),
                    *ifc_file.by_type("IfcEarthworksFill"),
                )
                if e.GlobalId == guid
            ),
            None,
        )
        if host is None:
            raise SaikeiSurfaceError(
                f"no IFC entity with GlobalId {guid!r} in this file"
            )

        predefined_type = getattr(host, "PredefinedType", None)
        if host.is_a("IfcGeographicElement") and predefined_type == "TERRAIN":
            kind = "existing"
        elif host.is_a("IfcEarthworksFill") and predefined_type == "SUBGRADE":
            kind = cls.infer_kind_from_spatial_parent(host)
        else:
            raise SaikeiSurfaceError(
                f"entity {host.is_a()} is not a Saikei surface host "
                "(expected IfcGeographicElement[TERRAIN] or "
                "IfcEarthworksFill[SUBGRADE])"
            )

        tin_id = cls._find_tin_id(host)
        if tin_id is None:
            raise SaikeiSurfaceError(
                f"host #{host.id()} has no IfcTriangulatedIrregularNetwork "
                "in its Body representation"
            )
        tin = ifc_file.by_id(tin_id)

        points = np.asarray(tin.Coordinates.CoordList, dtype=float)
        triangles = np.asarray(tin.CoordIndex, dtype=int) - 1
        triangle_flags = np.asarray(tin.Flags or [], dtype=int)
        outer_boundary = shapely.MultiPoint(
            [(float(p[0]), float(p[1])) for p in points]
        ).convex_hull

        return CivilSurface(
            guid=guid,
            name=host.Name or "",
            kind=kind,  # type: ignore[arg-type]
            points=points,
            triangles=triangles,
            triangle_flags=triangle_flags,
            outer_boundary=outer_boundary if isinstance(outer_boundary, shapely.Polygon) else None,
            breaklines=cls._recover_breaklines_from_annotations(ifc_file, host),
            ifc_host_entity_id=host.id(),
            ifc_tin_representation_id=tin_id,
            ifc_bbox_representation_id=cls._find_bbox_id(host),
        )

    @staticmethod
    def infer_kind_from_spatial_parent(
        host: "ifcopenshell.entity_instance",
    ) -> Literal["proposed_group", "proposed_site"]:
        """Determine whether an :class:`IfcEarthworksFill` belongs to a
        grading group or sits at the site composite root.

        Walks the host's ``HasAssignments`` inverse looking for
        :class:`IfcRelAssignsToGroup` whose ``RelatingGroup`` carries
        ``ObjectType="GradingGroup"`` (the convention Phase 5 will adopt
        when authoring grading groups per spec §6.3). Returns
        ``"proposed_group"`` if found, ``"proposed_site"`` otherwise.

        For Phase 4 files (no grading groups exist yet), this always
        returns ``"proposed_site"``. Once Phase 5 authors
        ``IfcGroup[GradingGroup]`` + ``IfcRelAssignsToGroup`` relations,
        the same helper correctly classifies pre-existing fills without
        a code change.

        Phase 4 author-time path: :meth:`author_ifc_host` accepts the
        caller-supplied ``surface.kind`` directly and doesn't go through
        this inference. This helper is for the rehydration path only,
        where the in-memory dataclass kind has been lost.
        """
        for rel in getattr(host, "HasAssignments", None) or []:
            if not rel.is_a("IfcRelAssignsToGroup"):
                continue
            group = rel.RelatingGroup
            if group is not None and getattr(group, "ObjectType", None) == "GradingGroup":
                return "proposed_group"
        return "proposed_site"

    @staticmethod
    def _recover_breaklines_from_annotations(
        ifc_file: "ifcopenshell.file",
        host: Optional["ifcopenshell.entity_instance"] = None,
    ) -> list[Breakline]:
        """Read ``IfcAnnotation[BREAKLINE]`` entities in the file and rebuild
        the corresponding :class:`Breakline` dataclasses.

        When ``host`` is provided, annotations are filtered by their
        :class:`IfcRelAssignsToProduct` relationships — only annotations
        explicitly assigned to ``host`` are returned. Annotations with NO
        such assignment (e.g., legacy data, or breaklines authored without
        :meth:`author_ifc_breakline`'s ``host_surface`` argument) are
        included as a fallback so single-surface Phase 4 files still
        recover their breaklines. Annotations assigned to a *different*
        host are excluded — that's the multi-surface disambiguation.

        Walks the polyline geometry from the annotation's
        ``IfcShapeRepresentation`` and pulls ``Kind`` / ``Source`` from
        ``Pset_SaikeiBreaklineCommon``. Entries that don't conform (no
        representation, missing pset, malformed polyline) are skipped
        silently.
        """
        recovered: list[Breakline] = []
        for annotation in ifc_file.by_type("IfcAnnotation"):
            if getattr(annotation, "ObjectType", None) != "BREAKLINE":
                continue
            if host is not None and not _annotation_belongs_to_host(
                annotation, host
            ):
                continue
            polyline = _extract_polyline_3d(annotation)
            if polyline is None or len(polyline) < 2:
                continue
            kind, source = _extract_breakline_pset(annotation)
            recovered.append(
                Breakline(
                    guid=annotation.GlobalId,
                    name=annotation.Name or "",
                    polyline=polyline,
                    kind=kind,
                    source=source,
                    ifc_annotation_id=annotation.id(),
                )
            )
        return recovered

    @classmethod
    def build_tin_from_points(
        cls,
        name: str,
        points: np.ndarray,
        kind: Literal["existing", "proposed_group", "proposed_site"] = "existing",
        guid: Optional[str] = None,
    ) -> CivilSurface:
        """Build an unconstrained TIN from a 3D point cloud.

        :param name: Human-readable label for the resulting surface.
        :param points: ``(N, 3)`` array of XYZ vertex coordinates in project units.
        :param kind: IFC host entity selection per :class:`CivilSurface.kind`.
        :param guid: Optional pre-assigned IFC GlobalId. ``None`` (default)
            mints a fresh ``ifcopenshell.guid.new()``; supply explicitly when
            rehydrating from an existing entity.
        :returns: :class:`CivilSurface` with ``triangles`` from
            :meth:`Triangulator.unconstrained`, ``triangle_flags`` zeros
            (no breaklines / holes / voids on a freshly-built TIN), and
            ``outer_boundary`` set to the convex hull of ``points`` so the
            volume-calculation domain is never undefined (per spec §6.4). No
            IFC authoring at this layer; commit 6 wraps
            :func:`ifcopenshell.api.surface.create_terrain` /
            ``create_proposed_surface`` and stamps step ids onto the returned
            surface.
        :raises SaikeiTriangulationError: if ``points`` is the wrong shape or
            has fewer than 3 vertices.
        """
        if not isinstance(points, np.ndarray):
            points = np.asarray(points, dtype=float)
        if points.ndim != 2 or points.shape[1] != 3:
            raise SaikeiTriangulationError(
                f"points must be (N, 3), got shape {points.shape}"
            )
        if points.shape[0] < 3:
            raise SaikeiTriangulationError(
                f"build_tin_from_points requires at least 3 points, got {points.shape[0]}"
            )

        try:
            triangles = cls.triangulator.unconstrained(points)
        except Exception as exc:
            raise SaikeiTriangulationError(
                f"unconstrained Delaunay failed: {exc}"
            ) from exc

        triangle_flags = np.zeros(len(triangles), dtype=int)
        outer_boundary = shapely.MultiPoint(
            [(float(x), float(y)) for x, y, *_ in points]
        ).convex_hull
        if not isinstance(outer_boundary, shapely.Polygon):
            # Three collinear points yield a LineString hull; the points are
            # pathological for a TIN regardless, but surface the error here
            # rather than letting callers debug a non-Polygon boundary.
            raise SaikeiTriangulationError(
                "convex hull of input points is not a polygon (collinear input?)"
            )

        return CivilSurface(
            guid=guid if guid is not None else ifcopenshell.guid.new(),
            name=name,
            kind=kind,
            points=np.asarray(points, dtype=float).copy(),
            triangles=triangles,
            triangle_flags=triangle_flags,
            outer_boundary=outer_boundary,
        )

    @classmethod
    def retriangulate(cls, surface: CivilSurface) -> None:
        """Rebuild ``surface.triangles`` and ``surface.triangle_flags`` via
        constrained Delaunay, honoring ``surface.breaklines``,
        ``surface.outer_boundary``, ``surface.holes``, and ``surface.voids``.

        Updates the surface in place. The points array is grown if any
        breakline polyline vertex isn't already present (matched by rounded
        XY at :data:`_ScipyShapelyTriangulator.COORDINATE_PRECISION`).

        Raises :class:`SaikeiTriangulationError` if the surface lacks an
        ``outer_boundary`` (use :meth:`build_tin_from_points` first, which
        sets a convex-hull default), or if the constrained backend errors.
        """
        if surface.outer_boundary is None:
            raise SaikeiTriangulationError(
                "surface has no outer_boundary; call build_tin_from_points first"
            )

        augmented_points, breakline_segments = cls._resolve_breakline_segments(surface)

        try:
            triangles, flags = cls.triangulator.constrained(
                augmented_points,
                breakline_segments,
                surface.outer_boundary,
                surface.holes,
                surface.voids,
            )
        except Exception as exc:
            raise SaikeiTriangulationError(
                f"constrained Delaunay failed: {exc}"
            ) from exc

        surface.points = augmented_points
        surface.triangles = triangles
        surface.triangle_flags = flags
        # The z_at STRtree index is cached per-surface (per spec §6.4 perf
        # target). Re-triangulating invalidates it; the next z_at call
        # rebuilds from the new triangles array.
        surface.metadata.pop("_z_at_index", None)

    @staticmethod
    def _resolve_breakline_segments(
        surface: CivilSurface,
    ) -> tuple[np.ndarray, list[tuple[int, int]]]:
        """Return ``(augmented_points, segments)`` for the surface's breaklines.

        Walks each :class:`Breakline.polyline`, looking up each vertex in
        ``surface.points`` by rounded XY. New vertices are appended; segments
        are emitted as ``(start_idx, end_idx)`` pairs for each consecutive
        polyline pair.
        """
        precision = _ScipyShapelyTriangulator.COORDINATE_PRECISION
        coord_to_index: dict[tuple[float, float], int] = {
            (round(float(x), precision), round(float(y), precision)): i
            for i, (x, y, *_) in enumerate(surface.points)
        }
        new_points: list[tuple[float, float, float]] = [
            (float(p[0]), float(p[1]), float(p[2])) for p in surface.points
        ]
        segments: list[tuple[int, int]] = []

        for breakline in surface.breaklines:
            indices: list[int] = []
            for x, y, z in breakline.polyline:
                key = (round(float(x), precision), round(float(y), precision))
                if key not in coord_to_index:
                    coord_to_index[key] = len(new_points)
                    new_points.append((float(x), float(y), float(z)))
                indices.append(coord_to_index[key])
            for a, b in zip(indices[:-1], indices[1:]):
                if a != b:
                    segments.append((a, b))

        return np.asarray(new_points, dtype=float), segments

    @classmethod
    def z_at(
        cls, surface: CivilSurface, x: float, y: float
    ) -> Optional[float]:
        """Interpolated Z at ``(x, y)`` via point-in-triangle + barycentric.

        :returns: interpolated Z value, or ``None`` if ``(x, y)`` is outside
            every triangle in ``surface.triangles``.

        STRtree-accelerated. The first call on a given surface builds an
        :class:`shapely.STRtree` of triangle XY polygons and caches it on
        ``surface.metadata["_z_at_index"]``; subsequent calls reuse the
        cached tree and only run barycentric checks on the candidate
        triangles whose XY bounding box contains the query point. The
        cache is invalidated by :meth:`retriangulate` (triangles array
        change → cache pop). Phase 5 slope projection issues thousands
        of ``z_at`` calls per slope vector; the linear scan would be
        ~10^8 Python iterations on realistic surfaces.

        The inside-test ``epsilon`` is intentionally **absolute**, not
        relative to triangle size. At civil-engineering project scales
        (1 m to 10 km extents in metric units), ``1e-9`` corresponds to
        nanometre-precision leakage at the boundary — well below survey
        accuracy and small enough that its effect on interpolated Z is
        negligible for any practical triangle.
        """
        px, py = float(x), float(y)
        points = surface.points
        epsilon = 1e-9

        tree = cls._get_or_build_z_at_index(surface)
        candidate_indices = tree.query(shapely.Point(px, py))

        for index in candidate_indices:
            triangle = surface.triangles[int(index)]
            a = points[triangle[0]]
            b = points[triangle[1]]
            c = points[triangle[2]]
            denom = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
            if abs(denom) < 1e-12:
                continue
            u = ((b[1] - c[1]) * (px - c[0]) + (c[0] - b[0]) * (py - c[1])) / denom
            v = ((c[1] - a[1]) * (px - c[0]) + (a[0] - c[0]) * (py - c[1])) / denom
            w = 1.0 - u - v
            if u >= -epsilon and v >= -epsilon and w >= -epsilon:
                return float(u * a[2] + v * b[2] + w * c[2])
        return None

    @staticmethod
    def _get_or_build_z_at_index(
        surface: CivilSurface,
    ) -> "shapely.STRtree":
        """Return the cached STRtree for :meth:`z_at` queries, building it
        on first use.

        Cache key: ``surface.metadata["_z_at_index"]``. Stored as a 5-tuple
        ``(points_id, points_shape, triangles_id, triangles_shape,
        strtree)``. Using ``id()`` + ``shape`` keys is fast (no per-call
        memcmp) while still defending against the common Phase 5 mutation
        patterns:

        - **Reallocation** — caller does ``surface.triangles = new_array``;
          the new array has a different id, cache rebuilds.
        - **Reshape** — caller appends rows; the shape changes, cache
          rebuilds.
        - **CPython id reuse** — old array is GC'd and a new array
          allocated at the same address with the same shape. This rare
          case can serve a stale tree, but the documented contract is
          that callers route mutations through :meth:`retriangulate`
          (which eagerly pops the cache). The id+shape key is the
          performance/safety balance per the spec §4.4 perf budget.

        Triangles are 2D (XY only) for the spatial-index step; the Z
        component is recovered from ``surface.points[triangle[i]][2]``
        in the barycentric step. The triangle-polygon list is intentionally
        not retained on the cache (the STRtree is keyed to indices into
        the original ``surface.triangles`` array, which is the source of
        truth for barycentric).
        """
        cached = surface.metadata.get("_z_at_index")
        current_key = (
            id(surface.points),
            surface.points.shape,
            id(surface.triangles),
            surface.triangles.shape,
        )
        if cached is not None:
            cached_pts_id, cached_pts_shape, cached_tri_id, cached_tri_shape, tree = cached
            if (
                cached_pts_id == current_key[0]
                and cached_pts_shape == current_key[1]
                and cached_tri_id == current_key[2]
                and cached_tri_shape == current_key[3]
            ):
                return tree

        triangle_polys: list[shapely.Polygon] = []
        for triangle in surface.triangles:
            triangle_polys.append(
                shapely.Polygon(
                    [
                        (
                            float(surface.points[triangle[i], 0]),
                            float(surface.points[triangle[i], 1]),
                        )
                        for i in range(3)
                    ]
                )
            )
        tree = shapely.STRtree(triangle_polys)
        surface.metadata["_z_at_index"] = (*current_key, tree)
        return tree

    @classmethod
    def author_ifc_host(
        cls,
        ifc_file: "ifcopenshell.file",
        surface: CivilSurface,
        site: Optional["ifcopenshell.entity_instance"] = None,
        triangulation_tolerance: float = 0.0,
    ) -> "ifcopenshell.entity_instance":
        """Persist ``surface`` as the appropriate IFC host entity per :attr:`CivilSurface.kind`.

        - ``existing`` → :func:`ifcopenshell.api.surface.create_terrain`
          (``IfcGeographicElement[TERRAIN]``).
        - ``proposed_group`` / ``proposed_site`` →
          :func:`ifcopenshell.api.surface.create_proposed_surface`
          (``IfcEarthworksFill[SUBGRADE]``). The two ``proposed_*`` kinds
          differ only in their spatial parent (group vs site); commits 8 / 9
          handle that wiring at the core layer.

        After the API mints a fresh ``GlobalId``, this wrapper rewrites it to
        match :attr:`CivilSurface.guid` so the in-memory dataclass and the IFC
        entity carry the same identifier. Step ids of the host, the
        :class:`IfcTriangulatedIrregularNetwork`, and the
        :class:`IfcBoundingBox` representations are stamped onto the surface.

        .. note::

            The GlobalId overwrite happens *after* all psets and inverse
            references are attached (the underlying API does its work first).
            Inverse references are by step id, not GlobalId, so they survive
            the overwrite intact. Callers must read ``host.GlobalId`` *after*
            this method returns — the value the API minted internally is
            discarded.

        :param ifc_file: target IFC file (typically ``tool.Ifc.get()``).
        :param surface: :class:`CivilSurface` to persist; ``points``,
            ``triangles``, and ``triangle_flags`` must be populated.
        :param site: optional explicit :class:`IfcSite` parent; defaults to the
            file's first ``IfcSite`` (matches the Phase 1 API behavior).
        :param triangulation_tolerance: forwarded to ``Pset_SaikeiGradingSurface``.
        :returns: the created :class:`IfcGeographicElement` or :class:`IfcEarthworksFill`.
        :raises SaikeiSurfaceError: if ``surface.kind`` is not one of the three
            supported values.
        """
        breakline_count = len(surface.breaklines)
        kwargs = {
            "name": surface.name,
            "points": surface.points,
            "triangles": surface.triangles,
            "triangle_flags": surface.triangle_flags,
            "site": site,
            "triangulation_tolerance": triangulation_tolerance,
            "breakline_count": breakline_count,
        }

        if surface.kind == "existing":
            host = ifcopenshell.api.surface.create_terrain(ifc_file, **kwargs)
        elif surface.kind in ("proposed_group", "proposed_site"):
            host = ifcopenshell.api.surface.create_proposed_surface(ifc_file, **kwargs)
        else:
            raise SaikeiSurfaceError(
                f"unknown surface.kind {surface.kind!r}; expected existing, "
                "proposed_group, or proposed_site"
            )

        host.GlobalId = surface.guid
        surface.ifc_host_entity_id = host.id()
        surface.ifc_tin_representation_id = cls._find_tin_id(host)
        surface.ifc_bbox_representation_id = cls._find_bbox_id(host)
        return host

    @classmethod
    def update_ifc_tin(
        cls,
        ifc_file: "ifcopenshell.file",
        surface: CivilSurface,
    ) -> "ifcopenshell.entity_instance":
        """Replace the host entity's existing Body TIN with one freshly
        built from ``surface.points``, ``surface.triangles``, and
        ``surface.triangle_flags``.

        Wraps :func:`ifcopenshell.api.surface.update_tin_representation`. The
        old TIN and its CoordList are garbage-collected if no other entities
        still reference them. The :class:`IfcShapeRepresentation` itself is
        preserved so any inverse references survive.

        :raises SaikeiSurfaceError: if ``surface.ifc_host_entity_id`` is unset
            (call :meth:`author_ifc_host` first) or if the host entity has no
            existing Body representation.
        """
        if surface.ifc_host_entity_id is None:
            raise SaikeiSurfaceError(
                "surface has no IFC host entity; call author_ifc_host first"
            )
        host = ifc_file.by_id(surface.ifc_host_entity_id)
        new_tin = ifcopenshell.api.surface.update_tin_representation(
            ifc_file,
            host,
            points=surface.points,
            triangles=surface.triangles,
            triangle_flags=surface.triangle_flags,
        )
        surface.ifc_tin_representation_id = new_tin.id()
        # Refresh Pset_SaikeiGradingSurface so BreaklineCount /
        # VertexCount stay consistent with the rebuilt TIN. Without this,
        # the pset reflects only the values at create_terrain /
        # create_proposed_surface time and goes stale after every edit.
        ifcopenshell.api.surface.apply_saikei_pset(
            ifc_file,
            host,
            breakline_count=len(surface.breaklines),
        )
        # Refresh the Box LOD bounding box so viewers using it for
        # culling / extents queries see the current geometry. Without
        # this, set_outer_boundary's narrower clip leaves the bbox
        # pointing at the original (larger) extents.
        cls._refresh_bounding_box(host, surface.points)
        return new_tin

    @staticmethod
    def _refresh_bounding_box(
        host: "ifcopenshell.entity_instance",
        points: np.ndarray,
    ) -> None:
        """Update the host's :class:`IfcBoundingBox` ``Corner`` /
        ``XDim`` / ``YDim`` / ``ZDim`` in place from the current points.

        No-op if the host has no Box representation. Updates the existing
        entity rather than replacing it so the IfcShapeRepresentation
        link stays intact and no orphan entities accumulate.
        """
        representation = host.Representation
        if representation is None:
            return
        bbox = None
        for shape_rep in representation.Representations or []:
            if shape_rep.RepresentationIdentifier != "Box":
                continue
            for item in shape_rep.Items or []:
                if item.is_a("IfcBoundingBox"):
                    bbox = item
                    break
            if bbox is not None:
                break
        if bbox is None:
            return

        if len(points) == 0:
            return
        xs = [float(p[0]) for p in points]
        ys = [float(p[1]) for p in points]
        zs = [float(p[2]) for p in points]
        min_xyz = (min(xs), min(ys), min(zs))
        max_xyz = (max(xs), max(ys), max(zs))
        # Match Phase 1 add_bounding_box_representation's positive-dim
        # nudge for axis-aligned degenerate surfaces.
        epsilon = 1e-6
        x_dim = max(max_xyz[0] - min_xyz[0], epsilon)
        y_dim = max(max_xyz[1] - min_xyz[1], epsilon)
        z_dim = max(max_xyz[2] - min_xyz[2], epsilon)

        bbox.Corner.Coordinates = (min_xyz[0], min_xyz[1], min_xyz[2])
        bbox.XDim = x_dim
        bbox.YDim = y_dim
        bbox.ZDim = z_dim

    @classmethod
    def author_ifc_breakline(
        cls,
        ifc_file: "ifcopenshell.file",
        breakline: Breakline,
        site: Optional["ifcopenshell.entity_instance"] = None,
        grading_group_guid: Optional[str] = None,
        host_surface: Optional["ifcopenshell.entity_instance"] = None,
    ) -> "ifcopenshell.entity_instance":
        """Persist ``breakline`` as a separate :class:`IfcAnnotation` entity.

        Breaklines live outside any TIN representation so they survive
        retriangulation (the TIN's :attr:`triangle_flags` independently
        encode breakline-edge membership). Wraps
        :func:`ifcopenshell.api.surface.add_breakline_annotation`.

        :param site: explicit :class:`IfcSite` parent; defaults to the file's
            first ``IfcSite``. Must be supplied if no ``IfcSite`` exists yet.
        :param grading_group_guid: optional GUID linking this breakline to a
            grading group whose retriangulation it participates in.
        :param host_surface: optional :class:`IfcGeographicElement` /
            :class:`IfcEarthworksFill` that this breakline modifies. When
            provided, this method authors an :class:`IfcRelAssignsToProduct`
            relating the annotation to the surface, so multi-surface files
            can disambiguate "which surface owns which breakline" during
            rehydration. Without it, the annotation is recovered as
            site-global and applied to every rehydrated surface (the
            documented Phase 4 fallback).
        :returns: the created :class:`IfcAnnotation`. Its ``GlobalId`` is
            rewritten to match :attr:`Breakline.guid` and the step id is
            stamped on :attr:`Breakline.ifc_annotation_id`.
        :raises SaikeiSurfaceError: if ``site`` is ``None`` and no IfcSite
            exists in the file.
        """
        target_site = cls._resolve_site(ifc_file, site)
        annotation = ifcopenshell.api.surface.add_breakline_annotation(
            ifc_file,
            site=target_site,
            polyline=breakline.polyline,
            name=breakline.name,
            kind=breakline.kind,
            source=breakline.source,
            grading_group_guid=grading_group_guid,
        )
        annotation.GlobalId = breakline.guid
        breakline.ifc_annotation_id = annotation.id()

        if host_surface is not None:
            # IfcRelAssignsToProduct: per IFC 4.3 §IfcRelAssigns,
            # RelatedObjectsType is OPTIONAL (IfcObjectTypeEnum) and is
            # safely omitted here — the relationship is fully specified
            # by RelatingProduct + RelatedObjects.
            ifc_file.create_entity(
                "IfcRelAssignsToProduct",
                GlobalId=ifcopenshell.guid.new(),
                Name=f"BreaklineAssignment/{breakline.name}",
                RelatedObjects=[annotation],
                RelatingProduct=host_surface,
            )

        return annotation

    @staticmethod
    def _resolve_site(
        ifc_file: "ifcopenshell.file",
        site: Optional["ifcopenshell.entity_instance"],
    ) -> "ifcopenshell.entity_instance":
        if site is not None:
            return site
        sites = ifc_file.by_type("IfcSite")
        if not sites:
            raise SaikeiSurfaceError(
                "no IfcSite present in project; pass site= explicitly or add an IfcSite first"
            )
        return sites[0]

    @staticmethod
    def _find_tin_id(host: "ifcopenshell.entity_instance") -> Optional[int]:
        """Return the step id of the host's Body
        :class:`IfcTriangulatedIrregularNetwork`, or ``None`` if absent."""
        representation = host.Representation
        if representation is None:
            return None
        for shape_rep in representation.Representations or []:
            if shape_rep.RepresentationIdentifier == "Body":
                for item in shape_rep.Items or []:
                    if item.is_a("IfcTriangulatedIrregularNetwork"):
                        return item.id()
        return None

    @staticmethod
    def _find_bbox_id(host: "ifcopenshell.entity_instance") -> Optional[int]:
        """Return the step id of the host's Box :class:`IfcBoundingBox`, or
        ``None`` if absent."""
        representation = host.Representation
        if representation is None:
            return None
        for shape_rep in representation.Representations or []:
            if shape_rep.RepresentationIdentifier == "Box":
                for item in shape_rep.Items or []:
                    if item.is_a("IfcBoundingBox"):
                        return item.id()
        return None

    @classmethod
    def create_blender_mesh(
        cls,
        ifc_file: "ifcopenshell.file",
        surface: CivilSurface,
    ) -> bpy.types.Object:
        """Create a Blender mesh + object for ``surface`` and link it to the
        IFC host entity.

        Mirrors the alignment-precedent in
        :meth:`bonsai.tool.alignment.Alignment.create_object_for_alignment`:

        1. If ``tool.Ifc.get_object(host)`` already returns an object, return
           that — no-op for re-entrant calls.
        2. Build a fresh ``bpy.types.Mesh`` from ``surface.points`` and
           ``surface.triangles``, name it ``IfcGeographicElement/<name>`` or
           ``IfcEarthworksFill/<name>``.
        3. Wrap in a new ``bpy.types.Object`` and bind via :func:`tool.Ifc.link`
           for the bidirectional dataclass ↔ Blender ↔ IFC mapping.
        4. Place into the project's collection hierarchy via
           :func:`tool.Collector.assign`.

        :raises SaikeiSurfaceError: if ``surface.ifc_host_entity_id`` is unset
            (call :meth:`author_ifc_host` first).
        """
        if surface.ifc_host_entity_id is None:
            raise SaikeiSurfaceError(
                "surface has no IFC host entity; call author_ifc_host first"
            )
        host = ifc_file.by_id(surface.ifc_host_entity_id)

        existing_obj = tool.Ifc.get_object(host)
        if existing_obj:
            return existing_obj

        display_name = f"{host.is_a()}/{host.Name or surface.guid}"
        mesh = cls._build_mesh_data(surface, mesh_name=display_name)
        obj = bpy.data.objects.new(display_name, mesh)

        tool.Ifc.link(host, obj)
        tool.Collector.assign(obj)
        return obj

    @classmethod
    def update_blender_mesh(
        cls,
        ifc_file: "ifcopenshell.file",
        surface: CivilSurface,
    ) -> Optional[bpy.types.Object]:
        """Rebuild the Blender mesh data for ``surface`` after retriangulation.

        Looks up the Blender object linked to the IFC host, clears the existing
        mesh data, and rebuilds from ``surface.points`` and ``surface.triangles``.
        Returns ``None`` if no Blender object is linked yet (caller may want to
        :meth:`create_blender_mesh` first).
        """
        if surface.ifc_host_entity_id is None:
            return None
        host = ifc_file.by_id(surface.ifc_host_entity_id)
        obj = tool.Ifc.get_object(host)
        if obj is None or not isinstance(obj.data, bpy.types.Mesh):
            return None

        mesh = obj.data
        mesh.clear_geometry()
        verts = [(float(p[0]), float(p[1]), float(p[2])) for p in surface.points]
        faces = [(int(t[0]), int(t[1]), int(t[2])) for t in surface.triangles]
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        return obj

    @staticmethod
    def _build_mesh_data(surface: CivilSurface, mesh_name: str) -> bpy.types.Mesh:
        """Construct a new ``bpy.types.Mesh`` from ``surface.points`` and
        ``surface.triangles``."""
        mesh = bpy.data.meshes.new(mesh_name)
        verts = [(float(p[0]), float(p[1]), float(p[2])) for p in surface.points]
        faces = [(int(t[0]), int(t[1]), int(t[2])) for t in surface.triangles]
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        return mesh

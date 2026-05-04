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

"""Saikei earthwork tool — math, IFC authoring, Blender object linkage.

Phase 6 of the Saikei grading/earthwork sprint. This module owns:

- :class:`VolumeResult` data primitive per spec §6.4 — carries the
  cut / fill volumes plus the closed-solid geometry that gets
  authored to IFC as :class:`IfcEarthworksCut` / :class:`IfcEarthworksFill`
  PolygonalFaceSet bodies.
- TIN-to-TIN prismoidal volume math per spec §6.4 — the canonical
  cut/fill calculation against an existing-vs-proposed surface pair.
- Cut/fill region extraction and closed-solid construction per spec
  §6.5 — turns a sub-triangle delta-Z field into watertight
  PolygonalFaceSet bodies that round-trip through IFC.
- IFC authoring wrappers around :mod:`ifcopenshell.api.earthwork`
  (Phase 3) — handles spatial containment under :class:`IfcSite`,
  :class:`IfcRelVoidsElement` linkage to the host terrain, and
  pre-computed quantity-set authoring (``Qto_EarthworksCut/FillBaseQuantities``,
  ``Pset_SaikeiGradingShrinkSwell``).
- Shrink/swell handling per spec §6.4 — caller supplies factors;
  this module multiplies through to ``LooseVolume`` and writes both
  the Qto and the pset consistently (closes the audit gap where
  ``LooseVolume`` was a pass-through value rather than computed from
  ``UndisturbedVolume × SwellFactor``).
- Blender mesh linkage for the cut/fill solids and the optional
  cut/fill color-map overlay — same pattern as :class:`bonsai.tool.surface`.

The tool layer is the only Saikei layer that imports ``numpy`` /
``shapely`` / ``bpy``. Core stays import-clean (only built-ins +
``ifcopenshell``); UI calls into core which calls into tool.

Subsequent commits land the prismoidal volume algorithm, the
closed-solid construction stages, and the IFC + Blender authoring
wrappers. This commit lands the dataclasses
(:class:`SubTriangle`, :class:`ClosedSolid`, :class:`VolumeResult`)
that the rest of the module references.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

import ifcopenshell
import numpy as np
import shapely

if TYPE_CHECKING:
    from .surface import CivilSurface

_logger = logging.getLogger(__name__)


# Cubic-yards conversion factor (1 m³ = 1.30795 cu yd). Used by the
# imperial-units convenience attributes on :class:`VolumeResult`. Civil
# engineers in the US specify earthwork in cubic yards; metric engineers
# in m³. Authoring stores m³ canonically; the cubic-yard fields are
# read-only views.
_M3_TO_CUBIC_YARDS = 1.307950619314


@dataclass
class SubTriangle:
    """A piece of the TIN-intersection grid used by §6.4 prismoidal
    volume math. Each sub-triangle is the XY intersection of one
    existing-surface triangle, one proposed-surface triangle, and the
    volume domain (existing.outer_boundary ∩ proposed.outer_boundary
    minus holes/voids).

    The signed contribution to total cut volume is
    ``area_m2 * (z_existing_avg - z_proposed_avg)``; positive means
    cut, negative means fill. Per-sub-triangle deltas survive into
    :class:`VolumeResult.per_triangle_deltas` for the optional cut/fill
    color map.
    """

    vertices_xy: np.ndarray
    """``(3, 2)`` array of XY coordinates. Z is reconstructed by
    linearly interpolating the host surfaces — keeping Z out of this
    structure avoids the round-trip noise of carrying it separately
    for two surfaces."""

    z_existing_avg: float
    """Average existing-surface Z over the sub-triangle (mean of the
    three vertex elevations interpolated on the existing TIN)."""

    z_proposed_avg: float
    """Average proposed-surface Z over the sub-triangle."""

    area_m2: float
    """XY-projected area of the sub-triangle, in project units squared
    (m² when the project is metric)."""

    @property
    def delta_z(self) -> float:
        """``z_existing_avg - z_proposed_avg``. Positive = cut
        (existing above proposed → excavate); negative = fill
        (existing below proposed → place fill); zero = at-grade."""
        return self.z_existing_avg - self.z_proposed_avg

    @property
    def signed_volume_m3(self) -> float:
        """Signed prismoidal volume contribution. Sign matches
        :attr:`delta_z`."""
        return self.area_m2 * self.delta_z


@dataclass
class ClosedSolid:
    """Watertight solid geometry ready for :class:`IfcPolygonalFaceSet`
    authoring. The cut and fill solids each become one of these.

    The contract for "watertight" is: every edge in :attr:`faces`
    appears in exactly two faces. Phase 3's
    :func:`ifcopenshell.api.earthwork.create_earthworks_cut` accepts
    these and authors a ``Closed=TRUE`` PolygonalFaceSet directly;
    no further tessellation runs at the IFC API boundary.
    """

    points: np.ndarray
    """``(N, 3)`` array of XYZ vertex coordinates. Indices into this
    array are 0-based on the dataclass surface; the IFC API converts
    to the IFC 1-based convention internally."""

    faces: list[list[int]]
    """List of vertex-index lists. Each face must have ≥ 3 vertices
    (triangles, quads, higher n-gons all valid). Caller is responsible
    for the watertight invariant — Phase 6's
    :meth:`Earthwork.build_cut_solid` / :meth:`build_fill_solid`
    construct these in §6.5's named stages."""


@dataclass
class VolumeResult:
    """Output of a TIN-to-TIN prismoidal volume calculation per spec §6.4.

    Volumes are written to standard IFC quantity sets via Phase 3's
    earthwork API:

    - ``Qto_EarthworksCutBaseQuantities``: ``UndisturbedVolume``,
      ``LooseVolume``, ``Weight``
    - ``Qto_EarthworksFillBaseQuantities``: ``CompactedVolume``,
      ``LooseVolume``

    Shrink/swell factors are written to
    ``Pset_SaikeiGradingShrinkSwell`` (Saikei custom pset, not in the
    IFC 4.3 standard pset library). The spec audit explicitly required
    that ``loose_cut_m3`` be derived from
    ``undisturbed_cut_m3 × swell_factor`` rather than carried as an
    independent input — this dataclass enforces that via
    :meth:`__post_init__`.
    """

    existing_surface_guid: str
    """GUID of the existing-ground :class:`bonsai.tool.surface.CivilSurface`."""

    proposed_surface_guid: str
    """GUID of the proposed-ground :class:`CivilSurface`. May be a
    Phase 5 group composite."""

    undisturbed_cut_m3: float
    """In-situ cut volume — the "bank" cubic-yardage in US parlance
    or "undisturbed" per IFC 4.3. Positive magnitude; never signed."""

    compacted_fill_m3: float
    """In-place compacted fill volume. Positive magnitude. The
    engineering takeoff number for fill quantities."""

    shrink_factor: float = 1.0
    """Fill-side shrinkage ratio (compacted / bank). Caller-supplied;
    typical values 0.85–0.95 depending on soil type. ``1.0`` means
    no shrinkage. Used by Phase 6 callers that need the bank-volume
    of fill source material."""

    swell_factor: float = 1.0
    """Cut-side swell ratio (loose / bank). Caller-supplied; typical
    values 1.10–1.30 depending on soil type. ``1.0`` means no swell.
    Multiplied through to :attr:`loose_cut_m3` in :meth:`__post_init__`
    so the Qto is internally consistent — closes the spec audit gap
    where ``LooseVolume`` was a pass-through value."""

    cut_solid: Optional[ClosedSolid] = None
    """Closed-solid geometry for the cut. Authored as
    :class:`IfcEarthworksCut` body (PolygonalFaceSet, Closed=TRUE).
    None until §6.5's solid construction runs; Phase 6 commit 5
    populates this."""

    fill_solid: Optional[ClosedSolid] = None
    """Closed-solid geometry for the fill. Authored as
    :class:`IfcEarthworksFill` body. None until §6.5's solid
    construction runs."""

    per_triangle_deltas: Optional[np.ndarray] = None
    """Optional ``(N,)`` array of per-sub-triangle ``delta_z`` values
    for the cut/fill color map. Aligned with the sub-triangle order
    out of the §6.4 intersection. ``None`` if the caller didn't request
    the color map."""

    ifc_cut_id: Optional[int] = None
    """Step id of the persisted :class:`IfcEarthworksCut`. Stamped by
    :meth:`Earthwork.author_cut_solid` after IFC authoring runs."""

    ifc_fill_id: Optional[int] = None
    """Step id of the persisted :class:`IfcEarthworksFill`."""

    guid: str = field(default_factory=ifcopenshell.guid.new)
    """Stable identifier for the registry. Volume results are keyed
    by GUID rather than by surface-pair GUIDs so multiple volume
    calculations against the same pair (e.g., before/after a
    shrink/swell adjustment) coexist."""

    def __post_init__(self) -> None:
        """Validate and propagate derived quantities.

        - ``undisturbed_cut_m3`` and ``compacted_fill_m3`` must be
          non-negative (volumes are magnitudes; signedness is
          captured by the cut-vs-fill split).
        - ``shrink_factor`` and ``swell_factor`` must be positive
          (a zero or negative factor would produce nonsense quantities).
        """
        if self.undisturbed_cut_m3 < 0:
            raise ValueError(
                f"undisturbed_cut_m3 must be ≥ 0; got {self.undisturbed_cut_m3}"
            )
        if self.compacted_fill_m3 < 0:
            raise ValueError(
                f"compacted_fill_m3 must be ≥ 0; got {self.compacted_fill_m3}"
            )
        if self.shrink_factor <= 0:
            raise ValueError(
                f"shrink_factor must be > 0; got {self.shrink_factor}"
            )
        if self.swell_factor <= 0:
            raise ValueError(
                f"swell_factor must be > 0; got {self.swell_factor}"
            )

    @property
    def loose_cut_m3(self) -> float:
        """Loose / bulked / swelled volume of cut material —
        ``undisturbed_cut_m3 × swell_factor``. The "haul" volume in
        construction parlance: how much truck space the excavated
        material occupies before recompaction."""
        return self.undisturbed_cut_m3 * self.swell_factor

    @property
    def bank_fill_m3(self) -> float:
        """Bank-volume equivalent of the placed fill —
        ``compacted_fill_m3 / shrink_factor``. The "borrow" quantity
        if the fill must be sourced from a bank-volume measured site
        (offsite borrow pit, balanced-haul calculation)."""
        return self.compacted_fill_m3 / self.shrink_factor

    @property
    def net_volume_m3(self) -> float:
        """``undisturbed_cut_m3 - compacted_fill_m3``. Positive = net
        excavation (haul-off site); negative = net import (borrow);
        zero = balanced earthwork. The single most-asked-for number
        in any earthwork report."""
        return self.undisturbed_cut_m3 - self.compacted_fill_m3

    @property
    def cut_cubic_yards(self) -> float:
        """Imperial-units convenience: ``undisturbed_cut_m3``
        converted to cubic yards (1 m³ = 1.307950619 cu yd)."""
        return self.undisturbed_cut_m3 * _M3_TO_CUBIC_YARDS

    @property
    def fill_cubic_yards(self) -> float:
        """Imperial-units convenience: ``compacted_fill_m3`` in cu yd."""
        return self.compacted_fill_m3 * _M3_TO_CUBIC_YARDS

    @property
    def net_cubic_yards(self) -> float:
        """Imperial-units convenience: ``net_volume_m3`` in cu yd."""
        return self.net_volume_m3 * _M3_TO_CUBIC_YARDS


class SaikeiEarthworkError(Exception):
    """Base exception for tool.Earthwork failures.

    Volume-math edge cases (zero-domain intersection, degenerate
    triangulation) and solid-construction failures (non-manifold
    geometry, watertightness violations) raise this so operators can
    catch a single typed exception and report cleanly.

    Subclasses may be added in future commits as specific failure
    modes need finer-grained handling (mirroring
    :class:`bonsai.tool.grading.SaikeiGradingError` family).
    """


class Earthwork:
    """Earthwork tool surface — Phase 6 entry point.

    Per :class:`bonsai.tool.surface.Surface` and
    :class:`bonsai.tool.grading.Grading` precedents, all methods are
    classmethods (no instance state); per-file caches live in
    :attr:`_registry` keyed by ``(id(ifc_file), guid)``.

    Subsequent commits flesh this out with the prismoidal volume
    method, the cut/fill solid constructors, and the IFC authoring
    wrappers around :mod:`ifcopenshell.api.earthwork`.
    """

    _registry: dict[tuple[int, str], object] = {}
    """Per spec §4.6: lazy-rehydrating cache keyed by ``(id(ifc_file),
    guid)``. Stores :class:`VolumeResult` instances once Phase 6
    commit 2 lands the dataclass. Headless tests call :meth:`clear`
    in autouse teardown to prevent cross-test contamination."""

    @classmethod
    def clear(cls) -> None:
        """Wipe the entire registry. Headless test teardown calls
        this to prevent cross-test contamination."""
        cls._registry.clear()

    # ------------------------------------------------------------------
    # TIN-to-TIN prismoidal volume — spec §6.4
    # ------------------------------------------------------------------

    @classmethod
    def compute_volumes(
        cls,
        existing_surface: "CivilSurface",
        proposed_surface: "CivilSurface",
        domain: Optional[shapely.Polygon] = None,
        shrink_factor: float = 1.0,
        swell_factor: float = 1.0,
        capture_per_triangle_deltas: bool = False,
        build_solids: bool = False,
    ) -> VolumeResult:
        """Compute cut and fill volumes between two surfaces.

        Implements the spec §6.4 algorithm: resolve the volume domain
        as the intersection of the two outer boundaries (with
        convex-hull fallback when boundaries are unset, per §6.4 step
        1), then for every overlapping triangle pair clip and
        triangulate the XY intersection, accumulating signed
        prismoidal volume = ``area × (z_existing - z_proposed)``.
        Positive contributions accumulate into ``undisturbed_cut_m3``;
        negative contributions accumulate into ``compacted_fill_m3``
        as a positive magnitude.

        Broad phase uses a Shapely STRtree on existing triangles to
        cull non-overlapping pairs in O(log N); narrow phase is the
        explicit Shapely intersection. The implementation runs in
        Python so per-call overhead matters for large surfaces; for
        the typical Saikei pad / corridor scale (≤ 10⁴ triangles per
        surface) this finishes well under one second.

        :param existing_surface: the existing-ground TIN. Typically an
            :class:`IfcGeographicElement[TERRAIN]`.
        :param proposed_surface: the proposed-ground TIN. May be a
            Phase 5 group composite (``IfcEarthworksFill[SUBGRADE]``).
        :param domain: optional explicit volume-domain polygon. If
            ``None``, derived from the intersection of the two
            surfaces' outer boundaries; if either is unset, that
            surface's convex hull stands in.
        :param shrink_factor: forwarded into the result; default 1.0
            (no shrinkage). See :class:`VolumeResult.shrink_factor`.
        :param swell_factor: forwarded into the result; default 1.0
            (no swell). See :class:`VolumeResult.swell_factor`.
        :param capture_per_triangle_deltas: when True, the result's
            ``per_triangle_deltas`` field is populated with one
            entry per sub-triangle in iteration order. Used by the
            optional cut/fill color-map overlay (Phase 6 commit 12+).
        :param build_solids: when True, the result's ``cut_solid``
            and ``fill_solid`` fields are populated with closed-solid
            geometry (a "prism soup" — one triangular prism per
            sub-triangle, 6 vertices and 5 faces each). Each prism
            independently bounds a watertight chunk of cut / fill
            volume; the IFC PolygonalFaceSet body holds the union
            of all of them. Volumes from the prisms agree with the
            Qto values (both come from the same sub-triangle pass).
        :returns: a :class:`VolumeResult` with cut / fill magnitudes
            populated.
        """
        domain = cls._resolve_volume_domain(
            existing_surface, proposed_surface, domain
        )
        if domain.is_empty:
            return VolumeResult(
                existing_surface_guid=existing_surface.guid,
                proposed_surface_guid=proposed_surface.guid,
                undisturbed_cut_m3=0.0,
                compacted_fill_m3=0.0,
                shrink_factor=shrink_factor,
                swell_factor=swell_factor,
                per_triangle_deltas=(
                    np.zeros(0, dtype=float)
                    if capture_per_triangle_deltas else None
                ),
            )

        existing_polys = cls._triangle_polygons(existing_surface)
        proposed_polys = cls._triangle_polygons(proposed_surface)
        existing_tree = shapely.STRtree(existing_polys)

        cut_total = 0.0
        fill_total = 0.0
        deltas: list[float] = []
        cut_subs: list[SubTriangle] = []
        fill_subs: list[SubTriangle] = []

        for proposed_poly in proposed_polys:
            candidate_indices = existing_tree.query(proposed_poly)
            if len(candidate_indices) == 0:
                continue
            for idx in candidate_indices:
                existing_poly = existing_polys[int(idx)]
                pair_intersection = proposed_poly.intersection(existing_poly)
                if pair_intersection.is_empty:
                    continue
                clipped = pair_intersection.intersection(domain)
                if clipped.is_empty or clipped.area <= 0:
                    continue
                # Triangulate the (possibly polygonal) overlap so
                # prismoidal integration sees only triangles. Shapely's
                # constrained_delaunay_triangles is the same primitive
                # tool.Surface uses for breakline triangulation; it
                # returns a GeometryCollection of Polygons, so we
                # iterate.
                for sub_geom in cls._iter_sub_triangles(clipped):
                    sub_tri = cls._make_sub_triangle(
                        sub_geom, existing_surface, proposed_surface
                    )
                    if sub_tri is None or sub_tri.area_m2 <= 0:
                        continue
                    signed = sub_tri.signed_volume_m3
                    if capture_per_triangle_deltas:
                        deltas.append(sub_tri.delta_z)
                    if signed > 0:
                        cut_total += signed
                        if build_solids:
                            cut_subs.append(sub_tri)
                    elif signed < 0:
                        fill_total += -signed
                        if build_solids:
                            fill_subs.append(sub_tri)

        cut_solid = (
            cls._build_prism_soup_solid(cut_subs) if build_solids else None
        )
        fill_solid = (
            cls._build_prism_soup_solid(fill_subs) if build_solids else None
        )

        return VolumeResult(
            existing_surface_guid=existing_surface.guid,
            proposed_surface_guid=proposed_surface.guid,
            undisturbed_cut_m3=float(cut_total),
            compacted_fill_m3=float(fill_total),
            shrink_factor=shrink_factor,
            swell_factor=swell_factor,
            cut_solid=cut_solid,
            fill_solid=fill_solid,
            per_triangle_deltas=(
                np.asarray(deltas, dtype=float)
                if capture_per_triangle_deltas else None
            ),
        )

    # ------------------------------------------------------------------
    # Volume-math internals
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_volume_domain(
        existing: "CivilSurface",
        proposed: "CivilSurface",
        explicit: Optional[shapely.Polygon],
    ) -> shapely.Polygon:
        """Resolve the volume domain per spec §6.4 step 1+2.

        - Caller-supplied ``explicit`` wins.
        - Otherwise, intersect each surface's ``outer_boundary``
          (or convex hull when unset).
        - Each surface's holes / voids are subtracted from its own
          contribution before intersection.
        """
        if explicit is not None:
            return explicit
        existing_domain = Earthwork._surface_xy_domain(existing)
        proposed_domain = Earthwork._surface_xy_domain(proposed)
        return existing_domain.intersection(proposed_domain)

    @staticmethod
    def _surface_xy_domain(surface: "CivilSurface") -> shapely.Polygon:
        """Build the XY domain of a single surface: outer_boundary
        (or convex hull) minus holes minus voids."""
        if surface.outer_boundary is not None:
            outer = shapely.Polygon(surface.outer_boundary)
        elif len(surface.points) >= 3:
            outer = shapely.MultiPoint(
                [(float(p[0]), float(p[1])) for p in surface.points]
            ).convex_hull
            if outer.geom_type != "Polygon":
                # Degenerate (collinear / single point) — domain is empty.
                return shapely.Polygon()
        else:
            return shapely.Polygon()
        for hole in (getattr(surface, "holes", None) or []):
            outer = outer.difference(shapely.Polygon(hole))
        for void in (getattr(surface, "voids", None) or []):
            outer = outer.difference(shapely.Polygon(void))
        return outer

    @staticmethod
    def _triangle_polygons(
        surface: "CivilSurface",
    ) -> list[shapely.Polygon]:
        """Return one Shapely polygon per triangle in ``surface``.
        Used for STRtree broad-phase + narrow-phase intersection."""
        polys: list[shapely.Polygon] = []
        for triangle in surface.triangles:
            a = surface.points[int(triangle[0])]
            b = surface.points[int(triangle[1])]
            c = surface.points[int(triangle[2])]
            poly = shapely.Polygon(
                [
                    (float(a[0]), float(a[1])),
                    (float(b[0]), float(b[1])),
                    (float(c[0]), float(c[1])),
                ]
            )
            if poly.is_valid and poly.area > 0:
                polys.append(poly)
            else:
                # Defensive: the TIN should not contain degenerate
                # triangles, but Phase 5 composite outputs occasionally
                # do (zero-area edge case in the boundary triangulation).
                # Drop them silently rather than fail the whole volume
                # calculation.
                polys.append(shapely.Polygon())
        return polys

    @staticmethod
    def _iter_sub_triangles(geom):
        """Yield triangle-shaped Polygons covering ``geom``.

        Shapely's intersection of two convex triangles is itself
        convex (triangle, quad, pentagon, or hexagon), so triangulating
        always succeeds for non-degenerate inputs. ``constrained_delaunay_triangles``
        returns a GeometryCollection of triangle Polygons even when
        the input is already a triangle — uniform interface.
        """
        if geom.is_empty:
            return
        if geom.geom_type == "Polygon":
            polys = [geom]
        elif geom.geom_type in {"MultiPolygon", "GeometryCollection"}:
            polys = [g for g in geom.geoms if g.geom_type == "Polygon"]
        else:
            return
        for poly in polys:
            if poly.area <= 0:
                continue
            try:
                triangulated = shapely.constrained_delaunay_triangles(poly)
            except Exception as exc:
                _logger.debug(
                    "skipping sub-polygon during volume integration: %s",
                    exc,
                )
                continue
            if triangulated.is_empty:
                continue
            for tri in triangulated.geoms:
                if tri.geom_type == "Polygon" and tri.area > 0:
                    yield tri

    @staticmethod
    def _build_prism_soup_solid(
        sub_triangles: list[SubTriangle],
    ) -> Optional[ClosedSolid]:
        """Build a prism-soup :class:`ClosedSolid` covering all
        ``sub_triangles``. One triangular prism per sub-triangle —
        6 vertices (3 on existing, 3 on proposed) and 5 faces (top
        triangle, bottom triangle, 3 side quads).

        Each prism is independently watertight; the IFC PolygonalFaceSet
        body holds the union of all of them. This is the spec §6.5
        MVP solid construction — a single connected manifold per
        cut/fill region (the §6.5 "stages" approach with zero-delta
        contour boundary stitching) is a Phase 6.1 refinement.

        :returns: ``None`` if ``sub_triangles`` is empty (no cut/fill
            volume to author); otherwise a :class:`ClosedSolid` with
            ``points.shape == (6N, 3)`` and ``len(faces) == 5N``.
        """
        if not sub_triangles:
            return None

        all_points: list[tuple[float, float, float]] = []
        all_faces: list[list[int]] = []

        for sub in sub_triangles:
            base = len(all_points)
            xy = sub.vertices_xy
            # 3 vertices on the proposed surface (bottom of cut, top
            # of fill — orientation-agnostic; faces below define
            # outward normals).
            for x, y in xy:
                all_points.append(
                    (float(x), float(y), float(sub.z_proposed_avg))
                )
            # 3 vertices on the existing surface (top of cut, bottom
            # of fill).
            for x, y in xy:
                all_points.append(
                    (float(x), float(y), float(sub.z_existing_avg))
                )
            # Vertex layout per prism:
            #   p0,p1,p2 = proposed-Z triangle
            #   p3,p4,p5 = existing-Z triangle (same XY, different Z)
            p0, p1, p2, p3, p4, p5 = (base + i for i in range(6))
            # Cap faces. Order picks outward normals consistent for
            # cut prisms (existing above proposed); fill prisms use
            # the same definition geometrically since signed volumes
            # are tracked by the dataclass, not the geometry.
            all_faces.append([p3, p4, p5])  # top  (existing-Z tri)
            all_faces.append([p2, p1, p0])  # bottom (proposed-Z tri, reversed)
            # Side quads — 3 of them, one per prism edge.
            all_faces.append([p0, p1, p4, p3])
            all_faces.append([p1, p2, p5, p4])
            all_faces.append([p2, p0, p3, p5])

        points_array = np.asarray(all_points, dtype=float)
        return ClosedSolid(points=points_array, faces=all_faces)

    @staticmethod
    def _make_sub_triangle(
        tri: shapely.Polygon,
        existing: "CivilSurface",
        proposed: "CivilSurface",
    ) -> Optional[SubTriangle]:
        """Build a :class:`SubTriangle` from a Shapely triangle by
        interpolating Z on both surfaces at each vertex.

        Returns ``None`` if any vertex falls outside either surface's
        triangulation — defensive guard for boundary-tolerance cases
        where the volume domain extends past the actual triangulated
        region by sub-millimetre amounts.
        """
        # Lazy import — surface module is the heavyweight one and
        # importing it at module-top would force every earthwork
        # import to pull in numpy / shapely / scipy.
        from .surface import Surface as _SurfaceTool

        coords = list(tri.exterior.coords)
        if len(coords) < 4:  # triangle is 3 unique + closing repeat
            return None
        vertices_xy = np.array([(float(x), float(y)) for x, y in coords[:3]])
        z_existing_vals: list[float] = []
        z_proposed_vals: list[float] = []
        for x, y in vertices_xy:
            z_e = _SurfaceTool.z_at(existing, float(x), float(y))
            z_p = _SurfaceTool.z_at(proposed, float(x), float(y))
            if z_e is None or z_p is None:
                return None
            z_existing_vals.append(z_e)
            z_proposed_vals.append(z_p)
        return SubTriangle(
            vertices_xy=vertices_xy,
            z_existing_avg=float(np.mean(z_existing_vals)),
            z_proposed_avg=float(np.mean(z_proposed_vals)),
            area_m2=float(tri.area),
        )

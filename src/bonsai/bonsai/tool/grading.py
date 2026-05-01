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

"""Saikei grading tool layer — slope projection, IFC authoring, Blender linkage.

Phase 5 of the Saikei grading/earthwork sprint. This module owns:

- Data primitives :class:`FeatureLine`, :class:`GradingCriteria`,
  :class:`GradingObject`, :class:`GradingGroup` per spec §5.
- Slope projection math per spec §6.2 — `compute_grading_object`
  dispatches by ``criteria.target_kind`` to the four projection
  implementations (surface, elevation, relative_elevation, distance).
- IFC authoring wrappers around :mod:`ifcopenshell.api.grading`.
- Group composite-surface assembly per spec §6.3 (feature-line
  vertices + daylight-line vertices + ribbon triangles + interior fill
  → one ``proposed_group`` :class:`bonsai.tool.surface.CivilSurface`).
- Registry pattern matching :mod:`bonsai.tool.surface` (per spec §4.6).
- Blender object linkage (feature lines as curve objects, groups as
  Empty parents).

Subsequent commits add the :class:`Triangulator`-equivalent dispatcher,
the IFC authoring wrappers, the registry, and the group composition
math. This scaffold lands the dataclasses + typed exceptions that the
rest of the module references.

The tool layer is the only Saikei layer that imports ``numpy`` /
``shapely`` / ``bpy``. Core stays import-clean (only built-ins +
``ifcopenshell``); UI calls into core which calls into tool.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Optional, Union

import ifcopenshell.guid
import numpy as np
import shapely

if TYPE_CHECKING:
    import ifcopenshell

    from .surface import CivilSurface


_logger = logging.getLogger("bonsai.tool.grading")


# ---------------------------------------------------------------------------
# Slope-projection tunables — committed defaults
# ---------------------------------------------------------------------------
#
# These are queued for documentation in spec v3.2.5 (per
# .claude/skills/earthwork/v3.2.5_spec_amendments_queue.md item 3). The
# current values were tuned against typical civil-engineering project
# scales (1 m to 10 km extents in metric units, ~0.1–10 m grading steps).
# Override via the kwargs on :meth:`Grading.compute_grading_object`.

DEFAULT_SAMPLE_STEP = 1.0
"""Distance (project units, typically metres) between sample points along
each feature-line segment. Smaller = more daylight-line resolution but
linear cost. 1 m suits typical pad / corridor work."""

DEFAULT_MARCH_STEP = 0.5
"""Horizontal distance (project units) per outward-march iteration when
hunting for daylight against a target surface. Smaller = more accurate
crossing detection but higher per-sample cost. 0.5 m halves the
typical surface triangle scale; bisection refines further."""

DEFAULT_DAYLIGHT_EPSILON = 1e-3
"""Vertical tolerance (project units) for declaring "the slope hit the
target." 1 mm in metric — well below survey accuracy, comfortably above
IEEE 754 noise."""

DEFAULT_MAX_ITER = 10_000
"""Marching-loop iteration cap per sample point. At ``DEFAULT_MARCH_STEP
= 0.5 m`` this allows 5 km of horizontal projection before raising
:class:`SaikeiSlopeProjectionError` — far beyond any realistic civil
grading reach."""


# ---------------------------------------------------------------------------
# Typed exceptions
# ---------------------------------------------------------------------------


class SaikeiGradingError(Exception):
    """Base exception for the Saikei grading tool layer.

    Operators catch this (and its subclasses below) to convert tool-layer
    failures into ``self.report({"ERROR"}, ...)`` + ``CANCELLED`` per the
    spec §8.5 modal/headless contract. Headless callers receive the raw
    exception.
    """


class SaikeiSlopeProjectionError(SaikeiGradingError):
    """Raised when slope projection fails to produce a valid daylight line.

    Common causes:

    - Marching loop hit ``max_iter`` without intersecting the target
      surface (and ``retaining_wall_at_limit`` is ``False``).
    - Daylight line self-intersects (tight concave feature lines —
      Phase 5 MVP doesn't auto-resolve, raises instead).
    - ``criteria.target_kind == "surface"`` but the target surface has
      no triangulation at the projection sample XY.
    """


# ---------------------------------------------------------------------------
# Data primitives (spec §5)
# ---------------------------------------------------------------------------


@dataclass
class FeatureLine:
    """A 3D polyline used as a grading footprint. Civil 3D's Feature Line
    analog. Persisted to IFC as :class:`IfcAlignment` with an
    :class:`IfcIndexedPolyCurve` representation under the alignment Axis
    subcontext (per Phase 2's :func:`ifcopenshell.api.grading.create_feature_line`).
    """

    guid: str = field(default_factory=ifcopenshell.guid.new)
    """Stable identifier matching the IFC GlobalId. Defaults to a fresh
    ``ifcopenshell.guid.new()`` so the dataclass is constructible without
    minting one in the operator layer."""

    name: str = ""
    """Human-readable label."""

    vertices: list[tuple[float, float, float]] = field(default_factory=list)
    """Ordered ``(x, y, z)`` vertex sequence; at least two points required
    for slope projection."""

    closed: bool = False
    """True for closed loops (pad perimeters), False for open lines (e.g.,
    ditch centerlines). Affects slope-projection outward-direction
    determination — closed loops use polygon orientation; open lines
    require explicit side selection."""

    grading_group: Optional[str] = None
    """GUID of the parent :class:`GradingGroup`, or ``None`` if the feature
    line is unassigned."""

    ifc_alignment_id: Optional[int] = None
    """Step id of the persisted :class:`IfcAlignment`, or ``None`` if the
    feature line has not been authored to IFC yet."""


@dataclass
class GradingCriteria:
    """A rule for projecting a slope from a feature line. Civil 3D's
    Grading Criteria analog. Persisted as :class:`IfcPropertySetTemplate`
    at project scope (reusable, singleton-per-shape); instances are bound
    to grading groups via :class:`IfcRelDefinesByTemplate` per Phase 2's
    :func:`ifcopenshell.api.grading.assign_grading_criteria`.

    The four ``target_kind`` values map to the four Civil 3D base targets;
    ``target_ref`` is interpreted accordingly:

    - ``surface`` — ``target_ref`` is a :class:`CivilSurface` GUID. Slope
      marches outward until it intersects the target surface (daylights).
    - ``elevation`` — ``target_ref`` is an absolute Z value (float). Slope
      marches outward until it reaches that elevation.
    - ``relative_elevation`` — ``target_ref`` is a Z delta from the feature
      line. Slope marches outward by ``target_ref`` units of elevation
      change.
    - ``distance`` — ``target_ref`` is a horizontal distance (float). Slope
      runs out at exactly that horizontal offset, regardless of target.
    """

    guid: str = field(default_factory=ifcopenshell.guid.new)
    """Stable identifier matching the IFC GlobalId of the
    :class:`IfcPropertySetTemplate`."""

    name: str = ""
    """Human-readable label (e.g., ``"3:1 fill / 2:1 cut"``)."""

    target_kind: Literal[
        "surface", "elevation", "relative_elevation", "distance"
    ] = "surface"
    """Which Civil 3D target type the criteria implements."""

    target_ref: Union[str, float] = ""
    """For ``surface`` kind: the target :class:`CivilSurface` GUID.
    For the three numeric kinds: the absolute / relative elevation or
    distance value."""

    cut_slope: float = 2.0
    """Cut-side slope as ``H:V`` ratio. ``2.0`` means 2 horizontal to 1
    vertical (a 2:1 slope). Used when the feature line is below target."""

    fill_slope: float = 3.0
    """Fill-side slope as ``H:V`` ratio. Used when the feature line is
    above target."""

    max_distance: Optional[float] = None
    """Horizontal cap on the slope projection. ``None`` means unlimited
    (project until daylight). When set, the projection terminates at the
    cap if the target hasn't been reached."""

    retaining_wall_at_limit: bool = False
    """If ``True`` and the projection hits ``max_distance`` before reaching
    the target, insert a vertical retaining-wall segment to close the
    geometry rather than raising :class:`SaikeiSlopeProjectionError`."""

    ifc_template_id: Optional[int] = None
    """Step id of the persisted :class:`IfcPropertySetTemplate`."""


@dataclass
class GradingObject:
    """A feature line + criteria, producing one slope-projection ribbon.
    Civil 3D's Grading analog. Persisted as
    :class:`IfcEarthworksFill[SLOPEFILL]` per Phase 2's
    :func:`ifcopenshell.api.grading.add_slope_fill_to_group`.

    Edits to ``footprint`` (the feature line) trigger a rebuild — the
    ``daylight_line`` / ``projection_triangles`` / ``projection_points``
    fields are computed outputs, not authoring inputs. Spec §6.2 governs
    the projection algorithm.
    """

    guid: str = field(default_factory=ifcopenshell.guid.new)
    """Stable identifier matching the IFC GlobalId of the slope-fill
    entity."""

    name: str = ""
    """Human-readable label, typically ``"<feature-line-name> @ <criteria-name>"``."""

    footprint: Optional[FeatureLine] = None
    """The feature line driving the projection. ``None`` until populated
    by the orchestrator."""

    criteria: Optional[GradingCriteria] = None
    """The slope rule applied along the footprint. ``None`` until
    populated by the orchestrator."""

    target_surface_guid: Optional[str] = None
    """For ``criteria.target_kind == "surface"``: the GUID of the target
    :class:`CivilSurface` (existing-ground). Mirrors
    ``criteria.target_ref`` but typed as a GUID for type-safe lookups."""

    daylight_line: list[tuple[float, float, float]] = field(default_factory=list)
    """Computed 3D polyline of tie-out points where the slope intersects
    the target. One vertex per feature-line segment sample point."""

    projection_points: np.ndarray = field(
        default_factory=lambda: np.zeros((0, 3), dtype=float)
    )
    """``(N, 3)`` array of XYZ coordinates for the slope-fill ribbon
    (footprint vertices + daylight-line vertices interleaved)."""

    projection_triangles: np.ndarray = field(
        default_factory=lambda: np.zeros((0, 3), dtype=int)
    )
    """``(M, 3)`` int array of vertex indices into ``projection_points``,
    counterclockwise from above per IFC right-hand rule. Two triangles
    per sample step (the ribbon between feature line and daylight line)."""

    ifc_slope_fill_id: Optional[int] = None
    """Step id of the persisted :class:`IfcEarthworksFill[SLOPEFILL]`."""


@dataclass
class GradingGroup:
    """A collection of :class:`GradingObject` instances composing one
    graded feature. Civil 3D's Grading Group analog. Produces one
    composite proposed surface and one earthwork report.

    Persisted to IFC as a tuple of:

    - :class:`IfcGroup` with ``ObjectType="GradingGroup"`` (the logical
      collection; not in the spatial tree — discovered via
      :class:`IfcRelAssignsToGroup` queries).
    - :class:`IfcEarthworksFill[SUBGRADE]` per-group composite that
      aggregates the slope and interior fills via
      :class:`IfcRelAggregates`. Authored by Phase 2's
      :func:`ifcopenshell.api.grading.create_grading_group`.
    """

    guid: str = field(default_factory=ifcopenshell.guid.new)
    """Stable identifier matching the IFC GlobalId of the
    :class:`IfcGroup`."""

    name: str = ""
    """Human-readable label (e.g., ``"North Pad Grading"``)."""

    members: list[GradingObject] = field(default_factory=list)
    """Ordered list of grading objects in this group. Order matters for
    UI display only; composition (§6.3) is order-independent."""

    interior_fill: Literal[
        "none", "flat", "interpolate_from_boundary", "from_surface"
    ] = "interpolate_from_boundary"
    """Interior-fill strategy per spec §6.3:

    - ``none`` — no interior fill; the composite surface has a hole
      where the group's perimeter encloses no fill geometry.
    - ``flat`` — interior is a flat surface at the average feature-line
      elevation.
    - ``interpolate_from_boundary`` — Delaunay triangulation using
      feature-line vertices only (the most common Civil 3D default).
    - ``from_surface`` — use ``interior_fill_source_guid`` as the
      interior surface (pit-bottom / pre-designed pad-bottom case).
    """

    interior_fill_source_guid: Optional[str] = None
    """For ``interior_fill == "from_surface"``: GUID of the
    :class:`CivilSurface` providing the interior. Ignored for the other
    strategies."""

    target_surface_guid: Optional[str] = None
    """GUID of the existing-ground :class:`CivilSurface` the group's
    slopes project to. Cached on the group for efficient
    re-resolution on every rebuild."""

    output_surface_guid: Optional[str] = None
    """GUID of the composite ``proposed_group`` :class:`CivilSurface`
    produced by :meth:`Grading.rebuild_group_surface`. ``None`` until
    the first rebuild runs."""

    ifc_group_id: Optional[int] = None
    """Step id of the persisted :class:`IfcGroup[GradingGroup]`."""

    ifc_composite_fill_id: Optional[int] = None
    """Step id of the persisted aggregating
    :class:`IfcEarthworksFill[SUBGRADE]` composite."""

    ifc_interior_fill_id: Optional[int] = None
    """Step id of the per-group interior
    :class:`IfcEarthworksFill[SUBGRADE]` (when ``interior_fill != "none"``)."""

    metadata: dict = field(default_factory=dict)
    """Free-form per-group scratchpad; not persisted to IFC. Mirrors
    :attr:`bonsai.tool.surface.CivilSurface.metadata` so caches (e.g.,
    cached composite surface, last-rebuild timestamp) live alongside
    the data without polluting the IFC-facing fields."""


# ---------------------------------------------------------------------------
# Tool-layer entry point — slope projection (spec §6.2)
# ---------------------------------------------------------------------------


class Grading:
    """Tool-layer entry point for grading math, IFC authoring, and Blender
    linkage. Per spec §7.2 each method is a static or class method called
    from :mod:`bonsai.core.grading` orchestration.

    Subsequent commits add IFC authoring wrappers, the registry / lazy
    rehydration cache, and the group composite-surface assembly. This
    commit lands the slope-projection math (spec §6.2): given a feature
    line + criteria + target surface, compute a daylight line + ribbon
    triangulation suitable for authoring as
    :class:`IfcEarthworksFill[SLOPEFILL]`.
    """

    @classmethod
    def compute_grading_object(
        cls,
        feature_line: FeatureLine,
        criteria: GradingCriteria,
        target_surface: Optional["CivilSurface"] = None,
        sample_step: float = DEFAULT_SAMPLE_STEP,
        march_step: float = DEFAULT_MARCH_STEP,
        daylight_epsilon: float = DEFAULT_DAYLIGHT_EPSILON,
        max_iter: int = DEFAULT_MAX_ITER,
        side: Literal["left", "right", "auto"] = "auto",
        name: str = "",
    ) -> GradingObject:
        """Project a slope from ``feature_line`` per ``criteria`` and return
        a :class:`GradingObject` with daylight-line + ribbon triangulation.

        Per spec §6.2 the algorithm:

        1. Walk the feature line, sampling at ``sample_step`` intervals.
        2. At each sample, determine outward direction (closed loops:
           away from polygon interior; open loops: caller-specified
           ``side``).
        3. Dispatch by ``criteria.target_kind`` to the four projection
           implementations (surface / elevation / relative_elevation /
           distance).
        4. Triangulate the ribbon between the feature line and the
           daylight line — two triangles per consecutive sample pair.

        :param feature_line: footprint polyline driving the projection;
            requires ≥ 2 vertices.
        :param criteria: slope rule.
        :param target_surface: required when
            ``criteria.target_kind == "surface"``; ignored otherwise.
        :param sample_step: distance between sample points along each
            segment. Defaults to :data:`DEFAULT_SAMPLE_STEP`.
        :param march_step: horizontal distance per outward-march
            iteration (only used for ``surface`` kind).
        :param daylight_epsilon: vertical-distance tolerance for "the
            slope hit the target" (only used for ``surface`` kind).
        :param max_iter: marching-loop iteration cap per sample (only
            used for ``surface`` kind).
        :param side: outward direction for open feature lines —
            ``"left"`` or ``"right"`` of the traversal direction. For
            closed loops, ``"auto"`` (default) detects orientation;
            ``"left"`` / ``"right"`` overrides the auto-detection.
        :param name: human-readable label for the resulting
            :class:`GradingObject`. Defaults to empty string.
        :returns: a :class:`GradingObject` with ``footprint``, ``criteria``,
            ``daylight_line``, ``projection_points``, and
            ``projection_triangles`` populated.
        :raises SaikeiGradingError: on input validation (too-short feature
            line, missing target_surface for surface kind, invalid side
            for open feature line).
        :raises SaikeiSlopeProjectionError: on marching-loop failures
            (max_iter exceeded without daylight, max_distance exceeded
            without retaining-wall fallback, surface query returned None
            mid-march).
        """
        if len(feature_line.vertices) < 2:
            raise SaikeiGradingError(
                f"feature line needs ≥ 2 vertices for projection; "
                f"got {len(feature_line.vertices)}"
            )
        if criteria.target_kind == "surface" and target_surface is None:
            raise SaikeiGradingError(
                "criteria.target_kind == 'surface' requires a target_surface"
            )

        outward_unit_per_segment = cls._compute_outward_per_segment(
            feature_line, side
        )
        sample_points, sample_outward = cls._sample_along_feature_line(
            feature_line, outward_unit_per_segment, sample_step
        )

        daylight_line: list[tuple[float, float, float]] = []
        for footprint_xyz, outward_xy in zip(sample_points, sample_outward):
            tie = cls._project_one_sample(
                footprint_xyz,
                outward_xy,
                criteria,
                target_surface,
                march_step,
                daylight_epsilon,
                max_iter,
            )
            daylight_line.append(tie)

        projection_points, projection_triangles = cls._triangulate_ribbon(
            sample_points, daylight_line
        )

        return GradingObject(
            name=name,
            footprint=feature_line,
            criteria=criteria,
            target_surface_guid=(
                target_surface.guid if target_surface is not None else None
            ),
            daylight_line=daylight_line,
            projection_points=projection_points,
            projection_triangles=projection_triangles,
        )

    # ------------------------------------------------------------------
    # Outward-direction computation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_outward_per_segment(
        feature_line: FeatureLine,
        side: Literal["left", "right", "auto"],
    ) -> list[tuple[float, float]]:
        """Return one outward-unit XY vector per segment of ``feature_line``.

        Closed loops with ``side="auto"`` use polygon orientation: CCW
        polygons get outward = right of traversal direction (the standard
        Civil 3D convention); CW polygons get outward = left.

        Open feature lines with ``side="auto"`` raise — outward is
        ambiguous without a side hint.
        """
        vertices = feature_line.vertices
        if len(vertices) < 2:
            return []

        resolved_side = side
        if side == "auto":
            if not feature_line.closed:
                raise SaikeiGradingError(
                    "open feature line requires explicit side='left' or "
                    "side='right' — outward direction is ambiguous"
                )
            xy_ring = [(float(v[0]), float(v[1])) for v in vertices]
            if xy_ring[0] != xy_ring[-1]:
                xy_ring.append(xy_ring[0])
            try:
                polygon = shapely.Polygon(xy_ring)
                is_ccw = polygon.exterior.is_ccw
            except Exception as exc:
                raise SaikeiGradingError(
                    f"could not orient closed feature line: {exc}"
                ) from exc
            resolved_side = "right" if is_ccw else "left"

        outward_per_segment: list[tuple[float, float]] = []
        segment_count = (
            len(vertices)
            if feature_line.closed
            else len(vertices) - 1
        )
        for i in range(segment_count):
            v0 = vertices[i]
            v1 = vertices[(i + 1) % len(vertices)]
            dx = float(v1[0]) - float(v0[0])
            dy = float(v1[1]) - float(v0[1])
            length = math.hypot(dx, dy)
            if length < 1e-12:
                outward_per_segment.append((0.0, 0.0))
                continue
            # Right of direction: rotate (dx, dy) by -90° → (dy, -dx).
            # Left of direction: rotate by +90° → (-dy, dx).
            if resolved_side == "right":
                ox, oy = dy / length, -dx / length
            else:
                ox, oy = -dy / length, dx / length
            outward_per_segment.append((ox, oy))
        return outward_per_segment

    @staticmethod
    def _sample_along_feature_line(
        feature_line: FeatureLine,
        outward_per_segment: list[tuple[float, float]],
        sample_step: float,
    ) -> tuple[
        list[tuple[float, float, float]],
        list[tuple[float, float]],
    ]:
        """Return ``(sample_points, sample_outward)`` for the feature line.

        Each segment contributes ``ceil(length / sample_step) + 1`` samples;
        adjacent segments share their boundary vertex (deduplicated). The
        outward direction at each sample is the segment's outward unit
        vector.
        """
        vertices = feature_line.vertices
        sample_points: list[tuple[float, float, float]] = []
        sample_outward: list[tuple[float, float]] = []
        if len(vertices) < 2:
            return sample_points, sample_outward

        segment_count = (
            len(vertices)
            if feature_line.closed
            else len(vertices) - 1
        )
        for i in range(segment_count):
            v0 = vertices[i]
            v1 = vertices[(i + 1) % len(vertices)]
            outward = outward_per_segment[i]
            dx = float(v1[0]) - float(v0[0])
            dy = float(v1[1]) - float(v0[1])
            dz = float(v1[2]) - float(v0[2])
            length = math.hypot(dx, dy)
            if length < 1e-12:
                continue
            n_steps = max(1, math.ceil(length / sample_step))
            # Include the start vertex; skip the end (shared with next segment's start)
            # except on the last segment of an open line.
            include_end = (not feature_line.closed) and (i == segment_count - 1)
            stop = n_steps + 1 if include_end else n_steps
            for k in range(stop):
                t = k / n_steps
                px = float(v0[0]) + dx * t
                py = float(v0[1]) + dy * t
                pz = float(v0[2]) + dz * t
                sample_points.append((px, py, pz))
                sample_outward.append(outward)
        return sample_points, sample_outward

    # ------------------------------------------------------------------
    # Per-sample projection — dispatcher by target_kind
    # ------------------------------------------------------------------

    @classmethod
    def _project_one_sample(
        cls,
        footprint: tuple[float, float, float],
        outward: tuple[float, float],
        criteria: GradingCriteria,
        target_surface: Optional["CivilSurface"],
        march_step: float,
        daylight_epsilon: float,
        max_iter: int,
    ) -> tuple[float, float, float]:
        """Project one sample point outward to its tie-out (daylight)
        position. Dispatches by ``criteria.target_kind``."""
        if criteria.target_kind == "surface":
            return cls._project_to_surface(
                footprint,
                outward,
                criteria,
                target_surface,  # type: ignore[arg-type]
                march_step,
                daylight_epsilon,
                max_iter,
            )
        if criteria.target_kind == "elevation":
            target_z = float(criteria.target_ref)  # type: ignore[arg-type]
            return cls._project_to_elevation(
                footprint, outward, criteria, target_z
            )
        if criteria.target_kind == "relative_elevation":
            delta_z = float(criteria.target_ref)  # type: ignore[arg-type]
            return cls._project_to_elevation(
                footprint, outward, criteria, footprint[2] + delta_z
            )
        if criteria.target_kind == "distance":
            distance = float(criteria.target_ref)  # type: ignore[arg-type]
            return cls._project_to_distance(footprint, outward, criteria, distance)
        raise SaikeiGradingError(
            f"unknown target_kind {criteria.target_kind!r}; expected one of "
            "surface, elevation, relative_elevation, distance"
        )

    @staticmethod
    def _slope_ratio_and_dz_sign(
        footprint_z: float, target_z: float, criteria: GradingCriteria
    ) -> tuple[float, float]:
        """Return ``(slope_ratio_h_per_v, dz_sign)`` for the projection.

        ``dz_sign`` is +1 (cut, slope rises outward) when target is above
        footprint, -1 (fill, slope drops outward) when target is below.
        ``slope_ratio_h_per_v`` is :attr:`GradingCriteria.cut_slope` for
        cut and :attr:`GradingCriteria.fill_slope` for fill. The sign
        decision uses ``daylight_epsilon`` would be overkill — strict
        comparison is fine here because at-grade samples are caught
        upstream by the daylight check.
        """
        if target_z > footprint_z:
            return criteria.cut_slope, +1.0
        return criteria.fill_slope, -1.0

    @classmethod
    def _project_to_surface(
        cls,
        footprint: tuple[float, float, float],
        outward: tuple[float, float],
        criteria: GradingCriteria,
        target_surface: "CivilSurface",
        march_step: float,
        daylight_epsilon: float,
        max_iter: int,
    ) -> tuple[float, float, float]:
        """Marching-loop projection to a target :class:`CivilSurface`."""
        from .surface import Surface as _SurfaceTool

        x0, y0, z0 = footprint
        ox, oy = outward
        # Initial target query at the footprint XY — early-exit if already
        # at-grade.
        z_target_initial = _SurfaceTool.z_at(target_surface, x0, y0)
        if z_target_initial is not None and abs(z_target_initial - z0) < daylight_epsilon:
            return (x0, y0, z0)

        if z_target_initial is None:
            raise SaikeiSlopeProjectionError(
                f"footprint sample ({x0:.3f}, {y0:.3f}, {z0:.3f}) lies "
                "outside the target surface's triangulation; cannot "
                "determine cut/fill direction"
            )

        slope_ratio, dz_sign = cls._slope_ratio_and_dz_sign(
            z0, z_target_initial, criteria
        )
        # Per step: horizontal march_step, vertical = march_step / slope_ratio.
        dz_per_step = (march_step / slope_ratio) * dz_sign

        x, y, z = x0, y0, z0
        prev_delta = z_target_initial - z
        iters = 0
        max_dist = criteria.max_distance
        total_horizontal = 0.0
        while iters < max_iter:
            iters += 1
            x += ox * march_step
            y += oy * march_step
            z += dz_per_step
            total_horizontal += march_step
            z_target = _SurfaceTool.z_at(target_surface, x, y)
            if z_target is None:
                # Walked off the target's triangulation — treat as the
                # surface ending; return the last in-bounds point.
                raise SaikeiSlopeProjectionError(
                    f"slope projection from ({x0:.3f}, {y0:.3f}) walked "
                    f"off the target surface after {total_horizontal:.3f}m "
                    "without daylighting"
                )

            current_delta = z_target - z
            if abs(current_delta) < daylight_epsilon:
                return (x, y, z)
            # Crossing detection: sign flip → linearly interpolate.
            if (prev_delta > 0) != (current_delta > 0):
                # Walk back by a fraction along the last march step.
                fraction = prev_delta / (prev_delta - current_delta)
                tie_x = x - ox * march_step * (1 - fraction)
                tie_y = y - oy * march_step * (1 - fraction)
                tie_z = z - dz_per_step * (1 - fraction)
                return (tie_x, tie_y, tie_z)
            prev_delta = current_delta

            if max_dist is not None and total_horizontal >= max_dist:
                if criteria.retaining_wall_at_limit:
                    # Vertical wall: collapse to current XY at z_target.
                    return (x, y, z_target)
                raise SaikeiSlopeProjectionError(
                    f"slope projection from ({x0:.3f}, {y0:.3f}) hit "
                    f"max_distance={max_dist:.3f}m before reaching the "
                    "target surface; set retaining_wall_at_limit=True or "
                    "increase max_distance"
                )

        raise SaikeiSlopeProjectionError(
            f"slope projection from ({x0:.3f}, {y0:.3f}) exceeded "
            f"max_iter={max_iter} without daylighting "
            f"(traveled {total_horizontal:.3f}m)"
        )

    @classmethod
    def _project_to_elevation(
        cls,
        footprint: tuple[float, float, float],
        outward: tuple[float, float],
        criteria: GradingCriteria,
        target_z: float,
    ) -> tuple[float, float, float]:
        """Closed-form projection to an absolute Z. Marches until the
        slope reaches ``target_z``; horizontal distance is determined by
        the slope ratio and Z delta. ``max_distance`` caps the offset
        (with optional retaining wall)."""
        x0, y0, z0 = footprint
        delta_z = target_z - z0
        if abs(delta_z) < 1e-12:
            return (x0, y0, z0)

        slope_ratio, dz_sign = cls._slope_ratio_and_dz_sign(z0, target_z, criteria)
        # |delta_z| of vertical change → |delta_z| * slope_ratio horizontal.
        horizontal_distance = abs(delta_z) * slope_ratio
        if (
            criteria.max_distance is not None
            and horizontal_distance > criteria.max_distance
        ):
            if criteria.retaining_wall_at_limit:
                # Run out at max_distance, then vertical wall to target.
                return (
                    x0 + outward[0] * criteria.max_distance,
                    y0 + outward[1] * criteria.max_distance,
                    target_z,
                )
            raise SaikeiSlopeProjectionError(
                f"projection to elevation z={target_z:.3f} from z={z0:.3f} "
                f"requires {horizontal_distance:.3f}m horizontal but "
                f"max_distance={criteria.max_distance:.3f}m caps it"
            )

        return (
            x0 + outward[0] * horizontal_distance,
            y0 + outward[1] * horizontal_distance,
            target_z,
        )

    @staticmethod
    def _project_to_distance(
        footprint: tuple[float, float, float],
        outward: tuple[float, float],
        criteria: GradingCriteria,
        horizontal_distance: float,
    ) -> tuple[float, float, float]:
        """Closed-form projection to a fixed horizontal distance.
        Z is computed from the slope ratio (the at-grade case yields no
        Z change since cut_slope/fill_slope are ratios, not absolute
        directions — for ``distance`` kind, the Z delta is determined by
        whether cut_slope or fill_slope was last applicable).

        For Phase 5 MVP the ``distance`` kind interprets a positive
        horizontal distance as "run-out at the fill slope" by default —
        users who want a cut-side projection at fixed distance pass
        their cut_slope as fill_slope (the kind doesn't carry a side
        hint since the target isn't a surface)."""
        slope_ratio = criteria.fill_slope
        # Convention: distance kind is fill-side outward run with a
        # downward slope. Negative distance reverses both X-direction and
        # Z-direction (cut-side run), but Phase 5 MVP only documents the
        # positive case.
        x = footprint[0] + outward[0] * horizontal_distance
        y = footprint[1] + outward[1] * horizontal_distance
        z = footprint[2] - horizontal_distance / slope_ratio
        return (x, y, z)

    # ------------------------------------------------------------------
    # Ribbon triangulation
    # ------------------------------------------------------------------

    @staticmethod
    def _triangulate_ribbon(
        footprint_points: list[tuple[float, float, float]],
        daylight_points: list[tuple[float, float, float]],
    ) -> tuple[np.ndarray, np.ndarray]:
        """Build the ribbon mesh between the feature line and the daylight
        line. Two triangles per consecutive sample-point pair; output is
        ``(points, triangles)`` arrays suitable for direct use in
        :class:`bonsai.tool.surface.CivilSurface`.

        Vertex layout: footprint[0..N] then daylight[0..N], so vertex
        index ``i`` is footprint[i] and ``N + i`` is daylight[i]. Each
        ribbon strip uses the quad
        ``(footprint[i], footprint[i+1], daylight[i+1], daylight[i])``
        triangulated as ``(i, i+1, N+i+1)`` and ``(i, N+i+1, N+i)``.
        """
        n = len(footprint_points)
        if n < 2 or len(daylight_points) != n:
            return (
                np.zeros((0, 3), dtype=float),
                np.zeros((0, 3), dtype=int),
            )

        all_points = footprint_points + daylight_points
        points_array = np.asarray(all_points, dtype=float)

        triangles: list[tuple[int, int, int]] = []
        for i in range(n - 1):
            triangles.append((i, i + 1, n + i + 1))
            triangles.append((i, n + i + 1, n + i))
        triangles_array = np.asarray(triangles, dtype=int)
        return points_array, triangles_array

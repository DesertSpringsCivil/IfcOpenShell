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

import bpy
import ifcopenshell.api.grading
import ifcopenshell.api.group
import ifcopenshell.api.pset_template
import ifcopenshell.api.root
import ifcopenshell.api.surface
import ifcopenshell.guid
import numpy as np
import shapely

import bonsai.tool as tool

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


class BlockedByDependentError(SaikeiGradingError):
    """Raised when an operation is refused because another entity
    depends on its target (e.g., deleting a criteria template that
    is still referenced by a grading object, or deleting a feature
    line that is still assigned to a grading group as its source FL).
    The operator layer catches this, reports it via
    ``self.report({"ERROR"}, ...)``, and returns ``{"CANCELLED"}``
    per spec §3.3.
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
            sample_points, daylight_line, closed=feature_line.closed
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
            except Exception as exc:
                raise SaikeiGradingError(
                    f"could not orient closed feature line: {exc}"
                ) from exc
            # Self-intersecting / degenerate rings produce a polygon
            # whose exterior orientation may not match the input
            # traversal — outward direction would be silently wrong.
            # Reject upfront.
            if not polygon.is_valid:
                raise SaikeiGradingError(
                    f"closed feature line ring is not topologically valid: "
                    f"{shapely.is_valid_reason(polygon)}"
                )
            is_ccw = polygon.exterior.is_ccw
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
                # Catastrophic cancellation guard: if both deltas are
                # vanishingly close in value (parallel approach with
                # IEEE 754 noise), the denominator can collapse to
                # exactly zero; treat as "already at target."
                denominator = prev_delta - current_delta
                if abs(denominator) < 1e-15:
                    return (x, y, z)
                fraction = prev_delta / denominator
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
        closed: bool = False,
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

        :param closed: when ``True``, also emits the wrap-around strip
            from sample ``N-1`` back to sample ``0``. Required for closed
            feature lines so the ribbon doesn't have a missing strip
            between the last sample and vertex 0 (sample 0 is at
            vertex 0; the last sample is at ``(n_steps-1) / n_steps``
            of the last segment, NOT at vertex 0 — closing the loop).
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
        if closed:
            # Wrap-around strip from sample N-1 back to sample 0.
            triangles.append((n - 1, 0, n))
            triangles.append((n - 1, n, 2 * n - 1))
        triangles_array = np.asarray(triangles, dtype=int)
        return points_array, triangles_array

    # ------------------------------------------------------------------
    # IFC authoring wrappers (delegate to ifcopenshell.api.grading)
    # ------------------------------------------------------------------

    @classmethod
    def author_feature_line(
        cls,
        ifc_file: "ifcopenshell.file",
        feature_line: FeatureLine,
        site: Optional["ifcopenshell.entity_instance"] = None,
    ) -> "ifcopenshell.entity_instance":
        """Persist ``feature_line`` as :class:`IfcAlignment` with an
        :class:`IfcIndexedPolyCurve` representation, via Phase 2's
        :func:`ifcopenshell.api.grading.create_feature_line`.

        Mirrors :meth:`bonsai.tool.surface.Surface.author_ifc_host`: after
        the API mints a fresh GlobalId, this wrapper rewrites it to match
        :attr:`FeatureLine.guid` so the dataclass and IFC entity carry
        the same identifier. The step id is stamped on
        :attr:`FeatureLine.ifc_alignment_id`.

        :raises SaikeiGradingError: on ``len(vertices) < 2`` or
            wrapped Phase 2 API errors.
        """
        if len(feature_line.vertices) < 2:
            raise SaikeiGradingError(
                f"feature line needs ≥ 2 vertices to author; "
                f"got {len(feature_line.vertices)}"
            )
        try:
            alignment = ifcopenshell.api.grading.create_feature_line(
                ifc_file,
                name=feature_line.name,
                vertices=feature_line.vertices,
                closed=feature_line.closed,
                grading_group_guid=feature_line.grading_group,
                site=site,
            )
        except Exception as exc:
            raise SaikeiGradingError(
                f"Phase 2 create_feature_line failed: {exc}"
            ) from exc

        alignment.GlobalId = feature_line.guid
        feature_line.ifc_alignment_id = alignment.id()
        return alignment

    @classmethod
    def update_feature_line_vertices(
        cls,
        ifc_file: "ifcopenshell.file",
        feature_line: FeatureLine,
    ) -> None:
        """In-place update of an :class:`IfcAlignment`'s polyline
        coordinates to match the (possibly mutated) dataclass vertices.

        Phase 2's ``ifcopenshell.api.grading`` has no ``update_feature_line``
        function — feature lines are authored once and treated as immutable
        on the IFC side. This helper closes the gap so Phase 5's
        :func:`bonsai.core.grading.drape_feature_line` can persist the
        post-drape Z values back to IFC without re-authoring the
        alignment (which would orphan the old IfcAlignment + leave
        downstream :class:`IfcRelAggregates` references dangling).

        Locates the alignment's :class:`IfcIndexedPolyCurve` and updates
        its underlying :class:`IfcCartesianPointList3D.CoordList` to
        match ``feature_line.vertices`` (with the closed-loop duplicate
        re-added if ``feature_line.closed``).

        :raises SaikeiGradingError: if the alignment has no polyline
            representation (created with a different rep type, or never
            authored).
        """
        if feature_line.ifc_alignment_id is None:
            raise SaikeiGradingError(
                "feature line has no IFC alignment; call author_feature_line first"
            )
        alignment = ifc_file.by_id(feature_line.ifc_alignment_id)
        polycurve = None
        representation = alignment.Representation
        if representation is not None:
            for shape_rep in representation.Representations or []:
                for item in shape_rep.Items or []:
                    if item.is_a("IfcIndexedPolyCurve"):
                        polycurve = item
                        break
                if polycurve is not None:
                    break
        if polycurve is None or polycurve.Points is None:
            raise SaikeiGradingError(
                f"IfcAlignment #{alignment.id()} has no IfcIndexedPolyCurve "
                "representation; cannot update vertices in place"
            )

        coord_list: list[tuple[float, float, float]] = [
            (float(v[0]), float(v[1]), float(v[2]))
            for v in feature_line.vertices
        ]
        # Phase 2 closed-loop convention: append the start vertex as the
        # terminating point so the polyline geometry round-trips through
        # any consumer.
        if feature_line.closed and (
            len(coord_list) >= 2 and coord_list[0] != coord_list[-1]
        ):
            coord_list.append(coord_list[0])
        polycurve.Points.CoordList = coord_list

    @classmethod
    def author_criteria_template(
        cls,
        ifc_file: "ifcopenshell.file",
        criteria: GradingCriteria,
    ) -> "ifcopenshell.entity_instance":
        """Persist (or return the existing) :class:`IfcPropertySetTemplate`
        for ``SaikeiCivil_GradingCriteria`` at project scope.

        The Phase 2 API ``create_grading_criteria_template`` is a
        singleton-by-shape — calling it repeatedly returns the same
        template entity rather than creating duplicates, so the wrapper
        is idempotent. After obtaining the template, :attr:`GradingCriteria.guid`
        is updated to match the template's ``GlobalId`` so that the dataclass
        identifier and the IFC entity identifier are always consistent (the
        same convention as :meth:`author_feature_line`).
        """
        try:
            template = ifcopenshell.api.grading.create_grading_criteria_template(
                ifc_file
            )
        except Exception as exc:
            raise SaikeiGradingError(
                f"Phase 2 create_grading_criteria_template failed: {exc}"
            ) from exc
        criteria.ifc_template_id = template.id()
        criteria.guid = template.GlobalId
        return template

    @classmethod
    def author_group(
        cls,
        ifc_file: "ifcopenshell.file",
        group: GradingGroup,
        target_surface: Optional["ifcopenshell.entity_instance"] = None,
        interior_fill_source: Optional[
            "ifcopenshell.entity_instance"
        ] = None,
        site: Optional["ifcopenshell.entity_instance"] = None,
        author: Optional[str] = None,
    ) -> "ifcopenshell.entity_instance":
        """Persist ``group`` as :class:`IfcGroup[GradingGroup]` plus the
        per-group composite :class:`IfcEarthworksFill[SUBGRADE]`, via
        Phase 2's :func:`ifcopenshell.api.grading.create_grading_group`.

        Stamps the IfcGroup's step id on :attr:`GradingGroup.ifc_group_id`,
        the composite-fill's step id on
        :attr:`GradingGroup.ifc_composite_fill_id`, and rewrites the
        group's GlobalId to match :attr:`GradingGroup.guid`.

        :returns: the :class:`IfcGroup[GradingGroup]` entity. The composite
            :class:`IfcEarthworksFill` is reachable via the named tuple
            on the API result; callers that need it directly should
            pull it via ``ifc_file.by_id(group.ifc_composite_fill_id)``.
        """
        try:
            authoring = ifcopenshell.api.grading.create_grading_group(
                ifc_file,
                name=group.name,
                target_surface=target_surface,
                interior_fill=group.interior_fill,
                interior_fill_source=interior_fill_source,
                site=site,
                author=author,
            )
        except Exception as exc:
            raise SaikeiGradingError(
                f"Phase 2 create_grading_group failed: {exc}"
            ) from exc

        authoring.group.GlobalId = group.guid
        group.ifc_group_id = authoring.group.id()
        group.ifc_composite_fill_id = authoring.composite_fill.id()
        return authoring.group

    @classmethod
    def assign_criteria(
        cls,
        ifc_file: "ifcopenshell.file",
        group: GradingGroup,
        criteria: GradingCriteria,
        target_reference: Optional[str] = None,
    ) -> "ifcopenshell.entity_instance":
        """Bind ``criteria`` to ``group`` via the Phase 2
        :func:`ifcopenshell.api.grading.assign_grading_criteria`. The
        criteria template is auto-authored if not already present in the
        file (singleton-by-shape).

        Re-assigning the same criteria to the same group updates the
        existing pset's values in place rather than duplicating — the
        Phase 2 API guarantees idempotence.

        :param target_reference: GUID-or-numeric override for
            ``SaikeiCivil_GradingCriteria.TargetReference``. Defaults to
            ``str(criteria.target_ref)`` since the underlying API stores
            it as a string regardless of ``target_kind``.
        """
        if group.ifc_group_id is None:
            raise SaikeiGradingError(
                "group has no IFC entity; call author_group first"
            )
        if criteria.ifc_template_id is None:
            cls.author_criteria_template(ifc_file, criteria)
        ifc_group = ifc_file.by_id(group.ifc_group_id)
        ifc_template = ifc_file.by_id(criteria.ifc_template_id)  # type: ignore[arg-type]
        try:
            pset = ifcopenshell.api.grading.assign_grading_criteria(
                ifc_file,
                ifc_group,
                ifc_template,
                target_kind=criteria.target_kind,
                cut_slope=criteria.cut_slope,
                fill_slope=criteria.fill_slope,
                target_reference=(
                    target_reference
                    if target_reference is not None
                    else str(criteria.target_ref)
                ),
                max_distance=criteria.max_distance,
                retaining_wall_at_limit=criteria.retaining_wall_at_limit,
                name=criteria.name or None,
            )
        except Exception as exc:
            raise SaikeiGradingError(
                f"Phase 2 assign_grading_criteria failed: {exc}"
            ) from exc
        return pset

    @classmethod
    def author_slope_fill(
        cls,
        ifc_file: "ifcopenshell.file",
        group: GradingGroup,
        grading_object: GradingObject,
    ) -> "ifcopenshell.entity_instance":
        """Persist ``grading_object`` as
        :class:`IfcEarthworksFill[SLOPEFILL]` under ``group``, via Phase 2's
        :func:`ifcopenshell.api.grading.add_slope_fill_to_group`.

        Stamps the slope-fill step id on
        :attr:`GradingObject.ifc_slope_fill_id` and rewrites the
        slope-fill's GlobalId to match :attr:`GradingObject.guid`.
        """
        if group.ifc_group_id is None or group.ifc_composite_fill_id is None:
            raise SaikeiGradingError(
                "group has no IFC entities; call author_group first"
            )
        if grading_object.projection_points.shape[0] == 0:
            raise SaikeiGradingError(
                "grading object has empty projection_points; nothing to author"
            )

        ifc_group = ifc_file.by_id(group.ifc_group_id)
        ifc_composite = ifc_file.by_id(group.ifc_composite_fill_id)
        feature_line_entity = None
        if (
            grading_object.footprint is not None
            and grading_object.footprint.ifc_alignment_id is not None
        ):
            feature_line_entity = ifc_file.by_id(
                grading_object.footprint.ifc_alignment_id
            )

        try:
            slope_fill = ifcopenshell.api.grading.add_slope_fill_to_group(
                ifc_file,
                ifc_group,
                ifc_composite,
                name=grading_object.name,
                points=grading_object.projection_points,
                triangles=grading_object.projection_triangles,
                feature_line=feature_line_entity,
            )
        except Exception as exc:
            raise SaikeiGradingError(
                f"Phase 2 add_slope_fill_to_group failed: {exc}"
            ) from exc

        slope_fill.GlobalId = grading_object.guid
        grading_object.ifc_slope_fill_id = slope_fill.id()
        return slope_fill

    @classmethod
    def author_interior_fill(
        cls,
        ifc_file: "ifcopenshell.file",
        group: GradingGroup,
        points: np.ndarray,
        triangles: np.ndarray,
        name: Optional[str] = None,
    ) -> "ifcopenshell.entity_instance":
        """Persist the per-group interior fill as
        :class:`IfcEarthworksFill[SUBGRADE]` via Phase 2's
        :func:`ifcopenshell.api.grading.add_interior_fill_to_group`.
        One per group — the Phase 2 API enforces this constraint.

        Stamps the interior-fill step id on
        :attr:`GradingGroup.ifc_interior_fill_id`. The interior fill
        doesn't have its own dataclass GUID; the IFC entity's
        API-minted GUID is preserved.
        """
        if group.ifc_group_id is None or group.ifc_composite_fill_id is None:
            raise SaikeiGradingError(
                "group has no IFC entities; call author_group first"
            )
        if group.interior_fill == "none":
            raise SaikeiGradingError(
                "group.interior_fill is 'none'; no interior fill to author"
            )
        if points.shape[0] == 0 or triangles.shape[0] == 0:
            raise SaikeiGradingError(
                "interior fill has empty points / triangles; nothing to author"
            )

        ifc_group = ifc_file.by_id(group.ifc_group_id)
        ifc_composite = ifc_file.by_id(group.ifc_composite_fill_id)
        try:
            interior = ifcopenshell.api.grading.add_interior_fill_to_group(
                ifc_file,
                ifc_group,
                ifc_composite,
                name=name or f"{group.name} interior",
                points=points,
                triangles=triangles,
            )
        except Exception as exc:
            raise SaikeiGradingError(
                f"Phase 2 add_interior_fill_to_group failed: {exc}"
            ) from exc

        group.ifc_interior_fill_id = interior.id()
        return interior

    # ------------------------------------------------------------------
    # Registry — lazy-rehydrating cache (spec §4.6)
    # ------------------------------------------------------------------

    _registry: dict[tuple[int, str], object] = {}
    """Per spec §4.6: lazy-rehydrating cache keyed by ``(id(ifc_file),
    guid)``. Stores :class:`FeatureLine`, :class:`GradingCriteria`,
    :class:`GradingGroup`, and :class:`GradingObject` instances; the
    dataclass type is preserved by the value itself. Headless tests
    call :meth:`clear` in autouse teardown."""

    @classmethod
    def register(
        cls,
        ifc_file: "ifcopenshell.file",
        entity: Union[FeatureLine, GradingCriteria, GradingGroup, GradingObject],
    ) -> None:
        """Add ``entity`` to the registry under
        ``(id(ifc_file), entity.guid)``. Called by core orchestration
        after the relevant ``author_*`` so the in-memory dataclass is
        reused on subsequent ``get_*`` calls.

        :class:`GradingObject` registration is what backs the GPU
        decorator's ``draw_daylight_lines_3d`` — without it, daylight
        lines computed by ``compute_grading_object`` are lost as soon
        as the orchestrator returns."""
        cls._registry[(id(ifc_file), entity.guid)] = entity

    @classmethod
    def get_grading_object(
        cls, ifc_file: "ifcopenshell.file", guid: str
    ) -> GradingObject:
        """Return the registered :class:`GradingObject` for ``guid``.

        Unlike :meth:`get_feature_line` / :meth:`get_group` there is no
        rehydration path: a :class:`GradingObject`'s
        :attr:`~GradingObject.daylight_line` and
        :attr:`~GradingObject.projection_triangles` are *computed
        outputs* of :meth:`compute_grading_object`, not authoring
        inputs. IFC persists the resulting ribbon geometry
        (:class:`IfcEarthworksFill[SLOPEFILL]`) but not the sample-point
        correspondence needed to reconstruct the daylight polyline, so a
        cache miss means "recompute", not "read back".

        :raises SaikeiGradingError: if no grading object is registered
            under ``guid`` for this file, or the registered entity is of
            another type.
        """
        entity = cls._registry.get((id(ifc_file), guid))
        if entity is None:
            raise SaikeiGradingError(
                f"no GradingObject registered with GUID {guid!r}; "
                "grading objects are computed outputs — run "
                "add_grading_object (or rebuild the group) first"
            )
        if not isinstance(entity, GradingObject):
            raise SaikeiGradingError(
                f"GUID {guid!r} is registered as "
                f"{type(entity).__name__}, not GradingObject"
            )
        return entity

    @classmethod
    def invalidate(
        cls, ifc_file: "ifcopenshell.file", guid: str
    ) -> None:
        """Drop the cache entry for ``guid`` so the next ``get_*`` call
        rehydrates from IFC."""
        cls._registry.pop((id(ifc_file), guid), None)

    @classmethod
    def clear(cls) -> None:
        """Wipe the entire registry. Headless test teardown calls this to
        prevent cross-test contamination."""
        cls._registry.clear()

    @staticmethod
    def is_feature_line_alignment(alignment) -> bool:
        """Return True if ``alignment`` is a Saikei feature line
        (carries ``SaikeiCivil_FeatureLineCommon``), False if it's an
        ordinary IfcAlignment (e.g., a roadway centerline).

        Public predicate so UI-layer code (data cache, GPU decorator)
        doesn't have to duplicate the pset-name string.
        """
        for rel in getattr(alignment, "IsDefinedBy", None) or []:
            if not rel.is_a("IfcRelDefinesByProperties"):
                continue
            pset = rel.RelatingPropertyDefinition
            if pset is not None and pset.Name == "SaikeiCivil_FeatureLineCommon":
                return True
        return False

    @classmethod
    def iter_registered(
        cls,
        ifc_file: "ifcopenshell.file",
        entity_type: type,
    ):
        """Yield every registered entity matching ``entity_type`` for
        ``ifc_file``.

        Public iterator over :attr:`_registry` so UI-layer consumers
        (the GPU decorator, the data-cache UIList sync) don't have to
        reach into the registry's private ``(id(ifc_file), guid)`` key
        shape. Pass one of :class:`FeatureLine`, :class:`GradingCriteria`,
        :class:`GradingGroup`, :class:`GradingObject` as ``entity_type``.
        """
        ifc_key = id(ifc_file)
        for (file_key, _guid), entry in cls._registry.items():
            if file_key == ifc_key and isinstance(entry, entity_type):
                yield entry

    @classmethod
    def get_feature_line(
        cls, ifc_file: "ifcopenshell.file", guid: str
    ) -> FeatureLine:
        """Return the cached :class:`FeatureLine` for ``guid``,
        rehydrating from IFC on cache miss."""
        key = (id(ifc_file), guid)
        cached = cls._registry.get(key)
        if isinstance(cached, FeatureLine):
            return cached
        feature_line = cls._rehydrate_feature_line_from_ifc(ifc_file, guid)
        cls._registry[key] = feature_line
        return feature_line

    @classmethod
    def get_group(
        cls, ifc_file: "ifcopenshell.file", guid: str
    ) -> GradingGroup:
        """Return the cached :class:`GradingGroup` for ``guid``,
        rehydrating from IFC on cache miss.

        Phase 5 MVP rehydrates the group's metadata
        (name, interior_fill, target_surface_guid) and the IFC step ids
        but leaves ``members`` empty — member rehydration walks the
        :class:`IfcRelAggregates` graph (commit 6 territory). Callers
        that need member access should call :meth:`rebuild_group_members`
        after :meth:`get_group`."""
        key = (id(ifc_file), guid)
        cached = cls._registry.get(key)
        if isinstance(cached, GradingGroup):
            return cached
        group = cls._rehydrate_group_from_ifc(ifc_file, guid)
        cls._registry[key] = group
        return group

    @classmethod
    def _rehydrate_feature_line_from_ifc(
        cls, ifc_file: "ifcopenshell.file", guid: str
    ) -> FeatureLine:
        """Reconstruct a :class:`FeatureLine` from the IFC
        :class:`IfcAlignment` identified by ``guid``.

        Reads the polyline geometry from the alignment's representation
        and the ``SaikeiCivil_FeatureLineCommon`` for ``closed`` and
        ``GradingGroupGuid`` (per Phase 2's ``create_feature_line``).
        """
        alignment = next(
            (
                e
                for e in ifc_file.by_type("IfcAlignment")
                if e.GlobalId == guid
            ),
            None,
        )
        if alignment is None:
            raise SaikeiGradingError(
                f"no IfcAlignment with GlobalId {guid!r} in this file"
            )

        vertices = cls._extract_alignment_polyline(alignment)
        closed, grading_group_guid = cls._extract_feature_line_pset(alignment)

        # Phase 2 stores closed loops with the start vertex appended as
        # the terminating point so the polyline geometry round-trips
        # through any consumer. Strip that duplication on read so
        # ``vertices`` matches the original authoring input.
        if (
            closed
            and len(vertices) >= 2
            and vertices[0] == vertices[-1]
        ):
            vertices = vertices[:-1]

        return FeatureLine(
            guid=guid,
            name=alignment.Name or "",
            vertices=vertices,
            closed=closed,
            grading_group=grading_group_guid,
            ifc_alignment_id=alignment.id(),
        )

    @classmethod
    def _rehydrate_group_from_ifc(
        cls, ifc_file: "ifcopenshell.file", guid: str
    ) -> GradingGroup:
        """Reconstruct a :class:`GradingGroup` from the
        :class:`IfcGroup[GradingGroup]` identified by ``guid``.

        Reads ``SaikeiCivil_GradingSource`` for ``InteriorFillStrategy``
        and ``TargetSurfaceGuid``. Locates the per-group composite
        :class:`IfcEarthworksFill[SUBGRADE]` via the group's
        :class:`IfcRelAssignsToGroup` membership.

        Member :class:`GradingObject` rehydration is deferred — see
        :meth:`get_group` docstring.
        """
        ifc_group = next(
            (
                g
                for g in ifc_file.by_type("IfcGroup")
                if g.GlobalId == guid
                and getattr(g, "ObjectType", None) == "GradingGroup"
            ),
            None,
        )
        if ifc_group is None:
            raise SaikeiGradingError(
                f"no IfcGroup[GradingGroup] with GlobalId {guid!r} in this file"
            )

        interior_fill, target_surface_guid = cls._extract_grading_source_pset(
            ifc_group
        )
        composite_fill_id = cls._find_composite_fill_id(ifc_group)

        return GradingGroup(
            guid=guid,
            name=ifc_group.Name or "",
            interior_fill=interior_fill,  # type: ignore[arg-type]
            target_surface_guid=target_surface_guid,
            ifc_group_id=ifc_group.id(),
            ifc_composite_fill_id=composite_fill_id,
        )

    @staticmethod
    def _extract_alignment_polyline(
        alignment: "ifcopenshell.entity_instance",
    ) -> list[tuple[float, float, float]]:
        """Pull the 3D polyline points from an :class:`IfcAlignment`'s
        :class:`IfcIndexedPolyCurve` representation. Returns an empty
        list if the alignment has no polyline representation."""
        representation = alignment.Representation
        if representation is None:
            return []
        for shape_rep in representation.Representations or []:
            for item in shape_rep.Items or []:
                if item.is_a("IfcIndexedPolyCurve"):
                    points_entity = item.Points
                    if points_entity is None:
                        continue
                    coords = points_entity.CoordList or []
                    return [
                        (float(c[0]), float(c[1]), float(c[2]) if len(c) >= 3 else 0.0)
                        for c in coords
                    ]
                if item.is_a("IfcPolyline"):
                    pts = item.Points or []
                    out: list[tuple[float, float, float]] = []
                    for pt in pts:
                        coords = pt.Coordinates or ()
                        if len(coords) >= 3:
                            out.append(
                                (float(coords[0]), float(coords[1]), float(coords[2]))
                            )
                    return out
        return []

    @staticmethod
    def _extract_feature_line_pset(
        alignment: "ifcopenshell.entity_instance",
    ) -> tuple[bool, Optional[str]]:
        """Pull ``IsClosed`` and ``GradingGroupGuid`` from
        ``SaikeiCivil_FeatureLineCommon`` (per Phase 2's
        :func:`create_feature_line`). Defaults: not closed, no group."""
        closed = False
        grading_group_guid = None
        for rel in getattr(alignment, "IsDefinedBy", None) or []:
            if not rel.is_a("IfcRelDefinesByProperties"):
                continue
            pset = rel.RelatingPropertyDefinition
            if pset is None or pset.Name != "SaikeiCivil_FeatureLineCommon":
                continue
            for prop in pset.HasProperties or []:
                if prop.Name == "IsClosed" and prop.NominalValue is not None:
                    closed = bool(prop.NominalValue.wrappedValue)
                elif (
                    prop.Name == "GradingGroupGuid"
                    and prop.NominalValue is not None
                ):
                    val = prop.NominalValue.wrappedValue
                    grading_group_guid = val if val else None
        return closed, grading_group_guid

    @staticmethod
    def _extract_grading_source_pset(
        ifc_group: "ifcopenshell.entity_instance",
    ) -> tuple[str, Optional[str]]:
        """Pull ``InteriorFillStrategy`` and ``TargetSurfaceGuid`` from
        ``SaikeiCivil_GradingSource``. Defaults:
        ``"interpolate_from_boundary"``, no target."""
        interior_fill = "interpolate_from_boundary"
        target_surface_guid = None
        for rel in getattr(ifc_group, "IsDefinedBy", None) or []:
            if not rel.is_a("IfcRelDefinesByProperties"):
                continue
            pset = rel.RelatingPropertyDefinition
            if pset is None or pset.Name != "SaikeiCivil_GradingSource":
                continue
            for prop in pset.HasProperties or []:
                if (
                    prop.Name == "InteriorFillStrategy"
                    and prop.NominalValue is not None
                ):
                    interior_fill = prop.NominalValue.wrappedValue or interior_fill
                elif (
                    prop.Name == "TargetSurfaceGuid"
                    and prop.NominalValue is not None
                ):
                    val = prop.NominalValue.wrappedValue
                    target_surface_guid = val if val else None
        return interior_fill, target_surface_guid

    @staticmethod
    def _find_composite_fill_id(
        ifc_group: "ifcopenshell.entity_instance",
    ) -> Optional[int]:
        """Walk the group's :class:`IfcRelAssignsToGroup` inverse for the
        per-group composite :class:`IfcEarthworksFill[SUBGRADE]`. The
        composite is the first assigned fill (it's added at create time
        before any slope fills)."""
        for rel in getattr(ifc_group, "IsGroupedBy", None) or []:
            for related in rel.RelatedObjects or []:
                if (
                    related.is_a("IfcEarthworksFill")
                    and getattr(related, "PredefinedType", None) == "SUBGRADE"
                ):
                    return related.id()
        return None

    # ------------------------------------------------------------------
    # Blender object linkage
    # ------------------------------------------------------------------

    @classmethod
    def create_blender_curve(
        cls,
        ifc_file: "ifcopenshell.file",
        feature_line: FeatureLine,
    ) -> bpy.types.Object:
        """Create a Blender Bezier-curve object representing
        ``feature_line`` and link it to the IFC :class:`IfcAlignment`.

        Mirrors :meth:`bonsai.tool.surface.Surface.create_blender_mesh`
        (which produces meshes for surfaces). For feature lines a curve
        is the right primitive: low overhead, supports per-vertex
        elevation editing via Blender's existing curve-edit operators.
        Idempotent — re-entrant calls return the existing object.
        """
        if feature_line.ifc_alignment_id is None:
            raise SaikeiGradingError(
                "feature line has no IFC alignment; call author_feature_line first"
            )
        alignment = ifc_file.by_id(feature_line.ifc_alignment_id)
        existing_obj = tool.Ifc.get_object(alignment)
        if existing_obj:
            return existing_obj

        display_name = f"IfcAlignment/{alignment.Name or feature_line.guid}"
        curve_data = bpy.data.curves.new(display_name, "CURVE")
        curve_data.dimensions = "3D"
        spline = curve_data.splines.new("POLY")
        if feature_line.vertices:
            spline.points.add(len(feature_line.vertices) - 1)
            for i, (x, y, z) in enumerate(feature_line.vertices):
                spline.points[i].co = (float(x), float(y), float(z), 1.0)
            spline.use_cyclic_u = bool(feature_line.closed)

        obj = bpy.data.objects.new(display_name, curve_data)
        tool.Ifc.link(alignment, obj)
        tool.Collector.assign(obj)
        return obj

    @classmethod
    def update_blender_curve(
        cls,
        ifc_file: "ifcopenshell.file",
        feature_line: FeatureLine,
    ) -> bool:
        """Refresh the linked Blender curve's spline points to match
        ``feature_line.vertices``.

        Companion to :meth:`create_blender_curve`. Used by drape /
        edit-elevations flows: after the IFC alignment's polyline is
        rewritten via :meth:`update_feature_line_vertices`, the linked
        Blender curve still shows stale Z values until the in-memory
        spline is rewritten too.

        :returns: True if a curve object was found and updated, False
            if the feature line has no linked Blender object yet (the
            caller created the IFC entity but hasn't called
            :meth:`create_blender_curve` — silent no-op rather than an
            error so headless flows that don't need the viewport
            update continue working).
        """
        if feature_line.ifc_alignment_id is None:
            raise SaikeiGradingError(
                "feature line has no IFC alignment; "
                "call author_feature_line first"
            )
        alignment = ifc_file.by_id(feature_line.ifc_alignment_id)
        obj = tool.Ifc.get_object(alignment)
        if obj is None or obj.data is None or not obj.data.splines:
            return False
        spline = obj.data.splines[0]
        for i, (x, y, z) in enumerate(feature_line.vertices):
            if i < len(spline.points):
                spline.points[i].co = (float(x), float(y), float(z), 1.0)
        return True

    @classmethod
    def create_blender_empty_for_group(
        cls,
        ifc_file: "ifcopenshell.file",
        group: GradingGroup,
    ) -> bpy.types.Object:
        """Create a Blender Empty object representing the
        :class:`IfcGroup[GradingGroup]`. The Empty is a parent for the
        group's feature-line / slope-fill child objects so the user can
        select the whole grading assembly via outliner / scene-graph
        interaction.

        Mirrors :meth:`Surface.create_blender_mesh` for the
        non-geometric IFC entity case: groups don't have a TIN of their
        own (the composite proposed surface comes from the rebuild step
        in commit 6).
        """
        if group.ifc_group_id is None:
            raise SaikeiGradingError(
                "group has no IFC entity; call author_group first"
            )
        ifc_group = ifc_file.by_id(group.ifc_group_id)
        existing_obj = tool.Ifc.get_object(ifc_group)
        if existing_obj:
            return existing_obj

        display_name = f"IfcGroup/{ifc_group.Name or group.guid}"
        obj = bpy.data.objects.new(display_name, None)  # None = Empty
        obj.empty_display_type = "PLAIN_AXES"
        obj.empty_display_size = 1.0

        tool.Ifc.link(ifc_group, obj)
        tool.Collector.assign(obj)
        return obj

    # ------------------------------------------------------------------
    # Group composite surface (spec §6.3)
    # ------------------------------------------------------------------

    @classmethod
    def rebuild_group_surface(
        cls,
        ifc_file: "ifcopenshell.file",
        group: GradingGroup,
    ) -> "CivilSurface":
        """Compose all of ``group``'s grading objects (and the interior
        fill, when ``group.interior_fill != "none"``) into a single
        ``proposed_group`` :class:`bonsai.tool.surface.CivilSurface`.

        Per spec §6.3 the composite is built from:

        1. All feature-line vertices at their authored elevations.
        2. All daylight-line vertices at their computed elevations.
        3. All projection-ribbon triangles (one set per grading object).
        4. Interior-fill triangles per the ``interior_fill`` strategy
           (commit 7 of Phase 5 — currently only ``"none"`` is honored).

        The composite surface is authored to IFC as a host
        :class:`IfcEarthworksFill[SUBGRADE]` (the per-group composite
        already created by :meth:`author_group`) with a fresh
        Body TIN representation. Its ``ifc_host_entity_id``
        points at the existing composite fill — we don't author a
        second one.

        :returns: the assembled :class:`CivilSurface` with
            ``kind="proposed_group"`` and IFC step ids stamped. The
            surface's GUID matches the composite fill's IFC GlobalId
            so :meth:`bonsai.tool.surface.Surface.get` resolves it
            correctly.

            The caller must register the result in
            :attr:`bonsai.tool.surface.Surface._registry` via
            :meth:`bonsai.tool.surface.Surface.register` if subsequent
            in-session ``Surface.get`` calls should return the
            in-memory dataclass rather than triggering a
            ``_rehydrate_from_ifc`` round-trip. Core orchestration
            (commit 9) handles this; direct callers of the tool layer
            must do it explicitly.
        :raises SaikeiGradingError: when the group has no IFC entities
            (call :meth:`author_group` first), has no members to
            compose, requires a multi-member interior fill (Phase 5.1
            deferral), or hits any other documented input-validation
            check.
        """
        from .surface import (
            CivilSurface,
            Surface as _SurfaceTool,
            _ScipyShapelyTriangulator,
        )

        if group.ifc_group_id is None or group.ifc_composite_fill_id is None:
            raise SaikeiGradingError(
                "group has no IFC entities; call author_group first"
            )
        if not group.members:
            raise SaikeiGradingError(
                "group has no members; call author_slope_fill on at least "
                "one grading object before rebuilding"
            )
        merged_points, merged_triangles = cls._merge_member_geometry(
            group.members
        )
        if merged_triangles.shape[0] == 0 and group.interior_fill == "none":
            raise SaikeiGradingError(
                "merged group geometry is empty; nothing to compose"
            )

        # Interior fill: compute geometry per the chosen strategy and
        # append to the merged slope-fill geometry. The interior fill is
        # also authored separately as IfcEarthworksFill[SUBGRADE] under
        # the group via Phase 2's add_interior_fill_to_group.
        if group.interior_fill != "none":
            interior_points, interior_triangles = cls._compute_interior_fill(
                ifc_file, group
            )
            if interior_triangles.shape[0] > 0:
                cls.author_interior_fill(
                    ifc_file, group, interior_points, interior_triangles
                )
                # Concatenate with offset for the composite TIN.
                offset = merged_points.shape[0]
                merged_points = np.concatenate(
                    [merged_points, interior_points], axis=0
                ) if merged_points.shape[0] else interior_points
                if merged_triangles.shape[0]:
                    merged_triangles = np.concatenate(
                        [merged_triangles, interior_triangles + offset], axis=0
                    )
                else:
                    merged_triangles = interior_triangles

        # Build the proposed_group CivilSurface. Use the un-constrained
        # default backend to populate triangle_flags as zeros — the
        # cross-surface composition flag computation (Flag=-1 Hole for
        # fall-through to existing ground per spec §6.3 last paragraph)
        # is queued for Phase 6 alongside the volume math that consumes
        # the flags.
        #
        # CRITICAL: composite_surface.guid MUST match the actual IFC
        # composite fill's GlobalId — not a fresh ifcopenshell.guid.new().
        # Phase 6 retrieves the composite via tool.Surface.get(file,
        # group.output_surface_guid); a fresh GUID here would orphan the
        # dataclass from the IFC entity it represents.
        composite_fill_entity = ifc_file.by_id(group.ifc_composite_fill_id)
        triangle_flags = np.zeros(len(merged_triangles), dtype=int)
        outer_boundary = shapely.MultiPoint(
            [(float(p[0]), float(p[1])) for p in merged_points]
        ).convex_hull
        composite_surface = CivilSurface(
            guid=composite_fill_entity.GlobalId,
            name=f"{group.name} composite",
            kind="proposed_group",
            points=merged_points,
            triangles=merged_triangles,
            triangle_flags=triangle_flags,
            outer_boundary=(
                outer_boundary
                if isinstance(outer_boundary, shapely.Polygon)
                else None
            ),
            ifc_host_entity_id=group.ifc_composite_fill_id,
        )
        # The composite fill was created by author_group as a bare
        # shell (no Body representation yet). On first rebuild
        # we add a fresh TIN; on subsequent rebuilds we update the
        # existing one. Same for the BoundingBox rep.
        cls._add_or_update_composite_tin(ifc_file, composite_surface)
        # Cache the GUID on the group for downstream lookup; the surface
        # itself is registered in tool.Surface._registry by core
        # orchestration (commit 9 territory).
        group.output_surface_guid = composite_surface.guid
        return composite_surface

    # ------------------------------------------------------------------
    # Interior-fill strategies (spec §6.3)
    # ------------------------------------------------------------------

    @classmethod
    def _compute_interior_fill(
        cls,
        ifc_file: "ifcopenshell.file",
        group: GradingGroup,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Dispatch by ``group.interior_fill`` to one of the three
        non-trivial strategies. Phase 5 MVP supports only single-member
        groups (one closed feature line per group) — multi-member /
        disconnected-ring groups are deferred to Phase 5.1.

        :returns: ``(points, triangles)`` for the interior. Both empty
            arrays when ``group.interior_fill == "none"`` (caller filters).
        """
        empty = (
            np.zeros((0, 3), dtype=float),
            np.zeros((0, 3), dtype=int),
        )
        if group.interior_fill == "none":
            return empty
        if len(group.members) != 1:
            # SaikeiGradingError (not NotImplementedError) so the
            # operator/headless contract catches it consistently with
            # other validation failures and converts to
            # report({"ERROR"}, ...) + CANCELLED.
            raise SaikeiGradingError(
                "Phase 5 MVP supports interior fill on single-member "
                f"groups only; got {len(group.members)} members. "
                "Multi-ring composition is deferred to Phase 5.1."
            )
        member = group.members[0]
        if member.footprint is None or not member.footprint.closed:
            raise SaikeiGradingError(
                f"interior_fill={group.interior_fill!r} requires the group's "
                "feature line to be a closed loop; got open or missing"
            )
        if len(member.footprint.vertices) < 3:
            raise SaikeiGradingError(
                "interior fill requires a feature line with ≥ 3 vertices; "
                f"got {len(member.footprint.vertices)}"
            )

        if group.interior_fill == "flat":
            return cls._interior_fill_flat(member.footprint)
        if group.interior_fill == "interpolate_from_boundary":
            return cls._interior_fill_interpolate_from_boundary(member.footprint)
        if group.interior_fill == "from_surface":
            if group.interior_fill_source_guid is None:
                raise SaikeiGradingError(
                    "interior_fill='from_surface' requires "
                    "group.interior_fill_source_guid to be set"
                )
            from .surface import Surface as _SurfaceTool

            source_surface = _SurfaceTool.get(
                ifc_file, group.interior_fill_source_guid
            )
            return cls._interior_fill_from_surface(
                member.footprint, source_surface
            )
        raise SaikeiGradingError(
            f"unknown interior_fill strategy {group.interior_fill!r}"
        )

    @staticmethod
    def _interior_fill_flat(
        feature_line: FeatureLine,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Triangulate the feature-line ring at the average vertex Z.

        Used when the engineer wants a flat pad bottom. The triangulation
        reuses :class:`bonsai.tool.surface._ScipyShapelyTriangulator` —
        same constrained-Delaunay backend, same Steiner-point caveats."""
        from .surface import _ScipyShapelyTriangulator

        avg_z = sum(float(v[2]) for v in feature_line.vertices) / len(
            feature_line.vertices
        )
        points = np.asarray(
            [(float(v[0]), float(v[1]), avg_z) for v in feature_line.vertices],
            dtype=float,
        )
        ring_polygon = shapely.Polygon(
            [(float(v[0]), float(v[1])) for v in feature_line.vertices]
        )
        triangulator = _ScipyShapelyTriangulator()
        triangles, _flags = triangulator.constrained(
            points, [], ring_polygon, [], []
        )
        return points, triangles

    @staticmethod
    def _interior_fill_interpolate_from_boundary(
        feature_line: FeatureLine,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Delaunay-triangulate the feature-line ring using only the
        boundary vertices' Z values — interior triangles inherit Z by
        the triangulation's barycentric implicit interpolation. The
        most common Civil 3D default."""
        from .surface import _ScipyShapelyTriangulator

        points = np.asarray(
            [(float(v[0]), float(v[1]), float(v[2])) for v in feature_line.vertices],
            dtype=float,
        )
        ring_polygon = shapely.Polygon(
            [(float(v[0]), float(v[1])) for v in feature_line.vertices]
        )
        triangulator = _ScipyShapelyTriangulator()
        triangles, _flags = triangulator.constrained(
            points, [], ring_polygon, [], []
        )
        return points, triangles

    @staticmethod
    def _interior_fill_from_surface(
        feature_line: FeatureLine,
        source_surface: "CivilSurface",
    ) -> tuple[np.ndarray, np.ndarray]:
        """Use ``source_surface`` to drape the feature-line ring's vertices
        (replace each vertex's Z with ``source_surface.z_at(x, y)``),
        then triangulate the ring. Useful for pit-bottom or
        pre-designed pad-bottom cases.

        :raises SaikeiGradingError: if any feature-line vertex falls
            outside the source surface's triangulation.
        """
        from .surface import Surface as _SurfaceTool, _ScipyShapelyTriangulator

        draped: list[tuple[float, float, float]] = []
        for vertex in feature_line.vertices:
            x, y = float(vertex[0]), float(vertex[1])
            z = _SurfaceTool.z_at(source_surface, x, y)
            if z is None:
                raise SaikeiGradingError(
                    f"feature-line vertex ({x:.3f}, {y:.3f}) falls outside "
                    "the interior_fill source surface; cannot drape"
                )
            draped.append((x, y, z))

        points = np.asarray(draped, dtype=float)
        ring_polygon = shapely.Polygon(
            [(float(v[0]), float(v[1])) for v in feature_line.vertices]
        )
        triangulator = _ScipyShapelyTriangulator()
        triangles, _flags = triangulator.constrained(
            points, [], ring_polygon, [], []
        )
        return points, triangles

    @staticmethod
    def _add_or_update_composite_tin(
        ifc_file: "ifcopenshell.file",
        composite_surface: "CivilSurface",
    ) -> None:
        """Author or refresh the composite fill's Body +
        BoundingBox representations.

        On first rebuild the composite has no Body rep —
        :func:`ifcopenshell.api.surface.add_tin_representation` and
        :func:`add_bounding_box_representation` author them. On
        subsequent rebuilds :meth:`bonsai.tool.surface.Surface.update_ifc_tin`
        swaps the existing TIN in place (and refreshes the BoundingBox).
        """
        from .surface import Surface as _SurfaceTool

        host = ifc_file.by_id(composite_surface.ifc_host_entity_id)
        existing_tin_id = _SurfaceTool._find_tin_id(host)
        if existing_tin_id is not None:
            _SurfaceTool.update_ifc_tin(ifc_file, composite_surface)
            return

        # First-rebuild path: add fresh TIN + bbox.
        point_list = [
            (float(p[0]), float(p[1]), float(p[2]))
            for p in composite_surface.points
        ]
        new_tin = ifcopenshell.api.surface.add_tin_representation(
            ifc_file,
            host,
            point_list,
            composite_surface.triangles,
            triangle_flags=composite_surface.triangle_flags,
        )
        composite_surface.ifc_tin_representation_id = new_tin.id()

        # BoundingBox representation. Phase 1's helper checks for an
        # existing Box rep and raises if found; for a freshly-rebuilt
        # composite there is none yet.
        xs = [p[0] for p in point_list]
        ys = [p[1] for p in point_list]
        zs = [p[2] for p in point_list]
        epsilon = 1e-6
        min_xyz = (min(xs), min(ys), min(zs))
        max_xyz = (
            max(xs) if max(xs) > min(xs) else min(xs) + epsilon,
            max(ys) if max(ys) > min(ys) else min(ys) + epsilon,
            max(zs) if max(zs) > min(zs) else min(zs) + epsilon,
        )
        bbox = ifcopenshell.api.surface.add_bounding_box_representation(
            ifc_file, host, min_xyz=min_xyz, max_xyz=max_xyz
        )
        composite_surface.ifc_bbox_representation_id = bbox.id()

    @staticmethod
    def _merge_member_geometry(
        members: list[GradingObject],
    ) -> tuple[np.ndarray, np.ndarray]:
        """Concatenate the projection geometry of every member into a
        single ``(points, triangles)`` pair, with triangle indices
        offset to the merged points array.

        Each member contributes its full ``projection_points`` /
        ``projection_triangles`` pair; index 0 of member k's triangle
        array becomes ``offset_k`` in the merged array, where
        ``offset_k = sum(member_j.projection_points.shape[0] for j < k)``.
        """
        merged_points_list: list[np.ndarray] = []
        merged_triangles_list: list[np.ndarray] = []
        offset = 0
        for member in members:
            if (
                member.projection_points.shape[0] == 0
                or member.projection_triangles.shape[0] == 0
            ):
                continue
            merged_points_list.append(member.projection_points)
            merged_triangles_list.append(member.projection_triangles + offset)
            offset += member.projection_points.shape[0]

        if not merged_points_list:
            return (
                np.zeros((0, 3), dtype=float),
                np.zeros((0, 3), dtype=int),
            )
        merged_points = np.concatenate(merged_points_list, axis=0)
        merged_triangles = np.concatenate(merged_triangles_list, axis=0)
        return merged_points, merged_triangles

    # ------------------------------------------------------------------
    # Phase 7a delete / remove helpers (spec §5.2)
    # ------------------------------------------------------------------

    @classmethod
    def is_feature_line_in_use(
        cls,
        ifc_file: "ifcopenshell.file",
        feature_line_guid: str,
    ) -> tuple[bool, Optional[str]]:
        """Return ``(in_use, owning_group_name)`` for ``feature_line_guid``.

        A feature line is "in use" when it is a member of at least one
        :class:`IfcGroup` with ``ObjectType="GradingGroup"`` via an
        :class:`IfcRelAssignsToGroup` relationship.

        This checks the canonical source of truth — group membership via
        ``IfcRelAssignsToGroup`` — rather than the stale
        ``SaikeiCivil_FeatureLineCommon.GradingGroupGuid`` field, which is
        only written at feature-line create time and is never updated when
        the feature line is added to a group by
        :func:`ifcopenshell.api.grading.add_slope_fill_to_group`.

        :param ifc_file: the active IFC file.
        :param feature_line_guid: GlobalId of the feature line to check.
        :returns: ``(True, group_name)`` if in use; ``(False, None)``
            otherwise.
        """
        alignment = next(
            (
                e
                for e in ifc_file.by_type("IfcAlignment")
                if e.GlobalId == feature_line_guid
            ),
            None,
        )
        if alignment is None:
            return False, None

        for rel in getattr(alignment, "HasAssignments", None) or []:
            if not rel.is_a("IfcRelAssignsToGroup"):
                continue
            relating_group = getattr(rel, "RelatingGroup", None)
            if relating_group is None:
                continue
            if getattr(relating_group, "ObjectType", None) == "GradingGroup":
                return True, relating_group.Name or "<unnamed>"

        return False, None

    @classmethod
    def delete_feature_line(
        cls,
        ifc_file: "ifcopenshell.file",
        feature_line_guid: str,
    ) -> None:
        """Delete a feature line: removes the :class:`IfcAlignment` entity,
        its ``SaikeiCivil_FeatureLineCommon``, unlinks the Blender curve,
        and evicts the entry from the registry.

        :raises BlockedByDependentError: when the feature line is currently
            assigned to a grading group as its source FL — deleting it
            would orphan the group's slope projection.
        :raises SaikeiGradingError: when no :class:`IfcAlignment` with
            ``feature_line_guid`` exists in the file.
        """
        in_use, group_name = cls.is_feature_line_in_use(ifc_file, feature_line_guid)
        if in_use:
            raise BlockedByDependentError(
                f"Feature line in use by grading group {group_name!r}"
            )

        alignment = next(
            (
                e
                for e in ifc_file.by_type("IfcAlignment")
                if e.GlobalId == feature_line_guid
            ),
            None,
        )
        if alignment is None:
            raise SaikeiGradingError(
                f"no IfcAlignment with GlobalId {feature_line_guid!r} in this file"
            )

        # Unlink the Blender curve object before the IFC entity is removed.
        # IfcStore.unlink_element accepts exactly one argument; passing the
        # element lets it evict the id_map entry and purge IFC data from the
        # linked Blender object automatically.
        obj = tool.Ifc.get_object(alignment)
        tool.Ifc.unlink(element=alignment)
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)

        ifcopenshell.api.root.remove_product(ifc_file, product=alignment)

        # Evict from in-memory registry.
        cls.invalidate(ifc_file, feature_line_guid)

    @classmethod
    def criteria_dependents(
        cls,
        ifc_file: "ifcopenshell.file",
        criteria_guid: str,
    ) -> list[str]:
        """Return the names of grading groups that have this criteria bound.

        A criteria is "in use" when at least one :class:`IfcGroup` with
        ``ObjectType="GradingGroup"`` has a bound
        :class:`IfcPropertySet` instance linked to the criteria template
        via :class:`IfcRelDefinesByTemplate` — regardless of whether the
        group currently has any slope-fill members.

        The group-binding is the canonical "in use" state:
        :func:`ifcopenshell.api.grading.assign_grading_criteria` authors
        the ``IfcRelDefinesByTemplate`` link before any slope fills are
        added, so checking for slope-fill members would miss a freshly
        assigned but empty group and allow a delete that orphans the
        group's bound :class:`IfcPropertySet`.

        :param ifc_file: the active IFC file.
        :param criteria_guid: GlobalId of the criteria
            (:class:`IfcPropertySetTemplate`) to check.
        :returns: list of unique group names that have this criteria bound
            (may be empty if no groups are bound).
        """
        # Locate the IfcPropertySetTemplate for this criteria.
        criteria_template = next(
            (
                t
                for t in ifc_file.by_type("IfcPropertySetTemplate")
                if t.GlobalId == criteria_guid
            ),
            None,
        )
        if criteria_template is None:
            return []

        dependent_group_names: list[str] = []
        seen_group_ids: set[int] = set()

        for rel_defines in ifc_file.by_type("IfcRelDefinesByTemplate"):
            if rel_defines.RelatingTemplate.id() != criteria_template.id():
                continue
            for defined_pset in rel_defines.RelatedPropertySets or []:
                # Walk forward from the pset instance to every owning
                # IfcGroup[GradingGroup] via IfcRelDefinesByProperties.
                for rel_by_props in ifc_file.by_type("IfcRelDefinesByProperties"):
                    if rel_by_props.RelatingPropertyDefinition.id() != defined_pset.id():
                        continue
                    for product in rel_by_props.RelatedObjects or []:
                        if (
                            product.is_a("IfcGroup")
                            and getattr(product, "ObjectType", None) == "GradingGroup"
                            and product.id() not in seen_group_ids
                        ):
                            seen_group_ids.add(product.id())
                            dependent_group_names.append(
                                product.Name or "<unnamed>"
                            )

        return dependent_group_names

    @classmethod
    def delete_criteria(
        cls,
        ifc_file: "ifcopenshell.file",
        criteria_guid: str,
    ) -> None:
        """Delete a grading criteria template.

        :raises BlockedByDependentError: when one or more grading groups have
            this criteria bound via ``IfcRelDefinesByTemplate`` (a bound group
            with no slope fills still counts as a dependent).
        :raises SaikeiGradingError: when no criteria with ``criteria_guid``
            exists.
        """
        dependents = cls.criteria_dependents(ifc_file, criteria_guid)
        if dependents:
            count = len(dependents)
            raise BlockedByDependentError(
                f"Criteria in use by {count} grading group(s); "
                "unassign the criteria first."
            )

        criteria_template = next(
            (
                t
                for t in ifc_file.by_type("IfcPropertySetTemplate")
                if t.GlobalId == criteria_guid
            ),
            None,
        )
        if criteria_template is None:
            raise SaikeiGradingError(
                f"no criteria (IfcPropertySetTemplate) with GlobalId "
                f"{criteria_guid!r} in this file"
            )

        ifcopenshell.api.pset_template.remove_pset_template(
            ifc_file, pset_template=criteria_template
        )
        cls.invalidate(ifc_file, criteria_guid)

    @classmethod
    def remove_object_from_group(
        cls,
        ifc_file: "ifcopenshell.file",
        object_guid: str,
        group_guid: str,
    ) -> None:
        """Break the :class:`IfcRelAssignsToGroup` membership for a grading
        object (slope fill) without destroying the entity itself.

        Per spec §11 vocabulary: **Remove** severs a relationship; **Delete**
        destroys an entity. This method only removes the group membership.
        The ``IfcEarthworksFill[SLOPEFILL]`` entity remains in the file.

        :raises SaikeiGradingError: when the object or group cannot be found.
        """
        ifc_product = next(
            (
                e
                for e in ifc_file.by_type("IfcEarthworksFill")
                if e.GlobalId == object_guid
            ),
            None,
        )
        if ifc_product is None:
            raise SaikeiGradingError(
                f"no IfcEarthworksFill with GlobalId {object_guid!r} in this file"
            )

        ifc_group = next(
            (
                g
                for g in ifc_file.by_type("IfcGroup")
                if g.GlobalId == group_guid
                and getattr(g, "ObjectType", None) == "GradingGroup"
            ),
            None,
        )
        if ifc_group is None:
            raise SaikeiGradingError(
                f"no IfcGroup[GradingGroup] with GlobalId {group_guid!r} in this file"
            )

        ifcopenshell.api.group.unassign_group(
            ifc_file, products=[ifc_product], group=ifc_group
        )

        # Evict the grading object from the in-memory registry so the next
        # rebuild doesn't include stale geometry for the removed member.
        cls.invalidate(ifc_file, object_guid)

        # Also refresh the in-memory GradingGroup dataclass if cached.
        cached_group = cls._registry.get((id(ifc_file), group_guid))
        if cached_group is not None and hasattr(cached_group, "members"):
            cached_group.members = [
                m for m in cached_group.members if m.guid != object_guid
            ]

    # ------------------------------------------------------------------
    # Phase 7b stepped-offset + fillet helpers (spec §6.2)
    # ------------------------------------------------------------------

    #: Number of arc sample points used by :meth:`insert_fillet`.
    #: 16 matches common Civil 3D defaults for plan curves; future phases
    #: can expose this as a kwarg or a scene-property preference.
    _FILLET_ARC_SAMPLES: int = 16

    @classmethod
    def compute_stepped_offset(
        cls,
        ifc_file: "ifcopenshell.file",
        fl_id: int,
        offset: float,
        step_dz: float,
    ) -> list[tuple[float, float, float]]:
        """Compute a parallel offset polyline with a per-vertex Z step.

        Returns the offset polyline vertices for a "stepped offset" —
        each vertex is shifted perpendicular to the local segment
        direction by ``offset`` metres and incremented in Z by
        ``step_dz`` relative to the *source* vertex.

        Algorithm:
        1. Load the source feature line by IFC step id ``fl_id``.
        2. For each interior vertex, compute the averaged perpendicular
           direction from the two flanking segments; for end vertices
           use the single adjacent segment.
        3. Shift by ``offset`` in the XY plane along that perpendicular.
        4. Add ``step_dz * vertex_index`` to Z.

        This is a pure computation — no IFC entities are mutated.

        :param ifc_file: active IFC file.
        :param fl_id: IFC step id of the source :class:`IfcAlignment`.
        :param offset: perpendicular offset distance in project units
            (positive = left of direction of travel, negative = right).
        :param step_dz: Z increment applied cumulatively along the
            polyline (positive = uphill, negative = downhill).
        :returns: list of ``(x, y, z)`` tuples for the offset polyline.
        :raises SaikeiGradingError: if ``fl_id`` does not exist in
            ``ifc_file`` or is not a Saikei feature line.
        """
        alignment = None
        try:
            alignment = ifc_file.by_id(fl_id)
        except Exception:
            pass
        if alignment is None or not alignment.is_a("IfcAlignment"):
            raise SaikeiGradingError(
                f"No IfcAlignment with step id {fl_id} in this file"
            )
        if not cls.is_feature_line_alignment(alignment):
            raise SaikeiGradingError(
                f"IfcAlignment #{fl_id} is not a Saikei feature line "
                "(missing SaikeiCivil_FeatureLineCommon)"
            )

        feature_line = cls.get_feature_line(ifc_file, alignment.GlobalId)
        verts = feature_line.vertices
        n = len(verts)
        if n < 2:
            raise SaikeiGradingError(
                f"Feature line #{fl_id} has fewer than 2 vertices; "
                "cannot compute perpendicular offset"
            )

        # Build per-vertex perpendicular directions (2D).
        def _perp_2d(ax: float, ay: float, bx: float, by: float) -> tuple[float, float]:
            """Left-hand perpendicular of segment (a→b), normalised."""
            dx = bx - ax
            dy = by - ay
            length = math.hypot(dx, dy)
            if length < 1e-12:
                return (0.0, 1.0)
            # Left perpendicular: (-dy, dx)
            return (-dy / length, dx / length)

        perps: list[tuple[float, float]] = []
        for i in range(n):
            if i == 0:
                px, py = _perp_2d(verts[0][0], verts[0][1], verts[1][0], verts[1][1])
            elif i == n - 1:
                px, py = _perp_2d(
                    verts[n - 2][0], verts[n - 2][1],
                    verts[n - 1][0], verts[n - 1][1],
                )
            else:
                # Bisector direction: average of the two flanking left-hand
                # perpendiculars.  The offset point must lie at perpendicular
                # distance ``offset`` from BOTH adjacent segments.
                #
                # The bisector unit vector b satisfies:
                #   b · perp_in = sin(half_angle)
                # so the point at distance d along b has perpendicular distance
                #   d * sin(half_angle) from each segment.
                # Setting that equal to |offset| gives d = offset / sin(half_angle).
                #
                # Equivalently: scale the averaged-perpendicular sum vector by
                # 1 / cos(half_angle) where the averaged vector has length
                # 2 * cos(half_angle) when the inputs are unit vectors.
                # The simpler form used here: normalise the bisector to unit
                # length, then scale the result by 1 / sin(half_angle).
                px0, py0 = _perp_2d(
                    verts[i - 1][0], verts[i - 1][1],
                    verts[i][0], verts[i][1],
                )
                px1, py1 = _perp_2d(
                    verts[i][0], verts[i][1],
                    verts[i + 1][0], verts[i + 1][1],
                )
                # Bisector direction (unit) is (perp_in + perp_out) normalised.
                # The point at distance d along this bisector has perpendicular
                # distance d * sin(half_angle) from each segment.  To get
                # perpendicular distance = offset, set d = offset / sin(half_angle).
                bisector_x = px0 + px1
                bisector_y = py0 + py1
                bis_mag = math.hypot(bisector_x, bisector_y)
                if bis_mag < 1e-12:
                    # Near-collinear: fall back to incoming perpendicular.
                    px, py = px0, py0
                else:
                    # Normalise bisector to unit vector.
                    bux = bisector_x / bis_mag
                    buy = bisector_y / bis_mag
                    # sin(half_angle) = dot(bisector_unit, either perp_in/out).
                    # Since perp_in and perp_out are already unit vectors,
                    # sin_half = bux * px0 + buy * py0 (dot product).
                    sin_half = bux * px0 + buy * py0
                    # Guard near-collinear corners (sin_half ≈ 0 → scale blows up).
                    scale = 1.0 / max(abs(sin_half), 1e-6)
                    px = bux * scale
                    py = buy * scale
            perps.append((px, py))

        result: list[tuple[float, float, float]] = []
        for i, (x, y, z) in enumerate(verts):
            px, py = perps[i]
            result.append((
                x + offset * px,
                y + offset * py,
                z + step_dz * i,
            ))

        return result

    @classmethod
    def insert_fillet(
        cls,
        ifc_file: "ifcopenshell.file",
        fl_id: int,
        vertex_index: int,
        radius: float,
    ) -> None:
        """Replace a sharp corner at ``vertex_index`` with a circular arc.

        The arc replaces the original vertex with :attr:`_FILLET_ARC_SAMPLES`
        uniformly-sampled points along a circle of ``radius`` metres tangent
        to both adjacent segments. Updates the IFC entity's
        :class:`IfcIndexedPolyCurve` and the linked Blender curve in place.

        Algorithm:
        1. Locate the two adjacent segment vectors.
        2. Compute the interior half-angle ``θ/2`` between the two
           reversed inbound/outbound unit vectors.
        3. The tangent points are at distance
           ``t = radius / tan(θ/2)`` from the corner.  Raise
           :class:`SaikeiGradingError` if ``t > min(seg_len)/2``.
        4. Place arc centre along the angle bisector at distance
           ``radius / sin(θ/2)`` from the corner.
        5. Sample the arc from tangent point A to tangent point B
           (:attr:`_FILLET_ARC_SAMPLES` points).
        6. Splice the sample points into the vertex list, replacing the
           original corner vertex.

        :param ifc_file: active IFC file.
        :param fl_id: IFC step id of the source :class:`IfcAlignment`.
        :param vertex_index: index of the corner vertex to fillet.
        :param radius: fillet radius in project units.
        :raises SaikeiGradingError: for invalid index, nonpositive radius,
            or radius larger than either adjacent segment's half-length.
        """
        alignment = None
        try:
            alignment = ifc_file.by_id(fl_id)
        except Exception:
            pass
        if alignment is None or not alignment.is_a("IfcAlignment"):
            raise SaikeiGradingError(
                f"No IfcAlignment with step id {fl_id} in this file"
            )
        if not cls.is_feature_line_alignment(alignment):
            raise SaikeiGradingError(
                f"IfcAlignment #{fl_id} is not a Saikei feature line"
            )

        if radius <= 0.0:
            raise SaikeiGradingError(
                f"Fillet radius must be positive; got {radius}"
            )

        feature_line = cls.get_feature_line(ifc_file, alignment.GlobalId)
        verts = list(feature_line.vertices)
        n = len(verts)

        if not (1 <= vertex_index <= n - 2):
            raise SaikeiGradingError(
                f"vertex_index {vertex_index} is out of range [1, {n - 2}]; "
                "the fillet requires vertices on both sides of the corner"
            )

        prev_v = np.array(verts[vertex_index - 1], dtype=float)
        corner = np.array(verts[vertex_index], dtype=float)
        next_v = np.array(verts[vertex_index + 1], dtype=float)

        # Vectors from corner to neighbours.
        v_in = prev_v - corner
        v_out = next_v - corner
        len_in = float(np.linalg.norm(v_in))
        len_out = float(np.linalg.norm(v_out))

        if len_in < 1e-12 or len_out < 1e-12:
            raise SaikeiGradingError(
                "Adjacent segment has zero length — cannot insert fillet"
            )

        u_in = v_in / len_in
        u_out = v_out / len_out

        # Half-angle between the two legs.
        cos_half = float(np.clip(np.dot(u_in[:2], u_out[:2]), -1.0, 1.0))
        # cos_half here is cos(full_angle_between_reversed_legs/2)?
        # Actually dot(u_in, u_out) = cos(angle between them in 2D).
        # The angle between the two directed vectors from the corner is
        # alpha = acos(dot(u_in, u_out)) where alpha is the "opening"
        # angle of the bend. The tangent distance is radius/tan(alpha/2).
        full_cos = float(np.clip(np.dot(u_in[:2], u_out[:2]), -1.0, 1.0))
        full_angle = math.acos(full_cos)  # angle between the two legs (0..π)
        if full_angle < 1e-9 or abs(full_angle - math.pi) < 1e-9:
            raise SaikeiGradingError(
                "Corner angle is 0 or 180 degrees — fillet is degenerate"
            )
        half_angle = full_angle / 2.0
        tan_dist = radius / math.tan(half_angle)

        if tan_dist > len_in / 2.0 or tan_dist > len_out / 2.0:
            raise SaikeiGradingError(
                f"Fillet radius {radius} is too large for this corner: "
                f"tangent distance {tan_dist:.4f} exceeds half the adjacent "
                f"segment lengths ({len_in / 2:.4f}, {len_out / 2:.4f})"
            )

        # Tangent points on each leg.
        pt_a = corner + u_in * tan_dist
        pt_b = corner + u_out * tan_dist

        # Arc centre: bisector direction, distance = radius / sin(half_angle).
        bisector_2d = u_in[:2] + u_out[:2]
        bis_len = float(np.linalg.norm(bisector_2d))
        if bis_len < 1e-12:
            raise SaikeiGradingError("Degenerate corner bisector — cannot insert fillet")
        bisector_unit = np.zeros(3, dtype=float)
        bisector_unit[:2] = bisector_2d / bis_len
        # Z of centre interpolated between the two tangent points.
        centre_z = float(0.5 * (pt_a[2] + pt_b[2]))
        arc_centre = np.array(
            [
                corner[0] + bisector_unit[0] * (radius / math.sin(half_angle)),
                corner[1] + bisector_unit[1] * (radius / math.sin(half_angle)),
                centre_z,
            ],
            dtype=float,
        )

        # Angles from centre to tangent points in XY plane.
        def _angle_2d(centre: np.ndarray, pt: np.ndarray) -> float:
            return math.atan2(float(pt[1] - centre[1]), float(pt[0] - centre[0]))

        angle_a = _angle_2d(arc_centre, pt_a)
        angle_b = _angle_2d(arc_centre, pt_b)

        # The arc must go the short way (< π) between the tangent points,
        # in the direction that stays on the correct side of the corner.
        # Determine the sign of the turn using 2D cross product of u_in × u_out.
        cross_z = float(u_in[0] * u_out[1] - u_in[1] * u_out[0])
        # cross_z > 0 → left turn (counter-clockwise); < 0 → right turn (cw).
        # The fillet arc wraps on the *inside* of the bend.
        # CCW bend → arc goes CW from A to B (angle decreasing); and vice versa.
        if cross_z > 0:
            # Left turn: sweep CW (i.e., angle_a → angle_b clockwise).
            if angle_b > angle_a:
                angle_b -= 2 * math.pi
        else:
            # Right turn: sweep CCW.
            if angle_b < angle_a:
                angle_b += 2 * math.pi

        arc_points: list[tuple[float, float, float]] = []
        for k in range(cls._FILLET_ARC_SAMPLES):
            t = k / (cls._FILLET_ARC_SAMPLES - 1)
            angle = angle_a + t * (angle_b - angle_a)
            ax = arc_centre[0] + radius * math.cos(angle)
            ay = arc_centre[1] + radius * math.sin(angle)
            # Linear Z interpolation along the arc.
            az = float(pt_a[2]) + t * (float(pt_b[2]) - float(pt_a[2]))
            arc_points.append((ax, ay, az))

        # Splice: replace vertex_index with the arc samples.
        new_verts = verts[:vertex_index] + arc_points + verts[vertex_index + 1:]
        feature_line.vertices = new_verts

        try:
            cls.update_feature_line_vertices(ifc_file, feature_line)
        except SaikeiGradingError:
            raise

        try:
            cls.update_blender_curve(ifc_file, feature_line)
        except SaikeiGradingError:
            # No linked Blender curve yet (headless / pure-IFC authoring path).
            # This is expected when insert_fillet is called without a prior
            # create_blender_curve.  Silent no-op is correct here.
            pass
        except Exception as exc:
            # Unexpected Blender error — log a warning rather than swallowing
            # silently so developers can see it during debugging.
            import logging

            logging.getLogger(__name__).warning(
                "insert_fillet: update_blender_curve failed unexpectedly: %s", exc
            )

        # Invalidate the registry entry so the next get_feature_line
        # rehydrates the updated polyline from IFC.
        cls.invalidate(ifc_file, alignment.GlobalId)

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
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Optional, Union

import ifcopenshell.guid
import numpy as np

if TYPE_CHECKING:
    import ifcopenshell


_logger = logging.getLogger("bonsai.tool.grading")


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

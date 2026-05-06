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

"""Saikei grading core — orchestration only, NO bpy / numpy / shapely.

Phase 5 of the Saikei grading/earthwork sprint. This module owns the
business-rule layer for grading creation and editing: validates inputs,
sequences calls into :mod:`bonsai.tool.grading` (and :mod:`bonsai.tool.surface`
where surface lookups are needed), and translates user intent into the
right tool method chain.

Per spec §4.7 (alignment-precedent), every function takes the tool
classes as explicit type-injected parameters (``ifc_tool``,
``surface_tool``, ``grading_tool``) so tests can substitute Prophecy-
tracked stubs without monkeypatching.

What lives here:

- Validation: file loaded, name non-empty, target_kind / interior_fill
  in allowed sets, vertex / slope value sanity checks.
- Sequencing: build → author → register, with surface lookups for
  surface-targeted criteria.
- Decisions: "should we allow this?" — empty feature lines, unknown
  target kinds, multi-site warnings.

What does NOT live here:

- Math (slope projection, ribbon triangulation, interior fill) —
  :mod:`bonsai.tool.grading`.
- IFC entity creation — :mod:`bonsai.tool.grading` delegating to
  :mod:`ifcopenshell.api.grading`.
- Blender object/mesh manipulation (``bpy``) — :mod:`bonsai.tool.grading`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional, Union

if TYPE_CHECKING:
    from .. import tool


_logger = logging.getLogger("bonsai.core.grading")


_ALLOWED_TARGET_KINDS = {
    "surface",
    "elevation",
    "relative_elevation",
    "distance",
}
_ALLOWED_INTERIOR_FILLS = {
    "none",
    "flat",
    "interpolate_from_boundary",
    "from_surface",
}


def _warn_multi_site(ifc_file: Any) -> None:
    """Same multi-site footgun guard as :func:`bonsai.core.surface._warn_multi_site`,
    duplicated here to keep the core layer's import surface tight (no
    cross-core imports). Logs WARNING when ``len(by_type("IfcSite")) > 1``.
    """
    try:
        site_count = len(ifc_file.by_type("IfcSite"))
    except Exception:
        return
    if site_count > 1:
        _logger.warning(
            "Saikei grading operator running on a multi-site IFC file "
            "(%d IfcSite entities). The default spatial parent "
            "resolution picks the first IfcSite — pass an explicit "
            "site argument if that's not the one you intended.",
            site_count,
        )


def create_feature_line(
    ifc_tool: "type[tool.Ifc]",
    grading_tool: "type[tool.Grading]",
    name: str,
    vertices: Any,
    closed: bool = False,
) -> Any:
    """Author a feature line from an XYZ vertex sequence.

    Business rules:

    1. An IFC file must be loaded.
    2. ``name`` must be non-empty after stripping.
    3. ``vertices`` must contain at least 2 points (the tool layer
       enforces this; we surface it as a clean :class:`ValueError`
       at the orchestration boundary).

    Sequencing:

    1. Build a :class:`bonsai.tool.grading.FeatureLine` dataclass — the
       :class:`Grading` tool's :meth:`author_feature_line` will set
       defaults for any optional fields.
    2. :meth:`tool.Grading.author_feature_line` — persists as
       :class:`IfcAlignment` with :class:`IfcIndexedPolyCurve`
       representation.
    3. :meth:`tool.Grading.register` — adds to the registry under
       ``(id(ifc_file), guid)``.

    :param ifc_tool: the :class:`tool.Ifc` class.
    :param grading_tool: the :class:`tool.Grading` class.
    :param name: human-readable label.
    :param vertices: ``(N, 3)`` sequence of ``(x, y, z)`` coordinates.
    :param closed: True for closed loops (pad perimeters); False for
        open lines (e.g., ditch centerlines).
    :returns: the authored :class:`FeatureLine` dataclass with
        ``ifc_alignment_id`` stamped.
    :raises ValueError: if no IFC file is loaded, name is empty, or
        vertices has fewer than 2 points.
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")

    if not name or not name.strip():
        raise ValueError("feature line name cannot be empty")

    vertex_list = list(vertices)
    if len(vertex_list) < 2:
        raise ValueError(
            f"feature line needs ≥ 2 vertices; got {len(vertex_list)}"
        )

    _warn_multi_site(ifc_file)

    # Lazy-import the dataclass to keep the core module's TYPE_CHECKING
    # boundary clean — runtime construction goes through the tool
    # module's exported symbol so callers can substitute test doubles.
    from ..tool.grading import FeatureLine

    feature_line = FeatureLine(
        name=name.strip(),
        vertices=[
            (float(v[0]), float(v[1]), float(v[2])) for v in vertex_list
        ],
        closed=bool(closed),
    )
    grading_tool.author_feature_line(ifc_file, feature_line)
    grading_tool.register(ifc_file, feature_line)
    return feature_line


def create_grading_criteria(
    ifc_tool: "type[tool.Ifc]",
    grading_tool: "type[tool.Grading]",
    name: str,
    target_kind: str,
    target_ref: Union[str, float],
    cut_slope: float = 2.0,
    fill_slope: float = 3.0,
    max_distance: Optional[float] = None,
    retaining_wall_at_limit: bool = False,
) -> Any:
    """Author a reusable grading criteria.

    Business rules:

    1. An IFC file must be loaded.
    2. ``name`` must be non-empty after stripping.
    3. ``target_kind`` must be one of the four spec §5 values.
    4. ``cut_slope`` and ``fill_slope`` must be positive (slope ratios
       are H:V where H ≥ 0 by convention).

    Sequencing: build :class:`GradingCriteria` → author template (via
    Phase 2's :func:`create_grading_criteria_template`, idempotent
    singleton-by-shape) → register.

    Note: the criteria template is project-scoped and shared — a fresh
    criteria-instance binding to a group happens in
    :func:`add_grading_object`. This function only authors the
    template + dataclass; binding to a specific group is a separate
    edit-flow operation.

    :raises ValueError: on input validation failures listed above.
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")

    if not name or not name.strip():
        raise ValueError("grading criteria name cannot be empty")

    if target_kind not in _ALLOWED_TARGET_KINDS:
        raise ValueError(
            f"target_kind must be one of {sorted(_ALLOWED_TARGET_KINDS)}, "
            f"got {target_kind!r}"
        )

    if cut_slope <= 0 or fill_slope <= 0:
        raise ValueError(
            f"slope ratios must be positive; got cut_slope={cut_slope}, "
            f"fill_slope={fill_slope}"
        )

    from ..tool.grading import GradingCriteria

    criteria = GradingCriteria(
        name=name.strip(),
        target_kind=target_kind,  # type: ignore[arg-type]
        target_ref=target_ref,
        cut_slope=float(cut_slope),
        fill_slope=float(fill_slope),
        max_distance=(
            float(max_distance) if max_distance is not None else None
        ),
        retaining_wall_at_limit=bool(retaining_wall_at_limit),
    )
    grading_tool.author_criteria_template(ifc_file, criteria)
    grading_tool.register(ifc_file, criteria)
    return criteria


def create_grading_group(
    ifc_tool: "type[tool.Ifc]",
    surface_tool: "type[tool.Surface]",
    grading_tool: "type[tool.Grading]",
    name: str,
    target_surface_guid: Optional[str] = None,
    interior_fill: str = "interpolate_from_boundary",
    interior_fill_source_guid: Optional[str] = None,
) -> Any:
    """Author an empty grading group.

    Business rules:

    1. An IFC file must be loaded.
    2. ``name`` must be non-empty.
    3. ``interior_fill`` must be one of the four spec §6.3 values.
    4. ``interior_fill="from_surface"`` requires
       ``interior_fill_source_guid``.

    Sequencing:

    1. Resolve ``target_surface`` from ``target_surface_guid`` (lookup
       via :meth:`tool.Surface.get`) — required when grading objects
       added to this group will use ``target_kind="surface"`` criteria.
       Optional at group-creation time.
    2. Resolve ``interior_fill_source`` from ``interior_fill_source_guid``
       when applicable.
    3. Build :class:`GradingGroup` dataclass with the resolved targets.
    4. :meth:`tool.Grading.author_group` — authors
       :class:`IfcGroup[GradingGroup]` + per-group composite
       :class:`IfcEarthworksFill[SUBGRADE]`.
    5. :meth:`tool.Grading.register`.

    :raises ValueError: on input validation failures.
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")

    if not name or not name.strip():
        raise ValueError("grading group name cannot be empty")

    if interior_fill not in _ALLOWED_INTERIOR_FILLS:
        raise ValueError(
            f"interior_fill must be one of {sorted(_ALLOWED_INTERIOR_FILLS)}, "
            f"got {interior_fill!r}"
        )

    if interior_fill == "from_surface" and not interior_fill_source_guid:
        raise ValueError(
            "interior_fill='from_surface' requires interior_fill_source_guid"
        )

    _warn_multi_site(ifc_file)

    target_surface_entity = None
    if target_surface_guid:
        target_surface = surface_tool.get(ifc_file, target_surface_guid)
        target_surface_entity = ifc_file.by_id(target_surface.ifc_host_entity_id)

    interior_source_entity = None
    if interior_fill_source_guid:
        source_surface = surface_tool.get(ifc_file, interior_fill_source_guid)
        interior_source_entity = ifc_file.by_id(
            source_surface.ifc_host_entity_id
        )

    from ..tool.grading import GradingGroup

    group = GradingGroup(
        name=name.strip(),
        interior_fill=interior_fill,  # type: ignore[arg-type]
        interior_fill_source_guid=interior_fill_source_guid,
        target_surface_guid=target_surface_guid,
    )
    grading_tool.author_group(
        ifc_file,
        group,
        target_surface=target_surface_entity,
        interior_fill_source=interior_source_entity,
    )
    grading_tool.register(ifc_file, group)
    return group


def add_grading_object(
    ifc_tool: "type[tool.Ifc]",
    surface_tool: "type[tool.Surface]",
    grading_tool: "type[tool.Grading]",
    group_guid: str,
    feature_line_guid: str,
    criteria_guid: str,
) -> Any:
    """Apply a criteria to a feature line within a group, computing the
    slope projection and authoring the resulting slope fill.

    Business rules:

    1. An IFC file must be loaded.
    2. All three GUIDs must resolve via the appropriate registries.
    3. For ``criteria.target_kind == "surface"``, the criteria's
       ``target_ref`` (or the group's ``target_surface_guid`` as
       fallback) must resolve to a :class:`CivilSurface`.

    Sequencing:

    1. Resolve the three entities from registries (lazy-rehydrating
       on cache miss).
    2. Resolve the target surface (when applicable).
    3. :meth:`tool.Grading.compute_grading_object` — runs slope
       projection.
    4. :meth:`tool.Grading.assign_criteria` — binds a criteria pset
       to the group (idempotent on re-bind).
    5. :meth:`tool.Grading.author_slope_fill` — persists as
       :class:`IfcEarthworksFill[SLOPEFILL]`.
    6. Append the new :class:`GradingObject` to ``group.members``.

    :returns: the new :class:`GradingObject` with all step ids stamped.
    :raises ValueError: on input validation failures.
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")

    feature_line = grading_tool.get_feature_line(ifc_file, feature_line_guid)
    group = grading_tool.get_group(ifc_file, group_guid)
    # GradingCriteria isn't directly retrievable via get_*; the registry
    # caches it but doesn't yet have a get_criteria helper (Phase 5.1
    # deferral per the v3.2.5 amendments queue). For now, accept that
    # the caller passes a registered-criteria GUID — the registry
    # lookup happens via the internal _registry dict.
    criteria = grading_tool._registry.get(  # type: ignore[attr-defined]
        (id(ifc_file), criteria_guid)
    )
    if criteria is None:
        raise ValueError(
            f"no GradingCriteria registered with GUID {criteria_guid!r}; "
            "call create_grading_criteria first"
        )

    # Resolve target surface for "surface" kind.
    target_surface = None
    if criteria.target_kind == "surface":
        target_guid = (
            str(criteria.target_ref)
            if criteria.target_ref
            else group.target_surface_guid
        )
        if not target_guid:
            raise ValueError(
                "criteria.target_kind == 'surface' but no target_ref or "
                "group.target_surface_guid is set"
            )
        target_surface = surface_tool.get(ifc_file, target_guid)

    grading_object = grading_tool.compute_grading_object(
        feature_line,
        criteria,
        target_surface=target_surface,
        side="auto",
        name=f"{feature_line.name} @ {criteria.name}",
    )
    grading_tool.assign_criteria(ifc_file, group, criteria)
    grading_tool.author_slope_fill(ifc_file, group, grading_object)
    grading_tool.register(ifc_file, grading_object)
    group.members.append(grading_object)
    return grading_object


def rebuild_group(
    ifc_tool: "type[tool.Ifc]",
    surface_tool: "type[tool.Surface]",
    grading_tool: "type[tool.Grading]",
    group_guid: str,
) -> Any:
    """Force-rebuild ``group``'s composite proposed surface and register
    the result in the surface tool's cache.

    Sequencing:

    1. Resolve the group via :meth:`tool.Grading.get_group`.
    2. :meth:`tool.Grading.rebuild_group_surface` — assembles the
       composite :class:`CivilSurface` from member slope fills + the
       interior-fill strategy.
    3. :meth:`tool.Surface.register` — caches the composite in the
       surface registry under ``(id(ifc_file), group.output_surface_guid)``
       so subsequent ``tool.Surface.get`` calls (Phase 6 volume math,
       UI panel summaries) hit the cache rather than rehydrating.

    :returns: the composite :class:`CivilSurface`.
    :raises ValueError: on input validation failures.
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")

    group = grading_tool.get_group(ifc_file, group_guid)
    composite_surface = grading_tool.rebuild_group_surface(ifc_file, group)
    # Cache contract: tool.Surface.get(file, group.output_surface_guid)
    # must return the in-memory composite without round-tripping through
    # IFC rehydration.
    surface_tool.register(ifc_file, composite_surface)
    return composite_surface


def drape_feature_line(
    ifc_tool: "type[tool.Ifc]",
    surface_tool: "type[tool.Surface]",
    grading_tool: "type[tool.Grading]",
    feature_line_guid: str,
    surface_guid: str,
) -> Any:
    """Replace each vertex's Z on ``feature_line`` with
    ``surface.z_at(x, y)``. Persists the change to IFC via
    :meth:`tool.Grading.update_feature_line_vertices`.

    Common Civil 3D operation: drag a feature line over an existing
    surface and let the elevations match. Spec §6.2's slope projection
    starts with a feature line whose Z values are authored — this
    helper provides one way to author them.

    Business rules:

    1. An IFC file must be loaded.
    2. Both GUIDs must resolve via the appropriate registries.
    3. Every feature-line vertex's XY must fall inside the source
       surface's triangulation; otherwise :meth:`tool.Surface.z_at`
       returns ``None`` and we raise.

    :returns: the mutated :class:`FeatureLine` with new Z values.
    :raises ValueError: on input validation failures or out-of-bounds
        XY (any vertex outside the source surface).
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")

    feature_line = grading_tool.get_feature_line(ifc_file, feature_line_guid)
    surface = surface_tool.get(ifc_file, surface_guid)

    new_vertices: list[tuple[float, float, float]] = []
    for vertex in feature_line.vertices:
        x, y = float(vertex[0]), float(vertex[1])
        z = surface_tool.z_at(surface, x, y)
        if z is None:
            raise ValueError(
                f"feature-line vertex ({x:.3f}, {y:.3f}) falls outside "
                f"surface {surface_guid!r}'s triangulation; cannot drape"
            )
        new_vertices.append((x, y, float(z)))
    feature_line.vertices = new_vertices

    # Persist the new Z values back to the IFC alignment. Without this
    # step, the in-memory FeatureLine and the IFC entity diverge —
    # subsequent slope projections use the new Z's, but the IFC file
    # still has the old polyline.
    grading_tool.update_feature_line_vertices(ifc_file, feature_line)
    return feature_line


def delete_feature_line(
    ifc_tool: "type[tool.Ifc]",
    grading_tool: "type[tool.Grading]",
    feature_line_guid: str,
) -> None:
    """Delete a feature line from the IFC file and unlink its Blender object.

    Business rules:

    1. An IFC file must be loaded.
    2. The feature line must not be assigned to a grading group as its
       source FL — if it is, the tool layer raises
       :class:`BlockedByDependentError` (caught by the operator layer).

    :raises ValueError: if no IFC file is loaded or GUID is empty.
    :raises BlockedByDependentError: propagated from the tool layer when
        the feature line is in use by a grading group.
    :raises SaikeiGradingError: propagated from the tool layer when the
        entity cannot be found.
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")
    if not feature_line_guid:
        raise ValueError("feature_line_guid is required")

    grading_tool.delete_feature_line(ifc_file, feature_line_guid)


def remove_grading_object_from_group(
    ifc_tool: "type[tool.Ifc]",
    grading_tool: "type[tool.Grading]",
    surface_tool: "type[tool.Surface]",
    object_guid: str,
    group_guid: str,
) -> Any:
    """Remove a grading object from its parent group and rebuild the group surface.

    Per spec §11 vocabulary: **Remove** breaks the relationship without
    destroying the entity. This function:

    1. Validates inputs.
    2. Calls :meth:`tool.Grading.remove_object_from_group` to sever
       the :class:`IfcRelAssignsToGroup` link.
    3. Rebuilds the group composite surface via :func:`rebuild_group`
       so the group's proposed surface reflects the removal.

    :raises ValueError: if no IFC file is loaded or GUIDs are empty.
    :raises SaikeiGradingError: propagated from the tool layer.
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")
    if not object_guid or not group_guid:
        raise ValueError("object_guid and group_guid are both required")

    grading_tool.remove_object_from_group(ifc_file, object_guid, group_guid)

    # Rebuild the group composite surface only when the group still has
    # slope-fill members.  An empty group has nothing to compose, and
    # rebuild_group (called below) would raise on an empty member list.
    # We check IFC-side membership explicitly rather than catching the
    # exception, so any real rebuild failure propagates as intended.
    ifc_group = next(
        (
            g
            for g in ifc_file.by_type("IfcGroup")
            if g.GlobalId == group_guid
            and getattr(g, "ObjectType", None) == "GradingGroup"
        ),
        None,
    )
    has_slope_fill_members = False
    if ifc_group is not None:
        for rel in getattr(ifc_group, "IsGroupedBy", None) or []:
            for member in rel.RelatedObjects or []:
                if (
                    member.is_a("IfcEarthworksFill")
                    and getattr(member, "PredefinedType", None) == "SLOPEFILL"
                ):
                    has_slope_fill_members = True
                    break
            if has_slope_fill_members:
                break

    if has_slope_fill_members:
        rebuild_group(ifc_tool, surface_tool, grading_tool, group_guid=group_guid)

    return None


def delete_criteria(
    ifc_tool: "type[tool.Ifc]",
    grading_tool: "type[tool.Grading]",
    criteria_guid: str,
) -> None:
    """Delete a grading criteria template.

    Business rules:

    1. An IFC file must be loaded.
    2. No grading groups may have this criteria bound — if any do, the
       tool layer raises :class:`BlockedByDependentError` (caught by the
       operator layer). A bound group with no slope fills still blocks
       deletion.

    :raises ValueError: if no IFC file is loaded or GUID is empty.
    :raises BlockedByDependentError: propagated from the tool layer.
    :raises SaikeiGradingError: propagated from the tool layer.
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")
    if not criteria_guid:
        raise ValueError("criteria_guid is required")

    grading_tool.delete_criteria(ifc_file, criteria_guid)

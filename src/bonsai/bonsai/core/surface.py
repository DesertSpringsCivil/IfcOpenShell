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

"""Saikei surface core — orchestration only, NO bpy / scipy / shapely / numpy.

Phase 4 of the Saikei grading/earthwork sprint. This module owns the
business-rule layer for surface creation and editing: validates inputs,
sequences calls into :mod:`bonsai.tool.surface`, and translates user
intent ("create a TIN from these points") into the right tool method
chain.

Per spec §4.7 (alignment-precedent), every function takes the tool
classes as explicit type-injected parameters (``ifc_tool``,
``surface_tool``) so tests can substitute Prophecy-tracked stubs without
monkeypatching.

What lives here:

- Validation: file loaded, name non-empty, kind allowed.
- Sequencing: build → author → register; or build → author → register →
  create-mesh, depending on caller intent.
- Decisions: "should we allow this?" — e.g., reject empty point clouds.

What does NOT live here:

- Math (``scipy``/``shapely``/``numpy`` arithmetic) — :mod:`bonsai.tool.surface`.
- IFC entity creation (``ifc_file.create_entity``) — :mod:`bonsai.tool.surface`
  delegating to :mod:`ifcopenshell.api.surface`.
- Blender object/mesh manipulation (``bpy``) — :mod:`bonsai.tool.surface`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .. import tool


_ALLOWED_KINDS = {"existing", "proposed_group", "proposed_site"}

_logger = logging.getLogger("bonsai.core.surface")


def _warn_multi_site(ifc_file: Any) -> None:
    """Emit a warning when the file contains more than one IfcSite.

    Per spec §4.3, surface and breakline operators auto-resolve the spatial
    parent to ``file.by_type("IfcSite")[0]`` when no explicit site is
    supplied. In multi-site files this silently picks an arbitrary site,
    which can land surfaces in the wrong spatial container. The handoff
    flagged this as a footgun for Phases 4–6; this helper surfaces a
    warning so callers (operators, scripts) can detect the case and either
    abort or pass an explicit site.

    The warning routes through Python's logging module rather than
    ``self.report({"WARNING"}, ...)`` because core has no operator
    handle — UI operators can opt to elevate it (a Phase 4.1+ option).
    """
    try:
        site_count = len(ifc_file.by_type("IfcSite"))
    except Exception:
        return
    if site_count > 1:
        _logger.warning(
            "Saikei surface operator running on a multi-site IFC file "
            "(%d IfcSite entities). The default spatial parent "
            "resolution picks the first IfcSite — pass an explicit "
            "site argument if that's not the one you intended.",
            site_count,
        )


def create_surface_from_points(
    ifc_tool: "type[tool.Ifc]",
    surface_tool: "type[tool.Surface]",
    name: str,
    points: Any,
    kind: str = "existing",
    triangulation_tolerance: float = 0.0,
) -> Any:
    """Build a TIN from a point cloud, persist it to IFC, and register it.

    Business rules:

    1. An IFC file must be loaded (``ifc_tool.get()`` returns truthy).
    2. ``name`` must be non-empty after stripping.
    3. ``kind`` must be one of ``"existing"``, ``"proposed_group"``,
       ``"proposed_site"`` (the three Saikei surface host-entity flavours
       per spec §2.2).
    4. ``points`` is forwarded to the tool layer for shape / count
       validation (the tool layer raises :class:`SaikeiTriangulationError`
       on degenerate input).

    Sequencing:

    1. :meth:`tool.Surface.build_tin_from_points` — runs unconstrained
       Delaunay, returns a :class:`CivilSurface` with convex-hull boundary
       and zero flags.
    2. :meth:`tool.Surface.author_ifc_host` — persists as
       :class:`IfcGeographicElement[TERRAIN]` (existing) or
       :class:`IfcEarthworksFill[SUBGRADE]` (proposed_*) and stamps step
       ids onto the dataclass.
    3. :meth:`tool.Surface.register` — adds to the ``_registry`` cache
       under ``(id(ifc_file), guid)`` so subsequent :meth:`tool.Surface.get`
       calls hit the cache.

    Blender mesh creation is intentionally *not* part of this orchestration:
    it's a UI concern (operator level, commit 11 onward) and depends on a
    Bonsai-bootstrapped project / collection hierarchy that doesn't exist
    in headless contexts.

    :param ifc_tool: the :class:`tool.Ifc` class (injected, not instantiated).
    :param surface_tool: the :class:`tool.Surface` class.
    :param name: human-readable surface name (e.g., ``"Existing Ground"``).
    :param points: ``(N, 3)`` array of XYZ coordinates; numpy array or
        sequence of triples — the tool layer coerces.
    :param kind: surface kind per spec §2.2 / :class:`CivilSurface.kind`.
    :param triangulation_tolerance: forwarded to ``Pset_SaikeiGradingSurface``
        for downstream-tool quality reporting.
    :returns: the newly-built :class:`CivilSurface` (with all IFC step ids
        stamped).
    :raises ValueError: if no IFC file is loaded, name is empty, or kind is
        not in the allowed set.
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")

    if not name or not name.strip():
        raise ValueError("surface name cannot be empty")

    if kind not in _ALLOWED_KINDS:
        raise ValueError(
            f"kind must be one of {sorted(_ALLOWED_KINDS)}, got {kind!r}"
        )

    _warn_multi_site(ifc_file)

    surface = surface_tool.build_tin_from_points(
        name=name.strip(), points=points, kind=kind
    )
    surface_tool.author_ifc_host(
        ifc_file, surface, triangulation_tolerance=triangulation_tolerance
    )
    surface_tool.register(ifc_file, surface)
    return surface


def add_breakline_to_surface(
    ifc_tool: "type[tool.Ifc]",
    surface_tool: "type[tool.Surface]",
    surface_guid: str,
    breakline: Any,
    grading_group_guid: Optional[str] = None,
) -> Any:
    """Append a breakline to an existing surface and retriangulate.

    Business rules:

    1. An IFC file must be loaded.
    2. ``surface_guid`` must resolve to a registered or rehydrate-able surface.

    Sequencing:

    1. :meth:`tool.Surface.get` — fetch the surface from the registry
       (rehydrates from IFC if cache-missed).
    2. :meth:`tool.Surface.author_ifc_breakline` — persist as
       :class:`IfcAnnotation` with :class:`IfcPolyline` representation.
    3. Append to ``surface.breaklines`` so the next retriangulation honors it.
    4. :meth:`tool.Surface.retriangulate` — rebuild the constrained Delaunay
       with the new breakline as a forced edge (when it fully crosses the
       outer boundary; see ``_build_constrained_geometry`` docstring for the
       documented limitation).
    5. :meth:`tool.Surface.update_ifc_tin` — replace the host's existing
       Body TIN with the rebuilt one. Old TIN + CoordList are GC'd.

    Cache invalidation is intentionally deferred: the in-memory ``surface``
    instance was mutated in place (breakline appended, points / triangles /
    flags rebuilt by ``retriangulate``), and ``update_ifc_tin`` re-stamps
    ``surface.ifc_tin_representation_id`` to the new TIN's step id. A future
    phase will implement breakline rehydration from the ``IfcAnnotation``
    set; until then, calling :meth:`tool.Surface.invalidate` after this
    function would lose the breakline list on next :meth:`get`.

    :param ifc_tool: the :class:`tool.Ifc` class.
    :param surface_tool: the :class:`tool.Surface` class.
    :param surface_guid: GlobalId of the host surface entity.
    :param breakline: a :class:`Breakline` dataclass to attach.
    :param grading_group_guid: optional GUID linking the breakline to a
        grading group (forwarded to ``Pset_SaikeiBreaklineCommon``).
    :returns: the mutated :class:`CivilSurface`.
    :raises ValueError: if no IFC file is loaded.
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")

    _warn_multi_site(ifc_file)

    polyline = getattr(breakline, "polyline", None)
    if polyline is None or len(polyline) < 2:
        raise ValueError(
            f"breakline polyline must have ≥ 2 points; got "
            f"{0 if polyline is None else len(polyline)}"
        )

    surface = surface_tool.get(ifc_file, surface_guid)
    # Link the annotation to the host surface via IfcRelAssignsToProduct
    # so multi-surface files can disambiguate breakline ownership on
    # rehydration (per the cleanup-2 review). The link is defensive: if
    # the surface has no IFC host yet (test fixtures bypass author_ifc_host),
    # we skip the host-link and the breakline is recovered as
    # site-global.
    host_surface = None
    if surface.ifc_host_entity_id is not None:
        host_surface = ifc_file.by_id(surface.ifc_host_entity_id)
    surface_tool.author_ifc_breakline(
        ifc_file,
        breakline,
        grading_group_guid=grading_group_guid,
        host_surface=host_surface,
    )
    surface.breaklines.append(breakline)
    surface_tool.retriangulate(surface)
    surface_tool.update_ifc_tin(ifc_file, surface)
    return surface


def set_outer_boundary(
    ifc_tool: "type[tool.Ifc]",
    surface_tool: "type[tool.Surface]",
    surface_guid: str,
    boundary_polygon: Any,
) -> Any:
    """Replace a surface's outer-boundary polygon and retriangulate.

    Business rules:

    1. An IFC file must be loaded.
    2. ``surface_guid`` must resolve to a registered or rehydrate-able surface.
    3. ``boundary_polygon`` must be a :class:`shapely.Polygon` — the tool
       layer's :meth:`Triangulator.constrained` validates this and raises
       :class:`ValueError` on the wrong type. Core does not import shapely,
       so the type check is delegated downstream.

    Sequencing:

    1. :meth:`tool.Surface.get` — fetch from registry / rehydrate.
    2. Mutate ``surface.outer_boundary`` directly (caller-supplied authoring
       input per spec §5).
    3. :meth:`tool.Surface.retriangulate` — clip the constrained Delaunay
       to the new boundary; triangles outside are dropped, hole / void
       flags are recomputed.
    4. :meth:`tool.Surface.update_ifc_tin` — push the rebuilt TIN to IFC.

    Cache invalidation is deferred for the same reason as
    :func:`add_breakline_to_surface`.

    :returns: the mutated :class:`CivilSurface`.
    :raises ValueError: if no IFC file is loaded.
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")

    surface = surface_tool.get(ifc_file, surface_guid)
    surface.outer_boundary = boundary_polygon
    surface_tool.retriangulate(surface)
    surface_tool.update_ifc_tin(ifc_file, surface)
    return surface


def delete_surface(
    ifc_tool: "type[tool.Ifc]",
    surface_tool: "type[tool.Surface]",
    surface_guid: str,
) -> None:
    """Destroy a surface and all its associated IFC and Blender data.

    Business rules:

    1. An IFC file must be loaded.
    2. ``surface_guid`` must resolve to a supported surface host entity.

    Sequencing:

    1. :meth:`tool.Surface.delete` — removes the Blender object, the IFC
       host entity, all scoped breakline annotations, and the representation
       tree; evicts the registry entry.

    Cache invalidation: the tool layer evicts the registry entry so callers
    that hold a stale reference to the :class:`CivilSurface` dataclass get
    an error on next :meth:`tool.Surface.get` rather than operating on ghost
    data.

    :param ifc_tool: the :class:`tool.Ifc` class.
    :param surface_tool: the :class:`tool.Surface` class.
    :param surface_guid: GlobalId of the surface to destroy.
    :raises ValueError: if no IFC file is loaded.
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")

    surface_tool.delete(surface_guid)


def retriangulate_surface(
    ifc_tool: "type[tool.Ifc]",
    surface_tool: "type[tool.Surface]",
    surface_guid: str,
) -> Any:
    """Force rebuild the active surface's TIN without changing inputs.

    Useful when the surface's authoring polygons or breaklines were mutated
    out-of-band (e.g., a hole polygon was edited via the Properties panel
    without going through :func:`set_outer_boundary`). Rare in normal use —
    the edit-flow orchestrators (:func:`add_breakline_to_surface`,
    :func:`set_outer_boundary`) already retriangulate.

    :raises ValueError: if no IFC file is loaded.
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")

    surface = surface_tool.get(ifc_file, surface_guid)
    surface_tool.retriangulate(surface)
    surface_tool.update_ifc_tin(ifc_file, surface)
    return surface


def simplify_surface(
    ifc_tool: "type[tool.Ifc]",
    surface_tool: "type[tool.Surface]",
    surface_guid: str,
    tolerance: float,
) -> int:
    """Reduce the boundary vertex count of a surface by applying Douglas-Peucker.

    Business rules:
    1. An IFC file must be loaded.
    2. ``surface_guid`` must resolve to a supported surface host entity.

    Delegates all math to :meth:`tool.Surface.simplify`; returns the count of
    vertices removed (0 for a no-op).

    :raises ValueError: if no IFC file is loaded.
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")

    host = surface_tool.get_host_entity(ifc_file, surface_guid)
    if host is None:
        from bonsai.tool.surface import SaikeiSurfaceError

        raise SaikeiSurfaceError(
            f"no IFC entity with GlobalId {surface_guid!r} in this file"
        )

    return surface_tool.simplify(ifc_file, host.id(), tolerance)


def translate_surface_z(
    ifc_tool: "type[tool.Ifc]",
    surface_tool: "type[tool.Surface]",
    surface_guid: str,
    delta_z: float,
) -> None:
    """Uniformly shift all TIN vertices (and scoped breaklines) of a surface.

    Business rules:
    1. An IFC file must be loaded.
    2. ``surface_guid`` must resolve to a supported surface host entity.

    Delegates all math and IFC persistence to :meth:`tool.Surface.translate_z`.

    :raises ValueError: if no IFC file is loaded.
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")

    surface_tool.translate_z(ifc_file, surface_guid, delta_z)

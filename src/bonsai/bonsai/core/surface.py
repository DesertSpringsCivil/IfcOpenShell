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

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .. import tool


_ALLOWED_KINDS = {"existing", "proposed_group", "proposed_site"}


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
       SurfaceModel TIN with the rebuilt one. Old TIN + CoordList are GC'd.

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

    surface = surface_tool.get(ifc_file, surface_guid)
    surface_tool.author_ifc_breakline(
        ifc_file, breakline, grading_group_guid=grading_group_guid
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

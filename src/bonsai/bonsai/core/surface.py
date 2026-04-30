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

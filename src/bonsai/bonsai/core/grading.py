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

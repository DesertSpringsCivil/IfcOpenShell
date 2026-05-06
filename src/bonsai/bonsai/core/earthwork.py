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

"""Saikei earthwork core — orchestration only, NO bpy / numpy / shapely.

Phase 6 of the Saikei grading/earthwork sprint. This module owns the
business-rule layer for earthwork-volume computation and cut/fill
solid authoring: validates inputs, sequences calls into
:mod:`bonsai.tool.earthwork` (and :mod:`bonsai.tool.surface` for
existing/proposed surface lookups), and translates user intent into
the right tool method chain.

Per spec §4.7 (alignment-precedent), every function takes the tool
classes as explicit type-injected parameters (``ifc_tool``,
``surface_tool``, ``earthwork_tool``) so tests can substitute
test doubles without monkeypatching.

What lives here:

- Validation: file loaded, both surfaces resolved, shrink/swell factor
  ranges sane, surface kinds appropriate (existing → terrain,
  proposed → fill).
- Sequencing: volume math → cut/fill solid construction → IFC
  authoring → quantity-set authoring → shrink/swell pset.
- Decisions: should we author a cut entity for zero-cut scenarios?
  How does the swell factor multiply through to ``LooseVolume``?

What does NOT live here:

- Math (TIN-to-TIN prismoidal, region extraction, solid construction)
  — :mod:`bonsai.tool.earthwork`.
- IFC entity creation — :mod:`bonsai.tool.earthwork` delegating to
  :mod:`ifcopenshell.api.earthwork` (Phase 3).
- Blender object/mesh manipulation (``bpy``) —
  :mod:`bonsai.tool.earthwork`.

Public surface: :func:`compute_earthwork_volumes` validates inputs,
resolves both surfaces, runs the spec §6.4 prismoidal math via
:meth:`tool.Earthwork.compute_volumes`, then authors the result via
:meth:`tool.Earthwork.author_volume_result`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .. import tool  # noqa: F401


def compute_earthwork_volumes(
    ifc_tool: "type[tool.Ifc]",
    surface_tool: "type[tool.Surface]",
    earthwork_tool: "type[tool.Earthwork]",
    existing_surface_guid: str,
    proposed_surface_guid: str,
    shrink_factor: float = 1.0,
    swell_factor: float = 1.0,
    cut_name: str = "Earthwork Cut",
    fill_name: str = "Earthwork Fill",
    cut_predefined_type: str = "EXCAVATION",
    fill_predefined_type: str = "BACKFILL",
    capture_per_triangle_deltas: bool = False,
) -> Any:
    """Compute cut/fill volumes between two surfaces and persist to IFC.

    Business rules:

    1. An IFC file must be loaded.
    2. Both surfaces must resolve via :meth:`tool.Surface.get` — the
       caller is responsible for prior authoring.
    3. ``shrink_factor`` and ``swell_factor`` must be positive
       (the dataclass enforces this; we surface it as a clean
       :class:`ValueError` at the orchestration boundary).

    Sequencing:

    1. Resolve both surfaces.
    2. Look up the existing surface's IFC host entity (typically an
       :class:`IfcGeographicElement[TERRAIN]`) for void-relationship
       authoring.
    3. :meth:`tool.Earthwork.compute_volumes` with
       ``build_solids=True`` — runs §6.4 prismoidal volume math and
       builds prism-soup cut/fill solids.
    4. :meth:`tool.Earthwork.author_volume_result` — authors
       :class:`IfcEarthworksCut`, :class:`IfcEarthworksFill`,
       :class:`IfcRelVoidsElement`, :class:`IfcRelFillsElement`,
       both Qtos, and ``Pset_SaikeiGradingShrinkSwell``.

    :param ifc_tool: the :class:`tool.Ifc` class.
    :param surface_tool: the :class:`tool.Surface` class.
    :param earthwork_tool: the :class:`tool.Earthwork` class.
    :param existing_surface_guid: GUID of the existing-ground
        :class:`bonsai.tool.surface.CivilSurface`.
    :param proposed_surface_guid: GUID of the proposed-ground
        :class:`CivilSurface`. May be a Phase 5 group composite.
    :param shrink_factor: fill-side shrinkage ratio. Default 1.0.
    :param swell_factor: cut-side swell ratio. Default 1.0.
        ``LooseVolume = UndisturbedVolume × swell_factor``.
    :param cut_name / fill_name: human-readable IFC entity names.
    :param cut_predefined_type / fill_predefined_type: IFC enum
        values. See :meth:`tool.Earthwork.author_volume_result` for
        allowed sets.
    :param capture_per_triangle_deltas: when True, the result's
        ``per_triangle_deltas`` is populated for the optional
        cut/fill heat-map overlay.
    :returns: a :class:`bonsai.tool.earthwork.VolumeResult` with
        all fields stamped: cut/fill magnitudes, cut_solid /
        fill_solid geometry, ifc_cut_id / ifc_fill_id step ids.
    :raises ValueError: on input validation failures.
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")

    if shrink_factor <= 0:
        raise ValueError(
            f"shrink_factor must be > 0; got {shrink_factor}"
        )
    if swell_factor <= 0:
        raise ValueError(
            f"swell_factor must be > 0; got {swell_factor}"
        )

    existing_surface = surface_tool.get(ifc_file, existing_surface_guid)
    proposed_surface = surface_tool.get(ifc_file, proposed_surface_guid)

    terrain = _resolve_terrain_entity(ifc_file, existing_surface)

    result = earthwork_tool.compute_volumes(
        existing_surface,
        proposed_surface,
        shrink_factor=shrink_factor,
        swell_factor=swell_factor,
        capture_per_triangle_deltas=capture_per_triangle_deltas,
        build_solids=True,
    )

    # Pure no-op (zero cut + zero fill) — skip authoring entirely.
    # Authoring would still succeed but there's no IFC entity worth
    # creating, and downstream consumers shouldn't see a 0-volume
    # cut/fill in the project tree.
    if (
        result.cut_solid is None
        and result.fill_solid is None
    ):
        return result

    earthwork_tool.author_volume_result(
        ifc_file,
        result,
        terrain=terrain,
        cut_name=cut_name,
        fill_name=fill_name,
        cut_predefined_type=cut_predefined_type,
        fill_predefined_type=fill_predefined_type,
    )
    return result


def delete_earthwork_results(
    ifc_tool: "type[tool.Ifc]",
    earthwork_tool: "type[tool.Earthwork]",
    cut_guid: str,
    fill_guid: str,
) -> None:
    """Remove cut and fill volume-result entities from the IFC file.

    Orchestration only — delegates to
    :meth:`tool.Earthwork.delete_results` after verifying a file is
    loaded.  Callers (operators) pass the GUIDs captured at the last
    :func:`compute_earthwork_volumes` run; the operator is responsible
    for clearing any cached report fields on the PropertyGroup after
    this returns.

    :param ifc_tool: the :class:`tool.Ifc` class.
    :param earthwork_tool: the :class:`tool.Earthwork` class.
    :param cut_guid: ``GlobalId`` of the cut entity to remove.
    :param fill_guid: ``GlobalId`` of the fill entity to remove.
    :raises ValueError: if no IFC file is loaded.
    :raises tool.earthwork.SaikeiEarthworkError: if a GUID cannot be
        resolved (propagated from :meth:`tool.Earthwork.delete_results`).
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")
    earthwork_tool.delete_results(ifc_file, cut_guid=cut_guid, fill_guid=fill_guid)


def _resolve_terrain_entity(
    ifc_file: Any, existing_surface: Any
) -> Optional[Any]:
    """Return the IFC entity hosting ``existing_surface``, or None
    if it isn't yet authored to IFC.

    A pure-fill scenario doesn't need a terrain entity — the
    cut-side voiding chain isn't authored. A cut scenario without
    a host terrain raises in
    :meth:`tool.Earthwork.author_volume_result`.
    """
    host_id = getattr(existing_surface, "ifc_host_entity_id", None)
    if host_id is None:
        return None
    return ifc_file.by_id(host_id)

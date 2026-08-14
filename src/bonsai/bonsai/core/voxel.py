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

"""Saikei voxel core — orchestration only, NO bpy / numpy / IFC math.

Phase 5 of the Saikei grading/earthwork sprint (voxel pivot). This module owns
the business-rule layer for voxelizing surfaces into occupancy grids: validates
inputs, resolves the surface, and sequences calls into :mod:`bonsai.tool.voxel`
(lattice construction → height-function wiring → rasterization).

Per the alignment/surface precedent, every function takes the tool classes as
explicit type-injected parameters so tests can substitute Prophecy-tracked
stubs without monkeypatching.

What lives here: validation (file loaded, surface resolvable, params sane) and
sequencing. What does NOT: any numpy / lattice math / IFC authoring — all of
that is :mod:`bonsai.tool.voxel`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .. import tool


def voxelize_surface(
    ifc_tool: "type[tool.Ifc]",
    surface_tool: "type[tool.Surface]",
    voxel_tool: "type[tool.Voxel]",
    surface_guid: str,
    cell_size: Any,
    z_min: Optional[float] = None,
    z_max: Optional[float] = None,
    supersample: int = 1,
) -> Any:
    """Rasterize a registered surface into a soil-occupancy mask on a fresh lattice.

    Business rules:

    1. An IFC file must be loaded.
    2. ``surface_guid`` must resolve to a registered / rehydrate-able surface.
    3. ``cell_size`` must be positive (scalar or per-axis) and ``supersample``
       must be ``>= 1`` — both validated downstream by the tool layer, which
       raises :class:`ValueError` on bad input.

    Sequencing:

    1. :meth:`tool.Surface.get` — fetch the surface (rehydrates from IFC on
       cache miss).
    2. :meth:`tool.Voxel.grid_from_surface` — derive the lattice covering the
       surface's XY extent and the chosen Z range.
    3. :meth:`tool.Voxel.voxelize_surface` — the centre/supersample
       rasterization, wiring the surface's :meth:`~tool.Surface.z_at` internally.

    This produces a *derived* representation (spec §6): the TIN remains the
    parametric source of truth; the grid is computed from it for volumetrics.
    Cut/fill (Phase 4) voxelizes existing- and design-state surfaces onto a
    *shared* lattice — that path will build one :class:`~tool.voxel.GridDef`
    over both surfaces' bounds rather than per-surface grids here.

    :returns: ``(grid, mask)`` — the :class:`~tool.voxel.GridDef` and the bool
        occupancy mask (shape ``grid.counts``).
    :raises ValueError: if no IFC file is loaded.
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")

    surface = surface_tool.get(ifc_file, surface_guid)
    grid = voxel_tool.grid_from_surface(surface, cell_size, z_min=z_min, z_max=z_max)
    mask = voxel_tool.voxelize_surface(grid, surface, supersample=supersample)
    return grid, mask


def compute_cut_fill(
    ifc_tool: "type[tool.Ifc]",
    surface_tool: "type[tool.Surface]",
    voxel_tool: "type[tool.Voxel]",
    existing_guid: str,
    design_guid: str,
    cell_size: Any,
    z_min: Optional[float] = None,
    z_max: Optional[float] = None,
    supersample: int = 1,
) -> Any:
    """Compute cut / fill / net volumes between an existing- and a design-state surface.

    Business rules:

    1. An IFC file must be loaded.
    2. Both GUIDs must resolve to registered / rehydrate-able surfaces.

    Sequencing:

    1. :meth:`tool.Surface.get` ×2 — fetch existing + design surfaces.
    2. :meth:`tool.Voxel.shared_grid` — build the ONE lattice spanning both
       surfaces (the shared-lattice invariant, spec §5.1; differencing masks on
       mismatched lattices is meaningless).
    3. :meth:`tool.Voxel.voxelize_surface` ×2 — rasterize each state onto that
       shared grid.
    4. :meth:`tool.Voxel.cut_fill` — set-difference the masks into cut/fill/net
       volumes.

    Both masks share one grid by construction (both voxelized on it), so the
    cut/fill set-ops are well defined.

    :returns: ``(grid, result)`` where ``result`` is
        ``{"cut": ..., "fill": ..., "net": ...}`` (m³, bank/undisturbed volumes).
    :raises ValueError: if no IFC file is loaded.
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")

    existing = surface_tool.get(ifc_file, existing_guid)
    design = surface_tool.get(ifc_file, design_guid)
    grid = voxel_tool.shared_grid([existing, design], cell_size, z_min=z_min, z_max=z_max)
    existing_mask = voxel_tool.voxelize_surface(grid, existing, supersample=supersample)
    design_mask = voxel_tool.voxelize_surface(grid, design, supersample=supersample)
    result = voxel_tool.cut_fill(existing_mask, design_mask, grid)
    return grid, result


def author_cut_fill_sidecar(
    ifc_tool: "type[tool.Ifc]",
    surface_tool: "type[tool.Surface]",
    voxel_tool: "type[tool.Voxel]",
    existing_guid: str,
    design_guid: str,
    cell_size: Any,
    z_min: Optional[float] = None,
    z_max: Optional[float] = None,
    supersample: int = 1,
    swell_factor: float = 1.0,
) -> Any:
    """Generate a complete IFC 4.4 voxel earthwork sidecar from two surfaces.

    The end-to-end "produce the voxel deliverable" call — chains Phases 2–4 into
    one operation: voxelize existing + design onto a shared lattice, difference
    them into cut/fill, and author the result as ``IfcEarthworksCut`` /
    ``IfcEarthworksFill`` voxel grids with base quantities in a fresh sidecar.

    Business rules:

    1. An IFC file (the production model) must be loaded.
    2. Both GUIDs must resolve to registered / rehydrate-able surfaces.
    3. Only non-empty earthwork is authored: a cut element is created iff cut
       volume > 0, a fill element iff fill volume > 0 (an all-cut grading
       produces a cut element only).

    Sequencing: ``get``×2 → :meth:`tool.Voxel.shared_grid` →
    :meth:`tool.Voxel.voxelize_surface`×2 → :meth:`tool.Voxel.cut_fill_masks`
    (regions) + :meth:`tool.Voxel.cut_fill` (volumes) →
    :meth:`tool.Voxel.new_sidecar` → :meth:`tool.Voxel.author_earthwork` per
    non-empty region.

    The sidecar is returned in memory (the caller writes it to disk); each host
    records its production source surface GlobalId for cross-file linkage. The
    production model is not modified.

    :param swell_factor: bulking factor for the loose volume (loose = bank ×
        swell); default ``1.0`` (loose == bank).
    :returns: ``(sidecar_file, result)`` where ``result`` is the
        ``{"cut", "fill", "net"}`` volume summary.
    :raises ValueError: if no IFC file is loaded.
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")

    existing = surface_tool.get(ifc_file, existing_guid)
    design = surface_tool.get(ifc_file, design_guid)
    grid = voxel_tool.shared_grid([existing, design], cell_size, z_min=z_min, z_max=z_max)
    existing_mask = voxel_tool.voxelize_surface(grid, existing, supersample=supersample)
    design_mask = voxel_tool.voxelize_surface(grid, design, supersample=supersample)
    masks = voxel_tool.cut_fill_masks(existing_mask, design_mask)
    result = voxel_tool.cut_fill(existing_mask, design_mask, grid)

    sidecar = voxel_tool.new_sidecar()
    if result["cut"] > 0:
        voxel_tool.author_earthwork(
            sidecar, grid, masks["cut"],
            host_class="IfcEarthworksCut", predefined_type="EXCAVATION",
            name="Voxel Cut", bank_volume=result["cut"],
            source_surface_guid=existing_guid, swell_factor=swell_factor,
        )
    if result["fill"] > 0:
        voxel_tool.author_earthwork(
            sidecar, grid, masks["fill"],
            host_class="IfcEarthworksFill", predefined_type="EMBANKMENT",
            name="Voxel Fill", bank_volume=result["fill"],
            source_surface_guid=design_guid, swell_factor=swell_factor,
        )
    return sidecar, result


def preview_cut_fill(
    ifc_tool: "type[tool.Ifc]",
    surface_tool: "type[tool.Surface]",
    voxel_tool: "type[tool.Voxel]",
    existing_guid: str,
    design_guid: str,
    cell_size: Any,
    z_min: Optional[float] = None,
    z_max: Optional[float] = None,
    supersample: int = 1,
) -> Any:
    """Build a Blender cut/fill voxel preview and return the volume summary.

    Same compute path as :func:`compute_cut_fill`, plus a disposable Blender
    mesh (cut = red, fill = blue) for the viewport. Returns the
    ``{"cut", "fill", "net"}`` dict so the panel can show the numbers.

    :raises ValueError: if no IFC file is loaded.
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")

    existing = surface_tool.get(ifc_file, existing_guid)
    design = surface_tool.get(ifc_file, design_guid)
    grid = voxel_tool.shared_grid([existing, design], cell_size, z_min=z_min, z_max=z_max)
    existing_mask = voxel_tool.voxelize_surface(grid, existing, supersample=supersample)
    design_mask = voxel_tool.voxelize_surface(grid, design, supersample=supersample)
    masks = voxel_tool.cut_fill_masks(existing_mask, design_mask)
    result = voxel_tool.cut_fill(existing_mask, design_mask, grid)
    voxel_tool.create_preview_mesh(grid, masks)
    return result


def preview_surface_occupancy(
    ifc_tool: "type[tool.Ifc]",
    surface_tool: "type[tool.Surface]",
    voxel_tool: "type[tool.Voxel]",
    surface_guid: str,
    cell_size: Any,
    z_min: Optional[float] = None,
    z_max: Optional[float] = None,
    supersample: int = 1,
) -> Any:
    """Build a Blender occupancy preview of a single surface; return its volume.

    Voxelizes one surface (soil below it) and renders the occupancy as green
    voxels. Returns ``{"volume": ...}`` for the panel.

    :raises ValueError: if no IFC file is loaded.
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")

    surface = surface_tool.get(ifc_file, surface_guid)
    grid = voxel_tool.grid_from_surface(surface, cell_size, z_min=z_min, z_max=z_max)
    mask = voxel_tool.voxelize_surface(grid, surface, supersample=supersample)
    volume = voxel_tool.occupancy_volume(grid, mask)
    voxel_tool.create_preview_mesh(grid, {"occupancy": mask})
    return {"volume": volume}


def clear_preview(voxel_tool: "type[tool.Voxel]") -> Any:
    """Remove the Blender voxel preview objects."""
    return voxel_tool.clear_preview()


# --------------------------------------------------------------------------- #
# Stratum / geomodel (Phase 5)
# --------------------------------------------------------------------------- #


def _resolve_ordered_strata(ifc_tool, surface_tool, voxel_tool, surface_guids):
    """Shared prelude: resolve surfaces, order them top→bottom, build the legend.

    :returns: ``(ifc_file, ordered_surfaces, legend)``.
    :raises ValueError: if no IFC file is loaded or fewer than 2 surfaces given.
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")
    if len(surface_guids) < 2:
        raise ValueError("a geomodel needs at least 2 boundary surfaces")
    surfaces = [surface_tool.get(ifc_file, guid) for guid in surface_guids]
    ordered = voxel_tool.order_surfaces_by_elevation(surfaces)
    legend = voxel_tool.strata_legend(ordered)
    return ifc_file, ordered, legend


def compute_geomodel(
    ifc_tool: "type[tool.Ifc]",
    surface_tool: "type[tool.Surface]",
    voxel_tool: "type[tool.Voxel]",
    surface_guids: Any,
    cell_size: Any,
    z_min: Optional[float] = None,
    z_max: Optional[float] = None,
    supersample: int = 1,
) -> Any:
    """Classify a stratum geomodel from a stack of boundary surfaces.

    Resolves + elevation-orders the surfaces, builds the shared lattice over
    them, classifies each cell into a stratum code, and computes per-stratum
    volumes. No IFC authoring, no Blender mesh — for a panel readout.

    :returns: ``(grid, code_layer, volumes, legend)`` where ``volumes`` is
        ``{code: m³}`` and ``legend`` is ``{code: material_name}``.
    :raises ValueError: if no IFC file is loaded or fewer than 2 surfaces given.
    """
    _ifc, ordered, legend = _resolve_ordered_strata(ifc_tool, surface_tool, voxel_tool, surface_guids)
    grid = voxel_tool.shared_grid(ordered, cell_size, z_min=z_min, z_max=z_max)
    code_layer = voxel_tool.voxelize_strata(grid, ordered, supersample=supersample)
    volumes = voxel_tool.stratum_volumes(grid, code_layer)
    return grid, code_layer, volumes, legend


def preview_geomodel(
    ifc_tool: "type[tool.Ifc]",
    surface_tool: "type[tool.Surface]",
    voxel_tool: "type[tool.Voxel]",
    surface_guids: Any,
    cell_size: Any,
    z_min: Optional[float] = None,
    z_max: Optional[float] = None,
    supersample: int = 1,
) -> Any:
    """Build a stratum-colored Blender preview; return volumes + legend.

    :returns: ``{"volumes": {code: m³}, "legend": {code: name}}``.
    :raises ValueError: if no IFC file is loaded or fewer than 2 surfaces given.
    """
    _ifc, ordered, legend = _resolve_ordered_strata(ifc_tool, surface_tool, voxel_tool, surface_guids)
    grid = voxel_tool.shared_grid(ordered, cell_size, z_min=z_min, z_max=z_max)
    code_layer = voxel_tool.voxelize_strata(grid, ordered, supersample=supersample)
    volumes = voxel_tool.stratum_volumes(grid, code_layer)
    voxel_tool.create_strata_preview(grid, code_layer, legend)
    return {"volumes": volumes, "legend": legend}


def author_geomodel_sidecar(
    ifc_tool: "type[tool.Ifc]",
    surface_tool: "type[tool.Surface]",
    voxel_tool: "type[tool.Voxel]",
    surface_guids: Any,
    cell_size: Any,
    z_min: Optional[float] = None,
    z_max: Optional[float] = None,
    supersample: int = 1,
    name: str = "Voxel Geomodel",
) -> Any:
    """Author an IFC 4.4 ``IfcGeomodel`` voxel sidecar from a stack of surfaces.

    Classifies the strata, then authors an occupancy grid + an integer-coded
    RLE ``StratumCode`` layer (+ code→material legend) into a fresh sidecar.

    :returns: ``(sidecar_file, volumes, legend)``.
    :raises ValueError: if no IFC file is loaded or fewer than 2 surfaces given.
    """
    _ifc, ordered, legend = _resolve_ordered_strata(ifc_tool, surface_tool, voxel_tool, surface_guids)
    grid = voxel_tool.shared_grid(ordered, cell_size, z_min=z_min, z_max=z_max)
    code_layer = voxel_tool.voxelize_strata(grid, ordered, supersample=supersample)
    volumes = voxel_tool.stratum_volumes(grid, code_layer)
    sidecar = voxel_tool.new_sidecar()
    voxel_tool.author_geomodel(
        sidecar, grid, code_layer, legend, name=name, source_surface_guids=list(surface_guids)
    )
    return sidecar, volumes, legend


# --------------------------------------------------------------------------- #
# Per-stratum cut/fill — excavation quantities by material
# --------------------------------------------------------------------------- #


def _cut_fill_strata_prelude(
    ifc_tool, surface_tool, voxel_tool,
    existing_guid, design_guid, stratum_guids, cell_size, z_min, z_max, supersample,
):
    """Shared compute for per-stratum cut/fill.

    Builds ONE lattice spanning the earthwork surfaces (existing, design) AND the
    stratum boundaries, voxelizes everything onto it, and intersects the cut
    region with the stratum classification — the shared-lattice invariant (spec
    §5.1) is what makes cut ∩ stratum well defined.

    :returns: ``(grid, masks, code_layer, totals, cut_by_stratum, legend)``.
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")
    if len(stratum_guids) < 2:
        raise ValueError("per-stratum cut needs at least 2 stratum boundary surfaces")

    existing = surface_tool.get(ifc_file, existing_guid)
    design = surface_tool.get(ifc_file, design_guid)
    strata = [surface_tool.get(ifc_file, guid) for guid in stratum_guids]
    ordered = voxel_tool.order_surfaces_by_elevation(strata)
    legend = voxel_tool.strata_legend(ordered)

    grid = voxel_tool.shared_grid(
        [existing, design] + ordered, cell_size, z_min=z_min, z_max=z_max
    )
    existing_mask = voxel_tool.voxelize_surface(grid, existing, supersample=supersample)
    design_mask = voxel_tool.voxelize_surface(grid, design, supersample=supersample)
    masks = voxel_tool.cut_fill_masks(existing_mask, design_mask)
    code_layer = voxel_tool.voxelize_strata(grid, ordered, supersample=supersample)
    totals = voxel_tool.cut_fill(existing_mask, design_mask, grid)
    cut_by_stratum = voxel_tool.cut_fill_by_stratum(masks["cut"], code_layer, grid)
    return grid, masks, code_layer, totals, cut_by_stratum, legend


def compute_cut_fill_by_stratum(
    ifc_tool: "type[tool.Ifc]",
    surface_tool: "type[tool.Surface]",
    voxel_tool: "type[tool.Voxel]",
    existing_guid: str,
    design_guid: str,
    stratum_guids: Any,
    cell_size: Any,
    z_min: Optional[float] = None,
    z_max: Optional[float] = None,
    supersample: int = 1,
) -> Any:
    """Excavation volumes split by native stratum (no Blender mesh).

    :returns: ``(grid, totals, cut_by_stratum, legend)`` where ``totals`` is the
        overall ``{"cut", "fill", "net"}`` and ``cut_by_stratum`` is
        ``{stratum_code: excavated_m³}``.
    :raises ValueError: if no IFC file is loaded or < 2 stratum surfaces.
    """
    grid, _masks, _code, totals, cut_by_stratum, legend = _cut_fill_strata_prelude(
        ifc_tool, surface_tool, voxel_tool,
        existing_guid, design_guid, stratum_guids, cell_size, z_min, z_max, supersample,
    )
    return grid, totals, cut_by_stratum, legend


def preview_cut_fill_by_stratum(
    ifc_tool: "type[tool.Ifc]",
    surface_tool: "type[tool.Surface]",
    voxel_tool: "type[tool.Voxel]",
    existing_guid: str,
    design_guid: str,
    stratum_guids: Any,
    cell_size: Any,
    z_min: Optional[float] = None,
    z_max: Optional[float] = None,
    supersample: int = 1,
) -> Any:
    """Build a Blender preview of the cut region colored by native stratum, and
    return the per-material excavation volumes.

    :returns: ``{"totals": {...}, "cut_by_stratum": {code: m³}, "legend": {code: name}}``.
    :raises ValueError: if no IFC file is loaded or < 2 stratum surfaces.
    """
    grid, masks, code_layer, totals, cut_by_stratum, legend = _cut_fill_strata_prelude(
        ifc_tool, surface_tool, voxel_tool,
        existing_guid, design_guid, stratum_guids, cell_size, z_min, z_max, supersample,
    )
    cut_codes = voxel_tool.intersect_codes(code_layer, masks["cut"])
    voxel_tool.create_strata_preview(grid, cut_codes, legend)
    return {"totals": totals, "cut_by_stratum": cut_by_stratum, "legend": legend}

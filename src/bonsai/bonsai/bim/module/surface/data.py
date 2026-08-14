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

"""Data caching for the Saikei surface module's UI panel.

Mirrors :mod:`bonsai.bim.module.alignment.data`: the panel reads from
:class:`SurfaceData.data` rather than re-querying IFC every redraw. Bonsai's
:func:`bonsai.bim.handler.refresh_ui_data` calls :func:`refresh` (auto-
discovered via the ``modules`` dict) on every IFC mutation, which marks
``SurfaceData.is_loaded = False`` so the next panel ``draw()`` calls
:meth:`load`.
"""

import bpy

import bonsai.tool as tool


class SurfaceData:
    """Cached surface data for the panel."""

    data: dict = {}
    is_loaded: bool = False

    @classmethod
    def load(cls) -> None:
        """Refresh :attr:`data` from the active IFC file.

        Also re-syncs ``CivilSurfaceProperties.surfaces`` (the UIList
        backing collection) from the IFC entity tree. Without this sync,
        opening a file that already contains surfaces shows an empty
        UIList — only surfaces created in the *current* session would
        appear.
        """
        cls.data = {
            "surface_count": 0,
            "active_surface_summary": None,
        }

        ifc_file = tool.Ifc.get()
        if ifc_file is None:
            cls.is_loaded = True
            return

        # Existing terrains and proposed-fill surfaces.
        terrains = ifc_file.by_type("IfcGeographicElement")
        terrains = [t for t in terrains if t.PredefinedType == "TERRAIN"]
        fills = ifc_file.by_type("IfcEarthworksFill")
        fills = [f for f in fills if f.PredefinedType == "SUBGRADE"]
        cls.data["surface_count"] = len(terrains) + len(fills)

        # NOTE: the UIList sync (which writes CivilSurfaceProperties) is NOT
        # done here. load() runs during panel draw(), where Blender forbids
        # writing scene properties. The list is synced in sync_uilists(),
        # invoked from refresh() — on IFC mutations / file load, outside draw.
        cls.is_loaded = True

    @classmethod
    def sync_uilists(cls) -> None:
        """Reconcile ``CivilSurfaceProperties.surfaces`` with the current IFC.

        Writes scene properties, so it MUST run outside panel ``draw()``.
        Called from :func:`refresh`, never from :meth:`load`.
        """
        ifc_file = tool.Ifc.get()
        if ifc_file is None:
            return
        terrains = [t for t in ifc_file.by_type("IfcGeographicElement") if t.PredefinedType == "TERRAIN"]
        fills = [f for f in ifc_file.by_type("IfcEarthworksFill") if f.PredefinedType == "SUBGRADE"]
        cls._sync_uilist_from_ifc(terrains, fills)

    @staticmethod
    def _sync_uilist_from_ifc(
        terrains: list, fills: list
    ) -> None:
        """Reconcile ``CivilSurfaceProperties.surfaces`` with the IFC
        entity set.

        Idempotent: clears the collection and rebuilds from the IFC tree.
        Preserves ``active_surface_index`` if the previously-selected GUID
        is still present in the file; otherwise resets to 0.

        The :attr:`active_surface_id` and :attr:`active_surface_guid`
        scratchpad are restored *after* the rebuild so the
        ``_on_active_surface_index_change`` callback firing mid-rebuild
        (against an intermediate empty / partial collection) doesn't
        leave the panel pointing at stale state. We snapshot the GUID
        before clearing, then restore both the index AND the
        id/guid scratchpad explicitly at the end.
        """
        scene = bpy.context.scene if bpy.context else None
        if scene is None or not hasattr(scene, "CivilSurfaceProperties"):
            return
        props = scene.CivilSurfaceProperties

        previous_guid = props.active_surface_guid

        props.surfaces.clear()
        for entity in terrains:
            item = props.surfaces.add()
            item.name = entity.Name or ""
            item.guid = entity.GlobalId
            item.ifc_id = entity.id()
            item.kind = "existing"
        for entity in fills:
            item = props.surfaces.add()
            item.name = entity.Name or ""
            item.guid = entity.GlobalId
            item.ifc_id = entity.id()
            # Disambiguation between proposed_group / proposed_site via
            # spatial-parent inspection. Phase 4 files (no IfcGroup yet)
            # always classify as proposed_site; Phase 5 files with grading
            # groups classify proposed_group correctly without code change.
            item.kind = tool.Surface.infer_kind_from_spatial_parent(entity)

        # Find the index for the previously-selected GUID, defaulting to 0.
        target_index = 0
        for index, item in enumerate(props.surfaces):
            if item.guid == previous_guid:
                target_index = index
                break

        # Set the index (this fires the update callback once, against the
        # fully-built collection — safe).
        props.active_surface_index = target_index

        # Belt-and-braces: explicitly restore the id/guid scratchpad in
        # case the callback short-circuited (e.g., index was already
        # target_index and Blender skipped the update event).
        if 0 <= target_index < len(props.surfaces):
            current = props.surfaces[target_index]
            props.active_surface_id = current.ifc_id
            props.active_surface_guid = current.guid
        else:
            props.active_surface_id = 0
            props.active_surface_guid = ""

    @classmethod
    def active_surface_summary(
        cls, ifc_file, surface_guid: str
    ) -> dict:
        """Return a dict summarizing the active surface for the panel.

        Goes through :meth:`tool.Surface.get` (which lazy-rehydrates from
        the registry) so the values stay consistent with the in-memory
        dataclass. Called only when an active surface is selected — the
        panel polls ``CivilSurfaceProperties.active_surface_guid``.
        """
        try:
            surface = tool.Surface.get(ifc_file, surface_guid)
        except Exception:
            return {
                "name": "(missing)",
                "kind": "",
                "vertex_count": 0,
                "triangle_count": 0,
                "breakline_count": 0,
                "has_boundary": False,
            }
        return {
            "name": surface.name,
            "kind": surface.kind,
            "vertex_count": int(len(surface.points)),
            "triangle_count": int(len(surface.triangles)),
            "breakline_count": len(surface.breaklines),
            "has_boundary": surface.outer_boundary is not None,
        }

    @classmethod
    def get_active_surface_statistics(
        cls, ifc_file, surface_guid: str
    ) -> dict:
        """Return extended read-only statistics for the statistics sub-panel.

        Computes Z-min, Z-max, vertex count, triangle count, breakline count,
        and bounding-box footprint (XY width x depth) from the in-memory
        :class:`CivilSurface` dataclass. Returns a dict with sentinel values
        when the surface cannot be resolved (safe for the panel to read without
        guarding).

        The :class:`CIVIL_PT_surface_statistics` panel calls this during
        ``draw()``; caching is handled by the dataclass registry so repeated
        redraws do not re-read IFC.
        """
        _empty: dict = {
            "name": "(missing)",
            "vertex_count": 0,
            "triangle_count": 0,
            "breakline_count": 0,
            "z_min": 0.0,
            "z_max": 0.0,
            "bb_width": 0.0,
            "bb_depth": 0.0,
        }
        if not surface_guid:
            return _empty
        try:
            import numpy as np

            surface = tool.Surface.get(ifc_file, surface_guid)
        except Exception:
            return _empty

        points = surface.points  # (N, 3) numpy array
        if len(points) == 0:
            return _empty

        z_min = float(points[:, 2].min())
        z_max = float(points[:, 2].max())
        x_min = float(points[:, 0].min())
        x_max = float(points[:, 0].max())
        y_min = float(points[:, 1].min())
        y_max = float(points[:, 1].max())

        return {
            "name": surface.name,
            "vertex_count": int(len(points)),
            "triangle_count": int(len(surface.triangles)),
            "breakline_count": len(surface.breaklines),
            "z_min": z_min,
            "z_max": z_max,
            "bb_width": x_max - x_min,
            "bb_depth": y_max - y_min,
        }


def refresh() -> None:
    """Mark :class:`SurfaceData` as needing reload on next access.
    Called by Bonsai's UI refresh hook after IFC mutations.

    NOTE: the UIList sync (:meth:`SurfaceData.sync_uilists`) is NOT done here —
    it writes scene properties and would clobber the operators' own in-session
    list management on every mutation. The list is populated by the surface
    operators during a session and re-synced from IFC once on file load via
    the module's load_post handler.
    """
    SurfaceData.is_loaded = False

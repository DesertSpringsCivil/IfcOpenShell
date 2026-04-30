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

        cls._sync_uilist_from_ifc(terrains, fills)

        cls.is_loaded = True

    @staticmethod
    def _sync_uilist_from_ifc(
        terrains: list, fills: list
    ) -> None:
        """Reconcile ``CivilSurfaceProperties.surfaces`` with the IFC
        entity set.

        Idempotent: clears the collection and rebuilds from the IFC tree.
        Preserves ``active_surface_index`` if the previously-selected GUID
        is still present in the file; otherwise resets to 0.
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
            # Disambiguation between proposed_group / proposed_site
            # happens in tool.Surface.infer_kind_from_spatial_parent;
            # the UIList just shows the icon for "proposed of some kind."
            item.kind = "proposed_group"

        # Restore the previous selection if its GUID is still in the list.
        for index, item in enumerate(props.surfaces):
            if item.guid == previous_guid:
                props.active_surface_index = index
                break
        else:
            props.active_surface_index = 0 if len(props.surfaces) else 0

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


def refresh() -> None:
    """Mark :class:`SurfaceData` as needing reload on next access.

    Called by Bonsai's UI refresh hook after IFC mutations.
    """
    SurfaceData.is_loaded = False

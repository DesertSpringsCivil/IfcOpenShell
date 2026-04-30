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
:func:`bonsai.bim.handler.refresh_ui_data` clears the ``is_loaded`` flag on
each IFC mutation, forcing the next panel ``draw()`` to call :meth:`load`.
"""

import bonsai.tool as tool


class SurfaceData:
    """Cached surface data for the panel."""

    data: dict = {}
    is_loaded: bool = False

    @classmethod
    def load(cls) -> None:
        """Refresh :attr:`data` from the active IFC file."""
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

        cls.is_loaded = True

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

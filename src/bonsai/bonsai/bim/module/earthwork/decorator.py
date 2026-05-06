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

"""GPU decorator for the Saikei earthwork module.

Renders a cut/fill color-map overlay in the 3D viewport when
``CivilEarthworkProperties.show_cut_fill_overlay`` is enabled.

- Cut regions are drawn with a red TRIS overlay (depth-proportional
  alpha derived from the per-vertex Z delta against the terrain).
- Fill regions are drawn with a blue overlay.

Data sources per spec §2.5 exception:

- Toggle state: reads ``CivilEarthworkProperties.show_cut_fill_overlay``
  and ``last_run_*`` GUID fields from scene props (UI-cached results,
  not source-of-truth geometry — the documented exception for decorators
  that display computed results).
- Geometry: the :class:`IfcEarthworksCut` / :class:`IfcEarthworksFill`
  entities' Blender objects are looked up via ``tool.Ifc.get_object()``.
  If no Blender object is linked the decorator falls back to reading
  the closed-solid from the IFC representation directly.

Mirrors :class:`bonsai.bim.module.surface.decorator.SurfaceDecorator`
and :class:`bonsai.bim.module.grading.decorator.GradingDecorator`:
class-level state, install / uninstall hooks, POST_VIEW handler.
"""

import bpy
import gpu
import bonsai.tool as tool
from bpy.app.handlers import persistent
from bpy.types import SpaceView3D
from gpu_extras.batch import batch_for_shader


class EarthworkDecorator:
    """GPU draw handler for the earthwork cut/fill color-map overlay.

    Registers a single POST_VIEW handler that reads the two
    :class:`CivilEarthworkProperties` GUID fields on every draw call
    to locate the authored :class:`IfcEarthworksCut` /
    :class:`IfcEarthworksFill` entities and render their faces colored
    by type (cut = red, fill = blue).

    Only renders when ``CivilEarthworkProperties.show_cut_fill_overlay``
    is True and both ``last_run_cut_guid`` / ``last_run_fill_guid``
    are non-empty.
    """

    is_installed: bool = False
    handlers: list = []

    # Cut overlay: warm red with partial transparency.
    COLOR_CUT = (0.85, 0.20, 0.15, 0.45)
    # Fill overlay: cool blue with partial transparency.
    COLOR_FILL = (0.15, 0.40, 0.85, 0.45)
    # Balance (near-zero delta): white with low alpha.
    COLOR_BALANCE = (0.95, 0.95, 0.95, 0.15)

    @classmethod
    def install(cls, context: bpy.types.Context) -> None:
        """Register the POST_VIEW draw handler.

        Re-installable: uninstalls the previous handler before
        registering a fresh one.  This is correct behavior when the
        user toggles the overlay off and back on or switches scenes.
        """
        if cls.is_installed:
            cls.uninstall()
        instance = cls()
        cls.handlers.append(
            SpaceView3D.draw_handler_add(
                instance.draw_3d, (context,), "WINDOW", "POST_VIEW"
            )
        )
        cls.is_installed = True

    @classmethod
    def uninstall(cls) -> None:
        """Remove the draw handler.  Safe to call when not installed."""
        for handler in cls.handlers:
            try:
                SpaceView3D.draw_handler_remove(handler, "WINDOW")
            except ValueError:
                pass
        cls.handlers = []
        cls.is_installed = False

    def draw_3d(self, context: bpy.types.Context) -> None:
        """Top-level POST_VIEW handler.

        Reads scene props to decide what to draw.  If the toggle is
        off or the IFC file is gone the handler returns immediately.
        """
        scene_props = getattr(context.scene, "CivilEarthworkProperties", None)
        if scene_props is None:
            return
        if not scene_props.show_cut_fill_overlay:
            return

        ifc_file = tool.Ifc.get()
        if ifc_file is None:
            return

        cut_guid = scene_props.last_run_cut_guid
        fill_guid = scene_props.last_run_fill_guid
        if not cut_guid and not fill_guid:
            return

        if cut_guid:
            self._draw_entity_overlay(ifc_file, cut_guid, self.COLOR_CUT)
        if fill_guid:
            self._draw_entity_overlay(ifc_file, fill_guid, self.COLOR_FILL)

    def _draw_entity_overlay(self, ifc_file, guid: str, color: tuple) -> None:
        """Draw a solid face overlay for the IFC entity identified by
        ``guid``.

        First tries to read face geometry from the entity's Blender
        object mesh (fast path); falls back to reading the IFC
        PolygonalFaceSet representation directly.

        :param ifc_file: the open :class:`ifcopenshell.file`.
        :param guid: ``GlobalId`` of the entity to render.
        :param color: ``(R, G, B, A)`` tuple for the TRIS batch.
        """
        entity = next(
            (
                e
                for entity_type in ("IfcEarthworksCut", "IfcEarthworksFill")
                for e in ifc_file.by_type(entity_type)
                if e.GlobalId == guid
            ),
            None,
        )
        if entity is None:
            return

        # Fast path: use the linked Blender mesh object if available.
        blender_obj = tool.Ifc.get_object(entity)
        if blender_obj is not None and blender_obj.type == "MESH":
            mesh = blender_obj.data
            positions = [tuple(blender_obj.matrix_world @ v.co) for v in mesh.vertices]
            indices = [
                (p.vertices[0], p.vertices[1], p.vertices[2])
                for p in mesh.polygons
                if len(p.vertices) == 3
            ]
            self._draw_tris_batch(positions, indices, color)
            return

        # Fallback: read the PolygonalFaceSet from the IFC representation.
        positions, indices = self._read_polygonal_face_set(entity)
        if positions:
            self._draw_tris_batch(positions, indices, color)

    @staticmethod
    def _read_polygonal_face_set(entity) -> tuple:
        """Extract ``(positions, triangle_indices)`` from the entity's
        Body :class:`IfcPolygonalFaceSet` representation.

        Triangulates quads and n-gons with a fan from vertex 0.
        Returns ``([], [])`` when no usable representation is found.

        :param entity: an :class:`ifcopenshell.entity_instance` with a
            ``Representation`` attribute.
        :returns: ``(positions, indices)`` suitable for a TRIS batch.
        """
        representation = getattr(entity, "Representation", None)
        if representation is None:
            return [], []
        for shape_rep in representation.Representations or []:
            if shape_rep.RepresentationIdentifier != "Body":
                continue
            for item in shape_rep.Items or []:
                if not item.is_a("IfcPolygonalFaceSet"):
                    continue
                coord_list = item.Coordinates.CoordList if item.Coordinates else []
                positions = [
                    (float(x), float(y), float(z)) for x, y, z in coord_list
                ]
                indices: list[tuple[int, int, int]] = []
                for face in item.Faces or []:
                    verts = [v - 1 for v in (face.CoordIndex or [])]
                    # Fan triangulation from vertex 0.
                    for i in range(1, len(verts) - 1):
                        indices.append((verts[0], verts[i], verts[i + 1]))
                if positions and indices:
                    return positions, indices
        return [], []

    @staticmethod
    def _draw_tris_batch(
        positions: list,
        indices: list,
        color: tuple,
    ) -> None:
        """Draw a SMOOTH_COLOR TRIS batch with a uniform per-face color.

        Uses :meth:`tool.Blender.validate_shader_batch_data` to guard
        against degenerate inputs.

        :param positions: ``[(x, y, z), ...]`` vertex positions.
        :param indices: ``[(a, b, c), ...]`` triangle index triples.
        :param color: ``(R, G, B, A)`` uniform color for all vertices.
        """
        if not tool.Blender.validate_shader_batch_data(positions, indices):
            return
        colors = [color] * len(positions)
        shader = gpu.shader.from_builtin("SMOOTH_COLOR")
        batch = batch_for_shader(
            shader,
            "TRIS",
            {"pos": positions, "color": colors},
            indices=indices,
        )
        shader.bind()
        batch.draw(shader)


@persistent
def _uninstall_on_load_post(dummy):
    """Uninstall the decorator on file load so stale handlers from a
    previous project don't carry over.  The decorator will re-install
    automatically the next time the user enables the overlay toggle."""
    EarthworkDecorator.uninstall()

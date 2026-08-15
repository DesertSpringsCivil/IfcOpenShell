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

"""GPU decorator for the Saikei grading module.

One class, two draw methods:

1. :meth:`draw_feature_lines_3d` — every authored feature line
   (:class:`IfcAlignment` with ``SaikeiCivil_FeatureLineCommon``)
   rendered as a yellow polyline. Toggled by
   ``CivilGradingProperties.show_feature_lines``.
2. :meth:`draw_daylight_lines_3d` — every cached
   :class:`tool.grading.GradingObject`'s daylight tie-out polyline
   rendered as an orange polyline. Toggled by
   ``CivilGradingProperties.show_daylight_lines``.

Mirrors :class:`bonsai.bim.module.surface.decorator.SurfaceDecorator`:
class-level state, install / uninstall hooks called from PropertyGroup
``update=`` callbacks (``_on_decorator_toggle_change`` in
:mod:`prop`).

Daylight-line rendering reads from the in-memory
:attr:`tool.grading.Grading._registry` — freshly-authored grading
objects appear as soon as ``core.grading.add_grading_object`` returns
(it calls :meth:`tool.Grading.register` on the new
:class:`GradingObject`). Grading objects loaded from disk do NOT
appear: the ribbon geometry is persisted as the slope-fill's
representation, but the daylight line itself is the ribbon's outer
edge and is not currently derived on read. IFC-side rehydration of
``daylight_line`` is a Phase 5.1 follow-up.
"""

import bpy
import gpu
import bonsai.tool as tool
from bpy.types import SpaceView3D
from gpu_extras.batch import batch_for_shader


class GradingDecorator:
    """GPU draw handler for grading-module visualization.

    Registers a POST_VIEW handler that reads the two
    :class:`CivilGradingProperties` toggles each draw call. A single
    install persists across both toggles being on/off without
    re-installing.
    """

    is_installed: bool = False
    handlers: list = []

    COLOR_FEATURE_LINE = (1.00, 0.85, 0.20, 0.95)
    COLOR_DAYLIGHT_LINE = (0.95, 0.55, 0.15, 0.95)
    LINE_WIDTH = 2.0

    @classmethod
    def install(cls, context: bpy.types.Context) -> None:
        """Register the POST_VIEW draw handler.

        If a handler is already installed, it is removed before the new
        one is registered against ``context``. This is the right
        behavior when the user toggles the decorator off and back on,
        or switches scenes — the new context captures the new
        viewport's state.
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
        """Remove the draw handler. Safe to call when not installed."""
        for handler in cls.handlers:
            try:
                SpaceView3D.draw_handler_remove(handler, "WINDOW")
            except ValueError:
                pass
        cls.handlers = []
        cls.is_installed = False

    def draw_3d(self, context: bpy.types.Context) -> None:
        """Top-level POST_VIEW handler. Dispatches to per-method draws
        based on the current property toggles."""
        scene_props = getattr(context.scene, "CivilGradingProperties", None)
        if scene_props is None:
            return
        if not scene_props.show_feature_lines and not scene_props.show_daylight_lines:
            return

        ifc_file = tool.Ifc.get()
        if ifc_file is None:
            return

        if scene_props.show_feature_lines:
            self.draw_feature_lines_3d(ifc_file)
        if scene_props.show_daylight_lines:
            self.draw_daylight_lines_3d(ifc_file)

    def draw_feature_lines_3d(self, ifc_file) -> None:
        """Render every authored feature line as a polyline."""
        positions, indices = self._collect_feature_line_segments(ifc_file)
        self._draw_polyline_batch(positions, indices, self.COLOR_FEATURE_LINE)

    def draw_daylight_lines_3d(self, ifc_file) -> None:
        """Render every in-memory grading object's daylight line."""
        positions, indices = self._collect_daylight_line_segments(ifc_file)
        self._draw_polyline_batch(positions, indices, self.COLOR_DAYLIGHT_LINE)

    @staticmethod
    def _collect_feature_line_segments(ifc_file):
        """Build ``(positions, line_indices)`` from every IfcAlignment
        carrying ``SaikeiCivil_FeatureLineCommon``."""
        positions: list[tuple[float, float, float]] = []
        indices: list[tuple[int, int]] = []
        for alignment in ifc_file.by_type("IfcAlignment"):
            if not tool.Grading.is_feature_line_alignment(alignment):
                continue
            try:
                feature_line = tool.Grading.get_feature_line(
                    ifc_file, alignment.GlobalId
                )
            except Exception:
                continue
            vertices = list(feature_line.vertices)
            if len(vertices) < 2:
                continue
            base = len(positions)
            positions.extend(tuple(map(float, v)) for v in vertices)
            for i in range(len(vertices) - 1):
                indices.append((base + i, base + i + 1))
            if feature_line.closed:
                indices.append((base + len(vertices) - 1, base))
        return positions, indices

    @staticmethod
    def _collect_daylight_line_segments(ifc_file):
        """Build ``(positions, line_indices)`` from every cached
        :class:`tool.grading.GradingObject`'s ``daylight_line``.

        Only entities present in the in-memory registry contribute.
        ``core.grading.add_grading_object`` registers the new object
        after authoring, so in-session daylight lines render
        immediately. Disk-loaded grading objects await Phase 5.1's
        IFC-side daylight rehydration.
        """
        from bonsai.tool.grading import GradingObject

        positions: list[tuple[float, float, float]] = []
        indices: list[tuple[int, int]] = []
        for entry in tool.Grading.iter_registered(ifc_file, GradingObject):
            daylight = list(entry.daylight_line)
            if len(daylight) < 2:
                continue
            base = len(positions)
            positions.extend(tuple(map(float, p)) for p in daylight)
            for i in range(len(daylight) - 1):
                indices.append((base + i, base + i + 1))
            footprint = entry.footprint
            if footprint is not None and footprint.closed:
                indices.append((base + len(daylight) - 1, base))
        return positions, indices

    def _draw_polyline_batch(
        self,
        positions: list[tuple[float, float, float]],
        indices: list[tuple[int, int]],
        color: tuple[float, float, float, float],
    ) -> None:
        """Single-shader batch draw via ``POLYLINE_UNIFORM_COLOR``."""
        if not tool.Blender.validate_shader_batch_data(positions, indices):
            return
        shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
        shader.bind()
        region = bpy.context.region
        viewport_size = (
            (region.width, region.height) if region is not None else (1920, 1080)
        )
        shader.uniform_float("viewportSize", viewport_size)
        shader.uniform_float("lineWidth", self.LINE_WIDTH)
        batch = batch_for_shader(
            shader, "LINES", {"pos": positions}, indices=indices
        )
        shader.uniform_float("color", color)
        batch.draw(shader)

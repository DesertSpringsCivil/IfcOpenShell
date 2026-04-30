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

"""GPU decorator for the Saikei surface module.

One class, two draw methods per the Phase 4 handoff:

1. :meth:`draw_triangles_3d` — ``POLYLINE_UNIFORM_COLOR`` shader, edges as
   line indices. Toggled by ``CivilSurfaceProperties.show_triangles``.
2. :meth:`draw_elevation_banding_3d` — ``SMOOTH_COLOR`` shader, per-vertex
   colors precomputed from Z + a ramp, drawn as TRIS. Toggled by
   ``CivilSurfaceProperties.show_elevation_banding``.

Phase 4.1 will add ``draw_contours_3d`` and ``draw_slope_vectors_3d`` as
additional methods on the same class.

Mirrors the alignment-precedent in
:mod:`bonsai.bim.module.alignment.decorator`: class-level state, install /
uninstall hooks called from PropertyGroup ``update=`` callbacks.
"""

import bpy
import gpu
import bonsai.tool as tool
import bonsai.tool.surface as tool_surface
from bpy.types import SpaceView3D
from gpu_extras.batch import batch_for_shader


class SurfaceDecorator:
    """GPU draw handler for terrain TIN visualization.

    Registers handlers in ``SpaceView3D.draw_handler_add`` (POST_VIEW for
    3D world-space drawing). Reads
    ``CivilSurfaceProperties.show_triangles`` / ``show_elevation_banding``
    each draw to decide what to render — that means a single install
    persists across both toggles being on/off without re-installing.
    """

    is_installed: bool = False
    handlers: list = []

    # Wireframe color (light gray for high contrast against Blender's
    # default viewport background).
    COLOR_TRIANGLE_EDGE = (0.85, 0.85, 0.85, 0.9)
    LINE_WIDTH = 1.5

    # Elevation-banding ramp endpoints (R, G, B, A). Linear interpolation
    # from min-Z (cool blue) through mid (green) to max-Z (warm red).
    COLOR_ELEVATION_LOW = (0.20, 0.40, 0.80, 0.6)
    COLOR_ELEVATION_MID = (0.20, 0.80, 0.40, 0.6)
    COLOR_ELEVATION_HIGH = (0.85, 0.30, 0.20, 0.6)

    @classmethod
    def install(cls, context: bpy.types.Context) -> None:
        """Register the POST_VIEW draw handler.

        Re-installable, not idempotent: a repeated call uninstalls the
        previous handler and registers a fresh one against the supplied
        context. This is the right behavior when the user toggles the
        decorator off and back on, or switches scenes — the new context
        captures the new viewport's state.
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
        """Top-level POST_VIEW handler. Dispatches to the per-method draws
        based on the current property toggles."""
        scene_props = getattr(context.scene, "CivilSurfaceProperties", None)
        if scene_props is None:
            return
        if not scene_props.show_triangles and not scene_props.show_elevation_banding:
            return

        ifc_file = tool.Ifc.get()
        if ifc_file is None or not scene_props.active_surface_guid:
            return

        try:
            surface = tool.Surface.get(ifc_file, scene_props.active_surface_guid)
        except tool_surface.SaikeiSurfaceError:
            return

        if scene_props.show_triangles:
            self.draw_triangles_3d(surface)
        if scene_props.show_elevation_banding:
            self.draw_elevation_banding_3d(surface)

    def draw_triangles_3d(self, surface: "tool_surface.CivilSurface") -> None:
        """Render the TIN triangle wireframe via POLYLINE_UNIFORM_COLOR."""
        positions = [tuple(map(float, p)) for p in surface.points]
        indices: list[tuple[int, int]] = []
        for triangle in surface.triangles:
            a, b, c = int(triangle[0]), int(triangle[1]), int(triangle[2])
            indices.extend([(a, b), (b, c), (c, a)])

        if not tool.Blender.validate_shader_batch_data(positions, indices):
            return

        shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
        shader.bind()
        region = bpy.context.region
        if region is not None:
            shader.uniform_float(
                "viewportSize", (region.width, region.height)
            )
        shader.uniform_float("lineWidth", self.LINE_WIDTH)
        batch = batch_for_shader(
            shader, "LINES", {"pos": positions}, indices=indices
        )
        shader.uniform_float("color", self.COLOR_TRIANGLE_EDGE)
        batch.draw(shader)

    def draw_elevation_banding_3d(
        self, surface: "tool_surface.CivilSurface"
    ) -> None:
        """Render the TIN as colored TRIS via SMOOTH_COLOR with per-vertex
        Z-derived colors (low → mid → high ramp)."""
        if len(surface.points) == 0 or len(surface.triangles) == 0:
            return

        z_values = [float(p[2]) for p in surface.points]
        z_min = min(z_values)
        z_max = max(z_values)
        z_span = z_max - z_min if z_max > z_min else 1.0

        positions = [tuple(map(float, p)) for p in surface.points]
        colors = [
            self._elevation_color((z - z_min) / z_span) for z in z_values
        ]

        # Triangulated indices for TRIS — flatten triangle index triples.
        indices = [
            (int(t[0]), int(t[1]), int(t[2])) for t in surface.triangles
        ]
        if not tool.Blender.validate_shader_batch_data(positions, indices):
            return

        shader = gpu.shader.from_builtin("SMOOTH_COLOR")
        batch = batch_for_shader(
            shader,
            "TRIS",
            {"pos": positions, "color": colors},
            indices=indices,
        )
        shader.bind()
        batch.draw(shader)

    @classmethod
    def _elevation_color(cls, t: float) -> tuple[float, float, float, float]:
        """Linear-interpolate the three-stop elevation ramp at parameter
        ``t`` ∈ [0, 1]."""
        t = max(0.0, min(1.0, t))
        if t < 0.5:
            return cls._lerp_rgba(
                cls.COLOR_ELEVATION_LOW, cls.COLOR_ELEVATION_MID, t * 2.0
            )
        return cls._lerp_rgba(
            cls.COLOR_ELEVATION_MID, cls.COLOR_ELEVATION_HIGH, (t - 0.5) * 2.0
        )

    @staticmethod
    def _lerp_rgba(
        a: tuple[float, float, float, float],
        b: tuple[float, float, float, float],
        t: float,
    ) -> tuple[float, float, float, float]:
        return (
            a[0] + (b[0] - a[0]) * t,
            a[1] + (b[1] - a[1]) * t,
            a[2] + (b[2] - a[2]) * t,
            a[3] + (b[3] - a[3]) * t,
        )

# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2025, 2026 Michael Yoder <myoder@desertspringscivil.com>
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

"""Alignment module decorators for GPU visualization.

This module contains decorators for rendering visual feedback during
alignment-related operations, such as PI editing.
"""

import bpy
import blf
import gpu
import math
import bonsai.tool as tool
from bpy.types import SpaceView3D
from gpu_extras.batch import batch_for_shader


class PIEditDecorator:
    """Decorator for visualizing PI edit mode.

    This decorator provides visual feedback while the user is editing
    PI (Point of Intersection) positions with standard Blender transform tools:
    - Yellow lines connecting PI empties (tangent preview)
    - HUD text showing instructions

    The decorator reads positions directly from the PI empty objects,
    which are updated by Blender's transform operators (G key).
    """

    # Class-level state (cleared on uninstall)
    is_installed = False
    handlers = []

    # References to PI empty objects
    pi_empties = []

    # Whether to draw tangent-slide grab handles (spec 1.3, "T" key)
    show_tangent_handles = False

    # Colors
    COLOR_TANGENT_LINE = (1.0, 0.9, 0.2, 1.0)  # Yellow for tangent lines
    COLOR_HUD_TEXT = (1.0, 1.0, 1.0, 1.0)  # White for HUD text
    COLOR_EDIT_MODE_BG = (0.2, 0.4, 0.8, 0.8)  # Blue tint for edit mode indicator
    COLOR_TANGENT_HANDLE = (1.0, 0.3, 0.85, 1.0)  # Magenta for tangent-slide handles

    # Drawing parameters
    LINE_WIDTH = 2.5
    HANDLE_POINT_SIZE = 11.0

    @classmethod
    def install(cls, context, pi_empties):
        """Install decorator handlers for PI edit mode visualization.

        Args:
            context: Blender context
            pi_empties: List of PI EMPTY objects to visualize
        """
        if cls.is_installed:
            cls.uninstall()

        cls.pi_empties = pi_empties

        handler = cls()
        # POST_VIEW for 3D world-space drawing (tangent lines in 3D)
        cls.handlers.append(
            SpaceView3D.draw_handler_add(handler.draw_tangent_lines_3d, (context,), "WINDOW", "POST_VIEW")
        )
        # POST_PIXEL for 2D screen-space drawing (HUD)
        cls.handlers.append(
            SpaceView3D.draw_handler_add(handler.draw_hud, (context,), "WINDOW", "POST_PIXEL")
        )
        cls.is_installed = True

    @classmethod
    def uninstall(cls):
        """Remove all handlers and clear state."""
        for handler in cls.handlers:
            try:
                SpaceView3D.draw_handler_remove(handler, "WINDOW")
            except ValueError:
                pass
        cls.handlers = []
        cls.is_installed = False
        cls.pi_empties = []
        cls.show_tangent_handles = False

    @classmethod
    def update_positions(cls, pi_empties):
        """Update the list of PI empties (called when positions change).

        Args:
            pi_empties: Updated list of PI EMPTY objects
        """
        cls.pi_empties = pi_empties

    @classmethod
    def set_tangent_handles_visible(cls, visible: bool):
        """Toggle drawing of tangent-slide grab handles (spec 1.3, "T" key)."""
        cls.show_tangent_handles = visible

    def draw_batch_3d(self, shader_type, content_pos, color, indices=None):
        """Draw a batch of 3D primitives using GPU shader.

        Args:
            shader_type: Type of primitive ("LINES", "POINTS", etc.)
            content_pos: List of 3D vertex positions
            color: RGBA color tuple
            indices: Optional list of index pairs for lines
        """
        if not tool.Blender.validate_shader_batch_data(content_pos, indices):
            return
        shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
        shader.bind()

        # Get viewport size from active region
        region = bpy.context.region
        shader.uniform_float("viewportSize", (region.width, region.height))
        shader.uniform_float("lineWidth", self.LINE_WIDTH)

        batch = batch_for_shader(shader, shader_type, {"pos": content_pos}, indices=indices)
        shader.uniform_float("color", color)
        batch.draw(shader)

    def draw_tangent_lines_3d(self, context):
        """Draw yellow tangent lines connecting PI empties in 3D space."""
        if not self.pi_empties or len(self.pi_empties) < 2:
            return

        # Collect 3D positions from empties
        positions = []
        for empty in self.pi_empties:
            if empty and empty.name in bpy.data.objects:
                positions.append(tuple(empty.location))

        if len(positions) < 2:
            return

        # Setup blending for line drawing
        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("LESS_EQUAL")
        gpu.state.depth_mask_set(False)

        # Build edges list
        edges = [[i, i + 1] for i in range(len(positions) - 1)]

        # Draw lines
        self.draw_batch_3d("LINES", positions, self.COLOR_TANGENT_LINE, edges)

        # Tangent-slide grab handles (spec 1.3, "T" key) — one per tangent
        # chord midpoint, shown only while tangent-slide mode is armed.
        if PIEditDecorator.show_tangent_handles and len(positions) >= 2:
            midpoints = [
                (
                    (positions[i][0] + positions[i + 1][0]) / 2.0,
                    (positions[i][1] + positions[i + 1][1]) / 2.0,
                    (positions[i][2] + positions[i + 1][2]) / 2.0,
                )
                for i in range(len(positions) - 1)
            ]
            if tool.Blender.validate_shader_batch_data(midpoints, None):
                gpu.state.point_size_set(self.HANDLE_POINT_SIZE)
                shader = gpu.shader.from_builtin("UNIFORM_COLOR")
                batch = batch_for_shader(shader, "POINTS", {"pos": midpoints})
                shader.bind()
                shader.uniform_float("color", self.COLOR_TANGENT_HANDLE)
                batch.draw(shader)

        # Restore state
        gpu.state.blend_set("NONE")
        gpu.state.depth_test_set("NONE")
        gpu.state.depth_mask_set(True)

    def draw_hud(self, context):
        """Draw HUD text with edit mode instructions."""
        region = context.region
        if not region:
            return

        font_id = 0
        font_size = tool.Blender.scale_font_size(14)
        blf.size(font_id, font_size)
        blf.enable(font_id, blf.SHADOW)
        blf.shadow(font_id, 6, 0, 0, 0, 1)  # Black shadow for readability
        blf.color(font_id, *self.COLOR_HUD_TEXT)

        # Position in top-left of viewport
        margin = 20
        line_height = 22
        y_pos = region.height - margin

        # Count valid empties
        valid_count = sum(1 for e in self.pi_empties if e and e.name in bpy.data.objects)

        # Instructions
        instructions = [
            "PI Edit Mode",
            f"PIs: {valid_count}",
            "",
            "G: Move selected PI",
            "I: Insert PI on tangent",
            "X: Delete nearest PI",
            "C: Add curve   Alt+C: Delete curve",
            "T: Tangent slide" + (" (ON)" if PIEditDecorator.show_tangent_handles else ""),
            "",
            "ENTER: Apply changes",
            "ESC: Cancel",
        ]

        for i, line in enumerate(instructions):
            blf.position(font_id, margin, y_pos - (i * line_height), 0)
            blf.draw(font_id, line)

        blf.disable(font_id, blf.SHADOW)


class ProfileViewDecorator:
    """2D profile-view overlay (D2): a station-vs-elevation plot at the bottom
    of the 3D viewport.

    Shows the existing-ground (terrain) profile, the design profile, PVI
    markers, and a labelled grid — the visualization engineers actually use to
    design vertical alignments. Drawn in POST_PIXEL (window pixel space, origin
    bottom-left), following Bonsai's drawing-decoration idiom.

    Profile data is sampled from the tool layer on install / ``refresh`` and
    cached on the class; the screen transform is rebuilt every frame so the
    plot follows viewport resizing. The interactive editor reads the same
    cached transform via ``current_transform`` to map mouse -> (station, elev).
    """

    is_installed = False
    handlers = []

    # Live configuration (set on install)
    alignment_id = 0
    terrain_name = ""
    interval = 10.0
    panel_height = 260
    # 0 = auto-fit; > 0 locks vertical scale to N× the horizontal scale.
    vertical_exaggeration = 0.0

    # Cached sampled data (data space: lists of (station, elevation))
    design_points = []
    terrain_points = []
    pvi_points = []

    # Formatted station labels keyed by rounded station — populated lazily
    # during draw so the (unit-dependent) formatter runs once per tick value,
    # not once per frame. Cleared on refresh().
    station_labels = {}

    # Live edit preview (tangent polyline through the PVIs being dragged); when
    # set, it is drawn over the design profile. None when not editing.
    preview_points = None

    # Last transform built during draw — used by the interactive PVI editor to
    # convert mouse position to (station, elevation).
    current_transform = None

    # Layout (pixels)
    MARGIN_LEFT = 64
    MARGIN_RIGHT = 24
    MARGIN_BOTTOM = 28
    PADDING_TOP = 26

    # Colors (RGBA)
    COLOR_BG = (0.08, 0.09, 0.11, 0.86)
    COLOR_FRAME = (0.50, 0.50, 0.55, 1.0)
    COLOR_GRID = (0.24, 0.26, 0.30, 1.0)
    COLOR_TERRAIN = (0.70, 0.45, 0.22, 1.0)  # brown
    COLOR_DESIGN = (0.20, 0.80, 0.95, 1.0)  # cyan
    COLOR_PVI = (1.0, 0.85, 0.15, 1.0)  # yellow
    COLOR_TEXT = (0.88, 0.88, 0.90, 1.0)

    @classmethod
    def install(cls, context, alignment_id, terrain_obj, interval, panel_height, vertical_exaggeration=0.0):
        if cls.is_installed:
            cls.uninstall()
        cls.alignment_id = alignment_id
        cls.terrain_name = terrain_obj.name if terrain_obj else ""
        cls.interval = interval
        cls.panel_height = panel_height
        cls.vertical_exaggeration = vertical_exaggeration
        cls.refresh()
        handler = cls()
        cls.handlers.append(
            SpaceView3D.draw_handler_add(handler.draw_profile, (context,), "WINDOW", "POST_PIXEL")
        )
        cls.is_installed = True

    @classmethod
    def uninstall(cls):
        for handler in cls.handlers:
            try:
                SpaceView3D.draw_handler_remove(handler, "WINDOW")
            except ValueError:
                pass
        cls.handlers = []
        cls.is_installed = False
        cls.current_transform = None
        cls.preview_points = None

    @classmethod
    def refresh(cls):
        """Re-sample the design + terrain profiles and PVI markers from IFC."""
        cls.design_points = []
        cls.terrain_points = []
        cls.pvi_points = []
        cls.station_labels = {}

        ifc_file = tool.Ifc.get()
        if ifc_file is None or not cls.alignment_id:
            return
        try:
            alignment = ifc_file.by_id(cls.alignment_id)
        except RuntimeError:
            return
        if not alignment.is_a("IfcAlignment"):
            return

        cls.design_points = tool.Alignment.sample_design_profile(alignment, cls.interval)

        terrain_obj = bpy.data.objects.get(cls.terrain_name) if cls.terrain_name else None
        if terrain_obj is not None:
            cls.terrain_points = tool.Alignment.sample_terrain_profile(alignment, terrain_obj, cls.interval)

        if tool.Alignment.get_vertical_layout(alignment) is not None:
            try:
                pvis = tool.Alignment.back_calculate_pvis_from_vertical(alignment)
                cls.pvi_points = [(p["station"], p["elevation"]) for p in pvis]
            except (ValueError, KeyError):
                cls.pvi_points = []

    # ------------------------------------------------------------------ draw

    def draw_profile(self, context):
        region = context.region
        if region is None:
            return
        cls = ProfileViewDecorator
        panel_h = max(int(cls.panel_height), 120)
        width = region.width

        gpu.state.blend_set("ALPHA")
        self._draw_quad(0, 0, width, panel_h, cls.COLOR_BG)
        self._draw_text(cls.MARGIN_LEFT, panel_h - 19, "Profile View — Station vs Elevation", cls.COLOR_TEXT, size=12)

        rect_x = cls.MARGIN_LEFT
        rect_y = cls.MARGIN_BOTTOM
        rect_w = width - cls.MARGIN_LEFT - cls.MARGIN_RIGHT
        rect_h = panel_h - cls.MARGIN_BOTTOM - cls.PADDING_TOP
        if rect_w < 80 or rect_h < 40:
            gpu.state.blend_set("NONE")
            return

        transform = tool.Alignment.build_profile_view_transform(
            cls.design_points,
            cls.terrain_points,
            rect_x,
            rect_y,
            rect_w,
            rect_h,
            vertical_exaggeration=cls.vertical_exaggeration,
        )
        cls.current_transform = transform
        if transform is None:
            self._draw_text(
                rect_x + 10,
                rect_y + rect_h / 2,
                "No profile data — add a vertical alignment or designate terrain, then Refresh.",
                cls.COLOR_TEXT,
            )
            gpu.state.blend_set("NONE")
            return

        self._draw_grid(region, transform)
        self._draw_frame(region, transform)

        if len(cls.terrain_points) >= 2:
            verts = [(*transform.data_to_screen(s, e), 0.0) for (s, e) in cls.terrain_points]
            self._draw_lines(region, verts, [(i, i + 1) for i in range(len(verts) - 1)], cls.COLOR_TERRAIN, 2.0)

        if len(cls.design_points) >= 2:
            verts = [(*transform.data_to_screen(s, e), 0.0) for (s, e) in cls.design_points]
            self._draw_lines(region, verts, [(i, i + 1) for i in range(len(verts) - 1)], cls.COLOR_DESIGN, 2.5)

        # Live edit preview (tangent polyline through the dragged PVIs).
        if cls.preview_points and len(cls.preview_points) >= 2:
            verts = [(*transform.data_to_screen(s, e), 0.0) for (s, e) in cls.preview_points]
            self._draw_lines(region, verts, [(i, i + 1) for i in range(len(verts) - 1)], (1.0, 0.3, 0.8, 1.0), 1.5)

        pvi_verts = [(*transform.data_to_screen(s, e), 0.0) for (s, e) in cls.pvi_points]
        self._draw_points(pvi_verts, cls.COLOR_PVI, 9.0)
        for (station, elevation), vert in zip(cls.pvi_points, pvi_verts):
            self._draw_text(vert[0] + 6, vert[1] + 7, f"{elevation:.2f}", cls.COLOR_PVI, size=10)

        # Legend
        legend_x = rect_x + rect_w - 150
        legend_y = rect_y + rect_h - 14
        self._draw_text(legend_x, legend_y, "— Design", cls.COLOR_DESIGN, size=10)
        if cls.terrain_points:
            self._draw_text(legend_x, legend_y - 15, "— Terrain", cls.COLOR_TERRAIN, size=10)

        gpu.state.blend_set("NONE")

    # --------------------------------------------------------------- helpers

    def _draw_grid(self, region, transform):
        cls = ProfileViewDecorator
        station_step = self._nice_step(transform.station_max - transform.station_min, 8)
        elevation_step = self._nice_step(transform.elevation_max - transform.elevation_min, 5)

        verts = []
        indices = []
        if station_step:
            station = math.ceil(transform.station_min / station_step) * station_step
            while station <= transform.station_max + 1e-9:
                px, _ = transform.data_to_screen(station, transform.elevation_min)
                base = len(verts)
                verts.append((px, transform.rect_y, 0.0))
                verts.append((px, transform.rect_y + transform.rect_height, 0.0))
                indices.append((base, base + 1))
                self._draw_text(px - 14, transform.rect_y - 15, self._station_label(station), cls.COLOR_TEXT, size=9)
                station += station_step
        if elevation_step:
            elevation = math.ceil(transform.elevation_min / elevation_step) * elevation_step
            while elevation <= transform.elevation_max + 1e-9:
                _, py = transform.data_to_screen(transform.station_min, elevation)
                base = len(verts)
                verts.append((transform.rect_x, py, 0.0))
                verts.append((transform.rect_x + transform.rect_width, py, 0.0))
                indices.append((base, base + 1))
                self._draw_text(transform.rect_x - 52, py - 4, self._fmt(elevation), cls.COLOR_TEXT, size=9)
                elevation += elevation_step
        self._draw_lines(region, verts, indices, cls.COLOR_GRID, 1.0)

    def _draw_frame(self, region, transform):
        x0, y0 = transform.rect_x, transform.rect_y
        x1, y1 = transform.rect_x + transform.rect_width, transform.rect_y + transform.rect_height
        verts = [(x0, y0, 0.0), (x1, y0, 0.0), (x1, y1, 0.0), (x0, y1, 0.0)]
        self._draw_lines(region, verts, [(0, 1), (1, 2), (2, 3), (3, 0)], ProfileViewDecorator.COLOR_FRAME, 1.5)

    def _draw_lines(self, region, verts, indices, color, width=1.0):
        if len(verts) < 2 or not indices:
            return
        shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
        shader.bind()
        shader.uniform_float("viewportSize", (region.width, region.height))
        shader.uniform_float("lineWidth", width)
        batch = batch_for_shader(shader, "LINES", {"pos": verts}, indices=indices)
        shader.uniform_float("color", color)
        batch.draw(shader)

    def _draw_quad(self, x0, y0, x1, y1, color):
        verts = [(x0, y0, 0.0), (x1, y0, 0.0), (x1, y1, 0.0), (x0, y1, 0.0)]
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        batch = batch_for_shader(shader, "TRIS", {"pos": verts}, indices=[(0, 1, 2), (0, 2, 3)])
        shader.bind()
        shader.uniform_float("color", color)
        batch.draw(shader)

    def _draw_points(self, verts, color, size=8.0):
        if not verts:
            return
        gpu.state.point_size_set(size)
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        batch = batch_for_shader(shader, "POINTS", {"pos": verts})
        shader.bind()
        shader.uniform_float("color", color)
        batch.draw(shader)

    def _draw_text(self, x, y, text, color, size=11):
        font_id = 0
        blf.size(font_id, tool.Blender.scale_font_size(size))
        blf.color(font_id, *color)
        blf.position(font_id, x, y, 0)
        blf.draw(font_id, text)

    @staticmethod
    def _nice_step(span, target_count):
        """Return a 1/2/5 x 10^n step giving roughly ``target_count`` divisions."""
        if span <= 0 or target_count <= 0:
            return 0.0
        raw = span / target_count
        magnitude = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1.0
        normalized = raw / magnitude
        if normalized < 1.5:
            nice = 1.0
        elif normalized < 3.0:
            nice = 2.0
        elif normalized < 7.0:
            nice = 5.0
        else:
            nice = 10.0
        return nice * magnitude

    @classmethod
    def _station_label(cls, station):
        """Project-notation station label, cached per tick value."""
        key = round(station, 4)
        label = cls.station_labels.get(key)
        if label is None:
            try:
                label = tool.Alignment.format_station(station)
            except Exception:
                label = cls._fmt(station)
            cls.station_labels[key] = label
        return label

    @staticmethod
    def _fmt(value):
        return f"{value:.0f}" if abs(value) >= 100 else f"{value:.1f}"

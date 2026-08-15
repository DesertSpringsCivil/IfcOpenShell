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


"""Alignment Tool - Blender implementations for alignment visualization.

This module contains Blender-specific code for creating and managing
alignment objects in the 3D view. It bridges the core business logic
to the Blender environment.

All methods are classmethods following Bonsai's tool pattern.
"""

from __future__ import annotations
import bpy
import math
import logging
import bonsai.tool as tool
import bonsai.bim.import_ifc
import ifcopenshell.api.alignment
from typing import TYPE_CHECKING, Optional, List, Tuple
from dataclasses import dataclass

if TYPE_CHECKING:
    import ifcopenshell


# =============================================================================
# Data Classes for PI Geometry Results
# =============================================================================


@dataclass
class PIGeometryResult:
    """Result of PI geometry calculation."""

    stations: List[float]
    lengths: List[float]
    directions: List[float]
    total_length: float


@dataclass
class PVIGeometryResult:
    """Result of PVI geometry calculation for vertical alignment.

    Parallel arrays:
    - stations/elevations/grades: one entry per PVI (grades has n-1 entries)
    - k_values/bvc_stations/evc_stations: one entry per *interior* PVI (n-2 entries)
    """

    stations: List[float]
    elevations: List[float]
    grades: List[float]
    k_values: List[float]
    bvc_stations: List[float]
    evc_stations: List[float]
    total_length: float


@dataclass
class AlignmentPoint:
    """A point evaluated on the 3D combined alignment at a given station.

    This is the result type for ``evaluate_alignment_at_station`` — the
    keystone query that downstream features (cross-section placement,
    corridor sweep, terrain sampling, daylighting) all depend on.

    Coordinates are in model (project) units, in the alignment's local
    coordinate system — the same space used by ``segment_vertices`` and the
    Blender segment objects. Callers needing global map coordinates should
    georeference via ``tool.Georeference``.

    The frame is orthonormal and right-handed:
    - ``tangent`` points in the direction of increasing station,
    - ``up`` is the local vertical of the alignment frame,
    - ``normal`` is the in-plane lateral direction (left of travel).

    ``grade`` is the vertical grade (rise/run) at the station, derived from
    the tangent. It is 0.0 for a horizontal-only alignment.
    """

    station: float
    position: Tuple[float, float, float]
    tangent: Tuple[float, float, float]
    normal: Tuple[float, float, float]
    up: Tuple[float, float, float]
    grade: float


@dataclass
class ProfileViewTransform:
    """Maps between profile-data space (station, elevation) and viewport pixels.

    The profile view (D2) is a 2D station-vs-elevation plot drawn as a screen
    overlay. This transform is the single source of truth for both directions:
    the decorator uses ``data_to_screen`` to plot the terrain/design polylines,
    and the interactive PVI editor uses ``screen_to_data`` to turn a mouse
    position into a (station, elevation). Keeping the mapping here (pure math)
    makes it unit-testable independent of any GPU/viewport context.

    The plot rectangle is given by its bottom-left corner (rect_x, rect_y) and
    size (rect_w, rect_h) in pixels; data bounds are inclusive.
    """

    station_min: float
    station_max: float
    elevation_min: float
    elevation_max: float
    rect_x: float
    rect_y: float
    rect_width: float
    rect_height: float

    def data_to_screen(self, station: float, elevation: float) -> Tuple[float, float]:
        station_span = (self.station_max - self.station_min) or 1.0
        elevation_span = (self.elevation_max - self.elevation_min) or 1.0
        px = self.rect_x + (station - self.station_min) / station_span * self.rect_width
        py = self.rect_y + (elevation - self.elevation_min) / elevation_span * self.rect_height
        return (px, py)

    def screen_to_data(self, px: float, py: float) -> Tuple[float, float]:
        station_span = (self.station_max - self.station_min) or 1.0
        elevation_span = (self.elevation_max - self.elevation_min) or 1.0
        station = self.station_min + (px - self.rect_x) / (self.rect_width or 1.0) * station_span
        elevation = self.elevation_min + (py - self.rect_y) / (self.rect_height or 1.0) * elevation_span
        return (station, elevation)


class Alignment:
    """Tool class for alignment-related Blender operations.

    Following Bonsai's tool pattern, all methods are classmethods
    that can be called without instantiation.
    """

    # =========================================================================
    # Geometry Calculation Methods
    # =========================================================================

    @classmethod
    def calculate_pi_geometry(cls, pis: List[Tuple[float, float]], start_station: float = 0.0) -> PIGeometryResult:
        """Calculate lengths, stations, and directions for a list of PI points.

        Args:
            pis: List of (x, y) coordinate tuples for each PI
            start_station: Starting station value

        Returns:
            PIGeometryResult containing calculated values
        """
        if len(pis) < 2:
            return PIGeometryResult(
                stations=[start_station] if pis else [],
                lengths=[0.0] if pis else [],
                directions=[0.0] if pis else [],
                total_length=0.0,
            )

        stations = []
        lengths = []
        directions = []
        cumulative_length = start_station

        for i, pi in enumerate(pis):
            stations.append(cumulative_length)

            if i < len(pis) - 1:
                next_pi = pis[i + 1]
                dx = next_pi[0] - pi[0]
                dy = next_pi[1] - pi[1]
                length = math.sqrt(dx * dx + dy * dy)
                direction = math.atan2(dy, dx)
                lengths.append(length)
                directions.append(direction)
                cumulative_length += length
            else:
                lengths.append(0.0)
                directions.append(0.0)

        total_length = cumulative_length - start_station

        return PIGeometryResult(stations=stations, lengths=lengths, directions=directions, total_length=total_length)

    @classmethod
    def calculate_tangent_length(cls, radius: float, deflection_angle: float) -> float:
        """Calculate tangent length for a circular curve.

        T = R * tan(Δ/2)

        Args:
            radius: Curve radius
            deflection_angle: Deflection angle in radians

        Returns:
            Tangent length
        """
        if deflection_angle == 0 or radius == 0:
            return 0.0
        return radius * math.tan(deflection_angle / 2)

    @classmethod
    def calculate_arc_length(cls, radius: float, deflection_angle: float) -> float:
        """Calculate arc length for a circular curve.

        L = R * Δ

        Args:
            radius: Curve radius
            deflection_angle: Deflection angle in radians

        Returns:
            Arc length
        """
        return radius * deflection_angle

    @classmethod
    def deflection_angle_from_points(
        cls, p1: Tuple[float, float], p2: Tuple[float, float], p3: Tuple[float, float]
    ) -> float:
        """Calculate deflection angle at p2 from three (e, n) coordinate tuples.

        Args:
            p1: Previous PI coordinates (e, n)
            p2: Current PI coordinates (e, n)
            p3: Next PI coordinates (e, n)

        Returns:
            Deflection angle in radians (signed: positive=left, negative=right)
        """
        dx1 = p2[0] - p1[0]
        dy1 = p2[1] - p1[1]
        incoming = math.atan2(dy1, dx1)

        dx2 = p3[0] - p2[0]
        dy2 = p3[1] - p2[1]
        outgoing = math.atan2(dy2, dx2)

        delta = outgoing - incoming
        while delta > math.pi:
            delta -= 2 * math.pi
        while delta < -math.pi:
            delta += 2 * math.pi
        return delta

    @classmethod
    def arc_length_at_pi(
        cls,
        p1: Tuple[float, float],
        p2: Tuple[float, float],
        p3: Tuple[float, float],
        radius: float,
    ) -> float:
        """Calculate arc length L = R * |delta| at a PI with curve.

        Args:
            p1, p2, p3: (e, n) coordinate tuples for prev, current, next PI
            radius: Curve radius (must be > 0)

        Returns:
            Arc length
        """
        if radius <= 0:
            return 0.0
        deflection = cls.deflection_angle_from_points(p1, p2, p3)
        return cls.calculate_arc_length(radius, abs(deflection))

    @classmethod
    def tangent_length_at_pi(
        cls,
        p1: Tuple[float, float],
        p2: Tuple[float, float],
        p3: Tuple[float, float],
        radius: float,
    ) -> float:
        """Calculate tangent length T = R * tan(|delta|/2) at a PI.

        Args:
            p1, p2, p3: (e, n) coordinate tuples for prev, current, next PI
            radius: Curve radius (must be > 0)

        Returns:
            Tangent length
        """
        if radius <= 0:
            return 0.0
        deflection = cls.deflection_angle_from_points(p1, p2, p3)
        return cls.calculate_tangent_length(radius, abs(deflection))

    @classmethod
    def tangent_segment_length(
        cls,
        p_start: Tuple[float, float],
        p_end: Tuple[float, float],
        start_tangent: float = 0.0,
        end_tangent: float = 0.0,
    ) -> float:
        """Calculate tangent segment length between two PIs, minus curve tangent lengths.

        Args:
            p_start: (e, n) coordinate tuple for start PI
            p_end: (e, n) coordinate tuple for end PI
            start_tangent: Tangent length to subtract at start
            end_tangent: Tangent length to subtract at end

        Returns:
            Net segment length (clamped to 0)
        """
        dx = p_end[0] - p_start[0]
        dy = p_end[1] - p_start[1]
        full_length = math.sqrt(dx * dx + dy * dy)
        return max(0.0, full_length - start_tangent - end_tangent)

    # =========================================================================
    # Spiral Transitions & Compound/Reverse Curves (spec 1.5, 1.6)
    # =========================================================================
    # Pure-math helpers: A-value <-> length conversion, radii-element
    # construction for the PI-method solver, and PI-table display geometry
    # (arc length / tangent lengths with spirals, PCC/PRC classification).
    # The semantic (DesignParameters-only) PI reconstruction that spec 1.5's
    # edit-mode round-trip depends on lives further down, next to
    # back_calculate_pis_from_alignment (its only caller).

    @staticmethod
    def spiral_length_from_a_value(a_value: float, radius: float) -> float:
        """Clothoid spiral length from its A-value: L = A^2 / R (spec 1.5
        A-value mode). Returns 0.0 if radius <= 0 (an A-value is meaningless
        without a curve to transition into)."""
        if radius <= 0 or a_value <= 0:
            return 0.0
        return (a_value * a_value) / radius

    @staticmethod
    def a_value_from_spiral_length(length: float, radius: float) -> float:
        """Clothoid A-value from its length: A = sqrt(R * L) -- the inverse
        of ``spiral_length_from_a_value``. Returns 0.0 if radius <= 0 or
        length <= 0."""
        if radius <= 0 or length <= 0:
            return 0.0
        return math.sqrt(radius * length)

    @classmethod
    def build_pi_radius_element(
        cls,
        radius: float,
        spiral_in: float = 0.0,
        spiral_out: float = 0.0,
        join_next: bool = False,
    ):
        """Build one element of the ``radii`` sequence that
        ``ifcopenshell.api.alignment.layout_horizontal_alignment_by_pi_method``
        (and its pure-geometry sibling ``solve_horizontal_alignment_by_pi_method``)
        expects for a single PI, per spec 1.5/1.6:

        - plain ``radius`` (float) when there are no spirals and no
          join_next -- the original, pre-spiral behavior: a bare circular
          curve, or, at radius 0.0, a pass-through tangent PI.
        - ``(radius, spiral_in, spiral_out)`` when either spiral length is
          > 0 -- spiral-curve-spiral, or spiral-spiral when the two spirals
          consume the PI's full deflection (the solver decides which; this
          function only shapes the element).
        - ``{"radius": ..., "lin": ..., "lout": ..., "join_next": True}``
          when ``join_next`` is set (spec 1.6 compound/reverse curves) --
          the dict form is used even when both spiral lengths are 0.0,
          since join_next is only accepted by the solver in dict form.
        """
        if join_next:
            return {"radius": float(radius), "lin": float(spiral_in), "lout": float(spiral_out), "join_next": True}
        if spiral_in > 0.0 or spiral_out > 0.0:
            return (float(radius), float(spiral_in), float(spiral_out))
        return float(radius)

    @classmethod
    def spiral_curve_geometry_at_pi(
        cls,
        p1: Tuple[float, float],
        p2: Tuple[float, float],
        p3: Tuple[float, float],
        radius: float,
        spiral_in: float = 0.0,
        spiral_out: float = 0.0,
    ) -> dict:
        """Pure-math PI-table display geometry (spec 1.5) for a curve at a
        PI, with or without spiral transitions -- a direct port of
        ``solve_horizontal_alignment_by_pi_method``'s own spiral composition
        (the same ``theta = L / (2R)`` spiral angle, the same
        ``ifcopenshell.api.alignment.compute_clothoid_end`` quadrature) so
        the table's Tan / Spiral / Curve row lengths agree with what the
        solver actually writes to IFC, without needing to run the solver
        (or the geometry engine) just to redraw the table.

        Returns a dict:
            "deflection": signed delta at the PI, radians (0.0 if no curve)
            "tangent_in": distance from the PI back to TS (or PC if there is
                no entry spiral)
            "tangent_out": distance from the PI forward to ST (or PT if
                there is no exit spiral)
            "arc_length": length of the CIRCULAR portion only -- 0.0 for a
                pure spiral-spiral transition, where the spirals consume the
                whole deflection

        radius <= 0 (no curve at this PI) returns all zeros.
        """
        if radius <= 0:
            return {"deflection": 0.0, "tangent_in": 0.0, "tangent_out": 0.0, "arc_length": 0.0}

        delta = cls.deflection_angle_from_points(p1, p2, p3)

        if spiral_in <= 0.0 and spiral_out <= 0.0:
            tangent = cls.calculate_tangent_length(radius, abs(delta))
            arc_length = cls.calculate_arc_length(radius, abs(delta))
            return {"deflection": delta, "tangent_in": tangent, "tangent_out": tangent, "arc_length": arc_length}

        import ifcopenshell.api.alignment as align_api

        R = float(radius)
        theta1 = spiral_in / (2.0 * R)
        theta2 = spiral_out / (2.0 * R)
        theta_c = max(abs(delta) - theta1 - theta2, 0.0)
        arc_length = R * theta_c

        # Composition mirrors the solver exactly: pieces are built for a
        # curve turning left (unsigned R, theta_c) and mirrored into world
        # space by s -- see solve_horizontal_alignment_by_pi_method's own
        # comment on this same composition.
        s = 1.0 if 0.0 < delta else -1.0
        pieces = []
        if spiral_in > 0.0:
            pieces.append(align_api.compute_clothoid_end(spiral_in, 0.0, 1.0 / R))
        pieces.append((R * math.sin(theta_c), R * (1.0 - math.cos(theta_c)), theta_c))
        if spiral_out > 0.0:
            pieces.append(align_api.compute_clothoid_end(spiral_out, 1.0 / R, 0.0))

        x = y = direction = 0.0
        for dx_, dy_, dtheta_ in pieces:
            x += dx_ * math.cos(direction) - s * dy_ * math.sin(direction)
            y += dx_ * math.sin(direction) + s * dy_ * math.cos(direction)
            direction += s * dtheta_

        if abs(math.sin(delta)) < 1e-12:
            return {"deflection": delta, "tangent_in": 0.0, "tangent_out": 0.0, "arc_length": arc_length}

        tangent_in = x - y / math.tan(delta)
        tangent_out = y / math.sin(delta)
        return {"deflection": delta, "tangent_in": tangent_in, "tangent_out": tangent_out, "arc_length": arc_length}

    @classmethod
    def junction_type(
        cls,
        p_prev: Tuple[float, float],
        p_this: Tuple[float, float],
        p_next: Tuple[float, float],
        p_next2: Tuple[float, float],
    ) -> str:
        """Classify a join_next compound/reverse curve junction (spec 1.6)
        between the curve at PI ``p_this`` and the curve at PI ``p_next`` by
        comparing their deflection signs: a PCC (point of compound
        curvature) when the two curves turn the SAME direction, a PRC
        (point of reverse curvature) when they turn OPPOSITE directions.

        Uses the PI polygon's own turn direction at each PI (well-defined
        from three consecutive PI points regardless of whether a real
        tangent run separates the two curves), so this works for a
        join_next junction exactly as it would for two independently
        tangent-connected curves.
        """
        delta1 = cls.deflection_angle_from_points(p_prev, p_this, p_next)
        delta2 = cls.deflection_angle_from_points(p_this, p_next, p_next2)
        return "PCC" if (delta1 >= 0.0) == (delta2 >= 0.0) else "PRC"

    # =========================================================================
    # Vertical Alignment Geometry Methods
    # =========================================================================

    @classmethod
    def calculate_grade(cls, start_elevation: float, end_elevation: float, horizontal_distance: float) -> float:
        """Calculate the grade (slope) between two PVI points.

        g = (end_elevation - start_elevation) / horizontal_distance

        Args:
            start_elevation: Elevation at start PVI
            end_elevation: Elevation at end PVI
            horizontal_distance: Horizontal distance between PVIs

        Returns:
            Grade as a decimal (e.g. 0.02 = 2% uphill). Returns 0.0 for
            zero or negative horizontal_distance.
        """
        if horizontal_distance <= 0:
            return 0.0
        return (end_elevation - start_elevation) / horizontal_distance

    @classmethod
    def calculate_k_value(cls, curve_length: float, grade_change: float) -> float:
        """Calculate the K-value (rate of grade change) for a vertical curve.

        K = L / A, where A = |Δg| expressed in PERCENT — the civil convention
        used by the AASHTO sight-distance tables (length per percent of grade
        change). A higher K-value means a more gradual curve.

        Args:
            curve_length: Vertical curve length (L)
            grade_change: Algebraic grade change Δg = g2 - g1 (decimal)

        Returns:
            K-value per percent grade change. Returns 0.0 if grade_change is
            effectively zero (flat curve) or if curve_length is zero.
        """
        if abs(grade_change) < 1e-10 or curve_length <= 0:
            return 0.0
        return curve_length / abs(grade_change * 100.0)

    @classmethod
    def calculate_vertical_curve_length_from_k(cls, k_value: float, grade_change: float) -> float:
        """Calculate vertical curve length from K-value and grade change.

        L = K * A, where A = |Δg| in PERCENT — the inverse of
        ``calculate_k_value``, sharing its per-percent civil convention.

        Args:
            k_value: Design K-value (length per percent grade change)
            grade_change: Algebraic grade change Δg = g2 - g1 (decimal)

        Returns:
            Vertical curve length
        """
        return k_value * abs(grade_change * 100.0)

    # Minimum K values for stopping sight distance, AASHTO "A Policy on
    # Geometric Design of Highways and Streets" (Green Book), 7th Edition:
    # Table 3-34 (crest) and Table 3-36 (sag). Keyed by design speed;
    # imperial K in ft per % grade change at mph, metric K in m per % at km/h
    # (6th Edition metric tables). Advisory only — deviations are flagged,
    # never blocked (the engineer seals the drawings).
    AASHTO_K_TABLE_IMPERIAL = {
        # mph: (crest_K, sag_K)
        30: (19.0, 37.0),
        35: (29.0, 49.0),
        40: (44.0, 64.0),
        45: (61.0, 79.0),
        50: (84.0, 96.0),
        55: (114.0, 115.0),
        60: (151.0, 136.0),
        65: (193.0, 157.0),
        70: (247.0, 181.0),
    }
    AASHTO_K_TABLE_METRIC = {
        # km/h: (crest_K, sag_K)
        30: (2.0, 6.0),
        40: (4.0, 9.0),
        50: (7.0, 13.0),
        60: (11.0, 18.0),
        70: (17.0, 23.0),
        80: (26.0, 30.0),
        90: (39.0, 38.0),
        100: (52.0, 45.0),
        110: (74.0, 55.0),
        120: (95.0, 63.0),
    }

    @classmethod
    def is_imperial_project(cls) -> bool:
        """True when the project LENGTHUNIT is a conversion-based (imperial) unit."""
        import ifcopenshell.util.unit

        ifc_file = tool.Ifc.get()
        if ifc_file is None:
            return False
        unit_type = ifcopenshell.util.unit.get_project_unit(ifc_file, "LENGTHUNIT")
        return unit_type is not None and unit_type.is_a("IfcConversionBasedUnit")

    @classmethod
    def required_k_for_design_speed(cls, design_speed: float, is_crest: bool) -> Optional[float]:
        """Minimum AASHTO stopping-sight-distance K for ``design_speed``.

        The table (imperial mph / metric km/h, chosen by project units) is
        looked up at the given speed, rounding UP to the next tabulated speed
        (conservative). Returns None when design_speed is 0/negative or above
        the table's range.
        """
        if design_speed <= 0:
            return None
        table = cls.AASHTO_K_TABLE_IMPERIAL if cls.is_imperial_project() else cls.AASHTO_K_TABLE_METRIC
        for speed in sorted(table):
            if design_speed <= speed:
                crest_k, sag_k = table[speed]
                return crest_k if is_crest else sag_k
        return None

    @classmethod
    def set_design_criteria(cls, alignment: "ifcopenshell.entity_instance", design_speed: float) -> None:
        """Persist design criteria on the alignment as Pset_SaikeiDesignCriteria.

        IFC 4.3 has no standard pset for alignment design criteria, so the
        design speed rides in a Saikei pset for save/reopen round-trip.
        """
        import ifcopenshell.api.pset
        import ifcopenshell.util.element

        ifc_file = tool.Ifc.get()
        existing = ifcopenshell.util.element.get_pset(alignment, "Pset_SaikeiDesignCriteria", should_inherit=False)
        if existing:
            pset_entity = ifc_file.by_id(existing["id"])
        else:
            pset_entity = ifcopenshell.api.pset.add_pset(ifc_file, product=alignment, name="Pset_SaikeiDesignCriteria")
        ifcopenshell.api.pset.edit_pset(ifc_file, pset=pset_entity, properties={"DesignSpeed": float(design_speed)})

    @classmethod
    def get_design_criteria(cls, alignment: "ifcopenshell.entity_instance") -> Optional[float]:
        """Return the persisted design speed, or None when never set."""
        import ifcopenshell.util.element

        pset = ifcopenshell.util.element.get_pset(alignment, "Pset_SaikeiDesignCriteria", should_inherit=False)
        if pset and pset.get("DesignSpeed") is not None:
            return float(pset["DesignSpeed"])
        return None

    @classmethod
    def calculate_elevation_on_parabola(
        cls,
        start_elevation: float,
        start_gradient: float,
        end_gradient: float,
        curve_length: float,
        distance_from_bvc: float,
    ) -> float:
        """Calculate elevation at any point on a symmetric parabolic vertical curve.

        y = y_BVC + g1 * x + ((g2 - g1) / (2 * L)) * x²

        Args:
            start_elevation: Elevation at BVC (Begin Vertical Curve)
            start_gradient: Incoming grade g1 (decimal)
            end_gradient: Outgoing grade g2 (decimal)
            curve_length: Total curve length L
            distance_from_bvc: Distance x from BVC to the point of interest

        Returns:
            Elevation at the given distance from BVC
        """
        if curve_length <= 0:
            return start_elevation + start_gradient * distance_from_bvc
        grade_change_rate = (end_gradient - start_gradient) / (2.0 * curve_length)
        return start_elevation + start_gradient * distance_from_bvc + grade_change_rate * distance_from_bvc**2

    @classmethod
    def calculate_high_low_point_distance(
        cls,
        start_gradient: float,
        end_gradient: float,
        curve_length: float,
    ) -> Optional[float]:
        """Calculate distance from BVC to the high or low point on a parabola.

        The high point occurs on a crest curve (g1 > 0, g2 < 0).
        The low point occurs on a sag curve (g1 < 0, g2 > 0).

        x_hl = g1 * L / (g1 - g2)

        Args:
            start_gradient: Incoming grade g1 (decimal)
            end_gradient: Outgoing grade g2 (decimal)
            curve_length: Total curve length L

        Returns:
            Distance from BVC to the high/low point, or None if no
            high/low point exists within the curve (grades don't change sign).
        """
        grade_denominator = start_gradient - end_gradient
        if abs(grade_denominator) < 1e-10:
            return None  # Constant gradient — no high/low point
        x_high_low = start_gradient * curve_length / grade_denominator
        if 0 < x_high_low < curve_length:
            return x_high_low
        return None  # High/low point is outside the curve

    @classmethod
    def calculate_bvc_evc_stations(cls, pvi_station: float, curve_length: float) -> Tuple[float, float]:
        """Calculate BVC and EVC stations from the PVI station and curve length.

        For a symmetric parabolic curve:
            BVC = PVI - L/2
            EVC = PVI + L/2

        Args:
            pvi_station: Station of the Point of Vertical Intersection
            curve_length: Total vertical curve length L

        Returns:
            Tuple of (bvc_station, evc_station)
        """
        half_length = curve_length / 2.0
        return (pvi_station - half_length, pvi_station + half_length)

    @classmethod
    def calculate_pvi_geometry(
        cls,
        pvis: List[Tuple[float, float]],
        curve_lengths: Optional[List[float]] = None,
    ) -> PVIGeometryResult:
        """Calculate full geometry for a series of PVI (Point of Vertical Intersection) points.

        Args:
            pvis: List of (station, elevation) tuples, ordered by station
            curve_lengths: Optional list of curve lengths for interior PVIs.
                           Must have len(pvis) - 2 entries (no curves at endpoints).
                           Defaults to 0.0 for all interior PVIs if not provided.

        Returns:
            PVIGeometryResult with stations, elevations, grades (n-1 entries),
            and k_values / bvc_stations / evc_stations for each interior PVI (n-2 entries).
        """
        num_pvis = len(pvis)

        if num_pvis == 0:
            return PVIGeometryResult(
                stations=[],
                elevations=[],
                grades=[],
                k_values=[],
                bvc_stations=[],
                evc_stations=[],
                total_length=0.0,
            )

        stations = [float(pvi[0]) for pvi in pvis]
        elevations = [float(pvi[1]) for pvi in pvis]

        if num_pvis == 1:
            return PVIGeometryResult(
                stations=stations,
                elevations=elevations,
                grades=[],
                k_values=[],
                bvc_stations=[],
                evc_stations=[],
                total_length=0.0,
            )

        # Calculate grades between consecutive PVIs (n-1 values)
        grades = []
        for i in range(num_pvis - 1):
            horizontal_distance = stations[i + 1] - stations[i]
            grades.append(cls.calculate_grade(elevations[i], elevations[i + 1], horizontal_distance))

        # Prepare curve lengths for interior PVIs (n-2 values)
        num_interior_pvis = num_pvis - 2
        if curve_lengths is None:
            interior_curve_lengths = [0.0] * num_interior_pvis
        else:
            interior_curve_lengths = list(curve_lengths)

        # Compute K-values and BVC/EVC for each interior PVI
        k_values = []
        bvc_station_list = []
        evc_station_list = []

        for interior_index in range(num_interior_pvis):
            pvi_index = interior_index + 1  # Interior PVIs are at index 1..(n-2)
            curve_length = (
                interior_curve_lengths[interior_index] if interior_index < len(interior_curve_lengths) else 0.0
            )
            grade_incoming = grades[interior_index]
            grade_outgoing = grades[interior_index + 1]
            grade_change = grade_outgoing - grade_incoming

            k_values.append(cls.calculate_k_value(curve_length, grade_change))
            bvc, evc = cls.calculate_bvc_evc_stations(stations[pvi_index], curve_length)
            bvc_station_list.append(bvc)
            evc_station_list.append(evc)

        total_length = stations[-1] - stations[0]

        return PVIGeometryResult(
            stations=stations,
            elevations=elevations,
            grades=grades,
            k_values=k_values,
            bvc_stations=bvc_station_list,
            evc_stations=evc_station_list,
            total_length=total_length,
        )

    @classmethod
    def is_crest_curve(cls, start_gradient: float, end_gradient: float) -> bool:
        """Check if two grades form a crest (hill) curve.

        A crest curve transitions from a higher to a lower grade (g1 > g2).
        It controls stopping sight distance.

        Args:
            start_gradient: Incoming grade (decimal)
            end_gradient: Outgoing grade (decimal)

        Returns:
            True if end_gradient < start_gradient
        """
        return end_gradient < start_gradient

    @classmethod
    def is_sag_curve(cls, start_gradient: float, end_gradient: float) -> bool:
        """Check if two grades form a sag (valley) curve.

        A sag curve transitions from a lower to a higher grade (g1 < g2).
        It controls headlight sight distance and rider comfort.

        Args:
            start_gradient: Incoming grade (decimal)
            end_gradient: Outgoing grade (decimal)

        Returns:
            True if end_gradient > start_gradient
        """
        return end_gradient > start_gradient

    @classmethod
    def back_calculate_pvis_from_vertical(
        cls,
        alignment: "ifcopenshell.entity_instance",
        vertical_layout: Optional["ifcopenshell.entity_instance"] = None,
    ) -> List[dict]:
        """Reverse-engineer PVI positions from IFC vertical alignment segments.

        Reconstructs the original PVI table from CONSTANTGRADIENT and
        PARABOLICARC IfcAlignmentVerticalSegment entities. The PVI for a
        PARABOLICARC is at the tangent intersection: station = BVC + L/2,
        elevation = BVC_elevation + g1 * (L/2).

        Args:
            alignment: The IfcAlignment entity (used to resolve the default
                vertical layout when ``vertical_layout`` is None, and for
                error messages).
            vertical_layout: Explicit IfcAlignmentVertical to read from
                (spec 2.1's multi-vertical selector) -- lets a caller target
                a design-alternative vertical nested on a CHILD alignment,
                which ``align_api.get_vertical_layout(alignment)`` (a
                first-match scan of ``alignment``'s own nest) would never
                find. None (the default) preserves the original behavior:
                resolve the vertical nested directly on ``alignment``.

        Returns:
            List of dicts, each containing:
            - "station": float — distance along horizontal alignment
            - "elevation": float — elevation at PVI
            - "curve_length": float — vertical curve length (0 for endpoints)

        Raises:
            ValueError: If no vertical layout can be resolved, or it has no
                real segments
        """
        import ifcopenshell.api.alignment as align_api

        v_layout = vertical_layout if vertical_layout is not None else align_api.get_vertical_layout(alignment)
        if v_layout is None:
            raise ValueError(f"Alignment #{alignment.id()} has no vertical layout")

        segments = align_api.get_layout_segments(v_layout)
        if not segments:
            raise ValueError(f"Alignment #{alignment.id()} has no vertical segments")

        real_segments = [seg for seg in segments if not cls.is_zero_length_segment(seg)]
        if not real_segments:
            raise ValueError(f"Alignment #{alignment.id()} has no real vertical segments")

        pvis = []

        # First PVI: start of first real segment
        first_dp = real_segments[0].DesignParameters
        pvis.append(
            {
                "station": float(first_dp.StartDistAlong),
                "elevation": float(first_dp.StartHeight),
                "curve_length": 0.0,
            }
        )

        # Interior PVIs: one per PARABOLICARC segment
        for seg in real_segments:
            dp = seg.DesignParameters
            if not dp.is_a("IfcAlignmentVerticalSegment"):
                continue
            if dp.PredefinedType != "PARABOLICARC":
                continue
            horizontal_length = float(dp.HorizontalLength)
            # PVI is at the tangent intersection: BVC + L/2
            pvi_station = float(dp.StartDistAlong) + horizontal_length / 2.0
            # Elevation at PVI = BVC elevation extended by back tangent grade
            pvi_elevation = float(dp.StartHeight) + float(dp.StartGradient) * (horizontal_length / 2.0)
            pvis.append(
                {
                    "station": pvi_station,
                    "elevation": pvi_elevation,
                    "curve_length": horizontal_length,
                }
            )

        # Last PVI: end of last real segment
        last_dp = real_segments[-1].DesignParameters
        last_station = float(last_dp.StartDistAlong) + float(last_dp.HorizontalLength)
        # Elevation at end = StartHeight + (g1 + g2) / 2 * L (works for both types)
        last_elevation = float(last_dp.StartHeight) + (
            (float(last_dp.StartGradient) + float(last_dp.EndGradient)) / 2.0 * float(last_dp.HorizontalLength)
        )
        if abs(last_station - pvis[-1]["station"]) > 1e-6:
            pvis.append(
                {
                    "station": last_station,
                    "elevation": last_elevation,
                    "curve_length": 0.0,
                }
            )

        return pvis

    @classmethod
    def create_pvi_edit_empties(
        cls,
        alignment: "ifcopenshell.entity_instance",
        pvis: List[dict],
    ) -> List[bpy.types.Object]:
        """Create EMPTY objects at PVI locations for vertical profile editing.

        Empties are placed in profile space: X=station, Y=0, Z=elevation.
        This represents the vertical alignment as a station-elevation diagram.
        Users should work in Front Orthographic view to move PVIs.

        Args:
            alignment: The IfcAlignment entity
            pvis: List of PVI dicts from back_calculate_pvis_from_vertical()

        Returns:
            List of created Blender EMPTY objects, sorted by index
        """
        alignment_obj = tool.Ifc.get_object(alignment)
        if alignment_obj is None:
            return []

        collection = (
            alignment_obj.users_collection[0] if alignment_obj.users_collection else bpy.context.scene.collection
        )
        alignment_id = alignment.id()
        empties = []

        for i, pvi in enumerate(pvis):
            station = float(pvi["station"])
            elevation = float(pvi["elevation"])
            curve_length = float(pvi.get("curve_length", 0.0))

            name = f"PVI.{i + 1:03d}"
            empty = bpy.data.objects.new(name, None)
            empty.empty_display_type = "SPHERE"
            empty.empty_display_size = 2.0
            # Profile space: X = station, Y = 0, Z = elevation
            empty.location = (station, 0.0, elevation)

            empty["civil_is_pvi_empty"] = True
            empty["civil_pvi_index"] = i
            empty["civil_pvi_curve_length"] = curve_length
            empty["civil_alignment_id"] = alignment_id

            empty.parent = alignment_obj
            collection.objects.link(empty)
            empties.append(empty)

        return empties

    @classmethod
    def get_pvi_edit_empties(cls, alignment_id: int) -> List[bpy.types.Object]:
        """Find all PVI EMPTY objects for a given alignment.

        Args:
            alignment_id: The IFC ID of the alignment being edited

        Returns:
            List of PVI EMPTY objects, sorted by pvi_index
        """
        empties = [
            obj
            for obj in bpy.data.objects
            if obj.get("civil_is_pvi_empty") and obj.get("civil_alignment_id") == alignment_id
        ]
        empties.sort(key=lambda e: e.get("civil_pvi_index", 0))
        return empties

    @classmethod
    def remove_pvi_edit_empties(cls, alignment_id: int) -> int:
        """Remove all PVI EMPTY objects for a given alignment.

        Args:
            alignment_id: The IFC ID of the alignment being edited

        Returns:
            Number of objects removed
        """
        empties = cls.get_pvi_edit_empties(alignment_id)
        for empty in empties:
            bpy.data.objects.remove(empty, do_unlink=True)
        return len(empties)

    @classmethod
    def collect_pvis_from_empties_vertical(cls, alignment_id: int) -> Tuple[List[Tuple[float, float]], List[float]]:
        """Gather current PVI positions from EMPTY objects.

        Reads the profile-space positions of PVI empties (X=station, Z=elevation)
        and assembles them for layout_vertical_by_pvi_method.

        Args:
            alignment_id: The IFC ID of the alignment being edited

        Returns:
            Tuple of:
            - vpoints: List of (station, elevation) tuples
            - lengths: List of curve lengths for interior PVIs only (not first/last)
        """
        empties = cls.get_pvi_edit_empties(alignment_id)

        if len(empties) < 2:
            return ([], [])

        vpoints = []
        lengths = []

        for i, empty in enumerate(empties):
            station = empty.location.x  # Profile space: X = station
            elevation = empty.location.z  # Profile space: Z = elevation
            vpoints.append((station, elevation))

            if 0 < i < len(empties) - 1:
                curve_length = float(empty.get("civil_pvi_curve_length", 0.0))
                lengths.append(curve_length)

        return (vpoints, lengths)

    # =========================================================================
    # PI Extraction from IFC Segments
    # =========================================================================

    @classmethod
    def _get_segment_vertices_in_model_units(
        cls, ifc_file: "ifcopenshell.file", segment: "ifcopenshell.entity_instance"
    ):
        """Get segment control points (Start, End, TI, NI) in model units.

        Wraps ifcopenshell.api.alignment.segment_vertices() with:
        - Backward-compatible fallback for segments without Axis/Segment
          representation (falls back to IfcCurveSegment via get_mapped_segments)
        - Unit conversion (geometry engine returns SI; we need model units)

        Args:
            ifc_file: The IFC file
            segment: An IfcAlignmentSegment entity

        Returns:
            Tuple of (start, end, ti, ni) where each is (x, y) in model units,
            or None for ti/ni when lines are parallel.
            Returns None if segment cannot be evaluated.
        """
        import ifcopenshell.api.alignment as align_api
        import ifcopenshell.util.unit

        unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc_file)

        def convert(point):
            if point is None:
                return None
            return (point[0] / unit_scale, point[1] / unit_scale)

        result = align_api.segment_vertices(ifc_file, segment)
        if result is None:
            return None
        start, end, ti, ni = result

        return (convert(start), convert(end), convert(ti), convert(ni))

    @classmethod
    def extract_pis_from_segments(cls, segments):
        """Extract PI data from IFC alignment segments.

        Uses ifcopenshell.api.alignment.segment_vertices() to extract
        PI (tangent intersection) points from segment geometry.

        Args:
            segments: List of IfcAlignmentSegment entities

        Returns:
            List of dicts with keys: e, n, pi_type, radius
        """
        ifc_file = tool.Ifc.get()

        # Filter out zero-length terminal segments
        real_segments = [seg for seg in segments if not cls.is_zero_length_segment(seg)]
        if not real_segments:
            return []

        # Get vertices for all segments
        seg_vertices = [cls._get_segment_vertices_in_model_units(ifc_file, seg) for seg in real_segments]

        pis = []

        # First PI: start of first segment
        if seg_vertices[0] is not None:
            start_pt = seg_vertices[0][0]
            pis.append({"e": start_pt[0], "n": start_pt[1], "pi_type": "ENDPOINT", "radius": 0.0})

        # Process interior PIs
        prev_is_line = True
        for i, (seg, verts) in enumerate(zip(real_segments, seg_vertices)):
            if verts is None:
                prev_is_line = False
                continue

            start, end, ti, ni = verts
            dp = seg.DesignParameters

            if ti is not None:
                # Curve segment: TI is the PI
                radius = abs(float(dp.StartRadiusOfCurvature or dp.EndRadiusOfCurvature or 0))
                pis.append({"e": ti[0], "n": ti[1], "pi_type": "CURVE", "radius": radius})
                prev_is_line = False
            else:
                # Line segment: if previous was also a line, connection = tangent PI
                if i > 0 and prev_is_line:
                    pis.append({"e": start[0], "n": start[1], "pi_type": "TANGENT", "radius": 0.0})
                prev_is_line = True

        # Last PI: end of last segment
        if seg_vertices[-1] is not None:
            end_pt = seg_vertices[-1][1]
            if pis:
                last = pis[-1]
                dist = ((end_pt[0] - last["e"]) ** 2 + (end_pt[1] - last["n"]) ** 2) ** 0.5
                if dist > 0.001:
                    pis.append({"e": end_pt[0], "n": end_pt[1], "pi_type": "ENDPOINT", "radius": 0.0})
            else:
                pis.append({"e": end_pt[0], "n": end_pt[1], "pi_type": "ENDPOINT", "radius": 0.0})

        return pis

    # =========================================================================
    # IFC API Wrappers (for core layer delegation)
    # =========================================================================

    @classmethod
    def get_vertical_layout(cls, alignment: "ifcopenshell.entity_instance"):
        """Get the IfcAlignmentVertical layout from an alignment.

        Args:
            alignment: The IfcAlignment entity

        Returns:
            The IfcAlignmentVertical entity, or None
        """
        import ifcopenshell.api.alignment as align_api

        return align_api.get_vertical_layout(alignment)

    @classmethod
    def add_vertical_layout(cls, alignment: "ifcopenshell.entity_instance") -> "ifcopenshell.entity_instance":
        """Add a new IfcAlignmentVertical layout to an alignment.

        Handles IFC Concept Template 4.1.4.4.1.1 (first vertical) vs.
        4.1.4.4.1.2 (reusing horizontal for subsequent verticals).

        Args:
            alignment: The IfcAlignment entity

        Returns:
            The newly created IfcAlignmentVertical entity
        """
        import ifcopenshell.api.alignment as align_api

        ifc_file = tool.Ifc.get()
        return align_api.add_vertical_layout(ifc_file, alignment)

    @classmethod
    def layout_vertical_by_pvi_method(
        cls,
        layout: "ifcopenshell.entity_instance",
        vpoints: list,
        lengths: list,
    ):
        """Add segments to a vertical layout using the PVI method.

        Creates CONSTANTGRADIENT and PARABOLICARC segments from a series
        of PVI (Point of Vertical Intersection) points.

        Args:
            layout: The IfcAlignmentVertical layout
            vpoints: List of (station, elevation) pairs — includes start and end
            lengths: List of parabolic curve lengths for each interior PVI
                     (must have len(vpoints) - 2 entries)
        """
        import ifcopenshell.api.alignment as align_api

        ifc_file = tool.Ifc.get()
        align_api.layout_vertical_alignment_by_pi_method(ifc_file, layout, vpoints, lengths)

    @classmethod
    def get_horizontal_layout(cls, alignment: "ifcopenshell.entity_instance"):
        """Get the IfcAlignmentHorizontal layout from an alignment.

        Args:
            alignment: The IfcAlignment entity

        Returns:
            The IfcAlignmentHorizontal entity, or None
        """
        import ifcopenshell.api.alignment as align_api

        return align_api.get_horizontal_layout(alignment)

    # =========================================================================
    # Alignment Evaluation — 3D Combination (D3)
    # =========================================================================

    @staticmethod
    def _normalize3(vec) -> Tuple[float, float, float]:
        """Return ``vec`` (any 3-indexable) as a unit vector tuple.

        Returns the zero vector if the magnitude is degenerate.
        """
        x, y, z = float(vec[0]), float(vec[1]), float(vec[2])
        magnitude = math.sqrt(x * x + y * y + z * z)
        if magnitude < 1e-12:
            return (0.0, 0.0, 0.0)
        return (x / magnitude, y / magnitude, z / magnitude)

    @classmethod
    def get_alignment_curve(cls, alignment: "ifcopenshell.entity_instance"):
        """Return the geometric representation curve for an alignment.

        Delegates to the alignment API. The curve type reflects which layouts
        are present:
        - IfcCompositeCurve — horizontal only
        - IfcGradientCurve — horizontal + vertical (3D, elevation baked in)
        - IfcSegmentedReferenceCurve — horizontal + vertical + cant

        Args:
            alignment: The IfcAlignment entity

        Returns:
            The representation curve, or None if the alignment has none.
        """
        import ifcopenshell.api.alignment as align_api

        return align_api.get_curve(alignment)

    @classmethod
    def get_alignment_length(cls, alignment: "ifcopenshell.entity_instance") -> Optional[float]:
        """Total length (model units) of the horizontal alignment domain.

        Sums the SegmentLength of every horizontal IfcAlignmentSegment (the
        mandatory zero-length terminator contributes 0). This is the upper
        bound of the distance-along domain that can be evaluated.

        Args:
            alignment: The IfcAlignment entity

        Returns:
            Total length, or None if there is no horizontal layout.
        """
        import ifcopenshell.api.alignment as align_api

        h_layout = align_api.get_horizontal_layout(alignment)
        if h_layout is None:
            return None
        total = 0.0
        for rel in getattr(h_layout, "IsNestedBy", []) or []:
            for segment in rel.RelatedObjects or []:
                if segment.is_a() == "IfcAlignmentSegment" and segment.DesignParameters:
                    length = getattr(segment.DesignParameters, "SegmentLength", None)
                    if length:
                        total += float(length)
        return total

    @classmethod
    def _evaluate_curve_at_distance(cls, curve, distance_along: float, unit_scale: float):
        """Evaluate the geometry engine on ``curve`` at a distance-along.

        Shared low-level path for evaluate_alignment_at_station and the 3D
        centerline sampler. Handles the SI unit convention: the engine's
        parameter and reported translation are in SI, so the model-unit
        distance is scaled up before evaluation and the position scaled back.

        Args:
            curve: An IfcCompositeCurve / IfcGradientCurve / IfcSegmentedReferenceCurve
            distance_along: Distance along the curve, in model units
            unit_scale: model->SI scale from ifcopenshell.util.unit

        Returns:
            (position, tangent, normal, up) all in model units, or None.
        """
        import ifcopenshell.api.alignment as align_api

        try:
            # evaluate_representation returns a transposed 4x4 transform:
            #   row 0 = tangent, row 1 = normal, row 2 = up, row 3 = position.
            # The engine parameter and translation are SI; basis rows are
            # orthonormal (unit-independent) direction vectors.
            matrix = align_api.evaluate_representation(curve, distance_along * unit_scale)
        except (RuntimeError, ValueError, NotImplementedError):
            return None
        if matrix is None:
            return None

        position = (
            float(matrix[3, 0]) / unit_scale,
            float(matrix[3, 1]) / unit_scale,
            float(matrix[3, 2]) / unit_scale,
        )
        tangent = cls._normalize3(matrix[0, :3])
        normal = cls._normalize3(matrix[1, :3])
        up = cls._normalize3(matrix[2, :3])
        return position, tangent, normal, up

    @classmethod
    def evaluate_alignment_at_station(
        cls, alignment: "ifcopenshell.entity_instance", station: float
    ) -> Optional[AlignmentPoint]:
        """Evaluate 3D position and orientation frame at a station.

        This is the keystone query for the road-design pipeline. Cross-section
        placement, corridor mesh generation, terrain sampling, and daylight
        calculations all build on it.

        The IfcOpenShell geometry engine is evaluated directly on the
        alignment's representation curve (consistent with the project's
        "use the geometry engine, not manual trigonometry" principle):
        - When a vertical layout exists the curve is an IfcGradientCurve, so
          the returned position is a true 3D point with design elevation.
        - For a horizontal-only alignment the curve is an IfcCompositeCurve
          and Z is 0.0.

        Args:
            alignment: The IfcAlignment entity
            station: Station value (start station + distance along)

        Returns:
            An AlignmentPoint in model units, or None if the alignment has no
            evaluatable representation or the station is outside its domain.
            (The engine extrapolates beyond the ends, so out-of-domain
            stations are rejected explicitly rather than returning garbage.)
        """
        import ifcopenshell.api.alignment as align_api
        import ifcopenshell.util.unit

        curve = align_api.get_curve(alignment)
        if curve is None:
            return None
        if curve.is_a() not in ("IfcCompositeCurve", "IfcGradientCurve", "IfcSegmentedReferenceCurve"):
            # A layout-less alignment (bare polyline) cannot be parametrically evaluated.
            return None

        ifc_file = tool.Ifc.get()
        # Station -> distance along the horizontal alignment (model units).
        # None means the station falls inside a forward (gap) station equation
        # (spec 4.3) -- there is no physical point on the alignment for it.
        distance_along = align_api.distance_along_from_station(ifc_file, alignment, station)
        if distance_along is None or distance_along < -1e-9:
            return None  # station precedes the start of the alignment, or is an equation gap

        # Reject stations beyond the end (engine would silently extrapolate).
        total_length = cls.get_alignment_length(alignment)
        if total_length is not None and distance_along > total_length + 1e-6 * max(1.0, total_length):
            return None

        unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc_file)
        evaluated = cls._evaluate_curve_at_distance(curve, distance_along, unit_scale)
        if evaluated is None:
            return None
        position, tangent, normal, up = evaluated

        # Vertical grade (rise/run) derived from the tangent vector.
        horizontal_run = math.hypot(tangent[0], tangent[1])
        grade = (tangent[2] / horizontal_run) if horizontal_run > 1e-9 else 0.0

        return AlignmentPoint(
            station=float(station),
            position=position,
            tangent=tangent,
            normal=normal,
            up=up,
            grade=grade,
        )

    @classmethod
    def create_alignment(cls, name: str, start_station: float = 0.0) -> "ifcopenshell.entity_instance":
        """Create a full IfcAlignment with horizontal layout via the alignment API.

        Creates the complete IFC structure: IfcAlignment, IfcAlignmentHorizontal,
        stationing referent, geometric representation, and zero-length terminal.
        Also creates the Blender object hierarchy.

        Args:
            name: The alignment name
            start_station: Starting station value (default 0.0)

        Returns:
            The created IfcAlignment entity
        """
        import ifcopenshell.api.alignment as align_api

        ifc_file = tool.Ifc.get()
        alignment = align_api.create(ifc_file, name=name, start_station=start_station)
        cls.create_hierarchy_for_alignment(alignment)
        return alignment

    @classmethod
    def add_horizontal_layout_to_alignment(
        cls, alignment: "ifcopenshell.entity_instance"
    ) -> "ifcopenshell.entity_instance":
        """Add an IfcAlignmentHorizontal layout to a bare IfcAlignment.

        Creates the nested horizontal layout, zero-length terminal segment,
        and geometric representation using the alignment API. Use this to
        bootstrap an alignment created via Add Element (which has no layouts).

        Args:
            alignment: A bare IfcAlignment entity with no horizontal layout.

        Returns:
            The newly created IfcAlignmentHorizontal entity.
        """
        import ifcopenshell.api.alignment as align_api
        import ifcopenshell.api.nest
        import ifcopenshell.util.alignment
        from ifcopenshell.api.alignment._add_zero_length_segment import (
            _add_zero_length_segment,
        )

        ifc_file = tool.Ifc.get()

        # Create and nest the horizontal layout
        h_layout = ifc_file.createIfcAlignmentHorizontal(GlobalId=ifcopenshell.guid.new())
        ifcopenshell.api.nest.assign_object(ifc_file, related_objects=[h_layout], relating_object=alignment)

        # Create geometric representation (curves) for the alignment
        align_api._create_geometric_representation(ifc_file, alignment)

        # Add stationing referent (required by segment creation API)
        start_station = 0.0
        station_name = ifcopenshell.util.alignment.station_as_string(ifc_file, start_station)
        align_api.add_stationing_referent(ifc_file, alignment, 0.0, start_station, station_name, alignment)

        # Add zero-length terminal segment
        _add_zero_length_segment(ifc_file, h_layout)

        # Add geometric representation to the zero-length segment
        curve = align_api.get_layout_curve(h_layout)
        axis_geom_subcontext = align_api.get_axis_subcontext(ifc_file)
        axis_representation = ifc_file.createIfcShapeRepresentation(
            ContextOfItems=axis_geom_subcontext,
            RepresentationIdentifier="Axis",
            RepresentationType="Segment",
            Items=(curve.Segments[-1],),
        )
        product = ifc_file.createIfcProductDefinitionShape(Representations=(axis_representation,))
        zero_length_segment = h_layout.IsNestedBy[0].RelatedObjects[-1]
        zero_length_segment.ObjectPlacement = alignment.ObjectPlacement
        zero_length_segment.Representation = product

        return h_layout

    @classmethod
    def clear_layout_segments(cls, layout: "ifcopenshell.entity_instance"):
        """Clear the real (non-terminator) segments from a layout.

        The alignment API's PI/PVI layout functions *append* segments and
        expose no clear/remove helper, so editing a layout (PI/PVI recalc, edit
        mode) requires removing the previous segments first. This removes both
        halves of each real segment — the geometric IfcCurveSegment in the
        layout's representation curve and the semantic IfcAlignmentSegment —
        while preserving the layout entity and its mandatory zero-length
        terminator (which the layout functions then update in place).

        Args:
            layout: The IFC layout entity (IfcAlignmentHorizontal/Vertical/Cant)
        """
        import ifcopenshell.api.alignment as align_api
        import ifcopenshell.api.root
        import ifcopenshell.util.element

        ifc_file = tool.Ifc.get()

        # 1) Remove the geometric curve segments (keep the zero-length terminator).
        curve = align_api.get_layout_curve(layout)
        if curve is not None and getattr(curve, "Segments", None):
            kept_curve_segments = []
            dropped_curve_segments = []
            for curve_segment in curve.Segments:
                segment_length = curve_segment.SegmentLength
                value = float(getattr(segment_length, "wrappedValue", segment_length))
                (kept_curve_segments if abs(value) < 1e-6 else dropped_curve_segments).append(curve_segment)
            curve.Segments = kept_curve_segments
            for curve_segment in dropped_curve_segments:
                ifcopenshell.util.element.remove_deep2(ifc_file, curve_segment)

        # 2) Remove the semantic IfcAlignmentSegments (keep the terminator).
        dropped_segments = []
        for rel in getattr(layout, "IsNestedBy", []) or []:
            kept_related = []
            for segment in rel.RelatedObjects or []:
                if segment.is_a("IfcAlignmentSegment") and not cls.is_zero_length_segment(segment):
                    dropped_segments.append(segment)
                else:
                    kept_related.append(segment)
            rel.RelatedObjects = kept_related
        for segment in dropped_segments:
            ifcopenshell.api.root.remove_product(ifc_file, product=segment)

    @classmethod
    def layout_by_pi_method(cls, layout: "ifcopenshell.entity_instance", hpoints: list, radii: list):
        """Add segments to a horizontal layout using the PI method.

        Args:
            layout: The IfcAlignmentHorizontal layout
            hpoints: List of (E, N) coordinate pairs for PIs
            radii: List of curve radii for interior PIs
        """
        import ifcopenshell.api.alignment as align_api

        ifc_file = tool.Ifc.get()
        align_api.layout_horizontal_alignment_by_pi_method(ifc_file, layout, hpoints, radii)

    # =========================================================================
    # Zero-Length Segment Utilities
    # =========================================================================

    @classmethod
    def is_zero_length_segment(cls, segment: "ifcopenshell.entity_instance") -> bool:
        """Check if a segment is a zero-length terminator segment.

        Zero-length segments are required by IFC to mark the end of an alignment
        but should be invisible to users in the UI.

        Args:
            segment: The IfcAlignmentSegment entity

        Returns:
            True if this is a zero-length segment
        """
        if not hasattr(segment, "DesignParameters") or not segment.DesignParameters:
            return False

        dp = segment.DesignParameters

        # Check based on segment type
        if dp.is_a("IfcAlignmentHorizontalSegment"):
            return abs(dp.SegmentLength) < 1e-6
        elif dp.is_a("IfcAlignmentVerticalSegment"):
            return abs(dp.HorizontalLength) < 1e-6
        elif dp.is_a("IfcAlignmentCantSegment"):
            return abs(dp.HorizontalLength) < 1e-6

        return False

    @classmethod
    def layout_has_real_segments(cls, layout: "ifcopenshell.entity_instance") -> bool:
        """Check if a layout has any real (non-zero-length) segments.

        An empty layout only has the mandatory zero-length terminator segment.

        Args:
            layout: The IFC layout entity (IfcAlignmentHorizontal, etc.)

        Returns:
            True if the layout has at least one real segment
        """
        for rel in getattr(layout, "IsNestedBy", []) or []:
            for segment in rel.RelatedObjects or []:
                if segment.is_a("IfcAlignmentSegment"):
                    if not cls.is_zero_length_segment(segment):
                        return True
        return False

    # =========================================================================
    # Blender Object Creation
    # =========================================================================

    @classmethod
    def create_object_for_alignment(cls, alignment: ifcopenshell.entity_instance) -> Optional[bpy.types.Object]:
        """Create a Blender object for an IFC alignment and link it properly.

        This follows Bonsai's pattern for creating Blender representations:
        1. Create a Blender Empty object
        2. Link it to the IFC element via tool.Ifc.link()
        3. Assign it to the appropriate collection via tool.Collector.assign()

        Args:
            alignment: The IFC alignment entity

        Returns:
            The created Blender object, or existing one if already linked
        """
        # Check if a Blender object already exists for this IFC element
        existing_obj = tool.Ifc.get_object(alignment)
        if existing_obj:
            return existing_obj

        # Create Blender Empty object with naming pattern "IfcClass/Name"
        name = f"IfcAlignment/{alignment.Name or 'Unnamed'}"
        obj = bpy.data.objects.new(name, None)  # None = Empty object
        obj.empty_display_type = "ARROWS"
        obj.empty_display_size = 1.0

        # Link the Blender object to the IFC element (creates bidirectional mapping)
        tool.Ifc.link(alignment, obj)

        # Assign to appropriate collection (Bonsai handles collection hierarchy)
        tool.Collector.assign(obj)

        return obj

    @classmethod
    def create_object_for_layout(
        cls, layout_entity: ifcopenshell.entity_instance, parent_obj: Optional[bpy.types.Object] = None
    ) -> Optional[bpy.types.Object]:
        """Create a Blender object for an IFC alignment layout.

        Args:
            layout_entity: The IFC layout entity (IfcAlignmentHorizontal, etc.)
            parent_obj: The parent Blender object (IfcAlignment object)

        Returns:
            The created Blender object, or existing one if already linked
        """
        # Check if a Blender object already exists for this IFC element
        existing_obj = tool.Ifc.get_object(layout_entity)
        if existing_obj:
            return existing_obj

        # Determine the layout type from the IFC class
        ifc_class = layout_entity.is_a()
        name = f"{ifc_class}"

        obj = bpy.data.objects.new(name, None)
        obj.empty_display_type = "PLAIN_AXES"
        obj.empty_display_size = 0.5

        # Link to IFC element
        tool.Ifc.link(layout_entity, obj)

        # Set parent relationship in Blender (mirrors IFC nesting)
        if parent_obj:
            obj.parent = parent_obj

        # Assign to same collection as parent (avoid "Unsorted")
        if parent_obj and parent_obj.users_collection:
            parent_obj.users_collection[0].objects.link(obj)
        else:
            tool.Collector.assign(obj)

        return obj

    @classmethod
    def _create_segment_curve(
        cls, segment: "ifcopenshell.entity_instance", index: int, parent_obj: Optional[bpy.types.Object] = None
    ) -> Optional[bpy.types.Object]:
        """Create a Blender curve object for an IFC alignment segment.

        Creates actual curve geometry using IfcOpenShell's geometry engine,
        so the segment can be selected and highlighted in the viewport.

        Zero-length segments (required terminators) are skipped as they should
        be invisible to users.

        Args:
            segment: The IfcAlignmentSegment entity
            index: The segment index (for naming)
            parent_obj: The parent Blender object (layout object)

        Returns:
            The created Blender curve object, or existing one if already linked,
            or None for zero-length segments or geometry failures
        """
        # Skip zero-length segments - they are required terminators but should be invisible
        if cls.is_zero_length_segment(segment):
            return None

        # Check if a Blender object already exists for this IFC element
        existing_obj = tool.Ifc.get_object(segment)
        if existing_obj:
            return existing_obj

        # Get segment parameters for naming
        if not hasattr(segment, "DesignParameters") or not segment.DesignParameters:
            return None

        dp = segment.DesignParameters
        seg_type = getattr(dp, "PredefinedType", "UNKNOWN") or "UNKNOWN"
        name = f"Segment {index + 1} ({seg_type})"

        # Get vertices for this segment using IfcOpenShell's geometry engine
        logger = logging.getLogger("ImportIFC")
        ifc_import_settings = bonsai.bim.import_ifc.IfcImportSettings.factory(bpy.context, None, logger)
        ifc_importer = bonsai.bim.import_ifc.IfcImporter(ifc_import_settings)
        ifc_importer.file = tool.Ifc.get()

        mapped_segments = ifcopenshell.api.alignment.get_mapped_segments(segment)
        tool.Loader.load_settings()
        obj = None
        for curve_segment in mapped_segments:
            if curve_segment is not None:
                geometry = tool.Loader.create_generic_shape(curve_segment)
                # Currently, there may be potentially two IfcCurveSegments, for Helmert
                mesh = ifc_importer.create_mesh(curve_segment, geometry)
                obj = bpy.data.objects.new(f"IfcAlignmentSegment/{name}", mesh)

                # Parent to layout object and assign to same collection
                if parent_obj:
                    obj.parent = parent_obj
                    if parent_obj.users_collection:
                        parent_obj.users_collection[0].objects.link(obj)
                    else:
                        tool.Collector.assign(obj)
                else:
                    tool.Collector.assign(obj)

        # Link the Blender object to the IfcAlignmentSegment (the IfcProduct),
        # not the IfcCurveSegment (geometry). This follows Bonsai's convention
        # of one Blender object per IfcProduct and ensures correct cleanup.
        if obj:
            tool.Ifc.link(segment, obj)

        return obj

    @classmethod
    def create_alignment_from_csv(cls, filepath: str) -> "ifcopenshell.entity_instance":
        """Create alignment(s) from a CSV file via the alignment API.

        The CSV format (see ifcopenshell.api.alignment.create_from_csv) is one
        horizontal row (X,Y,R triples) followed by any number of vertical rows
        (D,Z,L triples) — extra verticals become aggregated child alignments.
        Per IFC 4.1.5.1 alignments cannot be contained in spatial structures,
        so the imported alignment is referenced into every IfcSite instead.
        """
        import ifcopenshell.api.alignment as align_api
        import ifcopenshell.api.spatial

        ifc_file = tool.Ifc.get()
        alignment = align_api.create_from_csv(ifc_file, filepath)
        for site in ifc_file.by_type("IfcSite"):
            ifcopenshell.api.spatial.reference_structure(ifc_file, products=[alignment], relating_structure=site)
        return alignment

    @classmethod
    def get_child_alignments(cls, alignment: "ifcopenshell.entity_instance") -> list:
        """Return child IfcAlignments aggregated under ``alignment``.

        Per IFC CT 4.1.4.4.1.2, an alignment reusing one horizontal for
        several verticals aggregates a child IfcAlignment per extra vertical.
        Returns [] for the common single-vertical case.
        """
        children = []
        for rel in alignment.IsDecomposedBy or []:
            for related in rel.RelatedObjects:
                if related.is_a("IfcAlignment"):
                    children.append(related)
        return children

    @classmethod
    def create_objects_for_referents(cls, alignment: "ifcopenshell.entity_instance") -> int:
        """Create empty objects for IfcReferents nested on ``alignment``.

        Returns the number of referent objects created.
        """
        count = 0
        for rel in alignment.IsNestedBy or []:
            for referent in rel.RelatedObjects:
                if referent.is_a("IfcReferent"):
                    referent_obj = bpy.data.objects.new(tool.Loader.get_name(referent), None)
                    tool.Geometry.link(referent, referent_obj)
                    tool.Collector.assign(referent_obj, should_clean_users_collection=False)
                    count += 1
        return count

    @classmethod
    def create_hierarchy_for_alignment(cls, alignment: "ifcopenshell.entity_instance") -> Optional[bpy.types.Object]:
        """Create the full Blender object hierarchy for an alignment.

        Creates:
        - IfcAlignment object (root)
        - IfcAlignmentHorizontal object (child)
        - IfcAlignmentVertical object (child, if present)
        - IfcAlignmentCant object (child, if present)
        - Segment objects under each layout

        Args:
            alignment: The IFC alignment entity

        Returns:
            The root alignment Blender object
        """
        # Create the alignment object
        alignment_obj = cls.create_object_for_alignment(alignment)
        if not alignment_obj:
            return None

        # Get nested layouts via IfcRelNests
        layouts = []
        for rel in getattr(alignment, "IsNestedBy", []) or []:
            for obj in rel.RelatedObjects or []:
                if obj.is_a() in ("IfcAlignmentHorizontal", "IfcAlignmentVertical", "IfcAlignmentCant"):
                    layouts.append(obj)

        # Create Blender objects for each layout and its segments
        for layout in layouts:
            layout_obj = cls.create_object_for_layout(layout, alignment_obj)
            if layout_obj:
                cls.create_objects_for_layout_segments(layout, layout_obj)

        return alignment_obj

    @classmethod
    def create_objects_for_layout_segments(
        cls, layout: "ifcopenshell.entity_instance", layout_obj: bpy.types.Object
    ) -> List[bpy.types.Object]:
        """Create Blender curve objects for all segments in a layout.

        Each segment becomes its own selectable curve object, using IfcOpenShell's
        geometry engine to generate accurate geometry for all segment types
        (LINE, CIRCULARARC, CLOTHOID, spirals, etc.).

        Args:
            layout: The IFC layout entity (IfcAlignmentHorizontal, etc.)
            layout_obj: The parent Blender object for the layout

        Returns:
            List of created Blender curve objects for each segment
        """
        result_objs = []

        # Create individual curve objects for each segment
        # Each segment is its own selectable object with actual geometry
        visible_index = 0
        for rel in getattr(layout, "IsNestedBy", []) or []:
            for segment in rel.RelatedObjects or []:
                if segment.is_a() == "IfcAlignmentSegment":
                    seg_obj = cls._create_segment_curve(segment, visible_index, layout_obj)
                    if seg_obj:
                        result_objs.append(seg_obj)
                    visible_index += 1  # Always increment for consistent numbering

        return result_objs

    # =========================================================================
    # 3D Combined Alignment Visualization (D3)
    # =========================================================================

    CENTERLINE_3D_TAG = "civil_3d_centerline_alignment_id"

    @classmethod
    def create_3d_alignment_object(
        cls, alignment: "ifcopenshell.entity_instance", distance_interval: float = 5.0
    ) -> Optional[bpy.types.Object]:
        """Create/refresh a Blender polyline of the draped 3D centerline.

        Samples the alignment's representation curve with the geometry engine
        at ``distance_interval`` spacing — an IfcGradientCurve when a vertical
        layout exists, giving the true 3D profile draped over the horizontal
        alignment. The result is a single mesh object parented to the alignment
        object.

        This is the D3 "3D curve visualization": distinct from the per-segment
        objects, whose vertical-layout geometry lives in profile space rather
        than draped in real XYZ. Sampling via evaluate_representation (rather
        than the engine's generate_vertices) keeps a single evaluation code
        path and avoids engine-version-specific piecewise-step settings.
        Calling it again rebuilds the object.

        Args:
            alignment: The IfcAlignment entity
            distance_interval: Spacing between sampled vertices (model units)

        Returns:
            The created mesh object, or None if the alignment has no
            evaluatable representation.
        """
        import ifcopenshell.api.alignment as align_api
        import ifcopenshell.util.unit

        curve = align_api.get_curve(alignment)
        if curve is None or curve.is_a() not in (
            "IfcCompositeCurve",
            "IfcGradientCurve",
            "IfcSegmentedReferenceCurve",
        ):
            return None

        total_length = cls.get_alignment_length(alignment)
        if not total_length or total_length <= 0:
            return None

        ifc_file = tool.Ifc.get()
        unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc_file)
        interval = max(float(distance_interval), 1e-6)

        # Sample distance-along over [0, length], always including the endpoint.
        distances = []
        distance = 0.0
        while distance < total_length:
            distances.append(distance)
            distance += interval
        distances.append(total_length)

        coords = []
        for distance in distances:
            evaluated = cls._evaluate_curve_at_distance(curve, distance, unit_scale)
            if evaluated is not None:
                # evaluate returns model/project units; Blender mesh space is
                # metres (1 BU = 1 m), so scale up to overlay the segment objects.
                position = evaluated[0]
                coords.append((position[0] * unit_scale, position[1] * unit_scale, position[2] * unit_scale))
        if len(coords) < 2:
            return None

        # Idempotent: drop any prior centerline for this alignment first.
        cls.remove_3d_alignment_object(alignment)

        mesh = bpy.data.meshes.new(f"IfcAlignment/{alignment.Name or 'Unnamed'}/3D Centerline")
        edges = [(i, i + 1) for i in range(len(coords) - 1)]
        mesh.from_pydata(coords, edges, [])
        mesh.update()

        obj = bpy.data.objects.new(f"{alignment.Name or 'Alignment'} 3D Centerline", mesh)
        obj[cls.CENTERLINE_3D_TAG] = alignment.id()

        alignment_obj = tool.Ifc.get_object(alignment)
        if alignment_obj:
            obj.parent = alignment_obj
            if alignment_obj.users_collection:
                alignment_obj.users_collection[0].objects.link(obj)
            else:
                tool.Collector.assign(obj)
        else:
            tool.Collector.assign(obj)

        return obj

    @classmethod
    def remove_3d_alignment_object(cls, alignment: "ifcopenshell.entity_instance") -> int:
        """Remove the 3D centerline helper object for an alignment, if any.

        Returns the number of objects removed (normally 0 or 1).
        """
        alignment_id = alignment.id()
        removed = 0
        for obj in list(bpy.data.objects):
            if obj.get(cls.CENTERLINE_3D_TAG) == alignment_id:
                cls._remove_blender_object(obj)
                removed += 1
        return removed

    # =========================================================================
    # Profile View — Terrain & Design Sampling (D2)
    # =========================================================================

    @classmethod
    def get_alignment_start_station(cls, alignment: "ifcopenshell.entity_instance") -> float:
        """Return the alignment's start station (model units).

        Derived from the API's distance_along_from_station, which returns
        (station - start_station): evaluating at station 0 yields -start, so the
        start station is its negation. Robust to API renames and to alignments
        whose stationing does not begin at 0.
        """
        import ifcopenshell.api.alignment as align_api

        ifc_file = tool.Ifc.get()
        return -float(align_api.distance_along_from_station(ifc_file, alignment, 0.0))

    @classmethod
    def format_station(cls, station: float) -> str:
        """Format a station (project units) in project stationing notation.

        Delegates to ifcopenshell.util.alignment.station_as_string, which
        derives the notation from the project LENGTHUNIT: imperial projects
        read ``100+50.00``, metric projects ``10+050.000``. Falls back to a
        plain number when no IFC file is open (e.g. dialog previews before a
        project exists).
        """
        import ifcopenshell.util.alignment

        ifc_file = tool.Ifc.get()
        if ifc_file is None:
            return f"{float(station):.2f}"
        return ifcopenshell.util.alignment.station_as_string(ifc_file, float(station))

    @classmethod
    def _station_samples(cls, start_station: float, length: float, interval: float):
        """Yield stations from start..start+length inclusive at ``interval``."""
        interval = max(float(interval), 1e-6)
        distance = 0.0
        while distance < length:
            yield start_station + distance
            distance += interval
        yield start_station + length

    @classmethod
    def sample_design_profile(cls, alignment: "ifcopenshell.entity_instance", interval: float = 10.0):
        """Sample the design profile (station, elevation) along the alignment.

        Evaluates the combined alignment at each station and takes the Z of the
        resulting 3D point (the design grade). For a horizontal-only alignment
        every elevation is 0.0. Returns a list of (station, elevation) in model
        units.
        """
        length = cls.get_alignment_length(alignment)
        if not length or length <= 0:
            return []
        start = cls.get_alignment_start_station(alignment)
        points = []
        for station in cls._station_samples(start, length, interval):
            evaluated = cls.evaluate_alignment_at_station(alignment, station)
            if evaluated is not None:
                points.append((station, evaluated.position[2]))
        return points

    @classmethod
    def sample_terrain_profile(
        cls, alignment: "ifcopenshell.entity_instance", terrain_obj: "bpy.types.Object", interval: float = 10.0
    ):
        """Sample existing-ground elevation under the alignment centerline.

        For each station the horizontal (x, y) centerline position is computed
        and the terrain mesh is ray-cast vertically to find the ground
        elevation. Returns a list of (station, ground_elevation) in model units;
        stations with no terrain hit are skipped (the centerline can run beyond
        the terrain extent).

        The terrain BVH is built in Blender world space (metres); the alignment
        position from evaluate is in IFC project units, so it is scaled up by
        unit_scale before the vertical ray-cast, and the returned ground
        elevation is scaled back to project units (matching sample_design_profile
        and the PVI markers, so the profile view is unit-consistent).
        """
        import ifcopenshell.util.unit
        from mathutils import Vector
        from mathutils.bvhtree import BVHTree

        if terrain_obj is None or terrain_obj.type != "MESH" or not terrain_obj.data.polygons:
            return []
        length = cls.get_alignment_length(alignment)
        if not length or length <= 0:
            return []

        unit_scale = ifcopenshell.util.unit.calculate_unit_scale(tool.Ifc.get())
        matrix = terrain_obj.matrix_world
        world_verts = [matrix @ v.co for v in terrain_obj.data.vertices]
        polygons = [tuple(p.vertices) for p in terrain_obj.data.polygons]
        if not world_verts or not polygons:
            return []
        bvh = BVHTree.FromPolygons(world_verts, polygons)

        # Cast straight down from above the terrain's highest point.
        max_z = max(v.z for v in world_verts)
        min_z = min(v.z for v in world_verts)
        ray_start_z = max_z + (max_z - min_z) + 1.0
        down = Vector((0.0, 0.0, -1.0))

        start = cls.get_alignment_start_station(alignment)
        points = []
        for station in cls._station_samples(start, length, interval):
            evaluated = cls.evaluate_alignment_at_station(alignment, station)
            if evaluated is None:
                continue
            x, y, _ = evaluated.position  # IFC project units
            # Ray-cast in Blender world metres; report ground in project units.
            location = bvh.ray_cast(Vector((x * unit_scale, y * unit_scale, ray_start_z)), down)[0]
            if location is not None:
                points.append((station, location.z / unit_scale))
        return points

    @classmethod
    def build_profile_view_transform(
        cls,
        design_points,
        terrain_points,
        rect_x: float,
        rect_y: float,
        rect_width: float,
        rect_height: float,
        elevation_pad_fraction: float = 0.1,
        vertical_exaggeration: float = 0.0,
    ) -> Optional[ProfileViewTransform]:
        """Build a ProfileViewTransform fitting the sampled profiles to a rect.

        Station bounds come from the data. Elevation bounds depend on
        ``vertical_exaggeration``:

        - ``0`` (default): auto-fit — bounds hug the data, padded by
          ``elevation_pad_fraction`` of the elevation span so polylines do not
          touch the plot edges.
        - ``> 0``: profile-sheet exaggeration — the vertical scale is locked to
          ``vertical_exaggeration ×`` the horizontal scale (pixels per unit),
          centered on the data's elevation midpoint. Data outside the resulting
          window draws clipped; the axis labels stay true elevations either way.

        Returns None if there is nothing to plot.
        """
        all_points = list(design_points) + list(terrain_points)
        if not all_points:
            return None
        stations = [p[0] for p in all_points]
        elevations = [p[1] for p in all_points]
        station_min, station_max = min(stations), max(stations)

        if vertical_exaggeration > 0 and rect_width > 0:
            station_span = (station_max - station_min) or 1.0
            horizontal_scale = rect_width / station_span  # px per station unit
            vertical_scale = horizontal_scale * vertical_exaggeration
            displayed_span = rect_height / vertical_scale
            elevation_mid = (max(elevations) + min(elevations)) / 2.0
            elevation_min = elevation_mid - displayed_span / 2.0
            elevation_max = elevation_mid + displayed_span / 2.0
        else:
            elevation_span = (max(elevations) - min(elevations)) or 1.0
            pad = elevation_span * elevation_pad_fraction
            elevation_min = min(elevations) - pad
            elevation_max = max(elevations) + pad

        return ProfileViewTransform(
            station_min=station_min,
            station_max=station_max,
            elevation_min=elevation_min,
            elevation_max=elevation_max,
            rect_x=rect_x,
            rect_y=rect_y,
            rect_width=rect_width,
            rect_height=rect_height,
        )

    @classmethod
    def update_pi_properties(cls, props, geometry_result) -> None:
        """Update Blender PropertyGroup with calculated geometry.

        This bridges the pure Python calculation results back to
        the Blender UI properties.

        Args:
            props: The CivilAlignmentProperties PropertyGroup
            geometry_result: PIGeometryResult from core.alignment
        """
        pis = props.pis
        for i, pi in enumerate(pis):
            if i < len(geometry_result.stations):
                pi.station = geometry_result.stations[i]
            if i < len(geometry_result.lengths):
                pi.length_to_next = geometry_result.lengths[i]
            if i < len(geometry_result.directions):
                pi.direction_to_next = geometry_result.directions[i]

    @classmethod
    def _remove_blender_object(cls, obj: bpy.types.Object) -> bool:
        """Safely remove a Blender object and its data.

        Args:
            obj: The Blender object to remove

        Returns:
            True if removed successfully
        """
        # Unlink from IFC if linked
        try:
            tool.Ifc.unlink(obj=obj)
        except Exception:
            pass  # Object might not be linked

        # Store data reference before removing object
        data = obj.data

        # Remove the object
        bpy.data.objects.remove(obj, do_unlink=True)

        # Clean up orphan curve/mesh data
        if data and data.users == 0:
            if isinstance(data, bpy.types.Curve):
                bpy.data.curves.remove(data)
            elif isinstance(data, bpy.types.Mesh):
                bpy.data.meshes.remove(data)

        return True

    @classmethod
    def remove_layout_segment_objects(cls, layout: ifcopenshell.entity_instance) -> int:
        """Remove all Blender objects for segments in a layout.

        Args:
            layout: The IFC layout entity (IfcAlignmentHorizontal, etc.)

        Returns:
            Number of objects removed
        """
        removed_count = 0

        for rel in getattr(layout, "IsNestedBy", []) or []:
            for segment in rel.RelatedObjects or []:
                if segment.is_a() == "IfcAlignmentSegment":
                    obj = tool.Ifc.get_object(segment)
                    if obj and cls._remove_blender_object(obj):
                        removed_count += 1

        return removed_count

    @classmethod
    def remove_alignment_hierarchy(cls, alignment: ifcopenshell.entity_instance) -> int:
        """Remove all Blender objects for an alignment and its children.

        Args:
            alignment: The IFC alignment entity

        Returns:
            Number of objects removed
        """
        removed_count = 0

        # Get nested layouts via IfcRelNests
        for rel in getattr(alignment, "IsNestedBy", []) or []:
            for layout in rel.RelatedObjects or []:
                if layout.is_a() in ("IfcAlignmentHorizontal", "IfcAlignmentVertical", "IfcAlignmentCant"):
                    # Remove segment objects first
                    removed_count += cls.remove_layout_segment_objects(layout)

                    # Remove layout object
                    layout_obj = tool.Ifc.get_object(layout)
                    if layout_obj and cls._remove_blender_object(layout_obj):
                        removed_count += 1

        # Remove alignment object
        alignment_obj = tool.Ifc.get_object(alignment)
        if alignment_obj and cls._remove_blender_object(alignment_obj):
            removed_count += 1

        return removed_count

    # =========================================================================
    # Validation and Safe Wrappers
    # =========================================================================
    # These methods provide pre-validation before calling IfcOpenShell alignment
    # API functions. This prevents issues like orphan layouts (from undo/redo)
    # causing invalid IFC entities (e.g., IfcRelPositions with empty RelatedProducts).
    #
    # The key principle: validate BEFORE operations to prevent invalid data,
    # rather than cleaning up after the fact.

    @classmethod
    def validate_layout_has_parent_alignment(
        cls, layout: "ifcopenshell.entity_instance"
    ) -> Optional["ifcopenshell.entity_instance"]:
        """Check if a layout entity has a valid parent IfcAlignment.

        Orphan layouts (e.g., from undo/redo operations) can cause issues
        when the alignment API tries to create referents, as the code
        expects a parent alignment to exist.

        Args:
            layout: The IFC layout entity (IfcAlignmentHorizontal, etc.)

        Returns:
            The parent IfcAlignment if found, None otherwise
        """
        import ifcopenshell.api.alignment as align_api

        return align_api.get_alignment(layout)

    @classmethod
    def safe_layout_horizontal_by_pi_method(
        cls, ifc_file: "ifcopenshell.file", layout: "ifcopenshell.entity_instance", hpoints: list, radii: list
    ) -> bool:
        """Safely add segments to a horizontal layout using PI method.

        This wrapper validates that the layout has a valid parent alignment
        before calling the IfcOpenShell API. This prevents the creation of
        invalid IfcRelPositions entities.

        Args:
            ifc_file: The IFC file
            layout: The IfcAlignmentHorizontal layout
            hpoints: List of (X, Y) coordinate pairs for PIs
            radii: List of curve radii

        Returns:
            True if successful

        Raises:
            ValueError: If layout has no parent alignment
        """
        import ifcopenshell.api.alignment as align_api

        # Validate layout has a parent alignment - this is the key check
        # that prevents orphan stationing from being created
        alignment = cls.validate_layout_has_parent_alignment(layout)
        if alignment is None:
            raise ValueError(
                f"Layout #{layout.id()} ({layout.is_a()}) has no parent IfcAlignment. "
                "This may be an orphan layout from undo/redo. "
                "Cannot add segments without a valid parent alignment."
            )

        # Now safe to call the API - stationing will be associated with alignment
        align_api.layout_horizontal_alignment_by_pi_method(ifc_file, layout, hpoints, radii)

        return True

    # =========================================================================
    # PI Edit Mode Methods
    # =========================================================================
    # These methods support the PI Edit Mode feature, which allows users to
    # move alignment PIs (Points of Intersection) using Blender's standard
    # transform tools (G key). The workflow is:
    # 1. Back-calculate PI positions from existing IFC segments
    # 2. Create temporary EMPTY objects at each PI location
    # 3. User moves empties with standard Blender tools
    # 4. Collect new positions and regenerate alignment segments

    @classmethod
    def reconstruct_pis_from_horizontal_segments(cls, segment_records: List[dict]) -> List[dict]:
        """Pure-math reconstruction of PI positions -- and, per spec 1.5,
        curve radius plus entry/exit spiral lengths -- from an ORDERED list
        of horizontal segment records. No IFC entities, no geometry engine:
        each record is a plain dict ``{"predefined_type", "start_point"
        (x, y), "start_direction" (radians), "start_radius" (float or
        None), "end_radius" (float or None), "length"}`` -- exactly the
        fields stored directly on ``IfcAlignmentHorizontalSegment``
        (StartPoint, StartDirection, Start/EndRadiusOfCurvature,
        SegmentLength), so ``back_calculate_pis_from_alignment`` can supply
        them straight from DesignParameters attribute reads.

        This mirrors ``solve_horizontal_alignment_by_pi_method`` in reverse:

        - Two consecutive LINE segments meeting with nothing between them
          recover a TANGENT PI at their shared point (no curve).
        - A maximal RUN of non-LINE segments, bounded by LINE segments (or
          the ends of the whole alignment), recovers ONE curve PI. The PI
          point is the intersection of the run's own first segment's
          (start_point, start_direction) -- already colinear with the
          incoming tangent -- and the run's own last segment's END point/
          direction (via ``ifcopenshell.api.alignment.
          compute_horizontal_segment_end``, colinear with the outgoing
          tangent). The run's TYPE SEQUENCE is pattern-matched to recover
          (radius, spiral_in, spiral_out):

              (CIRCULARARC,)                            plain curve
              (CLOTHOID, CIRCULARARC)                    entry spiral only
              (CIRCULARARC, CLOTHOID)                    exit spiral only
              (CLOTHOID, CIRCULARARC, CLOTHOID)          spiral-curve-spiral
              (CLOTHOID, CLOTHOID)                       spiral-spiral (no arc)

        Any other run shape -- most notably TWO OR MORE CIRCULARARC segments
        meeting with no separating LINE, the signature IFC leaves for a
        join_next compound/reverse curve junction (spec 1.6) -- cannot be
        reduced to a single PI's (radius, spiral_in, spiral_out) and raises
        ValueError, per spec 1.2: "Where derivation is ambiguous the
        alignment is edited by segment instead." PI edit mode does not
        round-trip join_next; spec 1.6 curves are joined/unjoined directly
        against the PI table instead (CIVIL_OT_join_curves / _unjoin_curves).

        Returns a list of PI dicts, alignment order, endpoints included:
        ``{"e", "n", "radius", "pi_type", "spiral_in", "spiral_out"}``.

        Raises:
            ValueError: on an irreducible run (see above), or if the
                incoming/outgoing tangents at a curve group do not intersect
                (degenerate geometry).
        """
        import ifcopenshell.api.alignment as align_api

        if not segment_records:
            return []

        def as_hsd(rec: dict):
            return align_api.HorizontalSegmentDefinition(
                start_point=rec["start_point"],
                start_direction=rec["start_direction"],
                start_radius_of_curvature=rec["start_radius"] or 0.0,
                end_radius_of_curvature=rec["end_radius"] or 0.0,
                segment_length=rec["length"],
                predefined_type=rec["predefined_type"],
            )

        def segment_end(rec: dict):
            """(x, y, direction_radians) at the end of ``rec``, computed
            purely from its own parameters -- no geometry engine."""
            return align_api.compute_horizontal_segment_end(as_hsd(rec))

        def ambiguous_run(types: tuple) -> ValueError:
            return ValueError(
                f"Segment sequence {types} at this PI is ambiguous and cannot be reduced to a "
                "single PI's curve parameters (likely a compound or reverse curve junction); "
                "the alignment is edited by segment instead"
            )

        n = len(segment_records)
        pis: List[dict] = []
        start_pt = segment_records[0]["start_point"]
        pis.append(
            {
                "e": start_pt[0],
                "n": start_pt[1],
                "radius": 0.0,
                "pi_type": "ENDPOINT",
                "spiral_in": 0.0,
                "spiral_out": 0.0,
            }
        )

        i = 0
        while i < n:
            rec = segment_records[i]
            if rec["predefined_type"] == "LINE":
                if i + 1 < n and segment_records[i + 1]["predefined_type"] == "LINE":
                    bx, by, _ = segment_end(rec)
                    pis.append(
                        {"e": bx, "n": by, "radius": 0.0, "pi_type": "TANGENT", "spiral_in": 0.0, "spiral_out": 0.0}
                    )
                i += 1
                continue

            j = i
            while j < n and segment_records[j]["predefined_type"] != "LINE":
                j += 1
            group = segment_records[i:j]
            types = tuple(g["predefined_type"] for g in group)

            first, last = group[0], group[-1]
            in_point = first["start_point"]
            in_direction = (math.cos(first["start_direction"]), math.sin(first["start_direction"]))
            out_x, out_y, out_dir_radians = segment_end(last)
            out_direction = (math.cos(out_dir_radians), math.sin(out_dir_radians))

            pi_point = cls.line_intersection_2d(in_point, in_direction, (out_x, out_y), out_direction)
            if pi_point is None:
                raise ValueError(
                    "Could not locate a PI point for this curve -- the incoming and outgoing "
                    "tangents do not intersect; the alignment is edited by segment instead"
                )

            if types == ("CIRCULARARC",):
                (arc,) = group
                radius = abs(arc["start_radius"] or arc["end_radius"] or 0.0)
                spiral_in, spiral_out = 0.0, 0.0
            elif types == ("CLOTHOID", "CIRCULARARC"):
                entry, arc = group
                radius = abs(arc["start_radius"] or arc["end_radius"] or 0.0)
                spiral_in, spiral_out = entry["length"], 0.0
            elif types == ("CIRCULARARC", "CLOTHOID"):
                arc, exitc = group
                radius = abs(arc["start_radius"] or arc["end_radius"] or 0.0)
                spiral_in, spiral_out = 0.0, exitc["length"]
            elif types == ("CLOTHOID", "CIRCULARARC", "CLOTHOID"):
                entry, arc, exitc = group
                radius = abs(arc["start_radius"] or arc["end_radius"] or 0.0)
                spiral_in, spiral_out = entry["length"], exitc["length"]
            elif types == ("CLOTHOID", "CLOTHOID"):
                entry, exitc = group
                radius = abs(entry["end_radius"] or exitc["start_radius"] or 0.0)
                spiral_in, spiral_out = entry["length"], exitc["length"]
            else:
                raise ambiguous_run(types)

            pis.append(
                {
                    "e": pi_point[0],
                    "n": pi_point[1],
                    "radius": radius,
                    "pi_type": "CURVE",
                    "spiral_in": spiral_in,
                    "spiral_out": spiral_out,
                }
            )
            i = j

        final_x, final_y, _ = segment_end(segment_records[-1])
        last_pi = pis[-1]
        dist = math.hypot(final_x - last_pi["e"], final_y - last_pi["n"])
        if dist > 0.001:
            pis.append(
                {
                    "e": final_x,
                    "n": final_y,
                    "radius": 0.0,
                    "pi_type": "ENDPOINT",
                    "spiral_in": 0.0,
                    "spiral_out": 0.0,
                }
            )
        else:
            last_pi["pi_type"] = "ENDPOINT"

        return pis

    @classmethod
    def back_calculate_pis_from_alignment(cls, alignment: "ifcopenshell.entity_instance") -> List[dict]:
        """Reverse-engineer PI positions -- and, per spec 1.5, curve radius
        plus entry/exit spiral lengths -- from IFC alignment segments.

        Reads ``IfcAlignmentHorizontalSegment.DesignParameters`` (StartPoint,
        StartDirection, Start/EndRadiusOfCurvature, SegmentLength) directly
        and delegates to ``reconstruct_pis_from_horizontal_segments`` for the
        pure-math reconstruction -- NO geometry engine evaluation (unlike the
        pre-spec-1.5 implementation, which used
        ``ifcopenshell.api.alignment.segment_vertices()``; that TI-based
        approach cannot correctly locate a PI whose curve has spiral
        transitions, since a spiral's own tangent-at-end is tangent to the
        circular arc, not to the outgoing PI leg). Mirrors
        ``radius_at_station`` / ``back_calculate_cant_points_from_layout``'s
        semantic-only reading pattern.

        Args:
            alignment: The IfcAlignment entity

        Returns:
            List of dicts, each containing:
            - "e": float - Easting coordinate in IFC space
            - "n": float - Northing coordinate in IFC space
            - "radius": float - Curve radius (0 for endpoints/tangent PIs)
            - "pi_type": str - "ENDPOINT", "CURVE", or "TANGENT"
            - "spiral_in": float - entry spiral length (0.0 if none)
            - "spiral_out": float - exit spiral length (0.0 if none)

        Raises:
            ValueError: If the alignment has no horizontal layout or
                segments, or if a run of segments cannot be reduced to a
                single PI's curve parameters (spec 1.2: "Where derivation is
                ambiguous the alignment is edited by segment instead" --
                the signature of a join_next compound/reverse curve
                junction, spec 1.6, which PI edit mode does not round-trip).
        """
        import ifcopenshell.api.alignment as align_api
        import ifcopenshell.util.unit

        ifc_file = tool.Ifc.get()

        # Get horizontal layout
        h_layout = align_api.get_horizontal_layout(alignment)
        if h_layout is None:
            raise ValueError(f"Alignment #{alignment.id()} has no horizontal layout")

        # Get all segments
        segments = align_api.get_layout_segments(h_layout)
        if not segments:
            raise ValueError(f"Alignment #{alignment.id()} has no segments")

        # Filter out zero-length terminator segments
        real_segments = [seg for seg in segments if not cls.is_zero_length_segment(seg)]
        if not real_segments:
            raise ValueError(f"Alignment #{alignment.id()} has no real segments (only terminator)")

        angle_unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc_file, "PLANEANGLEUNIT")
        segment_records = []
        for seg in real_segments:
            dp = seg.DesignParameters
            if dp is None or not dp.is_a("IfcAlignmentHorizontalSegment"):
                raise ValueError(
                    f"Alignment #{alignment.id()} segment #{seg.id()} has no horizontal design "
                    "parameters; the alignment is edited by segment instead"
                )
            segment_records.append(
                {
                    "predefined_type": dp.PredefinedType,
                    "start_point": tuple(dp.StartPoint.Coordinates[:2]),
                    "start_direction": float(dp.StartDirection) * angle_unit_scale,
                    "start_radius": float(dp.StartRadiusOfCurvature) if dp.StartRadiusOfCurvature is not None else None,
                    "end_radius": float(dp.EndRadiusOfCurvature) if dp.EndRadiusOfCurvature is not None else None,
                    "length": float(dp.SegmentLength),
                }
            )

        return cls.reconstruct_pis_from_horizontal_segments(segment_records)

    @classmethod
    def create_pi_edit_empties(
        cls,
        alignment: "ifcopenshell.entity_instance",
        pis: List[dict],
    ) -> List[bpy.types.Object]:
        """Create EMPTY objects at PI locations for editing.

        Creates temporary Blender EMPTY objects at each PI position,
        allowing users to move them with standard Blender tools (G key).

        The empties are:
        - Parented to the alignment object
        - Tagged with custom properties for identification
        - Named sequentially (PI.001, PI.002, etc.)

        Args:
            alignment: The IfcAlignment entity
            pis: List of PI dicts from back_calculate_pis_from_alignment()

        Returns:
            List of created Blender EMPTY objects, sorted by index
        """
        alignment_obj = tool.Ifc.get_object(alignment)
        if alignment_obj is None:
            return []

        # Get the collection to add objects to
        collection = None
        if alignment_obj.users_collection:
            collection = alignment_obj.users_collection[0]
        else:
            collection = bpy.context.scene.collection

        import ifcopenshell.util.unit

        alignment_id = alignment.id()
        empties = []
        # Georeference returns IFC project units; Blender world space is metres
        # (1 BU = 1 m), so scale up to place empties at the correct location.
        unit_scale = ifcopenshell.util.unit.calculate_unit_scale(tool.Ifc.get())

        for i, pi in enumerate(pis):
            # IFC project units -> Blender world metres
            local = tool.Georeference.enh2xyz((float(pi["e"]), float(pi["n"]), 0.0))
            blender_pos = (local[0] * unit_scale, local[1] * unit_scale, local[2] * unit_scale)

            # Create EMPTY object
            name = f"PI.{i + 1:03d}"
            empty = bpy.data.objects.new(name, None)
            empty.empty_display_type = "SPHERE"
            empty.empty_display_size = 2.0
            empty.location = blender_pos

            # Tag with custom properties for identification
            empty["civil_is_pi_empty"] = True
            empty["civil_pi_index"] = i
            empty["civil_pi_radius"] = pi["radius"]
            empty["civil_alignment_id"] = alignment_id
            empty["civil_pi_type"] = pi["pi_type"]
            # Spec 1.5 spiral transitions -- back_calculate_pis_from_alignment
            # populates these from real segments; spec 1.6 join_next is never
            # reconstructed into edit mode (an ambiguous run refuses entry
            # instead -- see reconstruct_pis_from_horizontal_segments), so
            # this is always False from that caller, but the key is still
            # written for round-trip symmetry with collect_pis_from_empties.
            empty["civil_pi_spiral_in"] = float(pi.get("spiral_in", 0.0))
            empty["civil_pi_spiral_out"] = float(pi.get("spiral_out", 0.0))
            empty["civil_pi_join_next"] = bool(pi.get("join_next", False))

            # Parent to alignment object
            empty.parent = alignment_obj

            # Link to collection
            collection.objects.link(empty)

            empties.append(empty)

        return empties

    @classmethod
    def get_pi_edit_empties(cls, alignment_id: int) -> List[bpy.types.Object]:
        """Find all PI EMPTY objects for a given alignment.

        Searches all objects in the scene for empties tagged with
        the PI edit mode custom properties.

        Args:
            alignment_id: The IFC ID of the alignment being edited

        Returns:
            List of PI EMPTY objects, sorted by pi_index
        """
        empties = []

        for obj in bpy.data.objects:
            if obj.get("civil_is_pi_empty") and obj.get("civil_alignment_id") == alignment_id:
                empties.append(obj)

        # Sort by PI index
        empties.sort(key=lambda e: e.get("civil_pi_index", 0))

        return empties

    @classmethod
    def remove_pi_edit_empties(cls, alignment_id: int) -> int:
        """Remove all PI EMPTY objects for a given alignment.

        Args:
            alignment_id: The IFC ID of the alignment being edited

        Returns:
            Number of objects removed
        """
        empties = cls.get_pi_edit_empties(alignment_id)
        removed_count = 0

        for empty in empties:
            bpy.data.objects.remove(empty, do_unlink=True)
            removed_count += 1

        return removed_count

    @classmethod
    def collect_pis_from_empties(cls, alignment_id: int) -> Tuple[List[Tuple[float, float]], List]:
        """Gather current PI positions from EMPTY objects.

        Reads the current positions of PI empties and converts them
        back to IFC coordinates for regenerating the alignment.

        Args:
            alignment_id: The IFC ID of the alignment being edited

        Returns:
            Tuple of:
            - hpoints: List of (x, y) tuples in IFC coordinates
            - radii: List of radii-elements for interior PIs only (not
              first/last) -- see ``build_pi_radius_element`` for the plain
              float / (R, Lin, Lout) tuple / join_next dict forms.
        """
        empties = cls.get_pi_edit_empties(alignment_id)

        if len(empties) < 2:
            return ([], [])

        import ifcopenshell.util.unit

        hpoints = []
        radii = []
        # Blender world metres -> IFC project units before georeferencing.
        unit_scale = ifcopenshell.util.unit.calculate_unit_scale(tool.Ifc.get())

        for i, empty in enumerate(empties):
            # Blender metres -> IFC project units -> global E/N
            translation = empty.matrix_world.translation
            local = (translation[0] / unit_scale, translation[1] / unit_scale, translation[2] / unit_scale)
            ifc_pos = tool.Georeference.xyz2enh(local)
            hpoints.append((ifc_pos[0], ifc_pos[1]))

            # Collect radii for interior PIs only (not first or last)
            if 0 < i < len(empties) - 1:
                radius = float(empty.get("civil_pi_radius", 0.0))
                spiral_in = float(empty.get("civil_pi_spiral_in", 0.0))
                spiral_out = float(empty.get("civil_pi_spiral_out", 0.0))
                join_next = bool(empty.get("civil_pi_join_next", False))
                radii.append(cls.build_pi_radius_element(radius, spiral_in, spiral_out, join_next))

        return (hpoints, radii)

    @classmethod
    def set_layout_segments_selectable(cls, layout: "ifcopenshell.entity_instance", selectable: bool) -> None:
        """Toggle viewport selectability of a layout's segment objects.

        During PI edit mode the segment curves are made non-selectable so
        viewport clicks land on the PI edit empties rather than on the curves
        drawn along the alignment (which otherwise intercept the clicks).
        """
        if layout is None:
            return
        for rel in getattr(layout, "IsNestedBy", []) or []:
            for segment in rel.RelatedObjects or []:
                if segment.is_a() == "IfcAlignmentSegment":
                    obj = tool.Ifc.get_object(segment)
                    if obj:
                        obj.hide_select = not selectable

    # =========================================================================
    # PI Edit Mode — In-Mode Editing (spec 1.3)
    # =========================================================================
    # Pure-math helpers first (no bpy — unit-testable with plain coordinates),
    # then the Blender/empty-touching methods that use them.

    @staticmethod
    def compute_curve_tangent_length(
        p_prev: Optional[Tuple[float, float]],
        p_pi: Tuple[float, float],
        p_next: Optional[Tuple[float, float]],
        radius: float,
    ) -> float:
        """Tangent length T = R * tan(delta/2) a curve at ``p_pi`` claims on
        each adjacent tangent (the PC/PT setback distance).

        ``delta`` is the deflection angle between the incoming tangent
        (``p_prev`` -> ``p_pi``) and the outgoing tangent (``p_pi`` ->
        ``p_next``). Returns 0.0 if there is no curve (radius <= 0) or a
        neighbor is missing (endpoint PIs never carry a curve).
        """
        if radius is None or radius <= 0 or p_prev is None or p_next is None:
            return 0.0
        v_in = (p_pi[0] - p_prev[0], p_pi[1] - p_prev[1])
        v_out = (p_next[0] - p_pi[0], p_next[1] - p_pi[1])
        len_in = math.hypot(*v_in)
        len_out = math.hypot(*v_out)
        if len_in < 1e-9 or len_out < 1e-9:
            return 0.0
        dot = (v_in[0] * v_out[0] + v_in[1] * v_out[1]) / (len_in * len_out)
        dot = max(-1.0, min(1.0, dot))
        delta = math.acos(dot)
        return radius * math.tan(delta / 2.0)

    @staticmethod
    def project_point_onto_segment_2d(
        point: Tuple[float, float], a: Tuple[float, float], b: Tuple[float, float]
    ) -> Tuple[float, Tuple[float, float], float]:
        """Project ``point`` onto the segment ``a``->``b``.

        Returns (t, closest_point, perpendicular_distance):
        - ``t``: the clamped [0, 1] parametric position of the closest point.
        - ``closest_point``: the clamped closest point on the segment.
        - ``perpendicular_distance``: distance from ``point`` to the closest
          point — used to rank candidate segments by nearness.
        """
        ax, ay = a
        bx, by = b
        px, py = point
        dx, dy = bx - ax, by - ay
        length_sq = dx * dx + dy * dy
        if length_sq < 1e-12:
            return 0.0, (ax, ay), math.hypot(px - ax, py - ay)
        t_raw = ((px - ax) * dx + (py - ay) * dy) / length_sq
        t = max(0.0, min(1.0, t_raw))
        closest = (ax + t * dx, ay + t * dy)
        perpendicular = math.hypot(px - closest[0], py - closest[1])
        return t, closest, perpendicular

    @staticmethod
    def line_intersection_2d(
        p1: Tuple[float, float],
        d1: Tuple[float, float],
        p2: Tuple[float, float],
        d2: Tuple[float, float],
    ) -> Optional[Tuple[float, float]]:
        """Intersect line ``p1 + t*d1`` with line ``p2 + s*d2``.

        Returns the intersection point, or None if the lines are parallel
        (or nearly so).
        """
        x1, y1 = p1
        dx1, dy1 = d1
        x2, y2 = p2
        dx2, dy2 = d2
        denom = dx1 * dy2 - dy1 * dx2
        if abs(denom) < 1e-9:
            return None
        t = ((x2 - x1) * dy2 - (y2 - y1) * dx2) / denom
        return (x1 + t * dx1, y1 + t * dy1)

    @classmethod
    def find_tangent_insertion_point(
        cls,
        points: List[Tuple[float, float]],
        radii: List[float],
        position: Tuple[float, float],
    ) -> dict:
        """Locate where ``position`` projects onto the PI polyline for PI
        insertion (spec 1.3, ``I`` key).

        ``points``/``radii`` are the ordered PI (x, y) positions and their
        matching curve radii (0.0 = no curve). Finds the tangent segment
        nearest to ``position`` and refuses the insertion if the projected
        point falls inside either endpoint's curve tangent-claim — that
        portion of the segment is actually swept by a circular arc in the
        PI-method construction, not a straight tangent.

        Returns:
            {"ok": True, "segment_index": i, "point": (x, y)} on success, or
            {"ok": False, "reason": "..."} on refusal.
        """
        if len(points) < 2:
            return {"ok": False, "reason": "Need at least 2 PIs"}

        candidates = []
        for i in range(len(points) - 1):
            a, b = points[i], points[i + 1]
            t, closest, perpendicular = cls.project_point_onto_segment_2d(position, a, b)
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            candidates.append((perpendicular, i, t, closest, length))
        candidates.sort(key=lambda c: c[0])
        _, segment_index, t, closest, length = candidates[0]

        a = points[segment_index]
        b = points[segment_index + 1]
        prev_point = points[segment_index - 1] if segment_index - 1 >= 0 else None
        next_point = points[segment_index + 2] if segment_index + 2 < len(points) else None

        claim_a = cls.compute_curve_tangent_length(prev_point, a, b, radii[segment_index])
        claim_b = cls.compute_curve_tangent_length(a, b, next_point, radii[segment_index + 1])

        distance_along = t * length
        min_allowed = claim_a
        max_allowed = length - claim_b

        if min_allowed > max_allowed + 1e-9:
            return {"ok": False, "reason": "Adjacent curves leave no straight tangent to insert onto"}
        if distance_along < min_allowed - 1e-6 or distance_along > max_allowed + 1e-6:
            return {"ok": False, "reason": "Insertion point falls inside a curve's tangent extents"}

        return {"ok": True, "segment_index": segment_index, "point": closest}

    @classmethod
    def validate_curve_fit_geometry(
        cls,
        points: List[Tuple[float, float]],
        radii: List[float],
        index: int,
        new_radius: float,
    ) -> Tuple[bool, Optional[str]]:
        """Pure math: would a curve of ``new_radius`` at PI ``index`` fit
        within its two adjacent tangent segments, net of the tangent already
        claimed there by neighboring curves?

        ``points``/``radii`` are the full ordered PI lists — ``radii[index]``
        is ignored (it is the *current* radius; ``new_radius`` is the
        candidate being validated). Endpoints (index 0 or len-1) can never
        hold a curve.

        Returns (ok, reason) — reason is None when ok is True.
        """
        n = len(points)
        if index <= 0 or index >= n - 1:
            return False, "Curves can only be added to interior PIs"
        if new_radius <= 0:
            return False, "Radius must be greater than zero"

        prev_point = points[index - 1]
        this_point = points[index]
        next_point = points[index + 1]

        claim_here = cls.compute_curve_tangent_length(prev_point, this_point, next_point, new_radius)

        # Tangent segment on the PREV side: [prev_point, this_point].
        prev_prev = points[index - 2] if index - 2 >= 0 else None
        claim_prev_far = cls.compute_curve_tangent_length(prev_prev, prev_point, this_point, radii[index - 1])
        length_prev = math.hypot(this_point[0] - prev_point[0], this_point[1] - prev_point[1])
        if claim_here + claim_prev_far > length_prev + 1e-6:
            return False, (
                f"Radius {new_radius:.2f} is too large — the tangent back to the "
                f"previous PI is only {length_prev:.2f} long"
            )

        # Tangent segment on the NEXT side: [this_point, next_point].
        next_next = points[index + 2] if index + 2 < n else None
        claim_next_far = cls.compute_curve_tangent_length(this_point, next_point, next_next, radii[index + 1])
        length_next = math.hypot(next_point[0] - this_point[0], next_point[1] - this_point[1])
        if claim_here + claim_next_far > length_next + 1e-6:
            return (
                False,
                f"Radius {new_radius:.2f} is too large — the tangent to the next PI is only {length_next:.2f} long",
            )

        return True, None

    @classmethod
    def validate_curve_fit(
        cls, empties: List[bpy.types.Object], index: int, radius: float
    ) -> Tuple[bool, Optional[str]]:
        """Blender-facing wrapper for ``validate_curve_fit_geometry``.

        Extracts (x, y) positions and current radii from PI edit empties,
        then delegates to the pure-math check.
        """
        # Uses .location, not matrix_world — create_pi_edit_empties parents
        # these to an identity-transform alignment object and sets .location
        # to the already-world coordinate, so .location is immediately
        # correct without waiting on a depsgraph/view-layer update (which
        # matrix_world would need after any location change this frame).
        points = [(float(e.location.x), float(e.location.y)) for e in empties]
        radii = [float(e.get("civil_pi_radius", 0.0)) for e in empties]
        return cls.validate_curve_fit_geometry(points, radii, index, radius)

    @staticmethod
    def slide_tangent(
        p_prev: Optional[Tuple[float, float]],
        p_a: Tuple[float, float],
        p_b: Tuple[float, float],
        p_next: Optional[Tuple[float, float]],
        delta: Tuple[float, float],
    ) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        """Slide the tangent line through ``p_a``->``p_b`` parallel to itself
        (bearing-constant slide, spec 1.3 ``T`` key).

        Only the component of ``delta`` perpendicular to the tangent
        direction is applied — sliding along the tangent's own bearing would
        not be a "slide". The two PI positions move to where the translated
        line intersects their OTHER adjacent tangent (the one not being
        slid), keeping every other tangent's bearing unchanged:
        - ``new_p_a`` = intersection of the slid line with (p_prev -> p_a).
        - ``new_p_b`` = intersection of the slid line with (p_b -> p_next).

        ``p_prev``/``p_next`` may be None when ``p_a``/``p_b`` is an
        alignment endpoint with no "other" tangent — in that case the
        endpoint is simply translated by the perpendicular delta.

        Returns (new_p_a, new_p_b).
        """
        dx = p_b[0] - p_a[0]
        dy = p_b[1] - p_a[1]
        length = math.hypot(dx, dy)
        if length < 1e-9:
            return p_a, p_b
        direction = (dx / length, dy / length)
        normal = (-direction[1], direction[0])
        perp_mag = delta[0] * normal[0] + delta[1] * normal[1]
        perp_delta = (normal[0] * perp_mag, normal[1] * perp_mag)

        shifted_a = (p_a[0] + perp_delta[0], p_a[1] + perp_delta[1])
        shifted_b = (p_b[0] + perp_delta[0], p_b[1] + perp_delta[1])

        new_p_a = shifted_a
        if p_prev is not None:
            other_dir_a = (p_a[0] - p_prev[0], p_a[1] - p_prev[1])
            if math.hypot(*other_dir_a) > 1e-9:
                intersection = tool.Alignment.line_intersection_2d(p_prev, other_dir_a, shifted_a, direction)
                if intersection is not None:
                    new_p_a = intersection

        new_p_b = shifted_b
        if p_next is not None:
            other_dir_b = (p_next[0] - p_b[0], p_next[1] - p_b[1])
            if math.hypot(*other_dir_b) > 1e-9:
                intersection = tool.Alignment.line_intersection_2d(p_b, other_dir_b, shifted_a, direction)
                if intersection is not None:
                    new_p_b = intersection

        return new_p_a, new_p_b

    @classmethod
    def insert_pi_on_tangent(
        cls, alignment_id: int, position: Tuple[float, float]
    ) -> Tuple[Optional[bpy.types.Object], Optional[str]]:
        """Insert a new PI empty onto the nearest tangent segment (spec 1.3,
        ``I`` key).

        ``position`` is an (x, y) point in the same Blender world-space
        convention used by the PI empties (see ``collect_pis_from_empties``).
        Renumbers ``civil_pi_index`` on the new empty and every empty after
        it so indices stay contiguous.

        Returns (new_empty, None) on success, or (None, reason) if there are
        fewer than 2 PIs, or the projection falls inside a curve's tangent
        extents (find_tangent_insertion_point refusal).
        """
        empties = cls.get_pi_edit_empties(alignment_id)
        if len(empties) < 2:
            return None, "Need at least 2 PIs to insert onto a tangent"

        # .location, not matrix_world — see the comment in validate_curve_fit.
        points = [(float(e.location.x), float(e.location.y)) for e in empties]
        radii = [float(e.get("civil_pi_radius", 0.0)) for e in empties]

        result = cls.find_tangent_insertion_point(points, radii, position)
        if not result["ok"]:
            return None, result["reason"]

        segment_index = result["segment_index"]
        x, y = result["point"]

        reference = empties[segment_index]
        alignment_obj = reference.parent
        collection = reference.users_collection[0] if reference.users_collection else bpy.context.scene.collection

        new_empty = bpy.data.objects.new(f"PI.{segment_index + 2:03d}", None)
        new_empty.empty_display_type = "SPHERE"
        new_empty.empty_display_size = 2.0
        new_empty.location = (x, y, reference.location.z)

        new_empty["civil_is_pi_empty"] = True
        new_empty["civil_pi_index"] = segment_index + 1
        new_empty["civil_pi_radius"] = 0.0
        new_empty["civil_alignment_id"] = alignment_id
        new_empty["civil_pi_type"] = "TANGENT"

        if alignment_obj is not None:
            new_empty.parent = alignment_obj
        collection.objects.link(new_empty)

        # Renumber every empty after the insertion point to make room.
        for empty in empties[segment_index + 1 :]:
            empty["civil_pi_index"] = empty.get("civil_pi_index", 0) + 1

        return new_empty, None

    @classmethod
    def delete_pi_edit_empty(cls, alignment_id: int, index: int) -> bool:
        """Delete the PI empty at ``index`` and renumber the rest.

        The core-level rule about how many PIs must remain (spec 1.3, ``X``
        key) lives in ``core.alignment.delete_pi_in_edit_mode`` — this is the
        unconditional tool-layer primitive it calls after the guard passes.

        Returns True if an empty was removed, False if ``index`` was invalid.
        """
        empties = cls.get_pi_edit_empties(alignment_id)
        if not (0 <= index < len(empties)):
            return False
        bpy.data.objects.remove(empties[index], do_unlink=True)
        for new_index, empty in enumerate(cls.get_pi_edit_empties(alignment_id)):
            empty["civil_pi_index"] = new_index
        return True

    @classmethod
    def set_pi_radius(cls, empties: List[bpy.types.Object], index: int, radius: float) -> None:
        """Set the curve radius on the PI empty at ``index`` (spec 1.3, ``C``
        key — called by ``civil.set_pi_curve_radius`` after
        ``validate_curve_fit`` passes)."""
        empty = empties[index]
        empty["civil_pi_radius"] = float(radius)
        empty["civil_pi_type"] = "CURVE" if radius > 0 else "TANGENT"

    @classmethod
    def clear_pi_radius(cls, alignment_id: int, index: int) -> None:
        """Clear the curve radius on the PI empty at ``index`` (spec 1.3,
        ``Alt+C`` key) — the curve is removed, the PI becomes a pass-through
        tangent point."""
        empties = cls.get_pi_edit_empties(alignment_id)
        if 0 <= index < len(empties):
            empties[index]["civil_pi_radius"] = 0.0
            empties[index]["civil_pi_type"] = "TANGENT"

    # =========================================================================
    # Alignment / Vertical Deletion (spec 1.4, 2.6)
    # =========================================================================

    @classmethod
    def remove_alignment_entity(cls, alignment: "ifcopenshell.entity_instance") -> None:
        """Remove the IfcAlignment entity itself (IFC layer only).

        Isolated from ``core.alignment.delete_alignment`` so core stays free
        of direct ``ifcopenshell.api`` calls. Mirrors what the standalone
        ``root.remove_product`` call in the old ``CIVIL_OT_clear_pis``
        operator did: relationships (placement, representation, the
        alignment's own IfcRelNests membership) are cleaned up, but nested
        layout/segment entities are not cascade-removed — they become
        unreferenced. This is an existing, pre-Saikei limitation of
        ``root.remove_product`` for decomposition trees, not new behavior.
        """
        import ifcopenshell.api.root

        ifc_file = tool.Ifc.get()
        ifcopenshell.api.root.remove_product(ifc_file, product=alignment)

    @classmethod
    def remove_vertical_layout(cls, alignment: "ifcopenshell.entity_instance") -> None:
        """Remove the vertical layout and revert the alignment to
        horizontal-only (spec 2.6).

        Mirrors ``add_vertical_layout`` in reverse for the single-vertical
        case Saikei supports (``core.add_vertical_to_alignment`` blocks a
        second vertical, so when present the vertical layout is always
        nested directly under the alignment per IFC CT 4.1.4.4.1.1 — never
        split onto a child alignment via CT 4.1.4.4.1.2).

        Removes, in order:
        1. The vertical layout's real segments (both halves — geometric
           curve segments and semantic IfcAlignmentSegments).
        2. Blender objects for those segments and the layout's own object.
        3. The terminator's semantic IfcAlignmentSegment (its geometric half
           is removed in step 5, with the rest of the gradient curve).
        4. The IfcAlignmentVertical entity itself.
        5. The "Axis"/Curve3D IfcGradientCurve representation that
           ``add_vertical_layout`` assigned to the alignment — reverting the
           "FootPrint"/Curve2D representation it renamed back to
           "Axis"/Curve2D so the alignment reads as horizontal-only again.
        6. Any stale 3D-centerline helper object (it drove off the vertical).

        Does nothing if the alignment has no vertical layout.
        """
        import ifcopenshell.api.alignment as align_api
        import ifcopenshell.api.geometry
        import ifcopenshell.api.root
        import ifcopenshell.util.representation

        ifc_file = tool.Ifc.get()

        v_layout = align_api.get_vertical_layout(alignment)
        if v_layout is None:
            return

        # 1-2) Real segments (geometric + semantic) and their Blender objects.
        cls.clear_layout_segments(v_layout)
        cls.remove_layout_segment_objects(v_layout)
        layout_obj = tool.Ifc.get_object(v_layout)
        if layout_obj:
            cls._remove_blender_object(layout_obj)

        # 3) The terminator's semantic IfcAlignmentSegment.
        for rel in getattr(v_layout, "IsNestedBy", []) or []:
            for segment in list(rel.RelatedObjects or []):
                if segment.is_a("IfcAlignmentSegment"):
                    ifcopenshell.api.root.remove_product(ifc_file, product=segment)

        # 4) The layout entity itself (unnests it from the alignment).
        ifcopenshell.api.root.remove_product(ifc_file, product=v_layout)

        # 5) Revert the geometric representation add_vertical_layout created.
        for representation in list(ifcopenshell.util.representation.get_representations_iter(alignment)):
            if representation.RepresentationIdentifier == "Axis" and representation.RepresentationType == "Curve3D":
                ifcopenshell.api.geometry.unassign_representation(ifc_file, alignment, representation)
                ifcopenshell.api.geometry.remove_representation(ifc_file, representation=representation)
            elif (
                representation.RepresentationIdentifier == "FootPrint"
                and representation.RepresentationType == "Curve2D"
            ):
                representation.RepresentationIdentifier = "Axis"

        # 6) Stale 3D centerline helper (it was draped over the vertical).
        cls.remove_3d_alignment_object(alignment)

    @classmethod
    def get_active_alignment(cls) -> ifcopenshell.entity_instance | None:
        if obj := tool.Blender.get_active_object():
            if (element := tool.Ifc.get_entity(obj)) and element.is_a("IfcAlignment"):
                return element

    # =========================================================================
    # Cant — IFC API Wrappers (spec Section 3)
    # =========================================================================
    # "Adding cant is what marks an alignment as rail" (spec 3.1). A cant
    # layout requires both a horizontal AND a vertical layout to already
    # exist: the geometry engine needs an IfcGradientCurve to use as the
    # BaseCurve of the IfcSegmentedReferenceCurve that add_cant_layout
    # produces (see ifcopenshell.api.alignment.add_cant_layout's docstring).

    @classmethod
    def get_cant_layout(cls, alignment: "ifcopenshell.entity_instance"):
        """Get the IfcAlignmentCant layout from an alignment, or None."""
        import ifcopenshell.api.alignment as align_api

        return align_api.get_cant_layout(alignment)

    @classmethod
    def add_cant_layout(
        cls, alignment: "ifcopenshell.entity_instance", rail_head_distance: float = 1.0
    ) -> "ifcopenshell.entity_instance":
        """Add a new IfcAlignmentCant layout to an alignment (spec 3.1).

        Wraps ifcopenshell.api.alignment.add_cant_layout, which requires both
        a horizontal AND a vertical layout to already exist (enforced by
        core.alignment.add_cant_to_alignment before this is called) and
        extends the alignment's geometric representation from
        IfcGradientCurve to IfcSegmentedReferenceCurve when one exists.

        Args:
            alignment: The IfcAlignment entity
            rail_head_distance: Distance between rail heads (model units),
                assigned to IfcAlignmentCant.RailHeadDistance — the API uses
                it to convert cant height (a vertical offset between the two
                rails) into the rotation angle of the track cross-section
                about the alignment axis for the geometric representation.

        Returns:
            The newly created IfcAlignmentCant entity (including its
            mandatory zero-length terminator segment).
        """
        import ifcopenshell.api.alignment as align_api

        ifc_file = tool.Ifc.get()
        return align_api.add_cant_layout(ifc_file, alignment, rail_head_distance=rail_head_distance)

    @classmethod
    def remove_cant_layout(cls, alignment: "ifcopenshell.entity_instance") -> None:
        """Remove the cant layout, reverting the alignment's representation
        from IfcSegmentedReferenceCurve back to IfcGradientCurve (spec 3.6).

        Mirrors remove_vertical_layout in structure. Cant has no CT
        4.1.4.4.1.2-style "reuse" concept — add_cant_layout's docstring notes
        IFC 4.3 defines no such template for cant — so there is always at
        most one cant layout, nested directly under `alignment`.

        Removes, in order:
        1. The cant layout's real segments (both halves — geometric
           IfcCurveSegments and semantic IfcAlignmentSegments).
        2. Blender objects for those segments and the layout's own object.
        3. The terminator's semantic IfcAlignmentSegment.
        4. The "Axis"/Curve3D representation's IfcSegmentedReferenceCurve —
           repointing Items back at its BaseCurve (the IfcGradientCurve
           add_cant_layout reused, which must NOT be deleted) before
           deep-removing the wrapper, so the gradient curve is recognized as
           still referenced and survives.
        5. The IfcAlignmentCant entity itself.
        6. Any stale 3D-centerline helper object (defensive — cant does not
           currently affect the D3 centerline sampler, but this keeps the
           cleanup symmetric with remove_vertical_layout).

        Does nothing if the alignment has no cant layout.
        """
        import ifcopenshell.api.alignment as align_api
        import ifcopenshell.api.root
        import ifcopenshell.util.element
        import ifcopenshell.util.representation

        ifc_file = tool.Ifc.get()

        cant_layout = align_api.get_cant_layout(alignment)
        if cant_layout is None:
            return

        # 1-2) Real segments (geometric + semantic) and their Blender objects.
        cls.clear_layout_segments(cant_layout)
        cls.remove_layout_segment_objects(cant_layout)
        layout_obj = tool.Ifc.get_object(cant_layout)
        if layout_obj:
            cls._remove_blender_object(layout_obj)

        # 3) The terminator's semantic IfcAlignmentSegment.
        for rel in getattr(cant_layout, "IsNestedBy", []) or []:
            for segment in list(rel.RelatedObjects or []):
                if segment.is_a("IfcAlignmentSegment"):
                    ifcopenshell.api.root.remove_product(ifc_file, product=segment)

        # 4) Revert the "Axis"/"Curve3D" representation: IfcSegmentedReferenceCurve -> its BaseCurve.
        for representation in list(ifcopenshell.util.representation.get_representations_iter(alignment)):
            if representation.RepresentationIdentifier == "Axis" and representation.RepresentationType == "Curve3D":
                items = list(representation.Items or [])
                for item in items:
                    if item.is_a("IfcSegmentedReferenceCurve"):
                        base_curve = item.BaseCurve
                        representation.Items = tuple(base_curve if it is item else it for it in items)
                        ifcopenshell.util.element.remove_deep2(ifc_file, item)
                        break

        # 5) The layout entity itself (unnests it from the alignment).
        ifcopenshell.api.root.remove_product(ifc_file, product=cant_layout)

        # 6) Stale 3D centerline helper.
        cls.remove_3d_alignment_object(alignment)

    @classmethod
    def get_horizontal_extent_semantic(cls, alignment: "ifcopenshell.entity_instance") -> float:
        """Total length (model units) of the horizontal alignment domain,
        computed purely from IfcAlignmentHorizontalSegment.SegmentLength
        design parameters — no geometry engine evaluation.

        The cant table's station-range validation
        (``core.alignment.update_cant_segments``) must work even where
        map_shape/evaluate is unavailable (the win64 packaging gap,
        IfcOpenShell#9301). ``get_alignment_length`` is *already* purely
        semantic (it sums SegmentLength design parameters and never calls
        the geometry engine) — this is a thin, purpose-dedicated alias so the
        cant extent check has an explicit, geometry-engine-free contract that
        does not depend on ``get_alignment_length`` staying that way if it is
        ever extended for D3/evaluation purposes.

        Returns:
            Total horizontal length, or 0.0 if there is no horizontal layout.
        """
        return cls.get_alignment_length(alignment) or 0.0

    @classmethod
    def back_calculate_cant_points_from_layout(cls, alignment: "ifcopenshell.entity_instance") -> List[dict]:
        """Reverse-engineer the cant point table from IFC
        IfcAlignmentCantSegment design parameters — semantic only, no
        geometry engine (mirrors ``back_calculate_pvis_from_vertical``'s
        pattern for the vertical layout).

        Used by the profile view's cant band (spec 3.4) to redraw straight
        from IFC without depending on the ``props.cant_points`` UI
        collection, so the band works even if the Cant Editor panel has
        never been opened this session.

        Returns:
            List of dicts: ``{"station", "cant_left", "cant_right",
            "transition_type"}``, one per point (segment boundary) — in the
            same convention as ``write_cant_segments`` (a point's
            transition_type carries its value INTO the next point; the last
            point's is unused). Empty list if the alignment has no cant
            layout or no real segments.
        """
        import ifcopenshell.api.alignment as align_api

        cant_layout = align_api.get_cant_layout(alignment)
        if cant_layout is None:
            return []

        segments = align_api.get_layout_segments(cant_layout)
        real_segments = [seg for seg in segments if not cls.is_zero_length_segment(seg)]
        if not real_segments:
            return []

        points = []
        for segment in real_segments:
            dp = segment.DesignParameters
            points.append(
                {
                    "station": float(dp.StartDistAlong),
                    "cant_left": float(dp.StartCantLeft),
                    "cant_right": float(dp.StartCantRight),
                    "transition_type": dp.PredefinedType,
                }
            )

        last_dp = real_segments[-1].DesignParameters
        end_left = last_dp.EndCantLeft if last_dp.EndCantLeft is not None else last_dp.StartCantLeft
        end_right = last_dp.EndCantRight if last_dp.EndCantRight is not None else last_dp.StartCantRight
        points.append(
            {
                "station": float(last_dp.StartDistAlong) + float(last_dp.HorizontalLength),
                "cant_left": float(end_left),
                "cant_right": float(end_right),
                "transition_type": last_dp.PredefinedType,  # unused — no outgoing segment
            }
        )
        return points

    @classmethod
    def write_cant_segments(cls, alignment: "ifcopenshell.entity_instance", points: list) -> None:
        """Write the cant table to IFC as IfcAlignmentCantSegments (spec 3.2).

        ``points`` is an ordered list of dicts: ``{"station", "cant_left",
        "cant_right", "transition_type"}``. Points mark STATIONS where cant
        VALUES are defined; each CONSECUTIVE PAIR of points becomes one
        IfcAlignmentCantSegment. The convention — not obvious from the IFC
        schema, so documented here and in ``CivilCantPointProperties``: a
        point's ``transition_type`` is the type of the segment that carries
        its value INTO the NEXT point — i.e. ``points[i]["transition_type"]``
        governs the segment ``[points[i], points[i + 1]]``. The LAST point's
        ``transition_type`` is unused (there is no "next" segment for it).

        Note on CONSTANTCANT: the geometric mapping for CONSTANTCANT segments
        (``_map_alignment_cant_segment._map_constant_cant``) only reads the
        segment's *start* cant values — the end values are written to IFC
        (per the schema, and so a later transition-type edit does not lose
        data) but are not swept for a still-CONSTANTCANT segment. If the
        table's next point has different cant values, the rendered geometry
        will hold flat at the start value and then jump at the segment
        boundary; ``sample_cant_profile`` mirrors this so the display band is
        honest about it.

        Clears the cant layout's existing real segments first (mirrors
        ``layout_by_pi_method`` / ``layout_vertical_by_pvi_method``'s "clear
        then rebuild" idiom), then calls ``create_layout_segment`` for each
        consecutive pair. The mandatory zero-length terminator is preserved
        and repositioned automatically by
        ``create_layout_segment``/``_add_segment_to_layout``.

        Args:
            alignment: The IfcAlignment entity (must already have a cant
                layout)
            points: Ordered cant point list, strictly increasing station
                (validated by ``core.alignment.update_cant_segments`` before
                this is called)

        Raises:
            ValueError: If the alignment has no cant layout.
        """
        import ifcopenshell.api.alignment as align_api

        ifc_file = tool.Ifc.get()
        cant_layout = align_api.get_cant_layout(alignment)
        if cant_layout is None:
            raise ValueError(f"Alignment #{alignment.id()} has no cant layout")

        cls.clear_layout_segments(cant_layout)

        for current, following in zip(points, points[1:]):
            design_parameters = ifc_file.createIfcAlignmentCantSegment(
                StartDistAlong=float(current["station"]),
                HorizontalLength=float(following["station"]) - float(current["station"]),
                StartCantLeft=float(current["cant_left"]),
                EndCantLeft=float(following["cant_left"]),
                StartCantRight=float(current["cant_right"]),
                EndCantRight=float(following["cant_right"]),
                PredefinedType=current.get("transition_type", "LINEARTRANSITION"),
            )
            align_api.create_layout_segment(ifc_file, cant_layout, design_parameters)

    # =========================================================================
    # Cant — Rotation Reference (spec 3.3)
    # =========================================================================
    # "Recorded, not assumed": the rotation reference (which rail — low,
    # centerline, or high — the cant rotation is measured about) is persisted
    # for save/reopen round-trip and downstream tooling to read, but has NO
    # geometry consequence yet. The geometric representation always applies
    # cant per RailHeadDistance exactly as authored by the alignment API;
    # this flag does not currently change the sweep.

    @classmethod
    def set_cant_rotation_reference(cls, cant_layout: "ifcopenshell.entity_instance", rotation_reference: str) -> None:
        """Persist the cant rotation reference as Pset_SaikeiCant.RotationReference.

        IFC 4.3 has no standard pset for which rail the cant rotation is
        measured about, so it rides in a Saikei pset on the IfcAlignmentCant
        entity for save/reopen round-trip (mirrors
        ``set_design_criteria``'s pset pattern on IfcAlignment).
        """
        import ifcopenshell.api.pset
        import ifcopenshell.util.element

        ifc_file = tool.Ifc.get()
        existing = ifcopenshell.util.element.get_pset(cant_layout, "Pset_SaikeiCant", should_inherit=False)
        if existing:
            pset_entity = ifc_file.by_id(existing["id"])
        else:
            pset_entity = ifcopenshell.api.pset.add_pset(ifc_file, product=cant_layout, name="Pset_SaikeiCant")
        ifcopenshell.api.pset.edit_pset(
            ifc_file, pset=pset_entity, properties={"RotationReference": rotation_reference}
        )

    @classmethod
    def get_cant_rotation_reference(cls, cant_layout: "ifcopenshell.entity_instance") -> Optional[str]:
        """Return the persisted cant rotation reference, or None when never set."""
        import ifcopenshell.util.element

        pset = ifcopenshell.util.element.get_pset(cant_layout, "Pset_SaikeiCant", should_inherit=False)
        if pset and pset.get("RotationReference"):
            return str(pset["RotationReference"])
        return None

    # =========================================================================
    # Cant — Pure Math (spec 3.2)
    # =========================================================================

    # Standard gravity, m/s^2 (ISO 80000-3 / NIST). Used for both metric and
    # imperial equilibrium-cant derivations via a single SI-consistent
    # formula — see cant_equilibrium.
    GRAVITY_MPS2 = 9.80665

    # Source: EN 13803-1:2017 "Railway applications — Track — Track alignment
    # design parameters — Track gauges 1435 mm and wider", plain line, normal
    # limits. Transcribed as ADVISORY defaults (never blocking — see
    # compute_cant_checks); the engineer of record may override every value
    # via CivilAlignmentProperties.cant_limit_*. Exact figures vary by
    # edition/national annex — treat these as reasonable ballpark defaults,
    # not a substitute for the governing standard.
    #
    # All values use the SAME internal convention as the rest of this module:
    # length-valued limits in metres (Blender's LENGTH-property convention —
    # see AlignmentPI.radius for the same pattern), rate-valued limits
    # (gradient/twist) as dimensionless length-per-length ratios rather than
    # a display-scaled mm/m or in/ft number, so a limit compares directly
    # against compute_cant_checks()'s raw ratio without unit conversion at
    # check time (mm/m and in/ft are NOT numerically comparable to the same
    # threshold — see cant_gradient/twist's docstrings). The published EN
    # 13803 figures are in mm and mm/m; the comments below show that
    # conversion.
    EN13803_DEFAULT_LIMITS = {
        "max_applied_cant": 0.160,  # 160 mm
        "max_deficiency": 0.153,  # 153 mm
        "max_excess": 0.110,  # 110 mm
        "max_cant_gradient": 0.00225,  # 2.25 mm/m == 0.00225 m/m
        "max_twist": 0.003,  # 3 mm/m == 0.003 m/m (see twist()'s docstring
        # for the MVP simplification: twist rate is computed identically to
        # cant gradient here, i.e. no separate fixed measurement base length)
    }

    @classmethod
    def cant_equilibrium(cls, speed: float, radius: float, gauge: float, is_imperial: bool = False) -> float:
        """Equilibrium cant E_eq = gauge * v^2 / (g * radius) — the applied
        cant at which centripetal acceleration exactly balances the lateral
        gravity component contributed by the rail cant (no net lateral force
        on passengers/cargo at ``speed``).

        ``gauge`` and ``radius`` (and the returned E_eq) must share the SAME
        length unit for the formula to be dimensionally correct; this module
        always passes them in METRES (Blender's internal LENGTH-property
        convention — see AlignmentPI.radius for the same pattern), so ``g``
        below is the standard 9.80665 m/s^2 and ``speed`` is converted to
        m/s internally. Only ``speed``'s convention needs ``is_imperial`` to
        pick the right velocity conversion — matching
        ``CivilAlignmentProperties.design_speed`` and
        ``Alignment.is_imperial_project()``:

        - Metric (``is_imperial=False``): ``speed`` is km/h ->
          v(m/s) = speed / 3.6.
        - Imperial (``is_imperial=True``): ``speed`` is mph ->
          v(m/s) = speed * 0.44704 (1 mph = 0.44704 m/s, exact by definition).

        Using ONE SI-consistent formula for both conventions (rather than two
        separate empirical mm/inch constants) keeps gauge/radius/E_eq in
        whatever length unit the caller is working in.

        Returns 0.0 for non-positive radius, speed, or gauge (straight track,
        no speed, or no gauge has no equilibrium cant to compute).
        """
        if radius is None or radius <= 0 or speed is None or speed <= 0 or not gauge or gauge <= 0:
            return 0.0
        speed_mps = (speed * 0.44704) if is_imperial else (speed / 3.6)
        return gauge * speed_mps**2 / (cls.GRAVITY_MPS2 * radius)

    @classmethod
    def cant_gradient(cls, delta_cant: float, length: float, is_imperial: bool = False) -> float:
        """Cant gradient (rate of change of applied cant along a transition),
        expressed per the project's display convention:

        - Metric (``is_imperial=False``): millimetres per metre of
          transition length — ``delta_cant / length * 1000``.
        - Imperial (``is_imperial=True``): inches per foot of transition
          length — ``delta_cant / length * 12``.

        Because the ratio ``delta_cant / length`` is unit-independent (both
        are passed in the same internal metres, so any length-unit
        conversion cancels out of the ratio), the two display conventions
        are simply a different scale factor (1000 vs 12) on the same
        underlying ratio — NOT a value that can be compared directly against
        a limit expressed in the other convention (2.25 mm/m is a much
        gentler gradient than a numeric "2.25" would mean as in/ft). Limit
        checks in ``compute_cant_checks`` therefore compare the RAW ratio,
        not this display-scaled value — see ``EN13803_DEFAULT_LIMITS``.

        Returns 0.0 for non-positive length.
        """
        if length is None or length <= 0:
            return 0.0
        ratio = delta_cant / length
        return ratio * 12.0 if is_imperial else ratio * 1000.0

    @classmethod
    def twist(
        cls, delta_cant: float, length: float, speed: Optional[float] = None, is_imperial: bool = False
    ) -> Tuple[float, float]:
        """Track twist: the rate of change of cross-level (applied cant)
        along a transition.

        MVP simplification: this module computes twist identically to
        ``cant_gradient`` (the rate of change of applied cant over the
        transition length) — EN 13803 formally measures twist over a fixed
        base length (e.g. 3 m) rather than instantaneously along the whole
        transition, which is out of scope for this pass; see
        ``EN13803_DEFAULT_LIMITS``'s comment.

        Returns a tuple ``(twist_per_length, twist_per_time_mm_s)``:

        - ``twist_per_length``: same display convention as
          ``cant_gradient`` — mm/m (metric) or in/ft (imperial).
        - ``twist_per_time_mm_s``: millimetres of cant change PER SECOND
          (always mm, regardless of ``is_imperial`` — this is the
          conventional railway ride-comfort criterion unit) experienced by a
          vehicle traversing the transition at ``speed`` (km/h metric, mph
          imperial — same convention as ``cant_equilibrium``). ``0.0`` when
          ``speed`` is ``None`` or non-positive.
        """
        twist_per_length = cls.cant_gradient(delta_cant, length, is_imperial)
        if not speed or speed <= 0 or not length or length <= 0:
            return twist_per_length, 0.0
        speed_mps = (speed * 0.44704) if is_imperial else (speed / 3.6)
        if speed_mps <= 0:
            return twist_per_length, 0.0
        time_through_transition = length / speed_mps
        if time_through_transition <= 0:
            return twist_per_length, 0.0
        delta_cant_mm = abs(delta_cant) * 1000.0
        twist_per_time_mm_s = delta_cant_mm / time_through_transition
        return twist_per_length, twist_per_time_mm_s

    @classmethod
    def radius_at_station(cls, alignment: "ifcopenshell.entity_instance", station: float) -> float:
        """Curvature radius at ``station``, walked purely from the horizontal
        layout's IfcAlignmentHorizontalSegment design parameters
        (SegmentLength, StartRadiusOfCurvature, EndRadiusOfCurvature) — NO
        geometry engine evaluation, so this works even where map_shape/
        evaluate is unavailable (the win64 packaging gap, IfcOpenShell#9301).

        NOTE: unlike IfcAlignmentVerticalSegment / IfcAlignmentCantSegment,
        IfcAlignmentHorizontalSegment has NO ``StartDistAlong`` attribute (it
        instead carries an absolute ``StartPoint``/``StartDirection``) — so
        "distance along" for the horizontal layout is not stored per segment
        and must be accumulated by summing ``SegmentLength`` in nested order,
        exactly like ``get_alignment_length``/``get_horizontal_extent_semantic``.
        ``station`` uses that same 0-based distance-along convention (station
        0 = the start of the first real segment).

        - LINE segments: no curvature (returns 0.0 — "infinite" radius).
        - CIRCULARARC segments: constant radius = StartRadiusOfCurvature.
        - Spiral/transition segments (CLOTHOID etc.): the true curvature
          varies continuously along the spiral — for a clothoid, curvature
          (1/R) is exactly LINEAR in arc length. This is approximated (exact,
          for a true clothoid) by linearly interpolating CURVATURE (1/R, not
          R directly) between the segment's start and end radius over the
          local distance-along, then inverting back to a radius. A bounding
          radius of ``None``/0 is treated as zero curvature (an infinite
          radius, i.e. the spiral end tangent to a straight).

        Returns 0.0 if the station falls before the first segment, after the
        last, within a LINE segment, or if the alignment has no horizontal
        layout.
        """
        import ifcopenshell.api.alignment as align_api

        h_layout = align_api.get_horizontal_layout(alignment)
        if h_layout is None:
            return 0.0

        distance_along = 0.0
        for segment in align_api.get_layout_segments(h_layout):
            if cls.is_zero_length_segment(segment):
                continue
            dp = getattr(segment, "DesignParameters", None)
            if dp is None or not dp.is_a("IfcAlignmentHorizontalSegment"):
                continue
            length = float(dp.SegmentLength)
            if length <= 0:
                continue
            start = distance_along
            distance_along += length
            if not (start - 1e-9 <= station <= distance_along + 1e-9):
                continue

            predefined_type = dp.PredefinedType
            if predefined_type == "LINE":
                return 0.0

            start_radius = dp.StartRadiusOfCurvature
            end_radius = dp.EndRadiusOfCurvature
            if predefined_type == "CIRCULARARC":
                return abs(float(start_radius)) if start_radius else 0.0

            # Transition / spiral: interpolate CURVATURE (1/R) linearly
            # along the segment's local distance, then invert to radius.
            local = max(0.0, min(1.0, (station - start) / length))
            start_curvature = 1.0 / abs(float(start_radius)) if start_radius else 0.0
            end_curvature = 1.0 / abs(float(end_radius)) if end_radius else 0.0
            curvature = start_curvature + (end_curvature - start_curvature) * local
            return (1.0 / curvature) if abs(curvature) > 1e-12 else 0.0

        return 0.0

    @classmethod
    def compute_cant_checks(
        cls,
        points: list,
        index: int,
        alignment: "ifcopenshell.entity_instance",
        gauge: float,
        limits: dict,
        design_speed: float,
    ) -> dict:
        """Computed values + limit violations for the cant segment running
        from ``points[index]`` to ``points[index + 1]`` (spec 3.2 — a
        point's transition_type carries its value INTO the next point, so
        this is the segment ``points[index]`` governs).

        Args:
            points: Ordered list of dicts with "station", "cant_left",
                "cant_right", "transition_type", "design_speed" (0 = inherit
                ``design_speed``) — see ``CivilCantPointProperties``.
            index: Index of the governing point; requires a "next" point, so
                valid range is ``0 <= index < len(points) - 1`` (mirrors how
                the vertical PVI table has no Grade row after the last PVI).
            alignment: The IfcAlignment entity (radius is looked up via
                ``radius_at_station`` at the segment's START station).
            gauge: Track gauge (model units — metres), fed to
                ``cant_equilibrium``.
            limits: Dict shaped like ``EN13803_DEFAULT_LIMITS`` (possibly
                user-overridden) — a limit is skipped (never flagged) if its
                key is missing.
            design_speed: Alignment-level fallback design speed, used when
                the point's own "design_speed" is 0/unset.

        Returns:
            A dict with keys "radius", "applied_left", "applied_right",
            "applied" (= applied_right - applied_left, the actual
            superelevation — see ``write_cant_segments``'s note on how the
            geometry engine derives cant from the left/right pair),
            "equilibrium", "deficiency" (>= 0, E_eq - applied when
            under-canted, else 0), "excess" (>= 0, applied - E_eq when
            over-canted, else 0), "gradient", "twist_per_length",
            "twist_per_time", and "violations" (list of limit-name strings
            from ``limits`` that are exceeded).

            Returns an all-zero dict with no violations when ``index`` is
            out of the valid range.
        """
        zero_result = {
            "radius": 0.0,
            "applied_left": 0.0,
            "applied_right": 0.0,
            "applied": 0.0,
            "equilibrium": 0.0,
            "deficiency": 0.0,
            "excess": 0.0,
            "gradient": 0.0,
            "twist_per_length": 0.0,
            "twist_per_time": 0.0,
            "violations": [],
        }
        if not (0 <= index < len(points) - 1):
            return zero_result

        point = points[index]
        next_point = points[index + 1]
        station = float(point["station"])
        is_imperial = cls.is_imperial_project()

        speed = float(point.get("design_speed") or 0.0) or float(design_speed or 0.0)

        radius = cls.radius_at_station(alignment, station)
        applied_left = float(point["cant_left"])
        applied_right = float(point["cant_right"])
        applied = applied_right - applied_left

        equilibrium = 0.0
        if speed > 0 and radius > 0 and gauge:
            equilibrium = cls.cant_equilibrium(speed, radius, gauge, is_imperial)
        deficiency = max(0.0, equilibrium - applied)
        excess = max(0.0, applied - equilibrium)

        next_applied = float(next_point["cant_right"]) - float(next_point["cant_left"])
        delta_cant = next_applied - applied
        length = float(next_point["station"]) - station
        gradient = cls.cant_gradient(delta_cant, length, is_imperial)
        twist_per_length, twist_per_time = cls.twist(delta_cant, length, speed, is_imperial)
        raw_rate_ratio = (delta_cant / length) if length > 0 else 0.0

        violations = []
        if limits:
            if "max_applied_cant" in limits and abs(applied) > limits["max_applied_cant"]:
                violations.append("max_applied_cant")
            if "max_deficiency" in limits and deficiency > limits["max_deficiency"]:
                violations.append("max_deficiency")
            if "max_excess" in limits and excess > limits["max_excess"]:
                violations.append("max_excess")
            if "max_cant_gradient" in limits and abs(raw_rate_ratio) > limits["max_cant_gradient"]:
                violations.append("max_cant_gradient")
            if "max_twist" in limits and abs(raw_rate_ratio) > limits["max_twist"]:
                violations.append("max_twist")

        return {
            "radius": radius,
            "applied_left": applied_left,
            "applied_right": applied_right,
            "applied": applied,
            "equilibrium": equilibrium,
            "deficiency": deficiency,
            "excess": excess,
            "gradient": gradient,
            "twist_per_length": twist_per_length,
            "twist_per_time": twist_per_time,
            "violations": violations,
        }

    # =========================================================================
    # Cant — Profile Sampling (spec 3.4, display-only)
    # =========================================================================

    @staticmethod
    def _ramp_linear(xi: float) -> float:
        """LINEARTRANSITION: f(xi) = xi — constant-rate straight-line ramp
        (nonzero slope at both ends)."""
        return xi

    @staticmethod
    def _ramp_bloss(xi: float) -> float:
        """BLOSSCURVE: the cubic "smoothstep" ramp
        f(xi) = 3*xi^2 - 2*xi^3 — zero slope AND zero curvature at both ends
        (the classic S-curve transition). Matches the coefficients used by
        ``ifcopenshell.api.alignment._map_alignment_cant_segment._map_bloss_curve``
        (a0=Ds, a1=0, a2=3f, a3=-2f -> y = Ds + f*(3*xi^2 - 2*xi^3))."""
        return 3.0 * xi**2 - 2.0 * xi**3

    @staticmethod
    def _ramp_cosine(xi: float) -> float:
        """COSINECURVE: f(xi) = 0.5 * (1 - cos(pi * xi)) — a half-cosine
        "raised cosine" ramp, zero slope at both ends."""
        return 0.5 * (1.0 - math.cos(math.pi * xi))

    @staticmethod
    def _ramp_sine(xi: float) -> float:
        """SINECURVE: f(xi) = xi - sin(2*pi*xi) / (2*pi) — zero slope AND
        zero curvature at both ends (a full sine-wave period subtracted from
        the linear ramp)."""
        return xi - math.sin(2.0 * math.pi * xi) / (2.0 * math.pi)

    @staticmethod
    def _ramp_helmert(xi: float) -> float:
        """HELMERTCURVE: the standard two-parabola ("Helmert") ramp — a
        rising parabola on the first half and a mirrored falling-complement
        parabola on the second half, meeting at the midpoint with continuous
        (matching) slope::

            f(xi) = 2*xi^2                for 0 <= xi <= 0.5
            f(xi) = 1 - 2*(1 - xi)^2      for 0.5 <  xi <= 1

        Zero slope at both ends; slope is continuous at the midpoint but
        curvature flips sign there — the defining trait of a Helmert
        (parabolic) transition, as opposed to Bloss's fully continuous
        curvature."""
        if xi <= 0.5:
            return 2.0 * xi**2
        return 1.0 - 2.0 * (1.0 - xi) ** 2

    @classmethod
    def _ramp_for_transition_type(cls, transition_type: str, xi: float) -> float:
        """Dispatch to the normalized ramp f(xi) for a cant transition type.

        ``xi`` is clamped to [0, 1] before dispatch. CONSTANTCANT returns
        0.0 — callers should special-case CONSTANTCANT to hold the segment's
        start value rather than using this ramp at all (see
        ``sample_cant_profile``); 0.0 is a safe default should it ever be
        called directly for CONSTANTCANT.

        VIENNESEBEND approximates with the Bloss ramp (spec 3.4) — the true
        Viennese Bend is a 7th-order polynomial spiral with no simple
        closed-form normalized ramp; Bloss is visually close and shares its
        zero-slope, zero-curvature endpoints.
        """
        xi = max(0.0, min(1.0, xi))
        if transition_type == "LINEARTRANSITION":
            return cls._ramp_linear(xi)
        if transition_type == "HELMERTCURVE":
            return cls._ramp_helmert(xi)
        if transition_type in ("BLOSSCURVE", "VIENNESEBEND"):
            return cls._ramp_bloss(xi)
        if transition_type == "COSINECURVE":
            return cls._ramp_cosine(xi)
        if transition_type == "SINECURVE":
            return cls._ramp_sine(xi)
        if transition_type == "CONSTANTCANT":
            return 0.0
        return cls._ramp_linear(xi)

    @classmethod
    def sample_cant_profile(cls, points: list, stations) -> List[Tuple[float, float, float]]:
        """Sample applied cant (left, right) at each of ``stations`` by
        walking the piecewise-defined cant table ``points`` (spec 3.2/3.4 —
        a point's transition_type carries its value INTO the next point;
        same convention as ``write_cant_segments``).

        Display-only approximation (spec 3.4): each of the seven
        IfcAlignmentCant transition types is reproduced here via its
        STANDARD textbook normalized ramp function f(xi), xi in [0, 1] — NOT
        by re-deriving IfcOpenShell's internal
        IfcSecondOrderPolynomialSpiral / clothoid / etc. arc-length
        parameterization, which the geometry engine uses for the
        authoritative swept geometry. The two should look visually identical
        for any well-formed transition; this sampler exists purely to draw
        the cant band overlay without needing the geometry engine.

        CONSTANTCANT holds the segment's START value flat across the whole
        segment (mirroring ``_map_constant_cant``, which never reads the end
        cant values) — see ``write_cant_segments``'s note on the resulting
        jump if the next point's values differ.

        Args:
            points: Ordered list of cant point dicts (see
                ``write_cant_segments``). Sorted defensively by station.
            stations: Iterable of station values to sample. Stations outside
                the points' station range are clamped to the nearest
                endpoint's values.

        Returns:
            List of ``(station, applied_left, applied_right)`` tuples, one
            per input station, in the same order as ``stations``.
        """
        stations = list(stations)
        if len(points) < 2:
            return [(float(s), 0.0, 0.0) for s in stations]

        ordered = sorted(points, key=lambda p: p["station"])
        first, last = ordered[0], ordered[-1]

        result: List[Tuple[float, float, float]] = []
        for raw_station in stations:
            station = float(raw_station)
            if station <= first["station"]:
                result.append((station, float(first["cant_left"]), float(first["cant_right"])))
                continue
            if station >= last["station"]:
                result.append((station, float(last["cant_left"]), float(last["cant_right"])))
                continue

            for start_point, end_point in zip(ordered, ordered[1:]):
                if start_point["station"] <= station <= end_point["station"]:
                    length = end_point["station"] - start_point["station"]
                    xi = (station - start_point["station"]) / length if length > 0 else 0.0
                    transition_type = start_point.get("transition_type", "LINEARTRANSITION")

                    if transition_type == "CONSTANTCANT":
                        left = float(start_point["cant_left"])
                        right = float(start_point["cant_right"])
                    else:
                        ramp = cls._ramp_for_transition_type(transition_type, xi)
                        left = float(start_point["cant_left"]) + ramp * (
                            float(end_point["cant_left"]) - float(start_point["cant_left"])
                        )
                        right = float(start_point["cant_right"]) + ramp * (
                            float(end_point["cant_right"]) - float(start_point["cant_right"])
                        )
                    result.append((station, left, right))
                    break

        return result

    # =========================================================================
    # Stationing Referents (spec Section 4)
    # =========================================================================
    # Station equations and event referents below all key off the SAME
    # distance_along <-> station conversion
    # (align_api.distance_along_from_station / station_from_distance_along)
    # that the alignment API's stationing nest already respects station
    # equations for -- so once a referent exists here, every downstream
    # reader (the referent list, format_station, the profile view,
    # get_station_ticks, ...) sees the updated stationing automatically. No
    # separate "equation table" is maintained anywhere.

    # Pset used to remember which IfcRelNests a previous commit_layout_change
    # / add_event_referent call created, so repeat calls regenerate/append IN
    # PLACE instead of accumulating orphan nests with duplicate referents.
    # ifcopenshell.api.alignment.update_key_point_referents deliberately has
    # no such lookup of its own -- see its docstring -- callers are expected
    # to track and pass the nest back in themselves.
    _NEST_TRACKING_PSET = "Pset_SaikeiAlignment"
    _KEY_POINT_NEST_PROP = "KeyPointNestId"
    _EVENTS_NEST_PROP = "EventsNestId"

    @classmethod
    def _get_tracked_nest(
        cls, entity: "ifcopenshell.entity_instance", prop_name: str
    ) -> Optional["ifcopenshell.entity_instance"]:
        """Return the IfcRelNests previously recorded on ``entity`` under
        ``prop_name`` (Pset_SaikeiAlignment), or None if never set or stale
        (e.g. deleted since it was recorded)."""
        import ifcopenshell.util.element

        pset = ifcopenshell.util.element.get_pset(entity, cls._NEST_TRACKING_PSET, should_inherit=False)
        if not pset or pset.get(prop_name) is None:
            return None
        ifc_file = tool.Ifc.get()
        try:
            nest = ifc_file.by_id(int(pset[prop_name]))
        except RuntimeError:
            return None
        return nest if nest.is_a("IfcRelNests") else None

    @classmethod
    def _set_tracked_nest(
        cls, entity: "ifcopenshell.entity_instance", prop_name: str, nest: "ifcopenshell.entity_instance"
    ) -> None:
        """Persist ``nest``'s id on ``entity`` under ``prop_name`` for a
        later ``_get_tracked_nest`` lookup (mirrors ``set_design_criteria`` /
        ``set_cant_rotation_reference``'s pset-upsert pattern)."""
        import ifcopenshell.api.pset
        import ifcopenshell.util.element

        ifc_file = tool.Ifc.get()
        existing = ifcopenshell.util.element.get_pset(entity, cls._NEST_TRACKING_PSET, should_inherit=False)
        if existing:
            pset_entity = ifc_file.by_id(existing["id"])
        else:
            pset_entity = ifcopenshell.api.pset.add_pset(ifc_file, product=entity, name=cls._NEST_TRACKING_PSET)
        ifcopenshell.api.pset.edit_pset(ifc_file, pset=pset_entity, properties={prop_name: nest.id()})

    @classmethod
    def commit_layout_change(cls, alignment: "ifcopenshell.entity_instance") -> int:
        """THE single post-write funnel every operation that (re)writes
        horizontal, vertical, or cant layout segments should call once its
        IFC write has succeeded (spec 4.2): core.exit_pi_edit_mode /
        core.exit_pvi_edit_mode / core.update_cant_segments, and the two
        operator-layer write paths that predate core routing for their
        alignment_tool calls (CIVIL_OT_recalculate_pis's
        ``_build_alignment_from_active_pis`` helper, and
        CIVIL_OT_recalculate_pvis).

        For each layout that exists on ``alignment`` (horizontal, vertical,
        cant -- only those actually present are processed), regenerates
        that layout's key-point referent nest via
        ``update_key_point_referents(clear=True)``, reusing the SAME
        IfcRelNests across calls (via ``_get_tracked_nest`` /
        ``_set_tracked_nest``) so repeated commits regenerate in place
        instead of accumulating orphan nests with duplicate referents.

        A ``RuntimeError`` raised by the geometry engine (the win64
        packaging gap, IfcOpenShell#9301 -- "No geometry mapping
        registered") is caught NARROWLY per layout: that layout's
        key-point referents are simply skipped this time, but the commit as
        a whole -- and the caller's already-successful IFC write -- is
        never failed because of it. Any other RuntimeError re-raises.

        Also refreshes a live ``StationTickDecorator`` overlay (spec 4.1),
        if one is currently installed, so station ticks stay in sync with
        the segments that were just (re)written.

        Also resyncs every offset alignment recorded against ``alignment``
        (spec 1.7's "Updates with the parent") via
        ``resync_offset_alignments`` -- purely semantic (no geometry engine
        needed), so it always runs, unlike the key-point referent loop
        above.

        Returns:
            Total count of key-point referents (re)created across all
            layouts that were successfully processed (0 if none were, e.g.
            no geometry engine available anywhere). Does NOT include the
            offset-alignment resync count -- see ``resync_offset_alignments``
            directly if that count is needed.
        """
        import ifcopenshell.api.alignment as align_api

        ifc_file = tool.Ifc.get()
        total = 0

        layouts_to_process = [cls.get_horizontal_layout(alignment), cls.get_cant_layout(alignment)]
        layouts_to_process.extend(cls.get_vertical_layouts(alignment))

        for layout in layouts_to_process:
            if layout is None:
                continue
            existing_nest = cls._get_tracked_nest(layout, cls._KEY_POINT_NEST_PROP)
            try:
                nest = align_api.update_key_point_referents(ifc_file, layout, rel_nests=existing_nest, clear=True)
            except RuntimeError as e:
                if "geometry mapping" not in str(e).lower():
                    raise
                continue
            cls._set_tracked_nest(layout, cls._KEY_POINT_NEST_PROP, nest)
            total += len(nest.RelatedObjects)

        from bonsai.bim.module.alignment import decorator as alignment_decorator

        tick_decorator = alignment_decorator.StationTickDecorator
        if tick_decorator.is_installed:
            tick_decorator.refresh()

        cls.resync_offset_alignments(alignment)

        return total

    @classmethod
    def get_station_ticks(
        cls, alignment: "ifcopenshell.entity_instance", interval: float
    ) -> List[Tuple[Tuple[float, float, float], Tuple[float, float, float], float]]:
        """Sample station-tick positions along ``alignment`` for the
        viewport tick/label overlay (spec 4.1).

        Ticks land at round STATION values (start_station, start_station +
        interval, ...), matching civil-engineering drafting convention --
        NOT at even distance-along spacing -- so ticks stay at round
        station numbers even across a station equation (see
        ``_station_samples``, shared with ``sample_design_profile``'s D2
        sampling). Each tick is evaluated via
        ``evaluate_alignment_at_station``, so this degrades gracefully:
        - No geometry engine available (IfcOpenShell#9301) -> every station
          evaluates to None -> [] is returned.
        - A station inside a forward (gap) station equation -> that single
          tick is skipped; the rest are unaffected.

        Args:
            alignment: The IfcAlignment entity.
            interval: Spacing between ticks, in station units (project
                length units).

        Returns:
            List of ``(position_xyz, direction_xyz, station)`` tuples, one
            per tick that could be evaluated. ``position_xyz`` is scaled to
            Blender viewport (BU) space -- the same convention
            ``create_3d_alignment_object`` uses -- so callers
            (``StationTickDecorator``) draw it directly with no further
            unit conversion. ``direction_xyz`` is the (already unit-length,
            scale-invariant) tangent vector.
        """
        import ifcopenshell.util.unit

        length = cls.get_alignment_length(alignment)
        if not length or length <= 0:
            return []
        start_station = cls.get_alignment_start_station(alignment)
        unit_scale = ifcopenshell.util.unit.calculate_unit_scale(tool.Ifc.get())

        ticks = []
        for station in cls._station_samples(start_station, length, interval):
            evaluated = cls.evaluate_alignment_at_station(alignment, station)
            if evaluated is None:
                continue
            position = (
                evaluated.position[0] * unit_scale,
                evaluated.position[1] * unit_scale,
                evaluated.position[2] * unit_scale,
            )
            ticks.append((position, evaluated.tangent, evaluated.station))
        return ticks

    @classmethod
    def get_referents(cls, alignment: "ifcopenshell.entity_instance") -> List[dict]:
        """Return every IfcReferent nested (directly, via any IfcRelNests)
        on ``alignment`` -- spec 4.2's referent list: stationing referents
        (STATION, from ``add_stationing_referent`` / the station-equation
        wrapper below), key-point referents (POSITION, from
        ``commit_layout_change`` -> ``update_key_point_referents``), and
        event referents (SUPERELEVATIONEVENT / WIDTHEVENT, from
        ``add_event_referent``) alike.

        Referents positioned via ``ifcopenshell.api.alignment.
        add_positioning_referent`` are NOT nested to the alignment at all
        (that API links them to their ``positioned_product`` via
        ``IfcRelPositions`` instead, by design -- see its docstring) so they
        never appear here: this is the alignment's own referent list, not a
        global referent index.

        Args:
            alignment: The IfcAlignment entity.

        Returns:
            Dicts sorted by station ascending (entries with no resolvable
            Pset_Stationing.Station sort last): ``{"id", "name",
            "predefined_type", "station", "is_equation",
            "incoming_station"}``. ``station`` / ``incoming_station`` are
            ``None`` when Pset_Stationing / its ``IncomingStation`` is
            absent.
        """
        import ifcopenshell.util.element

        seen_ids = set()
        referents = []
        for rel in alignment.IsNestedBy or []:
            for obj in rel.RelatedObjects or []:
                if not obj.is_a("IfcReferent") or obj.id() in seen_ids:
                    continue
                seen_ids.add(obj.id())

                pset = ifcopenshell.util.element.get_pset(obj, "Pset_Stationing", should_inherit=False)
                station = None
                incoming_station = None
                if pset:
                    if pset.get("Station") is not None:
                        station = float(pset["Station"])
                    if pset.get("IncomingStation") is not None:
                        incoming_station = float(pset["IncomingStation"])

                referents.append(
                    {
                        "id": obj.id(),
                        "name": obj.Name or "",
                        "predefined_type": obj.PredefinedType,
                        "station": station,
                        "is_equation": incoming_station is not None,
                        "incoming_station": incoming_station,
                    }
                )

        referents.sort(key=lambda r: (r["station"] is None, r["station"] if r["station"] is not None else 0.0))
        return referents

    @classmethod
    def distance_along_from_station(cls, alignment: "ifcopenshell.entity_instance", station: float) -> Optional[float]:
        """Thin wrapper over ``align_api.distance_along_from_station`` (spec
        4.3) -- resolves a station (respecting any existing station
        equations) to a distance along the alignment, or None if the
        station falls inside a forward (gap) equation."""
        import ifcopenshell.api.alignment as align_api

        return align_api.distance_along_from_station(tool.Ifc.get(), alignment, station)

    @classmethod
    def add_station_equation_referent(
        cls,
        alignment: "ifcopenshell.entity_instance",
        distance_along: float,
        back_station: float,
        ahead_station: float,
    ) -> "ifcopenshell.entity_instance":
        """Author a station-equation STATION referent (spec 4.3): the point
        at ``distance_along`` where stationing switches from
        ``back_station`` (incoming, in the EXISTING sequence) to
        ``ahead_station`` (outgoing) -- a gap (ahead > back) or an overlap
        (ahead < back) are both legal surveying practice; only refusing an
        equal back/ahead pair is ``core.add_station_equation``'s job, not
        this thin authoring wrapper's.

        A thin wrapper over ``align_api.add_stationing_referent``'s
        ``incoming_station`` parameter -- the exact mechanism
        ``distance_along_from_station`` / ``station_from_distance_along``
        already key off of, so every downstream reader (the referent list,
        ``format_station``, the profile view, ``get_station_ticks``, ...)
        respects the equation automatically once this referent exists; no
        separate "equation table" is maintained anywhere.

        Returns:
            The created IfcReferent (``PredefinedType="STATION"``).
        """
        import ifcopenshell.api.alignment as align_api

        ifc_file = tool.Ifc.get()
        name = f"STA EQN {cls.format_station(back_station)}={cls.format_station(ahead_station)}"
        return align_api.add_stationing_referent(
            ifc_file,
            name=name,
            alignment=alignment,
            distance_along=distance_along,
            station=ahead_station,
            incoming_station=back_station,
        )

    @classmethod
    def add_event_referent(
        cls,
        alignment: "ifcopenshell.entity_instance",
        event_type: str,
        station: float,
        name: str = "",
        value: Optional[float] = None,
    ) -> "ifcopenshell.entity_instance":
        """Author an event referent (spec 4.4): a station-located marker
        (``SUPERELEVATIONEVENT`` or ``WIDTHEVENT``) for a future
        corridor-consuming event; carries no geometry consequence of its
        own here (corridor generation, when it exists, is the eventual
        consumer -- out of scope for this pass).

        Mirrors ``align_api.add_stationing_referent``'s IfcReferent +
        placement construction (basis-curve ``IfcLinearPlacement`` when the
        alignment has a real composite curve, ``IfcLocalPlacement``
        fallback otherwise) -- that function hardcodes
        ``PredefinedType="STATION"`` so it cannot be reused directly for an
        event referent. Nested into a DEDICATED events ``IfcRelNests``
        (tracked via ``Pset_SaikeiAlignment.EventsNestId`` on the alignment,
        alongside the per-layout key-point nest tracking above) -- not the
        stationing nest (``get_stationing_nest`` filters to
        ``PredefinedType=="STATION"`` only, so an event referent nested
        there would never be found again by that lookup) and not a
        key-point nest (those are wholly owned and periodically wiped by
        ``commit_layout_change``).

        Args:
            alignment: The IfcAlignment entity.
            event_type: ``"SUPERELEVATIONEVENT"`` or ``"WIDTHEVENT"``.
            station: Station value for the event (project stationing;
                station equations are NOT resolved to a precise
                distance_along here -- if the station falls inside a gap,
                the referent is still recorded at distance_along 0.0 rather
                than silently dropped; corridor consumption, out of scope,
                would need to handle that same ambiguity itself).
            name: Referent name; auto-generated from the formatted station
                and event type when blank.
            value: Optional payload value (e.g. target superelevation or
                width), recorded in ``Pset_SaikeiEvent.Value`` when given.

        Returns:
            The created IfcReferent.
        """
        import ifcopenshell.api.alignment as align_api
        import ifcopenshell.api.pset
        import ifcopenshell.guid

        ifc_file = tool.Ifc.get()

        distance_along = align_api.distance_along_from_station(ifc_file, alignment, station)
        if distance_along is None:
            distance_along = 0.0

        curve = align_api.get_basis_curve(alignment)
        if curve and curve.is_a("IfcCompositeCurve") and 0 < len(curve.Segments):
            object_placement = ifc_file.createIfcLinearPlacement(
                RelativePlacement=ifc_file.createIfcAxis2PlacementLinear(
                    Location=ifc_file.createIfcPointByDistanceExpression(
                        DistanceAlong=ifc_file.createIfcLengthMeasure(distance_along),
                        OffsetLateral=None,
                        OffsetVertical=None,
                        OffsetLongitudinal=None,
                        BasisCurve=curve,
                    )
                ),
            )
            # Deliberately NOT calling align_api.update_fallback_position
            # here (unlike add_stationing_referent, which this otherwise
            # mirrors): that helper's ENTIRE job is populating
            # IfcLinearPlacement.CartesianPosition, an OPTIONAL fallback for
            # consumers that cannot resolve parametric placements -- not
            # required for a valid, complete semantic model, and computing
            # it requires the geometry engine (ifcopenshell.util.placement.
            # get_local_placement -> ifcopenshell.geom.create_shape). Event
            # referents are a Saikei extension, not an upstream API
            # behavior to mirror exactly, so this keeps add_event_referent
            # fully semantic -- consistent with "semantic authoring works"
            # even where geometry evaluation doesn't (IfcOpenShell#9301).
        else:
            object_placement = ifc_file.createIfcLocalPlacement(
                PlacementRelTo=None,
                RelativePlacement=ifc_file.createIfcAxis2Placement2D(
                    Location=ifc_file.createIfcCartesianPoint(
                        alignment.ObjectPlacement.RelativePlacement.Location.Coordinates
                    )
                ),
            )

        referent_name = name or f"{cls.format_station(station)} ({event_type.replace('EVENT', '').title()} Event)"

        referent = ifc_file.createIfcReferent(
            GlobalId=ifcopenshell.guid.new(),
            OwnerHistory=None,
            Name=referent_name,
            Description=None,
            ObjectType=None,
            ObjectPlacement=object_placement,
            Representation=None,
            PredefinedType=event_type,
        )

        pset_stationing = ifcopenshell.api.pset.add_pset(ifc_file, product=referent, name="Pset_Stationing")
        ifcopenshell.api.pset.edit_pset(ifc_file, pset=pset_stationing, properties={"Station": float(station)})

        if value is not None:
            pset_event = ifcopenshell.api.pset.add_pset(ifc_file, product=referent, name="Pset_SaikeiEvent")
            ifcopenshell.api.pset.edit_pset(ifc_file, pset=pset_event, properties={"Value": float(value)})

        nest = cls._get_tracked_nest(alignment, cls._EVENTS_NEST_PROP)
        if nest is None:
            nest = ifc_file.createIfcRelNests(
                GlobalId=ifcopenshell.guid.new(), RelatingObject=alignment, RelatedObjects=(referent,)
            )
            cls._set_tracked_nest(alignment, cls._EVENTS_NEST_PROP, nest)
        else:
            nest.RelatedObjects = tuple(nest.RelatedObjects) + (referent,)

        return referent

    @classmethod
    def remove_referent(cls, alignment: "ifcopenshell.entity_instance", referent_id: int) -> None:
        """Delete a referent entity (spec 4.1, "Deletable"): its
        Pset_Stationing / Pset_SaikeiEvent property sets, its
        ObjectPlacement (if exclusively owned by it), and finally the
        referent itself. Mirrors the alignment API's own (private,
        non-exported) ``_remove_referent`` cleanup used internally by
        ``update_key_point_referents(clear=True)``.

        ``file.remove()`` also strips the referent out of any
        IfcRelNests.RelatedObjects referencing it, so no separate nest
        bookkeeping is needed here -- including the events / key-point
        nests tracked above, which simply end up with one fewer entry.

        Args:
            alignment: The IfcAlignment entity (unused directly -- kept for
                signature symmetry with the other referent methods, and in
                case a future revision needs to validate ownership here
                rather than in core).
            referent_id: The IFC id of the referent to delete.
        """
        import ifcopenshell.api.pset
        import ifcopenshell.util.element

        ifc_file = tool.Ifc.get()
        referent = ifc_file.by_id(referent_id)

        for inverse in list(ifc_file.get_inverse(referent)):
            if inverse.is_a("IfcRelDefinesByProperties"):
                ifcopenshell.api.pset.remove_pset(ifc_file, product=referent, pset=inverse.RelatingPropertyDefinition)

        object_placement = referent.ObjectPlacement
        if object_placement and ifc_file.get_total_inverses(object_placement) == 1:
            referent.ObjectPlacement = None
            ifcopenshell.util.element.remove_deep2(ifc_file, object_placement)

        ifc_file.remove(referent)

    # =========================================================================
    # Offset Alignments (spec 1.7)
    # =========================================================================
    # An offset alignment is a bare IfcAlignment whose ONLY representation is
    # an IfcOffsetCurveByDistances riding on the parent's current curve
    # (whatever align_api.get_curve(parent) returns -- IfcCompositeCurve for
    # horizontal-only, IfcGradientCurve once a vertical exists, etc). It has
    # no layouts of its own (no PI/PVI table), so create_hierarchy_for_
    # alignment degrades gracefully to just the root Empty -- there are no
    # nested IfcAlignmentHorizontal/Vertical/Cant to walk.
    #
    # "Updates with the parent" (spec 1.7) is implemented as a resync funnel:
    # the offset's recorded spec (Pset_SaikeiOffset) is the source of truth,
    # and resync_offset_alignments() rebuilds the IfcPointByDistanceExpression
    # table from it against the parent's CURRENT curve + extent every time
    # commit_layout_change() runs for the parent.

    _OFFSET_PSET = "Pset_SaikeiOffset"

    @classmethod
    def get_curve_for_alignment(cls, alignment: "ifcopenshell.entity_instance"):
        """Return ``alignment``'s top-level geometric representation curve
        (IfcPolyLine/IfcIndexedPolyCurve/IfcCompositeCurve/IfcGradientCurve/
        IfcSegmentedReferenceCurve/IfcOffsetCurveByDistances, depending on
        what's present), or None. Thin wrapper over ``align_api.get_curve``
        so core never has to import ``ifcopenshell.api`` directly.
        """
        import ifcopenshell.api.alignment as align_api

        return align_api.get_curve(alignment)

    @classmethod
    def _build_offset_points(
        cls,
        ifc_file: "ifcopenshell.file",
        basis_curve: "ifcopenshell.entity_instance",
        offset_spec: dict,
        extent: float,
    ) -> List["ifcopenshell.entity_instance"]:
        """Build the ``IfcPointByDistanceExpression`` list an
        ``IfcOffsetCurveByDistances`` needs, from an offset spec dict and
        the parent's CURRENT horizontal extent (spec 1.7).

        ``offset_spec`` is ``{"mode": "CONSTANT", "offset": float}`` or
        ``{"mode": "TAPER", "start_offset": float, "end_offset": float,
        "station_from": float, "station_to": float}`` -- "station" here
        follows the same convention as the cant point table
        (``write_cant_segments``): a 0-based DISTANCE-ALONG the alignment,
        not a true engineering station offset by start_station.

        CONSTANT produces two points holding the same offset across the
        whole extent. TAPER produces up to four points -- ``(0,
        start_offset)``, ``(station_from, start_offset)``, ``(station_to,
        end_offset)``, ``(extent, end_offset)`` -- a flat run, a linear
        ramp, then another flat run; ``station_from``/``station_to`` are
        clamped into ``[0, extent]`` and consecutive points at the same
        station are merged (keeping the later value) so a taper that
        touches either end of the extent doesn't emit a duplicate
        DistanceAlong.
        """
        mode = offset_spec.get("mode", "CONSTANT")
        if mode == "TAPER":
            start_offset = float(offset_spec.get("start_offset", 0.0))
            end_offset = float(offset_spec.get("end_offset", 0.0))
            station_from = max(0.0, min(float(offset_spec.get("station_from", 0.0)), extent))
            station_to = max(station_from, min(float(offset_spec.get("station_to", extent)), extent))
            raw_points = [
                (0.0, start_offset),
                (station_from, start_offset),
                (station_to, end_offset),
                (extent, end_offset),
            ]
        else:
            offset = float(offset_spec.get("offset", 0.0))
            raw_points = [(0.0, offset), (extent, offset)]

        merged: List[Tuple[float, float]] = []
        for station, offset_value in raw_points:
            if merged and abs(merged[-1][0] - station) < 1e-9:
                merged[-1] = (station, offset_value)
            else:
                merged.append((station, offset_value))

        return [
            ifc_file.createIfcPointByDistanceExpression(
                DistanceAlong=ifc_file.createIfcLengthMeasure(station),
                OffsetLateral=offset_value,
                BasisCurve=basis_curve,
            )
            for station, offset_value in merged
        ]

    @classmethod
    def _write_offset_pset(
        cls, offset_alignment: "ifcopenshell.entity_instance", parent: "ifcopenshell.entity_instance", offset_spec: dict
    ) -> None:
        """Persist ``offset_spec`` (plus the parent's GlobalId) on
        ``offset_alignment`` as Pset_SaikeiOffset -- IFC 4.3 has no standard
        pset for an offset's design intent, so this rides in a Saikei pset,
        both for save/reopen round-trip and as the source of truth
        ``resync_offset_alignments`` rebuilds from (mirrors
        ``set_design_criteria``'s pset-upsert pattern).
        """
        import ifcopenshell.api.pset

        ifc_file = tool.Ifc.get()
        mode = offset_spec.get("mode", "CONSTANT")
        properties = {"ParentGlobalId": parent.GlobalId, "Mode": mode}
        if mode == "TAPER":
            properties.update(
                StartOffset=float(offset_spec.get("start_offset", 0.0)),
                EndOffset=float(offset_spec.get("end_offset", 0.0)),
                StationFrom=float(offset_spec.get("station_from", 0.0)),
                StationTo=float(offset_spec.get("station_to", 0.0)),
            )
        else:
            properties["Offset"] = float(offset_spec.get("offset", 0.0))

        existing = ifcopenshell.util.element.get_pset(offset_alignment, cls._OFFSET_PSET, should_inherit=False)
        if existing:
            pset_entity = ifc_file.by_id(existing["id"])
        else:
            pset_entity = ifcopenshell.api.pset.add_pset(ifc_file, product=offset_alignment, name=cls._OFFSET_PSET)
        ifcopenshell.api.pset.edit_pset(ifc_file, pset=pset_entity, properties=properties)

    @classmethod
    def get_offset_spec(cls, offset_alignment: "ifcopenshell.entity_instance") -> Optional[dict]:
        """Return the recorded offset spec (Pset_SaikeiOffset), reshaped
        back into the same dict shape ``_build_offset_points``/
        ``create_offset_alignment`` accept (plus ``parent_global_id``), or
        None if ``offset_alignment`` was never authored as an offset (or the
        pset is missing/incomplete).
        """
        import ifcopenshell.util.element

        pset = ifcopenshell.util.element.get_pset(offset_alignment, cls._OFFSET_PSET, should_inherit=False)
        if not pset or "Mode" not in pset or "ParentGlobalId" not in pset:
            return None

        mode = pset["Mode"]
        spec: dict = {"mode": mode, "parent_global_id": pset["ParentGlobalId"]}
        if mode == "TAPER":
            spec.update(
                start_offset=float(pset.get("StartOffset", 0.0)),
                end_offset=float(pset.get("EndOffset", 0.0)),
                station_from=float(pset.get("StationFrom", 0.0)),
                station_to=float(pset.get("StationTo", 0.0)),
            )
        else:
            spec["offset"] = float(pset.get("Offset", 0.0))
        return spec

    @classmethod
    def find_offset_children(cls, parent: "ifcopenshell.entity_instance") -> List["ifcopenshell.entity_instance"]:
        """Return every IfcAlignment in the file whose Pset_SaikeiOffset
        records ``parent`` as its ParentGlobalId (spec 1.7's "listed as its
        child" set) -- offset alignments are NOT IfcRelAggregates children
        of the parent (they have their own top-level GlobalId, per
        ``create_as_offset_curve``), so this is a pset scan, not a
        decomposition walk.
        """
        ifc_file = tool.Ifc.get()
        parent_guid = parent.GlobalId
        children = []
        for candidate in ifc_file.by_type("IfcAlignment"):
            if candidate == parent:
                continue
            spec = cls.get_offset_spec(candidate)
            if spec and spec.get("parent_global_id") == parent_guid:
                children.append(candidate)
        return children

    @classmethod
    def create_offset_alignment(
        cls, parent: "ifcopenshell.entity_instance", name: str, offset_spec: dict
    ) -> "ifcopenshell.entity_instance":
        """Create an offset alignment riding on ``parent``'s current curve
        (spec 1.7). Builds the IfcPointByDistanceExpression table from
        ``offset_spec`` via ``_build_offset_points``, authors the bare
        IfcAlignment through ``align_api.create_as_offset_curve`` (parent's
        start station honored, same as every other create path), records
        ``offset_spec`` as Pset_SaikeiOffset for the resync funnel, and
        parents the new alignment's Blender object under the parent's own
        object so it shows as the parent's child in the outliner.

        Args:
            parent: The alignment being offset from -- must already have a
                curve (validated by ``core.create_offset_alignment``).
            name: Name for the new IfcAlignment.
            offset_spec: See ``_build_offset_points``'s docstring for shape.

        Returns:
            The newly created (offset) IfcAlignment entity.
        """
        import ifcopenshell.api.alignment as align_api

        ifc_file = tool.Ifc.get()
        basis_curve = align_api.get_curve(parent)
        extent = cls.get_horizontal_extent_semantic(parent)
        points = cls._build_offset_points(ifc_file, basis_curve, offset_spec, extent)

        start_station = cls.get_alignment_start_station(parent)
        offset_alignment = align_api.create_as_offset_curve(ifc_file, name, points, start_station=start_station)

        cls._write_offset_pset(offset_alignment, parent, offset_spec)

        # Offset alignments have no layouts -- create_hierarchy_for_alignment
        # degrades gracefully to just the root Empty (no Horizontal/Vertical/
        # Cant children to walk). Parent it under the parent's own object so
        # it appears as the parent's child in the outliner.
        offset_obj = cls.create_hierarchy_for_alignment(offset_alignment)
        parent_obj = tool.Ifc.get_object(parent)
        if offset_obj and parent_obj:
            offset_obj.parent = parent_obj
            if parent_obj.users_collection:
                target_collection = parent_obj.users_collection[0]
                for collection in list(offset_obj.users_collection):
                    if collection != target_collection:
                        collection.objects.unlink(offset_obj)
                if offset_obj.name not in target_collection.objects:
                    target_collection.objects.link(offset_obj)

        return offset_alignment

    @classmethod
    def resync_offset_alignments(cls, parent: "ifcopenshell.entity_instance") -> int:
        """Rebuild every offset alignment recorded against ``parent`` so it
        tracks the parent's CURRENT curve and extent (spec 1.7: "Updates
        with the parent"). Called from ``commit_layout_change`` so every
        PI/PVI/cant write that succeeds also refreshes any offsets.

        A plain PI recalculation keeps the SAME curve entity (only its
        Segments are replaced by ``clear_layout_segments`` / the layout
        API), so an offset's BasisCurve reference stays valid on its own in
        that case. But ``align_api.get_curve(parent)`` can start returning a
        DIFFERENT top-level entity -- e.g. adding a vertical layout wraps
        the old IfcCompositeCurve in a new IfcGradientCurve -- so this always
        re-fetches the parent's current curve and repoints, even when that
        turns out to be a no-op.

        Purely semantic: only constructs entities and mutates attributes, no
        geometry engine evaluation, so it works even under the win64
        packaging gap (IfcOpenShell#9301).

        Returns:
            Number of offset alignments resynced (0 if ``parent`` has none,
            or its curve is currently unavailable).
        """
        import ifcopenshell.util.element

        current_curve = cls.get_curve_for_alignment(parent)
        if current_curve is None:
            return 0

        children = cls.find_offset_children(parent)
        if not children:
            return 0

        ifc_file = tool.Ifc.get()
        extent = cls.get_horizontal_extent_semantic(parent)

        count = 0
        for offset_alignment in children:
            spec = cls.get_offset_spec(offset_alignment)
            if spec is None:
                continue
            curve = cls.get_curve_for_alignment(offset_alignment)
            if curve is None or not curve.is_a("IfcOffsetCurveByDistances"):
                continue

            old_points = list(curve.OffsetValues or [])
            new_points = cls._build_offset_points(ifc_file, current_curve, spec, extent)

            curve.BasisCurve = current_curve
            curve.OffsetValues = new_points

            for old_point in old_points:
                if old_point not in new_points:
                    ifcopenshell.util.element.remove_deep2(ifc_file, old_point)

            count += 1
        return count

    # =========================================================================
    # Convert Curve to Alignment (spec 1.8)
    # =========================================================================

    @classmethod
    def extract_polyline_from_curve(
        cls, obj: "bpy.types.Object", sample_resolution: Optional[int] = None
    ) -> List[Tuple[float, float, float]]:
        """Extract an ordered polyline (world-space XYZ) approximating a
        Blender CURVE object's shape (spec 1.8). Only the FIRST spline is
        used -- a multi-spline curve object is not a single alignment
        candidate.

        POLY splines are read directly (their control points ARE the
        polyline). BEZIER/NURBS splines are sampled via Blender's own
        curve-to-mesh evaluation (respecting the spline's own
        ``resolution_u``, optionally overridden by ``sample_resolution`` for
        the duration of this call) -- dependency-light (no separate spline
        math), producing a faithful polyline for the RDP simplification step
        that follows.

        Args:
            obj: A Blender CURVE object with at least one spline.
            sample_resolution: Optional override for ``resolution_u`` on
                every spline of ``obj`` for the duration of this extraction
                (restored afterward). None uses the curve's own settings.

        Returns:
            List of (x, y, z) world-space tuples, in curve point order.
            Empty list if ``obj`` is not a CURVE or has no splines/points.
        """
        if obj is None or obj.type != "CURVE" or not obj.data.splines:
            return []

        spline = obj.data.splines[0]

        if spline.type == "POLY":
            return [tuple(obj.matrix_world @ point.co.to_3d()) for point in spline.points]

        original_resolutions = None
        if sample_resolution is not None:
            original_resolutions = [s.resolution_u for s in obj.data.splines]
            for s in obj.data.splines:
                s.resolution_u = max(1, int(sample_resolution))

        try:
            depsgraph = bpy.context.evaluated_depsgraph_get()
            obj_eval = obj.evaluated_get(depsgraph)
            mesh = obj_eval.to_mesh()
            points = [tuple(obj.matrix_world @ vertex.co) for vertex in mesh.vertices]
            obj_eval.to_mesh_clear()
        finally:
            if original_resolutions is not None:
                for s, resolution in zip(obj.data.splines, original_resolutions):
                    s.resolution_u = resolution

        return points

    @classmethod
    def simplify_polyline(cls, points: List[Tuple[float, float]], tolerance: float) -> List[Tuple[float, float]]:
        """Ramer-Douglas-Peucker polyline simplification (spec 1.8) over 2D
        ``(x, y)`` points -- pure math, no IFC/Blender dependency.

        Recursively keeps the point with the greatest perpendicular
        distance from the chord between the current segment's endpoints,
        as long as that distance exceeds ``tolerance``; splits at that point
        and recurses on both halves. The first and last points are always
        kept.

        Args:
            points: Ordered (x, y) points.
            tolerance: Maximum perpendicular deviation allowed for a point
                to be dropped, in the same units as ``points``.

        Returns:
            The simplified point list (a subset of ``points``, same order).
            Returned as-is (a shallow copy) if there are fewer than 3 points
            or ``tolerance <= 0``.
        """
        if len(points) < 3 or tolerance <= 0.0:
            return list(points)

        def _perpendicular_distance(point, start, end) -> float:
            x, y = point
            x1, y1 = start
            x2, y2 = end
            dx, dy = x2 - x1, y2 - y1
            if dx == 0.0 and dy == 0.0:
                return math.hypot(x - x1, y - y1)
            t = ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)
            proj_x, proj_y = x1 + t * dx, y1 + t * dy
            return math.hypot(x - proj_x, y - proj_y)

        def _rdp(subset: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
            if len(subset) < 3:
                return subset
            start, end = subset[0], subset[-1]
            max_distance = -1.0
            split_index = 0
            for i in range(1, len(subset) - 1):
                distance = _perpendicular_distance(subset[i], start, end)
                if distance > max_distance:
                    max_distance = distance
                    split_index = i
            if max_distance > tolerance:
                left = _rdp(subset[: split_index + 1])
                right = _rdp(subset[split_index:])
                return left[:-1] + right
            return [start, end]

        return _rdp(list(points))

    @classmethod
    def count_distinct_points(cls, points: List[Tuple[float, float]], epsilon: float = 1e-6) -> int:
        """Count points in ``points`` that are NOT within ``epsilon`` of the
        immediately preceding KEPT point -- a minimal 2D coincidence filter
        (spec 1.8) used to validate a simplified polyline has enough
        distinct PIs to build an alignment from.
        """
        if not points:
            return 0
        count = 1
        last = points[0]
        for point in points[1:]:
            if math.hypot(point[0] - last[0], point[1] - last[1]) > epsilon:
                count += 1
                last = point
        return count

    @classmethod
    def convert_points_to_alignment(cls, name: str, points_xy: list) -> "ifcopenshell.entity_instance":
        """Create a new all-tangent horizontal alignment from 2D points
        (spec 1.8), via the same create + layout_by_pi_method path
        ``create_alignment``/``_build_alignment_from_active_pis`` use. Every
        PI is a plain tangent point (radius 0.0) -- users add curves
        afterward in the PI editor.

        ``points_xy`` are Blender WORLD-SPACE (x, y) coordinates (Z already
        discarded per spec 1.1's XY-plane rule). They are converted to local
        IFC coordinates through the SAME round trip the PI picker uses
        (``_transfer_polyline_to_pis`` / ``_build_alignment_from_active_pis``
        in ``bim.module.alignment.operator``): world -> unit_scale -> local
        -> ``tool.Georeference.xyz2enh`` -> global E/N -> ``auto_enh2xyz`` ->
        local again -- so a curve-derived alignment lands in exactly the
        frame an interactively-picked one would, including in a
        georeferenced project where that round trip is not a no-op.

        Args:
            name: Name for the new IfcAlignment.
            points_xy: Ordered (x, y) world-space points, at least 2.

        Returns:
            The newly created IfcAlignment entity.
        """
        import ifcopenshell.api.alignment as align_api
        import ifcopenshell.util.geolocation
        import ifcopenshell.util.unit

        ifc_file = tool.Ifc.get()
        unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc_file)

        hpoints = []
        for x, y in points_xy:
            local = (x / unit_scale, y / unit_scale, 0.0)
            enh = tool.Georeference.xyz2enh(local)
            local_back = ifcopenshell.util.geolocation.auto_enh2xyz(ifc_file, float(enh[0]), float(enh[1]), 0.0)
            hpoints.append([float(local_back[0]), float(local_back[1])])

        alignment = cls.create_alignment(name)
        h_layout = align_api.get_horizontal_layout(alignment)

        radii = [0.0] * max(0, len(hpoints) - 2)
        cls.layout_by_pi_method(h_layout, hpoints, radii)

        alignment_obj = tool.Ifc.get_object(alignment)
        layout_obj = tool.Ifc.get_object(h_layout)
        if not layout_obj and alignment_obj:
            layout_obj = cls.create_object_for_layout(h_layout, alignment_obj)
        if layout_obj:
            cls.create_objects_for_layout_segments(h_layout, layout_obj)

        cls.commit_layout_change(alignment)
        return alignment

    # =========================================================================
    # Multi-Vertical Selector (spec 2.1)
    # =========================================================================

    @classmethod
    def get_vertical_layouts(cls, alignment: "ifcopenshell.entity_instance") -> list:
        """Return EVERY IfcAlignmentVertical associated with ``alignment``
        -- the one nested directly on it (if any) followed by one per
        aggregated child alignment (CT 4.1.4.4.1.2's design alternatives).
        Thin wrapper over ``align_api.get_vertical_layouts`` (plural) so
        the multi-vertical selector (spec 2.1) has a single list to
        populate from, unlike ``get_vertical_layout`` (singular) which only
        ever finds the first/default one.
        """
        import ifcopenshell.api.alignment as align_api

        return align_api.get_vertical_layouts(alignment)

    @classmethod
    def add_alternative_vertical(cls, alignment: "ifcopenshell.entity_instance") -> "ifcopenshell.entity_instance":
        """Add a second (or subsequent) vertical layout as a DESIGN
        ALTERNATIVE (spec 2.1) -- a distinct action from the first add: an
        existing vertical is never silently replaced. Delegates the actual
        CT 4.1.4.4.1.1 -> 4.1.4.4.1.2 migration (moving any vertical
        currently nested directly on ``alignment`` onto its own new child
        alignment, then nesting the NEW vertical onto another new child) to
        ``align_api.add_vertical_layout`` -- see its docstring for the exact
        mechanics.

        After the API call, gives every newly-aggregated child alignment a
        full Blender object hierarchy (mirrors how CSV multi-vertical import
        already does this via ``create_hierarchy_for_alignment`` per child),
        and re-parents any layout object that pre-existed under the OLD
        root (the migrated first vertical keeps its entity id and Blender
        linkage -- only its IFC nest target changed) onto its new child's
        object, so the outliner reflects the new structure.

        Args:
            alignment: The (parent) IfcAlignment entity. Must already have a
                horizontal layout AND at least one vertical layout --
                enforced by ``core.alignment.add_alternative_vertical``, not
                here.

        Returns:
            The newly created IfcAlignmentVertical entity (including its
            mandatory zero-length terminator segment).
        """
        import ifcopenshell.api.alignment as align_api

        ifc_file = tool.Ifc.get()
        before_children = set(cls.get_child_alignments(alignment))

        vertical_layout = align_api.add_vertical_layout(ifc_file, alignment)

        after_children = cls.get_child_alignments(alignment)
        new_children = [child for child in after_children if child not in before_children]

        for child in new_children:
            child_obj = cls.create_hierarchy_for_alignment(child)
            if child_obj is None:
                continue
            child_vertical = align_api.get_vertical_layout(child)
            if child_vertical is None:
                continue
            layout_obj = tool.Ifc.get_object(child_vertical)
            if layout_obj is None or layout_obj.parent is child_obj:
                continue
            layout_obj.parent = child_obj
            if child_obj.users_collection:
                target_collection = child_obj.users_collection[0]
                for collection in list(layout_obj.users_collection):
                    if collection != target_collection:
                        collection.objects.unlink(layout_obj)
                if layout_obj.name not in target_collection.objects:
                    target_collection.objects.link(layout_obj)

        return vertical_layout

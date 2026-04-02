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

        K = L / |Δg|

        A higher K-value means a more gradual curve. K is used in AASHTO
        sight-distance calculations for crest and sag curves.

        Args:
            curve_length: Vertical curve length (L)
            grade_change: Algebraic grade change Δg = g2 - g1 (decimal)

        Returns:
            K-value. Returns 0.0 if grade_change is effectively zero (flat
            curve) or if curve_length is zero.
        """
        if abs(grade_change) < 1e-10 or curve_length <= 0:
            return 0.0
        return curve_length / abs(grade_change)

    @classmethod
    def calculate_vertical_curve_length_from_k(cls, k_value: float, grade_change: float) -> float:
        """Calculate vertical curve length from K-value and grade change.

        L = K * |Δg|

        Args:
            k_value: Design K-value
            grade_change: Algebraic grade change Δg = g2 - g1 (decimal)

        Returns:
            Vertical curve length
        """
        return k_value * abs(grade_change)

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
                stations=[], elevations=[], grades=[], k_values=[],
                bvc_stations=[], evc_stations=[], total_length=0.0,
            )

        stations = [float(pvi[0]) for pvi in pvis]
        elevations = [float(pvi[1]) for pvi in pvis]

        if num_pvis == 1:
            return PVIGeometryResult(
                stations=stations, elevations=elevations, grades=[], k_values=[],
                bvc_stations=[], evc_stations=[], total_length=0.0,
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
            curve_length = interior_curve_lengths[interior_index] if interior_index < len(interior_curve_lengths) else 0.0
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
    def back_calculate_pvis_from_vertical(cls, alignment: "ifcopenshell.entity_instance") -> List[dict]:
        """Reverse-engineer PVI positions from IFC vertical alignment segments.

        Reconstructs the original PVI table from CONSTANTGRADIENT and
        PARABOLICARC IfcAlignmentVerticalSegment entities. The PVI for a
        PARABOLICARC is at the tangent intersection: station = BVC + L/2,
        elevation = BVC_elevation + g1 * (L/2).

        Args:
            alignment: The IfcAlignment entity

        Returns:
            List of dicts, each containing:
            - "station": float — distance along horizontal alignment
            - "elevation": float — elevation at PVI
            - "curve_length": float — vertical curve length (0 for endpoints)

        Raises:
            ValueError: If alignment has no vertical layout or no real segments
        """
        import ifcopenshell.api.alignment as align_api

        v_layout = align_api.get_vertical_layout(alignment)
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
        pvis.append({
            "station": float(first_dp.StartDistAlong),
            "elevation": float(first_dp.StartHeight),
            "curve_length": 0.0,
        })

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
            pvis.append({
                "station": pvi_station,
                "elevation": pvi_elevation,
                "curve_length": horizontal_length,
            })

        # Last PVI: end of last real segment
        last_dp = real_segments[-1].DesignParameters
        last_station = float(last_dp.StartDistAlong) + float(last_dp.HorizontalLength)
        # Elevation at end = StartHeight + (g1 + g2) / 2 * L (works for both types)
        last_elevation = float(last_dp.StartHeight) + (
            (float(last_dp.StartGradient) + float(last_dp.EndGradient)) / 2.0 * float(last_dp.HorizontalLength)
        )
        if abs(last_station - pvis[-1]["station"]) > 1e-6:
            pvis.append({
                "station": last_station,
                "elevation": last_elevation,
                "curve_length": 0.0,
            })

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
            alignment_obj.users_collection[0]
            if alignment_obj.users_collection
            else bpy.context.scene.collection
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
            obj for obj in bpy.data.objects
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
    def collect_pvis_from_empties_vertical(
        cls, alignment_id: int
    ) -> Tuple[List[Tuple[float, float]], List[float]]:
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
            station = empty.location.x   # Profile space: X = station
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
        h_layout = ifc_file.createIfcAlignmentHorizontal(
            GlobalId=ifcopenshell.guid.new()
        )
        ifcopenshell.api.nest.assign_object(
            ifc_file, related_objects=[h_layout], relating_object=alignment
        )

        # Create geometric representation (curves) for the alignment
        align_api._create_geometric_representation(ifc_file, alignment)

        # Add stationing referent (required by segment creation API)
        start_station = 0.0
        station_name = ifcopenshell.util.alignment.station_as_string(ifc_file, start_station)
        align_api.add_stationing_referent(
            ifc_file, alignment, 0.0, start_station, station_name, alignment
        )

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
        product = ifc_file.createIfcProductDefinitionShape(
            Representations=(axis_representation,)
        )
        zero_length_segment = h_layout.IsNestedBy[0].RelatedObjects[-1]
        zero_length_segment.ObjectPlacement = alignment.ObjectPlacement
        zero_length_segment.Representation = product

        return h_layout

    @classmethod
    def clear_layout_segments(cls, layout: "ifcopenshell.entity_instance"):
        """Clear all segments from a layout, preserving the layout entity.

        Args:
            layout: The IFC layout entity (IfcAlignmentHorizontal, etc.)
        """
        import ifcopenshell.api.alignment as align_api

        ifc_file = tool.Ifc.get()
        align_api.clear_layout_segments(ifc_file, layout)

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
    def back_calculate_pis_from_alignment(cls, alignment: "ifcopenshell.entity_instance") -> List[dict]:
        """Reverse-engineer PI positions from IFC alignment segments.

        Uses ifcopenshell.api.alignment.segment_vertices() to extract
        the tangent intersection (TI) point for each segment — the TI
        IS the PI for curve segments.

        Args:
            alignment: The IfcAlignment entity

        Returns:
            List of dicts, each containing:
            - "e": float - Easting coordinate in IFC space
            - "n": float - Northing coordinate in IFC space
            - "radius": float - Curve radius (0 for endpoints/tangent PIs)
            - "pi_type": str - "ENDPOINT", "CURVE", or "TANGENT"

        Raises:
            ValueError: If alignment has no horizontal layout or segments
        """
        import ifcopenshell.api.alignment as align_api

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

        # Get vertices for all segments
        seg_vertices = [cls._get_segment_vertices_in_model_units(ifc_file, seg) for seg in real_segments]

        pis = []

        # First PI: start of first segment
        if seg_vertices[0] is not None:
            start_pt = seg_vertices[0][0]
            pis.append({"e": start_pt[0], "n": start_pt[1], "radius": 0.0, "pi_type": "ENDPOINT"})

        # Process each segment for interior PIs
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
                pis.append({"e": ti[0], "n": ti[1], "radius": radius, "pi_type": "CURVE"})
                prev_is_line = False
            else:
                # Line segment: if previous was also a line, connection = tangent PI
                if i > 0 and prev_is_line:
                    pis.append({"e": start[0], "n": start[1], "radius": 0.0, "pi_type": "TANGENT"})
                prev_is_line = True

        # Last PI: end of last segment
        if seg_vertices[-1] is not None:
            end_pt = seg_vertices[-1][1]
            if pis:
                last = pis[-1]
                dist = ((end_pt[0] - last["e"]) ** 2 + (end_pt[1] - last["n"]) ** 2) ** 0.5
                if dist > 0.001:
                    pis.append({"e": end_pt[0], "n": end_pt[1], "radius": 0.0, "pi_type": "ENDPOINT"})
            else:
                pis.append({"e": end_pt[0], "n": end_pt[1], "radius": 0.0, "pi_type": "ENDPOINT"})

        return pis

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

        alignment_id = alignment.id()
        empties = []

        for i, pi in enumerate(pis):
            # Convert IFC coordinates to Blender coordinates
            blender_pos = tool.Georeference.enh2xyz((float(pi["e"]), float(pi["n"]), 0.0))

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
    def collect_pis_from_empties(cls, alignment_id: int) -> Tuple[List[Tuple[float, float]], List[float]]:
        """Gather current PI positions from EMPTY objects.

        Reads the current positions of PI empties and converts them
        back to IFC coordinates for regenerating the alignment.

        Args:
            alignment_id: The IFC ID of the alignment being edited

        Returns:
            Tuple of:
            - hpoints: List of (x, y) tuples in IFC coordinates
            - radii: List of radii for interior PIs only (not first/last)
        """
        empties = cls.get_pi_edit_empties(alignment_id)

        if len(empties) < 2:
            return ([], [])

        hpoints = []
        radii = []

        for i, empty in enumerate(empties):
            # Convert Blender position to IFC coordinates
            ifc_pos = tool.Georeference.xyz2enh(tuple(empty.matrix_world.translation))
            hpoints.append((ifc_pos[0], ifc_pos[1]))

            # Collect radii for interior PIs only (not first or last)
            if 0 < i < len(empties) - 1:
                radius = empty.get("civil_pi_radius", 0.0)
                radii.append(radius)

        return (hpoints, radii)

    @classmethod
    def get_active_alignment(cls) -> ifcopenshell.entity_instance | None:
        if obj := tool.Blender.get_active_object():
            if (element := tool.Ifc.get_entity(obj)) and element.is_a("IfcAlignment"):
                return element

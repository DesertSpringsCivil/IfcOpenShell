# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2020, 2021 Dion Moult <dion@thinkmoult.com>, 2022 Yassine Oualid <yassine@sigmadimensions.com>, 2026 Michael Yoder <myoder@desertspringscivil.com>
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

# pyright: reportUnnecessaryTypeIgnoreComment=error


import bpy
import math
import time
import bonsai.core.alignment as core
import bonsai.tool as tool
import ifcopenshell.api.alignment
import ifcopenshell.api.spatial
import ifcopenshell.util.geolocation
import ifcopenshell.util.unit
from bpy_extras.io_utils import ImportHelper
from bpy_extras.view3d_utils import region_2d_to_origin_3d, region_2d_to_vector_3d, location_3d_to_region_2d
from bpy.types import Operator
from bpy.props import StringProperty, FloatProperty, IntProperty, EnumProperty, BoolProperty
from . import decorator as alignment_decorator
from bonsai.bim.module.model.polyline import PolylineOperator
from bonsai.bim.module.model.decorator import PolylineDecorator
from bonsai.bim.ifc import IfcStore


class ImportAlignmentCSV(bpy.types.Operator, tool.Ifc.Operator, ImportHelper):
    bl_idname = "bim.import_alignment_csv"
    bl_label = "Import Alignment CSV"
    bl_description = (
        "Import alignment(s) from a .csv file — one horizontal row (X,Y,R "
        "triples) plus any number of vertical rows (D,Z,L triples)"
    )
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".csv"
    filter_glob: bpy.props.StringProperty(default="*.csv", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return poll_ifc4x3(cls, context)

    def _execute(self, context):
        start = time.time()
        props = context.scene.CivilAlignmentProperties

        alignment = core.import_alignment_csv(tool.Ifc, tool.Alignment, filepath=self.filepath)

        props.active_alignment_name = alignment.Name or "Imported Alignment"
        props.active_alignment_id = alignment.id()
        refresh_referent_list(props, alignment)

        self.report({"INFO"}, "Imported in %s seconds" % (time.time() - start))


def poll_ifc4x3(cls, context):
    """Standard poll method for IFC4X3 requirement"""
    ifc = tool.Ifc.get()
    if ifc is None:
        cls.poll_message_set("No IFC file loaded. Open an IFC file via Bonsai.")
        return False
    if ifc.schema != "IFC4X3":
        cls.poll_message_set(f"Schema is {ifc.schema}. Alignments require IFC4X3.")
        return False
    return True


def _resolve_active_alignment(context):
    """Return the IfcAlignment for ``props.active_alignment_id``, or None.

    Operators that act on an existing alignment store it as
    ``active_alignment_id`` (set on create/visualize) and their ``_execute``
    uses that id — so their ``poll`` must resolve the alignment the same way,
    NOT via the active viewport object (which is typically a segment curve
    after PI/curve editing).
    """
    props = context.scene.CivilAlignmentProperties
    if props.active_alignment_id == 0:
        return None
    ifc_file = tool.Ifc.get()
    if ifc_file is None:
        return None
    try:
        alignment = ifc_file.by_id(props.active_alignment_id)
    except RuntimeError:
        return None
    return alignment if alignment.is_a("IfcAlignment") else None


def sync_pis_from_ifc(props):
    """Sync PI Editor data from IFC alignment.

    This is called on undo/redo to ensure the PI Editor reflects the current
    IFC state. It extracts PI data from the alignment's horizontal segments.

    If no active alignment exists or it's invalid, clears the PI Editor.

    Returns:
        bool: True if sync was successful, False if alignment was cleared.
    """
    ifc = tool.Ifc.get()
    if ifc is None:
        # No IFC file - clear everything
        props.pis.clear()
        props.active_pi_index = 0
        rebuild_display_rows(props)
        return False

    alignment = tool.Alignment.get_active_alignment()
    if not alignment:
        # Alignment no longer exists - clear everything
        props.pis.clear()
        props.active_pi_index = 0
        rebuild_display_rows(props)
        return False

    # Alignment exists - extract PI data from IFC segments
    h_layout = ifcopenshell.api.alignment.get_horizontal_layout(alignment)
    if not h_layout:
        # No horizontal layout - rebuild display with current props
        rebuild_display_rows(props)
        return True

    segments = ifcopenshell.api.alignment.get_layout_segments(h_layout)
    if not segments:
        # No segments - rebuild display with current props
        rebuild_display_rows(props)
        return True

    # Extract PIs from segment data
    # This reconstructs approximate PIs from the IFC segment geometry
    extracted_pis = tool.Alignment.extract_pis_from_segments(segments)

    if not extracted_pis:
        # Couldn't extract - keep current props.pis
        rebuild_display_rows(props)
        return True

    # Update props.pis with extracted data
    props.pis.clear()
    # pi.radius is a Blender LENGTH property (metres); the extracted radius is in
    # project units, so scale it so the table displays the correct value.
    unit_scale = ifcopenshell.util.unit.calculate_unit_scale(tool.Ifc.get())
    for pi_data in extracted_pis:
        pi = props.pis.add()
        pi.e = str(pi_data["e"])
        pi.n = str(pi_data["n"])
        pi.pi_type = pi_data["pi_type"]
        pi.radius = pi_data.get("radius", 0.0) * unit_scale

    props.active_pi_index = 0

    # Recalculate geometry and rebuild display
    recalculate_pi_geometry(props)
    return True


def refresh_referent_list(props, alignment):
    """Sync ``props.referents`` (CIVIL_UL_referents' backing collection)
    from IFC (spec 4.2).

    Called after any operator that adds or removes a referent, on
    alignment activation (create/import/visualize — mirrors
    ``sync_pis_from_ifc``'s role for the PI table, one level up: the
    referent list is read-only, so there is no equivalent "extract from
    segments" fallback path), and from the manual refresh button
    (``civil.refresh_referent_list``).

    Args:
        props: CivilAlignmentProperties
        alignment: The IfcAlignment entity, or None to just clear the list
            (e.g. the active alignment was deleted).
    """
    props.referents.clear()
    props.active_referent_index = 0
    if alignment is None:
        return
    for entry in tool.Alignment.get_referents(alignment):
        item = props.referents.add()
        item.referent_id = entry["id"]
        item.referent_name = entry["name"] or ""
        item.predefined_type = entry["predefined_type"] or ""
        item.has_station = entry["station"] is not None
        item.station = entry["station"] if entry["station"] is not None else 0.0
        item.is_equation = entry["is_equation"]
        item.incoming_station = entry["incoming_station"] if entry["incoming_station"] is not None else 0.0


def on_radius_changed(pi, context):
    """Callback when PI radius is changed. Triggers geometry recalculation.

    This is called from the AlignmentPI.radius property's update callback.
    When a radius is entered on a Mid point, this triggers:
    1. Spec 1.5: if spiral_mode is A_VALUE, re-derive spiral_in_length /
       spiral_out_length from the (unchanged) A-values and the NEW radius --
       "radius changes re-derive length from A when mode is A_VALUE".
    2. Recalculation of PI geometry (lengths, stations)
    3. Rebuild of display_rows (Mid point becomes Curve segment)
    4. If an active alignment exists, regeneration of IFC entities
    """
    if pi.spiral_mode == "A_VALUE":
        pi.spiral_in_length = tool.Alignment.spiral_length_from_a_value(pi.spiral_a_in, pi.radius)
        pi.spiral_out_length = tool.Alignment.spiral_length_from_a_value(pi.spiral_a_out, pi.radius)

    props = context.scene.CivilAlignmentProperties
    recalculate_pi_geometry(props)

    # If there's an active alignment, trigger IFC regeneration
    # This is handled by recalculate_pi_geometry when active_alignment_id is set


def on_spiral_length_changed(pi, context):
    """Callback when spiral_in_length/spiral_out_length changes (spec 1.5).

    LENGTH mode is authoritative for these fields, so this only recalculates
    PI geometry / rebuilds the display table -- it never writes back to
    spiral_a_in/spiral_a_out (rebuild_display_rows derives the A-value shown
    on Spiral rows on the fly, from length + radius).
    """
    props = context.scene.CivilAlignmentProperties
    recalculate_pi_geometry(props)


def on_spiral_a_value_changed(pi, context):
    """Callback when spiral_a_in/spiral_a_out changes (spec 1.5 A-value mode).

    Only re-derives the matching spiral length (using the current radius)
    when spiral_mode is A_VALUE -- "editing A updates length using current
    radius". In LENGTH mode the A-value fields are inert until spiral_mode
    switches back.
    """
    if pi.spiral_mode == "A_VALUE":
        pi.spiral_in_length = tool.Alignment.spiral_length_from_a_value(pi.spiral_a_in, pi.radius)
        pi.spiral_out_length = tool.Alignment.spiral_length_from_a_value(pi.spiral_a_out, pi.radius)

    props = context.scene.CivilAlignmentProperties
    recalculate_pi_geometry(props)


def on_spiral_mode_changed(pi, context):
    """Callback when spiral_mode toggles between LENGTH and A_VALUE.

    Reconciles the pair once, in the direction the newly-active mode
    requires, so whichever field the user edits next is already coherent
    with the other:
    - switching TO A_VALUE derives spiral_a_in/spiral_a_out from the
      current (authoritative) lengths and radius.
    - switching TO LENGTH leaves the lengths untouched -- they were already
      authoritative and are unaffected by the mode switch.
    """
    if pi.spiral_mode == "A_VALUE":
        pi.spiral_a_in = tool.Alignment.a_value_from_spiral_length(pi.spiral_in_length, pi.radius)
        pi.spiral_a_out = tool.Alignment.a_value_from_spiral_length(pi.spiral_out_length, pi.radius)

    props = context.scene.CivilAlignmentProperties
    recalculate_pi_geometry(props)


def recalculate_pi_geometry(props):
    """Recalculate lengths and stations for all PIs using tool layer."""
    pis = props.pis
    if len(pis) < 2:
        rebuild_display_rows(props)
        return

    # Extract PI coordinates for calculation
    pi_coords = [(float(pi.e), float(pi.n)) for pi in pis]

    # Use tool layer for calculation (math belongs in tool, not core)
    result = tool.Alignment.calculate_pi_geometry(pi_coords, props.start_station)

    # Update Blender properties with results
    tool.Alignment.update_pi_properties(props, result)

    # Rebuild the display rows for the interleaved table view
    rebuild_display_rows(props)


def rebuild_display_rows(props):
    """Rebuild the display_rows collection from the pis collection.

    Creates an interleaved view of points and segments in Civil 3D style:
        End point (POB)
          Tangent segment 1
        Mid point (or Curve segment if radius > 0)
          Tangent segment 2
        End point (POE)

    When a Mid point has a curve (radius > 0), it becomes a Curve segment row
    instead of a point row, showing PI coordinates + arc length + radius.

    Spec 1.5 (spirals): when the PI also has entry/exit spiral lengths, the
    single Curve row is replaced by up to three rows in curve order --
    "Spiral" (TS-Spiral, length = Lin, radius column = A-value), "Curve"
    (the circular portion, omitted entirely for a pure spiral-spiral
    transition where the spirals consume the full deflection), "Spiral"
    (CS-Spiral, length = Lout, radius column = A-value).

    Spec 1.6 (compound/reverse curves): when a PI's ``join_next`` is set and
    the next PI also has a curve, the intermediate "Tan" row between them is
    replaced by a single junction row -- display_type "PCC" or "PRC"
    (``tool.Alignment.junction_type``, a same/opposite deflection-sign
    comparison) -- since the two curves are directly tangent with no
    tangent run between them.

    Post-commit, rows that start at a named key point (TS/SC/CS/ST/PC/PT/
    PCC) look up their station from ``props.referents`` (POSITION referents,
    populated by ``refresh_referent_list`` from
    ``tool.Alignment.get_referents``), matched in station order to the same
    order these rows are generated in. Pre-commit -- or if a match can't be
    found -- a row simply shows no station (``has_station`` stays False).
    """
    props.display_rows.clear()

    pis = props.pis
    if len(pis) == 0:
        return

    segment_num = 0
    i = 0

    # Pre-compute coordinate tuples for tool method calls
    pi_coords = [(float(pi.e), float(pi.n)) for pi in pis]

    # POSITION (key-point) referents, station-ascending -- the same order
    # commit_layout_change's update_key_point_referents creates them in, so
    # consuming them in lockstep with the rows generated below lines them up.
    referent_queue = [r for r in props.referents if r.predefined_type == "POSITION"]

    def pop_station(label):
        if not referent_queue:
            return None
        candidate = referent_queue[0]
        if candidate.referent_name.rstrip().endswith(f"({label})"):
            referent_queue.pop(0)
            return candidate.station
        return None

    def apply_station(row, label):
        station = pop_station(label)
        if station is not None:
            row.station = station
            row.has_station = True

    while i < len(pis):
        pi = pis[i]
        is_interior = i > 0 and i < len(pis) - 1
        has_curve = is_interior and pi.radius > 0
        has_spiral = has_curve and (pi.spiral_in_length > 0 or pi.spiral_out_length > 0)
        geom = None
        joined_to_next = False

        if has_curve:
            geom = tool.Alignment.spiral_curve_geometry_at_pi(
                pi_coords[i - 1], pi_coords[i], pi_coords[i + 1], pi.radius, pi.spiral_in_length, pi.spiral_out_length
            )
            next_is_interior = (i + 1 > 0) and (i + 1 < len(pis) - 1)
            next_pi_has_curve = next_is_interior and pis[i + 1].radius > 0
            joined_to_next = bool(pi.join_next) and next_pi_has_curve and i + 2 < len(pis)

            if has_spiral:
                # TS-Spiral: only when there's an entry spiral.
                if pi.spiral_in_length > 0:
                    segment_num += 1
                    spiral_row = props.display_rows.add()
                    spiral_row.row_type = "SEGMENT"
                    spiral_row.segment_number = segment_num
                    spiral_row.pi_index = i
                    spiral_row.display_type = "Spiral"
                    spiral_row.length = pi.spiral_in_length
                    spiral_row.radius = tool.Alignment.a_value_from_spiral_length(pi.spiral_in_length, pi.radius)
                    apply_station(spiral_row, "T.S.")

                # Curve: the circular portion, omitted for a pure
                # spiral-spiral transition (the spirals consume Δ entirely).
                if geom["arc_length"] > 1e-6:
                    segment_num += 1
                    curve_row = props.display_rows.add()
                    curve_row.row_type = "SEGMENT"
                    curve_row.segment_number = segment_num
                    curve_row.pi_index = i
                    curve_row.display_type = "Curve"
                    curve_row.e = pi.e
                    curve_row.n = pi.n
                    curve_row.radius = pi.radius
                    curve_row.arc_length = geom["arc_length"]
                    apply_station(curve_row, "S.C." if pi.spiral_in_length > 0 else "P.C.")

                # CS-Spiral: only when there's an exit spiral.
                if pi.spiral_out_length > 0:
                    segment_num += 1
                    spiral_row = props.display_rows.add()
                    spiral_row.row_type = "SEGMENT"
                    spiral_row.segment_number = segment_num
                    spiral_row.pi_index = i
                    spiral_row.display_type = "Spiral"
                    spiral_row.length = pi.spiral_out_length
                    spiral_row.radius = tool.Alignment.a_value_from_spiral_length(pi.spiral_out_length, pi.radius)
                    no_arc = geom["arc_length"] <= 1e-6
                    apply_station(spiral_row, "S.S." if (no_arc and pi.spiral_in_length > 0) else "C.S.")
            else:
                # Plain circular curve, no spirals — unchanged from before.
                segment_num += 1
                curve_row = props.display_rows.add()
                curve_row.row_type = "SEGMENT"
                curve_row.segment_number = segment_num
                curve_row.pi_index = i
                curve_row.display_type = "Curve"
                curve_row.e = pi.e
                curve_row.n = pi.n
                curve_row.radius = pi.radius
                curve_row.arc_length = geom["arc_length"]
                apply_station(curve_row, "P.C.")
        else:
            # Regular point row (End or Mid without curve)
            point_row = props.display_rows.add()
            point_row.row_type = "POINT"
            point_row.pi_index = i

            if pi.pi_type == "ENDPOINT":
                point_row.display_type = "End"
            else:
                point_row.display_type = "Mid"

            point_row.e = pi.e
            point_row.n = pi.n

        # Junction row (spec 1.6): replaces the intermediate Tan row when
        # this PI's curve is joined directly to the next PI's curve.
        if joined_to_next:
            segment_num += 1
            junction_row = props.display_rows.add()
            junction_row.row_type = "SEGMENT"
            junction_row.segment_number = segment_num
            junction_row.pi_index = i
            junction_row.display_type = tool.Alignment.junction_type(
                pi_coords[i - 1], pi_coords[i], pi_coords[i + 1], pi_coords[i + 2]
            )
            apply_station(junction_row, "P.C.C.")
            i += 1
            continue

        # Add tangent segment row after this point/curve (except after last PI)
        if i < len(pis) - 1:
            segment_num += 1
            seg_row = props.display_rows.add()
            seg_row.row_type = "SEGMENT"
            seg_row.segment_number = segment_num
            seg_row.pi_index = i
            seg_row.display_type = "Tan"

            # Compute tangent lengths at each end to subtract from full distance
            start_t = 0.0
            end_t = 0.0
            if has_curve:
                start_t = geom["tangent_out"]
                apply_station(seg_row, "S.T." if pi.spiral_out_length > 0 else "P.T.")

            next_pi = pis[i + 1]
            next_is_interior = (i + 1 > 0) and (i + 1 < len(pis) - 1)
            next_has_curve = next_is_interior and next_pi.radius > 0
            if next_has_curve:
                next_geom = tool.Alignment.spiral_curve_geometry_at_pi(
                    pi_coords[i],
                    pi_coords[i + 1],
                    pi_coords[i + 2],
                    next_pi.radius,
                    next_pi.spiral_in_length,
                    next_pi.spiral_out_length,
                )
                end_t = next_geom["tangent_in"]

            seg_row.length = tool.Alignment.tangent_segment_length(pi_coords[i], pi_coords[i + 1], start_t, end_t)

        i += 1


# =============================================================================
# Vertical PVI Helpers
# =============================================================================


def on_curve_length_changed(pvi, context):
    """Callback when PVI curve_length changes. Triggers vertical geometry recalculation."""
    props = context.scene.CivilAlignmentProperties
    recalculate_pvi_geometry(props)


def recalculate_pvi_geometry(props):
    """Recalculate vertical geometry and rebuild display rows."""
    pvis = props.vertical_pvis
    if len(pvis) < 2:
        rebuild_vertical_display_rows(props)
        return

    rebuild_vertical_display_rows(props)


def rebuild_vertical_display_rows(props):
    """Rebuild vertical_display_rows from vertical_pvis collection.

    Creates an interleaved view of PVI points and grade segments:
        End (BOM) - station, elevation
          Grade 1 - slope %, tangent length
        PVI 1 - station, elevation [, curve_length, K]
          Grade 2 - slope %, tangent length
        ...
        End (EOM) - station, elevation
    """
    props.vertical_display_rows.clear()
    pvis = props.vertical_pvis
    if len(pvis) == 0:
        return

    # Compute geometry if we have enough points
    result = None
    if len(pvis) >= 2:
        vpoints = [(pvi.station, pvi.elevation) for pvi in pvis]
        curve_lengths = [pvis[i].curve_length for i in range(1, len(pvis) - 1)] or None
        try:
            result = tool.Alignment.calculate_pvi_geometry(vpoints, curve_lengths)
        except Exception:
            pass

    for i, pvi in enumerate(pvis):
        is_interior = 0 < i < len(pvis) - 1
        has_curve = is_interior and pvi.curve_length > 0

        # Add PVI point row
        row = props.vertical_display_rows.add()
        row.row_type = "POINT"
        row.pvi_index = i
        row.station = pvi.station
        row.elevation = pvi.elevation
        row.display_type = "End" if pvi.pvi_type == "ENDPOINT" else "PVI"
        if has_curve and result:
            row.curve_length = pvi.curve_length
            j = i - 1  # interior PVI index (0-based)
            if j < len(result.k_values):
                row.k_value = result.k_values[j]
                # Advisory AASHTO K check (spec 2.4) — flagged, never blocked.
                if props.design_speed > 0 and j + 1 < len(result.grades):
                    is_crest = result.grades[j] > result.grades[j + 1]
                    required = tool.Alignment.required_k_for_design_speed(props.design_speed, is_crest)
                    if required is not None and row.k_value < required:
                        row.k_deficient = True
                        row.k_required = required

        # Add grade segment after each PVI except the last
        if i < len(pvis) - 1:
            seg_row = props.vertical_display_rows.add()
            seg_row.row_type = "SEGMENT"
            seg_row.pvi_index = i
            seg_row.display_type = "Grade"
            if result and i < len(result.grades):
                seg_row.grade_pct = result.grades[i] * 100.0
            # Tangent length = horizontal distance minus half curve lengths at each end
            next_pvi = pvis[i + 1]
            horiz_dist = next_pvi.station - pvi.station
            half_curr = (pvi.curve_length / 2.0) if has_curve else 0.0
            next_is_interior = 0 < (i + 1) < len(pvis) - 1
            next_has_curve = next_is_interior and next_pvi.curve_length > 0
            half_next = (next_pvi.curve_length / 2.0) if next_has_curve else 0.0
            seg_row.length = max(0.0, horiz_dist - half_curr - half_next)


# =============================================================================
# Cant Helpers (spec Section 3)
# =============================================================================


def _cant_points_as_dicts(props):
    return [
        {
            "station": p.station,
            "cant_left": p.cant_left,
            "cant_right": p.cant_right,
            "transition_type": p.transition_type,
            "design_speed": p.design_speed,
        }
        for p in props.cant_points
    ]


def _cant_limits_from_props(props):
    return {
        "max_applied_cant": props.cant_limit_max_applied,
        "max_deficiency": props.cant_limit_max_deficiency,
        "max_excess": props.cant_limit_max_excess,
        "max_cant_gradient": props.cant_limit_max_gradient,
        "max_twist": props.cant_limit_max_twist,
    }


def rebuild_cant_display_rows(props):
    """Rebuild cant_display_rows from the cant_points collection (spec 3.2).

    Civil 3D-style interleaving: each POINT row (editable station/cant L-R/
    transition) is followed by ONE COMPUTED row for the segment LEAVING that
    point (E_eq, deficiency, excess, gradient, twist, and any violated
    limits) — mirroring rebuild_vertical_display_rows's POINT/SEGMENT
    interleaving, except cant always pairs exactly one COMPUTED row per
    POINT row (never more), and the last point has no COMPUTED row (no
    outgoing segment).

    This only recomputes the CHECKS — it never writes to IFC (spec 3.5): the
    explicit Recalculate button (civil.recalculate_cant) is what regenerates
    the IFC segments, matching the PI/PVI table idiom.
    """
    props.cant_display_rows.clear()

    points = props.cant_points
    if len(points) == 0:
        return

    alignment = tool.Alignment.get_active_alignment()
    point_dicts = _cant_points_as_dicts(props)
    limits = _cant_limits_from_props(props)
    gauge = props.track_gauge
    design_speed = props.design_speed

    for i in range(len(points)):
        point_row = props.cant_display_rows.add()
        point_row.row_type = "POINT"
        point_row.point_index = i

        if i < len(points) - 1 and alignment is not None:
            checks = tool.Alignment.compute_cant_checks(point_dicts, i, alignment, gauge, limits, design_speed)
            computed_row = props.cant_display_rows.add()
            computed_row.row_type = "COMPUTED"
            computed_row.point_index = i
            computed_row.radius = checks["radius"]
            computed_row.applied_left = checks["applied_left"]
            computed_row.applied_right = checks["applied_right"]
            computed_row.applied = checks["applied"]
            computed_row.equilibrium = checks["equilibrium"]
            computed_row.deficiency = checks["deficiency"]
            computed_row.excess = checks["excess"]
            computed_row.gradient = checks["gradient"]
            computed_row.twist_per_length = checks["twist_per_length"]
            computed_row.twist_per_time = checks["twist_per_time"]
            computed_row.violations = ", ".join(checks["violations"])


# =============================================================================
# PI Management Operators
# =============================================================================


class CIVIL_OT_add_pi(Operator):
    """Add a new PI point to the list"""

    bl_idname = "civil.add_pi"
    bl_label = "Add PI"
    bl_description = "Add a new PI (Point of Intersection) to the alignment"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return poll_ifc4x3(cls, context)

    def execute(self, context):
        props = context.scene.CivilAlignmentProperties

        # Add new PI
        pi = props.pis.add()

        # Set default position based on existing PIs
        if len(props.pis) == 1:
            # First PI - start at origin
            pi.e = str(0.0)
            pi.n = str(0.0)
            pi.pi_type = "ENDPOINT"
        elif len(props.pis) == 2:
            # Second PI - offset from first
            prev = props.pis[0]
            pi.e = str(float(prev.e) + 100.0)
            pi.n = prev.n
            pi.pi_type = "ENDPOINT"
        else:
            # Additional PIs - extrapolate from last two
            prev = props.pis[-2]
            prev_prev = props.pis[-3] if len(props.pis) > 2 else prev
            de = float(prev.e) - float(prev_prev.e) if len(props.pis) > 2 else 100.0
            dn = float(prev.n) - float(prev_prev.n) if len(props.pis) > 2 else 0.0
            pi.e = str(float(prev.e) + de)
            pi.n = str(float(prev.n) + dn)
            pi.pi_type = "TANGENT"

            # Previous endpoint becomes tangent or curve
            props.pis[-2].pi_type = "TANGENT"

        # Make new PI active
        props.active_pi_index = len(props.pis) - 1

        # Recalculate geometry
        recalculate_pi_geometry(props)

        return {"FINISHED"}


class CIVIL_OT_remove_pi(Operator):
    """Remove the selected PI point"""

    bl_idname = "civil.remove_pi"
    bl_label = "Remove PI"
    bl_description = "Remove the selected PI from the alignment"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if not poll_ifc4x3(cls, context):
            return False
        props = context.scene.CivilAlignmentProperties
        if len(props.pis) == 0:
            cls.poll_message_set("No PIs to remove")
            return False
        # Check if a POINT row is selected (can't remove from SEGMENT row selection)
        if props.display_rows:
            idx = props.active_display_row_index
            if 0 <= idx < len(props.display_rows):
                if props.display_rows[idx].row_type != "POINT":
                    cls.poll_message_set("Select a point row to remove")
                    return False
        return True

    def execute(self, context):
        props = context.scene.CivilAlignmentProperties

        # Get the PI index from the selected display row
        pi_index = -1
        if props.display_rows:
            idx = props.active_display_row_index
            if 0 <= idx < len(props.display_rows):
                row = props.display_rows[idx]
                if row.row_type == "POINT":
                    pi_index = row.pi_index

        # Fallback to active_pi_index if display_rows isn't being used
        if pi_index < 0:
            pi_index = props.active_pi_index

        if 0 <= pi_index < len(props.pis):
            props.pis.remove(pi_index)
            props.active_pi_index = min(pi_index, len(props.pis) - 1)

            # Recalculate geometry (also rebuilds display_rows)
            recalculate_pi_geometry(props)

            # Reset display row index to first row if needed
            if len(props.display_rows) > 0:
                props.active_display_row_index = min(props.active_display_row_index, len(props.display_rows) - 1)
            else:
                props.active_display_row_index = 0

        return {"FINISHED"}


def _resolve_selected_interior_pi_index(props):
    """Resolve which interior PI the selected PI-table row refers to (spec
    1.5/1.6). Mirrors ``CIVIL_OT_remove_pi``'s row-based resolution, but
    accepts POINT rows and SEGMENT rows alike -- a Curve/Spiral/PCC/PRC
    row's ``pi_index`` already points at its owning PI -- since the spiral
    and join operators act on curve rows, not just point rows. Falls back
    to ``active_pi_index`` when ``display_rows`` isn't populated.

    Returns the PI index, or None if it doesn't resolve to an INTERIOR PI
    (index 0 and the last index are endpoints, which can never hold a curve).
    """
    pi_index = -1
    if props.display_rows:
        idx = props.active_display_row_index
        if 0 <= idx < len(props.display_rows):
            pi_index = props.display_rows[idx].pi_index
    if pi_index < 0:
        pi_index = props.active_pi_index
    if 0 < pi_index < len(props.pis) - 1:
        return pi_index
    return None


class CIVIL_OT_set_pi_spiral(Operator):
    """Set entry/exit spiral transition lengths (or A-values) at a PI (spec 1.5)

    One operation covers both spiral-curve-spiral (radius > 0 with either
    length > 0) and spiral-spiral (the solver consumes the full deflection
    when the spiral lengths demand it — this operator just writes the PI's
    props; the solver decides which shape results). Like the existing
    radius flow, this writes props.pis only — the actual IFC write is
    deferred to the explicit Recalculate button, matching the PI table's
    established idiom.
    """

    bl_idname = "civil.set_pi_spiral"
    bl_label = "Set PI Spiral"
    bl_description = (
        "Set (or change) entry/exit spiral transition lengths at the selected PI, in length or "
        "A-value form. Covers spiral-curve-spiral and spiral-spiral in one operation"
    )
    bl_options = {"REGISTER", "UNDO"}

    pi_index: IntProperty(default=-1)
    radius: FloatProperty(name="Radius", description="Curve radius", default=100.0, min=0.0, unit="LENGTH")
    spiral_mode: EnumProperty(
        name="Mode",
        items=[
            ("LENGTH", "Length", "Enter spiral transition lengths directly"),
            ("A_VALUE", "A-Value", "Enter the clothoid A-value; length is derived as L = A^2 / R"),
        ],
        default="LENGTH",
    )
    spiral_in_length: FloatProperty(
        name="Entry Length (Lin)",
        description="Entry spiral length ahead of the curve",
        default=0.0,
        min=0.0,
        unit="LENGTH",
    )
    spiral_out_length: FloatProperty(
        name="Exit Length (Lout)",
        description="Exit spiral length following the curve",
        default=0.0,
        min=0.0,
        unit="LENGTH",
    )
    spiral_a_in: FloatProperty(name="Entry A", description="Entry spiral A-value", default=0.0, min=0.0, unit="LENGTH")
    spiral_a_out: FloatProperty(name="Exit A", description="Exit spiral A-value", default=0.0, min=0.0, unit="LENGTH")

    @classmethod
    def poll(cls, context):
        if not poll_ifc4x3(cls, context):
            return False
        props = context.scene.CivilAlignmentProperties
        if _resolve_selected_interior_pi_index(props) is None:
            cls.poll_message_set("Select an interior PI (a Curve/Spiral row, or a Mid point row) first")
            return False
        return True

    def invoke(self, context, event):
        props = context.scene.CivilAlignmentProperties
        self.pi_index = _resolve_selected_interior_pi_index(props)
        pi = props.pis[self.pi_index]
        self.radius = pi.radius
        self.spiral_mode = pi.spiral_mode
        self.spiral_in_length = pi.spiral_in_length
        self.spiral_out_length = pi.spiral_out_length
        self.spiral_a_in = pi.spiral_a_in
        self.spiral_a_out = pi.spiral_a_out
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "radius")
        layout.prop(self, "spiral_mode", expand=True)
        if self.spiral_mode == "LENGTH":
            layout.prop(self, "spiral_in_length")
            layout.prop(self, "spiral_out_length")
        else:
            layout.prop(self, "spiral_a_in")
            layout.prop(self, "spiral_a_out")

    def execute(self, context):
        props = context.scene.CivilAlignmentProperties
        if not (0 <= self.pi_index < len(props.pis)):
            self.report({"ERROR"}, "PI not found")
            return {"CANCELLED"}

        pi = props.pis[self.pi_index]
        pi.spiral_mode = self.spiral_mode
        pi.radius = self.radius

        if self.spiral_mode == "A_VALUE":
            pi.spiral_a_in = self.spiral_a_in
            pi.spiral_a_out = self.spiral_a_out
            pi.spiral_in_length = tool.Alignment.spiral_length_from_a_value(self.spiral_a_in, self.radius)
            pi.spiral_out_length = tool.Alignment.spiral_length_from_a_value(self.spiral_a_out, self.radius)
        else:
            pi.spiral_in_length = self.spiral_in_length
            pi.spiral_out_length = self.spiral_out_length
            pi.spiral_a_in = tool.Alignment.a_value_from_spiral_length(self.spiral_in_length, self.radius)
            pi.spiral_a_out = tool.Alignment.a_value_from_spiral_length(self.spiral_out_length, self.radius)

        recalculate_pi_geometry(props)
        self.report({"INFO"}, f"Spiral set on PI {self.pi_index + 1}")
        return {"FINISHED"}


def _try_recalculate_or_revert(context, revert_fn):
    """Attempt ``_build_alignment_from_active_pis``; on a solver refusal
    (ValueError -- e.g. join_next's tangent-closure check), call
    ``revert_fn()`` to restore props.pis to its last-known-good state and
    retry ONCE so the IFC segments (already cleared by the failed attempt --
    ``layout_horizontal_alignment_by_pi_method`` clears before it re-adds,
    and Bonsai does not auto-rollback IFC mutations from a caught exception,
    see ``IfcStore.execute_ifc_operator``) end up rebuilt from that reverted
    state rather than left segment-less. The retry is expected to succeed
    (it's the same configuration that worked before the failed edit); if it
    somehow doesn't, the ORIGINAL failure is still what gets reported.

    Returns (ok, message) from the first (attempted) build -- ``message``
    is the solver's explanatory text verbatim on failure (spec 1.6:
    "refused with an explanation").
    """
    try:
        ok, message = _build_alignment_from_active_pis(context)
    except ValueError as e:
        ok, message = False, str(e)

    if ok:
        return True, message

    revert_fn()
    try:
        _build_alignment_from_active_pis(context)
    except ValueError:
        pass  # best effort -- the original failure above is still reported

    return False, message


class CIVIL_OT_join_curves(Operator, tool.Ifc.Operator):
    """Join the selected PI's curve directly to the next PI's curve (spec 1.6)

    Sets join_next, then attempts the IFC write immediately (unlike the
    other PI-table edits, which defer to the Recalculate button) so a
    solver refusal — the two curves' tangent runs cannot close onto a
    shared tangency point — can be caught and reported, and join_next
    reverted so the table matches what's actually in IFC.
    """

    bl_idname = "civil.join_curves"
    bl_label = "Join Curves"
    bl_description = (
        "Join this PI's curve directly to the NEXT PI's curve at a shared tangency point (a PCC or "
        "PRC), with no intermediate tangent run"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if not poll_ifc4x3(cls, context):
            return False
        props = context.scene.CivilAlignmentProperties
        pi_index = _resolve_selected_interior_pi_index(props)
        if pi_index is None:
            cls.poll_message_set("Select an interior PI with a curve first")
            return False
        pi = props.pis[pi_index]
        if pi.radius <= 0:
            cls.poll_message_set("Selected PI has no curve to join")
            return False
        if pi.join_next:
            cls.poll_message_set("Already joined to the next curve")
            return False
        if pi_index + 1 >= len(props.pis) - 1 or props.pis[pi_index + 1].radius <= 0:
            cls.poll_message_set("The next PI must also have a curve")
            return False
        return True

    def _execute(self, context):
        props = context.scene.CivilAlignmentProperties
        pi_index = _resolve_selected_interior_pi_index(props)
        if pi_index is None:
            self.report({"ERROR"}, "Select an interior PI with a curve first")
            return {"CANCELLED"}

        pi = props.pis[pi_index]
        pi.join_next = True

        ok, message = _try_recalculate_or_revert(context, lambda: setattr(pi, "join_next", False))
        if not ok:
            self.report({"ERROR"}, message)
            return {"CANCELLED"}

        self.report({"INFO"}, message)
        return {"FINISHED"}


class CIVIL_OT_unjoin_curves(Operator, tool.Ifc.Operator):
    """Restore the intermediate tangent between the selected PI's curve and
    the next PI's curve (spec 1.6, the inverse of CIVIL_OT_join_curves)."""

    bl_idname = "civil.unjoin_curves"
    bl_label = "Unjoin Curves"
    bl_description = "Restore the tangent run between this PI's curve and the next PI's curve"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if not poll_ifc4x3(cls, context):
            return False
        props = context.scene.CivilAlignmentProperties
        pi_index = _resolve_selected_interior_pi_index(props)
        if pi_index is None or not props.pis[pi_index].join_next:
            cls.poll_message_set("Selected PI is not joined to the next curve")
            return False
        return True

    def _execute(self, context):
        props = context.scene.CivilAlignmentProperties
        pi_index = _resolve_selected_interior_pi_index(props)
        if pi_index is None:
            self.report({"ERROR"}, "PI not found")
            return {"CANCELLED"}

        pi = props.pis[pi_index]
        pi.join_next = False

        ok, message = _try_recalculate_or_revert(context, lambda: setattr(pi, "join_next", True))
        if not ok:
            self.report({"ERROR"}, message)
            return {"CANCELLED"}

        self.report({"INFO"}, message)
        return {"FINISHED"}


class CIVIL_OT_pick_pi_from_viewport(bpy.types.Operator, PolylineOperator, tool.Ifc.Operator):
    """Add PI points by clicking in the 3D viewport using polyline tools"""

    bl_idname = "civil.pick_pi_from_viewport"
    bl_label = "Pick PI from Viewport"
    bl_description = (
        "Click in the viewport to add PI points with snapping and numeric input. RMB/Enter to finish, ESC to cancel."
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return poll_ifc4x3(cls, context)

    def __init__(self, *args, **kwargs):
        bpy.types.Operator.__init__(self, *args, **kwargs)
        PolylineOperator.__init__(self)
        # Remove instructions that don't apply to alignments
        self.instructions.pop("Close Polyline", None)
        self.instructions.pop("Offset", None)

    def invoke(self, context, event):
        return IfcStore.execute_ifc_operator(self, context, event, method="INVOKE")

    def _invoke(self, context, event):
        # Find the 3D viewport — the operator is invoked from the Properties
        # panel, so we need to override context for PolylineOperator.invoke()
        # which requires bpy.context.space_data to be SpaceView3D.
        area_3d = None
        region_3d = None
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                area_3d = area
                for region in area.regions:
                    if region.type == "WINDOW":
                        region_3d = region
                        break
                break

        if not area_3d or not region_3d:
            self.report({"ERROR"}, "No 3D Viewport found")
            return {"CANCELLED"}

        with context.temp_override(area=area_3d, region=region_3d):
            super().invoke(context, event)

        self.tool_state.use_default_container = False
        self.tool_state.plane_method = "XY"
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        return IfcStore.execute_ifc_operator(self, context, event, method="MODAL")

    def _modal(self, context, event):
        PolylineDecorator.update(event, self.tool_state, self.input_ui, self.snapping_points[0])
        tool.Blender.update_viewport()

        self.handle_lock_axis(context, event)

        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            self.handle_mouse_move(context, event)
            return {"PASS_THROUGH"}

        self.handle_instructions(context)
        self.handle_mouse_move(context, event, should_round=True)
        self.choose_axis(event)
        self.handle_snap_selection(context, event)
        self.handle_keyboard_input(context, event)
        self._handle_inserting_polyline_no_close(context, event)

        # Finish: transfer polyline points to PI table
        if (
            not self.tool_state.is_input_on
            and event.value == "RELEASE"
            and event.type in {"RET", "NUMPAD_ENTER", "RIGHTMOUSE"}
        ):
            self._transfer_polyline_to_pis(context)
            context.workspace.status_text_set(text=None)
            PolylineDecorator.uninstall()
            tool.Polyline.clear_polyline()
            # Auto-visualize: build the IFC segments as soon as picking finishes,
            # so the user no longer needs a separate "Visualize" click.
            ok, message = _build_alignment_from_active_pis(context)
            if not ok:
                self.report({"WARNING"}, message)
            tool.Blender.update_viewport()
            return {"FINISHED"}

        cancel = self.handle_cancelation(context, event)
        if cancel is not None:
            return cancel

        return {"RUNNING_MODAL"}

    def _handle_inserting_polyline_no_close(self, context, event):
        """Insert polyline points without close-polyline (C key) behavior.

        Alignments are open curves, so the C key (close polyline) is suppressed.
        All other insertion behavior is preserved: LEFTMOUSE, BACKSPACE, and
        RET/ENTER with numeric input active.
        """
        # LEFTMOUSE: insert point at current snap/cursor position
        if not self.tool_state.is_input_on and event.value == "RELEASE" and event.type == "LEFTMOUSE":
            result = tool.Polyline.insert_polyline_point(self.input_ui, self.tool_state)
            if result:
                self.report({"WARNING"}, result)
            tool.Blender.update_viewport()

        # RET/ENTER with numeric input: validate and insert
        if (
            self.tool_state.is_input_on
            and event.value == "RELEASE"
            and event.type in {"RET", "NUMPAD_ENTER", "RIGHTMOUSE"}
        ):
            is_valid = self.recalculate_inputs(context)
            if is_valid:
                result = tool.Polyline.insert_polyline_point(self.input_ui, self.tool_state)
                if result:
                    self.report({"WARNING"}, result)

            self.tool_state.mode = "Mouse"
            self.tool_state.is_input_on = False
            self.input_type = None
            self.tool_state.input_type = None
            self.number_input = []
            self.number_output = ""
            PolylineDecorator.update(event, self.tool_state, self.input_ui, self.snapping_points[0])
            tool.Blender.update_viewport()

        # BACKSPACE: remove last point (when not typing numeric input)
        if not self.tool_state.is_input_on:
            if event.value == "RELEASE" and event.type == "BACK_SPACE":
                tool.Polyline.remove_last_polyline_point()
                tool.Blender.update_viewport()

    def _transfer_polyline_to_pis(self, context):
        """Transfer collected polyline points to the PI Editor table.

        Polyline points are in Blender coordinate space. This method converts
        each point to IFC coordinate space before storing in props.pis.
        """
        props = context.scene.CivilAlignmentProperties
        polyline_props = tool.Model.get_polyline_props()
        polyline_data = polyline_props.insertion_polyline
        if not polyline_data:
            return

        polyline_points = polyline_data[0].polyline_points
        if not polyline_points:
            return

        # Blender world space is metres (1 BU = 1 m); the georeference helpers
        # work in IFC project length units. Convert before storing so the
        # alignment is recreated at the correct scale (e.g. feet projects).
        unit_scale = ifcopenshell.util.unit.calculate_unit_scale(tool.Ifc.get())

        num_points = len(polyline_points)
        for i, point in enumerate(polyline_points):
            # Blender metres -> IFC project units -> global easting/northing (stored on props.pis).
            local = (point.x / unit_scale, point.y / unit_scale, 0.0)
            ifc_coord = tool.Georeference.xyz2enh(local)

            pi = props.pis.add()
            pi.e = str(ifc_coord[0])
            pi.n = str(ifc_coord[1])

            # Determine PI type based on position
            if i == 0 or i == num_points - 1:
                pi.pi_type = "ENDPOINT"
            else:
                pi.pi_type = "TANGENT"

        props.active_pi_index = len(props.pis) - 1
        recalculate_pi_geometry(props)
        rebuild_display_rows(props)


def _build_alignment_from_active_pis(context):
    """Build/refresh the IFC horizontal segments from props.pis on the active
    alignment and visualize them.

    Shared by the Recalculate/Visualize operator and the PI picker (so picking
    auto-visualizes on completion). Returns (ok: bool, message: str).
    """
    import ifcopenshell.api.alignment as align_api

    ifc = tool.Ifc.get()
    props = context.scene.CivilAlignmentProperties
    recalculate_pi_geometry(props)

    alignment = tool.Alignment.get_active_alignment()
    if not alignment:
        total_length = sum(pi.length_to_next for pi in props.pis)
        return (
            False,
            f"Select an IfcAlignment in the outliner first. "
            f"(Recalculated {len(props.pis)} PIs, total length: {total_length:.2f})",
        )
    if len(props.pis) < 2:
        return False, "Need at least 2 PIs to build the alignment"

    props.active_alignment_id = alignment.id()

    # Bootstrap horizontal layout if the alignment is bare (e.g. from Add Element)
    h_layout = align_api.get_horizontal_layout(alignment)
    if h_layout is None:
        h_layout = tool.Alignment.add_horizontal_layout_to_alignment(alignment)

    # Ensure Blender objects exist for the alignment hierarchy
    alignment_obj = tool.Ifc.get_object(alignment)
    if not alignment_obj:
        alignment_obj = tool.Alignment.create_hierarchy_for_alignment(alignment)

    # Stored PI E/N (IFC project units) -> local IFC coords for the API.
    hpoints = [
        [float(o) for o in ifcopenshell.util.geolocation.auto_enh2xyz(ifc, float(pi.e), float(pi.n), 0.0)[:2]]
        for pi in props.pis
    ]
    # pi.radius/spiral_in_length/spiral_out_length are Blender LENGTH properties
    # (stored in metres); the API expects project units, so convert back via
    # unit_scale — same as the coordinates. Spec 1.5/1.6: build_pi_radius_element
    # shapes each PI's radii entry as plain R / (R, Lin, Lout) / a join_next dict.
    unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
    radii = [
        tool.Alignment.build_pi_radius_element(
            pi.radius / unit_scale,
            pi.spiral_in_length / unit_scale,
            pi.spiral_out_length / unit_scale,
            pi.join_next,
        )
        for pi in props.pis[1:-1]
    ]

    tool.Alignment.remove_layout_segment_objects(h_layout)
    tool.Alignment.clear_layout_segments(h_layout)
    align_api.layout_horizontal_alignment_by_pi_method(ifc, h_layout, hpoints, radii)

    layout_obj = tool.Ifc.get_object(h_layout)
    if not layout_obj:
        layout_obj = tool.Alignment.create_object_for_layout(h_layout, alignment_obj)
    if layout_obj:
        tool.Alignment.create_objects_for_layout_segments(h_layout, layout_obj)

    # Regenerate key-point referents and refresh any live station-tick
    # overlay (spec 4.2 commit funnel), then resync the referent list UI.
    tool.Alignment.commit_layout_change(alignment)
    refresh_referent_list(props, alignment)

    tool.Blender.update_viewport()
    return True, f"Updated alignment '{alignment.Name}' with {len(hpoints)} PIs"


class CIVIL_OT_recalculate_pis(Operator, tool.Ifc.Operator):
    """Recalculate PI geometry and update IFC/visualization"""

    bl_idname = "civil.recalculate_pis"
    bl_label = "Recalculate PIs"
    bl_description = "Recalculate geometry, update IFC segments, and refresh visualization"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if not poll_ifc4x3(cls, context):
            return False
        props = context.scene.CivilAlignmentProperties
        if len(props.pis) < 2:
            cls.poll_message_set("Need at least 2 PIs to recalculate")
            return False
        return True

    def _execute(self, context):
        ok, message = _build_alignment_from_active_pis(context)
        self.report({"INFO"} if ok else {"WARNING"}, message)


class CIVIL_OT_clear_pis(Operator, tool.Ifc.Operator):
    """Delete the active alignment and clear the PI table"""

    bl_idname = "civil.clear_pis"
    bl_label = "Clear All PIs"
    bl_description = (
        "Delete the entire active alignment — its IFC entity, all nested "
        "layouts and segments, and its viewport objects — and clear the PI table"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if not poll_ifc4x3(cls, context):
            return False
        props = context.scene.CivilAlignmentProperties
        if len(props.pis) == 0:
            cls.poll_message_set("No PIs to clear")
            return False
        return True

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def _execute(self, context):
        props = context.scene.CivilAlignmentProperties

        removed_objects = 0

        # Delete the active alignment entirely (Blender + IFC) so the file is
        # never left with an orphaned, PI-less alignment. Resolved through
        # props.active_alignment_id — the same reference every other panel
        # operator uses — not the viewport's active object. Routed through
        # the same core.delete_alignment path as civil.delete_alignment so
        # there is exactly one alignment-deletion code path.
        if alignment := _resolve_active_alignment(context):
            removed_objects = core.delete_alignment(tool.Ifc, tool.Alignment, alignment.id())
            props.active_alignment_id = 0
            props.active_alignment_name = ""

        # Clear the PI list in the UI
        props.pis.clear()
        props.active_pi_index = 0

        # Clear the display rows
        props.display_rows.clear()
        props.active_display_row_index = 0

        if removed_objects > 0:
            self.report({"INFO"}, f"Deleted alignment and removed {removed_objects} objects")
        else:
            self.report({"INFO"}, "Cleared all PIs")


class CIVIL_OT_delete_alignment(Operator, tool.Ifc.Operator):
    """Delete the active alignment: its IFC entity and all viewport objects"""

    bl_idname = "civil.delete_alignment"
    bl_label = "Delete Alignment"
    bl_description = (
        "Delete the active alignment — its IFC entity and all of its viewport "
        "objects (layouts, segments, 3D centerline). Cannot be undone from "
        "the IFC side beyond Blender's normal undo stack."
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if not poll_ifc4x3(cls, context):
            return False
        if _resolve_active_alignment(context) is None:
            cls.poll_message_set("No alignment selected")
            return False
        return True

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def _execute(self, context):
        props = context.scene.CivilAlignmentProperties

        alignment = _resolve_active_alignment(context)
        if alignment is None:
            self.report({"ERROR"}, "Alignment no longer exists")
            return {"CANCELLED"}

        removed_objects = core.delete_alignment(tool.Ifc, tool.Alignment, alignment.id())

        # Reset every piece of UI state that referenced the now-deleted alignment.
        props.active_alignment_id = 0
        props.active_alignment_name = ""
        props.pis.clear()
        props.active_pi_index = 0
        props.display_rows.clear()
        props.active_display_row_index = 0
        props.vertical_pvis.clear()
        props.active_pvi_index = 0
        props.vertical_display_rows.clear()
        props.active_vertical_display_row_index = 0

        # The profile view (D2) samples this alignment — drop it if showing.
        profile_view = alignment_decorator.ProfileViewDecorator
        if profile_view.is_installed:
            profile_view.uninstall()
            props.show_profile_view = False

        tool.Blender.update_viewport()
        self.report({"INFO"}, f"Deleted alignment and removed {removed_objects} objects")
        return {"FINISHED"}


# =============================================================================
# Creation Operators
# =============================================================================


class CIVIL_OT_create_alignment_by_pis(Operator, tool.Ifc.Operator):
    """Create a new alignment and immediately start picking PI points"""

    bl_idname = "civil.create_alignment_by_pis"
    bl_label = "New Alignment (PI Method)"
    bl_description = "Create a new alignment and pick PI points from the viewport"
    bl_options = {"REGISTER", "UNDO"}

    alignment_name: StringProperty(name="Name", default="Alignment")

    @classmethod
    def poll(cls, context):
        return poll_ifc4x3(cls, context)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def _execute(self, context):
        props = context.scene.CivilAlignmentProperties

        # Create full alignment via core → tool → API
        try:
            alignment = core.create_alignment(tool.Ifc, tool.Alignment, self.alignment_name)
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        props.active_alignment_id = alignment.id()
        props.active_alignment_name = alignment.Name or self.alignment_name
        refresh_referent_list(props, alignment)

        # Clear any existing PIs from previous work
        props.pis.clear()
        props.active_pi_index = 0
        props.display_rows.clear()
        props.active_display_row_index = 0

        self.report({"INFO"}, f"Created alignment '{alignment.Name}' — pick PI points now")

        # Chain into PI picker (runs as separate modal with its own undo)
        bpy.ops.civil.pick_pi_from_viewport("INVOKE_DEFAULT")

        return {"FINISHED"}


class CIVIL_OT_create_alignment_by_pi(Operator, tool.Ifc.Operator):
    """Create alignment using the PI (Point of Intersection) method"""

    bl_idname = "civil.create_alignment_by_pi"
    bl_label = "Create by PI Method"
    bl_description = "Create alignment using PI points and curve radii. If an active alignment exists with no segments, adds to it instead of creating new."
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if not poll_ifc4x3(cls, context):
            return False
        props = context.scene.CivilAlignmentProperties
        if len(props.pis) < 2:
            cls.poll_message_set("Need at least 2 PI points")
            return False
        if not tool.Alignment.get_active_alignment():
            cls.poll_message_set("Select an alignment to edit")
            return False
        return True

    def _execute(self, context):
        props = context.scene.CivilAlignmentProperties

        # Convert global E/N coords (stored in props.pis) -> local IFC coords for the IfcOpenShell API
        hpoints = [
            [
                float(o)
                for o in ifcopenshell.util.geolocation.auto_enh2xyz(tool.Ifc.get(), float(pi.e), float(pi.n), 0.0)[:2]
            ]
            for pi in props.pis
        ]
        radii = [
            tool.Alignment.build_pi_radius_element(pi.radius, pi.spiral_in_length, pi.spiral_out_length, pi.join_next)
            for pi in props.pis[1:-1]
        ]

        existing_alignment = tool.Alignment.get_active_alignment()
        if not (h_layout := ifcopenshell.api.alignment.get_horizontal_layout(existing_alignment)):
            return
        # Check if horizontal layout is empty (only has zero-length terminal or no segments)
        segments = ifcopenshell.api.alignment.get_layout_segments(h_layout)
        has_real_segments = bool([s for s in segments if not tool.Alignment.is_zero_length_segment(s)])

        ifcopenshell.api.alignment.create_representation(tool.Ifc.get(), existing_alignment)

        if not has_real_segments:
            # Use existing alignment - add segments to it
            # Use safe wrapper to validate layout has parent alignment
            tool.Alignment.safe_layout_horizontal_by_pi_method(tool.Ifc.get(), h_layout, hpoints, radii)

            # Create/update Blender objects for the segments
            alignment_obj = tool.Ifc.get_object(existing_alignment)
            h_layout_obj = tool.Ifc.get_object(h_layout)

            if not h_layout_obj and alignment_obj:
                h_layout_obj = tool.Alignment.create_object_for_layout(h_layout, alignment_obj)

            if h_layout_obj:
                tool.Alignment.create_objects_for_layout_segments(h_layout, h_layout_obj)

            self.report({"INFO"}, f"Added {len(hpoints)} PIs to existing alignment '{existing_alignment.Name}'")


# CSV import lives on the single upstream operator id `bim.import_alignment_csv`
# (class ImportAlignmentCSV above) — it now routes through
# core.import_alignment_csv, which builds the Saikei viewport hierarchy for the
# parent and any aggregated child alignments.


# =============================================================================
# Stationing Operators
# =============================================================================


class CIVIL_OT_add_stationing_referent(Operator, tool.Ifc.Operator):
    """Add a stationing referent to the alignment"""

    bl_idname = "civil.add_stationing_referent"
    bl_label = "Add Stationing Referent"
    bl_description = "Add an IfcReferent for stationing"
    bl_options = {"REGISTER", "UNDO"}

    station: FloatProperty(
        name="Station",
        description="Station value for the referent (e.g., 10000 for 100+00)",
        default=10000.0,
    )

    name: StringProperty(
        name="Name",
        description="Name for the referent (leave blank to auto-generate)",
        default="",
    )

    @classmethod
    def poll(cls, context):
        if not poll_ifc4x3(cls, context):
            return False
        props = context.scene.CivilAlignmentProperties
        if props.active_alignment_id == 0:
            cls.poll_message_set("Select an alignment first")
            return False
        return True

    def invoke(self, context, event):
        # Default station to start_station from props
        props = context.scene.CivilAlignmentProperties
        self.station = props.start_station
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "station")
        layout.prop(self, "name")
        # Show station notation preview
        station_str = tool.Alignment.format_station(self.station)
        layout.label(text=f"Station notation: {station_str}")

    def _execute(self, context):
        ifc = tool.Ifc.get()
        props = context.scene.CivilAlignmentProperties

        alignment = _resolve_active_alignment(context)
        if alignment is None:
            self.report({"ERROR"}, "Alignment no longer exists. Reference cleared.")
            return {"CANCELLED"}

        # Compute distance_along from station and start_station
        # distance_along = station - start_station
        distance_along = self.station - props.start_station

        # Auto-generate name if not provided
        name = self.name if self.name else tool.Alignment.format_station(self.station)

        ifcopenshell.api.alignment.add_stationing_referent(
            ifc,
            alignment=alignment,
            distance_along=distance_along,
            station=self.station,
            name=name,
        )

        refresh_referent_list(props, alignment)
        self.report({"INFO"}, f"Added referent '{name}' at station {self.station}")


class CIVIL_OT_name_segments(Operator, tool.Ifc.Operator):
    """Auto-name segments based on station values"""

    bl_idname = "civil.name_segments"
    bl_label = "Name Segments"
    bl_description = "Automatically name segments with station-based labels"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if not poll_ifc4x3(cls, context):
            return False
        props = context.scene.CivilAlignmentProperties
        if props.active_alignment_id == 0:
            cls.poll_message_set("Select an alignment first")
            return False
        return True

    def _execute(self, context):
        ifc = tool.Ifc.get()
        props = context.scene.CivilAlignmentProperties

        alignment = _resolve_active_alignment(context)
        if alignment is None:
            self.report({"ERROR"}, "Alignment no longer exists. Reference cleared.")
            return {"CANCELLED"}

        ifcopenshell.api.alignment.name_segments(ifc, alignment)

        self.report({"INFO"}, "Named alignment segments")


class CIVIL_OT_add_station_equation(Operator, tool.Ifc.Operator):
    """Add a station equation to the active alignment (spec 4.3)"""

    bl_idname = "civil.add_station_equation"
    bl_label = "Add Station Equation"
    bl_description = (
        "Insert a station equation: the point where stationing jumps from a back "
        "station (in the existing sequence) to an ahead station -- a gap "
        "(ahead > back) or an overlap (ahead < back) are both legal"
    )
    bl_options = {"REGISTER", "UNDO"}

    back_station: FloatProperty(
        name="Back Station",
        description="Station immediately before the equation, in the EXISTING stationing",
        default=0.0,
    )
    ahead_station: FloatProperty(
        name="Ahead Station",
        description="Station immediately after the equation",
        default=0.0,
    )

    @classmethod
    def poll(cls, context):
        if not poll_ifc4x3(cls, context):
            return False
        props = context.scene.CivilAlignmentProperties
        if props.active_alignment_id == 0:
            cls.poll_message_set("Select an alignment first")
            return False
        return True

    def invoke(self, context, event):
        props = context.scene.CivilAlignmentProperties
        self.back_station = props.start_station
        self.ahead_station = props.start_station
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "back_station")
        layout.prop(self, "ahead_station")
        layout.label(text=f"Back:  {tool.Alignment.format_station(self.back_station)}")
        layout.label(text=f"Ahead: {tool.Alignment.format_station(self.ahead_station)}")

    def _execute(self, context):
        props = context.scene.CivilAlignmentProperties
        alignment = _resolve_active_alignment(context)
        if alignment is None:
            self.report({"ERROR"}, "Alignment no longer exists")
            return {"CANCELLED"}

        try:
            core.add_station_equation(tool.Ifc, tool.Alignment, alignment.id(), self.back_station, self.ahead_station)
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        refresh_referent_list(props, alignment)
        self.report(
            {"INFO"},
            f"Added station equation {tool.Alignment.format_station(self.back_station)} = "
            f"{tool.Alignment.format_station(self.ahead_station)}",
        )
        return {"FINISHED"}


class CIVIL_OT_add_event_referent(Operator, tool.Ifc.Operator):
    """Add an event referent to the active alignment (spec 4.4)"""

    bl_idname = "civil.add_event_referent"
    bl_label = "Add Event Referent"
    bl_description = (
        "Add a station-located event referent (superelevation or width change) -- "
        "a marker for future corridor consumption; carries no geometry consequence "
        "on its own"
    )
    bl_options = {"REGISTER", "UNDO"}

    event_type: EnumProperty(
        name="Event Type",
        items=[
            ("SUPERELEVATIONEVENT", "Superelevation Event", "Marks a superelevation change"),
            ("WIDTHEVENT", "Width Event", "Marks a width change"),
        ],
        default="SUPERELEVATIONEVENT",
    )
    station: FloatProperty(name="Station", description="Station value for the event", default=0.0)
    name: StringProperty(name="Name", description="Leave blank to auto-generate", default="")
    use_value: BoolProperty(name="Set Value", description="Record a payload value on the event", default=False)
    value: FloatProperty(name="Value", description="Payload value (e.g. target superelevation or width)", default=0.0)

    @classmethod
    def poll(cls, context):
        if not poll_ifc4x3(cls, context):
            return False
        props = context.scene.CivilAlignmentProperties
        if props.active_alignment_id == 0:
            cls.poll_message_set("Select an alignment first")
            return False
        return True

    def invoke(self, context, event):
        props = context.scene.CivilAlignmentProperties
        self.station = props.start_station
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "event_type")
        layout.prop(self, "station")
        layout.label(text=f"Station notation: {tool.Alignment.format_station(self.station)}")
        layout.prop(self, "name")
        row = layout.row(align=True)
        row.prop(self, "use_value")
        sub = row.row()
        sub.enabled = self.use_value
        sub.prop(self, "value")

    def _execute(self, context):
        props = context.scene.CivilAlignmentProperties
        alignment = _resolve_active_alignment(context)
        if alignment is None:
            self.report({"ERROR"}, "Alignment no longer exists")
            return {"CANCELLED"}

        try:
            core.add_event_referent(
                tool.Ifc,
                tool.Alignment,
                alignment.id(),
                self.event_type,
                self.station,
                self.name,
                self.value if self.use_value else None,
            )
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        refresh_referent_list(props, alignment)
        self.report({"INFO"}, f"Added {self.event_type.title()} at {tool.Alignment.format_station(self.station)}")
        return {"FINISHED"}


class CIVIL_OT_remove_referent(Operator, tool.Ifc.Operator):
    """Remove the selected referent from the alignment (spec 4.1, "Deletable")"""

    bl_idname = "civil.remove_referent"
    bl_label = "Remove Referent"
    bl_description = "Delete the selected referent"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if not poll_ifc4x3(cls, context):
            return False
        props = context.scene.CivilAlignmentProperties
        if props.active_alignment_id == 0:
            cls.poll_message_set("Select an alignment first")
            return False
        if not (0 <= props.active_referent_index < len(props.referents)):
            cls.poll_message_set("No referent selected")
            return False
        return True

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def _execute(self, context):
        props = context.scene.CivilAlignmentProperties
        alignment = _resolve_active_alignment(context)
        if alignment is None:
            self.report({"ERROR"}, "Alignment no longer exists")
            return {"CANCELLED"}

        item = props.referents[props.active_referent_index]
        try:
            core.remove_referent(tool.Ifc, tool.Alignment, alignment.id(), item.referent_id)
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        refresh_referent_list(props, alignment)
        self.report({"INFO"}, "Removed referent")
        return {"FINISHED"}


class CIVIL_OT_refresh_referent_list(Operator):
    """Manually resync the referent list from IFC (spec 4.2)"""

    bl_idname = "civil.refresh_referent_list"
    bl_label = "Refresh Referents"
    bl_description = "Reload the referent list from the current IFC state"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        if not poll_ifc4x3(cls, context):
            return False
        props = context.scene.CivilAlignmentProperties
        if props.active_alignment_id == 0:
            cls.poll_message_set("Select an alignment first")
            return False
        return True

    def execute(self, context):
        props = context.scene.CivilAlignmentProperties
        alignment = _resolve_active_alignment(context)
        refresh_referent_list(props, alignment)
        self.report({"INFO"}, f"Loaded {len(props.referents)} referents")
        return {"FINISHED"}


# =============================================================================
# PI Edit Mode Operator
# =============================================================================


class CIVIL_OT_set_pi_curve_radius(Operator, tool.Ifc.Operator):
    """Set (or change) the curve radius at a PI while in PI edit mode"""

    bl_idname = "civil.set_pi_curve_radius"
    bl_label = "Set PI Curve Radius"
    bl_description = "Set the curve radius at a PI, validating that it fits within the adjacent tangents"
    bl_options = {"REGISTER", "UNDO"}

    alignment_id: IntProperty(default=0)
    pi_index: IntProperty(default=0)
    radius: FloatProperty(name="Radius", description="Curve radius", default=100.0, min=0.0, unit="LENGTH")

    @classmethod
    def poll(cls, context):
        props = context.scene.CivilAlignmentProperties
        if not props.is_pi_edit_mode:
            cls.poll_message_set("Only available during PI edit mode")
            return False
        return True

    def invoke(self, context, event):
        # Pre-fill from the empty's current radius, if it already has a curve.
        empties = tool.Alignment.get_pi_edit_empties(self.alignment_id)
        if 0 <= self.pi_index < len(empties):
            current = empties[self.pi_index].get("civil_pi_radius", 0.0)
            if current:
                self.radius = current
        return context.window_manager.invoke_props_dialog(self)

    def _execute(self, context):
        empties = tool.Alignment.get_pi_edit_empties(self.alignment_id)
        if not (0 <= self.pi_index < len(empties)):
            self.report({"ERROR"}, "PI not found")
            return {"CANCELLED"}

        ok, reason = tool.Alignment.validate_curve_fit(empties, self.pi_index, self.radius)
        if not ok:
            self.report({"ERROR"}, reason)
            return {"CANCELLED"}

        tool.Alignment.set_pi_radius(empties, self.pi_index, self.radius)
        alignment_decorator.PIEditDecorator.update_positions(empties)
        tool.Blender.update_viewport()
        self.report({"INFO"}, f"Curve radius set to {self.radius:.2f}")
        return {"FINISHED"}


class CIVIL_OT_enter_pi_edit_mode(Operator, tool.Ifc.Operator):
    """Enter PI editing mode - move PIs with G key, press Enter to apply or Escape to cancel"""

    bl_idname = "civil.enter_pi_edit_mode"
    bl_label = "Edit PIs"
    bl_description = (
        "Enter PI edit mode. G: move selected PI. I: insert PI on tangent. "
        "X: delete nearest PI. C / Alt+C: add / delete curve. T: slide tangent. "
        "Enter to apply changes, Escape to cancel."
    )
    bl_options = {"REGISTER", "UNDO"}

    PICK_RADIUS_PX = 20.0

    # Instance state for modal operation
    _pi_empties: list = []
    _last_positions: list = []
    _area = None
    _alignment_id: int = 0

    # Tangent slide ("T" key) sub-state
    _tangent_slide_mode: bool = False
    _sliding_tangent_index: int = -1
    _slide_start_a = None
    _slide_start_b = None
    _slide_start_prev = None
    _slide_start_next = None
    _slide_anchor = None

    @classmethod
    def poll(cls, context):
        if not poll_ifc4x3(cls, context):
            return False
        props = context.scene.CivilAlignmentProperties
        if props.is_pi_edit_mode:
            cls.poll_message_set("Already in PI edit mode")
            return False
        if props.active_alignment_id == 0:
            cls.poll_message_set("No alignment selected")
            return False
        # Verify alignment still exists
        alignment = _resolve_active_alignment(context)
        if alignment is None:
            cls.poll_message_set("Selected alignment no longer exists")
            return False
        return True

    def invoke(self, context, event):
        return IfcStore.execute_ifc_operator(self, context, event, method="INVOKE")

    def _invoke(self, context, event):
        props = context.scene.CivilAlignmentProperties
        self._alignment_id = props.active_alignment_id

        # Enter edit mode via core layer (validates and creates empties)
        try:
            empties = core.enter_pi_edit_mode(tool.Ifc, tool.Alignment, self._alignment_id)
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        if not empties:
            self.report({"ERROR"}, "Failed to create PI empties")
            return {"CANCELLED"}

        # Cache references to empties and their positions
        self._pi_empties = empties
        self._last_positions = [e.location.copy() for e in empties]
        self._tangent_slide_mode = False
        self._sliding_tangent_index = -1

        # Find viewport for redraws
        self._area = None
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                self._area = area
                break

        # Install visual feedback decorator
        alignment_decorator.PIEditDecorator.install(context, empties)

        # Make the segment curves non-selectable so viewport clicks land on the
        # PI empties, and deselect everything so the user starts clean.
        alignment = tool.Ifc.get().by_id(self._alignment_id)
        h_layout = tool.Alignment.get_horizontal_layout(alignment)
        tool.Alignment.set_layout_segments_selectable(h_layout, False)
        for obj in list(context.selected_objects):
            obj.select_set(False)

        # Update UI state
        props.is_pi_edit_mode = True
        props.pi_edit_alignment_id = self._alignment_id

        # Start modal loop
        context.window_manager.modal_handler_add(self)
        self.report(
            {"INFO"},
            "PI Edit Mode: G move, I insert, X delete, C/Alt+C curve, T slide tangent. Enter=apply, Esc=cancel.",
        )
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        return IfcStore.execute_ifc_operator(self, context, event, method="MODAL")

    def _modal(self, context, event):
        # Safety: check if empties still exist (handles undo edge case)
        if not self._empties_still_exist():
            self.report({"WARNING"}, "PI Edit Mode cancelled - empties were removed")
            return self._cleanup_and_finish(context, apply=False)

        # --- Tangent slide drag in progress: this takes over input first. ---
        if self._sliding_tangent_index >= 0:
            if event.type == "MOUSEMOVE":
                self._update_tangent_slide(context, event)
                return {"RUNNING_MODAL"}
            if (event.type == "LEFTMOUSE" and event.value == "PRESS") or (
                event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS"
            ):
                self._confirm_tangent_slide(context)
                return {"RUNNING_MODAL"}
            if event.type == "ESC" and event.value == "PRESS":
                self._abort_tangent_slide(context)
                return {"RUNNING_MODAL"}
            # Swallow everything else while dragging.
            return {"RUNNING_MODAL"}

        # Detect position changes from ordinary G-key moves and update decorator.
        positions_changed = False
        for i, empty in enumerate(self._pi_empties):
            if empty.location != self._last_positions[i]:
                positions_changed = True
                self._last_positions[i] = empty.location.copy()
        if positions_changed:
            alignment_decorator.PIEditDecorator.update_positions(self._pi_empties)
            if self._area:
                self._area.tag_redraw()

        # --- I: insert PI on nearest tangent ---
        if event.type == "I" and event.value == "PRESS":
            self._handle_insert_pi(context, event)
            return {"RUNNING_MODAL"}

        # --- X: delete nearest PI ---
        if event.type == "X" and event.value == "PRESS":
            self._handle_delete_pi(context, event)
            return {"RUNNING_MODAL"}

        # --- C: add curve / Alt+C: delete curve ---
        if event.type == "C" and event.value == "PRESS":
            if event.alt:
                self._handle_delete_curve(context, event)
            else:
                self._handle_add_curve(context, event)
            return {"RUNNING_MODAL"}

        # --- T: toggle tangent slide mode ---
        if event.type == "T" and event.value == "PRESS":
            self._tangent_slide_mode = not self._tangent_slide_mode
            alignment_decorator.PIEditDecorator.set_tangent_handles_visible(self._tangent_slide_mode)
            if self._area:
                self._area.tag_redraw()
            self.report(
                {"INFO"},
                "Tangent slide: click a handle to grab" if self._tangent_slide_mode else "Tangent slide off",
            )
            return {"RUNNING_MODAL"}

        # --- LEFTMOUSE while tangent-slide mode is armed: try to grab a handle ---
        if self._tangent_slide_mode and event.type == "LEFTMOUSE" and event.value == "PRESS":
            index = self._nearest_tangent_handle(context, event)
            if index >= 0:
                self._start_tangent_slide(context, event, index)
                return {"RUNNING_MODAL"}
            # Missed all handles - fall through to normal viewport handling.

        # Handle keyboard input
        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            return self._cleanup_and_finish(context, apply=True)

        if event.type == "ESC" and event.value == "PRESS":
            return self._cleanup_and_finish(context, apply=False)

        # Let all other events pass through (G key, mouse, viewport navigation, etc.)
        return {"PASS_THROUGH"}

    def _empties_still_exist(self) -> bool:
        """Check if all PI empties still exist in the scene."""
        for empty in self._pi_empties:
            if empty is None:
                return False
            if empty.name not in bpy.data.objects:
                return False
        return True

    # -- Viewport picking helpers -------------------------------------------------

    def _mouse_to_ground_point(self, context, event):
        """Ray-cast the mouse into the alignment's Z=0 plane (PI empties live there)."""
        region = context.region
        rv3d = context.region_data
        if region is None or rv3d is None:
            return None
        coord = (event.mouse_region_x, event.mouse_region_y)
        origin = region_2d_to_origin_3d(region, rv3d, coord)
        direction = region_2d_to_vector_3d(region, rv3d, coord)
        if abs(direction.z) < 1e-9:
            return None
        t = -origin.z / direction.z
        if t < 0:
            return None
        point = origin + direction * t
        return (point.x, point.y)

    def _nearest_pi_empty(self, context, event, predicate=None, max_px=None):
        region = context.region
        rv3d = context.region_data
        if region is None or rv3d is None:
            return -1
        max_px = self.PICK_RADIUS_PX if max_px is None else max_px
        mouse = (event.mouse_region_x, event.mouse_region_y)
        best_index, best_distance = -1, max_px
        for i, empty in enumerate(self._pi_empties):
            if predicate is not None and not predicate(i, empty):
                continue
            # .location, not matrix_world — see the comment in
            # tool.Alignment.validate_curve_fit for why.
            co2d = location_3d_to_region_2d(region, rv3d, empty.location)
            if co2d is None:
                continue
            distance = math.hypot(co2d.x - mouse[0], co2d.y - mouse[1])
            if distance <= best_distance:
                best_index, best_distance = i, distance
        return best_index

    def _nearest_tangent_handle(self, context, event, max_px=None):
        region = context.region
        rv3d = context.region_data
        if region is None or rv3d is None:
            return -1
        max_px = self.PICK_RADIUS_PX if max_px is None else max_px
        mouse = (event.mouse_region_x, event.mouse_region_y)
        best_index, best_distance = -1, max_px
        for i in range(len(self._pi_empties) - 1):
            a = self._pi_empties[i].location
            b = self._pi_empties[i + 1].location
            mid = ((a.x + b.x) / 2.0, (a.y + b.y) / 2.0, (a.z + b.z) / 2.0)
            co2d = location_3d_to_region_2d(region, rv3d, mid)
            if co2d is None:
                continue
            distance = math.hypot(co2d.x - mouse[0], co2d.y - mouse[1])
            if distance <= best_distance:
                best_index, best_distance = i, distance
        return best_index

    def _refresh_empties(self, context):
        """Reload the empty list/positions after the SET of empties changed
        (insert/delete), and push the update to the decorator."""
        self._pi_empties = tool.Alignment.get_pi_edit_empties(self._alignment_id)
        self._last_positions = [e.location.copy() for e in self._pi_empties]
        alignment_decorator.PIEditDecorator.update_positions(self._pi_empties)
        if self._area:
            self._area.tag_redraw()

    # -- Key handlers ---------------------------------------------------------

    def _handle_insert_pi(self, context, event):
        ground_point = self._mouse_to_ground_point(context, event)
        if ground_point is None:
            return
        new_empty, reason = tool.Alignment.insert_pi_on_tangent(self._alignment_id, ground_point)
        if new_empty is None:
            self.report({"ERROR"}, reason or "Could not insert a PI here")
            return
        self._refresh_empties(context)
        self.report({"INFO"}, "PI inserted")

    def _handle_delete_pi(self, context, event):
        index = self._nearest_pi_empty(context, event)
        if index < 0:
            return
        try:
            core.delete_pi_in_edit_mode(tool.Ifc, tool.Alignment, self._alignment_id, index)
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return
        self._refresh_empties(context)
        self.report({"INFO"}, "PI deleted")

    def _handle_add_curve(self, context, event):
        def is_interior(i, empty):
            return 0 < i < len(self._pi_empties) - 1

        index = self._nearest_pi_empty(context, event, predicate=is_interior)
        if index < 0:
            return
        bpy.ops.civil.set_pi_curve_radius("INVOKE_DEFAULT", alignment_id=self._alignment_id, pi_index=index)

    def _handle_delete_curve(self, context, event):
        def is_curved(i, empty):
            return float(empty.get("civil_pi_radius", 0.0)) > 0.0

        index = self._nearest_pi_empty(context, event, predicate=is_curved)
        if index < 0:
            return
        tool.Alignment.clear_pi_radius(self._alignment_id, index)
        self._refresh_empties(context)
        self.report({"INFO"}, "Curve removed")

    # -- Tangent slide (T key) -------------------------------------------------

    def _start_tangent_slide(self, context, event, index):
        empties = self._pi_empties
        self._sliding_tangent_index = index
        self._slide_start_a = tuple(empties[index].location)[:2]
        self._slide_start_b = tuple(empties[index + 1].location)[:2]
        self._slide_start_prev = tuple(empties[index - 1].location)[:2] if index - 1 >= 0 else None
        self._slide_start_next = tuple(empties[index + 2].location)[:2] if index + 2 < len(empties) else None
        self._slide_anchor = self._mouse_to_ground_point(context, event)

    def _update_tangent_slide(self, context, event):
        if self._slide_anchor is None:
            return
        ground_point = self._mouse_to_ground_point(context, event)
        if ground_point is None:
            return
        delta = (ground_point[0] - self._slide_anchor[0], ground_point[1] - self._slide_anchor[1])
        new_a, new_b = tool.Alignment.slide_tangent(
            self._slide_start_prev, self._slide_start_a, self._slide_start_b, self._slide_start_next, delta
        )
        index = self._sliding_tangent_index
        empties = self._pi_empties
        empties[index].location.x, empties[index].location.y = new_a
        empties[index + 1].location.x, empties[index + 1].location.y = new_b
        alignment_decorator.PIEditDecorator.update_positions(empties)
        if self._area:
            self._area.tag_redraw()

    def _end_tangent_slide(self):
        self._sliding_tangent_index = -1
        self._slide_start_a = self._slide_start_b = None
        self._slide_start_prev = self._slide_start_next = None
        self._slide_anchor = None
        self._last_positions = [e.location.copy() for e in self._pi_empties]

    def _confirm_tangent_slide(self, context):
        self._end_tangent_slide()
        self.report({"INFO"}, "Tangent slide confirmed")

    def _abort_tangent_slide(self, context):
        index = self._sliding_tangent_index
        empties = self._pi_empties
        if index >= 0 and self._slide_start_a is not None:
            empties[index].location.x, empties[index].location.y = self._slide_start_a
            empties[index + 1].location.x, empties[index + 1].location.y = self._slide_start_b
            alignment_decorator.PIEditDecorator.update_positions(empties)
            if self._area:
                self._area.tag_redraw()
        self._end_tangent_slide()
        self.report({"INFO"}, "Tangent slide aborted")

    def _cleanup_and_finish(self, context, apply: bool):
        """Exit edit mode, optionally applying changes."""
        props = context.scene.CivilAlignmentProperties

        try:
            if apply:
                # Regenerate alignment from new PI positions
                core.exit_pi_edit_mode(tool.Ifc, tool.Alignment, self._alignment_id, apply=True)
                # exit_pi_edit_mode already ran commit_layout_change — resync
                # the referent list UI with whatever it (re)authored.
                try:
                    refresh_referent_list(props, tool.Ifc.get().by_id(self._alignment_id))
                except RuntimeError:
                    pass
                self.report({"INFO"}, "PI changes applied - alignment updated")
            else:
                # Just cleanup without regenerating
                core.exit_pi_edit_mode(tool.Ifc, tool.Alignment, self._alignment_id, apply=False)
                self.report({"INFO"}, "PI Edit Mode cancelled")
        except ValueError as e:
            self.report({"ERROR"}, str(e))

        # Cleanup decorator
        alignment_decorator.PIEditDecorator.uninstall()

        # Restore segment selectability (on apply the segments are rebuilt and
        # already selectable; on cancel this re-enables the originals).
        try:
            alignment = tool.Ifc.get().by_id(self._alignment_id)
            h_layout = tool.Alignment.get_horizontal_layout(alignment)
            tool.Alignment.set_layout_segments_selectable(h_layout, True)
        except (RuntimeError, AttributeError):
            pass

        # Reset UI state
        props.is_pi_edit_mode = False
        props.pi_edit_alignment_id = 0

        # Clear instance state
        self._pi_empties = []
        self._last_positions = []
        self._tangent_slide_mode = False
        self._sliding_tangent_index = -1
        self._slide_start_a = self._slide_start_b = None
        self._slide_start_prev = self._slide_start_next = None
        self._slide_anchor = None

        if self._area:
            self._area.tag_redraw()

        if apply:
            return {"FINISHED"}
        return {"CANCELLED"}


# =============================================================================
# Vertical Alignment Operators
# =============================================================================


class CIVIL_OT_add_vertical_to_alignment(Operator, tool.Ifc.Operator):
    """Add a vertical layout to the active alignment"""

    bl_idname = "civil.add_vertical_to_alignment"
    bl_label = "Add Vertical Layout"
    bl_description = "Add a vertical (profile) layout to the active alignment"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if not poll_ifc4x3(cls, context):
            return False
        props = context.scene.CivilAlignmentProperties
        if props.active_alignment_id == 0:
            cls.poll_message_set("No alignment selected")
            return False
        alignment = _resolve_active_alignment(context)
        if alignment is None:
            cls.poll_message_set("Selected alignment no longer exists")
            return False
        if tool.Alignment.get_vertical_layout(alignment) is not None:
            cls.poll_message_set("Alignment already has a vertical layout")
            return False
        return True

    def _execute(self, context):
        props = context.scene.CivilAlignmentProperties
        try:
            v_layout = core.add_vertical_to_alignment(tool.Ifc, tool.Alignment, props.active_alignment_id)
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        # Give the new layout an outliner node (parallel to IfcAlignmentHorizontal)
        # so it's visible. An empty vertical has no segment geometry yet — the
        # PVI Editor populates it.
        alignment = tool.Ifc.get().by_id(props.active_alignment_id)
        alignment_obj = tool.Ifc.get_object(alignment)
        if alignment_obj is None:
            alignment_obj = tool.Alignment.create_hierarchy_for_alignment(alignment)
        if v_layout and alignment_obj:
            tool.Alignment.create_object_for_layout(v_layout, alignment_obj)
        tool.Blender.update_viewport()
        self.report({"INFO"}, "Vertical layout added — open the PVI Editor to add PVIs")


class CIVIL_OT_visualize_3d_alignment(Operator, tool.Ifc.Operator):
    """Create or refresh the draped 3D centerline for the active alignment"""

    bl_idname = "civil.visualize_3d_alignment"
    bl_label = "Show 3D Centerline"
    bl_description = (
        "Create or refresh the draped 3D centerline (combined horizontal + vertical "
        "alignment) for the active alignment"
    )
    bl_options = {"REGISTER", "UNDO"}

    distance_interval: FloatProperty(
        name="Sample Interval",
        description="Spacing between sampled points along the alignment",
        default=5.0,
        min=0.1,
    )

    @classmethod
    def poll(cls, context):
        if not poll_ifc4x3(cls, context):
            return False
        props = context.scene.CivilAlignmentProperties
        if props.active_alignment_id == 0:
            cls.poll_message_set("No alignment selected")
            return False
        alignment = _resolve_active_alignment(context)
        if alignment is None:
            cls.poll_message_set("Selected alignment no longer exists")
            return False
        return True

    def _execute(self, context):
        props = context.scene.CivilAlignmentProperties
        try:
            obj = core.visualize_3d_alignment(
                tool.Ifc, tool.Alignment, props.active_alignment_id, self.distance_interval
            )
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        if obj is None:
            self.report({"WARNING"}, "Alignment has no geometry to visualize")
            return {"CANCELLED"}
        refresh_referent_list(props, _resolve_active_alignment(context))
        self.report({"INFO"}, "3D centerline updated")


def _load_pvis_into_props(props, pvis):
    """Replace props.vertical_pvis with the given back-calculated PVI dicts.

    The PVI dicts are in IFC project units. elevation and curve_length are
    Blender LENGTH properties (stored in metres), so scale them so the table
    displays the correct values; station has no unit and is stored raw.
    """
    props.vertical_pvis.clear()
    unit_scale = ifcopenshell.util.unit.calculate_unit_scale(tool.Ifc.get())
    count = len(pvis)
    for i, pvi in enumerate(pvis):
        item = props.vertical_pvis.add()
        item.station = float(pvi["station"])
        item.elevation = float(pvi["elevation"]) * unit_scale
        item.curve_length = float(pvi.get("curve_length", 0.0)) * unit_scale
        item.pvi_type = "ENDPOINT" if (i == 0 or i == count - 1) else "INTERIOR"
    props.active_pvi_index = 0
    rebuild_vertical_display_rows(props)


class CIVIL_OT_toggle_profile_view(Operator):
    """Show or hide the 2D profile view (station vs elevation) overlay"""

    bl_idname = "civil.toggle_profile_view"
    bl_label = "Toggle Profile View"
    bl_description = "Show/hide the 2D station-vs-elevation profile overlay for the active alignment"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        if not poll_ifc4x3(cls, context):
            return False
        props = context.scene.CivilAlignmentProperties
        if props.active_alignment_id == 0:
            cls.poll_message_set("No alignment selected")
            return False
        return True

    def execute(self, context):
        props = context.scene.CivilAlignmentProperties
        decorator = alignment_decorator.ProfileViewDecorator
        if decorator.is_installed:
            decorator.uninstall()
            props.show_profile_view = False
        else:
            decorator.install(
                context,
                props.active_alignment_id,
                props.profile_terrain,
                props.profile_view_interval,
                props.profile_view_height,
                vertical_exaggeration=props.profile_exaggeration,
                design_speed=props.design_speed,
                track_gauge=props.track_gauge,
                cant_limit_max_applied=props.cant_limit_max_applied,
            )
            props.show_profile_view = True
        tool.Blender.update_viewport()
        return {"FINISHED"}


class CIVIL_OT_refresh_profile_view(Operator):
    """Re-sample the design and terrain profiles shown in the profile view"""

    bl_idname = "civil.refresh_profile_view"
    bl_label = "Refresh Profile View"
    bl_description = "Re-sample the design profile and terrain after edits or settings changes"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        if not poll_ifc4x3(cls, context):
            return False
        if not alignment_decorator.ProfileViewDecorator.is_installed:
            cls.poll_message_set("Profile view is not shown")
            return False
        return True

    def execute(self, context):
        props = context.scene.CivilAlignmentProperties
        decorator = alignment_decorator.ProfileViewDecorator
        decorator.alignment_id = props.active_alignment_id
        decorator.terrain_name = props.profile_terrain.name if props.profile_terrain else ""
        decorator.interval = props.profile_view_interval
        decorator.panel_height = props.profile_view_height
        decorator.vertical_exaggeration = props.profile_exaggeration
        decorator.design_speed = props.design_speed
        decorator.track_gauge = props.track_gauge
        decorator.cant_limit_max_applied = props.cant_limit_max_applied
        decorator.refresh()
        tool.Blender.update_viewport()
        return {"FINISHED"}


class CIVIL_OT_edit_pvi_in_profile(Operator):
    """Interactively drag PVI markers in the profile view

    Click a PVI marker and drag to change its elevation (and station, for
    interior PVIs). ENTER commits to the IFC vertical alignment (undo-safe via
    civil.recalculate_pvis); ESC discards.
    """

    bl_idname = "civil.edit_pvi_in_profile"
    bl_label = "Edit PVIs in Profile"
    bl_description = "Drag PVI markers in the profile view to edit elevations and stations"
    bl_options = {"REGISTER", "UNDO"}

    PICK_RADIUS_PX = 16.0

    @classmethod
    def poll(cls, context):
        if not poll_ifc4x3(cls, context):
            return False
        if not alignment_decorator.ProfileViewDecorator.is_installed:
            cls.poll_message_set("Show the profile view first")
            return False
        props = context.scene.CivilAlignmentProperties
        if props.active_alignment_id == 0:
            cls.poll_message_set("No alignment selected")
            return False
        alignment = _resolve_active_alignment(context)
        if alignment is None or tool.Alignment.get_vertical_layout(alignment) is None:
            cls.poll_message_set("Active alignment has no vertical layout")
            return False
        return True

    def invoke(self, context, event):
        props = context.scene.CivilAlignmentProperties
        self.alignment_id = props.active_alignment_id
        alignment = tool.Ifc.get().by_id(self.alignment_id)
        pvis = tool.Alignment.back_calculate_pvis_from_vertical(alignment)
        if len(pvis) < 2:
            self.report({"ERROR"}, "Need at least 2 PVIs to edit")
            return {"CANCELLED"}
        _load_pvis_into_props(props, pvis)
        self.dragging = -1
        self._sync_decorator(props)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _sync_decorator(self, props):
        decorator = alignment_decorator.ProfileViewDecorator
        points = [(p.station, p.elevation) for p in props.vertical_pvis]
        decorator.pvi_points = points
        decorator.preview_points = list(points)
        tool.Blender.update_viewport()

    def _nearest_pvi(self, props, mouse_x, mouse_y):
        transform = alignment_decorator.ProfileViewDecorator.current_transform
        if transform is None:
            return -1
        best_index, best_distance = -1, self.PICK_RADIUS_PX
        for i, pvi in enumerate(props.vertical_pvis):
            px, py = transform.data_to_screen(pvi.station, pvi.elevation)
            distance = math.hypot(px - mouse_x, py - mouse_y)
            if distance <= best_distance:
                best_index, best_distance = i, distance
        return best_index

    def modal(self, context, event):
        props = context.scene.CivilAlignmentProperties
        transform = alignment_decorator.ProfileViewDecorator.current_transform

        if event.type == "MOUSEMOVE" and self.dragging >= 0 and transform is not None:
            station, elevation = transform.screen_to_data(event.mouse_region_x, event.mouse_region_y)
            pvi = props.vertical_pvis[self.dragging]
            pvi.elevation = elevation
            # Interior PVIs may also move in station, clamped between neighbours.
            if 0 < self.dragging < len(props.vertical_pvis) - 1:
                low = props.vertical_pvis[self.dragging - 1].station + 1e-3
                high = props.vertical_pvis[self.dragging + 1].station - 1e-3
                pvi.station = max(low, min(high, station))
            self._sync_decorator(props)
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE":
            if event.value == "PRESS":
                self.dragging = self._nearest_pvi(props, event.mouse_region_x, event.mouse_region_y)
                return {"RUNNING_MODAL"}
            if event.value == "RELEASE":
                self.dragging = -1
                return {"RUNNING_MODAL"}

        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            return self._commit(context)

        if event.type == "ESC" and event.value == "PRESS":
            return self._cancel(context)

        # Let the user navigate the viewport while editing.
        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            return {"PASS_THROUGH"}

        return {"RUNNING_MODAL"}

    def _commit(self, context):
        decorator = alignment_decorator.ProfileViewDecorator
        decorator.preview_points = None
        try:
            bpy.ops.civil.recalculate_pvis()
        except RuntimeError as e:
            self.report({"ERROR"}, str(e))
            decorator.refresh()
            tool.Blender.update_viewport()
            return {"CANCELLED"}
        decorator.refresh()
        tool.Blender.update_viewport()
        self.report({"INFO"}, "Profile updated")
        return {"FINISHED"}

    def _cancel(self, context):
        props = context.scene.CivilAlignmentProperties
        decorator = alignment_decorator.ProfileViewDecorator
        decorator.preview_points = None
        # Reload the table from IFC so the discarded drag does not linger.
        alignment = tool.Ifc.get().by_id(self.alignment_id)
        try:
            _load_pvis_into_props(props, tool.Alignment.back_calculate_pvis_from_vertical(alignment))
        except ValueError:
            pass
        decorator.refresh()
        tool.Blender.update_viewport()
        return {"CANCELLED"}


class CIVIL_OT_add_pvi(Operator):
    """Add a new PVI to the vertical alignment list"""

    bl_idname = "civil.add_pvi"
    bl_label = "Add PVI"
    bl_description = "Add a new PVI (Point of Vertical Intersection)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return poll_ifc4x3(cls, context)

    def execute(self, context):
        props = context.scene.CivilAlignmentProperties

        pvi = props.vertical_pvis.add()

        if len(props.vertical_pvis) == 1:
            pvi.station = 0.0
            pvi.elevation = 0.0
            pvi.pvi_type = "ENDPOINT"
        elif len(props.vertical_pvis) == 2:
            prev = props.vertical_pvis[0]
            pvi.station = prev.station + 100.0
            pvi.elevation = prev.elevation
            pvi.pvi_type = "ENDPOINT"
        else:
            prev = props.vertical_pvis[-2]
            prev_prev = props.vertical_pvis[-3]
            ds = prev.station - prev_prev.station
            de = prev.elevation - prev_prev.elevation
            pvi.station = prev.station + ds
            pvi.elevation = prev.elevation + de
            pvi.pvi_type = "INTERIOR"
            props.vertical_pvis[-2].pvi_type = "INTERIOR"

        props.active_pvi_index = len(props.vertical_pvis) - 1
        recalculate_pvi_geometry(props)
        return {"FINISHED"}


class CIVIL_OT_remove_pvi(Operator):
    """Remove the selected PVI from the vertical alignment list"""

    bl_idname = "civil.remove_pvi"
    bl_label = "Remove PVI"
    bl_description = "Remove the selected PVI"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if not poll_ifc4x3(cls, context):
            return False
        props = context.scene.CivilAlignmentProperties
        if len(props.vertical_pvis) == 0:
            cls.poll_message_set("No PVIs to remove")
            return False
        if props.vertical_display_rows:
            idx = props.active_vertical_display_row_index
            if 0 <= idx < len(props.vertical_display_rows):
                if props.vertical_display_rows[idx].row_type != "POINT":
                    cls.poll_message_set("Select a PVI point row to remove")
                    return False
        return True

    def execute(self, context):
        props = context.scene.CivilAlignmentProperties

        pvi_index = -1
        if props.vertical_display_rows:
            idx = props.active_vertical_display_row_index
            if 0 <= idx < len(props.vertical_display_rows):
                row = props.vertical_display_rows[idx]
                if row.row_type == "POINT":
                    pvi_index = row.pvi_index

        if pvi_index < 0:
            pvi_index = props.active_pvi_index

        if 0 <= pvi_index < len(props.vertical_pvis):
            props.vertical_pvis.remove(pvi_index)
            props.active_pvi_index = min(pvi_index, len(props.vertical_pvis) - 1)
            recalculate_pvi_geometry(props)

            if len(props.vertical_display_rows) > 0:
                props.active_vertical_display_row_index = min(
                    props.active_vertical_display_row_index, len(props.vertical_display_rows) - 1
                )
            else:
                props.active_vertical_display_row_index = 0

        return {"FINISHED"}


class CIVIL_OT_recalculate_pvis(Operator, tool.Ifc.Operator):
    """Recalculate PVI geometry and update the IFC vertical alignment"""

    bl_idname = "civil.recalculate_pvis"
    bl_label = "Recalculate PVIs"
    bl_description = "Recalculate geometry, update IFC vertical segments, and refresh visualization"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if not poll_ifc4x3(cls, context):
            return False
        props = context.scene.CivilAlignmentProperties
        if len(props.vertical_pvis) < 2:
            cls.poll_message_set("Need at least 2 PVIs to recalculate")
            return False
        return True

    def _execute(self, context):
        props = context.scene.CivilAlignmentProperties
        recalculate_pvi_geometry(props)

        alignment = _resolve_active_alignment(context)
        if alignment is not None and props.design_speed > 0:
            # Persist the advisory design speed so flags survive save/reopen.
            tool.Alignment.set_design_criteria(alignment, props.design_speed)
        if not alignment:
            total_len = 0.0
            if len(props.vertical_pvis) >= 2:
                total_len = props.vertical_pvis[-1].station - props.vertical_pvis[0].station
            self.report({"INFO"}, f"Recalculated {len(props.vertical_pvis)} PVIs, total length: {total_len:.2f}")
            return

        v_layout = tool.Alignment.get_vertical_layout(alignment)
        if v_layout is None:
            self.report({"ERROR"}, "Alignment has no vertical layout — add vertical first")
            return

        # station has no unit (raw project units); elevation and curve_length are
        # Blender LENGTH properties (stored in metres) — convert to project units
        # for the API, same as the horizontal radius.
        unit_scale = ifcopenshell.util.unit.calculate_unit_scale(tool.Ifc.get())
        vpoints = [(pvi.station, pvi.elevation / unit_scale) for pvi in props.vertical_pvis]
        curve_lengths = [
            props.vertical_pvis[i].curve_length / unit_scale for i in range(1, len(props.vertical_pvis) - 1)
        ]

        tool.Alignment.remove_layout_segment_objects(v_layout)
        tool.Alignment.clear_layout_segments(v_layout)
        tool.Alignment.layout_vertical_by_pvi_method(v_layout, vpoints, curve_lengths)

        # Ensure the vertical layout has an outliner node so its segments display
        # (it won't if the layout was created before the node-creation fix).
        layout_obj = tool.Ifc.get_object(v_layout)
        if not layout_obj:
            alignment_obj = tool.Ifc.get_object(alignment)
            if alignment_obj:
                layout_obj = tool.Alignment.create_object_for_layout(v_layout, alignment_obj)
        if layout_obj:
            tool.Alignment.create_objects_for_layout_segments(v_layout, layout_obj)

        # Regenerate key-point referents and refresh any live station-tick
        # overlay (spec 4.2 commit funnel), then resync the referent list UI.
        tool.Alignment.commit_layout_change(alignment)
        refresh_referent_list(props, alignment)

        tool.Blender.update_viewport()
        self.report({"INFO"}, f"Updated vertical alignment '{alignment.Name}' with {len(vpoints)} PVIs")


class CIVIL_OT_clear_pvis(Operator, tool.Ifc.Operator):
    """Clear all PVIs from the vertical editor"""

    bl_idname = "civil.clear_pvis"
    bl_label = "Clear All PVIs"
    bl_description = "Remove all PVIs from the vertical editor"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if not poll_ifc4x3(cls, context):
            return False
        props = context.scene.CivilAlignmentProperties
        if len(props.vertical_pvis) == 0:
            cls.poll_message_set("No PVIs to clear")
            return False
        return True

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def _execute(self, context):
        props = context.scene.CivilAlignmentProperties
        props.vertical_pvis.clear()
        props.active_pvi_index = 0
        props.vertical_display_rows.clear()
        props.active_vertical_display_row_index = 0
        self.report({"INFO"}, "Cleared all PVIs")


class CIVIL_OT_delete_vertical_layout(Operator, tool.Ifc.Operator):
    """Delete the vertical layout and its IFC segments, reverting to horizontal-only"""

    bl_idname = "civil.delete_vertical_layout"
    bl_label = "Delete Vertical Layout"
    bl_description = (
        "Delete the vertical layout and its IFC segments, reverting the "
        "alignment to horizontal-only. Unlike Clear All PVIs — which only "
        "clears the table rows above — this also removes the underlying "
        "IfcAlignmentVertical and its segments from the IFC model"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if not poll_ifc4x3(cls, context):
            return False
        props = context.scene.CivilAlignmentProperties
        if props.active_alignment_id == 0:
            cls.poll_message_set("No alignment selected")
            return False
        alignment = _resolve_active_alignment(context)
        if alignment is None:
            cls.poll_message_set("Selected alignment no longer exists")
            return False
        if tool.Alignment.get_vertical_layout(alignment) is None:
            cls.poll_message_set("Alignment has no vertical layout")
            return False
        return True

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def _execute(self, context):
        props = context.scene.CivilAlignmentProperties

        try:
            core.delete_vertical_layout(tool.Ifc, tool.Alignment, props.active_alignment_id)
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        # The PVI table represented the layout that is now gone.
        props.vertical_pvis.clear()
        props.active_pvi_index = 0
        props.vertical_display_rows.clear()
        props.active_vertical_display_row_index = 0

        # The profile view (D2) samples the vertical layout — drop it if it
        # was showing this alignment so it doesn't keep drawing stale data.
        profile_view = alignment_decorator.ProfileViewDecorator
        if profile_view.is_installed and profile_view.alignment_id == props.active_alignment_id:
            profile_view.uninstall()
            props.show_profile_view = False

        tool.Blender.update_viewport()
        self.report({"INFO"}, "Vertical layout deleted")
        return {"FINISHED"}


class CIVIL_OT_enter_pvi_edit_mode(Operator, tool.Ifc.Operator):
    """Enter PVI editing mode - move PVIs with G key, press Enter to apply or Escape to cancel"""

    bl_idname = "civil.enter_pvi_edit_mode"
    bl_label = "Edit PVIs"
    bl_description = (
        "Enter PVI edit mode. Move PVI points with G key. " "Press Enter to apply changes, Escape to cancel."
    )
    bl_options = {"REGISTER", "UNDO"}

    _pvi_empties: list = []
    _last_positions: list = []
    _area = None
    _alignment_id: int = 0

    @classmethod
    def poll(cls, context):
        if not poll_ifc4x3(cls, context):
            return False
        props = context.scene.CivilAlignmentProperties
        if props.is_pvi_edit_mode:
            cls.poll_message_set("Already in PVI edit mode")
            return False
        if props.active_alignment_id == 0:
            cls.poll_message_set("No alignment selected")
            return False
        alignment = _resolve_active_alignment(context)
        if alignment is None:
            cls.poll_message_set("Selected alignment no longer exists")
            return False
        if tool.Alignment.get_vertical_layout(alignment) is None:
            cls.poll_message_set("Alignment has no vertical layout")
            return False
        return True

    def invoke(self, context, event):
        return IfcStore.execute_ifc_operator(self, context, event, method="INVOKE")

    def _invoke(self, context, event):
        props = context.scene.CivilAlignmentProperties
        self._alignment_id = props.active_alignment_id

        # Rehydrate the persisted advisory design speed (spec 2.4) so K flags
        # come back after save/reopen without re-entering the value.
        alignment = _resolve_active_alignment(context)
        if alignment is not None and props.design_speed == 0:
            persisted_speed = tool.Alignment.get_design_criteria(alignment)
            if persisted_speed:
                props.design_speed = persisted_speed

        try:
            empties = core.enter_pvi_edit_mode(tool.Ifc, tool.Alignment, self._alignment_id)
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        if not empties:
            self.report({"ERROR"}, "Failed to create PVI empties")
            return {"CANCELLED"}

        self._pvi_empties = empties
        self._last_positions = [e.location.copy() for e in empties]

        self._area = None
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                self._area = area
                break

        alignment_decorator.PIEditDecorator.install(context, empties)

        props.is_pvi_edit_mode = True
        props.pvi_edit_alignment_id = self._alignment_id

        context.window_manager.modal_handler_add(self)
        self.report({"INFO"}, "PVI Edit Mode: Move PVIs with G. Press Enter to apply, Escape to cancel.")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        return IfcStore.execute_ifc_operator(self, context, event, method="MODAL")

    def _modal(self, context, event):
        props = context.scene.CivilAlignmentProperties

        if not self._empties_still_exist():
            self.report({"WARNING"}, "PVI Edit Mode cancelled - empties were removed")
            return self._cleanup_and_finish(context, apply=False)

        positions_changed = False
        for i, empty in enumerate(self._pvi_empties):
            if empty.location != self._last_positions[i]:
                positions_changed = True
                self._last_positions[i] = empty.location.copy()

        if positions_changed:
            alignment_decorator.PIEditDecorator.update_positions(self._pvi_empties)
            if self._area:
                self._area.tag_redraw()

        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            return self._cleanup_and_finish(context, apply=True)

        if event.type == "ESC" and event.value == "PRESS":
            return self._cleanup_and_finish(context, apply=False)

        return {"PASS_THROUGH"}

    def _empties_still_exist(self) -> bool:
        for empty in self._pvi_empties:
            if empty is None or empty.name not in bpy.data.objects:
                return False
        return True

    def _cleanup_and_finish(self, context, apply: bool):
        props = context.scene.CivilAlignmentProperties

        try:
            if apply:
                core.exit_pvi_edit_mode(tool.Ifc, tool.Alignment, self._alignment_id, apply=True)
                # exit_pvi_edit_mode already ran commit_layout_change — resync
                # the referent list UI with whatever it (re)authored.
                try:
                    refresh_referent_list(props, tool.Ifc.get().by_id(self._alignment_id))
                except RuntimeError:
                    pass
                self.report({"INFO"}, "PVI changes applied - vertical alignment updated")
            else:
                core.exit_pvi_edit_mode(tool.Ifc, tool.Alignment, self._alignment_id, apply=False)
                self.report({"INFO"}, "PVI Edit Mode cancelled")
        except ValueError as e:
            self.report({"ERROR"}, str(e))

        alignment_decorator.PIEditDecorator.uninstall()

        props.is_pvi_edit_mode = False
        props.pvi_edit_alignment_id = 0

        self._pvi_empties = []
        self._last_positions = []

        if self._area:
            self._area.tag_redraw()

        if apply:
            return {"FINISHED"}
        return {"CANCELLED"}


# =============================================================================
# Cant Operators (spec Section 3)
# =============================================================================


class CIVIL_OT_add_cant_to_alignment(Operator, tool.Ifc.Operator):
    """Add a cant layout to the active alignment — marks it as rail"""

    bl_idname = "civil.add_cant_to_alignment"
    bl_label = "Add Cant"
    bl_description = (
        "Add a cant (rail superelevation) layout to the active alignment. Requires both a "
        "horizontal and a vertical layout to already exist"
    )
    bl_options = {"REGISTER", "UNDO"}

    rail_head_distance: FloatProperty(
        name="Rail Head Distance",
        description=(
            "Distance between rail heads — the alignment API uses it to convert cant height "
            "(a vertical offset between the two rails) into a rotation angle for the geometric "
            "representation"
        ),
        default=1.5,
        min=0.0001,
        unit="LENGTH",
    )

    @classmethod
    def poll(cls, context):
        if not poll_ifc4x3(cls, context):
            return False
        props = context.scene.CivilAlignmentProperties
        if props.active_alignment_id == 0:
            cls.poll_message_set("No alignment selected")
            return False
        alignment = _resolve_active_alignment(context)
        if alignment is None:
            cls.poll_message_set("Selected alignment no longer exists")
            return False
        if tool.Alignment.get_vertical_layout(alignment) is None:
            cls.poll_message_set("Alignment has no vertical layout — add vertical first")
            return False
        if tool.Alignment.get_cant_layout(alignment) is not None:
            cls.poll_message_set("Alignment already has a cant layout")
            return False
        return True

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def _execute(self, context):
        props = context.scene.CivilAlignmentProperties
        try:
            cant_layout = core.add_cant_to_alignment(
                tool.Ifc, tool.Alignment, props.active_alignment_id, self.rail_head_distance
            )
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        # Give the new layout an outliner node (parallel to IfcAlignmentHorizontal/Vertical),
        # mirroring CIVIL_OT_add_vertical_to_alignment.
        alignment = tool.Ifc.get().by_id(props.active_alignment_id)
        alignment_obj = tool.Ifc.get_object(alignment)
        if alignment_obj is None:
            alignment_obj = tool.Alignment.create_hierarchy_for_alignment(alignment)
        if cant_layout and alignment_obj:
            tool.Alignment.create_object_for_layout(cant_layout, alignment_obj)

        # Persist the (default) rotation reference immediately so the pset
        # round-trips even if the user never touches the dropdown.
        if cant_layout:
            tool.Alignment.set_cant_rotation_reference(cant_layout, props.cant_rotation_reference)

        props.cant_points.clear()
        props.active_cant_point_index = 0
        props.cant_display_rows.clear()
        props.active_cant_display_row_index = 0

        tool.Blender.update_viewport()
        self.report({"INFO"}, "Cant layout added — add cant points below")


class CIVIL_OT_add_cant_point(Operator):
    """Add a new cant point to the table"""

    bl_idname = "civil.add_cant_point"
    bl_label = "Add Cant Point"
    bl_description = "Add a new cant point — appends after the selected point, or at the end"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return poll_ifc4x3(cls, context)

    def execute(self, context):
        props = context.scene.CivilAlignmentProperties
        points = props.cant_points

        # Resolve the currently-selected POINT row (if any) to insert after.
        insert_after = len(points) - 1
        if points and props.cant_display_rows:
            idx = props.active_cant_display_row_index
            if 0 <= idx < len(props.cant_display_rows):
                row = props.cant_display_rows[idx]
                if row.row_type == "POINT" and row.point_index < len(points) - 1:
                    insert_after = row.point_index

        if len(points) == 0:
            new_point = points.add()
            new_point.station = 0.0
            new_point.cant_left = 0.0
            new_point.cant_right = 0.0
            new_point.transition_type = "LINEARTRANSITION"
            new_index = 0
        else:
            before = points[insert_after]
            if insert_after + 1 < len(points):
                after = points[insert_after + 1]
                new_station = (before.station + after.station) / 2.0
            else:
                alignment = tool.Alignment.get_active_alignment()
                extent = tool.Alignment.get_horizontal_extent_semantic(alignment) if alignment else 0.0
                new_station = min(before.station + 100.0, extent) if extent > before.station else before.station + 100.0

            # bpy CollectionProperty only supports append; add then shift values
            # down to open a slot at insert_after + 1 (mirrors civil.insert_pi
            # style renumbering, done here inline since it's a plain float shift).
            points.add()
            new_index = len(points) - 1
            for i in range(new_index, insert_after + 1, -1):
                src, dst = points[i - 1], points[i]
                dst.station = src.station
                dst.cant_left = src.cant_left
                dst.cant_right = src.cant_right
                dst.transition_type = src.transition_type
                dst.design_speed = src.design_speed
            new_point = points[insert_after + 1]
            new_point.station = new_station
            new_point.cant_left = before.cant_left
            new_point.cant_right = before.cant_right
            new_point.transition_type = before.transition_type
            new_point.design_speed = 0.0
            new_index = insert_after + 1

        props.active_cant_point_index = new_index
        rebuild_cant_display_rows(props)
        return {"FINISHED"}


class CIVIL_OT_remove_cant_point(Operator):
    """Remove the selected cant point"""

    bl_idname = "civil.remove_cant_point"
    bl_label = "Remove Cant Point"
    bl_description = "Remove the selected cant point"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if not poll_ifc4x3(cls, context):
            return False
        props = context.scene.CivilAlignmentProperties
        if len(props.cant_points) == 0:
            cls.poll_message_set("No cant points to remove")
            return False
        if props.cant_display_rows:
            idx = props.active_cant_display_row_index
            if 0 <= idx < len(props.cant_display_rows):
                if props.cant_display_rows[idx].row_type != "POINT":
                    cls.poll_message_set("Select a point row to remove")
                    return False
        return True

    def execute(self, context):
        props = context.scene.CivilAlignmentProperties

        point_index = -1
        if props.cant_display_rows:
            idx = props.active_cant_display_row_index
            if 0 <= idx < len(props.cant_display_rows):
                row = props.cant_display_rows[idx]
                if row.row_type == "POINT":
                    point_index = row.point_index

        if point_index < 0:
            point_index = props.active_cant_point_index

        if 0 <= point_index < len(props.cant_points):
            props.cant_points.remove(point_index)
            props.active_cant_point_index = min(point_index, len(props.cant_points) - 1)
            rebuild_cant_display_rows(props)

            if len(props.cant_display_rows) > 0:
                props.active_cant_display_row_index = min(
                    props.active_cant_display_row_index, len(props.cant_display_rows) - 1
                )
            else:
                props.active_cant_display_row_index = 0

        return {"FINISHED"}


class CIVIL_OT_recalculate_cant(Operator, tool.Ifc.Operator):
    """Recalculate cant checks and write IFC cant segments"""

    bl_idname = "civil.recalculate_cant"
    bl_label = "Recalculate Cant"
    bl_description = "Recalculate checks, write IFC cant segments, and refresh visualization"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if not poll_ifc4x3(cls, context):
            return False
        props = context.scene.CivilAlignmentProperties
        if len(props.cant_points) < 2:
            cls.poll_message_set("Need at least 2 cant points to recalculate")
            return False
        return True

    def _execute(self, context):
        props = context.scene.CivilAlignmentProperties
        rebuild_cant_display_rows(props)

        alignment = _resolve_active_alignment(context)
        if alignment is None:
            self.report({"ERROR"}, "Select an IfcAlignment in the outliner first")
            return {"CANCELLED"}

        cant_layout = tool.Alignment.get_cant_layout(alignment)
        if cant_layout is None:
            self.report({"ERROR"}, "Alignment has no cant layout — add cant first")
            return {"CANCELLED"}

        points = _cant_points_as_dicts(props)
        try:
            core.update_cant_segments(tool.Ifc, tool.Alignment, alignment.id(), points)
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        tool.Alignment.remove_layout_segment_objects(cant_layout)
        layout_obj = tool.Ifc.get_object(cant_layout)
        if not layout_obj:
            alignment_obj = tool.Ifc.get_object(alignment)
            if alignment_obj:
                layout_obj = tool.Alignment.create_object_for_layout(cant_layout, alignment_obj)
        if layout_obj:
            tool.Alignment.create_objects_for_layout_segments(cant_layout, layout_obj)

        # core.update_cant_segments already ran commit_layout_change — just
        # resync the referent list UI with whatever it (re)authored.
        refresh_referent_list(props, alignment)

        tool.Blender.update_viewport()
        self.report({"INFO"}, f"Updated cant layout with {len(points)} points")


class CIVIL_OT_clear_cant_points(Operator, tool.Ifc.Operator):
    """Clear all cant points from the editor table"""

    bl_idname = "civil.clear_cant_points"
    bl_label = "Clear All Cant Points"
    bl_description = (
        "Remove all cant points from the editor table (rows only — does not delete the "
        "cant layout or its IFC segments; use Delete Cant Layout for that)"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if not poll_ifc4x3(cls, context):
            return False
        props = context.scene.CivilAlignmentProperties
        if len(props.cant_points) == 0:
            cls.poll_message_set("No cant points to clear")
            return False
        return True

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def _execute(self, context):
        props = context.scene.CivilAlignmentProperties
        props.cant_points.clear()
        props.active_cant_point_index = 0
        props.cant_display_rows.clear()
        props.active_cant_display_row_index = 0
        self.report({"INFO"}, "Cleared all cant points")


class CIVIL_OT_delete_cant_layout(Operator, tool.Ifc.Operator):
    """Delete the cant layout and its IFC segments"""

    bl_idname = "civil.delete_cant_layout"
    bl_label = "Delete Cant Layout"
    bl_description = (
        "Delete the cant layout and its IFC segments, reverting the alignment's representation "
        "to horizontal + vertical only. Anything swept with cant is not rebuilt automatically "
        "(no corridor/sweep tooling exists yet)"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if not poll_ifc4x3(cls, context):
            return False
        props = context.scene.CivilAlignmentProperties
        if props.active_alignment_id == 0:
            cls.poll_message_set("No alignment selected")
            return False
        alignment = _resolve_active_alignment(context)
        if alignment is None:
            cls.poll_message_set("Selected alignment no longer exists")
            return False
        if tool.Alignment.get_cant_layout(alignment) is None:
            cls.poll_message_set("Alignment has no cant layout")
            return False
        return True

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def _execute(self, context):
        props = context.scene.CivilAlignmentProperties

        try:
            core.delete_cant_layout(tool.Ifc, tool.Alignment, props.active_alignment_id)
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        props.cant_points.clear()
        props.active_cant_point_index = 0
        props.cant_display_rows.clear()
        props.active_cant_display_row_index = 0

        tool.Blender.update_viewport()
        self.report({"INFO"}, "Cant layout deleted")
        return {"FINISHED"}

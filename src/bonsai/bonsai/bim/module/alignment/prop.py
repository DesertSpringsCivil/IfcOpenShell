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


"""Property groups for the alignment module"""

import bpy
from bpy.types import PropertyGroup
from bpy.props import (
    StringProperty,
    FloatProperty,
    IntProperty,
    BoolProperty,
    CollectionProperty,
    EnumProperty,
)


def _on_curve_length_update(self, context):
    """Callback when curve_length property changes on a VerticalPVI.

    Dynamically imports the operator module to call on_curve_length_changed,
    avoiding circular imports.
    """
    from . import operator as ops

    ops.on_curve_length_changed(self, context)


def _on_radius_update(self, context):
    """Callback when radius property changes.

    This dynamically imports the operator module to call on_radius_changed,
    avoiding circular imports since prop.py is imported before operator.py.
    on_radius_changed also re-derives spiral lengths from the (unchanged)
    A-values when spiral_mode is A_VALUE (spec 1.5: "radius changes
    re-derive length from A when mode is A_VALUE").
    """
    from . import operator as ops

    ops.on_radius_changed(self, context)


def _on_spiral_length_update(self, context):
    """Callback when spiral_in_length/spiral_out_length changes (spec 1.5).

    The length fields are authoritative in LENGTH mode, so this only
    recalculates PI geometry / rebuilds the display table -- it never
    writes back to spiral_a_in/spiral_a_out (the table derives the
    A-value shown on Spiral rows on the fly, from length + radius).
    """
    from . import operator as ops

    ops.on_spiral_length_changed(self, context)


def _on_spiral_a_value_update(self, context):
    """Callback when spiral_a_in/spiral_a_out changes (spec 1.5 A-value mode).

    Only re-derives the matching spiral length (using the current radius)
    when spiral_mode is A_VALUE -- "editing A updates length using current
    radius".
    """
    from . import operator as ops

    ops.on_spiral_a_value_changed(self, context)


def _on_spiral_mode_update(self, context):
    """Callback when spiral_mode toggles between LENGTH and A_VALUE.

    Reconciles the pair once, in the direction the newly-active mode
    requires, so whichever field the user edits next is already coherent
    with the other.
    """
    from . import operator as ops

    ops.on_spiral_mode_changed(self, context)


def _terrain_object_poll(self, obj):
    """Restrict the profile-view terrain picker to mesh objects."""
    return obj.type == "MESH"


def _on_design_speed_update(self, context):
    """Re-flag the PVI table when the design speed changes."""
    from . import operator as ops

    ops.rebuild_vertical_display_rows(self)


def _on_cant_value_update(self, context):
    """Callback when a cant point's edited value changes.

    Mirrors ``_on_design_speed_update``: recomputes the CHECKS row (E_eq,
    deficiency/excess, gradient, twist, limit violations) so the table stays
    live as the user types. This does NOT write to IFC — spec 3.5 keeps the
    PI/PVI table idiom of an explicit Recalculate button for the IFC write;
    "recompute on cell edit" here refers only to the advisory checks.
    """
    from . import operator as ops

    props = context.scene.CivilAlignmentProperties
    ops.rebuild_cant_display_rows(props)


def _on_cant_rotation_reference_update(self, context):
    """Persist the cant rotation reference immediately when changed (spec 3.3).

    "Recorded, not assumed": there is no Recalculate-button gate for this
    value (unlike the cant point table) since it has no geometry consequence
    to defer — it is a pure design-intent record, so it is written to
    Pset_SaikeiCant as soon as the dropdown changes.
    """
    import bonsai.tool as tool

    props = context.scene.CivilAlignmentProperties
    if props.active_alignment_id == 0:
        return
    ifc_file = tool.Ifc.get()
    if ifc_file is None:
        return
    try:
        alignment = ifc_file.by_id(props.active_alignment_id)
    except RuntimeError:
        return
    cant_layout = tool.Alignment.get_cant_layout(alignment)
    if cant_layout is None:
        return
    tool.Alignment.set_cant_rotation_reference(cant_layout, self.cant_rotation_reference)


def _on_active_vertical_layout_index_update(self, context):
    """Sync the PVI table from whichever row of ``vertical_layouts`` is now
    selected (spec 2.1: "selecting a row ... re-syncs the PVI table from
    THAT layout"). Lazy import mirrors the other update callbacks
    (prop.py loads before operator.py).
    """
    from . import operator as ops

    ops.sync_pvis_from_selected_vertical_layout(context.scene.CivilAlignmentProperties)


def _on_show_station_labels_update(self, context):
    """Install/uninstall the station-tick viewport decorator (spec 4.1).

    Unlike the profile view (toggled by a dedicated ``civil.
    toggle_profile_view`` operator), station ticks have no separate toggle
    operator — this BoolProperty's ``update`` callback owns the
    StationTickDecorator's install/uninstall lifecycle directly, per spec.
    Lazy import to avoid circular imports (prop.py loads before
    decorator.py).
    """
    import bonsai.tool as tool

    from . import decorator as alignment_decorator

    props = context.scene.CivilAlignmentProperties
    tick_decorator = alignment_decorator.StationTickDecorator

    if self.show_station_labels:
        tick_decorator.install(context, props.active_alignment_id, props.station_interval)
    elif tick_decorator.is_installed:
        tick_decorator.uninstall()
    tool.Blender.update_viewport()


def _on_station_interval_update(self, context):
    """Refresh a live station-tick overlay when the interval changes."""
    import bonsai.tool as tool

    from . import decorator as alignment_decorator

    tick_decorator = alignment_decorator.StationTickDecorator
    if tick_decorator.is_installed:
        tick_decorator.interval = self.station_interval
        tick_decorator.refresh()
        tool.Blender.update_viewport()


def _on_profile_exaggeration_update(self, context):
    """Push a changed exaggeration onto a live profile view immediately.

    Lazy import to avoid circular imports (prop.py loads before decorator.py).
    """
    from . import decorator as alignment_decorator

    profile_view = alignment_decorator.ProfileViewDecorator
    if profile_view.is_installed:
        profile_view.vertical_exaggeration = self.profile_exaggeration
        import bonsai.tool as tool

        tool.Blender.update_viewport()


class AlignmentPI(PropertyGroup):
    """Property group for a single PI (Point of Intersection)

    In the PI method, alignments are defined by:
    - Endpoint PIs: Start (POB) and End (POE) points
    - Interior PIs: Points where tangents intersect, optionally with curves
    """

    # Coordinates stored as global easting/northing (map coordinates).
    # Coordinate flow: Blender coords -> xyz2enh() -> global E/N (stored here)
    #                  global E/N -> ifcopenshell.util.geolocation.auto_enh2xyz() -> local IFC coords (for IfcOpenShell API)
    e: StringProperty(name="E", description="Easting (global map coordinates)", default="0.0")
    n: StringProperty(name="N", description="Northing (global map coordinates)", default="0.0")

    # PI Type
    pi_type: EnumProperty(
        name="Type",
        description="Type of PI point",
        items=[
            ("ENDPOINT", "Endpoint", "Start or end point (no curve)"),
            ("TANGENT", "Tangent", "Pass-through point (no curve)"),
            ("CURVE", "Curve", "Point of intersection with curve"),
        ],
        default="TANGENT",
    )

    # Curve parameters (only used when pi_type == "CURVE")
    radius: FloatProperty(
        name="Radius",
        description="Curve radius (0 = no curve, sharp angle)",
        default=0.0,
        min=0.0,
        precision=3,
        unit="LENGTH",
        update=_on_radius_update,
    )

    # ---- Spiral transitions (spec 1.5) ----
    # Spiral-curve-spiral (radius > 0 with either length > 0) and
    # spiral-spiral (both lengths > 0, consuming the PI's full deflection —
    # the solver decides this, not the UI) are both covered by these two
    # length fields; CIVIL_OT_set_pi_spiral is the one operation that covers
    # both cases per spec 1.5 ("spiral-curve-spiral and spiral-spiral as one
    # operation").
    spiral_mode: EnumProperty(
        name="Spiral Mode",
        description=(
            "Whether spiral transition lengths are entered directly, or via the clothoid A-value "
            "(A^2 = R * L, the classic spiral design parameter)"
        ),
        items=[
            ("LENGTH", "Length", "Enter spiral transition lengths directly"),
            ("A_VALUE", "A-Value", "Enter the clothoid A-value; length is derived as L = A^2 / R"),
        ],
        default="LENGTH",
        update=_on_spiral_mode_update,
    )

    spiral_in_length: FloatProperty(
        name="Entry Spiral (Lin)",
        description="Entry spiral transition length ahead of the curve (0 = no entry spiral)",
        default=0.0,
        min=0.0,
        precision=3,
        unit="LENGTH",
        update=_on_spiral_length_update,
    )

    spiral_out_length: FloatProperty(
        name="Exit Spiral (Lout)",
        description="Exit spiral transition length following the curve (0 = no exit spiral)",
        default=0.0,
        min=0.0,
        precision=3,
        unit="LENGTH",
        update=_on_spiral_length_update,
    )

    spiral_a_in: FloatProperty(
        name="Entry A",
        description=(
            "Clothoid A-value for the entry spiral (A^2 = R * L). Used when Spiral Mode is "
            "A-Value; editing it re-derives the entry spiral length from the current radius, and "
            "editing the radius while in A-Value mode re-derives the length from this A-value"
        ),
        default=0.0,
        min=0.0,
        precision=3,
        unit="LENGTH",
        update=_on_spiral_a_value_update,
    )

    spiral_a_out: FloatProperty(
        name="Exit A",
        description=(
            "Clothoid A-value for the exit spiral (A^2 = R * L). Used when Spiral Mode is "
            "A-Value; editing it re-derives the exit spiral length from the current radius, and "
            "editing the radius while in A-Value mode re-derives the length from this A-value"
        ),
        default=0.0,
        min=0.0,
        precision=3,
        unit="LENGTH",
        update=_on_spiral_a_value_update,
    )

    # ---- Compound / reverse curves (spec 1.6) ----
    join_next: BoolProperty(
        name="Join Next",
        description=(
            "Join this PI's curve directly to the NEXT PI's curve at a shared tangency point, with "
            "no intermediate tangent run -- a PCC (point of compound curvature) when the two curves "
            "curve the same way, a PRC (point of reverse curvature) when they curve opposite ways. "
            "Set via civil.join_curves, which validates and reverts on solver refusal"
        ),
        default=False,
    )

    # Computed/display values (updated by recalculate operator)
    length_to_next: FloatProperty(
        name="Length",
        description="Length of tangent to next PI",
        default=0.0,
        precision=3,
        unit="LENGTH",
    )

    direction_to_next: FloatProperty(
        name="Direction",
        description="Bearing/direction to next PI (degrees)",
        default=0.0,
        precision=4,
        subtype="ANGLE",
    )

    # Station at this PI (computed)
    station: FloatProperty(
        name="Station",
        description="Station value at this PI",
        default=0.0,
        precision=2,
    )


class VerticalPVI(PropertyGroup):
    """Property group for a single PVI (Point of Vertical Intersection).

    In the PVI method, vertical alignments are defined by:
    - Endpoint PVIs: Start (BOM) and End (EOM) points
    - Interior PVIs: Points where grade tangents intersect, optionally with parabolic curves
    """

    station: FloatProperty(
        name="Station",
        description="Station value at this PVI",
        default=0.0,
        precision=2,
    )

    elevation: FloatProperty(
        name="Elevation",
        description="Elevation at this PVI",
        default=0.0,
        precision=3,
        unit="LENGTH",
    )

    pvi_type: EnumProperty(
        name="Type",
        description="Type of PVI point",
        items=[
            ("ENDPOINT", "Endpoint", "Start or end point (no curve)"),
            ("INTERIOR", "Interior", "Interior PVI, optionally with vertical curve"),
        ],
        default="INTERIOR",
    )

    curve_length: FloatProperty(
        name="Curve Length",
        description="Vertical parabolic curve length (0 = no curve, sharp grade break)",
        default=0.0,
        min=0.0,
        precision=2,
        unit="LENGTH",
        update=_on_curve_length_update,
    )


class VerticalDisplayRow(PropertyGroup):
    """Property group for interleaved PVI/grade display in the vertical table.

    Creates the Civil 3D-style view:
        End (BOM) - station, elevation
          Grade segment 1 - slope %, length
        PVI 1 - station, elevation, curve length, K
          Grade segment 2 - slope %, length
        ...
        End (EOM) - station, elevation
    """

    row_type: EnumProperty(
        name="Row Type",
        items=[
            ("POINT", "Point", "A PVI point row"),
            ("SEGMENT", "Segment", "A grade segment row"),
        ],
        default="POINT",
    )

    pvi_index: IntProperty(name="PVI Index", default=0)
    display_type: StringProperty(name="Type", default="")

    # PVI point data (POINT rows)
    station: FloatProperty(name="Station", default=0.0, precision=2)
    elevation: FloatProperty(name="Elevation", default=0.0, precision=3)
    curve_length: FloatProperty(name="Curve Length", default=0.0, precision=2)
    k_value: FloatProperty(name="K Value", default=0.0, precision=1)
    # Advisory AASHTO K check (spec 2.4): flagged, never blocking.
    k_deficient: BoolProperty(name="K Deficient", default=False)
    k_required: FloatProperty(name="Required K", default=0.0, precision=1)

    # Grade segment data (SEGMENT rows)
    grade_pct: FloatProperty(name="Grade %", default=0.0, precision=3)
    length: FloatProperty(name="Length", default=0.0, precision=2)


class AlignmentDisplayRow(PropertyGroup):
    """Property group for interleaved point/segment display in the table.

    This creates the Civil 3D-style view where points and segments
    are shown on separate rows:
        Point 1 (End)
          Segment 1 (Tan)
        Point 2 (Tan)
          Segment 2 (Tan)
        ...
    """

    # Row type discriminator
    row_type: EnumProperty(
        name="Row Type",
        items=[
            ("POINT", "Point", "A PI point row"),
            ("SEGMENT", "Segment", "A segment row between points"),
        ],
        default="POINT",
    )

    # Segment number (1, 2, 3...) - only for SEGMENT rows
    segment_number: IntProperty(name="Segment #", default=0)

    # Point index in the pis collection - for both types
    # For POINT rows: the PI index
    # For SEGMENT rows: the starting PI index of this segment
    pi_index: IntProperty(name="PI Index", default=0)

    # Display type string: End, Mid, Tan, Curve for the original rows; plus,
    # per spec 1.5/1.6, "Spiral" (a TS-Spiral/CS-Spiral row -- length column
    # is the spiral length, radius column shows the A-value) and "PCC"/"PRC"
    # (a join_next junction marker row replacing the intermediate Tan row).
    display_type: StringProperty(name="Type", default="")

    # Point coordinates (only for POINT rows)
    e: StringProperty(name="E", default="0.0")
    n: StringProperty(name="N", default="0.0")

    # Segment properties (only for SEGMENT rows). On a "Spiral" row, radius
    # holds the A-value (not the PI's curve radius); on a "PCC"/"PRC" row
    # length/radius are unused (0.0).
    length: FloatProperty(name="Length", default=0.0, precision=2, unit="LENGTH")
    radius: FloatProperty(name="Radius", default=0.0, precision=2, unit="LENGTH")
    arc_length: FloatProperty(name="Arc Length", default=0.0, precision=2, unit="LENGTH")

    # Key-point station (spec 1.5): the station of the TS/SC/CS/ST/PCC/PRC
    # point this row starts at, matched post-commit from the alignment's
    # POSITION referents (civil.refresh_referent_list / get_referents).
    # has_station is False pre-commit (or if the referent could not be
    # matched), in which case the row simply shows no station.
    station: FloatProperty(name="Station", default=0.0, precision=2)
    has_station: BoolProperty(name="Has Station", default=False)


CANT_TRANSITION_TYPE_ITEMS = [
    ("CONSTANTCANT", "Constant", "Holds the cant flat at this point's value (no transition)"),
    ("LINEARTRANSITION", "Linear", "Straight-line ramp between this point's value and the next"),
    ("HELMERTCURVE", "Helmert", "Two-parabola transition; zero slope at both ends, continuous slope at midpoint"),
    ("BLOSSCURVE", "Bloss", "Cubic S-curve transition; zero slope and zero curvature at both ends"),
    ("COSINECURVE", "Cosine", "Half-cosine transition; zero slope at both ends"),
    ("SINECURVE", "Sine", "Sine-wave transition; zero slope and zero curvature at both ends"),
    ("VIENNESEBEND", "Viennese Bend", "7th-order polynomial spiral transition (approximated as Bloss for display)"),
]


class CivilCantPointProperties(PropertyGroup):
    """Property group for a single cant point (spec 3.2).

    Cant points mark STATIONS where cant VALUES (the left/right rail
    heights relative to the reference plane) are defined. Consecutive points
    make up SEGMENTS: the segment length is the station delta between them,
    and each point's ``transition_type`` describes the shape of the segment
    that carries ITS value INTO THE NEXT point's value (i.e.
    ``transition_type`` on the LAST point is unused — there is no segment
    leaving it). This is the same convention used by
    ``tool.Alignment.write_cant_segments`` and ``sample_cant_profile``.
    """

    station: FloatProperty(
        name="Station",
        description="Station value at this cant point (distance along the horizontal alignment)",
        default=0.0,
        precision=2,
    )

    cant_left: FloatProperty(
        name="Cant L",
        description="Left rail height at this station, relative to the reference plane",
        default=0.0,
        precision=4,
        unit="LENGTH",
        update=_on_cant_value_update,
    )

    cant_right: FloatProperty(
        name="Cant R",
        description="Right rail height at this station, relative to the reference plane",
        default=0.0,
        precision=4,
        unit="LENGTH",
        update=_on_cant_value_update,
    )

    transition_type: EnumProperty(
        name="Transition",
        description=(
            "Shape of the segment carrying this point's cant value into the NEXT point's value "
            "(unused on the last point, which has no outgoing segment)"
        ),
        items=CANT_TRANSITION_TYPE_ITEMS,
        default="LINEARTRANSITION",
        update=_on_cant_value_update,
    )

    design_speed: FloatProperty(
        name="Design Speed",
        description=(
            "Design speed for the equilibrium-cant check at this point — mph in imperial "
            "projects, km/h in metric projects. 0 inherits the alignment-level Design Speed"
        ),
        default=0.0,
        min=0.0,
        soft_max=200.0,
        update=_on_cant_value_update,
    )


class CantDisplayRow(PropertyGroup):
    """Property group for the interleaved cant point / computed-checks table
    (spec 3.2) — mirrors ``AlignmentDisplayRow`` / ``VerticalDisplayRow``'s
    POINT/SEGMENT interleaving:

        Point 1  (station, cant L/R, transition — editable)
          Computed  (E_eq, deficiency, excess, gradient, twist for the
                     segment leaving Point 1)
        Point 2
          Computed
        ...
        Point N  (no Computed row — no outgoing segment)
    """

    row_type: EnumProperty(
        name="Row Type",
        items=[
            ("POINT", "Point", "A cant point row"),
            ("COMPUTED", "Computed", "Computed checks for the segment leaving this point"),
        ],
        default="POINT",
    )

    point_index: IntProperty(name="Point Index", default=0)

    radius: FloatProperty(name="Radius", default=0.0, precision=2)
    applied_left: FloatProperty(name="Applied L", default=0.0, precision=4)
    applied_right: FloatProperty(name="Applied R", default=0.0, precision=4)
    applied: FloatProperty(name="Applied", default=0.0, precision=4)
    equilibrium: FloatProperty(name="E_eq", default=0.0, precision=4)
    deficiency: FloatProperty(name="Deficiency", default=0.0, precision=4)
    excess: FloatProperty(name="Excess", default=0.0, precision=4)
    gradient: FloatProperty(name="Gradient", default=0.0, precision=3)
    twist_per_length: FloatProperty(name="Twist Rate", default=0.0, precision=3)
    twist_per_time: FloatProperty(name="Twist (mm/s)", default=0.0, precision=2)

    # Comma-separated limit names from EN13803_DEFAULT_LIMITS (or the user's
    # overrides) that this segment violates — empty string when compliant.
    violations: StringProperty(name="Violations", default="")


class CivilReferentItem(PropertyGroup):
    """Read-only mirror of one IfcReferent nested on the active alignment
    (spec 4.2) — populated by ``operator.refresh_referent_list()``, never
    edited in-place; changes go through the Add/Remove referent operators
    followed by a fresh sync.
    """

    referent_id: IntProperty(name="Referent ID", description="IFC entity id of the referent", default=0)
    referent_name: StringProperty(name="Name", default="")
    predefined_type: StringProperty(
        name="Type",
        description="IfcReferentTypeEnum value (STATION, POSITION, SUPERELEVATIONEVENT, WIDTHEVENT, ...)",
        default="",
    )
    station: FloatProperty(name="Station", default=0.0, precision=2)
    has_station: BoolProperty(
        name="Has Station", description="Whether Pset_Stationing.Station could be resolved", default=False
    )
    is_equation: BoolProperty(
        name="Is Station Equation", description="Whether Pset_Stationing.IncomingStation is set", default=False
    )
    incoming_station: FloatProperty(
        name="Incoming Station", description="Meaningful only when is_equation is True", default=0.0, precision=2
    )


class CivilVerticalLayoutItem(PropertyGroup):
    """Read-only mirror of one IfcAlignmentVertical associated with the
    active alignment (spec 2.1) -- the parent's own directly-nested
    vertical (if any) plus one per aggregated child alignment (CT
    4.1.4.4.1.2's design alternatives). Populated by
    ``operator.refresh_vertical_list()``; selecting a row in
    ``CIVIL_UL_vertical_layouts`` re-syncs the PVI table from that layout
    via ``active_vertical_layout_index``'s update callback.
    """

    layout_id: IntProperty(name="Layout ID", description="IFC entity id of the IfcAlignmentVertical", default=0)
    owning_alignment_id: IntProperty(
        name="Owning Alignment ID",
        description=(
            "IFC entity id of the IfcAlignment this layout is nested under -- the active alignment "
            "itself when only one vertical exists, or an aggregated child once a second is added"
        ),
        default=0,
    )
    display_name: StringProperty(name="Name", default="")
    is_alternative: BoolProperty(
        name="Is Alternative",
        description=(
            "Position-based label: False for the first row returned by tool.Alignment."
            "get_vertical_layouts() (whichever the alignment API's own aggregation bookkeeping "
            "surfaces first), True for every other row. Not a claim about creation order -- once a "
            "second vertical exists, both live on aggregated children and IFC itself does not "
            "record which one was added first"
        ),
        default=False,
    )


class CivilAlignmentProperties(PropertyGroup):
    """Properties for the alignment module"""

    # Active alignment selection
    active_alignment_id: IntProperty(
        name="Active Alignment ID",
        description="IFC entity ID of the active alignment",
        default=0,
    )

    active_alignment_name: StringProperty(
        name="Active Alignment",
        description="Name of the currently active alignment",
        default="",
    )

    # New alignment creation properties
    new_alignment_name: StringProperty(
        name="Name",
        description="Name for new alignment",
        default="Alignment 1",
    )

    start_station: FloatProperty(
        name="Start Station",
        description="Starting station value (e.g., 10000 for 100+00)",
        default=10000.0,
        min=0.0,
    )

    # PI collection for PI method creation
    pis: CollectionProperty(type=AlignmentPI)
    active_pi_index: IntProperty(name="Active PI", default=0)

    # Combined point/segment display rows (for Civil 3D-style table)
    display_rows: CollectionProperty(type=AlignmentDisplayRow)
    active_display_row_index: IntProperty(name="Active Display Row", default=0)

    # PI Edit Mode state (for moving PIs with G key)
    is_pi_edit_mode: BoolProperty(
        name="PI Edit Mode Active",
        description="Whether PI edit mode is currently active",
        default=False,
    )

    pi_edit_alignment_id: IntProperty(
        name="Editing Alignment ID",
        description="IFC ID of alignment being edited in PI edit mode",
        default=0,
    )

    # Vertical PVI collection for PVI method creation
    vertical_pvis: CollectionProperty(type=VerticalPVI)
    active_pvi_index: IntProperty(name="Active PVI", default=0)

    # Vertical display rows (interleaved PVI/grade view)
    vertical_display_rows: CollectionProperty(type=VerticalDisplayRow)
    active_vertical_display_row_index: IntProperty(name="Active Vertical Display Row", default=0)

    # PVI Edit Mode state (for moving PVIs with G key)
    is_pvi_edit_mode: BoolProperty(
        name="PVI Edit Mode Active",
        description="Whether PVI edit mode is currently active",
        default=False,
    )

    pvi_edit_alignment_id: IntProperty(
        name="Editing Alignment ID (Vertical)",
        description="IFC ID of alignment being edited in PVI edit mode",
        default=0,
    )

    pvi_edit_vertical_layout_id: IntProperty(
        name="Editing Vertical Layout ID",
        description=(
            "IFC ID of the specific IfcAlignmentVertical being edited in PVI edit mode (spec 2.1) -- "
            "0 means the alignment's own/default vertical"
        ),
        default=0,
    )

    # ---- Multi-Vertical Selector (spec 2.1) ----
    vertical_layouts: CollectionProperty(type=CivilVerticalLayoutItem)
    active_vertical_layout_index: IntProperty(
        name="Active Vertical Layout",
        default=0,
        update=_on_active_vertical_layout_index_update,
    )
    active_vertical_layout_id: IntProperty(
        name="Active Vertical Layout ID",
        description="IFC entity id of the IfcAlignmentVertical the PVI table currently reads from/writes to",
        default=0,
    )

    # Display options
    show_station_labels: BoolProperty(
        name="Show Station Labels",
        description=(
            "Show station tick marks and labels along the active alignment "
            "(spec 4.1). Requires the geometry engine to place ticks — see "
            "the warning in the Stationing panel if none appear"
        ),
        default=True,
        update=_on_show_station_labels_update,
    )

    station_interval: FloatProperty(
        name="Station Interval",
        description="Interval between station markers",
        default=100.0,
        min=1.0,
        unit="LENGTH",
        update=_on_station_interval_update,
    )

    # ---- Referents (spec Section 4.2) ----
    referents: CollectionProperty(type=CivilReferentItem)
    active_referent_index: IntProperty(name="Active Referent", default=0)

    # ---- Profile View (D2) ----
    profile_terrain: bpy.props.PointerProperty(
        name="Terrain",
        description="Existing-ground mesh sampled for the profile view",
        type=bpy.types.Object,
        poll=_terrain_object_poll,
    )

    show_profile_view: BoolProperty(
        name="Show Profile View",
        description="Draw the 2D station-vs-elevation profile overlay in the 3D viewport",
        default=False,
    )

    profile_view_interval: FloatProperty(
        name="Sample Interval",
        description="Station spacing for sampling the design and terrain profiles",
        default=10.0,
        min=0.1,
        unit="LENGTH",
    )

    profile_view_height: IntProperty(
        name="Profile Height",
        description="Height of the profile overlay in pixels",
        default=260,
        min=120,
        max=900,
    )

    design_speed: FloatProperty(
        name="Design Speed",
        description=(
            "Design speed for advisory checks — mph in imperial projects, "
            "km/h in metric projects. 0 disables checking. Vertical curves "
            "shorter than the AASHTO stopping-sight-distance K require are "
            "flagged in the PVI table, never blocked"
        ),
        default=0.0,
        min=0.0,
        soft_max=120.0,
        update=_on_design_speed_update,
    )

    profile_exaggeration: FloatProperty(
        name="Vertical Exaggeration",
        description=(
            "Vertical scale of the profile view relative to its horizontal "
            "scale, like a profile sheet's exaggeration. 0 = auto-fit the "
            "elevation range to the panel"
        ),
        default=0.0,
        min=0.0,
        soft_max=20.0,
        update=_on_profile_exaggeration_update,
    )

    # ---- Cant (spec Section 3) ----
    cant_points: CollectionProperty(type=CivilCantPointProperties)
    active_cant_point_index: IntProperty(name="Active Cant Point", default=0)

    cant_display_rows: CollectionProperty(type=CantDisplayRow)
    active_cant_display_row_index: IntProperty(name="Active Cant Display Row", default=0)

    track_gauge: FloatProperty(
        name="Track Gauge",
        description=(
            "Rail gauge used for the equilibrium cant / deficiency / excess checks "
            "(EN 13803 standard gauge = 1.435 m)"
        ),
        default=1.435,
        min=0.0,
        precision=4,
        unit="LENGTH",
        update=_on_cant_value_update,
    )

    show_cant_limits: BoolProperty(
        name="Show Cant Limits",
        description="Expand/collapse the EN 13803 limit-override box in the Cant Editor panel",
        default=False,
    )

    cant_rotation_reference: EnumProperty(
        name="Rotation Reference",
        description=(
            "Which rail the cant rotation is measured about — recorded for design intent "
            "and save/reopen round-trip (Pset_SaikeiCant.RotationReference); no geometry "
            "consequence yet, the geometric representation always applies cant per "
            "RailHeadDistance exactly as authored"
        ),
        items=[
            ("LOW_RAIL", "Low Rail", "Cant rotation measured about the low (inner) rail"),
            ("CENTERLINE", "Centerline", "Cant rotation measured about the track centerline"),
            ("HIGH_RAIL", "High Rail", "Cant rotation measured about the high (outer) rail"),
        ],
        default="LOW_RAIL",
        update=_on_cant_rotation_reference_update,
    )

    # EN 13803-1:2017 plain-line normal-limit defaults (metres / dimensionless
    # ratios — see tool.Alignment.EN13803_DEFAULT_LIMITS, the source of truth
    # these mirror; PropertyGroup defaults must be literals so they cannot
    # simply reference that dict at class-definition time). Advisory only,
    # user-overridable.
    cant_limit_max_applied: FloatProperty(
        name="Max Applied Cant",
        description="EN 13803 plain-line normal limit: 160 mm",
        default=0.160,
        min=0.0,
        precision=4,
        unit="LENGTH",
    )
    cant_limit_max_deficiency: FloatProperty(
        name="Max Deficiency",
        description="EN 13803 plain-line normal limit: 153 mm",
        default=0.153,
        min=0.0,
        precision=4,
        unit="LENGTH",
    )
    cant_limit_max_excess: FloatProperty(
        name="Max Excess",
        description="EN 13803 plain-line normal limit: 110 mm",
        default=0.110,
        min=0.0,
        precision=4,
        unit="LENGTH",
    )
    cant_limit_max_gradient: FloatProperty(
        name="Max Cant Gradient",
        description="EN 13803 plain-line normal limit: 2.25 mm/m, stored as a dimensionless ratio (m/m)",
        default=0.00225,
        min=0.0,
        precision=6,
    )
    cant_limit_max_twist: FloatProperty(
        name="Max Twist",
        description="EN 13803 plain-line normal limit: 3 mm/m, stored as a dimensionless ratio (m/m)",
        default=0.003,
        min=0.0,
        precision=6,
    )

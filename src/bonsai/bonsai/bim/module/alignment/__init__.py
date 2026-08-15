# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2020, 2021 Dion Moult <dion@thinkmoult.com>, 2026 Michael Yoder <myoder@desertspringscivil.com>
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

import bpy
import ifcopenshell.api.alignment as align_api
from bpy.app.handlers import persistent
from . import ui, prop, operator, decorator, workspace

# =============================================================================
# Referent naming callback (spec 4.2/4.4) — module-global, registered at
# addon register() / cleared at unregister()
# =============================================================================
# ifcopenshell.api.alignment.update_key_point_referents's built-in label
# tables return "xx" for direct spiral-to-spiral transitions (horizontal —
# a transition curve immediately following another transition curve, with
# no arc or line between them) and for EVERY cant-segment transition (no
# built-in cant labeling exists yet at all). register_referent_name_callback
# lets a caller override the default per-type labeling entirely (there is no
# partial-override mechanism — a registered callback must handle every
# transition combination for that layout type, including the ones the
# built-in table already labels correctly, plus the begin-of-alignment /
# end-of-alignment cases). See ifcopenshell.api.alignment.
# _get_segment_start_point_label for the exact contract and the built-in
# tables these two functions replicate + extend.

# Transition-curve DesignParameters.PredefinedType values shared by every
# horizontal spiral kind (IFC4X3 IfcAlignmentHorizontalSegmentTypeEnum).
_HORIZONTAL_TRANSITION_TYPES = frozenset(
    {"BLOSSCURVE", "CLOTHOID", "COSINECURVE", "CUBIC", "HELMERTCURVE", "SINECURVE", "VIENNESEBEND"}
)

# Cant-segment DesignParameters.PredefinedType values that are NOT the flat
# "no change" CONSTANTCANT segment (IFC4X3 IfcAlignmentCantSegmentTypeEnum).
_CANT_TRANSITION_TYPES = frozenset(
    {"BLOSSCURVE", "COSINECURVE", "HELMERTCURVE", "LINEARTRANSITION", "SINECURVE", "VIENNESEBEND"}
)


def _horizontal_referent_label(prev_segment, segment) -> str:
    """Fills the built-in horizontal label table's only gap: a direct
    spiral-to-spiral transition (compound spiral, no arc or line between
    the two spirals) is labeled "S.S." (Spiral to Spiral). Every other
    combination reproduces the built-in table exactly — see
    ifcopenshell.api.alignment._get_segment_start_point_label's
    _horizontal_label for the reference this mirrors.
    """
    if prev_segment is None and segment is not None:
        return "P.O.B."
    if prev_segment is not None and segment is None:
        return "P.O.E."

    prev_type = prev_segment.DesignParameters.PredefinedType
    next_type = segment.DesignParameters.PredefinedType

    if prev_type in _HORIZONTAL_TRANSITION_TYPES and next_type in _HORIZONTAL_TRANSITION_TYPES:
        return "S.S."
    if prev_type == "LINE" and next_type == "LINE":
        return "P.I."
    if prev_type == "LINE" and next_type == "CIRCULARARC":
        return "P.C."
    if prev_type == "CIRCULARARC" and next_type == "LINE":
        return "P.T."
    if prev_type == "CIRCULARARC" and next_type == "CIRCULARARC":
        return "P.C.C."
    if prev_type == "LINE" and next_type in _HORIZONTAL_TRANSITION_TYPES:
        return "T.S."
    if prev_type in _HORIZONTAL_TRANSITION_TYPES and next_type == "LINE":
        return "S.T."
    if prev_type == "CIRCULARARC" and next_type in _HORIZONTAL_TRANSITION_TYPES:
        return "C.S."
    if prev_type in _HORIZONTAL_TRANSITION_TYPES and next_type == "CIRCULARARC":
        return "S.C."
    return "xx"  # Unreached for any valid IfcAlignmentHorizontalSegmentTypeEnum pair.


def _cant_referent_label(prev_segment, segment) -> str:
    """Fills every "xx" in the built-in cant label table — no built-in cant
    labeling exists at all (unlike horizontal/vertical). Saikei surveyor
    labels, chosen for this project (there is no established convention to
    mirror the way there is for P.C./P.T./etc.), C-prefixed to read as
    "cant" analogues of the horizontal/vertical key-point labels:

    - "C.P.O.B." / "C.P.O.E." — begin/end of the cant layout (matches the
      built-in table's own choice for these two cases).
    - "B.C.T." (Begin Cant Transition) — CONSTANTCANT into a transition:
      the point cant starts ramping away from a held value.
    - "E.C.T." (End Cant Transition) — a transition back into CONSTANTCANT:
      the point cant finishes ramping and holds again.
    - "C.T.P." (Cant Transition Point) — one transition curve directly into
      another (compound cant transition, the cant analogue of "S.S.").
    - "C.P.I." (Cant Point of Intersection) — CONSTANTCANT directly into
      another CONSTANTCANT: a kink between two flat cant sections with no
      ramp between them (the cant analogue of "P.I.").
    """
    if prev_segment is None and segment is not None:
        return "C.P.O.B."
    if prev_segment is not None and segment is None:
        return "C.P.O.E."

    prev_type = prev_segment.DesignParameters.PredefinedType
    next_type = segment.DesignParameters.PredefinedType

    if prev_type == "CONSTANTCANT" and next_type == "CONSTANTCANT":
        return "C.P.I."
    if prev_type == "CONSTANTCANT" and next_type in _CANT_TRANSITION_TYPES:
        return "B.C.T."
    if prev_type in _CANT_TRANSITION_TYPES and next_type == "CONSTANTCANT":
        return "E.C.T."
    return "C.T.P."  # both sides are transitions — compound cant transition.


classes = (
    # Property groups (must be registered before classes that use them)
    prop.AlignmentPI,
    prop.AlignmentDisplayRow,
    prop.VerticalPVI,
    prop.VerticalDisplayRow,
    prop.CivilCantPointProperties,
    prop.CantDisplayRow,
    prop.CivilReferentItem,
    prop.CivilAlignmentProperties,
    # UILists
    ui.CIVIL_UL_alignment_pis,
    ui.CIVIL_UL_vertical_pvis,
    ui.CIVIL_UL_cant_points,
    ui.CIVIL_UL_referents,
    operator.ImportAlignmentCSV,
    # Operators - PI Management
    operator.CIVIL_OT_add_pi,
    operator.CIVIL_OT_remove_pi,
    operator.CIVIL_OT_pick_pi_from_viewport,
    operator.CIVIL_OT_recalculate_pis,
    operator.CIVIL_OT_clear_pis,
    operator.CIVIL_OT_delete_alignment,
    # Operators - Spiral Transitions & Compound/Reverse Curves (spec 1.5, 1.6)
    operator.CIVIL_OT_set_pi_spiral,
    operator.CIVIL_OT_join_curves,
    operator.CIVIL_OT_unjoin_curves,
    # Operators - Creation
    operator.CIVIL_OT_create_alignment_by_pis,
    operator.CIVIL_OT_create_alignment_by_pi,
    # Operators - Stationing (spec Section 4)
    operator.CIVIL_OT_add_stationing_referent,
    operator.CIVIL_OT_add_station_equation,
    operator.CIVIL_OT_add_event_referent,
    operator.CIVIL_OT_remove_referent,
    operator.CIVIL_OT_refresh_referent_list,
    operator.CIVIL_OT_name_segments,
    # Operators - PI Edit Mode
    operator.CIVIL_OT_set_pi_curve_radius,
    operator.CIVIL_OT_enter_pi_edit_mode,
    # Operators - Vertical PVI Management
    operator.CIVIL_OT_add_vertical_to_alignment,
    operator.CIVIL_OT_add_pvi,
    operator.CIVIL_OT_remove_pvi,
    operator.CIVIL_OT_recalculate_pvis,
    operator.CIVIL_OT_clear_pvis,
    operator.CIVIL_OT_delete_vertical_layout,
    # Operators - PVI Edit Mode
    operator.CIVIL_OT_enter_pvi_edit_mode,
    # Operators - 3D Combination (D3)
    operator.CIVIL_OT_visualize_3d_alignment,
    # Operators - Profile View (D2)
    operator.CIVIL_OT_toggle_profile_view,
    operator.CIVIL_OT_refresh_profile_view,
    operator.CIVIL_OT_edit_pvi_in_profile,
    # Operators - Cant (spec Section 3)
    operator.CIVIL_OT_add_cant_to_alignment,
    operator.CIVIL_OT_add_cant_point,
    operator.CIVIL_OT_remove_cant_point,
    operator.CIVIL_OT_recalculate_cant,
    operator.CIVIL_OT_clear_cant_points,
    operator.CIVIL_OT_delete_cant_layout,
    # UI Panels (appear in Properties sidebar under CIVIL tab)
    ui.CIVIL_PT_alignment_creation,
    ui.CIVIL_PT_pi_editor,
    ui.CIVIL_PT_vertical_creation,
    ui.CIVIL_PT_pvi_editor,
    ui.CIVIL_PT_profile_view,
    ui.CIVIL_PT_alignment_stationing,
    ui.CIVIL_PT_cant_editor,
)


def menu_func_import(self, context):
    self.layout.operator(operator.ImportAlignmentCSV.bl_idname, text="Alignment (.csv)")


def register():
    if not bpy.app.background:
        bpy.utils.register_tool(
            workspace.AlignmentTool,
            separator=True,
            group=False,
        )
    bpy.types.Scene.CivilAlignmentProperties = bpy.props.PointerProperty(type=prop.CivilAlignmentProperties)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    # Saikei's surveyor labels for the referent-naming gaps (spec 4.2/4.4) —
    # see _horizontal_referent_label / _cant_referent_label above. Vertical
    # is left at its built-in default (its own "xx" gaps, for CIRCULARARC /
    # CLOTHOID vertical curve types, are out of scope for this pass).
    align_api.register_referent_name_callback(horizontal=_horizontal_referent_label, cant=_cant_referent_label)


def unregister():
    if not bpy.app.background:
        bpy.utils.unregister_tool(workspace.AlignmentTool)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    del bpy.types.Scene.CivilAlignmentProperties
    # ifcopenshell.api.alignment offers no "unregister" for the naming
    # callback beyond re-registering None (its own documented reset path —
    # see register_referent_name_callback's docstring) — this is a
    # module-global in the ifcopenshell.api.alignment package, so clear it
    # explicitly rather than leaving Saikei's labels active after unregister.
    align_api.register_referent_name_callback(horizontal=None, vertical=None, cant=None)

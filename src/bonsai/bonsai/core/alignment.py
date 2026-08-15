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


"""Core alignment business logic - Orchestration only, NO bpy imports.

This module contains alignment-related business logic and workflow
orchestration. All calculations, algorithms, and IFC operations are
in the tool layer. Functions receive tool classes as parameters
following Bonsai's dependency injection pattern.

NOTE: Math, calculations, algorithms, and IFC API calls belong in
tool/alignment.py. This module only handles:
- Business rules and validation
- Workflow orchestration (calling tool methods in sequence)
- Decision-making about what should happen
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import ifcopenshell
    from .. import tool


# =============================================================================
# Alignment Creation
# =============================================================================


def create_alignment(
    ifc_tool: "type[tool.Ifc]",
    alignment_tool: "type[tool.Alignment]",
    name: str,
    start_station: float = 0.0,
) -> "ifcopenshell.entity_instance":
    """Create a new alignment with full IFC structure.

    Business rules:
    1. An IFC file must be loaded
    2. Name must not be empty
    3. Delegates to tool layer for IFC creation and Blender hierarchy

    Args:
        ifc_tool: The IFC tool class
        alignment_tool: The Alignment tool class
        name: The alignment name
        start_station: Starting station value

    Returns:
        The created IfcAlignment entity

    Raises:
        ValueError: If no IFC file is loaded or name is empty
    """
    if ifc_tool.get() is None:
        raise ValueError("No IFC file loaded")

    if not name or not name.strip():
        raise ValueError("Alignment name cannot be empty")

    return alignment_tool.create_alignment(name.strip(), start_station)


# =============================================================================
# PI Edit Mode Functions
# =============================================================================


def enter_pi_edit_mode(
    ifc_tool: "type[tool.Ifc]",
    alignment_tool: "type[tool.Alignment]",
    alignment_id: int,
) -> list:
    """Enter PI edit mode for an alignment.

    Business logic for entering PI edit mode:
    1. Validates that the alignment exists
    2. Validates that the alignment has a horizontal layout with real segments
    3. Back-calculates PI positions from segments
    4. Creates temporary EMPTY objects at each PI location

    Args:
        ifc_tool: The IFC tool class
        alignment_tool: The Alignment tool class
        alignment_id: The IFC ID of the alignment to edit

    Returns:
        List of created PI EMPTY objects

    Raises:
        ValueError: If alignment doesn't exist, has no horizontal layout,
                   or has no real segments
    """
    # Validate alignment exists
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")

    try:
        alignment = ifc_file.by_id(alignment_id)
    except RuntimeError:
        raise ValueError(f"Alignment with ID {alignment_id} not found")

    if not alignment.is_a("IfcAlignment"):
        raise ValueError(f"Entity {alignment_id} is not an IfcAlignment")

    # Validate alignment has horizontal layout (delegated to tool)
    h_layout = alignment_tool.get_horizontal_layout(alignment)
    if h_layout is None:
        raise ValueError(f"Alignment '{alignment.Name}' has no horizontal layout")

    # Validate layout has real segments (not just zero-length terminator)
    if not alignment_tool.layout_has_real_segments(h_layout):
        raise ValueError(f"Alignment '{alignment.Name}' has no editable segments")

    # Back-calculate PI positions from segments
    pis = alignment_tool.back_calculate_pis_from_alignment(alignment)

    if len(pis) < 2:
        raise ValueError(f"Alignment '{alignment.Name}' must have at least 2 PIs")

    # Create temporary EMPTY objects at each PI location
    empties = alignment_tool.create_pi_edit_empties(alignment, pis)

    return empties


def import_alignment_csv(
    ifc_tool: "type[tool.Ifc]",
    alignment_tool: "type[tool.Alignment]",
    filepath: str,
):
    """Import alignment(s) from a CSV file and build their viewport objects.

    Business rules:
    1. An IFC file must be loaded
    2. The CSV may carry one horizontal row plus any number of vertical rows;
       extra verticals arrive as aggregated child alignments and each child
       gets its own viewport hierarchy
    3. Referents generated by the import are materialized as empties

    Args:
        ifc_tool: The IFC tool class
        alignment_tool: The Alignment tool class
        filepath: Path to the CSV file

    Returns:
        The imported (parent) IfcAlignment entity

    Raises:
        ValueError: If no IFC file is loaded
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")

    alignment = alignment_tool.create_alignment_from_csv(filepath)

    alignment_tool.create_hierarchy_for_alignment(alignment)
    for child in alignment_tool.get_child_alignments(alignment):
        alignment_tool.create_hierarchy_for_alignment(child)
    alignment_tool.create_objects_for_referents(alignment)

    return alignment


def add_vertical_to_alignment(
    ifc_tool: "type[tool.Ifc]",
    alignment_tool: "type[tool.Alignment]",
    alignment_id: int,
):
    """Add a vertical layout to an existing horizontal alignment.

    Business rules:
    1. Alignment must exist and be an IfcAlignment
    2. Alignment must not already have a vertical layout
    3. Horizontal layout must exist (vertical requires horizontal)

    Args:
        ifc_tool: The IFC tool class
        alignment_tool: The Alignment tool class
        alignment_id: The IFC ID of the alignment

    Returns:
        The newly created IfcAlignmentVertical entity

    Raises:
        ValueError: If alignment doesn't exist, is wrong type, already has
                   a vertical layout, or has no horizontal layout
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")

    try:
        alignment = ifc_file.by_id(alignment_id)
    except RuntimeError:
        raise ValueError(f"Alignment with ID {alignment_id} not found")

    if not alignment.is_a("IfcAlignment"):
        raise ValueError(f"Entity {alignment_id} is not an IfcAlignment")

    if alignment_tool.get_horizontal_layout(alignment) is None:
        raise ValueError(f"Alignment '{alignment.Name}' has no horizontal layout — add horizontal first")

    if alignment_tool.get_vertical_layout(alignment) is not None:
        raise ValueError(f"Alignment '{alignment.Name}' already has a vertical layout")

    return alignment_tool.add_vertical_layout(alignment)


def add_alternative_vertical(
    ifc_tool: "type[tool.Ifc]",
    alignment_tool: "type[tool.Alignment]",
    alignment_id: int,
):
    """Add a SECOND (or subsequent) vertical layout as a design alternative
    (spec 2.1) — a distinct action from ``add_vertical_to_alignment``: an
    existing vertical design is never silently replaced. Deliberately does
    NOT carry that function's "already has a vertical layout" refusal —
    that is precisely the case this function exists to allow.

    Business rules:
    1. Alignment must exist and be an IfcAlignment
    2. Horizontal layout must still be required (vertical, alternative or
       not, always needs a horizontal to ride on)

    Args:
        ifc_tool: The IFC tool class
        alignment_tool: The Alignment tool class
        alignment_id: The IFC ID of the alignment

    Returns:
        The newly created IfcAlignmentVertical entity

    Raises:
        ValueError: If alignment doesn't exist, is wrong type, or has no
                   horizontal layout
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")

    try:
        alignment = ifc_file.by_id(alignment_id)
    except RuntimeError:
        raise ValueError(f"Alignment with ID {alignment_id} not found")

    if not alignment.is_a("IfcAlignment"):
        raise ValueError(f"Entity {alignment_id} is not an IfcAlignment")

    if alignment_tool.get_horizontal_layout(alignment) is None:
        raise ValueError(f"Alignment '{alignment.Name}' has no horizontal layout — add horizontal first")

    return alignment_tool.add_alternative_vertical(alignment)


def _resolve_vertical_layout(
    ifc_tool: "type[tool.Ifc]",
    alignment_tool: "type[tool.Alignment]",
    alignment: "ifcopenshell.entity_instance",
    vertical_layout_id: "Optional[int]",
):
    """Resolve which IfcAlignmentVertical an operation should target
    (spec 2.1's multi-vertical selector).

    ``vertical_layout_id`` is None for the common single-vertical case (or
    a caller that hasn't opted into the selector yet): falls back to
    ``alignment_tool.get_vertical_layout`` (the vertical nested directly on
    ``alignment``), preserving the original single-vertical behavior.

    When given, ``vertical_layout_id`` must resolve to one of
    ``alignment_tool.get_vertical_layouts(alignment)`` (the parent's own
    vertical plus one per aggregated design-alternative child) -- refuses
    an id that doesn't belong to this alignment at all, rather than
    silently operating on an unrelated entity.

    Raises:
        ValueError: If ``vertical_layout_id`` doesn't resolve to an entity,
            or resolves to one that isn't one of ``alignment``'s own
            vertical layouts.
    """
    if vertical_layout_id is None:
        return alignment_tool.get_vertical_layout(alignment)

    ifc_file = ifc_tool.get()
    try:
        candidate = ifc_file.by_id(vertical_layout_id)
    except RuntimeError:
        raise ValueError(f"Vertical layout with ID {vertical_layout_id} not found")

    if candidate not in alignment_tool.get_vertical_layouts(alignment):
        raise ValueError(f"Vertical layout #{vertical_layout_id} does not belong to alignment '{alignment.Name}'")

    return candidate


def enter_pvi_edit_mode(
    ifc_tool: "type[tool.Ifc]",
    alignment_tool: "type[tool.Alignment]",
    alignment_id: int,
    vertical_layout_id: "Optional[int]" = None,
) -> list:
    """Enter PVI edit mode for vertical alignment.

    Business logic:
    1. Validates that the alignment exists and has a vertical layout
    2. Resolves WHICH vertical layout to edit (spec 2.1's selector) --
       ``vertical_layout_id`` (the row currently active in the vertical
       layout list), or the parent's own vertical when None
    3. Validates that the vertical layout has real (non-terminator) segments
    4. Back-calculates PVI positions from existing segments
    5. Creates temporary EMPTY objects at each PVI location in profile space

    Args:
        ifc_tool: The IFC tool class
        alignment_tool: The Alignment tool class
        alignment_id: The IFC ID of the alignment to edit
        vertical_layout_id: IFC ID of the specific IfcAlignmentVertical to
            edit (spec 2.1), or None for the parent's own vertical (default,
            unchanged single-vertical behavior)

    Returns:
        List of created PVI EMPTY objects

    Raises:
        ValueError: If validation fails
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")

    try:
        alignment = ifc_file.by_id(alignment_id)
    except RuntimeError:
        raise ValueError(f"Alignment with ID {alignment_id} not found")

    if not alignment.is_a("IfcAlignment"):
        raise ValueError(f"Entity {alignment_id} is not an IfcAlignment")

    v_layout = _resolve_vertical_layout(ifc_tool, alignment_tool, alignment, vertical_layout_id)
    if v_layout is None:
        raise ValueError(f"Alignment '{alignment.Name}' has no vertical layout")

    if not alignment_tool.layout_has_real_segments(v_layout):
        raise ValueError(f"Alignment '{alignment.Name}' has no editable vertical segments")

    pvis = alignment_tool.back_calculate_pvis_from_vertical(alignment, vertical_layout=v_layout)

    if len(pvis) < 2:
        raise ValueError(f"Alignment '{alignment.Name}' must have at least 2 PVIs")

    return alignment_tool.create_pvi_edit_empties(alignment, pvis)


def exit_pvi_edit_mode(
    ifc_tool: "type[tool.Ifc]",
    alignment_tool: "type[tool.Alignment]",
    alignment_id: int,
    apply: bool,
    vertical_layout_id: "Optional[int]" = None,
) -> bool:
    """Exit PVI edit mode for vertical alignment.

    Business logic:
    1. If apply=True:
       - Collect new PVI positions from empties
       - Validate the new configuration
       - Resolve WHICH vertical layout to write (spec 2.1's selector) --
         same resolution as ``enter_pvi_edit_mode``, so an edit session
         always writes back to whatever layout it was entered against
       - Update vertical segments in-place (preserves alignment ID)
       - Refresh Blender visualization
    2. Always:
       - Remove temporary EMPTY objects
       - Return success status

    Args:
        ifc_tool: The IFC tool class
        alignment_tool: The Alignment tool class
        alignment_id: The IFC ID of the alignment being edited
        apply: If True, update alignment with new PVI positions
        vertical_layout_id: IFC ID of the specific IfcAlignmentVertical that
            was being edited (spec 2.1), or None for the parent's own
            vertical (default, unchanged single-vertical behavior)

    Returns:
        True if successful

    Raises:
        ValueError: If apply=True and validation fails
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        alignment_tool.remove_pvi_edit_empties(alignment_id)
        return True

    try:
        alignment = ifc_file.by_id(alignment_id)
    except RuntimeError:
        alignment_tool.remove_pvi_edit_empties(alignment_id)
        return True

    if apply:
        vpoints, lengths = alignment_tool.collect_pvis_from_empties_vertical(alignment_id)

        if len(vpoints) < 2:
            raise ValueError("At least 2 PVIs are required")

        v_layout = _resolve_vertical_layout(ifc_tool, alignment_tool, alignment, vertical_layout_id)
        if v_layout is None:
            raise ValueError("Alignment has no vertical layout")

        # Remove empties before modifying segments
        alignment_tool.remove_pvi_edit_empties(alignment_id)

        # Remove Blender visualization for vertical segments
        alignment_tool.remove_layout_segment_objects(v_layout)

        # Clear existing segments and regenerate
        alignment_tool.clear_layout_segments(v_layout)
        alignment_tool.layout_vertical_by_pvi_method(v_layout, vpoints, lengths)

        # Refresh Blender visualization
        layout_obj = ifc_tool.get_object(v_layout)
        if layout_obj:
            alignment_tool.create_objects_for_layout_segments(v_layout, layout_obj)

        # Regenerate key-point referents for the new vertical segments, and
        # refresh any live station-tick overlay (spec 4.2 commit funnel).
        alignment_tool.commit_layout_change(alignment)

        return True
    else:
        alignment_tool.remove_pvi_edit_empties(alignment_id)
        return True


def exit_pi_edit_mode(
    ifc_tool: "type[tool.Ifc]",
    alignment_tool: "type[tool.Alignment]",
    alignment_id: int,
    apply: bool,
) -> bool:
    """Exit PI edit mode for an alignment.

    Business logic for exiting PI edit mode:
    1. If apply=True:
       - Collect new PI positions from empties
       - Validate the new configuration
       - Update alignment segments in-place (preserves alignment ID)
    2. Always:
       - Remove temporary EMPTY objects
       - Return success status

    This function modifies the alignment segments in-place rather than
    deleting and recreating the alignment. This preserves the alignment's
    IFC entity ID, preventing stale reference issues.

    Args:
        ifc_tool: The IFC tool class
        alignment_tool: The Alignment tool class
        alignment_id: The IFC ID of the alignment being edited
        apply: If True, update alignment with new PI positions

    Returns:
        True if successful

    Raises:
        ValueError: If alignment doesn't exist or update fails
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        # No file loaded, just clean up empties
        alignment_tool.remove_pi_edit_empties(alignment_id)
        return True

    # Get alignment
    try:
        alignment = ifc_file.by_id(alignment_id)
    except RuntimeError:
        # Alignment was deleted, just clean up empties
        alignment_tool.remove_pi_edit_empties(alignment_id)
        return True

    if apply:
        # Collect PI positions from empties
        hpoints, radii = alignment_tool.collect_pis_from_empties(alignment_id)

        if len(hpoints) < 2:
            raise ValueError("At least 2 PIs are required")

        # Get horizontal layout (delegated to tool)
        h_layout = alignment_tool.get_horizontal_layout(alignment)
        if h_layout is None:
            raise ValueError("Alignment has no horizontal layout")

        # Remove empties before modifying segments
        alignment_tool.remove_pi_edit_empties(alignment_id)

        # Remove Blender visualization for segments (not the whole hierarchy)
        alignment_tool.remove_layout_segment_objects(h_layout)

        # Clear existing IFC segments and add new ones (delegated to tool)
        alignment_tool.clear_layout_segments(h_layout)
        alignment_tool.layout_by_pi_method(h_layout, hpoints, radii)

        # Refresh Blender visualization for new segments
        layout_obj = ifc_tool.get_object(h_layout)
        if layout_obj:
            alignment_tool.create_objects_for_layout_segments(h_layout, layout_obj)

        # Regenerate key-point referents for the new horizontal segments, and
        # refresh any live station-tick overlay (spec 4.2 commit funnel).
        alignment_tool.commit_layout_change(alignment)

        return True
    else:
        # Cancel - just remove empties without regenerating
        alignment_tool.remove_pi_edit_empties(alignment_id)
        return True


def delete_pi_in_edit_mode(
    ifc_tool: "type[tool.Ifc]",
    alignment_tool: "type[tool.Alignment]",
    alignment_id: int,
    index: int,
) -> None:
    """Delete a single PI empty during PI edit mode (spec 1.3, ``X`` key).

    Business rule: at least 3 PIs must remain after the deletion. This
    preserves at least one interior PI, so an in-progress edit can never be
    whittled down to a single bare tangent with no PI left that could ever
    hold a curve.

    Args:
        ifc_tool: The IFC tool class (unused — kept for signature parity
            with the other PI edit mode functions).
        alignment_tool: The Alignment tool class
        alignment_id: The IFC ID of the alignment being edited
        index: The ``civil_pi_index`` of the PI empty to delete

    Raises:
        ValueError: If fewer than 3 PIs would remain, or ``index`` does not
            match an existing PI empty.
    """
    empties = alignment_tool.get_pi_edit_empties(alignment_id)
    if len(empties) - 1 < 3:
        raise ValueError("At least 3 PIs must remain in PI edit mode — cannot delete")
    if not alignment_tool.delete_pi_edit_empty(alignment_id, index):
        raise ValueError(f"PI at index {index} not found")


# =============================================================================
# Alignment Evaluation & 3D Combination (D3)
# =============================================================================


def _resolve_alignment(ifc_tool, alignment_id):
    """Validate and return the IfcAlignment for ``alignment_id``.

    Raises:
        ValueError: If no IFC file is loaded, the id is unknown, or the
            entity is not an IfcAlignment.
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")
    try:
        alignment = ifc_file.by_id(alignment_id)
    except RuntimeError:
        raise ValueError(f"Alignment with ID {alignment_id} not found")
    if not alignment.is_a("IfcAlignment"):
        raise ValueError(f"Entity {alignment_id} is not an IfcAlignment")
    return alignment


# =============================================================================
# Alignment / Vertical Deletion (spec 1.4, 2.6)
# =============================================================================


def delete_alignment(
    ifc_tool: "type[tool.Ifc]",
    alignment_tool: "type[tool.Alignment]",
    alignment_id: int,
) -> int:
    """Delete an alignment entirely: its IFC entity and all viewport objects.

    Business rules:
    1. The alignment must exist and be an IfcAlignment.
    2. Blender objects for the alignment, its layouts/segments, and the 3D
       centerline helper (if any) are removed first, then the IFC entity.

    Args:
        ifc_tool: The IFC tool class
        alignment_tool: The Alignment tool class
        alignment_id: The IFC ID of the alignment to delete

    Returns:
        The number of Blender objects removed.

    Raises:
        ValueError: If the alignment doesn't exist or is the wrong type.
    """
    alignment = _resolve_alignment(ifc_tool, alignment_id)
    removed_objects = alignment_tool.remove_alignment_hierarchy(alignment)
    alignment_tool.remove_3d_alignment_object(alignment)
    alignment_tool.remove_alignment_entity(alignment)
    return removed_objects


def delete_vertical_layout(
    ifc_tool: "type[tool.Ifc]",
    alignment_tool: "type[tool.Alignment]",
    alignment_id: int,
) -> bool:
    """Delete the vertical layout, reverting the alignment to horizontal-only.

    Business rules:
    1. The alignment must exist and be an IfcAlignment.
    2. The alignment must currently have a vertical layout.

    Args:
        ifc_tool: The IFC tool class
        alignment_tool: The Alignment tool class
        alignment_id: The IFC ID of the alignment

    Returns:
        True if successful.

    Raises:
        ValueError: If the alignment doesn't exist, is the wrong type, or has
            no vertical layout.
    """
    alignment = _resolve_alignment(ifc_tool, alignment_id)
    if alignment_tool.get_vertical_layout(alignment) is None:
        raise ValueError(f"Alignment '{alignment.Name}' has no vertical layout")
    alignment_tool.remove_vertical_layout(alignment)
    return True


def evaluate_alignment_at_station(
    ifc_tool: "type[tool.Ifc]",
    alignment_tool: "type[tool.Alignment]",
    alignment_id: int,
    station: float,
):
    """Evaluate the combined 3D alignment at a station.

    The keystone query for the road-design pipeline: returns 3D position,
    tangent, and an orientation frame on the combined (horizontal + vertical)
    alignment. Geometry is delegated to the tool layer / geometry engine.

    Args:
        ifc_tool: The IFC tool class
        alignment_tool: The Alignment tool class
        alignment_id: The IFC ID of the alignment
        station: Station value to evaluate

    Returns:
        An AlignmentPoint, or None if the station is outside the alignment
        domain or the alignment has no evaluatable representation.

    Raises:
        ValueError: If the alignment doesn't exist or is the wrong type.
    """
    alignment = _resolve_alignment(ifc_tool, alignment_id)
    return alignment_tool.evaluate_alignment_at_station(alignment, station)


def visualize_3d_alignment(
    ifc_tool: "type[tool.Ifc]",
    alignment_tool: "type[tool.Alignment]",
    alignment_id: int,
    distance_interval: float = 5.0,
):
    """Create/refresh the draped 3D centerline visualization for an alignment.

    Business rules:
    1. The alignment must exist and be an IfcAlignment.
    2. It must have a horizontal layout (otherwise there is nothing to draw).

    Args:
        ifc_tool: The IFC tool class
        alignment_tool: The Alignment tool class
        alignment_id: The IFC ID of the alignment
        distance_interval: Spacing between sampled vertices (model units)

    Returns:
        The created Blender object, or None if there is no geometry to draw.

    Raises:
        ValueError: If the alignment doesn't exist, is the wrong type, or has
            no horizontal layout.
    """
    alignment = _resolve_alignment(ifc_tool, alignment_id)
    if alignment_tool.get_horizontal_layout(alignment) is None:
        raise ValueError(f"Alignment '{alignment.Name}' has no horizontal layout")
    return alignment_tool.create_3d_alignment_object(alignment, distance_interval)


# =============================================================================
# Offset Alignments (spec 1.7)
# =============================================================================


def create_offset_alignment(
    ifc_tool: "type[tool.Ifc]",
    alignment_tool: "type[tool.Alignment]",
    alignment_id: int,
    name: str,
    offset_spec: dict,
):
    """Create an offset alignment riding on the active alignment's current
    curve (spec 1.7: "Constant, or varying between stations").

    ``offset_spec`` is either ``{"mode": "CONSTANT", "offset": <float>}`` or
    ``{"mode": "TAPER", "start_offset": <float>, "end_offset": <float>,
    "station_from": <float>, "station_to": <float>}`` — a single linear
    taper over a station range, constant before/after, covering the named
    "widening or taper" use cases without a full multi-station table (see
    ``tool.Alignment._build_offset_points`` for the extension path to one).
    "station" here is a 0-based DISTANCE-ALONG the alignment (same
    convention as the cant point table's "station", NOT a true engineering
    station offset by start_station).

    Business rules:
    1. Parent alignment must exist, be an IfcAlignment, and already have a
       geometric representation curve to offset from.
    2. Name must not be empty.
    3. ``offset_spec["mode"]`` must be "CONSTANT" or "TAPER".
    4. CONSTANT: the offset must be non-zero (a zero offset is not an
       offset at all).
    5. TAPER: the two offsets cannot both be zero; ``station_from`` must be
       < ``station_to``; both must fall within the parent's current
       horizontal extent (computed semantically, no geometry engine, via
       ``get_horizontal_extent_semantic``).

    Args:
        ifc_tool: The IFC tool class
        alignment_tool: The Alignment tool class
        alignment_id: The IFC ID of the parent alignment
        name: Name for the new (offset) alignment
        offset_spec: See above

    Returns:
        The newly created (offset) IfcAlignment entity

    Raises:
        ValueError: If validation fails
    """
    alignment = _resolve_alignment(ifc_tool, alignment_id)

    if alignment_tool.get_curve_for_alignment(alignment) is None:
        raise ValueError(f"Alignment '{alignment.Name}' has no geometric representation to offset from")

    if not name or not name.strip():
        raise ValueError("Offset alignment name cannot be empty")

    mode = offset_spec.get("mode", "CONSTANT")
    if mode not in ("CONSTANT", "TAPER"):
        raise ValueError(f"Unknown offset mode '{mode}' — expected 'CONSTANT' or 'TAPER'")

    extent = alignment_tool.get_horizontal_extent_semantic(alignment)

    if mode == "CONSTANT":
        offset = float(offset_spec.get("offset", 0.0))
        if offset == 0.0:
            raise ValueError("Constant offset must be non-zero")
    else:
        start_offset = float(offset_spec.get("start_offset", 0.0))
        end_offset = float(offset_spec.get("end_offset", 0.0))
        station_from = float(offset_spec.get("station_from", 0.0))
        station_to = float(offset_spec.get("station_to", 0.0))

        if start_offset == 0.0 and end_offset == 0.0:
            raise ValueError("Taper start and end offsets cannot both be zero")
        if station_from >= station_to:
            raise ValueError("Taper station_from must be less than station_to")
        if station_from < -1e-6 or station_to > extent + 1e-6:
            raise ValueError(f"Taper station range must fall within the alignment's extent (0 to {extent:.3f})")

    return alignment_tool.create_offset_alignment(alignment, name.strip(), offset_spec)


# =============================================================================
# Convert Curve to Alignment (spec 1.8)
# =============================================================================


def convert_curve_to_alignment(
    ifc_tool: "type[tool.Ifc]",
    alignment_tool: "type[tool.Alignment]",
    name: str,
    points_xy: list,
    simplify_tolerance: float = 0.5,
):
    """Convert a sampled Blender curve/polyline into a new all-tangent
    horizontal alignment (spec 1.8).

    Business rules:
    1. An IFC file must be loaded.
    2. Name must not be empty.
    3. ``points_xy`` must have at least 2 points to begin with.
    4. After Ramer-Douglas-Peucker simplification (delegated to
       ``alignment_tool.simplify_polyline`` — pure math, tool layer), at
       least 2 DISTINCT points must remain (``alignment_tool.
       count_distinct_points``) — a fully-degenerate (single-point) curve
       cannot become an alignment even after simplification.

    Args:
        ifc_tool: The IFC tool class
        alignment_tool: The Alignment tool class
        name: Name for the new alignment
        points_xy: Ordered (x, y) world-space points sampled from the
            source curve (Z already discarded per spec 1.1's XY-plane rule)
        simplify_tolerance: Maximum perpendicular deviation allowed when
            simplifying ``points_xy`` to PI candidates

    Returns:
        A ``(alignment, pi_count, sample_count)`` tuple: the newly created
        IfcAlignment, the number of PIs it was built from (after
        simplification), and the number of raw samples it was simplified
        from.

    Raises:
        ValueError: If validation fails
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")

    if not name or not name.strip():
        raise ValueError("Alignment name cannot be empty")

    if len(points_xy) < 2:
        raise ValueError("Need at least 2 points to convert a curve to an alignment")

    simplified = alignment_tool.simplify_polyline(points_xy, simplify_tolerance)

    if alignment_tool.count_distinct_points(simplified) < 2:
        raise ValueError("Curve simplifies to fewer than 2 distinct points — lower the simplify tolerance")

    alignment = alignment_tool.convert_points_to_alignment(name.strip(), simplified)
    return alignment, len(simplified), len(points_xy)


# =============================================================================
# Cant (spec Section 3)
# =============================================================================
# Adding cant is what marks an alignment as rail (spec 3.1). A cant layout
# requires both a horizontal AND a vertical layout to exist first — the
# geometry engine needs an IfcGradientCurve to use as the BaseCurve of the
# IfcSegmentedReferenceCurve cant produces (see
# ifcopenshell.api.alignment.add_cant_layout's docstring).


def add_cant_to_alignment(
    ifc_tool: "type[tool.Ifc]",
    alignment_tool: "type[tool.Alignment]",
    alignment_id: int,
    rail_head_distance: float = 1.0,
):
    """Add a cant layout to an existing horizontal + vertical alignment.

    Business rules:
    1. Alignment must exist and be an IfcAlignment.
    2. Horizontal layout must exist (cant requires horizontal).
    3. Vertical layout must exist (cant requires vertical — the API's
       IfcSegmentedReferenceCurve wraps the vertical's IfcGradientCurve).
    4. Alignment must not already have a cant layout (one cant max).

    Args:
        ifc_tool: The IFC tool class
        alignment_tool: The Alignment tool class
        alignment_id: The IFC ID of the alignment
        rail_head_distance: Distance between rail heads, used to convert
            cant height to a rotation angle for the geometric representation

    Returns:
        The newly created IfcAlignmentCant entity

    Raises:
        ValueError: If alignment doesn't exist, is wrong type, has no
            horizontal or vertical layout, or already has a cant layout
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")

    try:
        alignment = ifc_file.by_id(alignment_id)
    except RuntimeError:
        raise ValueError(f"Alignment with ID {alignment_id} not found")

    if not alignment.is_a("IfcAlignment"):
        raise ValueError(f"Entity {alignment_id} is not an IfcAlignment")

    if alignment_tool.get_horizontal_layout(alignment) is None:
        raise ValueError(f"Alignment '{alignment.Name}' has no horizontal layout — add horizontal first")

    if alignment_tool.get_vertical_layout(alignment) is None:
        raise ValueError(
            f"Alignment '{alignment.Name}' has no vertical layout — add vertical first (cant requires vertical)"
        )

    if alignment_tool.get_cant_layout(alignment) is not None:
        raise ValueError(f"Alignment '{alignment.Name}' already has a cant layout")

    return alignment_tool.add_cant_layout(alignment, rail_head_distance)


def update_cant_segments(
    ifc_tool: "type[tool.Ifc]",
    alignment_tool: "type[tool.Alignment]",
    alignment_id: int,
    points: list,
) -> bool:
    """Write the cant table (points) to IFC as IfcAlignmentCantSegments.

    Business rules:
    1. Alignment must exist and be an IfcAlignment.
    2. Alignment must have a cant layout.
    3. At least 2 cant points are required (one segment minimum).
    4. Point stations must be strictly increasing (non-monotonic refused —
       consecutive points define a segment, so equal/reversed stations would
       produce a degenerate or negative-length segment).
    5. Points must fall within the horizontal alignment's extent, computed
       semantically (no geometry engine) via
       ``alignment_tool.get_horizontal_extent_semantic``.

    Args:
        ifc_tool: The IFC tool class
        alignment_tool: The Alignment tool class
        alignment_id: The IFC ID of the alignment
        points: Ordered list of dicts with "station", "cant_left",
            "cant_right", "transition_type" (the type carried INTO the next
            point — see ``tool.Alignment.write_cant_segments``)

    Returns:
        True if successful

    Raises:
        ValueError: If validation fails
    """
    ifc_file = ifc_tool.get()
    if ifc_file is None:
        raise ValueError("No IFC file loaded")

    try:
        alignment = ifc_file.by_id(alignment_id)
    except RuntimeError:
        raise ValueError(f"Alignment with ID {alignment_id} not found")

    if not alignment.is_a("IfcAlignment"):
        raise ValueError(f"Entity {alignment_id} is not an IfcAlignment")

    if alignment_tool.get_cant_layout(alignment) is None:
        raise ValueError(f"Alignment '{alignment.Name}' has no cant layout")

    if len(points) < 2:
        raise ValueError("At least 2 cant points are required")

    for previous, current in zip(points, points[1:]):
        if current["station"] <= previous["station"]:
            raise ValueError("Cant point stations must be strictly increasing")

    extent = alignment_tool.get_horizontal_extent_semantic(alignment)
    first_station = points[0]["station"]
    last_station = points[-1]["station"]
    if first_station < -1e-6 or last_station > extent + 1e-6:
        raise ValueError(f"Cant points must fall within the alignment's horizontal extent (0 to {extent:.3f})")

    alignment_tool.write_cant_segments(alignment, points)

    # Regenerate key-point referents for the new cant segments, and refresh
    # any live station-tick overlay (spec 4.2 commit funnel).
    alignment_tool.commit_layout_change(alignment)

    return True


def delete_cant_layout(
    ifc_tool: "type[tool.Ifc]",
    alignment_tool: "type[tool.Alignment]",
    alignment_id: int,
) -> bool:
    """Delete the cant layout, reverting the alignment's representation to
    horizontal + vertical only (spec 3.6).

    Business rules:
    1. The alignment must exist and be an IfcAlignment.
    2. The alignment must currently have a cant layout.

    Args:
        ifc_tool: The IFC tool class
        alignment_tool: The Alignment tool class
        alignment_id: The IFC ID of the alignment

    Returns:
        True if successful.

    Raises:
        ValueError: If the alignment doesn't exist, is the wrong type, or has
            no cant layout.
    """
    alignment = _resolve_alignment(ifc_tool, alignment_id)
    if alignment_tool.get_cant_layout(alignment) is None:
        raise ValueError(f"Alignment '{alignment.Name}' has no cant layout")
    alignment_tool.remove_cant_layout(alignment)
    return True


# =============================================================================
# Stationing Referents (spec Section 4)
# =============================================================================

# IfcReferentTypeEnum members spec 4.4's event referents may use. Corridor
# consumption of these is out of scope here — see tool.Alignment.add_event_referent.
_VALID_EVENT_TYPES = {"SUPERELEVATIONEVENT", "WIDTHEVENT"}


def add_station_equation(
    ifc_tool: "type[tool.Ifc]",
    alignment_tool: "type[tool.Alignment]",
    alignment_id: int,
    back_station: float,
    ahead_station: float,
):
    """Author a station equation (spec 4.3): the point where stationing
    switches from ``back_station`` (incoming, in the EXISTING stationing
    sequence) to ``ahead_station`` (outgoing) — a gap when ahead_station >
    back_station without picking up where the incoming side left off, or an
    overlap when ahead_station < back_station. Both are legal surveying
    practice; only a no-op equation (equal back/ahead) is refused.

    Business rules:
    1. Alignment must exist and be an IfcAlignment.
    2. back_station != ahead_station (a no-op equation is refused — gap
       and overlap are both otherwise legal, per spec 4.3).
    3. back_station must resolve to a distance along the alignment (via
       alignment_tool.distance_along_from_station) — None means it falls
       inside an existing equation's gap, which is refused with a specific
       message rather than silently placing the new equation at distance
       0.0.

    Args:
        ifc_tool: The IFC tool class
        alignment_tool: The Alignment tool class
        alignment_id: The IFC ID of the alignment
        back_station: Station value immediately BEFORE the equation, in the
            alignment's EXISTING stationing
        ahead_station: Station value immediately AFTER the equation

    Returns:
        The created IfcReferent (PredefinedType="STATION").

    Raises:
        ValueError: If validation fails.
    """
    alignment = _resolve_alignment(ifc_tool, alignment_id)

    if back_station == ahead_station:
        raise ValueError("Back and ahead station must differ to define a station equation")

    distance_along = alignment_tool.distance_along_from_station(alignment, back_station)
    if distance_along is None:
        raise ValueError(f"Back station {back_station} is not reachable (falls in an existing station equation gap?)")

    return alignment_tool.add_station_equation_referent(alignment, distance_along, back_station, ahead_station)


def add_event_referent(
    ifc_tool: "type[tool.Ifc]",
    alignment_tool: "type[tool.Alignment]",
    alignment_id: int,
    event_type: str,
    station: float,
    name: str = "",
    value: "Optional[float]" = None,
):
    """Author an event referent (spec 4.4): a station-located marker for a
    future corridor-consuming event (superelevation or width change) that
    carries no geometry consequence of its own here — corridor generation,
    when it exists, is the eventual consumer (out of scope).

    Business rules:
    1. Alignment must exist and be an IfcAlignment.
    2. event_type must be one of the supported IfcReferentTypeEnum event
       kinds: SUPERELEVATIONEVENT, WIDTHEVENT.

    Args:
        ifc_tool: The IFC tool class
        alignment_tool: The Alignment tool class
        alignment_id: The IFC ID of the alignment
        event_type: "SUPERELEVATIONEVENT" or "WIDTHEVENT"
        station: Station value for the event
        name: Optional referent name (auto-generated when blank)
        value: Optional payload value (e.g. target superelevation/width)

    Returns:
        The created IfcReferent.

    Raises:
        ValueError: If validation fails.
    """
    alignment = _resolve_alignment(ifc_tool, alignment_id)

    if event_type not in _VALID_EVENT_TYPES:
        raise ValueError(f"Unknown event type '{event_type}' — expected one of {sorted(_VALID_EVENT_TYPES)}")

    return alignment_tool.add_event_referent(alignment, event_type, station, name, value)


def remove_referent(
    ifc_tool: "type[tool.Ifc]",
    alignment_tool: "type[tool.Alignment]",
    alignment_id: int,
    referent_id: int,
) -> None:
    """Delete a referent from the alignment's referent list (spec 4.1,
    "Deletable").

    Business rules:
    1. Alignment must exist and be an IfcAlignment.
    2. The referent must actually be one of the alignment's own nested
       referents (found via alignment_tool.get_referents) — refuses
       deleting an arbitrary IfcReferent id unrelated to this alignment.

    Args:
        ifc_tool: The IFC tool class
        alignment_tool: The Alignment tool class
        alignment_id: The IFC ID of the alignment
        referent_id: The IFC ID of the referent to delete

    Raises:
        ValueError: If validation fails.
    """
    alignment = _resolve_alignment(ifc_tool, alignment_id)
    referents = alignment_tool.get_referents(alignment)
    if not any(r["id"] == referent_id for r in referents):
        raise ValueError(f"Referent #{referent_id} is not nested on alignment '{alignment.Name}'")
    alignment_tool.remove_referent(alignment, referent_id)

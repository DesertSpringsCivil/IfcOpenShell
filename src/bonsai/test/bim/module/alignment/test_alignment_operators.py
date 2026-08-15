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

"""Headless operator tests for the Saikei alignment module.

Tests non-modal alignment operators end-to-end in Blender headless mode.
Follows Bonsai's existing test patterns (NewIfc4X3 base class from bootstrap).

Operators tested:
    Horizontal: add_pi, remove_pi, recalculate_pis, clear_pis, create_alignment_by_pi
    Vertical: add_pvi, remove_pvi, recalculate_pvis, clear_pvis, add_vertical_to_alignment
    Utility: name_segments

Operators skipped (modal / viewport / file browser):
    pick_pi_from_viewport, enter_pi_edit_mode, enter_pvi_edit_mode, import_alignment_csv
"""

import math

import pytest

import bpy
import ifcopenshell
import ifcopenshell.api.alignment as align_api

import bonsai.tool as tool
from bonsai.bim.ifc import IfcStore
from test.bim.bootstrap import NewIfc4X3


def _geometry_mapping_available() -> bool:
    """True when the modular geometry-mapping plugins are present.

    v0.9.0 evaluates segment endpoints through the geometry engine, which
    loads per-schema ifcopenshell_geometry_mapping_* plugins at runtime. The
    win64 v0.9.0alpha0 builds ship without them (IfcOpenShell#9301), so
    geometry-dependent tests skip locally and run in CI where builds are
    complete.
    """
    import pathlib

    package_root = pathlib.Path(ifcopenshell.__file__).parent
    return any(f.name.startswith("ifcopenshell_geometry_mapping_") for f in package_root.iterdir())


requires_geometry_engine = pytest.mark.skipif(
    not _geometry_mapping_available(),
    reason="geometry mapping plugins unavailable (IfcOpenShell#9301); covered in CI",
)

pytestmark = pytest.mark.alignment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_alignment_props():
    """Shortcut to CivilAlignmentProperties on the scene."""
    return bpy.context.scene.CivilAlignmentProperties


def create_empty_alignment(name="Test Alignment"):
    """Create an IfcAlignment with an empty IfcAlignmentHorizontal layout.

    Uses align_api.create() which creates IfcAlignment + IfcAlignmentHorizontal
    + zero-length terminator + geometric representations + aggregation to project.

    This is the minimal setup required for operators that need an active
    alignment (e.g. create_alignment_by_pi, recalculate_pis).

    Returns:
        tuple: (alignment_entity, alignment_blender_obj)
    """
    ifc_file = tool.Ifc.get()

    # create() handles: IfcAlignment, IfcAlignmentHorizontal, IfcRelNests,
    # zero-length terminator, geometric representation, project aggregation
    alignment = align_api.create(ifc_file, name=name)

    # Create Blender objects via the tool layer
    alignment_obj = tool.Alignment.create_hierarchy_for_alignment(alignment)

    # Set as active so operators can find it via get_active_alignment()
    if alignment_obj:
        bpy.context.view_layer.objects.active = alignment_obj
        alignment_obj.select_set(True)

    # Set active alignment ID in properties
    props = get_alignment_props()
    props.active_alignment_id = alignment.id()
    props.active_alignment_name = name

    return alignment, alignment_obj


def add_pis_to_props(pi_data):
    """Add PIs to the props collection with specified coordinates.

    Args:
        pi_data: list of (e, n, radius) tuples.
                 First and last are auto-typed as ENDPOINT.
    """
    props = get_alignment_props()
    for i, (e, n, radius) in enumerate(pi_data):
        bpy.ops.civil.add_pi()
        pi = props.pis[len(props.pis) - 1]
        pi.e = str(e)
        pi.n = str(n)
        if radius > 0:
            pi.radius = radius


# ===========================================================================
# Horizontal PI Operators
# ===========================================================================


class TestAddPi(NewIfc4X3):
    """Tests for CIVIL_OT_add_pi (civil.add_pi)."""

    def test_add_first_pi_sets_endpoint_at_origin(self):
        props = get_alignment_props()
        result = bpy.ops.civil.add_pi()
        assert result == {"FINISHED"}
        assert len(props.pis) == 1
        assert float(props.pis[0].e) == 0.0
        assert float(props.pis[0].n) == 0.0
        assert props.pis[0].pi_type == "ENDPOINT"

    def test_add_second_pi_offsets_from_first(self):
        props = get_alignment_props()
        bpy.ops.civil.add_pi()
        bpy.ops.civil.add_pi()
        assert len(props.pis) == 2
        assert props.pis[1].pi_type == "ENDPOINT"
        # Second PI should be offset 100 units east
        assert float(props.pis[1].e) == pytest.approx(100.0)
        assert float(props.pis[1].n) == pytest.approx(0.0)

    def test_add_third_pi_extrapolates_and_changes_second_type(self):
        props = get_alignment_props()
        bpy.ops.civil.add_pi()
        bpy.ops.civil.add_pi()
        bpy.ops.civil.add_pi()
        assert len(props.pis) == 3
        # Second PI (index 1) should have been changed from ENDPOINT to TANGENT
        assert props.pis[1].pi_type == "TANGENT"
        # Third PI extrapolates direction
        assert float(props.pis[2].e) == pytest.approx(200.0)

    def test_active_pi_index_tracks_last_added(self):
        props = get_alignment_props()
        bpy.ops.civil.add_pi()
        assert props.active_pi_index == 0
        bpy.ops.civil.add_pi()
        assert props.active_pi_index == 1
        bpy.ops.civil.add_pi()
        assert props.active_pi_index == 2

    def test_add_pi_triggers_geometry_recalculation(self):
        """After adding 2+ PIs, display_rows should be populated."""
        props = get_alignment_props()
        bpy.ops.civil.add_pi()
        bpy.ops.civil.add_pi()
        # With 2 PIs, we should have at least 2 point rows and 1 segment row
        assert len(props.display_rows) >= 2


class TestRemovePi(NewIfc4X3):
    """Tests for CIVIL_OT_remove_pi (civil.remove_pi)."""

    def test_remove_pi_decrements_collection(self):
        props = get_alignment_props()
        bpy.ops.civil.add_pi()
        bpy.ops.civil.add_pi()
        bpy.ops.civil.add_pi()
        assert len(props.pis) == 3

        # Select first point row in display_rows
        if props.display_rows:
            props.active_display_row_index = 0
        result = bpy.ops.civil.remove_pi()
        assert result == {"FINISHED"}
        assert len(props.pis) == 2

    def test_remove_pi_from_single_item_list(self):
        props = get_alignment_props()
        bpy.ops.civil.add_pi()
        assert len(props.pis) == 1

        # Use active_pi_index fallback (no display_rows for 1 PI)
        props.active_pi_index = 0
        # display_rows may be empty with 1 PI, so remove_pi uses active_pi_index
        props.display_rows.clear()
        result = bpy.ops.civil.remove_pi()
        assert result == {"FINISHED"}
        assert len(props.pis) == 0

    def test_remove_pi_updates_active_index(self):
        props = get_alignment_props()
        bpy.ops.civil.add_pi()
        bpy.ops.civil.add_pi()
        bpy.ops.civil.add_pi()

        # Select last point row
        props.active_pi_index = 2
        props.display_rows.clear()
        bpy.ops.civil.remove_pi()
        # active_pi_index should clamp to valid range
        assert props.active_pi_index <= len(props.pis) - 1


class TestClearPis(NewIfc4X3):
    """Tests for CIVIL_OT_clear_pis (civil.clear_pis).

    Note: clear_pis defines invoke() with invoke_confirm, but calling via
    bpy.ops in Python uses EXEC_DEFAULT by default, skipping invoke.
    """

    def test_clear_pis_removes_all(self):
        props = get_alignment_props()
        for _ in range(5):
            bpy.ops.civil.add_pi()
        assert len(props.pis) == 5

        result = bpy.ops.civil.clear_pis()
        assert result == {"FINISHED"}
        assert len(props.pis) == 0
        assert len(props.display_rows) == 0

    def test_clear_pis_resets_indices(self):
        props = get_alignment_props()
        bpy.ops.civil.add_pi()
        bpy.ops.civil.add_pi()
        bpy.ops.civil.clear_pis()
        assert props.active_pi_index == 0
        assert props.active_display_row_index == 0

    def test_clear_pis_with_active_alignment_removes_ifc(self):
        """When an active alignment exists, clear_pis should remove it from IFC."""
        alignment, alignment_obj = create_empty_alignment()
        ifc_file = tool.Ifc.get()

        props = get_alignment_props()
        bpy.ops.civil.add_pi()
        bpy.ops.civil.add_pi()

        alignment_count_before = len(ifc_file.by_type("IfcAlignment"))
        bpy.ops.civil.clear_pis()

        alignment_count_after = len(ifc_file.by_type("IfcAlignment"))
        assert alignment_count_after < alignment_count_before
        assert len(props.pis) == 0

    def test_clear_pis_resolves_alignment_from_props_not_viewport(self):
        """The alignment is resolved via props.active_alignment_id, so it is
        deleted even when the viewport's active object is something else
        (typically a segment curve after PI editing)."""
        alignment, alignment_obj = create_empty_alignment()
        ifc_file = tool.Ifc.get()
        bpy.context.view_layer.objects.active = None

        props = get_alignment_props()
        bpy.ops.civil.add_pi()

        alignment_count_before = len(ifc_file.by_type("IfcAlignment"))
        bpy.ops.civil.clear_pis()

        assert len(ifc_file.by_type("IfcAlignment")) < alignment_count_before
        assert props.active_alignment_id == 0
        assert props.active_alignment_name == ""


class TestDeleteAlignment(NewIfc4X3):
    """Tests for CIVIL_OT_delete_alignment (civil.delete_alignment).

    Note: delete_alignment defines invoke() with invoke_confirm, but calling
    via bpy.ops in Python uses EXEC_DEFAULT by default, skipping invoke.
    """

    def test_delete_alignment_removes_ifc_entity(self):
        alignment, alignment_obj = create_empty_alignment()
        ifc_file = tool.Ifc.get()

        alignment_count_before = len(ifc_file.by_type("IfcAlignment"))
        result = bpy.ops.civil.delete_alignment()

        assert result == {"FINISHED"}
        assert len(ifc_file.by_type("IfcAlignment")) < alignment_count_before

    def test_delete_alignment_resets_active_alignment_props(self):
        alignment, alignment_obj = create_empty_alignment()
        props = get_alignment_props()

        bpy.ops.civil.delete_alignment()

        assert props.active_alignment_id == 0
        assert props.active_alignment_name == ""

    def test_delete_alignment_resets_pi_and_pvi_tables(self):
        alignment, alignment_obj = create_empty_alignment()
        props = get_alignment_props()
        bpy.ops.civil.add_pi()
        bpy.ops.civil.add_pi()
        bpy.ops.civil.add_pvi()

        bpy.ops.civil.delete_alignment()

        assert len(props.pis) == 0
        assert len(props.display_rows) == 0
        assert len(props.vertical_pvis) == 0
        assert len(props.vertical_display_rows) == 0

    def test_poll_fails_when_no_active_alignment(self):
        with pytest.raises(RuntimeError):
            bpy.ops.civil.delete_alignment()


class TestRecalculatePis(NewIfc4X3):
    """Tests for CIVIL_OT_recalculate_pis (civil.recalculate_pis)."""

    def test_recalculate_populates_display_rows(self):
        props = get_alignment_props()
        add_pis_to_props([(0, 0, 0), (500, 0, 0), (1000, 200, 0)])

        result = bpy.ops.civil.recalculate_pis()
        assert result == {"FINISHED"}
        assert len(props.display_rows) > 0

    def test_recalculate_computes_geometry_values(self):
        """PI geometry values (station, length_to_next) should be reasonable."""
        props = get_alignment_props()
        add_pis_to_props([(0, 0, 0), (500, 0, 0), (1000, 0, 0)])

        bpy.ops.civil.recalculate_pis()

        # Straight line: each segment should be 500 units
        assert props.pis[0].length_to_next == pytest.approx(500.0, abs=1.0)
        assert props.pis[1].length_to_next == pytest.approx(500.0, abs=1.0)

    @requires_geometry_engine
    def test_recalculate_with_active_alignment_updates_ifc(self):
        """When an active alignment exists, recalculate should update IFC segments."""
        alignment, alignment_obj = create_empty_alignment()
        ifc_file = tool.Ifc.get()

        props = get_alignment_props()
        add_pis_to_props([(0, 0, 0), (500, 0, 0), (1000, 200, 0)])

        # First, create alignment segments
        bpy.ops.civil.create_alignment_by_pi()

        # Re-select alignment object (create_alignment_by_pi may change selection)
        bpy.context.view_layer.objects.active = alignment_obj
        alignment_obj.select_set(True)

        # Modify a PI
        props.pis[1].e = str(600.0)

        # Recalculate should update IFC in-place
        result = bpy.ops.civil.recalculate_pis()
        assert result == {"FINISHED"}

        # IFC should still have segments
        segments = ifc_file.by_type("IfcAlignmentSegment")
        assert len(segments) >= 2


@requires_geometry_engine
class TestCreateAlignmentByPi(NewIfc4X3):
    """Tests for CIVIL_OT_create_alignment_by_pi (civil.create_alignment_by_pi).

    This operator requires an existing empty alignment set as active.
    """

    def test_create_alignment_creates_ifc_segments(self):
        """Basic 3-PI alignment: creates tangent + tangent segments in IFC."""
        alignment, alignment_obj = create_empty_alignment()
        ifc_file = tool.Ifc.get()

        props = get_alignment_props()
        add_pis_to_props([(0, 0, 0), (500, 0, 0), (1000, 200, 0)])

        result = bpy.ops.civil.create_alignment_by_pi()
        assert result == {"FINISHED"}

        # IFC should contain alignment segments
        segments = ifc_file.by_type("IfcAlignmentSegment")
        assert len(segments) >= 2

        # Alignment should still exist
        alignments = ifc_file.by_type("IfcAlignment")
        assert len(alignments) == 1

        # Horizontal layout should exist
        horizontals = ifc_file.by_type("IfcAlignmentHorizontal")
        assert len(horizontals) == 1

    def test_create_alignment_with_curve_creates_arc_segment(self):
        """3-PI alignment with radius on middle PI creates LINE + ARC + LINE."""
        alignment, alignment_obj = create_empty_alignment()
        ifc_file = tool.Ifc.get()

        props = get_alignment_props()
        add_pis_to_props([(0, 0, 0), (500, 0, 300), (1000, 200, 0)])

        result = bpy.ops.civil.create_alignment_by_pi()
        assert result == {"FINISHED"}

        # Check segment design parameter types
        segments = ifc_file.by_type("IfcAlignmentSegment")
        segment_types = []
        for seg in segments:
            dp = seg.DesignParameters
            if dp and hasattr(dp, "PredefinedType"):
                segment_types.append(dp.PredefinedType)

        # Should have at least LINE and CIRCULARARC
        assert "LINE" in segment_types
        assert "CIRCULARARC" in segment_types

    def test_create_alignment_produces_blender_objects(self):
        """After creation, Blender scene should contain alignment objects."""
        alignment, alignment_obj = create_empty_alignment()

        props = get_alignment_props()
        add_pis_to_props([(0, 0, 0), (500, 0, 0), (1000, 200, 0)])

        bpy.ops.civil.create_alignment_by_pi()

        # Should have at least the alignment object in the scene
        alignment_objects = [
            obj
            for obj in bpy.data.objects
            if tool.Ifc.get_entity(obj) and tool.Ifc.get_entity(obj).is_a("IfcAlignment")
        ]
        assert len(alignment_objects) >= 1

    def test_create_straight_alignment_two_pis(self):
        """Minimal alignment: 2 PIs producing a single tangent."""
        alignment, alignment_obj = create_empty_alignment()
        ifc_file = tool.Ifc.get()

        props = get_alignment_props()
        add_pis_to_props([(0, 0, 0), (1000, 0, 0)])

        result = bpy.ops.civil.create_alignment_by_pi()
        assert result == {"FINISHED"}

        segments = ifc_file.by_type("IfcAlignmentSegment")
        assert len(segments) >= 1


# ===========================================================================
# Vertical PVI Operators
# ===========================================================================


class TestAddPvi(NewIfc4X3):
    """Tests for CIVIL_OT_add_pvi (civil.add_pvi)."""

    def test_add_first_pvi_sets_endpoint_at_zero(self):
        props = get_alignment_props()
        result = bpy.ops.civil.add_pvi()
        assert result == {"FINISHED"}
        assert len(props.vertical_pvis) == 1
        assert props.vertical_pvis[0].station == pytest.approx(0.0)
        assert props.vertical_pvis[0].elevation == pytest.approx(0.0)
        assert props.vertical_pvis[0].pvi_type == "ENDPOINT"

    def test_add_second_pvi_offsets_from_first(self):
        props = get_alignment_props()
        bpy.ops.civil.add_pvi()
        bpy.ops.civil.add_pvi()
        assert len(props.vertical_pvis) == 2
        assert props.vertical_pvis[1].station == pytest.approx(100.0)
        assert props.vertical_pvis[1].pvi_type == "ENDPOINT"

    def test_add_third_pvi_extrapolates_and_changes_type(self):
        props = get_alignment_props()
        bpy.ops.civil.add_pvi()
        bpy.ops.civil.add_pvi()
        bpy.ops.civil.add_pvi()
        assert len(props.vertical_pvis) == 3
        # Second PVI (index 1) should become INTERIOR
        assert props.vertical_pvis[1].pvi_type == "INTERIOR"
        assert props.vertical_pvis[2].station == pytest.approx(200.0)

    def test_active_pvi_index_tracks_last_added(self):
        props = get_alignment_props()
        bpy.ops.civil.add_pvi()
        assert props.active_pvi_index == 0
        bpy.ops.civil.add_pvi()
        assert props.active_pvi_index == 1

    def test_add_pvi_triggers_vertical_geometry_recalculation(self):
        """After adding 2+ PVIs, vertical_display_rows should be populated."""
        props = get_alignment_props()
        bpy.ops.civil.add_pvi()
        bpy.ops.civil.add_pvi()
        assert len(props.vertical_display_rows) >= 2


class TestRemovePvi(NewIfc4X3):
    """Tests for CIVIL_OT_remove_pvi (civil.remove_pvi)."""

    def test_remove_pvi_decrements_collection(self):
        props = get_alignment_props()
        bpy.ops.civil.add_pvi()
        bpy.ops.civil.add_pvi()
        bpy.ops.civil.add_pvi()
        assert len(props.vertical_pvis) == 3

        # Clear display rows to use active_pvi_index fallback
        props.vertical_display_rows.clear()
        props.active_pvi_index = 0
        result = bpy.ops.civil.remove_pvi()
        assert result == {"FINISHED"}
        assert len(props.vertical_pvis) == 2

    def test_remove_last_pvi(self):
        props = get_alignment_props()
        bpy.ops.civil.add_pvi()
        props.vertical_display_rows.clear()
        props.active_pvi_index = 0
        result = bpy.ops.civil.remove_pvi()
        assert result == {"FINISHED"}
        assert len(props.vertical_pvis) == 0


class TestClearPvis(NewIfc4X3):
    """Tests for CIVIL_OT_clear_pvis (civil.clear_pvis)."""

    def test_clear_pvis_removes_all(self):
        props = get_alignment_props()
        for _ in range(4):
            bpy.ops.civil.add_pvi()
        assert len(props.vertical_pvis) == 4

        result = bpy.ops.civil.clear_pvis()
        assert result == {"FINISHED"}
        assert len(props.vertical_pvis) == 0
        assert len(props.vertical_display_rows) == 0

    def test_clear_pvis_resets_indices(self):
        props = get_alignment_props()
        bpy.ops.civil.add_pvi()
        bpy.ops.civil.add_pvi()
        bpy.ops.civil.clear_pvis()
        assert props.active_pvi_index == 0
        assert props.active_vertical_display_row_index == 0


class TestAddVerticalToAlignment(NewIfc4X3):
    """Tests for CIVIL_OT_add_vertical_to_alignment (civil.add_vertical_to_alignment)."""

    def test_add_vertical_creates_vertical_layout(self):
        """Adding vertical to alignment creates IfcAlignmentVertical."""
        alignment, alignment_obj = create_empty_alignment()
        ifc_file = tool.Ifc.get()

        # Should not have a vertical layout yet
        verticals_before = ifc_file.by_type("IfcAlignmentVertical")
        assert len(verticals_before) == 0

        result = bpy.ops.civil.add_vertical_to_alignment()
        assert result == {"FINISHED"}

        verticals_after = ifc_file.by_type("IfcAlignmentVertical")
        assert len(verticals_after) == 1

    def test_add_vertical_twice_raises_on_poll(self):
        """Cannot add vertical if alignment already has one — poll raises RuntimeError."""
        alignment, alignment_obj = create_empty_alignment()

        # Add vertical (first time succeeds)
        bpy.ops.civil.add_vertical_to_alignment()

        # Second attempt should fail the poll and raise RuntimeError
        with pytest.raises(RuntimeError):
            bpy.ops.civil.add_vertical_to_alignment()


class TestDeleteVerticalLayout(NewIfc4X3):
    """Tests for CIVIL_OT_delete_vertical_layout (civil.delete_vertical_layout).

    add_vertical_to_alignment does not require the geometry engine (see
    TestAddVerticalToAlignment above, unmarked) — delete_vertical_layout
    mirrors it in reverse and likewise needs no geometry evaluation.

    Note: delete_vertical_layout defines invoke() with invoke_confirm, but
    calling via bpy.ops in Python uses EXEC_DEFAULT by default, skipping invoke.
    """

    def test_poll_fails_without_alignment(self):
        with pytest.raises(RuntimeError):
            bpy.ops.civil.delete_vertical_layout()

    def test_poll_fails_without_vertical_layout(self):
        alignment, alignment_obj = create_empty_alignment()
        with pytest.raises(RuntimeError):
            bpy.ops.civil.delete_vertical_layout()

    def test_delete_vertical_layout_removes_ifc_vertical(self):
        alignment, alignment_obj = create_empty_alignment()
        ifc_file = tool.Ifc.get()
        bpy.ops.civil.add_vertical_to_alignment()
        assert len(ifc_file.by_type("IfcAlignmentVertical")) == 1

        result = bpy.ops.civil.delete_vertical_layout()

        assert result == {"FINISHED"}
        assert len(ifc_file.by_type("IfcAlignmentVertical")) == 0

    def test_delete_vertical_layout_clears_pvi_table(self):
        alignment, alignment_obj = create_empty_alignment()
        bpy.ops.civil.add_vertical_to_alignment()
        props = get_alignment_props()
        bpy.ops.civil.add_pvi()
        bpy.ops.civil.add_pvi()

        bpy.ops.civil.delete_vertical_layout()

        assert len(props.vertical_pvis) == 0
        assert len(props.vertical_display_rows) == 0

    def test_horizontal_alignment_survives(self):
        alignment, alignment_obj = create_empty_alignment()
        ifc_file = tool.Ifc.get()
        bpy.ops.civil.add_vertical_to_alignment()

        bpy.ops.civil.delete_vertical_layout()

        assert len(ifc_file.by_type("IfcAlignment")) == 1
        assert len(ifc_file.by_type("IfcAlignmentHorizontal")) == 1


class TestSetPiCurveRadius(NewIfc4X3):
    """Tests for CIVIL_OT_set_pi_curve_radius (civil.set_pi_curve_radius).

    Bypasses full PI edit mode entry (which needs the geometry engine to
    back-calculate PIs from real IFC segments) by building PI edit empties
    directly and flipping is_pi_edit_mode — matching exactly what the
    sub-operator itself reads (get_pi_edit_empties + props.is_pi_edit_mode).
    """

    def _bare_pi_empties(self, alignment):
        pis = [
            {"e": 0.0, "n": 0.0, "radius": 0.0, "pi_type": "ENDPOINT"},
            {"e": 100.0, "n": 0.0, "radius": 0.0, "pi_type": "TANGENT"},
            {"e": 100.0, "n": 100.0, "radius": 0.0, "pi_type": "ENDPOINT"},
        ]
        return tool.Alignment.create_pi_edit_empties(alignment, pis)

    def test_sets_radius_and_marks_curve_type(self):
        alignment, alignment_obj = create_empty_alignment()
        self._bare_pi_empties(alignment)
        props = get_alignment_props()
        props.is_pi_edit_mode = True

        result = bpy.ops.civil.set_pi_curve_radius("EXEC_DEFAULT", alignment_id=alignment.id(), pi_index=1, radius=50.0)

        assert result == {"FINISHED"}
        empties = tool.Alignment.get_pi_edit_empties(alignment.id())
        assert empties[1].get("civil_pi_radius") == pytest.approx(50.0)
        assert empties[1].get("civil_pi_type") == "CURVE"

    def test_refuses_when_radius_too_large(self):
        """A refused fit reports {"ERROR"}, which bpy.ops raises as RuntimeError."""
        alignment, alignment_obj = create_empty_alignment()
        self._bare_pi_empties(alignment)
        props = get_alignment_props()
        props.is_pi_edit_mode = True

        with pytest.raises(RuntimeError):
            bpy.ops.civil.set_pi_curve_radius("EXEC_DEFAULT", alignment_id=alignment.id(), pi_index=1, radius=500.0)

        empties = tool.Alignment.get_pi_edit_empties(alignment.id())
        assert empties[1].get("civil_pi_radius") == 0.0

    def test_poll_fails_outside_pi_edit_mode(self):
        props = get_alignment_props()
        props.is_pi_edit_mode = False
        with pytest.raises(RuntimeError):
            bpy.ops.civil.set_pi_curve_radius("EXEC_DEFAULT", alignment_id=1, pi_index=0, radius=50.0)


# ===========================================================================
# Spiral Transitions & Compound/Reverse Curves (spec 1.5, 1.6)
# ===========================================================================


def _select_pi_row(props, pi_index):
    """Force _resolve_selected_interior_pi_index's active_pi_index fallback
    (mirrors TestRemovePi's pattern) so a test can select a PI without
    needing display_rows populated with the exact row it wants."""
    props.active_pi_index = pi_index
    props.display_rows.clear()


class TestSetPiSpiral(NewIfc4X3):
    """Tests for CIVIL_OT_set_pi_spiral (civil.set_pi_spiral) — spec 1.5.

    Writes props.pis only (no IFC write, no geometry engine) — exactly like
    the inline radius edit flow it extends — so these run ungated.
    """

    def _three_pis(self):
        add_pis_to_props([(0.0, 0.0, 0.0), (500.0, 0.0, 0.0), (500.0, 500.0, 0.0)])

    def test_writes_spiral_lengths_in_length_mode(self):
        create_empty_alignment()
        props = get_alignment_props()
        self._three_pis()
        _select_pi_row(props, 1)

        result = bpy.ops.civil.set_pi_spiral(
            "EXEC_DEFAULT",
            pi_index=1,
            radius=500.0,
            spiral_mode="LENGTH",
            spiral_in_length=150.0,
            spiral_out_length=150.0,
        )

        assert result == {"FINISHED"}
        assert props.pis[1].radius == pytest.approx(500.0)
        assert props.pis[1].spiral_mode == "LENGTH"
        assert props.pis[1].spiral_in_length == pytest.approx(150.0)
        assert props.pis[1].spiral_out_length == pytest.approx(150.0)

    def test_writes_spiral_lengths_derived_from_a_value(self):
        create_empty_alignment()
        props = get_alignment_props()
        self._three_pis()
        _select_pi_row(props, 1)

        # A=300, R=500 -> L=180 (golden worked example).
        result = bpy.ops.civil.set_pi_spiral(
            "EXEC_DEFAULT", pi_index=1, radius=500.0, spiral_mode="A_VALUE", spiral_a_in=300.0, spiral_a_out=300.0
        )

        assert result == {"FINISHED"}
        assert props.pis[1].spiral_mode == "A_VALUE"
        assert props.pis[1].spiral_in_length == pytest.approx(180.0)
        assert props.pis[1].spiral_out_length == pytest.approx(180.0)

    def test_rebuild_shows_spiral_and_curve_rows(self):
        create_empty_alignment()
        props = get_alignment_props()
        self._three_pis()
        _select_pi_row(props, 1)

        bpy.ops.civil.set_pi_spiral(
            "EXEC_DEFAULT",
            pi_index=1,
            radius=500.0,
            spiral_mode="LENGTH",
            spiral_in_length=150.0,
            spiral_out_length=150.0,
        )

        spiral_rows = [r for r in props.display_rows if r.display_type == "Spiral"]
        curve_rows = [r for r in props.display_rows if r.display_type == "Curve"]
        assert len(spiral_rows) == 2
        assert len(curve_rows) == 1

    def test_no_ifc_write(self):
        """props-level only — no real IFC segments are authored."""
        alignment, alignment_obj = create_empty_alignment()
        props = get_alignment_props()
        self._three_pis()
        _select_pi_row(props, 1)

        bpy.ops.civil.set_pi_spiral(
            "EXEC_DEFAULT",
            pi_index=1,
            radius=500.0,
            spiral_mode="LENGTH",
            spiral_in_length=150.0,
            spiral_out_length=150.0,
        )

        h_layout = align_api.get_horizontal_layout(alignment)
        segments = align_api.get_layout_segments(h_layout)
        assert all(tool.Alignment.is_zero_length_segment(s) for s in segments)

    def test_poll_fails_without_interior_pi_selected(self):
        create_empty_alignment()
        with pytest.raises(RuntimeError):
            bpy.ops.civil.set_pi_spiral("EXEC_DEFAULT")


class TestJoinCurvesUnjoinCurvesPoll(NewIfc4X3):
    """Poll-only tests for civil.join_curves / civil.unjoin_curves — no IFC
    write, so these run ungated."""

    def test_join_poll_fails_without_curve_at_selected_pi(self):
        create_empty_alignment()
        props = get_alignment_props()
        add_pis_to_props([(0.0, 0.0, 0.0), (500.0, 0.0, 0.0), (1000.0, 500.0, 0.0)])
        _select_pi_row(props, 1)
        with pytest.raises(RuntimeError):
            bpy.ops.civil.join_curves()

    def test_join_poll_fails_when_next_pi_has_no_curve(self):
        create_empty_alignment()
        props = get_alignment_props()
        add_pis_to_props([(0.0, 0.0, 0.0), (500.0, 0.0, 300.0), (1000.0, 500.0, 0.0), (1500.0, 500.0, 0.0)])
        _select_pi_row(props, 1)
        with pytest.raises(RuntimeError):
            bpy.ops.civil.join_curves()

    def test_join_poll_fails_when_already_joined(self):
        create_empty_alignment()
        props = get_alignment_props()
        add_pis_to_props([(0.0, 0.0, 0.0), (500.0, 0.0, 300.0), (1000.0, 500.0, 300.0), (1500.0, 500.0, 0.0)])
        props.pis[1].join_next = True
        _select_pi_row(props, 1)
        with pytest.raises(RuntimeError):
            bpy.ops.civil.join_curves()

    def test_unjoin_poll_fails_when_not_joined(self):
        create_empty_alignment()
        props = get_alignment_props()
        add_pis_to_props([(0.0, 0.0, 0.0), (500.0, 0.0, 300.0), (1000.0, 500.0, 300.0), (1500.0, 500.0, 0.0)])
        _select_pi_row(props, 1)
        with pytest.raises(RuntimeError):
            bpy.ops.civil.unjoin_curves()


@requires_geometry_engine
class TestJoinCurvesUnjoinCurves(NewIfc4X3):
    """End-to-end tests for CIVIL_OT_join_curves / CIVIL_OT_unjoin_curves —
    spec 1.6. Geometry-gated: the write path goes through
    _build_alignment_from_active_pis -> align_api.
    layout_horizontal_alignment_by_pi_method -> create_layout_segment,
    which needs the geometry engine (ENV LIMIT #9301). The pure
    solver-level refusal (no IFC, no geometry engine) is covered ungated in
    test/tool/test_alignment.py::TestJoinNextSolverRefusalPropagatesVerbatim,
    and poll-only behavior above in TestJoinCurvesUnjoinCurvesPoll.
    """

    def _symmetric_reverse_curve_pis(self, radius=300.0, deflection_deg=60.0):
        """A symmetric S-curve (reverse curve): PI1 turns left, PI2 turns
        right by the same angle, with the PI1-PI2 leg length chosen so both
        curves' (equal, symmetric) tangent claims sum EXACTLY to that leg —
        join_next should succeed with no intermediate tangent run."""
        delta = math.radians(deflection_deg)
        tangent = radius * math.tan(delta / 2.0)
        shared_leg = 2.0 * tangent

        pob = (0.0, 0.0, 0.0)
        pi1 = (1000.0, 0.0, radius)
        pi2_x = pi1[0] + shared_leg * math.cos(delta)
        pi2_y = pi1[1] + shared_leg * math.sin(delta)
        pi2 = (pi2_x, pi2_y, radius)
        poe = (pi2_x + 500.0, pi2_y, 0.0)
        return [pob, pi1, pi2, poe]

    def test_join_curves_succeeds_flag_and_junction_row(self):
        create_empty_alignment()
        props = get_alignment_props()
        add_pis_to_props(self._symmetric_reverse_curve_pis())
        bpy.ops.civil.recalculate_pis()

        _select_pi_row(props, 1)
        result = bpy.ops.civil.join_curves("EXEC_DEFAULT")

        assert result == {"FINISHED"}
        assert props.pis[1].join_next is True
        junction_rows = [r for r in props.display_rows if r.display_type in {"PCC", "PRC"}]
        assert len(junction_rows) == 1
        # PI1 turns left, PI2 turns right by the same angle -- opposite
        # directions -- a point of reverse curvature.
        assert junction_rows[0].display_type == "PRC"

    def test_join_curves_reverts_flag_on_solver_refusal(self):
        """PI2 far too close to PI1 for the requested radius -- the tangent
        closure check must fail, and join_next revert so the table matches
        what's actually in IFC."""
        alignment, alignment_obj = create_empty_alignment()
        ifc_file = tool.Ifc.get()
        props = get_alignment_props()
        pob, pi1, pi2, poe = self._symmetric_reverse_curve_pis()
        pi2_too_close = (pi1[0] + 5.0, pi1[1] + 5.0, pi2[2])
        add_pis_to_props([pob, pi1, pi2_too_close, poe])
        bpy.ops.civil.recalculate_pis()

        def _real_segment_count():
            return len(
                [s for s in ifc_file.by_type("IfcAlignmentSegment") if not tool.Alignment.is_zero_length_segment(s)]
            )

        count_before = _real_segment_count()

        _select_pi_row(props, 1)
        with pytest.raises(RuntimeError):
            bpy.ops.civil.join_curves("EXEC_DEFAULT")

        assert props.pis[1].join_next is False
        assert _real_segment_count() == count_before

    def test_unjoin_curves_clears_flag_and_junction_row(self):
        create_empty_alignment()
        props = get_alignment_props()
        add_pis_to_props(self._symmetric_reverse_curve_pis())
        bpy.ops.civil.recalculate_pis()
        _select_pi_row(props, 1)
        bpy.ops.civil.join_curves("EXEC_DEFAULT")
        assert props.pis[1].join_next is True

        _select_pi_row(props, 1)
        result = bpy.ops.civil.unjoin_curves("EXEC_DEFAULT")

        assert result == {"FINISHED"}
        assert props.pis[1].join_next is False
        junction_rows = [r for r in props.display_rows if r.display_type in {"PCC", "PRC"}]
        assert len(junction_rows) == 0


# ===========================================================================
# End-to-End Scenarios
# ===========================================================================


@requires_geometry_engine
class TestEndToEndAlignmentCreation(NewIfc4X3):
    """Full workflow: create alignment, add PIs, create IFC, validate."""

    def test_basic_three_pi_alignment_workflow(self):
        """Scenario 1: Create a basic 3-PI alignment end-to-end."""
        alignment, alignment_obj = create_empty_alignment("E2E Test Alignment")
        ifc_file = tool.Ifc.get()
        props = get_alignment_props()

        # Add 3 PIs: straight segment then angled
        add_pis_to_props([(0, 0, 0), (500, 0, 0), (1000, 200, 0)])
        assert len(props.pis) == 3

        # Create alignment
        result = bpy.ops.civil.create_alignment_by_pi()
        assert result == {"FINISHED"}

        # Validate IFC entities
        alignments = ifc_file.by_type("IfcAlignment")
        assert len(alignments) == 1
        assert alignments[0].Name == "E2E Test Alignment"

        horizontals = ifc_file.by_type("IfcAlignmentHorizontal")
        assert len(horizontals) == 1

        segments = ifc_file.by_type("IfcAlignmentSegment")
        # At minimum: tangent + tangent (+ zero-length terminator possibly)
        assert len(segments) >= 2

        # All segment design params should be IfcAlignmentHorizontalSegment
        for seg in segments:
            dp = seg.DesignParameters
            if dp:
                assert dp.is_a("IfcAlignmentHorizontalSegment")

    def test_three_pi_with_curve_workflow(self):
        """Scenario 2: 3-PI alignment with curve produces correct IFC segments."""
        alignment, alignment_obj = create_empty_alignment("Curved Alignment")
        ifc_file = tool.Ifc.get()
        props = get_alignment_props()

        # PI with 300m radius on middle point
        add_pis_to_props([(0, 0, 0), (500, 0, 300), (1000, 500, 0)])

        bpy.ops.civil.create_alignment_by_pi()

        segments = ifc_file.by_type("IfcAlignmentSegment")
        predefined_types = set()
        for seg in segments:
            dp = seg.DesignParameters
            if dp and hasattr(dp, "PredefinedType"):
                predefined_types.add(dp.PredefinedType)

        assert "LINE" in predefined_types
        assert "CIRCULARARC" in predefined_types

    def test_five_pi_complex_alignment(self):
        """Scenario 3: 5-PI alignment with multiple curves."""
        alignment, alignment_obj = create_empty_alignment("Complex Alignment")
        ifc_file = tool.Ifc.get()
        props = get_alignment_props()

        add_pis_to_props(
            [
                (0, 0, 0),
                (300, 0, 200),
                (600, 300, 150),
                (900, 300, 250),
                (1200, 0, 0),
            ]
        )

        result = bpy.ops.civil.create_alignment_by_pi()
        assert result == {"FINISHED"}

        segments = ifc_file.by_type("IfcAlignmentSegment")
        # 5 PIs with 3 interior curves → many segments
        assert len(segments) >= 4

    def test_add_remove_pi_cycle(self):
        """Scenario 4: Add/remove PIs cycle - props stay consistent."""
        props = get_alignment_props()

        bpy.ops.civil.add_pi()
        bpy.ops.civil.add_pi()
        bpy.ops.civil.add_pi()
        assert len(props.pis) == 3

        # Remove middle PI
        props.display_rows.clear()
        props.active_pi_index = 1
        bpy.ops.civil.remove_pi()
        assert len(props.pis) == 2

        # Add two more
        bpy.ops.civil.add_pi()
        bpy.ops.civil.add_pi()
        assert len(props.pis) == 4

        # Clear all
        bpy.ops.civil.clear_pis()
        assert len(props.pis) == 0
        assert len(props.display_rows) == 0

    def test_vertical_alignment_after_horizontal(self):
        """Scenario 5: Create horizontal, then add vertical layout."""
        alignment, alignment_obj = create_empty_alignment("H+V Alignment")
        ifc_file = tool.Ifc.get()
        props = get_alignment_props()

        # Create horizontal (PIs must not be collinear — upstream API divides by zero)
        add_pis_to_props([(0, 0, 0), (500, 200, 0), (1000, 0, 0)])
        bpy.ops.civil.create_alignment_by_pi()

        # Re-select alignment object
        bpy.context.view_layer.objects.active = alignment_obj
        alignment_obj.select_set(True)

        # Add vertical layout
        result = bpy.ops.civil.add_vertical_to_alignment()
        assert result == {"FINISHED"}

        # Verify both exist
        assert len(ifc_file.by_type("IfcAlignmentHorizontal")) == 1
        assert len(ifc_file.by_type("IfcAlignmentVertical")) == 1


@requires_geometry_engine
class TestEndToEndIfcRoundtrip(NewIfc4X3):
    """IFC save/reload roundtrip validation."""

    def test_alignment_survives_ifc_roundtrip(self):
        """Create alignment, save to temp file, reload, verify entities."""
        import tempfile
        import os

        alignment, alignment_obj = create_empty_alignment("Roundtrip Test")
        ifc_file = tool.Ifc.get()
        props = get_alignment_props()

        add_pis_to_props([(0, 0, 0), (500, 0, 300), (1000, 200, 0)])
        bpy.ops.civil.create_alignment_by_pi()

        # Count entities before save
        alignment_count = len(ifc_file.by_type("IfcAlignment"))
        horizontal_count = len(ifc_file.by_type("IfcAlignmentHorizontal"))
        segment_count = len(ifc_file.by_type("IfcAlignmentSegment"))

        assert alignment_count == 1
        assert horizontal_count == 1
        assert segment_count >= 2

        # Save to temp file
        temp_path = os.path.join(tempfile.gettempdir(), "alignment_roundtrip_test.ifc")
        ifc_file.write(temp_path)

        # Reload
        reloaded = ifcopenshell.open(temp_path)

        # Verify entity counts match
        assert len(reloaded.by_type("IfcAlignment")) == alignment_count
        assert len(reloaded.by_type("IfcAlignmentHorizontal")) == horizontal_count
        assert len(reloaded.by_type("IfcAlignmentSegment")) == segment_count

        # Verify alignment name survived
        assert reloaded.by_type("IfcAlignment")[0].Name == "Roundtrip Test"

        # Cleanup
        os.unlink(temp_path)


# Station formatting is tool-layer now (tool.Alignment.format_station wrapping
# ifcopenshell.util.alignment.station_as_string) — see TestFormatStation in
# test/tool/test_alignment.py.


@requires_geometry_engine
class TestImportAlignmentCsv(NewIfc4X3):
    """bim.import_alignment_csv — the single, merged CSV import path.

    CSV rows use full X,Y,R (or D,Z,L) triples: the first and last R/L values
    are placeholders per the API's create_from_csv contract.
    """

    def _write_csv(self, tmp_path, rows):
        path = tmp_path / "alignment.csv"
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        return str(path)

    def test_import_sets_active_alignment_and_builds_hierarchy(self, tmp_path):
        filepath = self._write_csv(tmp_path, ["0,0,0,1000,0,300,2000,800,0"])
        result = bpy.ops.bim.import_alignment_csv("EXEC_DEFAULT", filepath=filepath)
        assert result == {"FINISHED"}

        props = get_alignment_props()
        assert props.active_alignment_id != 0
        alignment = tool.Ifc.get().by_id(props.active_alignment_id)
        assert alignment.is_a("IfcAlignment")
        assert tool.Ifc.get_object(alignment) is not None

    def test_import_with_vertical_row_creates_vertical_layout(self, tmp_path):
        filepath = self._write_csv(
            tmp_path,
            [
                "0,0,0,1000,0,300,2000,800,0",
                "0,100,0,500,110,200,1000,105,0",
            ],
        )
        result = bpy.ops.bim.import_alignment_csv("EXEC_DEFAULT", filepath=filepath)
        assert result == {"FINISHED"}

        props = get_alignment_props()
        alignment = tool.Ifc.get().by_id(props.active_alignment_id)
        assert align_api.get_vertical_layout(alignment) is not None


class TestVerticalKFlags(NewIfc4X3):
    """Advisory AASHTO K flagging in the PVI table (spec 2.4). Pure props +
    math — no geometry engine required."""

    def _setup_metric_pvis(self, curve_length):
        import ifcopenshell.api.unit

        # Pin metric METRE units so the km/h K table governs.
        ifcopenshell.api.unit.assign_unit(tool.Ifc.get(), length={"is_metric": True, "raw": "METERS"})
        props = get_alignment_props()
        for i, (station, elevation) in enumerate(((0.0, 100.0), (500.0, 110.0), (1000.0, 100.0))):
            pvi = props.vertical_pvis.add()
            pvi.station = station
            pvi.elevation = elevation
            pvi.pvi_type = "ENDPOINT" if i in (0, 2) else "INTERIOR"
        props.vertical_pvis[1].curve_length = curve_length
        return props

    def test_short_crest_curve_is_flagged(self):
        from bonsai.bim.module.alignment.operator import rebuild_vertical_display_rows

        # Grades +2% / -2% (crest), K = L/A = 40/4 = 10 < 52 required at 100 km/h.
        props = self._setup_metric_pvis(curve_length=40.0)
        props.design_speed = 100.0
        rebuild_vertical_display_rows(props)

        pvi_rows = [r for r in props.vertical_display_rows if r.row_type == "POINT" and r.display_type == "PVI"]
        assert len(pvi_rows) == 1
        assert pvi_rows[0].k_deficient
        assert pvi_rows[0].k_required == pytest.approx(52.0)

    def test_adequate_curve_is_not_flagged(self):
        from bonsai.bim.module.alignment.operator import rebuild_vertical_display_rows

        # K = 400/4 = 100 >= 52 required at 100 km/h.
        props = self._setup_metric_pvis(curve_length=400.0)
        props.design_speed = 100.0
        rebuild_vertical_display_rows(props)

        pvi_rows = [r for r in props.vertical_display_rows if r.row_type == "POINT" and r.display_type == "PVI"]
        assert not pvi_rows[0].k_deficient

    def test_zero_design_speed_never_flags(self):
        from bonsai.bim.module.alignment.operator import rebuild_vertical_display_rows

        props = self._setup_metric_pvis(curve_length=40.0)
        props.design_speed = 0.0
        rebuild_vertical_display_rows(props)

        pvi_rows = [r for r in props.vertical_display_rows if r.row_type == "POINT" and r.display_type == "PVI"]
        assert not pvi_rows[0].k_deficient


# ===========================================================================
# Cant Operators (spec Section 3)
# ===========================================================================


def create_alignment_with_horizontal_and_vertical(name="Cant Test Alignment"):
    """Build an alignment with both horizontal and vertical layouts present
    (bare — zero-length terminators only), the minimum
    civil.add_cant_to_alignment's poll requires. Mirrors create_empty_alignment()
    + civil.add_vertical_to_alignment, neither of which needs the geometry
    engine (see TestAddVerticalToAlignment above)."""
    alignment, alignment_obj = create_empty_alignment(name)
    bpy.ops.civil.add_vertical_to_alignment()
    return alignment, alignment_obj


def add_cant_points_to_props(point_data):
    """Add cant points to the props collection with specified values.

    Args:
        point_data: list of (station, cant_left, cant_right, transition_type) tuples.
    """
    props = get_alignment_props()
    for station, cant_left, cant_right, transition_type in point_data:
        bpy.ops.civil.add_cant_point()
        point = props.cant_points[len(props.cant_points) - 1]
        point.station = station
        point.cant_left = cant_left
        point.cant_right = cant_right
        point.transition_type = transition_type


class TestAddCantToAlignment(NewIfc4X3):
    """Tests for CIVIL_OT_add_cant_to_alignment (civil.add_cant_to_alignment).

    add_cant_layout does not require the geometry engine — empirically
    confirmed (see tool/test_alignment.py's TestGetAddRemoveCantLayout and
    add_cant_layout's own defensive try/except around update_end_point).
    """

    def test_poll_fails_without_alignment(self):
        with pytest.raises(RuntimeError):
            bpy.ops.civil.add_cant_to_alignment()

    def test_poll_fails_without_vertical_layout(self):
        alignment, alignment_obj = create_empty_alignment()
        with pytest.raises(RuntimeError):
            bpy.ops.civil.add_cant_to_alignment()

    def test_add_cant_creates_cant_layout(self):
        alignment, alignment_obj = create_alignment_with_horizontal_and_vertical()
        ifc_file = tool.Ifc.get()
        assert len(ifc_file.by_type("IfcAlignmentCant")) == 0

        result = bpy.ops.civil.add_cant_to_alignment("EXEC_DEFAULT", rail_head_distance=1.75)
        assert result == {"FINISHED"}

        cants = ifc_file.by_type("IfcAlignmentCant")
        assert len(cants) == 1
        assert cants[0].RailHeadDistance == pytest.approx(1.75)

    def test_add_cant_twice_raises_on_poll(self):
        alignment, alignment_obj = create_alignment_with_horizontal_and_vertical()
        bpy.ops.civil.add_cant_to_alignment()
        with pytest.raises(RuntimeError):
            bpy.ops.civil.add_cant_to_alignment()

    def test_add_cant_persists_rotation_reference(self):
        alignment, alignment_obj = create_alignment_with_horizontal_and_vertical()
        props = get_alignment_props()
        # No cant layout exists yet, so the update callback is a no-op — it
        # only sets the Blender property value, which _execute() reads below.
        props.cant_rotation_reference = "HIGH_RAIL"

        bpy.ops.civil.add_cant_to_alignment()

        ifc_file = tool.Ifc.get()
        alignment_fresh = ifc_file.by_id(alignment.id())
        cant_layout = tool.Alignment.get_cant_layout(alignment_fresh)
        assert tool.Alignment.get_cant_rotation_reference(cant_layout) == "HIGH_RAIL"

    def test_add_cant_creates_outliner_object(self):
        alignment, alignment_obj = create_alignment_with_horizontal_and_vertical()
        bpy.ops.civil.add_cant_to_alignment()

        ifc_file = tool.Ifc.get()
        alignment_fresh = ifc_file.by_id(alignment.id())
        cant_layout = tool.Alignment.get_cant_layout(alignment_fresh)
        assert tool.Ifc.get_object(cant_layout) is not None

    def test_add_cant_clears_stale_table(self):
        alignment, alignment_obj = create_alignment_with_horizontal_and_vertical()
        props = get_alignment_props()
        bpy.ops.civil.add_cant_point()
        assert len(props.cant_points) == 1

        bpy.ops.civil.add_cant_to_alignment()

        assert len(props.cant_points) == 0
        assert len(props.cant_display_rows) == 0


class TestDeleteCantLayout(NewIfc4X3):
    """Tests for CIVIL_OT_delete_cant_layout (civil.delete_cant_layout).

    Note: delete_cant_layout defines invoke() with invoke_confirm, but
    calling via bpy.ops in Python uses EXEC_DEFAULT by default, skipping
    invoke (same as TestDeleteVerticalLayout above).
    """

    def test_poll_fails_without_alignment(self):
        with pytest.raises(RuntimeError):
            bpy.ops.civil.delete_cant_layout()

    def test_poll_fails_without_cant_layout(self):
        alignment, alignment_obj = create_alignment_with_horizontal_and_vertical()
        with pytest.raises(RuntimeError):
            bpy.ops.civil.delete_cant_layout()

    def test_delete_cant_layout_removes_ifc_cant(self):
        alignment, alignment_obj = create_alignment_with_horizontal_and_vertical()
        ifc_file = tool.Ifc.get()
        bpy.ops.civil.add_cant_to_alignment()
        assert len(ifc_file.by_type("IfcAlignmentCant")) == 1

        result = bpy.ops.civil.delete_cant_layout()

        assert result == {"FINISHED"}
        assert len(ifc_file.by_type("IfcAlignmentCant")) == 0

    def test_delete_cant_layout_clears_cant_table(self):
        alignment, alignment_obj = create_alignment_with_horizontal_and_vertical()
        bpy.ops.civil.add_cant_to_alignment()
        add_cant_points_to_props([(0.0, 0.0, 0.0, "LINEARTRANSITION"), (100.0, 0.0, 0.10, "LINEARTRANSITION")])
        props = get_alignment_props()
        assert len(props.cant_points) == 2

        bpy.ops.civil.delete_cant_layout()

        assert len(props.cant_points) == 0
        assert len(props.cant_display_rows) == 0

    def test_horizontal_and_vertical_survive(self):
        alignment, alignment_obj = create_alignment_with_horizontal_and_vertical()
        ifc_file = tool.Ifc.get()
        bpy.ops.civil.add_cant_to_alignment()

        bpy.ops.civil.delete_cant_layout()

        assert len(ifc_file.by_type("IfcAlignment")) == 1
        assert len(ifc_file.by_type("IfcAlignmentHorizontal")) == 1
        assert len(ifc_file.by_type("IfcAlignmentVertical")) == 1


class TestAddCantPoint(NewIfc4X3):
    """Tests for CIVIL_OT_add_cant_point (civil.add_cant_point)."""

    def test_add_first_point_at_origin(self):
        props = get_alignment_props()
        result = bpy.ops.civil.add_cant_point()
        assert result == {"FINISHED"}
        assert len(props.cant_points) == 1
        assert props.cant_points[0].station == pytest.approx(0.0)
        assert props.cant_points[0].transition_type == "LINEARTRANSITION"

    def test_add_second_point_extends_beyond_first(self):
        props = get_alignment_props()
        bpy.ops.civil.add_cant_point()
        bpy.ops.civil.add_cant_point()
        assert len(props.cant_points) == 2
        assert props.cant_points[1].station > props.cant_points[0].station

    def test_add_point_rebuilds_point_rows(self):
        props = get_alignment_props()
        bpy.ops.civil.add_cant_point()
        bpy.ops.civil.add_cant_point()
        point_rows = [r for r in props.cant_display_rows if r.row_type == "POINT"]
        assert len(point_rows) == 2


class TestRemoveCantPoint(NewIfc4X3):
    """Tests for CIVIL_OT_remove_cant_point (civil.remove_cant_point)."""

    def test_remove_point_decrements_collection(self):
        props = get_alignment_props()
        bpy.ops.civil.add_cant_point()
        bpy.ops.civil.add_cant_point()
        bpy.ops.civil.add_cant_point()
        assert len(props.cant_points) == 3

        props.cant_display_rows.clear()
        props.active_cant_point_index = 0
        result = bpy.ops.civil.remove_cant_point()
        assert result == {"FINISHED"}
        assert len(props.cant_points) == 2

    def test_remove_last_point(self):
        props = get_alignment_props()
        bpy.ops.civil.add_cant_point()
        props.cant_display_rows.clear()
        props.active_cant_point_index = 0
        result = bpy.ops.civil.remove_cant_point()
        assert result == {"FINISHED"}
        assert len(props.cant_points) == 0


class TestClearCantPoints(NewIfc4X3):
    """Tests for CIVIL_OT_clear_cant_points (civil.clear_cant_points)."""

    def test_clear_removes_all_points_but_not_layout(self):
        alignment, alignment_obj = create_alignment_with_horizontal_and_vertical()
        bpy.ops.civil.add_cant_to_alignment()
        add_cant_points_to_props([(0.0, 0.0, 0.0, "LINEARTRANSITION"), (100.0, 0.0, 0.10, "LINEARTRANSITION")])
        props = get_alignment_props()
        ifc_file = tool.Ifc.get()

        result = bpy.ops.civil.clear_cant_points()

        assert result == {"FINISHED"}
        assert len(props.cant_points) == 0
        assert len(props.cant_display_rows) == 0
        # Rows-only clear (spec 3.2) — the cant layout itself is untouched.
        assert len(ifc_file.by_type("IfcAlignmentCant")) == 1


@requires_geometry_engine
class TestRecalculateCant(NewIfc4X3):
    """Tests for CIVIL_OT_recalculate_cant (civil.recalculate_cant) — spec
    Section 3 end to end: add cant -> table edit -> recalculate -> IFC
    segments exist.

    Gated: recalculate_cant writes IFC segments via
    ifcopenshell.api.alignment.create_layout_segment, which (via
    _add_segment_to_layout -> _get_segment_endpoint) needs the geometry
    engine even for a purely semantic write — see the note atop
    TestWriteCantSegments in test/tool/test_alignment.py.
    """

    def test_recalculate_writes_cant_segments(self):
        alignment, alignment_obj = create_alignment_with_horizontal_and_vertical("Recalc Cant")
        bpy.ops.civil.add_cant_to_alignment()
        add_cant_points_to_props(
            [
                (0.0, 0.0, 0.0, "LINEARTRANSITION"),
                (100.0, 0.0, 0.15, "LINEARTRANSITION"),
            ]
        )

        result = bpy.ops.civil.recalculate_cant()
        assert result == {"FINISHED"}

        ifc_file = tool.Ifc.get()
        alignment_fresh = ifc_file.by_id(alignment.id())
        cant_layout = tool.Alignment.get_cant_layout(alignment_fresh)
        segments = align_api.get_layout_segments(cant_layout)
        real_segments = [s for s in segments if not tool.Alignment.is_zero_length_segment(s)]
        assert len(real_segments) == 1
        dp = real_segments[0].DesignParameters
        assert dp.StartDistAlong == pytest.approx(0.0)
        assert dp.HorizontalLength == pytest.approx(100.0)
        assert dp.EndCantRight == pytest.approx(0.15)
        assert dp.PredefinedType == "LINEARTRANSITION"

    def test_recalculate_creates_segment_objects(self):
        alignment, alignment_obj = create_alignment_with_horizontal_and_vertical("Recalc Cant Objs")
        bpy.ops.civil.add_cant_to_alignment()
        add_cant_points_to_props(
            [
                (0.0, 0.0, 0.0, "LINEARTRANSITION"),
                (100.0, 0.0, 0.10, "LINEARTRANSITION"),
            ]
        )

        bpy.ops.civil.recalculate_cant()

        ifc_file = tool.Ifc.get()
        alignment_fresh = ifc_file.by_id(alignment.id())
        cant_layout = tool.Alignment.get_cant_layout(alignment_fresh)
        assert tool.Ifc.get_object(cant_layout) is not None

    def test_recalculate_rewrites_on_second_call(self):
        alignment, alignment_obj = create_alignment_with_horizontal_and_vertical("Recalc Cant Rewrite")
        bpy.ops.civil.add_cant_to_alignment()
        add_cant_points_to_props(
            [
                (0.0, 0.0, 0.0, "LINEARTRANSITION"),
                (100.0, 0.0, 0.10, "LINEARTRANSITION"),
                (200.0, 0.0, 0.0, "LINEARTRANSITION"),
            ]
        )
        bpy.ops.civil.recalculate_cant()

        props = get_alignment_props()
        props.cant_points.clear()
        props.cant_display_rows.clear()
        add_cant_points_to_props([(0.0, 0.0, 0.0, "LINEARTRANSITION"), (50.0, 0.0, 0.05, "LINEARTRANSITION")])
        bpy.ops.civil.recalculate_cant()

        ifc_file = tool.Ifc.get()
        alignment_fresh = ifc_file.by_id(alignment.id())
        cant_layout = tool.Alignment.get_cant_layout(alignment_fresh)
        segments = align_api.get_layout_segments(cant_layout)
        real_segments = [s for s in segments if not tool.Alignment.is_zero_length_segment(s)]
        assert len(real_segments) == 1
        assert real_segments[0].DesignParameters.HorizontalLength == pytest.approx(50.0)


# ===========================================================================
# Stationing Referents (spec Section 4)
# ===========================================================================


@requires_geometry_engine
class TestAddStationingReferent(NewIfc4X3):
    """Tests for CIVIL_OT_add_stationing_referent (civil.add_stationing_referent).

    Gated: ifcopenshell.api.alignment.add_stationing_referent calls
    update_fallback_position, which (via ifcopenshell.util.placement.
    get_local_placement -> ifcopenshell.geom.create_shape) needs the
    geometry engine whenever the alignment's curve already has real
    geometry — true even for the bare create_empty_alignment() fixture,
    since align_api.create() always builds a zero-length-terminator
    representation. See TestAddEventReferent below for the one referent
    kind that stays ungated (spec 4.4's add_event_referent deliberately
    skips that call).
    """

    def test_add_stationing_referent_syncs_referent_list(self):
        alignment, alignment_obj = create_empty_alignment("StaRef")
        props = get_alignment_props()
        props.start_station = 0.0

        result = bpy.ops.civil.add_stationing_referent(station=150.0, name="Test Ref")

        assert result == {"FINISHED"}
        assert len(props.referents) >= 1
        assert any(r.referent_name == "Test Ref" for r in props.referents)
        # And it is genuinely on IFC, not just the UI mirror.
        ifc_file = tool.Ifc.get()
        alignment_fresh = ifc_file.by_id(alignment.id())
        assert any(r["name"] == "Test Ref" for r in tool.Alignment.get_referents(alignment_fresh))


@requires_geometry_engine
class TestAddStationEquationOperator(NewIfc4X3):
    """Tests for CIVIL_OT_add_station_equation (civil.add_station_equation) —
    spec 4.3.

    Gated for the same reason as TestAddStationingReferent above:
    add_station_equation_referent is a thin wrapper over
    align_api.add_stationing_referent.
    """

    def test_add_station_equation_shows_equation_marker_in_referent_list(self):
        alignment, alignment_obj = create_empty_alignment("EqnTest")
        props = get_alignment_props()
        props.start_station = 0.0

        result = bpy.ops.civil.add_station_equation(back_station=100.0, ahead_station=300.0)

        assert result == {"FINISHED"}
        equation_items = [r for r in props.referents if r.is_equation]
        assert len(equation_items) == 1
        assert equation_items[0].incoming_station == pytest.approx(100.0)
        assert equation_items[0].station == pytest.approx(300.0)

    def test_add_station_equation_rejects_equal_back_and_ahead(self):
        alignment, alignment_obj = create_empty_alignment("EqnBad")
        props = get_alignment_props()
        props.start_station = 0.0

        result = bpy.ops.civil.add_station_equation(back_station=100.0, ahead_station=100.0)

        # core.add_station_equation raises ValueError -> operator reports
        # an error and cancels rather than authoring a no-op equation.
        assert result == {"CANCELLED"}
        assert not any(r.is_equation for r in props.referents)


class TestAddEventReferentOperator(NewIfc4X3):
    """Tests for CIVIL_OT_add_event_referent (civil.add_event_referent) —
    spec 4.4. Semantic authoring: NOT gated behind @requires_geometry_engine
    (see tool.Alignment.add_event_referent's comment on why it skips
    update_fallback_position)."""

    def test_add_event_referent_creates_entity_and_syncs_list(self):
        import ifcopenshell.util.element

        alignment, alignment_obj = create_empty_alignment("EventTest")
        props = get_alignment_props()

        result = bpy.ops.civil.add_event_referent(
            event_type="WIDTHEVENT", station=150.0, name="Widen Here", use_value=True, value=3.6
        )

        assert result == {"FINISHED"}
        # create_empty_alignment() -> align_api.create() already seeds one
        # default STATION referent at start_station -- the event referent
        # is the second entry.
        assert len(props.referents) == 2
        item = next(r for r in props.referents if r.predefined_type == "WIDTHEVENT")
        assert item.referent_name == "Widen Here"
        assert item.has_station
        assert item.station == pytest.approx(150.0)

        ifc_file = tool.Ifc.get()
        alignment_fresh = ifc_file.by_id(alignment.id())
        referents = [r for r in ifc_file.by_type("IfcReferent") if r.PredefinedType == "WIDTHEVENT"]
        assert len(referents) == 1
        assert ifcopenshell.util.element.get_pset(referents[0], "Pset_SaikeiEvent")["Value"] == pytest.approx(3.6)

    def test_add_event_referent_without_value_omits_saikei_event_pset(self):
        import ifcopenshell.util.element

        create_empty_alignment("EventNoValue")

        result = bpy.ops.civil.add_event_referent(event_type="SUPERELEVATIONEVENT", station=75.0, use_value=False)

        assert result == {"FINISHED"}
        ifc_file = tool.Ifc.get()
        referent = next(r for r in ifc_file.by_type("IfcReferent") if r.PredefinedType == "SUPERELEVATIONEVENT")
        assert ifcopenshell.util.element.get_pset(referent, "Pset_SaikeiEvent") is None


class TestRemoveReferent(NewIfc4X3):
    """Tests for CIVIL_OT_remove_referent (civil.remove_referent) — spec
    4.1 ("Deletable"). Seeds referents via the semantic add_event_referent
    tool method directly rather than through the geometry-gated stationing
    operators, so removal itself can be tested without the engine."""

    def test_remove_referent_deletes_entity_and_resyncs_list(self):
        alignment, alignment_obj = create_empty_alignment("RemoveMe")
        tool.Alignment.add_event_referent(alignment, "SUPERELEVATIONEVENT", 100.0)
        props = get_alignment_props()
        bpy.ops.civil.refresh_referent_list()
        # create_empty_alignment() -> align_api.create() already seeds one
        # default STATION referent at station 0.0; sorted ahead of the
        # SUPERELEVATIONEVENT referent at station 100.0.
        assert len(props.referents) == 2
        equation_index = next(i for i, r in enumerate(props.referents) if r.predefined_type == "SUPERELEVATIONEVENT")
        props.active_referent_index = equation_index

        result = bpy.ops.civil.remove_referent()

        assert result == {"FINISHED"}
        assert len(props.referents) == 1
        assert props.referents[0].predefined_type == "STATION"
        ifc_file = tool.Ifc.get()
        alignment_fresh = ifc_file.by_id(alignment.id())
        remaining = tool.Alignment.get_referents(alignment_fresh)
        assert all(r["predefined_type"] != "SUPERELEVATIONEVENT" for r in remaining)

    def test_remove_referent_poll_fails_when_nothing_selected(self):
        create_empty_alignment("NothingSelected")
        assert bpy.ops.civil.remove_referent.poll() is False


class TestRefreshReferentList(NewIfc4X3):
    """Tests for CIVIL_OT_refresh_referent_list (civil.refresh_referent_list)."""

    def test_refresh_populates_referent_list_from_ifc(self):
        alignment, alignment_obj = create_empty_alignment("RefreshMe")
        tool.Alignment.add_event_referent(alignment, "WIDTHEVENT", 200.0)
        props = get_alignment_props()
        assert len(props.referents) == 0  # not yet synced

        result = bpy.ops.civil.refresh_referent_list()

        assert result == {"FINISHED"}
        # create_empty_alignment() -> align_api.create() already seeds one
        # default STATION referent; the WIDTHEVENT referent is the second.
        assert len(props.referents) == 2

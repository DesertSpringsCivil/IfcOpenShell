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

import pytest

import bonsai.core.alignment as subject
from test.core.bootstrap import alignment, ifc

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeIfcEntity(dict):
    """A JSON-serializable stand-in for an IFC entity.

    Inherits from dict so json.dumps can serialize it when it appears as an
    argument to Prophecy-tracked tool methods.  The ifc_class key drives
    is_a(), and the name key drives the Name property.
    """

    def is_a(self, ifc_class: str) -> bool:
        return self.get("ifc_class") == ifc_class

    @property
    def Name(self) -> str:
        return self.get("name", "Test Entity")


class FakeIfcFile:
    """Minimal stand-in for an open IFC file."""

    def __init__(self, entity=None, not_found: bool = False):
        self._entity = entity
        self._not_found = not_found

    def by_id(self, entity_id: int):
        if self._not_found:
            raise RuntimeError(f"Could not find #{entity_id}")
        return self._entity


def make_alignment_entity(name: str = "Test Alignment") -> FakeIfcEntity:
    return FakeIfcEntity({"ifc_class": "IfcAlignment", "name": name})


def make_non_alignment_entity(name: str = "Wall") -> FakeIfcEntity:
    return FakeIfcEntity({"ifc_class": "IfcWall", "name": name})


# ---------------------------------------------------------------------------
# enter_pi_edit_mode
# ---------------------------------------------------------------------------


class TestEnterPiEditMode:
    def test_raises_when_no_ifc_file_loaded(self, ifc, alignment):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.enter_pi_edit_mode(ifc, alignment, alignment_id=1)

    def test_raises_when_alignment_not_found(self, ifc, alignment):
        ifc.get().should_be_called().will_return(FakeIfcFile(not_found=True))
        with pytest.raises(ValueError, match="not found"):
            subject.enter_pi_edit_mode(ifc, alignment, alignment_id=1)

    def test_raises_when_entity_is_not_an_alignment(self, ifc, alignment):
        entity = make_non_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        with pytest.raises(ValueError, match="not an IfcAlignment"):
            subject.enter_pi_edit_mode(ifc, alignment, alignment_id=1)

    def test_raises_when_alignment_has_no_horizontal_layout(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_horizontal_layout(entity).should_be_called().will_return(None)
        with pytest.raises(ValueError, match="no horizontal layout"):
            subject.enter_pi_edit_mode(ifc, alignment, alignment_id=1)

    def test_raises_when_alignment_has_no_real_segments(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_horizontal_layout(entity).should_be_called().will_return("h_layout")
        alignment.layout_has_real_segments("h_layout").should_be_called().will_return(False)
        with pytest.raises(ValueError, match="no editable segments"):
            subject.enter_pi_edit_mode(ifc, alignment, alignment_id=1)

    def test_raises_when_back_calculated_pis_fewer_than_two(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_horizontal_layout(entity).should_be_called().will_return("h_layout")
        alignment.layout_has_real_segments("h_layout").should_be_called().will_return(True)
        alignment.back_calculate_pis_from_alignment(entity).should_be_called().will_return([(0.0, 0.0)])
        with pytest.raises(ValueError, match="at least 2 PIs"):
            subject.enter_pi_edit_mode(ifc, alignment, alignment_id=1)

    def test_returns_empties_for_valid_alignment(self, ifc, alignment):
        entity = make_alignment_entity()
        pis = [(0.0, 0.0), (100.0, 0.0), (200.0, 50.0)]
        empties = ["empty_0", "empty_1", "empty_2"]
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_horizontal_layout(entity).should_be_called().will_return("h_layout")
        alignment.layout_has_real_segments("h_layout").should_be_called().will_return(True)
        alignment.back_calculate_pis_from_alignment(entity).should_be_called().will_return(pis)
        alignment.create_pi_edit_empties(entity, pis).should_be_called().will_return(empties)
        result = subject.enter_pi_edit_mode(ifc, alignment, alignment_id=1)
        assert result == empties


# ---------------------------------------------------------------------------
# exit_pi_edit_mode
# ---------------------------------------------------------------------------


class TestExitPiEditMode:
    def test_cleans_up_and_returns_true_when_no_ifc_file(self, ifc, alignment):
        ifc.get().should_be_called().will_return(None)
        alignment.remove_pi_edit_empties(1).should_be_called()
        result = subject.exit_pi_edit_mode(ifc, alignment, alignment_id=1, apply=True)
        assert result is True

    def test_cleans_up_and_returns_true_when_alignment_deleted(self, ifc, alignment):
        ifc.get().should_be_called().will_return(FakeIfcFile(not_found=True))
        alignment.remove_pi_edit_empties(1).should_be_called()
        result = subject.exit_pi_edit_mode(ifc, alignment, alignment_id=1, apply=True)
        assert result is True

    def test_removes_empties_and_returns_true_when_apply_is_false(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.remove_pi_edit_empties(1).should_be_called()
        result = subject.exit_pi_edit_mode(ifc, alignment, alignment_id=1, apply=False)
        assert result is True

    def test_raises_when_fewer_than_two_pis_collected_on_apply(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.collect_pis_from_empties(1).should_be_called().will_return(([(0.0, 0.0)], [0.0]))
        with pytest.raises(ValueError, match="At least 2 PIs"):
            subject.exit_pi_edit_mode(ifc, alignment, alignment_id=1, apply=True)

    def test_raises_when_no_horizontal_layout_on_apply(self, ifc, alignment):
        entity = make_alignment_entity()
        hpoints = [(0.0, 0.0), (100.0, 0.0)]
        radii = [0.0, 0.0]
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.collect_pis_from_empties(1).should_be_called().will_return((hpoints, radii))
        alignment.get_horizontal_layout(entity).should_be_called().will_return(None)
        with pytest.raises(ValueError, match="no horizontal layout"):
            subject.exit_pi_edit_mode(ifc, alignment, alignment_id=1, apply=True)

    def test_applies_new_pis_without_layout_obj_and_returns_true(self, ifc, alignment):
        entity = make_alignment_entity()
        hpoints = [(0.0, 0.0), (100.0, 0.0)]
        radii = [0.0, 0.0]
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.collect_pis_from_empties(1).should_be_called().will_return((hpoints, radii))
        alignment.get_horizontal_layout(entity).should_be_called().will_return("h_layout")
        alignment.remove_pi_edit_empties(1).should_be_called()
        alignment.remove_layout_segment_objects("h_layout").should_be_called()
        alignment.clear_layout_segments("h_layout").should_be_called()
        alignment.layout_by_pi_method("h_layout", hpoints, radii).should_be_called()
        ifc.get_object("h_layout").should_be_called().will_return(None)
        alignment.commit_layout_change(entity).should_be_called()
        result = subject.exit_pi_edit_mode(ifc, alignment, alignment_id=1, apply=True)
        assert result is True

    def test_creates_segment_objects_when_layout_obj_exists(self, ifc, alignment):
        entity = make_alignment_entity()
        hpoints = [(0.0, 0.0), (100.0, 0.0)]
        radii = [0.0, 0.0]
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.collect_pis_from_empties(1).should_be_called().will_return((hpoints, radii))
        alignment.get_horizontal_layout(entity).should_be_called().will_return("h_layout")
        alignment.remove_pi_edit_empties(1).should_be_called()
        alignment.remove_layout_segment_objects("h_layout").should_be_called()
        alignment.clear_layout_segments("h_layout").should_be_called()
        alignment.layout_by_pi_method("h_layout", hpoints, radii).should_be_called()
        ifc.get_object("h_layout").should_be_called().will_return("layout_obj")
        alignment.create_objects_for_layout_segments("h_layout", "layout_obj").should_be_called()
        alignment.commit_layout_change(entity).should_be_called()
        result = subject.exit_pi_edit_mode(ifc, alignment, alignment_id=1, apply=True)
        assert result is True


# ---------------------------------------------------------------------------
# add_vertical_to_alignment
# ---------------------------------------------------------------------------


class TestImportAlignmentCsv:
    def test_raises_when_no_ifc_file_loaded(self, ifc, alignment):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.import_alignment_csv(ifc, alignment, filepath="pis.csv")

    def test_imports_and_builds_hierarchy_for_parent_only(self, ifc, alignment):
        ifc.get().should_be_called().will_return("ifc_file")
        alignment.create_alignment_from_csv("pis.csv").should_be_called().will_return("parent")
        alignment.create_hierarchy_for_alignment("parent").should_be_called()
        alignment.get_child_alignments("parent").should_be_called().will_return([])
        alignment.create_objects_for_referents("parent").should_be_called()
        result = subject.import_alignment_csv(ifc, alignment, filepath="pis.csv")
        assert result == "parent"

    def test_builds_hierarchy_for_each_aggregated_child(self, ifc, alignment):
        ifc.get().should_be_called().will_return("ifc_file")
        alignment.create_alignment_from_csv("pis.csv").should_be_called().will_return("parent")
        alignment.create_hierarchy_for_alignment("parent").should_be_called()
        alignment.get_child_alignments("parent").should_be_called().will_return(["child_a", "child_b"])
        alignment.create_hierarchy_for_alignment("child_a").should_be_called()
        alignment.create_hierarchy_for_alignment("child_b").should_be_called()
        alignment.create_objects_for_referents("parent").should_be_called()
        result = subject.import_alignment_csv(ifc, alignment, filepath="pis.csv")
        assert result == "parent"


class TestAddVerticalToAlignment:
    def test_raises_when_no_ifc_file_loaded(self, ifc, alignment):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.add_vertical_to_alignment(ifc, alignment, alignment_id=1)

    def test_raises_when_alignment_not_found(self, ifc, alignment):
        ifc.get().should_be_called().will_return(FakeIfcFile(not_found=True))
        with pytest.raises(ValueError, match="not found"):
            subject.add_vertical_to_alignment(ifc, alignment, alignment_id=1)

    def test_raises_when_entity_is_not_an_alignment(self, ifc, alignment):
        entity = make_non_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        with pytest.raises(ValueError, match="not an IfcAlignment"):
            subject.add_vertical_to_alignment(ifc, alignment, alignment_id=1)

    def test_raises_when_no_horizontal_layout_exists(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_horizontal_layout(entity).should_be_called().will_return(None)
        with pytest.raises(ValueError, match="no horizontal layout"):
            subject.add_vertical_to_alignment(ifc, alignment, alignment_id=1)

    def test_raises_when_vertical_layout_already_exists(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_horizontal_layout(entity).should_be_called().will_return("h_layout")
        alignment.get_vertical_layout(entity).should_be_called().will_return("v_layout")
        with pytest.raises(ValueError, match="already has a vertical layout"):
            subject.add_vertical_to_alignment(ifc, alignment, alignment_id=1)

    def test_creates_and_returns_vertical_layout(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_horizontal_layout(entity).should_be_called().will_return("h_layout")
        alignment.get_vertical_layout(entity).should_be_called().will_return(None)
        alignment.add_vertical_layout(entity).should_be_called().will_return("new_v_layout")
        result = subject.add_vertical_to_alignment(ifc, alignment, alignment_id=1)
        assert result == "new_v_layout"


# ---------------------------------------------------------------------------
# enter_pvi_edit_mode
# ---------------------------------------------------------------------------


class TestEnterPviEditMode:
    def test_raises_when_no_ifc_file_loaded(self, ifc, alignment):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.enter_pvi_edit_mode(ifc, alignment, alignment_id=1)

    def test_raises_when_alignment_not_found(self, ifc, alignment):
        ifc.get().should_be_called().will_return(FakeIfcFile(not_found=True))
        with pytest.raises(ValueError, match="not found"):
            subject.enter_pvi_edit_mode(ifc, alignment, alignment_id=1)

    def test_raises_when_entity_is_not_an_alignment(self, ifc, alignment):
        entity = make_non_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        with pytest.raises(ValueError, match="not an IfcAlignment"):
            subject.enter_pvi_edit_mode(ifc, alignment, alignment_id=1)

    def test_raises_when_alignment_has_no_vertical_layout(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_vertical_layout(entity).should_be_called().will_return(None)
        with pytest.raises(ValueError, match="no vertical layout"):
            subject.enter_pvi_edit_mode(ifc, alignment, alignment_id=1)

    def test_raises_when_vertical_layout_has_no_real_segments(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_vertical_layout(entity).should_be_called().will_return("v_layout")
        alignment.layout_has_real_segments("v_layout").should_be_called().will_return(False)
        with pytest.raises(ValueError, match="no editable vertical segments"):
            subject.enter_pvi_edit_mode(ifc, alignment, alignment_id=1)

    def test_raises_when_fewer_than_two_pvis(self, ifc, alignment):
        entity = make_alignment_entity()
        pvis = [{"station": 0.0, "elevation": 100.0, "curve_length": 0.0}]
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_vertical_layout(entity).should_be_called().will_return("v_layout")
        alignment.layout_has_real_segments("v_layout").should_be_called().will_return(True)
        alignment.back_calculate_pvis_from_vertical(entity).should_be_called().will_return(pvis)
        with pytest.raises(ValueError, match="at least 2 PVIs"):
            subject.enter_pvi_edit_mode(ifc, alignment, alignment_id=1)

    def test_returns_empties_for_valid_vertical_alignment(self, ifc, alignment):
        entity = make_alignment_entity()
        pvis = [
            {"station": 0.0, "elevation": 100.0, "curve_length": 0.0},
            {"station": 500.0, "elevation": 110.0, "curve_length": 0.0},
        ]
        empties = ["pvi_empty_0", "pvi_empty_1"]
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_vertical_layout(entity).should_be_called().will_return("v_layout")
        alignment.layout_has_real_segments("v_layout").should_be_called().will_return(True)
        alignment.back_calculate_pvis_from_vertical(entity).should_be_called().will_return(pvis)
        alignment.create_pvi_edit_empties(entity, pvis).should_be_called().will_return(empties)
        result = subject.enter_pvi_edit_mode(ifc, alignment, alignment_id=1)
        assert result == empties


# ---------------------------------------------------------------------------
# exit_pvi_edit_mode
# ---------------------------------------------------------------------------


class TestExitPviEditMode:
    def test_cleans_up_and_returns_true_when_no_ifc_file(self, ifc, alignment):
        ifc.get().should_be_called().will_return(None)
        alignment.remove_pvi_edit_empties(1).should_be_called()
        result = subject.exit_pvi_edit_mode(ifc, alignment, alignment_id=1, apply=True)
        assert result is True

    def test_cleans_up_and_returns_true_when_alignment_deleted(self, ifc, alignment):
        ifc.get().should_be_called().will_return(FakeIfcFile(not_found=True))
        alignment.remove_pvi_edit_empties(1).should_be_called()
        result = subject.exit_pvi_edit_mode(ifc, alignment, alignment_id=1, apply=True)
        assert result is True

    def test_removes_empties_without_apply(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.remove_pvi_edit_empties(1).should_be_called()
        result = subject.exit_pvi_edit_mode(ifc, alignment, alignment_id=1, apply=False)
        assert result is True

    def test_raises_when_fewer_than_two_vpoints_on_apply(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.collect_pvis_from_empties_vertical(1).should_be_called().will_return(([(0.0, 100.0)], []))
        with pytest.raises(ValueError, match="At least 2 PVIs"):
            subject.exit_pvi_edit_mode(ifc, alignment, alignment_id=1, apply=True)

    def test_raises_when_no_vertical_layout_on_apply(self, ifc, alignment):
        entity = make_alignment_entity()
        vpoints = [(0.0, 100.0), (500.0, 110.0)]
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.collect_pvis_from_empties_vertical(1).should_be_called().will_return((vpoints, []))
        alignment.get_vertical_layout(entity).should_be_called().will_return(None)
        with pytest.raises(ValueError, match="no vertical layout"):
            subject.exit_pvi_edit_mode(ifc, alignment, alignment_id=1, apply=True)

    def test_applies_new_pvis_without_layout_obj(self, ifc, alignment):
        entity = make_alignment_entity()
        vpoints = [(0.0, 100.0), (500.0, 110.0)]
        lengths = []
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.collect_pvis_from_empties_vertical(1).should_be_called().will_return((vpoints, lengths))
        alignment.get_vertical_layout(entity).should_be_called().will_return("v_layout")
        alignment.remove_pvi_edit_empties(1).should_be_called()
        alignment.remove_layout_segment_objects("v_layout").should_be_called()
        alignment.clear_layout_segments("v_layout").should_be_called()
        alignment.layout_vertical_by_pvi_method("v_layout", vpoints, lengths).should_be_called()
        ifc.get_object("v_layout").should_be_called().will_return(None)
        alignment.commit_layout_change(entity).should_be_called()
        result = subject.exit_pvi_edit_mode(ifc, alignment, alignment_id=1, apply=True)
        assert result is True

    def test_creates_segment_objects_when_layout_obj_exists(self, ifc, alignment):
        entity = make_alignment_entity()
        vpoints = [(0.0, 100.0), (500.0, 110.0)]
        lengths = []
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.collect_pvis_from_empties_vertical(1).should_be_called().will_return((vpoints, lengths))
        alignment.get_vertical_layout(entity).should_be_called().will_return("v_layout")
        alignment.remove_pvi_edit_empties(1).should_be_called()
        alignment.remove_layout_segment_objects("v_layout").should_be_called()
        alignment.clear_layout_segments("v_layout").should_be_called()
        alignment.layout_vertical_by_pvi_method("v_layout", vpoints, lengths).should_be_called()
        ifc.get_object("v_layout").should_be_called().will_return("layout_obj")
        alignment.create_objects_for_layout_segments("v_layout", "layout_obj").should_be_called()
        alignment.commit_layout_change(entity).should_be_called()
        result = subject.exit_pvi_edit_mode(ifc, alignment, alignment_id=1, apply=True)
        assert result is True


# ---------------------------------------------------------------------------
# evaluate_alignment_at_station  (D3 keystone)
# ---------------------------------------------------------------------------


class TestEvaluateAlignmentAtStation:
    def test_raises_when_no_ifc_file_loaded(self, ifc, alignment):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.evaluate_alignment_at_station(ifc, alignment, alignment_id=1, station=100.0)

    def test_raises_when_alignment_not_found(self, ifc, alignment):
        ifc.get().should_be_called().will_return(FakeIfcFile(not_found=True))
        with pytest.raises(ValueError, match="not found"):
            subject.evaluate_alignment_at_station(ifc, alignment, alignment_id=1, station=100.0)

    def test_raises_when_entity_is_not_an_alignment(self, ifc, alignment):
        entity = make_non_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        with pytest.raises(ValueError, match="not an IfcAlignment"):
            subject.evaluate_alignment_at_station(ifc, alignment, alignment_id=1, station=100.0)

    def test_delegates_to_tool_and_returns_result(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.evaluate_alignment_at_station(entity, 100.0).should_be_called().will_return("point")
        result = subject.evaluate_alignment_at_station(ifc, alignment, alignment_id=1, station=100.0)
        assert result == "point"


# ---------------------------------------------------------------------------
# visualize_3d_alignment  (D3 — draped 3D centerline)
# ---------------------------------------------------------------------------


class TestVisualize3dAlignment:
    def test_raises_when_no_ifc_file_loaded(self, ifc, alignment):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.visualize_3d_alignment(ifc, alignment, alignment_id=1)

    def test_raises_when_entity_is_not_an_alignment(self, ifc, alignment):
        entity = make_non_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        with pytest.raises(ValueError, match="not an IfcAlignment"):
            subject.visualize_3d_alignment(ifc, alignment, alignment_id=1)

    def test_raises_when_no_horizontal_layout(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_horizontal_layout(entity).should_be_called().will_return(None)
        with pytest.raises(ValueError, match="no horizontal layout"):
            subject.visualize_3d_alignment(ifc, alignment, alignment_id=1)

    def test_delegates_to_tool(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_horizontal_layout(entity).should_be_called().will_return("h_layout")
        alignment.create_3d_alignment_object(entity, 5.0).should_be_called().will_return("obj")
        result = subject.visualize_3d_alignment(ifc, alignment, alignment_id=1)
        assert result == "obj"


# ---------------------------------------------------------------------------
# delete_alignment  (spec 1.4)
# ---------------------------------------------------------------------------


class TestDeleteAlignment:
    def test_raises_when_no_ifc_file_loaded(self, ifc, alignment):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.delete_alignment(ifc, alignment, alignment_id=1)

    def test_raises_when_alignment_not_found(self, ifc, alignment):
        ifc.get().should_be_called().will_return(FakeIfcFile(not_found=True))
        with pytest.raises(ValueError, match="not found"):
            subject.delete_alignment(ifc, alignment, alignment_id=1)

    def test_raises_when_entity_is_not_an_alignment(self, ifc, alignment):
        entity = make_non_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        with pytest.raises(ValueError, match="not an IfcAlignment"):
            subject.delete_alignment(ifc, alignment, alignment_id=1)

    def test_removes_hierarchy_and_entity_and_returns_removed_count(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.remove_alignment_hierarchy(entity).should_be_called().will_return(3)
        alignment.remove_3d_alignment_object(entity).should_be_called()
        alignment.remove_alignment_entity(entity).should_be_called()
        result = subject.delete_alignment(ifc, alignment, alignment_id=1)
        assert result == 3


# ---------------------------------------------------------------------------
# delete_vertical_layout  (spec 2.6)
# ---------------------------------------------------------------------------


class TestDeleteVerticalLayout:
    def test_raises_when_no_ifc_file_loaded(self, ifc, alignment):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.delete_vertical_layout(ifc, alignment, alignment_id=1)

    def test_raises_when_alignment_not_found(self, ifc, alignment):
        ifc.get().should_be_called().will_return(FakeIfcFile(not_found=True))
        with pytest.raises(ValueError, match="not found"):
            subject.delete_vertical_layout(ifc, alignment, alignment_id=1)

    def test_raises_when_entity_is_not_an_alignment(self, ifc, alignment):
        entity = make_non_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        with pytest.raises(ValueError, match="not an IfcAlignment"):
            subject.delete_vertical_layout(ifc, alignment, alignment_id=1)

    def test_raises_when_no_vertical_layout(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_vertical_layout(entity).should_be_called().will_return(None)
        with pytest.raises(ValueError, match="no vertical layout"):
            subject.delete_vertical_layout(ifc, alignment, alignment_id=1)

    def test_removes_vertical_layout(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_vertical_layout(entity).should_be_called().will_return("v_layout")
        alignment.remove_vertical_layout(entity).should_be_called()
        result = subject.delete_vertical_layout(ifc, alignment, alignment_id=1)
        assert result is True


# ---------------------------------------------------------------------------
# delete_pi_in_edit_mode  (spec 1.3, "X" key core-level guard)
# ---------------------------------------------------------------------------


class TestDeletePiInEditMode:
    def test_raises_when_fewer_than_three_would_remain(self, ifc, alignment):
        alignment.get_pi_edit_empties(1).should_be_called().will_return(["e0", "e1", "e2"])
        with pytest.raises(ValueError, match="At least 3 PIs"):
            subject.delete_pi_in_edit_mode(ifc, alignment, alignment_id=1, index=1)

    def test_raises_when_index_not_found(self, ifc, alignment):
        alignment.get_pi_edit_empties(1).should_be_called().will_return(["e0", "e1", "e2", "e3"])
        alignment.delete_pi_edit_empty(1, 9).should_be_called().will_return(False)
        with pytest.raises(ValueError, match="not found"):
            subject.delete_pi_in_edit_mode(ifc, alignment, alignment_id=1, index=9)

    def test_deletes_when_enough_pis_remain(self, ifc, alignment):
        alignment.get_pi_edit_empties(1).should_be_called().will_return(["e0", "e1", "e2", "e3"])
        alignment.delete_pi_edit_empty(1, 1).should_be_called().will_return(True)
        subject.delete_pi_in_edit_mode(ifc, alignment, alignment_id=1, index=1)


# ---------------------------------------------------------------------------
# add_cant_to_alignment  (spec 3.1)
# ---------------------------------------------------------------------------


class TestAddCantToAlignment:
    def test_raises_when_no_ifc_file_loaded(self, ifc, alignment):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.add_cant_to_alignment(ifc, alignment, alignment_id=1)

    def test_raises_when_alignment_not_found(self, ifc, alignment):
        ifc.get().should_be_called().will_return(FakeIfcFile(not_found=True))
        with pytest.raises(ValueError, match="not found"):
            subject.add_cant_to_alignment(ifc, alignment, alignment_id=1)

    def test_raises_when_entity_is_not_an_alignment(self, ifc, alignment):
        entity = make_non_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        with pytest.raises(ValueError, match="not an IfcAlignment"):
            subject.add_cant_to_alignment(ifc, alignment, alignment_id=1)

    def test_raises_when_no_horizontal_layout_exists(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_horizontal_layout(entity).should_be_called().will_return(None)
        with pytest.raises(ValueError, match="no horizontal layout"):
            subject.add_cant_to_alignment(ifc, alignment, alignment_id=1)

    def test_raises_when_no_vertical_layout_exists(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_horizontal_layout(entity).should_be_called().will_return("h_layout")
        alignment.get_vertical_layout(entity).should_be_called().will_return(None)
        with pytest.raises(ValueError, match="no vertical layout"):
            subject.add_cant_to_alignment(ifc, alignment, alignment_id=1)

    def test_raises_when_cant_layout_already_exists(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_horizontal_layout(entity).should_be_called().will_return("h_layout")
        alignment.get_vertical_layout(entity).should_be_called().will_return("v_layout")
        alignment.get_cant_layout(entity).should_be_called().will_return("cant_layout")
        with pytest.raises(ValueError, match="already has a cant layout"):
            subject.add_cant_to_alignment(ifc, alignment, alignment_id=1)

    def test_creates_and_returns_cant_layout(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_horizontal_layout(entity).should_be_called().will_return("h_layout")
        alignment.get_vertical_layout(entity).should_be_called().will_return("v_layout")
        alignment.get_cant_layout(entity).should_be_called().will_return(None)
        alignment.add_cant_layout(entity, 1.75).should_be_called().will_return("new_cant_layout")
        result = subject.add_cant_to_alignment(ifc, alignment, alignment_id=1, rail_head_distance=1.75)
        assert result == "new_cant_layout"

    def test_defaults_rail_head_distance_to_one(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_horizontal_layout(entity).should_be_called().will_return("h_layout")
        alignment.get_vertical_layout(entity).should_be_called().will_return("v_layout")
        alignment.get_cant_layout(entity).should_be_called().will_return(None)
        alignment.add_cant_layout(entity, 1.0).should_be_called().will_return("new_cant_layout")
        result = subject.add_cant_to_alignment(ifc, alignment, alignment_id=1)
        assert result == "new_cant_layout"


# ---------------------------------------------------------------------------
# update_cant_segments  (spec 3.2)
# ---------------------------------------------------------------------------


class TestUpdateCantSegments:
    def _points(self, *stations):
        return [
            {"station": s, "cant_left": 0.0, "cant_right": 0.05, "transition_type": "LINEARTRANSITION"}
            for s in stations
        ]

    def test_raises_when_no_ifc_file_loaded(self, ifc, alignment):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.update_cant_segments(ifc, alignment, alignment_id=1, points=self._points(0.0, 100.0))

    def test_raises_when_alignment_not_found(self, ifc, alignment):
        ifc.get().should_be_called().will_return(FakeIfcFile(not_found=True))
        with pytest.raises(ValueError, match="not found"):
            subject.update_cant_segments(ifc, alignment, alignment_id=1, points=self._points(0.0, 100.0))

    def test_raises_when_entity_is_not_an_alignment(self, ifc, alignment):
        entity = make_non_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        with pytest.raises(ValueError, match="not an IfcAlignment"):
            subject.update_cant_segments(ifc, alignment, alignment_id=1, points=self._points(0.0, 100.0))

    def test_raises_when_no_cant_layout(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_cant_layout(entity).should_be_called().will_return(None)
        with pytest.raises(ValueError, match="no cant layout"):
            subject.update_cant_segments(ifc, alignment, alignment_id=1, points=self._points(0.0, 100.0))

    def test_raises_when_fewer_than_two_points(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_cant_layout(entity).should_be_called().will_return("cant_layout")
        with pytest.raises(ValueError, match="At least 2 cant points"):
            subject.update_cant_segments(ifc, alignment, alignment_id=1, points=self._points(0.0))

    def test_raises_when_stations_not_strictly_increasing(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_cant_layout(entity).should_be_called().will_return("cant_layout")
        with pytest.raises(ValueError, match="strictly increasing"):
            subject.update_cant_segments(ifc, alignment, alignment_id=1, points=self._points(100.0, 100.0))

    def test_raises_when_stations_go_backwards(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_cant_layout(entity).should_be_called().will_return("cant_layout")
        with pytest.raises(ValueError, match="strictly increasing"):
            subject.update_cant_segments(ifc, alignment, alignment_id=1, points=self._points(100.0, 50.0))

    def test_raises_when_points_extend_beyond_horizontal_extent(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_cant_layout(entity).should_be_called().will_return("cant_layout")
        alignment.get_horizontal_extent_semantic(entity).should_be_called().will_return(500.0)
        with pytest.raises(ValueError, match="horizontal extent"):
            subject.update_cant_segments(ifc, alignment, alignment_id=1, points=self._points(0.0, 600.0))

    def test_writes_segments_and_returns_true(self, ifc, alignment):
        entity = make_alignment_entity()
        points = self._points(0.0, 100.0, 300.0)
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_cant_layout(entity).should_be_called().will_return("cant_layout")
        alignment.get_horizontal_extent_semantic(entity).should_be_called().will_return(500.0)
        alignment.write_cant_segments(entity, points).should_be_called()
        alignment.commit_layout_change(entity).should_be_called()
        result = subject.update_cant_segments(ifc, alignment, alignment_id=1, points=points)
        assert result is True


# ---------------------------------------------------------------------------
# delete_cant_layout  (spec 3.6)
# ---------------------------------------------------------------------------


class TestDeleteCantLayout:
    def test_raises_when_no_ifc_file_loaded(self, ifc, alignment):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.delete_cant_layout(ifc, alignment, alignment_id=1)

    def test_raises_when_alignment_not_found(self, ifc, alignment):
        ifc.get().should_be_called().will_return(FakeIfcFile(not_found=True))
        with pytest.raises(ValueError, match="not found"):
            subject.delete_cant_layout(ifc, alignment, alignment_id=1)

    def test_raises_when_entity_is_not_an_alignment(self, ifc, alignment):
        entity = make_non_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        with pytest.raises(ValueError, match="not an IfcAlignment"):
            subject.delete_cant_layout(ifc, alignment, alignment_id=1)

    def test_raises_when_no_cant_layout(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_cant_layout(entity).should_be_called().will_return(None)
        with pytest.raises(ValueError, match="no cant layout"):
            subject.delete_cant_layout(ifc, alignment, alignment_id=1)

    def test_removes_cant_layout(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_cant_layout(entity).should_be_called().will_return("cant_layout")
        alignment.remove_cant_layout(entity).should_be_called()
        result = subject.delete_cant_layout(ifc, alignment, alignment_id=1)
        assert result is True


# ---------------------------------------------------------------------------
# add_station_equation  (spec 4.3)
# ---------------------------------------------------------------------------


class TestAddStationEquation:
    def test_raises_when_no_ifc_file_loaded(self, ifc, alignment):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.add_station_equation(ifc, alignment, alignment_id=1, back_station=100.0, ahead_station=200.0)

    def test_raises_when_alignment_not_found(self, ifc, alignment):
        ifc.get().should_be_called().will_return(FakeIfcFile(not_found=True))
        with pytest.raises(ValueError, match="not found"):
            subject.add_station_equation(ifc, alignment, alignment_id=1, back_station=100.0, ahead_station=200.0)

    def test_raises_when_entity_is_not_an_alignment(self, ifc, alignment):
        entity = make_non_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        with pytest.raises(ValueError, match="not an IfcAlignment"):
            subject.add_station_equation(ifc, alignment, alignment_id=1, back_station=100.0, ahead_station=200.0)

    def test_raises_when_back_and_ahead_stations_are_equal(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        with pytest.raises(ValueError, match="must differ"):
            subject.add_station_equation(ifc, alignment, alignment_id=1, back_station=100.0, ahead_station=100.0)

    def test_raises_when_back_station_unreachable(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.distance_along_from_station(entity, 150.0).should_be_called().will_return(None)
        with pytest.raises(ValueError, match="not reachable"):
            subject.add_station_equation(ifc, alignment, alignment_id=1, back_station=150.0, ahead_station=500.0)

    def test_creates_gap_equation_and_returns_referent(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.distance_along_from_station(entity, 100.0).should_be_called().will_return(100.0)
        alignment.add_station_equation_referent(entity, 100.0, 100.0, 300.0).should_be_called().will_return("referent")
        result = subject.add_station_equation(ifc, alignment, alignment_id=1, back_station=100.0, ahead_station=300.0)
        assert result == "referent"

    def test_creates_overlap_equation_and_returns_referent(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.distance_along_from_station(entity, 300.0).should_be_called().will_return(300.0)
        alignment.add_station_equation_referent(entity, 300.0, 300.0, 100.0).should_be_called().will_return("referent")
        result = subject.add_station_equation(ifc, alignment, alignment_id=1, back_station=300.0, ahead_station=100.0)
        assert result == "referent"


# ---------------------------------------------------------------------------
# add_event_referent  (spec 4.4)
# ---------------------------------------------------------------------------


class TestAddEventReferent:
    def test_raises_when_no_ifc_file_loaded(self, ifc, alignment):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.add_event_referent(ifc, alignment, alignment_id=1, event_type="SUPERELEVATIONEVENT", station=100.0)

    def test_raises_when_alignment_not_found(self, ifc, alignment):
        ifc.get().should_be_called().will_return(FakeIfcFile(not_found=True))
        with pytest.raises(ValueError, match="not found"):
            subject.add_event_referent(ifc, alignment, alignment_id=1, event_type="SUPERELEVATIONEVENT", station=100.0)

    def test_raises_when_entity_is_not_an_alignment(self, ifc, alignment):
        entity = make_non_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        with pytest.raises(ValueError, match="not an IfcAlignment"):
            subject.add_event_referent(ifc, alignment, alignment_id=1, event_type="SUPERELEVATIONEVENT", station=100.0)

    def test_raises_when_event_type_is_unknown(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        with pytest.raises(ValueError, match="Unknown event type"):
            subject.add_event_referent(ifc, alignment, alignment_id=1, event_type="BOGUSEVENT", station=100.0)

    def test_creates_superelevation_event_and_returns_referent(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.add_event_referent(entity, "SUPERELEVATIONEVENT", 100.0, "", None).should_be_called().will_return(
            "referent"
        )
        result = subject.add_event_referent(
            ifc, alignment, alignment_id=1, event_type="SUPERELEVATIONEVENT", station=100.0
        )
        assert result == "referent"

    def test_creates_width_event_with_name_and_value(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.add_event_referent(entity, "WIDTHEVENT", 250.0, "Lane Widening", 3.6).should_be_called().will_return(
            "referent"
        )
        result = subject.add_event_referent(
            ifc,
            alignment,
            alignment_id=1,
            event_type="WIDTHEVENT",
            station=250.0,
            name="Lane Widening",
            value=3.6,
        )
        assert result == "referent"


# ---------------------------------------------------------------------------
# remove_referent  (spec 4.1)
# ---------------------------------------------------------------------------


class TestRemoveReferent:
    def test_raises_when_no_ifc_file_loaded(self, ifc, alignment):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.remove_referent(ifc, alignment, alignment_id=1, referent_id=99)

    def test_raises_when_alignment_not_found(self, ifc, alignment):
        ifc.get().should_be_called().will_return(FakeIfcFile(not_found=True))
        with pytest.raises(ValueError, match="not found"):
            subject.remove_referent(ifc, alignment, alignment_id=1, referent_id=99)

    def test_raises_when_entity_is_not_an_alignment(self, ifc, alignment):
        entity = make_non_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        with pytest.raises(ValueError, match="not an IfcAlignment"):
            subject.remove_referent(ifc, alignment, alignment_id=1, referent_id=99)

    def test_raises_when_referent_not_nested_on_alignment(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_referents(entity).should_be_called().will_return([{"id": 1, "name": "x"}])
        with pytest.raises(ValueError, match="not nested"):
            subject.remove_referent(ifc, alignment, alignment_id=1, referent_id=99)

    def test_removes_referent(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_referents(entity).should_be_called().will_return([{"id": 99, "name": "x"}])
        alignment.remove_referent(entity, 99).should_be_called()
        subject.remove_referent(ifc, alignment, alignment_id=1, referent_id=99)

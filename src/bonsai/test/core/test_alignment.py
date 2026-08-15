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
    """Minimal stand-in for an open IFC file.

    ``by_id_map``, when given, resolves ``by_id(id)`` per-id (needed for
    tests that exercise more than one ``by_id`` lookup against different
    entities, e.g. the multi-vertical selector's ``vertical_layout_id``
    resolution). When omitted, every ``by_id`` call returns the same
    ``entity`` regardless of id, matching the original single-entity
    behavior every other test in this module relies on.
    """

    def __init__(self, entity=None, not_found: bool = False, by_id_map: dict = None):
        self._entity = entity
        self._not_found = not_found
        self._by_id_map = by_id_map

    def by_id(self, entity_id: int):
        if self._not_found:
            raise RuntimeError(f"Could not find #{entity_id}")
        if self._by_id_map is not None:
            if entity_id not in self._by_id_map:
                raise RuntimeError(f"Could not find #{entity_id}")
            return self._by_id_map[entity_id]
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
        alignment.back_calculate_pvis_from_vertical(entity, vertical_layout="v_layout").should_be_called().will_return(
            pvis
        )
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
        alignment.back_calculate_pvis_from_vertical(entity, vertical_layout="v_layout").should_be_called().will_return(
            pvis
        )
        alignment.create_pvi_edit_empties(entity, pvis).should_be_called().will_return(empties)
        result = subject.enter_pvi_edit_mode(ifc, alignment, alignment_id=1)
        assert result == empties

    def test_targets_the_selected_vertical_layout_when_given(self, ifc, alignment):
        entity = make_alignment_entity()
        v_layout_2 = FakeIfcEntity({"ifc_class": "IfcAlignmentVertical", "name": "V2"})
        pvis = [
            {"station": 0.0, "elevation": 100.0, "curve_length": 0.0},
            {"station": 500.0, "elevation": 110.0, "curve_length": 0.0},
        ]
        empties = ["pvi_empty_0", "pvi_empty_1"]
        # ifc.get() is called twice: once to resolve the alignment, once
        # inside _resolve_vertical_layout to look up vertical_layout_id.
        fake_file = FakeIfcFile(by_id_map={1: entity, 42: v_layout_2})
        ifc.get().should_be_called(2).will_return(fake_file)
        alignment.get_vertical_layouts(entity).should_be_called().will_return(["v_layout", v_layout_2])
        alignment.layout_has_real_segments(v_layout_2).should_be_called().will_return(True)
        alignment.back_calculate_pvis_from_vertical(entity, vertical_layout=v_layout_2).should_be_called().will_return(
            pvis
        )
        alignment.create_pvi_edit_empties(entity, pvis).should_be_called().will_return(empties)
        result = subject.enter_pvi_edit_mode(ifc, alignment, alignment_id=1, vertical_layout_id=42)
        assert result == empties

    def test_raises_when_vertical_layout_id_does_not_belong_to_alignment(self, ifc, alignment):
        entity = make_alignment_entity()
        unrelated_layout = FakeIfcEntity({"ifc_class": "IfcAlignmentVertical", "name": "Unrelated"})
        fake_file = FakeIfcFile(by_id_map={1: entity, 42: unrelated_layout})
        ifc.get().should_be_called(2).will_return(fake_file)
        alignment.get_vertical_layouts(entity).should_be_called().will_return(["v_layout"])
        with pytest.raises(ValueError, match="does not belong"):
            subject.enter_pvi_edit_mode(ifc, alignment, alignment_id=1, vertical_layout_id=42)


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


# ---------------------------------------------------------------------------
# create_offset_alignment  (spec 1.7)
# ---------------------------------------------------------------------------


class TestCreateOffsetAlignment:
    def test_raises_when_no_ifc_file_loaded(self, ifc, alignment):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.create_offset_alignment(ifc, alignment, alignment_id=1, name="Offset", offset_spec={})

    def test_raises_when_alignment_not_found(self, ifc, alignment):
        ifc.get().should_be_called().will_return(FakeIfcFile(not_found=True))
        with pytest.raises(ValueError, match="not found"):
            subject.create_offset_alignment(ifc, alignment, alignment_id=1, name="Offset", offset_spec={})

    def test_raises_when_entity_is_not_an_alignment(self, ifc, alignment):
        entity = make_non_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        with pytest.raises(ValueError, match="not an IfcAlignment"):
            subject.create_offset_alignment(ifc, alignment, alignment_id=1, name="Offset", offset_spec={})

    def test_raises_when_parent_has_no_curve(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_curve_for_alignment(entity).should_be_called().will_return(None)
        with pytest.raises(ValueError, match="no geometric representation"):
            subject.create_offset_alignment(ifc, alignment, alignment_id=1, name="Offset", offset_spec={})

    def test_raises_when_name_is_empty(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_curve_for_alignment(entity).should_be_called().will_return("curve")
        with pytest.raises(ValueError, match="cannot be empty"):
            subject.create_offset_alignment(ifc, alignment, alignment_id=1, name="   ", offset_spec={})

    def test_raises_when_mode_is_unknown(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_curve_for_alignment(entity).should_be_called().will_return("curve")
        with pytest.raises(ValueError, match="Unknown offset mode"):
            subject.create_offset_alignment(
                ifc, alignment, alignment_id=1, name="Offset", offset_spec={"mode": "BOGUS"}
            )

    def test_raises_when_constant_offset_is_zero(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_curve_for_alignment(entity).should_be_called().will_return("curve")
        alignment.get_horizontal_extent_semantic(entity).should_be_called().will_return(500.0)
        with pytest.raises(ValueError, match="must be non-zero"):
            subject.create_offset_alignment(
                ifc, alignment, alignment_id=1, name="Offset", offset_spec={"mode": "CONSTANT", "offset": 0.0}
            )

    def test_creates_constant_offset_alignment(self, ifc, alignment):
        entity = make_alignment_entity()
        offset_spec = {"mode": "CONSTANT", "offset": 5.0}
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_curve_for_alignment(entity).should_be_called().will_return("curve")
        alignment.get_horizontal_extent_semantic(entity).should_be_called().will_return(500.0)
        alignment.create_offset_alignment(entity, "Offset", offset_spec).should_be_called().will_return(
            "offset_alignment"
        )
        result = subject.create_offset_alignment(ifc, alignment, alignment_id=1, name="Offset", offset_spec=offset_spec)
        assert result == "offset_alignment"

    def test_raises_when_taper_offsets_both_zero(self, ifc, alignment):
        entity = make_alignment_entity()
        offset_spec = {
            "mode": "TAPER",
            "start_offset": 0.0,
            "end_offset": 0.0,
            "station_from": 0.0,
            "station_to": 100.0,
        }
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_curve_for_alignment(entity).should_be_called().will_return("curve")
        alignment.get_horizontal_extent_semantic(entity).should_be_called().will_return(500.0)
        with pytest.raises(ValueError, match="cannot both be zero"):
            subject.create_offset_alignment(ifc, alignment, alignment_id=1, name="Offset", offset_spec=offset_spec)

    def test_raises_when_taper_station_from_not_less_than_station_to(self, ifc, alignment):
        entity = make_alignment_entity()
        offset_spec = {
            "mode": "TAPER",
            "start_offset": 5.0,
            "end_offset": 10.0,
            "station_from": 200.0,
            "station_to": 100.0,
        }
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_curve_for_alignment(entity).should_be_called().will_return("curve")
        alignment.get_horizontal_extent_semantic(entity).should_be_called().will_return(500.0)
        with pytest.raises(ValueError, match="station_from must be less than station_to"):
            subject.create_offset_alignment(ifc, alignment, alignment_id=1, name="Offset", offset_spec=offset_spec)

    def test_raises_when_taper_range_outside_extent(self, ifc, alignment):
        entity = make_alignment_entity()
        offset_spec = {
            "mode": "TAPER",
            "start_offset": 5.0,
            "end_offset": 10.0,
            "station_from": 0.0,
            "station_to": 600.0,
        }
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_curve_for_alignment(entity).should_be_called().will_return("curve")
        alignment.get_horizontal_extent_semantic(entity).should_be_called().will_return(500.0)
        with pytest.raises(ValueError, match="must fall within the alignment's extent"):
            subject.create_offset_alignment(ifc, alignment, alignment_id=1, name="Offset", offset_spec=offset_spec)

    def test_creates_taper_offset_alignment(self, ifc, alignment):
        entity = make_alignment_entity()
        offset_spec = {
            "mode": "TAPER",
            "start_offset": 5.0,
            "end_offset": 10.0,
            "station_from": 0.0,
            "station_to": 100.0,
        }
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_curve_for_alignment(entity).should_be_called().will_return("curve")
        alignment.get_horizontal_extent_semantic(entity).should_be_called().will_return(500.0)
        alignment.create_offset_alignment(entity, "Taper Offset", offset_spec).should_be_called().will_return(
            "offset_alignment"
        )
        result = subject.create_offset_alignment(
            ifc, alignment, alignment_id=1, name="Taper Offset", offset_spec=offset_spec
        )
        assert result == "offset_alignment"


# ---------------------------------------------------------------------------
# convert_curve_to_alignment  (spec 1.8)
# ---------------------------------------------------------------------------


class TestConvertCurveToAlignment:
    def test_raises_when_no_ifc_file_loaded(self, ifc, alignment):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.convert_curve_to_alignment(ifc, alignment, name="A1", points_xy=[(0.0, 0.0), (1.0, 1.0)])

    def test_raises_when_name_is_empty(self, ifc, alignment):
        ifc.get().should_be_called().will_return("ifc_file")
        with pytest.raises(ValueError, match="cannot be empty"):
            subject.convert_curve_to_alignment(ifc, alignment, name="  ", points_xy=[(0.0, 0.0), (1.0, 1.0)])

    def test_raises_when_fewer_than_two_raw_points(self, ifc, alignment):
        ifc.get().should_be_called().will_return("ifc_file")
        with pytest.raises(ValueError, match="at least 2 points"):
            subject.convert_curve_to_alignment(ifc, alignment, name="A1", points_xy=[(0.0, 0.0)])

    def test_raises_when_simplified_has_fewer_than_two_distinct_points(self, ifc, alignment):
        points_xy = [(0.0, 0.0), (0.0, 1e-9), (0.0, 2e-9)]
        ifc.get().should_be_called().will_return("ifc_file")
        alignment.simplify_polyline(points_xy, 0.5).should_be_called().will_return([(0.0, 0.0)])
        alignment.count_distinct_points([(0.0, 0.0)]).should_be_called().will_return(1)
        with pytest.raises(ValueError, match="fewer than 2 distinct points"):
            subject.convert_curve_to_alignment(ifc, alignment, name="A1", points_xy=points_xy)

    def test_creates_alignment_and_returns_counts(self, ifc, alignment):
        points_xy = [(0.0, 0.0), (50.0, 0.0), (100.0, 5.0), (150.0, 5.0)]
        simplified = [(0.0, 0.0), (100.0, 5.0), (150.0, 5.0)]
        ifc.get().should_be_called().will_return("ifc_file")
        alignment.simplify_polyline(points_xy, 0.5).should_be_called().will_return(simplified)
        alignment.count_distinct_points(simplified).should_be_called().will_return(3)
        alignment.convert_points_to_alignment("A1", simplified).should_be_called().will_return("alignment")
        result_alignment, pi_count, sample_count = subject.convert_curve_to_alignment(
            ifc, alignment, name="A1", points_xy=points_xy
        )
        assert result_alignment == "alignment"
        assert pi_count == 3
        assert sample_count == 4


# ---------------------------------------------------------------------------
# add_alternative_vertical  (spec 2.1)
# ---------------------------------------------------------------------------


class TestAddAlternativeVertical:
    def test_raises_when_no_ifc_file_loaded(self, ifc, alignment):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.add_alternative_vertical(ifc, alignment, alignment_id=1)

    def test_raises_when_alignment_not_found(self, ifc, alignment):
        ifc.get().should_be_called().will_return(FakeIfcFile(not_found=True))
        with pytest.raises(ValueError, match="not found"):
            subject.add_alternative_vertical(ifc, alignment, alignment_id=1)

    def test_raises_when_entity_is_not_an_alignment(self, ifc, alignment):
        entity = make_non_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        with pytest.raises(ValueError, match="not an IfcAlignment"):
            subject.add_alternative_vertical(ifc, alignment, alignment_id=1)

    def test_raises_when_no_horizontal_layout(self, ifc, alignment):
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_horizontal_layout(entity).should_be_called().will_return(None)
        with pytest.raises(ValueError, match="no horizontal layout"):
            subject.add_alternative_vertical(ifc, alignment, alignment_id=1)

    def test_does_not_refuse_when_alignment_already_has_a_vertical(self, ifc, alignment):
        # The whole point of add_alternative_vertical (spec 2.1): unlike
        # add_vertical_to_alignment, an existing vertical is NOT a refusal
        # condition -- so this deliberately never calls get_vertical_layout.
        entity = make_alignment_entity()
        ifc.get().should_be_called().will_return(FakeIfcFile(entity=entity))
        alignment.get_horizontal_layout(entity).should_be_called().will_return("h_layout")
        alignment.add_alternative_vertical(entity).should_be_called().will_return("v_layout_2")
        result = subject.add_alternative_vertical(ifc, alignment, alignment_id=1)
        assert result == "v_layout_2"

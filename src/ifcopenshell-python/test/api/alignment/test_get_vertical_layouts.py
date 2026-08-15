# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2025 Thomas Krijnen <thomas@aecgeeks.com>
#
# This file is part of IfcOpenShell.
#
# IfcOpenShell is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# IfcOpenShell is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with IfcOpenShell.  If not, see <http://www.gnu.org/licenses/>.

import pytest

import ifcopenshell.api.alignment
import ifcopenshell.api.context
import ifcopenshell.api.unit

try:
    ifcopenshell.file(schema="IFC4X3")
    IFC4X3_AVAILABLE = True
except RuntimeError:
    IFC4X3_AVAILABLE = False


def _setup_file() -> ifcopenshell.file:
    file = ifcopenshell.file(schema="IFC4X3")
    project = file.createIfcProject(GlobalId=ifcopenshell.guid.new(), Name="Test")
    length = ifcopenshell.api.unit.add_si_unit(file, unit_type="LENGTHUNIT")
    ifcopenshell.api.unit.assign_unit(file, units=[length])
    ifcopenshell.api.context.add_context(file, context_type="Model")
    return file


@pytest.mark.skipif(not IFC4X3_AVAILABLE, reason="IFC4X3 not available")
def test_get_vertical_layouts_with_no_vertical_layout():
    file = _setup_file()
    alignment = ifcopenshell.api.alignment.create(file, "A0", include_vertical=False)

    assert ifcopenshell.api.alignment.get_vertical_layouts(alignment) == []


@pytest.mark.skipif(not IFC4X3_AVAILABLE, reason="IFC4X3 not available")
def test_get_vertical_layouts_nested_directly_on_alignment():
    # IFC CT 4.1.4.4.1.1 Alignment Layout - Horizontal, Vertical and Cant: a single vertical
    # layout is nested directly onto the alignment. get_vertical_layout finds it there, and so
    # should get_vertical_layouts.
    file = _setup_file()
    alignment = ifcopenshell.api.alignment.create(file, "A1", include_vertical=True)
    v1 = ifcopenshell.api.alignment.get_vertical_layout(alignment)

    assert v1 is not None
    assert ifcopenshell.api.alignment.get_vertical_layouts(alignment) == [v1]


@pytest.mark.skipif(not IFC4X3_AVAILABLE, reason="IFC4X3 not available")
def test_get_vertical_layouts_migrated_to_aggregated_children():
    # IFC CT 4.1.4.4.1.2 Alignment Layout - Reusing Horizontal Layout: once a second vertical
    # layout is added, add_vertical_layout migrates *both* verticals onto their own aggregated
    # child IfcAlignment. From that point on, the parent's own IsNestedBy carries no
    # IfcAlignmentVertical at all - get_vertical_layout's first-match scan of it would return
    # None, even though two vertical layouts still exist. get_vertical_layouts must find both by
    # also walking the aggregated children.
    file = _setup_file()
    alignment = ifcopenshell.api.alignment.create(file, "A1", include_vertical=True)
    v1 = ifcopenshell.api.alignment.get_vertical_layout(alignment)

    v2 = ifcopenshell.api.alignment.add_vertical_layout(file, alignment)

    # the migration happened: nothing is nested directly on the parent alignment anymore
    directly_nested_verticals = [
        related_object
        for rel in alignment.IsNestedBy
        for related_object in rel.RelatedObjects
        if related_object.is_a("IfcAlignmentVertical")
    ]
    assert directly_nested_verticals == []

    # there are now two aggregated child alignments, one per vertical layout
    assert len(alignment.IsDecomposedBy) == 1
    assert len(alignment.IsDecomposedBy[0].RelatedObjects) == 2

    vertical_layouts = ifcopenshell.api.alignment.get_vertical_layouts(alignment)

    # NOTE: exact ordering across the two children is not asserted here. add_vertical_layout
    # merges the second child alignment into the existing IfcRelAggregates.RelatedObjects via
    # ifcopenshell.api.aggregate.assign_object, which folds the previous and new RelatedObjects
    # through a Python set union (see api/aggregate/assign_object.py). That set-mediated merge's
    # iteration order is not guaranteed - empirically it varies from run to run in this same
    # process - so get_vertical_layouts' children-order guarantee is only as good as whatever
    # order IfcRelAggregates.RelatedObjects happens to record. Assert membership, not order.
    assert len(vertical_layouts) == 2
    assert set(vertical_layouts) == {v1, v2}


test_get_vertical_layouts_with_no_vertical_layout()
test_get_vertical_layouts_nested_directly_on_alignment()
test_get_vertical_layouts_migrated_to_aggregated_children()

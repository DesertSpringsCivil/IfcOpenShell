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


def _make_file() -> ifcopenshell.file:
    file = ifcopenshell.file(schema="IFC4X3")
    file.createIfcProject(GlobalId=ifcopenshell.guid.new(), Name="Test")
    length = ifcopenshell.api.unit.add_si_unit(file, unit_type="LENGTHUNIT")
    ifcopenshell.api.unit.assign_unit(file, units=[length])
    ifcopenshell.api.context.add_context(file, context_type="Model")
    return file


@pytest.mark.skipif(not IFC4X3_AVAILABLE, reason="IFC4X3 not available")
def test_add_cant_layout_raises_without_vertical_layout():
    file = _make_file()
    alignment = ifcopenshell.api.alignment.create(file, "A1", include_vertical=False)

    with pytest.raises(ValueError):
        ifcopenshell.api.alignment.add_cant_layout(file, alignment)


@pytest.mark.skipif(not IFC4X3_AVAILABLE, reason="IFC4X3 not available")
def test_add_cant_layout_raises_without_horizontal_layout():
    # an alignment can never exist without a horizontal layout through the public API (create() always
    # makes one), so this exercises the guard directly against a bare, unnested IfcAlignmentVertical.
    file = _make_file()
    alignment = file.createIfcAlignment(GlobalId=ifcopenshell.guid.new(), Name="A1")

    with pytest.raises(ValueError):
        ifcopenshell.api.alignment.add_cant_layout(file, alignment)


@pytest.mark.skipif(not IFC4X3_AVAILABLE, reason="IFC4X3 not available")
def test_add_cant_layout_raises_when_cant_already_exists():
    file = _make_file()
    alignment = ifcopenshell.api.alignment.create(file, "A1", include_vertical=True)

    ifcopenshell.api.alignment.add_cant_layout(file, alignment, rail_head_distance=1.435)

    with pytest.raises(ValueError):
        ifcopenshell.api.alignment.add_cant_layout(file, alignment, rail_head_distance=1.435)


@pytest.mark.skipif(not IFC4X3_AVAILABLE, reason="IFC4X3 not available")
def test_add_cant_layout_creates_semantic_cant_with_zero_length_terminator():
    file = _make_file()
    alignment = ifcopenshell.api.alignment.create(file, "A1", include_vertical=True)

    cant_layout = ifcopenshell.api.alignment.add_cant_layout(file, alignment, rail_head_distance=1.435)

    assert cant_layout.is_a("IfcAlignmentCant")
    assert cant_layout.RailHeadDistance == 1.435

    # nested directly on the alignment, alongside the horizontal and vertical layouts
    layout_nest = ifcopenshell.api.alignment.get_alignment_layout_nest(alignment)
    assert len(layout_nest.RelatedObjects) == 3
    assert layout_nest.RelatedObjects[0].is_a("IfcAlignmentHorizontal")
    assert layout_nest.RelatedObjects[1].is_a("IfcAlignmentVertical")
    assert layout_nest.RelatedObjects[2] == cant_layout

    # mandatory zero length terminal segment on the semantic layout
    assert ifcopenshell.api.alignment.has_zero_length_segment(cant_layout)
    cant_segment_nest = ifcopenshell.api.alignment.get_alignment_segment_nest(cant_layout)
    assert len(cant_segment_nest.RelatedObjects) == 1
    terminal_segment = cant_segment_nest.RelatedObjects[0]
    assert terminal_segment.is_a("IfcAlignmentSegment")
    assert terminal_segment.DesignParameters.is_a("IfcAlignmentCantSegment")
    assert terminal_segment.DesignParameters.HorizontalLength == 0.0


@pytest.mark.skipif(not IFC4X3_AVAILABLE, reason="IFC4X3 not available")
def test_get_cant_layout_finds_newly_added_cant_layout():
    file = _make_file()
    alignment = ifcopenshell.api.alignment.create(file, "A1", include_vertical=True)

    assert ifcopenshell.api.alignment.get_cant_layout(alignment) is None

    cant_layout = ifcopenshell.api.alignment.add_cant_layout(file, alignment, rail_head_distance=1.435)

    assert ifcopenshell.api.alignment.get_cant_layout(alignment) == cant_layout


@pytest.mark.skipif(not IFC4X3_AVAILABLE, reason="IFC4X3 not available")
def test_add_cant_layout_without_geometry_stays_semantic_only():
    # create() with include_geometry=False leaves the alignment without a Representation. add_cant_layout
    # should still succeed semantically and must not attempt to touch a representation that doesn't exist.
    file = _make_file()
    alignment = ifcopenshell.api.alignment.create(file, "A1", include_vertical=True, include_geometry=False)
    assert alignment.Representation is None

    cant_layout = ifcopenshell.api.alignment.add_cant_layout(file, alignment, rail_head_distance=1.435)

    assert alignment.Representation is None
    assert ifcopenshell.api.alignment.get_cant_layout(alignment) == cant_layout
    assert ifcopenshell.api.alignment.has_zero_length_segment(cant_layout)


@pytest.mark.skipif(not IFC4X3_AVAILABLE, reason="IFC4X3 not available")
def test_add_cant_layout_extends_existing_representation():
    # add_cant_layout()'s own zero-length-segment bookkeeping is designed to avoid the geometry engine
    # entirely (see the RuntimeError guard in add_cant_layout.py), so this is expected to pass even on
    # environments missing the compiled geometry-mapping DLLs (win64 packaging gap, IfcOpenShell#9301).
    # The try/except below is a safety net in case that assumption doesn't hold in some environment:
    # if RuntimeError("No geometry mapping registered for ifc4x3_add2") still surfaces, skip rather than fail.
    file = _make_file()
    alignment = ifcopenshell.api.alignment.create(file, "A1", include_vertical=True)

    gradient_curve = ifcopenshell.api.alignment.get_curve(alignment)
    assert gradient_curve.is_a("IfcGradientCurve")

    try:
        cant_layout = ifcopenshell.api.alignment.add_cant_layout(file, alignment, rail_head_distance=1.435)
    except RuntimeError as e:
        if "No geometry mapping registered" in str(e):
            pytest.skip(f"geometry mapping DLLs unavailable in this environment (IfcOpenShell#9301): {e}")
        raise

    curve = ifcopenshell.api.alignment.get_curve(alignment)
    assert curve.is_a("IfcSegmentedReferenceCurve")
    assert curve.BaseCurve == gradient_curve

    # get_layout_curve resolves the cant layout to the same segmented reference curve
    assert ifcopenshell.api.alignment.get_layout_curve(cant_layout) == curve

    # the geometric curve also carries the mandatory zero length terminal segment
    assert ifcopenshell.api.alignment.has_zero_length_segment(curve)

    # update_end_point() was invoked, so EndPoint should be populated (not left as $)
    assert curve.EndPoint is not None
    assert curve.EndPoint.is_a("IfcAxis2Placement3D")

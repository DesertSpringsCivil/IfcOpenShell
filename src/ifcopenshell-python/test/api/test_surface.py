# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2026 Desert Springs Civil Engineering PLLC
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

"""Tests for ``ifcopenshell.api.surface``.

Pure pytest suite — no Blender, no bpy. Each public function gets its own
test class. Round-trip discipline: every "creates an entity" test writes the
file to disk, reopens it, and asserts the structure is preserved.
"""

import ifcopenshell
import ifcopenshell.api.unit
import pytest


def _empty_project_file() -> ifcopenshell.file:
    """Build a minimal IFC4X3_ADD2 file with an IfcProject, a metric SI unit, and an IfcSite."""
    file = ifcopenshell.file(schema="IFC4X3_ADD2")
    project = file.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), Name="Test Project")
    length_unit = ifcopenshell.api.unit.add_si_unit(file, unit_type="LENGTHUNIT")
    ifcopenshell.api.unit.assign_unit(file, units=[length_unit])
    site = file.create_entity("IfcSite", GlobalId=ifcopenshell.guid.new(), Name="Test Site")
    file.create_entity(
        "IfcRelAggregates",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=project,
        RelatedObjects=[site],
    )
    return file


@pytest.fixture
def empty_project_file() -> ifcopenshell.file:
    return _empty_project_file()


def _site(file: ifcopenshell.file) -> ifcopenshell.entity_instance:
    return file.by_type("IfcSite")[0]


def _flat_pad_geometry() -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    """3×3 grid of vertices on a 100×100 m flat pad at z=100, with 8 triangles."""
    points: list[tuple[float, float, float]] = []
    for j in range(3):
        for i in range(3):
            points.append((float(i * 50), float(j * 50), 100.0))
    triangles: list[tuple[int, int, int]] = []
    for j in range(2):
        for i in range(2):
            a = j * 3 + i
            b = a + 1
            c = a + 3
            d = a + 4
            triangles.append((a, b, d))
            triangles.append((a, d, c))
    return points, triangles


def _pyramid_geometry() -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    """4-vertex pyramid (square base + apex), used for round-trip tests on tiny meshes."""
    points = [
        (0.0, 0.0, 0.0),
        (10.0, 0.0, 0.0),
        (10.0, 10.0, 0.0),
        (0.0, 10.0, 0.0),
        (5.0, 5.0, 5.0),
    ]
    # 4 side faces + 2 base triangles
    triangles = [
        (0, 1, 4),
        (1, 2, 4),
        (2, 3, 4),
        (3, 0, 4),
        (0, 1, 2),
        (0, 2, 3),
    ]
    return points, triangles


def _make_geographic_element(file: ifcopenshell.file, name: str = "Test Terrain") -> ifcopenshell.entity_instance:
    return file.create_entity(
        "IfcGeographicElement",
        GlobalId=ifcopenshell.guid.new(),
        Name=name,
        PredefinedType="TERRAIN",
    )


def test_package_importable() -> None:
    """Smoke test: the package imports and exposes the expected docstring."""
    import ifcopenshell.api.surface

    assert ifcopenshell.api.surface.__doc__ is not None
    assert "surface" in ifcopenshell.api.surface.__doc__.lower()


class TestRepresentationContext:
    """Tests for the internal subcontext resolver (``_representation_context``)."""

    def test_creates_surface_model_subcontext_on_empty_file(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.surface import _representation_context

        sub = _representation_context.get_surface_model_subcontext(empty_project_file)
        assert sub.is_a("IfcGeometricRepresentationSubContext")
        assert sub.ContextIdentifier == "SurfaceModel"
        assert sub.TargetView == "MODEL_VIEW"
        assert sub.ParentContext.is_a("IfcGeometricRepresentationContext")
        assert sub.ParentContext.ContextType == "Model"

    def test_lookup_is_idempotent(self, empty_project_file: ifcopenshell.file) -> None:
        """Calling twice must return the same subcontext entity, not a duplicate."""
        from ifcopenshell.api.surface import _representation_context

        first = _representation_context.get_surface_model_subcontext(empty_project_file)
        second = _representation_context.get_surface_model_subcontext(empty_project_file)
        assert first.id() == second.id()
        # Only one Model context, only one SurfaceModel subcontext.
        contexts = empty_project_file.by_type("IfcGeometricRepresentationContext", include_subtypes=False)
        subcontexts = [
            c
            for c in empty_project_file.by_type("IfcGeometricRepresentationSubContext")
            if c.ContextIdentifier == "SurfaceModel"
        ]
        assert len(contexts) == 1
        assert len(subcontexts) == 1

    def test_box_and_body_subcontexts_share_parent(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.surface import _representation_context

        body = _representation_context.get_body_subcontext(empty_project_file)
        box = _representation_context.get_box_subcontext(empty_project_file)
        surface = _representation_context.get_surface_model_subcontext(empty_project_file)
        assert body.ParentContext.id() == box.ParentContext.id() == surface.ParentContext.id()
        assert body.ContextIdentifier == "Body"
        assert box.ContextIdentifier == "Box"


class TestAddTinRepresentation:
    """Tests for ``ifcopenshell.api.surface.add_tin_representation``."""

    def test_happy_path_on_host_with_no_existing_representation(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.surface import add_tin_representation

        host = _make_geographic_element(empty_project_file)
        points, triangles = _flat_pad_geometry()

        tin = add_tin_representation(empty_project_file, host, points, triangles)

        assert tin.is_a("IfcTriangulatedIrregularNetwork")
        assert tin.Coordinates.is_a("IfcCartesianPointList3D")
        assert len(tin.Coordinates.CoordList) == 9
        assert len(tin.CoordIndex) == 8
        # All indices must be 1-based and in the valid range.
        for triangle in tin.CoordIndex:
            for index in triangle:
                assert 1 <= index <= 9
        assert tin.Flags == (0,) * 8 or tin.Flags == [0] * 8
        assert tin.Closed is False

        shape = host.Representation
        assert shape.is_a("IfcProductDefinitionShape")
        assert len(shape.Representations) == 1
        rep = shape.Representations[0]
        assert rep.RepresentationIdentifier == "SurfaceModel"
        assert rep.RepresentationType == "Tessellation"
        assert rep.Items[0].id() == tin.id()

    def test_one_based_index_conversion(self, empty_project_file: ifcopenshell.file) -> None:
        """The API takes 0-based; the entity must store 1-based exactly."""
        from ifcopenshell.api.surface import add_tin_representation

        host = _make_geographic_element(empty_project_file)
        points = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        triangles = [(0, 1, 2)]

        tin = add_tin_representation(empty_project_file, host, points, triangles)
        assert list(tin.CoordIndex[0]) == [1, 2, 3]

    def test_triangle_flags_are_persisted(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.surface import add_tin_representation

        host = _make_geographic_element(empty_project_file)
        points, triangles = _pyramid_geometry()
        flags = [1, 2, 3, 4, 0, 0]

        tin = add_tin_representation(empty_project_file, host, points, triangles, triangle_flags=flags)
        assert list(tin.Flags) == flags

    def test_existing_box_rep_does_not_block_surface_model(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        """add_tin_representation must coexist with a pre-existing Box representation."""
        from ifcopenshell.api.surface import _representation_context, add_tin_representation

        host = _make_geographic_element(empty_project_file)
        # Pre-populate a Box representation by hand.
        box_subctx = _representation_context.get_box_subcontext(empty_project_file)
        box_item = empty_project_file.create_entity(
            "IfcBoundingBox",
            Corner=empty_project_file.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0)),
            XDim=10.0,
            YDim=10.0,
            ZDim=1.0,
        )
        box_rep = empty_project_file.create_entity(
            "IfcShapeRepresentation",
            ContextOfItems=box_subctx,
            RepresentationIdentifier="Box",
            RepresentationType="BoundingBox",
            Items=[box_item],
        )
        host.Representation = empty_project_file.create_entity(
            "IfcProductDefinitionShape", Representations=[box_rep]
        )

        points, triangles = _flat_pad_geometry()
        add_tin_representation(empty_project_file, host, points, triangles)

        rep_identifiers = {r.RepresentationIdentifier for r in host.Representation.Representations}
        assert rep_identifiers == {"Box", "SurfaceModel"}

    def test_double_add_raises_value_error(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.surface import add_tin_representation

        host = _make_geographic_element(empty_project_file)
        points, triangles = _flat_pad_geometry()
        add_tin_representation(empty_project_file, host, points, triangles)

        with pytest.raises(ValueError, match="SurfaceModel"):
            add_tin_representation(empty_project_file, host, points, triangles)

    def test_empty_points_raises(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.surface import add_tin_representation

        host = _make_geographic_element(empty_project_file)
        with pytest.raises(ValueError, match="points must not be empty"):
            add_tin_representation(empty_project_file, host, [], [])

    def test_empty_triangles_raises(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.surface import add_tin_representation

        host = _make_geographic_element(empty_project_file)
        with pytest.raises(ValueError, match="triangles must not be empty"):
            add_tin_representation(empty_project_file, host, [(0.0, 0.0, 0.0)], [])

    def test_out_of_range_index_raises(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.surface import add_tin_representation

        host = _make_geographic_element(empty_project_file)
        points = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        with pytest.raises(ValueError, match="out of range"):
            add_tin_representation(empty_project_file, host, points, [(0, 1, 5)])

    def test_round_trip_through_disk(
        self, empty_project_file: ifcopenshell.file, tmp_path
    ) -> None:
        from ifcopenshell.api.surface import add_tin_representation

        host = _make_geographic_element(empty_project_file, name="Pyramid")
        points, triangles = _pyramid_geometry()
        flags = [10, 20, 30, 40, 50, 60]
        add_tin_representation(empty_project_file, host, points, triangles, triangle_flags=flags)

        path = tmp_path / "pyramid.ifc"
        empty_project_file.write(str(path))
        reopened = ifcopenshell.open(str(path))

        terrains = [e for e in reopened.by_type("IfcGeographicElement") if e.Name == "Pyramid"]
        assert len(terrains) == 1
        rep = terrains[0].Representation.Representations[0]
        tin = rep.Items[0]
        assert tin.is_a("IfcTriangulatedIrregularNetwork")
        assert len(tin.Coordinates.CoordList) == 5
        assert len(tin.CoordIndex) == 6
        assert list(tin.Flags) == flags
        for triangle in tin.CoordIndex:
            for index in triangle:
                assert 1 <= index <= 5

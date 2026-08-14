# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2026 Michael Yoder <myoder@desertspringscivil.com>
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

    def test_creates_body_subcontext_on_empty_file(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.surface import _representation_context

        sub = _representation_context.get_body_subcontext(empty_project_file)
        assert sub.is_a("IfcGeometricRepresentationSubContext")
        assert sub.ContextIdentifier == "Body"
        assert sub.TargetView == "MODEL_VIEW"
        assert sub.ParentContext.is_a("IfcGeometricRepresentationContext")
        assert sub.ParentContext.ContextType == "Model"

    def test_lookup_is_idempotent(self, empty_project_file: ifcopenshell.file) -> None:
        """Calling twice must return the same subcontext entity, not a duplicate."""
        from ifcopenshell.api.surface import _representation_context

        first = _representation_context.get_body_subcontext(empty_project_file)
        second = _representation_context.get_body_subcontext(empty_project_file)
        assert first.id() == second.id()
        # Only one Model context, only one Body subcontext.
        contexts = empty_project_file.by_type("IfcGeometricRepresentationContext", include_subtypes=False)
        subcontexts = [
            c
            for c in empty_project_file.by_type("IfcGeometricRepresentationSubContext")
            if c.ContextIdentifier == "Body"
        ]
        assert len(contexts) == 1
        assert len(subcontexts) == 1

    def test_box_and_body_subcontexts_share_parent(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.surface import _representation_context

        body = _representation_context.get_body_subcontext(empty_project_file)
        box = _representation_context.get_box_subcontext(empty_project_file)
        assert body.ParentContext.id() == box.ParentContext.id()
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
        assert rep.RepresentationIdentifier == "Body"
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
        assert rep_identifiers == {"Box", "Body"}

    def test_double_add_raises_value_error(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.surface import add_tin_representation

        host = _make_geographic_element(empty_project_file)
        points, triangles = _flat_pad_geometry()
        add_tin_representation(empty_project_file, host, points, triangles)

        with pytest.raises(ValueError, match="Body"):
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


class TestAddBoundingBoxRepresentation:
    """Tests for ``ifcopenshell.api.surface.add_bounding_box_representation``."""

    def test_happy_path(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.surface import add_bounding_box_representation

        host = _make_geographic_element(empty_project_file)
        box = add_bounding_box_representation(
            empty_project_file, host, min_xyz=(0.0, 0.0, 0.0), max_xyz=(10.0, 20.0, 5.0)
        )

        assert box.is_a("IfcBoundingBox")
        assert tuple(box.Corner.Coordinates) == (0.0, 0.0, 0.0)
        assert box.XDim == 10.0
        assert box.YDim == 20.0
        assert box.ZDim == 5.0

        rep = host.Representation.Representations[0]
        assert rep.RepresentationIdentifier == "Box"
        assert rep.RepresentationType == "BoundingBox"

    def test_negative_min_corner(self, empty_project_file: ifcopenshell.file) -> None:
        """A box with negative min coordinates is fine as long as max > min on every axis."""
        from ifcopenshell.api.surface import add_bounding_box_representation

        host = _make_geographic_element(empty_project_file)
        box = add_bounding_box_representation(
            empty_project_file, host, min_xyz=(-5.0, -5.0, -1.0), max_xyz=(5.0, 5.0, 1.0)
        )
        assert tuple(box.Corner.Coordinates) == (-5.0, -5.0, -1.0)
        assert box.XDim == 10.0

    def test_zero_dimension_raises(self, empty_project_file: ifcopenshell.file) -> None:
        """IFC requires IfcPositiveLengthMeasure — zero dim is invalid."""
        from ifcopenshell.api.surface import add_bounding_box_representation

        host = _make_geographic_element(empty_project_file)
        with pytest.raises(ValueError, match="strictly greater"):
            add_bounding_box_representation(
                empty_project_file, host, min_xyz=(0.0, 0.0, 0.0), max_xyz=(10.0, 0.0, 5.0)
            )

    def test_inverted_corner_raises(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.surface import add_bounding_box_representation

        host = _make_geographic_element(empty_project_file)
        with pytest.raises(ValueError, match="strictly greater"):
            add_bounding_box_representation(
                empty_project_file, host, min_xyz=(10.0, 0.0, 0.0), max_xyz=(0.0, 10.0, 5.0)
            )

    def test_double_add_raises(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.surface import add_bounding_box_representation

        host = _make_geographic_element(empty_project_file)
        add_bounding_box_representation(
            empty_project_file, host, min_xyz=(0.0, 0.0, 0.0), max_xyz=(1.0, 1.0, 1.0)
        )
        with pytest.raises(ValueError, match="Box representation"):
            add_bounding_box_representation(
                empty_project_file, host, min_xyz=(0.0, 0.0, 0.0), max_xyz=(1.0, 1.0, 1.0)
            )

    def test_round_trip_through_disk(
        self, empty_project_file: ifcopenshell.file, tmp_path
    ) -> None:
        from ifcopenshell.api.surface import add_bounding_box_representation

        host = _make_geographic_element(empty_project_file, name="WithBox")
        add_bounding_box_representation(
            empty_project_file, host, min_xyz=(1.0, 2.0, 3.0), max_xyz=(4.0, 6.0, 9.0)
        )

        path = tmp_path / "with_box.ifc"
        empty_project_file.write(str(path))
        reopened = ifcopenshell.open(str(path))
        host_again = [e for e in reopened.by_type("IfcGeographicElement") if e.Name == "WithBox"][0]
        rep = host_again.Representation.Representations[0]
        assert rep.RepresentationIdentifier == "Box"
        box = rep.Items[0]
        assert tuple(box.Corner.Coordinates) == (1.0, 2.0, 3.0)
        assert (box.XDim, box.YDim, box.ZDim) == (3.0, 4.0, 6.0)


class TestApplySaikeiPset:
    """Tests for ``ifcopenshell.api.surface.apply_saikei_pset``."""

    def _read_back_properties(self, pset: ifcopenshell.entity_instance) -> dict[str, object]:
        """Translate IfcPropertySet.HasProperties into a flat name→value dict."""
        out: dict[str, object] = {}
        for prop in pset.HasProperties or []:
            if prop.is_a("IfcPropertySingleValue") and prop.NominalValue is not None:
                out[prop.Name] = prop.NominalValue.wrappedValue
        return out

    def test_creates_pset_with_defaults(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.surface import apply_saikei_pset

        host = _make_geographic_element(empty_project_file)
        pset = apply_saikei_pset(empty_project_file, host)

        assert pset.is_a("IfcPropertySet")
        assert pset.Name == "Pset_SaikeiGradingSurface"
        properties = self._read_back_properties(pset)
        assert properties["TriangulationTolerance"] == 0.0
        assert properties["BreaklineCount"] == 0
        # VertexCount is omitted when no Body rep exists.
        assert "VertexCount" not in properties
        assert "BoundaryPolygonReference" not in properties

    def test_explicit_values_persist(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.surface import apply_saikei_pset

        host = _make_geographic_element(empty_project_file)
        pset = apply_saikei_pset(
            empty_project_file,
            host,
            triangulation_tolerance=0.005,
            breakline_count=4,
            vertex_count=1234,
            boundary_polygon_reference="3VxJzKQwT9XwJZ8RbZkH7E",
        )

        properties = self._read_back_properties(pset)
        assert properties["TriangulationTolerance"] == 0.005
        assert properties["BreaklineCount"] == 4
        assert properties["VertexCount"] == 1234
        assert properties["BoundaryPolygonReference"] == "3VxJzKQwT9XwJZ8RbZkH7E"

    def test_vertex_count_inferred_from_existing_tin(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        """If vertex_count is None, the function reads the Body TIN's point count."""
        from ifcopenshell.api.surface import add_tin_representation, apply_saikei_pset

        host = _make_geographic_element(empty_project_file)
        points, triangles = _flat_pad_geometry()
        add_tin_representation(empty_project_file, host, points, triangles)

        pset = apply_saikei_pset(empty_project_file, host)
        properties = self._read_back_properties(pset)
        assert properties["VertexCount"] == len(points)

    def test_second_call_updates_in_place(self, empty_project_file: ifcopenshell.file) -> None:
        """Re-applying must update the pset rather than creating a duplicate."""
        from ifcopenshell.api.surface import apply_saikei_pset

        host = _make_geographic_element(empty_project_file)
        first = apply_saikei_pset(empty_project_file, host, triangulation_tolerance=0.001)
        second = apply_saikei_pset(empty_project_file, host, triangulation_tolerance=0.005, breakline_count=7)

        assert first.id() == second.id()
        properties = self._read_back_properties(second)
        assert properties["TriangulationTolerance"] == 0.005
        assert properties["BreaklineCount"] == 7

        # Exactly one IfcRelDefinesByProperties for this pset.
        rels = [
            r
            for r in host.IsDefinedBy or []
            if r.is_a("IfcRelDefinesByProperties")
            and r.RelatingPropertyDefinition.Name == "Pset_SaikeiGradingSurface"
        ]
        assert len(rels) == 1

    def test_round_trip_through_disk(
        self, empty_project_file: ifcopenshell.file, tmp_path
    ) -> None:
        from ifcopenshell.api.surface import apply_saikei_pset

        host = _make_geographic_element(empty_project_file, name="WithPset")
        apply_saikei_pset(
            empty_project_file,
            host,
            triangulation_tolerance=0.01,
            breakline_count=2,
            vertex_count=42,
            boundary_polygon_reference="abc123",
        )

        path = tmp_path / "with_pset.ifc"
        empty_project_file.write(str(path))
        reopened = ifcopenshell.open(str(path))
        host_again = [e for e in reopened.by_type("IfcGeographicElement") if e.Name == "WithPset"][0]
        psets = [
            r.RelatingPropertyDefinition
            for r in host_again.IsDefinedBy or []
            if r.is_a("IfcRelDefinesByProperties")
            and r.RelatingPropertyDefinition.Name == "Pset_SaikeiGradingSurface"
        ]
        assert len(psets) == 1
        properties = self._read_back_properties(psets[0])
        assert properties["TriangulationTolerance"] == 0.01
        assert properties["BreaklineCount"] == 2
        assert properties["VertexCount"] == 42
        assert properties["BoundaryPolygonReference"] == "abc123"


def _empty_project_file_no_site() -> ifcopenshell.file:
    """Build a minimal IFC4X3_ADD2 file with an IfcProject + unit, but no IfcSite."""
    file = ifcopenshell.file(schema="IFC4X3_ADD2")
    file.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), Name="Test Project")
    length_unit = ifcopenshell.api.unit.add_si_unit(file, unit_type="LENGTHUNIT")
    ifcopenshell.api.unit.assign_unit(file, units=[length_unit])
    return file


class TestCreateTerrain:
    """Tests for ``ifcopenshell.api.surface.create_terrain``."""

    def _read_pset(
        self, product: ifcopenshell.entity_instance, pset_name: str
    ) -> dict[str, object]:
        for rel in product.IsDefinedBy or []:
            if not rel.is_a("IfcRelDefinesByProperties"):
                continue
            pset = rel.RelatingPropertyDefinition
            if pset.is_a("IfcPropertySet") and pset.Name == pset_name:
                return {
                    p.Name: p.NominalValue.wrappedValue
                    for p in pset.HasProperties or []
                    if p.is_a("IfcPropertySingleValue") and p.NominalValue is not None
                }
        return {}

    def test_happy_path(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.surface import create_terrain

        points, triangles = _flat_pad_geometry()
        terrain = create_terrain(
            empty_project_file,
            name="Existing Ground",
            points=points,
            triangles=triangles,
            triangulation_tolerance=0.005,
            breakline_count=0,
        )

        assert terrain.is_a("IfcGeographicElement")
        assert terrain.PredefinedType == "TERRAIN"
        assert terrain.Name == "Existing Ground"

        # Has both Body and Box reps.
        rep_identifiers = {
            r.RepresentationIdentifier for r in terrain.Representation.Representations
        }
        assert rep_identifiers == {"Body", "Box"}

        # Contained in the site.
        containers = [
            r
            for r in terrain.ContainedInStructure or []
            if r.is_a("IfcRelContainedInSpatialStructure")
        ]
        assert len(containers) == 1
        assert containers[0].RelatingStructure.is_a("IfcSite")

        # Standard pset present.
        common = self._read_pset(terrain, "Pset_GeographicElementCommon")
        assert common.get("Status") == "NEW"

        # Saikei pset present and populated.
        saikei = self._read_pset(terrain, "Pset_SaikeiGradingSurface")
        assert saikei["TriangulationTolerance"] == 0.005
        assert saikei["BreaklineCount"] == 0
        assert saikei["VertexCount"] == len(points)

        # OmniClass classification — distinguishes terrain from proposed
        # surfaces beyond entity-type + name (per
        # SURFACES_GRADING_EARTHWORKS.md Principle #8).
        rels = [
            r
            for r in empty_project_file.by_type("IfcRelAssociatesClassification")
            if terrain in r.RelatedObjects
        ]
        assert len(rels) == 1
        ref = rels[0].RelatingClassification
        assert ref.is_a("IfcClassificationReference")
        assert ref.Identification == "22-07 31 13"
        assert ref.Name == "Site Preparation"

    def test_site_auto_resolution(self, empty_project_file: ifcopenshell.file) -> None:
        """When site=None, the project's first IfcSite is used."""
        from ifcopenshell.api.surface import create_terrain

        points, triangles = _flat_pad_geometry()
        terrain = create_terrain(
            empty_project_file, name="A", points=points, triangles=triangles
        )

        rel = (terrain.ContainedInStructure or [None])[0]
        assert rel is not None
        assert rel.RelatingStructure.id() == _site(empty_project_file).id()

    def test_explicit_site_overrides_auto(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.surface import create_terrain

        # Add a second site and pass it explicitly.
        second_site = empty_project_file.create_entity(
            "IfcSite", GlobalId=ifcopenshell.guid.new(), Name="Second Site"
        )
        empty_project_file.create_entity(
            "IfcRelAggregates",
            GlobalId=ifcopenshell.guid.new(),
            RelatingObject=empty_project_file.by_type("IfcProject")[0],
            RelatedObjects=[second_site],
        )
        points, triangles = _flat_pad_geometry()
        terrain = create_terrain(
            empty_project_file, name="A", points=points, triangles=triangles, site=second_site
        )

        rel = (terrain.ContainedInStructure or [None])[0]
        assert rel.RelatingStructure.id() == second_site.id()

    def test_raises_when_no_site(self) -> None:
        from ifcopenshell.api.surface import create_terrain

        file = _empty_project_file_no_site()
        points, triangles = _flat_pad_geometry()
        with pytest.raises(ValueError, match="no IfcSite"):
            create_terrain(file, name="A", points=points, triangles=triangles)

    def test_empty_points_raises(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.surface import create_terrain

        with pytest.raises(ValueError, match="points must not be empty"):
            create_terrain(empty_project_file, name="A", points=[], triangles=[])

    def test_out_of_range_triangle_index_raises(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.surface import create_terrain

        points = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        with pytest.raises(ValueError, match="out of range"):
            create_terrain(
                empty_project_file, name="A", points=points, triangles=[(0, 1, 7)]
            )

    def test_round_trip_through_disk(
        self, empty_project_file: ifcopenshell.file, tmp_path
    ) -> None:
        from ifcopenshell.api.surface import create_terrain

        points, triangles = _pyramid_geometry()
        create_terrain(
            empty_project_file,
            name="RTPyramid",
            points=points,
            triangles=triangles,
            triangulation_tolerance=0.01,
            breakline_count=3,
        )

        path = tmp_path / "rt.ifc"
        empty_project_file.write(str(path))
        reopened = ifcopenshell.open(str(path))
        terrains = [
            e for e in reopened.by_type("IfcGeographicElement") if e.Name == "RTPyramid"
        ]
        assert len(terrains) == 1
        terrain = terrains[0]
        assert terrain.PredefinedType == "TERRAIN"
        rep_identifiers = {
            r.RepresentationIdentifier for r in terrain.Representation.Representations
        }
        assert rep_identifiers == {"Body", "Box"}
        saikei_pset = self._read_pset(terrain, "Pset_SaikeiGradingSurface")
        assert saikei_pset["TriangulationTolerance"] == 0.01
        assert saikei_pset["BreaklineCount"] == 3
        assert saikei_pset["VertexCount"] == 5


class TestCreateProposedSurface:
    """Tests for ``ifcopenshell.api.surface.create_proposed_surface``."""

    def _read_pset(
        self, product: ifcopenshell.entity_instance, pset_name: str
    ) -> dict[str, object]:
        for rel in product.IsDefinedBy or []:
            if not rel.is_a("IfcRelDefinesByProperties"):
                continue
            pset = rel.RelatingPropertyDefinition
            if pset.is_a("IfcPropertySet") and pset.Name == pset_name:
                return {
                    p.Name: p.NominalValue.wrappedValue
                    for p in pset.HasProperties or []
                    if p.is_a("IfcPropertySingleValue") and p.NominalValue is not None
                }
        return {}

    def test_happy_path(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.surface import create_proposed_surface

        points, triangles = _flat_pad_geometry()
        proposed = create_proposed_surface(
            empty_project_file,
            name="Proposed Subgrade",
            points=points,
            triangles=triangles,
            triangulation_tolerance=0.002,
            breakline_count=1,
        )

        assert proposed.is_a("IfcEarthworksFill")
        assert proposed.PredefinedType == "SUBGRADE"
        assert proposed.Name == "Proposed Subgrade"

        rep_identifiers = {
            r.RepresentationIdentifier for r in proposed.Representation.Representations
        }
        assert rep_identifiers == {"Body", "Box"}

        rel = (proposed.ContainedInStructure or [None])[0]
        assert rel is not None and rel.RelatingStructure.is_a("IfcSite")

        common = self._read_pset(proposed, "Pset_EarthworksFillCommon")
        assert common.get("Status") == "NEW"
        # Geographic-element pset must NOT be attached to a fill.
        assert self._read_pset(proposed, "Pset_GeographicElementCommon") == {}

        saikei = self._read_pset(proposed, "Pset_SaikeiGradingSurface")
        assert saikei["TriangulationTolerance"] == 0.002
        assert saikei["BreaklineCount"] == 1
        assert saikei["VertexCount"] == len(points)

        # OmniClass classification — proposed surfaces share the slope-fill
        # default code (22-07 31 23 Fill) so they're distinguishable from
        # terrains (22-07 31 13 Site Preparation).
        rels = [
            r
            for r in empty_project_file.by_type("IfcRelAssociatesClassification")
            if proposed in r.RelatedObjects
        ]
        assert len(rels) == 1
        ref = rels[0].RelatingClassification
        assert ref.Identification == "22-07 31 23"
        assert ref.Name == "Fill"

    def test_raises_when_no_site(self) -> None:
        from ifcopenshell.api.surface import create_proposed_surface

        file = _empty_project_file_no_site()
        points, triangles = _flat_pad_geometry()
        with pytest.raises(ValueError, match="no IfcSite"):
            create_proposed_surface(file, name="A", points=points, triangles=triangles)

    def test_empty_points_raises(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.surface import create_proposed_surface

        with pytest.raises(ValueError, match="points must not be empty"):
            create_proposed_surface(empty_project_file, name="A", points=[], triangles=[])

    def test_round_trip_through_disk(
        self, empty_project_file: ifcopenshell.file, tmp_path
    ) -> None:
        from ifcopenshell.api.surface import create_proposed_surface

        points, triangles = _pyramid_geometry()
        create_proposed_surface(
            empty_project_file,
            name="RTSubgrade",
            points=points,
            triangles=triangles,
            triangulation_tolerance=0.003,
            breakline_count=2,
        )

        path = tmp_path / "rt_proposed.ifc"
        empty_project_file.write(str(path))
        reopened = ifcopenshell.open(str(path))
        proposed = [
            e for e in reopened.by_type("IfcEarthworksFill") if e.Name == "RTSubgrade"
        ]
        assert len(proposed) == 1
        assert proposed[0].PredefinedType == "SUBGRADE"
        saikei = self._read_pset(proposed[0], "Pset_SaikeiGradingSurface")
        assert saikei["TriangulationTolerance"] == 0.003
        assert saikei["BreaklineCount"] == 2
        assert saikei["VertexCount"] == 5


class TestAddBreaklineAnnotation:
    """Tests for ``ifcopenshell.api.surface.add_breakline_annotation``."""

    def _read_pset(
        self, product: ifcopenshell.entity_instance, pset_name: str
    ) -> dict[str, object]:
        for rel in product.IsDefinedBy or []:
            if not rel.is_a("IfcRelDefinesByProperties"):
                continue
            pset = rel.RelatingPropertyDefinition
            if pset.is_a("IfcPropertySet") and pset.Name == pset_name:
                return {
                    p.Name: p.NominalValue.wrappedValue
                    for p in pset.HasProperties or []
                    if p.is_a("IfcPropertySingleValue") and p.NominalValue is not None
                }
        return {}

    def test_happy_path(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.surface import add_breakline_annotation

        site = _site(empty_project_file)
        polyline = [(0.0, 0.0, 0.0), (10.0, 0.0, 1.0), (20.0, 5.0, 2.0)]
        breakline = add_breakline_annotation(
            empty_project_file, site=site, polyline=polyline, name="Top of curb"
        )

        assert breakline.is_a("IfcAnnotation")
        assert breakline.Name == "Top of curb"
        assert breakline.ObjectType == "BREAKLINE"
        assert breakline.PredefinedType == "USERDEFINED"

        rep = breakline.Representation.Representations[0]
        assert rep.RepresentationIdentifier == "Annotation"
        assert rep.RepresentationType == "Curve3D"
        polyline_entity = rep.Items[0]
        assert polyline_entity.is_a("IfcPolyline")
        assert len(polyline_entity.Points) == 3
        assert tuple(polyline_entity.Points[0].Coordinates) == (0.0, 0.0, 0.0)

        rel = (breakline.ContainedInStructure or [None])[0]
        assert rel is not None and rel.RelatingStructure.id() == site.id()

        properties = self._read_pset(breakline, "Pset_SaikeiBreaklineCommon")
        assert properties["Kind"] == "standard"
        assert properties["Source"] == "manual"
        assert "GradingGroupGuid" not in properties

    def test_kind_and_source_persist(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.surface import add_breakline_annotation

        site = _site(empty_project_file)
        breakline = add_breakline_annotation(
            empty_project_file,
            site=site,
            polyline=[(0.0, 0.0, 0.0), (1.0, 1.0, 1.0)],
            name="Wall break",
            kind="wall",
            source="csv import",
            grading_group_guid="3VxJzKQwT9XwJZ8RbZkH7E",
        )

        properties = self._read_pset(breakline, "Pset_SaikeiBreaklineCommon")
        assert properties["Kind"] == "wall"
        assert properties["Source"] == "csv import"
        assert properties["GradingGroupGuid"] == "3VxJzKQwT9XwJZ8RbZkH7E"

    def test_short_polyline_raises(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.surface import add_breakline_annotation

        site = _site(empty_project_file)
        with pytest.raises(ValueError, match="at least two points"):
            add_breakline_annotation(
                empty_project_file, site=site, polyline=[(0.0, 0.0, 0.0)], name="Solo"
            )

    def test_invalid_kind_raises(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.surface import add_breakline_annotation

        site = _site(empty_project_file)
        with pytest.raises(ValueError, match="kind must be one of"):
            add_breakline_annotation(
                empty_project_file,
                site=site,
                polyline=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
                name="Bad",
                kind="explosive",
            )

    def test_round_trip_through_disk(
        self, empty_project_file: ifcopenshell.file, tmp_path
    ) -> None:
        from ifcopenshell.api.surface import add_breakline_annotation

        site = _site(empty_project_file)
        polyline = [(0.0, 0.0, 0.0), (5.0, 5.0, 1.0), (10.0, 0.0, 0.5)]
        add_breakline_annotation(
            empty_project_file,
            site=site,
            polyline=polyline,
            name="RTBreak",
            kind="non_destructive",
            source="survey",
        )

        path = tmp_path / "rt_breakline.ifc"
        empty_project_file.write(str(path))
        reopened = ifcopenshell.open(str(path))
        breaklines = [
            a for a in reopened.by_type("IfcAnnotation") if a.Name == "RTBreak"
        ]
        assert len(breaklines) == 1
        breakline = breaklines[0]
        rep = breakline.Representation.Representations[0]
        assert rep.RepresentationIdentifier == "Annotation"
        assert len(rep.Items[0].Points) == 3
        # Coords preserved through serialization
        round_trip_coords = [
            tuple(point.Coordinates) for point in rep.Items[0].Points
        ]
        assert round_trip_coords == polyline

        properties = self._read_pset(breakline, "Pset_SaikeiBreaklineCommon")
        assert properties["Kind"] == "non_destructive"
        assert properties["Source"] == "survey"


class TestUpdateTinRepresentation:
    """Tests for ``ifcopenshell.api.surface.update_tin_representation``."""

    def test_happy_path_replaces_in_place(self, empty_project_file: ifcopenshell.file) -> None:
        """The new TIN replaces the old; the IfcShapeRepresentation entity is preserved."""
        from ifcopenshell.api.surface import add_tin_representation, update_tin_representation

        host = _make_geographic_element(empty_project_file)
        points, triangles = _flat_pad_geometry()
        add_tin_representation(empty_project_file, host, points, triangles)
        old_rep_id = host.Representation.Representations[0].id()

        new_points, new_triangles = _pyramid_geometry()
        new_tin = update_tin_representation(
            empty_project_file, host, new_points, new_triangles
        )

        # Same shape representation, new items.
        assert host.Representation.Representations[0].id() == old_rep_id
        assert host.Representation.Representations[0].Items[0].id() == new_tin.id()
        assert new_tin.is_a("IfcTriangulatedIrregularNetwork")
        assert len(new_tin.Coordinates.CoordList) == len(new_points)
        assert len(new_tin.CoordIndex) == len(new_triangles)

    def test_old_entities_garbage_collected_when_orphaned(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.surface import add_tin_representation, update_tin_representation

        host = _make_geographic_element(empty_project_file)
        points, triangles = _flat_pad_geometry()
        add_tin_representation(empty_project_file, host, points, triangles)

        tins_before = len(empty_project_file.by_type("IfcTriangulatedIrregularNetwork"))
        coord_lists_before = len(empty_project_file.by_type("IfcCartesianPointList3D"))
        assert tins_before == 1
        assert coord_lists_before == 1

        update_tin_representation(empty_project_file, host, points, triangles)

        # Counts unchanged: old gc'd, new created.
        assert len(empty_project_file.by_type("IfcTriangulatedIrregularNetwork")) == 1
        assert len(empty_project_file.by_type("IfcCartesianPointList3D")) == 1

    def test_old_entities_kept_when_still_referenced(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        """If something else holds a reference to the old TIN, gc must not remove it."""
        from ifcopenshell.api.surface import add_tin_representation, update_tin_representation

        host = _make_geographic_element(empty_project_file)
        points, triangles = _flat_pad_geometry()
        old_tin = add_tin_representation(empty_project_file, host, points, triangles)

        # Park the old TIN inside a second (unrelated) shape representation so it has another inverse.
        from ifcopenshell.api.surface._representation_context import (
            get_body_subcontext,
        )

        unrelated_rep = empty_project_file.create_entity(
            "IfcShapeRepresentation",
            ContextOfItems=get_body_subcontext(empty_project_file),
            RepresentationIdentifier="Body",
            RepresentationType="Tessellation",
            Items=[old_tin],
        )
        assert unrelated_rep is not None

        update_tin_representation(empty_project_file, host, points, triangles)

        # Old TIN still alive because unrelated_rep references it.
        assert len(empty_project_file.by_type("IfcTriangulatedIrregularNetwork")) == 2

    def test_raises_when_no_existing_body_rep(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.surface import update_tin_representation

        host = _make_geographic_element(empty_project_file)
        points, triangles = _flat_pad_geometry()
        with pytest.raises(ValueError, match="no Body"):
            update_tin_representation(empty_project_file, host, points, triangles)

    def test_round_trip_through_disk(
        self, empty_project_file: ifcopenshell.file, tmp_path
    ) -> None:
        from ifcopenshell.api.surface import add_tin_representation, update_tin_representation

        host = _make_geographic_element(empty_project_file, name="Mutable")
        points, triangles = _flat_pad_geometry()
        add_tin_representation(empty_project_file, host, points, triangles)

        new_points, new_triangles = _pyramid_geometry()
        new_flags = [9, 8, 7, 6, 5, 4]
        update_tin_representation(
            empty_project_file, host, new_points, new_triangles, triangle_flags=new_flags
        )

        path = tmp_path / "updated.ifc"
        empty_project_file.write(str(path))
        reopened = ifcopenshell.open(str(path))
        host_again = [
            e for e in reopened.by_type("IfcGeographicElement") if e.Name == "Mutable"
        ][0]
        rep = [
            r
            for r in host_again.Representation.Representations
            if r.RepresentationIdentifier == "Body"
        ][0]
        tin = rep.Items[0]
        assert len(tin.Coordinates.CoordList) == len(new_points)
        assert list(tin.Flags) == new_flags


class TestSchemaValidation:
    """Validator integration: every authored entity tree must be schema-valid.

    The inline check runs ``ifcopenshell.validate.validate`` against a
    flat-pad demo file every time. The external bSI reference validator
    binary check is opt-in: set the ``BSI_VALIDATOR_PATH`` environment
    variable to an executable that takes one IFC path and returns 0 on
    success. CI is expected to provide that env var; local runs skip.
    """

    def _build_flat_pad_demo(
        self, file: ifcopenshell.file
    ) -> ifcopenshell.entity_instance:
        from ifcopenshell.api.surface import (
            add_breakline_annotation,
            create_terrain,
        )

        points, triangles = _flat_pad_geometry()
        terrain = create_terrain(
            file,
            name="Validator Pad",
            points=points,
            triangles=triangles,
            triangulation_tolerance=0.005,
            breakline_count=1,
        )
        add_breakline_annotation(
            file,
            site=_site(file),
            polyline=[(0.0, 50.0, 100.0), (100.0, 50.0, 100.0)],
            name="Centerline break",
            kind="standard",
            source="hand",
        )
        return terrain

    def test_inline_ifcopenshell_validate(
        self, empty_project_file: ifcopenshell.file, tmp_path
    ) -> None:
        """Run ifcopenshell.validate over a fully-authored flat-pad demo file."""
        import logging

        import ifcopenshell.validate

        self._build_flat_pad_demo(empty_project_file)

        path = tmp_path / "validator_demo.ifc"
        empty_project_file.write(str(path))
        reopened = ifcopenshell.open(str(path))

        records: list[logging.LogRecord] = []

        class _CollectingHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        logger = logging.Logger("surface-validate")
        logger.addHandler(_CollectingHandler(level=logging.DEBUG))

        ifcopenshell.validate.validate(reopened, logger)

        errors = [r.getMessage() for r in records if r.levelno >= logging.WARNING]
        assert errors == [], f"validate() reported issues: {errors}"

    def test_external_bsi_validator_if_present(
        self, empty_project_file: ifcopenshell.file, tmp_path
    ) -> None:
        """Optional: run an external bSI validator binary on the demo file."""
        import os
        import shutil
        import subprocess

        validator_path = os.environ.get("BSI_VALIDATOR_PATH")
        if validator_path is None:
            pytest.skip("BSI_VALIDATOR_PATH not set; skipping external validator test")
        if not shutil.which(validator_path) and not os.path.isfile(validator_path):
            pytest.skip(f"validator at {validator_path!r} not executable; skipping")

        self._build_flat_pad_demo(empty_project_file)
        path = tmp_path / "validator_demo.ifc"
        empty_project_file.write(str(path))

        result = subprocess.run(
            [validator_path, str(path)], capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, (
            f"bSI validator returned {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

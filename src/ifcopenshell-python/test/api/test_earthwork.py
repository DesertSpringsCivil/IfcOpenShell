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

"""Tests for ``ifcopenshell.api.earthwork``.

Pure pytest suite — no Blender, no bpy. Each public function gets its own
test class. Round-trip discipline: every "creates an entity" test writes the
file to disk, reopens it, and asserts the structure is preserved.
Idempotent operations get an extra "call twice with different values" test
asserting the persisted entity is updated in place rather than duplicated.
"""

import warnings

import ifcopenshell
import ifcopenshell.api.unit
import pytest


def _empty_project_file() -> ifcopenshell.file:
    """Build a minimal IFC4X3_ADD2 file with an IfcProject, SI unit, and IfcSite."""
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


def _read_pset(
    product: ifcopenshell.entity_instance, pset_name: str
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


def _make_cut(file: ifcopenshell.file, name: str = "Test Cut") -> ifcopenshell.entity_instance:
    return file.create_entity(
        "IfcEarthworksCut",
        GlobalId=ifcopenshell.guid.new(),
        Name=name,
        PredefinedType="EXCAVATION",
    )


def test_package_importable() -> None:
    """Smoke test: the package imports and exposes the expected docstring."""
    import ifcopenshell.api.earthwork

    assert ifcopenshell.api.earthwork.__doc__ is not None
    assert "earthwork" in ifcopenshell.api.earthwork.__doc__.lower()


class TestSharedHelpers:
    """Tests for the earthwork-specific helpers in ``_shared``."""

    def test_attach_earthworks_cut_common_creates_status_pset(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.earthwork._shared import attach_earthworks_cut_common

        cut = _make_cut(empty_project_file)
        pset = attach_earthworks_cut_common(empty_project_file, cut)

        assert pset.is_a("IfcPropertySet")
        assert pset.Name == "Pset_EarthworksCutCommon"
        properties = _read_pset(cut, "Pset_EarthworksCutCommon")
        assert properties.get("Status") == "NEW"

    def test_validate_cut_predefined_type_accepts_known_values(self) -> None:
        from ifcopenshell.api.earthwork._shared import (
            ALLOWED_CUT_TYPES,
            validate_cut_predefined_type,
        )

        # Spot-check each allowed value doesn't raise.
        for value in ALLOWED_CUT_TYPES:
            validate_cut_predefined_type(value)

    def test_validate_cut_predefined_type_rejects_unknown(self) -> None:
        from ifcopenshell.api.earthwork._shared import validate_cut_predefined_type

        with pytest.raises(ValueError, match="predefined_type must be one of"):
            validate_cut_predefined_type("CUTTING")  # close but not in the enum
        with pytest.raises(ValueError, match="predefined_type must be one of"):
            validate_cut_predefined_type("invented")

    def test_validate_fill_predefined_type_accepts_phase3_values(self) -> None:
        from ifcopenshell.api.earthwork._shared import (
            PHASE3_FILL_TYPES,
            validate_fill_predefined_type,
        )

        for value in PHASE3_FILL_TYPES:
            with warnings.catch_warnings():
                warnings.simplefilter("error")  # any warning fails the test
                validate_fill_predefined_type(value)

    def test_validate_fill_predefined_type_warns_on_phase2_reserved(self) -> None:
        from ifcopenshell.api.earthwork._shared import validate_fill_predefined_type

        for value in ("SLOPEFILL", "SUBGRADE"):
            with pytest.warns(UserWarning, match="reserved by ifcopenshell.api.grading"):
                validate_fill_predefined_type(value)

    def test_validate_fill_predefined_type_rejects_unknown(self) -> None:
        from ifcopenshell.api.earthwork._shared import validate_fill_predefined_type

        with pytest.raises(ValueError, match="must be a valid IfcEarthworksFillTypeEnum"):
            validate_fill_predefined_type("invented")


def _make_fill(file: ifcopenshell.file, name: str = "Test Fill") -> ifcopenshell.entity_instance:
    return file.create_entity(
        "IfcEarthworksFill",
        GlobalId=ifcopenshell.guid.new(),
        Name=name,
        PredefinedType="EMBANKMENT",
    )


def _tetrahedron_solid_geometry() -> tuple[
    list[tuple[float, float, float]], list[list[int]]
]:
    """4 vertices + 4 triangular faces forming a closed tetrahedron (signed volume = 1/6)."""
    points = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    ]
    # Counterclockwise from outside.
    faces = [
        [0, 2, 1],  # base z=0
        [0, 1, 3],  # y=0 face
        [1, 2, 3],  # diagonal face
        [0, 3, 2],  # x=0 face
    ]
    return points, faces


def _cube_solid_geometry() -> tuple[
    list[tuple[float, float, float]], list[list[int]]
]:
    """8 vertices + 6 quad faces forming a closed unit cube. Volume = 1."""
    points = [
        (0.0, 0.0, 0.0),  # 0
        (1.0, 0.0, 0.0),  # 1
        (1.0, 1.0, 0.0),  # 2
        (0.0, 1.0, 0.0),  # 3
        (0.0, 0.0, 1.0),  # 4
        (1.0, 0.0, 1.0),  # 5
        (1.0, 1.0, 1.0),  # 6
        (0.0, 1.0, 1.0),  # 7
    ]
    faces = [
        [0, 3, 2, 1],  # bottom z=0 (CCW from below)
        [4, 5, 6, 7],  # top z=1
        [0, 1, 5, 4],  # y=0
        [2, 3, 7, 6],  # y=1
        [1, 2, 6, 5],  # x=1
        [0, 4, 7, 3],  # x=0
    ]
    return points, faces


def _mixed_arity_solid_geometry() -> tuple[
    list[tuple[float, float, float]], list[list[int]]
]:
    """A 5-vertex pyramid: 4-vertex square base + 4 triangular sides. Mixed face arity."""
    points = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (1.0, 1.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.5, 0.5, 1.0),  # apex
    ]
    faces = [
        [0, 3, 2, 1],  # square base (4 vertices)
        [0, 1, 4],     # 4 triangular sides
        [1, 2, 4],
        [2, 3, 4],
        [3, 0, 4],
    ]
    return points, faces


class TestAddVolumeSolidRepresentation:
    """Tests for ``ifcopenshell.api.earthwork.add_volume_solid_representation``."""

    def test_happy_path_on_cube(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.earthwork import add_volume_solid_representation

        cut = _make_cut(empty_project_file)
        points, faces = _cube_solid_geometry()

        face_set = add_volume_solid_representation(
            empty_project_file, cut, points, faces
        )

        assert face_set.is_a("IfcPolygonalFaceSet")
        assert face_set.Closed is True
        assert face_set.Coordinates.is_a("IfcCartesianPointList3D")
        assert len(face_set.Coordinates.CoordList) == 8
        assert len(face_set.Faces) == 6
        # All face indices must be 1-based and in the valid range.
        for face in face_set.Faces:
            for index in face.CoordIndex:
                assert 1 <= index <= 8

        rep = cut.Representation.Representations[0]
        assert rep.RepresentationIdentifier == "Body"
        assert rep.RepresentationType == "Tessellation"
        assert rep.Items[0].id() == face_set.id()

    def test_one_based_index_conversion(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        """0-based input becomes 1-based in IFC."""
        from ifcopenshell.api.earthwork import add_volume_solid_representation

        cut = _make_cut(empty_project_file)
        points, faces = _tetrahedron_solid_geometry()

        face_set = add_volume_solid_representation(empty_project_file, cut, points, faces)
        assert list(face_set.Faces[0].CoordIndex) == [1, 3, 2]

    def test_mixed_face_arity(self, empty_project_file: ifcopenshell.file) -> None:
        """Triangles and quads can coexist in the same face set."""
        from ifcopenshell.api.earthwork import add_volume_solid_representation

        cut = _make_cut(empty_project_file)
        points, faces = _mixed_arity_solid_geometry()

        face_set = add_volume_solid_representation(empty_project_file, cut, points, faces)
        face_arities = [len(face.CoordIndex) for face in face_set.Faces]
        assert sorted(face_arities) == [3, 3, 3, 3, 4]

    def test_closed_kwarg_persists(self, empty_project_file: ifcopenshell.file) -> None:
        """Open meshes (Closed=False) are also valid for IfcPolygonalFaceSet."""
        from ifcopenshell.api.earthwork import add_volume_solid_representation

        cut = _make_cut(empty_project_file)
        points, faces = _tetrahedron_solid_geometry()
        face_set = add_volume_solid_representation(
            empty_project_file, cut, points, faces, closed=False
        )
        assert face_set.Closed is False

    def test_works_on_fill_too(self, empty_project_file: ifcopenshell.file) -> None:
        """The function takes any IfcProduct, not just IfcEarthworksCut."""
        from ifcopenshell.api.earthwork import add_volume_solid_representation

        fill = _make_fill(empty_project_file)
        points, faces = _cube_solid_geometry()
        face_set = add_volume_solid_representation(
            empty_project_file, fill, points, faces
        )
        assert fill.Representation.Representations[0].Items[0].id() == face_set.id()

    def test_double_add_raises(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.earthwork import add_volume_solid_representation

        cut = _make_cut(empty_project_file)
        points, faces = _tetrahedron_solid_geometry()
        add_volume_solid_representation(empty_project_file, cut, points, faces)

        with pytest.raises(ValueError, match="already has a Body representation"):
            add_volume_solid_representation(empty_project_file, cut, points, faces)

    def test_empty_points_raises(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.earthwork import add_volume_solid_representation

        cut = _make_cut(empty_project_file)
        with pytest.raises(ValueError, match="points must not be empty"):
            add_volume_solid_representation(empty_project_file, cut, [], [])

    def test_empty_faces_raises(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.earthwork import add_volume_solid_representation

        cut = _make_cut(empty_project_file)
        with pytest.raises(ValueError, match="faces must not be empty"):
            add_volume_solid_representation(
                empty_project_file, cut, [(0.0, 0.0, 0.0)], []
            )

    def test_face_with_too_few_vertices_raises(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.earthwork import add_volume_solid_representation

        cut = _make_cut(empty_project_file)
        with pytest.raises(ValueError, match="requires at least 3"):
            add_volume_solid_representation(
                empty_project_file,
                cut,
                [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                [[0, 1]],  # only 2 vertices
            )

    def test_out_of_range_face_index_raises(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.earthwork import add_volume_solid_representation

        cut = _make_cut(empty_project_file)
        with pytest.raises(ValueError, match="outside the points array"):
            add_volume_solid_representation(
                empty_project_file,
                cut,
                [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                [[0, 1, 5]],
            )

    def test_round_trip(self, empty_project_file: ifcopenshell.file, tmp_path) -> None:
        from ifcopenshell.api.earthwork import add_volume_solid_representation

        cut = _make_cut(empty_project_file, name="RT")
        points, faces = _cube_solid_geometry()
        add_volume_solid_representation(empty_project_file, cut, points, faces)

        path = tmp_path / "rt_solid.ifc"
        empty_project_file.write(str(path))
        reopened = ifcopenshell.open(str(path))
        cuts = [c for c in reopened.by_type("IfcEarthworksCut") if c.Name == "RT"]
        assert len(cuts) == 1
        face_set = cuts[0].Representation.Representations[0].Items[0]
        assert face_set.is_a("IfcPolygonalFaceSet")
        assert face_set.Closed is True
        assert len(face_set.Coordinates.CoordList) == 8
        assert len(face_set.Faces) == 6
        for face in face_set.Faces:
            for index in face.CoordIndex:
                assert 1 <= index <= 8

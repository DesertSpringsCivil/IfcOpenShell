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


def _empty_project_file_no_site() -> ifcopenshell.file:
    file = ifcopenshell.file(schema="IFC4X3_ADD2")
    file.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), Name="No Site")
    length_unit = ifcopenshell.api.unit.add_si_unit(file, unit_type="LENGTHUNIT")
    ifcopenshell.api.unit.assign_unit(file, units=[length_unit])
    return file


class TestCreateEarthworksCut:
    """Tests for ``ifcopenshell.api.earthwork.create_earthworks_cut``."""

    def test_happy_path(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.earthwork import create_earthworks_cut

        points, faces = _cube_solid_geometry()
        cut = create_earthworks_cut(
            empty_project_file,
            name="Bulk excavation",
            points=points,
            faces=faces,
        )

        assert cut.is_a("IfcEarthworksCut")
        assert cut.Name == "Bulk excavation"
        assert cut.PredefinedType == "EXCAVATION"
        assert cut.ObjectPlacement is not None

    def test_contained_in_site(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.earthwork import create_earthworks_cut

        points, faces = _cube_solid_geometry()
        cut = create_earthworks_cut(
            empty_project_file, name="X", points=points, faces=faces
        )
        rel = (cut.ContainedInStructure or [None])[0]
        assert rel is not None
        assert rel.RelatingStructure.id() == _site(empty_project_file).id()

    def test_solid_body_representation_attached(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.earthwork import create_earthworks_cut

        points, faces = _cube_solid_geometry()
        cut = create_earthworks_cut(
            empty_project_file, name="X", points=points, faces=faces
        )
        rep = cut.Representation.Representations[0]
        assert rep.RepresentationIdentifier == "Body"
        assert rep.RepresentationType == "Tessellation"
        assert rep.Items[0].is_a("IfcPolygonalFaceSet")
        assert rep.Items[0].Closed is True

    def test_standard_pset_attached(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.earthwork import create_earthworks_cut

        points, faces = _tetrahedron_solid_geometry()
        cut = create_earthworks_cut(
            empty_project_file, name="X", points=points, faces=faces
        )
        common = _read_pset(cut, "Pset_EarthworksCutCommon")
        assert common.get("Status") == "NEW"

    def test_omniclass_classified_under_default_code(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.earthwork import create_earthworks_cut

        points, faces = _tetrahedron_solid_geometry()
        cut = create_earthworks_cut(
            empty_project_file, name="X", points=points, faces=faces
        )
        rels = empty_project_file.by_type("IfcRelAssociatesClassification")
        matching = [r for r in rels if cut in r.RelatedObjects]
        assert len(matching) == 1
        assert matching[0].RelatingClassification.Identification == "22-07 31 16"
        assert matching[0].RelatingClassification.Name == "Excavation and Fill"

    def test_explicit_omniclass_code_override(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        """Per the docstring: trench excavation gets a more specific code."""
        from ifcopenshell.api.earthwork import create_earthworks_cut

        points, faces = _tetrahedron_solid_geometry()
        cut = create_earthworks_cut(
            empty_project_file,
            name="Utility trench",
            points=points,
            faces=faces,
            predefined_type="TRENCH",
            omniclass_code="22-07 31 26",
            omniclass_title="Trench Excavation",
        )
        rels = empty_project_file.by_type("IfcRelAssociatesClassification")
        matching = [r for r in rels if cut in r.RelatedObjects]
        assert matching[0].RelatingClassification.Identification == "22-07 31 26"
        assert matching[0].RelatingClassification.Name == "Trench Excavation"

    def test_predefined_type_options(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        """Each valid predefined_type round-trips."""
        from ifcopenshell.api.earthwork import create_earthworks_cut

        for pt in ("CUT", "DREDGING", "TOPSOILREMOVAL", "TRENCH"):
            points, faces = _tetrahedron_solid_geometry()
            cut = create_earthworks_cut(
                empty_project_file,
                name=f"Cut-{pt}",
                points=points,
                faces=faces,
                predefined_type=pt,
            )
            assert cut.PredefinedType == pt

    def test_invalid_predefined_type_raises(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.earthwork import create_earthworks_cut

        points, faces = _tetrahedron_solid_geometry()
        with pytest.raises(ValueError, match="predefined_type must be one of"):
            create_earthworks_cut(
                empty_project_file,
                name="X",
                points=points,
                faces=faces,
                predefined_type="CUTTING",  # not in the IFC enum
            )

    def test_raises_when_no_site(self) -> None:
        from ifcopenshell.api.earthwork import create_earthworks_cut

        file = _empty_project_file_no_site()
        points, faces = _tetrahedron_solid_geometry()
        with pytest.raises(ValueError, match="no IfcSite"):
            create_earthworks_cut(file, name="X", points=points, faces=faces)

    def test_round_trip(self, empty_project_file: ifcopenshell.file, tmp_path) -> None:
        from ifcopenshell.api.earthwork import create_earthworks_cut

        points, faces = _cube_solid_geometry()
        create_earthworks_cut(
            empty_project_file,
            name="RTCut",
            points=points,
            faces=faces,
            predefined_type="DREDGING",
            omniclass_code="22-07 31 53",
            omniclass_title="Rock Removal",
        )

        path = tmp_path / "rt_cut.ifc"
        empty_project_file.write(str(path))
        reopened = ifcopenshell.open(str(path))
        cuts = [c for c in reopened.by_type("IfcEarthworksCut") if c.Name == "RTCut"]
        assert len(cuts) == 1
        cut = cuts[0]
        assert cut.PredefinedType == "DREDGING"
        rep = cut.Representation.Representations[0]
        assert rep.RepresentationIdentifier == "Body"
        face_set = rep.Items[0]
        assert face_set.Closed is True
        assert len(face_set.Faces) == 6
        common = _read_pset(cut, "Pset_EarthworksCutCommon")
        assert common.get("Status") == "NEW"
        rels = reopened.by_type("IfcRelAssociatesClassification")
        matching = [r for r in rels if cut in r.RelatedObjects]
        assert matching[0].RelatingClassification.Identification == "22-07 31 53"


class TestCreateEarthworksFill:
    """Tests for ``ifcopenshell.api.earthwork.create_earthworks_fill``."""

    def test_happy_path(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.earthwork import create_earthworks_fill

        points, faces = _cube_solid_geometry()
        fill = create_earthworks_fill(
            empty_project_file,
            name="Embankment",
            points=points,
            faces=faces,
        )

        assert fill.is_a("IfcEarthworksFill")
        assert fill.Name == "Embankment"
        assert fill.PredefinedType == "EMBANKMENT"

    def test_solid_body_representation_attached(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.earthwork import create_earthworks_fill

        points, faces = _cube_solid_geometry()
        fill = create_earthworks_fill(
            empty_project_file, name="X", points=points, faces=faces
        )
        rep = fill.Representation.Representations[0]
        assert rep.RepresentationIdentifier == "Body"
        assert rep.RepresentationType == "Tessellation"
        assert rep.Items[0].is_a("IfcPolygonalFaceSet")
        assert rep.Items[0].Closed is True

    def test_contained_in_site(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.earthwork import create_earthworks_fill

        points, faces = _cube_solid_geometry()
        fill = create_earthworks_fill(
            empty_project_file, name="X", points=points, faces=faces
        )
        rel = (fill.ContainedInStructure or [None])[0]
        assert rel is not None
        assert rel.RelatingStructure.id() == _site(empty_project_file).id()

    def test_standard_pset_attached(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.earthwork import create_earthworks_fill

        points, faces = _tetrahedron_solid_geometry()
        fill = create_earthworks_fill(
            empty_project_file, name="X", points=points, faces=faces
        )
        common = _read_pset(fill, "Pset_EarthworksFillCommon")
        assert common.get("Status") == "NEW"

    def test_omniclass_default(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.earthwork import create_earthworks_fill

        points, faces = _tetrahedron_solid_geometry()
        fill = create_earthworks_fill(
            empty_project_file, name="X", points=points, faces=faces
        )
        rels = empty_project_file.by_type("IfcRelAssociatesClassification")
        matching = [r for r in rels if fill in r.RelatedObjects]
        assert matching[0].RelatingClassification.Identification == "22-07 31 23"
        assert matching[0].RelatingClassification.Name == "Fill"

    def test_omniclass_override_for_backfill(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        """Per the docstring: backfill gets the more specific code."""
        from ifcopenshell.api.earthwork import create_earthworks_fill

        points, faces = _tetrahedron_solid_geometry()
        fill = create_earthworks_fill(
            empty_project_file,
            name="Trench backfill",
            points=points,
            faces=faces,
            predefined_type="BACKFILL",
            omniclass_code="22-07 31 23 16",
            omniclass_title="Backfill",
        )
        rels = empty_project_file.by_type("IfcRelAssociatesClassification")
        matching = [r for r in rels if fill in r.RelatedObjects]
        assert matching[0].RelatingClassification.Identification == "22-07 31 23 16"

    def test_predefined_type_options(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.earthwork import create_earthworks_fill

        for pt in ("BACKFILL", "COUNTERWEIGHT", "EMBANKMENT", "TRANSITIONSECTION"):
            points, faces = _tetrahedron_solid_geometry()
            fill = create_earthworks_fill(
                empty_project_file,
                name=f"Fill-{pt}",
                points=points,
                faces=faces,
                predefined_type=pt,
            )
            assert fill.PredefinedType == pt

    def test_warns_on_phase2_reserved_predefined_type(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        """SLOPEFILL/SUBGRADE are valid IFC values but warn the caller."""
        from ifcopenshell.api.earthwork import create_earthworks_fill

        points, faces = _tetrahedron_solid_geometry()
        with pytest.warns(UserWarning, match="reserved by ifcopenshell.api.grading"):
            fill = create_earthworks_fill(
                empty_project_file,
                name="Mistaken slope fill",
                points=points,
                faces=faces,
                predefined_type="SLOPEFILL",
            )
        assert fill.PredefinedType == "SLOPEFILL"  # still authored

    def test_invalid_predefined_type_raises(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.earthwork import create_earthworks_fill

        points, faces = _tetrahedron_solid_geometry()
        with pytest.raises(ValueError, match="must be a valid IfcEarthworksFillTypeEnum"):
            create_earthworks_fill(
                empty_project_file,
                name="X",
                points=points,
                faces=faces,
                predefined_type="invented",
            )

    def test_raises_when_no_site(self) -> None:
        from ifcopenshell.api.earthwork import create_earthworks_fill

        file = _empty_project_file_no_site()
        points, faces = _tetrahedron_solid_geometry()
        with pytest.raises(ValueError, match="no IfcSite"):
            create_earthworks_fill(file, name="X", points=points, faces=faces)

    def test_round_trip(self, empty_project_file: ifcopenshell.file, tmp_path) -> None:
        from ifcopenshell.api.earthwork import create_earthworks_fill

        points, faces = _cube_solid_geometry()
        create_earthworks_fill(
            empty_project_file,
            name="RTFill",
            points=points,
            faces=faces,
            predefined_type="EMBANKMENT",
            omniclass_code="22-07 31 23 13",
            omniclass_title="Embankment",
        )

        path = tmp_path / "rt_fill.ifc"
        empty_project_file.write(str(path))
        reopened = ifcopenshell.open(str(path))
        fills = [f for f in reopened.by_type("IfcEarthworksFill") if f.Name == "RTFill"]
        assert len(fills) == 1
        fill = fills[0]
        assert fill.PredefinedType == "EMBANKMENT"
        rep = fill.Representation.Representations[0]
        assert rep.RepresentationIdentifier == "Body"
        face_set = rep.Items[0]
        assert face_set.Closed is True
        common = _read_pset(fill, "Pset_EarthworksFillCommon")
        assert common.get("Status") == "NEW"
        rels = reopened.by_type("IfcRelAssociatesClassification")
        matching = [r for r in rels if fill in r.RelatedObjects]
        assert matching[0].RelatingClassification.Identification == "22-07 31 23 13"


def _make_terrain(
    file: ifcopenshell.file, name: str = "Existing Ground"
) -> ifcopenshell.entity_instance:
    return file.create_entity(
        "IfcGeographicElement",
        GlobalId=ifcopenshell.guid.new(),
        Name=name,
        PredefinedType="TERRAIN",
    )


class TestVoidTerrain:
    """Tests for ``ifcopenshell.api.earthwork.void_terrain``."""

    def test_happy_path(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.earthwork import (
            create_earthworks_cut,
            void_terrain,
        )

        terrain = _make_terrain(empty_project_file)
        points, faces = _cube_solid_geometry()
        cut = create_earthworks_cut(
            empty_project_file, name="Excavation", points=points, faces=faces
        )

        rel = void_terrain(empty_project_file, cut, terrain)

        assert rel.is_a("IfcRelVoidsElement")
        assert rel.RelatingBuildingElement.id() == terrain.id()
        assert rel.RelatedOpeningElement.id() == cut.id()

    def test_idempotent_for_same_pair(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        """Calling twice with the same cut/terrain returns the existing rel."""
        from ifcopenshell.api.earthwork import create_earthworks_cut, void_terrain

        terrain = _make_terrain(empty_project_file)
        points, faces = _cube_solid_geometry()
        cut = create_earthworks_cut(
            empty_project_file, name="X", points=points, faces=faces
        )
        first = void_terrain(empty_project_file, cut, terrain)
        second = void_terrain(empty_project_file, cut, terrain)
        assert first.id() == second.id()
        rels = empty_project_file.by_type("IfcRelVoidsElement")
        assert len(rels) == 1

    def test_retargeting_to_different_terrain_raises(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        """Cut->terrain is 1:1 by IFC schema; retargeting requires explicit removal first."""
        from ifcopenshell.api.earthwork import create_earthworks_cut, void_terrain

        terrain_a = _make_terrain(empty_project_file, name="EG-A")
        terrain_b = _make_terrain(empty_project_file, name="EG-B")
        points, faces = _cube_solid_geometry()
        cut = create_earthworks_cut(
            empty_project_file, name="X", points=points, faces=faces
        )
        void_terrain(empty_project_file, cut, terrain_a)
        with pytest.raises(ValueError, match="already voids"):
            void_terrain(empty_project_file, cut, terrain_b)

    def test_one_terrain_voided_by_many_cuts(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        """The terrain side has no cardinality limit — multiple cuts can void the same terrain."""
        from ifcopenshell.api.earthwork import create_earthworks_cut, void_terrain

        terrain = _make_terrain(empty_project_file)
        points, faces = _cube_solid_geometry()
        cut_a = create_earthworks_cut(
            empty_project_file, name="A", points=points, faces=faces
        )
        cut_b = create_earthworks_cut(
            empty_project_file, name="B", points=points, faces=faces
        )
        void_terrain(empty_project_file, cut_a, terrain)
        void_terrain(empty_project_file, cut_b, terrain)

        rels = empty_project_file.by_type("IfcRelVoidsElement")
        assert len(rels) == 2
        host_ids = {r.RelatingBuildingElement.id() for r in rels}
        assert host_ids == {terrain.id()}

    def test_wrong_cut_type_raises(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.earthwork import void_terrain

        terrain = _make_terrain(empty_project_file)
        not_a_cut = _make_fill(empty_project_file)  # IfcEarthworksFill, not Cut
        with pytest.raises(ValueError, match="must be an IfcFeatureElementSubtraction"):
            void_terrain(empty_project_file, not_a_cut, terrain)

    def test_wrong_terrain_type_raises(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.earthwork import create_earthworks_cut, void_terrain

        points, faces = _cube_solid_geometry()
        cut = create_earthworks_cut(
            empty_project_file, name="X", points=points, faces=faces
        )
        not_a_terrain = empty_project_file.create_entity(
            "IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0)
        )
        with pytest.raises(ValueError, match="must be an IfcElement"):
            void_terrain(empty_project_file, cut, not_a_terrain)

    def test_round_trip(self, empty_project_file: ifcopenshell.file, tmp_path) -> None:
        from ifcopenshell.api.earthwork import create_earthworks_cut, void_terrain

        terrain = _make_terrain(empty_project_file, name="RTGround")
        points, faces = _cube_solid_geometry()
        cut = create_earthworks_cut(
            empty_project_file, name="RTCut", points=points, faces=faces
        )
        void_terrain(empty_project_file, cut, terrain)

        path = tmp_path / "rt_void.ifc"
        empty_project_file.write(str(path))
        reopened = ifcopenshell.open(str(path))
        rels = reopened.by_type("IfcRelVoidsElement")
        assert len(rels) == 1
        assert rels[0].RelatingBuildingElement.Name == "RTGround"
        assert rels[0].RelatedOpeningElement.Name == "RTCut"


def _read_qto(
    product: ifcopenshell.entity_instance, qto_name: str
) -> dict[str, float]:
    """Translate the named IfcElementQuantity's children into a name→value dict."""
    for rel in product.IsDefinedBy or []:
        if not rel.is_a("IfcRelDefinesByProperties"):
            continue
        qto = rel.RelatingPropertyDefinition
        if not (qto.is_a("IfcElementQuantity") and qto.Name == qto_name):
            continue
        out: dict[str, float] = {}
        for q in qto.Quantities or []:
            if q.is_a("IfcQuantityLength"):
                out[q.Name] = q.LengthValue
            elif q.is_a("IfcQuantityVolume"):
                out[q.Name] = q.VolumeValue
            elif q.is_a("IfcQuantityWeight"):
                out[q.Name] = q.WeightValue
        return out
    return {}


class TestWriteCutQuantities:
    """Tests for ``ifcopenshell.api.earthwork.write_cut_quantities``."""

    def _make_cube_cut(self, file: ifcopenshell.file) -> ifcopenshell.entity_instance:
        from ifcopenshell.api.earthwork import create_earthworks_cut

        points, faces = _cube_solid_geometry()
        return create_earthworks_cut(file, name="X", points=points, faces=faces)

    def test_happy_path_writes_all_six_quantities(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.earthwork import write_cut_quantities

        cut = self._make_cube_cut(empty_project_file)
        qto = write_cut_quantities(
            empty_project_file,
            cut,
            length=10.0,
            width=5.0,
            depth=2.0,
            undisturbed_volume=100.0,
            loose_volume=125.0,
            weight=180000.0,
        )

        assert qto.is_a("IfcElementQuantity")
        assert qto.Name == "Qto_EarthworksCutBaseQuantities"
        assert len(qto.Quantities) == 6
        values = _read_qto(cut, "Qto_EarthworksCutBaseQuantities")
        assert values == {
            "Length": 10.0,
            "Width": 5.0,
            "Depth": 2.0,
            "UndisturbedVolume": 100.0,
            "LooseVolume": 125.0,
            "Weight": 180000.0,
        }

    def test_partial_write_omits_none_quantities(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        """None-valued args are omitted from the Qto entirely."""
        from ifcopenshell.api.earthwork import write_cut_quantities

        cut = self._make_cube_cut(empty_project_file)
        write_cut_quantities(
            empty_project_file, cut, undisturbed_volume=42.0
        )
        values = _read_qto(cut, "Qto_EarthworksCutBaseQuantities")
        assert values == {"UndisturbedVolume": 42.0}

    def test_idempotent_in_place_update(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        """Per Phase 3 idempotency contract: second call updates same IfcElementQuantity."""
        from ifcopenshell.api.earthwork import write_cut_quantities

        cut = self._make_cube_cut(empty_project_file)
        first = write_cut_quantities(
            empty_project_file, cut, undisturbed_volume=100.0, loose_volume=125.0
        )
        second = write_cut_quantities(
            empty_project_file,
            cut,
            length=10.0,
            undisturbed_volume=120.0,
            loose_volume=150.0,
            weight=200000.0,
        )

        assert first.id() == second.id()
        # Final values reflect the LAST call's args.
        values = _read_qto(cut, "Qto_EarthworksCutBaseQuantities")
        assert values == {
            "Length": 10.0,
            "UndisturbedVolume": 120.0,
            "LooseVolume": 150.0,
            "Weight": 200000.0,
        }
        # Exactly one Qto on the cut.
        qtos = [
            r.RelatingPropertyDefinition
            for r in cut.IsDefinedBy or []
            if r.is_a("IfcRelDefinesByProperties")
            and r.RelatingPropertyDefinition.Name == "Qto_EarthworksCutBaseQuantities"
        ]
        assert len(qtos) == 1

    def test_idempotent_burst_no_duplicates(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        """Five calls in a row leave one Qto, with the last-supplied values."""
        from ifcopenshell.api.earthwork import write_cut_quantities

        cut = self._make_cube_cut(empty_project_file)
        for i in range(5):
            write_cut_quantities(
                empty_project_file,
                cut,
                undisturbed_volume=100.0 + i,
                loose_volume=125.0 + i,
            )
        qtos = [
            r.RelatingPropertyDefinition
            for r in cut.IsDefinedBy or []
            if r.is_a("IfcRelDefinesByProperties")
            and r.RelatingPropertyDefinition.Name == "Qto_EarthworksCutBaseQuantities"
        ]
        assert len(qtos) == 1
        values = _read_qto(cut, "Qto_EarthworksCutBaseQuantities")
        assert values == {"UndisturbedVolume": 104.0, "LooseVolume": 129.0}

    def test_no_quantities_supplied_raises(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.earthwork import write_cut_quantities

        cut = self._make_cube_cut(empty_project_file)
        with pytest.raises(ValueError, match="at least one quantity"):
            write_cut_quantities(empty_project_file, cut)

    def test_wrong_target_type_raises(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.earthwork import write_cut_quantities

        not_a_cut = _make_fill(empty_project_file)
        with pytest.raises(ValueError, match="must be an IfcEarthworksCut"):
            write_cut_quantities(empty_project_file, not_a_cut, undisturbed_volume=10.0)

    def test_round_trip(self, empty_project_file: ifcopenshell.file, tmp_path) -> None:
        from ifcopenshell.api.earthwork import write_cut_quantities

        cut = self._make_cube_cut(empty_project_file)
        cut.Name = "RTQto"
        write_cut_quantities(
            empty_project_file,
            cut,
            length=15.0,
            width=8.0,
            depth=3.0,
            undisturbed_volume=360.0,
            loose_volume=450.0,
        )

        path = tmp_path / "rt_cut_qto.ifc"
        empty_project_file.write(str(path))
        reopened = ifcopenshell.open(str(path))
        cuts = [c for c in reopened.by_type("IfcEarthworksCut") if c.Name == "RTQto"]
        assert len(cuts) == 1
        values = _read_qto(cuts[0], "Qto_EarthworksCutBaseQuantities")
        assert values == {
            "Length": 15.0,
            "Width": 8.0,
            "Depth": 3.0,
            "UndisturbedVolume": 360.0,
            "LooseVolume": 450.0,
        }

    def test_idempotent_persists_through_reopen(
        self, empty_project_file: ifcopenshell.file, tmp_path
    ) -> None:
        """Reopening + calling again is also idempotent (file-state, not just memory-state)."""
        from ifcopenshell.api.earthwork import write_cut_quantities

        cut = self._make_cube_cut(empty_project_file)
        cut.Name = "RTPersist"
        write_cut_quantities(empty_project_file, cut, undisturbed_volume=50.0)

        path = tmp_path / "persist.ifc"
        empty_project_file.write(str(path))
        reopened = ifcopenshell.open(str(path))
        reopened_cut = [c for c in reopened.by_type("IfcEarthworksCut") if c.Name == "RTPersist"][0]

        write_cut_quantities(reopened, reopened_cut, undisturbed_volume=75.0, loose_volume=90.0)

        qtos = [
            r.RelatingPropertyDefinition
            for r in reopened_cut.IsDefinedBy or []
            if r.is_a("IfcRelDefinesByProperties")
            and r.RelatingPropertyDefinition.Name == "Qto_EarthworksCutBaseQuantities"
        ]
        assert len(qtos) == 1
        values = _read_qto(reopened_cut, "Qto_EarthworksCutBaseQuantities")
        assert values == {"UndisturbedVolume": 75.0, "LooseVolume": 90.0}


class TestWriteFillQuantities:
    """Tests for ``ifcopenshell.api.earthwork.write_fill_quantities``."""

    def _make_cube_fill(self, file: ifcopenshell.file) -> ifcopenshell.entity_instance:
        from ifcopenshell.api.earthwork import create_earthworks_fill

        points, faces = _cube_solid_geometry()
        return create_earthworks_fill(file, name="X", points=points, faces=faces)

    def test_happy_path_writes_all_five_quantities(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.earthwork import write_fill_quantities

        fill = self._make_cube_fill(empty_project_file)
        qto = write_fill_quantities(
            empty_project_file,
            fill,
            length=10.0,
            width=5.0,
            depth=2.0,
            compacted_volume=100.0,
            loose_volume=120.0,
        )

        assert qto.is_a("IfcElementQuantity")
        assert qto.Name == "Qto_EarthworksFillBaseQuantities"
        assert len(qto.Quantities) == 5
        values = _read_qto(fill, "Qto_EarthworksFillBaseQuantities")
        assert values == {
            "Length": 10.0,
            "Width": 5.0,
            "Depth": 2.0,
            "CompactedVolume": 100.0,
            "LooseVolume": 120.0,
        }

    def test_partial_write_omits_none_quantities(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.earthwork import write_fill_quantities

        fill = self._make_cube_fill(empty_project_file)
        write_fill_quantities(empty_project_file, fill, compacted_volume=42.0)
        values = _read_qto(fill, "Qto_EarthworksFillBaseQuantities")
        assert values == {"CompactedVolume": 42.0}

    def test_idempotent_in_place_update(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.earthwork import write_fill_quantities

        fill = self._make_cube_fill(empty_project_file)
        first = write_fill_quantities(empty_project_file, fill, compacted_volume=100.0)
        second = write_fill_quantities(
            empty_project_file,
            fill,
            length=10.0,
            compacted_volume=120.0,
            loose_volume=145.0,
        )

        assert first.id() == second.id()
        values = _read_qto(fill, "Qto_EarthworksFillBaseQuantities")
        assert values == {
            "Length": 10.0,
            "CompactedVolume": 120.0,
            "LooseVolume": 145.0,
        }

    def test_works_on_phase2_surface_fill_too(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        """A SLOPEFILL or SUBGRADE Phase-2 fill can also receive a Qto when its volume is computed."""
        from ifcopenshell.api.earthwork import write_fill_quantities

        # Author a SLOPEFILL directly (without going through api.grading) — same effect.
        slope_fill = empty_project_file.create_entity(
            "IfcEarthworksFill",
            GlobalId=ifcopenshell.guid.new(),
            Name="Slope",
            PredefinedType="SLOPEFILL",
        )
        write_fill_quantities(empty_project_file, slope_fill, compacted_volume=15.0)
        values = _read_qto(slope_fill, "Qto_EarthworksFillBaseQuantities")
        assert values == {"CompactedVolume": 15.0}

    def test_no_quantities_supplied_raises(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.earthwork import write_fill_quantities

        fill = self._make_cube_fill(empty_project_file)
        with pytest.raises(ValueError, match="at least one quantity"):
            write_fill_quantities(empty_project_file, fill)

    def test_wrong_target_type_raises(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.earthwork import write_fill_quantities

        not_a_fill = _make_cut(empty_project_file)
        with pytest.raises(ValueError, match="must be an IfcEarthworksFill"):
            write_fill_quantities(empty_project_file, not_a_fill, compacted_volume=10.0)

    def test_round_trip(self, empty_project_file: ifcopenshell.file, tmp_path) -> None:
        from ifcopenshell.api.earthwork import write_fill_quantities

        fill = self._make_cube_fill(empty_project_file)
        fill.Name = "RTFillQto"
        write_fill_quantities(
            empty_project_file,
            fill,
            length=15.0,
            width=8.0,
            depth=3.0,
            compacted_volume=360.0,
            loose_volume=420.0,
        )

        path = tmp_path / "rt_fill_qto.ifc"
        empty_project_file.write(str(path))
        reopened = ifcopenshell.open(str(path))
        fills = [f for f in reopened.by_type("IfcEarthworksFill") if f.Name == "RTFillQto"]
        assert len(fills) == 1
        values = _read_qto(fills[0], "Qto_EarthworksFillBaseQuantities")
        assert values == {
            "Length": 15.0,
            "Width": 8.0,
            "Depth": 3.0,
            "CompactedVolume": 360.0,
            "LooseVolume": 420.0,
        }


class TestApplyShrinkSwellPset:
    """Tests for ``ifcopenshell.api.earthwork.apply_shrink_swell_pset``."""

    def test_happy_path_on_fill(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.earthwork import apply_shrink_swell_pset

        fill = _make_fill(empty_project_file)
        pset = apply_shrink_swell_pset(
            empty_project_file, fill, shrink_factor=0.92, swell_factor=1.18
        )

        assert pset.is_a("IfcPropertySet")
        assert pset.Name == "Pset_SaikeiGradingShrinkSwell"
        properties = _read_pset(fill, "Pset_SaikeiGradingShrinkSwell")
        assert properties == {"ShrinkFactor": 0.92, "SwellFactor": 1.18}

    def test_happy_path_on_cut(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.earthwork import apply_shrink_swell_pset

        cut = _make_cut(empty_project_file)
        apply_shrink_swell_pset(
            empty_project_file, cut, shrink_factor=0.85, swell_factor=1.25
        )
        properties = _read_pset(cut, "Pset_SaikeiGradingShrinkSwell")
        assert properties == {"ShrinkFactor": 0.85, "SwellFactor": 1.25}

    def test_default_factors(self, empty_project_file: ifcopenshell.file) -> None:
        """Default 1.0/1.0 — caller hasn't supplied geotechnical data yet."""
        from ifcopenshell.api.earthwork import apply_shrink_swell_pset

        fill = _make_fill(empty_project_file)
        apply_shrink_swell_pset(empty_project_file, fill)
        properties = _read_pset(fill, "Pset_SaikeiGradingShrinkSwell")
        assert properties == {"ShrinkFactor": 1.0, "SwellFactor": 1.0}

    def test_idempotent_in_place_update(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.earthwork import apply_shrink_swell_pset

        fill = _make_fill(empty_project_file)
        first = apply_shrink_swell_pset(
            empty_project_file, fill, shrink_factor=0.92, swell_factor=1.18
        )
        second = apply_shrink_swell_pset(
            empty_project_file, fill, shrink_factor=0.88, swell_factor=1.22
        )

        assert first.id() == second.id()
        properties = _read_pset(fill, "Pset_SaikeiGradingShrinkSwell")
        assert properties == {"ShrinkFactor": 0.88, "SwellFactor": 1.22}

        rels = [
            r
            for r in fill.IsDefinedBy or []
            if r.is_a("IfcRelDefinesByProperties")
            and r.RelatingPropertyDefinition.Name == "Pset_SaikeiGradingShrinkSwell"
        ]
        assert len(rels) == 1

    def test_wrong_target_type_raises(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.earthwork import apply_shrink_swell_pset

        not_an_earthwork = empty_project_file.create_entity(
            "IfcGeographicElement",
            GlobalId=ifcopenshell.guid.new(),
            Name="Terrain",
            PredefinedType="TERRAIN",
        )
        with pytest.raises(ValueError, match="must be IfcEarthworksFill or IfcEarthworksCut"):
            apply_shrink_swell_pset(empty_project_file, not_an_earthwork)

    def test_round_trip(self, empty_project_file: ifcopenshell.file, tmp_path) -> None:
        from ifcopenshell.api.earthwork import apply_shrink_swell_pset

        fill = _make_fill(empty_project_file, name="RTSwell")
        apply_shrink_swell_pset(
            empty_project_file, fill, shrink_factor=0.93, swell_factor=1.20
        )

        path = tmp_path / "rt_shrink_swell.ifc"
        empty_project_file.write(str(path))
        reopened = ifcopenshell.open(str(path))
        fills = [f for f in reopened.by_type("IfcEarthworksFill") if f.Name == "RTSwell"]
        assert len(fills) == 1
        properties = _read_pset(fills[0], "Pset_SaikeiGradingShrinkSwell")
        assert properties == {"ShrinkFactor": 0.93, "SwellFactor": 1.20}

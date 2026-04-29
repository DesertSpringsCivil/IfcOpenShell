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

"""Tests for ``ifcopenshell.api.grading``.

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


def _empty_project_file_no_site() -> ifcopenshell.file:
    """Like _empty_project_file but skips IfcSite creation, for site-resolution tests."""
    file = ifcopenshell.file(schema="IFC4X3_ADD2")
    file.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), Name="No Site")
    length_unit = ifcopenshell.api.unit.add_si_unit(file, unit_type="LENGTHUNIT")
    ifcopenshell.api.unit.assign_unit(file, units=[length_unit])
    return file


@pytest.fixture
def empty_project_file() -> ifcopenshell.file:
    return _empty_project_file()


def _make_fill(file: ifcopenshell.file, name: str = "Test Fill") -> ifcopenshell.entity_instance:
    return file.create_entity(
        "IfcEarthworksFill",
        GlobalId=ifcopenshell.guid.new(),
        Name=name,
        PredefinedType="SLOPEFILL",
    )


def test_package_importable() -> None:
    """Smoke test: the package imports and exposes the expected docstring."""
    import ifcopenshell.api.grading

    assert ifcopenshell.api.grading.__doc__ is not None
    assert "grading" in ifcopenshell.api.grading.__doc__.lower()


class TestSharedHelpers:
    """Tests for the internal site-resolution and OmniClass helpers."""

    def test_resolve_site_returns_explicit_site_unchanged(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.grading._shared import _resolve_site

        explicit = empty_project_file.create_entity(
            "IfcSite", GlobalId=ifcopenshell.guid.new(), Name="Explicit"
        )
        assert _resolve_site(empty_project_file, explicit).id() == explicit.id()

    def test_resolve_site_auto_picks_first_when_none(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.grading._shared import _resolve_site

        resolved = _resolve_site(empty_project_file, None)
        assert resolved.is_a("IfcSite")
        assert resolved.id() == empty_project_file.by_type("IfcSite")[0].id()

    def test_resolve_site_raises_when_no_site(self) -> None:
        from ifcopenshell.api.grading._shared import _resolve_site

        file = _empty_project_file_no_site()
        with pytest.raises(ValueError, match="no IfcSite"):
            _resolve_site(file, None)

    def test_omniclass_classification_creates_full_chain(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.grading._shared import apply_omniclass_classification

        fill = _make_fill(empty_project_file)
        rel = apply_omniclass_classification(
            empty_project_file, fill, "22-07 31 23", "Fill"
        )

        assert rel.is_a("IfcRelAssociatesClassification")
        assert fill in rel.RelatedObjects
        reference = rel.RelatingClassification
        assert reference.is_a("IfcClassificationReference")
        assert reference.Identification == "22-07 31 23"
        assert reference.Name == "Fill"
        classification = reference.ReferencedSource
        assert classification.is_a("IfcClassification")
        assert classification.Name == "OmniClass Table 22"

    def test_omniclass_reuses_classification_across_codes(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        """Two different codes share one IfcClassification, but get distinct references."""
        from ifcopenshell.api.grading._shared import apply_omniclass_classification

        fill_a = _make_fill(empty_project_file, name="A")
        fill_b = _make_fill(empty_project_file, name="B")
        apply_omniclass_classification(empty_project_file, fill_a, "22-07 31 23", "Fill")
        apply_omniclass_classification(empty_project_file, fill_b, "22-07 31 16", "Excavation and Fill")

        classifications = empty_project_file.by_type("IfcClassification")
        references = empty_project_file.by_type("IfcClassificationReference")
        assert len(classifications) == 1
        assert len(references) == 2

    def test_omniclass_appends_to_existing_rel_for_same_code(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        """A second product with the same code joins the existing rel — no duplicate rel."""
        from ifcopenshell.api.grading._shared import apply_omniclass_classification

        fill_a = _make_fill(empty_project_file, name="A")
        fill_b = _make_fill(empty_project_file, name="B")
        rel_a = apply_omniclass_classification(empty_project_file, fill_a, "22-07 31 23", "Fill")
        rel_b = apply_omniclass_classification(empty_project_file, fill_b, "22-07 31 23", "Fill")

        assert rel_a.id() == rel_b.id()
        assert {fill_a.id(), fill_b.id()} == {p.id() for p in rel_a.RelatedObjects}
        rels = empty_project_file.by_type("IfcRelAssociatesClassification")
        assert len(rels) == 1

    def test_omniclass_idempotent_for_same_product_and_code(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        """Calling twice on the same product/code does not duplicate it in RelatedObjects."""
        from ifcopenshell.api.grading._shared import apply_omniclass_classification

        fill = _make_fill(empty_project_file)
        apply_omniclass_classification(empty_project_file, fill, "22-07 31 23", "Fill")
        apply_omniclass_classification(empty_project_file, fill, "22-07 31 23", "Fill")

        rels = empty_project_file.by_type("IfcRelAssociatesClassification")
        assert len(rels) == 1
        assert [p.id() for p in rels[0].RelatedObjects] == [fill.id()]

    def test_omniclass_round_trip(
        self, empty_project_file: ifcopenshell.file, tmp_path
    ) -> None:
        from ifcopenshell.api.grading._shared import apply_omniclass_classification

        fill = _make_fill(empty_project_file, name="RTOmni")
        apply_omniclass_classification(empty_project_file, fill, "22-07 31 23", "Fill")

        path = tmp_path / "rt_omni.ifc"
        empty_project_file.write(str(path))
        reopened = ifcopenshell.open(str(path))
        rels = reopened.by_type("IfcRelAssociatesClassification")
        assert len(rels) == 1
        reference = rels[0].RelatingClassification
        assert reference.Identification == "22-07 31 23"
        assert reference.ReferencedSource.Name == "OmniClass Table 22"


def _make_group(file: ifcopenshell.file, name: str = "Test Group") -> ifcopenshell.entity_instance:
    return file.create_entity(
        "IfcGroup",
        GlobalId=ifcopenshell.guid.new(),
        Name=name,
        ObjectType="GradingGroup",
    )


class TestAddMemberToGroup:
    """Tests for ``ifcopenshell.api.grading.add_member_to_group``."""

    def test_creates_new_rel_when_group_has_no_members(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.grading import add_member_to_group

        group = _make_group(empty_project_file)
        product = _make_fill(empty_project_file)
        rel = add_member_to_group(empty_project_file, group, product)

        assert rel.is_a("IfcRelAssignsToGroup")
        assert rel.RelatingGroup.id() == group.id()
        assert [p.id() for p in rel.RelatedObjects] == [product.id()]

    def test_appends_to_existing_rel(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.grading import add_member_to_group

        group = _make_group(empty_project_file)
        first = _make_fill(empty_project_file, name="First")
        second = _make_fill(empty_project_file, name="Second")

        rel_a = add_member_to_group(empty_project_file, group, first)
        rel_b = add_member_to_group(empty_project_file, group, second)

        assert rel_a.id() == rel_b.id()
        assert {p.id() for p in rel_a.RelatedObjects} == {first.id(), second.id()}
        rels = empty_project_file.by_type("IfcRelAssignsToGroup")
        assert len(rels) == 1

    def test_dedupes_when_product_already_member(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.grading import add_member_to_group

        group = _make_group(empty_project_file)
        product = _make_fill(empty_project_file)

        add_member_to_group(empty_project_file, group, product)
        add_member_to_group(empty_project_file, group, product)

        rels = empty_project_file.by_type("IfcRelAssignsToGroup")
        assert len(rels) == 1
        assert [p.id() for p in rels[0].RelatedObjects] == [product.id()]

    def test_accepts_multiple_products_in_one_call(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.grading import add_member_to_group

        group = _make_group(empty_project_file)
        a = _make_fill(empty_project_file, name="A")
        b = _make_fill(empty_project_file, name="B")
        c = _make_fill(empty_project_file, name="C")

        rel = add_member_to_group(empty_project_file, group, a, b, c)
        assert {p.id() for p in rel.RelatedObjects} == {a.id(), b.id(), c.id()}

    def test_accepts_subgroup_as_member(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        """The schema allows IfcGroup as a member of another IfcGroup."""
        from ifcopenshell.api.grading import add_member_to_group

        parent = _make_group(empty_project_file, name="Parent")
        child = _make_group(empty_project_file, name="Child")
        rel = add_member_to_group(empty_project_file, parent, child)
        assert child.id() in {p.id() for p in rel.RelatedObjects}

    def test_raises_when_group_arg_is_not_a_group(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.grading import add_member_to_group

        not_a_group = _make_fill(empty_project_file)
        product = _make_fill(empty_project_file, name="P")
        with pytest.raises(ValueError, match="must be an IfcGroup"):
            add_member_to_group(empty_project_file, not_a_group, product)

    def test_raises_when_no_products_supplied(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.grading import add_member_to_group

        group = _make_group(empty_project_file)
        with pytest.raises(ValueError, match="at least one product"):
            add_member_to_group(empty_project_file, group)

    def test_raises_when_product_is_not_object_definition(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        """An IfcCartesianPoint isn't an IfcObjectDefinition; rejected."""
        from ifcopenshell.api.grading import add_member_to_group

        group = _make_group(empty_project_file)
        not_a_product = empty_project_file.create_entity(
            "IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0)
        )
        with pytest.raises(ValueError, match="not an IfcObjectDefinition"):
            add_member_to_group(empty_project_file, group, not_a_product)

    def test_round_trip(self, empty_project_file: ifcopenshell.file, tmp_path) -> None:
        from ifcopenshell.api.grading import add_member_to_group

        group = _make_group(empty_project_file, name="RTGroup")
        a = _make_fill(empty_project_file, name="RT_A")
        b = _make_fill(empty_project_file, name="RT_B")
        add_member_to_group(empty_project_file, group, a, b)

        path = tmp_path / "rt_group.ifc"
        empty_project_file.write(str(path))
        reopened = ifcopenshell.open(str(path))
        groups = [g for g in reopened.by_type("IfcGroup") if g.Name == "RTGroup"]
        assert len(groups) == 1
        member_names = {p.Name for p in groups[0].IsGroupedBy[0].RelatedObjects}
        assert member_names == {"RT_A", "RT_B"}


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


class TestCreateFeatureLine:
    """Tests for ``ifcopenshell.api.grading.create_feature_line``."""

    def test_happy_path(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.grading import create_feature_line

        vertices = [(0.0, 0.0, 100.0), (10.0, 0.0, 100.5), (10.0, 10.0, 101.0), (0.0, 10.0, 100.5)]
        feature_line = create_feature_line(
            empty_project_file,
            name="Pad perimeter",
            vertices=vertices,
            closed=True,
            source="manual",
            elevation_source="drape",
        )

        assert feature_line.is_a("IfcAlignment")
        assert feature_line.Name == "Pad perimeter"

        rep = feature_line.Representation.Representations[0]
        assert rep.RepresentationIdentifier == "Axis"
        assert rep.RepresentationType == "Curve3D"
        curve = rep.Items[0]
        assert curve.is_a("IfcIndexedPolyCurve")
        # closed=True means first vertex appended to close the loop
        assert len(curve.Points.CoordList) == 5
        assert tuple(curve.Points.CoordList[0]) == (0.0, 0.0, 100.0)
        assert tuple(curve.Points.CoordList[-1]) == (0.0, 0.0, 100.0)

        rel = (feature_line.ContainedInStructure or [None])[0]
        assert rel is not None and rel.RelatingStructure.is_a("IfcSite")

        properties = _read_pset(feature_line, "Pset_SaikeiFeatureLineCommon")
        assert properties["IsClosed"] is True
        assert properties["Source"] == "manual"
        assert properties["ElevationSource"] == "drape"
        assert "GradingGroupGuid" not in properties

    def test_open_polyline_no_repeated_endpoint(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.grading import create_feature_line

        vertices = [(0.0, 0.0, 100.0), (50.0, 0.0, 99.5), (100.0, 0.0, 99.0)]
        feature_line = create_feature_line(
            empty_project_file, name="Curb line", vertices=vertices, closed=False
        )

        curve = feature_line.Representation.Representations[0].Items[0]
        assert len(curve.Points.CoordList) == 3
        properties = _read_pset(feature_line, "Pset_SaikeiFeatureLineCommon")
        assert properties["IsClosed"] is False

    def test_grading_group_guid_optional_property(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.grading import create_feature_line

        feature_line = create_feature_line(
            empty_project_file,
            name="Linked",
            vertices=[(0.0, 0.0, 0.0), (1.0, 1.0, 1.0)],
            grading_group_guid="3VxJzKQwT9XwJZ8RbZkH7E",
        )
        properties = _read_pset(feature_line, "Pset_SaikeiFeatureLineCommon")
        assert properties["GradingGroupGuid"] == "3VxJzKQwT9XwJZ8RbZkH7E"

    def test_too_few_vertices_raises(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.grading import create_feature_line

        with pytest.raises(ValueError, match="at least two points"):
            create_feature_line(
                empty_project_file, name="Solo", vertices=[(0.0, 0.0, 0.0)]
            )

    def test_invalid_source_raises(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.grading import create_feature_line

        with pytest.raises(ValueError, match="source must be one of"):
            create_feature_line(
                empty_project_file,
                name="Bad",
                vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
                source="invented",
            )

    def test_raises_when_no_site(self) -> None:
        from ifcopenshell.api.grading import create_feature_line

        file = _empty_project_file_no_site()
        with pytest.raises(ValueError, match="no IfcSite"):
            create_feature_line(
                file, name="A", vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
            )

    def test_explicit_site_overrides_auto(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.grading import create_feature_line

        second_site = empty_project_file.create_entity(
            "IfcSite", GlobalId=ifcopenshell.guid.new(), Name="Second"
        )
        feature_line = create_feature_line(
            empty_project_file,
            name="On second",
            vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
            site=second_site,
        )
        rel = (feature_line.ContainedInStructure or [None])[0]
        assert rel.RelatingStructure.id() == second_site.id()

    def test_round_trip(self, empty_project_file: ifcopenshell.file, tmp_path) -> None:
        from ifcopenshell.api.grading import create_feature_line

        vertices = [(0.0, 0.0, 100.0), (10.0, 0.0, 100.5), (10.0, 10.0, 101.0), (0.0, 10.0, 100.5)]
        create_feature_line(
            empty_project_file,
            name="RTPad",
            vertices=vertices,
            closed=True,
            source="csv_import",
            elevation_source="csv",
            grading_group_guid="abc",
        )

        path = tmp_path / "rt_feature.ifc"
        empty_project_file.write(str(path))
        reopened = ifcopenshell.open(str(path))
        feature_lines = [a for a in reopened.by_type("IfcAlignment") if a.Name == "RTPad"]
        assert len(feature_lines) == 1
        feature_line = feature_lines[0]
        curve = feature_line.Representation.Representations[0].Items[0]
        assert len(curve.Points.CoordList) == 5  # 4 + 1 repeated for closure
        properties = _read_pset(feature_line, "Pset_SaikeiFeatureLineCommon")
        assert properties["IsClosed"] is True
        assert properties["Source"] == "csv_import"
        assert properties["GradingGroupGuid"] == "abc"

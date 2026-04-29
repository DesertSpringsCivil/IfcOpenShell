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


class TestCreateGradingCriteriaTemplate:
    """Tests for ``ifcopenshell.api.grading.create_grading_criteria_template``."""

    def test_creates_six_property_templates(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.grading import create_grading_criteria_template

        template = create_grading_criteria_template(empty_project_file)

        assert template.is_a("IfcPropertySetTemplate")
        assert template.Name == "Pset_SaikeiGradingCriteria"
        assert template.TemplateType == "PSET_OCCURRENCEDRIVEN"
        assert template.ApplicableEntity == "IfcGroup"
        property_templates = list(template.HasPropertyTemplates)
        assert len(property_templates) == 6
        names_to_specs = {t.Name: t for t in property_templates}
        assert set(names_to_specs) == {
            "TargetKind",
            "TargetReference",
            "CutSlope",
            "FillSlope",
            "MaxDistance",
            "RetainingWallAtLimit",
        }

    def test_target_kind_is_enumerated_with_four_values(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.grading import create_grading_criteria_template

        template = create_grading_criteria_template(empty_project_file)
        target_kind = next(t for t in template.HasPropertyTemplates if t.Name == "TargetKind")
        assert target_kind.TemplateType == "P_ENUMERATEDVALUE"
        assert target_kind.PrimaryMeasureType is None
        enumeration = target_kind.Enumerators
        assert enumeration.is_a("IfcPropertyEnumeration")
        assert enumeration.Name == "SaikeiGradingTargetKind"
        values = [v.wrappedValue for v in enumeration.EnumerationValues]
        assert values == ["surface", "elevation", "relative_elevation", "distance"]

    def test_measure_types_are_canonical(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        """Each non-enum property template has the right PrimaryMeasureType."""
        from ifcopenshell.api.grading import create_grading_criteria_template

        template = create_grading_criteria_template(empty_project_file)
        names_to_specs = {t.Name: t for t in template.HasPropertyTemplates}

        assert names_to_specs["TargetReference"].PrimaryMeasureType == "IfcLabel"
        assert names_to_specs["CutSlope"].PrimaryMeasureType == "IfcPositiveRatioMeasure"
        assert names_to_specs["FillSlope"].PrimaryMeasureType == "IfcPositiveRatioMeasure"
        assert names_to_specs["MaxDistance"].PrimaryMeasureType == "IfcPositiveLengthMeasure"
        assert names_to_specs["RetainingWallAtLimit"].PrimaryMeasureType == "IfcBoolean"

    def test_idempotent(self, empty_project_file: ifcopenshell.file) -> None:
        """A second call returns the same template, no duplicates."""
        from ifcopenshell.api.grading import create_grading_criteria_template

        first = create_grading_criteria_template(empty_project_file)
        second = create_grading_criteria_template(empty_project_file)
        assert first.id() == second.id()
        templates = empty_project_file.by_type("IfcPropertySetTemplate")
        assert len(templates) == 1
        enumerations = empty_project_file.by_type("IfcPropertyEnumeration")
        assert len(enumerations) == 1

    def test_round_trip(self, empty_project_file: ifcopenshell.file, tmp_path) -> None:
        from ifcopenshell.api.grading import create_grading_criteria_template

        create_grading_criteria_template(empty_project_file)

        path = tmp_path / "rt_template.ifc"
        empty_project_file.write(str(path))
        reopened = ifcopenshell.open(str(path))
        templates = [
            t for t in reopened.by_type("IfcPropertySetTemplate")
            if t.Name == "Pset_SaikeiGradingCriteria"
        ]
        assert len(templates) == 1
        template = templates[0]
        assert template.ApplicableEntity == "IfcGroup"
        assert len(template.HasPropertyTemplates) == 6
        target_kind = next(t for t in template.HasPropertyTemplates if t.Name == "TargetKind")
        values = [v.wrappedValue for v in target_kind.Enumerators.EnumerationValues]
        assert values == ["surface", "elevation", "relative_elevation", "distance"]


def _make_terrain(file: ifcopenshell.file, name: str = "Existing") -> ifcopenshell.entity_instance:
    """Build an IfcGeographicElement[TERRAIN] for use as target_surface in tests."""
    return file.create_entity(
        "IfcGeographicElement",
        GlobalId=ifcopenshell.guid.new(),
        Name=name,
        PredefinedType="TERRAIN",
    )


class TestCreateGradingGroup:
    """Tests for ``ifcopenshell.api.grading.create_grading_group``."""

    def test_happy_path_returns_named_tuple(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.grading import (
            GradingGroupAuthoring,
            create_grading_group,
        )

        result = create_grading_group(empty_project_file, name="Pad A")

        assert isinstance(result, GradingGroupAuthoring)
        assert result.group.is_a("IfcGroup")
        assert result.group.ObjectType == "GradingGroup"
        assert result.group.Name == "Pad A"
        assert result.composite_fill.is_a("IfcEarthworksFill")
        assert result.composite_fill.PredefinedType == "SUBGRADE"
        assert result.composite_fill.Name == "Pad A"

    def test_group_is_not_in_spatial_tree(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        """IfcGroup is not an IfcProduct; verify it has no spatial container relation."""
        from ifcopenshell.api.grading import create_grading_group

        result = create_grading_group(empty_project_file, name="X")

        # IfcGroup doesn't even have a ContainedInStructure attribute. Verify
        # by checking no IfcRelContainedInSpatialStructure references it.
        for rel in empty_project_file.by_type("IfcRelContainedInSpatialStructure"):
            assert result.group not in rel.RelatedElements

    def test_composite_fill_is_contained_in_site(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.grading import create_grading_group

        result = create_grading_group(empty_project_file, name="X")
        rel = (result.composite_fill.ContainedInStructure or [None])[0]
        assert rel is not None
        assert rel.RelatingStructure.id() == _site(empty_project_file).id()

    def test_composite_fill_added_to_group_as_member(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        """The composite fill is the group's first IfcRelAssignsToGroup member."""
        from ifcopenshell.api.grading import create_grading_group

        result = create_grading_group(empty_project_file, name="X")
        rels = result.group.IsGroupedBy
        assert len(rels) == 1
        assert result.composite_fill in rels[0].RelatedObjects

    def test_composite_fill_has_standard_pset(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.grading import create_grading_group

        result = create_grading_group(empty_project_file, name="X")
        common = _read_pset(result.composite_fill, "Pset_EarthworksFillCommon")
        assert common.get("Status") == "NEW"

    def test_composite_fill_is_omniclass_classified(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.grading import create_grading_group

        result = create_grading_group(empty_project_file, name="X")
        rels = empty_project_file.by_type("IfcRelAssociatesClassification")
        matching = [r for r in rels if result.composite_fill in r.RelatedObjects]
        assert len(matching) == 1
        reference = matching[0].RelatingClassification
        assert reference.Identification == "22-07 31 23"
        assert reference.ReferencedSource.Name == "OmniClass Table 22"

    def test_grading_source_pset_default_values(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.grading import create_grading_group

        result = create_grading_group(
            empty_project_file, name="X", interior_fill="flat"
        )
        source = _read_pset(result.group, "Pset_SaikeiGradingSource")
        assert source["InteriorFillStrategy"] == "flat"
        assert source["Version"] == 1
        assert isinstance(source["Timestamp"], int)
        assert "TargetSurfaceGuid" not in source
        assert "Author" not in source

    def test_target_surface_guid_recorded(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.grading import create_grading_group

        terrain = _make_terrain(empty_project_file, name="EG")
        result = create_grading_group(
            empty_project_file, name="X", target_surface=terrain, author="MJY"
        )
        source = _read_pset(result.group, "Pset_SaikeiGradingSource")
        assert source["TargetSurfaceGuid"] == terrain.GlobalId
        assert source["Author"] == "MJY"

    def test_invalid_interior_fill_raises(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.grading import create_grading_group

        with pytest.raises(ValueError, match="interior_fill must be one of"):
            create_grading_group(empty_project_file, name="X", interior_fill="bogus")

    def test_from_surface_requires_source(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.grading import create_grading_group

        with pytest.raises(ValueError, match="interior_fill_source"):
            create_grading_group(
                empty_project_file, name="X", interior_fill="from_surface"
            )

    def test_from_surface_with_source(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        """interior_fill='from_surface' is accepted when source is provided."""
        from ifcopenshell.api.grading import create_grading_group

        source_terrain = _make_terrain(empty_project_file, name="Src")
        result = create_grading_group(
            empty_project_file,
            name="X",
            interior_fill="from_surface",
            interior_fill_source=source_terrain,
        )
        info = _read_pset(result.group, "Pset_SaikeiGradingSource")
        assert info["InteriorFillStrategy"] == "from_surface"

    def test_raises_when_no_site(self) -> None:
        from ifcopenshell.api.grading import create_grading_group

        file = _empty_project_file_no_site()
        with pytest.raises(ValueError, match="no IfcSite"):
            create_grading_group(file, name="X")

    def test_round_trip(self, empty_project_file: ifcopenshell.file, tmp_path) -> None:
        from ifcopenshell.api.grading import create_grading_group

        terrain = _make_terrain(empty_project_file, name="RTTerrain")
        create_grading_group(
            empty_project_file,
            name="RTGroup",
            target_surface=terrain,
            interior_fill="interpolate_from_boundary",
            author="Tester",
        )

        path = tmp_path / "rt_grading_group.ifc"
        empty_project_file.write(str(path))
        reopened = ifcopenshell.open(str(path))

        groups = [
            g for g in reopened.by_type("IfcGroup")
            if g.Name == "RTGroup" and g.ObjectType == "GradingGroup"
        ]
        assert len(groups) == 1
        group = groups[0]
        # Composite fill is a member.
        rel = group.IsGroupedBy[0]
        members = rel.RelatedObjects
        assert any(
            m.is_a("IfcEarthworksFill") and m.PredefinedType == "SUBGRADE"
            for m in members
        )
        # Source pset round-trips.
        source = _read_pset(group, "Pset_SaikeiGradingSource")
        assert source["Author"] == "Tester"
        assert source["TargetSurfaceGuid"] == terrain.GlobalId


class TestAssignGradingCriteria:
    """Tests for ``ifcopenshell.api.grading.assign_grading_criteria``."""

    def _read_criteria_pset(
        self, group: ifcopenshell.entity_instance
    ) -> dict[str, object]:
        """Translate the bound IfcPropertySet into a name→value dict for assertions."""
        for rel in group.IsDefinedBy or []:
            if not rel.is_a("IfcRelDefinesByProperties"):
                continue
            pset = rel.RelatingPropertyDefinition
            if not (pset.is_a("IfcPropertySet") and pset.Name == "Pset_SaikeiGradingCriteria"):
                continue
            out: dict[str, object] = {}
            for prop in pset.HasProperties:
                if prop.is_a("IfcPropertyEnumeratedValue"):
                    out[prop.Name] = [v.wrappedValue for v in prop.EnumerationValues]
                elif prop.is_a("IfcPropertySingleValue") and prop.NominalValue is not None:
                    out[prop.Name] = prop.NominalValue.wrappedValue
            return out
        return {}

    def test_happy_path(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.grading import (
            assign_grading_criteria,
            create_grading_criteria_template,
            create_grading_group,
        )

        template = create_grading_criteria_template(empty_project_file)
        result = create_grading_group(empty_project_file, name="Pad")

        pset = assign_grading_criteria(
            empty_project_file,
            result.group,
            template,
            target_kind="surface",
            target_reference="3VxJzKQwT9XwJZ8RbZkH7E",
            cut_slope=2.0,
            fill_slope=3.0,
            max_distance=15.0,
            retaining_wall_at_limit=True,
        )

        assert pset.is_a("IfcPropertySet")
        assert pset.Name == "Pset_SaikeiGradingCriteria"

        properties = self._read_criteria_pset(result.group)
        assert properties["TargetKind"] == ["surface"]
        assert properties["TargetReference"] == "3VxJzKQwT9XwJZ8RbZkH7E"
        assert properties["CutSlope"] == 2.0
        assert properties["FillSlope"] == 3.0
        assert properties["MaxDistance"] == 15.0
        assert properties["RetainingWallAtLimit"] is True

    def test_template_binding_via_rel_defines_by_template(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        """The pset is linked back to its template via IfcRelDefinesByTemplate."""
        from ifcopenshell.api.grading import (
            assign_grading_criteria,
            create_grading_criteria_template,
            create_grading_group,
        )

        template = create_grading_criteria_template(empty_project_file)
        result = create_grading_group(empty_project_file, name="Pad")
        pset = assign_grading_criteria(
            empty_project_file,
            result.group,
            template,
            target_kind="elevation",
            cut_slope=2.0,
            fill_slope=3.0,
        )

        rels = empty_project_file.by_type("IfcRelDefinesByTemplate")
        matching = [r for r in rels if r.RelatingTemplate.id() == template.id()]
        assert len(matching) == 1
        assert pset in matching[0].RelatedPropertySets

    def test_optional_properties_omitted_when_none(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.grading import (
            assign_grading_criteria,
            create_grading_criteria_template,
            create_grading_group,
        )

        template = create_grading_criteria_template(empty_project_file)
        result = create_grading_group(empty_project_file, name="Pad")
        assign_grading_criteria(
            empty_project_file,
            result.group,
            template,
            target_kind="distance",
            cut_slope=2.5,
            fill_slope=3.0,
        )

        properties = self._read_criteria_pset(result.group)
        assert "TargetReference" not in properties
        assert "MaxDistance" not in properties
        # Required ones still there
        assert properties["TargetKind"] == ["distance"]
        assert properties["RetainingWallAtLimit"] is False

    def test_re_assign_updates_in_place(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        """A second call updates the same IfcPropertySet — no duplicate pset."""
        from ifcopenshell.api.grading import (
            assign_grading_criteria,
            create_grading_criteria_template,
            create_grading_group,
        )

        template = create_grading_criteria_template(empty_project_file)
        result = create_grading_group(empty_project_file, name="Pad")
        first = assign_grading_criteria(
            empty_project_file,
            result.group,
            template,
            target_kind="surface",
            cut_slope=2.0,
            fill_slope=3.0,
        )
        second = assign_grading_criteria(
            empty_project_file,
            result.group,
            template,
            target_kind="elevation",
            cut_slope=1.5,
            fill_slope=4.0,
            max_distance=10.0,
        )

        assert first.id() == second.id()
        properties = self._read_criteria_pset(result.group)
        assert properties["TargetKind"] == ["elevation"]
        assert properties["CutSlope"] == 1.5
        assert properties["FillSlope"] == 4.0
        assert properties["MaxDistance"] == 10.0

        # Exactly one criteria pset on the group.
        criteria_psets = [
            r.RelatingPropertyDefinition
            for r in result.group.IsDefinedBy or []
            if r.is_a("IfcRelDefinesByProperties")
            and r.RelatingPropertyDefinition.Name == "Pset_SaikeiGradingCriteria"
        ]
        assert len(criteria_psets) == 1

    def test_custom_name_override(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.grading import (
            assign_grading_criteria,
            create_grading_criteria_template,
            create_grading_group,
        )

        template = create_grading_criteria_template(empty_project_file)
        result = create_grading_group(empty_project_file, name="Pad")
        pset = assign_grading_criteria(
            empty_project_file,
            result.group,
            template,
            target_kind="surface",
            cut_slope=2.0,
            fill_slope=3.0,
            name="3:1 fill / 2:1 cut",
        )
        # IfcPropertySet.Name is the override, but the bound template still
        # discoverable via IfcRelDefinesByTemplate (so pset Name is purely
        # display-side).
        assert pset.Name == "3:1 fill / 2:1 cut"

    def test_invalid_target_kind_raises(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.grading import (
            assign_grading_criteria,
            create_grading_criteria_template,
            create_grading_group,
        )

        template = create_grading_criteria_template(empty_project_file)
        result = create_grading_group(empty_project_file, name="Pad")
        with pytest.raises(ValueError, match="target_kind must be one of"):
            assign_grading_criteria(
                empty_project_file,
                result.group,
                template,
                target_kind="not_allowed",
                cut_slope=2.0,
                fill_slope=3.0,
            )

    def test_non_positive_slope_raises(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.grading import (
            assign_grading_criteria,
            create_grading_criteria_template,
            create_grading_group,
        )

        template = create_grading_criteria_template(empty_project_file)
        result = create_grading_group(empty_project_file, name="Pad")
        with pytest.raises(ValueError, match="cut_slope must be > 0"):
            assign_grading_criteria(
                empty_project_file,
                result.group,
                template,
                target_kind="surface",
                cut_slope=0.0,
                fill_slope=3.0,
            )
        with pytest.raises(ValueError, match="fill_slope must be > 0"):
            assign_grading_criteria(
                empty_project_file,
                result.group,
                template,
                target_kind="surface",
                cut_slope=2.0,
                fill_slope=-1.0,
            )

    def test_non_positive_max_distance_raises(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.grading import (
            assign_grading_criteria,
            create_grading_criteria_template,
            create_grading_group,
        )

        template = create_grading_criteria_template(empty_project_file)
        result = create_grading_group(empty_project_file, name="Pad")
        with pytest.raises(ValueError, match="max_distance must be > 0"):
            assign_grading_criteria(
                empty_project_file,
                result.group,
                template,
                target_kind="surface",
                cut_slope=2.0,
                fill_slope=3.0,
                max_distance=0.0,
            )

    def test_wrong_template_raises(self, empty_project_file: ifcopenshell.file) -> None:
        """Passing an arbitrary IfcPropertySetTemplate is rejected."""
        from ifcopenshell.api.grading import (
            assign_grading_criteria,
            create_grading_group,
        )

        bogus_template = empty_project_file.create_entity(
            "IfcPropertySetTemplate",
            GlobalId=ifcopenshell.guid.new(),
            Name="Pset_NotOurs",
            TemplateType="PSET_OCCURRENCEDRIVEN",
            HasPropertyTemplates=[
                empty_project_file.create_entity(
                    "IfcSimplePropertyTemplate",
                    GlobalId=ifcopenshell.guid.new(),
                    Name="Bogus",
                    TemplateType="P_SINGLEVALUE",
                    PrimaryMeasureType="IfcLabel",
                )
            ],
        )
        result = create_grading_group(empty_project_file, name="Pad")
        with pytest.raises(ValueError, match="Pset_SaikeiGradingCriteria"):
            assign_grading_criteria(
                empty_project_file,
                result.group,
                bogus_template,
                target_kind="surface",
                cut_slope=2.0,
                fill_slope=3.0,
            )

    def test_round_trip(self, empty_project_file: ifcopenshell.file, tmp_path) -> None:
        from ifcopenshell.api.grading import (
            assign_grading_criteria,
            create_grading_criteria_template,
            create_grading_group,
        )

        template = create_grading_criteria_template(empty_project_file)
        result = create_grading_group(empty_project_file, name="RTPad")
        assign_grading_criteria(
            empty_project_file,
            result.group,
            template,
            target_kind="elevation",
            target_reference="100.5",
            cut_slope=2.0,
            fill_slope=3.0,
            max_distance=12.0,
            retaining_wall_at_limit=True,
        )

        path = tmp_path / "rt_criteria.ifc"
        empty_project_file.write(str(path))
        reopened = ifcopenshell.open(str(path))
        groups = [
            g for g in reopened.by_type("IfcGroup")
            if g.Name == "RTPad" and g.ObjectType == "GradingGroup"
        ]
        assert len(groups) == 1
        properties = self._read_criteria_pset(groups[0])
        assert properties["TargetKind"] == ["elevation"]
        assert properties["TargetReference"] == "100.5"
        assert properties["MaxDistance"] == 12.0
        assert properties["RetainingWallAtLimit"] is True

        # Template binding survives round-trip.
        rels = reopened.by_type("IfcRelDefinesByTemplate")
        assert len(rels) == 1
        assert rels[0].RelatingTemplate.Name == "Pset_SaikeiGradingCriteria"


def _slope_ribbon_geometry() -> tuple[
    list[tuple[float, float, float]], list[tuple[int, int, int]]
]:
    """8 triangles forming a slope ribbon around a 10×10 m square pad.

    Inner ring: square at z=100 (the feature line elevation).
    Outer ring: square 5 m wider in each direction at z=99 (the daylight line).
    """
    inner = [
        (0.0, 0.0, 100.0),
        (10.0, 0.0, 100.0),
        (10.0, 10.0, 100.0),
        (0.0, 10.0, 100.0),
    ]
    outer = [
        (-5.0, -5.0, 99.0),
        (15.0, -5.0, 99.0),
        (15.0, 15.0, 99.0),
        (-5.0, 15.0, 99.0),
    ]
    points = inner + outer
    # Two triangles per side (4 sides) = 8 triangles.
    triangles = []
    for i in range(4):
        j = (i + 1) % 4
        a = i  # inner i
        b = j  # inner i+1
        c = 4 + i  # outer i
        d = 4 + j  # outer i+1
        triangles.append((a, c, d))
        triangles.append((a, d, b))
    return points, triangles


class TestAddSlopeFillToGroup:
    """Tests for ``ifcopenshell.api.grading.add_slope_fill_to_group``."""

    def test_happy_path(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.grading import (
            add_slope_fill_to_group,
            create_grading_group,
        )

        result = create_grading_group(empty_project_file, name="Pad")
        points, triangles = _slope_ribbon_geometry()

        slope = add_slope_fill_to_group(
            empty_project_file,
            result.group,
            result.composite_fill,
            name="North slope",
            points=points,
            triangles=triangles,
        )

        assert slope.is_a("IfcEarthworksFill")
        assert slope.PredefinedType == "SLOPEFILL"
        assert slope.Name == "North slope"

    def test_tin_and_box_representations_attached(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.grading import (
            add_slope_fill_to_group,
            create_grading_group,
        )

        result = create_grading_group(empty_project_file, name="Pad")
        points, triangles = _slope_ribbon_geometry()
        slope = add_slope_fill_to_group(
            empty_project_file,
            result.group,
            result.composite_fill,
            name="S",
            points=points,
            triangles=triangles,
        )

        identifiers = {r.RepresentationIdentifier for r in slope.Representation.Representations}
        assert identifiers == {"SurfaceModel", "Box"}

    def test_added_to_group_as_member(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.grading import (
            add_slope_fill_to_group,
            create_grading_group,
        )

        result = create_grading_group(empty_project_file, name="Pad")
        points, triangles = _slope_ribbon_geometry()
        slope = add_slope_fill_to_group(
            empty_project_file,
            result.group,
            result.composite_fill,
            name="S",
            points=points,
            triangles=triangles,
        )

        rels = result.group.IsGroupedBy
        assert len(rels) == 1
        members = rels[0].RelatedObjects
        assert slope in members
        # Composite fill is also still a member.
        assert result.composite_fill in members

    def test_aggregated_under_composite(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.grading import (
            add_slope_fill_to_group,
            create_grading_group,
        )

        result = create_grading_group(empty_project_file, name="Pad")
        points, triangles = _slope_ribbon_geometry()
        slope = add_slope_fill_to_group(
            empty_project_file,
            result.group,
            result.composite_fill,
            name="S",
            points=points,
            triangles=triangles,
        )

        # The composite has IsDecomposedBy[*] linking it to slope as RelatedObject
        decomposed = result.composite_fill.IsDecomposedBy
        assert len(decomposed) == 1
        assert slope in decomposed[0].RelatedObjects

    def test_multiple_slopes_share_one_aggregation_rel(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        """Adding two slope fills under the same composite results in one IfcRelAggregates."""
        from ifcopenshell.api.grading import (
            add_slope_fill_to_group,
            create_grading_group,
        )

        result = create_grading_group(empty_project_file, name="Pad")
        points, triangles = _slope_ribbon_geometry()

        slope_a = add_slope_fill_to_group(
            empty_project_file,
            result.group,
            result.composite_fill,
            name="A",
            points=points,
            triangles=triangles,
        )
        slope_b = add_slope_fill_to_group(
            empty_project_file,
            result.group,
            result.composite_fill,
            name="B",
            points=points,
            triangles=triangles,
        )

        decomposed = result.composite_fill.IsDecomposedBy
        assert len(decomposed) == 1
        children = decomposed[0].RelatedObjects
        assert {slope_a.id(), slope_b.id()} <= {c.id() for c in children}

    def test_omniclass_classified_under_22_07_31_23(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.grading import (
            add_slope_fill_to_group,
            create_grading_group,
        )

        result = create_grading_group(empty_project_file, name="Pad")
        points, triangles = _slope_ribbon_geometry()
        slope = add_slope_fill_to_group(
            empty_project_file,
            result.group,
            result.composite_fill,
            name="S",
            points=points,
            triangles=triangles,
        )

        rels = empty_project_file.by_type("IfcRelAssociatesClassification")
        slope_rels = [r for r in rels if slope in r.RelatedObjects]
        assert len(slope_rels) == 1
        assert slope_rels[0].RelatingClassification.Identification == "22-07 31 23"

    def test_feature_line_added_to_group_when_supplied(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.grading import (
            add_slope_fill_to_group,
            create_feature_line,
            create_grading_group,
        )

        result = create_grading_group(empty_project_file, name="Pad")
        feature_line = create_feature_line(
            empty_project_file,
            name="FL",
            vertices=[(0.0, 0.0, 100.0), (10.0, 0.0, 100.0)],
        )
        points, triangles = _slope_ribbon_geometry()
        slope = add_slope_fill_to_group(
            empty_project_file,
            result.group,
            result.composite_fill,
            name="S",
            points=points,
            triangles=triangles,
            feature_line=feature_line,
        )
        assert slope is not None  # use the value to satisfy linters

        members = result.group.IsGroupedBy[0].RelatedObjects
        assert feature_line in members

    def test_standard_pset_attached(self, empty_project_file: ifcopenshell.file) -> None:
        from ifcopenshell.api.grading import (
            add_slope_fill_to_group,
            create_grading_group,
        )

        result = create_grading_group(empty_project_file, name="Pad")
        points, triangles = _slope_ribbon_geometry()
        slope = add_slope_fill_to_group(
            empty_project_file,
            result.group,
            result.composite_fill,
            name="S",
            points=points,
            triangles=triangles,
        )
        common = _read_pset(slope, "Pset_EarthworksFillCommon")
        assert common.get("Status") == "NEW"

    def test_wrong_group_type_raises(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.grading import (
            add_slope_fill_to_group,
            create_grading_group,
        )

        result = create_grading_group(empty_project_file, name="Pad")
        not_a_group = result.composite_fill  # a fill, not a group
        with pytest.raises(ValueError, match="group must be an IfcGroup"):
            add_slope_fill_to_group(
                empty_project_file,
                not_a_group,
                result.composite_fill,
                name="S",
                points=[(0.0, 0.0, 0.0)],
                triangles=[],
            )

    def test_wrong_composite_type_raises(
        self, empty_project_file: ifcopenshell.file
    ) -> None:
        from ifcopenshell.api.grading import (
            add_slope_fill_to_group,
            create_grading_group,
        )

        result = create_grading_group(empty_project_file, name="Pad")
        with pytest.raises(ValueError, match="composite_fill must be an IfcEarthworksFill"):
            add_slope_fill_to_group(
                empty_project_file,
                result.group,
                result.group,  # wrong type
                name="S",
                points=[(0.0, 0.0, 0.0)],
                triangles=[],
            )

    def test_round_trip(self, empty_project_file: ifcopenshell.file, tmp_path) -> None:
        from ifcopenshell.api.grading import (
            add_slope_fill_to_group,
            create_grading_group,
        )

        result = create_grading_group(empty_project_file, name="RTPad")
        points, triangles = _slope_ribbon_geometry()
        add_slope_fill_to_group(
            empty_project_file,
            result.group,
            result.composite_fill,
            name="RT_Slope",
            points=points,
            triangles=triangles,
        )

        path = tmp_path / "rt_slope.ifc"
        empty_project_file.write(str(path))
        reopened = ifcopenshell.open(str(path))
        slopes = [
            f for f in reopened.by_type("IfcEarthworksFill")
            if f.Name == "RT_Slope" and f.PredefinedType == "SLOPEFILL"
        ]
        assert len(slopes) == 1
        slope = slopes[0]
        identifiers = {r.RepresentationIdentifier for r in slope.Representation.Representations}
        assert identifiers == {"SurfaceModel", "Box"}
        # Aggregated under the composite (which is named "RTPad").
        composite = slope.Decomposes[0].RelatingObject
        assert composite.Name == "RTPad"
        assert composite.PredefinedType == "SUBGRADE"

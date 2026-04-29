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

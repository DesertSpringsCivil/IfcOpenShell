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

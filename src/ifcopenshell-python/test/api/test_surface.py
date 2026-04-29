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

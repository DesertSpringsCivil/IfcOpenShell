# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2026 Michael Yoder <myoder@desertspringscivil.com>
#
# This file is part of Bonsai.
#
# Bonsai is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Bonsai is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Bonsai.  If not, see <http://www.gnu.org/licenses/>.

"""Smoke tests for the Saikei surface module's property registration.

Run via the canonical Phase 4 invocation under Blender headless. Verifies
that :func:`bonsai.bim.module.surface.register` attaches the
``CivilSurfaceProperties`` pointer to ``bpy.types.Scene`` and that the
property groups expose the expected fields.
"""

import bpy
import pytest

import bonsai.bim.module.surface.prop as surface_prop


class TestSurfacePropertyRegistration:
    """Smoke tests for the registered :class:`CivilSurfaceProperties`."""

    def test_civil_surface_properties_attached_to_scene(self) -> None:
        """The module register() hook should attach the property group as a
        PointerProperty named ``CivilSurfaceProperties`` on ``bpy.types.Scene``."""
        # bpy.types.Scene.bl_rna inspection — check the registered annotation.
        rna = bpy.types.Scene.bl_rna
        assert "CivilSurfaceProperties" in rna.properties, (
            "CivilSurfaceProperties not registered on bpy.types.Scene; "
            "bonsai.bim.module.surface.register() may not have run"
        )

    def test_active_scene_can_access_civil_surface_properties(self) -> None:
        """A scene's ``CivilSurfaceProperties`` should be accessible and have
        the expected default values."""
        props = bpy.context.scene.CivilSurfaceProperties
        assert props.new_surface_name == "Existing Ground"
        assert props.new_surface_kind == "existing"
        assert props.triangulation_tolerance == pytest.approx(0.0)
        assert props.active_surface_id == 0
        assert props.active_surface_guid == ""
        assert len(props.surfaces) == 0
        assert props.show_triangles is False
        assert props.show_elevation_banding is False

    def test_new_surface_kind_enum_has_three_options(self) -> None:
        """The kind enum exposes the three surface kinds per spec §2.2."""
        rna = surface_prop.CivilSurfaceProperties.bl_rna
        kind_prop = rna.properties["new_surface_kind"]
        assert {item.identifier for item in kind_prop.enum_items} == {
            "existing",
            "proposed_group",
            "proposed_site",
        }


class TestCivilSurfaceListItem:
    """Tests for :class:`bonsai.bim.module.surface.prop.CivilSurfaceListItem`."""

    def test_can_be_added_to_collection_with_defaults(self) -> None:
        """Adding a list item should default name/guid/ifc_id/kind sensibly."""
        props = bpy.context.scene.CivilSurfaceProperties
        item = props.surfaces.add()
        try:
            assert item.name == ""
            assert item.guid == ""
            assert item.ifc_id == 0
            assert item.kind == "existing"
        finally:
            props.surfaces.remove(0)

    def test_can_set_fields(self) -> None:
        """The list item's fields should be writable."""
        props = bpy.context.scene.CivilSurfaceProperties
        item = props.surfaces.add()
        try:
            item.name = "My Surface"
            item.guid = "0123456789ABCDEFGHIJKL"
            item.ifc_id = 42
            item.kind = "proposed_group"
            assert item.name == "My Surface"
            assert item.guid == "0123456789ABCDEFGHIJKL"
            assert item.ifc_id == 42
            assert item.kind == "proposed_group"
        finally:
            props.surfaces.remove(0)


class TestSurfacesUIList:
    """Tests for :class:`CIVIL_UL_surfaces`."""

    def test_uilist_class_is_registered(self) -> None:
        assert hasattr(bpy.types, "CIVIL_UL_surfaces")

    def test_uilist_has_kind_icon_map(self) -> None:
        """All three Saikei surface kinds map to a recognized Blender icon."""
        icon_map = surface_prop.CIVIL_UL_surfaces._KIND_ICON
        assert set(icon_map.keys()) == {
            "existing",
            "proposed_group",
            "proposed_site",
        }
        # Sanity: icons should be uppercase strings (Blender convention).
        for icon in icon_map.values():
            assert isinstance(icon, str) and icon == icon.upper()

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

"""Tests for ``bonsai.core.surface``.

Pure-Python core tests — no Blender required. Run from ``src/bonsai``::

    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/core/test_surface.py -o "addopts=" -v
"""

import pytest

import bonsai.core.surface as subject
from test.core.bootstrap import ifc, surface


class FakeIfcFile(dict):
    """Minimal IFC-file stand-in for core tests.

    Inherits from ``dict`` so :class:`Prophecy` can JSON-serialize it when it
    appears in tracked tool-method arguments.
    """

    def __init__(self, name: str = "TestFile") -> None:
        super().__init__(file_name=name)


class FakeCivilSurface(dict):
    """Stand-in for :class:`bonsai.tool.surface.CivilSurface`. Inherits from
    ``dict`` for Prophecy serialization (same reason as :class:`FakeIfcFile`)."""

    def __init__(self, name: str = "TestSurface", guid: str = "fake-guid") -> None:
        super().__init__(name=name, guid=guid)


# ---------------------------------------------------------------------------
# create_surface_from_points
# ---------------------------------------------------------------------------


class TestCreateSurfaceFromPoints:
    def test_raises_when_no_ifc_file_loaded(self, ifc, surface):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.create_surface_from_points(
                ifc, surface, name="Test", points=[(0, 0, 0), (1, 0, 0), (0, 1, 0)]
            )

    def test_raises_when_name_is_empty(self, ifc, surface):
        ifc.get().should_be_called().will_return(FakeIfcFile())
        with pytest.raises(ValueError, match="surface name cannot be empty"):
            subject.create_surface_from_points(
                ifc, surface, name="", points=[(0, 0, 0), (1, 0, 0), (0, 1, 0)]
            )

    def test_raises_when_name_is_whitespace_only(self, ifc, surface):
        ifc.get().should_be_called().will_return(FakeIfcFile())
        with pytest.raises(ValueError, match="surface name cannot be empty"):
            subject.create_surface_from_points(
                ifc,
                surface,
                name="   ",
                points=[(0, 0, 0), (1, 0, 0), (0, 1, 0)],
            )

    def test_raises_when_kind_is_invalid(self, ifc, surface):
        ifc.get().should_be_called().will_return(FakeIfcFile())
        with pytest.raises(ValueError, match="kind must be one of"):
            subject.create_surface_from_points(
                ifc,
                surface,
                name="Test",
                points=[(0, 0, 0), (1, 0, 0), (0, 1, 0)],
                kind="bogus",
            )

    def test_happy_path_calls_tool_methods_in_order(self, ifc, surface):
        """Build → author → register, all called once with the right args."""
        fake_file = FakeIfcFile()
        fake_surface = FakeCivilSurface(name="HappyPath")
        points = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]

        ifc.get().should_be_called().will_return(fake_file)
        surface.build_tin_from_points(
            name="HappyPath", points=points, kind="existing"
        ).should_be_called().will_return(fake_surface)
        surface.author_ifc_host(
            fake_file, fake_surface, triangulation_tolerance=0.0
        ).should_be_called()
        surface.register(fake_file, fake_surface).should_be_called()

        result = subject.create_surface_from_points(
            ifc, surface, name="HappyPath", points=points
        )
        assert result is fake_surface

    def test_strips_name_whitespace_before_passing_to_tool(self, ifc, surface):
        fake_file = FakeIfcFile()
        fake_surface = FakeCivilSurface(name="Trimmed")
        points = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]

        ifc.get().should_be_called().will_return(fake_file)
        # Name passed to tool must be stripped.
        surface.build_tin_from_points(
            name="Trimmed", points=points, kind="existing"
        ).should_be_called().will_return(fake_surface)
        surface.author_ifc_host(
            fake_file, fake_surface, triangulation_tolerance=0.0
        ).should_be_called()
        surface.register(fake_file, fake_surface).should_be_called()

        subject.create_surface_from_points(
            ifc, surface, name="  Trimmed  ", points=points
        )

    def test_kind_proposed_group_passes_through(self, ifc, surface):
        fake_file = FakeIfcFile()
        fake_surface = FakeCivilSurface()
        points = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]

        ifc.get().should_be_called().will_return(fake_file)
        surface.build_tin_from_points(
            name="P", points=points, kind="proposed_group"
        ).should_be_called().will_return(fake_surface)
        surface.author_ifc_host(
            fake_file, fake_surface, triangulation_tolerance=0.0
        ).should_be_called()
        surface.register(fake_file, fake_surface).should_be_called()

        subject.create_surface_from_points(
            ifc, surface, name="P", points=points, kind="proposed_group"
        )

    def test_kind_proposed_site_passes_through(self, ifc, surface):
        fake_file = FakeIfcFile()
        fake_surface = FakeCivilSurface()
        points = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]

        ifc.get().should_be_called().will_return(fake_file)
        surface.build_tin_from_points(
            name="S", points=points, kind="proposed_site"
        ).should_be_called().will_return(fake_surface)
        surface.author_ifc_host(
            fake_file, fake_surface, triangulation_tolerance=0.0
        ).should_be_called()
        surface.register(fake_file, fake_surface).should_be_called()

        subject.create_surface_from_points(
            ifc, surface, name="S", points=points, kind="proposed_site"
        )

    def test_triangulation_tolerance_forwarded_to_tool(self, ifc, surface):
        fake_file = FakeIfcFile()
        fake_surface = FakeCivilSurface()
        points = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]

        ifc.get().should_be_called().will_return(fake_file)
        surface.build_tin_from_points(
            name="T", points=points, kind="existing"
        ).should_be_called().will_return(fake_surface)
        surface.author_ifc_host(
            fake_file, fake_surface, triangulation_tolerance=0.005
        ).should_be_called()
        surface.register(fake_file, fake_surface).should_be_called()

        subject.create_surface_from_points(
            ifc,
            surface,
            name="T",
            points=points,
            triangulation_tolerance=0.005,
        )

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

    def __init__(
        self,
        name: str = "TestSurface",
        guid: str = "fake-guid",
        ifc_host_entity_id=None,
    ) -> None:
        super().__init__(name=name, guid=guid)
        # Real attributes the orchestration mutates (registered after dict init
        # so they don't pollute the dict for json.dumps).
        self.breaklines: list = []
        self.outer_boundary = None
        self.ifc_host_entity_id = ifc_host_entity_id


class FakeBreakline(dict):
    """Stand-in for :class:`Breakline`."""

    def __init__(self, guid: str = "bl-guid", name: str = "test-breakline") -> None:
        super().__init__(guid=guid, name=name)


class FakePolygon(dict):
    """Stand-in for :class:`shapely.Polygon`."""

    def __init__(self, label: str = "boundary") -> None:
        super().__init__(label=label)


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

    def test_multi_site_file_emits_warning(self, ifc, surface, caplog):
        """Closes the cold-review-flagged multi-site footgun (spec §4.3).
        Files with >1 IfcSite log a WARNING-level message so callers
        notice the implicit-first-site spatial-parent resolution.
        """

        class MultiSiteFakeFile(FakeIfcFile):
            def by_type(self, ifc_class):
                if ifc_class == "IfcSite":
                    return [object(), object()]  # 2 sites
                return []

        fake_file = MultiSiteFakeFile()
        fake_surface = FakeCivilSurface()

        ifc.get().should_be_called().will_return(fake_file)
        surface.build_tin_from_points(
            name="MS", points=[(0, 0, 0), (1, 0, 0), (0, 1, 0)], kind="existing"
        ).should_be_called().will_return(fake_surface)
        surface.author_ifc_host(
            fake_file, fake_surface, triangulation_tolerance=0.0
        ).should_be_called()
        surface.register(fake_file, fake_surface).should_be_called()

        with caplog.at_level("WARNING", logger="bonsai.core.surface"):
            subject.create_surface_from_points(
                ifc,
                surface,
                name="MS",
                points=[(0, 0, 0), (1, 0, 0), (0, 1, 0)],
            )

        assert any(
            "multi-site" in r.message.lower() for r in caplog.records
        ), f"expected multi-site warning, got: {[r.message for r in caplog.records]}"

    def test_single_site_file_does_not_warn(self, ifc, surface, caplog):
        """Sanity: single-site files don't trigger the warning."""

        class SingleSiteFakeFile(FakeIfcFile):
            def by_type(self, ifc_class):
                if ifc_class == "IfcSite":
                    return [object()]  # 1 site
                return []

        fake_file = SingleSiteFakeFile()
        fake_surface = FakeCivilSurface()

        ifc.get().should_be_called().will_return(fake_file)
        surface.build_tin_from_points(
            name="OK", points=[(0, 0, 0), (1, 0, 0), (0, 1, 0)], kind="existing"
        ).should_be_called().will_return(fake_surface)
        surface.author_ifc_host(
            fake_file, fake_surface, triangulation_tolerance=0.0
        ).should_be_called()
        surface.register(fake_file, fake_surface).should_be_called()

        with caplog.at_level("WARNING", logger="bonsai.core.surface"):
            subject.create_surface_from_points(
                ifc,
                surface,
                name="OK",
                points=[(0, 0, 0), (1, 0, 0), (0, 1, 0)],
            )

        assert not any(
            "multi-site" in r.message.lower() for r in caplog.records
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


# ---------------------------------------------------------------------------
# add_breakline_to_surface
# ---------------------------------------------------------------------------


class TestAddBreaklineToSurface:
    def test_raises_when_no_ifc_file_loaded(self, ifc, surface):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.add_breakline_to_surface(
                ifc, surface, surface_guid="g", breakline=FakeBreakline()
            )

    def test_happy_path_calls_tool_methods_in_order(self, ifc, surface):
        """get → author_ifc_breakline → mutate breaklines → retriangulate →
        update_ifc_tin, all called once. Surface with no IFC host (test
        fixture default) skips the host-link."""
        fake_file = FakeIfcFile()
        fake_surface = FakeCivilSurface()  # ifc_host_entity_id=None
        breakline = FakeBreakline()

        ifc.get().should_be_called().will_return(fake_file)
        surface.get(fake_file, "guid-A").should_be_called().will_return(fake_surface)
        surface.author_ifc_breakline(
            fake_file,
            breakline,
            grading_group_guid=None,
            host_surface=None,
        ).should_be_called()
        surface.retriangulate(fake_surface).should_be_called()
        surface.update_ifc_tin(fake_file, fake_surface).should_be_called()

        result = subject.add_breakline_to_surface(
            ifc, surface, surface_guid="guid-A", breakline=breakline
        )
        assert result is fake_surface
        # Breakline got appended to the dataclass list.
        assert breakline in fake_surface.breaklines

    def test_grading_group_guid_passes_through(self, ifc, surface):
        fake_file = FakeIfcFile()
        fake_surface = FakeCivilSurface()
        breakline = FakeBreakline()

        ifc.get().should_be_called().will_return(fake_file)
        surface.get(fake_file, "guid-B").should_be_called().will_return(fake_surface)
        surface.author_ifc_breakline(
            fake_file,
            breakline,
            grading_group_guid="grp-1",
            host_surface=None,
        ).should_be_called()
        surface.retriangulate(fake_surface).should_be_called()
        surface.update_ifc_tin(fake_file, fake_surface).should_be_called()

        subject.add_breakline_to_surface(
            ifc,
            surface,
            surface_guid="guid-B",
            breakline=breakline,
            grading_group_guid="grp-1",
        )


# ---------------------------------------------------------------------------
# set_outer_boundary
# ---------------------------------------------------------------------------


class TestSetOuterBoundary:
    def test_raises_when_no_ifc_file_loaded(self, ifc, surface):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.set_outer_boundary(
                ifc, surface, surface_guid="g", boundary_polygon=FakePolygon()
            )

    def test_happy_path_calls_tool_methods_in_order(self, ifc, surface):
        """get → mutate outer_boundary → retriangulate → update_ifc_tin."""
        fake_file = FakeIfcFile()
        fake_surface = FakeCivilSurface()
        polygon = FakePolygon(label="new-boundary")

        ifc.get().should_be_called().will_return(fake_file)
        surface.get(fake_file, "guid-X").should_be_called().will_return(fake_surface)
        surface.retriangulate(fake_surface).should_be_called()
        surface.update_ifc_tin(fake_file, fake_surface).should_be_called()

        result = subject.set_outer_boundary(
            ifc, surface, surface_guid="guid-X", boundary_polygon=polygon
        )
        assert result is fake_surface
        assert fake_surface.outer_boundary is polygon

    def test_polygon_replaces_previous_boundary(self, ifc, surface):
        """Mutation overwrites the existing outer_boundary attribute."""
        fake_file = FakeIfcFile()
        fake_surface = FakeCivilSurface()
        fake_surface.outer_boundary = FakePolygon(label="old")
        polygon = FakePolygon(label="new")

        ifc.get().should_be_called().will_return(fake_file)
        surface.get(fake_file, "g").should_be_called().will_return(fake_surface)
        surface.retriangulate(fake_surface).should_be_called()
        surface.update_ifc_tin(fake_file, fake_surface).should_be_called()

        subject.set_outer_boundary(
            ifc, surface, surface_guid="g", boundary_polygon=polygon
        )
        assert fake_surface.outer_boundary is polygon


# ---------------------------------------------------------------------------
# retriangulate_surface
# ---------------------------------------------------------------------------


class TestRetriangulateSurface:
    def test_raises_when_no_ifc_file_loaded(self, ifc, surface):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.retriangulate_surface(ifc, surface, surface_guid="g")

    def test_happy_path_calls_tool_methods_in_order(self, ifc, surface):
        """get → retriangulate → update_ifc_tin."""
        fake_file = FakeIfcFile()
        fake_surface = FakeCivilSurface()

        ifc.get().should_be_called().will_return(fake_file)
        surface.get(fake_file, "guid-R").should_be_called().will_return(fake_surface)
        surface.retriangulate(fake_surface).should_be_called()
        surface.update_ifc_tin(fake_file, fake_surface).should_be_called()

        result = subject.retriangulate_surface(
            ifc, surface, surface_guid="guid-R"
        )
        assert result is fake_surface

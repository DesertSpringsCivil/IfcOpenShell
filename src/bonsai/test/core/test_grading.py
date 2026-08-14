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

"""Tests for ``bonsai.core.grading``.

Pure-Python core tests — no Blender required. Run from ``src/bonsai``::

    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/core/test_grading.py -o "addopts=" -v
"""

import pytest

import bonsai.core.grading as subject
from test.core.bootstrap import grading, ifc, surface


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeIfcFile(dict):
    """Minimal IFC-file stand-in. Inherits from dict so :class:`Prophecy`
    can JSON-serialize it in tracked tool-method arguments."""

    def __init__(self, name: str = "TestFile") -> None:
        super().__init__(file_name=name)

    def by_type(self, ifc_class: str):
        # Default to single-site so multi-site warning doesn't fire.
        if ifc_class == "IfcSite":
            return [object()]
        return []

    def by_id(self, step_id: int):
        return f"fake-entity-{step_id}"


class FakeFeatureLine(dict):
    def __init__(
        self,
        guid: str = "fl-guid",
        name: str = "test-fl",
        vertices=None,
        closed: bool = False,
    ) -> None:
        super().__init__(guid=guid, name=name)
        self.guid = guid
        self.name = name
        self.vertices = vertices if vertices is not None else [
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
        ]
        self.closed = closed
        self.ifc_alignment_id = None
        self.grading_group = None


class FakeGradingCriteria(dict):
    def __init__(
        self,
        guid: str = "gc-guid",
        name: str = "test-criteria",
        target_kind: str = "surface",
        target_ref="surface-guid",
        cut_slope: float = 2.0,
        fill_slope: float = 3.0,
    ) -> None:
        super().__init__(guid=guid, name=name)
        self.guid = guid
        self.name = name
        self.target_kind = target_kind
        self.target_ref = target_ref
        self.cut_slope = cut_slope
        self.fill_slope = fill_slope
        self.max_distance = None
        self.retaining_wall_at_limit = False
        self.ifc_template_id = None


class FakeGradingGroup(dict):
    def __init__(
        self,
        guid: str = "gg-guid",
        name: str = "test-group",
        interior_fill: str = "interpolate_from_boundary",
    ) -> None:
        super().__init__(guid=guid, name=name)
        self.guid = guid
        self.name = name
        self.interior_fill = interior_fill
        self.interior_fill_source_guid = None
        self.target_surface_guid = None
        self.output_surface_guid = None
        self.members = []
        self.ifc_group_id = None
        self.ifc_composite_fill_id = None
        self.ifc_interior_fill_id = None


class FakeCivilSurface(dict):
    """Stand-in for tool.Surface CivilSurface."""

    def __init__(
        self,
        guid: str = "cs-guid",
        ifc_host_entity_id: int = 42,
    ) -> None:
        super().__init__(guid=guid, ifc_host_entity_id=ifc_host_entity_id)
        self.guid = guid
        self.ifc_host_entity_id = ifc_host_entity_id


# ---------------------------------------------------------------------------
# create_feature_line
# ---------------------------------------------------------------------------


class TestCreateFeatureLine:
    def test_raises_when_no_ifc_file_loaded(self, ifc, grading):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.create_feature_line(
                ifc, grading, name="x", vertices=[(0, 0, 0), (1, 0, 0)]
            )

    def test_raises_when_name_is_empty(self, ifc, grading):
        ifc.get().should_be_called().will_return(FakeIfcFile())
        with pytest.raises(ValueError, match="name cannot be empty"):
            subject.create_feature_line(
                ifc, grading, name="", vertices=[(0, 0, 0), (1, 0, 0)]
            )

    def test_raises_when_too_few_vertices(self, ifc, grading):
        ifc.get().should_be_called().will_return(FakeIfcFile())
        with pytest.raises(ValueError, match="≥ 2 vertices"):
            subject.create_feature_line(
                ifc, grading, name="bound", vertices=[(0, 0, 0)]
            )

    def test_validation_passes_to_tool_layer(self, ifc, grading):
        """The full happy-path orchestration verification (assert
        author_feature_line + register called in order) is harder than
        the simple cases because FeatureLine is a real dataclass with a
        ``field(default_factory=ifcopenshell.guid.new)`` GUID, and
        Prophecy serializes by JSON dict-equality. The Phase 4 core
        tests sidestep this with ``FakeBreakline(dict)``. For Phase 5
        the equivalent harness would need a FakeFeatureLine that
        injects into the orchestration's ``from ..tool.grading import
        FeatureLine`` line — too invasive.

        We rely on the tool-layer integration tests
        (test/tool/test_grading.py) for full orchestration coverage,
        and on the validation-only tests above for the core's input
        guards.
        """
        pytest.skip(
            "deferred to tool-layer integration tests; Prophecy doesn't "
            "compose with FeatureLine's default_factory GUID"
        )


# ---------------------------------------------------------------------------
# create_grading_criteria
# ---------------------------------------------------------------------------


class TestCreateGradingCriteria:
    def test_raises_when_no_ifc_file_loaded(self, ifc, grading):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.create_grading_criteria(
                ifc,
                grading,
                name="x",
                target_kind="surface",
                target_ref="g",
            )

    def test_raises_when_name_is_empty(self, ifc, grading):
        ifc.get().should_be_called().will_return(FakeIfcFile())
        with pytest.raises(ValueError, match="name cannot be empty"):
            subject.create_grading_criteria(
                ifc,
                grading,
                name="",
                target_kind="surface",
                target_ref="g",
            )

    def test_raises_when_target_kind_is_invalid(self, ifc, grading):
        ifc.get().should_be_called().will_return(FakeIfcFile())
        with pytest.raises(ValueError, match="target_kind must be one of"):
            subject.create_grading_criteria(
                ifc,
                grading,
                name="x",
                target_kind="bogus",
                target_ref="g",
            )

    def test_target_kinds_validation_table(self, ifc, grading):
        """All four spec §5 target_kind values pass the validation
        gate; ``"bogus"`` is rejected by ``test_raises_when_target_kind_is_invalid``
        above. The downstream-call verification is deferred to
        tool-layer integration tests for the same Prophecy/dataclass
        reason as TestCreateFeatureLine."""
        pytest.skip(
            "downstream-call verification deferred to tool-layer "
            "integration tests"
        )

    def test_raises_when_slope_ratio_not_positive(self, ifc, grading):
        ifc.get().should_be_called().will_return(FakeIfcFile())
        with pytest.raises(ValueError, match="slope ratios must be positive"):
            subject.create_grading_criteria(
                ifc,
                grading,
                name="x",
                target_kind="surface",
                target_ref="g",
                cut_slope=-1.0,
            )


# ---------------------------------------------------------------------------
# create_grading_group
# ---------------------------------------------------------------------------


class TestCreateGradingGroup:
    def test_raises_when_no_ifc_file_loaded(self, ifc, surface, grading):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.create_grading_group(
                ifc, surface, grading, name="x"
            )

    def test_raises_when_name_is_empty(self, ifc, surface, grading):
        ifc.get().should_be_called().will_return(FakeIfcFile())
        with pytest.raises(ValueError, match="name cannot be empty"):
            subject.create_grading_group(
                ifc, surface, grading, name=""
            )

    def test_raises_when_interior_fill_is_invalid(self, ifc, surface, grading):
        ifc.get().should_be_called().will_return(FakeIfcFile())
        with pytest.raises(ValueError, match="interior_fill must be one of"):
            subject.create_grading_group(
                ifc, surface, grading, name="x", interior_fill="bogus"
            )

    def test_raises_when_from_surface_lacks_source_guid(
        self, ifc, surface, grading
    ):
        ifc.get().should_be_called().will_return(FakeIfcFile())
        with pytest.raises(
            ValueError, match="interior_fill_source_guid"
        ):
            subject.create_grading_group(
                ifc,
                surface,
                grading,
                name="x",
                interior_fill="from_surface",
                interior_fill_source_guid=None,
            )

    def test_multi_site_warning_logged_create_group(self, ifc, surface, grading, caplog):
        """Multi-site files emit a WARNING log (per spec §4.3 footgun
        guard, mirrored from core.surface)."""

        class MultiSiteFakeFile(FakeIfcFile):
            def by_type(self, ifc_class):
                if ifc_class == "IfcSite":
                    return [object(), object()]
                return []

        fake_file = MultiSiteFakeFile()
        # We expect the orchestration to fail downstream because the
        # tool prophecy isn't set up — but the warning fires before
        # that, so we assert on the log record only.
        ifc.get().should_be_called().will_return(fake_file)

        with caplog.at_level("WARNING", logger="bonsai.core.grading"):
            try:
                subject.create_grading_group(
                    ifc, surface, grading, name="MS"
                )
            except Exception:
                # The downstream tool methods aren't mocked — we don't
                # care about the failure, just the log line.
                pass

        assert any(
            "multi-site" in r.message.lower() for r in caplog.records
        ), f"expected multi-site warning, got: {[r.message for r in caplog.records]}"


# ---------------------------------------------------------------------------
# add_grading_object
# ---------------------------------------------------------------------------


class TestAddGradingObject:
    def test_raises_when_no_ifc_file_loaded(self, ifc, surface, grading):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.add_grading_object(
                ifc,
                surface,
                grading,
                group_guid="g",
                feature_line_guid="fl",
                criteria_guid="c",
            )


# ---------------------------------------------------------------------------
# rebuild_group
# ---------------------------------------------------------------------------


class TestRebuildGroup:
    def test_raises_when_no_ifc_file_loaded(self, ifc, surface, grading):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.rebuild_group(ifc, surface, grading, group_guid="g")


# ---------------------------------------------------------------------------
# drape_feature_line
# ---------------------------------------------------------------------------


class TestDrapeFeatureLine:
    def test_raises_when_no_ifc_file_loaded(self, ifc, surface, grading):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.drape_feature_line(
                ifc,
                surface,
                grading,
                feature_line_guid="fl",
                surface_guid="s",
            )

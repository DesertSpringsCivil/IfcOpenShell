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

"""Tests for ``bonsai.core.earthwork``.

Pure-Python core tests — no Blender required. Run from ``src/bonsai``::

    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/core/test_earthwork.py -o "addopts=" -v

These tests cover the validation rules of
:func:`bonsai.core.earthwork.compute_earthwork_volumes`. The full
happy-path orchestration verification (cut + fill author) is
exercised end-to-end by the Phase 6 bSI integration test in
``test/tool/test_earthwork.py`` — same convention as Phase 5's
core tests, which sidestep Prophecy's JSON-dict-equality limitation
on dataclasses with ``field(default_factory=...)`` GUIDs.
"""

import pytest

import bonsai.core.earthwork as subject
from test.core.bootstrap import earthwork, ifc, surface


class FakeIfcFile(dict):
    """Minimal IFC-file stand-in."""

    def by_id(self, step_id: int):
        return f"fake-host-#{step_id}"


# ---------------------------------------------------------------------------
# Validation paths in compute_earthwork_volumes
# ---------------------------------------------------------------------------


class TestComputeEarthworkVolumesValidation:
    """Input-validation rules surface as ValueError at the
    orchestration boundary before any tool-method calls fire."""

    def test_no_ifc_file_loaded_raises(
        self, ifc, surface, earthwork
    ) -> None:
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.compute_earthwork_volumes(
                ifc, surface, earthwork,
                existing_surface_guid="eg",
                proposed_surface_guid="pr",
            )

    def test_zero_shrink_factor_raises(
        self, ifc, surface, earthwork
    ) -> None:
        ifc.get().should_be_called().will_return(FakeIfcFile())
        with pytest.raises(ValueError, match="shrink_factor must be"):
            subject.compute_earthwork_volumes(
                ifc, surface, earthwork,
                existing_surface_guid="eg",
                proposed_surface_guid="pr",
                shrink_factor=0.0,
            )

    def test_negative_shrink_factor_raises(
        self, ifc, surface, earthwork
    ) -> None:
        ifc.get().should_be_called().will_return(FakeIfcFile())
        with pytest.raises(ValueError, match="shrink_factor must be"):
            subject.compute_earthwork_volumes(
                ifc, surface, earthwork,
                existing_surface_guid="eg",
                proposed_surface_guid="pr",
                shrink_factor=-0.5,
            )

    def test_zero_swell_factor_raises(
        self, ifc, surface, earthwork
    ) -> None:
        ifc.get().should_be_called().will_return(FakeIfcFile())
        with pytest.raises(ValueError, match="swell_factor must be"):
            subject.compute_earthwork_volumes(
                ifc, surface, earthwork,
                existing_surface_guid="eg",
                proposed_surface_guid="pr",
                swell_factor=0.0,
            )

    def test_negative_swell_factor_raises(
        self, ifc, surface, earthwork
    ) -> None:
        ifc.get().should_be_called().will_return(FakeIfcFile())
        with pytest.raises(ValueError, match="swell_factor must be"):
            subject.compute_earthwork_volumes(
                ifc, surface, earthwork,
                existing_surface_guid="eg",
                proposed_surface_guid="pr",
                swell_factor=-1.0,
            )

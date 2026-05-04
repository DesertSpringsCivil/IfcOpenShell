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

"""Tests for ``bonsai.tool.earthwork``.

Run via the canonical Phase 4/5/6 invocation (PowerShell, from src/bonsai)::

    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
    python -m pytest test/tool/test_earthwork.py `
      -o "addopts=" `
      -p pytest-blender `
      -v `
      --blender-executable "C:\\Program Files\\Blender Foundation\\Blender_5\\blender.exe"
"""

import numpy as np
import pytest

import bonsai.tool.earthwork as tool_earthwork


@pytest.fixture(autouse=True)
def _reset_earthwork_registry():
    """Wipe :attr:`Earthwork._registry` between every test (per spec
    §4.6). Mirrors the surface and grading modules' autouse teardown."""
    yield
    tool_earthwork.Earthwork.clear()


# ---------------------------------------------------------------------------
# SubTriangle
# ---------------------------------------------------------------------------


class TestSubTriangle:
    """Tests for :class:`bonsai.tool.earthwork.SubTriangle`."""

    def test_delta_z_positive_for_cut(self) -> None:
        st = tool_earthwork.SubTriangle(
            vertices_xy=np.array([(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]),
            z_existing_avg=110.0,
            z_proposed_avg=100.0,
            area_m2=0.5,
        )
        assert st.delta_z == pytest.approx(10.0)

    def test_delta_z_negative_for_fill(self) -> None:
        st = tool_earthwork.SubTriangle(
            vertices_xy=np.array([(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]),
            z_existing_avg=95.0,
            z_proposed_avg=100.0,
            area_m2=0.5,
        )
        assert st.delta_z == pytest.approx(-5.0)

    def test_signed_volume_is_area_times_delta(self) -> None:
        st = tool_earthwork.SubTriangle(
            vertices_xy=np.array([(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]),
            z_existing_avg=110.0,
            z_proposed_avg=100.0,
            area_m2=0.5,
        )
        # 0.5 m² × 10 m delta = 5.0 m³ cut.
        assert st.signed_volume_m3 == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# ClosedSolid
# ---------------------------------------------------------------------------


class TestClosedSolid:
    """Tests for :class:`bonsai.tool.earthwork.ClosedSolid`."""

    def test_holds_points_and_faces(self) -> None:
        # Unit-cube tetrahedron: 4 vertices, 4 triangular faces.
        points = np.array(
            [
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
            ]
        )
        faces = [[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]]
        solid = tool_earthwork.ClosedSolid(points=points, faces=faces)
        assert solid.points.shape == (4, 3)
        assert len(solid.faces) == 4
        assert solid.faces[0] == [0, 1, 2]


# ---------------------------------------------------------------------------
# VolumeResult
# ---------------------------------------------------------------------------


class TestVolumeResult:
    """Tests for :class:`bonsai.tool.earthwork.VolumeResult`."""

    def test_default_construction(self) -> None:
        result = tool_earthwork.VolumeResult(
            existing_surface_guid="exist-guid",
            proposed_surface_guid="proposed-guid",
            undisturbed_cut_m3=100.0,
            compacted_fill_m3=80.0,
        )
        assert result.undisturbed_cut_m3 == pytest.approx(100.0)
        assert result.compacted_fill_m3 == pytest.approx(80.0)
        assert result.shrink_factor == pytest.approx(1.0)
        assert result.swell_factor == pytest.approx(1.0)
        assert result.cut_solid is None
        assert result.fill_solid is None
        assert result.guid is not None and len(result.guid) == 22  # IFC GlobalId

    def test_loose_cut_propagates_swell_factor(self) -> None:
        """Closes the spec audit gap: loose volume = undisturbed * swell."""
        result = tool_earthwork.VolumeResult(
            existing_surface_guid="e",
            proposed_surface_guid="p",
            undisturbed_cut_m3=100.0,
            compacted_fill_m3=0.0,
            swell_factor=1.25,
        )
        assert result.loose_cut_m3 == pytest.approx(125.0)

    def test_loose_cut_with_default_swell_equals_undisturbed(self) -> None:
        result = tool_earthwork.VolumeResult(
            existing_surface_guid="e",
            proposed_surface_guid="p",
            undisturbed_cut_m3=100.0,
            compacted_fill_m3=0.0,
        )
        assert result.loose_cut_m3 == pytest.approx(100.0)

    def test_bank_fill_propagates_shrink_factor(self) -> None:
        """compacted_fill / shrink_factor = bank-volume of fill source."""
        result = tool_earthwork.VolumeResult(
            existing_surface_guid="e",
            proposed_surface_guid="p",
            undisturbed_cut_m3=0.0,
            compacted_fill_m3=85.0,
            shrink_factor=0.85,
        )
        assert result.bank_fill_m3 == pytest.approx(100.0)

    def test_net_volume_signed_correctly(self) -> None:
        # Cut > Fill → positive net (haul-off).
        cut_heavy = tool_earthwork.VolumeResult(
            existing_surface_guid="e",
            proposed_surface_guid="p",
            undisturbed_cut_m3=120.0,
            compacted_fill_m3=80.0,
        )
        assert cut_heavy.net_volume_m3 == pytest.approx(40.0)

        # Fill > Cut → negative net (borrow needed).
        fill_heavy = tool_earthwork.VolumeResult(
            existing_surface_guid="e",
            proposed_surface_guid="p",
            undisturbed_cut_m3=80.0,
            compacted_fill_m3=120.0,
        )
        assert fill_heavy.net_volume_m3 == pytest.approx(-40.0)

        # Balanced.
        balanced = tool_earthwork.VolumeResult(
            existing_surface_guid="e",
            proposed_surface_guid="p",
            undisturbed_cut_m3=100.0,
            compacted_fill_m3=100.0,
        )
        assert balanced.net_volume_m3 == pytest.approx(0.0)

    def test_cubic_yards_conversion(self) -> None:
        """1 m³ = 1.307950619 cu yd."""
        result = tool_earthwork.VolumeResult(
            existing_surface_guid="e",
            proposed_surface_guid="p",
            undisturbed_cut_m3=1.0,
            compacted_fill_m3=1.0,
        )
        assert result.cut_cubic_yards == pytest.approx(1.30795, abs=1e-5)
        assert result.fill_cubic_yards == pytest.approx(1.30795, abs=1e-5)
        assert result.net_cubic_yards == pytest.approx(0.0)

    def test_negative_cut_volume_raises(self) -> None:
        with pytest.raises(ValueError, match="undisturbed_cut_m3 must be"):
            tool_earthwork.VolumeResult(
                existing_surface_guid="e",
                proposed_surface_guid="p",
                undisturbed_cut_m3=-1.0,
                compacted_fill_m3=0.0,
            )

    def test_negative_fill_volume_raises(self) -> None:
        with pytest.raises(ValueError, match="compacted_fill_m3 must be"):
            tool_earthwork.VolumeResult(
                existing_surface_guid="e",
                proposed_surface_guid="p",
                undisturbed_cut_m3=0.0,
                compacted_fill_m3=-1.0,
            )

    def test_zero_or_negative_shrink_factor_raises(self) -> None:
        with pytest.raises(ValueError, match="shrink_factor must be"):
            tool_earthwork.VolumeResult(
                existing_surface_guid="e",
                proposed_surface_guid="p",
                undisturbed_cut_m3=10.0,
                compacted_fill_m3=10.0,
                shrink_factor=0.0,
            )

    def test_zero_or_negative_swell_factor_raises(self) -> None:
        with pytest.raises(ValueError, match="swell_factor must be"):
            tool_earthwork.VolumeResult(
                existing_surface_guid="e",
                proposed_surface_guid="p",
                undisturbed_cut_m3=10.0,
                compacted_fill_m3=10.0,
                swell_factor=-0.5,
            )

    def test_distinct_results_have_distinct_guids(self) -> None:
        a = tool_earthwork.VolumeResult(
            existing_surface_guid="e",
            proposed_surface_guid="p",
            undisturbed_cut_m3=10.0,
            compacted_fill_m3=10.0,
        )
        b = tool_earthwork.VolumeResult(
            existing_surface_guid="e",
            proposed_surface_guid="p",
            undisturbed_cut_m3=10.0,
            compacted_fill_m3=10.0,
        )
        assert a.guid != b.guid


# ---------------------------------------------------------------------------
# Earthwork tool surface (placeholder until subsequent commits land math)
# ---------------------------------------------------------------------------


class TestEarthworkRegistryLifecycle:
    """Tests for :meth:`Earthwork.clear` and the registry shape.
    Volume math + author wrappers come in subsequent commits."""

    def test_clear_wipes_registry(self) -> None:
        tool_earthwork.Earthwork._registry[(123, "guid-a")] = "sentinel"
        assert len(tool_earthwork.Earthwork._registry) == 1
        tool_earthwork.Earthwork.clear()
        assert tool_earthwork.Earthwork._registry == {}

    def test_clear_is_idempotent_on_empty_registry(self) -> None:
        tool_earthwork.Earthwork.clear()
        tool_earthwork.Earthwork.clear()  # no error

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

"""Tests for ``bonsai.core.voxel``.

Pure-Python core tests — no Blender required. Run from ``src/bonsai``::

    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/core/test_voxel.py -o "addopts=" -v
"""

import pytest

import bonsai.core.voxel as subject
from test.core.bootstrap import ifc, surface, voxel  # noqa: F401


class FakeIfcFile(dict):
    """Minimal IFC-file stand-in (dict for Prophecy JSON serialization)."""

    def __init__(self, name: str = "TestFile") -> None:
        super().__init__(file_name=name)


class FakeCivilSurface(dict):
    """Stand-in for a registered CivilSurface."""

    def __init__(self, guid: str = "surf-guid") -> None:
        super().__init__(guid=guid)


class TestVoxelizeSurface:
    def test_raises_when_no_ifc_file_loaded(self, ifc, surface, voxel):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.voxelize_surface(
                ifc, surface, voxel, surface_guid="x", cell_size=1.0
            )

    def test_happy_path_calls_tool_methods_in_order(self, ifc, surface, voxel):
        """get → grid_from_surface → voxelize_surface, returning (grid, mask)."""
        fake_file = FakeIfcFile()
        fake_surface = FakeCivilSurface()
        fake_grid = {"grid": "g"}
        fake_mask = {"mask": "m"}

        ifc.get().should_be_called().will_return(fake_file)
        surface.get(fake_file, "surf-guid").should_be_called().will_return(fake_surface)
        voxel.grid_from_surface(
            fake_surface, 1.0, z_min=None, z_max=None
        ).should_be_called().will_return(fake_grid)
        voxel.voxelize_surface(
            fake_grid, fake_surface, supersample=1
        ).should_be_called().will_return(fake_mask)

        grid, mask = subject.voxelize_surface(
            ifc, surface, voxel, surface_guid="surf-guid", cell_size=1.0
        )
        assert grid is fake_grid
        assert mask is fake_mask

    def test_passes_z_range_and_supersample_through(self, ifc, surface, voxel):
        fake_file = FakeIfcFile()
        fake_surface = FakeCivilSurface()
        fake_grid = {"grid": "g"}
        fake_mask = {"mask": "m"}

        ifc.get().should_be_called().will_return(fake_file)
        surface.get(fake_file, "surf-guid").should_be_called().will_return(fake_surface)
        voxel.grid_from_surface(
            fake_surface, 0.5, z_min=0.0, z_max=20.0
        ).should_be_called().will_return(fake_grid)
        voxel.voxelize_surface(
            fake_grid, fake_surface, supersample=3
        ).should_be_called().will_return(fake_mask)

        subject.voxelize_surface(
            ifc,
            surface,
            voxel,
            surface_guid="surf-guid",
            cell_size=0.5,
            z_min=0.0,
            z_max=20.0,
            supersample=3,
        )


class TestComputeCutFill:
    def test_raises_when_no_ifc_file_loaded(self, ifc, surface, voxel):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.compute_cut_fill(
                ifc, surface, voxel, existing_guid="e", design_guid="d", cell_size=1.0
            )

    def test_happy_path_shared_lattice_then_difference(self, ifc, surface, voxel):
        """get×2 → shared_grid → voxelize×2 (same grid) → cut_fill."""
        fake_file = FakeIfcFile()
        existing = FakeCivilSurface(guid="existing")
        design = FakeCivilSurface(guid="design")
        grid = {"grid": "shared"}
        existing_mask = {"mask": "existing"}
        design_mask = {"mask": "design"}
        result = {"cut": 200.0, "fill": 0.0, "net": -200.0}

        ifc.get().should_be_called().will_return(fake_file)
        surface.get(fake_file, "existing").should_be_called().will_return(existing)
        surface.get(fake_file, "design").should_be_called().will_return(design)
        voxel.shared_grid(
            [existing, design], 1.0, z_min=None, z_max=None
        ).should_be_called().will_return(grid)
        voxel.voxelize_surface(
            grid, existing, supersample=1
        ).should_be_called().will_return(existing_mask)
        voxel.voxelize_surface(
            grid, design, supersample=1
        ).should_be_called().will_return(design_mask)
        voxel.cut_fill(
            existing_mask, design_mask, grid
        ).should_be_called().will_return(result)

        out_grid, out_result = subject.compute_cut_fill(
            ifc, surface, voxel, existing_guid="existing", design_guid="design", cell_size=1.0
        )
        assert out_grid is grid
        assert out_result is result


class TestAuthorCutFillSidecar:
    def test_raises_when_no_ifc_file_loaded(self, ifc, surface, voxel):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.author_cut_fill_sidecar(
                ifc, surface, voxel, existing_guid="e", design_guid="d", cell_size=1.0
            )

    def _wire_common(self, ifc, surface, voxel, result):
        """Predict the shared get→grid→voxelize→masks→cut_fill→new_sidecar chain."""
        fake_file = FakeIfcFile()
        existing = FakeCivilSurface(guid="existing")
        design = FakeCivilSurface(guid="design")
        grid = {"grid": "shared"}
        emask = {"mask": "e"}
        dmask = {"mask": "d"}
        masks = {"cut": "CUTMASK", "fill": "FILLMASK"}
        sidecar = FakeIfcFile("sidecar")

        ifc.get().should_be_called().will_return(fake_file)
        surface.get(fake_file, "existing").should_be_called().will_return(existing)
        surface.get(fake_file, "design").should_be_called().will_return(design)
        voxel.shared_grid(
            [existing, design], 1.0, z_min=None, z_max=None
        ).should_be_called().will_return(grid)
        voxel.voxelize_surface(grid, existing, supersample=1).should_be_called().will_return(emask)
        voxel.voxelize_surface(grid, design, supersample=1).should_be_called().will_return(dmask)
        voxel.cut_fill_masks(emask, dmask).should_be_called().will_return(masks)
        voxel.cut_fill(emask, dmask, grid).should_be_called().will_return(result)
        voxel.new_sidecar().should_be_called().will_return(sidecar)
        return grid, masks, sidecar

    def test_cut_only_authors_one_element(self, ifc, surface, voxel):
        result = {"cut": 200.0, "fill": 0.0, "net": -200.0}
        grid, masks, sidecar = self._wire_common(ifc, surface, voxel, result)
        voxel.author_earthwork(
            sidecar, grid, "CUTMASK", host_class="IfcEarthworksCut",
            predefined_type="EXCAVATION", name="Voxel Cut", bank_volume=200.0,
            source_surface_guid="existing", swell_factor=1.0,
        ).should_be_called()
        # fill branch must NOT be called (fill == 0)

        out_file, out_result = subject.author_cut_fill_sidecar(
            ifc, surface, voxel, existing_guid="existing", design_guid="design", cell_size=1.0
        )
        assert out_file is sidecar
        assert out_result is result

    def test_cut_and_fill_author_both(self, ifc, surface, voxel):
        result = {"cut": 50.0, "fill": 30.0, "net": -20.0}
        grid, masks, sidecar = self._wire_common(ifc, surface, voxel, result)
        voxel.author_earthwork(
            sidecar, grid, "CUTMASK", host_class="IfcEarthworksCut",
            predefined_type="EXCAVATION", name="Voxel Cut", bank_volume=50.0,
            source_surface_guid="existing", swell_factor=1.0,
        ).should_be_called()
        voxel.author_earthwork(
            sidecar, grid, "FILLMASK", host_class="IfcEarthworksFill",
            predefined_type="EMBANKMENT", name="Voxel Fill", bank_volume=30.0,
            source_surface_guid="design", swell_factor=1.0,
        ).should_be_called()

        subject.author_cut_fill_sidecar(
            ifc, surface, voxel, existing_guid="existing", design_guid="design", cell_size=1.0
        )


class TestGeomodel:
    def test_raises_when_no_ifc_file_loaded(self, ifc, surface, voxel):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.compute_geomodel(ifc, surface, voxel, surface_guids=["a", "b"], cell_size=1.0)

    def test_raises_with_fewer_than_two_surfaces(self, ifc, surface, voxel):
        ifc.get().should_be_called().will_return(FakeIfcFile())
        with pytest.raises(ValueError, match="at least 2 boundary"):
            subject.compute_geomodel(ifc, surface, voxel, surface_guids=["only"], cell_size=1.0)

    def _wire(self, ifc, surface, voxel):
        fake_file = FakeIfcFile()
        sA = FakeCivilSurface(guid="gA")
        sB = FakeCivilSurface(guid="gB")
        ordered = [sB, sA]
        legend = {1: "Clay"}
        grid = {"grid": "g"}
        code = {"code": "c"}
        volumes = {1: 100.0}

        ifc.get().should_be_called().will_return(fake_file)
        surface.get(fake_file, "gA").should_be_called().will_return(sA)
        surface.get(fake_file, "gB").should_be_called().will_return(sB)
        voxel.order_surfaces_by_elevation([sA, sB]).should_be_called().will_return(ordered)
        voxel.strata_legend(ordered).should_be_called().will_return(legend)
        voxel.shared_grid(ordered, 1.0, z_min=None, z_max=None).should_be_called().will_return(grid)
        voxel.voxelize_strata(grid, ordered, supersample=1).should_be_called().will_return(code)
        voxel.stratum_volumes(grid, code).should_be_called().will_return(volumes)
        return grid, code, volumes, legend

    def test_compute_geomodel(self, ifc, surface, voxel):
        grid, code, volumes, legend = self._wire(ifc, surface, voxel)
        out = subject.compute_geomodel(
            ifc, surface, voxel, surface_guids=["gA", "gB"], cell_size=1.0
        )
        assert out == (grid, code, volumes, legend)

    def test_preview_geomodel_builds_mesh(self, ifc, surface, voxel):
        grid, code, volumes, legend = self._wire(ifc, surface, voxel)
        voxel.create_strata_preview(grid, code, legend).should_be_called()
        out = subject.preview_geomodel(
            ifc, surface, voxel, surface_guids=["gA", "gB"], cell_size=1.0
        )
        assert out == {"volumes": volumes, "legend": legend}

    def test_author_geomodel_sidecar(self, ifc, surface, voxel):
        grid, code, volumes, legend = self._wire(ifc, surface, voxel)
        sidecar = FakeIfcFile("sidecar")
        voxel.new_sidecar().should_be_called().will_return(sidecar)
        voxel.author_geomodel(
            sidecar, grid, code, legend, name="Voxel Geomodel",
            source_surface_guids=["gA", "gB"],
        ).should_be_called()
        out_file, out_volumes, out_legend = subject.author_geomodel_sidecar(
            ifc, surface, voxel, surface_guids=["gA", "gB"], cell_size=1.0
        )
        assert out_file is sidecar
        assert out_volumes == volumes
        assert out_legend == legend


class TestCutFillByStratum:
    def test_raises_when_no_ifc_file_loaded(self, ifc, surface, voxel):
        ifc.get().should_be_called().will_return(None)
        with pytest.raises(ValueError, match="No IFC file loaded"):
            subject.compute_cut_fill_by_stratum(
                ifc, surface, voxel, existing_guid="E", design_guid="D",
                stratum_guids=["gA", "gB"], cell_size=1.0,
            )

    def _wire(self, ifc, surface, voxel):
        fake_file = FakeIfcFile()
        existing = FakeCivilSurface(guid="E")
        design = FakeCivilSurface(guid="D")
        sA = FakeCivilSurface(guid="gA")
        sB = FakeCivilSurface(guid="gB")
        ordered = [sB, sA]
        legend = {1: "Clay", 2: "Sand"}
        grid = {"grid": "g"}
        emask = {"m": "e"}
        dmask = {"m": "d"}
        masks = {"cut": "CUTM", "fill": "FILLM"}
        code = {"code": "c"}
        totals = {"cut": 100.0, "fill": 0.0, "net": -100.0}
        by_stratum = {1: 60.0, 2: 40.0}

        ifc.get().should_be_called().will_return(fake_file)
        surface.get(fake_file, "E").should_be_called().will_return(existing)
        surface.get(fake_file, "D").should_be_called().will_return(design)
        surface.get(fake_file, "gA").should_be_called().will_return(sA)
        surface.get(fake_file, "gB").should_be_called().will_return(sB)
        voxel.order_surfaces_by_elevation([sA, sB]).should_be_called().will_return(ordered)
        voxel.strata_legend(ordered).should_be_called().will_return(legend)
        voxel.shared_grid(
            [existing, design, sB, sA], 1.0, z_min=None, z_max=None
        ).should_be_called().will_return(grid)
        voxel.voxelize_surface(grid, existing, supersample=1).should_be_called().will_return(emask)
        voxel.voxelize_surface(grid, design, supersample=1).should_be_called().will_return(dmask)
        voxel.cut_fill_masks(emask, dmask).should_be_called().will_return(masks)
        voxel.voxelize_strata(grid, ordered, supersample=1).should_be_called().will_return(code)
        voxel.cut_fill(emask, dmask, grid).should_be_called().will_return(totals)
        voxel.cut_fill_by_stratum("CUTM", code, grid).should_be_called().will_return(by_stratum)
        return grid, code, masks, totals, by_stratum, legend

    def test_compute(self, ifc, surface, voxel):
        grid, code, masks, totals, by_stratum, legend = self._wire(ifc, surface, voxel)
        out = subject.compute_cut_fill_by_stratum(
            ifc, surface, voxel, existing_guid="E", design_guid="D",
            stratum_guids=["gA", "gB"], cell_size=1.0,
        )
        assert out == (grid, totals, by_stratum, legend)

    def test_preview(self, ifc, surface, voxel):
        grid, code, masks, totals, by_stratum, legend = self._wire(ifc, surface, voxel)
        cut_codes = {"cc": "x"}
        voxel.intersect_codes(code, "CUTM").should_be_called().will_return(cut_codes)
        voxel.create_strata_preview(grid, cut_codes, legend).should_be_called()
        out = subject.preview_cut_fill_by_stratum(
            ifc, surface, voxel, existing_guid="E", design_guid="D",
            stratum_guids=["gA", "gB"], cell_size=1.0,
        )
        assert out == {"totals": totals, "cut_by_stratum": by_stratum, "legend": legend}

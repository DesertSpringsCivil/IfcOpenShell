# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2026 Michael Yoder <myoder@desertspringscivil.com>
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

"""Tests for ``ifcopenshell.api.voxel``.

Pure pytest — no Blender, no bpy — but requires the compiled IfcOpenShell
wrapper + express parser to register the prototype ``IFC4X4_TM27`` schema (e.g.
Blender's bundled ifcopenshell). The schema is parsed/registered once per
session (the EXPRESS parse is slow). Round-trip discipline: "creates an entity"
tests write the file to disk, reopen, and assert the structure survives.
"""

import ifcopenshell
import ifcopenshell.api.voxel as voxel
import ifcopenshell.guid
import pytest

# A 2x2x1 occupancy mask [1,0,1,1] -> RLE count-first run-pairs (the Phase-0
# spike stream). value 1 = occupied, 0 = empty.
SPIKE_OCCUPANCY = [1, 1, 1, 0, 2, 1]


@pytest.fixture(scope="session", autouse=True)
def _register_schema():
    """Register IFC4X4_TM27 once for the whole session (slow EXPRESS parse).

    The prototype schema is built from a base IFC4x3 ``.exp`` + the TM27 delta;
    if no base is configured (``SAIKEI_IFC4X3_BASE_EXP`` or a sibling
    ``IFC4.x-development`` checkout), the suite skips rather than fails — TM27
    targets an unreleased schema, so a base must be supplied to run these.
    """
    try:
        voxel.ensure_registered()
    except RuntimeError as exc:
        pytest.skip(f"IFC4X4_TM27 base schema unavailable — {exc}")


@pytest.fixture
def sidecar() -> ifcopenshell.file:
    return voxel.new_file()


def _roundtrip(file: ifcopenshell.file, tmp_path) -> ifcopenshell.file:
    path = str(tmp_path / "voxel.ifc")
    file.write(path)
    return ifcopenshell.open(path)


def _make_host(file: ifcopenshell.file, name: str = "Cut") -> ifcopenshell.entity_instance:
    return file.create_entity(
        "IfcEarthworksCut",
        GlobalId=ifcopenshell.guid.new(),
        Name=name,
        PredefinedType="EXCAVATION",
    )


# --------------------------------------------------------------------------- #
# Schema / bootstrap
# --------------------------------------------------------------------------- #


def test_package_importable():
    assert voxel.__doc__ is not None
    assert "voxel" in voxel.__doc__.lower()


def test_ensure_registered_is_idempotent():
    assert voxel.ensure_registered() == "IFC4X4_TM27"
    assert voxel.ensure_registered() == "IFC4X4_TM27"  # second call no-op


def test_new_file_bootstrap(sidecar):
    assert sidecar.schema == "IFC4X4"  # major identifier of IFC4X4_TM27
    project = sidecar.by_type("IfcProject")[0]
    assert project.UnitsInContext is not None
    assert sidecar.by_type("IfcSite")
    assert any(
        c.is_a() == "IfcGeometricRepresentationContext" and c.ContextType == "Model"
        for c in sidecar.by_type("IfcGeometricRepresentationContext")
    )


# --------------------------------------------------------------------------- #
# add_voxel_grid_representation
# --------------------------------------------------------------------------- #


class TestAddVoxelGrid:
    def test_roundtrip(self, sidecar, tmp_path):
        host = _make_host(sidecar)
        voxel.add_voxel_grid_representation(
            sidecar, host, voxel_sizes=(1.0, 1.0, 2.0), voxel_counts=(2, 2, 1),
            occupancy=SPIKE_OCCUPANCY,
        )
        reopened = _roundtrip(sidecar, tmp_path)
        grid = reopened.by_type("IfcVoxelGrid")[0]
        assert (grid.VoxelSizeX, grid.VoxelSizeY, grid.VoxelSizeZ) == (1.0, 1.0, 2.0)
        assert (grid.NumberOfVoxelsX, grid.NumberOfVoxelsY, grid.NumberOfVoxelsZ) == (2, 2, 1)
        assert list(grid.Voxels) == SPIKE_OCCUPANCY

    def test_attached_as_body_tessellation(self, sidecar):
        host = _make_host(sidecar)
        voxel.add_voxel_grid_representation(
            sidecar, host, voxel_sizes=(1, 1, 1), voxel_counts=(2, 2, 1),
            occupancy=SPIKE_OCCUPANCY,
        )
        rep = host.Representation.Representations[0]
        assert rep.RepresentationIdentifier == "Body"
        assert rep.RepresentationType == "Tessellation"
        assert rep.Items[0].is_a("IfcVoxelGrid")

    def test_rejects_odd_occupancy(self, sidecar):
        host = _make_host(sidecar)
        with pytest.raises(ValueError, match="even length"):
            voxel.add_voxel_grid_representation(
                sidecar, host, voxel_sizes=(1, 1, 1), voxel_counts=(2, 2, 1),
                occupancy=[1, 1, 1],
            )

    def test_rejects_nonpositive_size(self, sidecar):
        host = _make_host(sidecar)
        with pytest.raises(ValueError, match="sizes must be"):
            voxel.add_voxel_grid_representation(
                sidecar, host, voxel_sizes=(1, 0, 1), voxel_counts=(2, 2, 1),
                occupancy=SPIKE_OCCUPANCY,
            )

    def test_rejects_duplicate_body(self, sidecar):
        host = _make_host(sidecar)
        kw = dict(voxel_sizes=(1, 1, 1), voxel_counts=(2, 2, 1), occupancy=SPIKE_OCCUPANCY)
        voxel.add_voxel_grid_representation(sidecar, host, **kw)
        with pytest.raises(ValueError, match="already has a Body"):
            voxel.add_voxel_grid_representation(sidecar, host, **kw)


# --------------------------------------------------------------------------- #
# add_voxel_data
# --------------------------------------------------------------------------- #


class TestAddVoxelData:
    def _host_with_grid(self, file):
        host = _make_host(file)
        voxel.add_voxel_grid_representation(
            file, host, voxel_sizes=(1, 1, 1), voxel_counts=(2, 2, 1),
            occupancy=SPIKE_OCCUPANCY,
        )
        return host

    def test_label_layer_roundtrip(self, sidecar, tmp_path):
        host = self._host_with_grid(sidecar)
        voxel.add_voxel_data(
            sidecar, host, value_data=["sand", "clay", "sand"], data_type="label",
            value_type="IfcLabel", name="Material",
        )
        reopened = _roundtrip(sidecar, tmp_path)
        mat = reopened.by_type("IfcLabelVoxelData")[0]
        assert list(mat.ValueData) == ["sand", "clay", "sand"]
        assert mat.Name == "Material"

    def test_real_layer_with_unit_roundtrip(self, sidecar, tmp_path):
        host = self._host_with_grid(sidecar)
        unit = sidecar.create_entity("IfcSIUnit", UnitType="MASSUNIT", Name="GRAM")
        voxel.add_voxel_data(
            sidecar, host, value_data=[0.9, 0.7, 0.95], data_type="real",
            value_type="IfcReal", unit=unit, name="Confidence",
        )
        reopened = _roundtrip(sidecar, tmp_path)
        conf = reopened.by_type("IfcRealVoxelData")[0]
        assert list(conf.ValueData) == [0.9, 0.7, 0.95]
        assert conf.Unit is not None

    def test_assigned_to_host(self, sidecar):
        host = self._host_with_grid(sidecar)
        layer = voxel.add_voxel_data(
            sidecar, host, value_data=[1, 2, 3], data_type="integer",
        )
        rels = [r for r in sidecar.by_type("IfcRelAssignsToProduct") if layer in (r.RelatedObjects or [])]
        assert len(rels) == 1
        assert rels[0].RelatingProduct == host
        # SameRepresentation: layer shares the host's product shape.
        assert layer.Representation == host.Representation

    def test_rejects_unknown_type(self, sidecar):
        host = self._host_with_grid(sidecar)
        with pytest.raises(ValueError, match="data_type must be"):
            voxel.add_voxel_data(sidecar, host, value_data=[1], data_type="bogus")

    def test_rejects_unit_on_label(self, sidecar):
        host = self._host_with_grid(sidecar)
        unit = sidecar.create_entity("IfcSIUnit", UnitType="MASSUNIT", Name="GRAM")
        with pytest.raises(ValueError, match="does not carry a Unit"):
            voxel.add_voxel_data(
                sidecar, host, value_data=["a"], data_type="label", unit=unit
            )

    def test_requires_grid_first(self, sidecar):
        host = _make_host(sidecar)  # no grid authored
        with pytest.raises(ValueError, match="voxel grid"):
            voxel.add_voxel_data(sidecar, host, value_data=[1], data_type="integer")


# --------------------------------------------------------------------------- #
# create_voxel_earthwork (top-level)
# --------------------------------------------------------------------------- #


class TestCreateVoxelEarthwork:
    def test_cut_roundtrip(self, sidecar, tmp_path):
        host, grid = voxel.create_voxel_earthwork(
            sidecar, name="Pad excavation", voxel_sizes=(1, 1, 1),
            voxel_counts=(2, 2, 1), occupancy=SPIKE_OCCUPANCY,
            source_surface_guid="0Source0Surface0Guid00",
        )
        assert host.is_a("IfcEarthworksCut")
        reopened = _roundtrip(sidecar, tmp_path)
        cut = reopened.by_type("IfcEarthworksCut")[0]
        assert list(reopened.by_type("IfcVoxelGrid")[0].Voxels) == SPIKE_OCCUPANCY
        # contained in site
        assert reopened.by_type("IfcRelContainedInSpatialStructure")
        # source-surface cross-file link persisted on Description
        assert cut.Description == "voxelized-from:0Source0Surface0Guid00"

    def test_fill_host(self, sidecar):
        host, _ = voxel.create_voxel_earthwork(
            sidecar, name="Embankment", voxel_sizes=(1, 1, 1), voxel_counts=(2, 2, 1),
            occupancy=SPIKE_OCCUPANCY, host_class="IfcEarthworksFill",
            predefined_type="EMBANKMENT",
        )
        assert host.is_a("IfcEarthworksFill")
        assert host.PredefinedType == "EMBANKMENT"

    def test_rejects_bad_host_class(self, sidecar):
        with pytest.raises(ValueError, match="host_class must be"):
            voxel.create_voxel_earthwork(
                sidecar, name="x", voxel_sizes=(1, 1, 1), voxel_counts=(2, 2, 1),
                occupancy=SPIKE_OCCUPANCY, host_class="IfcWall",
            )

    def test_full_stack_with_layers_roundtrips(self, sidecar, tmp_path):
        """Grid + material + confidence, the full TM27 multi-layer shape."""
        host, _ = voxel.create_voxel_earthwork(
            sidecar, name="Geomodel cell", voxel_sizes=(1, 1, 1),
            voxel_counts=(2, 2, 1), occupancy=SPIKE_OCCUPANCY,
        )
        voxel.add_voxel_data(
            sidecar, host, value_data=["sand", "clay", "sand"], data_type="label",
            value_type="IfcLabel", name="Material",
        )
        voxel.add_voxel_data(
            sidecar, host, value_data=[0.9, 0.7, 0.95], data_type="real",
            value_type="IfcReal", name="Confidence",
        )
        reopened = _roundtrip(sidecar, tmp_path)
        assert len(reopened.by_type("IfcVoxelGrid")) == 1
        assert len(reopened.by_type("IfcLabelVoxelData")) == 1
        assert len(reopened.by_type("IfcRealVoxelData")) == 1
        # Both layers reference the one grid representation.
        grid_rep = reopened.by_type("IfcEarthworksCut")[0].Representation
        for layer in reopened.by_type("IfcLabelVoxelData") + reopened.by_type("IfcRealVoxelData"):
            assert layer.Representation == grid_rep


# --------------------------------------------------------------------------- #
# write_earthwork_quantities (Phase 4 QTO)
# --------------------------------------------------------------------------- #


def _read_quantities(product, qto_name):
    for rel in product.IsDefinedBy or []:
        if not rel.is_a("IfcRelDefinesByProperties"):
            continue
        q = rel.RelatingPropertyDefinition
        if q is not None and q.is_a("IfcElementQuantity") and q.Name == qto_name:
            return {x.Name: x[3] for x in q.Quantities or []}  # [3] = the *Value attr
    return {}


class TestWriteQuantities:
    def test_cut_quantities_roundtrip(self, sidecar, tmp_path):
        host, _ = voxel.create_voxel_earthwork(
            sidecar, name="Cut", voxel_sizes=(1, 1, 1), voxel_counts=(2, 2, 1),
            occupancy=SPIKE_OCCUPANCY,
        )
        voxel.write_earthwork_quantities(sidecar, host, bank_volume=200.0, loose_volume=250.0)
        reopened = _roundtrip(sidecar, tmp_path)
        cut = reopened.by_type("IfcEarthworksCut")[0]
        q = _read_quantities(cut, "Qto_EarthworksCutBaseQuantities")
        assert q["UndisturbedVolume"] == 200.0
        assert q["LooseVolume"] == 250.0

    def test_fill_quantities_roundtrip(self, sidecar, tmp_path):
        host, _ = voxel.create_voxel_earthwork(
            sidecar, name="Fill", voxel_sizes=(1, 1, 1), voxel_counts=(2, 2, 1),
            occupancy=SPIKE_OCCUPANCY, host_class="IfcEarthworksFill",
            predefined_type="EMBANKMENT",
        )
        voxel.write_earthwork_quantities(sidecar, host, bank_volume=180.0, loose_volume=200.0)
        reopened = _roundtrip(sidecar, tmp_path)
        fill = reopened.by_type("IfcEarthworksFill")[0]
        q = _read_quantities(fill, "Qto_EarthworksFillBaseQuantities")
        assert q["CompactedVolume"] == 180.0
        assert q["LooseVolume"] == 200.0

    def test_rejects_non_earthwork_host(self, sidecar):
        site = sidecar.by_type("IfcSite")[0]
        with pytest.raises(ValueError, match="EarthworksCut or IfcEarthworksFill"):
            voxel.write_earthwork_quantities(sidecar, site, bank_volume=1.0)


# --------------------------------------------------------------------------- #
# create_voxel_geomodel (stratum host)
# --------------------------------------------------------------------------- #


class TestCreateVoxelGeomodel:
    def test_geomodel_roundtrip(self, sidecar, tmp_path):
        host = voxel.create_voxel_geomodel(
            sidecar, name="Geomodel", voxel_sizes=(1, 1, 1), voxel_counts=(2, 2, 1),
            occupancy=SPIKE_OCCUPANCY,
            source_surface_guids=["0Surf0A", "0Surf0B"],
            legend={1: "Clay", 2: "Sand"},
        )
        assert host.is_a("IfcGeomodel")
        # Stratum code layer (gathered over occupied cells), RLE integer.
        voxel.add_voxel_data(
            sidecar, host, value_data=[3, 1, 3, 2], data_type="integer",
            value_type="IfcInteger", name="StratumCode",
        )
        reopened = _roundtrip(sidecar, tmp_path)
        geo = reopened.by_type("IfcGeomodel")[0]
        assert list(reopened.by_type("IfcVoxelGrid")[0].Voxels) == SPIKE_OCCUPANCY
        assert list(reopened.by_type("IfcIntegerVoxelData")[0].ValueData) == [3, 1, 3, 2]
        assert "strata:1=Clay;2=Sand" in (geo.Description or "")
        assert "voxelized-from:0Surf0A,0Surf0B" in (geo.Description or "")

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

import ifcopenshell
import ifcopenshell.api.unit
import ifcopenshell.guid
import numpy as np
import pytest

import bonsai.tool.earthwork as tool_earthwork
import bonsai.tool.surface as tool_surface


def _make_ifc_file_with_site() -> ifcopenshell.file:
    """Build a minimal IFC4X3 file with project + site + units, ready
    for earthwork authoring tests. Mirrors the helper in
    test_surface.py / test_grading.py."""
    ifc_file = ifcopenshell.file(schema="IFC4X3_ADD2")
    project = ifc_file.create_entity(
        "IfcProject", GlobalId=ifcopenshell.guid.new(), Name="Test Project"
    )
    length = ifcopenshell.api.unit.add_si_unit(ifc_file, unit_type="LENGTHUNIT")
    ifcopenshell.api.unit.assign_unit(ifc_file, units=[length])
    site = ifc_file.create_entity(
        "IfcSite", GlobalId=ifcopenshell.guid.new(), Name="Test Site"
    )
    ifc_file.create_entity(
        "IfcRelAggregates",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=project,
        RelatedObjects=[site],
    )
    return ifc_file


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


# ---------------------------------------------------------------------------
# TIN-to-TIN prismoidal volume — spec §6.4
# ---------------------------------------------------------------------------


def _flat_square_surface(
    name: str, z: float, half_extent: float = 5.0
) -> tool_surface.CivilSurface:
    """Helper: a flat 10×10 (or ``2*half_extent``) square TIN at the
    given Z. Two triangles, four corner points."""
    points = np.array(
        [
            (-half_extent, -half_extent, z),
            (half_extent, -half_extent, z),
            (half_extent, half_extent, z),
            (-half_extent, half_extent, z),
        ]
    )
    return tool_surface.Surface.build_tin_from_points(name, points)


class TestComputeVolumesFlatPair:
    """Sanity tests against analytically-known volumes."""

    def test_flat_existing_above_flat_proposed_is_pure_cut(self) -> None:
        """Existing at z=110, proposed at z=100, 10×10 m square →
        pure cut of 10 × 10 × 10 = 1000 m³."""
        existing = _flat_square_surface("eg", 110.0)
        proposed = _flat_square_surface("pr", 100.0)
        result = tool_earthwork.Earthwork.compute_volumes(
            existing, proposed
        )
        assert result.undisturbed_cut_m3 == pytest.approx(1000.0, rel=1e-9)
        assert result.compacted_fill_m3 == pytest.approx(0.0, abs=1e-9)
        assert result.net_volume_m3 == pytest.approx(1000.0, rel=1e-9)

    def test_flat_existing_below_flat_proposed_is_pure_fill(self) -> None:
        """Existing at z=95, proposed at z=100, 10×10 m square →
        pure fill of 10 × 10 × 5 = 500 m³."""
        existing = _flat_square_surface("eg", 95.0)
        proposed = _flat_square_surface("pr", 100.0)
        result = tool_earthwork.Earthwork.compute_volumes(
            existing, proposed
        )
        assert result.undisturbed_cut_m3 == pytest.approx(0.0, abs=1e-9)
        assert result.compacted_fill_m3 == pytest.approx(500.0, rel=1e-9)
        assert result.net_volume_m3 == pytest.approx(-500.0, rel=1e-9)

    def test_at_grade_pair_is_zero(self) -> None:
        """Identical Z surfaces → no cut, no fill."""
        existing = _flat_square_surface("eg", 100.0)
        proposed = _flat_square_surface("pr", 100.0)
        result = tool_earthwork.Earthwork.compute_volumes(
            existing, proposed
        )
        assert result.undisturbed_cut_m3 == pytest.approx(0.0, abs=1e-9)
        assert result.compacted_fill_m3 == pytest.approx(0.0, abs=1e-9)


class TestComputeVolumesMixedCutFill:
    """When a sloped proposed crosses a flat existing, both cut and
    fill accumulate. Check the integral analytically."""

    def test_sloped_proposed_over_flat_existing(self) -> None:
        """Existing flat at z=100, proposed sloped z=100+2x. Cut and
        fill by symmetry are equal magnitudes; the net is zero by
        construction.

        On a coarse 4-corner Delaunay triangulation each surface
        produces 2 triangles split along the antidiagonal. Each
        intersection sub-triangle's centroid sits well off x=0 (the
        true cut/fill boundary), so the per-piece prismoidal rule
        gives ±500/3 ≈ 166.67 m³ on each side rather than the
        finer-resolution analytical ±250. This is the known
        triangle-straddle limitation of the spec §6.4 algorithm; the
        spec §6.5 region-extraction step (Phase 6 commit 4) refines
        accuracy by subdividing at zero-delta contours. For now the
        test asserts the per-piece result and the symmetry property
        (cut == fill, net ≈ 0) — those are the algorithm's
        load-bearing invariants regardless of triangulation density.
        """
        existing = _flat_square_surface("eg", 100.0)
        proposed_points = np.array(
            [
                (-5.0, -5.0, 90.0),
                (5.0, -5.0, 110.0),
                (5.0, 5.0, 110.0),
                (-5.0, 5.0, 90.0),
            ]
        )
        proposed = tool_surface.Surface.build_tin_from_points(
            "pr_sloped", proposed_points
        )
        result = tool_earthwork.Earthwork.compute_volumes(
            existing, proposed
        )
        # Per-piece prismoidal output: 500/3 each side.
        assert result.undisturbed_cut_m3 == pytest.approx(500.0 / 3.0, rel=1e-6)
        assert result.compacted_fill_m3 == pytest.approx(500.0 / 3.0, rel=1e-6)
        # Symmetry — cut and fill are equal magnitudes.
        assert result.undisturbed_cut_m3 == pytest.approx(
            result.compacted_fill_m3, rel=1e-9
        )
        # Net = 0 by symmetry.
        assert result.net_volume_m3 == pytest.approx(0.0, abs=1e-6)


class TestComputeVolumesShrinkSwell:
    """Shrink/swell factors must propagate through to the result."""

    def test_swell_factor_propagates_to_loose_cut(self) -> None:
        """100 m³ cut × swell 1.25 → 125 m³ loose."""
        existing = _flat_square_surface("eg", 110.0)
        proposed = _flat_square_surface("pr", 100.0)
        result = tool_earthwork.Earthwork.compute_volumes(
            existing, proposed, swell_factor=1.25
        )
        assert result.undisturbed_cut_m3 == pytest.approx(1000.0, rel=1e-9)
        assert result.loose_cut_m3 == pytest.approx(1250.0, rel=1e-9)


class TestComputeVolumesPerTriangleDeltas:
    """Optional cut/fill color-map output."""

    def test_per_triangle_deltas_is_none_by_default(self) -> None:
        existing = _flat_square_surface("eg", 110.0)
        proposed = _flat_square_surface("pr", 100.0)
        result = tool_earthwork.Earthwork.compute_volumes(
            existing, proposed
        )
        assert result.per_triangle_deltas is None

    def test_per_triangle_deltas_populated_when_requested(self) -> None:
        existing = _flat_square_surface("eg", 110.0)
        proposed = _flat_square_surface("pr", 100.0)
        result = tool_earthwork.Earthwork.compute_volumes(
            existing, proposed, capture_per_triangle_deltas=True
        )
        assert result.per_triangle_deltas is not None
        assert len(result.per_triangle_deltas) > 0
        # All deltas should be +10 (existing 110 - proposed 100).
        assert np.allclose(result.per_triangle_deltas, 10.0)


class TestComputeVolumesDomainFallback:
    """Convex-hull fallback when outer_boundary is missing."""

    def test_convex_hull_fallback_when_outer_boundary_unset(self) -> None:
        """A surface with no outer_boundary should still volume-
        integrate. _surface_xy_domain falls back to convex hull when
        outer_boundary is None — exercise that path directly by
        forcing it on a surface."""
        existing = _flat_square_surface("eg", 110.0)
        proposed = _flat_square_surface("pr", 100.0)
        # build_tin_from_points populates outer_boundary; clear it
        # to exercise the convex-hull fallback path.
        existing.outer_boundary = None
        proposed.outer_boundary = None
        result = tool_earthwork.Earthwork.compute_volumes(
            existing, proposed
        )
        assert result.undisturbed_cut_m3 == pytest.approx(1000.0, rel=1e-9)


class TestComputeVolumesBuildSolids:
    """Optional prism-soup solid construction (spec §6.5 MVP)."""

    def test_solids_are_none_by_default(self) -> None:
        existing = _flat_square_surface("eg", 110.0)
        proposed = _flat_square_surface("pr", 100.0)
        result = tool_earthwork.Earthwork.compute_volumes(
            existing, proposed
        )
        assert result.cut_solid is None
        assert result.fill_solid is None

    def test_cut_solid_populated_for_cut_pair(self) -> None:
        existing = _flat_square_surface("eg", 110.0)
        proposed = _flat_square_surface("pr", 100.0)
        result = tool_earthwork.Earthwork.compute_volumes(
            existing, proposed, build_solids=True
        )
        assert result.cut_solid is not None
        # Two existing triangles × two proposed triangles → at most
        # 2 sub-triangles for this aligned pair (each existing tri ∩
        # corresponding proposed tri = the same triangle).
        # Each sub-triangle becomes a 6-vertex / 5-face prism.
        assert result.cut_solid.points.shape[1] == 3
        assert result.cut_solid.points.shape[0] >= 6
        assert len(result.cut_solid.faces) >= 5
        # Vertex count is 6 × number of prisms.
        n_prisms = len(result.cut_solid.faces) // 5
        assert result.cut_solid.points.shape[0] == 6 * n_prisms
        # No fill volume → fill_solid is None.
        assert result.fill_solid is None

    def test_fill_solid_populated_for_fill_pair(self) -> None:
        existing = _flat_square_surface("eg", 95.0)
        proposed = _flat_square_surface("pr", 100.0)
        result = tool_earthwork.Earthwork.compute_volumes(
            existing, proposed, build_solids=True
        )
        assert result.fill_solid is not None
        assert result.cut_solid is None

    def test_prism_height_matches_delta(self) -> None:
        """For a pure-cut pair, every prism's existing-Z minus
        proposed-Z equals the delta. Sample one prism."""
        existing = _flat_square_surface("eg", 110.0)
        proposed = _flat_square_surface("pr", 100.0)
        result = tool_earthwork.Earthwork.compute_volumes(
            existing, proposed, build_solids=True
        )
        assert result.cut_solid is not None
        # First 3 vertices: proposed-Z (z=100). Next 3: existing-Z (z=110).
        first_prism = result.cut_solid.points[:6]
        z_proposed = first_prism[:3, 2]
        z_existing = first_prism[3:, 2]
        assert np.allclose(z_proposed, 100.0)
        assert np.allclose(z_existing, 110.0)


class TestComputeVolumesNonOverlapping:
    """Two surfaces that don't overlap in XY produce zero volume."""

    def test_disjoint_domains_yield_zero_volumes(self) -> None:
        existing = _flat_square_surface("eg", 110.0, half_extent=5.0)
        # Proposed is well clear of existing in XY.
        proposed_points = np.array(
            [
                (100.0, 100.0, 100.0),
                (110.0, 100.0, 100.0),
                (110.0, 110.0, 100.0),
                (100.0, 110.0, 100.0),
            ]
        )
        proposed = tool_surface.Surface.build_tin_from_points(
            "pr_far", proposed_points
        )
        result = tool_earthwork.Earthwork.compute_volumes(
            existing, proposed
        )
        assert result.undisturbed_cut_m3 == pytest.approx(0.0, abs=1e-9)
        assert result.compacted_fill_m3 == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# IFC author wrappers (Phase 6 commit 5)
# ---------------------------------------------------------------------------


class TestAuthorVolumeResult:
    """Tests for :meth:`Earthwork.author_volume_result`."""

    @staticmethod
    def _setup(z_existing: float, z_proposed: float):
        """Build an IFC file with a real terrain entity, a flat
        existing surface authored as IfcGeographicElement[TERRAIN],
        and a flat proposed surface (in-memory dataclass only).
        Returns (ifc_file, terrain_entity, existing_surface,
        proposed_surface)."""
        ifc_file = _make_ifc_file_with_site()
        existing = _flat_square_surface("eg", z_existing)
        proposed = _flat_square_surface("pr", z_proposed)
        terrain = tool_surface.Surface.author_ifc_host(ifc_file, existing)
        return ifc_file, terrain, existing, proposed

    def test_authors_cut_for_pure_cut(self) -> None:
        ifc_file, terrain, existing, proposed = self._setup(110.0, 100.0)
        result = tool_earthwork.Earthwork.compute_volumes(
            existing, proposed, build_solids=True
        )
        tool_earthwork.Earthwork.author_volume_result(
            ifc_file, result, terrain=terrain
        )
        cuts = ifc_file.by_type("IfcEarthworksCut")
        assert len(cuts) == 1
        assert result.ifc_cut_id == cuts[0].id()
        assert result.ifc_fill_id is None  # pure cut

    def test_authors_fill_for_pure_fill(self) -> None:
        ifc_file, terrain, existing, proposed = self._setup(95.0, 100.0)
        result = tool_earthwork.Earthwork.compute_volumes(
            existing, proposed, build_solids=True
        )
        tool_earthwork.Earthwork.author_volume_result(
            ifc_file, result, terrain=terrain
        )
        fills = ifc_file.by_type("IfcEarthworksFill")
        assert len(fills) == 1
        assert result.ifc_fill_id == fills[0].id()
        assert result.ifc_cut_id is None  # pure fill

    def test_void_terrain_relationship_authored(self) -> None:
        ifc_file, terrain, existing, proposed = self._setup(110.0, 100.0)
        result = tool_earthwork.Earthwork.compute_volumes(
            existing, proposed, build_solids=True
        )
        tool_earthwork.Earthwork.author_volume_result(
            ifc_file, result, terrain=terrain
        )
        rels = ifc_file.by_type("IfcRelVoidsElement")
        assert len(rels) == 1
        assert rels[0].RelatingBuildingElement.id() == terrain.id()
        assert rels[0].RelatedOpeningElement.id() == result.ifc_cut_id

    def test_qto_carries_undisturbed_and_loose_volumes(self) -> None:
        """Pin the audit fix: LooseVolume = UndisturbedVolume × SwellFactor.
        Authoring 100 m³ cut with swell 1.25 must write 125 m³ loose."""
        ifc_file, terrain, existing, proposed = self._setup(110.0, 100.0)
        result = tool_earthwork.Earthwork.compute_volumes(
            existing, proposed, build_solids=True, swell_factor=1.25
        )
        tool_earthwork.Earthwork.author_volume_result(
            ifc_file, result, terrain=terrain
        )
        cut = ifc_file.by_id(result.ifc_cut_id)
        # Find the cut's Qto and read the volume values back.
        qto = next(
            rel.RelatingPropertyDefinition
            for rel in cut.IsDefinedBy or []
            if rel.is_a("IfcRelDefinesByProperties")
            and rel.RelatingPropertyDefinition.is_a("IfcElementQuantity")
            and rel.RelatingPropertyDefinition.Name
            == "Qto_EarthworksCutBaseQuantities"
        )
        values = {q.Name: q.VolumeValue for q in qto.Quantities or []
                  if q.is_a("IfcQuantityVolume")}
        assert values["UndisturbedVolume"] == pytest.approx(1000.0, rel=1e-6)
        assert values["LooseVolume"] == pytest.approx(1250.0, rel=1e-6)

    def test_shrink_swell_pset_attached(self) -> None:
        ifc_file, terrain, existing, proposed = self._setup(110.0, 100.0)
        result = tool_earthwork.Earthwork.compute_volumes(
            existing, proposed, build_solids=True,
            shrink_factor=0.92, swell_factor=1.25,
        )
        tool_earthwork.Earthwork.author_volume_result(
            ifc_file, result, terrain=terrain
        )
        cut = ifc_file.by_id(result.ifc_cut_id)
        psets = [
            rel.RelatingPropertyDefinition
            for rel in cut.IsDefinedBy or []
            if rel.is_a("IfcRelDefinesByProperties")
        ]
        names = {p.Name for p in psets if p.is_a("IfcPropertySet")}
        assert "Pset_SaikeiGradingShrinkSwell" in names

    def test_cut_without_terrain_raises(self) -> None:
        ifc_file = _make_ifc_file_with_site()
        existing = _flat_square_surface("eg", 110.0)
        proposed = _flat_square_surface("pr", 100.0)
        result = tool_earthwork.Earthwork.compute_volumes(
            existing, proposed, build_solids=True
        )
        with pytest.raises(
            tool_earthwork.SaikeiEarthworkError, match="cut entities require a host terrain"
        ):
            tool_earthwork.Earthwork.author_volume_result(
                ifc_file, result, terrain=None
            )

    def test_pure_fill_does_not_need_terrain(self) -> None:
        """Fill-only result has no cut, so no IfcRelVoidsElement and
        no terrain requirement."""
        ifc_file = _make_ifc_file_with_site()
        existing = _flat_square_surface("eg", 95.0)
        proposed = _flat_square_surface("pr", 100.0)
        result = tool_earthwork.Earthwork.compute_volumes(
            existing, proposed, build_solids=True
        )
        # Should not raise.
        tool_earthwork.Earthwork.author_volume_result(
            ifc_file, result, terrain=None
        )
        assert result.ifc_fill_id is not None


# ---------------------------------------------------------------------------
# Phase 6 acceptance — bSI validator integration
# ---------------------------------------------------------------------------


import bpy  # noqa: E402  — used only by the bSI integration tests below.

import bonsai.tool as tool  # noqa: E402
from test.bim.bootstrap import NewIfc4X3  # noqa: E402


class TestEarthworkBSIIntegration(NewIfc4X3):
    """End-to-end integration test mirroring the Phase 4 + Phase 5
    'done' criterion (parallel to TestSurfaceBSIIntegration and
    TestGradingBSIIntegration).

    Drives the full operator chain (existing-ground create →
    proposed-surface from points → compute earthwork volumes)
    through ``bpy.ops``, writes the result to disk, reopens via
    :func:`ifcopenshell.open`, and runs
    :func:`ifcopenshell.validate.validate` to assert no schema
    warnings. When this passes, end users can author a complete
    earthwork-volume scenario in Bonsai and round-trip the result
    through IFC with a clean validator report.
    """

    @staticmethod
    def _validate_clean(ifc_path) -> None:
        """Re-open ``ifc_path`` and assert validate reports no
        warnings."""
        import logging

        import ifcopenshell.validate

        reopened = ifcopenshell.open(str(ifc_path))

        records: list[logging.LogRecord] = []

        class _CollectingHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        logger = logging.Logger("phase6-acceptance-validate")
        logger.addHandler(_CollectingHandler(level=logging.DEBUG))
        ifcopenshell.validate.validate(reopened, logger)

        errors = [r.getMessage() for r in records if r.levelno >= logging.WARNING]
        assert errors == [], f"ifcopenshell.validate() reported: {errors}"
        return reopened

    def _build_two_surfaces(self, tmp_path) -> tuple[str, str]:
        """Author two flat surfaces (existing at z=110, proposed at
        z=100) via the surface module's create operator. Returns
        ``(existing_guid, proposed_guid)``."""
        # Existing ground.
        eg_path = tmp_path / "eg.csv"
        eg_path.write_text(
            "-50,-50,110\n50,-50,110\n50,50,110\n-50,50,110\n"
        )
        bpy.context.scene.CivilSurfaceProperties.new_surface_name = (
            "bSI Earthwork EG"
        )
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(eg_path)
        )
        existing_guid = bpy.context.scene.CivilSurfaceProperties.active_surface_guid

        # Proposed ground (lower → all cut).
        pr_path = tmp_path / "pr.csv"
        pr_path.write_text(
            "-50,-50,100\n50,-50,100\n50,50,100\n-50,50,100\n"
        )
        bpy.context.scene.CivilSurfaceProperties.new_surface_name = (
            "bSI Earthwork PR"
        )
        bpy.context.scene.CivilSurfaceProperties.new_surface_kind = "proposed_site"
        bpy.ops.civil.surface_create_from_points(
            "EXEC_DEFAULT", csv_filepath=str(pr_path)
        )
        proposed_guid = bpy.context.scene.CivilSurfaceProperties.active_surface_guid

        return existing_guid, proposed_guid

    def test_full_workflow_round_trip_and_validate(self, tmp_path) -> None:
        """Author existing + proposed, run compute_earthwork_volumes,
        round-trip the IFC file through ifcopenshell.validate."""
        existing_guid, proposed_guid = self._build_two_surfaces(tmp_path)

        bpy.ops.civil.compute_earthwork_volumes(
            "EXEC_DEFAULT",
            existing_surface_guid=existing_guid,
            proposed_surface_guid=proposed_guid,
            shrink_factor=1.0,
            swell_factor=1.25,
        )

        ifc_path = tmp_path / "phase6_acceptance.ifc"
        tool.Ifc.get().write(str(ifc_path))
        reopened = self._validate_clean(ifc_path)

        # Round-trip structure assertions: cut + voiding rel exist;
        # Qto carries undisturbed + loose volumes.
        cuts = reopened.by_type("IfcEarthworksCut")
        assert len(cuts) == 1
        cut = cuts[0]

        rels = reopened.by_type("IfcRelVoidsElement")
        assert len(rels) == 1
        assert rels[0].RelatedOpeningElement.id() == cut.id()

        # Qto check: LooseVolume = UndisturbedVolume * 1.25.
        qto = next(
            rel.RelatingPropertyDefinition
            for rel in cut.IsDefinedBy or []
            if rel.is_a("IfcRelDefinesByProperties")
            and rel.RelatingPropertyDefinition.is_a("IfcElementQuantity")
            and rel.RelatingPropertyDefinition.Name
            == "Qto_EarthworksCutBaseQuantities"
        )
        values = {
            q.Name: q.VolumeValue
            for q in qto.Quantities or []
            if q.is_a("IfcQuantityVolume")
        }
        assert values["LooseVolume"] == pytest.approx(
            values["UndisturbedVolume"] * 1.25, rel=1e-6
        )

    def test_panel_cache_populated_after_operator(self, tmp_path) -> None:
        """The CivilEarthworkProperties cache fields should hold the
        last-run report after the operator finishes."""
        existing_guid, proposed_guid = self._build_two_surfaces(tmp_path)

        bpy.ops.civil.compute_earthwork_volumes(
            "EXEC_DEFAULT",
            existing_surface_guid=existing_guid,
            proposed_surface_guid=proposed_guid,
            swell_factor=1.25,
        )

        props = bpy.context.scene.CivilEarthworkProperties
        # 100×100 m × 10m delta = 100,000 m³ cut.
        assert props.last_cut_m3 == pytest.approx(100_000.0, rel=1e-6)
        assert props.last_fill_m3 == pytest.approx(0.0, abs=1e-6)
        assert props.last_net_m3 == pytest.approx(100_000.0, rel=1e-6)
        # Loose cut = undisturbed × swell_factor.
        assert props.last_loose_cut_m3 == pytest.approx(125_000.0, rel=1e-6)
        assert props.last_run_existing_guid == existing_guid
        assert props.last_run_proposed_guid == proposed_guid

    def test_missing_guids_cancels_with_error(self) -> None:
        """Operator should cancel cleanly when surface GUIDs are
        empty rather than crashing."""
        with pytest.raises(RuntimeError, match="required"):
            bpy.ops.civil.compute_earthwork_volumes(
                "EXEC_DEFAULT",
                existing_surface_guid="",
                proposed_surface_guid="",
            )

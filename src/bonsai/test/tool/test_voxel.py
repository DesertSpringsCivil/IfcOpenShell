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

"""Tests for ``bonsai.tool.voxel`` — Phase 1 RLE codec + occupancy ordering.

Run via the canonical Phase 4/5 invocation (PowerShell, from src/bonsai)::

    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
    python -m pytest test/tool/test_voxel.py `
      -o "addopts=" `
      -p pytest-blender `
      -v `
      --blender-executable "C:\\Program Files\\Blender Foundation\\Blender_5\\blender.exe"

The codec is pure-Python, but the file imports ``bonsai.tool`` (which pulls
``bpy`` via sibling tool modules), so it runs in Blender headless like the
surface tool tests.
"""

import types

import ifcopenshell
import ifcopenshell.guid
import numpy as np
import pytest

import bonsai.core.voxel as core_voxel
import bonsai.tool as tool
from bonsai.tool.voxel import GridDef, Voxel


# --------------------------------------------------------------------------- #
# RLE codec primitives
# --------------------------------------------------------------------------- #


class TestRleEncode:
    def test_basic_runs(self):
        assert Voxel.rle_encode([1, 1, 1, 0, 0, 1]) == [(1, 3), (0, 2), (1, 1)]

    def test_empty(self):
        assert Voxel.rle_encode([]) == []

    def test_single(self):
        assert Voxel.rle_encode([7]) == [(7, 1)]

    def test_all_same_collapses_to_one_run(self):
        assert Voxel.rle_encode([0] * 1000) == [(0, 1000)]

    def test_alternating_is_one_run_per_element(self):
        seq = [0, 1, 0, 1, 0]
        assert Voxel.rle_encode(seq) == [(0, 1), (1, 1), (0, 1), (1, 1), (0, 1)]


class TestRleDecode:
    def test_inverts_encode(self):
        seq = [1, 1, 0, 0, 0, 2, 2]
        assert Voxel.rle_decode(Voxel.rle_encode(seq)) == seq

    def test_empty(self):
        assert Voxel.rle_decode([]) == []

    def test_rejects_nonpositive_count(self):
        with pytest.raises(ValueError, match="count must be"):
            Voxel.rle_decode([(1, 0)])


class TestFlatten:
    def test_flatten_is_count_first(self):
        # (value, count) runs -> [count, value, ...]
        assert Voxel.rle_flatten([(1, 3), (0, 2), (1, 1)]) == [3, 1, 2, 0, 1, 1]

    def test_unflatten_inverts_flatten(self):
        runs = [(5, 2), (9, 4), (5, 1)]
        assert Voxel.rle_unflatten(Voxel.rle_flatten(runs)) == runs

    def test_unflatten_rejects_odd_length(self):
        with pytest.raises(ValueError, match="even length"):
            Voxel.rle_unflatten([3, 1, 2])

    def test_full_primitive_roundtrip(self):
        seq = [1, 1, 1, 0, 0, 1, 1, 1, 1]
        flat = Voxel.rle_flatten(Voxel.rle_encode(seq))
        back = Voxel.rle_decode(Voxel.rle_unflatten(flat))
        assert back == seq


class TestVectorizedRuns:
    def test_encode_runs_basic(self):
        assert Voxel.encode_runs(np.array([1, 1, 1, 0, 0, 1])) == [3, 1, 2, 0, 1, 1]

    def test_encode_runs_empty(self):
        assert Voxel.encode_runs(np.array([], dtype=int)) == []

    def test_matches_groupby_reference_int(self):
        rng = np.random.default_rng(0)
        arr = rng.integers(0, 3, size=5000)
        assert Voxel.encode_runs(arr) == Voxel.rle_flatten(Voxel.rle_encode(arr.tolist()))

    def test_matches_groupby_reference_float(self):
        rng = np.random.default_rng(1)
        arr = rng.choice([0.0, 0.5, 1.0], size=2000)
        assert Voxel.encode_runs(arr) == Voxel.rle_flatten(Voxel.rle_encode(arr.tolist()))

    def test_decode_runs_inverts(self):
        rng = np.random.default_rng(2)
        arr = rng.integers(0, 4, size=3000)
        assert Voxel.decode_runs(Voxel.encode_runs(arr)).tolist() == arr.tolist()

    def test_decode_runs_rejects_odd_length(self):
        with pytest.raises(ValueError, match="even length"):
            Voxel.decode_runs([3, 1, 2])

    def test_encode_occupancy_uses_vectorized_path_same_output(self):
        # Equivalence with the groupby reference on a random 3D mask.
        rng = np.random.default_rng(3)
        mask = rng.integers(0, 2, size=(12, 8, 5)).astype(bool)
        reference = Voxel.rle_flatten(Voxel.rle_encode(Voxel.mask_to_voxels(mask)))
        assert Voxel.encode_occupancy(mask) == reference


class TestCompressionRatio:
    def test_uniform_is_highly_compressible(self):
        # 1,000,000 identical cells -> one run -> 2 tokens.
        assert Voxel.compression_ratio([1] * 1_000_000) == pytest.approx(500_000.0)

    def test_alternating_is_worst_case_half(self):
        # n runs of 1 -> 2n tokens for n cells -> ratio 0.5 (RLE doubles size).
        assert Voxel.compression_ratio([0, 1] * 50) == pytest.approx(0.5)

    def test_empty_is_inf(self):
        assert Voxel.compression_ratio([]) == float("inf")


# --------------------------------------------------------------------------- #
# Canonical occupancy ordering (TM27: X fastest, then Y, then Z)
# --------------------------------------------------------------------------- #


class TestOrdering:
    def test_x_varies_fastest(self):
        # A single occupied cell at (x=1, y=0, z=0) must land at flat index 1
        # (index 0 is (0,0,0)); proves X is the fastest-varying axis.
        mask = np.zeros((2, 2, 2), dtype=bool)
        mask[1, 0, 0] = True
        voxels = Voxel.mask_to_voxels(mask)
        assert voxels == [0, 1, 0, 0, 0, 0, 0, 0]

    def test_y_is_second_axis(self):
        mask = np.zeros((2, 2, 2), dtype=bool)
        mask[0, 1, 0] = True  # X→Y→Z index 2
        assert Voxel.mask_to_voxels(mask) == [0, 0, 1, 0, 0, 0, 0, 0]

    def test_z_is_slowest_axis(self):
        mask = np.zeros((2, 2, 2), dtype=bool)
        mask[0, 0, 1] = True  # X→Y→Z index 4 (nx*ny = 4)
        assert Voxel.mask_to_voxels(mask) == [0, 0, 0, 0, 1, 0, 0, 0]

    def test_values_coerced_to_int_0_1(self):
        mask = np.array([[[2.5]], [[0.0]]])  # nonzero -> 1, zero -> 0
        assert Voxel.mask_to_voxels(mask) == [1, 0]

    def test_requires_3d(self):
        with pytest.raises(ValueError, match="must be 3D"):
            Voxel.mask_to_voxels(np.zeros((4, 4)))

    def test_voxels_to_mask_inverts(self):
        rng = np.random.default_rng(42)
        mask = rng.integers(0, 2, size=(5, 4, 3)).astype(bool)
        flat = Voxel.mask_to_voxels(mask)
        rebuilt = Voxel.voxels_to_mask(flat, 5, 4, 3)
        assert np.array_equal(rebuilt, mask)

    def test_voxels_to_mask_rejects_count_mismatch(self):
        with pytest.raises(ValueError, match="!= nx"):
            Voxel.voxels_to_mask([1, 0, 1], 2, 2, 2)


# --------------------------------------------------------------------------- #
# Combined occupancy entry points
# --------------------------------------------------------------------------- #


class TestOccupancy:
    def test_matches_phase0_spike_stream(self):
        # The Phase-0 spike authored IFCVOXELGRID(...,(1,1,1,0,2,1)) for a
        # 2x2x1 grid whose X→Y→Z mask was [1,0,1,1]. Lock that exact stream.
        mask = np.zeros((2, 2, 1), dtype=bool)
        mask[0, 0, 0] = True   # idx 0
        mask[1, 0, 0] = False  # idx 1
        mask[0, 1, 0] = True   # idx 2
        mask[1, 1, 0] = True   # idx 3
        assert Voxel.mask_to_voxels(mask) == [1, 0, 1, 1]
        assert Voxel.encode_occupancy(mask) == [1, 1, 1, 0, 2, 1]

    def test_roundtrip_small(self):
        mask = np.zeros((2, 2, 1), dtype=bool)
        mask[0, 0, 0] = mask[0, 1, 0] = mask[1, 1, 0] = True
        rle = Voxel.encode_occupancy(mask)
        assert np.array_equal(Voxel.decode_occupancy(rle, 2, 2, 1), mask)

    def test_roundtrip_large_random(self):
        rng = np.random.default_rng(7)
        nx, ny, nz = 40, 30, 20
        mask = rng.integers(0, 2, size=(nx, ny, nz)).astype(bool)
        rle = Voxel.encode_occupancy(mask)
        assert np.array_equal(Voxel.decode_occupancy(rle, nx, ny, nz), mask)

    def test_terrain_bounded_mask_compresses(self):
        # Bottom 60% full (terrain below a flat surface): two long runs.
        nx, ny, nz = 50, 50, 20
        mask = np.zeros((nx, ny, nz), dtype=bool)
        mask[:, :, : int(nz * 0.6)] = True
        rle = Voxel.encode_occupancy(mask)
        # X→Y→Z order: all-True block then all-False block => exactly 2 runs.
        assert len(rle) == 4
        assert np.array_equal(Voxel.decode_occupancy(rle, nx, ny, nz), mask)

    def test_decode_detects_dimension_mismatch(self):
        # A stream that decodes to 4 cells can't fill a 2x2x2=8 grid.
        rle = Voxel.rle_flatten(Voxel.rle_encode([1, 0, 1, 1]))
        with pytest.raises(ValueError, match="!= nx"):
            Voxel.decode_occupancy(rle, 2, 2, 2)


def test_voxel_tool_is_registered():
    """tool.Voxel resolves through the package (conforms to the interface)."""
    assert tool.Voxel is Voxel


# --------------------------------------------------------------------------- #
# Phase 2: lattice (GridDef)
# --------------------------------------------------------------------------- #


class TestGridDef:
    def test_make_grid_scalar_size(self):
        g = Voxel.make_grid((0, 0, 0), 1.0, (2, 3, 4))
        assert g.size == (1.0, 1.0, 1.0)
        assert g.counts == (2, 3, 4)
        assert g.cell_count == 24
        assert g.cell_volume == 1.0
        assert g.max_corner == (2.0, 3.0, 4.0)

    def test_anisotropic_cell_volume(self):
        g = Voxel.make_grid((1, 2, 3), (0.5, 0.5, 0.25), (2, 2, 4))
        assert g.cell_volume == pytest.approx(0.0625)
        assert g.max_corner == (2.0, 3.0, 4.0)

    def test_rejects_nonpositive_size(self):
        with pytest.raises(ValueError, match="sizes must be"):
            Voxel.make_grid((0, 0, 0), (1, 0, 1), (2, 2, 2))

    def test_rejects_zero_counts(self):
        with pytest.raises(ValueError, match="counts must be"):
            Voxel.make_grid((0, 0, 0), 1.0, (2, 0, 2))

    def test_coerces_counts_to_int(self):
        g = Voxel.make_grid((0, 0, 0), 1.0, (2.0, 2.0, 2.0))
        assert g.counts == (2, 2, 2)
        assert all(isinstance(c, int) for c in g.counts)


class TestLattice:
    def test_grid_from_bounds_exact(self):
        g = Voxel.grid_from_bounds((0, 0, 0), (10, 10, 5), 1.0)
        assert g.counts == (10, 10, 5)
        assert g.origin == (0.0, 0.0, 0.0)

    def test_grid_from_bounds_ceils_to_cover(self):
        g = Voxel.grid_from_bounds((0, 0, 0), (2.5, 2.5, 2.5), 1.0)
        assert g.counts == (3, 3, 3)  # ceil(2.5) -> max_corner 3 >= 2.5

    def test_grid_from_bounds_anisotropic_cell(self):
        g = Voxel.grid_from_bounds((0, 0, 0), (10, 10, 4), (2, 2, 1))
        assert g.counts == (5, 5, 4)

    def test_grid_from_bounds_rejects_inverted(self):
        with pytest.raises(ValueError, match="max"):
            Voxel.grid_from_bounds((0, 0, 0), (1, -1, 1), 1.0)

    def test_xyz_bounds(self):
        pts = np.array([[0, 0, 1], [4, 2, 3], [1, -1, 2]], dtype=float)
        mn, mx = Voxel.xyz_bounds(pts)
        assert mn == (0.0, -1.0, 1.0)
        assert mx == (4.0, 2.0, 3.0)

    def test_xyz_bounds_rejects_non_n3(self):
        with pytest.raises(ValueError, match=r"N, 3"):
            Voxel.xyz_bounds(np.zeros((4, 2)))

    def test_grid_from_surface_default_z(self):
        surf = types.SimpleNamespace(points=np.array([[0, 0, 1.0], [4, 2, 3.0]]))
        g = Voxel.grid_from_surface(surf, 1.0)
        assert g.origin == (0.0, 0.0, 1.0)
        assert g.counts == (4, 2, 2)

    def test_grid_from_surface_z_override(self):
        surf = types.SimpleNamespace(points=np.array([[0, 0, 1.0], [4, 2, 3.0]]))
        g = Voxel.grid_from_surface(surf, 1.0, z_min=0.0, z_max=10.0)
        assert g.origin == (0.0, 0.0, 0.0)
        assert g.counts == (4, 2, 10)

    def test_assert_shared_lattice_ok(self):
        a = Voxel.make_grid((0, 0, 0), 1.0, (2, 2, 2))
        b = Voxel.make_grid((0, 0, 0), 1.0, (2, 2, 2))
        Voxel.assert_shared_lattice(a, b)  # no raise

    def test_assert_shared_lattice_diff_counts(self):
        a = Voxel.make_grid((0, 0, 0), 1.0, (2, 2, 2))
        b = Voxel.make_grid((0, 0, 0), 1.0, (2, 2, 3))
        with pytest.raises(ValueError, match="counts differ"):
            Voxel.assert_shared_lattice(a, b)

    def test_assert_shared_lattice_diff_origin(self):
        a = Voxel.make_grid((0, 0, 0), 1.0, (2, 2, 2))
        b = Voxel.make_grid((0.5, 0, 0), 1.0, (2, 2, 2))
        with pytest.raises(ValueError, match="origin differs"):
            Voxel.assert_shared_lattice(a, b)

    def test_cell_centers(self):
        g = Voxel.make_grid((0, 0, 0), (2, 2, 2), (2, 2, 2))
        xs, ys, zs = Voxel.cell_centers(g)
        assert list(xs) == [1.0, 3.0]
        assert list(ys) == [1.0, 3.0]
        assert list(zs) == [1.0, 3.0]


# --------------------------------------------------------------------------- #
# Phase 2: voxelization
# --------------------------------------------------------------------------- #


class TestVoxelize:
    def test_flat_plane(self):
        g = Voxel.make_grid((0, 0, 0), 1.0, (2, 2, 10))
        mask = Voxel.voxelize_below_surface(g, lambda xs, ys: np.full(len(xs), 5.0))
        assert mask.shape == (2, 2, 10)
        assert mask[:, :, :5].all()  # centres 0.5..4.5 < 5 -> soil
        assert not mask[:, :, 5:].any()  # centres 5.5..9.5 > 5 -> air
        assert Voxel.occupancy_volume(g, mask) == 20.0

    def test_nan_region_is_air(self):
        g = Voxel.make_grid((0, 0, 0), 1.0, (2, 2, 10))

        def hf(xs, ys):
            return np.where(xs < 1.0, 5.0, np.nan)  # only column x<1 defined

        mask = Voxel.voxelize_below_surface(g, hf)
        assert mask[0, :, :5].all()
        assert not mask[1, :, :].any()  # NaN column -> air
        assert Voxel.occupancy_volume(g, mask) == 10.0

    def test_sloped_surface(self):
        g = Voxel.make_grid((0, 0, 0), 1.0, (4, 1, 4))
        mask = Voxel.voxelize_below_surface(g, lambda xs, ys: xs)  # height = x
        # column i (x centre i+0.5): occupied levels = # of z-centres < i+0.5
        assert mask[0, 0].sum() == 0
        assert mask[1, 0].sum() == 1
        assert mask[2, 0].sum() == 2
        assert mask[3, 0].sum() == 3
        assert mask.sum() == 6

    def test_supersample_refines_boundary(self):
        # Single cell; height is high at the cell's XY edges, low at its centre.
        # Centre test (s=1) -> air; majority of a 3x3 subgrid -> soil.
        g = Voxel.make_grid((0, 0, 0), 1.0, (1, 1, 1))

        def hf(xs, ys):
            return np.where((xs < 0.3) | (xs > 0.7), 10.0, 0.0)

        assert bool(Voxel.voxelize_below_surface(g, hf, supersample=1)[0, 0, 0]) is False
        assert bool(Voxel.voxelize_below_surface(g, hf, supersample=3)[0, 0, 0]) is True

    def test_supersample_rejects_zero(self):
        g = Voxel.make_grid((0, 0, 0), 1.0, (1, 1, 1))
        with pytest.raises(ValueError, match="supersample"):
            Voxel.voxelize_below_surface(g, lambda xs, ys: np.zeros(len(xs)), supersample=0)

    def test_encode_roundtrip_of_voxelized_mask(self):
        g = Voxel.make_grid((0, 0, 0), 1.0, (3, 3, 4))
        mask = Voxel.voxelize_below_surface(g, lambda xs, ys: np.full(len(xs), 2.0))
        rle = Voxel.encode_occupancy(mask)
        assert np.array_equal(Voxel.decode_occupancy(rle, 3, 3, 4), mask)

    def test_shared_lattice_cut_region(self):
        # Existing ground at z=5, design (lower) at z=3, same lattice.
        g = Voxel.make_grid((0, 0, 0), 1.0, (2, 2, 10))
        existing = Voxel.voxelize_below_surface(g, lambda xs, ys: np.full(len(xs), 5.0))
        design = Voxel.voxelize_below_surface(g, lambda xs, ys: np.full(len(xs), 3.0))
        assert (design & ~existing).sum() == 0  # design soil ⊆ existing soil
        assert (existing & ~design).sum() > 0  # a cut (soil->air) region exists


class TestHeightFnFromZAt:
    def test_wraps_z_at_with_nan_outside(self):
        def z_at(surface, x, y):
            return (x + y) if x < 5 else None  # None == outside

        hf = Voxel.height_fn_from_z_at(z_at, surface=object())
        out = hf(np.array([1.0, 6.0]), np.array([2.0, 1.0]))
        assert out[0] == 3.0
        assert np.isnan(out[1])


class TestVoxelizeSurfaceIntegration:
    def test_real_tin_voxelizes(self):
        """End-to-end: a real tool.Surface TIN -> z_at -> occupancy."""
        pts = [(0, 0, 5), (10, 0, 5), (10, 10, 5), (0, 10, 5)]  # flat pad at z=5
        surf = tool.Surface.build_tin_from_points(name="EG", points=pts, kind="existing")
        g = Voxel.grid_from_surface(surf, 1.0, z_min=0.0, z_max=5.0)
        mask = Voxel.voxelize_surface(g, surf)
        # XY fully inside the square hull; z centres 0.5..4.5 all below 5 -> all soil.
        assert g.counts == (10, 10, 5)
        assert mask.all()
        assert Voxel.occupancy_volume(g, mask) == 500.0


# --------------------------------------------------------------------------- #
# Phase 4: cut / fill set-ops (+ boundary cross-validation)
# --------------------------------------------------------------------------- #


def _flat(z):
    return lambda xs, ys: np.full(len(xs), float(z))


class TestCutFill:
    def test_pure_cut_matches_prism_volume(self):
        # Existing flat z=5, design flat z=3 over a 10x10 pad, 1 m cells.
        # The boundary method's prism volume = area * dz = 100 * 2 = 200 m^3,
        # all cut (design everywhere below existing). Cell-aligned -> exact.
        g = Voxel.make_grid((0, 0, 0), 1.0, (10, 10, 5))
        existing = Voxel.voxelize_below_surface(g, _flat(5))
        design = Voxel.voxelize_below_surface(g, _flat(3))
        r = Voxel.cut_fill(existing, design, g)
        assert r["cut"] == 200.0
        assert r["fill"] == 0.0
        assert r["net"] == -200.0  # net export

    def test_pure_fill(self):
        g = Voxel.make_grid((0, 0, 0), 1.0, (10, 10, 5))
        existing = Voxel.voxelize_below_surface(g, _flat(2))
        design = Voxel.voxelize_below_surface(g, _flat(4))
        r = Voxel.cut_fill(existing, design, g)
        assert r["fill"] == 200.0
        assert r["cut"] == 0.0
        assert r["net"] == 200.0  # net import

    def test_mixed_cut_and_fill(self):
        # Existing flat z=3; design = 2x ramp (heights 1,3,5,7 at x-centres
        # 0.5,1.5,2.5,3.5). Cut where design below existing, fill where above.
        g = Voxel.make_grid((0, 0, 0), 1.0, (4, 1, 4))
        existing = Voxel.voxelize_below_surface(g, _flat(3))
        design = Voxel.voxelize_below_surface(g, lambda xs, ys: 2.0 * xs)
        r = Voxel.cut_fill(existing, design, g)
        assert r["cut"] == 2.0
        assert r["fill"] == 2.0
        assert r["net"] == 0.0

    def test_cross_validation_converges_with_resolution(self):
        # Existing z=5, design z=2.5 over 4x4 -> prism cut = 16 * 2.5 = 40 m^3.
        # 1 m cells stair-step to 48 (design clamps to z=2); 0.5 m cells land
        # exactly on 2.5 -> 40. Finer must be at least as close to the truth.
        truth = 40.0
        g1 = Voxel.make_grid((0, 0, 0), 1.0, (4, 4, 5))
        cut1 = Voxel.cut_fill(
            Voxel.voxelize_below_surface(g1, _flat(5)),
            Voxel.voxelize_below_surface(g1, _flat(2.5)),
            g1,
        )["cut"]
        g2 = Voxel.make_grid((0, 0, 0), 0.5, (8, 8, 10))
        cut2 = Voxel.cut_fill(
            Voxel.voxelize_below_surface(g2, _flat(5)),
            Voxel.voxelize_below_surface(g2, _flat(2.5)),
            g2,
        )["cut"]
        assert cut1 == 48.0
        assert cut2 == 40.0
        assert abs(cut2 - truth) <= abs(cut1 - truth)

    def test_cut_fill_masks(self):
        existing = np.array([[[True, True]]])  # 1x1x2
        design = np.array([[[True, False]]])
        masks = Voxel.cut_fill_masks(existing, design)
        assert masks["cut"].tolist() == [[[False, True]]]  # 2nd cell soil->air
        assert masks["fill"].tolist() == [[[False, False]]]

    def test_cut_fill_masks_rejects_shape_mismatch(self):
        with pytest.raises(ValueError, match="share shape"):
            Voxel.cut_fill_masks(np.zeros((2, 2, 2), bool), np.zeros((2, 2, 3), bool))

    def test_cut_fill_rejects_lattice_mismatch(self):
        g = Voxel.make_grid((0, 0, 0), 1.0, (2, 2, 2))
        with pytest.raises(ValueError, match="shared lattice"):
            Voxel.cut_fill(np.zeros((2, 2, 2), bool), np.zeros((2, 2, 3), bool), g)

    def test_shared_grid_unions_bounds(self):
        a = types.SimpleNamespace(points=np.array([[0, 0, 1.0], [4, 4, 5.0]]))
        b = types.SimpleNamespace(points=np.array([[-2, 1, 0.0], [3, 6, 8.0]]))
        g = Voxel.shared_grid([a, b], 1.0)
        assert g.origin == (-2.0, 0.0, 0.0)
        # max corner covers (4, 6, 8): counts ceil((4-(-2)),(6-0),(8-0)) = (6,6,8)
        assert g.counts == (6, 6, 8)

    def test_shared_grid_z_override(self):
        a = types.SimpleNamespace(points=np.array([[0, 0, 2.0], [4, 4, 5.0]]))
        g = Voxel.shared_grid([a], 1.0, z_min=0.0, z_max=10.0)
        assert g.origin[2] == 0.0
        assert g.counts[2] == 10

    def test_bulk_applies_factor(self):
        assert Voxel.bulk(200.0, 1.25) == 250.0  # loose = bank * swell


# --------------------------------------------------------------------------- #
# Phase 4b: sidecar authoring wrappers (over ifcopenshell.api.voxel)
# --------------------------------------------------------------------------- #


def _read_quantity(host, qto_name, quantity_name):
    for rel in host.IsDefinedBy or []:
        if not rel.is_a("IfcRelDefinesByProperties"):
            continue
        q = rel.RelatingPropertyDefinition
        if q is not None and q.is_a("IfcElementQuantity") and q.Name == qto_name:
            for quantity in q.Quantities or []:
                if quantity.Name == quantity_name:
                    return quantity[3]  # the *Value attribute
    return None


class TestAuthoringWrappers:
    def test_new_sidecar_is_ifc4x4(self):
        f = Voxel.new_sidecar()
        assert f.schema == "IFC4X4"
        assert f.by_type("IfcProject")

    def test_author_earthwork_roundtrips_grid_and_qto(self):
        f = Voxel.new_sidecar()
        grid = Voxel.make_grid((0, 0, 0), 1.0, (2, 2, 1))
        mask = Voxel.voxels_to_mask([1, 0, 1, 1], 2, 2, 1)  # 3 occupied cells
        host = Voxel.author_earthwork(
            f, grid, mask, host_class="IfcEarthworksCut", predefined_type="EXCAVATION",
            name="Cut", bank_volume=3.0, source_surface_guid="src-guid", swell_factor=1.25,
        )
        assert host.is_a("IfcEarthworksCut")
        assert host.Description == "voxelized-from:src-guid"
        # Grid occupancy is the RLE of the mask.
        ifc_grid = f.by_type("IfcVoxelGrid")[0]
        assert list(ifc_grid.Voxels) == Voxel.encode_occupancy(mask)  # [1,1,1,0,2,1]
        assert (ifc_grid.NumberOfVoxelsX, ifc_grid.NumberOfVoxelsY, ifc_grid.NumberOfVoxelsZ) == (2, 2, 1)
        # Quantities: bank + swelled loose.
        assert _read_quantity(host, "Qto_EarthworksCutBaseQuantities", "UndisturbedVolume") == 3.0
        assert _read_quantity(host, "Qto_EarthworksCutBaseQuantities", "LooseVolume") == 3.75

    def test_author_earthwork_fill(self):
        f = Voxel.new_sidecar()
        grid = Voxel.make_grid((0, 0, 0), 1.0, (2, 2, 1))
        mask = Voxel.voxels_to_mask([1, 1, 0, 0], 2, 2, 1)
        host = Voxel.author_earthwork(
            f, grid, mask, host_class="IfcEarthworksFill", predefined_type="EMBANKMENT",
            name="Fill", bank_volume=2.0,
        )
        assert host.is_a("IfcEarthworksFill")
        assert _read_quantity(host, "Qto_EarthworksFillBaseQuantities", "CompactedVolume") == 2.0


# --------------------------------------------------------------------------- #
# End-to-end: real surfaces -> core.author_cut_fill_sidecar -> sidecar
# --------------------------------------------------------------------------- #


class TestEndToEndSidecar:
    def test_real_surfaces_to_voxel_sidecar(self):
        """Full chain through core with real tool.Surface TINs, cross-validated.

        Existing flat z=5, design flat z=3 over a 10x10 pad -> the boundary prism
        cut volume is 100 * 2 = 200 m^3, all cut. The generated sidecar must
        contain one IfcEarthworksCut voxel grid with UndisturbedVolume == 200 and
        no fill element.
        """
        prod = ifcopenshell.file(schema="IFC4X3_ADD2")
        project = prod.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), Name="Prod")
        site = prod.create_entity("IfcSite", GlobalId=ifcopenshell.guid.new(), Name="Site")
        prod.create_entity(
            "IfcRelAggregates", GlobalId=ifcopenshell.guid.new(),
            RelatingObject=project, RelatedObjects=[site],
        )

        eg_pts = [(0, 0, 5), (10, 0, 5), (10, 10, 5), (0, 10, 5)]
        design_pts = [(0, 0, 3), (10, 0, 3), (10, 10, 3), (0, 10, 3)]
        existing = tool.Surface.build_tin_from_points(name="EG", points=eg_pts, kind="existing")
        tool.Surface.author_ifc_host(prod, existing)
        tool.Surface.register(prod, existing)
        design = tool.Surface.build_tin_from_points(name="DG", points=design_pts, kind="proposed_group")
        tool.Surface.author_ifc_host(prod, design)
        tool.Surface.register(prod, design)

        class FakeIfc:
            @staticmethod
            def get():
                return prod

        try:
            sidecar, result = core_voxel.author_cut_fill_sidecar(
                FakeIfc, tool.Surface, tool.Voxel,
                existing_guid=existing.guid, design_guid=design.guid,
                cell_size=1.0, z_min=0.0, z_max=5.0,
            )

            assert result["cut"] == 200.0
            assert result["fill"] == 0.0
            assert sidecar.schema == "IFC4X4"
            cuts = sidecar.by_type("IfcEarthworksCut")
            assert len(cuts) == 1
            assert not sidecar.by_type("IfcEarthworksFill")  # no fill region
            assert len(sidecar.by_type("IfcVoxelGrid")) == 1
            assert _read_quantity(cuts[0], "Qto_EarthworksCutBaseQuantities", "UndisturbedVolume") == 200.0
            assert cuts[0].Description == f"voxelized-from:{existing.guid}"
        finally:
            tool.Surface.clear()


# --------------------------------------------------------------------------- #
# Phase 6: Blender preview mesh
# --------------------------------------------------------------------------- #


class TestPreviewMesh:
    def test_creates_colored_cube_mesh(self):
        import bpy

        Voxel.clear_preview()
        g = Voxel.make_grid((0, 0, 0), 1.0, (2, 2, 2))
        mask = np.zeros((2, 2, 2), dtype=bool)
        mask[0, 0, 0] = mask[1, 1, 1] = True  # 2 occupied cells
        names = Voxel.create_preview_mesh(g, {"cut": mask})
        try:
            assert len(names) == 1
            obj = bpy.data.objects[names[0]]
            assert obj["saikei_voxel_preview"] is True
            assert len(obj.data.vertices) == 16  # 2 cells × 8 corners
            assert len(obj.data.polygons) == 12  # 2 cells × 6 faces
            assert obj.data.materials[0].diffuse_color[0] > 0.5  # red-ish cut
        finally:
            assert Voxel.clear_preview() >= 1
            assert not [o for o in bpy.data.objects if o.get("saikei_voxel_preview")]

    def test_multiple_masks_make_separate_objects(self):
        Voxel.clear_preview()
        g = Voxel.make_grid((0, 0, 0), 1.0, (2, 2, 2))
        cut = np.zeros((2, 2, 2), dtype=bool); cut[0, 0, 0] = True
        fill = np.zeros((2, 2, 2), dtype=bool); fill[1, 1, 1] = True
        names = Voxel.create_preview_mesh(g, {"cut": cut, "fill": fill})
        try:
            assert len(names) == 2
        finally:
            Voxel.clear_preview()

    def test_skips_empty_mask(self):
        Voxel.clear_preview()
        g = Voxel.make_grid((0, 0, 0), 1.0, (2, 2, 2))
        assert Voxel.create_preview_mesh(g, {"cut": np.zeros((2, 2, 2), dtype=bool)}) == []
        Voxel.clear_preview()

    def test_enforces_cell_cap(self):
        Voxel.clear_preview()
        g = Voxel.make_grid((0, 0, 0), 1.0, (100, 100, 100))  # 1e6 > 250k cap
        with pytest.raises(ValueError, match="cap"):
            Voxel.create_preview_mesh(g, {"occupancy": np.ones((100, 100, 100), dtype=bool)})
        Voxel.clear_preview()


# --------------------------------------------------------------------------- #
# Phase 5: stratum / geomodel
# --------------------------------------------------------------------------- #


class TestStrata:
    def _three_surface_codes(self):
        # Boundaries at z=9 (top), 6, 3 (bottom) -> 2 strata over a 2x2x10 grid.
        g = Voxel.make_grid((0, 0, 0), 1.0, (2, 2, 10))
        fields = [np.full((2, 2), 9.0), np.full((2, 2), 6.0), np.full((2, 2), 3.0)]
        return g, Voxel.classify_strata(g, fields)

    def test_classify_strata_codes(self):
        g, code = self._three_surface_codes()
        assert code.shape == (2, 2, 10)
        # stratum 1 (between z9 and z6): zc 6.5/7.5/8.5 → 3 layers × 4 cells
        assert (code == 1).sum() == 12
        # stratum 2 (between z6 and z3): zc 3.5/4.5/5.5 → 3 layers × 4 cells
        assert (code == 2).sum() == 12
        # air: below z3 (k0-2) + above z9 (k9) = 4 layers × 4
        assert (code == 0).sum() == 16

    def test_classify_strata_requires_two_surfaces(self):
        g = Voxel.make_grid((0, 0, 0), 1.0, (2, 2, 2))
        with pytest.raises(ValueError, match=">= 2 boundary"):
            Voxel.classify_strata(g, [np.full((2, 2), 1.0)])

    def test_stratum_volume_and_volumes(self):
        g, code = self._three_surface_codes()
        assert Voxel.stratum_volume(g, code, 1) == 12.0
        assert Voxel.stratum_volume(g, code, 2) == 12.0
        assert Voxel.stratum_volumes(g, code) == {1: 12.0, 2: 12.0}  # excludes code 0

    def test_gather_occupied_xyz_order(self):
        code = np.zeros((2, 2, 1), dtype=int)
        code[0, 0, 0] = 5
        code[1, 0, 0] = 0
        code[0, 1, 0] = 7
        code[1, 1, 0] = 9
        mask = code > 0
        # X→Y→Z gather of occupied cells: (0,0)=5, (0,1)=7, (1,1)=9
        assert Voxel.gather_occupied(code, mask).tolist() == [5, 7, 9]

    def test_order_surfaces_by_elevation(self):
        low = types.SimpleNamespace(points=np.array([[0, 0, 1.0], [1, 1, 2.0]]), name="low")
        high = types.SimpleNamespace(points=np.array([[0, 0, 8.0], [1, 1, 9.0]]), name="high")
        mid = types.SimpleNamespace(points=np.array([[0, 0, 4.0], [1, 1, 5.0]]), name="mid")
        ordered = Voxel.order_surfaces_by_elevation([low, high, mid])
        assert [s.name for s in ordered] == ["high", "mid", "low"]

    def test_strata_legend(self):
        s = [types.SimpleNamespace(name=n) for n in ("Top of Clay", "Top of Sand", "Bedrock")]
        # 3 surfaces → 2 strata, each named by its top boundary surface
        assert Voxel.strata_legend(s) == {1: "Top of Clay", 2: "Top of Sand"}

    def test_author_geomodel_roundtrip(self):
        g, code = self._three_surface_codes()
        legend = {1: "Clay", 2: "Sand"}
        f = Voxel.new_sidecar()
        host = Voxel.author_geomodel(f, g, code, legend, name="Geo", source_surface_guids=["gA", "gB", "gC"])
        assert host.is_a("IfcGeomodel")
        # occupancy grid = code>0
        grid = f.by_type("IfcVoxelGrid")[0]
        assert np.array_equal(
            Voxel.decode_occupancy(grid.Voxels, 2, 2, 10), code > 0
        )
        # stratum code layer round-trips (gathered over occupied cells)
        layer = f.by_type("IfcIntegerVoxelData")[0]
        gathered = Voxel.gather_occupied(code, code > 0)
        assert Voxel.decode_runs(layer.ValueData).tolist() == gathered.tolist()
        assert "strata:1=Clay;2=Sand" in (host.Description or "")

    def test_create_strata_preview_one_object_per_stratum(self):
        Voxel.clear_preview()
        g, code = self._three_surface_codes()
        names = Voxel.create_strata_preview(g, code, {1: "Clay", 2: "Sand"})
        try:
            assert len(names) == 2  # one mesh per stratum
        finally:
            Voxel.clear_preview()


class TestCutByStratum:
    def test_excavation_split_by_stratum(self):
        g = Voxel.make_grid((0, 0, 0), 1.0, (1, 1, 4))
        code = np.zeros((1, 1, 4), dtype=int)
        code[0, 0, 0] = code[0, 0, 1] = 2  # bottom two cells = stratum 2
        code[0, 0, 2] = code[0, 0, 3] = 1  # top two cells = stratum 1
        cut = np.zeros((1, 1, 4), dtype=bool)
        cut[0, 0, 1] = True  # excavate one stratum-2 cell
        cut[0, 0, 2] = True  # excavate one stratum-1 cell
        assert Voxel.cut_fill_by_stratum(cut, code, g) == {1: 1.0, 2: 1.0}

    def test_ignores_unclassified_cut_cells(self):
        g = Voxel.make_grid((0, 0, 0), 1.0, (1, 1, 4))
        code = np.zeros((1, 1, 4), dtype=int)
        code[0, 0, 2] = 1  # only one classified cell
        cut = np.ones((1, 1, 4), dtype=bool)  # cut everything
        assert Voxel.cut_fill_by_stratum(cut, code, g) == {1: 1.0}  # code-0 cut cells excluded

    def test_rejects_shape_mismatch(self):
        g = Voxel.make_grid((0, 0, 0), 1.0, (2, 2, 2))
        with pytest.raises(ValueError, match="shared lattice"):
            Voxel.cut_fill_by_stratum(np.zeros((2, 2, 2), bool), np.zeros((2, 2, 3), int), g)

    def test_intersect_codes(self):
        code = np.array([[[1, 2, 3]]])
        mask = np.array([[[True, False, True]]])
        assert Voxel.intersect_codes(code, mask).tolist() == [[[1, 0, 3]]]

    def test_per_stratum_sums_to_total_cut(self):
        # End-to-end consistency: per-stratum excavation sums to the overall cut.
        g = Voxel.make_grid((0, 0, 0), 1.0, (5, 5, 10))
        existing = Voxel.voxelize_below_surface(g, _flat(8))
        design = Voxel.voxelize_below_surface(g, _flat(4))
        cut_mask = Voxel.cut_fill_masks(existing, design)["cut"]
        code = Voxel.classify_strata(g, [np.full((5, 5), 8.0), np.full((5, 5), 6.0), np.full((5, 5), 2.0)])
        by_stratum = Voxel.cut_fill_by_stratum(cut_mask, code, g)
        total_cut = Voxel.cut_fill(existing, design, g)["cut"]
        assert sum(by_stratum.values()) == total_cut

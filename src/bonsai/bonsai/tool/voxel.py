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

"""Saikei voxel tool layer — Phase 1: the RLE codec + occupancy ordering.

Phase 5 of the Saikei grading/earthwork sprint pivots earthwork volumetrics
from the boundary/prismoidal method to run-length-encoded (RLE) occupancy
voxels, modeled on IFC 4.4 TM27 (``IfcVoxelGrid`` + ``IfcVoxelData``). See
``Saikei_Voxel_RLE_BuildSpec.md`` at the repo root.

This module is the tool-layer math foundation. Phase 1 owns exactly two things:

1. **The RLE codec** (spec §3.4) — encode a dense sequence to ``(value, count)``
   runs, decode back, and (un)flatten runs to/from the flat integer stream that
   is actually serialized into IFC.
2. **The canonical occupancy ordering** (TM27 ``IfcVoxelGrid.Voxels``: "along X,
   then Y and finally Z") — convert a 3D occupancy mask to/from the flat list,
   and the two combined ``encode_occupancy`` / ``decode_occupancy`` entry points
   that Phase 3 IFC authoring will call.

Why RLE and why integers (the spike findings, see ``spike_voxel/``):

- IfcOpenShell's wrapper has no setter/getter for a ``LIST OF IfcBoolean``, so
  TM27's dense boolean mask is un-authorable; a ``LIST OF IfcInteger`` round-
  trips. RLE-as-integer is therefore both the compression strategy *and* the
  only occupancy encoding that survives the toolchain. Occupancy values are
  ``1`` (occupied / soil) and ``0`` (empty / air).

Encoding conventions (fix one; spec §9 flags these as forum open-questions):

- In-memory runs are ``(value, count)`` tuples (matches spec §3.4 ``rle_encode``).
- The flat serialized stream is **count-first**: ``[count, value, count, value,
  …]`` (matches spec §3.4 ``rle_flatten`` and the Phase-0 spike). Even length;
  every count is a positive integer.

Layering: this is the only Saikei voxel layer permitted ``numpy``. The codec
primitives are pure-Python (stdlib only); the mask helpers use ``numpy`` for the
X→Y→Z ravel. No ``bpy`` / ``ifcopenshell`` here in Phase 1 — IFC authoring and
Blender linkage land in later phases. ``bonsai.core.voxel`` orchestration calls
into this class; UI calls into core.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby
from typing import TYPE_CHECKING, Callable, Optional, Sequence, Union

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray


@dataclass(frozen=True)
class GridDef:
    """Definition of a regular voxel lattice — the shared geometry both the
    existing-state and design-state occupancy masks are sampled onto.

    Maps directly onto TM27 ``IfcVoxelGrid`` (``size`` → ``VoxelSize{X,Y,Z}``,
    ``counts`` → ``NumberOfVoxels{X,Y,Z}``). ``origin`` is the **minimum corner**
    of cell ``(0, 0, 0)`` in project coordinates; TM27 carries no origin on the
    grid itself (placement comes from the host product), so Saikei tracks it
    here and maps it to the host ``ObjectPlacement`` at authoring time.

    Cell ``(i, j, k)`` spans ``[origin + (i,j,k)*size, origin + (i+1,j+1,k+1)*size]``
    and its centre is ``origin + (i+0.5, j+0.5, k+0.5)*size``. Cell ordering is
    the canonical TM27 X→Y→Z (see :meth:`Voxel.mask_to_voxels`).
    """

    origin: tuple[float, float, float]
    """Minimum corner of cell (0, 0, 0), project coordinates."""

    size: tuple[float, float, float]
    """Per-axis cell size ``(sx, sy, sz)`` — anisotropic spacing is allowed
    (fine vertical / coarse horizontal is common in geology)."""

    counts: tuple[int, int, int]
    """Per-axis cell count ``(nx, ny, nz)``."""

    def __post_init__(self) -> None:
        object.__setattr__(self, "origin", tuple(float(o) for o in self.origin))
        object.__setattr__(self, "size", tuple(float(s) for s in self.size))
        object.__setattr__(self, "counts", tuple(int(c) for c in self.counts))
        if len(self.origin) != 3 or len(self.size) != 3 or len(self.counts) != 3:
            raise ValueError("origin, size, and counts must each have 3 components")
        if any(s <= 0 for s in self.size):
            raise ValueError(f"voxel sizes must be > 0, got {self.size}")
        if any(c < 1 for c in self.counts):
            raise ValueError(f"voxel counts must be >= 1, got {self.counts}")

    @property
    def cell_count(self) -> int:
        nx, ny, nz = self.counts
        return nx * ny * nz

    @property
    def cell_volume(self) -> float:
        sx, sy, sz = self.size
        return sx * sy * sz

    @property
    def max_corner(self) -> tuple[float, float, float]:
        """Maximum corner of the lattice (origin + counts*size)."""
        return tuple(o + s * c for o, s, c in zip(self.origin, self.size, self.counts))


class Voxel:
    """Tool-layer entry point for voxel math. Phase 1: RLE codec + ordering.

    Every method is a :func:`staticmethod` called from
    :mod:`bonsai.core.voxel` orchestration (mirrors :class:`bonsai.tool.Surface`).
    """

    # ------------------------------------------------------------------ #
    # RLE codec primitives (spec §3.4) — pure Python, work on any sequence.
    # ------------------------------------------------------------------ #

    @staticmethod
    def rle_encode(seq: Sequence) -> list[tuple]:
        """Dense sequence → list of ``(value, count)`` runs.

        Adjacent equal values collapse to one run. An empty input yields an
        empty run list.

        >>> Voxel.rle_encode([1, 1, 1, 0, 0, 1])
        [(1, 3), (0, 2), (1, 1)]
        """
        return [(value, sum(1 for _ in group)) for value, group in groupby(seq)]

    @staticmethod
    def rle_decode(runs: Sequence[tuple]) -> list:
        """List of ``(value, count)`` runs → dense list.

        Inverse of :meth:`rle_encode`.

        :raises ValueError: if any count is not a positive integer.
        """
        out: list = []
        for value, count in runs:
            if int(count) < 1:
                raise ValueError(f"run count must be >= 1, got {count!r}")
            out.extend([value] * int(count))
        return out

    @staticmethod
    def rle_flatten(runs: Sequence[tuple]) -> list:
        """``(value, count)`` runs → flat **count-first** stream.

        ``[(v0, c0), (v1, c1), …] → [c0, v0, c1, v1, …]``. This is the form
        serialized into ``IfcVoxelGrid.Voxels`` / ``IfcVoxelData.ValueData``.
        """
        flat: list = []
        for value, count in runs:
            flat.extend([count, value])
        return flat

    @staticmethod
    def rle_unflatten(flat: Sequence) -> list[tuple]:
        """Flat count-first stream → ``(value, count)`` runs.

        Inverse of :meth:`rle_flatten`.

        :raises ValueError: if ``flat`` has odd length (not whole runs).
        """
        if len(flat) % 2 != 0:
            raise ValueError(
                f"flat RLE stream must have even length (count, value pairs); "
                f"got length {len(flat)}"
            )
        return [(flat[i + 1], flat[i]) for i in range(0, len(flat), 2)]

    @staticmethod
    def encode_runs(values: "NDArray") -> list:
        """Vectorized count-first RLE of a 1D **numeric** array.

        The scalable counterpart to ``rle_flatten(rle_encode(...))``: run
        boundaries are found with ``numpy`` (``O(n)``, no per-element Python), so
        this handles infrastructure-scale streams (10^8 cells) in well under a
        second, where the ``groupby`` primitives would take minutes. Produces the
        identical ``[count, value, count, value, …]`` stream.

        Numeric only (int / float) — encode label payloads as integer codes
        first. Counts are promoted to int64 so they never overflow at scale.

        >>> Voxel.encode_runs(np.array([1, 1, 1, 0, 0, 1]))
        [3, 1, 2, 0, 1, 1]
        """
        arr = np.asarray(values).ravel()
        if arr.size == 0:
            return []
        change = np.flatnonzero(arr[1:] != arr[:-1]) + 1
        starts = np.concatenate(([0], change))
        ends = np.concatenate((change, [arr.size]))
        counts = (ends - starts).astype(np.int64)
        vals = arr[starts]
        out = np.empty(counts.size * 2, dtype=np.promote_types(vals.dtype, np.int64))
        out[0::2] = counts
        out[1::2] = vals
        return out.tolist()

    @staticmethod
    def decode_runs(flat: Sequence) -> "NDArray":
        """Vectorized inverse of :meth:`encode_runs` — count-first stream → dense
        1D array (via ``np.repeat``; scales to 10^8)."""
        arr = np.asarray(flat)
        if arr.size == 0:
            return arr
        if arr.size % 2 != 0:
            raise ValueError(
                f"flat RLE stream must have even length (count, value pairs); got {arr.size}"
            )
        counts = arr[0::2].astype(np.int64)
        values = arr[1::2]
        return np.repeat(values, counts)

    @staticmethod
    def compression_ratio(seq: Sequence) -> float:
        """Dense element count ÷ flat-RLE token count.

        ``> 1`` means RLE is smaller. Returns ``inf`` for an empty sequence
        (degenerate: zero tokens either way). A perfectly alternating sequence
        gives ``0.5`` (RLE doubles the size — the worst case, by design a
        per-layer tax only noisy layers pay; see spec §1.2).
        """
        dense = len(seq)
        runs = len(Voxel.rle_encode(seq))
        return dense / (runs * 2) if runs else float("inf")

    # ------------------------------------------------------------------ #
    # Canonical occupancy ordering (TM27: X fastest, then Y, then Z).
    # ------------------------------------------------------------------ #

    @staticmethod
    def mask_to_voxels(mask: "NDArray") -> list[int]:
        """3D occupancy mask ``(nx, ny, nz)`` → flat ``int`` list, X→Y→Z order.

        TM27 ``IfcVoxelGrid.Voxels`` is ordered "along X, then Y and finally Z"
        — i.e. the X index varies fastest. That is exactly Fortran/column-major
        ravel of an ``[x, y, z]``-indexed array (equivalent to the build-spec's
        ``reshape((nz, ny, nx)).transpose(2, 1, 0)`` round-trip, expressed more
        directly). Values are coerced to ``int`` (``1`` occupied, ``0`` empty)
        so the result is wrapper-authorable (see module docstring).

        :param mask: numpy array of shape ``(nx, ny, nz)``; bool or numeric
            (nonzero → occupied).
        :returns: flat list of ``0``/``1`` ints of length ``nx*ny*nz``.
        :raises ValueError: if ``mask`` is not 3-dimensional.
        """
        arr = np.asarray(mask)
        if arr.ndim != 3:
            raise ValueError(f"occupancy mask must be 3D (nx, ny, nz); got shape {arr.shape}")
        return (arr.ravel(order="F") != 0).astype(int).tolist()

    @staticmethod
    def voxels_to_mask(
        voxels: Sequence[int], nx: int, ny: int, nz: int
    ) -> "NDArray":
        """Flat X→Y→Z occupancy list → 3D ``bool`` mask ``(nx, ny, nz)``.

        Inverse of :meth:`mask_to_voxels`.

        :raises ValueError: if ``len(voxels) != nx*ny*nz``.
        """
        expected = nx * ny * nz
        if len(voxels) != expected:
            raise ValueError(
                f"voxel count {len(voxels)} != nx*ny*nz = {nx}*{ny}*{nz} = {expected}"
            )
        return np.asarray(voxels).reshape((nx, ny, nz), order="F") != 0

    # ------------------------------------------------------------------ #
    # Combined occupancy entry points (what Phase-3 IFC authoring calls).
    # ------------------------------------------------------------------ #

    @staticmethod
    def encode_occupancy(mask: "NDArray") -> list[int]:
        """3D occupancy mask → flat count-first RLE int stream for ``Voxels``.

        Ravels the mask X→Y→Z (TM27 order) to 0/1 ints and run-length encodes it
        with the vectorized :meth:`encode_runs`. This is the single "serialize
        this occupancy" call; :meth:`decode_occupancy` is its exact inverse given
        the grid dimensions. Output is identical to
        ``rle_flatten(rle_encode(mask_to_voxels(mask)))`` but scales to 10^8.
        """
        arr = np.asarray(mask)
        if arr.ndim != 3:
            raise ValueError(f"occupancy mask must be 3D (nx, ny, nz); got shape {arr.shape}")
        return Voxel.encode_runs((arr.ravel(order="F") != 0).astype(np.int8))

    @staticmethod
    def decode_occupancy(
        voxels_rle: Sequence[int], nx: int, ny: int, nz: int
    ) -> "NDArray":
        """Flat count-first RLE int stream → 3D ``bool`` mask ``(nx, ny, nz)``.

        Inverse of :meth:`encode_occupancy` (vectorized via :meth:`decode_runs`).

        :raises ValueError: if the decoded length != ``nx*ny*nz`` (the RLE
            stream is inconsistent with the stated grid dimensions).
        """
        dense = Voxel.decode_runs(voxels_rle)
        expected = nx * ny * nz
        if dense.size != expected:
            raise ValueError(
                f"decoded length {dense.size} != nx*ny*nz = {nx}*{ny}*{nz} = {expected}"
            )
        return dense.reshape((nx, ny, nz), order="F") != 0

    # ------------------------------------------------------------------ #
    # Phase 2: lattice construction (the shared grid for cut/fill).
    # ------------------------------------------------------------------ #

    @staticmethod
    def make_grid(
        origin: Sequence[float],
        size: Union[float, Sequence[float]],
        counts: Sequence[int],
    ) -> GridDef:
        """Construct a :class:`GridDef` from explicit origin / size / counts.

        :param size: scalar (isotropic) or ``(sx, sy, sz)``.
        """
        sx, sy, sz = (size, size, size) if np.isscalar(size) else tuple(size)
        return GridDef(tuple(origin), (sx, sy, sz), tuple(counts))

    @staticmethod
    def grid_from_bounds(
        min_xyz: Sequence[float],
        max_xyz: Sequence[float],
        cell_size: Union[float, Sequence[float]],
    ) -> GridDef:
        """Build the smallest :class:`GridDef` that fully covers ``[min, max]``.

        Counts are ``ceil(extent / size)`` per axis (≥ 1), so the lattice's
        ``max_corner`` is ``>=`` ``max_xyz``. ``origin = min_xyz``. This is the
        canonical way to derive a shared lattice spanning one or more surfaces
        (for cut/fill, pass bounds covering BOTH surfaces).
        """
        sx, sy, sz = (cell_size, cell_size, cell_size) if np.isscalar(cell_size) else tuple(cell_size)
        size = (float(sx), float(sy), float(sz))
        counts = []
        for lo, hi, s in zip(min_xyz, max_xyz, size):
            if hi < lo:
                raise ValueError(f"max ({hi}) < min ({lo}) on one axis")
            counts.append(max(1, int(np.ceil((float(hi) - float(lo)) / s))))
        return GridDef(tuple(float(v) for v in min_xyz), size, tuple(counts))

    @staticmethod
    def xyz_bounds(points: "NDArray") -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        """Axis-aligned ``(min_xyz, max_xyz)`` of an ``(N, 3)`` point array."""
        arr = np.asarray(points, dtype=float)
        if arr.ndim != 2 or arr.shape[1] != 3:
            raise ValueError(f"points must be (N, 3); got shape {arr.shape}")
        return tuple(arr.min(axis=0)), tuple(arr.max(axis=0))

    @staticmethod
    def grid_from_surface(
        surface: object,
        cell_size: Union[float, Sequence[float]],
        z_min: Optional[float] = None,
        z_max: Optional[float] = None,
    ) -> GridDef:
        """Convenience: a lattice covering ``surface.points`` (XY) and the Z
        range ``[z_min, z_max]`` (defaulting to the surface's own Z extent).

        For single-surface occupancy. Cut/fill should instead use
        :meth:`grid_from_bounds` over bounds spanning both surfaces so the
        shared-lattice invariant (:meth:`assert_shared_lattice`) holds.
        """
        (xmin, ymin, zmin_pts), (xmax, ymax, zmax_pts) = Voxel.xyz_bounds(surface.points)
        lo = (xmin, ymin, zmin_pts if z_min is None else float(z_min))
        hi = (xmax, ymax, zmax_pts if z_max is None else float(z_max))
        return Voxel.grid_from_bounds(lo, hi, cell_size)

    @staticmethod
    def assert_shared_lattice(a: GridDef, b: GridDef, tol: float = 1e-9) -> None:
        """Precondition check for cut/fill: ``a`` and ``b`` must be the same
        lattice (identical counts; origin/size equal within ``tol``).

        :raises ValueError: if the two grids are not voxel-for-voxel aligned —
            differencing masks across mismatched lattices is meaningless
            (spec §5.1 INVARIANT).
        """
        if a.counts != b.counts:
            raise ValueError(f"grid counts differ: {a.counts} vs {b.counts}")
        for label, va, vb in (("origin", a.origin, b.origin), ("size", a.size, b.size)):
            if any(abs(x - y) > tol for x, y in zip(va, vb)):
                raise ValueError(f"grid {label} differs beyond tol {tol}: {va} vs {vb}")

    @staticmethod
    def cell_centers(grid: GridDef) -> tuple["NDArray", "NDArray", "NDArray"]:
        """Per-axis 1D arrays of cell-centre coordinates ``(xs, ys, zs)``."""
        x0, y0, z0 = grid.origin
        sx, sy, sz = grid.size
        nx, ny, nz = grid.counts
        xs = x0 + (np.arange(nx) + 0.5) * sx
        ys = y0 + (np.arange(ny) + 0.5) * sy
        zs = z0 + (np.arange(nz) + 0.5) * sz
        return xs, ys, zs

    # ------------------------------------------------------------------ #
    # Phase 2: voxelization (TIN/surface -> occupancy mask).
    # ------------------------------------------------------------------ #

    @staticmethod
    def height_fn_from_z_at(z_at: Callable, surface: object) -> Callable:
        """Adapt a ``z_at(surface, x, y) -> float | None`` query (the shape of
        :meth:`tool.Surface.z_at`) into the vectorized height function
        :meth:`voxelize_below_surface` expects.

        Returns ``height_fn(xs, ys) -> z`` over equal-length 1D arrays, with
        ``np.nan`` where the surface is undefined (query outside every
        triangle). Takes the bound ``z_at`` *callable* (not the tool class) so
        it stays injectable in unit tests and serializable across the core
        boundary.
        """

        def height_fn(xs: "NDArray", ys: "NDArray") -> "NDArray":
            out = np.empty(len(xs), dtype=float)
            for i in range(len(xs)):
                z = z_at(surface, float(xs[i]), float(ys[i]))
                out[i] = np.nan if z is None else float(z)
            return out

        return height_fn

    @staticmethod
    def voxelize_surface(grid: GridDef, surface: object, supersample: int = 1) -> "NDArray":
        """Production wiring: rasterize a real :class:`CivilSurface` to occupancy
        by sampling :meth:`tool.Surface.z_at`.

        This is the single core-facing voxelization call (core passes only the
        serializable ``grid`` + ``surface``). It composes
        :meth:`height_fn_from_z_at` (over ``tool.Surface.z_at``) with
        :meth:`voxelize_below_surface`. Unit tests exercise those two pieces
        directly with analytic height functions; this method is covered by an
        integration test against a real ``tool.Surface``-built TIN.
        """
        import bonsai.tool as tool

        height_fn = Voxel.height_fn_from_z_at(tool.Surface.z_at, surface)
        return Voxel.voxelize_below_surface(grid, height_fn, supersample=supersample)

    @staticmethod
    def voxelize_below_surface(
        grid: GridDef,
        height_fn: Callable[["NDArray", "NDArray"], "NDArray"],
        supersample: int = 1,
    ) -> "NDArray":
        """Rasterize a surface to an occupancy mask: a cell is soil (TRUE) when
        it lies below the surface (spec §6 centre test).

        For ``supersample == 1`` (default): a cell is occupied iff its XY centre
        column's surface height exceeds the cell's Z centre. For
        ``supersample == s > 1``: each cell's XY footprint is sampled on an
        ``s × s`` sub-grid and a cell is occupied at level ``k`` iff a **majority**
        of the ``s²`` sub-columns are below the surface there (ties → occupied) —
        this reduces the stair-step bias on boundary cells without changing the
        boolean-occupancy semantics.

        ``height_fn`` must return ``np.nan`` where the surface is undefined;
        ``nan > z`` is ``False``, so columns outside the surface are air.

        :param height_fn: vectorized ``(xs, ys) -> z`` over 1D arrays (NaN = undefined).
        :returns: bool occupancy mask of shape ``grid.counts`` ``(nx, ny, nz)``,
            X→Y→Z indexable (feed to :meth:`encode_occupancy`).
        :raises ValueError: if ``supersample < 1``.

        Memory note: the intermediate comparison is ``O(nx·ny·s²·nz)`` booleans;
        for very large grids at ``s > 1`` this should be chunked (deferred).
        """
        s = int(supersample)
        if s < 1:
            raise ValueError(f"supersample must be >= 1, got {supersample}")

        x0, y0, z0 = grid.origin
        sx, sy, sz = grid.size
        nx, ny, nz = grid.counts

        xs = x0 + (np.arange(nx * s) + 0.5) * (sx / s)
        ys = y0 + (np.arange(ny * s) + 0.5) * (sy / s)
        zc = z0 + (np.arange(nz) + 0.5) * sz

        gx, gy = np.meshgrid(xs, ys, indexing="ij")  # (nx*s, ny*s)
        heights = np.asarray(height_fn(gx.ravel(), gy.ravel()), dtype=float).reshape(nx * s, ny * s)

        # Per-cell block of s*s subsample heights: (nx*s, ny*s) -> (nx, ny, s*s).
        per_cell = heights.reshape(nx, s, ny, s).transpose(0, 2, 1, 3).reshape(nx, ny, s * s)

        # Count subsamples below the surface at each Z level (NaN -> not below).
        below = per_cell[:, :, :, None] > zc[None, None, None, :]  # (nx, ny, s*s, nz)
        counts = below.sum(axis=2)  # (nx, ny, nz)
        return counts * 2 >= (s * s)  # majority vote; s==1 -> plain centre test

    @staticmethod
    def occupancy_volume(grid: GridDef, mask: "NDArray") -> float:
        """Soil volume of an occupancy ``mask`` on ``grid`` = count(TRUE) × cell
        volume (spec §5.1)."""
        return int(np.asarray(mask, dtype=bool).sum()) * grid.cell_volume

    # ------------------------------------------------------------------ #
    # Phase 4: cut/fill as occupancy set-ops (spec §5.1).
    # ------------------------------------------------------------------ #

    @staticmethod
    def shared_grid(
        surfaces: Sequence[object],
        cell_size: Union[float, Sequence[float]],
        z_min: Optional[float] = None,
        z_max: Optional[float] = None,
    ) -> GridDef:
        """Build the single lattice that covers ALL ``surfaces`` — the shared
        lattice cut/fill differencing requires (spec §5.1 INVARIANT).

        Existing-state and design-state surfaces MUST be voxelized onto the same
        grid or their masks can't be differenced cell-for-cell. This unions the
        surfaces' XY (and Z, unless overridden) bounds and builds one grid.

        :param z_min/z_max: optional common Z span (e.g. a base datum below both
            surfaces); default to the combined Z extent of all surfaces' points.
        """
        if not surfaces:
            raise ValueError("shared_grid needs at least one surface")
        bounds = [Voxel.xyz_bounds(s.points) for s in surfaces]
        mins = [b[0] for b in bounds]
        maxs = [b[1] for b in bounds]
        lo = (
            min(m[0] for m in mins),
            min(m[1] for m in mins),
            min(m[2] for m in mins) if z_min is None else float(z_min),
        )
        hi = (
            max(m[0] for m in maxs),
            max(m[1] for m in maxs),
            max(m[2] for m in maxs) if z_max is None else float(z_max),
        )
        return Voxel.grid_from_bounds(lo, hi, cell_size)

    @staticmethod
    def cut_fill_masks(existing_mask: "NDArray", design_mask: "NDArray") -> dict:
        """Boolean cut / fill masks between two occupancy states on one lattice.

        - ``cut``  = ``existing & ~design`` — soil → air (excavation).
        - ``fill`` = ``~existing & design`` — air → soil (embankment).

        :raises ValueError: if the two masks don't share a shape.
        """
        existing = np.asarray(existing_mask, dtype=bool)
        design = np.asarray(design_mask, dtype=bool)
        if existing.shape != design.shape:
            raise ValueError(
                f"existing/design masks must share shape (same lattice); "
                f"got {existing.shape} vs {design.shape}"
            )
        return {"cut": existing & ~design, "fill": ~existing & design}

    @staticmethod
    def cut_fill(existing_mask: "NDArray", design_mask: "NDArray", grid: GridDef) -> dict:
        """Cut / fill / net volumes between existing- and design-state occupancy.

        Counting, not calculus (spec §intro): ``cut`` = (soil→air cells) × cell
        volume, ``fill`` = (air→soil cells) × cell volume, ``net = fill - cut``
        (positive ⇒ import / embankment-dominant, negative ⇒ export). Overhangs
        and disconnected pockets need no special handling.

        Both masks must be on ``grid`` (shape == ``grid.counts``) — enforced as
        the shared-lattice precondition.

        :raises ValueError: if either mask's shape != ``grid.counts``.
        """
        existing = np.asarray(existing_mask, dtype=bool)
        design = np.asarray(design_mask, dtype=bool)
        counts = tuple(grid.counts)
        if existing.shape != counts or design.shape != counts:
            raise ValueError(
                f"masks {existing.shape} / {design.shape} must match grid counts "
                f"{counts} (cut/fill requires a shared lattice)"
            )
        masks = Voxel.cut_fill_masks(existing, design)
        vcell = grid.cell_volume
        cut = int(masks["cut"].sum()) * vcell
        fill = int(masks["fill"].sum()) * vcell
        return {"cut": cut, "fill": fill, "net": fill - cut}

    @staticmethod
    def bulk(volume: float, factor: float) -> float:
        """Apply a shrink/swell bulking factor to a bank volume.

        ``loose = undisturbed × swell_factor``; ``compacted = loose ×
        shrink_factor``. A trivial multiply kept in the tool layer so core stays
        arithmetic-free.
        """
        return float(volume) * float(factor)

    # ------------------------------------------------------------------ #
    # Phase 4b: author the IFC 4.4 voxel sidecar (wraps ifcopenshell.api.voxel).
    # ------------------------------------------------------------------ #

    @staticmethod
    def new_sidecar() -> "ifcopenshell.file":
        """Create a fresh, bootstrapped IFC 4.4 voxel sidecar file.

        Wraps :func:`ifcopenshell.api.voxel.new_file` (registers the prototype
        ``IFC4X4_TM27`` schema on first use). The production model stays
        IFC4X3_ADD2; voxel grids live here.
        """
        import ifcopenshell.api.voxel as api_voxel

        return api_voxel.new_file()

    @staticmethod
    def author_earthwork(
        sidecar_file: "ifcopenshell.file",
        grid: GridDef,
        mask: "NDArray",
        *,
        host_class: str,
        predefined_type: str,
        name: str,
        bank_volume: float,
        source_surface_guid: Optional[str] = None,
        swell_factor: float = 1.0,
    ) -> "ifcopenshell.entity_instance":
        """Author one voxel earthwork element into the sidecar: host + RLE
        occupancy grid + base quantities.

        RLE-encodes ``mask`` (:meth:`encode_occupancy`), creates the
        ``IfcEarthworksCut`` / ``IfcEarthworksFill`` host carrying that grid
        (:func:`ifcopenshell.api.voxel.create_voxel_earthwork`), and writes
        ``Qto_Earthworks*BaseQuantities`` with ``bank_volume`` and the swelled
        ``loose`` volume (:func:`ifcopenshell.api.voxel.write_earthwork_quantities`).

        :param grid: the shared lattice (:class:`GridDef`); its ``size`` /
            ``counts`` define the ``IfcVoxelGrid`` dimensions.
        :param mask: the occupancy region for this element (e.g. the cut or fill
            mask from :meth:`cut_fill_masks`).
        :param bank_volume: in-place volume (m³) — the ``cut`` or ``fill`` value.
        :param source_surface_guid: production-model surface GlobalId for the
            cross-file link.
        :returns: the created earthwork host entity.
        """
        import ifcopenshell.api.voxel as api_voxel

        occupancy = Voxel.encode_occupancy(mask)
        host, _grid = api_voxel.create_voxel_earthwork(
            sidecar_file,
            name=name,
            voxel_sizes=grid.size,
            voxel_counts=grid.counts,
            occupancy=occupancy,
            host_class=host_class,
            predefined_type=predefined_type,
            source_surface_guid=source_surface_guid,
        )
        api_voxel.write_earthwork_quantities(
            sidecar_file,
            host,
            bank_volume=bank_volume,
            loose_volume=Voxel.bulk(bank_volume, swell_factor),
        )
        return host

    # ------------------------------------------------------------------ #
    # Phase 6: Blender preview (disposable cube meshes from masks).
    # ------------------------------------------------------------------ #

    #: Viewport colors per known mask role (RGBA).
    PREVIEW_COLORS = {
        "occupancy": (0.20, 0.70, 0.30, 1.0),  # green
        "cut": (0.85, 0.20, 0.20, 1.0),  # red
        "fill": (0.20, 0.45, 0.85, 1.0),  # blue
    }

    #: Fallback palette cycled for arbitrary (e.g. per-stratum) mask names.
    PREVIEW_PALETTE = [
        (0.80, 0.52, 0.30, 1.0),  # ochre / clay
        (0.93, 0.82, 0.45, 1.0),  # sand
        (0.55, 0.62, 0.40, 1.0),  # silt / green-grey
        (0.45, 0.55, 0.70, 1.0),  # blue-grey
        (0.62, 0.42, 0.45, 1.0),  # marl
        (0.70, 0.70, 0.72, 1.0),  # rock / grey
    ]

    #: Cap on occupied cells per mask in a preview (keeps mesh build snappy).
    PREVIEW_CELL_CAP = 250_000

    # Cube corner offsets (unit cube, indexed by dx + 2*dy + 4*dz) and faces.
    _CUBE_CORNERS = np.array(
        [[dx, dy, dz] for dz in (0, 1) for dy in (0, 1) for dx in (0, 1)], dtype=float
    )
    _CUBE_FACES = np.array(
        [[0, 1, 3, 2], [4, 5, 7, 6], [0, 1, 5, 4], [2, 3, 7, 6], [0, 2, 6, 4], [1, 3, 7, 5]]
    )

    PREVIEW_COLLECTION = "Saikei Voxel Preview"

    @staticmethod
    def create_preview_mesh(grid: GridDef, masks: dict) -> list:
        """Build disposable Blender cube meshes from occupancy masks.

        One merged mesh object per entry in ``masks`` (``{"cut": mask, "fill":
        mask}`` or ``{"occupancy": mask}``): each occupied cell becomes a box at
        its lattice position, colored per :attr:`PREVIEW_COLORS`. Objects are
        tagged ``["saikei_voxel_preview"]`` and linked under a dedicated
        collection so :meth:`clear_preview` can remove them. Replaces any prior
        preview first.

        This is a *disposable derived cache* (the IFC/grid is the source of
        truth) — regenerate any time from the grid + masks.

        :raises ValueError: if a mask has more than :attr:`PREVIEW_CELL_CAP`
            occupied cells (use a larger ``cell_size``).
        """
        import bpy

        Voxel.clear_preview()
        origin = np.asarray(grid.origin, dtype=float)
        size = np.asarray(grid.size, dtype=float)

        scene_coll = bpy.context.scene.collection
        coll = bpy.data.collections.get(Voxel.PREVIEW_COLLECTION)
        if coll is None:
            coll = bpy.data.collections.new(Voxel.PREVIEW_COLLECTION)
        if coll.name not in scene_coll.children:
            scene_coll.children.link(coll)

        created = []
        for idx, (name, mask) in enumerate(masks.items()):
            occ = np.argwhere(np.asarray(mask, dtype=bool))
            if occ.shape[0] == 0:
                continue
            if occ.shape[0] > Voxel.PREVIEW_CELL_CAP:
                raise ValueError(
                    f"preview '{name}' has {occ.shape[0]:,} occupied cells "
                    f"(> cap {Voxel.PREVIEW_CELL_CAP:,}); increase cell_size"
                )
            count = occ.shape[0]
            base = origin + occ.astype(float) * size  # (M, 3) cell min corners
            verts = (base[:, None, :] + Voxel._CUBE_CORNERS[None, :, :] * size).reshape(-1, 3)
            faces = (Voxel._CUBE_FACES[None, :, :] + (np.arange(count)[:, None, None] * 8)).reshape(-1, 4)

            # Known roles keep their semantic color; everything else (strata)
            # cycles the palette by insertion order.
            color = Voxel.PREVIEW_COLORS.get(name) or Voxel.PREVIEW_PALETTE[idx % len(Voxel.PREVIEW_PALETTE)]
            mesh = bpy.data.meshes.new(f"SaikeiVoxel_{name}")
            mesh.from_pydata(verts.tolist(), [], faces.tolist())
            mesh.update()
            material = bpy.data.materials.new(f"SaikeiVoxel_{name}")
            material.diffuse_color = color
            mesh.materials.append(material)

            obj = bpy.data.objects.new(f"Voxel {name.capitalize()}", mesh)
            obj["saikei_voxel_preview"] = True
            obj.color = color
            coll.objects.link(obj)
            created.append(obj.name)
        return created

    @staticmethod
    def clear_preview() -> int:
        """Remove all Saikei voxel-preview objects (and the empty collection).

        Returns the number of objects removed. Idempotent.
        """
        import bpy

        removed = 0
        for obj in list(bpy.data.objects):
            if obj.get("saikei_voxel_preview"):
                bpy.data.objects.remove(obj, do_unlink=True)
                removed += 1
        coll = bpy.data.collections.get(Voxel.PREVIEW_COLLECTION)
        if coll is not None and not coll.objects:
            bpy.data.collections.remove(coll)
        return removed

    # ------------------------------------------------------------------ #
    # Phase 5: stratum / geomodel (semantic layers from boundary surfaces).
    # ------------------------------------------------------------------ #

    @staticmethod
    def order_surfaces_by_elevation(surfaces: Sequence[object]) -> list:
        """Order surfaces top → bottom by mean point elevation (descending).

        Stratigraphic boundaries are ordered by elevation; the geomodel
        classifier (:meth:`classify_strata`) assumes this top-down order.
        """
        return sorted(surfaces, key=lambda s: -float(np.asarray(s.points)[:, 2].mean()))

    @staticmethod
    def strata_legend(ordered_surfaces: Sequence[object]) -> dict:
        """Map each stratum code (1-based) to the name of its top boundary surface.

        ``N`` ordered surfaces define ``N-1`` strata: stratum ``k`` lies between
        ``surfaces[k-1]`` (top) and ``surfaces[k]`` (bottom), so it is named after
        ``surfaces[k-1]``.
        """
        names = [getattr(s, "name", f"surface_{i}") for i, s in enumerate(ordered_surfaces)]
        return {k: names[k - 1] for k in range(1, len(names))}

    @staticmethod
    def classify_strata(grid: GridDef, height_fields: Sequence["NDArray"]) -> "NDArray":
        """Classify each cell into a stratum code from ordered boundary height fields.

        ``height_fields`` are ``(nx, ny)`` arrays (NaN where undefined), ordered
        top → bottom. A cell's code = the number of boundary surfaces above its
        centre: ``0`` = above the top surface (air), ``1..N-1`` = stratum index,
        and cells below the bottom surface (count ``N``) are set to ``0``
        (unmodeled). Injectable counterpart of :meth:`voxelize_strata`.

        :raises ValueError: with fewer than 2 surfaces, or a field shape that
            doesn't match ``grid``'s XY.
        """
        nx, ny, nz = grid.counts
        stacked = np.stack([np.asarray(h, dtype=float) for h in height_fields], axis=0)
        n_surfaces = stacked.shape[0]
        if n_surfaces < 2:
            raise ValueError("need >= 2 boundary surfaces (>= 1 stratum)")
        if stacked.shape[1:] != (nx, ny):
            raise ValueError(f"height fields must be {(nx, ny)}; got {stacked.shape[1:]}")
        _, _, zc = Voxel.cell_centers(grid)
        # Count surfaces above each cell centre (NaN > z is False -> not counted).
        above = stacked[:, :, :, None] > zc[None, None, None, :]  # (N, nx, ny, nz)
        code = above.sum(axis=0).astype(np.int16)  # (nx, ny, nz) in 0..N
        code[code == n_surfaces] = 0  # below the bottom boundary -> unmodeled
        return code

    @staticmethod
    def voxelize_strata(grid: GridDef, surfaces: Sequence[object], supersample: int = 1) -> "NDArray":
        """Classify a stratum-code layer from real surfaces (wires tool.Surface.z_at).

        Production counterpart of :meth:`classify_strata`: samples each surface's
        ``z_at`` over cell-centre XY to build the height fields, then classifies.
        ``surfaces`` must be ordered top → bottom (see
        :meth:`order_surfaces_by_elevation`). ``supersample`` is accepted for API
        symmetry but classification is currently cell-centre based.
        """
        import bonsai.tool as tool

        nx, ny, _ = grid.counts
        xs, ys, _ = Voxel.cell_centers(grid)
        gx, gy = np.meshgrid(xs, ys, indexing="ij")
        fx, fy = gx.ravel(), gy.ravel()
        fields = []
        for surface in surfaces:
            height_fn = Voxel.height_fn_from_z_at(tool.Surface.z_at, surface)
            fields.append(height_fn(fx, fy).reshape(nx, ny))
        return Voxel.classify_strata(grid, fields)

    @staticmethod
    def gather_occupied(values: "NDArray", mask: "NDArray") -> "NDArray":
        """Gather ``values`` at occupied cells in canonical X→Y→Z order.

        TM27 payloads in occupancy mode store one value per occupied cell; this
        produces that gathered list aligned to :meth:`encode_occupancy`'s order.
        """
        flat_values = np.asarray(values).ravel(order="F")
        flat_mask = np.asarray(mask, dtype=bool).ravel(order="F")
        return flat_values[flat_mask]

    @staticmethod
    def stratum_volume(grid: GridDef, code_layer: "NDArray", target_code: int) -> float:
        """Volume of one stratum = count(cells where code == target) × cell volume (spec §5.2)."""
        return int((np.asarray(code_layer) == target_code).sum()) * grid.cell_volume

    @staticmethod
    def stratum_volumes(grid: GridDef, code_layer: "NDArray") -> dict:
        """Volume per stratum code present (excluding 0 = unmodeled): ``{code: m³}``."""
        arr = np.asarray(code_layer)
        vcell = grid.cell_volume
        return {int(c): int((arr == c).sum()) * vcell for c in np.unique(arr) if c > 0}

    @staticmethod
    def author_geomodel(
        sidecar_file: "ifcopenshell.file",
        grid: GridDef,
        code_layer: "NDArray",
        legend: dict,
        *,
        name: str,
        source_surface_guids: Optional[Sequence[str]] = None,
    ) -> "ifcopenshell.entity_instance":
        """Author an IfcGeomodel with an occupancy grid + an integer-coded,
        RLE stratum layer (and a code→material legend) into the sidecar.

        Occupancy = cells with a stratum (code > 0); the stratum codes are
        gathered over occupied cells (TM27 occupancy-mode payload) and RLE-
        encoded into an ``IfcIntegerVoxelData`` named ``StratumCode``.
        """
        import ifcopenshell.api.voxel as api_voxel

        code = np.asarray(code_layer, dtype=np.int16)
        occupancy = code > 0
        host = api_voxel.create_voxel_geomodel(
            sidecar_file,
            name=name,
            voxel_sizes=grid.size,
            voxel_counts=grid.counts,
            occupancy=Voxel.encode_occupancy(occupancy),
            source_surface_guids=source_surface_guids,
            legend=legend,
        )
        api_voxel.add_voxel_data(
            sidecar_file,
            host,
            value_data=Voxel.encode_runs(Voxel.gather_occupied(code, occupancy)),
            data_type="integer",
            value_type="IfcInteger",
            name="StratumCode",
        )
        return host

    @staticmethod
    def cut_fill_by_stratum(cut_mask: "NDArray", code_layer: "NDArray", grid: GridDef) -> dict:
        """Excavation volume split by native stratum: ``{stratum_code: m³}``.

        Intersects the cut (soil→air) region with the stratum classification on a
        **shared lattice** — each excavated cell belongs to exactly one native
        stratum, so the answer is a masked count per code. This is the per-material
        excavation quantity an estimator needs (rock vs clay disposal/cost), and
        is trivial in the occupancy model (vs clipping prisms against stratum
        solids in the boundary method).

        :raises ValueError: if the masks don't both match ``grid.counts``.
        """
        cut = np.asarray(cut_mask, dtype=bool)
        code = np.asarray(code_layer)
        counts = tuple(grid.counts)
        if cut.shape != counts or code.shape != counts:
            raise ValueError(
                f"cut mask {cut.shape} and code layer {code.shape} must match grid "
                f"counts {counts} (per-stratum cut requires a shared lattice)"
            )
        vcell = grid.cell_volume
        cut_codes = code[cut]  # stratum code of each excavated cell
        return {
            int(k): int((cut_codes == k).sum()) * vcell
            for k in np.unique(cut_codes)
            if k > 0
        }

    @staticmethod
    def intersect_codes(code_layer: "NDArray", mask: "NDArray") -> "NDArray":
        """Codes kept where ``mask`` is True, zeroed elsewhere — e.g. the stratum
        codes restricted to the cut region, for a per-material excavation preview."""
        code = np.asarray(code_layer)
        return np.where(np.asarray(mask, dtype=bool), code, 0).astype(code.dtype)

    @staticmethod
    def create_strata_preview(grid: GridDef, code_layer: "NDArray", legend: Optional[dict] = None) -> list:
        """Build a Blender preview with one palette-colored mesh per stratum."""
        arr = np.asarray(code_layer)
        legend = legend or {}
        masks = {}
        for code in np.unique(arr):
            if code <= 0:
                continue
            label = legend.get(int(code), f"stratum_{int(code)}")
            masks[label] = arr == code
        return Voxel.create_preview_mesh(grid, masks)

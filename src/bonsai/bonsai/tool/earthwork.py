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

"""Saikei earthwork tool — math, IFC authoring, Blender object linkage.

Phase 6 of the Saikei grading/earthwork sprint. This module owns:

- :class:`VolumeResult` data primitive per spec §6.4 — carries the
  cut / fill volumes plus the closed-solid geometry that gets
  authored to IFC as :class:`IfcEarthworksCut` / :class:`IfcEarthworksFill`
  PolygonalFaceSet bodies.
- TIN-to-TIN prismoidal volume math per spec §6.4 — the canonical
  cut/fill calculation against an existing-vs-proposed surface pair.
- Cut/fill region extraction and closed-solid construction per spec
  §6.5 — turns a sub-triangle delta-Z field into watertight
  PolygonalFaceSet bodies that round-trip through IFC.
- IFC authoring wrappers around :mod:`ifcopenshell.api.earthwork`
  (Phase 3) — handles spatial containment under :class:`IfcSite`,
  :class:`IfcRelVoidsElement` linkage to the host terrain, and
  pre-computed quantity-set authoring (``Qto_EarthworksCut/FillBaseQuantities``,
  ``Pset_SaikeiGradingShrinkSwell``).
- Shrink/swell handling per spec §6.4 — caller supplies factors;
  this module multiplies through to ``LooseVolume`` and writes both
  the Qto and the pset consistently (closes the audit gap where
  ``LooseVolume`` was a pass-through value rather than computed from
  ``UndisturbedVolume × SwellFactor``).
- Blender mesh linkage for the cut/fill solids and the optional
  cut/fill color-map overlay — same pattern as :class:`bonsai.tool.surface`.

The tool layer is the only Saikei layer that imports ``numpy`` /
``shapely`` / ``bpy``. Core stays import-clean (only built-ins +
``ifcopenshell``); UI calls into core which calls into tool.

Subsequent commits land the prismoidal volume algorithm, the
closed-solid construction stages, and the IFC + Blender authoring
wrappers. This commit lands the dataclasses
(:class:`SubTriangle`, :class:`ClosedSolid`, :class:`VolumeResult`)
that the rest of the module references.
"""

from __future__ import annotations

import ifcopenshell
import numpy as np
from dataclasses import dataclass, field
from typing import Optional


# Cubic-yards conversion factor (1 m³ = 1.30795 cu yd). Used by the
# imperial-units convenience attributes on :class:`VolumeResult`. Civil
# engineers in the US specify earthwork in cubic yards; metric engineers
# in m³. Authoring stores m³ canonically; the cubic-yard fields are
# read-only views.
_M3_TO_CUBIC_YARDS = 1.307950619314


@dataclass
class SubTriangle:
    """A piece of the TIN-intersection grid used by §6.4 prismoidal
    volume math. Each sub-triangle is the XY intersection of one
    existing-surface triangle, one proposed-surface triangle, and the
    volume domain (existing.outer_boundary ∩ proposed.outer_boundary
    minus holes/voids).

    The signed contribution to total cut volume is
    ``area_m2 * (z_existing_avg - z_proposed_avg)``; positive means
    cut, negative means fill. Per-sub-triangle deltas survive into
    :class:`VolumeResult.per_triangle_deltas` for the optional cut/fill
    color map.
    """

    vertices_xy: np.ndarray
    """``(3, 2)`` array of XY coordinates. Z is reconstructed by
    linearly interpolating the host surfaces — keeping Z out of this
    structure avoids the round-trip noise of carrying it separately
    for two surfaces."""

    z_existing_avg: float
    """Average existing-surface Z over the sub-triangle (mean of the
    three vertex elevations interpolated on the existing TIN)."""

    z_proposed_avg: float
    """Average proposed-surface Z over the sub-triangle."""

    area_m2: float
    """XY-projected area of the sub-triangle, in project units squared
    (m² when the project is metric)."""

    @property
    def delta_z(self) -> float:
        """``z_existing_avg - z_proposed_avg``. Positive = cut
        (existing above proposed → excavate); negative = fill
        (existing below proposed → place fill); zero = at-grade."""
        return self.z_existing_avg - self.z_proposed_avg

    @property
    def signed_volume_m3(self) -> float:
        """Signed prismoidal volume contribution. Sign matches
        :attr:`delta_z`."""
        return self.area_m2 * self.delta_z


@dataclass
class ClosedSolid:
    """Watertight solid geometry ready for :class:`IfcPolygonalFaceSet`
    authoring. The cut and fill solids each become one of these.

    The contract for "watertight" is: every edge in :attr:`faces`
    appears in exactly two faces. Phase 3's
    :func:`ifcopenshell.api.earthwork.create_earthworks_cut` accepts
    these and authors a ``Closed=TRUE`` PolygonalFaceSet directly;
    no further tessellation runs at the IFC API boundary.
    """

    points: np.ndarray
    """``(N, 3)`` array of XYZ vertex coordinates. Indices into this
    array are 0-based on the dataclass surface; the IFC API converts
    to the IFC 1-based convention internally."""

    faces: list[list[int]]
    """List of vertex-index lists. Each face must have ≥ 3 vertices
    (triangles, quads, higher n-gons all valid). Caller is responsible
    for the watertight invariant — Phase 6's
    :meth:`Earthwork.build_cut_solid` / :meth:`build_fill_solid`
    construct these in §6.5's named stages."""


@dataclass
class VolumeResult:
    """Output of a TIN-to-TIN prismoidal volume calculation per spec §6.4.

    Volumes are written to standard IFC quantity sets via Phase 3's
    earthwork API:

    - ``Qto_EarthworksCutBaseQuantities``: ``UndisturbedVolume``,
      ``LooseVolume``, ``Weight``
    - ``Qto_EarthworksFillBaseQuantities``: ``CompactedVolume``,
      ``LooseVolume``

    Shrink/swell factors are written to
    ``Pset_SaikeiGradingShrinkSwell`` (Saikei custom pset, not in the
    IFC 4.3 standard pset library). The spec audit explicitly required
    that ``loose_cut_m3`` be derived from
    ``undisturbed_cut_m3 × swell_factor`` rather than carried as an
    independent input — this dataclass enforces that via
    :meth:`__post_init__`.
    """

    existing_surface_guid: str
    """GUID of the existing-ground :class:`bonsai.tool.surface.CivilSurface`."""

    proposed_surface_guid: str
    """GUID of the proposed-ground :class:`CivilSurface`. May be a
    Phase 5 group composite."""

    undisturbed_cut_m3: float
    """In-situ cut volume — the "bank" cubic-yardage in US parlance
    or "undisturbed" per IFC 4.3. Positive magnitude; never signed."""

    compacted_fill_m3: float
    """In-place compacted fill volume. Positive magnitude. The
    engineering takeoff number for fill quantities."""

    shrink_factor: float = 1.0
    """Fill-side shrinkage ratio (compacted / bank). Caller-supplied;
    typical values 0.85–0.95 depending on soil type. ``1.0`` means
    no shrinkage. Used by Phase 6 callers that need the bank-volume
    of fill source material."""

    swell_factor: float = 1.0
    """Cut-side swell ratio (loose / bank). Caller-supplied; typical
    values 1.10–1.30 depending on soil type. ``1.0`` means no swell.
    Multiplied through to :attr:`loose_cut_m3` in :meth:`__post_init__`
    so the Qto is internally consistent — closes the spec audit gap
    where ``LooseVolume`` was a pass-through value."""

    cut_solid: Optional[ClosedSolid] = None
    """Closed-solid geometry for the cut. Authored as
    :class:`IfcEarthworksCut` body (PolygonalFaceSet, Closed=TRUE).
    None until §6.5's solid construction runs; Phase 6 commit 5
    populates this."""

    fill_solid: Optional[ClosedSolid] = None
    """Closed-solid geometry for the fill. Authored as
    :class:`IfcEarthworksFill` body. None until §6.5's solid
    construction runs."""

    per_triangle_deltas: Optional[np.ndarray] = None
    """Optional ``(N,)`` array of per-sub-triangle ``delta_z`` values
    for the cut/fill color map. Aligned with the sub-triangle order
    out of the §6.4 intersection. ``None`` if the caller didn't request
    the color map."""

    ifc_cut_id: Optional[int] = None
    """Step id of the persisted :class:`IfcEarthworksCut`. Stamped by
    :meth:`Earthwork.author_cut_solid` after IFC authoring runs."""

    ifc_fill_id: Optional[int] = None
    """Step id of the persisted :class:`IfcEarthworksFill`."""

    guid: str = field(default_factory=ifcopenshell.guid.new)
    """Stable identifier for the registry. Volume results are keyed
    by GUID rather than by surface-pair GUIDs so multiple volume
    calculations against the same pair (e.g., before/after a
    shrink/swell adjustment) coexist."""

    def __post_init__(self) -> None:
        """Validate and propagate derived quantities.

        - ``undisturbed_cut_m3`` and ``compacted_fill_m3`` must be
          non-negative (volumes are magnitudes; signedness is
          captured by the cut-vs-fill split).
        - ``shrink_factor`` and ``swell_factor`` must be positive
          (a zero or negative factor would produce nonsense quantities).
        """
        if self.undisturbed_cut_m3 < 0:
            raise ValueError(
                f"undisturbed_cut_m3 must be ≥ 0; got {self.undisturbed_cut_m3}"
            )
        if self.compacted_fill_m3 < 0:
            raise ValueError(
                f"compacted_fill_m3 must be ≥ 0; got {self.compacted_fill_m3}"
            )
        if self.shrink_factor <= 0:
            raise ValueError(
                f"shrink_factor must be > 0; got {self.shrink_factor}"
            )
        if self.swell_factor <= 0:
            raise ValueError(
                f"swell_factor must be > 0; got {self.swell_factor}"
            )

    @property
    def loose_cut_m3(self) -> float:
        """Loose / bulked / swelled volume of cut material —
        ``undisturbed_cut_m3 × swell_factor``. The "haul" volume in
        construction parlance: how much truck space the excavated
        material occupies before recompaction."""
        return self.undisturbed_cut_m3 * self.swell_factor

    @property
    def bank_fill_m3(self) -> float:
        """Bank-volume equivalent of the placed fill —
        ``compacted_fill_m3 / shrink_factor``. The "borrow" quantity
        if the fill must be sourced from a bank-volume measured site
        (offsite borrow pit, balanced-haul calculation)."""
        return self.compacted_fill_m3 / self.shrink_factor

    @property
    def net_volume_m3(self) -> float:
        """``undisturbed_cut_m3 - compacted_fill_m3``. Positive = net
        excavation (haul-off site); negative = net import (borrow);
        zero = balanced earthwork. The single most-asked-for number
        in any earthwork report."""
        return self.undisturbed_cut_m3 - self.compacted_fill_m3

    @property
    def cut_cubic_yards(self) -> float:
        """Imperial-units convenience: ``undisturbed_cut_m3``
        converted to cubic yards (1 m³ = 1.307950619 cu yd)."""
        return self.undisturbed_cut_m3 * _M3_TO_CUBIC_YARDS

    @property
    def fill_cubic_yards(self) -> float:
        """Imperial-units convenience: ``compacted_fill_m3`` in cu yd."""
        return self.compacted_fill_m3 * _M3_TO_CUBIC_YARDS

    @property
    def net_cubic_yards(self) -> float:
        """Imperial-units convenience: ``net_volume_m3`` in cu yd."""
        return self.net_volume_m3 * _M3_TO_CUBIC_YARDS


class SaikeiEarthworkError(Exception):
    """Base exception for tool.Earthwork failures.

    Volume-math edge cases (zero-domain intersection, degenerate
    triangulation) and solid-construction failures (non-manifold
    geometry, watertightness violations) raise this so operators can
    catch a single typed exception and report cleanly.

    Subclasses may be added in future commits as specific failure
    modes need finer-grained handling (mirroring
    :class:`bonsai.tool.grading.SaikeiGradingError` family).
    """


class Earthwork:
    """Earthwork tool surface — Phase 6 entry point.

    Per :class:`bonsai.tool.surface.Surface` and
    :class:`bonsai.tool.grading.Grading` precedents, all methods are
    classmethods (no instance state); per-file caches live in
    :attr:`_registry` keyed by ``(id(ifc_file), guid)``.

    Subsequent commits flesh this out with the prismoidal volume
    method, the cut/fill solid constructors, and the IFC authoring
    wrappers around :mod:`ifcopenshell.api.earthwork`.
    """

    _registry: dict[tuple[int, str], object] = {}
    """Per spec §4.6: lazy-rehydrating cache keyed by ``(id(ifc_file),
    guid)``. Stores :class:`VolumeResult` instances once Phase 6
    commit 2 lands the dataclass. Headless tests call :meth:`clear`
    in autouse teardown to prevent cross-test contamination."""

    @classmethod
    def clear(cls) -> None:
        """Wipe the entire registry. Headless test teardown calls
        this to prevent cross-test contamination."""
        cls._registry.clear()

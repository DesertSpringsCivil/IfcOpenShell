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

Subsequent commits land the :class:`VolumeResult` dataclass, the
prismoidal volume algorithm, the closed-solid construction stages,
and the IFC + Blender authoring wrappers. This scaffold lands the
package shell + the typed exception so the rest of the module can
reference it without circular imports.
"""

from __future__ import annotations


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

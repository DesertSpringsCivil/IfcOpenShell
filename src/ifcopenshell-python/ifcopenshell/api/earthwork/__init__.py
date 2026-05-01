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

"""High-level API for authoring earthwork-volume IFC 4.3 entities.

Persists cut and fill volumes as :class:`IfcEarthworksCut` /
:class:`IfcEarthworksFill` entities with closed
:class:`IfcPolygonalFaceSet` body representations, the standard
``Qto_Earthworks*BaseQuantities``, the Saikei
``Pset_SaikeiGradingShrinkSwell``, and OmniClass Table 22
classifications. Phase 3 of the Saikei grading/earthwork sprint;
depends on Phase 1 (``ifcopenshell.api.surface``) for terrain authoring
and Phase 2 (``ifcopenshell.api.grading``) for the de-facto civil-
engineering shared helper module.

The API persists what it's given — the prismoidal-volume math (spec
§6.4) and watertight closed-solid construction (spec §6.5) live in
Bonsai's ``tool.Earthwork`` (Phase 6). Watertightness, manifold
topology, and signed-volume agreement are NOT verified here; the
calling code is responsible for them.

Entity tree authored
====================

For an excavation+fill scenario:

- :class:`IfcEarthworksCut` (the act of excavation)

  - Identity placement, contained in :class:`IfcSite`
  - :class:`IfcPolygonalFaceSet` (Closed=TRUE) body representation
    (RepresentationIdentifier="Body", RepresentationType="Tessellation")
  - ``Pset_EarthworksCutCommon`` (Status="NEW")
  - OmniClass Table 22 classification (default ``22-07 31 16``
    Excavation and Fill; overridable)
  - :class:`IfcRelVoidsElement` to host terrain
    (typically an :class:`IfcGeographicElement[TERRAIN]` from Phase 1)
  - ``Qto_EarthworksCutBaseQuantities`` with Length / Width / Depth
    (IfcQuantityLength), UndisturbedVolume / LooseVolume
    (IfcQuantityVolume), Weight (IfcQuantityWeight)
  - ``Pset_SaikeiGradingShrinkSwell`` with ShrinkFactor / SwellFactor

- :class:`IfcEarthworksFill` (the placed fill material)

  - Identity placement, contained in :class:`IfcSite`
  - PredefinedType in the volume-bearing range:
    ``BACKFILL`` / ``COUNTERWEIGHT`` / ``EMBANKMENT`` (default) /
    ``SUBGRADEBED`` / ``TRANSITIONSECTION``. Phase 2's surface fills
    (``SLOPEFILL`` / ``SUBGRADE``) are reserved for grading composition;
    passing them here emits a :class:`UserWarning`.
  - :class:`IfcPolygonalFaceSet` body representation (same shape as cut)
  - ``Pset_EarthworksFillCommon`` (Status="NEW")
  - OmniClass classification (default ``22-07 31 23`` Fill; overridable)
  - ``Qto_EarthworksFillBaseQuantities`` with Length / Width / Depth,
    CompactedVolume / LooseVolume (no Weight on the fill side, per
    buildingSMART standard)
  - ``Pset_SaikeiGradingShrinkSwell``

Idempotency contract
====================

Three of the seven public functions update existing entities in place
rather than creating duplicates:

- :func:`write_cut_quantities`
- :func:`write_fill_quantities`
- :func:`apply_shrink_swell_pset`

This is load-bearing for Phase 6's cascade-rebuild flows, where a
volume calculation may be re-run many times against the same product.
The persisted Qto / Pset entity identity is preserved across
re-authoring calls; only the property values change.

:func:`void_terrain` is also idempotent for the same (cut, terrain)
pair — calling twice returns the same :class:`IfcRelVoidsElement`.
Retargeting a cut to a different terrain raises :class:`ValueError`
(IFC's 1:1 cardinality on :class:`IfcFeatureElementSubtraction`).

Currently supported
===================

1. :func:`add_volume_solid_representation` — lower-level helper
   authoring an :class:`IfcPolygonalFaceSet` (Closed=TRUE) Body /
   Tessellation representation; called by both create_earthworks_*.
2. :func:`create_earthworks_cut` — top-level cut creation.
3. :func:`create_earthworks_fill` — top-level volume-bearing fill
   creation.
4. :func:`void_terrain` — :class:`IfcRelVoidsElement` between a cut and
   its host terrain.
5. :func:`link_fill_to_cut` — :class:`IfcRelFillsElement` between a
   cut and a fill that occupies it (footing, pipe segment, embankment,
   etc.). Mirror of :func:`void_terrain` for the cut→fill half of the
   voiding chain.
6. :func:`write_cut_quantities` — idempotent
   ``Qto_EarthworksCutBaseQuantities`` author.
7. :func:`write_fill_quantities` — idempotent
   ``Qto_EarthworksFillBaseQuantities`` author.
8. :func:`apply_shrink_swell_pset` — idempotent
   ``Pset_SaikeiGradingShrinkSwell`` author.

Future versions of this API may support
=======================================

1. Cut/fill solid replacement in place (mirror of
   :func:`ifcopenshell.api.surface.update_tin_representation`) — when
   Phase 6 needs to recompute a volume's geometry without re-creating
   the entire entity.
2. Bulk Qto authoring across the whole earthwork section of a project
   from a Bonsai-side computed table.
3. Standalone ``unvoid_terrain`` to remove an
   :class:`IfcRelVoidsElement` cleanly (currently callers go through
   ``file.remove`` on the rel directly).

Quick example
=============

.. code:: python

    import ifcopenshell
    import ifcopenshell.api.earthwork
    import ifcopenshell.api.surface

    # ... bootstrap an IFC4X3_ADD2 file with IfcProject + IfcSite ...

    terrain = ifcopenshell.api.surface.create_terrain(
        ifc, name="Existing Ground",
        points=eg_points, triangles=eg_triangles,
    )

    cut = ifcopenshell.api.earthwork.create_earthworks_cut(
        ifc, name="Pad excavation",
        points=cut_points, faces=cut_faces,
        predefined_type="EXCAVATION",
    )
    ifcopenshell.api.earthwork.void_terrain(ifc, cut, terrain)
    ifcopenshell.api.earthwork.write_cut_quantities(
        ifc, cut,
        length=20.0, width=20.0, depth=2.0,
        undisturbed_volume=800.0, loose_volume=1000.0,
    )
    ifcopenshell.api.earthwork.apply_shrink_swell_pset(
        ifc, cut, shrink_factor=0.92, swell_factor=1.25,
    )

    fill = ifcopenshell.api.earthwork.create_earthworks_fill(
        ifc, name="Embankment",
        points=fill_points, faces=fill_faces,
        predefined_type="EMBANKMENT",
    )
    ifcopenshell.api.earthwork.write_fill_quantities(
        ifc, fill,
        compacted_volume=500.0, loose_volume=600.0,
    )

    ifc.write("earthwork_demo.ifc")

A runnable version lives at ``test/api/demo_earthwork.py``.

This API is under development and subject to code-breaking changes.
"""

from .add_volume_solid_representation import add_volume_solid_representation
from .apply_shrink_swell_pset import apply_shrink_swell_pset
from .create_earthworks_cut import create_earthworks_cut
from .create_earthworks_fill import create_earthworks_fill
from .link_fill_to_cut import link_fill_to_cut
from .void_terrain import void_terrain
from .write_cut_quantities import write_cut_quantities
from .write_fill_quantities import write_fill_quantities

__all__ = [
    "add_volume_solid_representation",
    "apply_shrink_swell_pset",
    "create_earthworks_cut",
    "create_earthworks_fill",
    "link_fill_to_cut",
    "void_terrain",
    "write_cut_quantities",
    "write_fill_quantities",
]

# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2026 Desert Springs Civil Engineering PLLC
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

"""High-level API for authoring grading-related IFC 4.3 entities.

Civil 3D-style grading: feature lines, reusable criteria templates,
grading groups, and the per-group earthwork fills (slope + interior) that
compose a graded feature. Phase 2 of the Saikei grading/earthwork sprint;
depends on Phase 1 (``ifcopenshell.api.surface``) for TIN authoring on
fills. Same shape as the alignment and surface APIs: file-per-function,
soft numpy dependency, no Blender or ``bpy`` imports.

Entity tree authored
====================

A complete grading group as authored by this API:

- :class:`IfcGroup` with ``ObjectType="GradingGroup"`` (the logical
  collection)

  - ``Pset_SaikeiGradingSource`` (criteria reference, author, timestamp,
    target surface, interior-fill strategy)
  - ``Pset_SaikeiGradingCriteria`` (instance bound to the project's
    template via :class:`IfcRelDefinesByTemplate`)
  - ``Pset_SaikeiGradingAlignment`` (optional, for corridor linkage)
  - :class:`IfcRelAssignsToGroup` membership: composite fill, slope
    fills, interior fill, source feature lines

- :class:`IfcEarthworksFill[SUBGRADE]` per-group composite

  - Spatially contained in :class:`IfcSite` via
    :class:`IfcRelContainedInSpatialStructure` (the deferred Phase 4/5
    site-composite aggregation will replace this with an
    :class:`IfcRelAggregates` to a site-level composite)
  - Aggregates the slope and interior fills via
    :class:`IfcRelAggregates`
  - ``Pset_EarthworksFillCommon`` (``Status="NEW"``)
  - OmniClass Table 22 classification (``22-07 31 23`` Fill)

- :class:`IfcEarthworksFill[SLOPEFILL]` per slope projection ribbon

  - SurfaceModel TIN representation (via Phase 1 reuse)
  - Box LOD representation (via Phase 1 reuse)
  - ``Pset_EarthworksFillCommon`` + OmniClass ``22-07 31 23`` (Fill)

- :class:`IfcEarthworksFill[SUBGRADE]` interior fill (one per group, when
  ``interior_fill != "none"``)

  - SurfaceModel TIN + Box LOD + standard pset
  - OmniClass ``22-07 31 16`` (Excavation and Fill — the standard takeoff
    code for pad subgrade, distinct from slope fills)

- :class:`IfcAlignment` feature lines (3D ``IfcIndexedPolyCurve`` under
  the alignment Axis subcontext)

  - Spatially contained in :class:`IfcSite` (distinct from transportation
    alignments, which are project-aggregated)
  - ``Pset_SaikeiFeatureLineCommon``

- :class:`IfcPropertySetTemplate` for ``Pset_SaikeiGradingCriteria``
  (project-scope, singleton; six :class:`IfcSimplePropertyTemplate`
  children including an :class:`IfcPropertyEnumeration` for
  ``TargetKind``). Discoverable via ``file.by_type``; instances bound via
  :class:`IfcRelDefinesByTemplate`.

Triangulation contract
======================

Like :mod:`ifcopenshell.api.surface`, this API does **not** triangulate.
Bonsai's ``tool.Grading`` (Phase 5) computes the slope-projection ribbons
and interior-fill triangulations; this API persists what it's given.
Triangle indices on the API surface are 0-based; conversion to IFC's
1-based convention happens internally via the Phase 1 surface API.

Currently supported
===================

1. :func:`create_feature_line` — :class:`IfcAlignment` 3D polyline.
2. :func:`create_grading_criteria_template` — singleton
   :class:`IfcPropertySetTemplate` for ``Pset_SaikeiGradingCriteria``.
3. :func:`create_grading_group` — entity pair
   (:class:`IfcGroup`, per-group composite :class:`IfcEarthworksFill`)
   returned as a :class:`GradingGroupAuthoring` named tuple.
4. :func:`assign_grading_criteria` — bind the criteria template to a
   group with concrete values; idempotent on re-assign.
5. :func:`add_slope_fill_to_group` — author an
   :class:`IfcEarthworksFill[SLOPEFILL]` and wire it into the group +
   composite.
6. :func:`add_interior_fill_to_group` — author the per-group
   :class:`IfcEarthworksFill[SUBGRADE]` interior; one per group.
7. :func:`link_alignment_to_group` —
   ``Pset_SaikeiGradingAlignment`` for corridor linkage; valid on either
   :class:`IfcGroup` or :class:`IfcEarthworksFill`.
8. :func:`add_member_to_group` — lower-level
   :class:`IfcRelAssignsToGroup` building block.

Future versions of this API may support
=======================================

1. ``aggregate_group_to_site_composite`` — wire a per-group composite
   fill under a site-level composite, removing the per-group composite's
   :class:`IfcRelContainedInSpatialStructure` to :class:`IfcSite` (the
   deferred Phase 4/5 hand-off).
2. ``replace_slope_fill_geometry`` — in-place TIN replacement for slope
   fills, mirroring :func:`ifcopenshell.api.surface.update_tin_representation`.
3. ``unassign_grading_criteria`` — explicit removal of a criteria binding
   from a group.

Quick example
=============

.. code:: python

    import ifcopenshell
    import ifcopenshell.api.grading
    import ifcopenshell.api.surface
    import ifcopenshell.api.unit
    import ifcopenshell.guid

    # Bootstrap a project with an IfcSite.
    ifc = ifcopenshell.file(schema="IFC4X3_ADD2")
    project = ifc.create_entity(
        "IfcProject", GlobalId=ifcopenshell.guid.new(), Name="Demo"
    )
    length = ifcopenshell.api.unit.add_si_unit(ifc, unit_type="LENGTHUNIT")
    ifcopenshell.api.unit.assign_unit(ifc, units=[length])
    site = ifc.create_entity(
        "IfcSite", GlobalId=ifcopenshell.guid.new(), Name="Demo Site"
    )
    ifc.create_entity(
        "IfcRelAggregates",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=project,
        RelatedObjects=[site],
    )

    # Existing-ground TIN (Phase 1 surface API).
    eg_points = [(0.0, 0.0, 99.0), (100.0, 0.0, 99.0),
                 (100.0, 100.0, 99.0), (0.0, 100.0, 99.0)]
    eg_triangles = [(0, 1, 2), (0, 2, 3)]
    terrain = ifcopenshell.api.surface.create_terrain(
        ifc, name="Existing Ground",
        points=eg_points, triangles=eg_triangles,
    )

    # Pad-perimeter feature line at z=100 (1 m fill above existing).
    feature_line = ifcopenshell.api.grading.create_feature_line(
        ifc, name="Pad perimeter",
        vertices=[(20.0, 20.0, 100.0), (30.0, 20.0, 100.0),
                  (30.0, 30.0, 100.0), (20.0, 30.0, 100.0)],
        closed=True,
    )

    # 3:1 fill / 2:1 cut criteria template + grading group.
    template = ifcopenshell.api.grading.create_grading_criteria_template(ifc)
    grading = ifcopenshell.api.grading.create_grading_group(
        ifc, name="Pad Grading",
        target_surface=terrain, interior_fill="flat",
    )
    ifcopenshell.api.grading.assign_grading_criteria(
        ifc, grading.group, template,
        target_kind="surface",
        target_reference=terrain.GlobalId,
        cut_slope=2.0, fill_slope=3.0,
    )

    # Slope fill (Bonsai's tool.Grading would compute these triangles in
    # practice; here we hand-author a simple ribbon).
    slope_points = [...]
    slope_triangles = [...]
    ifcopenshell.api.grading.add_slope_fill_to_group(
        ifc, grading.group, grading.composite_fill,
        name="Pad slope",
        points=slope_points, triangles=slope_triangles,
        feature_line=feature_line,
    )

    ifc.write("grading_demo.ifc")

A runnable version of the same workflow lives at
``test/api/demo_grading.py``.

This API is under development and subject to code-breaking changes.
"""

from .add_interior_fill_to_group import add_interior_fill_to_group
from .add_member_to_group import add_member_to_group
from .add_slope_fill_to_group import add_slope_fill_to_group
from .assign_grading_criteria import assign_grading_criteria
from .create_feature_line import create_feature_line
from .create_grading_criteria_template import create_grading_criteria_template
from .create_grading_group import GradingGroupAuthoring, create_grading_group
from .link_alignment_to_group import link_alignment_to_group

__all__ = [
    "GradingGroupAuthoring",
    "add_interior_fill_to_group",
    "add_member_to_group",
    "add_slope_fill_to_group",
    "assign_grading_criteria",
    "create_feature_line",
    "create_grading_criteria_template",
    "create_grading_group",
    "link_alignment_to_group",
]

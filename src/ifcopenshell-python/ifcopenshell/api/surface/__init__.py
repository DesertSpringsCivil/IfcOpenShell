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

"""High-level API for authoring surface-related IFC 4.3 entities.

This API persists pre-triangulated terrain and proposed-grading surfaces. It
is the Phase 1 building block of the Saikei civil-engineering work — Phases 2
(``ifcopenshell.api.grading``) and 3 (``ifcopenshell.api.earthwork``) build
on top of it. It mirrors the shape of ``ifcopenshell.api.alignment``: file-
per-function, soft numpy dependency, no Blender or ``bpy`` imports.

Entity tree authored
====================

For an existing-ground TIN, ``create_terrain`` produces:

- ``IfcGeographicElement`` (PredefinedType=TERRAIN, Name as supplied)
  - contained in IfcSite via IfcRelContainedInSpatialStructure
  - has IfcProductDefinitionShape with two representations:
    - Body ``IfcShapeRepresentation`` (RepresentationType=Tessellation)
      containing ``IfcTriangulatedIrregularNetwork`` (Coordinates,
      CoordIndex 1-based, Flags) and an ``IfcCartesianPointList3D``
    - Box ``IfcShapeRepresentation`` containing ``IfcBoundingBox``
  - has ``Pset_GeographicElementCommon`` (standard, Status="NEW")
  - has ``Pset_SaikeiGradingSurface`` (Saikei-specific:
    TriangulationTolerance, BreaklineCount, VertexCount,
    BoundaryPolygonReference)

``create_proposed_surface`` produces the same tree but rooted at
``IfcEarthworksFill`` (PredefinedType=SUBGRADE) with
``Pset_EarthworksFillCommon`` instead.

Breaklines are stored as separate ``IfcAnnotation`` entities with
``IfcPolyline`` representations under the Annotation subcontext, so they
survive retriangulation. The TIN's per-triangle ``Flags`` list independently
encodes which triangles touch which breaklines.

Triangulation contract
======================

The API does **not** triangulate — callers pass pre-triangulated point
clouds. This separates I/O from geometry: Bonsai's ``tool.Surface`` (Phase 4)
runs the constrained Delaunay step (SciPy + Shapely) and calls into this API
to persist the result. A standalone Python script that already has its own
triangulation can do the same.

Triangle indices are 0-based on the API surface; the API converts to the IFC
1-based convention internally. Triangle flags are an optional integer per
triangle, defaulting to all zeros.

Currently supported
===================

1. Authoring an existing-ground TIN as ``IfcGeographicElement[TERRAIN]``
   with full pset coverage: :func:`create_terrain`.
2. Authoring a proposed-ground TIN as ``IfcEarthworksFill[SUBGRADE]``:
   :func:`create_proposed_surface`.
3. Lower-level building blocks for incremental authoring:
   :func:`add_tin_representation`, :func:`add_bounding_box_representation`,
   :func:`apply_saikei_pset`.
4. Persisting breaklines as separate annotations: :func:`add_breakline_annotation`.
5. In-place TIN replacement (retriangulation, breakline-add, boundary-edit):
   :func:`update_tin_representation` — old TIN entities are garbage-collected
   when no other references remain.

Future versions of this API may support
=======================================

1. Separate authoring helpers for vegetation polygons (``IfcGeographicElement
   [VEGETATION]``) and survey points (``IfcGeographicElement[SOIL_BORING_POINT]``).
2. Round-tripping through the bSI reference validator as a built-in
   precondition rather than only as a CI test.
3. Selective rebuild of only the Body rep when the bounding-box rep
   does not need updating, and vice versa.

Quick example
=============

.. code:: python

    import ifcopenshell
    import ifcopenshell.api.context
    import ifcopenshell.api.surface
    import ifcopenshell.api.unit
    import ifcopenshell.guid

    ifc = ifcopenshell.file(schema="IFC4X3_ADD2")
    project = ifc.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), Name="Demo")
    length = ifcopenshell.api.unit.add_si_unit(ifc, unit_type="LENGTHUNIT")
    ifcopenshell.api.unit.assign_unit(ifc, units=[length])
    site = ifc.create_entity("IfcSite", GlobalId=ifcopenshell.guid.new(), Name="Demo Site")
    ifc.create_entity(
        "IfcRelAggregates",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=project,
        RelatedObjects=[site],
    )

    # Two triangles forming a 10x10 square pad at z=100.
    points = [(0.0, 0.0, 100.0), (10.0, 0.0, 100.0), (10.0, 10.0, 100.0), (0.0, 10.0, 100.0)]
    triangles = [(0, 1, 2), (0, 2, 3)]

    terrain = ifcopenshell.api.surface.create_terrain(
        ifc,
        name="Existing Ground",
        points=points,
        triangles=triangles,
        triangulation_tolerance=0.005,
    )

    ifcopenshell.api.surface.add_breakline_annotation(
        ifc,
        site=site,
        polyline=[(0.0, 5.0, 100.0), (10.0, 5.0, 100.0)],
        name="Centerline",
        kind="standard",
    )

    ifc.write("demo.ifc")

A runnable version of the same workflow lives at
``test/api/demo_surface.py`` and can be invoked directly with
``python -m test.api.demo_surface demo.ifc``.

This API is under development and subject to code-breaking changes.
"""

from .add_bounding_box_representation import add_bounding_box_representation
from .add_breakline_annotation import add_breakline_annotation
from .add_tin_representation import add_tin_representation
from .apply_saikei_pset import apply_saikei_pset
from .create_proposed_surface import create_proposed_surface
from .create_terrain import create_terrain
from .update_tin_representation import update_tin_representation

__all__ = [
    "add_bounding_box_representation",
    "add_breakline_annotation",
    "add_tin_representation",
    "apply_saikei_pset",
    "create_proposed_surface",
    "create_terrain",
    "update_tin_representation",
]

#!/usr/bin/env python3
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

"""Runnable demo for ``ifcopenshell.api.earthwork``.

Builds a complete cut + fill scenario end-to-end:

1. Existing-ground TIN at z=99 (Phase 1 ``api.surface``)
2. An IfcEarthworksCut[EXCAVATION] with a closed cube body, voiding
   the terrain via IfcRelVoidsElement
3. Qto_EarthworksCutBaseQuantities and Pset_SaikeiGradingShrinkSwell
   on the cut
4. An IfcEarthworksFill[EMBANKMENT] with a closed tetrahedron body
5. Qto_EarthworksFillBaseQuantities and Pset_SaikeiGradingShrinkSwell
   on the fill

Writes to disk, reopens, and prints a structural summary.

Usage:
    python -m test.api.demo_earthwork [output_path]

If ``output_path`` is omitted, writes to ``earthwork_demo.ifc`` in the
current working directory.

This file is **not** a pytest test (no ``test_`` prefix; not collected).
"""

from __future__ import annotations

import sys
from pathlib import Path

import ifcopenshell
import ifcopenshell.api.earthwork
import ifcopenshell.api.surface
import ifcopenshell.api.unit
import ifcopenshell.guid


def _build_empty_project() -> ifcopenshell.file:
    file = ifcopenshell.file(schema="IFC4X3_ADD2")
    project = file.create_entity(
        "IfcProject", GlobalId=ifcopenshell.guid.new(), Name="Saikei Earthwork Demo"
    )
    length = ifcopenshell.api.unit.add_si_unit(file, unit_type="LENGTHUNIT")
    ifcopenshell.api.unit.assign_unit(file, units=[length])
    site = file.create_entity(
        "IfcSite", GlobalId=ifcopenshell.guid.new(), Name="Demo Site"
    )
    file.create_entity(
        "IfcRelAggregates",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=project,
        RelatedObjects=[site],
    )
    return file


def _existing_terrain_geometry() -> tuple[
    list[tuple[float, float, float]], list[tuple[int, int, int]]
]:
    """3x3 vertex grid forming a 100x100 m flat existing-ground TIN at z=99."""
    points: list[tuple[float, float, float]] = []
    for j in range(3):
        for i in range(3):
            points.append((float(i * 50), float(j * 50), 99.0))
    triangles: list[tuple[int, int, int]] = []
    for j in range(2):
        for i in range(2):
            a = j * 3 + i
            b = a + 1
            c = a + 3
            d = a + 4
            triangles.append((a, b, d))
            triangles.append((a, d, c))
    return points, triangles


def _cube_solid_geometry() -> tuple[
    list[tuple[float, float, float]], list[list[int]]
]:
    """8 vertices + 6 quad faces forming a closed unit cube. Volume = 1."""
    points = [
        (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (1.0, 1.0, 1.0), (0.0, 1.0, 1.0),
    ]
    faces = [
        [0, 3, 2, 1], [4, 5, 6, 7],
        [0, 1, 5, 4], [2, 3, 7, 6],
        [1, 2, 6, 5], [0, 4, 7, 3],
    ]
    return points, faces


def _tetrahedron_solid_geometry() -> tuple[
    list[tuple[float, float, float]], list[list[int]]
]:
    """4 vertices + 4 triangular faces forming a closed tetrahedron."""
    points = [
        (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0),
    ]
    faces = [[0, 2, 1], [0, 1, 3], [1, 2, 3], [0, 3, 2]]
    return points, faces


def main(argv: list[str]) -> int:
    output_path = Path(argv[1]) if len(argv) > 1 else Path("earthwork_demo.ifc")

    file = _build_empty_project()

    # 1. Existing-ground TIN.
    eg_points, eg_triangles = _existing_terrain_geometry()
    terrain = ifcopenshell.api.surface.create_terrain(
        file,
        name="Existing Ground",
        points=eg_points,
        triangles=eg_triangles,
        triangulation_tolerance=0.005,
    )

    # 2. Cut volume voiding the terrain.
    cut_points, cut_faces = _cube_solid_geometry()
    cut = ifcopenshell.api.earthwork.create_earthworks_cut(
        file,
        name="Bulk excavation",
        points=cut_points,
        faces=cut_faces,
        predefined_type="EXCAVATION",
    )
    ifcopenshell.api.earthwork.void_terrain(file, cut, terrain)

    # 3. Cut Qto + shrink/swell.
    ifcopenshell.api.earthwork.write_cut_quantities(
        file,
        cut,
        length=10.0,
        width=10.0,
        depth=10.0,
        undisturbed_volume=1000.0,
        loose_volume=1250.0,
        weight=1800000.0,
    )
    ifcopenshell.api.earthwork.apply_shrink_swell_pset(
        file, cut, shrink_factor=0.92, swell_factor=1.25
    )

    # 4. Fill volume.
    fill_points, fill_faces = _tetrahedron_solid_geometry()
    fill = ifcopenshell.api.earthwork.create_earthworks_fill(
        file,
        name="Embankment",
        points=fill_points,
        faces=fill_faces,
        predefined_type="EMBANKMENT",
    )

    # 5. Fill Qto + shrink/swell.
    ifcopenshell.api.earthwork.write_fill_quantities(
        file,
        fill,
        length=15.0,
        width=8.0,
        depth=3.0,
        compacted_volume=360.0,
        loose_volume=432.0,
    )
    ifcopenshell.api.earthwork.apply_shrink_swell_pset(
        file, fill, shrink_factor=0.95, swell_factor=1.20
    )

    file.write(str(output_path))
    print(f"wrote {output_path}")

    reopened = ifcopenshell.open(str(output_path))
    cuts = reopened.by_type("IfcEarthworksCut")
    fills = reopened.by_type("IfcEarthworksFill")
    voids = reopened.by_type("IfcRelVoidsElement")
    qtos = reopened.by_type("IfcElementQuantity")
    poly_face_sets = reopened.by_type("IfcPolygonalFaceSet")

    print(f"  IfcEarthworksCut:             {len(cuts)} (expected 1)")
    print(f"  IfcEarthworksFill:            {len(fills)} (expected 1)")
    print(f"  IfcRelVoidsElement:           {len(voids)} (expected 1)")
    print(f"  IfcElementQuantity:           {len(qtos)} (expected 2 - cut + fill)")
    print(f"  IfcPolygonalFaceSet:          {len(poly_face_sets)} (expected 2 - cube + tetrahedron)")
    print(f"  cut.Name = {cuts[0].Name!r}")
    print(f"  cut voids: {voids[0].RelatingBuildingElement.Name!r}")
    print(f"  fill.Name = {fills[0].Name!r}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

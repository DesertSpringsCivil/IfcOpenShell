#!/usr/bin/env python3
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

"""Runnable demo for ``ifcopenshell.api.surface``.

Builds a flat 100x100 m pad at z=100 with breakline annotations, writes the
result to disk, reopens it, and prints a summary. Useful as a smoke test
when adding new entities to the API or for stakeholder demos.

Usage:
    python -m test.api.demo_surface [output_path]

If ``output_path`` is omitted, the demo writes to ``surface_demo.ifc`` in
the current working directory.

This file is **not** a pytest test — it's not collected (no ``test_``
prefix). Pure stakeholder/dev convenience.
"""

from __future__ import annotations

import sys
from pathlib import Path

import ifcopenshell
import ifcopenshell.api.surface
import ifcopenshell.api.unit
import ifcopenshell.guid


def _build_empty_project() -> ifcopenshell.file:
    file = ifcopenshell.file(schema="IFC4X3_ADD2")
    project = file.create_entity(
        "IfcProject", GlobalId=ifcopenshell.guid.new(), Name="Saikei Surface Demo"
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


def _flat_pad_geometry() -> tuple[
    list[tuple[float, float, float]], list[tuple[int, int, int]]
]:
    """3x3 vertex grid forming a 100x100 m flat pad at z=100, 8 triangles."""
    points: list[tuple[float, float, float]] = []
    for j in range(3):
        for i in range(3):
            points.append((float(i * 50), float(j * 50), 100.0))
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


def main(argv: list[str]) -> int:
    output_path = Path(argv[1]) if len(argv) > 1 else Path("surface_demo.ifc")

    file = _build_empty_project()
    site = file.by_type("IfcSite")[0]
    points, triangles = _flat_pad_geometry()

    terrain = ifcopenshell.api.surface.create_terrain(
        file,
        name="Existing Ground",
        points=points,
        triangles=triangles,
        triangulation_tolerance=0.005,
        breakline_count=1,
    )
    ifcopenshell.api.surface.add_breakline_annotation(
        file,
        site=site,
        polyline=[(0.0, 50.0, 100.0), (100.0, 50.0, 100.0)],
        name="Centerline break",
        kind="standard",
        source="hand",
    )

    file.write(str(output_path))
    print(f"wrote {output_path}")

    reopened = ifcopenshell.open(str(output_path))
    terrains = reopened.by_type("IfcGeographicElement")
    annotations = reopened.by_type("IfcAnnotation")
    tins = reopened.by_type("IfcTriangulatedIrregularNetwork")
    polylines = reopened.by_type("IfcPolyline")

    print(f"  IfcGeographicElement: {len(terrains)} (expected 1)")
    print(f"  IfcAnnotation:        {len(annotations)} (expected 1)")
    print(f"  IfcTriangulatedIrregularNetwork: {len(tins)} (expected 1)")
    print(f"  IfcPolyline:          {len(polylines)} (expected 1)")
    print(f"  terrain.Name = {terrains[0].Name!r}")
    print(f"  terrain reps = {[r.RepresentationIdentifier for r in terrains[0].Representation.Representations]}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

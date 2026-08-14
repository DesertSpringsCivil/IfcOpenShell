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

"""Runnable demo for ``ifcopenshell.api.grading``.

Builds a complete grading scenario end-to-end:

1. Existing-ground TIN at z=99 (Phase 1 ``api.surface``)
2. A 10×10 m pad perimeter feature line at z=100
3. A 3:1 fill / 2:1 cut criteria template
4. A grading group with ``interior_fill="flat"``
5. The criteria bound to the group (``target_kind="surface"``)
6. Two slope-fill ribbons (north and south edges of the pad)
7. A flat interior fill (the pad floor)
8. Corridor linkage on the group via Pset_SaikeiGradingAlignment

Writes the result to disk, reopens it, and prints a structural summary.
Useful as a smoke test when changes to the API surface or as a stakeholder
demo of the grading entity tree.

Usage:
    python -m test.api.demo_grading [output_path]

If ``output_path`` is omitted, writes to ``grading_demo.ifc`` in the
current working directory.

This file is **not** a pytest test (no ``test_`` prefix; not collected).
"""

from __future__ import annotations

import sys
from pathlib import Path

import ifcopenshell
import ifcopenshell.api.grading
import ifcopenshell.api.surface
import ifcopenshell.api.unit
import ifcopenshell.guid


def _build_empty_project() -> ifcopenshell.file:
    file = ifcopenshell.file(schema="IFC4X3_ADD2")
    project = file.create_entity(
        "IfcProject", GlobalId=ifcopenshell.guid.new(), Name="Saikei Grading Demo"
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
    """3×3 vertex grid forming a 100×100 m flat existing-ground TIN at z=99."""
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


def _slope_ribbon_geometry() -> tuple[
    list[tuple[float, float, float]], list[tuple[int, int, int]]
]:
    """Slope ribbon between an inner pad (z=100) and an outer daylight loop (z=99)."""
    inner = [
        (20.0, 20.0, 100.0),
        (30.0, 20.0, 100.0),
        (30.0, 30.0, 100.0),
        (20.0, 30.0, 100.0),
    ]
    outer = [
        (15.0, 15.0, 99.0),
        (35.0, 15.0, 99.0),
        (35.0, 35.0, 99.0),
        (15.0, 35.0, 99.0),
    ]
    points = inner + outer
    triangles = []
    for i in range(4):
        j = (i + 1) % 4
        a, b, c, d = i, j, 4 + i, 4 + j
        triangles.append((a, c, d))
        triangles.append((a, d, b))
    return points, triangles


def _pad_floor_geometry() -> tuple[
    list[tuple[float, float, float]], list[tuple[int, int, int]]
]:
    points = [
        (20.0, 20.0, 100.0),
        (30.0, 20.0, 100.0),
        (30.0, 30.0, 100.0),
        (20.0, 30.0, 100.0),
    ]
    triangles = [(0, 1, 2), (0, 2, 3)]
    return points, triangles


def main(argv: list[str]) -> int:
    output_path = Path(argv[1]) if len(argv) > 1 else Path("grading_demo.ifc")

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

    # 2. Feature line — pad perimeter at z=100.
    feature_line = ifcopenshell.api.grading.create_feature_line(
        file,
        name="Pad perimeter",
        vertices=[
            (20.0, 20.0, 100.0),
            (30.0, 20.0, 100.0),
            (30.0, 30.0, 100.0),
            (20.0, 30.0, 100.0),
        ],
        closed=True,
        source="manual",
    )

    # 3. Criteria template.
    template = ifcopenshell.api.grading.create_grading_criteria_template(file)

    # 4. Grading group + composite fill.
    grading = ifcopenshell.api.grading.create_grading_group(
        file,
        name="Pad Grading",
        target_surface=terrain,
        interior_fill="flat",
        author="Demo",
    )

    # 5. Bind criteria.
    ifcopenshell.api.grading.assign_grading_criteria(
        file,
        grading.group,
        template,
        target_kind="surface",
        target_reference=terrain.GlobalId,
        cut_slope=2.0,
        fill_slope=3.0,
        max_distance=10.0,
    )

    # 6. Two slope-fill ribbons.
    slope_points, slope_triangles = _slope_ribbon_geometry()
    ifcopenshell.api.grading.add_slope_fill_to_group(
        file,
        grading.group,
        grading.composite_fill,
        name="N slope",
        points=slope_points,
        triangles=slope_triangles,
        feature_line=feature_line,
    )
    ifcopenshell.api.grading.add_slope_fill_to_group(
        file,
        grading.group,
        grading.composite_fill,
        name="S slope",
        points=slope_points,
        triangles=slope_triangles,
    )

    # 7. Interior fill — the pad floor.
    floor_points, floor_triangles = _pad_floor_geometry()
    ifcopenshell.api.grading.add_interior_fill_to_group(
        file,
        grading.group,
        grading.composite_fill,
        name="Pad floor",
        points=floor_points,
        triangles=floor_triangles,
    )

    # 8. Corridor linkage on the group.
    ifcopenshell.api.grading.link_alignment_to_group(
        file,
        grading.group,
        feature_line,
        start_station=0.0,
        end_station=40.0,
    )

    file.write(str(output_path))
    print(f"wrote {output_path}")

    reopened = ifcopenshell.open(str(output_path))
    groups = [g for g in reopened.by_type("IfcGroup") if g.ObjectType == "GradingGroup"]
    fills = reopened.by_type("IfcEarthworksFill")
    feature_lines = reopened.by_type("IfcAlignment")
    templates = reopened.by_type("IfcPropertySetTemplate")
    rel_assigns = reopened.by_type("IfcRelAssignsToGroup")
    rel_aggregates = reopened.by_type("IfcRelAggregates")
    rel_define_template = reopened.by_type("IfcRelDefinesByTemplate")

    print(f"  IfcGroup[GradingGroup]:       {len(groups)} (expected 1)")
    print(f"  IfcEarthworksFill:            {len(fills)} (expected 4 - composite + 2 slope + interior)")
    print(f"  IfcAlignment:                 {len(feature_lines)} (expected 1)")
    print(f"  IfcPropertySetTemplate:       {len(templates)} (expected 1)")
    print(f"  IfcRelAssignsToGroup:         {len(rel_assigns)} (expected 1)")
    print(f"  IfcRelAggregates:             {len(rel_aggregates)} (expected 2 - project->site, composite->children)")
    print(f"  IfcRelDefinesByTemplate:      {len(rel_define_template)} (expected 1)")
    print(f"  group.Name = {groups[0].Name!r}")
    print(f"  group members count = {len(rel_assigns[0].RelatedObjects)}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

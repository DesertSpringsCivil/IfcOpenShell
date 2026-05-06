"""Tier 1 grading demo — end-to-end headless IFC authoring.

This script exercises the complete Saikei Tier 1 grading workflow using only
``ifcopenshell.api.*`` calls (no Blender, no bonsai imports). It can be run
from any Python environment that has ``ifcopenshell``, ``numpy``, ``scipy``,
and ``shapely`` installed — Blender is NOT required.

Usage::

    python tier1_demo.py <output_path>

    # Example — regenerate the reference fixture:
    python src/bonsai/scripts/tier1_demo.py docs/grading/examples/tier1_demo.ifc

Sections:
  A — Bootstrap IFC project + IfcSite
  B — Terrain (existing ground) from CSV points
  C — Grading group + criteria + slope/interior fills
  D — Prismoidal volume math (inline, ~50 lines) + earthwork entities
  E — Write + validate

Georef omitted; production projects use
``ifcopenshell.api.georeference.add_georeferencing``. For Tier 1 the demo
authors in the local engineering frame only — the documented contract. An
incomplete IfcMapConversion stub would be worse than none.
"""

from __future__ import annotations

import argparse
import csv
import pathlib
import sys
from typing import Optional

import ifcopenshell
import ifcopenshell.api.earthwork
import ifcopenshell.api.grading
import ifcopenshell.api.pset
import ifcopenshell.api.spatial
import ifcopenshell.api.surface
import ifcopenshell.api.unit
import ifcopenshell.guid
import ifcopenshell.validate
import numpy as np
import shapely
from scipy.spatial import Delaunay

# ---------------------------------------------------------------------------
# Section 0 — Inline helpers (no bonsai imports)
# ---------------------------------------------------------------------------

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_DEFAULT_CSV = _REPO_ROOT / "docs" / "grading" / "examples" / "tier1_terrain.csv"

# Shrink/swell factors — typical values from soil-classification charts
# (e.g. NAVFAC DM-7.1).  Override per-project when lab data is available.
# ShrinkFactor < 1.0: compacted fill occupies less volume than bank material.
# SwellFactor > 1.0: excavated material occupies more volume than bank state.
SHRINK_FACTOR = 0.92
SWELL_FACTOR = 1.25


def _load_csv(path: pathlib.Path) -> list[tuple[float, float, float]]:
    """Read x,y,z points from a headerless CSV file."""
    points: list[tuple[float, float, float]] = []
    with open(path, newline="") as fh:
        reader = csv.reader(fh)
        for row in reader:
            if not row or row[0].startswith("#"):
                continue
            x, y, z = float(row[0]), float(row[1]), float(row[2])
            points.append((x, y, z))
    return points


def _delaunay_xy(
    points: list[tuple[float, float, float]],
) -> list[tuple[int, int, int]]:
    """Triangulate a point cloud by projecting to XY and running SciPy Delaunay.

    Returns 0-based vertex-index triples ordered counterclockwise from above
    (Shapely / IFC convention). ~15 lines — inline so the demo is self-contained.
    """
    pts_2d = np.array([(p[0], p[1]) for p in points])
    tri = Delaunay(pts_2d)
    triangles: list[tuple[int, int, int]] = []
    for simplex in tri.simplices:
        a, b, c = int(simplex[0]), int(simplex[1]), int(simplex[2])
        # Enforce CCW orientation (positive cross product z-component).
        ax, ay = pts_2d[a]
        bx, by = pts_2d[b]
        cx, cy = pts_2d[c]
        if (bx - ax) * (cy - ay) - (by - ay) * (cx - ax) < 0:
            b, c = c, b  # swap to make CCW
        triangles.append((a, b, c))
    return triangles


def _z_at_xy(
    points: list[tuple[float, float, float]],
    triangles: list[tuple[int, int, int]],
    query_x: float,
    query_y: float,
) -> Optional[float]:
    """Interpolate Z on a TIN at (query_x, query_y).

    Walks triangles to find the containing triangle, then barycentric
    interpolates. Returns None when the query point is outside the TIN.
    """
    qp = shapely.Point(query_x, query_y)
    for tri in triangles:
        a, b, c = points[tri[0]], points[tri[1]], points[tri[2]]
        poly = shapely.Polygon([(a[0], a[1]), (b[0], b[1]), (c[0], c[1])])
        if poly.contains(qp) or poly.boundary.contains(qp):
            # Barycentric interpolation.
            denom = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
            if abs(denom) < 1e-12:
                return (a[2] + b[2] + c[2]) / 3.0
            w0 = ((b[1] - c[1]) * (query_x - c[0]) + (c[0] - b[0]) * (query_y - c[1])) / denom
            w1 = ((c[1] - a[1]) * (query_x - c[0]) + (a[0] - c[0]) * (query_y - c[1])) / denom
            w2 = 1.0 - w0 - w1
            return w0 * a[2] + w1 * b[2] + w2 * c[2]
    return None


def _compute_volumes_headless(
    existing_points: list[tuple[float, float, float]],
    existing_triangles: list[tuple[int, int, int]],
    proposed_points: list[tuple[float, float, float]],
    proposed_triangles: list[tuple[int, int, int]],
) -> tuple[float, float, "ClosedSolid", "ClosedSolid"]:
    """Inline prismoidal TIN-to-TIN volume math (~50 lines).

    Replicates the algorithm from ``bonsai.tool.earthwork.Earthwork.compute_volumes``
    without importing that module (which would pull in bonsai.__init__ → bpy).

    Per spec §5.4 acknowledgment: this is deliberate duplication — the demo
    doubles as a worked example for non-Bonsai consumers.

    Algorithm:
      For each proposed triangle × each intersecting existing triangle,
      clip their XY overlap and sub-triangulate. For each sub-triangle,
      accumulate signed prismoidal volume = area × (z_existing_avg − z_proposed_avg).
      Positive → cut; negative → fill. Build a prism-soup closed solid for each.

    Returns (cut_volume_m3, fill_volume_m3, cut_solid, fill_solid).
    """

    class SubTriangle:
        __slots__ = ("vertices_xy", "z_existing_avg", "z_proposed_avg", "area_m2")

        def __init__(self, vertices_xy, z_e, z_p, area):
            self.vertices_xy = vertices_xy
            self.z_existing_avg = z_e
            self.z_proposed_avg = z_p
            self.area_m2 = area

    class ClosedSolid:
        __slots__ = ("points", "faces")

        def __init__(self, pts, fcs):
            self.points = np.asarray(pts, dtype=float)
            self.faces = fcs

    # Build Shapely polygons for STRtree broad-phase.
    def _tri_poly(pts, tri):
        a, b, c = pts[tri[0]], pts[tri[1]], pts[tri[2]]
        return shapely.Polygon([(a[0], a[1]), (b[0], b[1]), (c[0], c[1])])

    existing_polys = [_tri_poly(existing_points, t) for t in existing_triangles]
    proposed_polys = [_tri_poly(proposed_points, t) for t in proposed_triangles]

    # Volume domain: convex hull of union of both point clouds.
    all_xy = [(p[0], p[1]) for p in existing_points + proposed_points]
    domain = shapely.MultiPoint(all_xy).convex_hull

    existing_tree = shapely.STRtree(existing_polys)

    cut_total = 0.0
    fill_total = 0.0
    cut_subs: list[SubTriangle] = []
    fill_subs: list[SubTriangle] = []

    for prop_poly in proposed_polys:
        candidate_idxs = existing_tree.query(prop_poly)
        for idx in candidate_idxs:
            ex_poly = existing_polys[int(idx)]
            clipped = prop_poly.intersection(ex_poly).intersection(domain)
            if clipped.is_empty or clipped.area <= 0:
                continue
            # Sub-triangulate the (possibly polygonal) overlap region.
            geoms = (
                [clipped]
                if clipped.geom_type == "Polygon"
                else (
                    [g for g in clipped.geoms if g.geom_type == "Polygon"]
                    if hasattr(clipped, "geoms")
                    else []
                )
            )
            for poly in geoms:
                if poly.area <= 0:
                    continue
                try:
                    tris = shapely.constrained_delaunay_triangles(poly)
                except Exception:
                    continue
                for sub in (tris.geoms if hasattr(tris, "geoms") else [tris]):
                    if sub.geom_type != "Polygon" or sub.area <= 0:
                        continue
                    coords = list(sub.exterior.coords)
                    if len(coords) < 4:
                        continue
                    verts_xy = np.array([(float(x), float(y)) for x, y in coords[:3]])
                    z_e_vals = [
                        _z_at_xy(existing_points, existing_triangles, float(x), float(y))
                        for x, y in verts_xy
                    ]
                    z_p_vals = [
                        _z_at_xy(proposed_points, proposed_triangles, float(x), float(y))
                        for x, y in verts_xy
                    ]
                    if any(v is None for v in z_e_vals) or any(v is None for v in z_p_vals):
                        continue
                    z_e_avg = float(np.mean(z_e_vals))
                    z_p_avg = float(np.mean(z_p_vals))
                    st = SubTriangle(verts_xy, z_e_avg, z_p_avg, float(sub.area))
                    signed = st.area_m2 * (st.z_existing_avg - st.z_proposed_avg)
                    if signed > 0:
                        cut_total += signed
                        cut_subs.append(st)
                    elif signed < 0:
                        fill_total += -signed
                        fill_subs.append(st)

    def _build_prism_soup(subs: list[SubTriangle], is_cut: bool) -> ClosedSolid:
        """One triangular prism per sub-triangle; 6 verts, 5 faces each."""
        all_pts: list[tuple[float, float, float]] = []
        all_faces: list[list[int]] = []
        for sub in subs:
            base = len(all_pts)
            xy = sub.vertices_xy
            for x, y in xy:
                all_pts.append((float(x), float(y), float(sub.z_proposed_avg)))
            for x, y in xy:
                all_pts.append((float(x), float(y), float(sub.z_existing_avg)))
            p0, p1, p2, p3, p4, p5 = (base + i for i in range(6))
            faces = [
                [p3, p4, p5],
                [p2, p1, p0],
                [p0, p1, p4, p3],
                [p1, p2, p5, p4],
                [p2, p0, p3, p5],
            ]
            if not is_cut:
                faces = [list(reversed(f)) for f in faces]
            all_faces.extend(faces)
        if not all_pts:
            # Degenerate fallback: a zero-volume prism so the API call succeeds.
            all_pts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0),
                       (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
            all_faces = [[3, 4, 5], [2, 1, 0], [0, 1, 4, 3], [1, 2, 5, 4], [2, 0, 3, 5]]
        return ClosedSolid(all_pts, all_faces)

    cut_solid = _build_prism_soup(cut_subs, is_cut=True)
    fill_solid = _build_prism_soup(fill_subs, is_cut=False)
    return cut_total, fill_total, cut_solid, fill_solid


def _build_pad_slope_ribbon(
    pad_verts: list[tuple[float, float, float]],
    terrain_points: list[tuple[float, float, float]],
    terrain_triangles: list[tuple[int, int, int]],
    slope_ratio: float,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    """Build a 4-sided slope-ribbon TIN around a rectangular pad.

    For each edge of the pad polygon, project horizontally outward by
    ``slope_ratio × height_difference`` to the terrain elevation.
    Returns (points, triangles) for the ribbon (one quad = 2 triangles per edge).
    ~25 lines.
    """
    ribbon_pts: list[tuple[float, float, float]] = []
    ribbon_tris: list[tuple[int, int, int]] = []

    n = len(pad_verts)
    # Start index in the ribbon_pts list for the pad vertices.
    for i, pv in enumerate(pad_verts):
        ribbon_pts.append(pv)

    for i in range(n):
        pv_a = pad_verts[i]
        pv_b = pad_verts[(i + 1) % n]
        mid_x = (pv_a[0] + pv_b[0]) / 2.0
        mid_y = (pv_a[1] + pv_b[1]) / 2.0
        edge_dx = pv_b[0] - pv_a[0]
        edge_dy = pv_b[1] - pv_a[1]
        edge_len = (edge_dx**2 + edge_dy**2) ** 0.5
        if edge_len < 1e-9:
            continue
        # Outward normal (pointing away from pad interior assumed at centroid ~25,25).
        pad_cx = sum(v[0] for v in pad_verts) / n
        pad_cy = sum(v[1] for v in pad_verts) / n
        nx = -(edge_dy / edge_len)
        ny = edge_dx / edge_len
        # Check outward direction.
        if (mid_x - pad_cx) * nx + (mid_y - pad_cy) * ny < 0:
            nx, ny = -nx, -ny

        pad_z = pv_a[2]  # Pad elevation (flat).
        terrain_z_mid = _z_at_xy(terrain_points, terrain_triangles, mid_x, mid_y)
        if terrain_z_mid is None:
            terrain_z_mid = pad_z - 1.0  # Fallback.
        dz = pad_z - terrain_z_mid
        horiz_dist = abs(dz) * slope_ratio + 0.5  # +0.5m minimum daylight projection.

        # Daylight points.
        dl_a_x = pv_a[0] + nx * horiz_dist
        dl_a_y = pv_a[1] + ny * horiz_dist
        dl_b_x = pv_b[0] + nx * horiz_dist
        dl_b_y = pv_b[1] + ny * horiz_dist
        dl_a_z = _z_at_xy(terrain_points, terrain_triangles, dl_a_x, dl_a_y) or (pad_z - dz)
        dl_b_z = _z_at_xy(terrain_points, terrain_triangles, dl_b_x, dl_b_y) or (pad_z - dz)

        # Add daylight vertices.
        idx_a_pad = i
        idx_b_pad = (i + 1) % n
        idx_a_dl = len(ribbon_pts)
        ribbon_pts.append((dl_a_x, dl_a_y, dl_a_z))
        idx_b_dl = len(ribbon_pts)
        ribbon_pts.append((dl_b_x, dl_b_y, dl_b_z))

        # Two triangles for this edge quad.
        ribbon_tris.append((idx_a_pad, idx_b_pad, idx_b_dl))
        ribbon_tris.append((idx_a_pad, idx_b_dl, idx_a_dl))

    return ribbon_pts, ribbon_tris


def _triangulate_pad_interior(
    pad_verts: list[tuple[float, float, float]],
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    """Fan-triangulate the pad interior from vertex 0. ~10 lines."""
    pts = list(pad_verts)
    tris: list[tuple[int, int, int]] = []
    for i in range(1, len(pts) - 1):
        tris.append((0, i, i + 1))
    return pts, tris


# ---------------------------------------------------------------------------
# Section A — Bootstrap
# ---------------------------------------------------------------------------


def _bootstrap_ifc_project() -> tuple[ifcopenshell.file, "ifcopenshell.entity_instance"]:
    """Create a minimal IFC4X3_ADD2 file with IfcProject + IfcSite."""
    ifc = ifcopenshell.file(schema="IFC4X3_ADD2")

    project = ifc.create_entity(
        "IfcProject",
        GlobalId=ifcopenshell.guid.new(),
        Name="Tier 1 Grading Demo",
        Description="Headless IFC grading demo — Saikei Civil Phase 7a",
    )

    length_unit = ifcopenshell.api.unit.add_si_unit(ifc, unit_type="LENGTHUNIT")
    area_unit = ifcopenshell.api.unit.add_si_unit(ifc, unit_type="AREAUNIT")
    volume_unit = ifcopenshell.api.unit.add_si_unit(ifc, unit_type="VOLUMEUNIT")
    ifcopenshell.api.unit.assign_unit(ifc, units=[length_unit, area_unit, volume_unit])

    site = ifc.create_entity(
        "IfcSite",
        GlobalId=ifcopenshell.guid.new(),
        Name="Demo Site",
        CompositionType="ELEMENT",
    )

    ifc.create_entity(
        "IfcRelAggregates",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=project,
        RelatedObjects=[site],
    )

    # georef omitted; production projects use
    # ifcopenshell.api.georeference.add_georeferencing

    return ifc, site


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


def main(output_path: pathlib.Path, csv_path: pathlib.Path = _DEFAULT_CSV) -> None:
    """Run the Tier 1 grading demo end-to-end.

    :param output_path: where to write the resulting IFC file.
    :param csv_path: path to the terrain CSV fixture.
    """
    # ------------------------------------------------------------------
    # Section A — bootstrap
    # ------------------------------------------------------------------
    ifc, site = _bootstrap_ifc_project()

    # ------------------------------------------------------------------
    # Section B — terrain
    # ------------------------------------------------------------------
    eg_points = _load_csv(csv_path)
    eg_triangles = _delaunay_xy(eg_points)

    terrain = ifcopenshell.api.surface.create_terrain(
        ifc,
        name="Existing Ground",
        points=eg_points,
        triangles=eg_triangles,
        site=site,
    )

    # Add a sample breakline along the terrain ridge.
    ifcopenshell.api.surface.add_breakline_annotation(
        ifc,
        site=site,
        polyline=[(0.0, 10.0, 99.1), (30.0, 10.0, 102.9)],
        name="Centerline",
        kind="standard",
    )

    # ------------------------------------------------------------------
    # Section C — grading
    # ------------------------------------------------------------------

    # Pad perimeter at elevation z=101.0 — straddles the terrain so we
    # get both cut (uphill/west side) and fill (downhill/east side).
    pad_z = 101.0
    pad_verts = [
        (10.0, 5.0, pad_z),
        (20.0, 5.0, pad_z),
        (20.0, 15.0, pad_z),
        (10.0, 15.0, pad_z),
    ]

    feature_line = ifcopenshell.api.grading.create_feature_line(
        ifc,
        name="Pad perimeter",
        vertices=pad_verts,
        closed=True,
        site=site,
    )

    criteria_template = ifcopenshell.api.grading.create_grading_criteria_template(ifc)

    grading = ifcopenshell.api.grading.create_grading_group(
        ifc,
        name="Pad Grading",
        target_surface=terrain,
        interior_fill="flat",
        site=site,
    )

    ifcopenshell.api.grading.assign_grading_criteria(
        ifc,
        grading.group,
        criteria_template,
        target_kind="surface",
        target_reference=terrain.GlobalId,
        cut_slope=2.0,
        fill_slope=3.0,
    )

    # Build slope ribbon + interior fill surfaces.
    slope_pts, slope_tris = _build_pad_slope_ribbon(
        pad_verts, eg_points, eg_triangles, slope_ratio=3.0
    )
    interior_pts, interior_tris = _triangulate_pad_interior(pad_verts)

    ifcopenshell.api.grading.add_slope_fill_to_group(
        ifc,
        grading.group,
        grading.composite_fill,
        name="Pad slope",
        points=slope_pts,
        triangles=slope_tris,
        feature_line=feature_line,
    )

    ifcopenshell.api.grading.add_interior_fill_to_group(
        ifc,
        grading.group,
        grading.composite_fill,
        name="Pad interior",
        points=interior_pts,
        triangles=interior_tris,
    )

    # ------------------------------------------------------------------
    # Section D — earthwork volumes
    # ------------------------------------------------------------------

    # Combine slope + interior into the proposed surface.
    proposed_points = slope_pts + interior_pts
    # Offset interior triangle indices to account for slope_pts offset.
    slope_count = len(slope_pts)
    proposed_triangles = list(slope_tris) + [
        (t[0] + slope_count, t[1] + slope_count, t[2] + slope_count)
        for t in interior_tris
    ]

    cut_volume, fill_volume, cut_solid, fill_solid = _compute_volumes_headless(
        eg_points, eg_triangles, proposed_points, proposed_triangles
    )

    # Cut entity.
    cut = ifcopenshell.api.earthwork.create_earthworks_cut(
        ifc,
        name="Pad excavation",
        points=[(float(x), float(y), float(z)) for x, y, z in cut_solid.points],
        faces=cut_solid.faces,
        predefined_type="EXCAVATION",
        site=site,
    )
    ifcopenshell.api.earthwork.void_terrain(ifc, cut, terrain)

    _cut_mins = cut_solid.points.min(axis=0)
    _cut_maxs = cut_solid.points.max(axis=0)
    _cut_length, _cut_width, _cut_depth = [
        max(float(v), 1e-6) for v in (_cut_maxs - _cut_mins).tolist()
    ]
    ifcopenshell.api.earthwork.write_cut_quantities(
        ifc,
        cut,
        length=_cut_length,
        width=_cut_width,
        depth=_cut_depth,
        undisturbed_volume=cut_volume,
        loose_volume=cut_volume * SWELL_FACTOR,
    )

    # Fill entity.
    fill = ifcopenshell.api.earthwork.create_earthworks_fill(
        ifc,
        name="Pad fill",
        points=[(float(x), float(y), float(z)) for x, y, z in fill_solid.points],
        faces=fill_solid.faces,
        predefined_type="EMBANKMENT",
        site=site,
    )
    ifcopenshell.api.earthwork.link_fill_to_cut(ifc, cut, fill)

    _fill_mins = fill_solid.points.min(axis=0)
    _fill_maxs = fill_solid.points.max(axis=0)
    _fill_length, _fill_width, _fill_depth = [
        max(float(v), 1e-6) for v in (_fill_maxs - _fill_mins).tolist()
    ]
    ifcopenshell.api.earthwork.write_fill_quantities(
        ifc,
        fill,
        length=_fill_length,
        width=_fill_width,
        depth=_fill_depth,
        compacted_volume=fill_volume,
        loose_volume=fill_volume / SHRINK_FACTOR,
    )

    # Shrink/swell psets on both entities.
    ifcopenshell.api.earthwork.apply_shrink_swell_pset(
        ifc, cut, shrink_factor=SHRINK_FACTOR, swell_factor=SWELL_FACTOR
    )
    ifcopenshell.api.earthwork.apply_shrink_swell_pset(
        ifc, fill, shrink_factor=SHRINK_FACTOR, swell_factor=SWELL_FACTOR
    )

    # ------------------------------------------------------------------
    # Section E — write + validate
    # ------------------------------------------------------------------
    output_path = pathlib.Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ifc.write(str(output_path))

    # Validate the written file.
    written_ifc = ifcopenshell.open(str(output_path))
    validation_logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(written_ifc, validation_logger)
    errors = [e for e in validation_logger.statements if e.get("level") == "ERROR"]
    if errors:
        raise AssertionError(
            f"IFC validation errors in {output_path}: {errors}"
        )

    net = cut_volume - fill_volume
    print(
        f"Cut: {cut_volume:.3f} m³, "
        f"Fill: {fill_volume:.3f} m³, "
        f"Net: {net:.3f} m³"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tier 1 grading demo — headless IFC authoring.")
    parser.add_argument(
        "output_path",
        nargs="?",
        default=str(_REPO_ROOT / "docs" / "grading" / "examples" / "tier1_demo.ifc"),
        help="Path to write the output IFC file (default: docs/grading/examples/tier1_demo.ifc)",
    )
    parser.add_argument(
        "--csv",
        default=str(_DEFAULT_CSV),
        help="Path to the terrain CSV fixture (default: docs/grading/examples/tier1_terrain.csv)",
    )
    args = parser.parse_args()
    main(output_path=pathlib.Path(args.output_path), csv_path=pathlib.Path(args.csv))

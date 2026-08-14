# Test Engineering Review: Saikei Grading & Earthwork Spec

**Reviewer:** saikei-tester agent
**Date:** 2026-04-24
**Subject:** [Saikei_Grading_Earthwork_Spec.md](Saikei_Grading_Earthwork_Spec.md)
**Review perspective:** The test engineer who owns the suite (currently 208 passing across core/tool/operator tiers for alignment) and will extend it for grading.

---

## Executive Summary

The spec is architecturally sound and testable, but it leaves critical test-infrastructure decisions open that must be closed before Sprint 1. The core risk is **testability tier creep** — decisions deferred to implementation will likely push math and TIN tests from pure-Python into Blender-headless unnecessarily. Below I evaluate the spec against 10 axes central to headless-first test strategy, then propose concrete file layout and test counts per sprint.

---

## 1. Testability per Sprint: Tier Assignment

| Sprint | Feature | Test Tier | Pure-Python | Blender-Headless | Notes |
|--------|---------|-----------|-------------|------------------|-------|
| **Sprint 1** | TIN build (unconstrained) | Core + Tool | ✓ | ✗ | `scipy.spatial.Delaunay` is pure Python |
| | TIN build (constrained CDT) | Tool | ✓ | ✗ | `shapely.constrained_delaunay_triangles` is pure Python |
| | Z interpolation (`z_at`) | Tool | ✓ | ✗ | Barycentric, no Blender deps |
| | Boundary/hole/void handling | Tool | ✓ | ✗ | Shapely polygon ops, pure Python |
| | `IfcGeotechnicalStratum` authoring | Tool IFC | ✓ | ✗ | `ifcopenshell.file()` in-memory, no Blender |
| | `IfcTriangulatedIrregularNetwork` round-trip | Tool IFC | ✓ | ✗ | Read/write via `ifcopenshell`, validate structure |
| | Blender mesh sync (`create_generic_shape`) | Tool Blender | ✗ | ✓ | Requires `tool.Loader.create_generic_shape()` → Blender API |
| | Surface panel + operators | UI | ✗ | ✓ | Blender operator registration, context, undo/redo |
| **Sprint 2** | Slope projection (all 4 methods) | Tool | ✓ | ✗ | Geometric computation, no Blender |
| | Feature line elevation edit cascade | Core | ✓ | ✗ | Dependency tracking, group rebuild orchestration |
| | `IfcAlignment` for feature lines | Tool IFC | ✓ | ✗ | Entity creation + polyline representation |
| | `IfcPropertySetTemplate` for criteria | Tool IFC | ✓ | ✗ | Pset template instantiation |
| | `IfcEarthworksFill[SLOPEFILL]` authoring | Tool IFC | ✓ | ✗ | Entity creation + aggregation |
| | Grading group composition | Tool | ✓ | ✗ | TIN merging logic (Delaunay on composite verts) |
| | Feature line + grading operators | UI | ✗ | ✓ | Blender picking, editing, visual feedback |
| **Sprint 3** | TIN-to-TIN prismoidal volume | Tool | ✓ | ✗ | Polygon intersection + barycentric interp, no Blender |
| | Cut/fill solid construction | Tool | ✓ | ✗ | BRep topology assembly, pure geometry |
| | `IfcPolygonalFaceSet` authoring | Tool IFC | ✓ | ✗ | Entity creation + validation |
| | Cut/fill color map | Tool Blender | ✗ | ✓ | Requires `bpy.data.meshes`, vertex colors |
| | Earthwork operators | UI | ✗ | ✓ | Panel integration, report display |

**Key insight:** The spec is **well-layered for headless testing**. Nearly all Tool-layer work (TIN math, volume calc, IFC authoring) is achievable in pure Python. Only mesh-sync and UI operators need Blender.

**Spec decision that preserves testability:** Using `shapely.constrained_delaunay_triangles` and `scipy.spatial.Delaunay` directly in Tool means no Blender dependency for triangulation. ✓

**Spec gap that could degrade testability:** Section 4.5 lists `tool.Loader.create_generic_shape()` as a shared tool for TIN→Blender mesh conversion. This is correct, but the spec should explicitly state: "TIN geometry representation testing happens in pure Python via `ifcopenshell` and property inspection; mesh-sync testing happens in Blender-headless tier with `tool.Loader` integration."

---

## 2. Fixture Needs — Test Data Sources

The spec introduces domain objects with non-trivial geometry. Tests need fixtures:

### Sprint 1 Fixtures

| Fixture | Purpose | Format | Source Prescription | Estimate |
|---------|---------|--------|-------------------|----------|
| `simple_point_cloud_100` | 100 random XYZ points in a 1000×1000×100 m envelope | CSV or list[tuple] | Generated in conftest.py via `np.random.seed(42)` | 5 points |
| `square_with_hole` | Outer 100×100 m square, 50×50 m hole at center | Shapely Polygon pair | Hand-authored in conftest, reused across tests | 10 points |
| `breakline_diagonal` | 3D polyline from (0,0,10) to (100,100,15) | list[tuple[float, float, float]] | Hand-authored, bridges TIN to test z_at interpolation | 2 segments |
| `real_world_site_tin` | 500-vertex TIN from USGS 1/3 arc-second DEM sample (site-scale) | `.tif` or pre-triangulated | Optional: if perf testing is in scope, fetch USGS tile once and cache | 500 verts |
| `existing_ground_ifc` | Valid in-memory IFC file with `IfcGeotechnicalStratum` + TIN | `ifcopenshell.file()` | Created by `test/core/bootstrap.py` fixture, reused across sprints | 1 file |

**Issue identified in spec:** Section 5 defines `CivilSurface` dataclass but does not commit to fixtures. The spec should prescribe:

> Tests for TIN math use generated synthetic point clouds (100–1000 vertices via `np.random.seed(42)` for reproducibility). Tests for IFC round-trip use a canonical in-memory IFC 4.3 file with a known TIN. A reference site-scale TIN (500+ vertices) is optional for performance testing in Sprint 3 but not required for MVP.

**Recommendation:** Commit fixture sources in a new `.claude/skills/earthwork/test_fixtures.md` document. Wire this into conftest.py before Sprint 1 code starts.

---

## 3. Numerical Tolerance Strategy

The spec is silent on tolerances. Surface math is numerically sensitive (coordinate precision, volume accumulation, barycentric interpolation). Tests without declared tolerances will flake.

### Proposed Tolerance Table

| Category | Operation | Tolerance | Justification |
|----------|-----------|-----------|---------------|
| **Coordinates** | Point-in-triangle, barycentric interp | 1e-9 m | Float64 machine epsilon at 1000 m scale |
| **Areas / Areas** | Triangle/polygon area calc | 1e-6 m² (1 µm²) | Rounding at 1000×1000 m extent |
| **Volumes** | Prismoidal volume, TIN-TIN diff | 0.1% of computed volume | Civil engineering practice (0.1 m³ on 1000 m³ is acceptable) |
| **Slopes** | Tangent, deflection angle | 1e-4 radians (~0.0057°) | Road design standard (< 1 in 100,000 grade error) |
| **Distances** | Segment length, station | 1e-6 m | Millimeter-scale precision at site extent |
| **Z interpolation** | `z_at(x, y)` in triangle | 1e-3 m (1 mm) | Grading design tolerance (1 cm max acceptable in civil practice) |

**Spec action item:** Section 6.4 (TIN-to-TIN volumes) should prescribe:

> Volume discrepancies due to numerical rounding are acceptable up to 0.1% of the computed volume. For a 1000 m³ cut, a 1 m³ tolerance is acceptable.

**Test-writing implication:** Every volume test must assert on a tolerance band, not an exact value. Example:

```python
def test_volume_prismoidal_simple_fill():
    """Unit test: 1 m³ fill (1m × 1m × 1m rectangular prism)."""
    existing_points = np.array([[0,0,0], [1,0,0], [1,1,0], [0,1,0]])
    existing_tri = np.array([[0,1,2], [0,2,3]])  # 2D square, z=0
    proposed_points = np.array([[0,0,1], [1,0,1], [1,1,1], [0,1,1]])
    proposed_tri = np.array([[0,1,2], [0,2,3]])  # 2D square, z=1

    result = Earthwork.volume_tin_to_tin(
        CivilSurface(..., points=existing_points, triangles=existing_tri),
        CivilSurface(..., points=proposed_points, triangles=proposed_tri)
    )
    assert abs(result.fill_volume_m3 - 1.0) < 1e-6  # 1 µm³ precision for unit test
```

---

## 4. Regression Corpus — Known-Answer Problems

The spec lacks closed-form test cases. This is a gap — volume/slope math tests need analytical reference values.

### Proposed Known-Answer Test Cases

| Test Case | Geometry | Expected Result | Reason |
|-----------|----------|-----------------|--------|
| **Volume: unit cube fill** | 1×1×1 m prism (existing at z=0, proposed at z=1) | fill = 1.0 m³, cut = 0.0 m³ | Trivial case validates core algorithm |
| **Volume: cone frustum** | Circular existing base (r=10m, z=0), circular proposed top (r=8m, z=5m) | fill ≈ 418.9 m³ (V = h(A1+A2+√(A1·A2))/3) | Civil standard; frustum formula is analytical |
| **Volume: prismatic embankment** | Trapezoidal x-section, 100 m long: base 30 m, top 20 m, height 5 m | fill ≈ 12,500 m³ (V = (b1+b2)/2 × h × L) | Road/embankment design standard |
| **Slope projection: 2:1 fill on flat** | Feature line at z=10m, existing ground z=5m, 2:1 slope projected to daylight | daylight at (x±10m, y, z=5m) from feature point | Trigonometric verification: distance = (z_diff) / slope |
| **Slope projection: 3:1 cut on flat** | Feature line at z=5m, existing ground z=10m, 3:1 cut slope | daylight at (x±15m, y, z=10m) | Verifies cut vs. fill slope direction reversal |
| **Z interpolation: barycentric** | Triangle verts (0,0,0), (10,0,5), (0,10,10); query (5,5,?) | z ≈ 7.5 m (centroid weighted) | Linear interp sanity check |
| **TIN boundary honor** | 10-point line defining a 100m × 50m outer boundary | outer polygon matches input; retriangulation respects boundary | Shapely's constrained Delaunay must not cross boundary |

**Spec action item:** Propose these cases in the test strategy doc. Each case must include the closed-form formula so reviewers can verify the expected result independently.

---

## 5. IFC Round-Trip Tests — Entity Graph Equivalence

The spec commits to IFC as the native persistence layer but does not prescribe round-trip testing strategy. This is a major gap.

### Proposed Round-Trip Test Structure

For each IFC entity introduced (Sprint 1 onwards), author a round-trip test:

```python
# test/tool/test_grading_ifc_roundtrip.py

class TestIfcTriangulatedIrregularNetworkRoundTrip:
    """Write a TIN to IFC, re-read it, verify structural equivalence."""

    def test_tin_vertices_preserved(self):
        """Input points → IfcCartesianPointList3D → re-read → verify match."""
        original_points = np.array([[0,0,0], [10,0,5], [0,10,10], [10,10,15]])
        surface = CivilSurface(
            guid=uuid.uuid4().hex,
            name="Test TIN",
            kind="existing",
            points=original_points,
            triangles=np.array([[0,1,2], [1,3,2]]),
            triangle_flags=np.array([0, 0]),
            ifc_host_entity_id=None,
        )

        # Write to IFC
        ifc_file = ifcopenshell.file(schema="IFC4X3")
        Surface.author_ifc_host(surface, ifc_file)
        Surface.author_ifc_tin_representation(surface, ifc_file)

        # Re-read and deserialize
        host_entity = ifc_file.by_id(surface.ifc_host_entity_id)
        tin_entity = ifc_file.by_id(surface.ifc_tin_representation_id)

        # Verify
        reread_coords = tin_entity.Coordinates.CoordList
        assert len(reread_coords) == 4
        for i, (x, y, z) in enumerate(reread_coords):
            assert abs(x - original_points[i, 0]) < 1e-9
            assert abs(y - original_points[i, 1]) < 1e-9
            assert abs(z - original_points[i, 2]) < 1e-9

    def test_breakline_flags_preserved(self):
        """Triangle flags → Flags list → re-read → verify match."""
        original_flags = np.array([0, 1, 1, 2])  # 0=normal, 1=on breakline 1, 2=on breakline 2
        surface = CivilSurface(
            guid=uuid.uuid4().hex,
            name="Test TIN with Flags",
            kind="existing",
            points=np.random.rand(5, 3) * 100,
            triangles=np.array([[0,1,2], [1,2,3], [2,3,4], [0,2,4]]),
            triangle_flags=original_flags,
        )

        # Write and re-read
        ifc_file = ifcopenshell.file(schema="IFC4X3")
        Surface.author_ifc_host(surface, ifc_file)
        Surface.author_ifc_tin_representation(surface, ifc_file)

        tin_entity = ifc_file.by_id(surface.ifc_tin_representation_id)
        reread_flags = tin_entity.Flags

        for i, flag in enumerate(original_flags):
            assert reread_flags[i] == flag

class TestIfcGeotechnicalStratumRoundTrip:
    """Write IfcGeotechnicalStratum, re-read, verify property inheritance."""

    def test_pset_geotechnical_stratum_type_common_attached(self):
        """Pset_GeotechnicalStratumTypeCommon must be attached via IfcRelDefinesByProperties."""
        # Write
        surface = CivilSurface(...)
        ifc_file = ifcopenshell.file(schema="IFC4X3")
        Surface.author_ifc_host(surface, ifc_file)
        Surface.apply_standard_psets(surface, ifc_file)

        # Re-read
        host_entity = ifc_file.by_id(surface.ifc_host_entity_id)
        pset = None
        for rel in ifc_file.by_type("IfcRelDefinesByProperties"):
            if host_entity in rel.RelatedObjects:
                for prop_set in rel.RelatingPropertyDefinition:
                    if prop_set.Name == "Pset_GeotechnicalStratumTypeCommon":
                        pset = prop_set
                        break

        assert pset is not None, "Pset_GeotechnicalStratumTypeCommon not found"
```

**Spec action item:** Add a "Round-Trip Testing" section to section 6 (Workflow Reference) or as a new section 14:

> Every IFC entity authored by Saikei undergoes a round-trip test: (1) author entity to in-memory IFC file, (2) re-read via `ifcopenshell.by_id()`, (3) deserialize and verify invariant properties (coordinates, relationships, classifications). Tests run without Blender, using pure-Python `ifcopenshell` API.

---

## 6. Property-Based Testing Candidates

Grading math has invariants that hold for all valid inputs. Property-based testing (via `hypothesis`) will catch corner cases.

### Proposed Hypothesis Tests

| Invariant | Scope | Hypothesis Strategy |
|-----------|-------|-------------------|
| **Daylight line stays on existing surface** | Sprint 2 slope projection | Generate random feature line + existing TIN; compute daylight line; verify each daylight point's Z matches surface Z at that (X,Y) within 1mm tolerance |
| **Cut + Fill volumes sum to net** | Sprint 3 volumes | Generate two TINs (existing, proposed) with random extents; compute cut, fill, net; assert `cut - fill ≈ net` (within 0.1% tolerance) |
| **Composite surface continuity** | Sprint 2 group composition | Generate N grading objects; compose into one TIN; verify no gaps or overlaps at feature line / daylight line boundaries (triangles share edges, no dangling verts) |
| **Breakline edge is not crossed** | Sprint 1 triangulation | Generate outer boundary + holes + breaklines; triangulate with CDT; verify no triangle edge crosses a breakline (all breakline vertices are in triangle edge lists) |
| **Barycentric interpolation sums to 1** | Sprint 1 Z interp | Generate random triangle + random point inside; compute barycentric coords; assert sum = 1.0 ± 1e-12 |
| **Slope projection respects outward direction** | Sprint 2 grading | Generate closed feature line (CCW); compute slope projections; verify all projection points are on the "outside" (determinant of (feature_pt, proj_pt, interior_pt) is positive) |

**Spec action item:** Commit to property-based testing in test strategy. Example:

```python
# test/tool/test_grading_properties.py
from hypothesis import given, strategies as st
import numpy as np

@given(st.lists(st.tuples(st.floats(-1000, 1000), st.floats(-1000, 1000)), min_size=3, max_size=100))
def test_barycentric_interpolation_sums_to_one(points):
    """For any triangle, barycentric coords of any interior point sum to 1.0."""
    if len(set(points)) < 3:
        return  # Skip degenerate cases
    p1, p2, p3 = points[:3]
    # ... compute barycentric for centroid ...
    assert abs(lambda1 + lambda2 + lambda3 - 1.0) < 1e-12
```

---

## 7. Determinism — Bit-Identical Output Guarantee

Triangulation algorithms (Delaunay, CDT) can produce non-deterministic output on tie-breaking (e.g., when 4 points are cocircular). This breaks test reproducibility.

**Spec gap:** Section 4.4 selects `shapely.constrained_delaunay_triangles` and `scipy.spatial.Delaunay` but does not address determinism.

**Recommendation:** Commit to seeding RNGs and avoiding floating-point tie-breaking where possible:

1. **For scipy.spatial.Delaunay:** Pre-sort points by (X, Y) to break ties consistently. Document: "Point cloud input is sorted lexicographically before triangulation to ensure deterministic output."

2. **For Shapely CDT:** The constrained Delaunay algorithm is inherently deterministic if inputs are consistent. But confirm: "Shapely 2.1+ CDT is deterministic for a given set of constraint polygons."

3. **Test isolation:** Every test that calls a triangulation function seeds `np.random.seed(42)` at the start. Example:

```python
def test_tin_build_with_breaklines():
    np.random.seed(42)
    points = np.random.rand(100, 3) * 1000
    breakline = [(10, 10, 0), (90, 90, 100)]

    tin1 = Surface.build_tin_from_points("test1", points, breakline)
    tin2 = Surface.build_tin_from_points("test2", points, breakline)

    # Verify bit-identical triangle arrays
    assert np.array_equal(tin1.triangles, tin2.triangles)
```

**Spec action item:** Add to section 4.4:

> Triangulation is deterministic: point clouds are sorted lexicographically before Delaunay, and Shapely's constrained Delaunay receives identical constraint polygons on every call. Tests seed `np.random.seed(42)` to ensure reproducibility across runs.

---

## 8. Performance Testing — Scale and Budget

The spec is silent on performance. Surface math scales O(n log n) for triangulation, O(mn) for volume intersection. Large inputs will have perf expectations.

### Proposed Perf Budgets

| Operation | Input Scale | Time Budget | Rationale |
|-----------|-------------|------------|-----------|
| **Delaunay (unconstrained)** | 100K vertices | < 5 sec | Typical site is 1000×1000 m @ 0.1 m spacing = ~100M points; but MVP is likely < 10K. SciPy Delaunay is O(n log n) and handles 100K in <1 sec on modern hardware. |
| **Delaunay (constrained CDT)** | 10K vertices + 20 breaklines | < 10 sec | Shapely is slower than unconstrained due to constraint satisfaction. 10K verts with breaklines is realistic for a complex site. |
| **Z interpolation (`z_at`)** | Query 1M random points on 10K-vertex TIN | < 1 sec | Point-in-triangle + barycentric is O(log n) with spatial indexing. Should be fast. |
| **TIN-to-TIN volume** | 10K existing, 10K proposed verts, ~100K triangle pairs | < 30 sec | Polygon intersection is O(mn), expensive. 100K pairs × O(intersection) is the bottleneck. 30 sec is tolerable for a one-time report. |
| **Slope projection (all 4 methods)** | Feature line 100 verts, existing TIN 10K verts, 1000 sample points | < 5 sec | Per-sample Z lookup + slope march is O(samples × log(TIN)). 1000 samples should be interactive. |

**Spec action item:** Add a Performance section to the testing guide:

> Sprint 3 includes a perf-test suite with time budgets for large inputs. Tests use `pytest-benchmark` to track regressions. Typical large-site inputs (10K vertices) must complete within 10 seconds per major operation (triangulation, volume calc, slope projection).

**No changes to spec itself** — perf testing is optional for MVP. But the budget should be stated somewhere discoverable.

---

## 9. Blender Tier Reduction — Pure-Python First

The spec is well-positioned for this: most Tool work is pure Python. But implementation will tempt shortcuts (e.g., authoring IFC via Blender-side code that has access to `bpy.context`).

**Spec action item:** Add an architecture note to section 4:

> **Pure-Python-First Rule:** All Tool-layer methods are testable without Blender. If a tool method signature includes `bpy.*` or `context`, that's a sign of layer violation. Core and Tool never depend on `bpy`. UI operators (Blender-side) call Tool methods and do not author IFC.

**Test file layout implication:** Tool tests are run via `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest ...` without Blender. If a tool test requires `bpy`, it's a refactoring signal.

---

## 10. Mock vs. Real IFC — Use Real for All Tool Tests

The spec is correct to use real `ifcopenshell.file()` in-memory files for tool tests, matching alignment precedent. Do not mock `ifcopenshell.api.*`.

**Spec confirmation:** Section 7.2 code examples call `ifc_file.create_entity()` directly, which is correct. This is already the alignment pattern.

**Test-writing rule:** Every Tool test that touches IFC does so with a real `ifcopenshell.file(schema="IFC4X3")` object. Example:

```python
def test_author_ifc_host_creates_stratum_for_existing():
    """Existing surface → IfcGeotechnicalStratum."""
    ifc_file = ifcopenshell.file(schema="IFC4X3")
    surface = CivilSurface(..., kind="existing")

    Surface.author_ifc_host(surface, ifc_file)

    host_entity = ifc_file.by_id(surface.ifc_host_entity_id)
    assert host_entity.is_a("IfcGeotechnicalStratum")
```

No mocking of `ifcopenshell.api` — exercise the real API where it exists.

---

## Summary: Test File Structure Proposal

```
src/bonsai/test/
├── core/
│   ├── test_alignment.py              (existing, 34 tests)
│   ├── test_grading.py                (new — Sprint 2, ~40 tests)
│   ├── test_earthwork.py              (new — Sprint 3, ~20 tests)
│   └── bootstrap.py                   (existing fixtures + Prophecy mocks)
│
├── tool/
│   ├── test_alignment.py              (existing, 135 tests)
│   ├── test_surface.py                (new — Sprint 1, ~60 tests)
│   │   ├── TIN construction (unconstrained, CDT, breaklines)     ~25 tests
│   │   ├── Z interpolation + boundary/hole/void                 ~20 tests
│   │   ├── IFC IfcGeotechnicalStratum + TIN round-trip          ~15 tests
│   ├── test_grading.py                (new — Sprint 2, ~80 tests)
│   │   ├── All four slope projection methods                     ~40 tests
│   │   ├── Feature line cascade rebuild                          ~20 tests
│   │   ├── Grading group composition (interior fill strategies)  ~20 tests
│   ├── test_earthwork.py              (new — Sprint 3, ~50 tests)
│   │   ├── TIN-to-TIN prismoidal volume (known-answer cases)    ~20 tests
│   │   ├── Cut/fill solid construction                          ~15 tests
│   │   ├── IFC IfcPolygonalFaceSet round-trip                   ~15 tests
│   └── test_grading_properties.py     (new — property-based, ~10 tests)
│       ├── @hypothesis tests for invariants (all sprints)
│
└── bim/module/alignment/test_alignment_operators.py (existing, 39 tests)
    (will add new files for surface/grading/earthwork operators — Sprint 1+)
```

### Test Count Estimate by Sprint

| Sprint | Layer | Count | Notes |
|--------|-------|-------|-------|
| **1** | Core | 0 | No new core logic (surface is tool-only in MVP) |
| | Tool | 60 | TIN build, z_at, boundaries, IFC round-trip |
| | UI/Blender | 15 | Surface panel + 3-4 operators |
| | **Total** | **75** | All runnable via `pytest test/tool/test_surface.py --override-ini="addopts="` (pure Python) |
| **2** | Core | 40 | Feature line edits, group rebuild orchestration, cascade logic |
| | Tool | 80 | Slope projection (4 methods), feature line, criteria, group composition |
| | UI/Blender | 20 | Grading operators (create group, add object, edit elevations) |
| | **Total** | **140** | Tool tests pure Python; UI tests Blender-headless |
| **3** | Core | 20 | Volume compute orchestration, earthwork report structure |
| | Tool | 50 | Prismoidal volume (with known-answer cases), solid construction, IFC round-trip |
| | UI/Blender | 20 | Earthwork operators (compute volumes, color map, export) |
| | **Total** | **90** | Same split: Tool pure Python, UI Blender-headless |
| **All** | **Total** | **305** | 208 from alignment (existing), +75+140+90=305 new grading tests |

---

## Critical Gaps in Spec for Test Planning

1. **Fixture sources not prescribed.** Spec should commit: "Synthetic point clouds via `np.random.seed(42)`, canonical IFC test file in conftest.py, optional real-world USGS DEM for perf tests."

2. **Numerical tolerances entirely absent.** Propose tolerance table above; add to spec section 6 or 14.

3. **Known-answer test cases missing.** Spec lists cone frustum, prismatic embankment, etc. as validation examples but does not commit to closed-form formulas for test cases.

4. **Round-trip testing strategy not mentioned.** Add: "Every IFC entity has a round-trip test."

5. **Determinism not addressed.** Triangulation tie-breaking could cause flaky tests. Specify seeding + lexicographic sort.

6. **Performance budgets not stated.** For a spec that touches triangulation (O(n log n)) and volume intersection (O(mn)), perf budgets matter.

7. **IFC API authoring pattern not enforced.** Spec section 7.2 shows correct `ifc_file.create_entity()` patterns, but no rule preventing Tool methods from accepting `bpy.*` arguments.

8. **Blender-headless test infrastructure not mentioned.** Spec should note: "Tool tests run via `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`. UI tests run via `--blender-executable`.

---

## Actionable Recommendations

### Pre-Sprint-1

1. **Create `.claude/skills/earthwork/test_fixtures.md`** — prescribe all fixture sources (synthetic, canonical IFC, optional real DEM).
2. **Add Tolerance section to spec section 6:** State coordinate/area/volume/slope tolerances table above.
3. **Add Known-Answer Test Cases to section 6:** List cone frustum, prismatic embankment, 2:1 slope, etc. with closed-form formulas.
4. **Add Pure-Python-First architecture note to section 4:** No `bpy` in Tool methods; mark layer violations clearly.

### Sprint 1 Planning

- Core layer: 0 new tests (surface is tool-only).
- Tool layer: 60 pure-Python tests (TIN, Z interp, boundaries, IFC round-trip via `ifcopenshell`).
- UI layer: 15 Blender-headless tests (panel, operators).
- **Test run:** `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest test/tool/test_surface.py -v` (no Blender).
- **Setup:** Add `test/tool/conftest.py` fixture file with synthetic points, canonical IFC template.

### Sprint 2 Planning

- Core layer: 40 pure-Python tests (orchestration, cascade edit logic).
- Tool layer: 80 pure-Python tests (slope projection, group composition, IFC authoring).
- UI layer: 20 Blender-headless tests (grading operators).
- **Property-based tests:** Start with 5-10 `@hypothesis` tests for slope direction, composite continuity.

### Sprint 3 Planning

- Tool layer: 50 pure-Python tests, including 20 with known-answer volume cases (cone frustum, embankment, etc.).
- IFC round-trip: Full `IfcPolygonalFaceSet` closed-solid validation.
- **Performance baseline:** Add 5 perf tests (10K-vertex scale) with benchmark tracking.

---

## Final Flags for Spec Reviewers

| Issue | Severity | Action |
|-------|----------|--------|
| Fixture sources undefined | Medium | Add `.claude/skills/earthwork/test_fixtures.md` before Sprint 1 code |
| Numerical tolerances silent | High | Add tolerance table to spec section 6 |
| No closed-form test cases | Medium | Commit cone frustum, prismatic embankment cases to spec |
| Determinism not addressed | Medium | Prescribe lexicographic sort + seed(42) in spec 4.4 |
| IFC authoring pattern not enforced | Low | Document "no bpy in Tool methods" as architecture rule |
| Performance budgets open | Low | State budgets in testing section (optional for MVP but discovered early) |
| Round-trip testing silent | Medium | Add section 14 to spec: "Round-Trip IFC Testing" |

---

**Conclusion:** The spec is **well-structured for headless testability**. With the tolerance, fixture, and round-trip testing decisions documented above before Sprint 1 starts, the test suite will be maintainable, deterministic, and achievable without forced Blender launches. Core recommendation: add three pre-Sprint-1 documents to `.claude/skills/earthwork/` covering fixtures, tolerances, and known-answer cases. This will unblock agent test-writing immediately.

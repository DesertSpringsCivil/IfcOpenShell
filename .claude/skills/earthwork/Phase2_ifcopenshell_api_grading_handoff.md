# Phase 2 hand-off — `ifcopenshell.api.grading`

**Sequencing:** Phase 1 (`ifcopenshell.api.surface`) shipped 2026-04-28 — 11 atomic commits, 47 tests, schema-clean. Phase 2 builds on top.

**Branch:** `saikei-dev` on the `desertspringscivil/IfcOpenShell` fork. Rebase up to `IfcOpenShell/IfcOpenShell saikei` when Phase 2 is review-ready.

**Workflow:** Drive Claude Code through the commit list below. Twelve atomic commits, each independently reviewable. Run tests after every commit.

---

## Spec amendment needed

**None.** v3.2.3 of `Saikei_Grading_Earthwork_Spec.md` already declares "Phase 2 ready" in its status line and has been corrected for the IFC 4.3.2 closed-tessellation guidance. Start coding.

---

## Phase 2 scope

Build `ifcopenshell.api.grading` — a high-level Python API for authoring grading objects, criteria templates, and grading groups in IFC 4.3. **No Bonsai code, no Blender dependency.** Tests run pure-Python via pytest, same harness as Phase 1.

Entities the API authors:

- `IfcAlignment` (feature lines, 3D polyline representation; reuses
  `ifcopenshell.api.alignment.create_as_polyline`)
- `IfcGroup` with `ObjectType="GradingGroup"` (the grading-group entity proper)
- `IfcEarthworksFill[SUBGRADE]` (per-group composite shell; aggregates the
  child fills via `IfcRelAggregates`)
- `IfcEarthworksFill[SLOPEFILL]` (one per grading object — the ribbon between
  feature line and daylight)
- `IfcEarthworksFill[SUBGRADE]` (interior fill, optional, when
  `interior_fill != "none"`)
- `IfcPropertySetTemplate` (project-scope, reusable criteria definition)
- `IfcPropertySet` instances bound to a template (the values of the criteria
  applied to a specific group)
- `IfcRelAssignsToGroup` (group membership)
- `IfcRelAggregates` (composite-fill aggregation tree)
- `IfcRelDefinesByProperties` for `Pset_SaikeiGradingSource`,
  `Pset_SaikeiFeatureLineCommon`, `Pset_SaikeiGradingAlignment`
- `IfcRelAssociatesClassification` for OmniClass Table 22 codes on every
  authored fill

Reuses from Phase 1 (no rework):

- `ifcopenshell.api.surface.add_tin_representation` for the SurfaceModel TINs
  on slope and interior fills
- `ifcopenshell.api.surface.add_bounding_box_representation` for LOD
  representations on the same fills
- `ifcopenshell.api.surface._representation_context` subcontext getters

**Out of scope for Phase 2:**

- Slope projection math (computes daylight line / projection ribbon) — lives
  in Bonsai's `tool.Grading` (Phase 5)
- Cut/fill volume math and closed-solid construction — Phase 3
  (`ifcopenshell.api.earthwork`) and Bonsai `tool.Earthwork` (Phase 6)
- Site-level composite aggregation (the `IfcEarthworksFill[SUBGRADE]` that
  aggregates per-group composites under IfcSite). The per-group composite
  *is* returned by `create_grading_group` so a future
  `aggregate_group_to_site_composite` helper or the Phase 4/5 Bonsai code can
  wire it up. See "Implementation notes — site composite hand-off" below.
- Cascade-on-edit behavior (Civil 3D-style dynamic grading) — Phase 5

---

## File tree (new files)

All paths relative to `src/ifcopenshell-python/ifcopenshell/api/grading/`:

```
grading/
├── __init__.py                              # Module docstring + public re-exports
├── _shared.py                               # Internal: site resolution, OmniClass classification, fill-host helper
├── add_member_to_group.py                   # Lower-level: IfcRelAssignsToGroup
├── add_slope_fill_to_group.py               # Top-level: IfcEarthworksFill[SLOPEFILL] + TIN + group/aggregate wiring
├── add_interior_fill_to_group.py            # Top-level: IfcEarthworksFill[SUBGRADE] interior + group/aggregate wiring
├── assign_grading_criteria.py               # Instantiate IfcPropertySet from a template, attach to group
├── create_feature_line.py                   # Top-level: IfcAlignment polyline + Pset_SaikeiFeatureLineCommon
├── create_grading_criteria_template.py      # IfcPropertySetTemplate authoring
├── create_grading_group.py                  # IfcGroup + per-group composite IfcEarthworksFill shell + Pset_SaikeiGradingSource
└── link_alignment_to_group.py               # Pset_SaikeiGradingAlignment (corridor linkage)
```

Plus tests at `src/ifcopenshell-python/test/api/test_grading.py` (single file
with one class per public function — same shape as
`test/api/test_surface.py`). Plus a runnable
`src/ifcopenshell-python/test/api/demo_grading.py`.

---

## Public function signatures

Every function takes `file: ifcopenshell.file` as the first arg. Type-hinted with
`ifcopenshell.entity_instance` forward references. NamedTuples used where two
related entities are returned, so callers can destructure clearly.

### `create_feature_line`

```python
def create_feature_line(
    file: "ifcopenshell.file",
    name: str,
    vertices: "list[tuple[float, float, float]]",
    *,
    closed: bool = False,
    source: "Literal['manual', 'drape', 'corridor_extract', 'csv_import']" = "manual",
    elevation_source: str = "manual",
    grading_group_guid: str | None = None,
    site: "ifcopenshell.entity_instance | None" = None,
) -> "ifcopenshell.entity_instance":
    """Create an IfcAlignment whose representation is a 3D IfcIndexedPolyCurve.

    Feature lines are Civil 3D's grading-footprint primitive: a 3D polyline
    with elevations at each vertex. Saikei persists them as IfcAlignment to
    reuse the alignment infrastructure (segments, stationing, picker UI) and
    because IFC 4.3 explicitly lists IfcPolyline as a valid alignment
    representation. Per-vertex elevations are encoded directly in the polyline
    coordinates, so no IfcAlignmentVertical is created.

    The alignment is contained in IfcSite via IfcRelContainedInSpatialStructure.
    Pset_SaikeiFeatureLineCommon is attached with IsClosed, Source,
    ElevationSource, and (optionally) GradingGroupGuid.

    Args:
        file: The IFC file to author into.
        name: Human-readable name for the feature line.
        vertices: An ordered sequence of (x, y, z) points; at least two required.
        closed: Whether the polyline is closed (typical for pad perimeters).
            When True, the polyline first vertex is repeated as the last segment
            endpoint at IFC author time.
        source: Free-form provenance label.
        elevation_source: How vertex elevations were obtained (e.g., "drape" if
            interpolated from an existing surface).
        grading_group_guid: Optional GUID of the grading group this feature
            line is a member of.
        site: The IfcSite to attach to. If None, the project's first IfcSite is used.

    Returns:
        The created IfcAlignment.

    Raises:
        ValueError: if vertices has fewer than two points, or site is None and
            no IfcSite exists in the project.
    """
```

### `create_grading_criteria_template`

```python
def create_grading_criteria_template(
    file: "ifcopenshell.file",
    name: str,
    *,
    target_kind: "Literal['surface', 'elevation', 'relative_elevation', 'distance']",
    cut_slope: float,
    fill_slope: float,
    max_distance: float | None = None,
    retaining_wall_at_limit: bool = False,
    description: str | None = None,
) -> "ifcopenshell.entity_instance":
    """Create a project-scope, reusable IfcPropertySetTemplate for grading criteria.

    The template defines the parameter STRUCTURE of Pset_SaikeiGradingCriteria
    (target_kind, cut_slope, fill_slope, max_distance, retaining_wall_at_limit).
    It does not bind to any specific group — that's assign_grading_criteria's
    job. One template can be assigned to many grading groups, each with its
    own value bindings.

    Authors:
      - IfcPropertySetTemplate with TemplateType=PSET_OCCURRENCEDRIVEN
      - Five IfcSimplePropertyTemplate entities (one per property)
      - Connection back to the project so the template is project-scope
        discoverable

    Default values stored on the template are used as fallback when an
    instance binding does not override them.

    Returns:
        The created IfcPropertySetTemplate.

    Raises:
        ValueError: if target_kind is not one of the four allowed values.
    """
```

### `create_grading_group`

```python
class GradingGroupAuthoring(NamedTuple):
    """Result of create_grading_group — both entities the caller now owns."""
    group: "ifcopenshell.entity_instance"          # IfcGroup ObjectType="GradingGroup"
    composite_fill: "ifcopenshell.entity_instance" # IfcEarthworksFill[SUBGRADE]


def create_grading_group(
    file: "ifcopenshell.file",
    name: str,
    *,
    target_surface: "ifcopenshell.entity_instance | None" = None,
    interior_fill: "Literal['none', 'flat', 'interpolate_from_boundary', 'from_surface']" = "interpolate_from_boundary",
    interior_fill_source: "ifcopenshell.entity_instance | None" = None,
    site: "ifcopenshell.entity_instance | None" = None,
    author: str | None = None,
) -> GradingGroupAuthoring:
    """Create the entity pair that constitutes a Saikei grading group.

    Authors two related entities:

    1. IfcGroup with ObjectType="GradingGroup" — the logical collection.
       NOT placed in the spatial tree (IfcGroup is not an IfcProduct).
       Discovered via by_type("IfcGroup") + ObjectType filter.

    2. IfcEarthworksFill[SUBGRADE] — the per-group composite shell that will
       aggregate slope fills and interior fill via IfcRelAggregates as those
       are added by add_slope_fill_to_group / add_interior_fill_to_group.
       Spatially contained in IfcSite via IfcRelContainedInSpatialStructure
       at creation. Standard Pset_EarthworksFillCommon and OmniClass
       classification attached.

    Pset_SaikeiGradingSource is attached to the IfcGroup with criteria
    reference (set later by assign_grading_criteria), author, timestamp,
    and version.

    Site-composite hand-off: the composite_fill returned here is intended to
    later be aggregated under a site-level IfcEarthworksFill[SUBGRADE] (the
    "site composite" authored via api.surface.create_proposed_surface). That
    aggregation is OUT OF SCOPE for Phase 2 — it lives in Phase 4/5 Bonsai
    glue code or a future api.grading helper. The composite_fill is returned
    so callers can wire it up.

    Args:
        file: The IFC file to author into.
        name: Human-readable name.
        target_surface: The existing-ground surface this group is grading
            against (typically an IfcGeographicElement[TERRAIN]). Recorded
            on Pset_SaikeiGradingSource. Optional at creation time.
        interior_fill: Interior fill strategy — see §6.3 of the spec.
        interior_fill_source: Required when interior_fill="from_surface";
            ignored otherwise.
        site: The IfcSite to attach the composite_fill to. If None, the
            project's first IfcSite is used.
        author: Free-form author label for Pset_SaikeiGradingSource.

    Returns:
        GradingGroupAuthoring(group, composite_fill).
    """
```

### `assign_grading_criteria`

```python
def assign_grading_criteria(
    file: "ifcopenshell.file",
    group: "ifcopenshell.entity_instance",
    criteria_template: "ifcopenshell.entity_instance",
    *,
    target_kind: str | None = None,
    cut_slope: float | None = None,
    fill_slope: float | None = None,
    max_distance: float | None = None,
    retaining_wall_at_limit: bool | None = None,
) -> "ifcopenshell.entity_instance":
    """Bind a criteria template to a grading group, optionally overriding values.

    Creates an IfcPropertySet bound to the supplied IfcPropertySetTemplate
    via HasPropertyTemplates, and attaches it to the group via
    IfcRelDefinesByProperties. Values left at None inherit the template's
    defaults; values supplied here override.

    If the group already has a Pset_SaikeiGradingCriteria binding, the
    existing IfcPropertySet is updated in place rather than duplicating —
    re-assigning is a "change criteria" operation.

    Returns:
        The IfcPropertySet (template-bound) that carries the values.

    Raises:
        ValueError: if criteria_template is not a Pset_SaikeiGradingCriteria
            template (defensive — shape-checks the entity type and name).
    """
```

### `add_slope_fill_to_group`

```python
def add_slope_fill_to_group(
    file: "ifcopenshell.file",
    group: "ifcopenshell.entity_instance",
    *,
    name: str,
    points: "PointArray",
    triangles: "TriangleArray",
    triangle_flags: "FlagArray" = None,
    feature_line: "ifcopenshell.entity_instance | None" = None,
    site: "ifcopenshell.entity_instance | None" = None,
) -> "ifcopenshell.entity_instance":
    """Author an IfcEarthworksFill[SLOPEFILL] containing the slope-projection ribbon.

    Authors the fill with:
      - IfcTriangulatedIrregularNetwork SurfaceModel representation (via
        api.surface.add_tin_representation — Phase 1 reuse)
      - IfcBoundingBox Box LOD representation (via Phase 1 reuse)
      - IfcRelContainedInSpatialStructure attaching to IfcSite
      - Pset_EarthworksFillCommon (Status="NEW")
      - OmniClass Table 22 classification (22-07 31 23 Fill)
      - IfcRelAssignsToGroup attaching to the supplied grading group
      - IfcRelAggregates attaching to the group's per-group composite_fill

    The "group's composite_fill" is discovered by walking
    group.IsGroupedBy → IfcRelAssignsToGroup → RelatedObjects looking for the
    IfcEarthworksFill[SUBGRADE] member with no aggregation parent (i.e., the
    composite that was created alongside the group). If that lookup fails —
    callers built the group some other way — ValueError is raised.

    Args:
        feature_line: Optional IfcAlignment whose criteria produced this slope
            fill. When provided, the fill is also assigned to the group's
            members (in addition to the slope-fill itself), establishing the
            traceability link between projection and source.

    Returns:
        The created IfcEarthworksFill.
    """
```

### `add_interior_fill_to_group`

Same shape as `add_slope_fill_to_group` but with `PredefinedType=SUBGRADE`,
OmniClass code `22-07 31 16` (Excavation and Fill), and only one allowed per
group (raises `ValueError` if a SUBGRADE-interior is already attached). No
`feature_line` parameter — interior fills are derived from the group as a whole.

### `link_alignment_to_group`

```python
def link_alignment_to_group(
    file: "ifcopenshell.file",
    group_or_fill: "ifcopenshell.entity_instance",
    alignment: "ifcopenshell.entity_instance",
    *,
    start_station: float | None = None,
    end_station: float | None = None,
) -> "ifcopenshell.entity_instance":
    """Attach Pset_SaikeiGradingAlignment to a group or fill, recording corridor linkage.

    Used when grading is being authored alongside a corridor — the AlignmentGuid,
    StartStation, and EndStation give cost-estimating tools the station range
    over which the grading applies.

    If the pset is already attached, values are updated in place. Returns the
    IfcPropertySet.

    Raises:
        ValueError: if group_or_fill is not an IfcGroup or IfcEarthworksFill,
            or if alignment is not an IfcAlignment.
    """
```

### `add_member_to_group`

```python
def add_member_to_group(
    file: "ifcopenshell.file",
    group: "ifcopenshell.entity_instance",
    *products: "ifcopenshell.entity_instance",
) -> "ifcopenshell.entity_instance":
    """Attach one or more IfcProduct entities to an IfcGroup.

    Lower-level building block. If the group already has an IfcRelAssignsToGroup
    rel, products are appended to its RelatedObjects (de-duplicated). Otherwise
    a new rel is created.

    Returns:
        The IfcRelAssignsToGroup (existing or newly created).

    Raises:
        ValueError: if group is not an IfcGroup, or products contains a non-IfcProduct.
    """
```

---

## Implementation notes

**Site resolution.** Mirrors Phase 1's `_resolve_site` helper — if `site=None`,
use `file.by_type("IfcSite")[0]`; raise `ValueError` if no IfcSite exists.
Lift this into `_shared.py` and call from each top-level function (don't
import from the Phase 1 surface package — that creates an inter-API
dependency that's awkward to track).

**OmniClass classification.** Add `_apply_omniclass_classification(file,
product, code, title)` to `_shared.py`. Authors `IfcClassification`
(once per file, idempotent), `IfcClassificationReference` (once per code),
and `IfcRelAssociatesClassification` (one per product). The
`IfcClassification` is named "OmniClass Table 22"; the
`IfcClassificationReference` carries `Identification=code` and `Name=title`.

**TIN attachment for slope/interior fills.** Don't re-author TIN logic — call
`ifcopenshell.api.surface.add_tin_representation` and
`ifcopenshell.api.surface.add_bounding_box_representation` directly. This
keeps the Phase 1 contract honest: every TIN in the file is authored by the
same code path, no drift.

**`Pset_SaikeiGradingSource` properties.** Per §3.3, this carries:
- `CriteriaReference` (IfcLabel, optional) — GUID of the assigned
  `IfcPropertySetTemplate`; populated by `assign_grading_criteria` after the
  fact, not by `create_grading_group`.
- `Author` (IfcLabel, optional)
- `Timestamp` (IfcTimeStamp, optional) — set to "now" at creation time
- `Version` (IfcInteger, default 1) — incremented on each rebuild (out of
  scope for Phase 2; just initialize to 1)
- `TargetSurfaceGuid` (IfcLabel, optional) — GUID of the existing-ground
  surface
- `InteriorFillStrategy` (IfcLabel) — one of the four strategy values

The pset is created with these properties at group-creation time. To satisfy
the schema's `HasProperties [1:?]` cardinality, ensure at least one property
is always written — `Version=1` is the minimum guaranteed value.

**`IfcPropertySetTemplate` authoring.** This is the most schema-heavy commit
in the phase. Reference shape:

```
IfcPropertySetTemplate
  Name = "Pset_SaikeiGradingCriteria"
  TemplateType = "PSET_OCCURRENCEDRIVEN"
  ApplicableEntity = "IfcGroup"
  HasPropertyTemplates = [
    IfcSimplePropertyTemplate(Name="TargetKind",     PrimaryMeasureType="IfcLabel",   ...),
    IfcSimplePropertyTemplate(Name="CutSlope",       PrimaryMeasureType="IfcReal",    ...),
    IfcSimplePropertyTemplate(Name="FillSlope",      PrimaryMeasureType="IfcReal",    ...),
    IfcSimplePropertyTemplate(Name="MaxDistance",    PrimaryMeasureType="IfcLengthMeasure", ...),
    IfcSimplePropertyTemplate(Name="RetainingWallAtLimit", PrimaryMeasureType="IfcBoolean", ...),
  ]
```

Project-scope discovery: `IfcPropertySetTemplate` instances are not
referenced from `IfcProject` directly — they live as top-level entities and
are found via `file.by_type("IfcPropertySetTemplate")` filtered by `Name`.
The connection between a template and its instance is via
`IfcRelDefinesByTemplate` (instance-side) — not the other direction.

**`IfcPropertySet` bound to a template.** When `assign_grading_criteria`
instantiates the pset, it MUST set the `HasPropertyTemplates` inverse
correctly via an `IfcRelDefinesByTemplate` relating the template to the
pset's properties. The pset itself has `Name=template.Name` (i.e.,
`"Pset_SaikeiGradingCriteria"`) and `HasProperties` populated with
`IfcPropertySingleValue`s whose names match the template's.

**`Pset_SaikeiFeatureLineCommon` properties.** `IsClosed` (IfcBoolean),
`Source` (IfcLabel), `ElevationSource` (IfcLabel),
`GradingGroupGuid` (IfcLabel, optional).

**`Pset_SaikeiGradingAlignment` properties.** `AlignmentGuid` (IfcLabel),
`StartStation` (IfcLengthMeasure, optional), `EndStation` (IfcLengthMeasure,
optional).

**Composite-fill discovery in `add_slope_fill_to_group` /
`add_interior_fill_to_group`.** Walk `group.IsGroupedBy[*].RelatedObjects`
looking for an `IfcEarthworksFill` whose `Decomposes` is empty (i.e., not
yet aggregated under a parent). That's the per-group composite. Cache nothing
— the inverse-walk is fast on a single-group scope.

**`create_feature_line` polyline encoding.** Use
`IfcIndexedPolyCurve` with an `IfcCartesianPointList3D` for compactness when
`vertices` exceeds ~10 points; fall back to `IfcPolyline` with
`IfcCartesianPoint`s for short feature lines (more readable in the IFC step
file). The `closed` flag is implemented by repeating the first vertex at the
end, not by an explicit "closed" attribute (IFC 4.3 doesn't have one for
these representation items).

Alternatively — and what I recommend — always use `IfcIndexedPolyCurve`
for consistency with the Phase 1 breakline annotation pattern and Rick
Brice's alignment work. Drop the `IfcPolyline` fallback unless we hit a
specific consumer that can't read it.

---

## Test plan

Tests live at `src/ifcopenshell-python/test/api/test_grading.py`. Pure pytest,
no Blender. Per-function class structure (precedent: `test_surface.py`).

**Fixtures (lift from Phase 1's test file or duplicate):**

- `empty_project_file` — IFC4X3_ADD2 with IfcProject, SI unit, IfcSite.
  Identical to Phase 1's fixture; lift it.
- `flat_pad_geometry`, `_pyramid_geometry` — same as Phase 1; reuse for
  slope/interior fill TIN tests.
- `feature_line_vertices` — a closed 4-vertex pad perimeter at z=100.
- `slope_ribbon_geometry` — 8 triangles forming a sloped ribbon between an
  inner pad perimeter and an outer daylight loop. Hand-calculable.

**Test cases per function (minimum):**

1. **`create_feature_line`** — happy path; closed flag round-trips; pset
   properties round-trip; site auto-resolution; ValueError on
   < 2 vertices; ValueError on no-site.

2. **`create_grading_criteria_template`** — happy path; the template carries
   exactly five property templates with correct `PrimaryMeasureType`s;
   ValueError on bad target_kind; round-trip through disk.

3. **`create_grading_group`** — happy path; returns a
   `GradingGroupAuthoring` named tuple; `composite_fill` is properly
   contained in IfcSite; group is NOT contained (verifies IfcGroup ≠ IfcProduct
   handling); `Pset_SaikeiGradingSource` carries the expected initial values.

4. **`assign_grading_criteria`** — happy path; values bound on the IfcPropertySet
   match the supplied overrides where given, template defaults otherwise;
   re-assigning updates in place (no duplicate pset); ValueError if the
   passed template is not a Pset_SaikeiGradingCriteria template.

5. **`add_slope_fill_to_group`** — happy path; the new fill is both a member
   of the group (IfcRelAssignsToGroup) AND aggregated under the composite
   (IfcRelAggregates); OmniClass classification attached; standard
   pset attached; round-trip; ValueError when the group has no composite_fill
   (i.e., a malformed group).

6. **`add_interior_fill_to_group`** — happy path; only one allowed per group
   (second call raises ValueError); same group-membership and aggregation
   wiring as slope fill.

7. **`link_alignment_to_group`** — happy path on IfcGroup; happy path on
   IfcEarthworksFill; re-linking updates in place; ValueError on wrong
   target type.

8. **`add_member_to_group`** — happy path adds; second call appends without
   duplicates; ValueError on wrong group type; ValueError on non-IfcProduct.

9. **`assign_grading_criteria` template-driven defaults** (cross-cutting test) —
   create a template with cut_slope=2.0, fill_slope=3.0; assign to a group
   with no overrides; verify the IfcPropertySet carries the template defaults
   verbatim. Catches the "did we wire the template defaults?" bug.

**Round-trip discipline:** every "creates an entity" test does
`file.write("/tmp/foo.ifc")` → `file2 = ifcopenshell.open(...)` → asserts the
structure is preserved.

**bSI reference validator:** add one CI test that runs the validator against
a full grading-scenario demo file (existing terrain from Phase 1 + feature
line + criteria template + grading group + 2 slope fills + interior fill +
criteria assignment). Skip if validator binary isn't available locally;
require it in CI. Inline `ifcopenshell.validate.validate(...)` always runs.

---

## Suggested commit order

Each commit is independently reviewable. Stop and run tests at every step.
Bonsai changes are still in the working tree from Phase 1's lifecycle —
expect the same path-scoped commit discipline (`git commit -- <paths>`) so
unrelated staged work doesn't leak into Phase 2 commits.

| # | Commit | Est. LoC | Depends on |
|---|--------|---------:|------------|
| 1 | `chore(api.grading): scaffold ifcopenshell.api.grading package` | ~30 | — |
| 2 | `feat(api.grading): _shared helpers (site resolution, OmniClass)` | ~120 | 1 |
| 3 | `feat(api.grading): add_member_to_group` | ~100 | 1 |
| 4 | `feat(api.grading): create_feature_line` | ~180 | 2 |
| 5 | `feat(api.grading): create_grading_criteria_template` | ~170 | 2 |
| 6 | `feat(api.grading): create_grading_group` | ~200 | 2,3 |
| 7 | `feat(api.grading): assign_grading_criteria` | ~150 | 5,6 |
| 8 | `feat(api.grading): add_slope_fill_to_group` | ~200 | 2,3,6 |
| 9 | `feat(api.grading): add_interior_fill_to_group` | ~150 | 2,3,6 |
| 10 | `feat(api.grading): link_alignment_to_group` | ~100 | 4,6 |
| 11 | `test(api.grading): bSI reference validator integration test` | ~180 | 4–10 |
| 12 | `docs(api.grading): module docstring + usage examples + demo` | ~120 | all |

Total estimate: ~1,700 LoC across 12 commits. Phase 1 came in at ~2,300 LoC
when tests are bundled per-commit (handoff estimated 1,030 LoC for code
only); expect Phase 2 to land in a similar range — 1,500–2,000.

---

## What "done" looks like for Phase 2

- All 12 commits land on `saikei-dev`.
- Tests pass:
  ```bash
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  PYTHONPATH=src/ifcopenshell-python \
  "/c/Program Files/Blender Foundation/Blender_5/5.0/python/bin/python.exe" \
  -m pytest src/ifcopenshell-python/test/api/test_grading.py -o "addopts="
  ```
- A standalone Python script can:
  1. Open a Phase-1-authored file with an existing-ground TIN.
  2. Call `ifcopenshell.api.grading.create_feature_line(...)` for a pad
     perimeter.
  3. Call `create_grading_criteria_template(...)` for a 3:1 fill / 2:1 cut
     criteria.
  4. Call `create_grading_group(...)` to author the group + composite shell.
  5. Call `assign_grading_criteria(...)` to bind the template to the group.
  6. Call `add_slope_fill_to_group(...)` four times (one per pad edge).
  7. Call `add_interior_fill_to_group(...)` once.
  8. Save and reopen.
  9. Run bSI validator and get a clean report.
- Demo script lives at `src/ifcopenshell-python/test/api/demo_grading.py`.

When that's all green, Phase 2 is shippable. Phase 3
(`ifcopenshell.api.earthwork`) starts on top of it.

---

## Things to flag as you go

- Any case where `IfcPropertySetTemplate` authoring needs an attribute that
  IfcOpenShell's create_entity API doesn't accept cleanly. The schema for
  templates is denser than for instance psets and has historically been
  underused in Bonsai land.
- Site-composite aggregation: by the end of Phase 2, the per-group composite
  fills are spatially placed under IfcSite but NOT aggregated under a
  site-level composite. The Phase 1 `create_proposed_surface` produces what
  could become that site-level composite, but the wiring is deferred. If
  Phase 4/5 needs the helper before Phase 3 starts, mention it — it's a
  one-function follow-on commit on top of Phase 2.
- Cross-API import boundary: Phase 2 imports
  `ifcopenshell.api.surface.add_tin_representation` and
  `ifcopenshell.api.surface.add_bounding_box_representation` from Phase 1.
  This is intentional (avoids re-authoring TIN logic) but creates a soft
  dependency. If Phase 1 changes those signatures during review, Phase 2 has
  to adapt.
- `IfcPropertySetTemplate` discovery: the spec says criteria are
  "project-scope discoverable." Nothing in IFC ties a template to a project
  beyond it being in the same file. If the demo script needs a way to filter
  templates by project (e.g., for multi-project files), say so — we'd extend
  `create_grading_criteria_template` with an optional project arg.

Otherwise: drive it.

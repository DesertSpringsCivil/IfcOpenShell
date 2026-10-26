# Saikei Civil

Civil engineering module for Bonsai (IfcOpenShell). Horizontal infrastructure design with native IFC 4.3.

**Upstream repo:** `IfcOpenShell/IfcOpenShell` branch `v0.9.0` — **PRs target v0.9.0 directly.**  
**Dev fork:** `desertspringscivil/IfcOpenShell` branch `saikei-dev-0.9.0` (agents work here)  
**Location in repo:** `src/bonsai/bonsai/` — Saikei is part of Bonsai, not a standalone extension.  
**Local dev path:** `C:\GitHub\IfcOpenShell-saikei-dev`

> `upstream/saikei` is dead — stale since 2026-03-03 and still on the February
> base. Do not branch from it or PR to it. Likewise `upstream/v0.8.0` is the
> old line; 0.9.0 forked off it on 2026-08-09.

## Git Workflow

Agents work freely on `saikei-dev-0.9.0`. When a feature is ready for Dion's review:
1. Create a review branch off `saikei-dev-0.9.0`
2. `git rebase -i upstream/v0.9.0` to squash into clean commits (≤4,000 lines)
3. PR to `IfcOpenShell/IfcOpenShell` branch `v0.9.0`
4. Keep working on `saikei-dev-0.9.0` while review happens

```bash
git fetch upstream                             # Sync latest
git rebase upstream/v0.9.0 saikei-dev-0.9.0    # Stay current
```

**Saikei's footprint in upstream Bonsai is 5 files, +250 lines, zero deletions:**
`bim/__init__.py` (+10), `bim/ui.py` (+92), `core/tool.py` (+139),
`tool/__init__.py` (+5), `api/alignment/__init__.py` (+4). Everything else is
new files. Lead with this when PRing — it is the whole review surface.

**History:** the pre-0.9.0 development trail (196 commits) is preserved at
`archive/saikei-dev-0.8.0` and tag `saikei-gsoc-0.8.0-history`.

## Architecture (NON-NEGOTIABLE)

Bonsai's 3-layer pattern. Violations must be caught immediately.

- **Core** (`core/alignment.py`): Business logic ONLY. Orchestration, validation. NO math, NO IFC creation, NO `bpy`.
- **Tool** (`tool/alignment.py`): ALL implementations. Math, IFC ops, Blender ops, coordinates.
- **UI** (`bim/module/alignment/`): Operators, panels, props, decorators, data caching.

Quick test: `math.tan()` → Tool. `ifcopenshell.api` → Tool. "Should we allow this?" → Core. Button click → UI.

## Naming Conventions

| Type | Prefix | Example |
|------|--------|---------|
| Operator | `CIVIL_OT_*` | `CIVIL_OT_add_pi` |
| Panel | `CIVIL_PT_*` | `CIVIL_PT_pi_editor` |
| UIList | `CIVIL_UL_*` | `CIVIL_UL_alignment_pis` |
| PropertyGroup | `Civil*Properties` | `CivilAlignmentProperties` |

NOT `BIM_*`, `BC_*`, or `SAIKEI_*`.

## Operator Pattern (Bonsai Standard)

```python
class CIVIL_OT_example(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "civil.example"
    bl_options = {"REGISTER", "UNDO"}

    def _execute(self, context):
        # _execute(), NOT execute() — Bonsai handles undo/redo wrapping
        result = core.alignment.do_thing(tool.Ifc, tool.Alignment, ...)
        return {"FINISHED"}
```

## IFC Operations

Use Rick Brice's merged alignment API (`ifcopenshell.api.alignment`):

```python
import ifcopenshell.api.alignment as align_api
align_api.layout_horizontal_alignment_by_pi_method(ifc_file, layout, hpoints, radii)
align_api.clear_layout_segments(ifc_file, layout)
align_api.segment_vertices(segment)  # Returns (start, end, ti, ni)
```

Access IFC file via Bonsai: `ifc_file = tool.Ifc.get()`

## Bonsai Shared Tools

```python
import bonsai.tool as tool
tool.Ifc.get() / .get_object() / .get_entity() / .link() / .unlink()
tool.Loader.create_generic_shape()    # Mesh from IFC geometry
tool.Georeference.enh2xyz() / .xyz2enh()
tool.Collector.assign()
tool.Blender.validate_shader_batch_data() / .scale_font_size()
```

## Testing

> ### 0.9.0 test environment status (2026-08-25) — migrated to Blender 5.2 / Python 3.13
>
> Blender 5.0 and 4.5 are **uninstalled**; Blender **5.2.1 LTS (Python 3.13.13)** is the
> only target. The native runtime was rebuilt locally for cp313 and lives in
> `src/ifcopenshell-python/ifcopenshell/`: **59 DLLs**, including the eight
> `ifcopenshell_geometry_mapping_*.dll` and the JSON/GLB serializers that the official
> win64 alpha artifacts omit (upstream **#9301**; fix PR **#9305** open). Geometry is
> live — a wall meshes to 8 verts / 12 faces — and all 480 `bonsai.*` modules import.
>
> **The rebuild only works on `saikei-dev-0.9.0`.** Branch `bench-baseline-20260823`
> (commit `eedfd1640`) froze the Python sources to match an *older* compiled wrapper but
> left `src/ifcwrap` untouched, so its `file.py` has no `class file_mixin` while
> `IfcParseWrapper.i:968` injects `from .file import file_mixin`. Regenerating the wrapper
> there yields a circular import via the eager `MethodList` at `entity_instance.py:67`.
> That branch cannot be rebuilt from its own sources — it is a frozen benchmark only.
>
> Rebuild recipe (from `win/`), see also the three traps:
> 1. `BuildDepsCache-x64.txt` **overwrites env vars** — edit the file, don't export.
>    Set `PYTHONHOME=C:\Python313` (3.13.7; ABI-compatible with Blender's 3.13.13).
> 2. `NoDefaultCurrentDirectoryInExePath` is set on this machine, so the `win\*.bat`
>    scripts cannot find their siblings (`vs-cfg.cmd`). Prepend the script dir to `PATH`
>    via a small `.cmd` wrapper.
> 3. Configure with `-DGLTF_SUPPORT=ON` (off by default; omits 9 DLLs), then build target
>    `ifcopenshell_wrapper` with **`--parallel 1`**. Any N>1 dies with dozens of
>    `error C1060: compiler is out of heap space` on the `geometry_mapping_ifc4`/`ifc4x1`
>    units — not RAM size, and not a 32-bit compiler (`PreferredToolArchitecture` is
>    already x64). MSBuild resumes, so retries make progress.
>
> Build inputs kept for rebuilds: `_deps/`, `_deps-vs2022-x64-installed/`,
> `_installed-vs2022-x64/`. Toolchain: VS2022 Build Tools v143 (MSVC 14.44.35207),
> SWIG 4.2.1. **No cp311 fallback remains** — the previous runtime backup and the
> `_build-vs2022-x64` tree were deleted on 2026-08-25, so a rebuild is a full
> from-scratch configure + compile (build *inputs* under `_deps*`/`_installed-*` survive,
> minus `_deps\python.3.11.8`).
>
> **Test status on 5.2 as of 2026-08-25** (measured, not aspirational):
>
> | Suite | Result |
> |---|---|
> | `test/core/` (no Blender) | **569 passed, 3 skipped** |
> | `test/tool/` (Blender 5.2 headless) | **1720 passed, 78 failed, 1 skipped** |
> | `test/bim/module/alignment/` (operators) | **120 passed** |
>
> The 78 tool failures span `test_surface` (35), `test_ifcgit` (15), `test_earthwork` (11),
> `test_voxel` (5), `test_grading` (5), `test_project` (3), `test_blender` (3),
> `test_drawing` (1). They are **order-dependent**: `test_earthwork` alone with
> surface+grading reports 51 failures but only 11 in a full `test/tool/` run, so shared
> state between suites is involved. A representative failure is
> `bpy.ops.civil.compute_earthwork_volumes` receiving empty GUIDs because
> `CivilSurfaceProperties.active_surface_guid` is not set after
> `civil.surface_create_from_points`. Operator kwargs themselves are fine on 5.2
> (verified with a minimal probe), so this is scene-PropertyGroup state, not a Blender
> API change. **These have not been bisected against Blender 5.0, which is uninstalled —
> whether they are 5.2 regressions or pre-existing on this branch is unresolved.**
>
> **Operator tests under `test/bim/` need two extra plugins** (see the
> canonical command below): `-p saikei_parse_fix -p pytest_bdd.plugin`.
> pytest-bdd + deps are installed in Blender's extensions site-packages
> but don't autoload under `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`; and the
> blosm addon (still present in 5.2's `scripts/addons`) shadows the PyPI `parse`
> package inside Blender, which `saikei_parse_fix.py` (a shim installed in both the
> outer Python and Blender extensions site-packages) evicts before pytest-bdd loads.
>
> **Signal to watch:** `.github/workflows/ci-bonsai-daily.yml` still reads
> `branches: [v0.8.0]` — no 0.9.0 nightly yet; PR-triggered CI is the
> second geometry-test signal (local is now the first).
>
> **Note for reviewers on other platforms:** linux64/pyodide artifacts were
> always complete, so geometry works there out of the box; only win64 needs
> the local build (or #9305's artifacts). Note also that upstream ships **cp311**
> artifacts — there is no official cp313 build yet, so Blender 5.2 requires the
> local rebuild regardless of #9305.

Run from `src/bonsai/`.

```bash
# Core tests — pure Python, no Blender required
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/core/test_alignment.py -o "addopts=" -v
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/core/test_surface.py -o "addopts=" -v

# Tool tests — requires Blender headless (pytest-blender)
# Canonical invocation: space-separated --blender-executable, NOT =-joined.
# pytest-blender's plugin.py:105 strips its own flags only when they appear as
# separate tokens; the =-joined form falls through to the inner pytest as a
# positional arg and breaks collection. Always use space-separated form.
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/tool/test_alignment.py \
  -o "addopts=" -p pytest-blender -v \
  --blender-executable "/c/Program Files/Blender Foundation/Blender 5.2/blender.exe"

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/tool/test_surface.py \
  -o "addopts=" -p pytest-blender -v \
  --blender-executable "/c/Program Files/Blender Foundation/Blender 5.2/blender.exe"

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/tool/test_grading.py \
  -o "addopts=" -p pytest-blender -v \
  --blender-executable "/c/Program Files/Blender Foundation/Blender 5.2/blender.exe"

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/tool/test_earthwork.py \
  -o "addopts=" -p pytest-blender -v \
  --blender-executable "/c/Program Files/Blender Foundation/Blender 5.2/blender.exe"

# Operator tests — requires Blender headless (pytest-blender) plus the
# pytest_bdd + saikei_parse_fix plugins (see the environment callout above)
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/bim/module/alignment/test_alignment_operators.py \
  -o "addopts=" -p pytest-blender -p saikei_parse_fix -p pytest_bdd.plugin -m "alignment" -v \
  --blender-executable "/c/Program Files/Blender Foundation/Blender 5.2/blender.exe"

# All alignment tests at once (tool + operator, in Blender headless)
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/tool/test_alignment.py test/bim/module/alignment/ \
  -o "addopts=" -p pytest-blender -p saikei_parse_fix -p pytest_bdd.plugin -m "alignment or not alignment" -v \
  --blender-executable "/c/Program Files/Blender Foundation/Blender 5.2/blender.exe"
```

**Phase 4 / 5 / 6 module note:** the tool tests at
`test/tool/test_surface.py`, `test/tool/test_grading.py`, and
`test/tool/test_earthwork.py` include both the pure-math tool tests
and operator-layer tests (via `NewIfc4X3` base class) since the
`test/bim/module/{surface,grading,earthwork}/` directories are
currently blocked by an env-level pytest-bdd / parse-type compat
issue in `test/bim/conftest.py`. Move the operator tests back to
`test/bim/module/{surface,grading,earthwork}/` once that's fixed
upstream.

**Prerequisites:** `pytest-blender`, `pytest-bdd` (+ `parse`, `parse-type`,
`gherkin-official`) and the `saikei_parse_fix.py` shim must be installed in Blender's
extensions site-packages (`%APPDATA%\Blender Foundation\Blender\5.2\extensions\.local\lib\python3.13\site-packages\`).
Install with `--no-deps` so Blender's bundled `pytest` and `numpy` are not shadowed.
`scipy` must be there too (`bonsai/tool/surface.py` imports `scipy.spatial`).

**Symlinks required** in that same site-packages directory:
- `bonsai` → `C:\GitHub\IfcOpenShell-saikei-dev\src\bonsai\bonsai` (dev repo)
- `ifcopenshell` → `C:\GitHub\IfcOpenShell-saikei-dev\src\ifcopenshell-python\ifcopenshell` (dev repo — holds the locally built cp313 runtime)

Create them with `cmd`'s `mklink /D`, **not** PowerShell: Developer Mode is on and
`mklink` honours it, so no elevation is needed, whereas PowerShell 5.1's
`New-Item -ItemType SymbolicLink` does not pass the unprivileged-create flag and fails
with *Administrator privilege required* — non-terminatingly, so a script can report
success while creating nothing. Verify with `Get-ChildItem -Force | ... $_.LinkType`.

## Code Style

- **Black** formatter + **ruff** linter (settings in `pyproject.toml`)
- PEP 8 naming with long descriptive variable names
- Blender 5.2+, Python 3.13

## Current State (May 2026)

**Done:**
- Horizontal alignment (PI method), segment visualization, PI picker, PI edit
  mode (G key), georef, CSV import, stationing, Add Element dialog integration.
- **Phase 4 — Bonsai surface module:** `tool.Surface` math layer (TIN
  construction, retriangulation, STRtree-accelerated Z-at-XY
  interpolation, IFC authoring via `ifcopenshell.api.surface`, Blender
  mesh linkage), `core.surface` orchestration
  (`create_surface_from_points`, `add_breakline_to_surface`,
  `set_outer_boundary`, `retriangulate_surface`), UI (operators
  `CIVIL_OT_surface_{create_from_points,add_breakline,set_boundary,
  retriangulate}`, panel `BIM_PT_tab_surface_modeler` with four
  sub-panels, `SurfaceDecorator` GPU drawing, registry with breakline
  recovery from IfcAnnotation on rehydration scoped via
  IfcRelAssignsToProduct). 175 surface tests (155 tool + 20 core) +
  bSI validator integration (single + multi-surface) green.
- **Phase 5 — Bonsai grading module:** `tool.Grading` (FeatureLine /
  GradingCriteria / GradingObject / GradingGroup dataclasses, slope-
  projection algorithm with marching-loop daylight detection on
  surface targets and closed-form for elevation/distance, four
  interior-fill strategies — none / flat / interpolate_from_boundary
  / from_surface, registry with `is_feature_line_alignment` /
  `iter_registered` public helpers, IFC authoring via
  `ifcopenshell.api.grading`, Blender curve linkage via
  `create_blender_curve` / `update_blender_curve`), `core.grading`
  orchestration (`create_feature_line`, `create_grading_criteria`,
  `create_grading_group`, `add_grading_object`, `rebuild_group`,
  `drape_feature_line`), UI (seven operators
  `CIVIL_OT_{feature_line_create,_drape,_edit_elevations,
  grading_create_criteria,_create_group,_add_object,_rebuild_group}`,
  panel `BIM_PT_tab_grading` with five sub-panels, four UILists
  including the feature-line picker, `GradingDecorator` GPU drawing
  for feature-line and daylight-line polylines, `GradingData` cache
  syncing groups + feature lines from IFC and criteria from
  registry). 178 grading tests (160 tool + 17 core + 3 bSI
  acceptance) + Phase 5 bSI validator integration test (full
  pad-grading scenario through `bpy.ops` chain) green.

- **Phase 6 — Bonsai earthwork module:** `tool.Earthwork` math layer
  (`SubTriangle` / `ClosedSolid` / `VolumeResult` dataclasses, TIN-to-TIN
  prismoidal volume math via STRtree-accelerated triangle-pair
  intersection + Shapely constrained Delaunay sub-triangulation,
  prism-soup closed-solid construction per spec §6.5 MVP, IFC
  authoring via `ifcopenshell.api.earthwork` with cut→terrain
  voiding and cut→fill linkage), `core.earthwork.compute_earthwork_volumes`
  orchestration (validates inputs, computes volumes, builds solids,
  authors all entities + Qto + SaikeiCivil_GradingShrinkSwell),
  UI (one operator `CIVIL_OT_compute_earthwork_volumes`, panel
  `BIM_PT_tab_earthwork` with Inputs and Compute sub-panels,
  `CivilEarthworkProperties` with persistent last-run report).
  Closes the audit gap: cut Qto `LooseVolume = UndisturbedVolume ×
  SwellFactor` exposed via `VolumeResult.loose_cut_m3` `@property`,
  fill Qto `LooseVolume = CompactedVolume / ShrinkFactor` via
  `bank_fill_m3`. 48 earthwork tests (40 tool + 5 core + 3 bSI
  acceptance) green; full Saikei suite at 577 passed + 2 skipped.

**Not done:** Vertical alignment, corridor generation, cross-sections,
drainage.

## Phase 5 Audit (May 2026)

After commit 15 landed, two cold-review passes were run against the
SURFACES_GRADING_EARTHWORKS reference doc (Professor Claude / Saikei-
internal). Audit fixes applied as commits 16's preamble:

- **TIN RepresentationIdentifier → 'Body'** (was 'SurfaceModel'). Phase
  3 was already correct; Phase 1 brought into line. Drops the
  redundant `SurfaceModel` subcontext.
- **OmniClass classification** added to `create_terrain` (`22-07 31 13`
  Site Preparation) and `create_proposed_surface` (`22-07 31 23`
  Fill). Both overridable. Closes Principle #8 ("never rely on entity
  type + name alone").
- **`api/earthwork/link_fill_to_cut`** — new helper authoring
  `IfcRelFillsElement`. Closes the cut→fill half of the voiding
  chain (was a Phase 6 prereq).
- **`tool.Grading.update_blender_curve`** — extracted from operator-
  layer spline mutation. 3-layer hygiene.
- **Schema + algorithm regression tests** — pinned `IfcEarthworksCutTypeEnum`
  spellings against the canonical IFC 4.3 ADD2 schema header, and
  verified non-monotonic-terrain slope projection returns the
  geometrically-correct first daylight (the original audit hypothesis
  was wrong; algorithm was already correct).
- **Georef delegation** documented in all three IFC API module
  docstrings (`api.surface`, `api.grading`, `api.earthwork`):
  caller's responsibility via `IfcMapConversion` (Bonsai's
  `tool.Georeference`).

**Remaining audit items** (deferred to Phase 6):
- Boundary-polygon round-trip on rehydration (currently falls back to
  convex hull). `SaikeiCivil_GradingSurface.BoundaryPolygonReference`
  slot exists but no read path.
- TIN-minus-TIN surface-difference algorithm (Phase 3 API takes a
  pre-computed solid; the differencing math is the Phase 6 task).
- `LooseVolume = UndisturbedVolume × SwellFactor` automatic
  computation (Phase 6 caller responsibility).

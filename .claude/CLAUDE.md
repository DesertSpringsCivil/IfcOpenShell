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

> ### 0.9.0 test environment status (2026-08-15) — geometry engine LIVE
>
> The full 0.9 native runtime is **built locally** and installed in
> `src/ifcopenshell-python/ifcopenshell/`: 59 DLLs including the eight
> `ifcopenshell_geometry_mapping_*.dll` that the official win64 alpha
> artifacts omit (upstream **#9301**; fix PR **#9305** open). Nothing is
> geometry-gated any more — the `requires_geometry_engine` skipif marks
> stay in place but all evaluate true, so the suites run with **zero
> skips**: 503 alignment (tool + operator), 121 core, 110 API.
>
> Build inputs kept for rebuilds: `_deps/`, `_deps-vs2022-x64-installed/`,
> `_installed-vs2022-x64/` (the built runtime, source of the copied DLLs).
> Toolchain: VS2022 Build Tools v143; deps from the public
> `IfcOpenShell/build-outputs@windows-x64` LFS cache. The previous official
> runtime is backed up at
> `%USERPROFILE%\ifcopenshell-runtime-backups\83fc219-official\`.
>
> **TODO when #9305 merges:** swap back to official artifacts — download the
> next `ifcopenshell-python-311-v0.9.0alpha0-<sha>-win64.zip`, replace the
> DLLs + `.pyd` + `ifcopenshell_wrapper.py` in the package dir, re-run the
> three suites. Rationale: bit-parity with what reviewers and CI actually
> run, so a local pass means the same thing everywhere. Keep the local build
> until that swap is verified green.
>
> **Operator tests under `test/bim/` need two extra plugins** (see the
> canonical command below): `-p saikei_parse_fix -p pytest_bdd.plugin`.
> pytest-bdd + deps are installed in Blender's extensions site-packages
> but don't autoload under `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`; and the
> blosm addon shadows the PyPI `parse` package inside Blender, which
> `saikei_parse_fix.py` (a shim installed in both the outer Python and
> Blender extensions site-packages) evicts before pytest-bdd loads.
>
> **Signal to watch:** `.github/workflows/ci-bonsai-daily.yml` still reads
> `branches: [v0.8.0]` — no 0.9.0 nightly yet; PR-triggered CI is the
> second geometry-test signal (local is now the first).
>
> **Note for reviewers on other platforms:** linux64/pyodide artifacts were
> always complete, so geometry works there out of the box; only win64 needs
> the local build (or #9305's artifacts).

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
  --blender-executable "/c/Program Files/Blender Foundation/Blender_5/blender.exe"

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/tool/test_surface.py \
  -o "addopts=" -p pytest-blender -v \
  --blender-executable "/c/Program Files/Blender Foundation/Blender_5/blender.exe"

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/tool/test_grading.py \
  -o "addopts=" -p pytest-blender -v \
  --blender-executable "/c/Program Files/Blender Foundation/Blender_5/blender.exe"

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/tool/test_earthwork.py \
  -o "addopts=" -p pytest-blender -v \
  --blender-executable "/c/Program Files/Blender Foundation/Blender_5/blender.exe"

# Operator tests — requires Blender headless (pytest-blender) plus the
# pytest_bdd + saikei_parse_fix plugins (see the environment callout above)
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/bim/module/alignment/test_alignment_operators.py \
  -o "addopts=" -p pytest-blender -p saikei_parse_fix -p pytest_bdd.plugin -m "alignment" -v \
  --blender-executable "/c/Program Files/Blender Foundation/Blender_5/blender.exe"

# All alignment tests at once (tool + operator, in Blender headless)
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/tool/test_alignment.py test/bim/module/alignment/ \
  -o "addopts=" -p pytest-blender -p saikei_parse_fix -p pytest_bdd.plugin -m "alignment or not alignment" -v \
  --blender-executable "/c/Program Files/Blender Foundation/Blender_5/blender.exe"
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

**Prerequisites:** `pytest-blender` and `pytest-bdd` must be installed in Blender's
extensions site-packages (`%APPDATA%\Blender Foundation\Blender\5.0\extensions\.local\lib\python3.11\site-packages\`).

**Symlinks required** in that same site-packages directory:
- `bonsai` → `C:\GitHub\IfcOpenShell-saikei-dev\src\bonsai\bonsai` (dev repo)
- `ifcopenshell` → `C:\GitHub\IfcOpenShell\src\ifcopenshell-python\ifcopenshell` (upstream, has compiled SWIG wrapper)

## Code Style

- **Black** formatter + **ruff** linter (settings in `pyproject.toml`)
- PEP 8 naming with long descriptive variable names
- Blender 5.0+, Python 3.11

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

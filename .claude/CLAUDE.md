# Saikei Civil

Civil engineering module for Bonsai (IfcOpenShell). Horizontal infrastructure design with native IFC 4.3.

**Upstream repo:** `IfcOpenShell/IfcOpenShell` branch `saikei` (Dion reviews PRs here)  
**Dev fork:** `desertspringscivil/IfcOpenShell` branch `saikei-dev` (agents work here)  
**Location in repo:** `src/bonsai/bonsai/` — Saikei is part of Bonsai, not a standalone extension.  
**Local dev path:** `C:\GitHub\IfcOpenShell-saikei-dev`

## Git Workflow

Agents work freely on `saikei-dev`. When a feature is ready for Dion's review:
1. Create a review branch off `saikei-dev`
2. `git rebase -i upstream/saikei` to squash into clean commits (≤4,000 lines)
3. PR to `IfcOpenShell/IfcOpenShell` branch `saikei`
4. Keep working on `saikei-dev` while review happens

```bash
git fetch upstream                    # Sync Dion's latest
git rebase upstream/saikei saikei-dev # Stay current
```

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

# Operator tests — requires Blender headless (pytest-blender)
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/bim/module/alignment/test_alignment_operators.py \
  -o "addopts=" -p pytest-blender -m "alignment" -v \
  --blender-executable "/c/Program Files/Blender Foundation/Blender_5/blender.exe"

# All alignment tests at once (tool + operator, in Blender headless)
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/tool/test_alignment.py test/bim/module/alignment/ \
  -o "addopts=" -p pytest-blender -m "alignment or not alignment" -v \
  --blender-executable "/c/Program Files/Blender Foundation/Blender_5/blender.exe"
```

**Phase 4 surface module note:** the tool tests at `test/tool/test_surface.py`
include both the pure-math tool tests and operator-layer tests
(via `NewIfc4X3` base class) since the `test/bim/module/surface/` directory
is currently blocked by an env-level pytest-bdd / parse-type compat issue
in `test/bim/conftest.py`. Move the operator tests back to
`test/bim/module/surface/` once that's fixed upstream.

**Prerequisites:** `pytest-blender` and `pytest-bdd` must be installed in Blender's
extensions site-packages (`%APPDATA%\Blender Foundation\Blender\5.0\extensions\.local\lib\python3.11\site-packages\`).

**Symlinks required** in that same site-packages directory:
- `bonsai` → `C:\GitHub\IfcOpenShell-saikei-dev\src\bonsai\bonsai` (dev repo)
- `ifcopenshell` → `C:\GitHub\IfcOpenShell\src\ifcopenshell-python\ifcopenshell` (upstream, has compiled SWIG wrapper)

## Code Style

- **Black** formatter + **ruff** linter (settings in `pyproject.toml`)
- PEP 8 naming with long descriptive variable names
- Blender 5.0+, Python 3.11

## Current State (April 2026)

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

**Not done:** Vertical alignment, corridor generation, cross-sections,
earthwork (volumes), drainage.

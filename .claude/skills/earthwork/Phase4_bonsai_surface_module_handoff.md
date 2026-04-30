# Phase 4 hand-off — Bonsai surface module

**Sequencing:** Phase 1 (`ifcopenshell.api.surface`) shipped 2026-04-28, Phase 2 (`ifcopenshell.api.grading`) shipped 2026-04-29, Phase 3 (`ifcopenshell.api.earthwork`) shipped 2026-04-29. Phase 4 is the **first Bonsai-side** phase and the start of the user-facing work — `tool.Surface` math, `core.surface` orchestration, and the surface UI module that wires everything to Blender.

**Branch:** `saikei-dev` on `desertspringscivil/IfcOpenShell`. Rebase up to `IfcOpenShell/IfcOpenShell saikei` when Phase 4 is review-ready.

**Workflow:** Sixteen atomic commits across three Bonsai layers, with a sub-agent review checkpoint between commits 7 and 8.

---

## Spec amendments needed

Two clarifications to queue for v3.2.5 (no rush; bundle with whatever else accumulates between now and end of Phase 4):

1. **§8.3 / §9** — Elevation banding is implemented via the `SurfaceDecorator` class with the SMOOTH_COLOR builtin GPU shader and per-vertex Z-derived colors, **NOT** via mesh `color_attributes`. Vertex-color attributes are not a Bonsai pattern; the decorator approach matches the 14 other Bonsai visualization modules. The §9 wording "mesh with vertex colors for elevation banding" is spec-author shorthand for the user-visible behavior, not a binding implementation detail.

2. **CLAUDE.md doc gap** (project-instructions, not the earthwork spec) — line 91's documented Blender test command misses the `-o "addopts="` flag that pytest.ini's intent requires. The canonical Phase 4 invocation is in this handoff (see "Test environment" below). Worth a one-line CLAUDE.md fix in a follow-on.

---

## Phase 4 scope

Build the Bonsai **surface module** — `tool.Surface` math, `core.surface` orchestration, `bim/module/surface/` UI — that gives end users a working Terrain Modeler. The module wraps Phase 1's `ifcopenshell.api.surface` for IFC authoring, adds the math layer (TIN construction, retriangulation, Z-at-XY interpolation), Blender object/mesh linkage, and the UI surface (panels, operators, GPU decorators).

**This is the first phase that produces user-visible behavior.** End of Phase 4: a user can load XYZ data, see a TIN render in Blender with toggleable triangle wireframe and elevation banding, add breaklines, set boundaries/holes/voids, and round-trip the result through IFC.

**Out of scope for Phase 4 (deferred to 4.1 or later):**

- Contour line decorator
- Slope vector decorator
- Vegetation polygons (`IfcGeographicElement[VEGETATION]`)
- Survey points (`IfcGeographicElement[SOIL_BORING_POINT]`)
- Cascade-on-edit between surfaces (Phase 5+)
- Cut/fill volume math (Phase 6)

---

## File tree (new files)

All paths relative to repo root:

```
src/bonsai/bonsai/
├── core/surface.py                                  ~250 LoC — orchestration only
├── tool/surface.py                                  ~900 LoC — math + IFC + Blender
└── bim/module/surface/
    ├── __init__.py                                   ~80 LoC — class registration, keymap
    ├── operator.py                                  ~500 LoC — CIVIL_OT_surface_*
    ├── prop.py                                      ~150 LoC — PropertyGroups, UILists
    ├── ui.py                                        ~200 LoC — CIVIL_PT_surface_panel
    ├── decorator.py                                 ~120 LoC — SurfaceDecorator (one class)
    └── data.py                                      ~100 LoC — UIList caching

src/bonsai/test/
├── core/test_surface.py                             ~150 LoC — pure-Python core tests
├── tool/test_surface.py                             ~250 LoC — Blender-headless tool tests
└── bim/module/surface/
    ├── __init__.py
    └── test_surface_operators.py                    ~200 LoC — Blender-headless operator tests
```

Plus updates to `src/bonsai/bonsai/core/tool.py` (Surface tool interface) and `src/bonsai/bonsai/__init__.py` (or wherever modules register).

Estimate: ~2,800 LoC across implementation + tests. Spec target was 2,500; expect to land 2,500–3,200 with tests bundled.

---

## Architectural anchors

The 3-layer architecture is **non-negotiable**:

- **Core** (`core/surface.py`): orchestration only. Calls tool methods; no math, no `bpy`, no `ifc_file.create_entity()`.
- **Tool** (`tool/surface.py`): all implementations. Math, IFC ops, Blender object linkage, coordinate transforms.
- **UI** (`bim/module/surface/`): operators, panels, props, decorators, data caching.

Quick test for any new code: `math.tan()` → Tool. `ifcopenshell.api.surface.create_terrain(...)` → Tool. `bpy.types.Operator` → UI. "Should we allow this?" → Core. Button click → UI.

**Cross-API imports.** `tool/surface.py` reuses Phase 1–3 helpers directly:

```python
import ifcopenshell.api.surface  # Phase 1 — IFC TIN authoring
import ifcopenshell.api.grading._shared as grading_shared  # Phase 2 helpers (cross-API import OK per Phase 3 spec amendment)
```

`tool/surface.py` does NOT re-author IFC entities. Every IFC write goes through `ifcopenshell.api.surface.*`. The math + Blender linkage is what Phase 4 adds.

**Bonsai shared tools** (no re-implementation):

- `tool.Ifc.get()` / `.get_object()` / `.get_entity()` / `.link()` / `.unlink()` for IFC entity ↔ Blender object correspondence
- `tool.Loader.create_generic_shape()` for `IfcTriangulatedIrregularNetwork` → Blender mesh via the IfcOpenShell geometry engine
- `tool.Georeference.enh2xyz()` / `.xyz2enh()` for coordinate transforms (engineering ↔ Blender near-origin)
- `tool.Collector.assign()` for spatial-hierarchy placement of new Blender objects
- `tool.Blender.validate_shader_batch_data()` for the GPU decorator pre-flight

---

## Implementation notes

**Triangulator abstraction.** Per spec §4.4, a `Triangulator` Protocol with two methods:

```python
from typing import Protocol
import numpy as np

class Triangulator(Protocol):
    def unconstrained(self, points: np.ndarray) -> np.ndarray:
        """SciPy Delaunay; returns (M, 3) triangle indices."""
    def constrained(
        self, points: np.ndarray,
        breakline_segments: list[tuple[int, int]],
        outer_boundary: "shapely.Polygon",
        holes: list["shapely.Polygon"],
        voids: list["shapely.Polygon"],
    ) -> tuple[np.ndarray, np.ndarray]:
        """Shapely 2.1+ constrained Delaunay; returns (triangles, flags)."""
```

`tool.Surface` holds a `Triangulator` instance as a class attribute, defaulting to `_ScipyShapelyTriangulator`. Tests override with deterministic stubs (predictable triangle order for hand-checked assertions). Performance target: under 2 s on 100k vertices unconstrained, under 10 s constrained.

**Registry / lazy rehydration.** Per spec §4.6, `tool.Surface._registry: dict[(int, str), CivilSurface]` keyed by `(id(ifc_file), guid)`. `Surface.get(file, guid)` returns the cached instance if present, otherwise reads the IFC entity, reconstructs the dataclass, caches, returns. `invalidate(file, guid)` drops the entry; `clear()` wipes the whole registry. Fixture teardown calls `clear()` to prevent cross-test contamination. IFC is the source of truth; the cache is a perf optimization.

**Polygon → Flags translation at persistence time.** The `outer_boundary` / `holes` / `voids` fields on `CivilSurface` are caller-supplied **authoring inputs** — Saikei-side polygons used by the `Triangulator` for clipping. At IFC persistence, `tool.Surface.author_ifc_tin_representation` walks the resulting `triangle_flags` array and translates per spec v3.2.2 §2.1 + §5: triangles whose centroid lies in a hole polygon get Flag `-1`; in a void polygon get Flag `-2`; otherwise the breakline-edge bitmask `0`–`7`. The IFC entity stores per-triangle integers, **not polygons**. On read-back, polygons can be approximately recovered by tracing the contiguous-flag sub-graphs.

**SurfaceDecorator pattern.** **One class**, mirrored verbatim from `bim/module/alignment/decorator.py` (lines 33–94 for install/uninstall/handlers boilerplate; lines 105–126 for `draw_batch_3d`). Two draw methods in Phase 4:

1. **Triangle edges.** `POLYLINE_UNIFORM_COLOR` shader, edges as line indices. Toggled by `CivilSurfaceProperties.show_triangles`. ~40 LoC.
2. **Elevation banding.** `SMOOTH_COLOR` shader, per-vertex colors precomputed from Z + a ramp, drawn as TRIS. Toggled by `CivilSurfaceProperties.show_elevation_banding`. ~50 LoC.

PropertyGroup booleans drive the install/uninstall via `update=` callbacks:

```python
def _on_show_triangles_change(self, context):
    if self.show_triangles or self.show_elevation_banding:
        SurfaceDecorator.install(context, _active_surface_meshes(context))
    else:
        SurfaceDecorator.uninstall()
```

Phase 4.1 adds `draw_contours` and `draw_slope_vectors` as additional methods on the same class — same pattern, no new file.

**Modal vs headless operator contract.** Per spec §8.5, every `[M+H]` operator implements both `invoke()` (modal entry) and `_execute()` (headless). The headless path is callable with `bpy.ops.civil.surface_X("EXEC_DEFAULT", **kwargs)`. Errors raised by tool methods are typed exceptions (`SaikeiSurfaceError`, `SaikeiTriangulationError`) caught in operator `_execute()` and converted to `self.report({"ERROR"}, str(e))` + `{"CANCELLED"}`. Headless callers receive the raw exception.

**Class registration.** `bim/module/surface/__init__.py` exposes a `classes` tuple (operators, panels, UILists, props) and a `register()` / `unregister()` pair, mirroring `bim/module/alignment/__init__.py`. The keymap registration (Tab-key for surface edit mode, etc.) lives there too.

---

## Test environment

**Canonical Phase 4 test invocation** (verified working by Cowork):

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -m pytest <test path> `
  -o "addopts=" `
  -p pytest-blender `
  -v `
  --blender-executable "C:\Program Files\Blender Foundation\Blender_5\blender.exe"
```

The `-o "addopts="` flag is **load-bearing**: it clobbers `pytest.ini`'s `addopts`, which would otherwise auto-load `pytest-bdd` and trigger an `AttributeError` from `parse-type`. Re-add `pytest-blender` explicitly with `-p pytest-blender`. Without these two flags, the harness fails at collection time on Windows.

**Harness gotcha — `--blender-executable` must be space-separated, not `=`-joined.** pytest-blender's CLI-arg parser (`plugin.py:105`) strips its own flags from the outer pytest invocation only when they appear as separate tokens. The `=`-joined form `--blender-executable=...` is a single token that fails the exact-match check, falls through to the inner pytest invocation as a positional arg, and errors with "file or directory not found" — collection finds zero tests because the test path can't even be parsed. Always use the space-separated form: `--blender-executable "C:\Program Files\..."`.

Pure-Python core tests (no Blender) use the simpler invocation that already works for the alignment module:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/core/test_surface.py -o "addopts=" -v
```

---

## Test plan

Each layer has its own test file with a specific harness:

**`test/core/test_surface.py`** — pure-Python (no Blender). Tests the `core.surface` orchestration with mock `tool.Ifc` / `tool.Surface` classes (per spec §4.7 explicit class injection). Covers: `create_surface_from_points` calls the right tool methods in the right order; `add_breakline_to_surface` triggers retriangulate + IFC update; error cases produce correct exception types.

**`test/tool/test_surface.py`** — Blender headless. Tests the `tool.Surface` implementation directly. Covers: `build_tin_from_points` with hand-calculable point clouds; `retriangulate` with breaklines (constrained Delaunay produces expected triangle topology); `z_at` interpolation against known-answer pyramids; boundary/hole/void Flags translation; registry caching; round-trip through `ifcopenshell.api.surface`.

**`test/bim/module/surface/test_surface_operators.py`** — Blender headless. Tests the operator layer end-to-end. Covers: `CIVIL_OT_surface_create_from_points` produces a CivilSurface, IFC entity, and Blender mesh; `CIVIL_OT_surface_add_breakline` headless path with kwargs; PropertyGroup state matches authored entity; SurfaceDecorator install/uninstall toggled by booleans.

**bSI validator integration** — same shape as Phase 1–3: build a complete surface scenario through Bonsai operators, write to disk, reopen, run `ifcopenshell.validate.validate()`, assert no schema warnings.

**Round-trip discipline** — every operator that authors IFC includes a write → reopen → assert-structure test, mirroring the Phase 1–3 pattern.

---

## Suggested commit order

Each commit is independently reviewable. Run tests after every step. Bonsai changes ride on top of existing `saikei-dev` work; nothing disturbs Phases 1–3.

| # | Commit | Layer | Est. LoC | Depends on |
|---|--------|------|---------:|------------|
| 1 | `chore(surface): scaffold bim/module/surface package` | UI | ~80 | — |
| 2 | `feat(tool.surface): CivilSurface + Breakline dataclasses + Triangulator protocol` | Tool | ~150 | 1 |
| 3 | `feat(tool.surface): _ScipyShapelyTriangulator default backend` | Tool | ~250 | 2 |
| 4 | `feat(tool.surface): build_tin_from_points + retriangulate + z_at` | Tool | ~300 | 2,3 |
| 5 | `feat(tool.surface): boundary/hole/void Flags translation` | Tool | ~200 | 4 |
| 6 | `feat(tool.surface): IFC authoring wrappers around api.surface` | Tool | ~250 | 4 |
| 7 | `feat(tool.surface): registry + Blender mesh linkage` | Tool | ~250 | 4,6 |
| **— sub-agent dispatch checkpoint —** | review tool layer before UI builds on it | | | |
| 8 | `feat(core.surface): create_surface_from_points orchestration` | Core | ~120 | 7 |
| 9 | `feat(core.surface): add_breakline + set_boundary orchestration` | Core | ~130 | 7,8 |
| 10 | `feat(surface.ui): CivilSurfaceProperties + UILists` | UI | ~200 | 1 |
| 11 | `feat(surface.ui): CIVIL_OT_surface_create_from_points` | UI | ~150 | 8,10 |
| 12 | `feat(surface.ui): CIVIL_OT_surface_add_breakline [M+H]` | UI | ~180 | 9,10 |
| 13 | `feat(surface.ui): CIVIL_OT_surface_set_boundary [M+H] + retriangulate + export_ifc` | UI | ~200 | 9,10 |
| 14 | `feat(surface.ui): CIVIL_PT_surface_panel + data caching` | UI | ~250 | 10–13 |
| 15 | `feat(surface.ui): SurfaceDecorator (triangles + elevation banding)` | UI | ~120 | 14 |
| 16 | `test(surface): bSI integration + docs (CLAUDE.md update + README)` | Tests/Docs | ~250 | all |

**Total estimate: ~2,930 LoC across 16 commits.** Phase 1–3 averaged ~1,800 LoC each; Phase 4 is roughly 1.6× the size, reflecting that this is where the UI/UX surface area lives.

### Sub-agent dispatch — between commits 7 and 8

After commit 7 (the tool layer is complete) and before commit 8 (the core layer starts wiring orchestration on top), one synchronous review pass with the saikei specialty agents:

- `saikei-architect` — verify 3-layer separation in tool/surface.py is clean (no `bpy`, no `ifc_file.create_entity`); registry pattern matches §4.6; Triangulator abstraction is swappable.
- `saikei-ifc` — verify IFC authoring delegates correctly to `ifcopenshell.api.surface`; OmniClass classification applied; round-trip through disk preserves entity structure.
- `saikei-tool-dev` — verify math is correct on hand-calculable cases; `z_at` interpolation accuracy; constrained Delaunay produces expected topology with breaklines; performance targets hit on a 10k-point fixture.
- `saikei-tester` — verify test coverage: per-method tests for tool.Surface, registry rehydrate, breakline edge-mask Flags translation.

Findings from the review feed into a follow-up cleanup commit (between 7 and 8) if needed, before the core/UI layers commit on top.

---

## What "done" looks like for Phase 4

- All 16 commits land on `saikei-dev`.
- Test invocation works:
  ```powershell
  $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
  cd src/bonsai
  python -m pytest test/core/test_surface.py `
    test/tool/test_surface.py `
    test/bim/module/surface/ `
    -o "addopts=" `
    -p pytest-blender `
    -v `
    --blender-executable "C:\Program Files\Blender Foundation\Blender_5\blender.exe"
  ```
- A user can:
  1. Load XYZ point data via `CIVIL_OT_surface_create_from_points`.
  2. See the resulting TIN render in Blender with triangle wireframe + elevation banding (toggled via panel checkboxes).
  3. Add a breakline via the modal `CIVIL_OT_surface_add_breakline` operator.
  4. Set an outer boundary via `CIVIL_OT_surface_set_boundary`.
  5. Export the result to IFC; reopen; verify the TIN, breakline annotations, boundary Flags, and Saikei pset all round-trip correctly.
  6. Run `ifcopenshell.validate` on the output and get a clean report.

When that's all green, Phase 4 is shippable. Phase 4.1 (contour + slope vector decorators) and Phase 5 (Bonsai grading module) start on top.

---

## Things to flag as you go

- Per `tool.Loader.create_generic_shape()` behavior with `IfcTriangulatedIrregularNetwork` — verify it produces a valid Blender mesh on the first call. If it doesn't, fall back to authoring the mesh directly from the CivilSurface points/triangles arrays (no IfcOpenShell geometry engine round-trip).
- Per the multi-site footgun (spec v3.2.4 §4.3) — Bonsai-side callers should detect `len(file.by_type("IfcSite")) > 1` and prompt the user. This is a UI concern; bake it into `CIVIL_OT_surface_create_from_points`'s invoke() rather than letting the API silently pick the first site.
- Cross-API helper imports — `tool.Surface` imports from `ifcopenshell.api.grading._shared` for `compute_bounding_box` etc. If a future refactor relocates these helpers (per the v3.2.4 tracked-but-not-fixed item), the imports are concentrated in one file.
- bSI viewer support — `IfcTriangulatedIrregularNetwork` has partial support in building-focused viewers. Saikei output is targeting IFC 4.3 civil tools (OpenRoads, DESITE, bSI reference validator). Don't optimize for Solibri rendering.

Otherwise: drive it.

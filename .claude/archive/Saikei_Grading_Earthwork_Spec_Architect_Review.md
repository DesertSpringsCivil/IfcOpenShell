# Saikei Grading/Earthwork Spec — 3-Layer Architecture Critique

**Reviewer:** saikei-architect agent
**Date:** 2026-04-24
**Subject:** [Saikei_Grading_Earthwork_Spec.md](Saikei_Grading_Earthwork_Spec.md) (v2, 1048 lines)
**Review axis:** 3-layer Bonsai architecture (core / tool / UI), with headless / agent-driven usage as the dominant concern.

---

## Overall verdict

Structurally very sound. The author clearly studied the alignment precedent — §4.3 even quotes Dion's clarification verbatim and §4.1–4.5 mirror the existing module layout. Layer boundaries are correct at the macro level; §7.1 core code is pure orchestration, §7.2 tool code holds all IFC/math. However, several concrete decisions will lock functionality into Blender-only use unless fixed before Sprint 1 starts. The headless axis is the dominant concern. Details below.

---

## 1. Layer boundaries — mostly clean, two real leaks

**Good.** §7.1 core/surface.py, core/grading.py, core/earthwork.py are textbook orchestration: validate inputs, sequence tool calls, return a guid. No math, no `ifcopenshell.api` import, no `bpy` import. The add_grading_object example (lines 679–694) is the correct pattern — core owns the *order* (compute → author IFC → add to group → rebuild → update viewport), tool owns *how*.

**Leak 1 — `tool.Grading.update_blender(group)` called from core.** Spec line 693, 708, and by implication 635, 646, 655. Calling `update_blender` from core isn't a layer violation per se (the name is in the tool namespace), but it creates an unconditional Blender dependency in every core workflow. A headless CI run of `create_surface_from_points()` will execute `tool.Surface.link_to_blender(surface)` — which in turn hits `bpy.data.objects.new(...)` — and crash. **Fix:** Every `tool.X.update_blender()` / `tool.X.link_to_blender()` call in core should be guarded, preferably by threading a `viewport_sync: bool = True` flag through the core function and only calling the Blender-touching tool method when the flag is true. Or better, have core emit an "invalidation event" that the UI layer subscribes to, so core never calls Blender-side tool methods at all. The alignment module actually has the same latent problem, but surfaces exacerbate it because automated surface generation is the obvious headless use case (drape a CSV of survey points, generate TIN, export IFC — zero GUI needed).

**Leak 2 — validation statements in §2 / §2.8 are prescriptive but unassigned.** Sentences like "Implementors should not use non-identity local placements for earthwork entities" (§2.8) and "Vertical: `IfcProjectedCRS.VerticalDatum` is required (not optional)" (§2.10) are business rules. Spec doesn't say where these are enforced. If they're enforced in `tool.Surface.author_ifc_host`, they're in the wrong layer — "should we allow non-identity placement?" is a core decision. **Fix:** call out a `core.surface.validate_before_authoring(surface, project_context)` step that raises `ValueError` before any tool method runs. Model it on the existing `if not name or not name.strip(): raise ValueError` pattern from `core/alignment.py:75`.

**Non-leak that looks like one.** §7.2 shows `tool.Ifc.get()` being called inside `tool.Surface.author_ifc_host` (spec line 768). That's the correct Bonsai pattern — `tool.Ifc` is the shared accessor; tools are *supposed* to reach for it. Not a violation.

---

## 2. Headless reachability — **largest risk in the spec, needs explicit remediation**

The spec never uses the word "headless." That's the tell. For every user-facing action listed in §8.2, I audited whether it's reachable from pure Python (`python -c "..."` with no Blender). Results:

| Action | Core function | Headless-clean? | Blocker |
|---|---|---|---|
| Create surface from points | `core.surface.create_surface_from_points` | **No** | Unconditional `tool.Surface.link_to_blender` |
| Add breakline | `core.surface.add_breakline_to_surface` | **No** | Unconditional `tool.Surface.update_blender` |
| Set boundary | `core.surface.set_surface_boundary` | **No** | Same |
| Create grading group | `core.grading.create_grading_group` | **Yes** (no blender call in §7.1) | Clean — keep it this way |
| Create criteria | `core.grading.create_grading_criteria` | **Yes** | Clean |
| Add grading object | `core.grading.add_grading_object` | **No** | `tool.Grading.update_blender(group)` |
| Edit feature line elevations | `core.grading.edit_feature_line_elevations` | **No** | Same |
| Compute earthwork volumes | `core.earthwork.compute_earthwork_volumes` | **Yes** | Clean |
| Generate cutfill map | `core.earthwork.generate_cutfill_map` | **No, intentionally** | Returns Blender mesh id — this is legitimately viewport-only |

So 5 of 9 are gratuitously Blender-coupled through the viewport sync call. Only `generate_cutfill_map` has a legitimate reason to require Blender (it builds a mesh overlay for visualization). The others are pure data/IFC operations that happen to also refresh the viewport — and the refresh is conflated with the operation.

**Concrete recommendation:** Split every core function into two concerns:
- `do_the_thing(tool, ...)` — pure orchestration, authors IFC, returns guid. Headless-clean.
- `sync_to_viewport(tool, guid)` — viewport sync. Operator calls both; headless caller calls only the first.

Either that, or add a `viewport_sync=True` parameter to each core function and gate the `update_blender` / `link_to_blender` calls on it. The parameter approach is less invasive and keeps the MCP API surface simple: an MCP tool wrapper passes `viewport_sync=False` unconditionally.

**Missing from spec entirely:** export to IFC. §8.2 lists `CIVIL_OT_surface_export_ifc` and `CIVIL_OT_earthwork_export_ifc` as operators, but no corresponding `core.surface.export_ifc` / `core.earthwork.export_ifc` function appears in §7.1. Either export is implicit in the create/author calls (in which case "export" is a misnomer — it's just "save the IFC file," which is Bonsai-global, not Saikei-specific), or the spec is missing core functions. Spec should clarify. For headless agent use, a *pure* `core.surface.export_to_ifc(tool, surface_guid, filepath) -> None` that takes an explicit filepath and doesn't touch `bpy.context` is essential. Without it, headless export is not reachable.

---

## 3. Operator pattern compliance — spec is correct, implementation discipline still required

§4.2 says "All operators inherit `tool.Ifc.Operator` and implement `_execute()`" — correct. No `execute()` anywhere. Prefixes `CIVIL_OT_*` / `CIVIL_PT_*` are right.

**Spec doesn't show a single operator body.** §8 lists 14 operator names but never gives skeleton code. Given that operators historically absorb business logic when a spec is vague about their thinness, this is a risk. **Recommendation:** Add a section "8.3 Operator reference body" showing exactly one skeleton:

```python
class CIVIL_OT_grading_create_group(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "civil.grading_create_group"
    bl_options = {"REGISTER", "UNDO"}
    name: StringProperty(...)
    target_surface_guid: StringProperty(...)
    interior_fill: EnumProperty(...)
    def _execute(self, context):
        core.grading.create_grading_group(
            tool.Grading, self.name, self.target_surface_guid, self.interior_fill,
        )
        return {"FINISHED"}
```

Then the rule "operators are this thin or they fail review" is enforceable by reference.

**Subtle mismatch in dependency injection signature.** §7.1 core signatures are `core.surface.create_surface_from_points(tool, ...)` — takes **the `tool` module** as single argument. But the existing alignment precedent (`core/alignment.py:47`) takes **individual tool classes**: `create_alignment(ifc_tool, alignment_tool, ...)`. CLAUDE.md operator example also shows `core.alignment.do_thing(tool.Ifc, tool.Alignment, ...)`. Spec deviates. Either is defensible, but mixing the two across Saikei is bad. **Recommendation:** Conform to the alignment pattern — pass `(tool.Ifc, tool.Surface, tool.Grading, tool.Earthwork, ...)` explicitly. Reasons: (a) it's the existing convention and consistency is cheap, (b) explicit tool-class injection is trivially mockable in tests, (c) it avoids importing `bonsai.tool` (the whole module) from core and makes the tool dependency set of each function legible at the signature.

---

## 4. Core dependency direction — mostly correct, one structural risk

Spec correctly keeps core imports minimal. `tool/surface.py` is where `import numpy`, `import shapely`, `import scipy.spatial` land (§4.4, §5). `tool/grading.py` and `tool/earthwork.py` similarly.

**Risk: dataclasses defined in tool, referenced from core signatures.** §6.1 shows `compute_earthwork_volumes(...) -> VolumeResult`. `VolumeResult` is defined in `tool/earthwork.py` per §5. So `core/earthwork.py` must `from bonsai.tool.earthwork import VolumeResult` at type-hint time. That imports the whole tool module, which imports numpy/shapely/scipy eagerly. Core is no longer a lightweight module. Worse, in Blender startup order, importing the tool eagerly may pull `bpy`-dependent code into core accidentally.

**Concrete fixes, in order of preference:**

1. **Move dataclasses to a dedicated `bonsai/civil_types.py` module** (or `bonsai/tool/civil_types.py` that imports only `dataclass`, `numpy`, `typing`, `shapely.geometry` — no `bpy`, no `ifcopenshell.api`). Both core and tool import from there. Zero circularity. This is how larger projects do it.
2. Or, keep dataclasses in tool modules but wrap the core-side imports in `if TYPE_CHECKING:` blocks (same pattern as `core/alignment.py:37–39`). Core function return annotations become strings (`-> "VolumeResult"`). Avoids runtime import. Works.
3. Or, have core traffic only in guids (strings) and plain dicts. `compute_earthwork_volumes` returns a `dict`, not a `VolumeResult`. Loses type safety. Don't.

I recommend option 1 for the grading sprint — it's a small refactor now and it's the seam MCP tool wrappers will reach for (see §6 of critique below).

---

## 5. Data model placement — mostly tool, one wrong

Per §5 spec places all four dataclasses (`Breakline`, `CivilSurface`, `FeatureLine`, `GradingCriteria`, `GradingObject`, `GradingGroup`, `VolumeResult`) in tool modules. That's defensible — they're tool-layer primitives.

**One is misplaced by intent.** `GradingCriteria` is described as a *persistable, reusable, user-facing* concept (§2.3 — "reusable across multiple groups... templates carry the parameter structure... instances bind to specific values"). Users will create 20 of these in a session and refer to them by name. That's a project-scoped ontology object, not a tool-internal structure. Leaving it in `tool/grading.py` means:
- Core can't talk about "the active criteria library" without pulling tool in.
- The criteria library becomes de facto ephemeral (tool-layer state), which means round-trip relies on re-parsing the `IfcPropertySetTemplate` set on each load.

That's actually fine *if* the spec commits to "criteria live in the IFC file, period" and resolution is always `tool.Grading.get_criteria(guid) -> GradingCriteria`. Which is what §7.1 implies. OK — keep `GradingCriteria` in tool, but **spec must say explicitly** that there is no cached criteria library and every reference goes through `tool.Grading.get_criteria()`. Otherwise the first PR will introduce a module-level dict.

**`CivilSurface` vs computed state.** `CivilSurface.points`, `.triangles`, `.triangle_flags` are *derived* from the IFC TIN + breaklines. The dataclass looks like it's meant to be cached. If it is cached, where? Spec doesn't say. See §7 below.

---

## 6. MCP / SDK exposure surface — spec has no plan; this needs a section

For headless agent use, the "public API" seam must be explicit. The spec currently points agents at the core layer implicitly ("Core is orchestration"), but never says "this is the MCP-exposed surface." Consequences:

- Agents writing MCP servers will either wrap random tool-layer methods (wrong granularity — a single user intent like "add a breakline" becomes 4 tool calls) or invent their own orchestration (duplicating core logic — the exact thing the architecture forbids).
- The dataclass-in-tool-module issue (§4 above) becomes acute: MCP servers traffic in JSON, so they'll need Pydantic/dataclass serializers, and those serializers have to live somewhere that doesn't pull `bpy`.

**Recommendation, to add as §12 (Headless / Agent API) in the spec:**

1. **Core is the public API seam.** Every MCP tool maps 1:1 to a `core.*` function. Never to a tool method directly.
2. **Core functions take `(tool.Ifc, tool.Surface, ...)` individual classes**, matching the alignment precedent. MCP adapter instantiates these lazily from a single `make_tool_context(ifc_filepath)` helper.
3. **Core functions accept and return JSON-serializable types** (guids as strings, numbers, lists, dicts). Where dataclasses are returned (`VolumeResult`), provide `to_dict()` methods. This is the rule that forces the civil_types module refactor from §4.
4. **No core function may call `tool.X.update_blender` or `tool.X.link_to_blender` unconditionally.** Use the `viewport_sync` flag pattern described in §2 above.
5. **MCP adapters run against `ifcopenshell.open(filepath)` directly; `tool.Ifc.get()` must be backed by a non-Blender IFC file provider in headless mode.** Check that `bonsai.tool.Ifc` already supports this — if not, that's a prerequisite task, not a Saikei task, but worth flagging.

Without this section, spec implicitly makes the UI layer (operators) the only integration point, which is exactly the anti-pattern the brief flagged.

---

## 7. State management — **spec is silent; this is the most likely future bug**

Spec does not say where `CivilSurface` instances live between operator invocations. Implicit options:

- **Module-level dict in `tool/surface.py`** (`_surface_registry: dict[str, CivilSurface] = {}`). Natural Python choice. Breaks test isolation (state leaks between tests), breaks thread safety, breaks headless parallelism (two scripts processing two different IFC files share the dict).
- **Blender Scene property (`bpy.types.Scene.civil_surfaces`)**. Natural Blender choice. Doesn't exist headlessly — scene isn't there.
- **Re-derive from IFC on every call**. `tool.Surface.get(guid)` always parses `IfcTriangulatedIrregularNetwork` and rebuilds the numpy arrays. Correct but potentially slow — a 500k-triangle site TIN reparsed on every query.
- **IFC-backed cache with invalidation.** Parse once, cache, invalidate on IFC write. Correct and fast, non-trivial to implement.

This decision has large downstream effects and is entirely absent from the spec. §7.1 line 642 `surface = tool.Surface.get(surface_guid)` implies *some* resolution mechanism exists but doesn't say what.

**Recommendation:** Commit to **option 4 (IFC-backed cache)** with the cache keyed by `(ifc_file_id, guid)` — where `ifc_file_id` is `id(ifc_file)` or a stable hash. This is the only option that is headless-safe, thread-safe (via a lock around the cache), and performant. Spec section 5 (data model) should grow a subsection "5.5 Surface lifecycle" that says so explicitly, so Sprint 1 doesn't default to a module-level dict.

**Related:** `GradingObject.daylight_line`, `.projection_triangles`, `.projection_points` are expensive computed outputs. Spec treats them as dataclass fields that live alongside the input data. Cache story applies here too — and `edit_feature_line_elevations` (§7.1 line 697) must invalidate them. Call that out in the spec.

---

## 8. Testability — reachable for ~80% of tool surface, but spec needs to say so

From the existing pattern: 135 tool tests + 39 operator tests pass for alignment, with tool tests running in Blender-headless (pytest-blender) and core tests running pure. §11 (Agent work breakdown) allocates tester LoC per sprint but doesn't specify the split between pure-Python core tests and Blender-headless tool tests.

**What's testable without Blender** (should go in `test/core/test_surface.py`, `test/core/test_grading.py`, `test/core/test_earthwork.py`):
- All §7.1 core functions, with mocked tool classes — the alignment module has 34 such tests, pattern is established.
- TIN math in tool: `build_tin_from_points`, `retriangulate`, `z_at`, outer-boundary clipping (no `bpy` needed — numpy/scipy/shapely are pure).
- Slope projection algorithm §6.2 (no `bpy` needed).
- TIN-to-TIN volume §6.4 (no `bpy`).
- Cut/fill solid construction §6.5 (no `bpy`).
- Most IFC authoring (`ifcopenshell` in-memory files work fine outside Blender, see existing tests at `src/bonsai/test/tool/test_alignment.py`).

**What needs Blender headless** (tool-layer Blender ops only):
- `link_to_blender`, `update_blender`, `build_cutfill_color_mesh`.

By my count, that's **maybe 15% of the tool surface** that needs Blender. The spec should split these into `tool/surface.py` (numpy/shapely/ifc, pure) and `tool/surface_blender.py` (bpy-touching), mirroring the implicit split that already exists in the tool layer. Tests for the first file run without `--blender-executable`; tests for the second need pytest-blender. That split is invisible in the current spec and will be ugly to introduce later.

**Missing from §11:** the spec doesn't allocate LoC for **pure-Python core tests**. Sprint 1 tester budget is 200 LoC, for "TIN build, CDT with breaklines, IFC round-trip, bSI reference validator run." None of that is the orchestration tests `test/core/test_alignment.py` contains. Add an explicit line for ~100 LoC of core orchestration tests per sprint. These are the tests that catch architecture regressions.

---

## 9. Specific spec sections flagged

| §  | Line(s) | Issue | Severity |
|----|---------|-------|----------|
| 4.5 | 307–311 | Lists `tool.Collector`, `tool.Blender` as reused shared tools. These are Blender-only tools. If headless core calls them, headless breaks. Same issue as §2 of critique. Spec should mark which are viewport-sync-only. | Med |
| 5 | 319 | "Data primitives live in tool modules... Core only sees them via tool-class methods." False by §7.1 — core signatures return dataclasses from tool. See §4 of critique. | Med |
| 7.1 | 627, 693, 708 | Every core function in surface.py and grading.py unconditionally calls a Blender tool method. See §2 of critique. | High |
| 7.1 | 627 | `create_surface_from_points(tool, ...)` takes `tool` module, inconsistent with alignment convention `(ifc_tool, alignment_tool, ...)`. See §3 of critique. | Med |
| 7.1 | missing | No `core.surface.export_to_ifc(...)` / `core.earthwork.export_to_ifc(...)`. Headless export isn't reachable. See §2. | High |
| 8.2 | 893 | No operator skeleton shown; easy for business logic to creep in at implementation time. See §3. | Low |
| 5 / 7 | throughout | Cache / state management for `CivilSurface` instances unspecified. See §7. | High |
| 11 | — | Sprint LoC allocations have no line for pure-Python core orchestration tests. See §8. | Low |
| 12 | — | No section on headless / MCP / agent API. See §6. | High |

---

## 10. Summary recommendations (in order)

1. **Add §12 "Headless operation" to the spec.** Declare core is the public API seam; core functions take individual tool classes and JSON-serializable args/returns; `viewport_sync: bool = True` flag gates every Blender-touching tool call from core.
2. **Extract dataclasses to `bonsai/civil_types.py`** (or `bonsai/tool/civil_types.py` — pure module, no bpy). Core and tool both import from there.
3. **Fix `core/*.py` signatures** to take individual tool classes (`ifc_tool`, `surface_tool`, `grading_tool`, ...) matching `core/alignment.py:47–78`.
4. **Add explicit core-layer validation hooks** (§2 leak 2). State the placement rule, the vertical-datum rule, and the name-empty rule as core business rules with concrete raise points.
5. **Add a §5.5 "Surface lifecycle / caching" subsection** committing to IFC-backed cache with invalidation; explicitly forbid module-level registry dicts.
6. **Split tool modules** into pure (`tool/surface.py`) and Blender-touching (`tool/surface_blender.py`) files. Run the pure files' tests without pytest-blender.
7. **Add `core.*.export_to_ifc(...)` functions** for each module with explicit filepath arguments.
8. **Add operator skeleton to §8.3** so thinness is enforceable by reference.

None of these block starting Sprint 1 on surfaces alone if the team accepts them as fixes-in-flight. But #1, #2, and #5 should be nailed down before Sprint 1 tool code lands — they affect the module layout and public signatures, and reworking them retroactively will cost more than setting them up correctly now.

---

**Key files referenced:**
- `c:\GitHub\IfcOpenShell-saikei-dev\.claude\skills\earthwork\Saikei_Grading_Earthwork_Spec.md`
- `c:\GitHub\IfcOpenShell-saikei-dev\src\bonsai\bonsai\core\alignment.py` (reference pattern for core layer)
- `c:\GitHub\IfcOpenShell-saikei-dev\src\bonsai\bonsai\tool\alignment.py` (reference pattern for tool layer, ~1138 lines)
- `c:\GitHub\IfcOpenShell-saikei-dev\src\bonsai\bonsai\bim\module\alignment\operator.py` (reference pattern for operator thinness)

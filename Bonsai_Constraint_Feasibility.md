# Can Bonsai's Gizmos Do Civil 3D "Fixed / Floating / Free"? — Feasibility Note

> Investigates whether Civil 3D's constraint-based alignment geometry
> (fixed/floating/free, tangent curves) can be implemented through Bonsai's
> existing gizmo + polyline mechanisms, and what IFC concept it maps to.
> Grounded in code: `bim/module/drawing/gizmos.py`, `tool/polyline.py`,
> `tool/cad.py`, and `ifcopenshell/api/alignment/`.

---

## TL;DR

**Yes — and the hardest piece already exists.** But the mental model needs one
correction: in Civil 3D, fixed/floating/free is **authoring-time design
intent**, not a stored geometry type. IFC does not store "this is a floating
curve." What IFC *does* store — and what Bonsai already computes — is the
**continuity between consecutive segments** via `IfcCurveSegment.Transition`.
That transition code *is* the persistent, standardized encoding of exactly the
tangency relationship a "floating/free" curve maintains.

So the right question isn't "can a gizmo draw a constrained curve?" It's "can
we (a) let the user express the constraint interactively, and (b) recompute
resolved geometry that satisfies it, then (c) tag the result with the right
transition code?" The answer to all three is yes, with parts already built.

---

## 1. The IFC concept you asked about: `IfcCurveSegment.Transition`

IFC 4.3 alignment geometry is a list of `IfcCurveSegment` (LINE / CIRCULARARC /
CLOTHOID). Each segment carries a **`Transition`** attribute of type
`IfcTransitionCode` describing how it joins the *next* segment:

| Transition code | Geometric meaning | Continuity | Civil 3D analog |
|---|---|---|---|
| `DISCONTINUOUS` | endpoints don't meet | — | a gap / separate fixed entity |
| `CONTINUOUS` | endpoints coincide | G0 (position) | entities touch but kink |
| `CONTSAMEGRADIENT` | + tangent directions match | **G1 (tangent)** | **floating / free curve** |
| `CONTSAMEGRADIENTSAMECURVATURE` | + curvature matches too | **G2 (curvature)** | **spiral transition (S-C-S)** |

This is the bullseye for your question. A Civil 3D **free curve fillet** (tangent
to both neighbors) is, in IFC terms, a CIRCULARARC segment joined
`CONTSAMEGRADIENT` on both sides. A **spiral transition** is the
`CONTSAMEGRADIENTSAMECURVATURE` case — the clothoid exists precisely to make
curvature continuous across the join.

**And it's already implemented.** `get_curve_segment_transition_code()`
(`ifcopenshell/api/alignment/get_curve_segment_transition_code.py`) evaluates
each segment's end vs. the next segment's start and compares three things:

```python
same_position  = np.allclose(end[:3, 3], start[:3, 3], atol=tol)   # G0
same_gradient  = np.allclose(end[:3, 0], start[:3, 0])             # G1 (tangent dir)
same_curvature = np.allclose(end[3:, :3], start[3:, :3])           # G2
# → DISCONTINUOUS / CONTINUOUS / CONTSAMEGRADIENT / CONTSAMEGRADIENTSAMECURVATURE
```

So Saikei *already* derives the tangency/curvature continuity from resolved
geometry and writes it to the IFC model. The PI method's auto-curves come out
as `CONTSAMEGRADIENT` for free.

**The key realization:** Civil 3D's fixed/floating/free is a UI abstraction over
a constraint solver. IFC throws the solver away and keeps only the *resolved
result + the continuity label*. You don't need to store the constraint graph in
IFC — you need to store resolved segments (done) with correct transition codes
(done), and keep the design intent (PIs, radii, "which curve is a free fillet")
in your own data model if you want re-editability.

---

## 2. What Bonsai's two mechanisms actually do

### A. The gizmo system (`drawing/gizmos.py`) — scalar parametric editing
- Config-driven: `DimensionGizmoConfig(attr_name, axis, min_value, …)` binds a
  draggable dimension line to **one scalar property** (width, depth, radius).
- Crucially it supports **derived-value constraints** via two callbacks:
  - `compute_value(props) -> float` — display a value computed from *other*
    props (e.g. stair `total_length = tread_run * num_treads`).
  - `apply_value(props, val)` — write back through a relationship.
  - `visibility_condition(props)` — show the gizmo only when meaningful.
- Has primitives beyond dimensions: **`GizmoArc`** (the door-swing arc),
  `GizmoLock`, `GizmoPen`, `GizmoArrow`, `ExtrusionGuidesGizmo`.
- Vertex **snapping** via KD-tree (`SnapManager`), keyboard numeric entry with
  relative mode (`+`/`-`), precision/snap modal states.

**Verdict:** the gizmo layer is a *single-element scalar editor with one-way
derived constraints*. It is **not** a bidirectional 2D constraint solver. It can
edit "the radius of this curve" with a live tangent-arc preview (`GizmoArc`),
and `compute_value`/`apply_value` can enforce "radius here drives the fillet
there" — but you write that relationship explicitly; Blender won't solve it.

### B. The polyline engine (`tool/polyline.py`) — interactive constrained drawing
This is the one Saikei's PI picker already uses, and it's closer to Civil 3D's
layout toolbar than the gizmos are. It already provides:
- **Relative-angle input**: angle `_A` is measured *relative to the previous
  segment* (`second_to_last → last → mouse`). **This is the tangency
  primitive** — "continue straight" is angle 180°, a controlled deflection is
  any other value.
- **Axis lock** (`lock_axis`, `axis_method` X/Y/Z), **plane lock**
  (`plane_method` XY/XZ/YZ) — dimensional constraints.
- **Distance + angle snapping** (`get_angle_snap_value`, increment snap).
- **Formula/units input** (Lark grammar: `=`, `+ - * /`, ft/in/mm).
- Coincidence guards (no duplicate points, no overlapping/collinear edges).

**Verdict:** the polyline engine is essentially a *constraint-aware sketch
input* — it already enforces angle/distance/axis constraints live. It draws
**straight segments only**; it has no curve-fitting or tangent-arc insertion
yet. That gap is the work.

### C. The geometry predicates (`tool/cad.py`) — the math constraints need
Already present and exactly the toolkit a tangency solver wants:
`are_edges_parallel`, `are_edges_collinear`, `intersect_edges`,
`closest_points`, `offset_edges`, `angle_3_vectors`, `is_x` (tolerance compare),
`intersect_edge_plane`. A free curve fillet = offset both neighbors inward by R,
intersect to find the arc center, trim — all expressible with these.

---

## 3. So: can a gizmo draw a curve tangent to the tangents it's drawing?

**Not the gizmo alone — but the combination can, and here's the honest split:**

- **Live, while drawing the tangents** → use the **polyline engine**, not
  gizmos. Add a "with curves" mode that, after each PI, inserts a CIRCULARARC
  fillet using `cad.offset_edges`/`intersect_edges` against the two adjacent
  tangents. The relative-angle machinery already gives you the deflection; the
  radius comes from a setting or live input. This mirrors C3D's
  *Tangent-Tangent (With Curves)* — **which Saikei's `layout_by_pi_method`
  already does at author time.** The missing part is doing it *live in the modal
  preview*, not the math.

- **Editing an existing curve** → use a **gizmo**. A `GizmoArc`-based radius
  handle with `apply_value` that re-runs the PI-method recompute so the
  neighbors stay tangent. This is the "floating/free stays tangent when you drag
  it" behavior — implemented as *recompute-on-edit*, not a persistent solver.

- **The tangency itself is never "stored as a constraint"** — it's re-derived on
  every edit and recorded in the output as the `CONTSAMEGRADIENT` transition
  code. That's the Bonsai-native pattern (the Enable→Edit→Finish loop:
  edit param → recompute representation → write IFC), and it happens to be
  exactly how IFC wants alignment stored anyway.

---

## 4. What it would take in Saikei (concrete)

| Capability | Mechanism to use | Status |
|---|---|---|
| Place PIs / tangents interactively | polyline engine (relative angle/axis lock) | ✅ in use |
| Auto-insert tangent curves at PIs | `layout_by_pi_method` + `cad` offset/intersect | ✅ at author time; ⬜ live preview |
| Resolve tangency (G1) on recompute | `cad.are_edges_parallel` + PI recompute | ✅ implicit in PI method |
| Tag joins with continuity | `get_curve_segment_transition_code` | ✅ already authored |
| Drag a curve's radius, keep tangent | `GizmoArc` + `apply_value` → recompute | ⬜ new (gizmo exists) |
| Spirals (G2 / `CONTSAMEGRADIENTSAMECURVATURE`) | CLOTHOID segment + recompute | ⬜ new |
| Free fillet between two *independent* curves | `cad` offset/intersect of two arcs | ⬜ new |
| Persist "this is a free fillet" design intent | own Pset / data model (not IFC-native) | ⬜ design decision |

**Bottom line for Dion:** Bonsai's gizmo system is a scalar editor, not a
constraint solver — so a *full* fixed/floating/free constraint engine would be
net-new and would live in Saikei's tool layer, not in Blender's gizmos. **But**
the three things that make it tractable are already here: (1) the polyline
engine enforces angle/axis constraints live, (2) `tool/cad.py` has the tangency
math, and (3) IFC's `IfcCurveSegment.Transition` — already computed by the
alignment API — is the standardized place the tangency/curvature result is
stored. The realistic path is **recompute-on-edit** (the existing PI method,
extended to a live preview and a `GizmoArc` radius handle), not a persistent
constraint graph. That stays native to both Bonsai's interaction model and IFC's
data model — and avoids reinventing Civil 3D's proprietary solver.

---

## Sources (code, this repo)
- `src/bonsai/bonsai/bim/module/drawing/gizmos.py` — gizmo framework, `DimensionGizmoConfig`, `GizmoArc`, `SnapManager`
- `src/bonsai/bonsai/tool/polyline.py` — relative-angle / axis-lock / snap draw engine
- `src/bonsai/bonsai/tool/cad.py` — `are_edges_parallel`, `intersect_edges`, `offset_edges`, `closest_points`, `angle_3_vectors`
- `src/ifcopenshell-python/ifcopenshell/api/alignment/get_curve_segment_transition_code.py` — G0/G1/G2 → transition code
- `src/ifcopenshell-python/ifcopenshell/api/alignment/add_zero_length_segment.py`, `_add_segment_to_curve.py` — transition code authoring
- `src/bonsai/bonsai/tool/alignment.py` — `layout_by_pi_method` (PI-method auto-curves)

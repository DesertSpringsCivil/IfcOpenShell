# Saikei Civil -- Keymaps Reference

User-facing reference for the keyboard and mouse bindings of every Saikei
modal operator hosted under the three T-bar civil tools. Civil 3D users
will look here first when learning Saikei's interaction model.

## How to use

1. Select a civil tool from the 3D-viewport T-bar (Surface, Grading, or
   Earthwork).
2. Click an operator button from the tool header bar (the icon row at the
   top of the viewport) or from the expanded sidebar (N-panel, Tool tab).
3. The modal activates immediately. Follow the on-screen hint in the status
   bar at the bottom of the viewport, then use the keys documented below.

All three tools share Blender's default selection keymap for the T-bar
slot itself; the per-operator keybindings documented here apply only while
a modal is running (status bar shows the active hint).

---

## Tools and their operators

### Surface tool (`bim.surface_tool`, T-bar icon: grid mesh)

**Label:** Surface
**Description:** Place breaklines, set boundaries, and raise or lower surfaces.

---

#### Pick Breakline (`civil.surface_pick_breakline`)

**Label:** Pick Breakline
**Description:** Click to place polyline vertices on the surface; Enter commits the breakline to IFC; Esc cancels.

| Key / Mouse         | Action                                              |
|---------------------|-----------------------------------------------------|
| Left click          | Add a vertex to the breakline polyline              |
| Enter / Numpad Enter| Commit -- author the breakline (requires >= 2 pts) |
| Esc / Right-click   | Cancel without authoring                            |

Each click raycasts to the Z=0 plane (Phase 7b limitation -- not the live
TIN surface). Vertices accumulate in memory; no IFC change occurs until
Enter is pressed. Cancelling at any point discards all placed vertices.
The polyline must have at least two vertices before Enter is accepted.

---

#### Pick Boundary (`civil.surface_pick_boundary`)

**Label:** Pick Boundary
**Description:** Click to place polygon vertices defining the outer boundary; Enter commits the closed polygon to IFC; Esc cancels.

| Key / Mouse         | Action                                              |
|---------------------|-----------------------------------------------------|
| Left click          | Add a vertex to the boundary polygon                |
| Enter / Numpad Enter| Commit -- set boundary (requires >= 3 pts)          |
| Esc / Right-click   | Cancel without authoring                            |

Identical interaction pattern to Pick Breakline, but the vertex list is
interpreted as a closed polygon ring. The polygon is closed automatically
on commit -- you do not need to repeat the first vertex at the end.
Minimum three vertices are required before Enter is accepted.

---

#### Raise or Lower Surface (`civil.surface_raise_lower`)

**Label:** Raise or Lower Surface
**Description:** Drag the mouse up or down to raise or lower the active surface uniformly. Numeric entry overrides the drag delta.

| Key / Mouse         | Action                                              |
|---------------------|-----------------------------------------------------|
| Mouse move (Y axis) | Preview delta Z (1 pixel = 0.01 project units)     |
| 0-9, Numpad 0-9     | Begin or extend a numeric delta value               |
| . (Period)          | Add a decimal point to the numeric value            |
| - (Minus)           | Negate the numeric value (prefix only)              |
| Enter / Numpad Enter| Commit -- translate all surface vertices by delta Z |
| Esc / Right-click   | Cancel without authoring                            |

Drag and numeric entry are mutually exclusive: as soon as you press any
digit key the drag preview is frozen and further mouse movement is ignored.
The numeric buffer is displayed only via the status bar hint (no on-canvas
readout in Phase 7b). A delta of exactly zero is treated as a no-op
(operator reports "no change" and returns without IFC mutation). Requires
an active surface selected in the Surface panel UIList before invocation.

---

### Grading tool (`bim.grading_tool`, T-bar icon: curve object)

**Label:** Grading
**Description:** Draw feature lines and apply slope criteria to design grading.

---

#### Draw Feature Line (`civil.feature_line_draw_modal`)

**Label:** Draw Feature Line
**Description:** Click to place vertices in the viewport; Enter commits the feature line to IFC; Esc cancels.

| Key / Mouse         | Action                                              |
|---------------------|-----------------------------------------------------|
| Left click          | Add a vertex to the feature line                    |
| Enter / Numpad Enter| Commit -- author the feature line (requires >= 2 pts)|
| Esc / Right-click   | Cancel without authoring                            |

Same Z=0 plane raycast pattern as the surface pick operators. The
"Closed Loop" flag (whether the feature line forms a closed pad perimeter
vs. an open ditch centerline) is set from the panel's state before
invoking; there is no modal toggle for it in Phase 7b.

---

#### Quick Elevation Edit (`civil.feature_line_grab_elevation`)

**Label:** Quick Elevation Edit
**Description:** G-key style modal for raising or lowering a feature-line vertex by a typed delta.

| Key / Mouse         | Action                                              |
|---------------------|-----------------------------------------------------|
| Mouse move (Y axis) | Preview vertex delta Z (1 pixel = 0.01 m)          |
| 0-9, Numpad 0-9     | Begin or extend a numeric delta value               |
| . (Period, Numpad.) | Add a decimal point to the numeric value            |
| - (Minus)           | Negate the numeric value                            |
| BackSpace           | Delete the last character of the numeric buffer     |
| Enter / Numpad Enter| Commit -- move the selected vertex by delta Z       |
| Esc / Right-click   | Cancel without authoring                            |

This is the single-vertex counterpart to the surface Raise/Lower operator.
Unlike Raise/Lower, this operator supports BackSpace to correct a mis-typed
digit (Raise/Lower does not). The vertex index to edit is set from the
panel before invocation; modal vertex-picking is not implemented in Phase 7b.
The active feature line must be selected in the Grading panel UIList.

---

#### Stepped Offset Feature Line (`civil.grading_stepped_offset_modal`)

**Label:** Stepped Offset Feature Line
**Description:** Create a parallel stepped-offset copy of a feature line. Each vertex is shifted perpendicular to the local direction and incremented in elevation.

| Key / Mouse         | Action                                                        |
|---------------------|---------------------------------------------------------------|
| Left click          | Confirm the active object as the source feature line          |
| Mouse move (X axis) | Preview offset distance after source is confirmed (2 px/unit)|
| 0-9, Numpad 0-9     | Begin or extend a numeric offset distance                     |
| . (Period, Numpad.) | Add a decimal point to the numeric value                      |
| - (Minus)           | Negate the offset (left vs. right side)                       |
| BackSpace           | Delete the last character of the numeric buffer               |
| Enter / Numpad Enter| Commit -- author the offset feature line                      |
| Esc / Right-click   | Cancel without authoring                                      |

Two-stage modal: the first left-click identifies the source feature line
from the currently active viewport object (the object must already be
selected before the modal starts). Once the source is confirmed, the modal
enters offset-distance input mode where drag and numeric entry both work.
The elevation step (`step_dz`) cannot be set interactively -- set it from
the operator properties panel or the headless API. Mouse drag uses the X
axis (horizontal) rather than Y, which is inconsistent with Raise/Lower
and Quick Elevation Edit (those use Y).

---

#### Fillet Feature Line Corner (`civil.grading_fillet_modal`)

**Label:** Fillet Feature Line Corner
**Description:** Replace a sharp corner in a feature line with a smooth circular arc. Pick the feature line, click a vertex, drag for radius.

| Key / Mouse         | Action                                                        |
|---------------------|---------------------------------------------------------------|
| Left click          | Confirm the active object as the source feature line          |
| Mouse move (X axis) | Preview fillet radius after source is confirmed (2 px/unit)  |
| 0-9, Numpad 0-9     | Begin or extend a numeric radius value                        |
| . (Period, Numpad.) | Add a decimal point                                           |
| BackSpace           | Delete the last character of the numeric buffer               |
| Enter / Numpad Enter| Commit -- insert the fillet arc at the specified vertex       |
| Esc / Right-click   | Cancel without authoring                                      |

Note: Minus is NOT in the fillet keymap (radius cannot be negative),
whereas it is present in Quick Elevation Edit and Stepped Offset. The
vertex index to fillet is set from the operator property panel, not via
a modal click-to-pick vertex. Radius drag is also X-axis, consistent
with Stepped Offset. The radius is clamped to a minimum of 0.0001 to
prevent a degenerate arc.

---

### Earthwork tool (`bim.earthwork_tool`, T-bar icon: volume displace modifier)

**Label:** Earthwork
**Description:** Probe cut and fill volumes interactively at any point.

---

#### Probe Volume (`civil.earthwork_volume_probe`)

**Label:** Probe Volume
**Description:** Click to place a cut/fill volume label at any point. Requires a prior Compute Volumes run to identify the surfaces.

| Key / Mouse         | Action                                              |
|---------------------|-----------------------------------------------------|
| Mouse move          | Preview probe position (no on-canvas readout)       |
| Left click          | Commit -- author a volume label annotation at cursor|
| Esc / Right-click   | Cancel without authoring                            |

This is the only earthwork modal operator. It requires that "Compute
Volumes" has been run at least once in the current session (the operator
reads the cached surface GUIDs from the Earthwork panel properties). The
volume label is authored as a point annotation in the IFC file. Unlike
the surface and grading pick operators, mouse movement here uses
PASS_THROUGH (the event is forwarded to Blender's normal viewport
navigation), so you can orbit and pan while hovering before clicking.

---

## Conventions

- Esc always cancels without IFC mutation.
- Enter (or Numpad Enter) always commits.
- Numeric typing always overrides mouse drag (where drag is supported).
  Once a digit is typed, further mouse movement does not update the
  drag-computed value until the next invocation.
- BackSpace clears the last typed character. It is available in Quick
  Elevation Edit, Stepped Offset, and Fillet -- but NOT in Raise/Lower
  Surface or the vertex-pick operators (those have no numeric buffer
  erasure in Phase 7b).
- Right-click is treated the same as Esc (cancels without authoring).
  Do not confuse this with Blender's context-menu right-click, which
  is suppressed while a Saikei modal is running.
- All click-to-place operators (Pick Breakline, Pick Boundary, Draw
  Feature Line) require the active surface or feature line to be
  pre-selected in the respective panel UIList before the modal starts.

---

## Civil 3D parity (where applicable)

| Saikei operator             | Civil 3D equivalent                              |
|-----------------------------|--------------------------------------------------|
| Pick Breakline              | Add Breaklines (Surface > Edit > Add Breaklines) |
| Pick Boundary               | Add Boundaries (Surface > Edit > Add Boundaries) |
| Raise or Lower Surface      | Raise/Lower Surface (Surface > Edit > Raise/Lower Surface) |
| Draw Feature Line           | Feature Lines > Create Feature Line              |
| Quick Elevation Edit        | Edit Elevations (Feature Line > Edit Elevations, G grip) |
| Stepped Offset Feature Line | Offset (Feature Line > Offset)                   |
| Fillet Feature Line Corner  | Fillet (Feature Line > Fillet)                   |
| Probe Volume                | Volume Dashboard point query (no direct analog)  |

---

## Future polish (Phase 7c and later)

- **Z=0 plane raycast:** All click-to-place modals (Pick Breakline, Pick
  Boundary, Draw Feature Line, Probe Volume) currently project clicks onto
  the Z=0 plane rather than the live TIN surface. A surface-snapping raycast
  is planned for a later phase.
- **On-canvas numeric readout:** The typed numeric buffer (Raise/Lower,
  Quick Elevation Edit, Stepped Offset, Fillet) is reported only via the
  status bar. A floating HUD readout is deferred.
- **In-modal vertex picking:** Stepped Offset and Fillet require the user
  to pre-select the source feature line before opening the modal; true
  in-modal click-to-pick and vertex-index selection are deferred.
- **BackSpace on Raise/Lower:** The surface Raise/Lower operator does not
  support BackSpace on the numeric buffer in Phase 7b. This inconsistency
  with the grading operators will be resolved in a polish pass.
- **Drag axis consistency:** Raise/Lower and Quick Elevation Edit drag on
  the Y axis; Stepped Offset and Fillet drag on the X axis. All four
  will be unified to Y-axis drag in Phase 7c to match Blender's G-key
  convention.
- **Probe Volume live readout:** The Earthwork probe modal shows no
  on-canvas depth preview while hovering. A HUD showing "cut: X.X m /
  fill: X.X m" under the cursor is planned.

---

## Last updated

Phase 7b -- May 2026 -- covers 8 modal operators across 3 T-bar tools:
Pick Breakline, Pick Boundary, Raise/Lower Surface (Surface tool);
Draw Feature Line, Quick Elevation Edit, Stepped Offset, Fillet (Grading
tool); Probe Volume (Earthwork tool).

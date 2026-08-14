# Vertical Alignment — Feature Spec

## Overview

Add vertical alignment (profile) support to Saikei. This is the PVI-based design (Point of Vertical Intersection) counterpart to the existing PI-based horizontal alignment. Vertical alignment defines the elevation profile along the road — grade lines connected by parabolic vertical curves.

**Prerequisite:** Horizontal alignment must exist. Vertical is nested under the same IfcAlignment.

**Design approach:** Follow the exact same patterns established for horizontal — PVI method mirrors PI method, reuse the same 3-layer architecture, same operator conventions, same tool patterns.

---

## IFC Entity Structure

```
IfcAlignment (existing)
├── IfcRelNests → IfcAlignmentHorizontal (existing)
│   └── ...
└── IfcRelNests → IfcAlignmentVertical (NEW)
    └── IfcRelNests → [IfcAlignmentSegment(s), zero-length terminator]
        each: DesignParameters → IfcAlignmentVerticalSegment

Representation:
    IfcGradientCurve (NEW — wraps the vertical curve)
        BaseCurve = IfcCompositeCurve (from horizontal)
        Segments = [IfcCurveSegment(s)]
```

### IfcAlignmentVerticalSegment Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| StartDistAlong | IfcLengthMeasure | Station (distance along horizontal) |
| HorizontalLength | IfcNonNegativeLengthMeasure | Horizontal projection of segment |
| StartHeight | IfcLengthMeasure | Elevation at segment start |
| StartGradient | IfcRatioMeasure | Grade at start (rise/run, e.g., 0.05 = 5%) |
| EndGradient | IfcRatioMeasure | Grade at end (for curves only) |
| RadiusOfCurvature | IfcPositiveLengthMeasure | Optional, for circular arcs |
| PredefinedType | Enum | CONSTANTGRADIENT or PARABOLICARC |

### Segment Types (Phase 1)

| PredefinedType | Geometric ParentCurve | Use |
|---------------|----------------------|-----|
| CONSTANTGRADIENT | IfcLine | Grade line between PVIs |
| PARABOLICARC | IfcPolynomialCurve | Vertical curve at PVI |

Circular arc vertical curves (IfcCircle) exist in the spec but are rare in US practice. Defer to Phase 2.

### Critical IFC Rules

- Zero-length terminator segment REQUIRED at end (same as horizontal)
- IfcAlignmentVertical nests under IfcAlignment via IfcRelNests
- IfcGradientCurve.BaseCurve = the horizontal IfcCompositeCurve
- Vertical is in a 2D "distance along, elevation" coordinate system — NOT XY
- Segment order maintained by IfcRelNests.RelatedObjects

---

## Rick Brice's API — What's Already Available

Rick's merged API handles the heavy IFC lifting. Use it.

```python
import ifcopenshell.api.alignment as align_api

# Create vertical layout on existing alignment
align_api.add_vertical_layout(ifc_file, alignment)

# Populate with PVI method
align_api.layout_vertical_alignment_by_pi_method(
    ifc_file, vertical_layout,
    vpoints=[(station1, elev1), (station2, elev2), ...],
    lengths=[0, curve_length1, curve_length2, ..., 0]
    # lengths[0] and lengths[-1] = 0 (endpoints have no curve)
)

# Get vertical layout from alignment
vertical_layout = align_api.get_vertical_layout(alignment)

# Get segments
segments = align_api.get_layout_segments(vertical_layout)

# Geometric representation created automatically by Rick's API
```

**Key insight:** `vpoints` are (station, elevation) tuples. `lengths` are vertical curve lengths at each PVI (0 for endpoints). This parallels horizontal where `hpoints` are (E, N) and `radii` control curves.

---

## Engineering Concepts

### PVI Method (Mirrors PI Method)
- PVIs (Points of Vertical Intersection) are where grade lines intersect
- Vertical curves (parabolas) are inserted at PVIs to provide smooth transitions
- Curve length controls how gradual the transition is

### Grade Calculation
```
grade = (elevation2 - elevation1) / (station2 - station1)
```
Grade is dimensionless (rise/run). Expressed as percentage: 5% = 0.05.

### Parabolic Vertical Curve Math
```
y(x) = A*x² + B*x + C
where:
    A = (end_gradient - start_gradient) / (2 * horizontal_length)
    B = start_gradient
    C = start_height
```

### K-Value (AASHTO Design Parameter)
```
K = L / |A|
where:
    L = curve length (ft or m)
    A = algebraic difference of grades (g2 - g1), as percentage
```
K-value determines sight distance. AASHTO Green Book provides minimum K-values by design speed.

### Curve Types
- **Crest curve:** Grades go from uphill to downhill (or less uphill). Controls stopping sight distance.
- **Sag curve:** Grades go from downhill to uphill (or less downhill). Controls headlight sight distance and comfort.

---

## Implementation Plan

### Phase 1: Tool Layer (`tool/alignment.py`)

Add these `@classmethod` methods to the existing `Alignment` class:

**Geometry calculations:**
- `calculate_pvi_geometry(pvis, start_station)` → grades, curve data (mirrors `calculate_pi_geometry`)
- `calculate_grade(station1, elev1, station2, elev2)` → float
- `calculate_vertical_curve_length_from_k(k_value, grade1, grade2)` → float
- `is_crest_curve(grade1, grade2)` → bool
- `is_sag_curve(grade1, grade2)` → bool
- `elevation_on_curve(station, pvi_station, pvi_elev, grade1, grade2, curve_length)` → float

**IFC wrappers (delegate to Rick's API):**
- `get_vertical_layout(alignment)` → wraps `align_api.get_vertical_layout()`
- `clear_vertical_segments(layout)` → wraps `align_api.clear_layout_segments()`
- `layout_vertical_by_pvi_method(ifc_file, layout, vpoints, lengths)` → wraps `align_api.layout_vertical_alignment_by_pi_method()`
- `add_vertical_layout_to_alignment(alignment)` → wraps `align_api.add_vertical_layout()`

**PVI extraction (reverse-engineer from IFC, mirrors PI extraction):**
- `extract_pvis_from_vertical_segments(segments)` → list of {station, elevation, curve_length}
- `back_calculate_pvis_from_vertical(alignment)` → full PVI data with grades

**Blender object creation:**
- Visualization approach: use `tool.Loader.create_generic_shape()` for segment visualization, same as horizontal
- PVI edit empties: `create_pvi_edit_empties()`, `collect_pvis_from_empties()`, `remove_pvi_edit_empties()` — mirror the PI edit pattern

### Phase 2: Core Layer (`core/alignment.py`)

Add pure business logic functions (NO math, NO IFC, NO bpy):

```python
def add_vertical_to_alignment(ifc, alignment_tool, alignment_id):
    """Add a vertical layout to an existing alignment."""
    ifc_file = ifc.get()
    alignment = ifc_file.by_id(alignment_id)
    if not alignment or not alignment.is_a("IfcAlignment"):
        raise ValueError("Invalid alignment")
    if alignment_tool.get_vertical_layout(alignment):
        raise ValueError("Alignment already has vertical layout")
    return alignment_tool.add_vertical_layout_to_alignment(alignment)

def enter_pvi_edit_mode(ifc, alignment_tool, alignment_id):
    """Mirror of enter_pi_edit_mode for vertical."""
    # Validate alignment exists, has vertical layout with real segments
    # Extract PVIs, create empties
    # Return empties list

def exit_pvi_edit_mode(ifc, alignment_tool, alignment_id, apply):
    """Mirror of exit_pi_edit_mode for vertical."""
    # If apply: collect empties, regenerate IFC, refresh viz
    # Always: remove empties
```

### Phase 3: UI Layer (`bim/module/alignment/`)

**New property groups in `prop.py`:**

```python
class VerticalPI(PropertyGroup):
    station: StringProperty(name="Station")  # StringProperty for precision
    elevation: StringProperty(name="Elevation")
    pvi_type: EnumProperty(items=[("ENDPOINT", "End", ""), ("GRADE", "Grade", ""), ("CURVE", "Curve", "")])
    curve_length: FloatProperty(name="Curve Length", min=0)
    grade_in: FloatProperty(name="Grade In (%)")
    grade_out: FloatProperty(name="Grade Out (%)")
```

Add to `CivilAlignmentProperties`:
```python
vertical_pvis: CollectionProperty(type=VerticalPI)
active_pvi_index: IntProperty()
vertical_display_rows: CollectionProperty(type=VerticalDisplayRow)
is_pvi_edit_mode: BoolProperty()
```

**New operators in `operator.py`:**

| Operator | bl_idname | Purpose |
|----------|-----------|---------|
| `CIVIL_OT_add_pvi` | `civil.add_pvi` | Add PVI to table |
| `CIVIL_OT_remove_pvi` | `civil.remove_pvi` | Remove selected PVI |
| `CIVIL_OT_create_vertical_by_pvi` | `civil.create_vertical_by_pvi` | Generate vertical from PVI table |
| `CIVIL_OT_recalculate_pvis` | `civil.recalculate_pvis` | Recalculate grades + regenerate |
| `CIVIL_OT_clear_pvis` | `civil.clear_pvis` | Clear all PVIs |
| `CIVIL_OT_enter_pvi_edit_mode` | `civil.enter_pvi_edit_mode` | Modal: move PVIs, ENTER/ESC |

**New panel in `ui.py`:**

`CIVIL_PT_vertical_editor` — Mirrors `CIVIL_PT_pi_editor`:
- PVI Edit Mode indicator
- Edit existing vertical button
- Header: No., Type, Station, Elevation, Grade, Curve Length
- List view of PVIs with grade/curve data
- Side buttons: Add, Remove
- Bottom: Recalculate, Clear All

**Representation template** (already partially defined):
The `ALIGNMENT_GRADIENT` template in `tool/alignment.py` creates both horizontal and vertical layouts. Ensure it works with adding vertical to an existing horizontal-only alignment.

---

## Acceptance Criteria

### Must Have
- [ ] Add PVIs to table with station, elevation, curve length
- [ ] Calculate grades between PVIs automatically
- [ ] Generate IfcAlignmentVertical with CONSTANTGRADIENT + PARABOLICARC segments
- [ ] Visualize vertical segments in Blender viewport (using geometry engine)
- [ ] PVI edit mode: move PVIs with G key, ENTER to apply, ESC to cancel
- [ ] Zero-length terminator at end of vertical layout
- [ ] Vertical nested under existing alignment (not standalone)
- [ ] IfcGradientCurve geometric representation (via Rick's API)

### Should Have
- [ ] Grade display in percent (e.g., "+3.50%")
- [ ] K-value display for each vertical curve
- [ ] Crest/sag curve identification
- [ ] Sync PVI table from existing IFC vertical alignment (undo/redo support)

### Could Have (Defer)
- [ ] AASHTO minimum K-value validation by design speed
- [ ] Sight distance calculation
- [ ] Circular arc vertical curves
- [ ] Profile view (2D station vs elevation plot)
- [ ] Terrain mesh sampling for existing ground elevation

---

## Tests to Write

### Core Tests (pure Python, no Blender)
```python
def test_add_vertical_rejects_nonexistent_alignment()
def test_add_vertical_rejects_duplicate_vertical()
def test_enter_pvi_edit_mode_validates_alignment()
def test_exit_pvi_edit_mode_apply_regenerates()
def test_exit_pvi_edit_mode_cancel_removes_empties()
```

### Tool Math Tests (pure Python)
```python
def test_grade_calculation_uphill()
def test_grade_calculation_downhill()
def test_grade_calculation_level()
def test_is_crest_curve()
def test_is_sag_curve()
def test_k_value_to_curve_length()
def test_elevation_on_parabolic_curve()
def test_pvi_geometry_straight_grade()
def test_pvi_geometry_with_curves()
```

### Tool IFC Tests (need IFC file in memory)
```python
def test_add_vertical_layout_creates_entity()
def test_layout_vertical_creates_segments()
def test_vertical_has_zero_length_terminator()
def test_extract_pvis_from_vertical_roundtrip()
```

---

## File Changes Summary

| File | Changes |
|------|---------|
| `tool/alignment.py` | Add ~15 new @classmethod methods for vertical geometry, IFC wrappers, PVI extraction, Blender objects |
| `core/alignment.py` | Add ~3 new functions: add_vertical, enter/exit_pvi_edit_mode |
| `bim/module/alignment/prop.py` | Add VerticalPI, VerticalDisplayRow property groups, extend CivilAlignmentProperties |
| `bim/module/alignment/operator.py` | Add ~6 new operators + helper functions |
| `bim/module/alignment/ui.py` | Add CIVIL_PT_vertical_editor panel |
| `bim/module/alignment/decorator.py` | Add PVIEditDecorator (or extend PIEditDecorator) |
| `bim/module/alignment/__init__.py` | Register new classes |
| `test/core/test_alignment.py` | Add ~5 core tests |
| `test/tool/test_alignment.py` | Add ~10 tool tests |

**Estimated total:** ~1,500-2,500 new lines. Well within the ≤4,000 line PR limit for Dion.

---

## Reference: How Horizontal Does It (Follow This Pattern)

The vertical implementation should mirror horizontal as closely as possible. When in doubt, look at how the existing horizontal code does it:

- `calculate_pi_geometry()` → model `calculate_pvi_geometry()` after this
- `back_calculate_pis_from_alignment()` → model `back_calculate_pvis_from_vertical()`
- `create_pi_edit_empties()` → model PVI edit empties
- `CIVIL_OT_add_pi` → model `CIVIL_OT_add_pvi`
- `CIVIL_PT_pi_editor` → model `CIVIL_PT_vertical_editor`
- `PIEditDecorator` → model PVI decorator

The horizontal implementation is the spec. Read it before writing vertical code.

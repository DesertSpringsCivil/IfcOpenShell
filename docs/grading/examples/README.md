# Tier 1 Grading Demo — Example Files

This directory contains the fixture and reference output for the Saikei Civil
Tier 1 grading workflow demo (`src/bonsai/scripts/tier1_demo.py`).

## Files

| File | Description |
|------|-------------|
| `tier1_terrain.csv` | Sample terrain point cloud (35 points, 5x7 grid, gentle slope in X). Format: `x,y,z` per row, no header. |
| `tier1_demo.ifc` | Reference IFC output committed in version control. Regenerate when any `ifcopenshell.api.{surface,grading,earthwork}` helper changes its output schema. |

## Running the demo

The demo is headless — no Blender required. Any Python with `ifcopenshell`,
`numpy`, `scipy`, and `shapely` installed can run it.

```bash
# From the repo root — generate or refresh the reference IFC:
python src/bonsai/scripts/tier1_demo.py docs/grading/examples/tier1_demo.ifc

# Write to a custom path:
python src/bonsai/scripts/tier1_demo.py /tmp/my_grading_demo.ifc
```

The script prints a one-line earthwork summary on completion:

```
Cut: 12.569 m³, Fill: 44.439 m³, Net: -31.870 m³
```

## Refreshing `tier1_demo.ifc`

Whenever an `ifcopenshell.api.*` function changes its IFC output (new entity
types, altered pset structure, etc.), regenerate the reference file and commit
it in the same PR as the API change:

```bash
python src/bonsai/scripts/tier1_demo.py docs/grading/examples/tier1_demo.ifc
git add docs/grading/examples/tier1_demo.ifc
```

The integration test `test_generated_matches_reference_structurally` will fail
until the reference is refreshed — this is intentional, acting as a CI signal
that the reference is stale.

## Integration tests

```bash
# Run from src/bonsai/:
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/integration/test_tier1_demo.py \
  -o "addopts=" -v
```

These tests run in plain Python — no `--blender-executable` flag needed.

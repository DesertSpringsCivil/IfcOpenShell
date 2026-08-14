"""Integration tests for the Tier 1 grading demo script.

Runs ``scripts/tier1_demo.main()`` as a module, validates the generated IFC,
and checks structural equivalence against the committed reference fixture.
No ``bpy`` or Blender required — these run in plain Python.
"""

from __future__ import annotations

import ast
import importlib.util
import pathlib
import sys
from types import ModuleType

import ifcopenshell
import ifcopenshell.validate
import pytest

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
_SCRIPTS_DIR = _REPO_ROOT / "src" / "bonsai" / "scripts"
_REFERENCE_IFC = _REPO_ROOT / "docs" / "grading" / "examples" / "tier1_demo.ifc"
_DEMO_SCRIPT = _SCRIPTS_DIR / "tier1_demo.py"


def _load_demo_module() -> ModuleType:
    """Import ``tier1_demo.py`` as a module without triggering __main__ block."""
    spec = importlib.util.spec_from_file_location("tier1_demo", str(_DEMO_SCRIPT))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Entity-count helpers
# ---------------------------------------------------------------------------

_TRACKED_ENTITY_TYPES = (
    "IfcGeographicElement",
    "IfcAlignment",
    "IfcGroup",
    "IfcEarthworksCut",
    "IfcEarthworksFill",
    "IfcAnnotation",
)


def _entity_counts(ifc: ifcopenshell.file) -> dict[str, int]:
    return {et: len(ifc.by_type(et)) for et in _TRACKED_ENTITY_TYPES}


def _validate_ifc(path: pathlib.Path) -> list[dict]:
    """Open a written IFC file, run validate, return any ERROR-level entries."""
    ifc = ifcopenshell.open(str(path))
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(ifc, logger)
    return [s for s in logger.statements if s.get("level") == "ERROR"]


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestTier1Demo:
    """Tests for the Tier 1 grading end-to-end demo script."""

    def test_demo_script_runs_without_error(self, tmp_path: pathlib.Path) -> None:
        """Invoke ``tier1_demo.main()`` to a temp path; assert no exceptions."""
        demo = _load_demo_module()
        output = tmp_path / "tier1_generated.ifc"
        demo.main(output_path=output)
        assert output.exists(), f"Script did not write IFC to {output}"
        assert output.stat().st_size > 1000, "Generated IFC is suspiciously small"

    def test_generated_ifc_validates(self, tmp_path: pathlib.Path) -> None:
        """Run ifcopenshell.validate() on the freshly generated IFC; assert clean."""
        demo = _load_demo_module()
        output = tmp_path / "tier1_validate.ifc"
        demo.main(output_path=output)
        errors = _validate_ifc(output)
        assert errors == [], f"IFC validation errors in generated file: {errors}"

    def test_reference_ifc_validates(self) -> None:
        """Run ifcopenshell.validate() on the committed reference fixture; assert clean."""
        assert _REFERENCE_IFC.exists(), (
            f"Reference IFC not found at {_REFERENCE_IFC}. "
            "Run: python src/bonsai/scripts/tier1_demo.py docs/grading/examples/tier1_demo.ifc"
        )
        errors = _validate_ifc(_REFERENCE_IFC)
        assert errors == [], f"IFC validation errors in reference file: {errors}"

    def test_generated_matches_reference_structurally(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Entity counts must match between a fresh run and the committed reference.

        GUIDs and timestamps differ on each run, so byte equality is not the
        right comparison (per §10.3). We assert the same script + same inputs
        produce the same entity counts — any drift signals an API change that
        warrants a reference-IFC refresh.
        """
        assert _REFERENCE_IFC.exists(), (
            f"Reference IFC not found at {_REFERENCE_IFC}. "
            "Regenerate with: python src/bonsai/scripts/tier1_demo.py docs/grading/examples/tier1_demo.ifc"
        )

        demo = _load_demo_module()
        output = tmp_path / "tier1_structural.ifc"
        demo.main(output_path=output)

        generated_ifc = ifcopenshell.open(str(output))
        reference_ifc = ifcopenshell.open(str(_REFERENCE_IFC))

        generated_counts = _entity_counts(generated_ifc)
        reference_counts = _entity_counts(reference_ifc)

        mismatches = {
            et: (generated_counts[et], reference_counts[et])
            for et in _TRACKED_ENTITY_TYPES
            if generated_counts[et] != reference_counts[et]
        }
        assert mismatches == {}, (
            f"Entity count mismatch (generated vs reference): {mismatches}\n"
            "If an API change intentionally altered the output, regenerate the reference IFC:\n"
            "  python src/bonsai/scripts/tier1_demo.py docs/grading/examples/tier1_demo.ifc"
        )

    def test_demo_does_not_import_bpy_or_bonsai(self) -> None:
        """Verify the demo script's source contains no bpy or bonsai imports.

        Parsed via ``ast`` — a literal source scan, not a runtime check — so it
        catches imports that would only fire in certain branches.
        """
        source = _DEMO_SCRIPT.read_text(encoding="utf-8")
        tree = ast.parse(source)

        forbidden_prefixes = ("bpy", "bonsai")

        violations: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if any(alias.name == p or alias.name.startswith(p + ".") for p in forbidden_prefixes):
                        violations.append(f"line {node.lineno}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if any(mod == p or mod.startswith(p + ".") for p in forbidden_prefixes):
                    violations.append(f"line {node.lineno}: from {mod} import ...")

        assert violations == [], (
            f"Demo script imports bpy/bonsai (forbidden for headless scripts):\n"
            + "\n".join(violations)
        )

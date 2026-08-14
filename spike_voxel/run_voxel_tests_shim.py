"""Run the REAL test/tool/test_voxel.py against the REAL bonsai.tool.voxel code,
shimming only the heavy bonsai.tool package container (which this session's
Blender env can't import: missing scipy + addon circular-import needs a full
registered-addon load). numpy + stdlib only — no bpy, no Blender process.

  PY="/c/Program Files/Blender Foundation/Blender5/5.0/python/bin/python.exe"
  export PYTHONPATH="<extensions .local site-packages>"   # for pytest
  cd src/bonsai && "$PY" ../../spike_voxel/run_voxel_tests_shim.py
"""
import importlib.util
import pathlib
import sys
import types

REPO = pathlib.Path(r"C:\GitHub\IfcOpenShell-saikei-dev\src\bonsai")
VOXEL_PY = REPO / "bonsai" / "tool" / "voxel.py"

# Load the real tool/voxel.py as bonsai.tool.voxel without running the heavy
# bonsai/ and bonsai/tool/__init__.py (which pull bpy/scipy/circular imports).
bonsai = types.ModuleType("bonsai"); bonsai.__path__ = []
bonsai_tool = types.ModuleType("bonsai.tool"); bonsai_tool.__path__ = []
sys.modules["bonsai"] = bonsai
sys.modules["bonsai.tool"] = bonsai_tool

spec = importlib.util.spec_from_file_location("bonsai.tool.voxel", VOXEL_PY)
voxel_mod = importlib.util.module_from_spec(spec)
sys.modules["bonsai.tool.voxel"] = voxel_mod
spec.loader.exec_module(voxel_mod)

# Wire the package surface the test expects: `import bonsai.tool as tool` →
# tool.Voxel, and `from bonsai.tool.voxel import Voxel`.
bonsai_tool.voxel = voxel_mod
bonsai_tool.Voxel = voxel_mod.Voxel
bonsai.tool = bonsai_tool

import pytest  # noqa: E402

sys.exit(pytest.main([
    "test/tool/test_voxel.py",
    "-o", "addopts=",
    "-p", "no:cacheprovider",
    "-v",
]))

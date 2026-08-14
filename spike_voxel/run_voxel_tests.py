"""Run the voxel tool tests inside Blender's Python (bpy available, bonsai
symlinked). Invoke:

  blender --background --python spike_voxel/run_voxel_tests.py

Runs from CWD = src/bonsai so the `test` package and relative paths resolve.
Avoids needing pytest-blender (not installed); pytest itself ships in Blender.
"""
import os
import sys

import pytest

# Ensure src/bonsai (CWD when launched per instructions) is importable.
sys.path.insert(0, os.getcwd())

code = pytest.main(
    [
        "test/tool/test_voxel.py",
        "-o", "addopts=",
        "-p", "no:cacheprovider",
        "-v",
    ]
)
# Blender swallows plain return codes; print a sentinel we can grep.
print(f"\n__PYTEST_EXIT_CODE__={int(code)}")
sys.exit(int(code))

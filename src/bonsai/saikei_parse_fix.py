# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2026 Michael Yoder <myoder@desertspringscivil.com>
#
# This file is part of Bonsai.
#
# Bonsai is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Bonsai is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Bonsai.  If not, see <http://www.gnu.org/licenses/>.

"""pytest plugin: work around a local dev-environment ``parse`` name collision
that blocks pytest-bdd (and therefore the operator test suite in
``test/bim/module/``) from collecting.

Some Blender installs carry a third-party addon (observed with "blosm", the
OSM import addon) that ships its own top-level package literally named
``parse`` — e.g. ``...\\Blender\\5.0\\scripts\\addons\\blosm\\parse\\__init__.py``.
Blender adds its addons directory to ``sys.path`` ahead of the extensions
site-packages directory, so a bare ``import parse`` resolves to the addon's
package instead of the real PyPI ``parse`` library. That shadow package has
no ``Parser`` class, so ``parse_type.cfparse`` (a pytest-bdd dependency) fails
at import time with::

    AttributeError: module 'parse' has no attribute 'Parser'

which pytest reports as a plugin validation error for the ``pytest_bdd_*``
hooks declared in ``test/bim/conftest.py`` — the operator test suite (which
uses ``bpy.ops`` "given/when/then" style helpers via pytest-bdd) cannot even
be collected until this is resolved.

This is purely an environment quirk — nothing in Saikei or upstream Bonsai
ships a conflicting ``parse`` module — so the fix lives here as an opt-in
pytest plugin rather than a permanent workaround baked into ``test/bim/conftest.py``.
Load it *before* ``pytest_bdd.plugin`` so the real ``parse`` module is already
cached in ``sys.modules`` by the time pytest-bdd (transitively) imports it:

    pytest ... -p saikei_parse_fix -p pytest_bdd.plugin

The fix re-imports ``parse`` with any ``.../addons/...`` directories
temporarily excluded from ``sys.path``, so it finds the genuine package
installed in site-packages, then caches that module under the ``parse`` key
in ``sys.modules`` so every subsequent ``import parse`` (by parse_type,
pytest-bdd, or anything else) reuses the correct one.
"""

import sys
import importlib
import importlib.util


def _is_addon_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    return "/addons/" in normalized or normalized.endswith("/addons")


def _install_real_parse_module() -> None:
    existing = sys.modules.get("parse")
    if existing is not None and hasattr(existing, "Parser"):
        # Already the genuine library (or something else providing Parser) —
        # nothing to do.
        return

    if existing is not None:
        del sys.modules["parse"]

    original_path = list(sys.path)
    try:
        sys.path = [p for p in original_path if not _is_addon_path(p)]
        spec = importlib.util.find_spec("parse")
        if spec is None or spec.loader is None:
            return
        module = importlib.util.module_from_spec(spec)
        sys.modules["parse"] = module
        spec.loader.exec_module(module)
    finally:
        sys.path = original_path


_install_real_parse_module()

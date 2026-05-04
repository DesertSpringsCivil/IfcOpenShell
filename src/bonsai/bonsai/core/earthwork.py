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

"""Saikei earthwork core — orchestration only, NO bpy / numpy / shapely.

Phase 6 of the Saikei grading/earthwork sprint. This module owns the
business-rule layer for earthwork-volume computation and cut/fill
solid authoring: validates inputs, sequences calls into
:mod:`bonsai.tool.earthwork` (and :mod:`bonsai.tool.surface` for
existing/proposed surface lookups), and translates user intent into
the right tool method chain.

Per spec §4.7 (alignment-precedent), every function takes the tool
classes as explicit type-injected parameters (``ifc_tool``,
``surface_tool``, ``earthwork_tool``) so tests can substitute
test doubles without monkeypatching.

What lives here:

- Validation: file loaded, both surfaces resolved, shrink/swell factor
  ranges sane, surface kinds appropriate (existing → terrain,
  proposed → fill).
- Sequencing: volume math → cut/fill solid construction → IFC
  authoring → quantity-set authoring → shrink/swell pset.
- Decisions: should we author a cut entity for zero-cut scenarios?
  How does the swell factor multiply through to ``LooseVolume``?

What does NOT live here:

- Math (TIN-to-TIN prismoidal, region extraction, solid construction)
  — :mod:`bonsai.tool.earthwork`.
- IFC entity creation — :mod:`bonsai.tool.earthwork` delegating to
  :mod:`ifcopenshell.api.earthwork` (Phase 3).
- Blender object/mesh manipulation (``bpy``) —
  :mod:`bonsai.tool.earthwork`.

Subsequent commits add ``compute_earthwork_volumes`` orchestration
once the math layer in :mod:`bonsai.tool.earthwork` is in place. This
scaffold lands the package shell + module docstring; the orchestration
functions land alongside the tool methods they sequence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .. import tool  # noqa: F401

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

"""Saikei grading module — Bonsai-side Civil 3D-style grading.

Phase 5 of the Saikei grading/earthwork sprint. Wraps Phase 2's
``ifcopenshell.api.grading`` for IFC authoring, adds the math layer
(feature-line slope projection, daylight-line computation, group
surface composition), Blender object linkage, and the UI surface
(panels, operators, decorators) that gives users a working grading
workflow.

Builds on Phase 4's surface module — feature-line elevations are
draped from `tool.Surface.z_at`, group composite surfaces are
authored as `proposed_group` `CivilSurface` instances, and breaklines
along feature lines reuse the host-link scoping from `tool.Surface.author_ifc_breakline`.

Subsequent commits add the dataclass / operator / panel / decorator
classes and register them here. This scaffold establishes the package
shell and the parent-module wiring at ``bim/__init__.py``.
"""

import bpy

# Operator / panel / UIList / PropertyGroup classes are added in later
# commits as the grading module fills out. The empty tuple lets the
# package register cleanly today; the bonsai.bim.__init__ batch
# registration loop simply has nothing to register for grading yet.
classes: tuple[type, ...] = ()


def register() -> None:
    """Module-level registration hook.

    Called by ``bonsai.bim`` after the parent has registered all module
    classes. PointerProperty registration on ``bpy.types.Scene``, the
    ``civil`` keymap (per spec §8.4), and any persistent handlers land
    here in subsequent commits.
    """
    # Future: bpy.types.Scene.CivilGradingProperties = bpy.props.PointerProperty(
    #     type=prop.CivilGradingProperties
    # )
    pass


def unregister() -> None:
    """Module-level teardown hook (mirror of :func:`register`)."""
    # Future: del bpy.types.Scene.CivilGradingProperties
    pass

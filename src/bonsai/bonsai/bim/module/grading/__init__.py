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

from . import operator, prop


classes: tuple[type, ...] = (
    prop.CivilGradingGroupItem,
    prop.CivilGradingCriteriaItem,
    prop.CivilGradingMemberItem,
    prop.CIVIL_UL_grading_groups,
    prop.CIVIL_UL_grading_criteria,
    prop.CIVIL_UL_grading_members,
    prop.CivilGradingProperties,
    operator.CIVIL_OT_feature_line_create,
    operator.CIVIL_OT_feature_line_drape,
    operator.CIVIL_OT_feature_line_edit_elevations,
    operator.CIVIL_OT_grading_create_criteria,
    operator.CIVIL_OT_grading_create_group,
    operator.CIVIL_OT_grading_add_object,
    operator.CIVIL_OT_grading_rebuild_group,
)


def register() -> None:
    """Module-level registration hook.

    Called by ``bonsai.bim`` after the parent has registered all module
    classes. Attaches :class:`CivilGradingProperties` to ``bpy.types.Scene``
    as a ``PointerProperty`` so the UI panel can read / write grading
    state via ``context.scene.CivilGradingProperties``.
    """
    bpy.types.Scene.CivilGradingProperties = bpy.props.PointerProperty(
        type=prop.CivilGradingProperties
    )


def unregister() -> None:
    """Module-level teardown hook (mirror of :func:`register`)."""
    del bpy.types.Scene.CivilGradingProperties

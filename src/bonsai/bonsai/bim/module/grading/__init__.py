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
along feature lines reuse the host-link scoping from
`tool.Surface.author_ifc_breakline`.

Module contents:

- :mod:`prop` — :class:`CivilGradingProperties` scene PointerProperty,
  three UILists (groups / criteria / members), three collection-element
  types, and the decorator-toggle update callback.
- :mod:`operator` — seven operators
  (``CIVIL_OT_feature_line_create`` / ``_drape`` / ``_edit_elevations``,
  ``CIVIL_OT_grading_create_criteria`` / ``_create_group`` /
  ``_add_object`` / ``_rebuild_group``).
- :mod:`ui` — five sub-panels under :class:`BIM_PT_tab_grading`
  (CIVIL > Grading).
- :mod:`decorator` — :class:`GradingDecorator` GPU draw handler
  (feature-line polylines + daylight-line tie-outs).
- :mod:`data` — :class:`GradingData` UI cache with IFC-tree sync for
  groups and registry-derived sync for criteria.

Wires up a ``@persistent load_post`` handler that uninstalls the
:class:`GradingDecorator` on file open and resets the decorator-toggle
BoolProperties — the decorator's draw handler captures context in a
closure, so without an uninstall on load the handler runs against the
old file's context and races the new file's initialization.
"""

import bpy
from bpy.app.handlers import persistent

from . import operator, prop, ui, workspace


classes: tuple[type, ...] = (
    prop.CivilGradingGroupItem,
    prop.CivilGradingCriteriaItem,
    prop.CivilGradingMemberItem,
    prop.CivilGradingFeatureLineItem,
    prop.CIVIL_UL_grading_groups,
    prop.CIVIL_UL_grading_criteria,
    prop.CIVIL_UL_grading_members,
    prop.CIVIL_UL_grading_feature_lines,
    prop.CivilGradingProperties,
    operator.CIVIL_OT_feature_line_create,
    operator.CIVIL_OT_feature_line_drape,
    operator.CIVIL_OT_feature_line_from_daylight,
    operator.CIVIL_OT_feature_line_edit_elevations,
    operator.CIVIL_OT_feature_line_delete,
    operator.CIVIL_OT_grading_create_criteria,
    operator.CIVIL_OT_grading_create_group,
    operator.CIVIL_OT_grading_add_object,
    operator.CIVIL_OT_grading_rebuild_group,
    operator.CIVIL_OT_grading_remove_object,
    operator.CIVIL_OT_grading_delete_criteria,
    operator.CIVIL_OT_feature_line_draw_modal,
    operator.CIVIL_OT_feature_line_grab_elevation,
    operator.CIVIL_OT_grading_stepped_offset_modal,
    operator.CIVIL_OT_grading_fillet_modal,
    ui.CIVIL_PT_grading_feature_lines,
    ui.CIVIL_PT_grading_criteria,
    ui.CIVIL_PT_grading_groups,
    ui.CIVIL_PT_grading_active_group,
    ui.CIVIL_PT_grading_display,
)


@persistent
def _on_load_post(_dummy: bpy.types.Scene) -> None:
    """File-load cleanup: uninstall the GPU draw handler captured against
    the previous file's context, and reset the decorator-toggle
    BoolProperties so the post-load state is deterministic regardless
    of whether ``load_post`` fires before or after property
    deserialization.

    Mirrors the surface module's ``_on_load_post`` (see
    :mod:`bonsai.bim.module.surface.__init__`). Without the uninstall
    half, the decorator's ``draw_3d`` callback continues to run with a
    closure over the old context, racing the new file's initialization.
    Lazy-imports the decorator module so this hook doesn't trigger a
    module-level import chain at addon-register time.
    """
    from . import decorator as grading_decorator
    from . import data as grading_data

    grading_decorator.GradingDecorator.uninstall()

    scene = bpy.context.scene if bpy.context else None
    props = getattr(scene, "CivilGradingProperties", None) if scene else None
    if props is not None:
        props.show_feature_lines = False
        props.show_daylight_lines = False

    # Re-sync the UILists from the freshly-loaded IFC. This runs outside panel
    # draw() (where writing scene properties is forbidden), so opening a file
    # that already contains grading entities shows them in the lists.
    try:
        grading_data.GradingData.sync_uilists()
    except Exception:
        pass


def register() -> None:
    """Module-level registration hook.

    Called by ``bonsai.bim`` after the parent has registered all module
    classes. Attaches :class:`CivilGradingProperties` to ``bpy.types.Scene``
    as a ``PointerProperty`` so the UI panel can read / write grading
    state via ``context.scene.CivilGradingProperties``. Also registers the
    file-load cleanup handler.
    """
    bpy.types.Scene.CivilGradingProperties = bpy.props.PointerProperty(
        type=prop.CivilGradingProperties
    )
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)
    if not bpy.app.background:
        bpy.utils.register_tool(
            workspace.GradingCivilTool, separator=True, group=False
        )


def unregister() -> None:
    """Module-level teardown hook (mirror of :func:`register`)."""
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    if not bpy.app.background:
        try:
            bpy.utils.unregister_tool(workspace.GradingCivilTool)
        except Exception:
            pass
    del bpy.types.Scene.CivilGradingProperties

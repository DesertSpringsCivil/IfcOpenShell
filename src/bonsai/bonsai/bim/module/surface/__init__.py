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

"""Saikei surface module — Bonsai-side terrain modeler.

Phase 4 of the Saikei grading/earthwork sprint. Wraps Phase 1's
``ifcopenshell.api.surface`` for IFC authoring, adds the math layer
(TIN construction, retriangulation, Z-at-XY interpolation), Blender
object/mesh linkage, and the UI surface (panels, operators, GPU
decorators) that gives users a working terrain modeler.

Subsequent commits add the operator / panel / decorator classes and
register them here. This commit (10) lands the property groups and
UIList; commit 11 adds the create operator, etc.
"""

import bpy
from bpy.app.handlers import persistent

from . import operator, prop, ui


classes: tuple[type, ...] = (
    prop.CivilSurfaceListItem,
    prop.CIVIL_UL_surfaces,
    prop.CivilSurfaceProperties,
    operator.CIVIL_OT_surface_create_from_points,
    operator.CIVIL_OT_surface_retriangulate,
    operator.CIVIL_OT_surface_set_boundary,
    operator.CIVIL_OT_surface_add_breakline,
    ui.CIVIL_PT_surface_creation,
    ui.CIVIL_PT_surface_list,
    ui.CIVIL_PT_surface_active,
    ui.CIVIL_PT_surface_display,
)


@persistent
def _on_load_post(_dummy: bpy.types.Scene) -> None:
    """File-load cleanup: uninstall the GPU draw handler that was
    captured against the previous file's context.

    Without this, the SurfaceDecorator's ``draw_3d`` callback continues
    to run with a closure over the old context, racing the new file's
    initialization. ``@bpy.app.handlers.persistent`` keeps this hook
    registered across .blend reloads.

    Lazy-imports the decorator module so this handler doesn't trigger
    a module-level import chain at addon-register time.
    """
    from . import decorator as surface_decorator

    surface_decorator.SurfaceDecorator.uninstall()


def register() -> None:
    """Module-level registration hook.

    Called by ``bonsai.bim`` after the parent has registered all module
    classes. Attaches :class:`CivilSurfaceProperties` to ``bpy.types.Scene``
    as a ``PointerProperty`` so the UI panel can read / write surface state
    via ``context.scene.CivilSurfaceProperties``. Also registers the
    file-load cleanup handler.
    """
    bpy.types.Scene.CivilSurfaceProperties = bpy.props.PointerProperty(
        type=prop.CivilSurfaceProperties
    )
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)


def unregister() -> None:
    """Module-level teardown hook (mirror of :func:`register`)."""
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    del bpy.types.Scene.CivilSurfaceProperties

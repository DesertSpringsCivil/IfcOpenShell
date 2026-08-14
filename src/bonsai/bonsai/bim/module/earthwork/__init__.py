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

"""Saikei earthwork module — Bonsai-side cut/fill volume computation.

Phase 6 of the Saikei grading/earthwork sprint. Wraps Phase 3's
``ifcopenshell.api.earthwork`` for IFC authoring, adds the math layer
(TIN-to-TIN prismoidal volume calculation, cut/fill solid
construction, shrink/swell pay quantities), Blender object linkage,
and the UI surface (panels, operators, optional cut/fill heat-map
decorator) that gives users a working earthwork-volume workflow.

Builds on Phase 4's surface module (existing ground + proposed
surfaces) and Phase 5's grading module (per-group composite proposed
surfaces). The earthwork volume calculation is the canonical "what
does this site cost in dirt?" computation: existing TIN minus
proposed TIN → cut/fill regions → closed PolygonalFaceSet bodies →
:class:`IfcEarthworksCut` + :class:`IfcEarthworksFill` with full
``Qto_Earthworks*BaseQuantities`` and ``Pset_SaikeiGradingShrinkSwell``
attached.

Subsequent commits add the VolumeResult dataclass / volume math /
solid construction / operator / panel / decorator classes and
register them here. This scaffold establishes the package shell and
the parent-module wiring at ``bim/__init__.py``.
"""

import bpy
from bpy.app.handlers import persistent

from . import decorator, operator, prop, ui, workspace


@persistent
def _on_load_post(_dummy: bpy.types.Scene) -> None:
    """File-load cleanup: uninstall the GPU draw handler captured against
    the previous file's context, and reset the overlay-toggle BoolProperty
    so the post-load state is deterministic.

    Mirrors :func:`bonsai.bim.module.grading.__init__._on_load_post`.
    Lazy-imports the decorator module to avoid triggering an import
    chain at addon-register time.
    """
    from . import decorator as earthwork_decorator

    earthwork_decorator.EarthworkDecorator.uninstall()

    scene = bpy.context.scene if bpy.context else None
    props = getattr(scene, "CivilEarthworkProperties", None) if scene else None
    if props is not None:
        props.show_cut_fill_overlay = False


classes: tuple[type, ...] = (
    prop.CivilEarthworkProperties,
    operator.CIVIL_OT_compute_earthwork_volumes,
    operator.CIVIL_OT_earthwork_clear_report,
    operator.CIVIL_OT_earthwork_delete_results,
    operator.CIVIL_OT_earthwork_volume_probe,
    ui.CIVIL_PT_earthwork_inputs,
    ui.CIVIL_PT_earthwork_compute,
)


def register() -> None:
    """Module-level registration hook.

    Called by ``bonsai.bim`` after the parent has registered all
    module classes. Attaches :class:`CivilEarthworkProperties` to
    ``bpy.types.Scene`` as a ``PointerProperty`` so the UI panel can
    read / write earthwork state via
    ``context.scene.CivilEarthworkProperties``.

    Registers the :class:`~decorator.EarthworkDecorator` load_post
    handler. The draw handler is installed lazily when the user first
    enables the cut/fill overlay toggle (via the update callback on
    :attr:`CivilEarthworkProperties.show_cut_fill_overlay`).
    """
    bpy.types.Scene.CivilEarthworkProperties = bpy.props.PointerProperty(
        type=prop.CivilEarthworkProperties
    )
    # Register the persistent load_post handler so the decorator
    # uninstalls itself on file load and the overlay toggle resets to
    # False (prevents stale handlers from carrying across open-file calls).
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)
    if not bpy.app.background:
        bpy.utils.register_tool(workspace.EarthworkCivilTool, separator=True, group=False)


def unregister() -> None:
    """Module-level teardown hook (mirror of :func:`register`)."""
    decorator.EarthworkDecorator.uninstall()
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    if not bpy.app.background:
        bpy.utils.unregister_tool(workspace.EarthworkCivilTool)
    del bpy.types.Scene.CivilEarthworkProperties

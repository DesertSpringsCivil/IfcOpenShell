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

from . import operator, prop, ui


classes: tuple[type, ...] = (
    prop.CivilEarthworkProperties,
    operator.CIVIL_OT_compute_earthwork_volumes,
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
    """
    bpy.types.Scene.CivilEarthworkProperties = bpy.props.PointerProperty(
        type=prop.CivilEarthworkProperties
    )


def unregister() -> None:
    """Module-level teardown hook (mirror of :func:`register`)."""
    del bpy.types.Scene.CivilEarthworkProperties

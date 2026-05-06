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

"""Property groups for the Saikei earthwork module.

Per spec §8.3, the UI exposes:

- Inputs for the volume operator: existing/proposed surface GUIDs,
  shrink/swell factors, predefined-type selectors for cut and fill.
- Last computed cut/fill/net volumes (cached from the most recent
  ``CIVIL_OT_compute_earthwork_volumes`` invocation; the panel reads
  from these so the user sees a persistent report rather than
  re-running the math on every panel redraw).

Single PointerProperty on ``bpy.types.Scene`` —
:class:`CivilEarthworkProperties` — registered in
:func:`bonsai.bim.module.earthwork.register`.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
from bpy.types import PropertyGroup


# Module-level item caches for the surface-dropdown enum callbacks.
# Blender 5.0's RNA enum system holds C-side pointers to the Python
# string objects returned from an items callback. If those strings are
# garbage-collected between the callback return and Blender's renderer
# read, the enum draw can crash. Anchoring the result in a module-level
# list (re-assigned via slice-replace, not rebind) keeps strings alive.
_existing_surface_items_cache: list = []
_proposed_surface_items_cache: list = []


def _on_overlay_toggle_change(self, context: bpy.types.Context) -> None:
    """Install / uninstall :class:`EarthworkDecorator` based on the
    cut/fill overlay toggle.

    Lazy-imports the decorator module to avoid the circular import that
    would otherwise arise (decorator imports tool which imports the bim
    module's prop). Matches the pattern used by
    :func:`bonsai.bim.module.grading.prop._on_decorator_toggle_change`.
    """
    from . import decorator as earthwork_decorator

    if self.show_cut_fill_overlay:
        if not earthwork_decorator.EarthworkDecorator.is_installed:
            earthwork_decorator.EarthworkDecorator.install(context)
    else:
        earthwork_decorator.EarthworkDecorator.uninstall()


def _get_existing_surface_items(self, context):
    """Dynamic enum items for the existing-surface dropdown.

    Returns ``[(guid, name, description), ...]`` by calling
    :meth:`tool.Surface.iter_surfaces`.  An empty sentinel entry is
    prepended so the initial state (nothing picked yet) maps to the
    blank ``existing_surface_guid`` default.

    Lazy-imports ``bonsai.tool`` to avoid the circular import that
    would otherwise arise when the prop module initialises before
    the full Bonsai tool layer is registered.

    Result is cached in a module-level list (slice-replaced, not
    re-assigned) so the returned reference stays valid for Blender's
    enum renderer. See _existing_surface_items_cache comment above.
    """
    import bonsai.tool as tool  # noqa: PLC0415 - intentional lazy import

    ifc_file = tool.Ifc.get()
    if ifc_file is None:
        _existing_surface_items_cache[:] = [("", "(no IFC file)", "")]
        return _existing_surface_items_cache
    items = [("", "(select existing surface)", "")]
    items.extend(tool.Surface.iter_surfaces(ifc_file))
    if len(items) == 1:
        _existing_surface_items_cache[:] = [("", "(no terrain surfaces)", "")]
    else:
        _existing_surface_items_cache[:] = items
    return _existing_surface_items_cache


def _get_proposed_surface_items(self, context):
    """Dynamic enum items for the proposed-surface dropdown.

    Returns ``[(guid, name, description), ...]`` by calling
    :meth:`tool.Surface.iter_proposed_surfaces`. Same module-level
    caching pattern as :func:`_get_existing_surface_items`.
    """
    import bonsai.tool as tool  # noqa: PLC0415 - intentional lazy import

    ifc_file = tool.Ifc.get()
    if ifc_file is None:
        _proposed_surface_items_cache[:] = [("", "(no IFC file)", "")]
        return _proposed_surface_items_cache
    items = [("", "(select proposed surface)", "")]
    items.extend(tool.Surface.iter_proposed_surfaces(ifc_file))
    if len(items) == 1:
        _proposed_surface_items_cache[:] = [("", "(no proposed surfaces)", "")]
    else:
        _proposed_surface_items_cache[:] = items
    return _proposed_surface_items_cache


def _on_existing_surface_enum_update(self, context):
    """Write the selected GUID into the canonical ``existing_surface_guid``
    StringProperty whenever the user picks a dropdown row."""
    if self.existing_surface_enum:
        self.existing_surface_guid = self.existing_surface_enum


def _on_proposed_surface_enum_update(self, context):
    """Write the selected GUID into the canonical ``proposed_surface_guid``
    StringProperty whenever the user picks a dropdown row."""
    if self.proposed_surface_enum:
        self.proposed_surface_guid = self.proposed_surface_enum


# Allowed values must match
# ifcopenshell.api.earthwork._shared.ALLOWED_CUT_TYPES /
# .PHASE3_FILL_TYPES.  Operator enforces validation; the EnumProperty
# items here are the user-facing picks.
_CUT_PREDEFINED_TYPES = [
    ("EXCAVATION", "Excavation", "General earthwork excavation (default)"),
    ("BASE_EXCAVATION", "Base Excavation", "Excavation to construction base"),
    ("CUT", "Cut", "Generic cut"),
    ("DREDGING", "Dredging", "Underwater excavation"),
    ("OVEREXCAVATION", "Over-Excavation", "Beyond required depth"),
    ("PAVEMENTMILLING", "Pavement Milling", "Removal of pavement"),
    ("STEPEXCAVATION", "Step Excavation", "Stepped widening"),
    ("TOPSOILREMOVAL", "Topsoil Removal", "Stripping organic topsoil"),
    ("TRENCH", "Trench", "Length >> depth/width"),
    ("USERDEFINED", "User Defined",
     "Custom type — set ObjectType manually via the pset editor"),
    ("NOTDEFINED", "Not Defined", "Type not specified"),
]

_FILL_PREDEFINED_TYPES = [
    ("BACKFILL", "Backfill", "Backfill (default)"),
    ("EMBANKMENT", "Embankment", "Embankment material"),
    ("COUNTERWEIGHT", "Counterweight", "Counterweight fill"),
    ("SUBGRADEBED", "Subgrade Bed", "Subgrade-bed material"),
    ("TRANSITIONSECTION", "Transition Section", "Transition material"),
    ("USERDEFINED", "User Defined",
     "Custom type — set ObjectType manually via the pset editor"),
    ("NOTDEFINED", "Not Defined", "Type not specified"),
]


class CivilEarthworkProperties(PropertyGroup):
    """Top-level Saikei earthwork module state. Attached to
    ``bpy.types.Scene`` via :func:`bonsai.bim.module.earthwork.register`."""

    # ----------------------------------------------------------------------
    # Volume-operator inputs
    # ----------------------------------------------------------------------

    existing_surface_guid: StringProperty(
        name="Existing Surface GUID",
        description="GlobalId of the existing-ground CivilSurface "
        "(typically an IfcGeographicElement[TERRAIN])",
        default="",
    )

    existing_surface_enum: EnumProperty(
        name="Existing Surface",
        description="Pick the existing (terrain) surface. Updates "
        "Existing Surface GUID automatically.",
        items=_get_existing_surface_items,
        update=_on_existing_surface_enum_update,
    )

    proposed_surface_guid: StringProperty(
        name="Proposed Surface GUID",
        description="GlobalId of the proposed-ground CivilSurface "
        "(may be a Phase 5 grading-group composite)",
        default="",
    )

    proposed_surface_enum: EnumProperty(
        name="Proposed Surface",
        description="Pick the proposed (design) surface. Updates "
        "Proposed Surface GUID automatically.",
        items=_get_proposed_surface_items,
        update=_on_proposed_surface_enum_update,
    )

    shrink_factor: FloatProperty(
        name="Shrink Factor",
        description="Fill-side shrinkage ratio (compacted / bank). "
        "Typical values 0.85-0.95. 1.0 means no shrinkage.",
        default=1.0,
        min=0.5,
        max=1.5,
    )

    swell_factor: FloatProperty(
        name="Swell Factor",
        description="Cut-side swell ratio (loose / bank). Typical "
        "values 1.10-1.30. 1.0 means no swell. LooseVolume on the "
        "cut Qto = UndisturbedVolume * SwellFactor. Excavated "
        "material always occupies more space than its bank state, "
        "so values < 1.0 are physically invalid.",
        default=1.0,
        min=1.0,
        max=1.5,
    )

    cut_predefined_type: EnumProperty(
        name="Cut Predefined Type",
        description="Cut type classification. "
        "Default EXCAVATION for general earthwork.",
        items=_CUT_PREDEFINED_TYPES,
        default="EXCAVATION",
    )

    fill_predefined_type: EnumProperty(
        name="Fill Predefined Type",
        description="Fill type classification. "
        "Volume-bearing range only — SLOPEFILL and SUBGRADE are "
        "reserved for Phase 2 grading composition.",
        items=_FILL_PREDEFINED_TYPES,
        default="BACKFILL",
    )

    cut_name: StringProperty(
        name="Cut Name",
        description="Human-readable name for the cut volume entity",
        default="Earthwork Cut",
    )

    fill_name: StringProperty(
        name="Fill Name",
        description="Human-readable name for the fill volume entity",
        default="Earthwork Fill",
    )

    # ----------------------------------------------------------------------
    # Last-computed report (cached from the most recent operator run)
    # ----------------------------------------------------------------------

    last_cut_m3: FloatProperty(
        name="Last Cut (m³)",
        description="Undisturbed cut volume from the most recent "
        "compute_earthwork_volumes invocation. Cached so the panel "
        "shows a persistent report rather than re-running the math "
        "every redraw.",
        default=0.0,
    )

    last_fill_m3: FloatProperty(
        name="Last Fill (m³)",
        description="Compacted fill volume from the most recent run.",
        default=0.0,
    )

    last_net_m3: FloatProperty(
        name="Last Net (m³)",
        description="Net = cut - fill. Positive = haul-off (net "
        "excavation); negative = borrow (net import); zero = "
        "balanced earthwork.",
        default=0.0,
    )

    last_loose_cut_m3: FloatProperty(
        name="Last Loose Cut (m³)",
        description="Loose cut volume = undisturbed * swell_factor. "
        "The 'haul' volume — how much truck space the excavated "
        "material occupies before recompaction.",
        default=0.0,
    )

    last_run_existing_guid: StringProperty(
        name="Last Run Existing GUID",
        description="Existing-surface GUID used in the last run. "
        "Used to validate the cached report still applies.",
        default="",
    )

    last_run_proposed_guid: StringProperty(
        name="Last Run Proposed GUID",
        description="Proposed-surface GUID used in the last run.",
        default="",
    )

    last_run_cut_guid: StringProperty(
        name="Last Run Cut GUID",
        description="GlobalId of the cut volume entity authored on the "
        "most recent compute run. Used by the delete-results operator "
        "to locate and remove the entity.",
        default="",
    )

    last_run_fill_guid: StringProperty(
        name="Last Run Fill GUID",
        description="GlobalId of the fill volume entity authored on "
        "the most recent compute run. Used by the delete-results "
        "operator.",
        default="",
    )

    # ----------------------------------------------------------------------
    # Display toggles
    # ----------------------------------------------------------------------

    show_cut_fill_overlay: BoolProperty(
        name="Show Cut/Fill Overlay",
        description="Draw the cut/fill color map over the earthwork "
        "solids in the 3D viewport. Cut regions render red, fill "
        "regions render blue.",
        default=False,
        update=_on_overlay_toggle_change,
    )

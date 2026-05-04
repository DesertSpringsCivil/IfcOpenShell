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
from bpy.props import EnumProperty, FloatProperty, StringProperty
from bpy.types import PropertyGroup


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
]

_FILL_PREDEFINED_TYPES = [
    ("BACKFILL", "Backfill", "Backfill (default)"),
    ("EMBANKMENT", "Embankment", "Embankment material"),
    ("COUNTERWEIGHT", "Counterweight", "Counterweight fill"),
    ("SUBGRADEBED", "Subgrade Bed", "Subgrade-bed material"),
    ("TRANSITIONSECTION", "Transition Section", "Transition material"),
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

    proposed_surface_guid: StringProperty(
        name="Proposed Surface GUID",
        description="GlobalId of the proposed-ground CivilSurface "
        "(may be a Phase 5 grading-group composite)",
        default="",
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
        "Qto = UndisturbedVolume * SwellFactor.",
        default=1.0,
        min=0.8,
        max=1.5,
    )

    cut_predefined_type: EnumProperty(
        name="Cut Predefined Type",
        description="IfcEarthworksCutTypeEnum value to author. "
        "Default EXCAVATION for general earthwork.",
        items=_CUT_PREDEFINED_TYPES,
        default="EXCAVATION",
    )

    fill_predefined_type: EnumProperty(
        name="Fill Predefined Type",
        description="IfcEarthworksFillTypeEnum value to author. "
        "Volume-bearing range only — SLOPEFILL and SUBGRADE are "
        "reserved for Phase 2 grading composition.",
        items=_FILL_PREDEFINED_TYPES,
        default="BACKFILL",
    )

    cut_name: StringProperty(
        name="Cut Name",
        description="Human-readable IFC entity name for the cut",
        default="Earthwork Cut",
    )

    fill_name: StringProperty(
        name="Fill Name",
        description="Human-readable IFC entity name for the fill",
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

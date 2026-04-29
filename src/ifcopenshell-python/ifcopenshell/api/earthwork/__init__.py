# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2026 Desert Springs Civil Engineering PLLC
#
# This file is part of IfcOpenShell.
#
# IfcOpenShell is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# IfcOpenShell is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with IfcOpenShell.  If not, see <http://www.gnu.org/licenses/>.

"""High-level API for authoring earthwork-volume IFC 4.3 entities.

Persists cut and fill volumes as :class:`IfcEarthworksCut` /
:class:`IfcEarthworksFill` with closed :class:`IfcPolygonalFaceSet` body
representations, the standard ``Qto_Earthworks*BaseQuantities``, the Saikei
``Pset_SaikeiGradingShrinkSwell``, and OmniClass Table 22 classifications.
The API persists what it's given — the prismoidal-volume math (spec §6.4)
and watertight closed-solid construction (spec §6.5) live in Bonsai's
``tool.Earthwork`` (Phase 6).

Phase 3 of the Saikei grading/earthwork sprint; depends on Phase 1
(``ifcopenshell.api.surface``) for terrain authoring and Phase 2
(``ifcopenshell.api.grading``) for the shared helper module.

Public functions are re-exported here so callers do
``ifcopenshell.api.earthwork.create_earthworks_cut(...)``.
"""

from .add_volume_solid_representation import add_volume_solid_representation
from .create_earthworks_cut import create_earthworks_cut
from .create_earthworks_fill import create_earthworks_fill
from .void_terrain import void_terrain
from .write_cut_quantities import write_cut_quantities
from .write_fill_quantities import write_fill_quantities

__all__ = [
    "add_volume_solid_representation",
    "create_earthworks_cut",
    "create_earthworks_fill",
    "void_terrain",
    "write_cut_quantities",
    "write_fill_quantities",
]

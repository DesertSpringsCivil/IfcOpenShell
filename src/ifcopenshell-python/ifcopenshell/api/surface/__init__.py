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

"""High-level API for authoring surface-related IFC 4.3 entities.

This API persists pre-triangulated terrain and proposed-grading surfaces as
IfcGeographicElement[TERRAIN] / IfcEarthworksFill[SUBGRADE] hosts carrying
IfcTriangulatedIrregularNetwork representations, with breaklines stored as
separate IfcAnnotation entities so they survive retriangulation.

This package is part of Phase 1 of the Saikei grading/earthwork sprint and
will be extended by ifcopenshell.api.grading (Phase 2) and
ifcopenshell.api.earthwork (Phase 3). It is under development and subject to
code-breaking changes.

Public functions are re-exported here so callers do
``ifcopenshell.api.surface.create_terrain(...)``.
"""

from .add_bounding_box_representation import add_bounding_box_representation
from .add_tin_representation import add_tin_representation

__all__ = [
    "add_bounding_box_representation",
    "add_tin_representation",
]

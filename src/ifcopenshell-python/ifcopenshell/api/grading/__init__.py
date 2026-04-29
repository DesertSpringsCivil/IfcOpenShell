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

"""High-level API for authoring grading-related IFC 4.3 entities.

This API persists Civil 3D-style grading objects: feature lines, reusable
grading criteria templates, grading groups, and the per-group earthwork
fills that compose a graded feature. It is Phase 2 of the Saikei
grading/earthwork sprint and depends on Phase 1
(``ifcopenshell.api.surface``) for TIN authoring.

Public functions are re-exported here so callers do
``ifcopenshell.api.grading.create_grading_group(...)``.
"""

__all__: list[str] = []

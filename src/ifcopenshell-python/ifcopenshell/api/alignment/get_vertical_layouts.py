# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2025 Thomas Krijnen <thomas@aecgeeks.com>
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

import ifcopenshell.api.alignment
from ifcopenshell import entity_instance


def get_vertical_layouts(alignment: entity_instance) -> list[entity_instance]:
    """
    Returns all of the IfcAlignmentVertical layouts associated with this alignment.

    Per IFC CT 4.1.4.4.1.1 Alignment Layout - Horizontal, Vertical and Cant, an alignment's first
    vertical layout is nested directly onto the alignment. get_vertical_layout finds it there.

    Per IFC CT 4.1.4.4.1.2 Alignment Layout - Reusing Horizontal Layout, once a second (or
    subsequent) vertical layout is added, add_vertical_layout migrates every vertical layout off
    of the parent alignment and onto its own aggregated child IfcAlignment, one vertical layout
    per child. From that point on, the parent's own nest has none, and get_vertical_layout's
    first-match scan of it returns None even though verticals still exist. This function instead
    checks both locations and returns every vertical layout it finds, in deterministic order.

    :param alignment: the alignment
    :return: the vertical layout nested directly on the alignment (if any), followed by one per
        aggregated child alignment, in aggregation order. Empty list if the alignment has no
        vertical layout at all.

    Example:

    .. code:: python

        alignment = model.by_type("IfcAlignment")[0]
        vertical_layouts = ifcopenshell.api.alignment.get_vertical_layouts(alignment)
    """
    vertical_layouts = []

    for rel in alignment.IsNestedBy:
        for related_object in rel.RelatedObjects:
            if related_object.is_a("IfcAlignmentVertical"):
                vertical_layouts.append(related_object)

    for child_alignment in ifcopenshell.api.alignment.get_child_alignments(alignment):
        for rel in child_alignment.IsNestedBy:
            for related_object in rel.RelatedObjects:
                if related_object.is_a("IfcAlignmentVertical"):
                    vertical_layouts.append(related_object)

    return vertical_layouts

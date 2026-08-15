# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2026 Michael Yoder <myoder@desertspringscivil.com>
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

"""Author the entity pair (IfcGroup + per-group composite IfcEarthworksFill) that constitutes a Saikei grading group."""

from __future__ import annotations

import time
from typing import NamedTuple, Optional

import ifcopenshell
import ifcopenshell.api.pset
import ifcopenshell.api.spatial
import ifcopenshell.guid

from ._shared import (
    _resolve_site,
    apply_omniclass_classification,
    attach_earthworks_fill_common,
    identity_placement,
)
from .add_member_to_group import add_member_to_group

GROUP_OBJECT_TYPE = "GradingGroup"
SOURCE_PSET_NAME = "SaikeiCivil_GradingSource"
COMPOSITE_FILL_OMNICLASS_CODE = "22-07 31 23"
COMPOSITE_FILL_OMNICLASS_TITLE = "Fill"
ALLOWED_INTERIOR_FILL_STRATEGIES = frozenset(
    {"none", "flat", "interpolate_from_boundary", "from_surface"}
)


class GradingGroupAuthoring(NamedTuple):
    """Result of :func:`create_grading_group` — the two related entities the caller now owns."""

    group: ifcopenshell.entity_instance
    """The :class:`IfcGroup` with ``ObjectType="GradingGroup"``."""
    composite_fill: ifcopenshell.entity_instance
    """The per-group composite :class:`IfcEarthworksFill` that aggregates child fills."""


def _attach_grading_source_pset(
    file: ifcopenshell.file,
    group: ifcopenshell.entity_instance,
    *,
    interior_fill: str,
    target_surface_guid: Optional[str],
    author: Optional[str],
) -> None:
    """Attach SaikeiCivil_GradingSource with creation-time metadata."""
    properties: dict[str, object] = {
        "InteriorFillStrategy": interior_fill,
        "Timestamp": int(time.time()),
        "Version": 1,
    }
    if target_surface_guid is not None:
        properties["TargetSurfaceGuid"] = target_surface_guid
    if author is not None:
        properties["Author"] = author
    pset = ifcopenshell.api.pset.add_pset(file, product=group, name=SOURCE_PSET_NAME)
    ifcopenshell.api.pset.edit_pset(file, pset=pset, properties=properties)


def create_grading_group(
    file: ifcopenshell.file,
    name: str,
    *,
    target_surface: Optional[ifcopenshell.entity_instance] = None,
    interior_fill: str = "interpolate_from_boundary",
    interior_fill_source: Optional[ifcopenshell.entity_instance] = None,
    site: Optional[ifcopenshell.entity_instance] = None,
    author: Optional[str] = None,
) -> GradingGroupAuthoring:
    """Author the entity pair that constitutes a Saikei grading group.

    Returns a :class:`GradingGroupAuthoring` named tuple wrapping two related
    entities the caller now owns:

    1. :class:`IfcGroup` with ``ObjectType="GradingGroup"`` — the logical
       collection. Carries ``SaikeiCivil_GradingSource`` with ``Timestamp``,
       ``Version``, ``InteriorFillStrategy``, and the optional
       ``TargetSurfaceGuid`` and ``Author``. NOT placed in the spatial tree
       (``IfcGroup`` is not an :class:`IfcProduct`); discoverable via
       ``file.by_type("IfcGroup")`` filtered by ``ObjectType``.

    2. :class:`IfcEarthworksFill` with ``PredefinedType=SUBGRADE`` — the
       per-group composite shell that subsequent
       :func:`add_slope_fill_to_group` and
       :func:`add_interior_fill_to_group` calls aggregate child fills under
       via :class:`IfcRelAggregates`. Spatially contained in :class:`IfcSite`
       via :class:`IfcRelContainedInSpatialStructure` so the file is
       schema-clean at every authoring step. Standard
       ``Pset_EarthworksFillCommon`` (``Status="NEW"``) and OmniClass Table 22
       classification (``22-07 31 23`` Fill) attached. The composite has no
       geometric representation at creation — the proposed TIN and fill solid
       are produced by the Phase 4/5 group-rebuild step.

    The composite fill is added to the group as its initial member via
    :class:`IfcRelAssignsToGroup`. Subsequent :func:`add_member_to_group`
    calls append further members.

    **Site-composite hand-off.** The returned ``composite_fill`` is intended
    to later be aggregated under a site-level composite (the
    :class:`IfcEarthworksFill[SUBGRADE]` authored via
    ``ifcopenshell.api.surface.create_proposed_surface``). That aggregation
    is OUT OF SCOPE for Phase 2 — Phase 4/5 Bonsai glue, or a future
    ``aggregate_group_to_site_composite`` helper, will wire it up. When that
    happens, the composite_fill's :class:`IfcRelContainedInSpatialStructure`
    relationship to :class:`IfcSite` should be removed in favour of the
    aggregation under the site composite (per spec §2.7).

    :param file: the IFC file to author into
    :param name: human-readable name shared by the group and the composite fill
    :param target_surface: the existing-ground surface this group is grading
        against; when supplied, its GUID is recorded on
        ``SaikeiCivil_GradingSource``
    :param interior_fill: one of ``none``, ``flat``,
        ``interpolate_from_boundary``, ``from_surface``
    :param interior_fill_source: required when
        ``interior_fill="from_surface"``; ignored otherwise
    :param site: the :class:`IfcSite` to spatially contain the composite_fill
        in; if ``None``, the project's first ``IfcSite`` is used
    :param author: free-form author label for ``SaikeiCivil_GradingSource``
    :returns: a :class:`GradingGroupAuthoring` named tuple
        ``(group, composite_fill)``
    :raises ValueError: if ``interior_fill`` is not one of the four allowed
        values, if ``interior_fill="from_surface"`` and
        ``interior_fill_source`` is ``None``, or if ``site`` is ``None`` and
        no :class:`IfcSite` exists in the project
    """
    if interior_fill not in ALLOWED_INTERIOR_FILL_STRATEGIES:
        raise ValueError(
            f"interior_fill must be one of {sorted(ALLOWED_INTERIOR_FILL_STRATEGIES)}, "
            f"got {interior_fill!r}"
        )
    if interior_fill == "from_surface" and interior_fill_source is None:
        raise ValueError(
            "interior_fill='from_surface' requires interior_fill_source to be supplied"
        )
    target_site = _resolve_site(file, site)

    group = file.create_entity(
        "IfcGroup",
        GlobalId=ifcopenshell.guid.new(),
        Name=name,
        ObjectType=GROUP_OBJECT_TYPE,
    )

    composite_fill = file.create_entity(
        "IfcEarthworksFill",
        GlobalId=ifcopenshell.guid.new(),
        Name=name,
        PredefinedType="SUBGRADE",
        ObjectPlacement=identity_placement(file),
    )
    ifcopenshell.api.spatial.assign_container(
        file, products=[composite_fill], relating_structure=target_site
    )
    attach_earthworks_fill_common(file, composite_fill)
    apply_omniclass_classification(
        file, composite_fill, COMPOSITE_FILL_OMNICLASS_CODE, COMPOSITE_FILL_OMNICLASS_TITLE
    )

    target_surface_guid = (
        target_surface.GlobalId if target_surface is not None else None
    )
    _attach_grading_source_pset(
        file,
        group,
        interior_fill=interior_fill,
        target_surface_guid=target_surface_guid,
        author=author,
    )

    add_member_to_group(file, group, composite_fill)

    return GradingGroupAuthoring(group=group, composite_fill=composite_fill)

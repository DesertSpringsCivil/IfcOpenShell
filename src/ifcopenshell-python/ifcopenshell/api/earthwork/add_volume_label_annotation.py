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

"""Author an IfcAnnotation labeling cut/fill depth at a specific XYZ.

Per Saikei spec section 1.6, every Saikei Pset is authored by an
ifcopenshell.api.* helper rather than inline in Bonsai code. This
helper authors the IfcAnnotation entity and attaches
Pset_SaikeiVolumeLabel with CutDepth, FillDepth, and optional
LabelText.
"""

from __future__ import annotations

import math
from typing import Optional

import ifcopenshell
import ifcopenshell.api.pset
import ifcopenshell.api.spatial
import ifcopenshell.guid
from ifcopenshell.api.grading._shared import (
    apply_omniclass_classification,
    _resolve_site,
)


def add_volume_label_annotation(
    file: ifcopenshell.file,
    site: ifcopenshell.entity_instance,
    xyz: tuple[float, float, float],
    cut_depth: float,
    fill_depth: float,
    label_text: Optional[str] = None,
    name: Optional[str] = None,
) -> ifcopenshell.entity_instance:
    """Author an :class:`IfcAnnotation` with ``Pset_SaikeiVolumeLabel`` at xyz.

    The annotation is spatially contained in ``site`` via
    :class:`IfcRelContainedInSpatialStructure`. Returns the annotation entity.

    Authors:

    - :class:`IfcAnnotation` with ``ObjectType = "VolumeLabel"``
    - :class:`IfcLocalPlacement` at ``xyz`` (no parent placement — placement
      is expressed as a world-origin-relative placement per spec §2.8)
    - :class:`IfcRelContainedInSpatialStructure` attaching the annotation to
      ``site``
    - ``Pset_SaikeiVolumeLabel`` with ``CutDepth``, ``FillDepth``, and
      optionally ``LabelText``
    - OmniClass Table 22 classification ``22-07 31 00`` (Earthwork —
      general site preparation; the umbrella code for volume probes)

    No :class:`IfcProductDefinitionShape` is authored — volume-label
    annotations are placement-only; the Bonsai ``EarthworkDecorator``
    provides the viewport visual from the Pset values.

    :param file: the IFC file to author into.
    :param site: the :class:`IfcSite` to spatially contain the annotation in.
        Resolved automatically (first site in file) when the caller passes the
        result of :func:`ifcopenshell.api.grading._shared._resolve_site`.
    :param xyz: ``(x, y, z)`` world position in project units (metres).
        All three components must be finite; raises :class:`ValueError` for
        ``NaN`` or infinite values.
    :param cut_depth: cut depth in metres at the probe point. May be 0.0 for a
        pure-fill location. Negative values are allowed — undulating terrain
        can produce negative net depths in edge cases (e.g. the proposed
        surface is everywhere above the existing in this region, but the probe
        sits on the border). Absolute interpretation is up to the consumer;
        the decorator shows whichever of CutDepth / FillDepth is non-zero.
    :param fill_depth: fill depth in metres at the probe point. Same sign
        convention as ``cut_depth``.
    :param label_text: optional free-text override for the annotation name
        and the ``LabelText`` Pset property. When ``None``, ``LabelText`` is
        omitted from the Pset and ``Name`` is auto-generated as
        ``"VolumeLabel C{cut_depth:.3f} F{fill_depth:.3f}"``.
    :param name: optional explicit ``Name`` attribute. When ``None``,
        ``label_text`` is used if supplied, otherwise the auto-generated
        cut/fill string. This parameter is distinct from ``label_text`` so
        callers can set a different display name vs. the Pset text.
    :returns: the created :class:`IfcAnnotation` entity.
    :raises ValueError: if ``xyz`` contains non-finite values.
    """
    # -- Validate xyz ----------------------------------------------------------
    try:
        x_val, y_val, z_val = (float(v) for v in xyz)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"xyz must be a 3-element sequence of real numbers; got {xyz!r}"
        ) from exc
    if not (math.isfinite(x_val) and math.isfinite(y_val) and math.isfinite(z_val)):
        raise ValueError(
            f"xyz coordinates must be finite; got ({x_val}, {y_val}, {z_val})"
        )

    cut_depth = float(cut_depth)
    fill_depth = float(fill_depth)
    if not math.isfinite(cut_depth):
        raise ValueError(f"cut_depth must be finite; got {cut_depth}")
    if not math.isfinite(fill_depth):
        raise ValueError(f"fill_depth must be finite; got {fill_depth}")

    # -- Resolve annotation name ----------------------------------------------
    auto_name = (
        label_text
        if label_text is not None
        else f"VolumeLabel C{cut_depth:.3f} F{fill_depth:.3f}"
    )
    annotation_name = name if name is not None else auto_name

    # -- Author IfcAnnotation -------------------------------------------------
    annotation = file.create_entity(
        "IfcAnnotation",
        GlobalId=ifcopenshell.guid.new(),
        Name=annotation_name,
        ObjectType="VolumeLabel",
    )

    # Placement at world xyz (no parent; absolute per spec §2.8).
    origin = file.create_entity(
        "IfcCartesianPoint", Coordinates=[x_val, y_val, z_val]
    )
    placement = file.create_entity(
        "IfcLocalPlacement",
        RelativePlacement=file.create_entity(
            "IfcAxis2Placement3D",
            Location=origin,
        ),
    )
    annotation.ObjectPlacement = placement

    # -- Spatial containment --------------------------------------------------
    ifcopenshell.api.spatial.assign_container(
        file, products=[annotation], relating_structure=site
    )

    # -- OmniClass Table 22 classification ------------------------------------
    apply_omniclass_classification(
        file,
        annotation,
        "22-07 31 00",
        "Earthwork",
    )

    # -- Pset_SaikeiVolumeLabel -----------------------------------------------
    pset = ifcopenshell.api.pset.add_pset(
        file,
        product=annotation,
        name="Pset_SaikeiVolumeLabel",
    )
    pset_properties: dict = {
        "CutDepth": cut_depth,
        "FillDepth": fill_depth,
    }
    if label_text is not None:
        pset_properties["LabelText"] = label_text
    ifcopenshell.api.pset.edit_pset(
        file,
        pset=pset,
        properties=pset_properties,
    )

    return annotation

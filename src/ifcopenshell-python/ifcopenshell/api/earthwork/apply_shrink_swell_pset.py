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

"""Attach SaikeiCivil_GradingShrinkSwell to an earthwork product."""

from __future__ import annotations

from typing import Optional

import ifcopenshell
import ifcopenshell.api.pset

PSET_NAME = "SaikeiCivil_GradingShrinkSwell"


def _find_existing_pset(
    product: ifcopenshell.entity_instance, pset_name: str
) -> Optional[ifcopenshell.entity_instance]:
    """Return the IfcPropertySet of ``pset_name`` directly attached to product, or None."""
    for rel in product.IsDefinedBy or []:
        if not rel.is_a("IfcRelDefinesByProperties"):
            continue
        pset = rel.RelatingPropertyDefinition
        if pset is not None and pset.is_a("IfcPropertySet") and pset.Name == pset_name:
            return pset
    return None


def apply_shrink_swell_pset(
    file: ifcopenshell.file,
    product: ifcopenshell.entity_instance,
    *,
    shrink_factor: float = 1.0,
    swell_factor: float = 1.0,
) -> ifcopenshell.entity_instance:
    """Attach (or update) :data:`SaikeiCivil_GradingShrinkSwell` on an earthwork product.

    Per spec §3.3 this Saikei-specific pset carries shrink and swell
    factors that the standard ``Qto_Earthworks*BaseQuantities`` don't
    cover:

    - ``ShrinkFactor`` — ratio of compacted (in-place) volume to bank
      (undisturbed) volume; typical < 1.0 for fine soils, > 1.0 for
      rock-derived fill.
    - ``SwellFactor`` — ratio of loose (delivered, post-excavation)
      volume to bank volume; typical > 1.0 since excavated soil bulks up.

    Defaults are 1.0 / 1.0 — neutral, "we don't have material data yet"
    placeholders. Phase 6's ``tool.Earthwork`` overrides them with project-
    specific values from the geotechnical report or rule-of-thumb tables.

    **Idempotent.** When the product already carries the pset, the
    existing :class:`IfcPropertySet` is updated in place — pattern matches
    :func:`write_cut_quantities` and :func:`write_fill_quantities`. Any
    additional non-standard properties on the existing pset (e.g.,
    user-added moisture-content fields) are preserved; only ShrinkFactor
    and SwellFactor are touched.

    Valid on either :class:`IfcEarthworksFill` or :class:`IfcEarthworksCut`.

    :param file: the IFC file to author into
    :param product: the :class:`IfcEarthworksFill` or
        :class:`IfcEarthworksCut` to attach the pset to
    :param shrink_factor: ``ShrinkFactor`` value (defaults to 1.0)
    :param swell_factor: ``SwellFactor`` value (defaults to 1.0)
    :returns: the :class:`IfcPropertySet` (existing or newly created)
    :raises ValueError: if ``product`` is neither an
        :class:`IfcEarthworksFill` nor an :class:`IfcEarthworksCut`
    """
    if not (
        product.is_a("IfcEarthworksFill") or product.is_a("IfcEarthworksCut")
    ):
        raise ValueError(
            f"product must be IfcEarthworksFill or IfcEarthworksCut, got "
            f"{product.is_a()} #{product.id()}"
        )

    properties: dict[str, object] = {
        "ShrinkFactor": float(shrink_factor),
        "SwellFactor": float(swell_factor),
    }

    pset = _find_existing_pset(product, PSET_NAME)
    if pset is None:
        pset = ifcopenshell.api.pset.add_pset(file, product=product, name=PSET_NAME)
    ifcopenshell.api.pset.edit_pset(file, pset=pset, properties=properties)
    return pset

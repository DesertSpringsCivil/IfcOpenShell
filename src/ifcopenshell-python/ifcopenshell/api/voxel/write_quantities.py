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

"""Write voxel-computed earthwork quantities onto a sidecar host."""

from __future__ import annotations

from typing import Optional

import ifcopenshell
import ifcopenshell.api.earthwork


def write_earthwork_quantities(
    file: ifcopenshell.file,
    host: ifcopenshell.entity_instance,
    *,
    bank_volume: float,
    loose_volume: Optional[float] = None,
) -> ifcopenshell.entity_instance:
    """Write ``Qto_Earthworks{Cut,Fill}BaseQuantities`` from voxel-computed volumes.

    Thin dispatcher over :mod:`ifcopenshell.api.earthwork` — that API's quantity
    authoring uses direct ``*Value`` attribute assignment (no standalone
    defined-type value wrappers), so it is safe on the runtime-registered
    ``IFC4X4_TM27`` schema (unlike Pset ``NominalValue`` authoring, which crashes
    the wrapper — Phase-3 finding F3). Idempotent: re-running updates the same
    ``IfcElementQuantity`` in place.

    Quantity mapping by host type:

    - ``IfcEarthworksCut``  → ``UndisturbedVolume`` = ``bank_volume`` (the
      voxel ``cut`` volume), ``LooseVolume`` = ``loose_volume`` (bank × swell).
    - ``IfcEarthworksFill`` → ``CompactedVolume``   = ``bank_volume`` (the
      voxel ``fill`` volume), ``LooseVolume`` = ``loose_volume``.

    :param bank_volume: the in-place (bank/undisturbed/compacted) volume, m³ —
        typically ``cut`` or ``fill`` from :meth:`bonsai.tool.Voxel.cut_fill`.
    :param loose_volume: optional loose (swelled) volume; omitted from the Qto if
        ``None`` (compute with :meth:`bonsai.tool.Voxel.bulk`).
    :returns: the authored :class:`IfcElementQuantity`.
    :raises ValueError: if ``host`` is not an earthwork cut or fill.
    """
    if host.is_a("IfcEarthworksCut"):
        return ifcopenshell.api.earthwork.write_cut_quantities(
            file, host, undisturbed_volume=bank_volume, loose_volume=loose_volume
        )
    if host.is_a("IfcEarthworksFill"):
        return ifcopenshell.api.earthwork.write_fill_quantities(
            file, host, compacted_volume=bank_volume, loose_volume=loose_volume
        )
    raise ValueError(
        f"host must be an IfcEarthworksCut or IfcEarthworksFill, got {host.is_a()}"
    )

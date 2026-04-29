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

"""Internal helpers specific to the earthwork API.

Shared helpers that are NOT earthwork-specific (identity_placement,
to_point_list, compute_bounding_box, apply_omniclass_classification,
attach_earthworks_fill_common, aggregate_under) live in
``ifcopenshell.api.grading._shared`` — the de facto civil-engineering
shared module — and are imported directly by Phase 3 modules. This file
holds only what's exclusively earthwork's:

- :func:`attach_earthworks_cut_common` — the cut-side standard pset author
  (mirror of grading._shared.attach_earthworks_fill_common).
- ``ALLOWED_CUT_TYPES`` and ``PHASE3_FILL_TYPES`` — the IFC 4.3 enum
  vocabularies the API accepts. ``PHASE3_FILL_TYPES`` excludes ``SLOPEFILL``
  and ``SUBGRADE`` since those belong to Phase 2 grading composition.
- :func:`validate_cut_predefined_type` and :func:`validate_fill_predefined_type` —
  guards used by the cut/fill creation functions.
"""

from __future__ import annotations

import warnings

import ifcopenshell
import ifcopenshell.api.pset

# IFC 4.3 IfcEarthworksCutTypeEnum values, verified against the schema.
ALLOWED_CUT_TYPES = frozenset(
    {
        "BASE_EXCAVATION",
        "CUT",
        "DREDGING",
        "EXCAVATION",
        "OVEREXCAVATION",
        "PAVEMENTMILLING",
        "STEPEXCAVATION",
        "TOPSOILREMOVAL",
        "TRENCH",
        "USERDEFINED",
        "NOTDEFINED",
    }
)

# Phase 3 IfcEarthworksFillTypeEnum values — excludes SLOPEFILL and SUBGRADE,
# which belong to Phase 2's api.grading composition (api.grading authors
# IfcEarthworksFill[SLOPEFILL] for slope ribbons and IfcEarthworksFill[SUBGRADE]
# for the per-group composite + interior fill).
PHASE3_FILL_TYPES = frozenset(
    {
        "BACKFILL",
        "COUNTERWEIGHT",
        "EMBANKMENT",
        "SUBGRADEBED",
        "TRANSITIONSECTION",
        "USERDEFINED",
        "NOTDEFINED",
    }
)

# All IfcEarthworksFillTypeEnum values — used for soft-validation in
# create_earthworks_fill: SLOPEFILL/SUBGRADE produce a UserWarning rather than
# a ValueError so callers can override if they really mean it.
ALL_FILL_TYPES = PHASE3_FILL_TYPES | {"SLOPEFILL", "SUBGRADE"}


def attach_earthworks_cut_common(
    file: ifcopenshell.file, cut: ifcopenshell.entity_instance
) -> ifcopenshell.entity_instance:
    """Attach ``Pset_EarthworksCutCommon`` with ``Status="NEW"`` to ``cut``.

    The minimum-property write is intentional: IFC's
    ``IfcPropertySet.HasProperties`` cardinality is ``[1:?]``, so an empty
    pset is schema-invalid. ``Status="NEW"`` is the lightest legal default;
    callers can override or extend via ``ifcopenshell.api.pset.edit_pset``.

    Mirror of :func:`ifcopenshell.api.grading._shared.attach_earthworks_fill_common`.

    :returns: the created :class:`IfcPropertySet`.
    """
    pset = ifcopenshell.api.pset.add_pset(file, product=cut, name="Pset_EarthworksCutCommon")
    ifcopenshell.api.pset.edit_pset(file, pset=pset, properties={"Status": "NEW"})
    return pset


def validate_cut_predefined_type(value: str) -> None:
    """Raise :class:`ValueError` if ``value`` isn't a valid IfcEarthworksCutTypeEnum value."""
    if value not in ALLOWED_CUT_TYPES:
        raise ValueError(
            f"predefined_type must be one of {sorted(ALLOWED_CUT_TYPES)}, "
            f"got {value!r}"
        )


def validate_fill_predefined_type(value: str) -> None:
    """Validate fill PredefinedType, warning on Phase 2-reserved values.

    SLOPEFILL and SUBGRADE are valid IFC values, but they are reserved by
    ``ifcopenshell.api.grading`` for grading-group composition. Passing them
    to ``create_earthworks_fill`` is almost always a caller mix-up between
    the two APIs, so we emit a :class:`UserWarning` while still allowing the
    value through. Truly unknown values raise :class:`ValueError`.
    """
    if value not in ALL_FILL_TYPES:
        raise ValueError(
            f"predefined_type must be a valid IfcEarthworksFillTypeEnum value "
            f"(got {value!r}); see ifcopenshell schema for the allowed set"
        )
    if value not in PHASE3_FILL_TYPES:
        warnings.warn(
            f"predefined_type={value!r} is reserved by ifcopenshell.api.grading "
            f"for grading-group composition; create_earthworks_fill is intended "
            f"for volume-bearing fills with PredefinedType in "
            f"{sorted(PHASE3_FILL_TYPES)}",
            UserWarning,
            stacklevel=3,
        )

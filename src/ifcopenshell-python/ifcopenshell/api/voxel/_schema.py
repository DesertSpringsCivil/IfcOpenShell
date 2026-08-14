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

"""Internal: register the prototype IFC 4.4 + TM27 schema and bootstrap sidecar files.

TM27 voxel entities (``IfcVoxelGrid`` / ``IfcVoxelData`` family) are not in any
released IfcOpenShell schema. Rather than vendoring a full ~14k-line schema, we
keep only the **TM27 delta** (the handful of new entities, below) and build the
prototype schema at runtime by appending it to a **base IFC4x3 longform EXPRESS**
— so this module carries only Saikei's contribution, not a copy of
buildingSMART's schema.

The base ``.exp`` (an ``IFC4x3_RC4``-compatible longform schema) is located via,
in order: the ``SAIKEI_IFC4X3_BASE_EXP`` environment variable; a sibling
``IFC4.x-development/reference_schemas/IFC4x3_RC4.exp`` checkout next to this
repo; or ``<repo>/reference_schemas/IFC4x3_RC4.exp``. If none is found,
:func:`ensure_registered` raises with guidance — the prototype targets an
**unreleased** schema, so a base must be supplied.

The merge: rename the ``SCHEMA`` header to ``IFC4X4_TM27``, extend the
``IfcProduct`` and ``IfcTessellatedItem`` ``SUPERTYPE OF (ONEOF …)`` lists to
admit the new leaves, and append :data:`TM27_DELTA` before ``END_SCHEMA``.

Two deliberate deviations from stock TM27 (both proven necessary in the spike):

- ``IfcVoxelGrid.Voxels`` is ``LIST [1:?] OF IfcInteger``, not
  ``ARRAY [1:?] OF IfcBoolean``. IfcOpenShell's express parser resolves an
  indeterminate-bound ``ARRAY`` to UNKNOWN, and its Python wrapper has no setter
  for a list-of-boolean. Occupancy is therefore carried as the Saikei RLE
  integer run-pair encoding: ``[count, value, …]`` with value ``1`` = occupied.
- Derived attributes (``GridSize``, ``Values``), WHERE rules, and the
  ``IfcListToExpandedArray`` function are omitted — they neither serialize nor
  affect authoring; this layer honors the WHERE-rule intent by construction.

The schema is registered at runtime via :func:`ifcopenshell.register_schema`
(needs the compiled wrapper). Registration is process-global and idempotent.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import ifcopenshell
import ifcopenshell.express
import ifcopenshell.guid

SCHEMA_NAME = "IFC4X4_TM27"
"""Identifier of the registered prototype schema (matches the built SCHEMA line
and the written FILE_SCHEMA header)."""

#: The Saikei TM27 entity delta appended to the base schema. ``Voxels`` /
#: ``ValueData`` are integer/typed LISTs carrying RLE run-pairs (see module doc).
TM27_DELTA = """
ENTITY IfcComplementaryData
 ABSTRACT SUPERTYPE OF (ONEOF
    (IfcVoxelData))
 SUBTYPE OF (IfcProduct);
END_ENTITY;

ENTITY IfcVoxelData
 ABSTRACT SUPERTYPE OF (ONEOF
    (IfcIntegerVoxelData
    ,IfcRealVoxelData
    ,IfcLabelVoxelData
    ,IfcLogicalVoxelData
    ,IfcVectorVoxelData))
 SUBTYPE OF (IfcComplementaryData);
\tValueType : OPTIONAL IfcLabel;
END_ENTITY;

ENTITY IfcIntegerVoxelData
 SUBTYPE OF (IfcVoxelData);
\tValueData : LIST [1:?] OF IfcInteger;
\tUnit : OPTIONAL IfcUnit;
END_ENTITY;

ENTITY IfcRealVoxelData
 SUBTYPE OF (IfcVoxelData);
\tValueData : LIST [1:?] OF IfcReal;
\tUnit : OPTIONAL IfcUnit;
END_ENTITY;

ENTITY IfcLabelVoxelData
 SUBTYPE OF (IfcVoxelData);
\tValueData : LIST [1:?] OF IfcLabel;
END_ENTITY;

ENTITY IfcLogicalVoxelData
 SUBTYPE OF (IfcVoxelData);
\tValueData : LIST [1:?] OF IfcLogical;
END_ENTITY;

ENTITY IfcVectorVoxelData
 SUBTYPE OF (IfcVoxelData);
\tValueData : LIST [1:?] OF IfcVector;
\tUnit : OPTIONAL IfcUnit;
END_ENTITY;

ENTITY IfcVoxelGrid
 SUBTYPE OF (IfcTessellatedItem);
\tVoxelSizeX : IfcNonNegativeLengthMeasure;
\tVoxelSizeY : IfcNonNegativeLengthMeasure;
\tVoxelSizeZ : IfcNonNegativeLengthMeasure;
\tNumberOfVoxelsX : IfcPositiveInteger;
\tNumberOfVoxelsY : IfcPositiveInteger;
\tNumberOfVoxelsZ : IfcPositiveInteger;
\tVoxels : LIST [1:?] OF IfcInteger;
END_ENTITY;
"""

_BUILT_EXP_PATH = Path(__file__).resolve().parent / "IFC4X4_TM27.exp"  # generated, gitignored
_registered = False


def _find_base_exp() -> "str | None":
    """Locate a base IFC4x3 longform ``.exp`` to merge the TM27 delta into."""
    env = os.environ.get("SAIKEI_IFC4X3_BASE_EXP")
    if env and os.path.exists(env):
        return env
    repo = Path(__file__).resolve().parents[5]  # …/src/ifcopenshell-python/ifcopenshell/api/voxel
    candidates = [
        repo.parent / "IFC4.x-development" / "reference_schemas" / "IFC4x3_RC4.exp",
        repo / "reference_schemas" / "IFC4x3_RC4.exp",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def build_merged_exp(base_exp_path: str) -> str:
    """Return the ``IFC4X4_TM27`` schema text = base ``.exp`` + the TM27 delta.

    Renames the SCHEMA header, extends the ``IfcProduct`` / ``IfcTessellatedItem``
    ``ONEOF`` supertype lists to admit the new leaves, and appends
    :data:`TM27_DELTA`. Anchors assume an ``IFC4x3_RC4``-compatible base.
    """
    src = Path(base_exp_path).read_text(encoding="utf-8")

    src, n = re.subn(r"SCHEMA\s+\w+\s*;", f"SCHEMA {SCHEMA_NAME};", src, count=1)
    if n != 1:
        raise ValueError(f"could not find a SCHEMA header in base exp {base_exp_path!r}")

    patches = [
        (
            ",IfcStructuralItem))\n SUBTYPE OF (IfcObject);",
            ",IfcStructuralItem\n    ,IfcComplementaryData))\n SUBTYPE OF (IfcObject);",
        ),
        (
            ",IfcTessellatedFaceSet))\n SUBTYPE OF (IfcGeometricRepresentationItem);",
            ",IfcTessellatedFaceSet\n    ,IfcVoxelGrid))\n SUBTYPE OF (IfcGeometricRepresentationItem);",
        ),
    ]
    for needle, replacement in patches:
        if src.count(needle) != 1:
            raise ValueError(
                f"base exp {base_exp_path!r} is not RC4-compatible: anchor not found uniquely "
                f"({needle!r}); set SAIKEI_IFC4X3_BASE_EXP to an IFC4x3_RC4 longform .exp"
            )
        src = src.replace(needle, replacement)

    head, sep, tail = src.rpartition("END_SCHEMA;")
    if not sep:
        raise ValueError(f"no END_SCHEMA in base exp {base_exp_path!r}")
    return head + TM27_DELTA + "\n" + sep + tail


def ensure_registered() -> str:
    """Build (if needed), parse, and register ``IFC4X4_TM27`` once per process.

    Idempotent: short-circuits on the wrapper's schema registry and a module
    flag. The merged ``.exp`` is written next to this module (gitignored) and
    reused across sessions; ``express.parse`` additionally caches its parse
    (``.exp.cache.dat``). Only the first build/parse is slow.

    :raises RuntimeError: if no base ``.exp`` can be found, or the compiled
        wrapper / express parser is unavailable.
    """
    global _registered
    if _registered:
        return SCHEMA_NAME
    try:
        ifcopenshell.ifcopenshell_wrapper.schema_by_name(SCHEMA_NAME)
        _registered = True
        return SCHEMA_NAME
    except Exception:
        pass  # not yet registered — build + register below

    base = _find_base_exp()
    if base is None:
        raise RuntimeError(
            f"Cannot register the {SCHEMA_NAME} prototype: no base IFC4x3 .exp found. "
            "TM27 targets the unreleased IFC 4.4, so a base longform schema is required. "
            "Set SAIKEI_IFC4X3_BASE_EXP to an IFC4x3_RC4 .exp (from buildingSMART's "
            "IFC4.x-development repo), or place one at "
            "<sibling>/IFC4.x-development/reference_schemas/IFC4x3_RC4.exp."
        )

    merged = build_merged_exp(base)
    # Rewrite the generated schema only when it changes; invalidate the stale
    # parse cache so an edited delta is picked up.
    if not _BUILT_EXP_PATH.exists() or _BUILT_EXP_PATH.read_text(encoding="utf-8") != merged:
        _BUILT_EXP_PATH.write_text(merged, encoding="utf-8")
        cache = _BUILT_EXP_PATH.with_suffix(_BUILT_EXP_PATH.suffix + ".cache.dat")
        if cache.exists():
            cache.unlink()

    try:
        schema = ifcopenshell.express.parse(str(_BUILT_EXP_PATH))
        ifcopenshell.register_schema(schema)
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            f"Failed to parse/register {SCHEMA_NAME} from {_BUILT_EXP_PATH!r}. The compiled "
            "IfcOpenShell wrapper and express parser are required (e.g. Blender's bundled "
            "ifcopenshell)."
        ) from exc

    _registered = True
    return SCHEMA_NAME


def new_file() -> ifcopenshell.file:
    """Create a bootstrapped ``IFC4X4_TM27`` sidecar file.

    Contains an ``IfcProject`` with an SI metre length unit, a ``Model``
    ``IfcGeometricRepresentationContext`` (the context voxel-grid representations
    are authored into), and an ``IfcSite`` aggregated to the project to host
    earthwork/geomodel elements.

    This is the *analysis sidecar* of the Saikei voxel pipeline: the production
    model stays IFC4X3_ADD2; voxel grids + QTO live here in IFC 4.4 and reference
    production surfaces by GlobalId (no schema mixing in one file).
    """
    ensure_registered()
    file = ifcopenshell.file(schema=SCHEMA_NAME)

    project = file.create_entity(
        "IfcProject", GlobalId=ifcopenshell.guid.new(), Name="Saikei Voxel Sidecar"
    )
    length_unit = file.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE")
    project.UnitsInContext = file.create_entity("IfcUnitAssignment", Units=[length_unit])

    get_model_context(file)

    site = file.create_entity(
        "IfcSite", GlobalId=ifcopenshell.guid.new(), Name="Saikei Voxel Site"
    )
    file.create_entity(
        "IfcRelAggregates",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=project,
        RelatedObjects=[site],
    )
    return file


def get_model_context(file: ifcopenshell.file) -> ifcopenshell.entity_instance:
    """Return the ``Model`` ``IfcGeometricRepresentationContext``, creating it
    if absent.

    Voxel-grid representations are authored as ``IfcShapeRepresentation`` with
    ``RepresentationIdentifier="Body"`` / ``RepresentationType="Tessellation"``
    (``IfcVoxelGrid`` is a tessellated item); a single ``Model`` context as
    ``ContextOfItems`` is sufficient (and avoids subcontext derived-attribute
    handling on the runtime-registered prototype schema).
    """
    for ctx in file.by_type("IfcGeometricRepresentationContext"):
        if ctx.is_a() == "IfcGeometricRepresentationContext" and ctx.ContextType == "Model":
            return ctx
    origin = file.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0))
    axis = file.create_entity("IfcAxis2Placement3D", Location=origin)
    return file.create_entity(
        "IfcGeometricRepresentationContext",
        ContextType="Model",
        CoordinateSpaceDimension=3,
        Precision=1e-5,
        WorldCoordinateSystem=axis,
    )

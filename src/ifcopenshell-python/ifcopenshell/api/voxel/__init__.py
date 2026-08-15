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

"""High-level API for authoring TM27 voxel IFC entities into a 4.4 sidecar.

Phase 5 of the Saikei grading/earthwork sprint (voxel pivot). This API persists
run-length-encoded occupancy voxels and per-cell semantic layers as the IFC 4.4
TM27 entities ``IfcVoxelGrid`` + ``IfcVoxelData``. It mirrors the shape of
``ifcopenshell.api.surface`` / ``ifcopenshell.api.earthwork``: file-per-function,
no Blender / ``bpy``, persists what it's given (RLE encoding is the caller's job;
see :meth:`bonsai.tool.Voxel.encode_occupancy`).

Schema
======

TM27 is not in any released schema, so this API registers a prototype schema at
runtime — ``IFC4X4_TM27`` (IFC4x3_RC4 + the TM27 delta; see :mod:`._schema`).
``IfcVoxelGrid.Voxels`` is ``LIST OF IfcInteger`` carrying RLE run-pairs (the
dense boolean mask is un-authorable through IfcOpenShell; Phase-0 finding).

Source-of-truth stance
======================

The voxel grid is a **derived/analysis** representation. The production model
stays IFC4X3_ADD2 (TIN / ``IfcSectionedSolidHorizontal`` are the parametric
source of truth); voxel grids live in a separate **IFC 4.4 sidecar** and point
back to production surfaces by GlobalId (``SaikeiCivil_VoxelSource``). No schema
mixing within a file.

Entity tree authored
====================

::

    IfcProject (SI metre unit; Model context)
      └─ IfcSite
          └─ IfcEarthworksCut / IfcEarthworksFill        (the volume host)
               ├─ Representation → IfcShapeRepresentation ('Body','Tessellation')
               │                     └─ Items[1] = IfcVoxelGrid (RLE occupancy)
               ├─ Description = "voxelized-from:<guid>" (optional cross-file link)
               └─ HasAssignments ← IfcRelAssignsToProduct
                                       └─ IfcVoxelData subtype(s)  (semantic layers,
                                          same grid representation)

Currently supported
===================

1. :func:`ensure_registered` / :func:`new_file` — register the prototype schema;
   bootstrap a sidecar (project + unit + context + site).
2. :func:`add_voxel_grid_representation` — attach an ``IfcVoxelGrid`` Body rep.
3. :func:`add_voxel_data` — author one ``IfcVoxelData`` semantic layer.
4. :func:`create_voxel_earthwork` — top-level host + grid (+ optional source link).
5. :func:`write_earthwork_quantities` — voxel-computed cut/fill volumes →
   ``Qto_Earthworks{Cut,Fill}BaseQuantities`` (delegates to
   ``ifcopenshell.api.earthwork``; direct-attr quantities are safe here).

This API is under development and subject to code-breaking changes. ``IFC4X4_TM27``
is a prototype pinned to TM27 (PR #1110) under public review.
"""

from ._schema import SCHEMA_NAME, ensure_registered, get_model_context, new_file
from .add_voxel_data import VOXEL_DATA_SUBTYPES, add_voxel_data
from .add_voxel_grid import add_voxel_grid_representation
from .create_voxel_earthwork import SOURCE_PREFIX, create_voxel_earthwork
from .create_voxel_geomodel import create_voxel_geomodel
from .write_quantities import write_earthwork_quantities

__all__ = [
    "SCHEMA_NAME",
    "SOURCE_PREFIX",
    "VOXEL_DATA_SUBTYPES",
    "add_voxel_data",
    "add_voxel_grid_representation",
    "create_voxel_earthwork",
    "create_voxel_geomodel",
    "ensure_registered",
    "get_model_context",
    "new_file",
    "write_earthwork_quantities",
]

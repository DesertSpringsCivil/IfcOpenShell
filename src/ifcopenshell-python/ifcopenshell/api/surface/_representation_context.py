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

"""Internal: resolve or create the geometric representation subcontexts the
surface API authors into.

Surfaces use three subcontexts under the project's "Model" context:

- ``Body`` (MODEL_VIEW) — identifier for the IfcTriangulatedIrregularNetwork
  TIN geometry. Standard IFC convention: 3D body representations live in
  the ``Body`` subcontext with ``RepresentationIdentifier='Body'``; the
  ``RepresentationType`` distinguishes the geometric kind (``Tessellation``
  for TINs).
- ``Box`` (MODEL_VIEW) — identifier for the bounding-box LOD representation.
- ``Annotation`` (MODEL_VIEW) — identifier for 3D annotations such as breakline
  polylines.

The lookup mirrors the ``ifcopenshell.api.alignment.get_axis_subcontext``
pattern: find an existing subcontext via ``ifcopenshell.util.representation``
or call ``ifcopenshell.api.context.add_context`` to create one. The parent
"Model" context is auto-created if missing.
"""

from __future__ import annotations

import ifcopenshell
import ifcopenshell.api.context
import ifcopenshell.util.representation


def _get_or_create_model_context(file: ifcopenshell.file) -> ifcopenshell.entity_instance:
    """Return the project's 3D "Model" IfcGeometricRepresentationContext, creating it if absent."""
    model_context = ifcopenshell.util.representation.get_context(file, "Model")
    if model_context is None:
        model_context = ifcopenshell.api.context.add_context(file, context_type="Model")
    return model_context


def _get_or_create_subcontext(
    file: ifcopenshell.file,
    context_identifier: str,
    target_view: str = "MODEL_VIEW",
) -> ifcopenshell.entity_instance:
    """Return the named Model subcontext, creating both it and the parent Model context if absent."""
    subcontext = ifcopenshell.util.representation.get_context(file, "Model", context_identifier, target_view)
    if subcontext is not None:
        return subcontext
    parent = _get_or_create_model_context(file)
    return ifcopenshell.api.context.add_context(
        file,
        context_type="Model",
        context_identifier=context_identifier,
        target_view=target_view,
        parent=parent,
    )


def get_body_subcontext(file: ifcopenshell.file) -> ifcopenshell.entity_instance:
    """Return the Model/Body/MODEL_VIEW subcontext, creating it if absent.

    The TIN body representation lives here with
    ``RepresentationIdentifier='Body'`` and
    ``RepresentationType='Tessellation'`` per IFC 4.3 convention.
    """
    return _get_or_create_subcontext(file, "Body", "MODEL_VIEW")


def get_box_subcontext(file: ifcopenshell.file) -> ifcopenshell.entity_instance:
    """Return the Model/Box/MODEL_VIEW subcontext, creating it if absent."""
    return _get_or_create_subcontext(file, "Box", "MODEL_VIEW")


def get_annotation_subcontext(file: ifcopenshell.file) -> ifcopenshell.entity_instance:
    """Return the Model/Annotation/MODEL_VIEW subcontext, creating it if absent.

    Used by 3D annotations such as breakline polylines that must persist in the
    spatial model (not the 2D plan) so they coexist with TIN representations.
    """
    return _get_or_create_subcontext(file, "Annotation", "MODEL_VIEW")

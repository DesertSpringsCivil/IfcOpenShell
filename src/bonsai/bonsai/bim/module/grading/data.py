# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2026 Michael Yoder <myoder@desertspringscivil.com>
#
# This file is part of Bonsai.
#
# Bonsai is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Bonsai is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Bonsai.  If not, see <http://www.gnu.org/licenses/>.

"""Data caching for the Saikei grading module's UI panel.

Mirrors :mod:`bonsai.bim.module.surface.data`. The panel reads from
:class:`GradingData.data` rather than re-querying IFC every redraw.
Bonsai's :func:`bonsai.bim.handler.refresh_ui_data` calls
:func:`refresh` (auto-discovered via the ``modules`` dict) on every
IFC mutation, which marks ``GradingData.is_loaded = False`` so the
next panel ``draw()`` calls :meth:`load`.
"""

import bpy

import bonsai.tool as tool
import bonsai.tool.grading as tool_grading


class GradingData:
    """Cached grading data for the panel."""

    data: dict = {}
    is_loaded: bool = False

    @classmethod
    def load(cls) -> None:
        """Refresh :attr:`data` from the active IFC file. Also re-syncs
        ``CivilGradingProperties.groups`` (from IFC),
        ``.feature_lines`` (from IFC), and ``.criteria`` (from the
        in-memory registry) so the panel shows entities authored in
        previous sessions.

        Limitations: criteria sync only sees criteria already
        registered with :class:`tool.Grading` — disk-loaded criteria
        whose dataclasses haven't been rehydrated yet won't appear
        until they're touched by an operator. Full IFC-side criteria
        rehydration (walking each group's ``SaikeiCivil_GradingCriteria``
        bindings) is Phase 5.1.
        """
        cls.data = {
            "group_count": 0,
            "criteria_count": 0,
            "feature_line_count": 0,
        }

        ifc_file = tool.Ifc.get()
        if ifc_file is None:
            cls.is_loaded = True
            return

        groups = [
            g
            for g in ifc_file.by_type("IfcGroup")
            if getattr(g, "ObjectType", None) == "GradingGroup"
        ]
        cls.data["group_count"] = len(groups)

        feature_line_alignments = [
            a
            for a in ifc_file.by_type("IfcAlignment")
            if tool.Grading.is_feature_line_alignment(a)
        ]
        cls.data["feature_line_count"] = len(feature_line_alignments)

        templates = ifc_file.by_type("IfcPropertySetTemplate")
        # Phase 2 authors a singleton-by-shape template — but the IFC
        # file may have other unrelated IfcPropertySetTemplate
        # entities (e.g., from upstream BIM authoring tools). Filter
        # by Name to count only Saikei criteria templates.
        criteria_templates = [
            t for t in templates if t.Name == "SaikeiCivil_GradingCriteria"
        ]
        cls.data["criteria_count"] = len(criteria_templates)

        # NOTE: the UIList sync (which writes CivilGradingProperties) is
        # deliberately NOT done here. load() runs during panel draw(), and
        # Blender forbids writing ID data (scene properties) from draw. The
        # lists are synced in sync_uilists(), invoked from refresh() — which
        # runs on IFC mutations / file load, outside draw.
        cls.is_loaded = True

    @classmethod
    def sync_uilists(cls) -> None:
        """Reconcile the grading UILists with the current IFC + registry.

        Writes ``CivilGradingProperties``, so it MUST run outside panel
        ``draw()``. Called from :func:`refresh` (Bonsai's post-mutation /
        file-load UI hook), never from :meth:`load`.
        """
        ifc_file = tool.Ifc.get()
        if ifc_file is None:
            return
        groups = [
            g for g in ifc_file.by_type("IfcGroup") if getattr(g, "ObjectType", None) == "GradingGroup"
        ]
        feature_line_alignments = [
            a for a in ifc_file.by_type("IfcAlignment") if tool.Grading.is_feature_line_alignment(a)
        ]
        cls._sync_groups_uilist_from_ifc(groups)
        cls._sync_feature_lines_uilist_from_ifc(feature_line_alignments)
        cls._sync_criteria_uilist_from_registry(ifc_file)

    @staticmethod
    def _sync_groups_uilist_from_ifc(groups: list) -> None:
        """Reconcile ``CivilGradingProperties.groups`` with the IFC
        entity set on every refresh."""
        scene = bpy.context.scene if bpy.context else None
        if scene is None or not hasattr(scene, "CivilGradingProperties"):
            return
        props = scene.CivilGradingProperties

        previous_guid = props.active_group_guid

        props.groups.clear()
        for entity in groups:
            try:
                group_dataclass = tool.Grading.get_group(
                    tool.Ifc.get(), entity.GlobalId
                )
            except Exception:
                # Rehydration failed (corrupt IFC, missing pset, etc.);
                # skip silently rather than crashing the panel.
                continue
            item = props.groups.add()
            item.name = group_dataclass.name
            item.guid = group_dataclass.guid
            item.ifc_id = entity.id()
            item.target_surface_guid = group_dataclass.target_surface_guid or ""
            item.interior_fill = group_dataclass.interior_fill

        # Restore active selection if its GUID is still in the list.
        target_index = 0
        for index, item in enumerate(props.groups):
            if item.guid == previous_guid:
                target_index = index
                break
        props.active_group_index = target_index
        if 0 <= target_index < len(props.groups):
            current = props.groups[target_index]
            props.active_group_id = current.ifc_id
            props.active_group_guid = current.guid
        else:
            props.active_group_id = 0
            props.active_group_guid = ""

    @staticmethod
    def _sync_feature_lines_uilist_from_ifc(alignments: list) -> None:
        """Reconcile ``CivilGradingProperties.feature_lines`` with the
        IfcAlignment[FeatureLine] entity set on every refresh.

        Backs the picker that pre-populates the ``feature_line_guid``
        parameter of the drape and edit-elevations operators."""
        scene = bpy.context.scene if bpy.context else None
        if scene is None or not hasattr(scene, "CivilGradingProperties"):
            return
        props = scene.CivilGradingProperties

        previous_guid = props.active_feature_line_guid

        props.feature_lines.clear()
        for alignment in alignments:
            try:
                feature_line = tool.Grading.get_feature_line(
                    tool.Ifc.get(), alignment.GlobalId
                )
            except Exception:
                continue
            item = props.feature_lines.add()
            item.name = feature_line.name
            item.guid = feature_line.guid
            item.ifc_id = alignment.id()
            item.closed = feature_line.closed
            item.vertex_count = len(feature_line.vertices)

        target_index = 0
        for index, item in enumerate(props.feature_lines):
            if item.guid == previous_guid:
                target_index = index
                break
        props.active_feature_line_index = target_index
        if 0 <= target_index < len(props.feature_lines):
            props.active_feature_line_guid = (
                props.feature_lines[target_index].guid
            )
        else:
            props.active_feature_line_guid = ""

    @staticmethod
    def _sync_criteria_uilist_from_registry(ifc_file) -> None:
        """Reconcile ``CivilGradingProperties.criteria`` with the
        :class:`GradingCriteria` entries in :attr:`tool.Grading._registry`
        for ``ifc_file``.

        Criteria are persisted as a singleton-by-shape
        :class:`IfcPropertySetTemplate` plus per-group bindings, so
        there is no canonical "list of criteria entities" to walk in
        IFC. The registry is the authoritative in-session list.
        Phase 5.1 will replace this with a walk of each group's
        ``SaikeiCivil_GradingCriteria`` bindings.
        """
        scene = bpy.context.scene if bpy.context else None
        if scene is None or not hasattr(scene, "CivilGradingProperties"):
            return
        props = scene.CivilGradingProperties

        previous_guid = props.active_criteria_guid

        criteria_entries = list(
            tool.Grading.iter_registered(ifc_file, tool_grading.GradingCriteria)
        )

        props.criteria.clear()
        for criteria in criteria_entries:
            item = props.criteria.add()
            item.name = criteria.name
            item.guid = criteria.guid
            item.target_kind = criteria.target_kind
            item.cut_slope = float(criteria.cut_slope)
            item.fill_slope = float(criteria.fill_slope)

        target_index = 0
        for index, item in enumerate(props.criteria):
            if item.guid == previous_guid:
                target_index = index
                break
        props.active_criteria_index = target_index
        if 0 <= target_index < len(props.criteria):
            props.active_criteria_guid = props.criteria[target_index].guid
        else:
            props.active_criteria_guid = ""


def refresh() -> None:
    """Mark :class:`GradingData` as needing reload on next access.
    Called by Bonsai's UI refresh hook after IFC mutations.

    NOTE: the UIList sync (:meth:`GradingData.sync_uilists`) is NOT done here.
    It writes scene properties and would clobber the operators' own in-session
    list management on every mutation. The lists are populated by the grading
    operators during a session and re-synced from IFC once on file load via
    the module's load_post handler.
    """
    GradingData.is_loaded = False

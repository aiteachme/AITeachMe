"""Docs domain wrapper for curriculum services."""

from app.services.knowledge.curriculum_service import (
    get_current_curriculum_snapshot,
    get_current_prereq_dag,
    get_current_theme_tree,
    get_teaching_unit_detail,
    get_teaching_units,
    manage_taxonomy_anchors,
)

__all__ = [
    "get_current_curriculum_snapshot",
    "get_current_prereq_dag",
    "get_current_theme_tree",
    "get_teaching_unit_detail",
    "get_teaching_units",
    "manage_taxonomy_anchors",
]

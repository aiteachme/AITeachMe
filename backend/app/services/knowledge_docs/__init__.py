"""Knowledge docs domain service entrypoints.

This package is the canonical docs-side service namespace. Legacy modules under
``app.services.knowledge`` are kept for compatibility during migration.
"""

from app.services.knowledge_docs.build_planner_service import (
    append_build_planner_message_service,
    confirm_build_planner_session_service,
    create_build_planner_session_service,
    get_confirmed_build_plan_service,
    get_latest_planner_session_service,
    mark_confirmed_build_plan_status,
)
from app.services.knowledge_docs.cleanup_service import clear_subject_knowledge
from app.services.knowledge_docs.curriculum_service import (
    get_teaching_unit_detail,
    manage_taxonomy_anchors,
)
from app.services.knowledge_docs.digest_service import (
    get_docgen_result,
    run_docgen_background,
    run_unified_build_background,
    trigger_docgen_build,
)
from app.services.knowledge_docs.overview_service import get_knowledge_overview
from app.services.knowledge_docs.study_plan_service import handle_study_plan_request

__all__ = [
    "append_build_planner_message_service",
    "clear_subject_knowledge",
    "confirm_build_planner_session_service",
    "create_build_planner_session_service",
    "get_docgen_result",
    "get_confirmed_build_plan_service",
    "get_knowledge_overview",
    "get_latest_planner_session_service",
    "get_teaching_unit_detail",
    "handle_study_plan_request",
    "mark_confirmed_build_plan_status",
    "manage_taxonomy_anchors",
    "run_docgen_background",
    "run_unified_build_background",
    "trigger_docgen_build",
]

"""Digest build lifecycle commands shared by docgen and graph lanes.

This module owns cross-lane build actions that API routes trigger, such as
cancelling active DocGen and KG-sync tasks. It does not build HTTP responses or
format SSE payloads.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session

from app.models.course import Course
from app.schemas.knowledge import DocGenBuildCancelData
from app.shared.infra.knowledge.build_store import (
    build_aggregate_knowledge_build_status,
    read_knowledge_build_runtime,
    release_knowledge_build_lock,
    update_knowledge_build_lane_status,
)
from app.shared.infra.storage import build_course_storage_scope
from app.utils.time import utcnow
from app.workflows.digest.planner import mark_confirmed_build_plan_status

ACTIVE_KNOWLEDGE_BUILD_STATUSES = {"accepted", "running", "publishing"}


def _is_active_build_status(status: str | None) -> bool:
    return str(status or "").strip() in ACTIVE_KNOWLEDGE_BUILD_STATUSES


async def cancel_knowledge_build(
    session: Session,
    *,
    course: Course,
    user_id: str,
    background_task_registry: Any | None = None,
) -> DocGenBuildCancelData:
    """Cancel active knowledge document and graph build work for one course."""

    course_scope = build_course_storage_scope(user_id=course.user_id, course_id=course.id)
    runtime = read_knowledge_build_runtime(course.id, course_scope=course_scope)
    aggregate_status = build_aggregate_knowledge_build_status(runtime)
    docgen_status = runtime.docgen_runtime if runtime is not None else None
    graph_status = runtime.graph_runtime if runtime is not None else None

    cancelled_task_count = 0
    if background_task_registry is not None:
        cancelled_task_count += await background_task_registry.cancel_matching(
            kind="knowledge.build.docs",
            course_id=course.id,
        )
        cancelled_task_count += await background_task_registry.cancel_matching(
            kind="knowledge.build.graph",
            course_id=course.id,
        )

    requested_at = aggregate_status.requested_at if aggregate_status is not None else utcnow()
    confirmed_plan_id = docgen_status.confirmed_plan_id if docgen_status is not None else None
    if confirmed_plan_id:
        mark_confirmed_build_plan_status(
            session,
            course_id=course.id,
            user_id=user_id,
            plan_id=confirmed_plan_id,
            status="cancelled",
        )

    if docgen_status is not None and _is_active_build_status(docgen_status.status):
        update_knowledge_build_lane_status(
            course.id,
            lane="docgen",
            course_scope=course_scope,
            requested_at=requested_at,
            build_group_id=docgen_status.build_group_id,
            status="cancelled",
            stage="cancelled",
            error_message="build_cancelled",
            draft_available=False,
            planner_session_id=docgen_status.planner_session_id,
            confirmed_plan_id=confirmed_plan_id,
            digest_mode=docgen_status.digest_mode,
            current_stage_description="本轮知识构建已被用户终止。",
        )

    if graph_status is not None and _is_active_build_status(graph_status.status):
        update_knowledge_build_lane_status(
            course.id,
            lane="graph",
            course_scope=course_scope,
            requested_at=requested_at,
            build_group_id=graph_status.build_group_id,
            status="cancelled",
            stage="cancelled",
            error_message="build_cancelled",
            current_stage_description="本轮图谱构建已被用户终止。",
        )

    release_knowledge_build_lock(course.id)
    return DocGenBuildCancelData(
        course_id=course.id,
        cancelled_task_count=cancelled_task_count,
        requested_at=requested_at,
    )


__all__ = [
    "ACTIVE_KNOWLEDGE_BUILD_STATUSES",
    "cancel_knowledge_build",
]

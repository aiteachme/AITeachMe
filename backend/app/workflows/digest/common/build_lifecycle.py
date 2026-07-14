"""Digest build lifecycle commands shared by docgen and graph lanes.

This module owns cross-lane build actions that API routes trigger, such as
cancelling active DocGen and KG-sync tasks. It does not build HTTP responses or
format SSE payloads.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from threading import Event, Thread
from time import monotonic
from typing import Any

import structlog
from sqlmodel import Session

from app.models.course import Course
from app.schemas.knowledge import DocGenBuildCancelData
from app.shared.infra.knowledge.build_store import (
    STALE_BUILD_LOCK_TTL,
    KnowledgeBuildRuntimeEnvelope,
    build_aggregate_knowledge_build_status,
    read_knowledge_build_lock,
    read_knowledge_build_runtime,
    renew_knowledge_build_lock,
    request_knowledge_build_cancellation,
    update_knowledge_build_lane_status,
)
from app.shared.infra.storage import CourseStorageScope, build_course_storage_scope
from app.utils.time import utcnow
from app.workflows.digest.planner import mark_confirmed_build_plan_status

ACTIVE_KNOWLEDGE_BUILD_STATUSES = {"accepted", "running", "publishing"}
BUILD_LOCK_RENEW_INTERVAL_SECONDS = min(
    60.0,
    max(30.0, STALE_BUILD_LOCK_TTL.total_seconds() / 3),
)
BUILD_LOCK_RENEW_RETRY_SECONDS = 30.0
BUILD_LOCK_RENEW_SAFETY_MARGIN_SECONDS = max(
    BUILD_LOCK_RENEW_RETRY_SECONDS,
    STALE_BUILD_LOCK_TTL.total_seconds() / 3,
)
BUILD_LOCK_RENEW_DEADLINE_SECONDS = max(
    BUILD_LOCK_RENEW_RETRY_SECONDS,
    STALE_BUILD_LOCK_TTL.total_seconds() - BUILD_LOCK_RENEW_SAFETY_MARGIN_SECONDS,
)

logger = structlog.get_logger(__name__)


class SynchronousKnowledgeBuildLeaseGuard:
    """Keep a lease alive for synchronous maintenance work."""

    def __init__(
        self,
        *,
        course_id: str,
        build_group_id: str,
        course_scope: CourseStorageScope,
    ) -> None:
        self._course_id = course_id
        self._build_group_id = build_group_id
        self._course_scope = course_scope
        self._stop = Event()
        self._lost = Event()
        self._thread = Thread(
            target=self._run,
            name=f"knowledge-build-lease-{course_id}",
            daemon=True,
        )

    @property
    def lost(self) -> bool:
        return self._lost.is_set()

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        self._thread.join()

    def _run(self) -> None:
        last_confirmed_at = monotonic()
        next_delay = 0.0
        while not self._stop.wait(next_delay):
            try:
                renewed = renew_knowledge_build_lock(
                    self._course_id,
                    build_group_id=self._build_group_id,
                    course_scope=self._course_scope,
                )
            except Exception as exc:
                unconfirmed_seconds = monotonic() - last_confirmed_at
                logger.warning(
                    "knowledge_build_sync_lock_renew_failed",
                    course_id=self._course_id,
                    build_group_id=self._build_group_id,
                    error=str(exc),
                    unconfirmed_seconds=round(unconfirmed_seconds, 3),
                )
                if unconfirmed_seconds >= BUILD_LOCK_RENEW_DEADLINE_SECONDS:
                    logger.error(
                        "knowledge_build_sync_lock_renew_deadline_exceeded",
                        course_id=self._course_id,
                        build_group_id=self._build_group_id,
                        unconfirmed_seconds=round(unconfirmed_seconds, 3),
                    )
                    self._lost.set()
                    return
                next_delay = min(
                    BUILD_LOCK_RENEW_RETRY_SECONDS,
                    max(
                        0.1,
                        BUILD_LOCK_RENEW_DEADLINE_SECONDS - unconfirmed_seconds,
                    ),
                )
                continue

            if not renewed:
                logger.error(
                    "knowledge_build_sync_lock_ownership_lost",
                    course_id=self._course_id,
                    build_group_id=self._build_group_id,
                )
                self._lost.set()
                return

            last_confirmed_at = monotonic()
            next_delay = BUILD_LOCK_RENEW_INTERVAL_SECONDS


@contextmanager
def maintain_synchronous_knowledge_build_lock_lease(
    *,
    course_id: str,
    build_group_id: str,
    course_scope: CourseStorageScope,
) -> Iterator[SynchronousKnowledgeBuildLeaseGuard]:
    """Renew a lease until synchronous maintenance leaves the context."""

    guard = SynchronousKnowledgeBuildLeaseGuard(
        course_id=course_id,
        build_group_id=build_group_id,
        course_scope=course_scope,
    )
    guard.start()
    try:
        yield guard
    finally:
        guard.close()


def _is_active_build_status(status: str | None) -> bool:
    return str(status or "").strip() in ACTIVE_KNOWLEDGE_BUILD_STATUSES


def mark_knowledge_build_runtime_cancelled(
    course_id: str,
    *,
    build_group_id: str,
    course_scope: CourseStorageScope,
    runtime: KnowledgeBuildRuntimeEnvelope | None = None,
) -> None:
    """Mark only active runtime lanes that belong to the cancelled lock owner."""

    owner = str(build_group_id or "").strip()
    if not owner:
        return
    resolved_runtime = runtime or read_knowledge_build_runtime(
        course_id,
        course_scope=course_scope,
    )
    if resolved_runtime is None:
        return

    docgen_status = resolved_runtime.docgen_runtime
    if (
        docgen_status is not None
        and docgen_status.build_group_id == owner
        and _is_active_build_status(docgen_status.status)
    ):
        update_knowledge_build_lane_status(
            course_id,
            lane="docgen",
            course_scope=course_scope,
            requested_at=docgen_status.requested_at,
            build_group_id=owner,
            status="cancelled",
            stage="cancelled",
            error_message="build_cancelled",
            draft_available=False,
            planner_session_id=docgen_status.planner_session_id,
            confirmed_plan_id=docgen_status.confirmed_plan_id,
            digest_mode=docgen_status.digest_mode,
            current_stage_description="本轮知识构建已被用户终止。",
        )

    graph_status = resolved_runtime.graph_runtime
    if (
        graph_status is not None
        and graph_status.build_group_id == owner
        and _is_active_build_status(graph_status.status)
    ):
        update_knowledge_build_lane_status(
            course_id,
            lane="graph",
            course_scope=course_scope,
            requested_at=graph_status.requested_at,
            build_group_id=owner,
            status="cancelled",
            stage="cancelled",
            error_message="build_cancelled",
            current_stage_description="本轮图谱构建已被用户终止。",
        )


async def maintain_knowledge_build_lock_lease(
    *,
    course_id: str,
    build_group_id: str,
    course_scope: CourseStorageScope,
    owner_task: asyncio.Task[Any],
) -> None:
    """Renew one owner lease and stop its task after cancellation or lock loss."""

    last_confirmed_at = monotonic()
    next_delay = 0.0
    while True:
        if next_delay > 0:
            await asyncio.sleep(next_delay)
        try:
            renewed = await asyncio.to_thread(
                renew_knowledge_build_lock,
                course_id,
                build_group_id=build_group_id,
                course_scope=course_scope,
            )
        except Exception as exc:
            unconfirmed_seconds = monotonic() - last_confirmed_at
            logger.warning(
                "knowledge_build_lock_renew_failed",
                course_id=course_id,
                build_group_id=build_group_id,
                error=str(exc),
                unconfirmed_seconds=round(unconfirmed_seconds, 3),
            )
            if unconfirmed_seconds >= BUILD_LOCK_RENEW_DEADLINE_SECONDS:
                logger.error(
                    "knowledge_build_lock_renew_deadline_exceeded",
                    course_id=course_id,
                    build_group_id=build_group_id,
                    unconfirmed_seconds=round(unconfirmed_seconds, 3),
                )
                owner_task.cancel()
                return
            next_delay = min(
                BUILD_LOCK_RENEW_RETRY_SECONDS,
                max(
                    0.1,
                    BUILD_LOCK_RENEW_DEADLINE_SECONDS - unconfirmed_seconds,
                ),
            )
            continue
        if renewed:
            last_confirmed_at = monotonic()
            next_delay = BUILD_LOCK_RENEW_INTERVAL_SECONDS
            continue

        try:
            lock = await asyncio.to_thread(
                read_knowledge_build_lock,
                course_id,
                course_scope=course_scope,
            )
        except Exception as exc:
            logger.warning(
                "knowledge_build_lock_read_after_renew_rejected_failed",
                course_id=course_id,
                build_group_id=build_group_id,
                error=str(exc),
            )
            lock = None

        if (
            lock is not None
            and lock.build_group_id == build_group_id
            and lock.cancel_requested_at is not None
        ):
            try:
                await asyncio.to_thread(
                    mark_knowledge_build_runtime_cancelled,
                    course_id,
                    build_group_id=build_group_id,
                    course_scope=course_scope,
                )
            except Exception as exc:
                logger.warning(
                    "knowledge_build_cancelled_runtime_write_failed",
                    course_id=course_id,
                    build_group_id=build_group_id,
                    error=str(exc),
                )
            logger.info(
                "knowledge_build_lock_cancellation_observed",
                course_id=course_id,
                build_group_id=build_group_id,
            )
        else:
            logger.error(
                "knowledge_build_lock_ownership_lost",
                course_id=course_id,
                build_group_id=build_group_id,
            )
        owner_task.cancel()
        return


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

    requested_at = aggregate_status.requested_at if aggregate_status is not None else utcnow()
    lock = read_knowledge_build_lock(course.id, course_scope=course_scope)
    lock_owner = str(lock.build_group_id or "").strip() if lock is not None else ""
    if lock_owner.startswith("knowledge-clear:"):
        logger.info(
            "knowledge_build_cancel_ignored_for_maintenance_lock",
            course_id=course.id,
            build_group_id=lock_owner,
        )
        return DocGenBuildCancelData(
            course_id=course.id,
            cancelled_task_count=0,
            requested_at=requested_at,
        )
    cancellation_requested = bool(
        lock_owner
        and request_knowledge_build_cancellation(
            course.id,
            build_group_id=lock_owner,
            course_scope=course_scope,
        )
    )
    if not cancellation_requested:
        return DocGenBuildCancelData(
            course_id=course.id,
            cancelled_task_count=0,
            requested_at=requested_at,
        )

    mark_knowledge_build_runtime_cancelled(
        course.id,
        build_group_id=lock_owner,
        course_scope=course_scope,
        runtime=runtime,
    )

    confirmed_plan_id = (
        docgen_status.confirmed_plan_id
        if docgen_status is not None
        and docgen_status.build_group_id == lock_owner
        and _is_active_build_status(docgen_status.status)
        else None
    )
    if confirmed_plan_id is not None:
        mark_confirmed_build_plan_status(
            session,
            course_id=course.id,
            user_id=user_id,
            plan_id=confirmed_plan_id,
            status="cancelled",
        )

    cancelled_task_count = 0
    if background_task_registry is not None:
        cancelled_counts = await asyncio.gather(
            background_task_registry.cancel_matching(
                kind="knowledge.build.docs",
                course_id=course.id,
            ),
            background_task_registry.cancel_matching(
                kind="knowledge.build.graph",
                course_id=course.id,
            ),
        )
        cancelled_task_count = sum(int(count or 0) for count in cancelled_counts)
    return DocGenBuildCancelData(
        course_id=course.id,
        cancelled_task_count=cancelled_task_count,
        requested_at=requested_at,
    )


__all__ = [
    "ACTIVE_KNOWLEDGE_BUILD_STATUSES",
    "BUILD_LOCK_RENEW_DEADLINE_SECONDS",
    "BUILD_LOCK_RENEW_INTERVAL_SECONDS",
    "cancel_knowledge_build",
    "maintain_knowledge_build_lock_lease",
    "maintain_synchronous_knowledge_build_lock_lease",
    "mark_knowledge_build_runtime_cancelled",
]

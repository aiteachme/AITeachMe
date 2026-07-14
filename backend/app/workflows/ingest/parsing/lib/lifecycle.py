"""Post-graph lifecycle helpers for ingest fast-parse runs.

这里承接 graph 外的副作用收口：
- runtime 级失败时兜底更新 RawFile 状态
- Phase 1 成功后按需派发 Phase 2 增强任务

graph.py 只负责图定义和单次运行入口，不直接处理这些副作用。
"""

from __future__ import annotations

import asyncio

import sqlalchemy as sa
import structlog

from app.shared.infra.database import managed_session
from app.models import IngestStatus, RawFile, TaskStatus
from app.repositories.files_repo import get_raw_file_by_id, update_raw_file
from app.utils.time import utcnow
from app.workflows.ingest.parsing.lib.runtime_helpers import _background_tasks
from app.workflows.ingest.parsing.state import IngestParseState

logger = structlog.get_logger(__name__)


def mark_parse_workflow_failed(
    *,
    user_id: str,
    file_id: str,
    error: str,
    step: str = "ingest.unhandled_error",
    course_id: str = "",
) -> None:
    """Best-effort failure fallback for runtime-level parse crashes."""

    try:
        with managed_session() as session:
            raw_file = get_raw_file_by_id(session, file_id)
            if raw_file is None or raw_file.user_id != user_id:
                return
            update_raw_file(
                session,
                raw_file,
                status=TaskStatus.FAILED.value,
                ingest_status=IngestStatus.FAILED.value,
                parse_error_message=error,
                digest_current_step=step,
            )
    except Exception:
        logger.exception("ingest_parse_failed_status_update_error", course_id=course_id, user_id=user_id, file_id=file_id)


def _claim_enhancement_dispatch(
    *,
    user_id: str,
    file_id: str,
    current_step: str,
) -> bool:
    """Atomically claim Phase 2 before a worker is spawned."""

    try:
        with managed_session() as session:
            result = session.exec(
                sa.update(RawFile)
                .where(
                    RawFile.id == file_id,
                    RawFile.user_id == user_id,
                    RawFile.status == TaskStatus.COMPLETED.value,
                    RawFile.ingest_status == IngestStatus.FAST_PARSED.value,
                )
                .values(
                    ingest_status=IngestStatus.ENHANCING.value,
                    current_step=current_step,
                    error_message=None,
                    updated_at=utcnow(),
                )
                .execution_options(synchronize_session=False)
            )
            return int(getattr(result, "rowcount", 0) or 0) == 1
    except Exception:
        logger.exception(
            "ingest_enhance_dispatch_claim_failed",
            user_id=user_id,
            file_id=file_id,
        )
        return False


def _requeue_enhancement_dispatch(
    *,
    user_id: str,
    file_id: str,
    claimed_step: str,
    reason: str = "enhance_dispatch_failed",
) -> None:
    """Undo a claim only when no worker could be admitted."""

    try:
        with managed_session() as session:
            session.exec(
                sa.update(RawFile)
                .where(
                    RawFile.id == file_id,
                    RawFile.user_id == user_id,
                    RawFile.status == TaskStatus.COMPLETED.value,
                    RawFile.ingest_status == IngestStatus.ENHANCING.value,
                    RawFile.current_step == claimed_step,
                )
                .values(
                    ingest_status=IngestStatus.FAST_PARSED.value,
                    current_step="ingest.enhance.retry_pending",
                    error_message=reason,
                    updated_at=utcnow(),
                )
                .execution_options(synchronize_session=False)
            )
    except Exception:
        logger.exception(
            "ingest_enhance_dispatch_requeue_failed",
            user_id=user_id,
            file_id=file_id,
        )


def _mark_enhancement_running(
    *,
    user_id: str,
    file_id: str,
    claimed_step: str,
) -> bool:
    """Fence queued cancellation cleanup before Phase 2 starts."""

    try:
        with managed_session() as session:
            result = session.exec(
                sa.update(RawFile)
                .where(
                    RawFile.id == file_id,
                    RawFile.user_id == user_id,
                    RawFile.status == TaskStatus.COMPLETED.value,
                    RawFile.ingest_status == IngestStatus.ENHANCING.value,
                    RawFile.current_step == claimed_step,
                )
                .values(
                    current_step="ingest.enhance.running",
                    updated_at=utcnow(),
                )
                .execution_options(synchronize_session=False)
            )
            return int(getattr(result, "rowcount", 0) or 0) == 1
    except Exception:
        logger.exception(
            "ingest_enhance_running_mark_failed",
            user_id=user_id,
            file_id=file_id,
        )
        return False


def dispatch_enhancement_for_file(
    *,
    user_id: str,
    file_id: str,
    course_id: str = "",
    background_task_registry=None,
    recovery: bool = False,
) -> bool:
    """Claim and spawn one Phase 2 worker without duplicate dispatch."""

    normalized_user_id = str(user_id or "").strip()
    normalized_file_id = str(file_id or "").strip()
    normalized_course_id = str(course_id or "").strip()
    if not normalized_user_id or not normalized_file_id:
        return False

    claimed_step = (
        "ingest.enhance.recovery_queued"
        if recovery
        else "ingest.enhance.queued"
    )
    if not _claim_enhancement_dispatch(
        user_id=normalized_user_id,
        file_id=normalized_file_id,
        current_step=claimed_step,
    ):
        return False

    from app.workflows.ingest.parsing.nodes.enhance import _run_deep_enhance_background

    async def run_claimed_enhancement() -> None:
        if not _mark_enhancement_running(
            user_id=normalized_user_id,
            file_id=normalized_file_id,
            claimed_step=claimed_step,
        ):
            _requeue_enhancement_dispatch(
                user_id=normalized_user_id,
                file_id=normalized_file_id,
                claimed_step=claimed_step,
                reason="enhance_start_claim_failed",
            )
            return
        await _run_deep_enhance_background(
            user_id=normalized_user_id,
            course_id=normalized_course_id,
            file_id=normalized_file_id,
        )

    enhance_coro = run_claimed_enhancement()
    registry_course = normalized_course_id or f"files:{normalized_user_id}"
    kind = "ingest.enhance.recovery" if recovery else "ingest.enhance"
    name_prefix = "ingest.enhance.recover" if recovery else "ingest.enhance"
    try:
        if background_task_registry is not None:
            background_task_registry.spawn(
                enhance_coro,
                kind=kind,
                course_id=registry_course,
                name=f"{name_prefix}:{registry_course}:{normalized_file_id}",
                dedupe_key=f"ingest.enhance:{registry_course}:{normalized_file_id}",
                cancel_cleanup=lambda: _requeue_enhancement_dispatch(
                    user_id=normalized_user_id,
                    file_id=normalized_file_id,
                    claimed_step=claimed_step,
                    reason="enhance_worker_cancelled",
                ),
            )
        else:
            task = asyncio.create_task(enhance_coro)
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)
    except Exception:
        enhance_coro.close()
        _requeue_enhancement_dispatch(
            user_id=normalized_user_id,
            file_id=normalized_file_id,
            claimed_step=claimed_step,
        )
        logger.exception(
            "ingest_enhance_background_spawn_failed",
            course_id=normalized_course_id,
            user_id=normalized_user_id,
            file_id=normalized_file_id,
            recovery=recovery,
        )
        return False
    return True


def dispatch_enhancement_if_needed(
    state: IngestParseState,
    *,
    background_task_registry=None,
) -> bool:
    """Dispatch Phase 2 enhancement for a successful Phase 1 result when needed."""

    if not state.get("needs_enhance"):
        return False

    course_id = str(state.get("course_id") or "").strip()
    user_id = str(state.get("user_id") or "").strip()
    file_id = str(state.get("file_id") or "").strip()
    if not user_id or not file_id:
        return False

    return dispatch_enhancement_for_file(
        user_id=user_id,
        course_id=course_id,
        file_id=file_id,
        background_task_registry=background_task_registry,
    )


__all__ = [
    "dispatch_enhancement_for_file",
    "dispatch_enhancement_if_needed",
    "mark_parse_workflow_failed",
]

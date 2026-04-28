"""Post-graph lifecycle helpers for ingest fast-parse runs.

这里承接 graph 外的副作用收口：
- runtime 级失败时兜底更新 RawFile 状态
- Phase 1 成功后按需派发 Phase 2 增强任务

graph.py 只负责图定义和单次运行入口，不直接处理这些副作用。
"""

from __future__ import annotations

import asyncio

import structlog

from app.shared.infra.database import managed_session
from app.models import IngestStatus, TaskStatus
from app.repositories.files_repo import get_raw_file_by_id, update_raw_file
from app.workflows.ingest.fast_parse.lib.enhance import _run_deep_enhance_background
from app.workflows.ingest.fast_parse.lib.runtime_helpers import _background_tasks
from app.workflows.ingest.fast_parse.state import IngestParseState

logger = structlog.get_logger(__name__)


def mark_parse_workflow_failed(
    *,
    user_id: str,
    file_id: str,
    error: str,
    step: str = "ingest.unhandled_error",
    subject: str = "",
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
        logger.exception("ingest_parse_failed_status_update_error", subject=subject, user_id=user_id, file_id=file_id)


def dispatch_enhancement_if_needed(
    state: IngestParseState,
    *,
    background_task_registry=None,
) -> bool:
    """Dispatch Phase 2 enhancement for a successful Phase 1 result when needed."""

    if not state.get("needs_enhance"):
        return False

    subject = str(state.get("subject") or "").strip()
    user_id = str(state.get("user_id") or "").strip()
    file_id = str(state.get("file_id") or "").strip()
    if not user_id or not file_id:
        return False

    enhance_coro = _run_deep_enhance_background(
        user_id=user_id,
        subject=subject,
        file_id=file_id,
    )
    registry_subject = subject or f"files:{user_id}"
    if background_task_registry is not None:
        try:
            background_task_registry.spawn(
                enhance_coro,
                kind="ingest.enhance",
                subject=registry_subject,
                name=f"ingest.enhance:{registry_subject}:{file_id}",
            )
            return True
        except Exception:
            logger.exception(
                "ingest_enhance_background_registry_spawn_failed",
                subject=subject,
                user_id=user_id,
                file_id=file_id,
            )

    task = asyncio.create_task(enhance_coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return True


__all__ = [
    "dispatch_enhancement_if_needed",
    "mark_parse_workflow_failed",
]

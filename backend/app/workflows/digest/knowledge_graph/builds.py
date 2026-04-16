"""Knowledge-graph background build orchestration."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

import structlog

from app.shared.infra.database import managed_session
from app.utils.docgen_store import release_knowledge_build_lock, update_knowledge_build_status
from app.utils.job_helpers import cleanup_pending_by_subject

logger = structlog.get_logger()


def _sanitize_build_error_message(error_message: str | None) -> str | None:
    text = (error_message or "").strip()
    if not text:
        return None
    if text == "build_cancelled":
        return "知识构建已取消。"
    if text == "build_crashed":
        return "知识构建异常失败。"
    if "Dimension mismatch" in text or "sqlite3.OperationalError" in text or ("chunk_embeddings" in text and "embedding" in text):
        return "Embedding 配置已变化，请先重建向量后再继续。"
    if "[SQL:" in text or "parameters:" in text or "Traceback" in text or len(text) > 240:
        return "知识构建异常失败。"
    return text


def _write_build_status(subject: str, *, requested_at: datetime, status: str, stage: str, **extra: object) -> None:
    payload = {"requested_at": requested_at, "status": status, "stage": stage, **extra}
    if "error_message" in payload:
        payload["error_message"] = _sanitize_build_error_message(payload.get("error_message"))
    update_knowledge_build_status(subject, **payload)


def _new_graph_run_id() -> int:
    return (uuid.uuid4().int % 2_000_000_000) + 1


def _new_build_session_id() -> str:
    return uuid.uuid4().hex


def _cleanup_pending_digest_outputs(subject: str) -> None:
    try:
        with managed_session() as session:
            cleanup_pending_by_subject(session, subject=subject, job_type="graph")
    except Exception:
        logger.exception("knowledge_pending_cleanup_failed", subject=subject)


async def run_graph_digest_background(*, subject: str, file_ids: list[int]) -> None:
    from app.workflows.digest import run_graph_digest_workflow

    run_id = _new_graph_run_id()
    digest_logger = logger.bind(subject=subject, run_id=run_id)
    try:
        digest_logger.info("graph_digest_background_started")
        result = await run_graph_digest_workflow(subject=subject, job_id=run_id, file_ids=file_ids)
        if result.failed:
            digest_logger.error("graph_digest_background_failed", error=result.error.detail)
            return
        digest_logger.info("graph_digest_background_completed")
    except Exception:
        digest_logger.exception("graph_digest_background_error")


async def run_graph_build_background(
    *,
    subject: str,
    file_ids: list[int],
    prompt: str | None,
    requested_at: datetime,
) -> None:
    from app.workflows.digest import run_graph_digest_workflow

    build_session_id = _new_build_session_id()
    try:
        _write_build_status(
            subject,
            requested_at=requested_at,
            status="running",
            stage="prepare_shared",
            build_session_id=build_session_id,
            error_message=None,
            draft_available=False,
            source_file_ids=file_ids,
            prompt=prompt,
        )
        _cleanup_pending_digest_outputs(subject)
        result = await run_graph_digest_workflow(
            subject=subject,
            job_id=_new_graph_run_id(),
            file_ids=file_ids,
            user_prompt=prompt,
            build_session_id=build_session_id,
        )
        if result.failed:
            _write_build_status(
                subject,
                requested_at=requested_at,
                status="failed",
                stage="failed",
                build_session_id=build_session_id,
                error_message=result.error.detail,
            )
            logger.error("knowledge_graph_build_failed", subject=subject, error=result.error.detail)
            return
        final_state = result.require_value()
        _write_build_status(
            subject,
            requested_at=requested_at,
            status="completed",
            stage="completed",
            build_session_id=build_session_id,
            error_message=None,
            processed_chunks=len(final_state.get("chunk_ids", [])),
        )
    except asyncio.CancelledError:
        _write_build_status(
            subject,
            requested_at=requested_at,
            status="cancelled",
            stage="cancelled",
            build_session_id=build_session_id,
            error_message="build_cancelled",
        )
        raise
    except Exception:
        _write_build_status(
            subject,
            requested_at=requested_at,
            status="failed",
            stage="failed",
            build_session_id=build_session_id,
            error_message="build_crashed",
        )
        logger.exception("knowledge_graph_build_error", subject=subject)
        return
    finally:
        release_knowledge_build_lock(subject)


__all__ = ["run_graph_build_background", "run_graph_digest_background"]

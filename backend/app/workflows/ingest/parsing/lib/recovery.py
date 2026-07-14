"""Fail-closed recovery helpers for ingest background admission gaps.

Active parse/enhancement workers are intentionally not reclaimed without an
attempt-level fencing token. Recovery is limited to work that has not started:
Phase 1 rows explicitly returned to ``retry_pending`` after spawn failure, and
stale ``fast_parsed`` rows atomically claimed before Phase 2 is spawned.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import sqlalchemy as sa
import structlog
from sqlmodel import Session, select

from app.models import IngestStatus, RawFile, TaskStatus
from app.shared.infra.database import managed_session
from app.utils.time import utcnow
from app.workflows.ingest.parsing.lib.runtime_helpers import _background_tasks

logger = structlog.get_logger()

STALLED_INGEST_TTL = timedelta(minutes=30)
INGEST_RECOVERY_SCAN_INTERVAL_SECONDS = 60.0


def _rowcount(result: object) -> int:
    return int(getattr(result, "rowcount", 0) or 0)


def _claim_parse_recovery(
    session: Session,
    raw_file: RawFile,
    *,
    claimed_at: datetime,
) -> bool:
    """Atomically claim a Phase 1 row known to have no admitted worker."""

    if raw_file.id is None:
        return False
    claimed = session.exec(
        sa.update(RawFile)
        .where(
            RawFile.id == raw_file.id,
            RawFile.user_id == raw_file.user_id,
            RawFile.status == TaskStatus.PENDING.value,
            RawFile.ingest_status == IngestStatus.RETRY_PENDING.value,
            RawFile.updated_at == raw_file.updated_at,
        )
        .values(
            status=TaskStatus.PROCESSING.value,
            ingest_status=IngestStatus.CLASSIFYING.value,
            current_step="ingest.parse.recovery_queued",
            error_message=None,
            updated_at=claimed_at,
        )
        .execution_options(synchronize_session=False)
    )
    session.commit()
    return _rowcount(claimed) == 1


async def recover_stalled_parses(*, task_registry=None) -> int:
    """Redispatch only durable Phase 1 admission failures.

    ``processing`` rows are never taken over here: a late old worker could
    otherwise overwrite storage and database state produced by the replacement.
    """

    from app.workflows.ingest.intake.parse_dispatch import (
        mark_parse_files_retry_pending,
        run_parse_files_background,
        spawn_parse_files_background,
    )

    dispatched = 0
    try:
        with managed_session() as session:
            candidates = list(
                session.exec(
                    select(RawFile)
                    .where(
                        RawFile.status == TaskStatus.PENDING.value,
                        RawFile.ingest_status == IngestStatus.RETRY_PENDING.value,
                    )
                    .order_by(RawFile.updated_at.asc())  # type: ignore[union-attr]
                ).all()
            )

            for raw_file in candidates:
                file_id = str(raw_file.id or "").strip()
                user_id = str(raw_file.user_id or "").strip()
                if not file_id or not user_id:
                    continue
                if not _claim_parse_recovery(session, raw_file, claimed_at=utcnow()):
                    continue

                course_id = str(raw_file.origin_course_id or "").strip() or None
                parse_coro = None
                try:
                    if task_registry is not None:
                        spawn_parse_files_background(
                            task_registry,
                            user_id=user_id,
                            course_id=course_id,
                            file_ids=[file_id],
                        )
                    else:
                        parse_coro = run_parse_files_background(
                            user_id=user_id,
                            course_id=course_id,
                            file_ids=[file_id],
                        )
                        task = asyncio.create_task(parse_coro)
                        _background_tasks.add(task)
                        task.add_done_callback(_background_tasks.discard)
                except Exception:
                    if parse_coro is not None:
                        parse_coro.close()
                    mark_parse_files_retry_pending(
                        user_id=user_id,
                        file_ids=[file_id],
                        reason="parse_recovery_dispatch_failed",
                    )
                    logger.exception(
                        "recover_stalled_parse_dispatch_failed",
                        user_id=user_id,
                        course_id=course_id or "",
                        file_id=file_id,
                    )
                    continue
                dispatched += 1
    except Exception:
        logger.exception("recover_stalled_parses_error")

    logger.info("recover_stalled_parses_dispatched", count=dispatched)
    return dispatched


async def recover_stalled_enhancements(
    *,
    task_registry=None,
    now: datetime | None = None,
) -> int:
    """Atomically dispatch stale Phase 2 work that has not started yet."""

    from app.workflows.ingest.parsing.lib.lifecycle import dispatch_enhancement_for_file

    cutoff = (now or utcnow()) - STALLED_INGEST_TTL
    try:
        with managed_session() as session:
            candidates = [
                (
                    str(raw_file.user_id or "").strip(),
                    str(raw_file.id or "").strip(),
                    str(raw_file.origin_course_id or "").strip(),
                )
                for raw_file in session.exec(
                    select(RawFile)
                    .where(
                        RawFile.status == TaskStatus.COMPLETED.value,
                        RawFile.ingest_status == IngestStatus.FAST_PARSED.value,
                        RawFile.updated_at <= cutoff,
                    )
                    .order_by(RawFile.updated_at.asc())  # type: ignore[union-attr]
                ).all()
            ]
    except Exception:
        logger.exception("recover_stalled_enhancements_error")
        return 0

    dispatched = 0
    for user_id, file_id, course_id in candidates:
        if not user_id or not file_id:
            continue
        if dispatch_enhancement_for_file(
            user_id=user_id,
            file_id=file_id,
            course_id=course_id,
            background_task_registry=task_registry,
            recovery=True,
        ):
            dispatched += 1

    logger.info("recover_stalled_enhancements_dispatched", count=dispatched)
    return dispatched


async def recover_stalled_ingest_once(*, task_registry=None) -> int:
    """Run one safe recovery pass for both ingest phases."""

    parse_count = await recover_stalled_parses(task_registry=task_registry)
    enhance_count = await recover_stalled_enhancements(task_registry=task_registry)
    return parse_count + enhance_count


async def run_ingest_recovery_loop(*, task_registry=None) -> None:
    """Continuously recover safe admission gaps after application startup."""

    while True:
        await recover_stalled_ingest_once(task_registry=task_registry)
        await asyncio.sleep(INGEST_RECOVERY_SCAN_INTERVAL_SECONDS)


__all__ = [
    "INGEST_RECOVERY_SCAN_INTERVAL_SECONDS",
    "STALLED_INGEST_TTL",
    "recover_stalled_enhancements",
    "recover_stalled_ingest_once",
    "recover_stalled_parses",
    "run_ingest_recovery_loop",
]

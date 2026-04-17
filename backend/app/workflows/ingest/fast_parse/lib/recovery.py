"""Recovery helpers for stalled ingest background enhancement."""

from __future__ import annotations

import asyncio

import structlog

from app.models import IngestStatus
from app.shared.infra.database import managed_session

logger = structlog.get_logger()

_STALLED_STATUSES = {
    IngestStatus.FAST_PARSED.value,
    IngestStatus.ENHANCING.value,
}


async def recover_stalled_enhancements(*, task_registry=None) -> int:
    """Scan for files stuck in fast_parsed/enhancing and redispatch Phase 2."""

    from sqlmodel import select

    from app.models.raw_file import RawFile
    from app.workflows.ingest.fast_parse.lib.enhance import _run_deep_enhance_background
    from app.workflows.ingest.fast_parse.lib.runtime_helpers import _background_tasks

    dispatched = 0

    try:
        with managed_session() as session:
            statement = select(RawFile).where(
                RawFile.ingest_status.in_(list(_STALLED_STATUSES))  # type: ignore[attr-defined]
            )
            stalled_files = session.exec(statement).all()

            if not stalled_files:
                logger.info("recover_stalled_enhancements_none_found")
                return 0

            logger.info(
                "recover_stalled_enhancements_found",
                count=len(stalled_files),
                file_ids=[item.id for item in stalled_files],
            )

            for raw_file in stalled_files:
                if raw_file.id is None:
                    continue

                subject = (raw_file.subject or "").strip()
                if not subject:
                    logger.warning(
                        "recover_stalled_skip_no_subject",
                        file_id=raw_file.id,
                    )
                    continue

                logger.info(
                    "recover_stalled_dispatching",
                    file_id=raw_file.id,
                    subject=subject,
                    current_status=raw_file.ingest_status,
                )
                enhance_coro = _run_deep_enhance_background(
                    subject=subject,
                    file_id=raw_file.id,
                )
                if task_registry is not None:
                    task_registry.spawn(
                        enhance_coro,
                        kind="ingest.enhance.recovery",
                        subject=subject,
                        name=f"ingest.enhance.recover:{subject}:{raw_file.id}",
                    )
                else:
                    task = asyncio.create_task(enhance_coro)
                    _background_tasks.add(task)
                    task.add_done_callback(_background_tasks.discard)
                dispatched += 1

    except Exception:
        logger.exception("recover_stalled_enhancements_error")

    logger.info("recover_stalled_enhancements_dispatched", count=dispatched)
    return dispatched


__all__ = ["recover_stalled_enhancements"]

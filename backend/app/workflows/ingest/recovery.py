"""Canonical stalled-enhancement recovery logic for ingest."""

from __future__ import annotations

import asyncio

import structlog

from app.shared.infra.database import managed_session
from app.models import IngestStatus

logger = structlog.get_logger()

_STALLED_STATUSES = {
    IngestStatus.FAST_PARSED.value,
    IngestStatus.ENHANCING.value,
}


async def recover_stalled_enhancements() -> int:
    """Scan for files stuck in fast_parsed/enhancing and redispatch Phase 2."""

    from app.workflows.ingest.parse_files import _run_deep_enhance_background
    from app.workflows.ingest.fast_parse.lib.runtime_helpers import _background_tasks

    dispatched = 0

    try:
        with managed_session() as session:
            from sqlmodel import select
            from app.models.raw_file import RawFile

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
                file_ids=[f.id for f in stalled_files],
            )

            for raw_file in stalled_files:
                if raw_file.id is None:
                    continue

                parts = [p for p in raw_file.storage_key.split("/") if p]
                subject = parts[0] if parts else ""
                if not subject:
                    logger.warning(
                        "recover_stalled_skip_no_subject",
                        file_id=raw_file.id,
                        storage_key=raw_file.storage_key,
                    )
                    continue

                logger.info(
                    "recover_stalled_dispatching",
                    file_id=raw_file.id,
                    subject=subject,
                    current_status=raw_file.ingest_status,
                )
                task = asyncio.create_task(
                    _run_deep_enhance_background(
                        subject=subject,
                        file_id=raw_file.id,
                        event_bus=None,
                    )
                )
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)
                dispatched += 1

    except Exception:
        logger.exception("recover_stalled_enhancements_error")

    logger.info("recover_stalled_enhancements_dispatched", count=dispatched)
    return dispatched


__all__ = ["recover_stalled_enhancements"]

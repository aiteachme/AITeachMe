"""Recovery module for stalled Phase 2 tasks.

On service startup, scans for raw_files with ingest_status in
{FAST_PARSED, ENHANCING} and re-dispatches their Phase 2
deep-enhance workflows. This handles the case where the service
was restarted while Phase 2 was in progress.
"""

from __future__ import annotations

import asyncio

import structlog

from app.infra.database import managed_session
from app.models import IngestStatus
from app.repositories.files_repo import get_raw_file_by_id

logger = structlog.get_logger()

# Stalled statuses that need Phase 2 recovery
_STALLED_STATUSES = {
    IngestStatus.FAST_PARSED.value,
    IngestStatus.ENHANCING.value,
}


async def recover_stalled_enhancements() -> int:
    """Scan for files stuck in Phase 1 complete or Phase 2 in-progress,
    and re-dispatch their background enhance tasks.

    Returns the number of tasks dispatched.
    """

    from app.workflows.ingest.runtime import _run_deep_enhance_background

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

                # Derive subject slug from storage_key
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
                asyncio.create_task(
                    _run_deep_enhance_background(
                        subject=subject,
                        file_id=raw_file.id,
                        event_bus=None,
                    )
                )
                dispatched += 1

    except Exception:
        logger.exception("recover_stalled_enhancements_error")

    logger.info("recover_stalled_enhancements_dispatched", count=dispatched)
    return dispatched

"""Shared file readiness predicates for digest lanes."""

from __future__ import annotations

from app.models import IngestStatus, TaskStatus
from app.models.raw_file import RawFile

DIGEST_READY_INGEST_STATUSES = frozenset(
    {
        IngestStatus.FAST_PARSED.value,
        IngestStatus.ENHANCING.value,
        IngestStatus.READY_FOR_DIGEST.value,
        IngestStatus.ENHANCE_FAILED.value,
    }
)


def is_markdown_ready_for_digest(raw_file: RawFile) -> bool:
    """Return whether a raw file has markdown usable by Planner/DocGen."""

    return (
        raw_file.status == TaskStatus.COMPLETED.value
        and raw_file.ingest_status in DIGEST_READY_INGEST_STATUSES
        and bool((raw_file.parsed_markdown or "").strip())
    )


__all__ = ["DIGEST_READY_INGEST_STATUSES", "is_markdown_ready_for_digest"]

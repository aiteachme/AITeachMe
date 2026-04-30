"""Course retrieval-index materialization helpers.

This is the narrow bridge used by ingest and digest lanes to ensure parsed
course files become searchable local RAG material. It deliberately keeps the
operation best-effort for workflow callers: document generation and upload
parsing should not fail only because an embedding provider is temporarily
unavailable.
"""

from __future__ import annotations

from uuid import uuid4

import structlog

from app.workflows.digest.common.materialize import materialize_shared_inputs
from app.workflows.digest.common.models import MaterializedSections, SharedInputs
from app.workflows.digest.common.prepare import prepare_shared_inputs

logger = structlog.get_logger(__name__)


async def materialize_course_inputs_for_retrieval(
    *,
    course_id: str,
    shared_inputs: SharedInputs,
    reason: str = "",
    raise_errors: bool = False,
) -> MaterializedSections | None:
    """Persist chunks and embeddings for already prepared course inputs."""

    normalized_course_id = str(course_id or "").strip()
    if not normalized_course_id or not shared_inputs.source_packets:
        return None

    build_session_id = f"retrieval_{uuid4().hex}"
    try:
        materialized = await materialize_shared_inputs(
            course_id=normalized_course_id,
            shared_inputs=shared_inputs,
            build_session_id=build_session_id,
        )
        logger.info(
            "course_retrieval_index_materialized",
            course_id=normalized_course_id,
            reason=reason,
            build_session_id=build_session_id,
            file_count=len(shared_inputs.source_packets),
            chunk_count=len(materialized.chunk_ids),
        )
        return materialized
    except Exception as exc:
        logger.warning(
            "course_retrieval_index_materialize_failed",
            course_id=normalized_course_id,
            reason=reason,
            error=str(exc),
        )
        if raise_errors:
            raise
        return None


async def index_course_files_for_retrieval(
    *,
    course_id: str,
    file_ids: list[str],
    reason: str = "",
    raise_errors: bool = False,
) -> MaterializedSections | None:
    """Load parsed files, split them, and materialize the course vector index."""

    normalized_course_id = str(course_id or "").strip()
    normalized_file_ids = [
        file_id
        for file_id in dict.fromkeys(str(item or "").strip() for item in file_ids)
        if file_id
    ]
    if not normalized_course_id or not normalized_file_ids:
        return None

    try:
        shared_inputs = await prepare_shared_inputs(
            normalized_course_id,
            normalized_file_ids,
        )
    except Exception as exc:
        logger.warning(
            "course_retrieval_index_prepare_failed",
            course_id=normalized_course_id,
            file_ids=normalized_file_ids,
            reason=reason,
            error=str(exc),
        )
        if raise_errors:
            raise
        return None

    if not shared_inputs.source_packets:
        logger.info(
            "course_retrieval_index_skipped_empty_sources",
            course_id=normalized_course_id,
            file_ids=normalized_file_ids,
            reason=reason,
        )
        return None

    return await materialize_course_inputs_for_retrieval(
        course_id=normalized_course_id,
        shared_inputs=shared_inputs,
        reason=reason,
        raise_errors=raise_errors,
    )


__all__ = [
    "index_course_files_for_retrieval",
    "materialize_course_inputs_for_retrieval",
]

"""In-memory KG extraction prefetch for DocGen sidecar runs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from threading import RLock
from typing import Any

import structlog

from app.shared.infra.database import managed_session
from app.shared.infra.llm_support.common import (
    LLMRuntimeSnapshot,
    capture_llm_runtime_snapshot,
    use_llm_runtime_snapshot,
)
from app.shared.infra.settings import get_settings
from app.workflows.digest.kg_doc_sync.lib.incremental_sync import (
    _graph_llm_concurrency_cap,
    extract_knowledge_graph_section_records_async,
)
from app.workflows.digest.kg_doc_sync.lib.models import SectionExtractionRecord
from app.workflows.support.courses.learning_context import load_course_llm_context

logger = structlog.get_logger(__name__)

_PREFETCH_START_DELAY_S = 0.5
_PREFETCH_CONSUME_GRACE_S = 8.0


@dataclass(slots=True)
class _PrefetchCache:
    course_id: str
    build_session_id: str
    task: asyncio.Task[None] | None = None
    records: list[SectionExtractionRecord] = field(default_factory=list)
    metrics: dict[str, int | str] = field(default_factory=dict)
    status: str = "running"
    error: str = ""


_LOCK = RLock()
_CACHES: dict[tuple[str, str], _PrefetchCache] = {}


def _key(course_id: str, build_session_id: str) -> tuple[str, str]:
    return str(course_id or "").strip(), str(build_session_id or "").strip()


def _clean_string_list(value: object) -> list[str]:
    items = value if isinstance(value, list) else ([] if value is None else [value])
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        parsed = str(item or "").strip()
        if not parsed or parsed in seen:
            continue
        seen.add(parsed)
        cleaned.append(parsed)
    return cleaned


def _chapter_source_file_ids(chapter: dict[str, Any]) -> list[str]:
    source_scope = chapter.get("source_scope")
    source_scope = dict(source_scope) if isinstance(source_scope, dict) else {}
    return _clean_string_list(
        chapter.get("source_file_ids")
        or source_scope.get("source_file_ids")
        or [
            item.get("file_id")
            for item in list(chapter.get("source_details") or [])
            if isinstance(item, dict)
        ]
    )


def _chapter_markdown(chapter: dict[str, Any]) -> str:
    title = str(chapter.get("title") or "").strip() or f"第 {chapter.get('chapter_index') or ''} 章".strip()
    markdown = str(chapter.get("markdown") or "").strip()
    if not markdown:
        return ""
    if markdown.lstrip().startswith("#"):
        return markdown
    return f"# {title}\n\n{markdown}"


def _prefetch_markdown(chapters: list[dict[str, Any]]) -> str:
    parts = [_chapter_markdown(chapter) for chapter in chapters]
    return "\n\n---\n\n".join(part for part in parts if part.strip()).strip()


def _structured_context(
    *,
    chapters: list[dict[str, Any]],
    document_backbone: dict[str, Any] | None,
    docgen_manifest: dict[str, Any] | None = None,
) -> dict[str, object]:
    manifest = dict(docgen_manifest or {})
    manifest.setdefault("document_backbone_snapshot", dict(document_backbone or {}))
    return {
        "doc_version_no": 0,
        "docgen_manifest": manifest,
        "chapters": [
            {
                "knowledge_document_id": None,
                "chapter_index": int(chapter.get("chapter_index") or index),
                "title": str(chapter.get("title") or "").strip(),
                "summary": str(chapter.get("summary") or chapter.get("summary_draft") or "").strip(),
                "digest_mode": str(chapter.get("digest_mode") or manifest.get("digest_mode") or "").strip(),
                "source_file_ids": _chapter_source_file_ids(chapter),
            }
            for index, chapter in enumerate(chapters, start=1)
        ],
    }


def start_docgen_kg_prefetch(
    *,
    course_id: str,
    build_session_id: str,
    chapters: list[dict[str, Any]],
    document_backbone: dict[str, Any] | None = None,
    docgen_manifest: dict[str, Any] | None = None,
    llm_snapshot: LLMRuntimeSnapshot | None = None,
) -> bool:
    """Start a non-blocking KG prefetch task for enhanced DocGen chapters."""

    settings = get_settings()
    if not settings.knowledge_graph.sync_after_docgen:
        return False
    if not settings.knowledge_graph.prefetch_during_docgen:
        return False
    course_id = str(course_id or "").strip()
    build_session_id = str(build_session_id or "").strip()
    if not course_id or not build_session_id:
        return False
    markdown = _prefetch_markdown(chapters)
    if not markdown:
        return False
    key = _key(course_id, build_session_id)
    with _LOCK:
        existing = _CACHES.pop(key, None)
        if existing is not None and existing.task is not None and not existing.task.done():
            existing.task.cancel()
        cache = _PrefetchCache(course_id=course_id, build_session_id=build_session_id)
        _CACHES[key] = cache

    snapshot = llm_snapshot or capture_llm_runtime_snapshot()
    structured_context = _structured_context(
        chapters=chapters,
        document_backbone=document_backbone,
        docgen_manifest=docgen_manifest,
    )
    concurrency = max(
        1,
        min(
            int(settings.knowledge_graph.prefetch_concurrency or 1),
            _graph_llm_concurrency_cap(),
        ),
    )

    def _on_record(record: SectionExtractionRecord) -> None:
        with _LOCK:
            active = _CACHES.get(key)
            if active is cache:
                active.records.append(record)

    async def _run() -> None:
        try:
            # Let the next DocGen node schedule first, so prefetch does not jump ahead of review work.
            await asyncio.sleep(_PREFETCH_START_DELAY_S)
            with managed_session() as session:
                course_context = load_course_llm_context(session, course_id=course_id)
            with use_llm_runtime_snapshot(snapshot):
                _records, metrics = await extract_knowledge_graph_section_records_async(
                    markdown=markdown,
                    course_context=course_context,
                    structured_context=structured_context,
                    concurrency_limit=concurrency,
                    on_record=_on_record,
                )
            with _LOCK:
                active = _CACHES.get(key)
                if active is cache:
                    active.metrics = dict(metrics)
                    active.status = "completed"
            logger.info(
                "docgen_kg_prefetch_completed",
                course_id=course_id,
                build_session_id=build_session_id,
                record_count=len(_records),
                concurrency=concurrency,
            )
        except asyncio.CancelledError:
            with _LOCK:
                active = _CACHES.get(key)
                if active is cache:
                    active.status = "cancelled"
            raise
        except Exception as exc:
            with _LOCK:
                active = _CACHES.get(key)
                if active is cache:
                    active.status = "failed"
                    active.error = str(exc)
            logger.warning(
                "docgen_kg_prefetch_failed",
                course_id=course_id,
                build_session_id=build_session_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )

    task = asyncio.create_task(_run(), name=f"docgen.kg_prefetch:{course_id}:{build_session_id}")
    with _LOCK:
        cache.task = task
    logger.info(
        "docgen_kg_prefetch_started",
        course_id=course_id,
        build_session_id=build_session_id,
        chapter_count=len(chapters),
        concurrency=concurrency,
    )
    return True


async def consume_docgen_kg_prefetch(
    *,
    course_id: str,
    build_session_id: str,
    wait_timeout_s: float = _PREFETCH_CONSUME_GRACE_S,
) -> tuple[list[SectionExtractionRecord], dict[str, int | str]]:
    """Return current prefetch records and stop any unfinished sidecar task."""

    key = _key(course_id, build_session_id)
    with _LOCK:
        cache = _CACHES.pop(key, None)
    if cache is None:
        return [], {"prefetch_status": "missing"}
    task = cache.task
    if task is not None and not task.done() and wait_timeout_s > 0:
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=wait_timeout_s)
        except TimeoutError:
            pass
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
    if task is not None and not task.done():
        cache.status = "consumed"
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    with _LOCK:
        records = list(cache.records)
        metrics = dict(cache.metrics)
        status = cache.status
        error = cache.error
    metrics.setdefault("prefetch_status", status)
    if error:
        metrics["prefetch_error"] = error
    metrics["prefetch_section_count"] = len(records)
    metrics["prefetch_failed_section_count"] = sum(1 for record in records if record.error)
    return records, metrics


def cancel_docgen_kg_prefetch(*, course_id: str, build_session_id: str) -> None:
    key = _key(course_id, build_session_id)
    with _LOCK:
        cache = _CACHES.pop(key, None)
    if cache is not None and cache.task is not None and not cache.task.done():
        cache.task.cancel()


__all__ = [
    "cancel_docgen_kg_prefetch",
    "consume_docgen_kg_prefetch",
    "start_docgen_kg_prefetch",
]

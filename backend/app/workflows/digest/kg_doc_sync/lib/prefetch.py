"""In-memory KG extraction prefetch for DocGen sidecar runs."""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
from dataclasses import dataclass, field
from threading import RLock
from typing import Any

import structlog
from langsmith import tracing_context

from app.shared.infra.database import managed_session
from app.shared.infra.llm_support.common import (
    LLMRuntimeSnapshot,
    capture_llm_runtime_snapshot,
    use_llm_runtime_snapshot,
)
from app.shared.infra.observability.trace import (
    langsmith_expected_cancellation_scope,
    langsmith_trace,
    llm_trace_scope,
)
from app.shared.infra.settings import get_settings
from app.workflows.digest.kg_doc_sync.lib.incremental_sync import (
    _graph_llm_concurrency_cap,
    extract_knowledge_graph_section_records_async,
)
from app.workflows.digest.kg_doc_sync.lib.model_policy import (
    kg_doc_sync_section_llm_max_retries,
    kg_doc_sync_section_llm_timeout_s,
)
from app.workflows.digest.kg_doc_sync.lib.models import SectionExtractionRecord
from app.workflows.support.courses.learning_context import load_course_llm_context

logger = structlog.get_logger(__name__)

_PREFETCH_AWAIT_GRACE_S = 8.0
_PREFETCH_EXTRACTION_ATTEMPTS = kg_doc_sync_section_llm_max_retries()
_PREFETCH_CONSUME_GRACE_S = float(
    kg_doc_sync_section_llm_timeout_s() * _PREFETCH_EXTRACTION_ATTEMPTS
    + 20
)


@dataclass(slots=True)
class _PrefetchCache:
    course_id: str
    build_session_id: str
    task: asyncio.Task[None] | None = None
    tasks: list[asyncio.Task[None]] = field(default_factory=list)
    records: list[SectionExtractionRecord] = field(default_factory=list)
    metrics: dict[str, int | str] = field(default_factory=dict)
    status: str = "running"
    error: str = ""


_LOCK = RLock()
_CACHES: dict[tuple[str, str], _PrefetchCache] = {}


def _key(course_id: str, build_session_id: str) -> tuple[str, str]:
    return str(course_id or "").strip(), str(build_session_id or "").strip()


def _prefetch_concurrency_limit(
    configured: int | None,
    *,
    global_limit: int | None = None,
) -> int:
    """Respect the configured prefetch limit and the shared global LLM limit."""

    configured_limit = max(1, int(configured or 1))
    llm_limit = max(
        1,
        int(_graph_llm_concurrency_cap() if global_limit is None else global_limit or 1),
    )
    return min(configured_limit, llm_limit)


def _prefetch_trace_phase(docgen_manifest: dict[str, Any] | None) -> str:
    return str((docgen_manifest or {}).get("kg_prefetch_phase") or "unknown").strip() or "unknown"


def _prefetch_trace_inputs(
    *,
    chapters: list[dict[str, Any]],
    markdown: str,
    concurrency: int,
    docgen_manifest: dict[str, Any] | None,
    incremental: bool,
) -> dict[str, Any]:
    return {
        "chapter_count": len(chapters),
        "markdown_chars": len(markdown),
        "concurrency_limit": concurrency,
        "kg_prefetch_phase": _prefetch_trace_phase(docgen_manifest),
        "incremental": bool(incremental),
    }


def _prefetch_trace_metadata(
    *,
    concurrency: int,
    configured_concurrency: int,
    llm_concurrency_cap: int,
    docgen_manifest: dict[str, Any] | None,
    incremental: bool,
) -> dict[str, Any]:
    return {
        "background_sidecar": "kg_docgen_prefetch",
        "kg_prefetch_phase": _prefetch_trace_phase(docgen_manifest),
        "incremental": bool(incremental),
        "configured_concurrency": configured_concurrency,
        "llm_concurrency_cap": llm_concurrency_cap,
        "effective_concurrency": concurrency,
    }


async def _extract_prefetch_records_with_trace(
    *,
    course_id: str,
    build_session_id: str,
    markdown: str,
    chapters: list[dict[str, Any]],
    course_context: Any,
    structured_context: dict[str, Any],
    docgen_manifest: dict[str, Any] | None,
    snapshot: LLMRuntimeSnapshot,
    concurrency: int,
    configured_concurrency: int,
    llm_concurrency_cap: int,
    incremental: bool,
    on_record: Any,
    prefetched_records: list[SectionExtractionRecord] | None = None,
) -> tuple[list[SectionExtractionRecord], dict[str, Any]]:
    workflow = "kg_docgen_prefetch"
    lane = "background"
    phase = _prefetch_trace_phase(docgen_manifest)
    trace_name = "KG：DocGen 增量预取" if incremental else "KG：DocGen 预取"
    with (
        langsmith_expected_cancellation_scope("kg_docgen_prefetch_sidecar"),
        use_llm_runtime_snapshot(snapshot),
    ):
        with llm_trace_scope(
            course_id=course_id,
            build_session_id=build_session_id,
            workflow=workflow,
            lane=lane,
            node=phase,
        ):
            with langsmith_trace(
                name=trace_name,
                run_type="chain",
                inputs=_prefetch_trace_inputs(
                    chapters=chapters,
                    markdown=markdown,
                    concurrency=concurrency,
                    docgen_manifest=docgen_manifest,
                    incremental=incremental,
                ),
                course_id=course_id,
                build_session_id=build_session_id,
                workflow=workflow,
                lane=lane,
                node=phase,
                extra_metadata=_prefetch_trace_metadata(
                    concurrency=concurrency,
                    configured_concurrency=configured_concurrency,
                    llm_concurrency_cap=llm_concurrency_cap,
                    docgen_manifest=docgen_manifest,
                    incremental=incremental,
                ),
                extra_tags=["background:kg_docgen_prefetch"],
            ) as trace_run:
                with (
                    tracing_context(parent=trace_run)
                    if trace_run is not None
                    else nullcontext()
                ):
                    records, metrics = await extract_knowledge_graph_section_records_async(
                        markdown=markdown,
                        course_context=course_context,
                        structured_context=structured_context,
                        concurrency_limit=concurrency,
                        prefetched_records=prefetched_records,
                        on_record=on_record,
                    )
                if trace_run is not None:
                    trace_run.end(
                        outputs={
                            **dict(metrics),
                            "record_count": len(records),
                            "concurrency_limit": concurrency,
                        }
                    )
                return records, dict(metrics)


def _drop_cache_if_current(key: tuple[str, str], cache: _PrefetchCache) -> None:
    with _LOCK:
        if _CACHES.get(key) is cache:
            _CACHES.pop(key, None)


def _cache_tasks(cache: _PrefetchCache) -> list[asyncio.Task[None]]:
    tasks: list[asyncio.Task[None]] = []
    if cache.task is not None:
        tasks.append(cache.task)
    for task in list(cache.tasks):
        if task not in tasks:
            tasks.append(task)
    return tasks


def _active_cache_tasks(cache: _PrefetchCache) -> list[asyncio.Task[None]]:
    return [task for task in _cache_tasks(cache) if not task.done()]


def _cancel_cache_tasks(cache: _PrefetchCache) -> None:
    for task in _active_cache_tasks(cache):
        task.cancel()


def _prefetch_metrics_snapshot(cache: _PrefetchCache) -> dict[str, int | str]:
    records = list(cache.records)
    metrics = dict(cache.metrics)
    status = str(cache.status or "").strip() or "running"
    active_tasks = _active_cache_tasks(cache)
    if not active_tasks and status == "running":
        status = "completed"
    metrics.setdefault("prefetch_status", status)
    if cache.error:
        metrics["prefetch_error"] = cache.error
    metrics["prefetch_section_count"] = len(records)
    metrics["prefetch_failed_section_count"] = sum(1 for record in records if record.error)
    metrics["prefetch_ready"] = 0 if active_tasks else 1
    metrics["prefetch_active_task_count"] = len(active_tasks)
    return metrics


def _record_key(record: SectionExtractionRecord) -> tuple[str, str]:
    return str(record.section_key or ""), str(record.content_hash or "")


def _cleanup_consumed_cache_when_done(key: tuple[str, str], cache: _PrefetchCache) -> None:
    active_tasks = _active_cache_tasks(cache)
    if not active_tasks:
        _drop_cache_if_current(key, cache)
        return

    def _cleanup(_task: asyncio.Task[None]) -> None:
        try:
            _task.exception()
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        if not _active_cache_tasks(cache):
            _drop_cache_if_current(key, cache)

    for task in active_tasks:
        task.add_done_callback(_cleanup)


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
    prior_records: list[SectionExtractionRecord] = []
    prior_metrics: dict[str, int | str] = {}
    prior_status = ""
    with _LOCK:
        existing = _CACHES.pop(key, None)
        if existing is not None:
            prior_records = list(existing.records)
            prior_status = str(existing.status or "")
        if existing is not None:
            _cancel_cache_tasks(existing)
        if prior_records:
            prior_metrics["prefetch_prior_section_count"] = len(prior_records)
            if prior_status:
                prior_metrics["prefetch_prior_status"] = prior_status
        cache = _PrefetchCache(
            course_id=course_id,
            build_session_id=build_session_id,
            records=prior_records,
            metrics=prior_metrics,
        )
        _CACHES[key] = cache

    snapshot = llm_snapshot or capture_llm_runtime_snapshot()
    structured_context = _structured_context(
        chapters=chapters,
        document_backbone=document_backbone,
        docgen_manifest=docgen_manifest,
    )
    configured_concurrency = int(settings.knowledge_graph.prefetch_concurrency or 1)
    llm_concurrency_cap = _graph_llm_concurrency_cap()
    prefetch_phase = _prefetch_trace_phase(docgen_manifest)
    concurrency = _prefetch_concurrency_limit(
        configured_concurrency,
        global_limit=llm_concurrency_cap,
    )
    with _LOCK:
        cache.metrics.update(
            {
                "prefetch_configured_concurrency": configured_concurrency,
                "prefetch_llm_concurrency_cap": llm_concurrency_cap,
                "prefetch_effective_concurrency": concurrency,
                "prefetch_fanout_mode": f"bounded_{prefetch_phase}_sections",
            }
        )

    def _on_record(record: SectionExtractionRecord) -> None:
        with _LOCK:
            active = _CACHES.get(key)
            if active is cache:
                active.records.append(record)

    async def _run() -> None:
        try:
            with managed_session() as session:
                course_context = load_course_llm_context(session, course_id=course_id)
            _records, metrics = await _extract_prefetch_records_with_trace(
                course_id=course_id,
                build_session_id=build_session_id,
                markdown=markdown,
                chapters=chapters,
                course_context=course_context,
                structured_context=structured_context,
                docgen_manifest=docgen_manifest,
                snapshot=snapshot,
                concurrency=concurrency,
                configured_concurrency=configured_concurrency,
                llm_concurrency_cap=llm_concurrency_cap,
                incremental=False,
                on_record=_on_record,
                prefetched_records=prior_records,
            )
            with _LOCK:
                active = _CACHES.get(key)
                if active is cache:
                    current_task = asyncio.current_task()
                    fresh_keys = {_record_key(record) for record in _records}
                    active.records = [
                        *_records,
                        *[
                            record
                            for record in active.records
                            if _record_key(record) not in fresh_keys
                        ],
                    ]
                    active.metrics = {
                        **dict(active.metrics),
                        **dict(metrics),
                        "prefetch_prior_section_count": int(
                            active.metrics.get("prefetch_prior_section_count", 0) or 0
                        ),
                    }
                    has_other_active_task = any(
                        task is not current_task and not task.done()
                        for task in _cache_tasks(active)
                    )
                    active.status = "running" if has_other_active_task else "completed"
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
                    current_task = asyncio.current_task()
                    has_other_active_task = any(
                        task is not current_task and not task.done()
                        for task in _cache_tasks(active)
                    )
                    active.status = "running" if has_other_active_task else "cancelled"
            raise
        except Exception as exc:
            with _LOCK:
                active = _CACHES.get(key)
                if active is cache:
                    current_task = asyncio.current_task()
                    has_other_active_task = any(
                        task is not current_task and not task.done()
                        for task in _cache_tasks(active)
                    )
                    active.status = "running" if has_other_active_task else "failed"
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


def start_docgen_kg_prefetch_incremental(
    *,
    course_id: str,
    build_session_id: str,
    chapters: list[dict[str, Any]],
    document_backbone: dict[str, Any] | None = None,
    docgen_manifest: dict[str, Any] | None = None,
    llm_snapshot: LLMRuntimeSnapshot | None = None,
) -> bool:
    """Start an additive chapter-level KG prefetch task without cancelling the active refresh."""

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
        cache = _CACHES.get(key)
        if cache is None:
            cache = _PrefetchCache(course_id=course_id, build_session_id=build_session_id)
            _CACHES[key] = cache
        prior_records = list(cache.records)
        cache.status = "running"
        cache.metrics["prefetch_incremental_task_count"] = int(
            cache.metrics.get("prefetch_incremental_task_count", 0) or 0
        ) + 1

    snapshot = llm_snapshot or capture_llm_runtime_snapshot()
    structured_context = _structured_context(
        chapters=chapters,
        document_backbone=document_backbone,
        docgen_manifest=docgen_manifest,
    )
    configured_concurrency = int(settings.knowledge_graph.prefetch_concurrency or 1)
    llm_concurrency_cap = _graph_llm_concurrency_cap()
    concurrency = _prefetch_concurrency_limit(
        configured_concurrency,
        global_limit=llm_concurrency_cap,
    )
    with _LOCK:
        cache.metrics.update(
            {
                "prefetch_configured_concurrency": configured_concurrency,
                "prefetch_llm_concurrency_cap": llm_concurrency_cap,
                "prefetch_effective_concurrency": concurrency,
            }
        )

    def _on_record(record: SectionExtractionRecord) -> None:
        with _LOCK:
            active = _CACHES.get(key)
            if active is cache:
                active.records.append(record)

    async def _run() -> None:
        try:
            with managed_session() as session:
                course_context = load_course_llm_context(session, course_id=course_id)
            _records, metrics = await _extract_prefetch_records_with_trace(
                course_id=course_id,
                build_session_id=build_session_id,
                markdown=markdown,
                chapters=chapters,
                course_context=course_context,
                structured_context=structured_context,
                docgen_manifest=docgen_manifest,
                snapshot=snapshot,
                concurrency=concurrency,
                configured_concurrency=configured_concurrency,
                llm_concurrency_cap=llm_concurrency_cap,
                incremental=True,
                on_record=_on_record,
                prefetched_records=prior_records,
            )
            with _LOCK:
                active = _CACHES.get(key)
                if active is cache:
                    current_task = asyncio.current_task()
                    fresh_keys = {_record_key(record) for record in _records}
                    active.records = [
                        *_records,
                        *[
                            record
                            for record in active.records
                            if _record_key(record) not in fresh_keys
                        ],
                    ]
                    active.metrics = {
                        **dict(active.metrics),
                        **dict(metrics),
                    }
                    has_other_active_task = any(
                        task is not current_task and not task.done()
                        for task in _cache_tasks(active)
                    )
                    active.status = "running" if has_other_active_task else "completed"
            logger.info(
                "docgen_kg_prefetch_incremental_completed",
                course_id=course_id,
                build_session_id=build_session_id,
                record_count=len(_records),
                chapter_count=len(chapters),
                concurrency=concurrency,
            )
        except asyncio.CancelledError:
            with _LOCK:
                active = _CACHES.get(key)
                if active is cache:
                    current_task = asyncio.current_task()
                    has_other_active_task = any(
                        task is not current_task and not task.done()
                        for task in _cache_tasks(active)
                    )
                    active.status = "running" if has_other_active_task else "cancelled"
            raise
        except Exception as exc:
            with _LOCK:
                active = _CACHES.get(key)
                if active is cache:
                    current_task = asyncio.current_task()
                    has_other_active_task = any(
                        task is not current_task and not task.done()
                        for task in _cache_tasks(active)
                    )
                    active.status = "running" if has_other_active_task else "failed"
                    active.error = str(exc)
            logger.warning(
                "docgen_kg_prefetch_incremental_failed",
                course_id=course_id,
                build_session_id=build_session_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )

    task = asyncio.create_task(_run(), name=f"docgen.kg_prefetch.incremental:{course_id}:{build_session_id}")
    with _LOCK:
        active = _CACHES.get(key)
        if active is cache:
            active.tasks.append(task)
    logger.info(
        "docgen_kg_prefetch_incremental_started",
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
    """Return finished prefetch records and stop any leftover sidecar calls."""

    key = _key(course_id, build_session_id)
    with _LOCK:
        cache = _CACHES.get(key)
    if cache is None:
        return [], {"prefetch_status": "missing"}
    active_tasks = _active_cache_tasks(cache)
    if active_tasks and wait_timeout_s > 0:
        try:
            done, _pending = await asyncio.wait(active_tasks, timeout=wait_timeout_s)
            for task in done:
                task.result()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
    active_tasks = _active_cache_tasks(cache)
    if active_tasks:
        cache.status = "consumed_cancelled"
        for task in active_tasks:
            task.cancel()
        await asyncio.gather(*active_tasks, return_exceptions=True)
        _cleanup_consumed_cache_when_done(key, cache)
    else:
        _drop_cache_if_current(key, cache)
    with _LOCK:
        records = list(cache.records)
        metrics = _prefetch_metrics_snapshot(cache)
    return records, metrics


async def await_docgen_kg_prefetch(
    *,
    course_id: str,
    build_session_id: str,
    wait_timeout_s: float = _PREFETCH_AWAIT_GRACE_S,
) -> dict[str, int | str]:
    """Wait for the DocGen KG prefetch task without consuming its cache."""

    key = _key(course_id, build_session_id)
    with _LOCK:
        cache = _CACHES.get(key)
    if cache is None:
        return {
            "prefetch_status": "missing",
            "prefetch_section_count": 0,
            "prefetch_failed_section_count": 0,
            "prefetch_ready": 0,
        }
    active_tasks = _active_cache_tasks(cache)
    if active_tasks and wait_timeout_s > 0:
        try:
            done, _pending = await asyncio.wait(active_tasks, timeout=wait_timeout_s)
            for task in done:
                task.result()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
    with _LOCK:
        active = _CACHES.get(key)
        if active is not cache:
            return {
                "prefetch_status": "missing",
                "prefetch_section_count": 0,
                "prefetch_failed_section_count": 0,
                "prefetch_ready": 0,
            }
        return _prefetch_metrics_snapshot(cache)


def snapshot_docgen_kg_prefetch(
    *,
    course_id: str,
    build_session_id: str,
) -> tuple[list[SectionExtractionRecord], dict[str, int | str]]:
    """Return a non-consuming snapshot of DocGen KG prefetch records."""

    key = _key(course_id, build_session_id)
    with _LOCK:
        cache = _CACHES.get(key)
        if cache is None:
            return [], {
                "prefetch_status": "missing",
                "prefetch_section_count": 0,
                "prefetch_failed_section_count": 0,
                "prefetch_ready": 0,
            }
        return list(cache.records), _prefetch_metrics_snapshot(cache)


def cancel_docgen_kg_prefetch(*, course_id: str, build_session_id: str) -> None:
    key = _key(course_id, build_session_id)
    with _LOCK:
        cache = _CACHES.pop(key, None)
    if cache is not None:
        _cancel_cache_tasks(cache)


__all__ = [
    "await_docgen_kg_prefetch",
    "cancel_docgen_kg_prefetch",
    "consume_docgen_kg_prefetch",
    "snapshot_docgen_kg_prefetch",
    "start_docgen_kg_prefetch",
    "start_docgen_kg_prefetch_incremental",
]

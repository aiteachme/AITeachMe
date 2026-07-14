"""Application-level registry for long-running background tasks."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import inspect
from threading import RLock
from typing import Any, Callable
from uuid import uuid4

import structlog

from app.utils.time import utcnow

logger = structlog.get_logger()


@dataclass(slots=True)
class ManagedTaskRecord:
    """Metadata describing one spawned background task."""

    task_id: str
    task: asyncio.Task[Any]
    kind: str
    course_id: str | None
    name: str
    created_at: object
    dedupe_key: str | None = None
    cancel_cleanup: Callable[[], Any] | None = None


_DEFAULT_KIND_LIMITS: dict[str, int] = {
    "courses.delete.cleanup": 1,
    "courses.icon_refine": 2,
    "exam.generate": 2,
    "exam.prewarm": 1,
    "exam.study_guide": 2,
    "files.index": 2,
    "files.parse": 2,
    "ingest.enhance": 3,
    "ingest.enhance.recovery": 2,
    "ingest.recovery": 1,
    "knowledge.build.docs": 1,
    "knowledge.build.graph": 1,
}


class BackgroundTaskRegistry:
    """Track API-triggered background tasks so they can be cancelled on shutdown."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._tasks: dict[str, ManagedTaskRecord] = {}
        self._tasks_by_dedupe_key: dict[str, str] = {}
        self._scoped_semaphores: dict[tuple[str, str], asyncio.Semaphore] = {}

    def spawn(
        self,
        coro,
        *,
        kind: str,
        course_id: str | None = None,
        name: str | None = None,
        dedupe_key: str | None = None,
        max_concurrency: int | None = None,
        cancel_cleanup: Callable[[], Any] | None = None,
    ) -> asyncio.Task[Any]:
        """Create and register a tracked task with optional local admission control."""

        task_name = name or f"{kind}:{course_id or 'global'}"
        normalized_dedupe_key = str(dedupe_key or "").strip() or None
        with self._lock:
            if normalized_dedupe_key is not None:
                existing_task_id = self._tasks_by_dedupe_key.get(normalized_dedupe_key)
                existing_record = self._tasks.get(existing_task_id or "")
                if existing_record is not None and not existing_record.task.done():
                    _close_unstarted_coroutine(coro)
                    logger.info(
                        "background_task_deduplicated",
                        existing_task_id=existing_task_id,
                        kind=kind,
                        course_id=course_id,
                        name=task_name,
                        dedupe_key=normalized_dedupe_key,
                    )
                    return existing_record.task
                if existing_task_id is not None:
                    self._tasks_by_dedupe_key.pop(normalized_dedupe_key, None)

        effective_limit = _normalize_kind_limit(kind, max_concurrency=max_concurrency)
        guarded_coro = self._run_with_kind_limit(coro, kind=kind, course_id=course_id, limit=effective_limit)
        task = asyncio.create_task(guarded_coro, name=task_name)
        record = ManagedTaskRecord(
            task_id=uuid4().hex,
            task=task,
            kind=kind,
            course_id=course_id,
            name=task_name,
            created_at=utcnow(),
            dedupe_key=normalized_dedupe_key,
            cancel_cleanup=cancel_cleanup,
        )
        with self._lock:
            self._tasks[record.task_id] = record
            if normalized_dedupe_key is not None:
                self._tasks_by_dedupe_key[normalized_dedupe_key] = record.task_id
        task.add_done_callback(
            lambda finished_task, task_id=record.task_id: self._finalize_task(task_id, finished_task)
        )
        logger.info(
            "background_task_spawned",
            task_id=record.task_id,
            kind=kind,
            course_id=course_id,
            name=task_name,
            dedupe_key=normalized_dedupe_key,
            max_concurrency=effective_limit,
        )
        return task

    async def _run_with_kind_limit(self, coro, *, kind: str, course_id: str | None, limit: int | None) -> Any:
        started = False
        try:
            if limit is None:
                started = True
                return await coro
            semaphore = self._get_scoped_semaphore(kind, course_id=course_id, limit=limit)
            async with semaphore:
                started = True
                return await coro
        finally:
            if not started:
                _close_unstarted_coroutine(coro)

    def _get_scoped_semaphore(self, kind: str, *, course_id: str | None, limit: int) -> asyncio.Semaphore:
        scope = str(course_id or "global").strip() or "global"
        key = (kind, scope)
        with self._lock:
            semaphore = self._scoped_semaphores.get(key)
            if semaphore is None:
                semaphore = asyncio.Semaphore(max(1, int(limit)))
                self._scoped_semaphores[key] = semaphore
            return semaphore

    def _finalize_task(self, task_id: str, task: asyncio.Task[Any]) -> None:
        with self._lock:
            record = self._tasks.pop(task_id, None)
            if record is not None and record.dedupe_key is not None:
                if self._tasks_by_dedupe_key.get(record.dedupe_key) == task_id:
                    self._tasks_by_dedupe_key.pop(record.dedupe_key, None)
        if record is None:
            return
        if task.cancelled():
            logger.info(
                "background_task_cancelled",
                task_id=task_id,
                kind=record.kind,
                course_id=record.course_id,
                name=record.name,
            )
            return
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            logger.info(
                "background_task_cancelled",
                task_id=task_id,
                kind=record.kind,
                course_id=record.course_id,
                name=record.name,
            )
            return
        if exc is not None:
            logger.error(
                "background_task_failed",
                task_id=task_id,
                kind=record.kind,
                course_id=record.course_id,
                name=record.name,
                error=str(exc),
            )
            return
        logger.info(
            "background_task_completed",
            task_id=task_id,
            kind=record.kind,
            course_id=record.course_id,
            name=record.name,
        )

    async def cancel_matching(
        self,
        *,
        kind: str | None = None,
        course_id: str | None = None,
        name: str | None = None,
        timeout_s: float = 3.0,
    ) -> int:
        """Cancel active tasks matching kind, course, and exact name."""

        with self._lock:
            records = [
                record
                for record in self._tasks.values()
                if (kind is None or record.kind == kind)
                and (course_id is None or record.course_id == course_id)
                and (name is None or record.name == name)
            ]
        if not records:
            return 0

        for record in records:
            record.task.cancel()

        done, pending = await asyncio.wait(
            [record.task for record in records],
            timeout=max(0.1, float(timeout_s)),
        )
        await self._run_confirmed_cancel_cleanups(records, done=done)
        if pending:
            logger.warning(
                "background_task_cancel_timeout",
                kind=kind,
                course_id=course_id,
                name=name,
                completed=len(done),
                pending=len(pending),
            )
        return len(records)

    async def shutdown(self, *, cancel_timeout_s: float = 5.0) -> None:
        """Cancel all tracked tasks and wait briefly for cleanup."""

        with self._lock:
            records = list(self._tasks.values())
        if not records:
            return

        logger.info(
            "background_task_shutdown_started",
            task_count=len(records),
            cancel_timeout_s=cancel_timeout_s,
        )
        for record in records:
            record.task.cancel()

        done, pending = await asyncio.wait(
            [record.task for record in records],
            timeout=cancel_timeout_s,
        )
        await self._run_confirmed_cancel_cleanups(records, done=done)
        if pending:
            logger.warning(
                "background_task_shutdown_timeout",
                completed=len(done),
                pending=len(pending),
            )
        logger.info("background_task_shutdown_completed", completed=len(done), pending=len(pending))

    async def _run_confirmed_cancel_cleanups(
        self,
        records: list[ManagedTaskRecord],
        *,
        done: set[asyncio.Task[Any]],
    ) -> None:
        """Run owner cleanup only after cancellation has fully completed."""

        for record in records:
            cleanup = record.cancel_cleanup
            if cleanup is None or record.task not in done or not record.task.cancelled():
                continue
            try:
                result = cleanup()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception(
                    "background_task_cancel_cleanup_failed",
                    task_id=record.task_id,
                    kind=record.kind,
                    course_id=record.course_id,
                    name=record.name,
                )


def _normalize_kind_limit(kind: str, *, max_concurrency: int | None) -> int | None:
    if max_concurrency is not None:
        return max(1, int(max_concurrency))
    configured = _DEFAULT_KIND_LIMITS.get(kind)
    if configured is None:
        return None
    return max(1, int(configured))


def _close_unstarted_coroutine(coro) -> None:
    if inspect.iscoroutine(coro):
        coro.close()


__all__ = ["BackgroundTaskRegistry", "ManagedTaskRecord"]

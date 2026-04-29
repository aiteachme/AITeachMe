"""Application-level registry for long-running background tasks."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from threading import RLock
from typing import Any
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


class BackgroundTaskRegistry:
    """Track API-triggered background tasks so they can be cancelled on shutdown."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._tasks: dict[str, ManagedTaskRecord] = {}

    def spawn(
        self,
        coro,
        *,
        kind: str,
        course_id: str | None = None,
        name: str | None = None,
    ) -> asyncio.Task[Any]:
        """Create and register a tracked task."""

        task_name = name or f"{kind}:{course_id or 'global'}"
        task = asyncio.create_task(coro, name=task_name)
        record = ManagedTaskRecord(
            task_id=uuid4().hex,
            task=task,
            kind=kind,
            course_id=course_id,
            name=task_name,
            created_at=utcnow(),
        )
        with self._lock:
            self._tasks[record.task_id] = record
        task.add_done_callback(
            lambda finished_task, task_id=record.task_id: self._finalize_task(task_id, finished_task)
        )
        logger.info(
            "background_task_spawned",
            task_id=record.task_id,
            kind=kind,
            course_id=course_id,
            name=task_name,
        )
        return task

    def _finalize_task(self, task_id: str, task: asyncio.Task[Any]) -> None:
        with self._lock:
            record = self._tasks.pop(task_id, None)
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
        timeout_s: float = 3.0,
    ) -> int:
        """Cancel active tasks matching kind and course, returning task count."""

        with self._lock:
            records = [
                record
                for record in self._tasks.values()
                if (kind is None or record.kind == kind)
                and (course_id is None or record.course_id == course_id)
            ]
        if not records:
            return 0

        for record in records:
            record.task.cancel()

        done, pending = await asyncio.wait(
            [record.task for record in records],
            timeout=max(0.1, float(timeout_s)),
        )
        if pending:
            logger.warning(
                "background_task_cancel_timeout",
                kind=kind,
                course_id=course_id,
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
        if pending:
            logger.warning(
                "background_task_shutdown_timeout",
                completed=len(done),
                pending=len(pending),
            )
            await asyncio.gather(*pending, return_exceptions=True)
        logger.info("background_task_shutdown_completed", completed=len(done), pending=len(pending))


__all__ = ["BackgroundTaskRegistry", "ManagedTaskRecord"]

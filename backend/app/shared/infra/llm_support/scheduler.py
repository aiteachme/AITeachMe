"""Shared async task scheduling for LLM-oriented work."""

from __future__ import annotations

import asyncio
import itertools
import time
import weakref
from collections.abc import Awaitable, Callable, Iterable, Mapping
from contextvars import Context, ContextVar, copy_context
from dataclasses import dataclass, field
from typing import Any, Generic, Literal, TypeVar

from langsmith import tracing_context
from langsmith.run_helpers import get_current_run_tree

from .common import get_llm_concurrency_limit

T = TypeVar("T")
R = TypeVar("R")
LLMTaskStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
_INSIDE_LLM_TASK: ContextVar[bool] = ContextVar("inside_llm_task", default=False)


@dataclass(frozen=True)
class LLMTaskSnapshot:
    """Point-in-time view of one scheduled LLM task."""

    task_id: str
    status: LLMTaskStatus
    label: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None


@dataclass
class _LLMTask(Generic[R]):
    task_id: str
    factory: Callable[[], Awaitable[R]]
    future: asyncio.Future[R]
    label: str | None
    metadata: dict[str, Any]
    created_at: float
    context: Context
    langsmith_parent: Any | None = None
    status: LLMTaskStatus = "queued"
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None
    runner: asyncio.Task[None] | None = None


class LLMTaskHandle(Generic[R]):
    """Handle returned by the shared LLM task scheduler."""

    def __init__(self, scheduler: "LLMTaskScheduler", task_id: str, future: asyncio.Future[R]) -> None:
        self._scheduler = scheduler
        self.task_id = task_id
        self._future = future

    def cancel(self) -> bool:
        return self._scheduler.cancel(self.task_id)

    def done(self) -> bool:
        return self._future.done()

    async def result(self) -> R:
        return await self._future

    def snapshot(self) -> LLMTaskSnapshot | None:
        return self._scheduler.get(self.task_id)

    def update(
        self,
        *,
        label: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> bool:
        return self._scheduler.update(self.task_id, label=label, metadata=metadata)

    def forget(self) -> bool:
        return self._scheduler.forget(self.task_id)


class LLMTaskScheduler:
    """Loop-local dynamic scheduler for upper-level LLM tasks.

    Actual provider calls still use ``get_llm_concurrency_limiter().slot()``. This
    scheduler controls workflow fan-out and background LLM work, while the
    provider limiter remains the final guard for every single model request.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, _LLMTask[Any]] = {}
        self._counter = itertools.count(1)
        self._active = 0
        self._changed = asyncio.Event()
        self._lock = asyncio.Lock()

    def submit(
        self,
        factory: Callable[[], Awaitable[R]],
        *,
        label: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> LLMTaskHandle[R]:
        loop = asyncio.get_running_loop()
        task_id = f"llm-task-{next(self._counter)}"
        future: asyncio.Future[R] = loop.create_future()
        task_context = copy_context()
        task: _LLMTask[R] = _LLMTask(
            task_id=task_id,
            factory=factory,
            future=future,
            label=label,
            metadata=dict(metadata or {}),
            created_at=time.monotonic(),
            context=task_context,
            langsmith_parent=_current_langsmith_run_tree(task_context),
        )
        self._tasks[task_id] = task
        runner = self._run_inline(task) if _INSIDE_LLM_TASK.get() else self._run(task)
        task.runner = asyncio.create_task(runner, name=label or task_id, context=task_context)
        return LLMTaskHandle(self, task_id, future)

    async def run_many(
        self,
        items: Iterable[T],
        worker: Callable[[T], Awaitable[R]],
        *,
        max_concurrent: int | None = None,
        on_result: Callable[[int, T, R], Awaitable[None]] | None = None,
    ) -> list[R]:
        indexed_items = list(enumerate(items))
        if not indexed_items:
            return []

        if _INSIDE_LLM_TASK.get():
            return await _run_nested_llm_tasks(
                indexed_items,
                worker,
                max_concurrent=max_concurrent,
                on_result=on_result,
            )
        return await self._run_pooled_many(
            indexed_items,
            worker,
            max_concurrent=max_concurrent,
            on_result=on_result,
        )

    def get(self, task_id: str) -> LLMTaskSnapshot | None:
        task = self._tasks.get(task_id)
        return self._snapshot(task) if task is not None else None

    def list(self) -> list[LLMTaskSnapshot]:
        return [self._snapshot(task) for task in self._tasks.values()]

    def update(
        self,
        task_id: str,
        *,
        label: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> bool:
        task = self._tasks.get(task_id)
        if task is None:
            return False
        if label is not None:
            task.label = label
        if metadata:
            task.metadata.update(dict(metadata))
        return True

    def cancel(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task is None or task.status in {"succeeded", "failed", "cancelled"}:
            return False
        task.status = "cancelled"
        task.finished_at = time.monotonic()
        if not task.future.done():
            task.future.cancel()
        if task.runner is not None and not task.runner.done():
            task.runner.cancel()
        self._notify_changed()
        return True

    def forget(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task is None or task.status not in {"succeeded", "failed", "cancelled"}:
            return False
        self._tasks.pop(task_id, None)
        return True

    async def _run(self, task: _LLMTask[R]) -> None:
        acquired = False
        token = None
        try:
            await self._acquire_slot(task)
            acquired = True
            token = _INSIDE_LLM_TASK.set(True)
            result = await _run_factory_with_langsmith_parent(task)
        except asyncio.CancelledError:
            self._mark_cancelled(task)
            raise
        except Exception as exc:
            self._mark_failed(task, exc)
        except BaseException as exc:
            self._mark_failed(task, self._coerce_task_exception(exc))
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
        else:
            self._mark_succeeded(task, result)
        finally:
            if token is not None:
                _INSIDE_LLM_TASK.reset(token)
            if acquired:
                await self._release_slot()

    async def _run_inline(self, task: _LLMTask[R]) -> None:
        token = None
        try:
            if task.status == "cancelled":
                raise asyncio.CancelledError()
            task.status = "running"
            task.started_at = time.monotonic()
            self._notify_changed()
            token = _INSIDE_LLM_TASK.set(True)
            result = await _run_factory_with_langsmith_parent(task)
        except asyncio.CancelledError:
            self._mark_cancelled(task)
            raise
        except Exception as exc:
            self._mark_failed(task, exc)
        except BaseException as exc:
            self._mark_failed(task, self._coerce_task_exception(exc))
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
        else:
            self._mark_succeeded(task, result)
        finally:
            if token is not None:
                _INSIDE_LLM_TASK.reset(token)

    async def _acquire_slot(self, task: _LLMTask[Any]) -> None:
        while True:
            async with self._lock:
                if task.status == "cancelled":
                    raise asyncio.CancelledError()
                if self._active < get_llm_concurrency_limit():
                    self._active += 1
                    task.status = "running"
                    task.started_at = time.monotonic()
                    return
                changed = self._changed
            try:
                await asyncio.wait_for(changed.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                pass

    async def _release_slot(self) -> None:
        async with self._lock:
            self._active = max(0, self._active - 1)
            self._notify_changed()

    def _mark_succeeded(self, task: _LLMTask[R], result: R) -> None:
        task.status = "succeeded"
        task.finished_at = time.monotonic()
        if not task.future.done():
            task.future.set_result(result)

    def _mark_failed(self, task: _LLMTask[Any], exc: Exception) -> None:
        task.status = "failed"
        task.error = f"{type(exc).__name__}: {exc}"
        task.finished_at = time.monotonic()
        if not task.future.done():
            task.future.set_exception(exc)

    @staticmethod
    def _coerce_task_exception(exc: BaseException) -> Exception:
        if isinstance(exc, Exception):
            return exc
        detail = str(exc).strip()
        message = f"LLM task aborted with {type(exc).__name__}"
        if detail:
            message = f"{message}: {detail}"
        return RuntimeError(message)

    def _mark_cancelled(self, task: _LLMTask[Any]) -> None:
        task.status = "cancelled"
        task.finished_at = time.monotonic()
        if not task.future.done():
            task.future.cancel()

    def _notify_changed(self) -> None:
        self._changed.set()
        self._changed = asyncio.Event()

    @staticmethod
    def _snapshot(task: _LLMTask[Any]) -> LLMTaskSnapshot:
        return LLMTaskSnapshot(
            task_id=task.task_id,
            status=task.status,
            label=task.label,
            metadata=dict(task.metadata),
            created_at=task.created_at,
            started_at=task.started_at,
            finished_at=task.finished_at,
            error=task.error,
        )

    async def _run_pooled_many(
        self,
        indexed_items: list[tuple[int, T]],
        worker: Callable[[T], Awaitable[R]],
        *,
        max_concurrent: int | None,
        on_result: Callable[[int, T, R], Awaitable[None]] | None,
    ) -> list[R]:
        async def _run_one(index: int, item: T) -> tuple[int, T, R]:
            result = await worker(item)
            return index, item, result

        async def _await_one(handle: LLMTaskHandle[tuple[int, T, R]]) -> tuple[int, R]:
            index, item, result = await handle.result()
            if on_result is not None:
                await on_result(index, item, result)
            return index, result

        submit_window = _task_window_size(len(indexed_items), max_concurrent=max_concurrent)
        next_position = 0
        running: dict[asyncio.Task[tuple[int, R]], LLMTaskHandle[tuple[int, T, R]]] = {}
        all_handles: list[LLMTaskHandle[tuple[int, T, R]]] = []
        indexed_results: list[tuple[int, R]] = []

        def _submit_until_window_full() -> None:
            nonlocal next_position
            while next_position < len(indexed_items) and len(running) < submit_window:
                index, item = indexed_items[next_position]
                next_position += 1
                handle = self.submit(
                    lambda index=index, item=item: _run_one(index, item),
                    label="llm.batch",
                    metadata={"batch_index": index},
                )
                waiter = asyncio.create_task(_await_one(handle))
                running[waiter] = handle
                all_handles.append(handle)

        _submit_until_window_full()
        try:
            while running:
                done, _pending = await asyncio.wait(
                    running.keys(),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for waiter in done:
                    handle = running.pop(waiter)
                    indexed_results.append(await waiter)
                    handle.forget()
                _submit_until_window_full()
        except asyncio.CancelledError:
            await _cancel_running_tasks(all_handles, running)
            raise
        except Exception:
            await _cancel_running_tasks(all_handles, running)
            raise
        finally:
            for handle in all_handles:
                handle.forget()

        return [
            result
            for _index, result in sorted(indexed_results, key=lambda item: item[0])
        ]


_LLM_SCHEDULERS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, LLMTaskScheduler]" = (
    weakref.WeakKeyDictionary()
)


def get_llm_scheduler() -> LLMTaskScheduler:
    loop = asyncio.get_running_loop()
    scheduler = _LLM_SCHEDULERS.get(loop)
    if scheduler is None:
        scheduler = LLMTaskScheduler()
        _LLM_SCHEDULERS[loop] = scheduler
    return scheduler


def _current_langsmith_run_tree(context: Context) -> Any | None:
    try:
        return context.run(get_current_run_tree)
    except Exception:
        return None


async def _run_factory_with_langsmith_parent(task: _LLMTask[R]) -> R:
    if task.langsmith_parent is None:
        return await task.factory()
    with tracing_context(parent=task.langsmith_parent):
        return await task.factory()


async def run_llm_tasks(
    items: Iterable[T],
    worker: Callable[[T], Awaitable[R]],
    *,
    max_concurrent: int | None = None,
    on_result: Callable[[int, T, R], Awaitable[None]] | None = None,
) -> list[R]:
    """Run a batch of LLM tasks through the shared scheduler."""

    return await get_llm_scheduler().run_many(
        items,
        worker,
        max_concurrent=max_concurrent,
        on_result=on_result,
    )


async def _run_nested_llm_tasks(
    indexed_items: list[tuple[int, T]],
    worker: Callable[[T], Awaitable[R]],
    *,
    max_concurrent: int | None,
    on_result: Callable[[int, T, R], Awaitable[None]] | None,
) -> list[R]:
    window = _task_window_size(len(indexed_items), max_concurrent=max_concurrent)
    semaphore = asyncio.Semaphore(window)

    async def _run_one(index: int, item: T) -> tuple[int, R]:
        async with semaphore:
            result = await worker(item)
            if on_result is not None:
                await on_result(index, item, result)
            return index, result

    indexed_results = await asyncio.gather(
        *(_run_one(index, item) for index, item in indexed_items)
    )
    return [
        result
        for _index, result in sorted(indexed_results, key=lambda item: item[0])
    ]


def _task_window_size(item_count: int, *, max_concurrent: int | None) -> int:
    batch_limit = get_llm_concurrency_limit() if max_concurrent is None else int(max_concurrent or 1)
    return max(1, min(batch_limit, get_llm_concurrency_limit(), item_count))


async def _cancel_running_tasks(
    handles: list[LLMTaskHandle[Any]],
    running: Mapping[asyncio.Task[Any], LLMTaskHandle[Any]],
) -> None:
    for handle in handles:
        handle.cancel()
    for waiter in list(running):
        if not waiter.done():
            waiter.cancel()
    await asyncio.gather(*running.keys(), return_exceptions=True)


__all__ = [
    "LLMTaskHandle",
    "LLMTaskScheduler",
    "LLMTaskSnapshot",
    "get_llm_scheduler",
    "run_llm_tasks",
]

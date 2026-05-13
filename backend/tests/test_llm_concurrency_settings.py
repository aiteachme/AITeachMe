from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from app.shared.infra.llm_support import (
    run_llm_tasks,
    get_llm_concurrency_limit,
    get_llm_concurrency_limiter,
)
from app.shared.infra.llm_support.defaults import DEFAULT_LLM_CONCURRENCY_LIMIT
from app.shared.infra.llm_support.scheduler import get_llm_scheduler
from app.shared.infra.settings import (
    get_settings,
    reset_project_settings_cache,
    set_system_settings_override,
)
from app.workflows.digest.kg_doc_sync.lib.incremental_sync import _graph_llm_concurrency_cap
from app.workflows.ingest.parsing.strategy import build_parse_plan
from app.workflows.support.system.settings import build_settings_overview_data


def _reset_settings_state() -> None:
    reset_project_settings_cache()
    set_system_settings_override({})


@pytest.fixture(autouse=True)
def reset_settings_after_test():
    _reset_settings_state()
    yield
    _reset_settings_state()


def test_llm_concurrency_uses_code_default() -> None:
    assert get_settings().llm.concurrency_limit == DEFAULT_LLM_CONCURRENCY_LIMIT
    assert get_llm_concurrency_limit() == DEFAULT_LLM_CONCURRENCY_LIMIT


def test_llm_concurrency_runtime_settings_override_default() -> None:
    set_system_settings_override({"llm": {"concurrency_limit": 3}})

    assert get_settings().llm.concurrency_limit == 3
    assert get_llm_concurrency_limit() == 3


def test_kg_graph_cap_uses_full_shared_llm_limit() -> None:
    set_system_settings_override({"llm": {"concurrency_limit": 8}})

    assert _graph_llm_concurrency_cap() == 8


def test_ingest_llm_ocr_plan_respects_shared_llm_limit(tmp_path: Path) -> None:
    set_system_settings_override({"llm": {"concurrency_limit": 1}})
    file_path = tmp_path / "notes.txt"
    file_path.write_text("hello", encoding="utf-8")

    plan = build_parse_plan(
        file_path=file_path,
        filetype=".txt",
        file_size_bytes=file_path.stat().st_size,
        classification=None,
    )

    assert plan.options.llm_ocr_page_concurrency == 1


def test_llm_concurrency_is_exposed_in_model_connection_settings() -> None:
    overview = build_settings_overview_data()
    connection = next(section for section in overview.sections if section.id == "connection")
    entry = next(item for item in connection.entries if item.key == "llm.concurrency_limit")

    assert entry.label == "全局 LLM 并发上限"
    assert entry.ui_group == "统一模型接入"
    assert entry.source == "settings"
    assert entry.editable is True
    assert entry.value == DEFAULT_LLM_CONCURRENCY_LIMIT


@pytest.mark.anyio
async def test_llm_limiter_uses_live_runtime_limit() -> None:
    set_system_settings_override({"llm": {"concurrency_limit": 1}})
    limiter = get_llm_concurrency_limiter()
    first_inside = asyncio.Event()
    release_first = asyncio.Event()
    second_inside = asyncio.Event()

    async def first_call() -> None:
        async with limiter:
            first_inside.set()
            await release_first.wait()

    async def second_call() -> None:
        async with limiter:
            second_inside.set()

    first_task = asyncio.create_task(first_call())
    await asyncio.wait_for(first_inside.wait(), timeout=1)
    second_task = asyncio.create_task(second_call())
    await asyncio.sleep(0.05)
    assert not second_inside.is_set()

    set_system_settings_override({"llm": {"concurrency_limit": 2}})
    await asyncio.wait_for(second_inside.wait(), timeout=1)
    release_first.set()
    await asyncio.gather(first_task, second_task)


@pytest.mark.anyio
async def test_llm_limiter_releases_slot_when_holder_is_cancelled() -> None:
    set_system_settings_override({"llm": {"concurrency_limit": 1}})
    limiter = get_llm_concurrency_limiter()
    first_inside = asyncio.Event()
    never_release = asyncio.Event()

    async def holder() -> None:
        async with limiter:
            first_inside.set()
            await never_release.wait()

    holder_task = asyncio.create_task(holder())
    await asyncio.wait_for(first_inside.wait(), timeout=1)
    holder_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await holder_task

    async def next_call() -> bool:
        async with limiter:
            return True

    assert await asyncio.wait_for(next_call(), timeout=1)


@pytest.mark.anyio
async def test_llm_limiter_is_process_wide_across_event_loops() -> None:
    set_system_settings_override({"llm": {"concurrency_limit": 1}})
    limiter = get_llm_concurrency_limiter()
    holder_inside = asyncio.Event()
    release_holder = asyncio.Event()
    thread_entered = threading.Event()
    thread_done = threading.Event()

    async def holder() -> None:
        async with limiter:
            holder_inside.set()
            await release_holder.wait()

    def run_in_thread() -> None:
        async def attempt() -> None:
            async with limiter:
                thread_entered.set()

        asyncio.run(attempt())
        thread_done.set()

    holder_task = asyncio.create_task(holder())
    await asyncio.wait_for(holder_inside.wait(), timeout=1)

    thread = threading.Thread(target=run_in_thread, name="llm-limiter-cross-loop-test")
    thread.start()
    await asyncio.sleep(0.1)
    assert not thread_entered.is_set()

    release_holder.set()
    await holder_task
    assert await asyncio.to_thread(thread_done.wait, 1)
    thread.join(timeout=1)
    assert thread_entered.is_set()


@pytest.mark.anyio
async def test_run_llm_tasks_uses_shared_fanout_limit() -> None:
    set_system_settings_override({"llm": {"concurrency_limit": 2}})
    active = 0
    max_active = 0
    completed: list[tuple[int, int, int]] = []
    first_two_started = asyncio.Event()
    release_workers = asyncio.Event()

    async def worker(value: int) -> int:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        if active == 2:
            first_two_started.set()
        try:
            await release_workers.wait()
            return value * 2
        finally:
            active -= 1

    async def on_result(index: int, item: int, result: int) -> None:
        completed.append((index, item, result))

    results_task = asyncio.create_task(run_llm_tasks(range(6), worker, on_result=on_result))
    await asyncio.wait_for(first_two_started.wait(), timeout=1)
    assert max_active == 2
    release_workers.set()
    results = await results_task

    assert max_active == 2
    assert results == [0, 2, 4, 6, 8, 10]
    assert sorted(completed) == [
        (0, 0, 0),
        (1, 1, 2),
        (2, 2, 4),
        (3, 3, 6),
        (4, 4, 8),
        (5, 5, 10),
    ]


@pytest.mark.anyio
async def test_llm_task_scheduler_accepts_dynamic_submissions() -> None:
    set_system_settings_override({"llm": {"concurrency_limit": 2}})
    scheduler = get_llm_scheduler()
    active = 0
    max_active = 0
    started: list[int] = []
    first_two_started = asyncio.Event()
    release_jobs = asyncio.Event()

    async def worker(value: int) -> int:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        started.append(value)
        if len(started) == 2:
            first_two_started.set()
        try:
            await release_jobs.wait()
            return value
        finally:
            active -= 1

    first = scheduler.submit(lambda: worker(1), label="test.first")
    second = scheduler.submit(lambda: worker(2), label="test.second")
    third = scheduler.submit(lambda: worker(3), label="test.third")

    await asyncio.wait_for(first_two_started.wait(), timeout=1)
    assert max_active == 2
    assert third.snapshot() is not None
    assert third.snapshot().status == "queued"

    fourth = scheduler.submit(lambda: worker(4), label="test.fourth")
    assert fourth.update(metadata={"source": "late-submit"}) is True
    assert fourth.snapshot() is not None
    assert fourth.snapshot().metadata["source"] == "late-submit"

    release_jobs.set()

    results = await asyncio.gather(
        first.result(),
        second.result(),
        third.result(),
        fourth.result(),
    )

    assert sorted(results) == [1, 2, 3, 4]
    assert max_active <= 2
    assert all(handle.snapshot().status == "succeeded" for handle in [first, second, third, fourth])


@pytest.mark.anyio
async def test_run_llm_tasks_batch_limit_does_not_occupy_global_slots() -> None:
    set_system_settings_override({"llm": {"concurrency_limit": 2}})
    gather_started = asyncio.Event()
    release_gather = asyncio.Event()
    late_started = asyncio.Event()

    async def gather_worker(value: int) -> int:
        gather_started.set()
        await release_gather.wait()
        return value

    gather_task = asyncio.create_task(
        run_llm_tasks(range(3), gather_worker, max_concurrent=1)
    )
    await asyncio.wait_for(gather_started.wait(), timeout=1)

    late_results = await asyncio.wait_for(
        run_llm_tasks(
            [None],
            lambda _item: _return_after_event(late_started, 99),
            max_concurrent=1,
        ),
        timeout=1,
    )
    assert late_results == [99]

    release_gather.set()
    assert await gather_task == [0, 1, 2]


@pytest.mark.anyio
async def test_run_llm_tasks_can_be_nested_without_deadlock() -> None:
    set_system_settings_override({"llm": {"concurrency_limit": 1}})

    async def inner_worker(value: int) -> int:
        await asyncio.sleep(0)
        return value * 10

    async def outer_worker(_value: int) -> list[int]:
        return await run_llm_tasks([1, 2], inner_worker)

    result = await asyncio.wait_for(
        run_llm_tasks([0], outer_worker),
        timeout=1,
    )

    assert result == [[10, 20]]


async def _return_after_event(event: asyncio.Event, value: int) -> int:
    event.set()
    return value

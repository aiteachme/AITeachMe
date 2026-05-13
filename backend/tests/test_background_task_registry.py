from __future__ import annotations

import asyncio

import pytest

from app.shared.infra.runtime.tasks import BackgroundTaskRegistry


@pytest.mark.anyio
async def test_background_task_registry_deduplicates_running_key() -> None:
    registry = BackgroundTaskRegistry()
    started = asyncio.Event()
    release = asyncio.Event()
    run_count = 0

    async def job() -> int:
        nonlocal run_count
        run_count += 1
        started.set()
        await release.wait()
        return run_count

    first = registry.spawn(job(), kind="test.registry", dedupe_key="same-key")
    await started.wait()
    second = registry.spawn(job(), kind="test.registry", dedupe_key="same-key")

    assert second is first
    assert run_count == 1

    release.set()
    assert await first == 1
    await registry.shutdown()


@pytest.mark.anyio
async def test_background_task_registry_limits_kind_concurrency() -> None:
    registry = BackgroundTaskRegistry()
    active_count = 0
    max_active_count = 0
    two_started = asyncio.Event()
    third_started = asyncio.Event()
    release = asyncio.Event()

    async def job() -> None:
        nonlocal active_count, max_active_count
        active_count += 1
        max_active_count = max(max_active_count, active_count)
        if active_count == 2:
            two_started.set()
        if active_count == 3:
            third_started.set()
        await release.wait()
        active_count -= 1

    tasks = [
        registry.spawn(job(), kind="test.registry.limited", max_concurrency=2)
        for _ in range(6)
    ]
    await asyncio.wait_for(two_started.wait(), timeout=0.5)
    await asyncio.sleep(0)
    assert not third_started.is_set()

    release.set()
    await asyncio.gather(*tasks)
    await registry.shutdown()

    assert max_active_count == 2


@pytest.mark.anyio
async def test_background_task_registry_limits_are_scoped_by_course() -> None:
    registry = BackgroundTaskRegistry()
    active_count = 0
    max_active_count = 0
    both_started = asyncio.Event()
    release = asyncio.Event()

    async def job() -> None:
        nonlocal active_count, max_active_count
        active_count += 1
        max_active_count = max(max_active_count, active_count)
        if active_count == 2:
            both_started.set()
        await release.wait()
        active_count -= 1

    tasks = [
        registry.spawn(job(), kind="test.registry.scoped", course_id="course_a", max_concurrency=1),
        registry.spawn(job(), kind="test.registry.scoped", course_id="course_b", max_concurrency=1),
    ]
    await asyncio.wait_for(both_started.wait(), timeout=0.5)
    release.set()
    await asyncio.gather(*tasks)
    await registry.shutdown()

    assert max_active_count == 2


@pytest.mark.anyio
async def test_background_task_registry_shutdown_preserves_timeout_for_stubborn_task() -> None:
    registry = BackgroundTaskRegistry()
    started = asyncio.Event()
    release = asyncio.Event()

    async def stubborn_job() -> None:
        started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            await release.wait()

    task = registry.spawn(stubborn_job(), kind="test.registry.stubborn")
    await started.wait()

    await asyncio.wait_for(registry.shutdown(cancel_timeout_s=0.01), timeout=0.5)

    assert not task.done()

    release.set()
    await asyncio.wait_for(task, timeout=0.5)

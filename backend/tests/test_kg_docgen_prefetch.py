from __future__ import annotations

import asyncio

import pytest

from app.workflows.digest.kg_doc_sync.lib import prefetch


def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_consume_docgen_kg_prefetch_cancels_unfinished_sidecar() -> None:
    key = ("course_prefetch_test", "build_prefetch_test")
    started = asyncio.Event()
    release = asyncio.Event()
    was_cancelled = False

    async def _runner() -> None:
        nonlocal was_cancelled
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            was_cancelled = True
            raise

    task = asyncio.create_task(_runner())
    await started.wait()
    cache = prefetch._PrefetchCache(course_id=key[0], build_session_id=key[1], task=task)
    with prefetch._LOCK:
        prefetch._CACHES[key] = cache

    try:
        records, metrics = await prefetch.consume_docgen_kg_prefetch(
            course_id=key[0],
            build_session_id=key[1],
            wait_timeout_s=0.01,
        )

        assert records == []
        assert metrics["prefetch_status"] == "consumed_cancelled"
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)

        with prefetch._LOCK:
            assert prefetch._CACHES.get(key) is None
        assert was_cancelled
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        with prefetch._LOCK:
            prefetch._CACHES.pop(key, None)

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar

import pytest

from app.shared.infra.storage.sync_bridge import run_store_sync


def test_storage_bridge_reuses_one_loop_in_sync_workers_and_preserves_context():
    marker = ContextVar("storage_test_context", default="missing")

    async def read():
        return asyncio.get_running_loop(), marker.get()

    def read_from_worker(value):
        token = marker.set(value)
        try:
            return [run_store_sync(read) for _ in range(3)]
        finally:
            marker.reset(token)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(read_from_worker, ["first", "second"]))
    background_loop = results[0][0][0]
    assert all(loop is background_loop for batch in results for loop, _ in batch)
    assert [value for _, value in results[0]] == ["first"] * 3
    assert [value for _, value in results[1]] == ["second"] * 3
    assert not background_loop.is_closed()


@pytest.mark.anyio
async def test_storage_bridge_can_run_inside_a_loop_and_preserves_error_policy():
    async def read():
        return asyncio.get_running_loop()

    async def fail():
        raise OSError("unavailable")

    assert run_store_sync(read) is not asyncio.get_running_loop()
    assert run_store_sync(fail, default="fallback") == "fallback"
    with pytest.raises(OSError, match="unavailable"):
        run_store_sync(fail)

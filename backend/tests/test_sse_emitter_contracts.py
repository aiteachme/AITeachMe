from __future__ import annotations

import asyncio

import pytest

from app.workflows.interact.chat.lib.streaming import SSEEventEmitter


class _DisconnectedRequest:
    async def is_disconnected(self) -> bool:
        return True


@pytest.mark.anyio
async def test_sse_stream_cancels_workflow_on_disconnect_by_default() -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def _runner() -> None:
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    task = asyncio.create_task(_runner())
    await started.wait()

    async for _payload in SSEEventEmitter().stream(
        request=_DisconnectedRequest(),
        workflow_task=task,
    ):
        pass

    assert cancelled.is_set()
    assert task.cancelled()


@pytest.mark.anyio
async def test_sse_stream_can_detach_workflow_on_disconnect() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    completed = asyncio.Event()

    async def _runner() -> None:
        started.set()
        await release.wait()
        completed.set()

    task = asyncio.create_task(_runner())
    await started.wait()

    async for _payload in SSEEventEmitter().stream(
        request=_DisconnectedRequest(),
        workflow_task=task,
        cancel_on_disconnect=False,
    ):
        pass

    assert not task.cancelled()
    assert not task.done()

    release.set()
    await asyncio.wait_for(task, timeout=1)
    assert completed.is_set()

from __future__ import annotations

import asyncio
import threading
from contextvars import ContextVar

import pytest

from app.shared.infra.workflow import workflow_tracer
from app.workflows.digest.common.node_tracing import traced_digest_node


@pytest.mark.anyio
async def test_sync_digest_node_keeps_loop_responsive_and_drains_cancelled_write() -> None:
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    request_context = ContextVar("digest_test_context", default="missing")
    observed = []
    loop_thread = threading.get_ident()

    def write_node(state):
        observed.append((threading.get_ident(), request_context.get()))
        started.set()
        assert release.wait(timeout=5)
        finished.set()
        return {"saved": True}

    node = traced_digest_node(
        workflow_tracer(workflow="digest.test", lane="test"), node_key="write",
        display_name="write", details={}, handler=write_node,
    )
    token = request_context.set("current-request")
    task = asyncio.create_task(node({"course_id": "test"}))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        assert observed[0][0] != loop_thread
        assert observed[0][1] == "current-request"
        assert not finished.is_set()
        for _ in range(2):
            task.cancel()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)
        assert finished.is_set()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        request_context.reset(token)


@pytest.mark.anyio
async def test_async_digest_node_keeps_callbacks_on_event_loop() -> None:
    loop_thread = threading.get_ident()

    async def node_handler(state):
        assert threading.get_ident() == loop_thread
        assert asyncio.get_running_loop()
        return {"saved": True}

    node = traced_digest_node(
        workflow_tracer(workflow="digest.test"), node_key="callback",
        display_name="callback", details={}, handler=node_handler,
    )
    assert await node({}) == {"saved": True}

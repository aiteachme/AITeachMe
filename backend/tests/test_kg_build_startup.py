from __future__ import annotations

import asyncio
import threading

import pytest

from app.utils.time import utcnow
from app.workflows.digest.kg_doc_sync.lib import builds


async def run_build():
    return await builds.run_graph_docs_sync_auto_build(
        course_id="course-startup", requested_at=utcnow(), build_group_id="group-startup",
        build_session_id="session-startup", file_ids=[], prompt=None,
    )


@pytest.mark.anyio
async def test_graph_version_read_failure_records_failed_status(monkeypatch):
    statuses = []

    def unavailable_version(*args, **kwargs):
        raise OSError("document version read failed")

    monkeypatch.setattr(builds, "_current_doc_version_no", unavailable_version)
    monkeypatch.setattr(builds, "_write_graph_status", lambda *args, **kwargs: statuses.append(kwargs))
    assert await run_build() == "failed"
    assert len(statuses) == 1
    assert statuses[0]["status"] == "failed"
    assert statuses[0]["error_message"] == "document version read failed"


@pytest.mark.anyio
async def test_graph_startup_cancellation_drains_version_read_and_records_cancelled(monkeypatch):
    loop = asyncio.get_running_loop()
    loop_thread = threading.get_ident()
    reading = asyncio.Event()
    release_read = threading.Event()
    finished_read = threading.Event()
    statuses = []

    def read_version(*args, **kwargs):
        assert threading.get_ident() != loop_thread
        loop.call_soon_threadsafe(reading.set)
        assert release_read.wait(5)
        finished_read.set()
        return 3

    def write_status(*args, **kwargs):
        assert threading.get_ident() != loop_thread
        assert finished_read.is_set()
        statuses.append(kwargs["status"])

    monkeypatch.setattr(builds, "_current_doc_version_no", read_version)
    monkeypatch.setattr(builds, "_write_graph_status", write_status)
    task = asyncio.create_task(run_build())
    try:
        await asyncio.wait_for(reading.wait(), 5)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release_read.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert statuses == ["cancelled"]
    finally:
        release_read.set()
        await asyncio.gather(task, return_exceptions=True)

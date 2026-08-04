from __future__ import annotations

import asyncio
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

from app.shared.infra.llm_support import (
    run_llm_tasks,
    get_llm_concurrency_limit,
    get_llm_concurrency_limiter,
)
from app.shared.infra.llm_support import common as llm_common
from app.shared.infra.llm_support import scheduler as scheduler_module
from app.shared.infra.llm_support.defaults import DEFAULT_LLM_CONCURRENCY_LIMIT
from app.shared.infra.llm_support.scheduler import get_llm_scheduler
from app.shared.infra.settings import (
    get_settings,
    reset_project_settings_cache,
    set_system_settings_override,
)
from app.workflows.digest.kg_doc_sync.lib.incremental_sync import _graph_llm_concurrency_cap
from app.workflows.ingest.parsing.strategy import build_parse_plan
from app.workflows.support.system.settings import (
    build_settings_overview_data,
    get_model_reasoning_capabilities,
)


def _reset_settings_state() -> None:
    reset_project_settings_cache()
    set_system_settings_override({})
    llm_common._LLM_LIMITER = None


@pytest.fixture(autouse=True)
def reset_settings_after_test():
    _reset_settings_state()
    yield
    _reset_settings_state()


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
    unified_entries = [item for item in connection.entries if item.ui_group == "统一模型接入"]
    unified_keys = [item.key for item in sorted(unified_entries, key=lambda item: item.ui_order)]

    assert entry.label == "全局 LLM 并发上限"
    assert entry.ui_group == "统一模型接入"
    assert entry.source == "settings"
    assert entry.editable is True
    assert entry.value == DEFAULT_LLM_CONCURRENCY_LIMIT
    assert unified_keys.index("llm.concurrency_limit") < unified_keys.index("llm.provider")
    assert unified_keys.index("llm.concurrency_limit") < unified_keys.index("llm.api_mode")


def test_fallback_models_default_to_inheriting_main_slots_and_are_exposed() -> None:
    overview = build_settings_overview_data()
    models_section = next(section for section in overview.sections if section.id == "models")
    fallback_entries = {
        entry.key: entry
        for entry in models_section.entries
        if entry.key.startswith("fallback_models.")
    }

    assert get_settings().fallback_models.model_dump() == {
        "light": None,
        "primary": None,
        "reason": None,
    }
    assert set(fallback_entries) == {
        "fallback_models.light",
        "fallback_models.primary",
        "fallback_models.reason",
    }
    assert all(entry.value is None for entry in fallback_entries.values())
    assert all(entry.editable is True for entry in fallback_entries.values())


def test_legacy_llm_routing_settings_are_upgraded_without_overriding_new_slots() -> None:
    set_system_settings_override({
        "llm": {
            "reasoning_effort": "high",
            "reasoning_efforts": {"reason": "xhigh"},
            "primary_model_allowlist": ["gpt-5.4-mini"],
        },
    })

    settings = get_settings()
    assert settings.llm.reasoning_efforts.model_dump() == {
        "light": "high",
        "primary": "high",
        "reason": "xhigh",
    }
    assert not hasattr(settings.llm, "primary_model_allowlist")


def test_reasoning_effort_selects_are_derived_from_each_effective_model() -> None:
    set_system_settings_override({
        "models": {
            "light": "gpt-4.1",
            "primary": "gpt-5.3-codex-spark",
            "reason": "gpt-5.6-sol",
        },
        "llm": {
            "reasoning_efforts": {
                "primary": "low",
                "reason": "max",
            },
        },
    })

    overview = build_settings_overview_data()
    models_section = next(section for section in overview.sections if section.id == "models")
    entries = {entry.key: entry for entry in models_section.entries}

    assert entries["llm.reasoning_efforts.light"].options == []
    assert entries["llm.reasoning_efforts.light"].ui_parent_key == "models.light"
    assert [option.value for option in entries["llm.reasoning_efforts.primary"].options] == [
        None,
        "low",
        "medium",
        "high",
        "xhigh",
    ]
    assert [option.value for option in entries["llm.reasoning_efforts.reason"].options] == [
        None,
        "none",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    ]
    assert entries["llm.reasoning_efforts.primary"].value == "low"
    assert entries["llm.reasoning_efforts.reason"].value == "max"
    assert entries["llm.reasoning_efforts.primary"].ui_parent_key == "models.primary"
    assert entries["llm.reasoning_efforts.reason"].ui_parent_key == "models.reason"


def test_known_non_reasoning_model_clears_stale_overview_effort() -> None:
    set_system_settings_override({
        "models": {"primary": "gpt-5.2-chat-latest"},
        "llm": {"reasoning_efforts": {"primary": "high"}},
    })

    overview = build_settings_overview_data()
    models_section = next(section for section in overview.sections if section.id == "models")
    entry = next(
        entry
        for entry in models_section.entries
        if entry.key == "llm.reasoning_efforts.primary"
    )

    assert entry.options == []
    assert entry.value is None


def test_model_reasoning_capabilities_preserve_known_unknown_distinction() -> None:
    assert get_model_reasoning_capabilities(" gpt-5.5 ").reasoning_efforts == [
        "none",
        "low",
        "medium",
        "high",
        "xhigh",
    ]
    assert get_model_reasoning_capabilities("gpt-5.2-chat-latest").reasoning_efforts == []
    assert get_model_reasoning_capabilities("custom-gateway-model").reasoning_efforts is None


def test_cloud_settings_overview_does_not_read_database_runtime_overrides(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.workflows.support.system.settings.is_local_mode",
        lambda: False,
    )

    def fail_if_read(_session):
        raise AssertionError("cloud settings overview must not read database runtime overrides")

    monkeypatch.setattr(
        "app.workflows.support.system.settings.get_system_runtime_settings_payload",
        fail_if_read,
    )

    overview = build_settings_overview_data(session=object())
    model_entry = next(
        entry
        for section in overview.sections
        for entry in section.entries
        if entry.key == "models.primary"
    )

    assert model_entry.editable is False


def test_rpm_rate_limit_is_treated_as_local_throttle() -> None:
    error = RuntimeError(
        'litellm.RateLimitError: {"error":{"message":"user requests-per-minute limit exceeded",'
        '"type":"rate_limit_exceeded"}}'
    )

    assert llm_common.is_concurrency_rate_limit_error(error)
    assert not llm_common.should_try_endpoint_fallback(error)


def test_gateway_outage_still_uses_endpoint_fallback() -> None:
    error = RuntimeError("primary gateway timed out")

    assert llm_common.should_try_endpoint_fallback(error)


def test_existing_advanced_settings_remain_exposed_in_settings_page() -> None:
    overview = build_settings_overview_data()
    exposed_keys = {
        entry.key
        for section in overview.sections
        for entry in section.entries
    }

    useful_existing_keys = {
        "llm.provider",
        "llm.api_version",
        "paddle_ocr.api_token",
        "paddle_ocr.model",
        "paddle_ocr.parse_mode",
        "paddle_ocr.parse_timeout_s",
        "paddle_ocr.chunk_max_pages",
        "paddle_ocr.chunk_concurrency",
        "mineru.api_token",
        "models.embedding_dim",
        "planner.history_turns",
        "interact.history_turns",
        "knowledge_graph.prefetch_during_docgen",
        "knowledge_graph.prefetch_concurrency",
        "knowledge_graph.max_parallel_extractions",
        "rag.top_k",
        "rag.similarity_threshold",
        "rag.rerank_top_k",
        "local_rag.min_results",
        "search.tavily_api_key",
        "search.google_api_key",
        "langsmith.tracing",
        "langsmith.api_key",
        "langsmith.project",
    }
    assert useful_existing_keys.issubset(exposed_keys)


@pytest.mark.anyio
async def test_llm_limiter_uses_live_runtime_limit() -> None:
    set_system_settings_override({"llm": {"concurrency_limit": 1}})
    limiter = get_llm_concurrency_limiter()
    first_inside = asyncio.Event()
    release_first = asyncio.Event()
    second_inside = asyncio.Event()

    async def first_call() -> None:
        async with limiter.slot():
            first_inside.set()
            await release_first.wait()

    async def second_call() -> None:
        async with limiter.slot():
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
async def test_llm_limiter_traces_wait_for_concurrency_slot(monkeypatch) -> None:
    set_system_settings_override({"llm": {"concurrency_limit": 1}})
    limiter = get_llm_concurrency_limiter()
    traces: list[dict[str, object]] = []

    class FakeRun:
        def __init__(self) -> None:
            self.outputs: dict[str, object] | None = None

        def end(self, outputs=None) -> None:
            self.outputs = dict(outputs or {})

    @contextmanager
    def fake_trace_substep(name: str, **kwargs):
        run = FakeRun()
        traces.append({"name": name, "kwargs": kwargs, "run": run})
        yield run

    monkeypatch.setattr(llm_common, "trace_substep", fake_trace_substep)

    first_inside = asyncio.Event()
    release_first = asyncio.Event()
    second_inside = asyncio.Event()

    async def first_call() -> None:
        async with limiter.slot():
            first_inside.set()
            await release_first.wait()

    async def second_call() -> None:
        async with limiter.slot():
            second_inside.set()

    first_task = asyncio.create_task(first_call())
    await asyncio.wait_for(first_inside.wait(), timeout=1)
    second_task = asyncio.create_task(second_call())
    await asyncio.sleep(0.05)

    assert second_inside.is_set() is False
    assert len(traces) == 1
    assert traces[0]["name"] == "LLM：等待并发槽"
    trace_kwargs = traces[0]["kwargs"]
    assert trace_kwargs["metadata"]["substep"] == "llm.concurrency.wait"
    assert trace_kwargs["inputs"]["configured_limit"] == 1
    assert trace_kwargs["inputs"]["active_count"] == 1

    release_first.set()
    await asyncio.wait_for(second_inside.wait(), timeout=1)
    await asyncio.gather(first_task, second_task)

    run = traces[0]["run"]
    assert isinstance(run, FakeRun)
    assert run.outputs is not None
    assert run.outputs["outcome"] == "acquired"
    assert run.outputs["configured_limit"] == 1
    assert int(run.outputs["wait_ms"]) >= 0


@pytest.mark.anyio
async def test_llm_limiter_releases_slot_when_holder_is_cancelled() -> None:
    set_system_settings_override({"llm": {"concurrency_limit": 1}})
    limiter = get_llm_concurrency_limiter()
    first_inside = asyncio.Event()
    never_release = asyncio.Event()

    async def holder() -> None:
        async with limiter.slot():
            first_inside.set()
            await never_release.wait()

    holder_task = asyncio.create_task(holder())
    await asyncio.wait_for(first_inside.wait(), timeout=1)
    holder_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await holder_task

    async def next_call() -> bool:
        async with limiter.slot():
            return True

    assert await asyncio.wait_for(next_call(), timeout=1)


@pytest.mark.anyio
async def test_llm_limiter_lease_can_be_released_from_another_task() -> None:
    set_system_settings_override({"llm": {"concurrency_limit": 1}})
    limiter = get_llm_concurrency_limiter()
    lease = limiter.slot()

    await asyncio.create_task(lease.__aenter__())
    assert limiter._active == 1

    await lease.__aexit__(None, None, None)
    assert limiter._active == 0

    async def next_call() -> bool:
        async with limiter.slot():
            return True

    assert await asyncio.wait_for(next_call(), timeout=1)


@pytest.mark.anyio
async def test_llm_limiter_releases_cross_task_closed_stream() -> None:
    set_system_settings_override({"llm": {"concurrency_limit": 1}})
    limiter = get_llm_concurrency_limiter()

    async def limited_stream():
        async with limiter.slot():
            yield "first"

    stream = limited_stream()
    assert await asyncio.create_task(anext(stream)) == "first"
    assert limiter._active == 1

    await stream.aclose()
    assert limiter._active == 0

    async def next_call() -> bool:
        async with limiter.slot():
            return True

    assert await asyncio.wait_for(next_call(), timeout=1)


@pytest.mark.anyio
async def test_llm_limiter_temporarily_reduces_after_concurrency_rate_limit() -> None:
    set_system_settings_override({"llm": {"concurrency_limit": 4}})
    limiter = get_llm_concurrency_limiter()
    limiter.note_rate_limit()

    active = 0
    max_active = 0
    first_two_started = asyncio.Event()
    release_workers = asyncio.Event()

    async def worker() -> None:
        nonlocal active, max_active
        async with limiter.slot():
            active += 1
            max_active = max(max_active, active)
            if active == 2:
                first_two_started.set()
            try:
                await release_workers.wait()
            finally:
                active -= 1

    tasks = [asyncio.create_task(worker()) for _ in range(3)]
    await asyncio.wait_for(first_two_started.wait(), timeout=1)
    await asyncio.sleep(0.05)

    assert max_active == 2
    release_workers.set()
    await asyncio.gather(*tasks)


@pytest.mark.anyio
async def test_retry_backoff_does_not_hold_limiter_slot(monkeypatch) -> None:
    set_system_settings_override({"llm": {"concurrency_limit": 1}})
    limiter = get_llm_concurrency_limiter()
    sleep_started = asyncio.Event()
    sleep_can_finish = asyncio.Event()
    second_inside = asyncio.Event()

    async def fake_sleep(_delay: float) -> None:
        sleep_started.set()
        await sleep_can_finish.wait()

    monkeypatch.setattr(llm_common.asyncio, "sleep", fake_sleep)

    async def retrying_call() -> None:
        async with limiter.slot() as lease:
            await llm_common.sleep_before_retry(
                1,
                error=RuntimeError("retryable"),
                lease=lease,
            )

    async def second_call() -> None:
        async with limiter.slot():
            second_inside.set()

    retry_task = asyncio.create_task(retrying_call())
    await asyncio.wait_for(sleep_started.wait(), timeout=1)

    second_task = asyncio.create_task(second_call())
    await asyncio.wait_for(second_inside.wait(), timeout=1)

    sleep_can_finish.set()
    await asyncio.gather(retry_task, second_task)


@pytest.mark.anyio
async def test_retry_backoff_reacquires_slot_before_returning(monkeypatch) -> None:
    set_system_settings_override({"llm": {"concurrency_limit": 1}})
    limiter = get_llm_concurrency_limiter()
    sleep_started = asyncio.Event()
    sleep_can_finish = asyncio.Event()
    blocker_inside = asyncio.Event()
    blocker_can_finish = asyncio.Event()
    retry_returned = asyncio.Event()

    async def fake_sleep(_delay: float) -> None:
        sleep_started.set()
        await sleep_can_finish.wait()

    monkeypatch.setattr(llm_common.asyncio, "sleep", fake_sleep)

    async def retrying_call() -> None:
        async with limiter.slot() as lease:
            await llm_common.sleep_before_retry(
                1,
                error=RuntimeError("retryable"),
                lease=lease,
            )
            retry_returned.set()

    async def blocker_call() -> None:
        async with limiter.slot():
            blocker_inside.set()
            await blocker_can_finish.wait()

    retry_task = asyncio.create_task(retrying_call())
    await asyncio.wait_for(sleep_started.wait(), timeout=1)

    blocker_task = asyncio.create_task(blocker_call())
    await asyncio.wait_for(blocker_inside.wait(), timeout=1)

    sleep_can_finish.set()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(retry_returned.wait(), timeout=0.05)

    blocker_can_finish.set()
    await asyncio.wait_for(retry_returned.wait(), timeout=1)
    await asyncio.gather(retry_task, blocker_task)


@pytest.mark.anyio
async def test_retry_backoff_cancelled_while_sleeping_leaves_slot_available(monkeypatch) -> None:
    set_system_settings_override({"llm": {"concurrency_limit": 1}})
    limiter = get_llm_concurrency_limiter()
    sleep_started = asyncio.Event()
    sleep_can_finish = asyncio.Event()

    async def fake_sleep(_delay: float) -> None:
        sleep_started.set()
        await sleep_can_finish.wait()

    monkeypatch.setattr(llm_common.asyncio, "sleep", fake_sleep)

    async def retrying_call() -> None:
        async with limiter.slot() as lease:
            await llm_common.sleep_before_retry(
                1,
                error=RuntimeError("retryable"),
                lease=lease,
            )

    retry_task = asyncio.create_task(retrying_call())
    await asyncio.wait_for(sleep_started.wait(), timeout=1)
    retry_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await retry_task

    async def next_call() -> bool:
        async with limiter.slot():
            return True

    assert await asyncio.wait_for(next_call(), timeout=1)


@pytest.mark.anyio
async def test_retry_backoff_nested_limiter_releases_only_current_slot(monkeypatch) -> None:
    set_system_settings_override({"llm": {"concurrency_limit": 2}})
    limiter = get_llm_concurrency_limiter()
    sleep_started = asyncio.Event()
    sleep_can_finish = asyncio.Event()
    blocker_inside = asyncio.Event()
    blocker_can_finish = asyncio.Event()
    third_inside = asyncio.Event()
    retry_returned = asyncio.Event()
    retry_can_finish = asyncio.Event()

    async def fake_sleep(_delay: float) -> None:
        sleep_started.set()
        await sleep_can_finish.wait()

    monkeypatch.setattr(llm_common.asyncio, "sleep", fake_sleep)

    async def retrying_call() -> None:
        async with limiter.slot():
            async with limiter.slot() as inner_lease:
                await llm_common.sleep_before_retry(
                    1,
                    error=RuntimeError("retryable"),
                    lease=inner_lease,
                )
                retry_returned.set()
                await retry_can_finish.wait()

    async def blocker_call() -> None:
        async with limiter.slot():
            blocker_inside.set()
            await blocker_can_finish.wait()

    async def third_call() -> None:
        async with limiter.slot():
            third_inside.set()

    retry_task = asyncio.create_task(retrying_call())
    await asyncio.wait_for(sleep_started.wait(), timeout=1)

    blocker_task = asyncio.create_task(blocker_call())
    await asyncio.wait_for(blocker_inside.wait(), timeout=1)

    third_task = asyncio.create_task(third_call())
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(third_inside.wait(), timeout=0.05)

    sleep_can_finish.set()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(retry_returned.wait(), timeout=0.05)

    blocker_can_finish.set()
    await asyncio.wait_for(retry_returned.wait(), timeout=1)
    retry_can_finish.set()
    await asyncio.gather(retry_task, blocker_task)
    await asyncio.wait_for(third_inside.wait(), timeout=1)
    await third_task


@pytest.mark.anyio
async def test_retry_backoff_child_task_does_not_release_parent_slot(monkeypatch) -> None:
    set_system_settings_override({"llm": {"concurrency_limit": 1}})
    limiter = get_llm_concurrency_limiter()
    sleep_started = asyncio.Event()
    sleep_can_finish = asyncio.Event()
    parent_can_finish = asyncio.Event()
    parent_inside = asyncio.Event()
    second_inside = asyncio.Event()

    async def fake_sleep(_delay: float) -> None:
        sleep_started.set()
        await sleep_can_finish.wait()

    monkeypatch.setattr(llm_common.asyncio, "sleep", fake_sleep)

    async def child_retry() -> None:
        await llm_common.sleep_before_retry(1, error=RuntimeError("retryable"))

    async def parent_call() -> None:
        async with limiter.slot():
            parent_inside.set()
            child_task = asyncio.create_task(child_retry())
            await asyncio.wait_for(sleep_started.wait(), timeout=1)
            sleep_can_finish.set()
            await child_task
            await parent_can_finish.wait()

    async def second_call() -> None:
        async with limiter.slot():
            second_inside.set()

    parent_task = asyncio.create_task(parent_call())
    await asyncio.wait_for(parent_inside.wait(), timeout=1)
    await asyncio.wait_for(sleep_started.wait(), timeout=1)

    second_task = asyncio.create_task(second_call())
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(second_inside.wait(), timeout=0.05)

    parent_can_finish.set()
    await parent_task
    await asyncio.wait_for(second_inside.wait(), timeout=1)
    await second_task


@pytest.mark.anyio
async def test_llm_limiter_is_process_wide_across_event_loops() -> None:
    set_system_settings_override({"llm": {"concurrency_limit": 1}})
    limiter = get_llm_concurrency_limiter()
    holder_inside = asyncio.Event()
    release_holder = asyncio.Event()
    thread_entered = threading.Event()
    thread_done = threading.Event()

    async def holder() -> None:
        async with limiter.slot():
            holder_inside.set()
            await release_holder.wait()

    def run_in_thread() -> None:
        async def attempt() -> None:
            async with limiter.slot():
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


@pytest.mark.anyio
async def test_run_llm_tasks_converts_generator_exit_to_failure() -> None:
    set_system_settings_override({"llm": {"concurrency_limit": 1}})

    async def worker(_value: object) -> int:
        raise GeneratorExit()

    with pytest.raises(RuntimeError, match="GeneratorExit"):
        await asyncio.wait_for(run_llm_tasks([None], worker), timeout=1)


@pytest.mark.anyio
async def test_run_llm_tasks_restores_langsmith_parent_for_workers(monkeypatch) -> None:
    set_system_settings_override({"llm": {"concurrency_limit": 2}})
    parent_run = object()
    observed_parents: list[object] = []

    @contextmanager
    def fake_tracing_context(**kwargs):
        observed_parents.append(kwargs.get("parent"))
        yield

    monkeypatch.setattr(scheduler_module, "get_current_run_tree", lambda: parent_run)
    monkeypatch.setattr(scheduler_module, "tracing_context", fake_tracing_context)

    async def worker(value: int) -> int:
        await asyncio.sleep(0)
        return value * 3

    assert await run_llm_tasks([1, 2], worker) == [3, 6]
    assert observed_parents == [parent_run, parent_run]


async def _return_after_event(event: asyncio.Event, value: int) -> int:
    event.set()
    return value

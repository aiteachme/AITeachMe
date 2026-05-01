from __future__ import annotations

import asyncio

import pytest

from app.shared.infra.llm_support import get_llm_concurrency_limit, get_llm_concurrency_limiter
from app.shared.infra.llm_support.defaults import DEFAULT_LLM_CONCURRENCY_LIMIT
from app.shared.infra.settings import (
    get_settings,
    reset_project_settings_cache,
    set_system_settings_override,
)
from app.workflows.digest.kg_doc_sync.lib.incremental_sync import _graph_llm_concurrency_cap
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


def test_kg_graph_cap_uses_shared_llm_limit() -> None:
    set_system_settings_override({"llm": {"concurrency_limit": 8}})

    assert _graph_llm_concurrency_cap() == 6


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

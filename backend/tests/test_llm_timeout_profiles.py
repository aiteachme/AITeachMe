import asyncio

import pytest

from app.shared.infra.exceptions import LLMTimeoutError
from app.shared.infra.llm_support import stream as stream_module
from app.shared.infra.llm_support import text as text_module
from app.shared.infra.llm_support.common import (
    build_completion_context,
    build_completion_kwargs,
    context_request_timeout_s,
    effective_max_retries,
)
from app.shared.infra.llm_support.routing import TaskType, get_task_profile


def test_heavy_llm_profiles_allow_long_background_calls():
    assert get_task_profile(TaskType.DOCGEN).timeout_s >= 600
    assert get_task_profile(TaskType.DOCGEN).max_retries >= 3
    assert get_task_profile(TaskType.DOCGEN_LIGHT).timeout_s >= 480
    assert get_task_profile(TaskType.EXTRACT).timeout_s >= 300
    assert get_task_profile(TaskType.VISION).timeout_s >= 480


def test_llm_profile_timeout_env_override(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT_DOCGEN_S", "420")
    monkeypatch.setenv("LLM_MAX_RETRIES_DOCGEN", "3")

    profile = get_task_profile(TaskType.DOCGEN)

    assert profile.timeout_s == 420
    assert profile.max_retries == 3


def test_task_type_profile_does_not_inject_generation_kwargs(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    context = build_completion_context(task_type=TaskType.CHAT, model="codex-auto-review")
    messages = [{"role": "user", "content": "hello"}]

    default_kwargs = build_completion_kwargs(
        context=context,
        messages=messages,
        extra_kwargs={},
    )
    explicit_kwargs = build_completion_kwargs(
        context=context,
        messages=messages,
        extra_kwargs={"temperature": 0.2},
    )
    explicit_token_kwargs = build_completion_kwargs(
        context=context,
        messages=messages,
        extra_kwargs={"max_tokens": 1234},
    )
    explicit_retry_kwargs = build_completion_kwargs(
        context=context,
        messages=messages,
        extra_kwargs={"max_retries": 2},
    )

    assert "temperature" not in default_kwargs
    assert "max_tokens" not in default_kwargs
    assert "max_retries" not in explicit_retry_kwargs
    assert explicit_kwargs["temperature"] == 0.2
    assert explicit_token_kwargs["max_tokens"] == 1234


def test_openai_reasoning_models_drop_unsupported_temperature(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://aihubmix.com/v1")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    context = build_completion_context(task_type=TaskType.EXTRACT, model="gpt-5.5")
    messages = [{"role": "user", "content": "extract graph"}]

    kwargs = build_completion_kwargs(
        context=context,
        messages=messages,
        extra_kwargs={
            "temperature": 0.1,
            "max_tokens": 7000,
        },
    )

    assert kwargs["model"] == "gpt-5.5"
    assert kwargs["max_tokens"] == 7000
    assert kwargs["custom_llm_provider"] == "openai"
    assert "temperature" not in kwargs


def test_explicit_max_retries_overrides_profile_without_provider_passthrough(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    context = build_completion_context(task_type=TaskType.CHAT)

    assert effective_max_retries(context, {"max_retries": 2}) == 2
    assert effective_max_retries(context, {"max_retries": 0}) == 1
    assert effective_max_retries(context, {"max_retries": 99}) == 10
    assert effective_max_retries(context, {"max_retries": "bad"}) == context.profile.max_retries


def test_outer_request_timeout_uses_explicit_call_timeout(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    context = build_completion_context(task_type=TaskType.DOCGEN)

    assert context_request_timeout_s(context, {"timeout": 420}) == 422


def test_invalid_explicit_timeout_falls_back_to_profile(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    context = build_completion_context(task_type=TaskType.DOCGEN)

    assert context_request_timeout_s(context, {"timeout": 0}) == context.profile.timeout_s + 2
    assert context_request_timeout_s(context, {"timeout": "bad"}) == context.profile.timeout_s + 2


@pytest.mark.anyio
async def test_text_completion_overall_timeout_wraps_full_call(monkeypatch):
    async def slow_completion(*_args, **_kwargs):
        await asyncio.sleep(0.05)
        return "late"

    monkeypatch.setattr(text_module, "_acompletion_impl", slow_completion)

    with pytest.raises(LLMTimeoutError):
        await text_module.acompletion(
            [{"role": "user", "content": "hello"}],
            overall_timeout_s=0.01,
        )


@pytest.mark.anyio
async def test_stream_completion_overall_timeout_wraps_full_stream(monkeypatch):
    async def slow_stream(*_args, **_kwargs):
        await asyncio.sleep(0.05)
        yield "late"

    monkeypatch.setattr(stream_module, "_acompletion_stream_impl", slow_stream)

    with pytest.raises(LLMTimeoutError):
        async for _ in stream_module.acompletion_stream(
            [{"role": "user", "content": "hello"}],
            overall_timeout_s=0.01,
        ):
            pass


@pytest.mark.anyio
async def test_stream_completion_overall_timeout_closes_inner_stream_on_outer_close(monkeypatch):
    closed = False

    async def stream_with_cleanup(*_args, **_kwargs):
        nonlocal closed
        try:
            yield "first"
            await asyncio.sleep(60)
        finally:
            closed = True

    monkeypatch.setattr(stream_module, "_acompletion_stream_impl", stream_with_cleanup)

    stream = stream_module.acompletion_stream(
        [{"role": "user", "content": "hello"}],
        overall_timeout_s=1,
    )
    async for _ in stream:
        break
    await stream.aclose()

    assert closed

import asyncio

import pytest

from app.shared.infra.exceptions import LLMTimeoutError
from app.shared.infra.llm_support import stream as stream_module
from app.shared.infra.llm_support import text as text_module
from app.shared.infra.llm_support.common import (
    apply_provider_extra_headers,
    build_completion_context,
    build_completion_kwargs,
    context_request_timeout_s,
    effective_max_retries,
)
from app.shared.infra.llm_support.routing import TaskType, get_task_profile


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


def test_aihubmix_app_code_header_is_injected_for_aihubmix_gateway(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://aihubmix.com/v1")
    monkeypatch.setenv("AIHUBMIX_APP_CODE", "CCOH5955")
    monkeypatch.setenv("LLM_AIHUBMIX_APP_CODE", "")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    context = build_completion_context(task_type=TaskType.CHAT, model="gpt-5.4-mini")

    kwargs = build_completion_kwargs(
        context=context,
        messages=[{"role": "user", "content": "hello"}],
        extra_kwargs={},
    )

    assert kwargs["extra_headers"] == {"APP-Code": "CCOH5955"}


def test_aihubmix_app_code_header_is_scoped_without_overriding_explicit_values(monkeypatch):
    monkeypatch.setenv("AIHUBMIX_APP_CODE", "CCOH5955")
    cases = [
        (
            {"api_base": "https://gateway.example.com/v1", "extra_headers": {"X-Trace": "keep"}},
            {"X-Trace": "keep"},
        ),
        (
            {"api_base": "https://aihubmix.com/v1", "extra_headers": {"APP-Code": "EXPLICIT"}},
            {"APP-Code": "EXPLICIT"},
        ),
    ]

    for call_kwargs, expected_headers in cases:
        apply_provider_extra_headers(call_kwargs)

        assert call_kwargs["extra_headers"] == expected_headers


def test_explicit_max_retries_overrides_profile_without_provider_passthrough(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    context = build_completion_context(task_type=TaskType.CHAT)

    assert effective_max_retries(context, {"max_retries": 2}) == 2
    assert effective_max_retries(context, {"max_retries": 0}) == 1
    assert effective_max_retries(context, {"max_retries": 99}) == 10
    assert effective_max_retries(context, {"max_retries": "bad"}) == context.profile.max_retries


def test_request_timeout_prefers_valid_explicit_value_and_rejects_invalid_values(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    context = build_completion_context(task_type=TaskType.DOCGEN)

    assert context_request_timeout_s(context, {"timeout": 420}) == 422
    for invalid_timeout in (0, "bad"):
        assert (
            context_request_timeout_s(context, {"timeout": invalid_timeout})
            == context.profile.timeout_s + 2
        )


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

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.shared.infra.llm_support import responses_adapter
from app.shared.infra.llm_support.common import build_completion_context, build_completion_contexts
from app.shared.infra.llm_support.responses_adapter import (
    chat_fallback_for_auto_responses,
    extract_response_text,
    resolve_provider_call,
    response_output_tool_events,
    response_stream_delta,
    response_stream_final_text,
)
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.exceptions import LLMCallError
from app.shared.infra.settings.defaults import get_default_settings_values
from app.shared.infra.settings import set_system_settings_override
from app.shared.infra.settings.support import get_llm_provider_model_defaults


class FakeResponseEventType:
    def __init__(self, value: str) -> None:
        self.value = value

    def __str__(self) -> str:
        return f"ResponsesAPIStreamEvents.{self.value.replace('.', '_').upper()}"


def teardown_function() -> None:
    set_system_settings_override({})


def test_auto_uses_responses_for_official_openai_reasoning_model(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    set_system_settings_override({
        "models": {"primary": "gpt-5.2"},
        "llm": {"api_mode": "auto", "reasoning_effort": "high"},
    })
    context = build_completion_context(task_type=TaskType.CHAT, model="primary")

    call = resolve_provider_call(
        context=context,
        call_kwargs={
            "model": "gpt-5.2",
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 123,
        },
    )

    assert call.api_mode == "responses"
    assert call.kwargs["model"] == "gpt-5.2"
    assert call.kwargs["input"] == [{"role": "user", "content": "hello"}]
    assert call.kwargs["max_output_tokens"] == 123
    assert call.kwargs["reasoning"] == {"effort": "high"}
    assert "messages" not in call.kwargs
    assert "max_tokens" not in call.kwargs


def test_auto_uses_responses_for_openai_compatible_reasoning_gateway(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example.com/v1")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    set_system_settings_override({
        "models": {"primary": "gpt-5.5"},
        "llm": {"api_mode": "auto", "reasoning_effort": None},
    })
    context = build_completion_context(task_type=TaskType.CHAT, model="primary")

    call = resolve_provider_call(
        context=context,
        call_kwargs={
            "model": "gpt-5.5",
            "messages": [{"role": "user", "content": "hello"}],
            "api_base": "https://gateway.example.com/v1",
            "custom_llm_provider": "openai",
            "max_tokens": 123,
        },
    )

    assert call.api_mode == "responses"
    assert call.kwargs["model"] == "gpt-5.5"
    assert call.kwargs["input"] == [{"role": "user", "content": "hello"}]
    assert call.kwargs["api_base"] == "https://gateway.example.com/v1"
    assert call.kwargs["custom_llm_provider"] == "openai"
    assert call.kwargs["max_output_tokens"] == 123
    assert "messages" not in call.kwargs
    assert "max_tokens" not in call.kwargs
    assert "reasoning" not in call.kwargs
    assert call.auto_chat_fallback_kwargs is not None


def test_auto_responses_html_gateway_error_falls_back_to_chat(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example.com/v1")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    set_system_settings_override({
        "models": {"primary": "gpt-5.5"},
        "llm": {"api_mode": "auto"},
    })
    context = build_completion_context(task_type=TaskType.CHAT, model="primary")
    call = resolve_provider_call(
        context=context,
        call_kwargs={
            "model": "gpt-5.5",
            "messages": [{"role": "user", "content": "hello"}],
            "api_base": "https://gateway.example.com/v1",
            "custom_llm_provider": "openai",
        },
    )

    fallback = chat_fallback_for_auto_responses(
        call,
        RuntimeError(
            "<!DOCTYPE html><html><head><title>Sub2API - AI API Gateway</title></head></html>. "
            "Check the reverse proxy or model server configuration."
        ),
    )

    assert fallback is not None
    assert fallback.api_mode == "chat_completions"
    assert fallback.kwargs["model"] == "gpt-5.5"
    assert fallback.kwargs["messages"] == [{"role": "user", "content": "hello"}]


def test_responses_output_tool_events_summarize_provider_native_calls() -> None:
    response = SimpleNamespace(
        output=[
            SimpleNamespace(
                type="web_search_call",
                id="ws_1",
                status="completed",
                action={"type": "search"},
            ),
            SimpleNamespace(type="message", content="done"),
            {
                "type": "file_search_call",
                "call_id": "fs_1",
                "status": "completed",
            },
        ],
    )

    assert response_output_tool_events(response) == [
        {
            "type": "web_search_call",
            "id": "ws_1",
            "status": "completed",
            "action_type": "search",
        },
        {
            "type": "file_search_call",
            "call_id": "fs_1",
            "status": "completed",
        },
    ]


def test_responses_text_extractors_accept_raw_text_and_sdk_events() -> None:
    assert extract_response_text("plain response text") == "plain response text"
    assert response_stream_delta("plain stream text") == "plain stream text"
    assert response_stream_delta(
        SimpleNamespace(type=FakeResponseEventType("response.output_text.delta"), delta="delta text")
    ) == "delta text"
    assert response_stream_final_text(
        SimpleNamespace(type="response.output_text.done", text="done text")
    ) == "done text"
    assert extract_response_text(
        SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="message",
                    content=[
                        SimpleNamespace(type="output_text", text="nested text"),
                    ],
                )
            ]
        )
    ) == "nested text"


def test_auto_uses_litellm_reasoning_probe_for_gateway_alias(monkeypatch):
    class FakeLiteLLM:
        @staticmethod
        def supports_reasoning(model: str, custom_llm_provider: str | None = None) -> bool:
            return model == "campus-tutor-pro" and custom_llm_provider is None

    monkeypatch.setattr(responses_adapter, "load_litellm", lambda: FakeLiteLLM)
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example.com/v1")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    set_system_settings_override({
        "models": {"primary": "campus-tutor-pro"},
        "llm": {"api_mode": "auto", "reasoning_effort": "low"},
    })
    context = build_completion_context(task_type=TaskType.CHAT, model="primary")

    call = resolve_provider_call(
        context=context,
        call_kwargs={
            "model": "campus-tutor-pro",
            "messages": [{"role": "user", "content": "hello"}],
            "api_base": "https://gateway.example.com/v1",
            "custom_llm_provider": "openai",
        },
    )

    assert call.api_mode == "responses"
    assert call.kwargs["input"] == [{"role": "user", "content": "hello"}]
    assert call.kwargs["reasoning"] == {"effort": "low"}


def test_auto_uses_explicit_litellm_responses_model_route(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    set_system_settings_override({
        "models": {"primary": "openai/responses/gpt-5.5"},
        "llm": {"api_mode": "auto"},
    })
    context = build_completion_context(task_type=TaskType.CHAT, model="primary")

    call = resolve_provider_call(
        context=context,
        call_kwargs={
            "model": "openai/responses/gpt-5.5",
            "messages": [{"role": "user", "content": "hello"}],
            "custom_llm_provider": "openai",
        },
    )

    assert call.api_mode == "responses"
    assert call.kwargs["model"] == "openai/responses/gpt-5.5"
    assert call.kwargs["input"] == [{"role": "user", "content": "hello"}]


def test_auto_keeps_unknown_gateway_alias_on_chat(monkeypatch):
    class FakeLiteLLM:
        @staticmethod
        def supports_reasoning(model: str, custom_llm_provider: str | None = None) -> bool:
            return False

    monkeypatch.setattr(responses_adapter, "load_litellm", lambda: FakeLiteLLM)
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example.com/v1")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    set_system_settings_override({
        "models": {"primary": "plain-chat-alias"},
        "llm": {"api_mode": "auto"},
    })
    context = build_completion_context(task_type=TaskType.CHAT, model="primary")

    call = resolve_provider_call(
        context=context,
        call_kwargs={
            "model": "plain-chat-alias",
            "messages": [{"role": "user", "content": "hello"}],
            "api_base": "https://gateway.example.com/v1",
            "custom_llm_provider": "openai",
        },
    )

    assert call.api_mode == "chat_completions"
    assert call.kwargs["messages"] == [{"role": "user", "content": "hello"}]


def test_forced_responses_for_gateway_maps_kwargs(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example.com/v1")
    set_system_settings_override({
        "models": {"primary": "gpt-5.2"},
        "llm": {"api_mode": "responses", "reasoning_effort": None},
    })
    context = build_completion_context(task_type=TaskType.CHAT, model="primary")

    call = resolve_provider_call(
        context=context,
        call_kwargs={
            "model": "gpt-5.2",
            "messages": [
                {"role": "system", "content": "Be concise."},
                {"role": "user", "content": "hello"},
            ],
            "api_base": "https://gateway.example.com/v1",
            "custom_llm_provider": "openai",
            "max_tokens": 456,
            "reasoning_effort": "low",
        },
    )

    assert call.api_mode == "responses"
    assert call.kwargs["instructions"] == "Be concise."
    assert call.kwargs["input"] == [{"role": "user", "content": "hello"}]
    assert call.kwargs["max_output_tokens"] == 456
    assert call.kwargs["reasoning"] == {"effort": "low"}


def test_auto_keeps_chat_only_response_format_on_chat(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    set_system_settings_override({
        "models": {"primary": "gpt-5.2"},
        "llm": {"api_mode": "auto"},
    })
    context = build_completion_context(task_type=TaskType.CHAT, model="primary")

    call = resolve_provider_call(
        context=context,
        call_kwargs={
            "model": "gpt-5.2",
            "messages": [{"role": "user", "content": "return json"}],
            "response_format": {"type": "json_object"},
        },
    )

    assert call.api_mode == "chat_completions"
    assert call.kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.anyio
async def test_text_completion_calls_litellm_responses_in_auto(monkeypatch):
    from app.shared.infra.llm_support import text as text_module

    calls: list[dict] = []

    class FakeLiteLLM:
        async def aresponses(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                output_text="hello from responses",
                usage=SimpleNamespace(input_tokens=3, output_tokens=4, total_tokens=7),
            )

        async def acompletion(self, **kwargs):  # pragma: no cover - should not be called
            raise AssertionError("Chat Completions should not be used")

    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.setattr(text_module, "load_litellm", lambda: FakeLiteLLM())
    set_system_settings_override({
        "models": {"primary": "gpt-5.2"},
        "llm": {"api_mode": "auto", "reasoning_effort": "high"},
    })

    result = await text_module.acompletion(
        [{"role": "user", "content": "hello"}],
        task_type=TaskType.CHAT,
        model="primary",
        max_tokens=32,
    )

    assert result == "hello from responses"
    assert calls[0]["model"] == "gpt-5.2"
    assert calls[0]["input"] == [{"role": "user", "content": "hello"}]
    assert calls[0]["max_output_tokens"] == 32
    assert calls[0]["reasoning"] == {"effort": "high"}


@pytest.mark.anyio
async def test_text_completion_records_provider_native_tool_events(monkeypatch):
    from app.shared.infra.llm_support import text as text_module

    trace_outputs: list[dict] = []

    class FakeTraceRun:
        def end(self, *, outputs):
            trace_outputs.append(outputs)

    @contextmanager
    def fake_langsmith_trace(**kwargs):
        yield FakeTraceRun()

    class FakeLiteLLM:
        async def aresponses(self, **kwargs):
            return SimpleNamespace(
                output_text="searched answer",
                output=[
                    SimpleNamespace(
                        type="web_search_call",
                        id="ws_1",
                        status="completed",
                    )
                ],
                usage=SimpleNamespace(input_tokens=3, output_tokens=4, total_tokens=7),
            )

        async def acompletion(self, **kwargs):  # pragma: no cover - should not be called
            raise AssertionError("Chat Completions should not be used")

    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.setattr(text_module, "load_litellm", lambda: FakeLiteLLM())
    monkeypatch.setattr(text_module, "langsmith_trace", fake_langsmith_trace)
    set_system_settings_override({
        "models": {"primary": "gpt-4.1"},
        "llm": {"api_mode": "auto", "native_web_search": "auto"},
    })

    result = await text_module.acompletion(
        [{"role": "user", "content": "latest AI news"}],
        task_type=TaskType.CHAT,
        model="primary",
        provider_native_tools=[{"type": "web_search", "mode": "auto"}],
    )

    assert result == "searched answer"
    assert trace_outputs[0]["llm_provider_tool_events"] == [
        {
            "type": "web_search_call",
            "id": "ws_1",
            "status": "completed",
        }
    ]


@pytest.mark.anyio
async def test_text_completion_auto_responses_falls_back_once_to_chat(monkeypatch):
    from app.shared.infra.llm_support import text as text_module

    response_calls: list[dict] = []
    chat_calls: list[dict] = []
    trace_outputs: list[dict] = []

    class FakeTraceRun:
        def end(self, *, outputs):
            trace_outputs.append(outputs)

    @contextmanager
    def fake_langsmith_trace(**kwargs):
        yield FakeTraceRun()

    class FakeLiteLLM:
        async def aresponses(self, **kwargs):
            response_calls.append(kwargs)
            raise RuntimeError("POST /responses not found")

        async def acompletion(self, **kwargs):
            chat_calls.append(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="chat fallback"),
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=2, completion_tokens=3, total_tokens=5),
            )

    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.setattr(text_module, "load_litellm", lambda: FakeLiteLLM())
    monkeypatch.setattr(text_module, "langsmith_trace", fake_langsmith_trace)
    set_system_settings_override({
        "models": {"primary": "gpt-5.2"},
        "llm": {"api_mode": "auto", "reasoning_effort": "high"},
    })

    result = await text_module.acompletion(
        [{"role": "user", "content": "hello"}],
        task_type=TaskType.CHAT,
        model="primary",
        max_tokens=32,
        max_retries=1,
    )

    assert result == "chat fallback"
    assert response_calls[0]["input"] == [{"role": "user", "content": "hello"}]
    assert chat_calls[0]["messages"] == [{"role": "user", "content": "hello"}]
    assert chat_calls[0]["max_tokens"] == 32
    assert chat_calls[0]["reasoning_effort"] == "high"
    assert trace_outputs[0]["llm_initial_api_mode"] == "responses"
    assert trace_outputs[0]["llm_final_api_mode"] == "chat_completions"
    assert trace_outputs[0]["llm_auto_responses_chat_fallback"] is True
    assert trace_outputs[0]["llm_final_api_mode_route_reason"] == "auto_responses_unsupported_chat_fallback"


@pytest.mark.anyio
async def test_forced_responses_does_not_fall_back_to_chat(monkeypatch):
    from app.shared.infra.llm_support import text as text_module

    chat_calls: list[dict] = []

    class FakeLiteLLM:
        async def aresponses(self, **kwargs):
            raise RuntimeError("POST /responses not found")

        async def acompletion(self, **kwargs):  # pragma: no cover - should not be called
            chat_calls.append(kwargs)
            return SimpleNamespace(choices=[])

    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.setattr(text_module, "load_litellm", lambda: FakeLiteLLM())
    set_system_settings_override({
        "models": {"primary": "gpt-5.2"},
        "llm": {"api_mode": "responses"},
    })

    with pytest.raises(Exception, match="/responses"):
        await text_module.acompletion(
            [{"role": "user", "content": "hello"}],
            task_type=TaskType.CHAT,
            model="primary",
            max_retries=1,
        )

    assert chat_calls == []


@pytest.mark.anyio
async def test_stream_completion_reads_responses_deltas_in_auto(monkeypatch):
    from app.shared.infra.llm_support import stream as stream_module

    calls: list[dict] = []

    class FakeResponsesStream:
        def __init__(self) -> None:
            self._chunks = iter([
                SimpleNamespace(type=FakeResponseEventType("response.output_text.delta"), delta="hel"),
                SimpleNamespace(type=FakeResponseEventType("response.output_text.delta"), delta="lo"),
            ])

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._chunks)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    class FakeLiteLLM:
        async def aresponses(self, **kwargs):
            calls.append(kwargs)
            return FakeResponsesStream()

        async def acompletion(self, **kwargs):  # pragma: no cover - should not be called
            raise AssertionError("Chat Completions should not be used")

    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.setattr(stream_module, "load_litellm", lambda: FakeLiteLLM())
    set_system_settings_override({
        "models": {"primary": "gpt-5.2"},
        "llm": {"api_mode": "auto", "reasoning_effort": "low"},
    })

    chunks = [
        chunk
        async for chunk in stream_module.acompletion_stream(
            [{"role": "user", "content": "hello"}],
            task_type=TaskType.CHAT,
            model="primary",
            max_tokens=32,
        )
    ]

    assert "".join(chunks) == "hello"
    assert calls[0]["model"] == "gpt-5.2"
    assert calls[0]["stream"] is True
    assert calls[0]["max_output_tokens"] == 32
    assert calls[0]["reasoning"] == {"effort": "low"}


@pytest.mark.anyio
async def test_stream_completion_reads_chat_shaped_responses_chunks(monkeypatch):
    from app.shared.infra.llm_support import stream as stream_module

    calls: list[dict] = []

    class FakeResponsesStream:
        def __init__(self) -> None:
            self._chunks = iter([
                SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="he"))],
                ),
                SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="llo"))],
                ),
            ])

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._chunks)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    class FakeLiteLLM:
        async def aresponses(self, **kwargs):
            calls.append(kwargs)
            return FakeResponsesStream()

        async def acompletion(self, **kwargs):  # pragma: no cover - should not be called
            raise AssertionError("Chat Completions should not be used")

    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.setattr(stream_module, "load_litellm", lambda: FakeLiteLLM())
    set_system_settings_override({
        "models": {"primary": "gpt-5.5"},
        "llm": {"api_mode": "auto", "reasoning_effort": "low"},
    })

    chunks = [
        chunk
        async for chunk in stream_module.acompletion_stream(
            [{"role": "user", "content": "hello"}],
            task_type=TaskType.CHAT,
            model="primary",
            max_tokens=32,
        )
    ]

    assert "".join(chunks) == "hello"
    assert calls[0]["model"] == "gpt-5.5"
    assert calls[0]["input"] == [{"role": "user", "content": "hello"}]


@pytest.mark.anyio
async def test_stream_completion_reads_raw_text_responses_chunks(monkeypatch):
    from app.shared.infra.llm_support import stream as stream_module

    class FakeResponsesStream:
        def __init__(self) -> None:
            self._chunks = iter(["he", "llo"])

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._chunks)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    class FakeLiteLLM:
        async def aresponses(self, **kwargs):
            return FakeResponsesStream()

        async def acompletion(self, **kwargs):  # pragma: no cover - should not be called
            raise AssertionError("Chat Completions should not be used")

    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.setattr(stream_module, "load_litellm", lambda: FakeLiteLLM())
    set_system_settings_override({
        "models": {"primary": "gpt-5.5"},
        "llm": {"api_mode": "auto"},
    })

    chunks = [
        chunk
        async for chunk in stream_module.acompletion_stream(
            [{"role": "user", "content": "hello"}],
            task_type=TaskType.CHAT,
            model="primary",
            max_tokens=32,
        )
    ]

    assert "".join(chunks) == "hello"


@pytest.mark.anyio
async def test_stream_completion_accepts_non_stream_responses_text(monkeypatch):
    from app.shared.infra.llm_support import stream as stream_module

    class FakeLiteLLM:
        async def aresponses(self, **kwargs):
            return SimpleNamespace(output_text="non-stream response text")

        async def acompletion(self, **kwargs):  # pragma: no cover - should not be called
            raise AssertionError("Chat Completions should not be used")

    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.setattr(stream_module, "load_litellm", lambda: FakeLiteLLM())
    set_system_settings_override({
        "models": {"primary": "gpt-5.5"},
        "llm": {"api_mode": "auto"},
    })

    chunks = [
        chunk
        async for chunk in stream_module.acompletion_stream(
            [{"role": "user", "content": "hello"}],
            task_type=TaskType.CHAT,
            model="primary",
            max_tokens=32,
        )
    ]

    assert "".join(chunks) == "non-stream response text"


@pytest.mark.anyio
async def test_stream_completion_reads_completed_responses_fallback(monkeypatch):
    from app.shared.infra.llm_support import stream as stream_module

    class FakeResponsesStream:
        def __init__(self) -> None:
            self._chunks = iter([
                SimpleNamespace(type="response.created"),
                SimpleNamespace(
                    type="response.completed",
                    response=SimpleNamespace(output_text="completed text"),
                ),
            ])

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._chunks)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    class FakeLiteLLM:
        async def aresponses(self, **kwargs):
            return FakeResponsesStream()

        async def acompletion(self, **kwargs):  # pragma: no cover - should not be called
            raise AssertionError("Chat Completions should not be used")

    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.setattr(stream_module, "load_litellm", lambda: FakeLiteLLM())
    set_system_settings_override({
        "models": {"primary": "gpt-5.5"},
        "llm": {"api_mode": "auto"},
    })

    chunks = [
        chunk
        async for chunk in stream_module.acompletion_stream(
            [{"role": "user", "content": "hello"}],
            task_type=TaskType.CHAT,
            model="primary",
            max_tokens=32,
        )
    ]

    assert "".join(chunks) == "completed text"


@pytest.mark.anyio
async def test_stream_completion_records_provider_native_tool_events(monkeypatch):
    from app.shared.infra.llm_support import stream as stream_module

    trace_outputs: list[dict] = []

    class FakeTraceRun:
        def add_event(self, event):  # noqa: ANN001
            return None

        def end(self, *, outputs):
            trace_outputs.append(outputs)

    @contextmanager
    def fake_langsmith_trace(**kwargs):
        yield FakeTraceRun()

    class FakeResponsesStream:
        def __init__(self) -> None:
            self._chunks = iter([
                SimpleNamespace(
                    type="response.completed",
                    response=SimpleNamespace(
                        output_text="completed text",
                        output=[
                            SimpleNamespace(
                                type="web_search_call",
                                id="ws_1",
                                status="completed",
                            )
                        ],
                    ),
                ),
            ])

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._chunks)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    class FakeLiteLLM:
        async def aresponses(self, **kwargs):
            return FakeResponsesStream()

        async def acompletion(self, **kwargs):  # pragma: no cover - should not be called
            raise AssertionError("Chat Completions should not be used")

    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.setattr(stream_module, "load_litellm", lambda: FakeLiteLLM())
    monkeypatch.setattr(stream_module, "langsmith_trace", fake_langsmith_trace)
    set_system_settings_override({
        "models": {"primary": "gpt-4.1"},
        "llm": {"api_mode": "auto", "native_web_search": "auto"},
    })

    chunks = [
        chunk
        async for chunk in stream_module.acompletion_stream(
            [{"role": "user", "content": "latest AI news"}],
            task_type=TaskType.CHAT,
            model="primary",
            provider_native_tools=[{"type": "web_search", "mode": "auto"}],
        )
    ]

    assert "".join(chunks) == "completed text"
    assert trace_outputs[0]["llm_provider_tool_events"] == [
        {
            "type": "web_search_call",
            "id": "ws_1",
            "status": "completed",
        }
    ]


def test_runtime_snapshot_pairs_primary_and_fallback_endpoints(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "primary-a,primary-b")
    monkeypatch.setenv("LLM_BASE_URL", "https://primary.example.com/v1")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "fallback-a,fallback-b")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "https://fallback-a.example.com/v1,https://fallback-b.example.com/v1")
    set_system_settings_override({
        "models": {"primary": "gpt-5.2"},
    })

    contexts = build_completion_contexts(task_type=TaskType.CHAT, model="primary")

    assert [context.endpoint_role for context in contexts] == [
        "primary",
        "primary",
        "fallback",
        "fallback",
    ]
    assert [context.base_url for context in contexts] == [
        "https://primary.example.com/v1",
        "https://primary.example.com/v1",
        "https://fallback-a.example.com/v1",
        "https://fallback-b.example.com/v1",
    ]
    assert [context.api_key for context in contexts] == [
        "primary-a",
        "primary-b",
        "fallback-a",
        "fallback-b",
    ]


def test_fallback_context_ignores_removed_provider_and_api_version_overrides(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "primary-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_VERSION", "2025-01-01")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "fallback-key")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "openai")
    monkeypatch.setenv("LLM_FALLBACK_API_VERSION", "2099-01-01")
    set_system_settings_override({
        "models": {"primary": "gpt-5.2", "reason": "gpt-5.2"},
    })

    contexts = build_completion_contexts(task_type=TaskType.CHAT, model="reason")

    assert contexts[1].endpoint_role == "fallback"
    assert contexts[1].provider == "deepseek"
    assert contexts[1].api_version == "2025-01-01"
    assert contexts[1].model == "deepseek-reasoner"


def test_fallback_context_uses_provider_default_models(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "primary-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "fallback-key")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "https://api.deepseek.com")
    set_system_settings_override({
        "models": {"primary": "gpt-5.2", "reason": "gpt-5.2"},
    })

    contexts = build_completion_contexts(task_type=TaskType.CHAT, model="reason")

    assert contexts[0].endpoint_role == "primary"
    assert contexts[0].model == "gpt-5.2"
    assert contexts[1].endpoint_role == "fallback"
    assert contexts[1].provider == "deepseek"
    assert contexts[1].model == "deepseek-reasoner"


def test_fallback_openai_compatible_uses_compatible_default_model(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "primary-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "fallback-key")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "https://fallback-gateway.example.com/v1")
    set_system_settings_override({
        "models": {"primary": "gpt-4o-mini", "light": "gpt-4o-mini"},
    })

    contexts = build_completion_contexts(task_type=TaskType.CHAT, model="light")

    assert contexts[0].endpoint_role == "primary"
    assert contexts[0].model == "gpt-4o-mini"
    assert contexts[1].endpoint_role == "fallback"
    assert contexts[1].provider == "openai_compatible"
    assert contexts[1].model == "gemini-3.1-flash-lite"


def test_fallback_api_key_without_base_url_is_ignored(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "primary-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://primary-gateway.example.com")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "fallback-key")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "")
    set_system_settings_override({
        "models": {"primary": "gpt-5.4-mini"},
    })

    contexts = build_completion_contexts(task_type=TaskType.CHAT, model="primary")

    assert [context.endpoint_role for context in contexts] == ["primary"]
    assert contexts[0].base_url == "https://primary-gateway.example.com"
    assert contexts[0].api_key == "primary-key"
    assert contexts[0].model == "gpt-5.4-mini"


def test_openai_compatible_provider_defaults_are_fallback_models():
    defaults = get_llm_provider_model_defaults("openai_compatible")

    assert defaults["primary"] == "gemini-3.1-flash-lite"
    assert defaults["reason"] == "gemini-3.1-flash-lite"
    assert defaults["light"] == "gemini-3.1-flash-lite"


def test_unconfigured_openai_compatible_settings_use_support_defaults(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://aihubmix.com/v1")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    defaults = get_default_settings_values()

    assert defaults["models"]["primary"] == "gemini-3.1-flash-lite"
    assert defaults["models"]["reason"] == "gemini-3.1-flash-lite"
    assert defaults["models"]["light"] == "gemini-3.1-flash-lite"


def test_langsmith_trace_metadata_records_actual_model_route():
    from app.shared.infra.llm_support.observability import _langsmith_trace_kwargs

    trace_kwargs = _langsmith_trace_kwargs(
        task_type=TaskType.CHAT,
        call_model="gpt-5.5",
        provider="openai",
        model_name="gpt-5.5",
        mode="text_chat_completions",
        messages=[{"role": "user", "content": "hello"}],
        call_kwargs={"model": "gpt-5.5", "messages": [{"role": "user", "content": "hello"}]},
        endpoint_role="fallback",
        model_selector="light",
    )

    metadata = trace_kwargs["extra_metadata"]
    assert trace_kwargs["inputs"]["model"] == "gpt-5.5"
    assert metadata["ls_model_name"] == "gpt-5.5"
    assert metadata["llm_endpoint_role"] == "fallback"
    assert metadata["llm_model_selector"] == "light"


@pytest.mark.anyio
async def test_text_completion_falls_back_to_default_provider_model(monkeypatch):
    from app.shared.infra.llm_support import text as text_module

    calls: list[dict] = []

    class FakeLiteLLM:
        async def aresponses(self, **kwargs):  # pragma: no cover - chat mode in this test
            raise AssertionError("Responses should not be used")

        async def acompletion(self, **kwargs):
            calls.append(kwargs)
            if kwargs["api_key"] == "primary-key":
                raise RuntimeError("primary gateway down")
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="fallback ok"),
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=2, completion_tokens=3, total_tokens=5),
            )

    monkeypatch.setenv("LLM_API_KEY", "primary-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "fallback-key")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setattr(text_module, "load_litellm", lambda: FakeLiteLLM())
    set_system_settings_override({
        "models": {"primary": "gpt-5.2"},
        "llm": {"api_mode": "chat_completions"},
    })

    result = await text_module.acompletion(
        [{"role": "user", "content": "hello"}],
        task_type=TaskType.CHAT,
        model="primary",
        max_retries=1,
    )

    assert result == "fallback ok"
    assert [call["api_key"] for call in calls] == ["primary-key", "fallback-key"]
    assert calls[0]["model"] == "gpt-5.2"
    assert calls[1]["model"] == "deepseek-chat"


@pytest.mark.anyio
async def test_text_completion_does_not_use_fallback_when_primary_succeeds(monkeypatch):
    from app.shared.infra.llm_support import text as text_module

    calls: list[dict] = []

    class FakeLiteLLM:
        async def aresponses(self, **kwargs):  # pragma: no cover - chat mode in this test
            raise AssertionError("Responses should not be used")

        async def acompletion(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="primary ok"),
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=2, completion_tokens=3, total_tokens=5),
            )

    monkeypatch.setenv("LLM_API_KEY", "primary-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "fallback-key")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "https://fallback-gateway.example.com/v1")
    monkeypatch.setattr(text_module, "load_litellm", lambda: FakeLiteLLM())
    set_system_settings_override({
        "models": {"primary": "gpt-5.2"},
        "llm": {"api_mode": "chat_completions"},
    })

    result = await text_module.acompletion(
        [{"role": "user", "content": "hello"}],
        task_type=TaskType.CHAT,
        model="primary",
        max_retries=1,
    )

    assert result == "primary ok"
    assert len(calls) == 1
    assert calls[0]["api_key"] == "primary-key"
    assert calls[0]["model"] == "gpt-5.2"


@pytest.mark.anyio
async def test_text_completion_retries_empty_primary_before_fallback(monkeypatch):
    from app.shared.infra.llm_support import text as text_module

    calls: list[dict] = []

    async def no_sleep(_attempt: int, **_kwargs) -> None:
        return None

    class FakeLiteLLM:
        async def aresponses(self, **kwargs):  # pragma: no cover - chat mode in this test
            raise AssertionError("Responses should not be used")

        async def acompletion(self, **kwargs):
            calls.append(kwargs)
            if kwargs["api_key"] == "primary-key" and len(calls) == 1:
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=""))],
                    usage=SimpleNamespace(prompt_tokens=2, completion_tokens=0, total_tokens=2),
                )
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="primary retry ok"),
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=2, completion_tokens=3, total_tokens=5),
            )

    monkeypatch.setenv("LLM_API_KEY", "primary-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "fallback-key")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setattr(text_module, "load_litellm", lambda: FakeLiteLLM())
    monkeypatch.setattr(text_module, "sleep_before_retry", no_sleep)
    set_system_settings_override({
        "models": {"primary": "gpt-5.4-mini"},
        "llm": {"api_mode": "chat_completions"},
    })

    result = await text_module.acompletion(
        [{"role": "user", "content": "hello"}],
        task_type=TaskType.CHAT,
        model="primary",
        max_retries=2,
    )

    assert result == "primary retry ok"
    assert [call["api_key"] for call in calls] == ["primary-key", "primary-key"]


@pytest.mark.anyio
async def test_text_completion_does_not_fallback_after_empty_primary_exhausted(monkeypatch):
    from app.shared.infra.llm_support import text as text_module

    calls: list[dict] = []

    async def no_sleep(_attempt: int, **_kwargs) -> None:
        return None

    class FakeLiteLLM:
        async def aresponses(self, **kwargs):  # pragma: no cover - chat mode in this test
            raise AssertionError("Responses should not be used")

        async def acompletion(self, **kwargs):
            calls.append(kwargs)
            if kwargs["api_key"] == "fallback-key":
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="fallback should not run"))],
                    usage=SimpleNamespace(prompt_tokens=2, completion_tokens=3, total_tokens=5),
                )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=""))],
                usage=SimpleNamespace(prompt_tokens=2, completion_tokens=0, total_tokens=2),
            )

    monkeypatch.setenv("LLM_API_KEY", "primary-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "fallback-key")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setattr(text_module, "load_litellm", lambda: FakeLiteLLM())
    monkeypatch.setattr(text_module, "sleep_before_retry", no_sleep)
    set_system_settings_override({
        "models": {"primary": "gpt-5.4-mini"},
        "llm": {"api_mode": "chat_completions"},
    })

    with pytest.raises(LLMCallError):
        await text_module.acompletion(
            [{"role": "user", "content": "hello"}],
            task_type=TaskType.CHAT,
            model="primary",
            max_retries=2,
        )

    assert [call["api_key"] for call in calls] == ["primary-key", "primary-key"]


@pytest.mark.anyio
async def test_text_completion_exhausts_primary_retries_before_fallback(monkeypatch):
    from app.shared.infra.llm_support import text as text_module

    calls: list[dict] = []

    async def no_sleep(_attempt: int, **_kwargs) -> None:
        return None

    class FakeLiteLLM:
        async def aresponses(self, **kwargs):  # pragma: no cover - chat mode in this test
            raise AssertionError("Responses should not be used")

        async def acompletion(self, **kwargs):
            calls.append(kwargs)
            if kwargs["api_key"] == "primary-key":
                raise RuntimeError("primary unavailable")
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="fallback ok"),
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=2, completion_tokens=3, total_tokens=5),
            )

    monkeypatch.setenv("LLM_API_KEY", "primary-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "fallback-key")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setattr(text_module, "load_litellm", lambda: FakeLiteLLM())
    monkeypatch.setattr(text_module, "sleep_before_retry", no_sleep)
    set_system_settings_override({
        "models": {"primary": "gpt-5.4-mini"},
        "llm": {"api_mode": "chat_completions"},
    })

    result = await text_module.acompletion(
        [{"role": "user", "content": "hello"}],
        task_type=TaskType.CHAT,
        model="primary",
        max_retries=2,
    )

    assert result == "fallback ok"
    assert [call["api_key"] for call in calls] == [
        "primary-key",
        "primary-key",
        "fallback-key",
    ]


@pytest.mark.anyio
async def test_stream_completion_falls_back_before_first_token(monkeypatch):
    from app.shared.infra.llm_support import stream as stream_module

    calls: list[dict] = []

    class FakeChatStream:
        def __init__(self) -> None:
            self._chunks = iter([
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(delta=SimpleNamespace(content="ok")),
                    ],
                ),
            ])

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._chunks)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    class FakeLiteLLM:
        async def aresponses(self, **kwargs):  # pragma: no cover - chat mode in this test
            raise AssertionError("Responses should not be used")

        async def acompletion(self, **kwargs):
            calls.append(kwargs)
            if kwargs["api_key"] == "primary-key":
                raise RuntimeError("primary stream down")
            return FakeChatStream()

    monkeypatch.setenv("LLM_API_KEY", "primary-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "fallback-key")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setattr(stream_module, "load_litellm", lambda: FakeLiteLLM())
    set_system_settings_override({
        "models": {"primary": "gpt-5.2"},
        "llm": {"api_mode": "chat_completions"},
    })

    chunks = [
        chunk
        async for chunk in stream_module.acompletion_stream(
            [{"role": "user", "content": "hello"}],
            task_type=TaskType.CHAT,
            model="primary",
            max_retries=1,
        )
    ]

    assert chunks == ["ok"]
    assert [call["api_key"] for call in calls] == ["primary-key", "fallback-key"]
    assert calls[1]["model"] == "deepseek-chat"


@pytest.mark.anyio
async def test_stream_completion_retries_empty_primary_before_fallback(monkeypatch):
    from app.shared.infra.llm_support import stream as stream_module

    calls: list[dict] = []

    async def no_sleep(_attempt: int, **_kwargs) -> None:
        return None

    class FakeResponsesStream:
        def __init__(self, chunks: list[object]) -> None:
            self._chunks = iter(chunks)

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._chunks)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    class FakeLiteLLM:
        async def aresponses(self, **kwargs):
            calls.append(kwargs)
            if kwargs["api_key"] == "primary-key" and len(calls) == 1:
                return FakeResponsesStream([])
            return FakeResponsesStream([
                SimpleNamespace(type=FakeResponseEventType("response.output_text.delta"), delta="retry ok"),
            ])

        async def acompletion(self, **kwargs):  # pragma: no cover - forced responses in this test
            raise AssertionError("Chat Completions should not be used")

    monkeypatch.setenv("LLM_API_KEY", "primary-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example.com")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "fallback-key")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "https://fallback-gateway.example.com")
    monkeypatch.setattr(stream_module, "load_litellm", lambda: FakeLiteLLM())
    monkeypatch.setattr(stream_module, "sleep_before_retry", no_sleep)
    set_system_settings_override({
        "models": {"primary": "gpt-5.4-mini"},
        "llm": {"api_mode": "responses"},
    })

    chunks = [
        chunk
        async for chunk in stream_module.acompletion_stream(
            [{"role": "user", "content": "hello"}],
            task_type=TaskType.CHAT,
            model="primary",
            max_retries=2,
        )
    ]

    assert chunks == ["retry ok"]
    assert [call["api_key"] for call in calls] == ["primary-key", "primary-key"]


@pytest.mark.anyio
async def test_stream_completion_does_not_fallback_after_empty_primary_exhausted(monkeypatch):
    from app.shared.infra.llm_support import stream as stream_module

    calls: list[dict] = []

    async def no_sleep(_attempt: int, **_kwargs) -> None:
        return None

    class FakeResponsesStream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class FakeLiteLLM:
        async def aresponses(self, **kwargs):
            calls.append(kwargs)
            return FakeResponsesStream()

        async def acompletion(self, **kwargs):  # pragma: no cover - forced responses in this test
            raise AssertionError("Chat Completions should not be used")

    monkeypatch.setenv("LLM_API_KEY", "primary-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example.com")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "fallback-key")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "https://fallback-gateway.example.com")
    monkeypatch.setattr(stream_module, "load_litellm", lambda: FakeLiteLLM())
    monkeypatch.setattr(stream_module, "sleep_before_retry", no_sleep)
    set_system_settings_override({
        "models": {"primary": "gpt-5.4-mini"},
        "llm": {"api_mode": "responses"},
    })

    with pytest.raises(LLMCallError):
        [
            chunk
            async for chunk in stream_module.acompletion_stream(
                [{"role": "user", "content": "hello"}],
                task_type=TaskType.CHAT,
                model="primary",
                max_retries=2,
            )
        ]

    assert [call["api_key"] for call in calls] == ["primary-key", "primary-key"]


@pytest.mark.anyio
async def test_stream_auto_responses_html_iteration_error_falls_back_to_chat(monkeypatch):
    from app.shared.infra.llm_support import stream as stream_module

    calls: list[tuple[str, dict]] = []

    class BrokenResponsesStream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise RuntimeError(
                "<html><head><title>Sub2API - AI API Gateway</title></head></html>. "
                "Check the reverse proxy or model server configuration."
            )

    class FakeChatStream:
        def __init__(self) -> None:
            self._chunks = iter([
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(delta=SimpleNamespace(content="chat ok")),
                    ],
                ),
            ])

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._chunks)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    class FakeLiteLLM:
        async def aresponses(self, **kwargs):
            calls.append(("responses", kwargs))
            return BrokenResponsesStream()

        async def acompletion(self, **kwargs):
            calls.append(("chat", kwargs))
            return FakeChatStream()

    monkeypatch.setenv("LLM_API_KEY", "primary-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example.com/v1")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setattr(stream_module, "load_litellm", lambda: FakeLiteLLM())
    set_system_settings_override({
        "models": {"primary": "gpt-5.5"},
        "llm": {"api_mode": "auto"},
    })

    chunks = [
        chunk
        async for chunk in stream_module.acompletion_stream(
            [{"role": "user", "content": "hello"}],
            task_type=TaskType.CHAT,
            model="primary",
            max_retries=1,
        )
    ]

    assert chunks == ["chat ok"]
    assert [kind for kind, _ in calls] == ["responses", "chat"]
    assert calls[0][1]["model"] == "gpt-5.5"
    assert calls[1][1]["model"] == "gpt-5.5"
    assert "input" in calls[0][1]
    assert "messages" in calls[1][1]


def test_llm_call_error_sanitizes_html_gateway_page():
    error = LLMCallError(
        reason=(
            "<!DOCTYPE html><html><head><title>Sub2API - AI API Gateway</title></head>"
            "<body><script>window.__APP_CONFIG__={}</script></body></html>"
        )
    )

    assert "上游网关返回了网页内容" in error.detail
    assert "Sub2API - AI API Gateway" in error.detail
    assert "<html" not in error.detail
    assert "__APP_CONFIG__" not in error.detail

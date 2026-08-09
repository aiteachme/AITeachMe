from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.shared.infra.llm_support.common import build_completion_context
from app.shared.infra.llm_support.native_tools import build_provider_native_tools
from app.shared.infra.llm_support.responses_adapter import provider_call_metadata, resolve_provider_call
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.settings import get_settings, set_system_settings_override
from app.workflows.common.model_policy import ProviderNativeToolPolicy


def teardown_function() -> None:
    set_system_settings_override({})


def test_native_web_search_routes_auto_to_openai_responses(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    set_system_settings_override({
        "models": {"primary": "gpt-5.4-mini"},
        "llm": {
            "api_mode": "auto",
            "responses_api_models": ["gpt-4.1"],
            "native_web_search": "auto",
            "native_web_search_external_access": False,
        },
    })
    native_tools = build_provider_native_tools(
        settings=get_settings(),
        web_search=True,
    )
    context = build_completion_context(task_type=TaskType.CHAT, model="primary")

    call = resolve_provider_call(
        context=context,
        call_kwargs={
            "model": "gpt-4.1",
            "messages": [{"role": "user", "content": "latest AI news"}],
            "provider_native_tools": native_tools,
        },
    )

    assert call.api_mode == "responses"
    assert call.kwargs["tools"] == [
        {"type": "web_search", "external_web_access": False},
    ]
    metadata = provider_call_metadata(call)
    assert metadata["llm_requested_api_mode"] == "auto"
    assert metadata["llm_initial_api_mode"] == "responses"
    assert metadata["llm_api_mode_route_reason"] == "auto_provider_native_tools"
    assert metadata["llm_provider_native_tool_types"] == ["web_search"]
    assert metadata["llm_auto_responses_chat_fallback_available"] is True
    assert "provider_native_tools" not in call.kwargs
    assert call.auto_chat_fallback_kwargs is not None
    assert "tools" not in call.auto_chat_fallback_kwargs


def test_native_tools_do_not_bypass_empty_responses_model_list(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    set_system_settings_override({
        "models": {"primary": "gpt-5.4-mini"},
        "llm": {"api_mode": "auto", "native_web_search": "force"},
    })
    context = build_completion_context(task_type=TaskType.CHAT, model="primary")

    call = resolve_provider_call(
        context=context,
        call_kwargs={
            "model": "gpt-4.1",
            "messages": [{"role": "user", "content": "latest AI news"}],
            "provider_native_tools": [
                {"type": "web_search", "mode": "force", "external_web_access": True},
            ],
        },
    )

    assert call.api_mode == "chat_completions"
    assert call.route_reason == "auto_plain_chat"
    assert "provider_native_tools" not in call.kwargs
    assert "tools" not in call.kwargs


def test_native_web_search_auto_is_sent_to_openai_compatible_responses_gateway(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example.com/v1")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    set_system_settings_override({
        "models": {"primary": "gpt-5.5"},
        "llm": {
            "api_mode": "auto",
            "responses_api_models": ["gpt-5.5"],
            "native_web_search": "auto",
        },
    })
    native_tools = build_provider_native_tools(
        settings=get_settings(),
        web_search=True,
    )
    context = build_completion_context(task_type=TaskType.CHAT, model="primary")

    call = resolve_provider_call(
        context=context,
        call_kwargs={
            "model": "gpt-5.5",
            "messages": [{"role": "user", "content": "latest AI news"}],
            "api_base": "https://gateway.example.com/v1",
            "custom_llm_provider": "openai",
            "provider_native_tools": native_tools,
        },
    )

    assert call.api_mode == "responses"
    assert call.kwargs["tools"] == [
        {"type": "web_search", "external_web_access": True},
    ]
    assert call.auto_chat_fallback_kwargs is not None
    assert call.requested_api_mode == "auto"
    assert call.route_reason == "auto_provider_native_tools"


def test_native_web_search_keeps_supported_responses_controls(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    set_system_settings_override({
        "models": {"primary": "gpt-5.5"},
        "llm": {"api_mode": "responses"},
    })
    context = build_completion_context(task_type=TaskType.CHAT, model="primary")

    call = resolve_provider_call(
        context=context,
        call_kwargs={
            "model": "gpt-5.5",
            "messages": [{"role": "user", "content": "research recent papers"}],
            "provider_native_tools": [
                {
                    "type": "web_search",
                    "mode": "force",
                    "search_context_size": "low",
                    "return_token_budget": "unlimited",
                    "filters": {"allowed_domains": ["openai.com"]},
                },
            ],
        },
    )

    assert call.api_mode == "responses"
    assert call.kwargs["tools"] == [
        {
            "type": "web_search",
            "search_context_size": "low",
            "return_token_budget": "unlimited",
            "filters": {"allowed_domains": ["openai.com"]},
        }
    ]


def test_native_file_search_requires_configured_vector_store_ids(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    set_system_settings_override({
        "models": {"primary": "gpt-5.4-mini"},
        "llm": {
            "api_mode": "auto",
            "responses_api_models": ["gpt-4.1"],
            "native_file_search": "auto",
            "native_file_search_vector_store_ids": "vs_course, vs_global",
            "native_file_search_max_results": 4,
        },
    })
    native_tools = build_provider_native_tools(
        settings=get_settings(),
        file_search=True,
    )
    context = build_completion_context(task_type=TaskType.CHAT, model="primary")

    call = resolve_provider_call(
        context=context,
        call_kwargs={
            "model": "gpt-4.1",
            "messages": [{"role": "user", "content": "find the proof in my files"}],
            "provider_native_tools": native_tools,
        },
    )

    assert call.api_mode == "responses"
    assert call.kwargs["tools"] == [
        {
            "type": "file_search",
            "vector_store_ids": ["vs_course", "vs_global"],
            "max_num_results": 4,
        },
    ]


def test_native_file_search_stays_disabled_without_vector_store_ids() -> None:
    set_system_settings_override({
        "llm": {
            "native_file_search": "auto",
            "native_file_search_vector_store_ids": "",
        },
    })

    assert build_provider_native_tools(settings=get_settings(), file_search=True) == []


def test_provider_native_tool_policy_can_disable_runtime_enabled_tools() -> None:
    set_system_settings_override({
        "llm": {
            "native_web_search": "force",
            "native_file_search": "force",
            "native_file_search_vector_store_ids": "vs_runtime",
        }
    })

    policy = ProviderNativeToolPolicy.disabled()

    assert policy.build(settings=get_settings(), web_search=True, file_search=True) == []


def test_provider_native_tool_policy_can_override_runtime_modes() -> None:
    set_system_settings_override({
        "llm": {
            "native_web_search": "off",
            "native_file_search": "off",
        }
    })

    policy = ProviderNativeToolPolicy(
        web_search="force",
        file_search="auto",
        web_search_external_access=False,
        file_search_vector_store_ids=("vs_policy",),
        file_search_max_results=2,
    )

    assert policy.build(settings=get_settings(), web_search=True, file_search=True) == [
        {
            "type": "web_search",
            "mode": "force",
            "external_web_access": False,
        },
        {
            "type": "file_search",
            "mode": "auto",
            "vector_store_ids": ["vs_policy"],
            "max_num_results": 2,
        },
    ]


@pytest.mark.anyio
async def test_project_function_tool_call_strips_provider_native_tools(monkeypatch) -> None:
    from app.shared.infra.llm_support import tool_calls

    calls: list[dict] = []

    class FakeLiteLLM:
        async def acompletion(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="", tool_calls=[]),
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=2, completion_tokens=3, total_tokens=5),
            )

    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setattr(tool_calls, "load_litellm", lambda: FakeLiteLLM())
    set_system_settings_override({
        "models": {"primary": "gpt-5.5"},
        "llm": {"api_mode": "auto"},
    })

    await tool_calls.acompletion_with_tools(
        [{"role": "user", "content": "查一下课程"}],
        tools=[{"type": "function", "function": {"name": "search_kb", "parameters": {}}}],
        task_type=TaskType.CHAT,
        model="primary",
        provider_native_tools=[{"type": "web_search", "mode": "force"}],
    )

    assert calls
    assert "provider_native_tools" not in calls[0]
    assert calls[0]["tools"] == [
        {"type": "function", "function": {"name": "search_kb", "parameters": {}}}
    ]

from __future__ import annotations

from app.shared.infra.llm_support.common import build_completion_context
from app.shared.infra.llm_support.native_tools import build_provider_native_tools
from app.shared.infra.llm_support.responses_adapter import resolve_provider_call
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.settings import get_settings, set_system_settings_override


def teardown_function() -> None:
    set_system_settings_override({})


def test_native_web_search_routes_auto_to_openai_responses(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    set_system_settings_override({
        "models": {"primary": "gpt-4.1"},
        "llm": {
            "api_mode": "auto",
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
    assert "provider_native_tools" not in call.kwargs
    assert call.auto_chat_fallback_kwargs is not None
    assert "tools" not in call.auto_chat_fallback_kwargs


def test_native_tools_are_not_sent_to_chat_completions(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    set_system_settings_override({
        "models": {"primary": "gpt-4.1"},
        "llm": {"api_mode": "chat_completions", "native_web_search": "force"},
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
    assert "tools" not in call.auto_chat_fallback_kwargs


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
        "models": {"primary": "gpt-4.1"},
        "llm": {
            "api_mode": "auto",
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

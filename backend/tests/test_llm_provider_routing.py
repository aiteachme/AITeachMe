from __future__ import annotations

from app.shared.infra.llm_support.common import build_completion_context, build_litellm_provider_kwargs
from app.shared.infra.llm_support.routing import LLMCallPurpose
from app.shared.infra.settings import reset_project_settings_cache


def test_build_provider_kwargs_for_anthropic(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("LLM_API_VERSION", raising=False)

    kwargs = build_litellm_provider_kwargs("claude-3-5-sonnet-latest")

    assert kwargs == {"custom_llm_provider": "anthropic"}


def test_build_provider_kwargs_for_gemini(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.delenv("LLM_API_VERSION", raising=False)

    kwargs = build_litellm_provider_kwargs("gemini-2.5-flash")

    assert kwargs == {"custom_llm_provider": "gemini"}


def test_build_provider_kwargs_for_azure_includes_api_version(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "azure")
    monkeypatch.setenv("LLM_API_VERSION", "2024-10-21")

    kwargs = build_litellm_provider_kwargs("gpt-4o-mini")

    assert kwargs == {
        "custom_llm_provider": "azure",
        "api_version": "2024-10-21",
    }


def test_build_provider_kwargs_for_ollama(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.delenv("LLM_API_VERSION", raising=False)

    kwargs = build_litellm_provider_kwargs("qwen2.5:7b")

    assert kwargs == {"custom_llm_provider": "ollama"}


def test_build_provider_kwargs_for_minimax_routes_to_anthropic(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "minimax")
    monkeypatch.delenv("LLM_API_VERSION", raising=False)

    kwargs = build_litellm_provider_kwargs("MiniMax-M2.7-highspeed")

    assert kwargs == {"custom_llm_provider": "anthropic"}


def test_build_provider_kwargs_for_openai_compatible_vendor_routes(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.delenv("LLM_API_VERSION", raising=False)

    deepseek_kwargs = build_litellm_provider_kwargs("deepseek-chat")
    siliconflow_kwargs = build_litellm_provider_kwargs("deepseek-ai/DeepSeek-V3.2")

    assert deepseek_kwargs == {"custom_llm_provider": "openai"}
    assert siliconflow_kwargs == {"custom_llm_provider": "openai"}


def test_build_provider_kwargs_prefers_prefixed_model(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_VERSION", "2024-10-21")

    kwargs = build_litellm_provider_kwargs("azure/my-deployment")

    assert kwargs == {
        "custom_llm_provider": "azure",
        "api_version": "2024-10-21",
    }


def test_build_provider_kwargs_keeps_openrouter_route_for_prefixed_models(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("LLM_API_VERSION", raising=False)

    kwargs = build_litellm_provider_kwargs("openai/gpt-4o-mini")

    assert kwargs == {"custom_llm_provider": "openrouter"}


def test_build_completion_context_allows_local_provider_without_api_key(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LLM_API_KEY", "")
    reset_project_settings_cache()

    context = build_completion_context(call_purpose=LLMCallPurpose.CHAT)

    assert context.api_key is None
    assert context.model == "qwen2.5"

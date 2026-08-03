from __future__ import annotations

import pytest

from app.schemas.system import ModelProbeRequest
from app.shared.infra.llm_support import common as llm_common
from app.shared.infra.settings import reset_project_settings_cache, set_system_settings_override
from app.workflows.support.system import settings as system_settings


def _reset_settings_state() -> None:
    reset_project_settings_cache()
    set_system_settings_override({})
    llm_common._LLM_LIMITER = None


@pytest.fixture(autouse=True)
def reset_settings_after_test():
    _reset_settings_state()
    yield
    _reset_settings_state()


@pytest.mark.anyio
async def test_settings_model_probe_tests_primary_reason_slot_with_runtime_api_routing(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setenv("LLM_API_KEY", "primary-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://primary-gateway.example.com")
    set_system_settings_override({
        "models": {
            "reason": "gpt-5.4-mini",
            "primary": "gpt-5.4-mini",
            "light": "gpt-5.4-mini",
        },
        "llm": {"api_mode": "responses"},
    })

    async def fake_completion(*_args, **kwargs):
        captured.update(kwargs)
        return "OK"

    monkeypatch.setattr(system_settings, "acompletion", fake_completion)

    result = await system_settings.test_settings_model_connection(
        ModelProbeRequest(model_slot="reason", endpoint_role="primary")
    )

    assert result.ok is True
    assert result.model_slot == "reason"
    assert result.endpoint_role == "primary"
    assert result.model == "gpt-5.4-mini"
    assert result.provider == "openai_compatible"
    assert result.api_mode == "responses"
    assert captured["model"] == "reason"
    assert "api_mode" not in captured
    assert captured["max_tokens"] == 16
    assert captured["timeout"] == 20
    assert captured["overall_timeout_s"] == 25
    assert captured["max_retries"] == 1


@pytest.mark.anyio
async def test_settings_model_probe_tests_fallback_light_slot_with_runtime_api_routing(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setenv("LLM_API_KEY", "primary-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://primary-gateway.example.com")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "fallback-key")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "https://fallback-gateway.example.com/v1")
    set_system_settings_override({
        "models": {
            "reason": "gpt-5.4-mini",
            "primary": "gpt-5.4-mini",
            "light": "gpt-5.4-mini",
        },
    })

    async def fake_completion(*_args, **kwargs):
        captured.update(kwargs)
        return "OK"

    monkeypatch.setattr(system_settings, "acompletion", fake_completion)

    result = await system_settings.test_settings_model_connection(
        ModelProbeRequest(model_slot="light", endpoint_role="fallback")
    )

    assert result.ok is True
    assert result.model_slot == "light"
    assert result.endpoint_role == "fallback"
    assert result.model == "gpt-5.4-mini"
    assert result.provider == "openai_compatible"
    assert result.api_mode == "auto"
    assert captured["model"] == "light"
    assert "api_mode" not in captured
    assert captured["max_tokens"] == 16
    assert captured["timeout"] == 20
    assert captured["overall_timeout_s"] == 25
    assert captured["max_retries"] == 1


@pytest.mark.anyio
async def test_settings_model_probe_uses_explicit_fallback_model(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setenv("LLM_API_KEY", "primary-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://primary-gateway.example.com")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "fallback-key")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")
    set_system_settings_override({
        "models": {
            "reason": "gpt-5.4-mini",
            "primary": "gpt-5.4-mini",
            "light": "gpt-5.4-mini",
        },
        "fallback_models": {"light": "gemini-3.1-flash-lite"},
    })

    async def fake_completion(*_args, **kwargs):
        captured.update(kwargs)
        return "OK"

    monkeypatch.setattr(system_settings, "acompletion", fake_completion)

    result = await system_settings.test_settings_model_connection(
        ModelProbeRequest(model_slot="light", endpoint_role="fallback")
    )

    assert result.ok is True
    assert result.model == "gemini-3.1-flash-lite"
    assert result.provider == "gemini"
    assert result.api_mode == "auto"
    assert captured["model"] == "light"
    assert "api_mode" not in captured


@pytest.mark.anyio
async def test_settings_model_probe_reports_missing_fallback_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "primary-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://primary-gateway.example.com")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "")

    result = await system_settings.test_settings_model_connection(
        ModelProbeRequest(model_slot="primary", endpoint_role="fallback")
    )

    assert result.ok is False
    assert result.model_slot == "primary"
    assert result.endpoint_role == "fallback"
    assert result.api_mode == "auto"
    assert "备用模型网关未配置" in result.message

from __future__ import annotations

import pytest

from app.shared.infra.embedding import api as embedding_api
from app.shared.infra.llm_support import common as llm_common
from app.shared.infra.settings import reset_project_settings_cache, set_system_settings_override


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
async def test_embedding_api_base_is_passed_through_without_rewriting(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setenv("LLM_API_KEY", "primary-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example.com")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    set_system_settings_override({
        "models": {"embedding": "text-embedding-v4"},
        "llm": {"primary_model_allowlist": ["text-embedding-v4"]},
    })

    async def fake_call_embedding(
        model: str,
        batch: list[str],
        api_base: str,
        api_key: str | None,
        provider: str | None = None,
        api_version: str | None = None,
    ) -> list[list[float]]:
        captured.update(
            {
                "model": model,
                "batch": batch,
                "api_base": api_base,
                "api_key": api_key,
                "provider": provider,
                "api_version": api_version,
            }
        )
        return [[0.1, 0.2, 0.3]]

    monkeypatch.setattr(embedding_api, "_call_embedding", fake_call_embedding)

    vectors = await embedding_api.aembed_texts(["hello"], batch_size=1)

    assert vectors == [[0.1, 0.2, 0.3]]
    assert captured == {
        "model": "text-embedding-v4",
        "batch": ["hello"],
        "api_base": "https://gateway.example.com",
        "api_key": "primary-key",
        "provider": "openai_compatible",
        "api_version": None,
    }


@pytest.mark.anyio
async def test_embedding_model_outside_primary_allowlist_uses_fallback_endpoint(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setenv("LLM_API_KEY", "primary-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://primary.example.com")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "fallback-key")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "https://fallback.example.com/v1")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    set_system_settings_override({
        "models": {"embedding": "text-embedding-v4"},
        "llm": {"primary_model_allowlist": ["gpt-5.5"]},
    })

    async def fake_call_embedding(
        model: str,
        batch: list[str],
        api_base: str,
        api_key: str | None,
        provider: str | None = None,
        api_version: str | None = None,
    ) -> list[list[float]]:
        captured.update(
            {
                "model": model,
                "batch": batch,
                "api_base": api_base,
                "api_key": api_key,
                "provider": provider,
                "api_version": api_version,
            }
        )
        return [[0.4, 0.5]]

    monkeypatch.setattr(embedding_api, "_call_embedding", fake_call_embedding)

    vectors = await embedding_api.aembed_texts(["hello"], batch_size=1)

    assert vectors == [[0.4, 0.5]]
    assert captured == {
        "model": "text-embedding-v4",
        "batch": ["hello"],
        "api_base": "https://fallback.example.com/v1",
        "api_key": "fallback-key",
        "provider": "openai_compatible",
        "api_version": None,
    }

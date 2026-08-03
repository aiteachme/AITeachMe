from __future__ import annotations

from contextlib import contextmanager

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
async def test_embedding_uses_primary_endpoint_without_rewriting_base(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setenv("LLM_API_KEY", "primary-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://primary.example.com")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "fallback-key")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "https://fallback.example.com/v1")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    set_system_settings_override({
        "models": {"embedding": "text-embedding-v4"},
    })

    async def fake_call_embedding(
        model: str,
        batch: list[str],
        api_base: str,
        api_key: str | None,
        provider: str | None = None,
        api_version: str | None = None,
        provider_timeout_s: int | None = None,
        overall_timeout_s: int | None = None,
    ) -> list[list[float]]:
        captured.update(
            {
                "model": model,
                "batch": batch,
                "api_base": api_base,
                "api_key": api_key,
                "provider": provider,
                "api_version": api_version,
                "provider_timeout_s": provider_timeout_s,
                "overall_timeout_s": overall_timeout_s,
            }
        )
        return [[0.4, 0.5]]

    monkeypatch.setattr(embedding_api, "_call_embedding", fake_call_embedding)

    vectors = await embedding_api.aembed_texts(["hello"], batch_size=1)

    assert vectors == [[0.4, 0.5]]
    assert captured == {
        "model": "text-embedding-v4",
        "batch": ["hello"],
        "api_base": "https://primary.example.com",
        "api_key": "primary-key",
        "provider": "openai_compatible",
        "api_version": None,
        "provider_timeout_s": 120,
        "overall_timeout_s": 122,
    }


@pytest.mark.anyio
async def test_embedding_batches_respect_explicit_concurrency_window(monkeypatch) -> None:
    captured_run_many: dict[str, object] = {}
    captured_traces: list[dict[str, object]] = []
    monkeypatch.setenv("LLM_API_KEY", "primary-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example.com")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    set_system_settings_override({
        "models": {"embedding": "text-embedding-v4"},
    })

    class FakeTraceRun:
        def __init__(self) -> None:
            self.outputs: dict[str, object] | None = None

        def end(self, outputs=None) -> None:
            self.outputs = dict(outputs or {})

    @contextmanager
    def fake_trace_substep(name: str, **kwargs):
        run = FakeTraceRun()
        captured_traces.append({"name": name, "kwargs": kwargs, "run": run})
        yield run

    async def fake_call_embedding(
        model: str,
        batch: list[str],
        api_base: str,
        api_key: str | None,
        provider: str | None = None,
        api_version: str | None = None,
        provider_timeout_s: int | None = None,
        overall_timeout_s: int | None = None,
    ) -> list[list[float]]:
        return [[float(len(item))] for item in batch]

    async def fake_run_llm_tasks(items, worker, *, max_concurrent=None, on_result=None):
        captured_run_many["items"] = list(items)
        captured_run_many["max_concurrent"] = max_concurrent
        results = []
        for item in captured_run_many["items"]:
            result = await worker(item)
            if on_result is not None:
                await on_result(int(item), item, result)
            results.append(result)
        return results

    monkeypatch.setattr(embedding_api, "_call_embedding", fake_call_embedding)
    monkeypatch.setattr(embedding_api, "run_llm_tasks", fake_run_llm_tasks)
    monkeypatch.setattr(embedding_api, "trace_substep", fake_trace_substep)

    vectors = await embedding_api.aembed_texts(
        ["a", "bb", "ccc", "dddd", "eeeee"],
        batch_size=2,
        max_concurrent=3,
    )

    assert vectors == [[1.0], [2.0], [3.0], [4.0], [5.0]]
    assert captured_run_many == {"items": [0, 1, 2], "max_concurrent": 3}
    assert captured_traces[0]["name"] == "Embedding：批量生成"
    assert captured_traces[0]["kwargs"]["inputs"]["batch_count"] == 3
    assert captured_traces[0]["kwargs"]["inputs"]["max_concurrent"] == 3
    trace_run = captured_traces[0]["run"]
    assert isinstance(trace_run, FakeTraceRun)
    assert trace_run.outputs is not None
    assert trace_run.outputs["status"] == "completed"
    assert trace_run.outputs["batch_count"] == 3


@pytest.mark.anyio
async def test_embedding_provider_call_receives_timeout(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeBadRequestError(Exception):
        pass

    class FakeLitellm:
        drop_params = False

        class exceptions:
            BadRequestError = FakeBadRequestError

        async def aembedding(self, **kwargs):
            captured.update(kwargs)

            class Response:
                data = [{"embedding": [0.1, 0.2]}]

            return Response()

    monkeypatch.setattr(embedding_api, "load_litellm", lambda: FakeLitellm())

    vectors = await embedding_api._call_embedding(
        model="text-embedding-v4",
        batch=["hello"],
        api_base="https://gateway.example.com",
        api_key="key",
        provider="openai_compatible",
        provider_timeout_s=17,
        overall_timeout_s=19,
    )

    assert vectors == [[0.1, 0.2]]
    assert captured["timeout"] == 17

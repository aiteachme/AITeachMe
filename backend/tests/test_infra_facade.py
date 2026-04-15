from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from app.shared.infra.facade import (
    InfraRuntime,
    build_infra_context,
    build_research_context,
    call_llm_structured,
    call_llm_text,
    list_tools,
    run_generation_eval,
    run_rag_eval,
    run_tool,
)
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.search.types import SearchResult
from app.shared.infra.tools.definition import ToolDefinition
from app.shared.infra.tools import registry as registry_module
from app.shared.infra.tools.registry import ToolRegistry


class _StructuredAnswer(BaseModel):
    answer: str


class _FakeRetriever:
    def __init__(self, name: str, results: list[SearchResult]) -> None:
        self.name = name
        self.results = results
        self.calls: list[str] = []

    async def traced_search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        self.calls.append(query)
        return list(self.results[:max_results])


@pytest.fixture(autouse=True)
def reset_tool_registry():
    original = registry_module._registry
    registry_module._registry = ToolRegistry()
    yield
    registry_module._registry = original


def test_llm_facade_forwards_task_type_and_structured_model(monkeypatch) -> None:
    captured: dict[str, object] = {}
    ctx = build_infra_context(subject="math", workflow="digest.docgen", lane="docgen", node="write")

    async def fake_text(messages, *, task_type, **kwargs):
        captured["text_task_type"] = task_type
        captured["text_messages"] = messages
        captured["text_kwargs"] = kwargs
        return "ok"

    async def fake_structured(response_model, messages, *, task_type, **kwargs):
        captured["structured_task_type"] = task_type
        captured["structured_messages"] = messages
        return response_model(answer="structured-ok")

    monkeypatch.setattr("app.shared.infra.facade.llm.acompletion", fake_text)
    monkeypatch.setattr("app.shared.infra.facade.llm.acompletion_structured", fake_structured)

    text_result = asyncio.run(call_llm_text(ctx, [{"role": "user", "content": "hi"}], task_type=TaskType.CHAT))
    structured = asyncio.run(
        call_llm_structured(
            ctx,
            _StructuredAnswer,
            [{"role": "user", "content": "hi"}],
            task_type=TaskType.EXTRACT,
        )
    )

    assert text_result.content == "ok"
    assert captured["text_task_type"] is TaskType.CHAT
    assert structured.answer == "structured-ok"
    assert captured["structured_task_type"] is TaskType.EXTRACT


def test_research_facade_skips_external_when_local_has_enough(monkeypatch) -> None:
    local = _FakeRetriever(
        "local_rag",
        [
            SearchResult(url="local://chunk/1", title="偏导数", snippet="偏导数描述坐标方向变化率", source="local_rag"),
            SearchResult(url="local://chunk/2", title="曲面切片", snippet="曲面切片帮助理解几何意义", source="local_rag"),
        ],
    )
    web = _FakeRetriever(
        "duckduckgo",
        [SearchResult(url="https://example.com", title="web", snippet="web", source="duckduckgo")],
    )

    monkeypatch.setattr(
        "app.shared.infra.facade.research.get_retrievers_for_subject",
        lambda **_kwargs: [local, web],
    )
    monkeypatch.setattr(
        "app.shared.infra.facade.research.get_configured_retriever_names",
        lambda **_kwargs: ["local_rag", "duckduckgo"],
    )

    ctx = build_infra_context(subject="math", workflow="digest.docgen")
    result = asyncio.run(
        build_research_context(
            ctx,
            query="偏导数 几何意义",
            read=False,
            compress=False,
            max_sources=5,
        )
    )

    assert result.local_hits == 2
    assert result.web_hits == 0
    assert web.calls == []
    assert "偏导数" in result.dense_context
    assert result.metadata["configured_retrievers"] == ["local_rag", "duckduckgo"]


def test_tool_facade_blocks_unapproved_high_risk_tool() -> None:
    calls: list[str] = []

    async def dangerous_tool(command: str) -> str:
        calls.append(command)
        return "ran"

    registry_module.get_tool_registry().register(
        ToolDefinition(
            name="execute_code",
            description="run code",
            parameters={"type": "object"},
            handler=dangerous_tool,
            is_async=True,
            risk_level="high",
            requires_approval=True,
        )
    )
    ctx = build_infra_context(subject="math")

    blocked = asyncio.run(run_tool(ctx, "execute_code", {"command": "echo hi"}))
    approved = asyncio.run(run_tool(ctx, "execute_code", {"command": "echo hi"}, approved=True))

    assert blocked.blocked is True
    assert calls == ["echo hi"]
    assert approved.success is True
    assert approved.result == "ran"


def test_tool_facade_lists_metadata_and_injects_subject() -> None:
    async def search_tool(subject: str, query: str) -> str:
        return f"{subject}:{query}"

    registry_module.get_tool_registry().register(
        ToolDefinition(
            name="search_kb",
            description="search",
            parameters={"type": "object"},
            handler=search_tool,
            is_async=True,
            tags=["retrieval"],
            scopes=["knowledge"],
            requires_subject=True,
        )
    )
    ctx = build_infra_context(subject="math")

    cards = list_tools(ctx, tags=["retrieval"])
    result = asyncio.run(run_tool(ctx, "search_kb", {"query": "偏导数"}))

    assert [card.name for card in cards] == ["search_kb"]
    assert cards[0].requires_subject is True
    assert result.result == "math:偏导数"


def test_eval_facade_returns_deterministic_scores() -> None:
    ctx = build_infra_context(subject="math")

    rag = asyncio.run(
        run_rag_eval(
            ctx,
            {
                "query": "偏导数 几何意义",
                "answer": "偏导数描述变化率",
                "context": "偏导数的几何意义是坐标方向变化率。",
                "threshold": 0.1,
            },
        )
    )
    generation = asyncio.run(
        run_generation_eval(
            ctx,
            {
                "output": "偏导数可以通过曲面切片理解。",
                "required_terms": ["偏导数", "曲面切片"],
            },
        )
    )

    assert rag.passed is True
    assert generation.score == 1.0
    assert generation.passed is True


def test_infra_runtime_wraps_facade_methods() -> None:
    runtime = InfraRuntime(build_infra_context(subject="math"))

    summary = runtime.get_runtime_summary()

    assert summary["context"]["subject"] == "math"

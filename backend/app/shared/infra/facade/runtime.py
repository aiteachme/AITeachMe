"""Typed runtime facade combining shared infra capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Mapping, TypeVar

from app.schemas.llm import ChatMessage
from app.shared.infra.llm_support.routing import TaskType

from .context import InfraContext
from .evals import EvalResult, run_generation_eval, run_rag_eval
from .llm import LLMTextResult, call_llm_structured, call_llm_text, stream_llm_text
from .research import ResearchContext, build_research_context, read_sources
from .summary import get_runtime_summary
from .tools import ToolCard, ToolRunResult, list_tools, run_tool

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class InfraRuntime:
    """Advanced typed entrypoint for shared infra capabilities."""

    context: InfraContext

    async def call_llm_text(
        self,
        messages: list[ChatMessage],
        *,
        task_type: TaskType = TaskType.DEFAULT,
        **kwargs,
    ) -> LLMTextResult:
        return await call_llm_text(self.context, messages, task_type=task_type, **kwargs)

    async def call_llm_structured(
        self,
        response_model: type[T],
        messages: list[ChatMessage],
        *,
        task_type: TaskType = TaskType.DEFAULT,
        **kwargs,
    ) -> T:
        return await call_llm_structured(self.context, response_model, messages, task_type=task_type, **kwargs)

    def stream_llm_text(
        self,
        messages: list[ChatMessage],
        *,
        task_type: TaskType = TaskType.DEFAULT,
        **kwargs,
    ) -> AsyncIterator[str]:
        return stream_llm_text(self.context, messages, task_type=task_type, **kwargs)

    async def build_research_context(self, **kwargs: Any) -> ResearchContext:
        return await build_research_context(self.context, **kwargs)

    async def read_sources(self, urls: list[str], **kwargs: Any):
        return await read_sources(self.context, urls, **kwargs)

    def list_tools(self, **kwargs: Any) -> list[ToolCard]:
        return list_tools(self.context, **kwargs)

    async def run_tool(self, name: str, arguments: Mapping[str, Any] | None = None, **kwargs: Any) -> ToolRunResult:
        return await run_tool(self.context, name, arguments, **kwargs)

    async def run_rag_eval(self, case: dict[str, Any], **kwargs: Any) -> EvalResult:
        return await run_rag_eval(self.context, case, **kwargs)

    async def run_generation_eval(self, case: dict[str, Any], **kwargs: Any) -> EvalResult:
        return await run_generation_eval(self.context, case, **kwargs)

    def get_runtime_summary(self) -> dict[str, Any]:
        return get_runtime_summary(self.context)


__all__ = ["InfraRuntime"]

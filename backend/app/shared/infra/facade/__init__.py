"""Stable facade entrypoints for shared infra capabilities."""

from app.shared.infra.facade.context import InfraContext, build_infra_context
from app.shared.infra.facade.evals import EvalResult, run_generation_eval, run_rag_eval
from app.shared.infra.facade.llm import LLMTextResult, call_llm_structured, call_llm_text, stream_llm_text
from app.shared.infra.facade.research import ResearchContext, build_research_context, read_sources
from app.shared.infra.facade.runtime import InfraRuntime
from app.shared.infra.facade.summary import get_runtime_summary
from app.shared.infra.facade.tools import ToolCard, ToolRunResult, list_tools, run_tool

__all__ = [
    "EvalResult",
    "InfraContext",
    "InfraRuntime",
    "LLMTextResult",
    "ResearchContext",
    "ToolCard",
    "ToolRunResult",
    "build_infra_context",
    "build_research_context",
    "call_llm_structured",
    "call_llm_text",
    "get_runtime_summary",
    "list_tools",
    "read_sources",
    "run_generation_eval",
    "run_rag_eval",
    "run_tool",
    "stream_llm_text",
]

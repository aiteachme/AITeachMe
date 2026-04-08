"""Public LiteLLM helpers re-exported from the internal support package."""

from app.shared.infra.llm_support import (
    _langsmith_inputs,
    _langsmith_outputs,
    _langsmith_trace_kwargs,
    _sanitize_langsmith_value,
    acompletion,
    acompletion_stream,
    acompletion_structured,
    acompletion_with_fallback,
    acompletion_with_tools,
    resolve_llm_tier,
)

__all__ = [
    "acompletion",
    "acompletion_stream",
    "acompletion_structured",
    "acompletion_with_fallback",
    "acompletion_with_tools",
    "resolve_llm_tier",
    "_langsmith_inputs",
    "_langsmith_outputs",
    "_langsmith_trace_kwargs",
    "_sanitize_langsmith_value",
]

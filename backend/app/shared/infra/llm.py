"""Compatibility shim for the old flat LLM helper import path.

New code should import from `app.shared.infra.llm_support`.
"""

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

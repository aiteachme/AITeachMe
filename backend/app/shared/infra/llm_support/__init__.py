"""Public LiteLLM helpers exposed as the shared infra LLM package."""

from .fallback import acompletion_with_fallback, resolve_llm_tier
from .stream import acompletion_stream
from .structured_calls import acompletion_structured
from .text import acompletion
from .tool_calls import acompletion_with_tools
from .observability import (
    _langsmith_inputs,
    _langsmith_outputs,
    _langsmith_trace_kwargs,
    _sanitize_langsmith_value,
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

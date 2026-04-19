"""Public LiteLLM helpers exposed as the shared infra LLM package."""

from .fallback import acompletion_with_fallback
from .image import GeneratedImage, ImageGenerationResult, agenerate_image
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
    "agenerate_image",
    "GeneratedImage",
    "ImageGenerationResult",
    "_langsmith_inputs",
    "_langsmith_outputs",
    "_langsmith_trace_kwargs",
    "_sanitize_langsmith_value",
]

"""Public LiteLLM helpers exposed as the shared infra LLM package.

The LLM stack is intentionally imported on first use. API modules import these
symbols during route registration, while LiteLLM/Instructor are comparatively
heavy and only needed when an actual model call is made.
"""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "acompletion",
    "acompletion_stream",
    "acompletion_structured",
    "acompletion_with_fallback",
    "acompletion_with_tools",
    "agenerate_image",
    "GeneratedImage",
    "ImageGenerationResult",
    "LLMTaskHandle",
    "LLMTaskScheduler",
    "LLMTaskSnapshot",
    "get_llm_scheduler",
    "run_llm_tasks",
    "submit_llm_task",
    "get_llm_concurrency_limit",
    "get_llm_concurrency_limiter",
    "_langsmith_inputs",
    "_langsmith_outputs",
    "_langsmith_trace_kwargs",
    "_sanitize_langsmith_value",
]

_ATTR_TO_MODULE = {
    "acompletion": "app.shared.infra.llm_support.text",
    "acompletion_stream": "app.shared.infra.llm_support.stream",
    "acompletion_structured": "app.shared.infra.llm_support.structured_calls",
    "acompletion_with_fallback": "app.shared.infra.llm_support.fallback",
    "acompletion_with_tools": "app.shared.infra.llm_support.tool_calls",
    "agenerate_image": "app.shared.infra.llm_support.image",
    "GeneratedImage": "app.shared.infra.llm_support.image",
    "ImageGenerationResult": "app.shared.infra.llm_support.image",
    "LLMTaskHandle": "app.shared.infra.llm_support.scheduler",
    "LLMTaskScheduler": "app.shared.infra.llm_support.scheduler",
    "LLMTaskSnapshot": "app.shared.infra.llm_support.scheduler",
    "get_llm_scheduler": "app.shared.infra.llm_support.scheduler",
    "run_llm_tasks": "app.shared.infra.llm_support.scheduler",
    "submit_llm_task": "app.shared.infra.llm_support.scheduler",
    "get_llm_concurrency_limit": "app.shared.infra.llm_support.common",
    "get_llm_concurrency_limiter": "app.shared.infra.llm_support.common",
    "_langsmith_inputs": "app.shared.infra.llm_support.observability",
    "_langsmith_outputs": "app.shared.infra.llm_support.observability",
    "_langsmith_trace_kwargs": "app.shared.infra.llm_support.observability",
    "_sanitize_langsmith_value": "app.shared.infra.llm_support.observability",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value

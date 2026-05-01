"""Shared LangSmith tracing helpers for digest prompt builders."""

from __future__ import annotations

from typing import Any, TypeVar

from app.shared.infra.env_support import get_env_bool
from app.shared.infra.observability.trace import (
    get_llm_trace_context,
    langsmith_trace,
    sanitize_langsmith_input,
    sanitize_langsmith_output,
)

T = TypeVar("T")


def trace_prompt_build(
    name: str,
    *,
    inputs: dict[str, Any],
    output: T,
) -> T:
    """Trace one prompt-building step and return the original prompt object."""

    if not get_env_bool("AITM_TRACE_PROMPT_BUILDERS", False):
        return output

    context = get_llm_trace_context()
    with langsmith_trace(
        name=f"Prompt：{name}",
        run_type="prompt",
        inputs=sanitize_langsmith_input(inputs, field_name="prompt_inputs"),
        course_id=context.course_id,
        build_session_id=context.build_session_id,
        workflow=context.workflow,
        lane=context.lane,
        node=context.node,
        extra_metadata={"prompt_builder": name},
        extra_tags=[f"prompt:{name}"],
    ) as run:
        if run is not None:
            run.end(outputs={"prompt": sanitize_langsmith_output(output, field_name="prompt")})
    return output


__all__ = ["trace_prompt_build"]

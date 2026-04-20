"""Shared LangSmith tracing helpers for digest prompt builders."""

from __future__ import annotations

from typing import Any, TypeVar

from app.shared.infra.observability.trace import (
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

    with langsmith_trace(
        name=f"Prompt：{name}",
        run_type="prompt",
        inputs=sanitize_langsmith_input(inputs, field_name="prompt_inputs"),
        extra_metadata={"prompt_builder": name},
        extra_tags=[f"prompt:{name}"],
    ) as run:
        if run is not None:
            run.end(outputs={"prompt": sanitize_langsmith_output(output, field_name="prompt")})
    return output


__all__ = ["trace_prompt_build"]

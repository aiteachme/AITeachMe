"""Shared LangSmith tracing for workflow prompt builders."""

from __future__ import annotations

import hashlib
import json
from typing import Any, TypeVar

from app.shared.infra.observability.trace import (
    get_llm_trace_context,
    langsmith_trace,
    sanitize_langsmith_input,
    sanitize_langsmith_output,
)

T = TypeVar("T")
_PROMPT_TRACE_JSON_BUDGET_BYTES = 8 * 1024


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _bounded_prompt_trace_value(value: Any) -> Any:
    """Keep one prompt trace value small while retaining audit metadata."""

    serialized = _json_bytes(value)
    if len(serialized) <= _PROMPT_TRACE_JSON_BUDGET_BYTES:
        return value

    preview_bytes = serialized[: _PROMPT_TRACE_JSON_BUDGET_BYTES // 2]
    preview = preview_bytes.decode("utf-8", errors="ignore")
    compact = {
        "truncated": True,
        "preview": preview,
        "original_json_chars": len(serialized.decode("utf-8", errors="replace")),
        "original_json_bytes": len(serialized),
        "sha256": hashlib.sha256(serialized).hexdigest(),
    }
    while len(_json_bytes(compact)) > _PROMPT_TRACE_JSON_BUDGET_BYTES and compact["preview"]:
        compact["preview"] = compact["preview"][: len(compact["preview"]) // 2]
    return compact


def trace_prompt_build(
    name: str,
    *,
    inputs: dict[str, Any],
    output: T,
) -> T:
    """Trace one prompt-building step and return the original prompt object."""

    context = get_llm_trace_context()
    trace_inputs = _bounded_prompt_trace_value(
        sanitize_langsmith_input(inputs, field_name="prompt_inputs")
    )
    trace_output = _bounded_prompt_trace_value(
        sanitize_langsmith_output(output, field_name="prompt")
    )
    with langsmith_trace(
        name=f"Prompt：{name}",
        run_type="prompt",
        inputs=trace_inputs,
        course_id=context.course_id,
        build_session_id=context.build_session_id,
        workflow=context.workflow,
        lane=context.lane,
        node=context.node,
        extra_metadata={"prompt_builder": name},
        extra_tags=[f"prompt:{name}"],
    ) as run:
        if run is not None:
            run.end(outputs={"prompt": trace_output})
    return output


__all__ = ["trace_prompt_build"]

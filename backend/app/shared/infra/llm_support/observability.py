"""Helpers for LangSmith-compatible LLM observability payloads."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from app.schemas.llm import ChatMessage
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.observability import (
    get_llm_trace_context,
    langsmith_capture_inputs_enabled,
    langsmith_capture_outputs_enabled,
    sanitize_langsmith_text as _shared_sanitize_langsmith_text,
    sanitize_langsmith_value as _shared_sanitize_langsmith_value,
)

def _langsmith_usage(
    *,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
) -> dict[str, int]:
    return {
        "input_tokens": int(prompt_tokens),
        "output_tokens": int(completion_tokens),
        "total_tokens": int(total_tokens),
    }


def _serialize_langsmith_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _model_provider_and_name(model: str) -> tuple[str, str]:
    normalized = str(model or "").strip()
    if not normalized:
        return "unknown", ""
    if "/" in normalized:
        provider, model_name = normalized.split("/", 1)
        return provider or "unknown", model_name or normalized
    return "openai", normalized


def _resolved_trace_model(
    call_kwargs: Mapping[str, Any],
    fallback_model: str,
) -> tuple[str, str, str]:
    raw_model = str(call_kwargs.get("model") or fallback_model).strip() or fallback_model
    provider, model_name = _model_provider_and_name(raw_model)
    return raw_model, provider, model_name or fallback_model


def _sanitize_langsmith_text(
    text: str,
    *,
    capture_text: bool,
    field_name: str = "",
) -> str:
    return _shared_sanitize_langsmith_text(
        text,
        capture_text=capture_text,
        field_name=field_name,
    )


def _sanitize_langsmith_value(
    value: Any,
    *,
    capture_text: bool,
    field_name: str = "",
) -> Any:
    return _shared_sanitize_langsmith_value(
        value,
        capture_text=capture_text,
        field_name=field_name,
    )


def _langsmith_tool_calls(message: Any) -> list[dict[str, Any]]:
    tool_calls = getattr(message, "tool_calls", None) or []
    return [
        {
            "id": tool_call.id,
            "type": tool_call.type or "function",
            "function": {
                "name": tool_call.function.name,
                "arguments": tool_call.function.arguments,
            },
        }
        for tool_call in tool_calls
    ]


def _langsmith_inputs(
    *,
    call_model: str,
    messages: list[ChatMessage],
    tools: list[dict] | None = None,
) -> dict[str, Any]:
    capture_inputs = langsmith_capture_inputs_enabled()
    inputs: dict[str, Any] = {
        "model": _sanitize_langsmith_text(call_model, capture_text=True, field_name="model"),
        "messages": _sanitize_langsmith_value(messages, capture_text=capture_inputs, field_name="messages"),
    }
    if tools:
        inputs["tools"] = _sanitize_langsmith_value(tools, capture_text=capture_inputs, field_name="tools")
    return inputs


def _langsmith_outputs(
    *,
    text: str | None = None,
    result: Any = None,
    tool_calls: list[dict[str, Any]] | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
) -> dict[str, Any]:
    capture_outputs = langsmith_capture_outputs_enabled()
    assistant_message: dict[str, Any] = {
        "role": "assistant",
        "content": _sanitize_langsmith_value(
            text if text is not None else "",
            capture_text=capture_outputs,
            field_name="content",
        ),
    }
    if tool_calls:
        assistant_message["tool_calls"] = _sanitize_langsmith_value(
            tool_calls,
            capture_text=capture_outputs,
            field_name="tool_calls",
        )

    outputs: dict[str, Any] = {
        "choices": [{"message": assistant_message}],
        "usage_metadata": _langsmith_usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        ),
    }
    if result is not None:
        if capture_outputs:
            outputs["result"] = _sanitize_langsmith_value(result, capture_text=True, field_name="result")
        else:
            outputs["result_type"] = type(result).__name__
    return outputs


def _langsmith_invocation_params(call_kwargs: Mapping[str, Any]) -> dict[str, Any]:
    capture_inputs = langsmith_capture_inputs_enabled()
    invocation_params: dict[str, Any] = {}
    for key in (
        "temperature",
        "max_tokens",
        "top_p",
        "presence_penalty",
        "frequency_penalty",
        "stop",
        "stream",
        "tool_choice",
        "response_format",
    ):
        value = call_kwargs.get(key)
        if value in (None, "", [], {}):
            continue
        if key == "max_tokens":
            invocation_params[key] = int(value)
            continue
        if key in {"temperature", "top_p", "presence_penalty", "frequency_penalty"}:
            invocation_params[key] = float(value)
            continue
        if isinstance(value, bool):
            invocation_params[key] = value
            continue
        invocation_params[key] = _sanitize_langsmith_value(
            value,
            capture_text=capture_inputs,
            field_name=key,
        )
    return invocation_params


def _record_new_token_event(trace_run: Any | None) -> None:
    if trace_run is None:
        return
    add_event = getattr(trace_run, "add_event", None)
    if callable(add_event):
        try:
            add_event({"name": "new_token"})
        except Exception:
            return


def _end_langsmith_trace(
    trace_run: Any | None,
    *,
    text: str | None = None,
    result: Any = None,
    tool_calls: list[dict[str, Any]] | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
) -> None:
    if trace_run is None:
        return
    trace_run.end(
        outputs=_langsmith_outputs(
            text=text,
            result=result,
            tool_calls=tool_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
    )


def _langsmith_llm_metadata(
    *,
    task_type: TaskType,
    provider: str,
    model_name: str,
    invocation_params: Mapping[str, Any] | None = None,
    attempt: int | None = None,
    mode: str,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "task_type": task_type.value,
        "mode": mode,
        "model": model_name,
        "ls_provider": provider,
        "ls_model_name": model_name,
        "ls_model_type": "chat",
    }
    if invocation_params:
        metadata["ls_invocation_params"] = dict(invocation_params)
        if "temperature" in invocation_params:
            metadata["ls_temperature"] = invocation_params["temperature"]
        if "max_tokens" in invocation_params:
            metadata["ls_max_tokens"] = invocation_params["max_tokens"]
        if "stop" in invocation_params:
            metadata["ls_stop"] = invocation_params["stop"]
    if attempt is not None:
        metadata["attempt"] = attempt
    return metadata


def _langsmith_trace_kwargs(
    *,
    task_type: TaskType,
    call_model: str,
    provider: str,
    model_name: str,
    mode: str,
    messages: list[ChatMessage],
    call_kwargs: Mapping[str, Any] | None = None,
    attempt: int | None = None,
    tools: list[dict] | None = None,
) -> dict[str, Any]:
    trace_context = get_llm_trace_context()
    invocation_params = _langsmith_invocation_params(call_kwargs or {})
    return {
        "inputs": _langsmith_inputs(call_model=call_model, messages=messages, tools=tools),
        "subject": trace_context.subject,
        "build_session_id": trace_context.build_session_id,
        "workflow": trace_context.workflow,
        "lane": trace_context.lane,
        "node": trace_context.node,
        "extra_metadata": _langsmith_llm_metadata(
            task_type=task_type,
            provider=provider,
            model_name=model_name,
            invocation_params=invocation_params,
            attempt=attempt,
            mode=mode,
        ),
        "extra_tags": [f"task:{task_type.value}", f"mode:{mode}"],
    }

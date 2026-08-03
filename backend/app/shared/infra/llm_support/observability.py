"""Helpers for LangSmith-compatible LLM observability payloads."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from app.schemas.llm import ChatMessage
from app.shared.infra.llm_support.routing import normalize_task_type
from app.shared.infra.observability.trace import (
    get_llm_trace_context,
    langsmith_capture_inputs_enabled,
    langsmith_capture_outputs_enabled,
    sanitize_langsmith_text as _shared_sanitize_langsmith_text,
    sanitize_langsmith_value as _shared_sanitize_langsmith_value,
)
from app.shared.infra.settings.support import (
    normalize_llm_provider_name,
    resolve_runtime_llm_provider,
    split_provider_model_name,
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


def _model_provider_and_name(
    model: str,
    *,
    runtime_provider: str | None = None,
) -> tuple[str, str]:
    normalized = str(model or "").strip()
    if not normalized:
        return "unknown", ""
    provider, model_name = split_provider_model_name(normalized)
    if provider:
        return provider, model_name or normalized
    resolved_provider = normalize_llm_provider_name(
        runtime_provider or resolve_runtime_llm_provider()
    ) or "unknown"
    if resolved_provider == "openai_compatible":
        resolved_provider = "openai"
    return resolved_provider, normalized


def _resolved_trace_model(
    call_kwargs: Mapping[str, Any],
    fallback_model: str,
    *,
    runtime_provider: str | None = None,
) -> tuple[str, str, str]:
    raw_model = str(call_kwargs.get("model") or fallback_model).strip() or fallback_model
    provider, model_name = _model_provider_and_name(
        raw_model,
        runtime_provider=runtime_provider,
    )
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
    extra_outputs: Mapping[str, Any] | None = None,
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
    if extra_outputs:
        outputs.update(
            {
                str(key): _sanitize_langsmith_value(
                    value,
                    capture_text=capture_outputs,
                    field_name=str(key),
                )
                for key, value in extra_outputs.items()
                if value not in (None, "", [], {})
            }
        )
    return outputs


def _langsmith_invocation_params(call_kwargs: Mapping[str, Any]) -> dict[str, Any]:
    capture_inputs = langsmith_capture_inputs_enabled()
    invocation_params: dict[str, Any] = {}
    for key in (
        "temperature",
        "max_tokens",
        "max_output_tokens",
        "top_p",
        "presence_penalty",
        "frequency_penalty",
        "stop",
        "stream",
        "tool_choice",
        "response_format",
        "reasoning_effort",
        "reasoning",
    ):
        value = call_kwargs.get(key)
        if value in (None, "", [], {}):
            continue
        if key in {"max_tokens", "max_output_tokens"}:
            invocation_params[key] = int(value)
            continue
        if key in {"temperature", "top_p", "presence_penalty", "frequency_penalty"}:
            invocation_params[key] = float(value)
            continue
        if key == "reasoning_effort":
            invocation_params[key] = str(value)
            continue
        if key == "reasoning" and isinstance(value, Mapping):
            sanitized_reasoning = _sanitize_langsmith_value(
                value,
                capture_text=capture_inputs,
                field_name=key,
            )
            effort = value.get("effort")
            if effort not in (None, ""):
                sanitized_reasoning["effort"] = str(effort)
            invocation_params[key] = sanitized_reasoning
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


def _langsmith_api_mode_from_mode(mode: str) -> str:
    mode_text = str(mode or "").strip()
    if mode_text.endswith("_chat_completions") or mode_text == "chat_completions":
        return "chat_completions"
    if mode_text.endswith("_responses") or mode_text == "responses":
        return "responses"
    if mode_text in {"structured", "tools", "tools_stream"}:
        return "chat_completions"
    return mode_text


def _langsmith_provider_tool_types(call_kwargs: Mapping[str, Any]) -> list[str]:
    tool_types: list[str] = []
    tools = call_kwargs.get("tools")
    if not isinstance(tools, list):
        return tool_types
    for tool in tools:
        if not isinstance(tool, Mapping):
            continue
        tool_type = str(tool.get("type") or "").strip()
        if not tool_type:
            function = tool.get("function")
            if isinstance(function, Mapping):
                tool_type = str(function.get("name") or "").strip()
        if tool_type and tool_type not in tool_types:
            tool_types.append(tool_type)
    return tool_types


def _record_new_token_event(trace_run: Any | None) -> None:
    if trace_run is None:
        return
    add_event = getattr(trace_run, "add_event", None)
    if callable(add_event):
        try:
            add_event({"name": "new_token"})
        except Exception:
            return


def llm_api_mode_outputs(
    *,
    initial_api_mode: str,
    final_api_mode: str,
    final_route_reason: str | None = None,
    auto_responses_chat_fallback: bool = False,
) -> dict[str, Any]:
    """Return compact output fields that explain the final provider transport."""

    outputs: dict[str, Any] = {
        "llm_initial_api_mode": initial_api_mode,
        "llm_final_api_mode": final_api_mode,
        "llm_api_mode_changed": initial_api_mode != final_api_mode,
        "llm_auto_responses_chat_fallback": auto_responses_chat_fallback,
    }
    if final_route_reason:
        outputs["llm_final_api_mode_route_reason"] = final_route_reason
    return outputs


def _end_langsmith_trace(
    trace_run: Any | None,
    *,
    text: str | None = None,
    result: Any = None,
    tool_calls: list[dict[str, Any]] | None = None,
    extra_outputs: Mapping[str, Any] | None = None,
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
            extra_outputs=extra_outputs,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
    )


def _langsmith_llm_metadata(
    *,
    task_type: object,
    provider: str,
    model_name: str,
    invocation_params: Mapping[str, Any] | None = None,
    attempt: int | None = None,
    mode: str,
    endpoint_role: str | None = None,
    model_selector: str | None = None,
) -> dict[str, Any]:
    task_label = normalize_task_type(task_type)
    metadata: dict[str, Any] = {
        "task_type": task_label,
        "mode": mode,
        "llm_initial_api_mode": _langsmith_api_mode_from_mode(mode),
        "model": model_name,
        "ls_provider": provider,
        "ls_model_name": model_name,
        "ls_model_type": "chat",
    }
    if endpoint_role:
        metadata["llm_endpoint_role"] = endpoint_role
    if model_selector:
        metadata["llm_model_selector"] = model_selector
    if invocation_params:
        metadata["ls_invocation_params"] = dict(invocation_params)
        if "temperature" in invocation_params:
            metadata["ls_temperature"] = invocation_params["temperature"]
        if "max_tokens" in invocation_params:
            metadata["ls_max_tokens"] = invocation_params["max_tokens"]
        if "max_output_tokens" in invocation_params:
            metadata["ls_max_tokens"] = invocation_params["max_output_tokens"]
        if "stop" in invocation_params:
            metadata["ls_stop"] = invocation_params["stop"]
        reasoning_effort = invocation_params.get("reasoning_effort")
        reasoning = invocation_params.get("reasoning")
        if reasoning_effort is None and isinstance(reasoning, Mapping):
            reasoning_effort = reasoning.get("effort")
        if reasoning_effort not in (None, ""):
            metadata["ls_reasoning_effort"] = reasoning_effort
    if attempt is not None:
        metadata["attempt"] = attempt
    return metadata


def _langsmith_trace_kwargs(
    *,
    task_type: object,
    call_model: str,
    provider: str,
    model_name: str,
    mode: str,
    messages: list[ChatMessage],
    call_kwargs: Mapping[str, Any] | None = None,
    attempt: int | None = None,
    endpoint_role: str | None = None,
    model_selector: str | None = None,
    tools: list[dict] | None = None,
    extra_metadata: Mapping[str, Any] | None = None,
    extra_tags: list[str] | None = None,
) -> dict[str, Any]:
    trace_context = get_llm_trace_context()
    invocation_params = _langsmith_invocation_params(call_kwargs or {})
    provider_tool_types = _langsmith_provider_tool_types(call_kwargs or {})
    task_label = normalize_task_type(task_type)
    metadata = {
        **dict(extra_metadata or {}),
        **_langsmith_llm_metadata(
            task_type=task_type,
            provider=provider,
            model_name=model_name,
            invocation_params=invocation_params,
            attempt=attempt,
            mode=mode,
            endpoint_role=endpoint_role,
            model_selector=model_selector,
        ),
    }
    if provider_tool_types:
        metadata["llm_tool_types"] = provider_tool_types
        provider_native_tool_types = [
            tool_type
            for tool_type in provider_tool_types
            if tool_type in {"web_search", "file_search"}
        ]
        if provider_native_tool_types and "llm_provider_native_tool_types" not in metadata:
            metadata["llm_provider_native_tool_types"] = provider_native_tool_types
    return {
        "inputs": _langsmith_inputs(call_model=call_model, messages=messages, tools=tools),
        "course_id": trace_context.course_id,
        "build_session_id": trace_context.build_session_id,
        "workflow": trace_context.workflow,
        "lane": trace_context.lane,
        "node": trace_context.node,
        "extra_metadata": metadata,
        "extra_tags": [f"task:{task_label}", *(extra_tags or [])],
    }

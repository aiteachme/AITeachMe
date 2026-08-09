"""Small adapter for choosing Chat Completions vs Responses API calls."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from app.shared.infra.llm_support.common import CompletionContext
from app.shared.infra.llm_support.model_catalog import (
    ModelAPIModeHint,
    ReasoningEffort,
    classify_known_model_api_mode,
    model_name_candidates,
    reasoning_efforts_for_model,
)
from app.shared.infra.settings.support import normalize_llm_provider_name

from .native_tools import (
    PROVIDER_NATIVE_TOOLS_KWARG,
    has_provider_native_tool_requests,
    provider_native_tool_request_types,
    provider_native_tools_for_responses,
)

ResolvedAPIMode = Literal["chat_completions", "responses"]

_OPENAI_REASONING_MODEL_PATTERN = re.compile(r"^(?:gpt-5(?:$|[.-])|o\d(?:$|[.-]))")
_HTML_GATEWAY_ERROR_MARKERS = (
    "<!doctype html",
    "<html",
    "text/html",
    "reverse proxy",
    "model server configuration",
    "api gateway",
    "sub2api",
)


@dataclass(frozen=True)
class ProviderCall:
    """Resolved provider method plus kwargs for one LiteLLM call."""

    api_mode: ResolvedAPIMode
    kwargs: dict[str, Any]
    auto_chat_fallback_kwargs: dict[str, Any] | None = None
    requested_api_mode: str = "auto"
    route_reason: str = "chat_default"
    provider_native_tool_types: tuple[str, ...] = ()


def provider_call_metadata(provider_call: ProviderCall) -> dict[str, Any]:
    """Return compact metadata describing one API-mode decision."""

    metadata: dict[str, Any] = {
        "llm_requested_api_mode": provider_call.requested_api_mode,
        "llm_initial_api_mode": provider_call.api_mode,
        "llm_api_mode_route_reason": provider_call.route_reason,
    }
    if provider_call.provider_native_tool_types:
        metadata["llm_provider_native_tool_types"] = list(provider_call.provider_native_tool_types)
    if provider_call.auto_chat_fallback_kwargs is not None:
        metadata["llm_auto_responses_chat_fallback_available"] = True
    return metadata


def resolve_provider_call(
    *,
    context: CompletionContext,
    call_kwargs: Mapping[str, Any],
) -> ProviderCall:
    """Return a provider call using stable settings and conservative auto mode."""

    requested_mode, clean_kwargs = _pop_adapter_kwargs(context, call_kwargs)
    supports_auto_responses = _supports_auto_responses_call(context, clean_kwargs)
    native_tool_types = tuple(provider_native_tool_request_types(clean_kwargs.get(PROVIDER_NATIVE_TOOLS_KWARG)))
    has_allowed_native_tools = _has_allowed_provider_native_tools(context, clean_kwargs)
    model_for_routing = clean_kwargs.get("model") or context.model
    model_api_mode = classify_model_api_mode(
        model_for_routing,
        responses_api_models=context.settings.llm.responses_api_models,
    )
    has_basic_message_shape = _has_basic_responses_message_shape(clean_kwargs.get("messages"))
    has_chat_only_output_shape = _has_chat_only_output_shape(clean_kwargs)
    should_use_responses = (
        requested_mode == "responses"
        or (
            requested_mode == "auto"
            and supports_auto_responses
            and model_api_mode == "responses"
            and has_basic_message_shape
            and not has_chat_only_output_shape
        )
    )
    if should_use_responses:
        if requested_mode == "responses":
            route_reason = "forced_responses"
        elif has_allowed_native_tools:
            route_reason = "auto_provider_native_tools"
        elif model_api_mode == "responses":
            route_reason = "auto_model_catalog_responses"
        return ProviderCall(
            api_mode="responses",
            kwargs=to_responses_kwargs(
                context=context,
                call_kwargs=clean_kwargs,
            ),
            auto_chat_fallback_kwargs=(
                to_chat_kwargs(context=context, call_kwargs=clean_kwargs)
                if requested_mode == "auto"
                else None
            ),
            requested_api_mode=requested_mode,
            route_reason=route_reason,
            provider_native_tool_types=native_tool_types,
        )
    if requested_mode == "chat_completions":
        route_reason = "forced_chat_completions"
    elif has_chat_only_output_shape:
        route_reason = "chat_only_output_shape"
    elif not has_basic_message_shape:
        route_reason = "chat_only_message_shape"
    elif not supports_auto_responses:
        route_reason = "auto_no_responses_support"
    elif native_tool_types and not has_allowed_native_tools:
        route_reason = "auto_native_tools_not_allowed"
    else:
        route_reason = "auto_plain_chat"
    return ProviderCall(
        api_mode="chat_completions",
        kwargs=to_chat_kwargs(context=context, call_kwargs=clean_kwargs),
        requested_api_mode=requested_mode,
        route_reason=route_reason,
        provider_native_tool_types=native_tool_types,
    )


def chat_fallback_for_auto_responses(
    provider_call: ProviderCall,
    error: Exception,
) -> ProviderCall | None:
    """Return a one-shot Chat fallback when auto Responses is unsupported."""

    if provider_call.api_mode != "responses" or provider_call.auto_chat_fallback_kwargs is None:
        return None
    if not _is_responses_unsupported_error(error):
        return None
    return ProviderCall(
        api_mode="chat_completions",
        kwargs=dict(provider_call.auto_chat_fallback_kwargs),
        requested_api_mode=provider_call.requested_api_mode,
        route_reason="auto_responses_unsupported_chat_fallback",
        provider_native_tool_types=provider_call.provider_native_tool_types,
    )


def to_chat_kwargs(
    *,
    context: CompletionContext,
    call_kwargs: Mapping[str, Any],
) -> dict[str, Any]:
    """Build Chat Completions kwargs without leaking adapter-only settings."""

    chat_kwargs = dict(call_kwargs)
    chat_kwargs.pop(PROVIDER_NATIVE_TOOLS_KWARG, None)
    effort = _resolve_reasoning_effort(context, chat_kwargs)
    if effort and _supports_chat_reasoning_effort(context, chat_kwargs):
        chat_kwargs["reasoning_effort"] = effort
    if "max_tokens" not in chat_kwargs and "max_output_tokens" in chat_kwargs:
        chat_kwargs["max_tokens"] = chat_kwargs.pop("max_output_tokens")
    else:
        chat_kwargs.pop("max_output_tokens", None)
    return chat_kwargs


def to_responses_kwargs(
    *,
    context: CompletionContext,
    call_kwargs: Mapping[str, Any],
) -> dict[str, Any]:
    """Build Responses API kwargs from the project's Chat-shaped kwargs."""

    responses_kwargs = dict(call_kwargs)
    native_tools = provider_native_tools_for_responses(
        responses_kwargs.pop(PROVIDER_NATIVE_TOOLS_KWARG, None),
        allow_auto=_supports_auto_responses_call(context, responses_kwargs),
        allow_force=True,
    )
    messages = responses_kwargs.pop("messages", [])
    instructions, response_input = _responses_input_from_messages(messages)
    existing_instructions = responses_kwargs.pop("instructions", None)
    if existing_instructions and instructions:
        instructions = f"{existing_instructions}\n\n{instructions}"
    elif existing_instructions:
        instructions = str(existing_instructions)
    if instructions:
        responses_kwargs["instructions"] = instructions
    responses_kwargs["input"] = response_input
    responses_kwargs.pop("response_format", None)

    if "max_output_tokens" not in responses_kwargs:
        max_tokens = responses_kwargs.pop("max_tokens", None)
        if max_tokens is None:
            max_tokens = responses_kwargs.pop("max_completion_tokens", None)
        if max_tokens is not None:
            responses_kwargs["max_output_tokens"] = max_tokens
    else:
        responses_kwargs.pop("max_tokens", None)
        responses_kwargs.pop("max_completion_tokens", None)

    effort = _resolve_reasoning_effort(context, responses_kwargs)
    if effort:
        reasoning = responses_kwargs.get("reasoning")
        if isinstance(reasoning, Mapping):
            responses_kwargs["reasoning"] = {**dict(reasoning), "effort": effort}
        else:
            responses_kwargs["reasoning"] = {"effort": effort}
    if native_tools:
        existing_tools = responses_kwargs.get("tools")
        if isinstance(existing_tools, list):
            responses_kwargs["tools"] = [*existing_tools, *native_tools]
        else:
            responses_kwargs["tools"] = native_tools
    return responses_kwargs


def _resolve_reasoning_effort(
    context: CompletionContext,
    call_kwargs: dict[str, Any],
) -> ReasoningEffort | str | None:
    """Resolve an explicit call override or the configured effort for this model tier."""

    explicit_effort = call_kwargs.pop("reasoning_effort", None)
    if explicit_effort:
        return str(explicit_effort)

    configured_effort = context.settings.llm.reasoning_efforts.for_selector(
        context.model_selector,
    )
    if configured_effort is None:
        return None

    supported_efforts = reasoning_efforts_for_model(
        call_kwargs.get("model") or context.model,
    )
    if supported_efforts is not None and configured_effort not in supported_efforts:
        return None
    return configured_effort


def extract_response_text(response: Any) -> str:
    """Extract visible assistant text from an OpenAI Responses-shaped object."""

    if isinstance(response, str):
        return response

    output_text = _get(response, "output_text")
    if output_text:
        return str(output_text)

    parts: list[str] = []
    for item in _as_list(_get(response, "output")):
        content = _get(item, "content")
        if isinstance(content, str):
            parts.append(content)
            continue
        for block in _as_list(content):
            text = _get(block, "text")
            if text:
                parts.append(str(text))
    return "".join(parts)


def response_output_tool_events(response: Any) -> list[dict[str, str]]:
    """Return compact provider-native tool events exposed by a Responses object."""

    events: list[dict[str, str]] = []
    for item in _as_list(_get(response, "output")):
        event = _response_output_tool_event(item)
        if event is not None and event not in events:
            events.append(event)
    return events[:20]


def response_stream_delta(chunk: Any) -> str:
    """Return visible text delta from one Responses streaming event."""

    if isinstance(chunk, str):
        return chunk

    chat_delta = _chat_completion_delta_text(chunk)
    if chat_delta:
        return chat_delta

    event_type = _event_type_text(chunk)
    delta = _get(chunk, "delta")
    if isinstance(delta, str) and ("delta" in event_type or not event_type):
        return delta
    delta_text = _content_to_text(delta)
    if delta_text and "delta" in event_type:
        return delta_text

    text = _get(chunk, "text")
    if isinstance(text, str) and "delta" in event_type:
        return text
    return ""


def response_stream_final_text(chunk: Any) -> str:
    """Return final visible text from a terminal Responses event when no deltas arrived."""

    event_type = _event_type_text(chunk)
    if event_type not in {"response.completed", "response.output_text.done"}:
        return ""
    response = _get(chunk, "response")
    if response is not None:
        text = extract_response_text(response)
        if text:
            return text
    if event_type == "response.output_text.done":
        return _content_to_text(_get(chunk, "text"))
    return extract_response_text(chunk)


def _response_output_tool_event(item: Any) -> dict[str, str] | None:
    item_type = str(_get(item, "type") or "").strip()
    if not _is_tool_output_type(item_type):
        return None
    event: dict[str, str] = {"type": item_type}
    for key in ("id", "call_id", "status", "name"):
        value = _get(item, key)
        if value not in (None, ""):
            event[key] = str(value)
    action = _get(item, "action")
    if isinstance(action, Mapping):
        action_type = _get(action, "type")
        if action_type not in (None, ""):
            event["action_type"] = str(action_type)
    return event


def _is_tool_output_type(item_type: str) -> bool:
    normalized = item_type.lower()
    return any(
        marker in normalized
        for marker in ("web_search", "file_search", "function_call", "tool_call")
    )


def _pop_adapter_kwargs(
    context: CompletionContext,
    call_kwargs: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    clean_kwargs = dict(call_kwargs)
    requested = clean_kwargs.pop("api_mode", None)
    if requested is None:
        if context.endpoint_role == "fallback":
            requested = "chat_completions"
        else:
            requested = context.settings.llm.api_mode
    requested_text = str(requested or "auto").strip().lower()
    if requested_text not in {"auto", "chat_completions", "responses"}:
        requested_text = "auto"
    return requested_text, clean_kwargs


def classify_model_api_mode(
    model: Any,
    *,
    responses_api_models: tuple[str, ...] | None = None,
) -> ModelAPIModeHint | None:
    """Return an exact model-level API mode hint for auto routing."""

    if responses_api_models is None:
        return classify_known_model_api_mode(model)
    return classify_known_model_api_mode(model, responses_api_models)


def _is_official_openai_call(
    context: CompletionContext,
    call_kwargs: Mapping[str, Any],
) -> bool:
    provider = normalize_llm_provider_name(context.provider)
    api_base = str(call_kwargs.get("api_base") or context.base_url or "").strip()
    if api_base:
        return "api.openai.com" in api_base.lower()
    if provider == "openai":
        return True
    return (
        provider in {"openai_compatible", None}
        and call_kwargs.get("custom_llm_provider") == "openai"
    )


def _supports_auto_responses_call(
    context: CompletionContext,
    call_kwargs: Mapping[str, Any],
) -> bool:
    if _is_official_openai_call(context, call_kwargs):
        return True

    provider = normalize_llm_provider_name(context.provider)
    if provider != "openai_compatible":
        return False
    return call_kwargs.get("custom_llm_provider") == "openai"


def _supports_chat_reasoning_effort(
    context: CompletionContext,
    call_kwargs: Mapping[str, Any],
) -> bool:
    """Return whether this OpenAI-protocol Chat call may accept reasoning_effort."""

    if not _supports_auto_responses_call(context, call_kwargs):
        return False

    model = call_kwargs.get("model") or context.model
    supported_efforts = reasoning_efforts_for_model(model)
    if supported_efforts is not None:
        return bool(supported_efforts)

    # Official OpenAI calls remain conservative for unknown aliases. Compatible
    # gateways may expose custom reasoning-model names that the local catalog
    # cannot know, so preserve an explicitly configured effort for those calls.
    if _is_official_openai_call(context, call_kwargs):
        return _is_openai_reasoning_model(model)
    return True


def _has_allowed_provider_native_tools(
    context: CompletionContext,
    call_kwargs: Mapping[str, Any],
) -> bool:
    raw_tools = call_kwargs.get(PROVIDER_NATIVE_TOOLS_KWARG)
    if not has_provider_native_tool_requests(raw_tools):
        return False
    return bool(
        provider_native_tools_for_responses(
            raw_tools,
            allow_auto=_supports_auto_responses_call(context, call_kwargs),
            allow_force=True,
        )
    )


def _canonical_model_name(model: Any) -> str:
    candidates = model_name_candidates(model)
    value = candidates[-1] if candidates else ""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _is_openai_reasoning_model(model: Any) -> bool:
    value = _canonical_model_name(model)
    return bool(_OPENAI_REASONING_MODEL_PATTERN.match(value))


def _has_basic_responses_message_shape(messages: Any) -> bool:
    if not isinstance(messages, list):
        return True
    for message in messages:
        if not isinstance(message, Mapping):
            continue
        role = str(message.get("role") or "").strip().lower()
        if role == "tool" or message.get("tool_calls") or message.get("function_call"):
            return False
    return True


def _has_chat_only_output_shape(call_kwargs: Mapping[str, Any]) -> bool:
    return call_kwargs.get("response_format") not in (None, "", {}, [])


def _is_responses_unsupported_error(error: Exception) -> bool:
    message = str(error or "").lower()
    if not message:
        return False
    if any(marker in message for marker in _HTML_GATEWAY_ERROR_MARKERS):
        return True
    unsupported_markers = (
        "404",
        "not found",
        "not support",
        "does not support",
        "unsupported",
        "unknown endpoint",
        "invalid endpoint",
        "no such endpoint",
        "unknown parameter",
        "unrecognized request argument",
        "unexpected keyword",
        "unexpected parameter",
        "extra_forbidden",
    )
    responses_markers = (
        "/responses",
        "responses",
        "max_output_tokens",
        "instructions",
        "reasoning",
        "input",
        "tools",
        "web_search",
        "file_search",
    )
    return any(marker in message for marker in unsupported_markers) and any(
        marker in message for marker in responses_markers
    )


def _responses_input_from_messages(messages: Any) -> tuple[str, list[dict[str, Any]]]:
    instructions: list[str] = []
    response_input: list[dict[str, Any]] = []
    for message in _as_list(messages):
        if not isinstance(message, Mapping):
            continue
        role = str(message.get("role") or "user").strip().lower()
        content = message.get("content")
        if role in {"system", "developer"}:
            text = _content_to_text(content)
            if text:
                instructions.append(text)
            continue
        item: dict[str, Any] = {
            "role": "assistant" if role == "assistant" else "user",
            "content": content or "",
        }
        name = message.get("name")
        if name:
            item["name"] = name
        response_input.append(item)
    return "\n\n".join(instructions), response_input


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, Mapping):
        text = _get(content, "text")
        if text:
            return str(text)
        nested = _get(content, "content")
        if nested is not None and nested is not content:
            return _content_to_text(nested)
        return ""
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = _get(item, "text")
            if text:
                parts.append(str(text))
        return "\n".join(parts)
    return "" if content is None else str(content)


def _event_type_text(chunk: Any) -> str:
    raw_type = _get(chunk, "type")
    value = getattr(raw_type, "value", raw_type)
    return str(value or "").strip().lower()


def _chat_completion_delta_text(chunk: Any) -> str:
    for choice in _as_list(_get(chunk, "choices")):
        delta = _get(choice, "delta")
        text = _content_to_text(_get(delta, "content"))
        if text:
            return text
        message = _get(choice, "message")
        text = _content_to_text(_get(message, "content"))
        if text:
            return text
        text = _content_to_text(_get(choice, "text"))
        if text:
            return text
    return ""


def _get(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, None)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]

"""Small adapter for choosing Chat Completions vs Responses API calls."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from app.shared.infra.llm_support.common import CompletionContext
from app.shared.infra.settings.support import normalize_llm_provider_name

from .litellm_loader import load_litellm

ResolvedAPIMode = Literal["chat_completions", "responses"]

_OPENAI_REASONING_MODEL_PATTERN = re.compile(r"^(?:gpt-5(?:$|[.-])|o\d(?:$|[.-]))")
_RESPONSES_ROUTE_MARKERS = frozenset({"responses"})
_REASONING_MODEL_NAME_MARKERS = (
    "reasoner",
    "reasoning",
    "thinking",
    "deepseek-r1",
    "qwen3",
    "qwq",
    "gpt-oss",
    "glm-5",
    "grok-4",
)


@dataclass(frozen=True)
class ProviderCall:
    """Resolved provider method plus kwargs for one LiteLLM call."""

    api_mode: ResolvedAPIMode
    kwargs: dict[str, Any]
    auto_chat_fallback_kwargs: dict[str, Any] | None = None


def resolve_provider_call(
    *,
    context: CompletionContext,
    call_kwargs: Mapping[str, Any],
) -> ProviderCall:
    """Return a provider call using stable settings and conservative auto mode."""

    requested_mode, clean_kwargs = _pop_adapter_kwargs(context, call_kwargs)
    should_use_responses = (
        requested_mode == "responses"
        or (
            requested_mode == "auto"
            and _supports_auto_responses_call(context, clean_kwargs)
            and _should_auto_route_model_to_responses(context, clean_kwargs)
            and _has_basic_responses_message_shape(clean_kwargs.get("messages"))
            and not _has_chat_only_output_shape(clean_kwargs)
        )
    )
    if should_use_responses:
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
        )
    return ProviderCall(
        api_mode="chat_completions",
        kwargs=to_chat_kwargs(context=context, call_kwargs=clean_kwargs),
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
    )


def to_chat_kwargs(
    *,
    context: CompletionContext,
    call_kwargs: Mapping[str, Any],
) -> dict[str, Any]:
    """Build Chat Completions kwargs without leaking adapter-only settings."""

    chat_kwargs = dict(call_kwargs)
    effort = chat_kwargs.pop("reasoning_effort", None) or context.settings.llm.reasoning_effort
    if (
        effort
        and _is_official_openai_call(context, chat_kwargs)
        and _is_openai_reasoning_model(chat_kwargs.get("model"))
    ):
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

    effort = responses_kwargs.pop("reasoning_effort", None) or context.settings.llm.reasoning_effort
    if effort:
        reasoning = responses_kwargs.get("reasoning")
        if isinstance(reasoning, Mapping):
            responses_kwargs["reasoning"] = {**dict(reasoning), "effort": effort}
        else:
            responses_kwargs["reasoning"] = {"effort": effort}
    return responses_kwargs


def extract_response_text(response: Any) -> str:
    """Extract visible assistant text from an OpenAI Responses-shaped object."""

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


def response_stream_delta(chunk: Any) -> str:
    """Return visible text delta from one Responses streaming event."""

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


def _pop_adapter_kwargs(
    context: CompletionContext,
    call_kwargs: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    clean_kwargs = dict(call_kwargs)
    requested = clean_kwargs.pop("api_mode", None) or context.settings.llm.api_mode
    requested_text = str(requested or "auto").strip().lower()
    if requested_text not in {"auto", "chat_completions", "responses"}:
        requested_text = "auto"
    return requested_text, clean_kwargs


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


def _should_auto_route_model_to_responses(
    context: CompletionContext,
    call_kwargs: Mapping[str, Any],
) -> bool:
    model = call_kwargs.get("model")
    if _has_explicit_responses_route(model):
        return True
    if _litellm_supports_reasoning_model(model, call_kwargs.get("custom_llm_provider")):
        return True
    return _has_reasoning_model_name(model)


def _model_name_candidates(model: Any) -> tuple[str, ...]:
    raw = str(model or "").strip()
    if not raw:
        return ()
    parts = [part for part in raw.replace("\\", "/").split("/") if part]
    candidates: list[str] = [raw]
    if parts:
        candidates.append(parts[-1])
    if len(parts) >= 2 and parts[-2].lower() in _RESPONSES_ROUTE_MARKERS:
        candidates.append(parts[-1])
    return tuple(dict.fromkeys(candidates))


def _canonical_model_name(model: Any) -> str:
    candidates = _model_name_candidates(model)
    value = candidates[-1] if candidates else ""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _has_explicit_responses_route(model: Any) -> bool:
    parts = [
        part.lower()
        for part in str(model or "").strip().replace("\\", "/").split("/")
        if part
    ]
    return any(part in _RESPONSES_ROUTE_MARKERS for part in parts[:-1])


def _is_openai_reasoning_model(model: Any) -> bool:
    value = _canonical_model_name(model)
    return bool(_OPENAI_REASONING_MODEL_PATTERN.match(value))


def _litellm_supports_reasoning_model(model: Any, custom_llm_provider: Any) -> bool:
    candidates = _model_name_candidates(model)
    if not candidates:
        return False
    provider_text = str(custom_llm_provider or "").strip() or None
    provider_candidates = tuple(dict.fromkeys((provider_text, None)))
    try:
        litellm = load_litellm()
    except Exception:
        return False
    supports_reasoning = getattr(litellm, "supports_reasoning", None)
    if not callable(supports_reasoning):
        return False
    for candidate in candidates:
        for provider in provider_candidates:
            try:
                if supports_reasoning(model=candidate, custom_llm_provider=provider):
                    return True
            except Exception:
                continue
    return False


def _has_reasoning_model_name(model: Any) -> bool:
    value = _canonical_model_name(model)
    if _OPENAI_REASONING_MODEL_PATTERN.match(value):
        return True
    return any(marker in value for marker in _REASONING_MODEL_NAME_MARKERS)


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

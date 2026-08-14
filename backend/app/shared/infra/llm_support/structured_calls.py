"""Structured completion helper built on top of LiteLLM."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from copy import deepcopy
from functools import lru_cache
from importlib import import_module
from typing import Any
from typing import TypeVar

from app.schemas.llm import ChatMessage
from app.shared.infra.exceptions import LLMTimeoutError
from app.shared.infra.observability.trace import langsmith_trace

from .litellm_loader import load_litellm
from .common import (
    build_completion_contexts,
    completion_context_groups,
    effective_call_timeout_s,
    effective_endpoint_group_max_retries,
    extract_usage,
    get_llm_concurrency_limiter,
    logger,
    log_attempt_cancelled,
    log_attempt_failed,
    log_attempt_started,
    log_attempt_timeout,
    merge_usage,
    prepare_completion_attempt,
    pop_overall_timeout_s,
    raise_last_error,
    context_request_timeout_s,
    should_advance_to_fallback,
    should_try_endpoint_fallback,
    sleep_before_retry,
    trace_log_fields,
    track_call,
    wait_for_overall_timeout,
)
from .observability import _end_langsmith_trace, _langsmith_trace_kwargs, llm_api_mode_outputs
from .native_tools import without_provider_native_tools
from .responses_adapter import (
    ProviderCall,
    chat_fallback_for_auto_responses,
    extract_response_text,
    provider_call_metadata,
    resolve_provider_call,
    response_output_tool_events,
)
from .structured import (
    JSON_OBJECT_RESPONSE_FORMAT,
    _build_structured_fallback_messages,
    _parse_structured_response_text,
    _serialize_structured_result,
)

T = TypeVar("T")


@lru_cache(maxsize=1)
def _load_instructor():
    try:
        return import_module("instructor")
    except ModuleNotFoundError:  # pragma: no cover - optional dependency in local dev
        return None


@lru_cache(maxsize=512)
def _supports_json_object_response_format(model: str, provider: str | None) -> bool:
    """Return whether LiteLLM reports JSON object response_format support."""

    if not model:
        return False
    litellm = load_litellm()
    try:
        supported_params = litellm.get_supported_openai_params(
            model=model,
            custom_llm_provider=provider or None,
        )
    except Exception as exc:  # pragma: no cover - provider table is external to our code
        logger.debug(
            "llm_structured_response_format_support_check_failed",
            model=model,
            provider=provider,
            error=str(exc),
        )
        return False
    return "response_format" in (supported_params or [])


def _call_provider(prepared_call_kwargs: Mapping[str, Any], fallback_provider: str) -> str:
    provider = str(
        prepared_call_kwargs.get("custom_llm_provider")
        or fallback_provider
        or ""
    ).strip()
    return provider or "unknown"


def _should_use_json_object_response_format(
    *,
    call_kwargs: Mapping[str, Any],
    call_model: str,
    provider: str,
) -> bool:
    configured_format = call_kwargs.get("response_format")
    if configured_format not in (None, "", {}, []):
        return (
            isinstance(configured_format, Mapping)
            and configured_format.get("type") == JSON_OBJECT_RESPONSE_FORMAT["type"]
        )
    return _supports_json_object_response_format(call_model, provider)


def _with_json_object_response_format(call_kwargs: dict[str, Any]) -> dict[str, Any]:
    if call_kwargs.get("response_format") in (None, "", {}, []):
        call_kwargs["response_format"] = deepcopy(JSON_OBJECT_RESPONSE_FORMAT)
    return call_kwargs


def _is_response_format_unsupported_error(exc: Exception) -> bool:
    message = str(exc).lower()
    if "response_format" not in message:
        return False
    return any(
        marker in message
        for marker in (
            "unsupported",
            "not support",
            "does not support",
            "unknown",
            "unrecognized",
            "invalid",
            "extra_forbidden",
        )
    )


def _object_get(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, None)


def _completion_response_text(response: Any) -> str:
    choices = _object_get(response, "choices")
    if not choices:
        return ""
    choice = choices[0]
    message = _object_get(choice, "message")
    if message is None:
        return ""

    tool_calls = _object_get(message, "tool_calls")
    if tool_calls:
        function = _object_get(tool_calls[0], "function")
        arguments = _object_get(function, "arguments")
        if arguments:
            return str(arguments)

    function_call = _object_get(message, "function_call")
    if function_call is not None:
        arguments = _object_get(function_call, "arguments")
        if arguments:
            return str(arguments)

    content = _object_get(message, "content")
    return str(content or "")


def _structured_failure_feedback(exc: Exception) -> tuple[str, str]:
    failed_attempts = list(getattr(exc, "failed_attempts", None) or [])
    for failed_attempt in reversed(failed_attempts):
        reason = str(getattr(failed_attempt, "exception", None) or "").strip()
        raw_text = _completion_response_text(getattr(failed_attempt, "completion", None))
        if reason or raw_text:
            return reason, raw_text

    raw_text = _completion_response_text(getattr(exc, "last_completion", None))
    return str(exc).strip(), raw_text


def _build_structured_repair_call_kwargs(
    *,
    call_kwargs: Mapping[str, Any],
    response_model: type[T],
    messages: list[ChatMessage],
    use_json_response_format: bool,
    failure_reason: str | None = None,
    invalid_response: str | None = None,
) -> dict[str, Any]:
    repair_kwargs = dict(call_kwargs)
    repair_kwargs["messages"] = _build_structured_fallback_messages(
        response_model,
        messages,
        failure_reason=failure_reason,
        invalid_response=invalid_response,
    )
    if use_json_response_format:
        _with_json_object_response_format(repair_kwargs)
    else:
        repair_kwargs.pop("response_format", None)
    return repair_kwargs


def _structured_mode_label(*, use_instructor: bool, use_json_response_format: bool) -> str:
    if not use_instructor:
        return "json_prompt"
    return "instructor_json" if use_json_response_format else "instructor_tools"


def _provider_response_text(response: Any, provider_call: ProviderCall) -> str:
    if provider_call.api_mode == "responses":
        return extract_response_text(response)
    return _completion_response_text(response)


async def _execute_provider_call(
    *,
    litellm: Any,
    context: Any,
    provider_call: ProviderCall,
) -> Any:
    provider_coro = (
        litellm.aresponses(**provider_call.kwargs)
        if provider_call.api_mode == "responses"
        else litellm.acompletion(**provider_call.kwargs)
    )
    return await asyncio.wait_for(
        provider_coro,
        timeout=context_request_timeout_s(context, provider_call.kwargs),
    )


async def _execute_provider_call_with_auto_fallback(
    *,
    litellm: Any,
    context: Any,
    provider_call: ProviderCall,
    attempt: int,
    model: str,
    route_reason: str,
) -> tuple[Any, ProviderCall, bool]:
    try:
        return (
            await _execute_provider_call(
                litellm=litellm,
                context=context,
                provider_call=provider_call,
            ),
            provider_call,
            False,
        )
    except Exception as provider_exc:
        fallback_call = chat_fallback_for_auto_responses(provider_call, provider_exc)
        if fallback_call is None:
            raise
        logger.warning(
            "llm_structured_auto_responses_fallback_to_chat",
            attempt=attempt,
            model=model,
            task_type=context.task_type,
            endpoint_role=context.endpoint_role,
            route_reason=route_reason,
            error=str(provider_exc),
        )
        return (
            await _execute_provider_call(
                litellm=litellm,
                context=context,
                provider_call=fallback_call,
            ),
            fallback_call,
            True,
        )


def _structured_json_prompt_kwargs(
    *,
    call_kwargs: Mapping[str, Any],
    response_model: type[T],
    messages: list[ChatMessage],
    failure_reason: str | None = None,
    invalid_response: str | None = None,
    force_api_mode: str | None = None,
) -> dict[str, Any]:
    prompt_kwargs = dict(call_kwargs)
    prompt_kwargs["messages"] = _build_structured_fallback_messages(
        response_model,
        messages,
        failure_reason=failure_reason,
        invalid_response=invalid_response,
    )
    prompt_kwargs.pop("response_format", None)
    if force_api_mode:
        prompt_kwargs["api_mode"] = force_api_mode
    return prompt_kwargs


async def acompletion_structured(
    response_model: type[T],
    messages: list[ChatMessage],
    *,
    task_type: object | None = None,
    model: str | None = None,
    extra_metadata: Mapping[str, Any] | None = None,
    **kwargs,
) -> T:
    """Async structured completion."""

    overall_timeout_s = pop_overall_timeout_s(kwargs)
    return await wait_for_overall_timeout(
        _acompletion_structured_impl(
            response_model,
            messages,
            task_type=task_type,
            model=model,
            extra_metadata=extra_metadata,
            kwargs=kwargs,
        ),
        overall_timeout_s,
    )


async def _acompletion_structured_impl(
    response_model: type[T],
    messages: list[ChatMessage],
    *,
    task_type: object | None,
    model: str | None,
    extra_metadata: Mapping[str, Any] | None,
    kwargs: dict[str, Any],
) -> T:
    litellm = load_litellm()
    instructor = _load_instructor()
    contexts = build_completion_contexts(
        task_type=task_type,
        model=model,
    )
    primary_context = contexts[0]
    use_instructor = instructor is not None
    last_error: Exception | None = None
    call_started_at = time.monotonic()
    tracked_model = primary_context.model
    attempt_number = 0
    has_fallback_endpoints = any(context.endpoint_role == "fallback" for context in contexts)

    if not use_instructor:
        logger.warning(
            "llm_structured_instructor_unavailable",
            response_model=response_model.__name__,
            model=tracked_model,
            task_type=primary_context.task_type,
            fallback_mode="json_prompt",
            **trace_log_fields(),
        )

    async with get_llm_concurrency_limiter().slot() as lease:
        for group_index, context_group in enumerate(completion_context_groups(contexts)):
            if (
                group_index > 0
                and context_group[0].endpoint_role == "fallback"
                and not should_try_endpoint_fallback(last_error)
            ):
                logger.warning(
                    "llm_structured_endpoint_fallback_skipped_non_endpoint_error",
                    task_type=primary_context.task_type,
                    model=tracked_model,
                    response_model=response_model.__name__,
                    error=str(last_error),
                    error_type=last_error.__class__.__name__ if last_error is not None else "",
                )
                break
            group_max_retries = effective_endpoint_group_max_retries(context_group[0], kwargs)
            for retry_round in range(1, group_max_retries + 1):
                for context in context_group:
                    attempt_number += 1
                    prepared = prepare_completion_attempt(
                        context=context,
                        messages=messages,
                        extra_kwargs=without_provider_native_tools(kwargs),
                        attempt=attempt_number,
                    )
                    tracked_model = prepared.tracked_model
                    base_provider_call = resolve_provider_call(
                        context=context,
                        call_kwargs=prepared.call_kwargs,
                    )
                    if base_provider_call.api_mode == "chat_completions":
                        prepared.call_kwargs.clear()
                        prepared.call_kwargs.update(base_provider_call.kwargs)
                        provider = _call_provider(prepared.call_kwargs, prepared.provider)
                        use_json_response_format = _should_use_json_object_response_format(
                            call_kwargs=prepared.call_kwargs,
                            call_model=prepared.call_model,
                            provider=provider,
                        )
                        if use_json_response_format:
                            _with_json_object_response_format(prepared.call_kwargs)
                        instructor_mode = None
                        client = None
                        if use_instructor:
                            instructor_mode = instructor.Mode.JSON if use_json_response_format else instructor.Mode.TOOLS
                            client = instructor.from_litellm(litellm.acompletion, mode=instructor_mode)
                        mode_label = _structured_mode_label(
                            use_instructor=use_instructor,
                            use_json_response_format=use_json_response_format,
                        )
                    else:
                        use_json_response_format = False
                        instructor_mode = None
                        client = None
                        mode_label = "json_prompt_responses"
                    log_attempt_started(
                        "llm_structured_started",
                        attempt=prepared,
                        context=context,
                        extra={
                            "response_model": response_model.__name__,
                            "mode": mode_label,
                        },
                    )
                    try:
                        prompt_t = 0
                        completion_t = 0
                        total_t = 0
                        assistant_text = ""
                        trace_messages = messages
                        if base_provider_call.api_mode == "responses":
                            response_call_kwargs = _structured_json_prompt_kwargs(
                                call_kwargs=prepared.call_kwargs,
                                response_model=response_model,
                                messages=messages,
                            )
                            provider_call = resolve_provider_call(
                                context=context,
                                call_kwargs=response_call_kwargs,
                            )
                            initial_api_mode = provider_call.api_mode
                            route_reason = provider_call.route_reason
                            auto_responses_chat_fallback = False
                            trace_messages = response_call_kwargs["messages"]
                            trace_metadata = {
                                **dict(extra_metadata or {}),
                                **provider_call_metadata(provider_call),
                            }
                            with langsmith_trace(
                                name="LLM：结构化生成",
                                run_type="llm",
                                **_langsmith_trace_kwargs(
                                    task_type=context.task_type,
                                    call_model=prepared.call_model,
                                    provider=prepared.provider,
                                    model_name=tracked_model,
                                    mode=f"structured_{provider_call.api_mode}",
                                    messages=trace_messages,
                                    call_kwargs=provider_call.kwargs,
                                    attempt=prepared.attempt,
                                    endpoint_role=context.endpoint_role,
                                    model_selector=context.model_selector,
                                    extra_metadata=trace_metadata,
                                ),
                            ) as trace_run:
                                usage = (0, 0, 0)
                                response, provider_call, did_fallback = await _execute_provider_call_with_auto_fallback(
                                    litellm=litellm,
                                    context=context,
                                    provider_call=provider_call,
                                    attempt=prepared.attempt,
                                    model=tracked_model,
                                    route_reason=route_reason,
                                )
                                auto_responses_chat_fallback = auto_responses_chat_fallback or did_fallback
                                usage = merge_usage(usage, extract_usage(response))
                                raw_text = _provider_response_text(response, provider_call)
                                if not raw_text.strip():
                                    raise ValueError("empty_llm_response")
                                assistant_text = raw_text
                                try:
                                    result = _parse_structured_response_text(response_model, raw_text)
                                except Exception as parse_exc:
                                    repair_call_kwargs = _structured_json_prompt_kwargs(
                                        call_kwargs=prepared.call_kwargs,
                                        response_model=response_model,
                                        messages=messages,
                                        failure_reason=str(parse_exc),
                                        invalid_response=raw_text,
                                        force_api_mode=(
                                            "chat_completions"
                                            if provider_call.api_mode == "chat_completions"
                                            else None
                                        ),
                                    )
                                    repair_call = resolve_provider_call(
                                        context=context,
                                        call_kwargs=repair_call_kwargs,
                                    )
                                    response, provider_call, did_fallback = (
                                        await _execute_provider_call_with_auto_fallback(
                                            litellm=litellm,
                                            context=context,
                                            provider_call=repair_call,
                                            attempt=prepared.attempt,
                                            model=tracked_model,
                                            route_reason=repair_call.route_reason,
                                        )
                                    )
                                    auto_responses_chat_fallback = auto_responses_chat_fallback or did_fallback
                                    usage = merge_usage(usage, extract_usage(response))
                                    raw_text = _provider_response_text(response, provider_call)
                                    if not raw_text.strip():
                                        raise ValueError("empty_llm_response")
                                    assistant_text = raw_text
                                    result = _parse_structured_response_text(response_model, raw_text)
                                prompt_t, completion_t, total_t = usage
                                extra_outputs = llm_api_mode_outputs(
                                    initial_api_mode=initial_api_mode,
                                    final_api_mode=provider_call.api_mode,
                                    final_route_reason=provider_call.route_reason,
                                    auto_responses_chat_fallback=auto_responses_chat_fallback,
                                )
                                if provider_call.api_mode == "responses":
                                    tool_events = response_output_tool_events(response)
                                    if tool_events:
                                        extra_outputs["llm_provider_tool_events"] = tool_events
                                _end_langsmith_trace(
                                    trace_run,
                                    text=assistant_text.strip() or _serialize_structured_result(result),
                                    result=result,
                                    extra_outputs=extra_outputs,
                                    prompt_tokens=prompt_t,
                                    completion_tokens=completion_t,
                                    total_tokens=total_t,
                                )
                            logger.info(
                                "llm_structured_complete",
                                attempt=prepared.attempt,
                                elapsed_s=round(time.monotonic() - prepared.started_at, 2),
                                response_model=response_model.__name__,
                                model=tracked_model,
                                task_type=context.task_type,
                                endpoint_role=context.endpoint_role,
                                mode=mode_label,
                                initial_api_mode=initial_api_mode,
                                final_api_mode=provider_call.api_mode,
                                initial_route_reason=route_reason,
                                final_route_reason=provider_call.route_reason,
                                auto_responses_chat_fallback=auto_responses_chat_fallback,
                            )
                            track_call(
                                task_type=context.task_type,
                                model=tracked_model,
                                start=call_started_at,
                                success=True,
                                prompt_tokens=prompt_t,
                                completion_tokens=completion_t,
                                total_tokens=total_t,
                            )
                            return result
                        trace_metadata = {
                            **dict(extra_metadata or {}),
                            **provider_call_metadata(base_provider_call),
                        }
                        if not use_instructor:
                            repair_call_kwargs = _build_structured_repair_call_kwargs(
                                call_kwargs=prepared.call_kwargs,
                                response_model=response_model,
                                messages=messages,
                                use_json_response_format=use_json_response_format,
                            )
                            prepared.call_kwargs.clear()
                            prepared.call_kwargs.update(repair_call_kwargs)
                            trace_messages = prepared.call_kwargs["messages"]
                        with langsmith_trace(
                            name="LLM：结构化生成",
                            run_type="llm",
                            **_langsmith_trace_kwargs(
                                task_type=context.task_type,
                                call_model=prepared.call_model,
                                provider=prepared.provider,
                                model_name=tracked_model,
                                mode="structured_chat_completions",
                                messages=trace_messages,
                                call_kwargs=prepared.call_kwargs,
                                attempt=prepared.attempt,
                                endpoint_role=context.endpoint_role,
                                model_selector=context.model_selector,
                                extra_metadata=trace_metadata,
                            ),
                        ) as trace_run:
                            if use_instructor:
                                assert client is not None
                                try:
                                    result = await asyncio.wait_for(
                                        client.chat.completions.create(
                                            response_model=response_model,
                                            max_retries=0,
                                            **prepared.call_kwargs,
                                        ),
                                        timeout=context_request_timeout_s(context, prepared.call_kwargs),
                                    )
                                    prompt_t, completion_t, total_t = extract_usage(result)
                                except asyncio.TimeoutError:
                                    raise
                                except asyncio.CancelledError:
                                    raise
                                except Exception as instructor_exc:
                                    failure_reason, invalid_response = _structured_failure_feedback(instructor_exc)
                                    logger.warning(
                                        "llm_structured_instructor_parse_failed_trying_repair",
                                        response_model=response_model.__name__,
                                        mode=mode_label,
                                        error=str(instructor_exc)[:200],
                                        **trace_log_fields(),
                                    )
                                    repair_use_json_response_format = use_json_response_format
                                    if _is_response_format_unsupported_error(instructor_exc):
                                        repair_use_json_response_format = False
                                    repair_call_kwargs = _build_structured_repair_call_kwargs(
                                        call_kwargs=prepared.call_kwargs,
                                        response_model=response_model,
                                        messages=messages,
                                        use_json_response_format=repair_use_json_response_format,
                                        failure_reason=failure_reason,
                                        invalid_response=invalid_response,
                                    )
                                    raw_response = await asyncio.wait_for(
                                        litellm.acompletion(**repair_call_kwargs),
                                        timeout=context_request_timeout_s(context, repair_call_kwargs),
                                    )
                                    prompt_t, completion_t, total_t = extract_usage(raw_response)
                                    raw_text = _completion_response_text(raw_response)
                                    if not raw_text.strip():
                                        raise ValueError("empty_llm_response")
                                    assistant_text = raw_text
                                    result = _parse_structured_response_text(response_model, raw_text)
                            else:
                                response = await asyncio.wait_for(
                                    litellm.acompletion(**prepared.call_kwargs),
                                    timeout=context_request_timeout_s(context, prepared.call_kwargs),
                                )
                                prompt_t, completion_t, total_t = extract_usage(response)
                                raw_content = response.choices[0].message.content or ""
                                if not raw_content.strip():
                                    raise ValueError("empty_llm_response")
                                assistant_text = raw_content
                                result = _parse_structured_response_text(response_model, raw_content)
                            _end_langsmith_trace(
                                trace_run,
                                text=assistant_text.strip() or _serialize_structured_result(result),
                                result=result,
                                extra_outputs=llm_api_mode_outputs(
                                    initial_api_mode=base_provider_call.api_mode,
                                    final_api_mode=base_provider_call.api_mode,
                                    final_route_reason=base_provider_call.route_reason,
                                ),
                                prompt_tokens=prompt_t,
                                completion_tokens=completion_t,
                                total_tokens=total_t,
                            )
                        logger.info(
                            "llm_structured_complete",
                            attempt=prepared.attempt,
                            elapsed_s=round(time.monotonic() - prepared.started_at, 2),
                            response_model=response_model.__name__,
                            model=tracked_model,
                            task_type=context.task_type,
                            endpoint_role=context.endpoint_role,
                            mode=mode_label,
                            api_mode=base_provider_call.api_mode,
                            route_reason=base_provider_call.route_reason,
                        )
                        track_call(
                            task_type=context.task_type,
                            model=tracked_model,
                            start=call_started_at,
                            success=True,
                            prompt_tokens=prompt_t,
                            completion_tokens=completion_t,
                            total_tokens=total_t,
                        )
                        return result
                    except asyncio.TimeoutError:
                        last_error = LLMTimeoutError(
                            timeout_s=effective_call_timeout_s(context, prepared.call_kwargs)
                        )
                        log_attempt_timeout(
                            "llm_structured_timeout",
                            attempt=prepared,
                            context=context,
                            extra={
                                "response_model": response_model.__name__,
                                "mode": mode_label,
                            },
                        )
                    except asyncio.CancelledError:
                        last_error = asyncio.CancelledError()
                        log_attempt_cancelled(
                            "llm_structured_cancelled",
                            attempt=prepared,
                            context=context,
                            extra={
                                "response_model": response_model.__name__,
                                "mode": mode_label,
                            },
                        )
                        track_call(
                            task_type=context.task_type,
                            model=tracked_model,
                            start=call_started_at,
                            success=False,
                            error="cancelled",
                        )
                        raise
                    except Exception as exc:
                        last_error = exc
                        log_attempt_failed(
                            "llm_structured_failed",
                            attempt=prepared,
                            context=context,
                            error=exc,
                            extra={
                                "response_model": response_model.__name__,
                                "mode": mode_label,
                            },
                        )

                if should_advance_to_fallback(
                    context_group,
                    has_fallback_endpoints=has_fallback_endpoints,
                    error=last_error,
                ):
                    logger.info(
                        "llm_structured_primary_retries_skipped_for_endpoint_fallback",
                        task_type=primary_context.task_type,
                        model=tracked_model,
                        error_type=last_error.__class__.__name__ if last_error is not None else "",
                    )
                    break
                if retry_round < group_max_retries:
                    await sleep_before_retry(retry_round, error=last_error, lease=lease)

    track_call(
        task_type=primary_context.task_type,
        model=tracked_model,
        start=call_started_at,
        success=False,
        error=str(last_error),
    )
    raise_last_error(last_error)
